#!/usr/bin/env python3
"""Benchmark one warmed recovered white-box graph call without file I/O."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import time

import numpy as np

from profile_whitebox_runtime import read_rgba_raw


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--weights", type=Path, required=True)
    parser.add_argument("--mlx-python", type=Path, required=True)
    parser.add_argument("--split", choices=("train", "validation", "test"), default="test")
    parser.add_argument("--sequence-id", required=True)
    parser.add_argument("--frame", type=int, default=1)
    parser.add_argument("--eye", type=int, choices=(0, 1), default=0)
    parser.add_argument("--mode", choices=("reference", "fast_fp16", "activation_fp8"), default="activation_fp8")
    parser.add_argument("--warmup", type=int, default=2)
    parser.add_argument("--iterations", type=int, default=5)
    args = parser.parse_args()

    mlx_python = args.mlx_python.expanduser().resolve()
    if str(mlx_python) not in sys.path:
        sys.path.insert(0, str(mlx_python))
    import torch
    from mlxdlss import NeuralRenderingPipeline
    from mlxdlss import model as recovered_model
    from mlxdlss.pipeline import load_weights

    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is required")
    rows = json.loads((args.cache.expanduser().resolve() / "rows.json").read_text(encoding="utf-8"))
    selected = [
        row
        for row in rows
        if row.get("split") == args.split
        and str(row.get("sequence_id")) == args.sequence_id
        and int(row.get("frame_id", -1)) == args.frame
        and int(row.get("eye", -1)) == args.eye
    ]
    if len(selected) != 1:
        raise ValueError(f"expected one row, found {len(selected)}")
    row = selected[0]
    width, height = int(row["color_size"][0]), int(row["color_size"][1])
    source = read_rgba_raw(Path(row["raw_paths"]["input"]), width, height)
    weights = load_weights(args.weights.expanduser().resolve())

    restore = None
    if args.mode == "reference":
        pipeline = NeuralRenderingPipeline(weights, device="cuda", precision="reference")
    else:
        if args.mode == "activation_fp8":
            original = recovered_model.e4m3_round_trip

            def direct_fp8(value):
                return value.clamp(-448.0, 448.0).to(torch.float8_e4m3fn).to(value.dtype)

            recovered_model.e4m3_round_trip = direct_fp8
            restore = lambda: setattr(recovered_model, "e4m3_round_trip", original)
        pipeline = NeuralRenderingPipeline(weights, device="cuda", precision="fast")

    prepared = pipeline.prepare(
        source,
        profile="standard",
        processing_scale=1.0,
        frame_index=0,
        local_tone_strength=1.0,
        local_structure_strength=1.0,
    )
    tensor = torch.from_numpy(np.ascontiguousarray(prepared.features)).to(
        pipeline.device, pipeline.dtype
    )[None]
    model = pipeline.model.eval()
    torch.cuda.reset_peak_memory_stats()
    with torch.no_grad():
        for _ in range(max(0, args.warmup)):
            _ = model(tensor)
    torch.cuda.synchronize()
    times = []
    with torch.no_grad():
        for _ in range(max(1, args.iterations)):
            torch.cuda.synchronize()
            started = time.perf_counter()
            _ = model(tensor)
            torch.cuda.synchronize()
            times.append((time.perf_counter() - started) * 1000.0)
    if restore is not None:
        restore()
    print(
        json.dumps(
            {
                "mode": args.mode,
                "sequence_id": row["sequence_id"],
                "frame": args.frame,
                "eye": args.eye,
                "chunk_tokens": __import__("os").environ.get("MLXDLSS_TORCH_CHUNK_TOKENS", "default"),
                "warmup": args.warmup,
                "iterations": args.iterations,
                "median_ms": float(np.median(times)),
                "p95_ms": float(np.percentile(times, 95.0)),
                "min_ms": float(np.min(times)),
                "max_ms": float(np.max(times)),
                "peak_allocated_bytes": int(torch.cuda.max_memory_allocated()),
                "gpu": torch.cuda.get_device_name(0),
                "torch": torch.__version__,
            },
            indent=2,
        ),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
