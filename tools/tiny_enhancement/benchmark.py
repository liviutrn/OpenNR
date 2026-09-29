"""Measure frozen tiny-model GPU inference latency on the RTX 5070 Ti."""

from __future__ import annotations

import argparse
import json
import statistics
import time
from pathlib import Path

import torch

from .models import build_model, parameter_count


def _percentile(values: list[float], fraction: float) -> float:
    values = sorted(values)
    if not values:
        return float("nan")
    index = (len(values) - 1) * fraction
    lower = int(index)
    upper = min(lower + 1, len(values) - 1)
    weight = index - lower
    return values[lower] * (1.0 - weight) + values[upper] * weight


def _measure(model: torch.nn.Module, height: int, width: int, warmup: int, iterations: int, dtype: torch.dtype) -> dict:
    image = torch.rand(1, 3, height, width, device="cuda", dtype=dtype)
    with torch.inference_mode(), torch.autocast(device_type="cuda", dtype=dtype):
        for _ in range(warmup):
            model(image)
        torch.cuda.synchronize()
        timings: list[float] = []
        for _ in range(iterations):
            start = torch.cuda.Event(enable_timing=True)
            end = torch.cuda.Event(enable_timing=True)
            start.record()
            model(image)
            end.record()
            end.synchronize()
            timings.append(float(start.elapsed_time(end)))
    return {
        "height": height,
        "width": width,
        "batch": 1,
        "precision": "fp16" if dtype == torch.float16 else "fp32",
        "warmup": warmup,
        "iterations": iterations,
        "median_ms": statistics.median(timings),
        "p95_ms": _percentile(timings, 0.95),
        "p99_ms": _percentile(timings, 0.99),
        "min_ms": min(timings),
        "max_ms": max(timings),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--warmup", type=int, default=10)
    parser.add_argument("--iterations", type=int, default=30)
    parser.add_argument("--full-height", type=int, default=2688)
    parser.add_argument("--full-width", type=int, default=2496)
    parser.add_argument("--device", default="cuda")
    args = parser.parse_args()
    if args.device != "cuda" or not torch.cuda.is_available():
        raise RuntimeError("the RTX 5070 Ti CUDA device is required for this benchmark")
    checkpoint = torch.load(args.checkpoint.resolve(), map_location="cuda", weights_only=False)
    model = build_model(checkpoint["architecture"], checkpoint.get("config")).cuda().eval()
    model.load_state_dict(checkpoint["model"])
    if parameter_count(model) != checkpoint["parameters"]:
        raise ValueError("checkpoint parameter count mismatch")
    torch.cuda.reset_peak_memory_stats()
    started = time.time()
    results = [
        _measure(model, 512, 512, args.warmup, args.iterations, torch.float16),
        _measure(model, args.full_height, args.full_width, max(3, args.warmup // 2), max(10, args.iterations // 2), torch.float16),
    ]
    torch.cuda.synchronize()
    result = {
        "schema": "opennr-tiny-enhancement-benchmark-v1",
        "architecture": checkpoint["architecture"],
        "checkpoint": str(args.checkpoint.resolve()),
        "checkpoint_step": checkpoint.get("step"),
        "parameters": parameter_count(model),
        "device": torch.cuda.get_device_name(0),
        "torch": torch.__version__,
        "cuda": torch.version.cuda,
        "peak_vram_gib": torch.cuda.max_memory_allocated() / 2**30,
        "seconds": time.time() - started,
        "measurements": results,
        "path_scope": "network-only forward pass; input already resident on GPU; no CPU readback",
    }
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()

