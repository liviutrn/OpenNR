"""Evaluate the public DLSS5 portable checkpoint on retained OpenNR full-eye captures.

This is an isolated research probe.  OpenNR's retained ``*.raw.bin`` files are
packed RGBA8, not the RGBA16F files used by the upstream helper, so the probe
normalizes the captured bytes to [0, 1] and compares in the same RGB8 code
domain.  It never loads or executes the repository's native DLL/CUBIN path.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

import numpy as np
import torch


def read_rgba8(path: Path, width: int, height: int) -> np.ndarray:
    values = np.fromfile(path, dtype=np.uint8)
    expected = width * height * 4
    if values.size != expected:
        raise ValueError(f"{path} has {values.size} bytes; expected {expected}")
    return values.reshape(height, width, 4)


def to_rgb_tensor(rgba: np.ndarray, device: torch.device, dtype: torch.dtype) -> torch.Tensor:
    rgb = np.ascontiguousarray(rgba[:, :, :3].transpose(2, 0, 1), dtype=np.float32) / 255.0
    return torch.from_numpy(rgb).unsqueeze(0).to(device=device, dtype=dtype)


def metrics(pred: np.ndarray, target: np.ndarray, source: np.ndarray) -> dict[str, float | int]:
    diff = np.abs(pred - target)
    source_diff = np.abs(source - target)
    rmse = float(np.sqrt(np.mean((pred - target) ** 2)))
    source_rmse = float(np.sqrt(np.mean((source - target) ** 2)))
    return {
        "mae": float(np.mean(diff)),
        "rmse": rmse,
        "psnr_db": float(20.0 * np.log10(1.0 / max(rmse, 1e-12))),
        "identity_mae": float(np.mean(source_diff)),
        "identity_rmse": source_rmse,
        "improvement_vs_identity_mae": float(np.mean(source_diff) - np.mean(diff)),
        "better_fraction_pixels": float(np.mean(diff < source_diff)),
        "changed_gt_1e-3_fraction": float(np.mean(diff > 1e-3)),
        "output_min": float(np.min(pred)),
        "output_max": float(np.max(pred)),
        "finite": int(bool(np.isfinite(pred).all())),
    }


def percentile(values: list[float], p: float) -> float:
    return float(np.percentile(np.asarray(values, dtype=np.float64), p))


def time_model(model: torch.nn.Module, image: torch.Tensor, warmup: int, iterations: int) -> dict[str, float | int]:
    if image.device.type != "cuda":
        started = time.perf_counter()
        with torch.inference_mode():
            for _ in range(warmup):
                output = model(image)
            for _ in range(iterations):
                output = model(image)
        elapsed = (time.perf_counter() - started) * 1000.0 / iterations
        return {"median_ms": float(elapsed), "p95_ms": float(elapsed), "samples": iterations}

    torch.cuda.synchronize(image.device)
    with torch.inference_mode():
        for _ in range(warmup):
            output = model(image)
    torch.cuda.synchronize(image.device)
    samples: list[float] = []
    for _ in range(iterations):
        start = torch.cuda.Event(enable_timing=True)
        end = torch.cuda.Event(enable_timing=True)
        start.record()
        with torch.inference_mode():
            output = model(image)
        end.record()
        end.synchronize()
        samples.append(float(start.elapsed_time(end)))
    return {
        "median_ms": percentile(samples, 50.0),
        "p95_ms": percentile(samples, 95.0),
        "p99_ms": percentile(samples, 99.0),
        "min_ms": float(min(samples)),
        "max_ms": float(max(samples)),
        "samples": len(samples),
    }


def save_png(path: Path, rgb: np.ndarray) -> None:
    try:
        from PIL import Image
    except ImportError as exc:  # pragma: no cover - environment diagnostic
        raise RuntimeError("Pillow is required only for --save-images") from exc
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(np.clip(np.rint(rgb * 255.0), 0, 255).astype(np.uint8), mode="RGB").save(path)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True, help="isolated public repository clone")
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--capture-root", type=Path, required=True)
    parser.add_argument("--sequence", required=True)
    parser.add_argument("--frames", default="13", help="comma-separated frame numbers")
    parser.add_argument("--eyes", default="0,1", help="comma-separated eye numbers")
    parser.add_argument("--width", type=int, required=True)
    parser.add_argument("--height", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--warmup", type=int, default=5)
    parser.add_argument("--iterations", type=int, default=20)
    parser.add_argument("--save-images", action="store_true")
    args = parser.parse_args()

    repo_src = args.repo / "src"
    sys.path.insert(0, str(repo_src))
    from dlss5.portable import DLSS5PortableModel, PORTABLE_FORMAT

    args.output.mkdir(parents=True, exist_ok=True)
    device = torch.device(args.device)
    if device.type == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("CUDA was requested but is unavailable")

    checkpoint = torch.load(args.checkpoint, map_location="cpu", weights_only=True)
    if checkpoint.get("format") != PORTABLE_FORMAT:
        raise ValueError(f"unsupported checkpoint format: {checkpoint.get('format')!r}")
    model_kwargs = checkpoint["model_kwargs"]
    model = DLSS5PortableModel(**model_kwargs)
    model.load_state_dict(checkpoint["state_dict"], strict=True)
    model.eval().to(device)

    frames = [int(value) for value in args.frames.split(",") if value.strip()]
    eyes = [int(value) for value in args.eyes.split(",") if value.strip()]
    results: dict[str, object] = {
        "repo": str(args.repo),
        "checkpoint": str(args.checkpoint),
        "checkpoint_sha256": sha256(args.checkpoint),
        "checkpoint_format": checkpoint.get("format"),
        "checkpoint_metadata": checkpoint.get("metadata", {}),
        "model_kwargs": model_kwargs,
        "capture_root": str(args.capture_root),
        "sequence": args.sequence,
        "frames": frames,
        "eyes": eyes,
        "shape": {"width": args.width, "height": args.height},
        "raw_contract": "OpenNR packed RGBA8; RGB normalized by 255; compare in RGB8 code domain",
        "device": str(device),
        "gpu": torch.cuda.get_device_name(device) if device.type == "cuda" else None,
        "precision_runs": {},
        "samples": [],
    }

    frame_records: list[dict[str, object]] = []
    for frame_number in frames:
        frame_dir = args.capture_root / args.sequence / "frames" / f"frame_{frame_number:08d}"
        for eye in eyes:
            input_path = frame_dir / f"input_eye{eye}_full.raw.bin"
            teacher_path = frame_dir / f"teacher_eye{eye}_full.raw.bin"
            source_rgba = read_rgba8(input_path, args.width, args.height)
            teacher_rgba = read_rgba8(teacher_path, args.width, args.height)
            source = source_rgba[:, :, :3].astype(np.float32) / 255.0
            teacher = teacher_rgba[:, :, :3].astype(np.float32) / 255.0
            image = to_rgb_tensor(source_rgba, device, torch.float32)
            with torch.inference_mode():
                output_fp32 = model(image).detach().float().cpu()[0].permute(1, 2, 0).numpy()
            output_fp32 = np.clip(output_fp32, 0.0, 1.0)
            record: dict[str, object] = {
                "frame": frame_number,
                "eye": eye,
                "input": str(input_path),
                "teacher": str(teacher_path),
                "fp32_metrics": metrics(output_fp32, teacher, source),
            }
            if args.save_images:
                stem = args.output / f"frame_{frame_number:08d}_eye{eye}"
                save_png(stem.with_name(stem.name + "_input.png"), source)
                save_png(stem.with_name(stem.name + "_teacher.png"), teacher)
                save_png(stem.with_name(stem.name + "_portable_fp32.png"), output_fp32)
                save_png(stem.with_name(stem.name + "_absdiff_x8.png"), np.clip(np.abs(output_fp32 - teacher) * 8.0, 0.0, 1.0))
                record["images"] = {
                    "input": str(stem.with_name(stem.name + "_input.png")),
                    "teacher": str(stem.with_name(stem.name + "_teacher.png")),
                    "portable_fp32": str(stem.with_name(stem.name + "_portable_fp32.png")),
                    "absdiff_x8": str(stem.with_name(stem.name + "_absdiff_x8.png")),
                }
            frame_records.append(record)

    # Time one representative retained eye with the tensor already resident on the GPU.
    representative = frame_records[0]
    rep_frame = int(representative["frame"])
    rep_eye = int(representative["eye"])
    rep_dir = args.capture_root / args.sequence / "frames" / f"frame_{rep_frame:08d}"
    rep_rgba = read_rgba8(rep_dir / f"input_eye{rep_eye}_full.raw.bin", args.width, args.height)
    for precision, dtype in (("fp32", torch.float32), ("fp16", torch.float16)):
        if precision == "fp16":
            model = model.half()
        else:
            model = model.float()
        image = to_rgb_tensor(rep_rgba, device, dtype)
        timing = time_model(model, image, args.warmup, args.iterations)
        results["precision_runs"][precision] = {
            "representative_frame": rep_frame,
            "representative_eye": rep_eye,
            "input_already_on_device": True,
            "timing": timing,
        }

    results["samples"] = frame_records
    sample_metrics = [record["fp32_metrics"] for record in frame_records]
    results["aggregate_fp32"] = {
        "sample_count": len(sample_metrics),
        "identity_mae_mean": float(np.mean([item["identity_mae"] for item in sample_metrics])),
        "portable_mae_mean": float(np.mean([item["mae"] for item in sample_metrics])),
        "portable_improvement_mean": float(np.mean([item["improvement_vs_identity_mae"] for item in sample_metrics])),
        "portable_better_samples": int(sum(item["improvement_vs_identity_mae"] > 0 for item in sample_metrics)),
        "finite_samples": int(sum(item["finite"] for item in sample_metrics)),
    }
    (args.output / "result.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(json.dumps(results["aggregate_fp32"], indent=2))
    print(json.dumps(results["precision_runs"], indent=2))
    print(f"result={args.output / 'result.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
