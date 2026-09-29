#!/usr/bin/env python3
"""Benchmark reduced-resolution recovered NR with a full-resolution residual."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import time

import numpy as np

from profile_whitebox_runtime import read_rgba_raw


def _stats(actual: np.ndarray, reference: np.ndarray | None) -> dict[str, float | None]:
    if reference is None:
        return {"mae_vs_reference": None, "p999_abs_vs_reference": None, "max_abs_vs_reference": None}
    delta = np.abs(np.asarray(actual, dtype=np.float32) - np.asarray(reference, dtype=np.float32))
    return {
        "mae_vs_reference": float(delta.mean()),
        "p999_abs_vs_reference": float(np.quantile(delta, 0.999)),
        "max_abs_vs_reference": float(delta.max()),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--weights", type=Path, required=True)
    parser.add_argument("--mlx-python", type=Path, required=True)
    parser.add_argument("--split", choices=("train", "validation", "test"), default="test")
    parser.add_argument("--sequence-id", required=True)
    parser.add_argument("--frame", type=int, default=1)
    parser.add_argument("--eye", type=int, choices=(0, 1), default=0)
    parser.add_argument("--scale", type=float, required=True)
    parser.add_argument("--warmup", type=int, default=1)
    parser.add_argument("--iterations", type=int, default=3)
    parser.add_argument("--reference", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    if not 0.1 <= args.scale <= 1.0:
        raise ValueError("scale must be within [0.1, 1.0]")
    mlx_python = args.mlx_python.expanduser().resolve()
    if str(mlx_python) not in sys.path:
        sys.path.insert(0, str(mlx_python))

    import torch
    from mlxdlss import NeuralRenderingPipeline
    from mlxdlss import model as recovered_model
    from mlxdlss.composition import compose_head, resample
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
    full_width, full_height = int(row["color_size"][0]), int(row["color_size"][1])
    source = read_rgba_raw(Path(row["raw_paths"]["input"]), full_width, full_height)
    reference = None
    if args.reference is not None:
        reference = np.asarray(np.load(args.reference.expanduser().resolve()), dtype=np.float32)
        if reference.shape != source.shape:
            raise ValueError(f"reference shape {reference.shape} does not match source {source.shape}")

    # The recovered source's public processing_scale intentionally only permits
    # supersampling. For this isolated experiment, resample the source first,
    # then use its ordinary scale=1 path at the reduced internal resolution.
    low_width = max(320, int(round(full_width * args.scale)))
    low_height = max(320, int(round(full_height * args.scale)))
    low = resample(source, low_width, low_height)

    original_round_trip = recovered_model.e4m3_round_trip

    def direct_fp8(value):
        return value.clamp(-448.0, 448.0).to(torch.float8_e4m3fn).to(value.dtype)

    recovered_model.e4m3_round_trip = direct_fp8
    try:
        weights = load_weights(args.weights.expanduser().resolve())
        pipeline = NeuralRenderingPipeline(weights, device="cuda", precision="fast")
        started = time.perf_counter()
        prepared = pipeline.prepare(
            low,
            profile="standard",
            processing_scale=1.0,
            frame_index=0,
            local_tone_strength=1.0,
            local_structure_strength=1.0,
        )
        preprocess_seconds = time.perf_counter() - started
        tensor = torch.from_numpy(np.ascontiguousarray(prepared.features)).to(
            pipeline.device, pipeline.dtype
        )[None]
        model = pipeline.model.eval()
        torch.cuda.reset_peak_memory_stats()
        with torch.no_grad():
            for _ in range(max(0, args.warmup)):
                head = model(tensor)
        torch.cuda.synchronize()
        times: list[float] = []
        heads: list[np.ndarray] = []
        with torch.no_grad():
            for _ in range(max(1, args.iterations)):
                torch.cuda.synchronize()
                tick = time.perf_counter()
                head = model(tensor)
                torch.cuda.synchronize()
                times.append((time.perf_counter() - tick) * 1000.0)
                heads.append(head.to(torch.float32).cpu().numpy()[0])
        low_head = heads[-1]
        low_output = compose_head(prepared.geometry.crop(low_head), low)

        # Matched-residual resolve: keep the pristine full-resolution source and
        # transfer only the low-resolution network's change back to it.
        low_delta = low_output - low
        full_delta = resample(low_delta, full_width, full_height)
        output = np.clip(source + full_delta, 0.0, 1.0).astype(np.float32)
        if args.output is not None:
            target = args.output.expanduser().resolve()
            target.parent.mkdir(parents=True, exist_ok=True)
            np.save(target.with_suffix(".npy"), output)
            from PIL import Image

            Image.fromarray(np.rint(output * 255.0).clip(0, 255).astype(np.uint8), mode="RGB").save(
                target.with_suffix(".png")
            )
    finally:
        recovered_model.e4m3_round_trip = original_round_trip

    result = {
        "mode": "activation_fp8_reduced_internal_resolution_matched_residual",
        "sequence_id": row["sequence_id"],
        "frame": args.frame,
        "eye": args.eye,
        "requested_scale": args.scale,
        "low_resolution": [low_width, low_height],
        "network_resolution": [prepared.geometry.network_width, prepared.geometry.network_height],
        "output_resolution": [full_width, full_height],
        "chunk_tokens": os.environ.get("MLXDLSS_TORCH_CHUNK_TOKENS", "default"),
        "warmup": args.warmup,
        "iterations": args.iterations,
        "preprocess_ms": preprocess_seconds * 1000.0,
        "model_median_ms": float(np.median(times)),
        "model_p95_ms": float(np.percentile(times, 95.0)),
        "model_min_ms": float(np.min(times)),
        "model_max_ms": float(np.max(times)),
        "peak_allocated_bytes": int(torch.cuda.max_memory_allocated()),
        "gpu": torch.cuda.get_device_name(0),
        "torch": torch.__version__,
        "reference_path": str(args.reference.expanduser().resolve()) if args.reference else None,
        "residual_stats": _stats(output, reference),
        "contract_warning": "Reduced internal resolution plus matched residual is an approximation; it is not full-resolution white-box parity or live VR evidence.",
    }
    print(json.dumps(result, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
