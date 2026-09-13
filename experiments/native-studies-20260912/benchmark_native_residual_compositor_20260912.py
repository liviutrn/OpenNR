"""Measure the resident GPU cost of a reduced native residual composite.

This is deliberately an offline CUDA reference, not a claim about the live
Skyrim D3D12 compositor.  It measures the operations used by the visual
definition:

    full_raw + bilinear_upsample(native_work - work_input)

The inputs are loaded once and kept resident on the GPU.  Host I/O and
network evaluation are outside the timed region.  The result is written to a
separate C: drive output directory so the full D: worktree remains untouched.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as F


FULL_WIDTH = 2496
FULL_HEIGHT = 2688


def read_rgba8(path: Path, width: int, height: int) -> torch.Tensor:
    payload = path.read_bytes()
    expected = width * height * 4
    if len(payload) != expected:
        raise ValueError(f"{path} has {len(payload)} bytes; expected {expected}")
    array = np.frombuffer(payload, dtype=np.uint8).reshape(height, width, 4)
    rgb = np.ascontiguousarray(array[:, :, :3].transpose(2, 0, 1))
    return torch.from_numpy(rgb).float().unsqueeze(0).div_(255.0)


def summarize(values: list[float]) -> dict[str, float | int]:
    array = np.asarray(values, dtype=np.float64)
    return {
        "count": int(array.size),
        "median_ms": float(np.percentile(array, 50)),
        "p95_ms": float(np.percentile(array, 95)),
        "mean_ms": float(array.mean()),
        "min_ms": float(array.min()),
        "max_ms": float(array.max()),
    }


def benchmark(fn, *, warmup: int, iterations: int) -> dict[str, float | int]:
    for _ in range(warmup):
        fn()
    torch.cuda.synchronize()

    samples: list[float] = []
    for _ in range(iterations):
        start = torch.cuda.Event(enable_timing=True)
        end = torch.cuda.Event(enable_timing=True)
        start.record()
        fn()
        end.record()
        end.synchronize()
        samples.append(float(start.elapsed_time(end)))
    return summarize(samples)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--full-input",
        type=Path,
        default=Path(
            r"C:\OpenNR_Captures_FullEyeTemporalStateTranche_20260910\seq-1789063628889-1\frames\frame_00000001\input_eye0_full.raw.bin"
        ),
    )
    parser.add_argument(
        "--work-input",
        type=Path,
        default=Path(
            r"D:\.CODEX_Projects\OpenNR-VR\out\native_teacher_resolution_renderer_contract_20260912\scale050\input_eye0.rgba"
        ),
    )
    parser.add_argument(
        "--native-work",
        type=Path,
        default=Path(
            r"D:\.CODEX_Projects\OpenNR-VR\out\native_teacher_resolution_renderer_contract_20260912\scale050\teacher_eye0.rgba"
        ),
    )
    parser.add_argument("--warmup", type=int, default=50)
    parser.add_argument("--iterations", type=int, default=200)
    parser.add_argument("--work-width", type=int, default=1248)
    parser.add_argument("--work-height", type=int, default=1344)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(r"C:\OpenNR\native_residual_compositor_bench_20260912.json"),
    )
    args = parser.parse_args()

    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is unavailable")

    full = read_rgba8(args.full_input, FULL_WIDTH, FULL_HEIGHT).cuda().half()
    work_input = read_rgba8(args.work_input, args.work_width, args.work_height).cuda().half()
    native_work = read_rgba8(args.native_work, args.work_width, args.work_height).cuda().half()
    output = torch.empty_like(full)

    def compose_no_clamp() -> None:
        residual = native_work - work_input
        upsampled = F.interpolate(
            residual,
            size=(FULL_HEIGHT, FULL_WIDTH),
            mode="bilinear",
            align_corners=False,
        )
        torch.add(full, upsampled, out=output)

    def compose_with_clamp() -> None:
        compose_no_clamp()
        output.clamp_(0.0, 1.0)

    def downsample() -> None:
        # This is the color-side preparation only.  Guide preparation and
        # the exact renderer resource contract remain outside this reference.
        F.interpolate(
            full,
            size=(args.work_height, args.work_width),
            mode="bilinear",
            align_corners=False,
        )

    # CUDA graph replay removes Python dispatch overhead and allocator churn,
    # giving a closer lower-level reference for a preallocated shader path.
    graph = torch.cuda.CUDAGraph()
    capture_stream = torch.cuda.Stream()
    torch.cuda.synchronize()
    with torch.cuda.stream(capture_stream):
        compose_with_clamp()
        capture_stream.synchronize()
        graph.capture_begin()
        compose_with_clamp()
        graph.capture_end()
    capture_stream.synchronize()
    torch.cuda.synchronize()

    def graph_compose() -> None:
        graph.replay()

    downsample_graph = torch.cuda.CUDAGraph()
    downsample_capture_stream = torch.cuda.Stream()
    with torch.cuda.stream(downsample_capture_stream):
        downsample()
        downsample_capture_stream.synchronize()
        downsample_graph.capture_begin()
        downsample()
        downsample_graph.capture_end()
    downsample_capture_stream.synchronize()
    torch.cuda.synchronize()

    def graph_downsample() -> None:
        downsample_graph.replay()

    result = {
        "device": torch.cuda.get_device_name(0),
        "torch": torch.__version__,
        "cuda": torch.version.cuda,
        "shape": {
            "full": [FULL_HEIGHT, FULL_WIDTH],
            "work": [args.work_height, args.work_width],
            "channels": 3,
            "dtype": "float16",
        },
        "inputs": {
            "full_input": str(args.full_input),
            "work_input": str(args.work_input),
            "native_work": str(args.native_work),
        },
        "warmup": args.warmup,
        "iterations": args.iterations,
        "eager_no_clamp": benchmark(compose_no_clamp, warmup=args.warmup, iterations=args.iterations),
        "eager_with_clamp": benchmark(compose_with_clamp, warmup=args.warmup, iterations=args.iterations),
        "cuda_graph_with_clamp": benchmark(graph_compose, warmup=args.warmup, iterations=args.iterations),
        "eager_color_downsample": benchmark(downsample, warmup=args.warmup, iterations=args.iterations),
        "cuda_graph_color_downsample": benchmark(graph_downsample, warmup=args.warmup, iterations=args.iterations),
        "finite": bool(torch.isfinite(output).all().item()),
        "output_range": [float(output.min().item()), float(output.max().item())],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
