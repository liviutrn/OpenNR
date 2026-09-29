#!/usr/bin/env python3
"""Profile one isolated recovered white-box graph invocation.

This tool is diagnostic only.  It profiles a complete captured eye frame in
the Python reference implementation and writes operator tables; it never
changes weights, captures, the native DLL, Skyrim, or a runtime.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import time

import numpy as np


def read_rgba_raw(path: Path, width: int, height: int) -> np.ndarray:
    raw = path.read_bytes()
    expected = width * height * 4
    if len(raw) != expected:
        raise ValueError(f"{path}: {len(raw)} bytes, expected {expected}")
    rgba = np.frombuffer(raw, dtype=np.uint8).reshape(height, width, 4)
    return np.ascontiguousarray(rgba[..., :3], dtype=np.float32) / 255.0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--weights", type=Path, required=True)
    parser.add_argument("--mlx-python", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--split", choices=("train", "validation", "test"), default="test")
    parser.add_argument("--sequence-id", required=True)
    parser.add_argument("--frame", type=int, default=1)
    parser.add_argument("--eye", type=int, choices=(0, 1), default=0)
    parser.add_argument("--mode", choices=("reference", "fast_fp16", "activation_fp8"), default="reference")
    parser.add_argument("--warmup", type=int, default=1)
    args = parser.parse_args()

    cache = args.cache.expanduser().resolve()
    weights_path = args.weights.expanduser().resolve()
    mlx_python = args.mlx_python.expanduser().resolve()
    output = args.output.expanduser().resolve()
    if output.exists() and any(output.iterdir()):
        raise FileExistsError(f"refusing to overwrite non-empty output: {output}")
    output.mkdir(parents=True, exist_ok=True)
    if str(mlx_python) not in sys.path:
        sys.path.insert(0, str(mlx_python))

    import torch
    from mlxdlss import NeuralRenderingPipeline
    from mlxdlss import model as recovered_model
    from mlxdlss.pipeline import load_weights

    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is required")
    rows = json.loads((cache / "rows.json").read_text(encoding="utf-8"))
    candidates = [
        row
        for row in rows
        if row.get("split") == args.split
        and str(row.get("sequence_id")) == args.sequence_id
        and int(row.get("frame_id", -1)) == args.frame
        and int(row.get("eye", -1)) == args.eye
    ]
    if len(candidates) != 1:
        raise ValueError(f"expected one row, found {len(candidates)}")
    row = candidates[0]
    width, height = (int(row["color_size"][0]), int(row["color_size"][1]))
    source = read_rgba_raw(Path(row["raw_paths"]["input"]), width, height)
    weights = load_weights(weights_path)

    if args.mode == "reference":
        pipeline = NeuralRenderingPipeline(weights, device="cuda", precision="reference")
    else:
        original_round_trip = None
        if args.mode == "activation_fp8":
            original_round_trip = recovered_model.e4m3_round_trip

            def direct_fp8(value):
                return value.clamp(-448.0, 448.0).to(torch.float8_e4m3fn).to(value.dtype)

            recovered_model.e4m3_round_trip = direct_fp8
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
    for _ in range(max(0, args.warmup)):
        with torch.no_grad():
            _ = model(tensor)
    torch.cuda.synchronize()

    started = time.perf_counter()
    with torch.profiler.profile(
        activities=[torch.profiler.ProfilerActivity.CPU, torch.profiler.ProfilerActivity.CUDA],
        record_shapes=False,
        profile_memory=False,
        with_stack=False,
    ) as profiler:
        with torch.no_grad():
            output_tensor = model(tensor)
        torch.cuda.synchronize()
    elapsed = time.perf_counter() - started

    table = profiler.key_averages().table(
        sort_by="self_cuda_time_total",
        row_limit=40,
    )
    (output / "operator_table.txt").write_text(table + "\n", encoding="utf-8")
    (output / "operator_table_cuda_total.txt").write_text(
        profiler.key_averages().table(sort_by="cuda_time_total", row_limit=40) + "\n",
        encoding="utf-8",
    )
    events = []
    for event in profiler.key_averages():
        events.append(
            {
                "key": event.key,
                "count": int(event.count),
                "self_cuda_us": float(event.self_device_time_total),
                "cuda_total_us": float(event.device_time_total),
                "self_cpu_us": float(event.self_cpu_time_total),
                "cpu_total_us": float(event.cpu_time_total),
            }
        )
    events.sort(key=lambda item: item["self_cuda_us"], reverse=True)
    summary = {
        "schema": "opennr-whitebox-runtime-profile-v1",
        "scope": "one complete captured eye, one warmed model call; operator diagnostic only",
        "cache": str(cache),
        "weights": str(weights_path),
        "row": {
            "sequence_id": row["sequence_id"],
            "frame_id": int(row["frame_id"]),
            "eye": int(row["eye"]),
            "split": row["split"],
            "shape": [height, width, 3],
        },
        "mode": args.mode,
        "torch_version": torch.__version__,
        "cuda_version": torch.version.cuda,
        "gpu": torch.cuda.get_device_name(0),
        "steady_state_profile_seconds": float(elapsed),
        "output_shape": list(output_tensor.shape),
        "events_by_self_cuda": events[:80],
        "warning": "This is the unfused Python/PyTorch reference path; native DLSS timings are not inferred from this table.",
    }
    (output / "profile.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(output), "mode": args.mode, "elapsed_seconds": elapsed, "top": events[:12]}, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
