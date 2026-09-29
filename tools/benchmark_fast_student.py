"""Measure FastStudent-v1 reset and steady-state CUDA latency."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import time

import numpy as np
import torch

from fast_student_v1 import FastStudentConfig, FastStudentV1, load_fast_student


def _percentiles(values: list[float]) -> dict[str, float]:
    array = np.asarray(values, dtype=np.float64)
    return {
        "median_ms": float(np.percentile(array, 50)),
        "p95_ms": float(np.percentile(array, 95)),
        "p99_ms": float(np.percentile(array, 99)),
        "mean_ms": float(array.mean()),
        "min_ms": float(array.min()),
        "max_ms": float(array.max()),
    }


def _measure_reset(model, rgb, guides, context, warmup: int, iterations: int):
    for _ in range(warmup):
        model.forward_temporal(rgb, guides, context, None)
    torch.cuda.synchronize()
    values = []
    for _ in range(iterations):
        start = torch.cuda.Event(enable_timing=True)
        end = torch.cuda.Event(enable_timing=True)
        start.record()
        model.forward_temporal(rgb, guides, context, None)
        end.record()
        end.synchronize()
        values.append(float(start.elapsed_time(end)))
    return values


def _measure_steady(model, rgb, guides, context, warmup: int, iterations: int):
    state = None
    for _ in range(warmup):
        _, state = model.forward_temporal(rgb, guides, context, state)
    torch.cuda.synchronize()
    values = []
    for _ in range(iterations):
        start = torch.cuda.Event(enable_timing=True)
        end = torch.cuda.Event(enable_timing=True)
        start.record()
        _, state = model.forward_temporal(rgb, guides, context, state)
        end.record()
        end.synchronize()
        values.append(float(start.elapsed_time(end)))
    return values


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint", type=Path)
    parser.add_argument("--height", type=int, default=512)
    parser.add_argument("--width", type=int, default=512)
    parser.add_argument("--guide-height", type=int)
    parser.add_argument("--guide-width", type=int)
    parser.add_argument("--context-height", type=int, default=96)
    parser.add_argument("--context-width", type=int, default=96)
    parser.add_argument("--warmup", type=int, default=50)
    parser.add_argument("--iterations", type=int, default=200)
    parser.add_argument("--base-width", type=int, default=32)
    parser.add_argument("--mid-width", type=int, default=64)
    parser.add_argument("--temporal-hidden", type=int, default=64)
    parser.add_argument("--blocks", type=int, default=2)
    parser.add_argument("--fp32", action="store_true")
    parser.add_argument(
        "--no-native-refine",
        action="store_true",
        help="profile the reduced-work residual path without the full-resolution refine convolution",
    )
    args = parser.parse_args()

    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is required for this benchmark")
    if args.warmup < 1 or args.iterations < 2:
        raise ValueError("warmup must be positive and iterations must be at least two")
    guide_height = args.guide_height or math.ceil(args.height / 4)
    guide_width = args.guide_width or math.ceil(args.width / 4)
    if args.checkpoint:
        model, saved = load_fast_student(args.checkpoint, "cuda")
        architecture = saved["architecture"]
    else:
        config = FastStudentConfig(
            base_width=args.base_width,
            mid_width=args.mid_width,
            temporal_hidden=args.temporal_hidden,
            blocks=args.blocks,
            use_native_refine=not args.no_native_refine,
        )
        model = FastStudentV1(config).cuda().eval()
        architecture = "fast_student_v1_untrained_identity"
    model.eval()
    precision = "FP32"
    if not args.fp32:
        model.half()
        precision = "FP16"
    dtype = next(model.parameters()).dtype
    rgb = torch.rand(1, 3, args.height, args.width, device="cuda", dtype=dtype)
    guides = torch.randn(1, 5, guide_height, guide_width, device="cuda", dtype=dtype)
    context = torch.randn(
        1, 8, args.context_height, args.context_width, device="cuda", dtype=dtype
    )
    parameter_count = sum(parameter.numel() for parameter in model.parameters())
    torch.cuda.reset_peak_memory_stats()
    started = time.perf_counter()
    with torch.inference_mode():
        reset = _measure_reset(model, rgb, guides, context, args.warmup, args.iterations)
        steady = _measure_steady(model, rgb, guides, context, args.warmup, args.iterations)
    torch.cuda.synchronize()
    elapsed = time.perf_counter() - started
    result = {
        "architecture": architecture,
        "precision": precision,
        "device": torch.cuda.get_device_name(0),
        "shape": {
            "height": args.height,
            "width": args.width,
            "guide_height": guide_height,
            "guide_width": guide_width,
            "context_height": args.context_height,
            "context_width": args.context_width,
        },
        "parameters": parameter_count,
        "reset": _percentiles(reset),
        "steady": _percentiles(steady),
        "peak_vram_gib": torch.cuda.max_memory_allocated() / 2**30,
        "warmup": args.warmup,
        "iterations": args.iterations,
        "wall_seconds": elapsed,
        "note": "isolated model CUDA timing; this is not Skyrim in-game acceptance",
    }
    print(json.dumps(result, indent=2), flush=True)


if __name__ == "__main__":
    main()
