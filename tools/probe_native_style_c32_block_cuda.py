"""Measure one complete fused C32 block on recovered DLSS5 data.

This is an offline CUDA backend experiment.  It joins the two already-tested
probes into one serial standard-C32 block:

    input adapter -> C32 MLP -> Q/K/V -> 8x8 attention -> projection/residual

The comparison is against the local eager direct-FP8 control.  It is not the
native NVIDIA DLL, a full 71-block schedule, or a live Skyrim runtime.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import time

import numpy as np
import torch
import triton

from probe_native_style_c32_cuda import _fused_c32_mlp, _reference_block
from probe_native_style_c32_attention_cuda import _fused_call, _project_qkv, _select_row


def _event_time(callback) -> float:
    start = torch.cuda.Event(enable_timing=True)
    end = torch.cuda.Event(enable_timing=True)
    start.record()
    callback()
    end.record()
    end.synchronize()
    return float(start.elapsed_time(end))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--weights", type=Path, required=True)
    parser.add_argument("--mlx-python", type=Path, required=True)
    parser.add_argument("--split", choices=("train", "validation", "test"), default="test")
    parser.add_argument("--sequence-id", default="seq-1789071762719-5")
    parser.add_argument("--frame", type=int, default=13)
    parser.add_argument("--eye", type=int, choices=(0, 1), default=0)
    parser.add_argument(
        "--block-index",
        type=int,
        choices=(0, 70),
        default=0,
        help="Standard C32 block weights to measure; block70 uses a block0-adapter proxy input",
    )
    parser.add_argument("--probe-height", type=int, default=0, help="Optional top-left region height; 0 means full eye")
    parser.add_argument("--probe-width", type=int, default=0, help="Optional top-left region width; 0 means full eye")
    parser.add_argument("--mlp-block-m", type=int, choices=(16, 32, 64, 128), default=16)
    parser.add_argument("--attention-block-m", type=int, choices=(16, 32, 64), default=64)
    parser.add_argument("--chunk-rows", type=int, default=32768)
    parser.add_argument("--warmup", type=int, default=1)
    parser.add_argument("--iterations", type=int, default=2)
    parser.add_argument(
        "--include-graph",
        action="store_true",
        help="Capture and replay the already-fused block as a CUDA Graph",
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is required")
    if args.chunk_rows <= 0 or args.warmup < 0 or args.iterations <= 0:
        raise ValueError("chunk-rows and iterations must be positive; warmup must be nonnegative")

    mlx_python = args.mlx_python.expanduser().resolve()
    if str(mlx_python) not in sys.path:
        sys.path.insert(0, str(mlx_python))
    tools_dir = Path(__file__).resolve().parent
    if str(tools_dir) not in sys.path:
        sys.path.insert(0, str(tools_dir))

    from mlxdlss import NeuralRenderingPipeline
    from mlxdlss import model as recovered_model
    from mlxdlss.pipeline import load_weights
    from profile_whitebox_runtime import read_rgba_raw

    cache = args.cache.expanduser().resolve()
    rows = json.loads((cache / "rows.json").read_text(encoding="utf-8"))
    row = _select_row(rows, args.split, args.sequence_id, args.frame, args.eye)
    source_width, source_height = int(row["color_size"][0]), int(row["color_size"][1])
    raw_paths = row.get("raw_paths") or row.get("paths")
    if not isinstance(raw_paths, dict) or "input" not in raw_paths:
        raise ValueError("selected row has neither raw_paths.input nor paths.input")
    source = read_rgba_raw(Path(raw_paths["input"]), source_width, source_height)

    weights = load_weights(args.weights.expanduser().resolve())
    preparation_pipeline = NeuralRenderingPipeline(weights, device="cpu", precision="reference")
    prepared = preparation_pipeline.prepare(
        source,
        profile="standard",
        processing_scale=1.0,
        frame_index=0,
        local_tone_strength=1.0,
        local_structure_strength=1.0,
    )
    full_features = torch.from_numpy(np.ascontiguousarray(prepared.features)).to("cuda", torch.float16)
    height = args.probe_height or int(full_features.shape[0])
    width = args.probe_width or int(full_features.shape[1])
    if height <= 0 or width <= 0 or height % 8 or width % 8:
        raise ValueError("probe dimensions must be positive multiples of eight")
    if height > full_features.shape[0] or width > full_features.shape[1]:
        raise ValueError("probe dimensions exceed the feature tensor")
    features = full_features[:height, :width].contiguous()
    feature_rows = height * width
    feature_matrix = features.reshape(feature_rows, 16)

    adapter = weights["block0.layer0.input_adapter_weight"].to("cuda", torch.float16).contiguous()
    value = (feature_matrix @ adapter).contiguous()
    block_prefix = f"block{args.block_index}.layer0"
    w1 = weights[f"{block_prefix}.weight1"].to("cuda", torch.float16).contiguous()
    w2 = weights[f"{block_prefix}.weight2"].to("cuda", torch.float16).contiguous()
    ffn_cosine = weights[f"{block_prefix}.ffn_cos_skip"].to("cuda", torch.float16).contiguous()
    qkv_weight = weights[f"{block_prefix}.qkv_weight"].to("cuda", torch.float16).contiguous()
    attention_scale = weights[f"{block_prefix}.attn_scale"].to("cuda", torch.float32).contiguous()
    logical_bias = recovered_model.recover_attention_bias_layout(
        weights[f"{block_prefix}.attn_bias"]
    ).to("cuda", torch.float16).contiguous()
    projection = weights[f"{block_prefix}.projection_weight"].to("cuda", torch.float16).contiguous()
    attention_cosine = weights[f"{block_prefix}.attn_cos_skip"].to("cuda", torch.float16).contiguous()

    fused_ffn = torch.empty_like(value)
    q = torch.empty_like(value)
    k = torch.empty_like(value)
    v = torch.empty_like(value)
    fused_output = torch.empty_like(value)

    def launch_mlp() -> None:
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

    def launch_attention() -> None:
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
            fused_output,
            height,
            width,
            args.attention_block_m,
        )

    def launch_block() -> None:
        launch_mlp()
        launch_attention()

    compile_started = time.perf_counter()
    launch_block()
    torch.cuda.synchronize()
    compile_seconds = time.perf_counter() - compile_started

    for _ in range(args.warmup):
        launch_block()
    torch.cuda.synchronize()
    graph_times = []
    if args.include_graph:
        graph = torch.cuda.CUDAGraph()
        with torch.cuda.graph(graph):
            launch_block()
        torch.cuda.synchronize()
        graph_times = [_event_time(graph.replay) for _ in range(args.iterations)]
    fused_block_times = [_event_time(launch_block) for _ in range(args.iterations)]
    fused_mlp_times = [_event_time(launch_mlp) for _ in range(args.iterations)]
    fused_attention_times = [_event_time(launch_attention) for _ in range(args.iterations)]

    original_round_trip = recovered_model.e4m3_round_trip

    def direct_fp8(value_tensor):
        return value_tensor.clamp(-448.0, 448.0).to(torch.float8_e4m3fn).to(value_tensor.dtype)

    def eager_block():
        eager_ffn = _reference_block(value, w1, w2, ffn_cosine, args.chunk_rows).contiguous()
        eager_image = eager_ffn.reshape(1, height, width, 32)
        branch = recovered_model.window_attention(
            eager_image,
            qkv_weight=qkv_weight,
            attention_scale=attention_scale,
            attention_bias=logical_bias,
            projection_weight=projection,
            head_count=1,
            window_size=8,
            window_origin=(0, 0),
        )
        return branch.reshape(feature_rows, 32) + eager_ffn * attention_cosine

    recovered_model.e4m3_round_trip = direct_fp8
    try:
        for _ in range(args.warmup):
            eager_block()
        torch.cuda.synchronize()
        eager_block_times = [_event_time(eager_block) for _ in range(args.iterations)]
        eager_output = eager_block().contiguous()
        torch.cuda.synchronize()
    finally:
        recovered_model.e4m3_round_trip = original_round_trip

    difference = (fused_output.float() - eager_output.float()).abs()
    percentile_sample = difference.reshape(-1)[::max(1, difference.numel() // 1_000_000)]
    args.output.expanduser().resolve().mkdir(parents=True, exist_ok=True)
    result = {
        "schema": "opennr-native-style-c32-block-cuda-probe-v1",
        "scope": f"one complete standard C32 block{args.block_index} MLP plus QKV/window-attention/projection/residual path; offline only",
        "promotion": False,
        "training_started": False,
        "new_capture_started": False,
        "row": {
            "split": row["split"],
            "sequence_id": row["sequence_id"],
            "frame": row["frame_id"],
            "eye": row["eye"],
            "source": raw_paths["input"],
        },
        "input": {
            "source_resolution": [source_width, source_height],
            "probe_resolution": [width, height],
            "probe_region": "top_left" if (height != source_height or width != source_width) else "full_eye",
            "tokens": int(feature_rows),
            "window_count": int((height // 8) * (width // 8)),
            "value_source": (
                "block0 adapter output"
                if args.block_index == 0
                else "block0 adapter output used as arithmetic-only proxy for block70"
            ),
        },
        "kernel": {
            "block": block_prefix,
            "operation": "C32 MLP + QKV projection + C32 cosine normalization + 8x8 attention + E4M3 value publication + projection + residual",
            "mlp_block_m": args.mlp_block_m,
            "attention_block_m": args.attention_block_m,
            "warps": 4,
            "stages": 2,
            "triton": triton.__version__,
        },
        "timing_ms": {
            "compile_and_first_run": compile_seconds * 1000.0,
            "fused_block_median": float(np.median(fused_block_times)),
            "fused_block_p95": float(np.percentile(fused_block_times, 95.0)),
            "fused_block_samples": fused_block_times,
            "cuda_graph_replay_median": (
                float(np.median(graph_times)) if graph_times else None
            ),
            "cuda_graph_replay_p95": (
                float(np.percentile(graph_times, 95.0)) if graph_times else None
            ),
            "cuda_graph_replay_samples": graph_times,
            "fused_mlp_median": float(np.median(fused_mlp_times)),
            "fused_attention_median": float(np.median(fused_attention_times)),
            "eager_block_median": float(np.median(eager_block_times)),
            "eager_block_p95": float(np.percentile(eager_block_times, 95.0)),
            "eager_block_samples": eager_block_times,
        },
        "speedup": float(np.median(eager_block_times) / np.median(fused_block_times)),
        "drift_vs_eager_direct_fp8": {
            "mae": float(difference.mean().item()),
            "p99_sample": float(torch.quantile(percentile_sample, 0.99).item()),
            "p999_sample": float(torch.quantile(percentile_sample, 0.999).item()),
            "max": float(difference.max().item()),
            "changed_fraction_gt_1e-3": float((difference > 1e-3).float().mean().item()),
        },
        "memory": {
            "peak_allocated_bytes": int(torch.cuda.max_memory_allocated()),
            "peak_reserved_bytes": int(torch.cuda.max_memory_reserved()),
        },
        "environment": {
            "gpu": torch.cuda.get_device_name(0),
            "torch": torch.__version__,
            "cuda": torch.version.cuda,
            "python": sys.version,
            "include_graph": args.include_graph,
        },
        "interpretation": (
            "One standard-C32 block backend proof only; not the NVIDIA DLL, full 71-block timing, "
            "exact native parity, temporal/stereo validation, or VR readiness."
            if args.block_index == 0
            else "Block70 arithmetic timing uses a block0-adapter proxy input; it is not a block70 feature-contract, native-DLL, full-model, temporal/stereo, or VR result."
        ),
    }
    (args.output.expanduser().resolve() / "result.json").write_text(
        json.dumps(result, indent=2), encoding="utf-8"
    )
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
