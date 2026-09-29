"""Compare row-major and direct-window-packed C128 attention on real data.

This is an offline CUDA backend experiment. It transfers the physical-layout
idea used by the public NR-B580 research snapshot to the recovered pooled C128
block: Q/K/V are projected and written directly in 8x8-window order, then the
attention kernel consumes that order without rebuilding window addresses.
It does not call the NVIDIA DLL and does not modify Skyrim, MGO, or any
packaged runtime.

The comparison is against the existing row-major Triton C128 probe and the
local eager direct-FP8 control. It is not native NVIDIA parity.
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
import triton.language as tl

from probe_native_style_c32_cuda import _round_fp8_half
from probe_native_style_c32_attention_cuda import _normalize_c32, _select_row
from probe_native_style_c64_block_cuda import _approx_exp, _half_add, _half_mul, _event_time
from probe_native_style_c128_block_cuda import (
    _fused_c128_branched_mlp,
    _project_c128_qkv,
    _attention_c128_windows,
)


@triton.jit
def _half_mul_packed(left, right):
    return (left.to(tl.float32) * right.to(tl.float32)).to(tl.float16)


@triton.jit
def _half_add_packed(left, right):
    return (left.to(tl.float32) + right.to(tl.float32)).to(tl.float16)


@triton.jit
def _project_c128_qkv_window_packed(
    X,
    WEIGHT,
    SCALE,
    Q,
    K,
    V,
    WIDTH: tl.constexpr,
    COLUMNS: tl.constexpr,
    BM: tl.constexpr,
):
    """Project row-major C128 input directly into [window, 64, 128] tensors."""

    program = tl.program_id(0)
    window = program // (64 // BM)
    tile = program % (64 // BM)
    local_row = tile * BM + tl.arange(0, BM)
    input_lane = tl.arange(0, 128)
    lane = tl.arange(0, 32)
    row_mask = local_row < 64

    window_row = window // COLUMNS
    window_col = window % COLUMNS
    row_y = window_row * 8 + local_row // 8
    row_x = window_col * 8 + local_row % 8
    row_index = row_y * WIDTH + row_x
    x = tl.load(
        X + row_index[:, None] * 128 + input_lane[None, :],
        mask=row_mask[:, None],
        other=0,
    )
    base = window * 8192
    for head in tl.static_range(4):
        output_offset = head * 32
        q_weight = tl.load(
            WEIGHT + input_lane[:, None] * 384 + output_offset + lane[None, :]
        )
        k_weight = tl.load(
            WEIGHT + input_lane[:, None] * 384 + 128 + output_offset + lane[None, :]
        )
        v_weight = tl.load(
            WEIGHT + input_lane[:, None] * 384 + 256 + output_offset + lane[None, :]
        )
        q = _normalize_c32(
            tl.dot(x, q_weight, out_dtype=tl.float32).to(tl.float16),
            BM,
            0.00006198883056640625,
        )
        k = _normalize_c32(
            tl.dot(x, k_weight, out_dtype=tl.float32).to(tl.float16),
            BM,
            0.00006198883056640625,
        )
        v = tl.dot(x, v_weight, out_dtype=tl.float32).to(tl.float16)
        scale = tl.load(SCALE + head)
        q = _half_mul_packed(q, scale)
        dest = base + local_row[:, None] * 128 + output_offset + lane[None, :]
        tl.store(Q + dest, _round_fp8_half(q), mask=row_mask[:, None])
        tl.store(K + dest, _round_fp8_half(k), mask=row_mask[:, None])
        tl.store(V + dest, _round_fp8_half(v), mask=row_mask[:, None])


@triton.jit
def _attention_c128_windows_packed(
    Q,
    K,
    V,
    X,
    BIAS,
    PROJECTION,
    COSINE,
    OUT,
    WIDTH: tl.constexpr,
    COLUMNS: tl.constexpr,
    BM: tl.constexpr,
):
    """Consume direct-window-packed C128 Q/K/V and write row-major output."""

    program = tl.program_id(0)
    window = program // (64 // BM)
    tile = program % (64 // BM)
    local_row = tile * BM + tl.arange(0, BM)
    local_key = tl.arange(0, 64)
    lane = tl.arange(0, 32)
    output_lane = tl.arange(0, 128)
    row_mask = local_row < 64

    window_row = window // COLUMNS
    window_col = window % COLUMNS
    row_y = window_row * 8 + local_row // 8
    row_x = window_col * 8 + local_row % 8
    row_index = row_y * WIDTH + row_x
    base = window * 8192

    x = tl.load(
        X + row_index[:, None] * 128 + output_lane[None, :],
        mask=row_mask[:, None],
        other=0,
    )
    branch = tl.zeros((BM, 128), dtype=tl.float32)
    for head in tl.static_range(4):
        head_offset = head * 32
        q = tl.load(
            Q + base + local_row[:, None] * 128 + head_offset + lane[None, :],
            mask=row_mask[:, None],
            other=0,
        )
        k = tl.load(
            K + base + local_key[None, :] * 128 + head_offset + lane[:, None]
        )
        v = tl.load(
            V + base + local_key[:, None] * 128 + head_offset + lane[None, :]
        )
        bias = tl.load(
            BIAS
            + head * 4096
            + local_row[:, None] * 64
            + local_key[None, :],
            mask=row_mask[:, None],
            other=0,
        )
        scores = _half_add_packed(
            tl.dot(q, k, out_dtype=tl.float32).to(tl.float16), bias
        )
        weights = _approx_exp(scores, BM)
        denominator = tl.sum(weights.to(tl.float32), axis=1).to(tl.float16)
        probability = _round_fp8_half(
            _half_mul_packed(
                weights,
                (1.0 / denominator.to(tl.float32)).to(tl.float16)[:, None],
            )
        )
        attended = _round_fp8_half(
            tl.dot(probability, v, out_dtype=tl.float32).to(tl.float16)
        )
        projection = tl.load(
            PROJECTION
            + (head_offset + lane)[:, None] * 128
            + output_lane[None, :]
        )
        branch += tl.dot(attended, projection, out_dtype=tl.float32)

    cosine = tl.load(COSINE + output_lane)
    result = _half_add_packed(
        branch.to(tl.float16), _half_mul_packed(x, cosine[None, :])
    )
    tl.store(
        OUT + row_index[:, None] * 128 + output_lane[None, :],
        result,
        mask=row_mask[:, None],
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--weights", type=Path, required=True)
    parser.add_argument("--mlx-python", type=Path, required=True)
    parser.add_argument("--split", choices=("train", "validation", "test"), default="test")
    parser.add_argument("--sequence-id", default="seq-1789071762719-5")
    parser.add_argument("--frame", type=int, default=13)
    parser.add_argument("--eye", type=int, choices=(0, 1), default=0)
    parser.add_argument("--attention-block-m", type=int, choices=(8, 16, 32, 64), default=32)
    parser.add_argument("--warmup", type=int, default=1)
    parser.add_argument("--iterations", type=int, default=3)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is required")
    if args.warmup < 0 or args.iterations <= 0:
        raise ValueError("warmup must be nonnegative and iterations must be positive")

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
    source = read_rgba_raw(Path(row["raw_paths"]["input"]), source_width, source_height)
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
    prefix_model = recovered_model.NeuralRenderingModel(weights).eval().to(torch.float16).to("cuda")
    input_tensor = torch.from_numpy(np.ascontiguousarray(prepared.features)).to("cuda", torch.float16).unsqueeze(0)
    with torch.inference_mode():
        value = input_tensor @ prefix_model.weight("block0.layer0.input_adapter_weight")
        block0 = prefix_model._window(value, 0, head_count=1)
        value = recovered_model.e4m3_round_trip(recovered_model.average_pool2(block0))
        del block0
        for index in range(1, 4):
            value = prefix_model._window(value, index, head_count=1)
        value = prefix_model._downsample_window(value, 4, head_count=1)
        for index in range(5, 8):
            value = prefix_model._window(value, index, head_count=2)
        c128_full = prefix_model._downsample_window(value, 8, head_count=2)[0].contiguous()
    del input_tensor, value, prefix_model
    torch.cuda.synchronize()

    height, width = int(c128_full.shape[0]), int(c128_full.shape[1])
    if height <= 0 or width <= 0 or height % 8 or width % 8:
        raise ValueError("C128 dimensions must be positive multiples of eight")
    features = c128_full.contiguous()
    del c128_full
    rows_total = height * width
    value = features.reshape(rows_total, 128)

    prefix = "block9.layer0"
    expand = weights[f"{prefix}.ffn_expand_weight"].to("cuda", torch.float16).contiguous()
    branch = weights[f"{prefix}.ffn_branch_projection_weight"].to("cuda", torch.float16).contiguous()
    output_projection = weights[f"{prefix}.ffn_output_projection_weight"].to("cuda", torch.float16).contiguous()
    ffn_cosine = weights[f"{prefix}.ffn_cos_skip"].to("cuda", torch.float16).contiguous()
    qkv_weight = weights[f"{prefix}.qkv_weight"].to("cuda", torch.float16).contiguous()
    attention_scale = weights[f"{prefix}.attn_scale"].to("cuda", torch.float32).contiguous()
    attention_bias = weights[f"{prefix}.attn_bias"].to("cuda", torch.float16).contiguous()
    attention_projection = weights[f"{prefix}.projection_weight"].to("cuda", torch.float16).contiguous()
    attention_cosine = weights[f"{prefix}.attn_cos_skip"].to("cuda", torch.float16).contiguous()

    fused_ffn = torch.empty_like(value)
    q = torch.empty_like(value)
    k = torch.empty_like(value)
    v = torch.empty_like(value)
    row_output = torch.empty_like(value)
    windows = (height // 8) * (width // 8)
    packed_q = torch.empty((windows, 64, 128), device="cuda", dtype=torch.float16)
    packed_k = torch.empty_like(packed_q)
    packed_v = torch.empty_like(packed_q)
    packed_output = torch.empty_like(value)

    def launch_mlp() -> None:
        _fused_c128_branched_mlp[(triton.cdiv(rows_total, 16),)](
            value,
            expand,
            branch,
            output_projection,
            ffn_cosine,
            fused_ffn,
            rows_total,
            16,
            num_warps=4,
            num_stages=2,
            enable_fp_fusion=False,
        )

    def launch_row_attention() -> None:
        _project_c128_qkv[(triton.cdiv(rows_total, 16),)](
            fused_ffn,
            qkv_weight,
            attention_scale,
            q,
            k,
            v,
            rows_total,
            16,
            num_warps=4,
            num_stages=2,
            enable_fp_fusion=False,
        )
        _attention_c128_windows[(windows * (64 // args.attention_block_m),)](
            q,
            k,
            v,
            fused_ffn,
            attention_bias,
            attention_projection,
            attention_cosine,
            row_output,
            width,
            width // 8,
            args.attention_block_m,
            64 // args.attention_block_m,
            num_warps=4,
            num_stages=2,
            enable_fp_fusion=False,
        )

    def launch_packed_attention() -> None:
        _project_c128_qkv_window_packed[(windows * (64 // args.attention_block_m),)](
            fused_ffn,
            qkv_weight,
            attention_scale,
            packed_q,
            packed_k,
            packed_v,
            width,
            width // 8,
            args.attention_block_m,
            num_warps=4,
            num_stages=2,
            enable_fp_fusion=False,
        )
        _attention_c128_windows_packed[(windows * (64 // args.attention_block_m),)](
            packed_q,
            packed_k,
            packed_v,
            fused_ffn,
            attention_bias,
            attention_projection,
            attention_cosine,
            packed_output,
            width,
            width // 8,
            args.attention_block_m,
            num_warps=4,
            num_stages=2,
            enable_fp_fusion=False,
        )

    def launch_row_block() -> None:
        launch_mlp()
        launch_row_attention()

    def launch_packed_block() -> None:
        launch_mlp()
        launch_packed_attention()

    compile_started = time.perf_counter()
    launch_row_block()
    launch_packed_block()
    torch.cuda.synchronize()
    compile_seconds = time.perf_counter() - compile_started

    for _ in range(args.warmup):
        launch_row_block()
        launch_packed_block()
    torch.cuda.synchronize()

    row_times = [_event_time(launch_row_attention) for _ in range(args.iterations)]
    packed_times = [_event_time(launch_packed_attention) for _ in range(args.iterations)]
    row_block_times = [_event_time(launch_row_block) for _ in range(args.iterations)]
    packed_block_times = [_event_time(launch_packed_block) for _ in range(args.iterations)]

    original_round_trip = recovered_model.e4m3_round_trip

    def direct_fp8(value_tensor):
        return value_tensor.clamp(-448.0, 448.0).to(torch.float8_e4m3fn).to(value_tensor.dtype)

    recovered_model.e4m3_round_trip = direct_fp8
    try:
        def eager_block():
            eager_ffn = recovered_model.branched_feed_forward(
                value,
                expansion_weight=expand,
                branch_projection_weight=branch,
                output_projection_weight=output_projection,
            )
            eager_ffn = recovered_model.e4m3_round_trip(
                recovered_model.cosine_residual(value, eager_ffn, ffn_cosine)
            )
            eager_image = eager_ffn.reshape(1, height, width, 128)
            attended = recovered_model.window_attention(
                eager_image,
                qkv_weight=qkv_weight,
                attention_scale=attention_scale,
                attention_bias=attention_bias.unsqueeze(0),
                projection_weight=attention_projection,
                head_count=4,
                window_size=8,
                window_origin=(0, 0),
            )
            return recovered_model.cosine_residual(
                eager_ffn,
                attended.reshape(rows_total, 128),
                attention_cosine,
            )

        for _ in range(args.warmup):
            eager_block()
        torch.cuda.synchronize()
        eager_times = [_event_time(eager_block) for _ in range(args.iterations)]
        eager_output = eager_block().contiguous()
        torch.cuda.synchronize()
    finally:
        recovered_model.e4m3_round_trip = original_round_trip

    launch_packed_block()
    torch.cuda.synchronize()
    difference = (packed_output.float() - eager_output.float()).abs()
    row_packed_difference = (row_output.float() - packed_output.float()).abs()
    percentile_sample = difference.reshape(-1)[::max(1, difference.numel() // 1_000_000)]

    output = args.output.expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    result = {
        "schema": "opennr-native-style-c128-packed-cuda-probe-v1",
        "scope": "one block9 C128 direct-window-packed QKV/attention path; offline only",
        "promotion": False,
        "training_started": False,
        "new_capture_started": False,
        "row": {
            "split": row["split"],
            "sequence_id": row["sequence_id"],
            "frame": row["frame_id"],
            "eye": row["eye"],
            "source": row["raw_paths"]["input"],
        },
        "input": {
            "source_resolution": [source_width, source_height],
            "feature_resolution": [width, height],
            "tokens": rows_total,
            "windows": windows,
            "packed_shape": [windows, 64, 128],
            "channels": 128,
            "heads": 4,
        },
        "kernel": {
            "operation": "row-major baseline versus direct-window-packed C128 QKV + 8x8 attention + projection/residual",
            "attention_block_m": args.attention_block_m,
            "qkv_block_m": args.attention_block_m,
            "warps": 4,
            "stages": 2,
            "triton": triton.__version__,
        },
        "timing_ms": {
            "row_major_attention_median": float(np.median(row_times)),
            "row_major_attention_p95": float(np.percentile(row_times, 95.0)),
            "packed_attention_median": float(np.median(packed_times)),
            "packed_attention_p95": float(np.percentile(packed_times, 95.0)),
            "row_major_complete_block_median": float(np.median(row_block_times)),
            "packed_complete_block_median": float(np.median(packed_block_times)),
            "packed_complete_block_p95": float(np.percentile(packed_block_times, 95.0)),
            "eager_block_median": float(np.median(eager_times)),
            "compile_seconds": compile_seconds,
            "row_major_attention_samples": row_times,
            "packed_attention_samples": packed_times,
            "row_major_complete_block_samples": row_block_times,
            "packed_complete_block_samples": packed_block_times,
            "eager_block_samples": eager_times,
        },
        "speed": {
            "attention_layout_speedup": float(np.median(row_times) / np.median(packed_times)),
            "complete_block_speedup": float(np.median(row_block_times) / np.median(packed_block_times)),
            "eager_to_packed_complete_block_speedup": float(np.median(eager_times) / np.median(packed_block_times)),
        },
        "parity": {
            "packed_vs_eager_mae": float(difference.mean().item()),
            "packed_vs_eager_p99_sample": float(torch.quantile(percentile_sample, 0.99).item()),
            "packed_vs_eager_max": float(difference.max().item()),
            "packed_vs_eager_changed_fraction_gt_1e-3": float((difference > 1e-3).float().mean().item()),
            "row_vs_packed_mae": float(row_packed_difference.mean().item()),
            "row_vs_packed_max": float(row_packed_difference.max().item()),
        },
        "memory": {
            "peak_allocated_bytes": int(torch.cuda.max_memory_allocated()),
            "peak_reserved_bytes": int(torch.cuda.max_memory_reserved()),
        },
        "environment": {
            "gpu": torch.cuda.get_device_name(0),
            "torch": torch.__version__,
            "cuda": torch.version.cuda,
        },
        "contract_warning": "The packed and row-major paths are independent CUDA probes compared with the local eager direct-FP8 control; this is not native NVIDIA parity or live VR evidence.",
    }
    (output / "result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
