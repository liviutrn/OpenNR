"""Benchmark forward-only capacity-temporal inference on a local CUDA GPU.

This is a quality/compute diagnostic. It does not train, modify checkpoints,
or establish live stereo, headset, compositor, or VR-budget acceptance.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import statistics
import time

import torch

from train_temporal_student import StrictTemporalCache, _device_batch, _load_temporal


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--checkpoint", type=Path, action="append", required=True)
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--batch", type=int, default=2)
    parser.add_argument("--warmup", type=int, default=10)
    parser.add_argument("--iterations", type=int, default=50)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is required for this forward-only benchmark")
    if args.batch < 1 or args.warmup < 0 or args.iterations < 1:
        raise ValueError("batch must be positive, warmup non-negative, iterations positive")

    cache = StrictTemporalCache(args.cache, "validation")
    selected, arrays = next(cache.stream_batches(args.batch))
    rgb_np, _target_np, guides_np, context_np = arrays
    rgb, _target, guides, context = _device_batch(
        (rgb_np[:, 0], rgb_np[:, 0], guides_np[:, 0], context_np[:, 0]), "cuda"
    )
    rgb = rgb.float() / 255.0
    guides = guides.float()
    context = context.float()

    results = []
    for checkpoint_path in args.checkpoint:
        model, saved = _load_temporal(checkpoint_path, "cuda")
        model.eval()
        torch.cuda.synchronize()
        torch.cuda.empty_cache()
        baseline_allocated = torch.cuda.memory_allocated()

        state = None
        with torch.inference_mode():
            for _ in range(args.warmup):
                with torch.autocast(device_type="cuda", dtype=torch.bfloat16):
                    _prediction, state = model.forward_temporal(rgb, guides, context, state)
        torch.cuda.synchronize()

        timings = []
        state = None
        with torch.inference_mode():
            for _ in range(args.iterations):
                started = time.perf_counter()
                with torch.autocast(device_type="cuda", dtype=torch.bfloat16):
                    _prediction, state = model.forward_temporal(rgb, guides, context, state)
                torch.cuda.synchronize()
                timings.append((time.perf_counter() - started) * 1000.0)

        results.append(
            {
                "checkpoint": str(checkpoint_path.resolve()),
                "architecture": saved.get("architecture"),
                "step": saved.get("step"),
                "parameters": sum(parameter.numel() for parameter in model.parameters()),
                "batch": args.batch,
                "streams_used": [list(item) for item in selected],
                "mean_ms_batch": statistics.mean(timings),
                "median_ms_batch": statistics.median(timings),
                "p95_ms_batch": sorted(timings)[max(0, int(0.95 * len(timings)) - 1)],
                "mean_ms_per_eye_frame": statistics.mean(timings) / args.batch,
                "baseline_allocated_gib": baseline_allocated / (1024**3),
                "peak_allocated_gib": torch.cuda.max_memory_allocated() / (1024**3),
                "peak_reserved_gib": torch.cuda.max_memory_reserved() / (1024**3),
            }
        )
        del model, state
        torch.cuda.empty_cache()

    payload = {"device": torch.cuda.get_device_name(0), "results": results}
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
