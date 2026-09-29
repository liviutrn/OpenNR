"""Benchmark an offline learned residual resolver on resident full-eye tensors."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as F

from scale_resolve_student import GuidedScaleResolveStudent, ScaleResolveConfig, ScaleResolveStudent


FULL_WIDTH = 2496
FULL_HEIGHT = 2688
GUIDE_WIDTH = 1664
GUIDE_HEIGHT = 1792


def read_rgb8(path: Path, width: int, height: int) -> torch.Tensor:
    payload = path.read_bytes()
    expected = width * height * 4
    if len(payload) != expected:
        raise ValueError(f"{path} has {len(payload)} bytes; expected {expected}")
    array = np.frombuffer(payload, dtype=np.uint8).reshape(height, width, 4)[:, :, :3].copy()
    return torch.from_numpy(array.transpose(2, 0, 1)).float().unsqueeze(0) / 255.0


def read_guides(frame_dir: Path, eye: int, device: torch.device, dtype: torch.dtype) -> torch.Tensor:
    depth = np.fromfile(frame_dir / f"depth_eye{eye}_full.raw.bin", dtype="<f4")
    motion = np.fromfile(frame_dir / f"motion_vectors_eye{eye}_full.raw.bin", dtype="<f2")
    depth = depth.reshape(GUIDE_HEIGHT, GUIDE_WIDTH, 1)
    motion = motion.reshape(GUIDE_HEIGHT, GUIDE_WIDTH, 2).astype(np.float32)
    depth = np.nan_to_num(depth, nan=0.0, posinf=0.0, neginf=0.0).clip(0.0, 1.0)
    motion = np.nan_to_num(motion, nan=0.0, posinf=0.0, neginf=0.0).clip(-128.0, 128.0) / 128.0
    guide = torch.from_numpy(np.concatenate((depth, motion), axis=2).transpose(2, 0, 1)).unsqueeze(0)
    return F.interpolate(
        guide.to(device=device, dtype=dtype),
        size=(FULL_HEIGHT, FULL_WIDTH),
        mode="bilinear",
        align_corners=False,
    )


def percentiles(values: list[float]) -> dict[str, float]:
    array = np.asarray(values, dtype=np.float64)
    return {
        "median_ms": float(np.percentile(array, 50)),
        "p95_ms": float(np.percentile(array, 95)),
        "min_ms": float(np.min(array)),
        "max_ms": float(np.max(array)),
    }


def time_serial(model, inputs, guided: bool, warmup: int, iterations: int) -> dict[str, float]:
    with torch.inference_mode():
        for _ in range(warmup):
            for values in inputs:
                if guided:
                    model(values[0], values[1], values[2])
                else:
                    model(values[0], values[1])
    torch.cuda.synchronize()
    values: list[float] = []
    with torch.inference_mode():
        for _ in range(iterations):
            start = torch.cuda.Event(enable_timing=True)
            end = torch.cuda.Event(enable_timing=True)
            start.record()
            for item in inputs:
                if guided:
                    model(item[0], item[1], item[2])
                else:
                    model(item[0], item[1])
            end.record()
            end.synchronize()
            values.append(float(start.elapsed_time(end)))
    return percentiles(values)


def time_concurrent(model, inputs, guided: bool, warmup: int, iterations: int) -> dict[str, float]:
    streams = [torch.cuda.Stream(), torch.cuda.Stream()]

    def run() -> None:
        for stream, item in zip(streams, inputs):
            with torch.cuda.stream(stream):
                if guided:
                    model(item[0], item[1], item[2])
                else:
                    model(item[0], item[1])

    with torch.inference_mode():
        for _ in range(warmup):
            run()
    torch.cuda.synchronize()
    values: list[float] = []
    with torch.inference_mode():
        for _ in range(iterations):
            start = torch.cuda.Event(enable_timing=True)
            end = torch.cuda.Event(enable_timing=True)
            done = [torch.cuda.Event() for _ in streams]
            start.record()
            run()
            for stream, event in zip(streams, done):
                stream.record_event(event)
            for event in done:
                torch.cuda.current_stream().wait_event(event)
            end.record()
            end.synchronize()
            values.append(float(start.elapsed_time(end)))
    return percentiles(values)


def time_naive(inputs, warmup: int, iterations: int) -> dict[str, float]:
    with torch.inference_mode():
        for _ in range(warmup):
            for rgb, edit, _ in inputs:
                _ = (rgb + edit).clamp(0.0, 1.0)
    torch.cuda.synchronize()
    values: list[float] = []
    with torch.inference_mode():
        for _ in range(iterations):
            start = torch.cuda.Event(enable_timing=True)
            end = torch.cuda.Event(enable_timing=True)
            start.record()
            for rgb, edit, _ in inputs:
                _ = (rgb + edit).clamp(0.0, 1.0)
            end.record()
            end.synchronize()
            values.append(float(start.elapsed_time(end)))
    return percentiles(values)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--replay-root", type=Path, required=True)
    parser.add_argument("--frame", type=int, default=1)
    parser.add_argument("--warmup", type=int, default=10)
    parser.add_argument("--iterations", type=int, default=40)
    parser.add_argument("--device", default="cuda")
    args = parser.parse_args()
    device = torch.device(args.device)
    if device.type != "cuda" or not torch.cuda.is_available():
        raise RuntimeError("CUDA is required")
    # All measurements use one fixed full-eye shape.  Let cuDNN select the
    # fastest algorithm for that shape before the timed region.
    torch.backends.cudnn.benchmark = True
    checkpoint = torch.load(args.checkpoint, map_location="cpu", weights_only=False)
    config = ScaleResolveConfig(**checkpoint["config"])
    guided = bool(checkpoint.get("guided", False))
    model = (GuidedScaleResolveStudent(config) if guided else ScaleResolveStudent(config)).to(device).eval()
    model.load_state_dict(checkpoint["model"], strict=True)
    replay_root = args.replay_root.resolve()
    manifest = json.loads((replay_root / "input_manifest.json").read_text(encoding="utf-8"))
    small_width, small_height = (int(value) for value in manifest["network_dimensions"])
    frame_dir = Path(manifest["sequence"]) / "frames" / f"frame_{args.frame:08d}"
    inputs = []
    for eye in range(2):
        rgb = read_rgb8(frame_dir / f"input_eye{eye}_full.raw.bin", FULL_WIDTH, FULL_HEIGHT).to(device)
        small_input = read_rgb8(replay_root / f"frame_{args.frame:08d}" / f"input_eye{eye}.rgba", small_width, small_height).to(device)
        small_output = read_rgb8(replay_root / f"frame_{args.frame:08d}" / f"teacher_eye{eye}.rgba", small_width, small_height).to(device)
        edit = F.interpolate(small_output - small_input, size=(FULL_HEIGHT, FULL_WIDTH), mode="bilinear", align_corners=False)
        guides = read_guides(frame_dir, eye, device, torch.float32) if guided else None
        inputs.append((rgb, edit, guides))

    result = {
        "schema": "opennr-scale-resolve-benchmark-v1",
        "checkpoint": str(args.checkpoint.resolve()),
        "checkpoint_sha256": checkpoint.get("checkpoint_sha256"),
        "guided": guided,
        "device": torch.cuda.get_device_name(device),
        "shape": [FULL_WIDTH, FULL_HEIGHT],
        "scale_percent": int(manifest["scale_percent"]),
        "scope": "resident tensors; full-resolution resolver only; no input conversion, copies, native pass or compositor",
        "naive_resolve_serial_stereo": time_naive(inputs, args.warmup, args.iterations),
        "learned_resolve_serial_stereo_fp32": time_serial(model, inputs, guided, args.warmup, args.iterations),
        "learned_resolve_concurrent_stereo_fp32": time_concurrent(model, inputs, guided, args.warmup, args.iterations),
    }
    model.half()
    fp16_inputs = [(rgb.half(), edit.half(), guides.half() if guides is not None else None) for rgb, edit, guides in inputs]
    result["learned_resolve_serial_stereo_fp16"] = time_serial(model, fp16_inputs, guided, args.warmup, args.iterations)
    result["learned_resolve_concurrent_stereo_fp16"] = time_concurrent(model, fp16_inputs, guided, args.warmup, args.iterations)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
