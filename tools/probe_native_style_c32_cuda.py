"""Probe a native-style fused C32 MLP on the recovered DLSS5 graph.

This is an offline backend experiment.  It uses the real logical weights and a
real Skyrim feature tensor, but it does not call the native NVIDIA DLL and it
does not modify any game/runtime files.  The kernel covers one repeated
block-local region only:

    C32 -> C128 -> quadratic gate -> E4M3 -> C32 -> cosine residual

The full 71-block graph, attention, temporal state, stereo contract, and live
VR acceptance remain out of scope for this probe.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import time

import numpy as np
import torch
import triton
import triton.language as tl


@triton.jit
def _round_fp8_half(x):
    """Saturating E4M3 finite conversion, returned as decoded FP16."""

    bits = x.to(tl.uint16, bitcast=True).to(tl.int32)
    sign = bits & 0x8000
    raw = bits & 0x7FFF
    magnitude = tl.minimum(raw, 0x5F00)  # 448, max E4M3FN finite value.
    exponent = magnitude >> 10
    significand = (magnitude & 1023) + tl.where(exponent != 0, 1024, 0)
    shift = tl.maximum(16 - tl.maximum(exponent, 1), 1)
    quotient = significand >> shift
    remainder = significand - (quotient << shift)
    midpoint = 1 << (shift - 1)
    rounded = quotient + (
        (remainder > midpoint)
        | ((remainder == midpoint) & ((quotient & 1) != 0))
    ).to(tl.int32)
    subnormal = (rounded.to(tl.float32) * 0.001953125).to(tl.float16)
    subnormal_bits = subnormal.to(tl.uint16, bitcast=True).to(tl.int32)
    normal = (magnitude + 63 + ((magnitude >> 7) & 1)) & 0x7F80
    result = tl.where(magnitude < 0x2400, subnormal_bits, normal) | sign
    result = tl.where(raw > 0x7C00, 0x7F80 | sign, result)
    return result.to(tl.uint16).to(tl.float16, bitcast=True)


@triton.jit
def _quadratic_gate_activation(x):
    # This follows the recovered graph's half-visible intermediate boundaries.
    clamped = tl.minimum(tl.maximum(x.to(tl.float32), -4.0), 4.0).to(tl.float16)
    linear = (
        tl.abs(clamped).to(tl.float32) * -0.055908203125 + 0.447265625
    ).to(tl.float16)
    gate = (
        clamped.to(tl.float32) * linear.to(tl.float32) + 0.89453125
    ).to(tl.float16)
    return (x.to(tl.float32) * gate.to(tl.float32)).to(tl.float16)


@triton.jit
def _fused_c32_mlp(X, W1, W2, COSINE, OUT, rows_total: tl.constexpr, BM: tl.constexpr):
    rows = tl.program_id(0) * BM + tl.arange(0, BM)
    channels = tl.arange(0, 32)
    hidden_channels = tl.arange(0, 128)
    mask = rows[:, None] < rows_total

    x = tl.load(X + rows[:, None] * 32 + channels[None, :], mask=mask, other=0)
    w1 = tl.load(W1 + channels[:, None] * 128 + hidden_channels[None, :])
    expanded = tl.dot(x, w1, out_dtype=tl.float32).to(tl.float16)
    hidden = _round_fp8_half(_quadratic_gate_activation(expanded))
    w2 = tl.load(W2 + hidden_channels[:, None] * 32 + channels[None, :])
    branch = tl.dot(hidden, w2, out_dtype=tl.float32)
    cosine = tl.load(COSINE + channels)
    result = (branch + x.to(tl.float32) * cosine[None, :].to(tl.float32)).to(tl.float16)
    tl.store(OUT + rows[:, None] * 32 + channels[None, :], result, mask=mask)


def _select_row(rows: list[dict], split: str, sequence_id: str, frame: int, eye: int) -> dict:
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


def _event_time(callback) -> float:
    start = torch.cuda.Event(enable_timing=True)
    end = torch.cuda.Event(enable_timing=True)
    start.record()
    callback()
    end.record()
    end.synchronize()
    return float(start.elapsed_time(end))


def _reference_block(value: torch.Tensor, w1: torch.Tensor, w2: torch.Tensor, cosine: torch.Tensor, chunk_rows: int) -> torch.Tensor:
    """Current eager-style direct-FP8 control, bounded by row chunks."""

    output = torch.empty_like(value)
    for start in range(0, value.shape[0], chunk_rows):
        part = value[start : start + chunk_rows]
        expanded = part @ w1
        clamped = expanded.to(torch.float16).clamp(-4.0, 4.0)
        linear = (clamped.abs().to(torch.float32) * -0.055908203125 + 0.447265625).to(torch.float16)
        gate = (clamped.to(torch.float32) * linear.to(torch.float32) + 0.89453125).to(torch.float16)
        activated = (expanded.to(torch.float32) * gate.to(torch.float32)).to(torch.float16)
        hidden = activated.clamp(-448.0, 448.0).to(torch.float8_e4m3fn).to(torch.float16)
        contracted = hidden @ w2
        output[start : start + part.shape[0]] = contracted + part * cosine
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--weights", type=Path, required=True)
    parser.add_argument("--mlx-python", type=Path, required=True)
    parser.add_argument("--split", choices=("train", "validation", "test"), default="test")
    parser.add_argument("--sequence-id", default="seq-1789071762719-5")
    parser.add_argument("--frame", type=int, default=13)
    parser.add_argument("--eye", type=int, choices=(0, 1), default=0)
    parser.add_argument("--chunk-rows", type=int, default=32768)
    parser.add_argument("--block-m", type=int, choices=(16, 32, 64, 128), default=32)
    parser.add_argument("--warmup", type=int, default=2)
    parser.add_argument("--iterations", type=int, default=3)
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
    from mlxdlss.pipeline import load_weights
    from profile_whitebox_runtime import read_rgba_raw

    cache = args.cache.expanduser().resolve()
    rows = json.loads((cache / "rows.json").read_text(encoding="utf-8"))
    row = _select_row(rows, args.split, args.sequence_id, args.frame, args.eye)
    width, height = int(row["color_size"][0]), int(row["color_size"][1])
    source = read_rgba_raw(Path(row["raw_paths"]["input"]), width, height)

    # The pipeline is CPU-resident here because only prepare() is needed.  This
    # avoids allocating all 649 weights on CUDA for a one-block probe.
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

    features = torch.from_numpy(np.ascontiguousarray(prepared.features)).to("cuda", torch.float16)
    feature_rows = features.shape[0] * features.shape[1]
    feature_matrix = features.reshape(feature_rows, 16)
    adapter = weights["block0.layer0.input_adapter_weight"].to("cuda", torch.float16).contiguous()
    value = (feature_matrix @ adapter).contiguous()
    w1 = weights["block0.layer0.weight1"].to("cuda", torch.float16).contiguous()
    w2 = weights["block0.layer0.weight2"].to("cuda", torch.float16).contiguous()
    cosine = weights["block0.layer0.ffn_cos_skip"].to("cuda", torch.float16).contiguous()
    fused_output = torch.empty_like(value)

    # Compile and execute once outside the timing loop.  The compile time is
    # reported separately because it is not a per-frame runtime cost.
    compile_started = time.perf_counter()
    _fused_c32_mlp[(triton.cdiv(feature_rows, args.block_m),)](
        value, w1, w2, cosine, fused_output, feature_rows, args.block_m,
        num_warps=4,
        num_stages=2,
        enable_fp_fusion=False,
    )
    torch.cuda.synchronize()
    compile_seconds = time.perf_counter() - compile_started

    for _ in range(args.warmup):
        _fused_c32_mlp[(triton.cdiv(feature_rows, args.block_m),)](
            value, w1, w2, cosine, fused_output, feature_rows, args.block_m,
            num_warps=4,
            num_stages=2,
            enable_fp_fusion=False,
        )
    torch.cuda.synchronize()
    fused_times = [
        _event_time(
            lambda: _fused_c32_mlp[(triton.cdiv(feature_rows, args.block_m),)](
                value, w1, w2, cosine, fused_output, feature_rows, args.block_m,
                num_warps=4,
                num_stages=2,
                enable_fp_fusion=False,
            )
        )
        for _ in range(args.iterations)
    ]

    baseline_output = torch.empty_like(value)
    for _ in range(args.warmup):
        baseline_output.copy_(_reference_block(value, w1, w2, cosine, args.chunk_rows))
    torch.cuda.synchronize()
    baseline_times = [
        _event_time(lambda: baseline_output.copy_(_reference_block(value, w1, w2, cosine, args.chunk_rows)))
        for _ in range(args.iterations)
    ]

    torch.cuda.synchronize()
    difference = (fused_output.float() - baseline_output.float()).abs()
    # A full quantile workspace for the 32-channel full-eye tensor would be
    # unnecessarily large.  The fixed stride keeps the percentile diagnostic
    # deterministic while mean/max/fraction below still cover every value.
    percentile_sample = difference.reshape(-1)[::1024]
    args.output.expanduser().resolve().mkdir(parents=True, exist_ok=True)
    result = {
        "schema": "opennr-native-style-c32-cuda-probe-v1",
        "scope": "one block0 C32 MLP on a real Skyrim feature tensor; no attention, temporal, stereo, native DLL, or live runtime",
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
            "source_resolution": [width, height],
            "feature_resolution": [int(features.shape[1]), int(features.shape[0])],
            "feature_rows": int(feature_rows),
            "feature_channels": 16,
            "block_input_channels": 32,
        },
        "kernel": {
            "block": "block0.layer0",
            "operation": "C32 expansion -> quadratic gate -> E4M3 -> C32 contraction -> cosine residual",
            "block_m": args.block_m,
            "warps": 4,
            "stages": 2,
            "triton": triton.__version__,
        },
        "timing_ms": {
            "compile_and_first_run": compile_seconds * 1000.0,
            "fused_median": float(np.median(fused_times)),
            "fused_p95": float(np.percentile(fused_times, 95.0)),
            "fused_samples": fused_times,
            "eager_direct_fp8_chunked_median": float(np.median(baseline_times)),
            "eager_direct_fp8_chunked_p95": float(np.percentile(baseline_times, 95.0)),
            "eager_samples": baseline_times,
        },
        "speedup": float(np.median(baseline_times) / np.median(fused_times)),
        "drift_vs_eager_direct_fp8": {
            "mae": float(difference.mean().item()),
            "p99": float(torch.quantile(percentile_sample, 0.99).item()),
            "p999": float(torch.quantile(percentile_sample, 0.999).item()),
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
            "chunk_rows": args.chunk_rows,
        },
        "interpretation": "A positive result validates the native-style fusion direction for one block only. It does not establish full-graph speed, exact native parity, temporal/stereo behavior, or VR readiness.",
    }
    (args.output.expanduser().resolve() / "result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
