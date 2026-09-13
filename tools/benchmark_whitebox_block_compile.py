#!/usr/bin/env python3
"""Benchmark generic compilation of one recovered C32 block.

This is an offline diagnostic companion to ``benchmark_whitebox_compile_resolution``.
It intentionally compiles only the adapter plus block-0 window path, because a
successful per-block compile would justify a staged backend while a full-graph
compile may be too large for a generic compiler.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
import time

import numpy as np

from profile_whitebox_runtime import read_rgba_raw


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def select_row(cache: Path, split: str, sequence_id: str, frame: int, eye: int) -> dict:
    rows = json.loads((cache / "rows.json").read_text(encoding="utf-8"))
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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--weights", type=Path, required=True)
    parser.add_argument("--mlx-python", type=Path, required=True)
    parser.add_argument("--split", choices=("train", "validation", "test"), default="test")
    parser.add_argument("--sequence-id", required=True)
    parser.add_argument("--frame", type=int, default=13)
    parser.add_argument("--eye", type=int, choices=(0, 1), default=0)
    parser.add_argument("--scale", type=float, default=0.33)
    parser.add_argument("--warmup", type=int, default=1)
    parser.add_argument("--iterations", type=int, default=2)
    parser.add_argument(
        "--rounding",
        choices=("direct-fp8", "bitwise"),
        default="direct-fp8",
        help="activation publication implementation used by the recovered graph",
    )
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not 0.1 <= args.scale <= 1.0:
        raise ValueError("scale must be within [0.1, 1.0]")
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
    from mlxdlss.composition import resample
    from mlxdlss.pipeline import load_weights

    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is required")
    row = select_row(cache, args.split, args.sequence_id, args.frame, args.eye)
    full_width = int(row["color_size"][0])
    full_height = int(row["color_size"][1])
    source = read_rgba_raw(Path(row["raw_paths"]["input"]), full_width, full_height)
    low_width = max(320, int(round(full_width * args.scale)))
    low_height = max(320, int(round(full_height * args.scale)))
    low = resample(source, low_width, low_height)

    original_round_trip = recovered_model.e4m3_round_trip

    def direct_fp8(value: torch.Tensor) -> torch.Tensor:
        return value.clamp(-448.0, 448.0).to(torch.float8_e4m3fn).to(value.dtype)

    if args.rounding == "direct-fp8":
        recovered_model.e4m3_round_trip = direct_fp8
    status = "complete"
    error = None
    compile_setup_ms = None
    first_invocation_ms = None
    steady_times: list[float] = []
    parity = None
    peak_allocated = None
    peak_reserved = None
    network_resolution = None
    try:
        weights = load_weights(weights_path)
        pipeline = NeuralRenderingPipeline(weights, device="cuda", precision="fast")
        prepared = pipeline.prepare(
            low,
            profile="standard",
            processing_scale=1.0,
            frame_index=0,
            local_tone_strength=1.0,
            local_structure_strength=1.0,
        )
        network_resolution = [
            int(prepared.geometry.network_width),
            int(prepared.geometry.network_height),
        ]
        features = torch.from_numpy(np.ascontiguousarray(prepared.features)).to(
            pipeline.device, pipeline.dtype
        )[None]
        model = pipeline.model.eval()
        adapter = model.weight("block0.layer0.input_adapter_weight")
        block_input = features @ adapter

        class Block0(torch.nn.Module):
            def __init__(self, source_model: torch.nn.Module):
                super().__init__()
                self.source_model = source_model

            def forward(self, value: torch.Tensor) -> torch.Tensor:
                return self.source_model._window(value, 0, head_count=1)

        block = Block0(model).eval()
        with torch.no_grad():
            eager_output = block(block_input)
        torch.cuda.synchronize()

        started = time.perf_counter()
        compiled = torch.compile(block, mode="reduce-overhead", fullgraph=False, dynamic=False)
        compile_setup_ms = (time.perf_counter() - started) * 1000.0
        torch.cuda.reset_peak_memory_stats()
        torch.cuda.synchronize()
        started = time.perf_counter()
        with torch.no_grad():
            compiled_output = compiled(block_input)
        torch.cuda.synchronize()
        first_invocation_ms = (time.perf_counter() - started) * 1000.0
        parity_error = (compiled_output - eager_output).abs()
        parity = {
            "mae": float(parity_error.mean().item()),
            "p99": float(torch.quantile(parity_error.float().reshape(-1), 0.99).item()),
            "max": float(parity_error.max().item()),
        }
        with torch.no_grad():
            for _ in range(max(0, args.warmup)):
                _ = compiled(block_input)
        torch.cuda.synchronize()
        with torch.no_grad():
            for _ in range(max(1, args.iterations)):
                torch.cuda.synchronize()
                started = time.perf_counter()
                _ = compiled(block_input)
                torch.cuda.synchronize()
                steady_times.append((time.perf_counter() - started) * 1000.0)
        peak_allocated = int(torch.cuda.max_memory_allocated())
        peak_reserved = int(torch.cuda.max_memory_reserved())
    except Exception as exc:
        status = "failed"
        error = repr(exc)
    finally:
        recovered_model.e4m3_round_trip = original_round_trip

    result = {
        "schema": "opennr-whitebox-block-compile-v1",
        "status": status,
        "error": error,
        "scale": args.scale,
        "input_resolution": [low_width, low_height],
        "network_resolution": network_resolution,
        "sequence_id": row["sequence_id"],
        "frame": int(row["frame_id"]),
        "eye": int(row["eye"]),
        "weights": str(weights_path),
        "weights_sha256": sha256_file(weights_path),
        "rounding": args.rounding,
        "torch": torch.__version__,
        "cuda": torch.version.cuda,
        "gpu": torch.cuda.get_device_name(0),
        "compile_setup_ms": compile_setup_ms,
        "first_invocation_ms": first_invocation_ms,
        "steady_median_ms": float(np.median(steady_times)) if steady_times else None,
        "steady_p95_ms": float(np.percentile(steady_times, 95.0)) if steady_times else None,
        "steady_times_ms": steady_times,
        "compiled_vs_eager": parity,
        "peak_cuda_memory_allocated_bytes": peak_allocated,
        "peak_cuda_memory_reserved_bytes": peak_reserved,
        "scope_warning": "One block only; offline timing and parity diagnostic, not full-model, native, temporal, stereo, live-VR, or promotion evidence.",
    }
    (output / "result.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2), flush=True)
    return 0 if status == "complete" else 1


if __name__ == "__main__":
    raise SystemExit(main())
