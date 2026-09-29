"""Measure a resident-GPU reduced native residual composite for both eyes.

This is an offline CUDA reference for the color-side operations only.  It
keeps both eyes resident and runs them sequentially on one stream so the
result can be compared with the native teacher resolution study's stereo
timings.  It does not include native NGX evaluation, guide preparation, or
live renderer synchronization.
"""

from __future__ import annotations

import argparse
import json
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


def summary(values: list[float]) -> dict[str, float | int]:
    array = np.asarray(values, dtype=np.float64)
    return {
        "count": int(array.size),
        "median_ms": float(np.percentile(array, 50)),
        "p95_ms": float(np.percentile(array, 95)),
        "mean_ms": float(array.mean()),
        "min_ms": float(array.min()),
        "max_ms": float(array.max()),
    }


def benchmark(fn, warmup: int, iterations: int) -> dict[str, float | int]:
    for _ in range(warmup):
        fn()
    torch.cuda.synchronize()
    values: list[float] = []
    for _ in range(iterations):
        start = torch.cuda.Event(enable_timing=True)
        end = torch.cuda.Event(enable_timing=True)
        start.record()
        fn()
        end.record()
        end.synchronize()
        values.append(float(start.elapsed_time(end)))
    return summary(values)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--work-width", type=int, default=1248)
    parser.add_argument("--work-height", type=int, default=1344)
    parser.add_argument("--residual-strength", type=float, default=1.0)
    parser.add_argument(
        "--full-input-eye0",
        type=Path,
        default=Path(
            r"C:\OpenNR_Captures_FullEyeTemporalStateTranche_20260910\seq-1789063628889-1\frames\frame_00000001\input_eye0_full.raw.bin"
        ),
    )
    parser.add_argument(
        "--full-input-eye1",
        type=Path,
        default=Path(
            r"C:\OpenNR_Captures_FullEyeTemporalStateTranche_20260910\seq-1789063628889-1\frames\frame_00000001\input_eye1_full.raw.bin"
        ),
    )
    parser.add_argument(
        "--work-input-eye0",
        type=Path,
        default=Path(
            r"D:\.CODEX_Projects\OpenNR-VR\out\native_teacher_resolution_renderer_contract_20260912\scale050\input_eye0.rgba"
        ),
    )
    parser.add_argument(
        "--work-input-eye1",
        type=Path,
        default=Path(
            r"D:\.CODEX_Projects\OpenNR-VR\out\native_teacher_resolution_renderer_contract_20260912\scale050\input_eye1.rgba"
        ),
    )
    parser.add_argument(
        "--native-work-eye0",
        type=Path,
        default=Path(
            r"D:\.CODEX_Projects\OpenNR-VR\out\native_teacher_resolution_renderer_contract_20260912\scale050\teacher_eye0.rgba"
        ),
    )
    parser.add_argument(
        "--native-work-eye1",
        type=Path,
        default=Path(
            r"D:\.CODEX_Projects\OpenNR-VR\out\native_teacher_resolution_renderer_contract_20260912\scale050\teacher_eye1.rgba"
        ),
    )
    parser.add_argument("--warmup", type=int, default=40)
    parser.add_argument("--iterations", type=int, default=120)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(r"C:\OpenNR\native_residual_compositor_stereo_bench_scale050_20260912.json"),
    )
    args = parser.parse_args()

    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is unavailable")

    full = [
        read_rgba8(args.full_input_eye0, FULL_WIDTH, FULL_HEIGHT).cuda().half(),
        read_rgba8(args.full_input_eye1, FULL_WIDTH, FULL_HEIGHT).cuda().half(),
    ]
    work_input = [
        read_rgba8(args.work_input_eye0, args.work_width, args.work_height).cuda().half(),
        read_rgba8(args.work_input_eye1, args.work_width, args.work_height).cuda().half(),
    ]
    native_work = [
        read_rgba8(args.native_work_eye0, args.work_width, args.work_height).cuda().half(),
        read_rgba8(args.native_work_eye1, args.work_width, args.work_height).cuda().half(),
    ]
    output = [torch.empty_like(full[0]), torch.empty_like(full[1])]

    def compose() -> None:
        for eye in range(2):
            residual = (native_work[eye] - work_input[eye]) * args.residual_strength
            upsampled = F.interpolate(
                residual,
                size=(FULL_HEIGHT, FULL_WIDTH),
                mode="bilinear",
                align_corners=False,
            )
            torch.add(full[eye], upsampled, out=output[eye])
            output[eye].clamp_(0.0, 1.0)

    def downsample() -> None:
        for eye in range(2):
            F.interpolate(
                full[eye],
                size=(args.work_height, args.work_width),
                mode="bilinear",
                align_corners=False,
            )

    compose_graph = torch.cuda.CUDAGraph()
    capture_stream = torch.cuda.Stream()
    with torch.cuda.stream(capture_stream):
        compose()
        capture_stream.synchronize()
        compose_graph.capture_begin()
        compose()
        compose_graph.capture_end()
    capture_stream.synchronize()
    torch.cuda.synchronize()

    downsample_graph = torch.cuda.CUDAGraph()
    downsample_stream = torch.cuda.Stream()
    with torch.cuda.stream(downsample_stream):
        downsample()
        downsample_stream.synchronize()
        downsample_graph.capture_begin()
        downsample()
        downsample_graph.capture_end()
    downsample_stream.synchronize()
    torch.cuda.synchronize()

    def graph_compose() -> None:
        compose_graph.replay()

    def graph_downsample() -> None:
        downsample_graph.replay()

    result = {
        "device": torch.cuda.get_device_name(0),
        "torch": torch.__version__,
        "cuda": torch.version.cuda,
        "eyes": 2,
        "shape": {
            "full": [FULL_HEIGHT, FULL_WIDTH],
            "work": [args.work_height, args.work_width],
            "channels": 3,
            "dtype": "float16",
        },
        "warmup": args.warmup,
        "iterations": args.iterations,
        "eager_composite_with_clamp": benchmark(compose, args.warmup, args.iterations),
        "cuda_graph_composite_with_clamp": benchmark(graph_compose, args.warmup, args.iterations),
        "eager_color_downsample": benchmark(downsample, args.warmup, args.iterations),
        "cuda_graph_color_downsample": benchmark(graph_downsample, args.warmup, args.iterations),
        "finite": bool(all(torch.isfinite(item).all().item() for item in output)),
        "output_ranges": [[float(item.min().item()), float(item.max().item())] for item in output],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
