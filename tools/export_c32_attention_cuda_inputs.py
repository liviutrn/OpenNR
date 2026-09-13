"""Export one real recovered C32 attention block for the C++/CUDA probe.

The exporter intentionally stops at the existing fused-Triton C32 MLP output.
It saves that real full-eye tensor, the recovered QKV/attention/projection
records, the window-packed Q/K/V tensors, and the existing fused-Triton
attention output as a frozen comparison boundary.  It does not collect data,
modify Skyrim, or call the native NVIDIA runtime.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

import numpy as np
import torch
import triton


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def select_row(rows: list[dict], split: str, sequence_id: str, frame: int, eye: int) -> dict:
    selected = [
        row
        for row in rows
        if row.get("split") == split
        and str(row.get("sequence_id")) == sequence_id
        and int(row.get("frame_id", -1)) == frame
        and int(row.get("eye", -1)) == eye
    ]
    if len(selected) != 1:
        raise ValueError(f"expected one row, found {len(selected)}")
    return selected[0]


def save_tensor(tensor: torch.Tensor, path: Path, *, dtype: torch.dtype) -> dict:
    value = tensor.detach().to(dtype).contiguous().cpu().numpy()
    value.tofile(path)
    return {
        "path": str(path),
        "shape": list(value.shape),
        "dtype": str(value.dtype),
        "bytes": int(path.stat().st_size),
        "sha256": sha256(path),
    }


def pack_attention_windows(tensor: torch.Tensor, height: int, width: int) -> torch.Tensor:
    """Convert HWC32 Q/K/V into the [window, 64, 32] Triton attention layout."""
    if tensor.shape != (height * width, 32):
        raise ValueError(f"expected [{height * width}, 32], got {tuple(tensor.shape)}")
    return tensor.reshape(height // 8, 8, width // 8, 8, 32).permute(
        0, 2, 1, 3, 4
    ).reshape(-1, 64, 32).contiguous()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--weights", type=Path, required=True)
    parser.add_argument("--mlx-python", type=Path, required=True)
    parser.add_argument("--split", choices=("train", "validation", "test"), default="test")
    parser.add_argument("--sequence-id", required=True)
    parser.add_argument("--frame", type=int, required=True)
    parser.add_argument("--eye", type=int, choices=(0, 1), default=0)
    parser.add_argument("--probe-height", type=int, default=0)
    parser.add_argument("--probe-width", type=int, default=0)
    parser.add_argument("--mlp-block-m", type=int, choices=(16, 32, 64, 128), default=16)
    parser.add_argument("--attention-block-m", type=int, choices=(16, 32, 64), default=64)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is required")

    mlx_python = args.mlx_python.expanduser().resolve()
    if str(mlx_python) not in sys.path:
        sys.path.insert(0, str(mlx_python))
    tools_dir = Path(__file__).resolve().parent
    if str(tools_dir) not in sys.path:
        sys.path.insert(0, str(tools_dir))

    from mlxdlss import NeuralRenderingPipeline
    from mlxdlss import model as recovered_model
    from mlxdlss.pipeline import load_weights
    from probe_native_style_c32_attention_cuda import _fused_call, _project_qkv
    from probe_native_style_c32_cuda import _fused_c32_mlp
    from profile_whitebox_runtime import read_rgba_raw

    cache = args.cache.expanduser().resolve()
    rows = json.loads((cache / "rows.json").read_text(encoding="utf-8"))
    row = select_row(rows, args.split, args.sequence_id, args.frame, args.eye)
    paths = row.get("raw_paths") or row.get("paths")
    if not isinstance(paths, dict) or "input" not in paths:
        raise ValueError("selected row has neither raw_paths.input nor paths.input")

    source_width, source_height = int(row["color_size"][0]), int(row["color_size"][1])
    source = read_rgba_raw(Path(paths["input"]), source_width, source_height)
    weights = load_weights(args.weights.expanduser().resolve())
    pipeline = NeuralRenderingPipeline(weights, device="cpu", precision="reference")
    prepared = pipeline.prepare(
        source,
        profile="standard",
        processing_scale=1.0,
        frame_index=0,
        local_tone_strength=1.0,
        local_structure_strength=1.0,
    )

    full_features = torch.from_numpy(np.ascontiguousarray(prepared.features)).to(
        "cuda", torch.float16
    )
    height = args.probe_height or int(full_features.shape[0])
    width = args.probe_width or int(full_features.shape[1])
    if height <= 0 or width <= 0 or height % 8 or width % 8:
        raise ValueError("probe dimensions must be positive multiples of eight")
    if height > full_features.shape[0] or width > full_features.shape[1]:
        raise ValueError("probe dimensions exceed the feature tensor")
    features = full_features[:height, :width].contiguous()
    feature_rows = height * width
    value = (features.reshape(feature_rows, 16) @ weights["block0.layer0.input_adapter_weight"].to(
        "cuda", torch.float16
    ).contiguous()).contiguous()

    w1 = weights["block0.layer0.weight1"].to("cuda", torch.float16).contiguous()
    w2 = weights["block0.layer0.weight2"].to("cuda", torch.float16).contiguous()
    ffn_cosine = weights["block0.layer0.ffn_cos_skip"].to("cuda", torch.float16).contiguous()
    fused_ffn = torch.empty_like(value)
    _fused_c32_mlp[(triton.cdiv(feature_rows, args.mlp_block_m),)](
        value,
        w1,
        w2,
        ffn_cosine,
        fused_ffn,
        feature_rows,
        args.mlp_block_m,
        num_warps=4,
        num_stages=2,
        enable_fp_fusion=False,
    )

    block_prefix = "block0.layer0"
    qkv_weight = weights[f"{block_prefix}.qkv_weight"].to("cuda", torch.float16).contiguous()
    attention_scale = weights[f"{block_prefix}.attn_scale"].to("cuda", torch.float32).contiguous()
    logical_bias = recovered_model.recover_attention_bias_layout(
        weights[f"{block_prefix}.attn_bias"]
    ).to("cuda", torch.float16).contiguous()
    projection = weights[f"{block_prefix}.projection_weight"].to("cuda", torch.float16).contiguous()
    attention_cosine = weights[f"{block_prefix}.attn_cos_skip"].to("cuda", torch.float16).contiguous()
    q = torch.empty_like(fused_ffn)
    k = torch.empty_like(fused_ffn)
    v = torch.empty_like(fused_ffn)
    reference = torch.empty_like(fused_ffn)

    _project_qkv[(triton.cdiv(feature_rows, 32),)](
        fused_ffn,
        qkv_weight,
        attention_scale,
        q,
        k,
        v,
        feature_rows,
        32,
        num_warps=4,
        num_stages=2,
        enable_fp_fusion=False,
    )
    _fused_call(
        q,
        k,
        v,
        fused_ffn,
        logical_bias[0],
        projection,
        attention_cosine,
        reference,
        height,
        width,
        args.attention_block_m,
    )
    torch.cuda.synchronize()
    q_packed = pack_attention_windows(q, height, width)
    k_packed = pack_attention_windows(k, height, width)
    v_packed = pack_attention_windows(v, height, width)
    k_transpose_packed = k_packed.transpose(1, 2).contiguous()

    output = args.output.expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    manifest = {
        "schema": "opennr-c32-attention-cuda-inputs-v1",
        "promotion": False,
        "training_started": False,
        "new_capture_started": False,
        "source": {
            "split": row["split"],
            "sequence_id": row["sequence_id"],
            "frame": row["frame_id"],
            "eye": row["eye"],
            "input": str(Path(paths["input"]).resolve()),
            "source_resolution": [source_width, source_height],
        },
        "probe": {
            "feature_resolution": [width, height],
            "tokens": feature_rows,
            "window_count": (height // 8) * (width // 8),
            "mlp_block_m": args.mlp_block_m,
            "attention_block_m": args.attention_block_m,
        },
        "weights_path": str(args.weights.expanduser().resolve()),
        "files": {
            "ffn": save_tensor(fused_ffn, output / "ffn.bin", dtype=torch.float16),
            "qkv_weight": save_tensor(qkv_weight, output / "qkv_weight.bin", dtype=torch.float16),
            "attention_scale": save_tensor(attention_scale, output / "attention_scale.bin", dtype=torch.float32),
            "bias": save_tensor(logical_bias[0], output / "bias.bin", dtype=torch.float16),
            "projection": save_tensor(projection, output / "projection.bin", dtype=torch.float16),
            "cosine": save_tensor(attention_cosine, output / "cosine.bin", dtype=torch.float16),
            "q_packed": save_tensor(q_packed, output / "q_packed.bin", dtype=torch.float16),
            "k_packed": save_tensor(k_packed, output / "k_packed.bin", dtype=torch.float16),
            "k_transpose_packed": save_tensor(
                k_transpose_packed, output / "k_transpose_packed.bin", dtype=torch.float16
            ),
            "v_packed": save_tensor(v_packed, output / "v_packed.bin", dtype=torch.float16),
            "reference": save_tensor(reference, output / "reference.bin", dtype=torch.float16),
        },
        "comparison_reference": "existing fused Triton QKV plus attention kernel; not native NVIDIA output",
        "environment": {
            "gpu": torch.cuda.get_device_name(0),
            "torch": torch.__version__,
            "cuda": torch.version.cuda,
            "triton": triton.__version__,
        },
    }
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
