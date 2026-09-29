"""Evaluate a native internal-resolution curve with a full-resolution residual resolve.

The native resolution study stores Feature 18 input/output pairs at several
internal model resolutions for one retained Skyrim frame.  This tool does not
call a DLL.  It replays those saved results against the full-resolution native
teacher in two offline ways:

* direct: bilinear-upsample the reduced native output;
* matched residual: keep the full-resolution input and add an upsampled
  ``reduced_output - reduced_input`` residual.

The second branch is the composition pattern used by several public DLSS-NR
cost-scaling experiments.  It is an offline structural study, not a runtime or
VR acceptance test.  The stored native timings are copied from the registered
resolution-only study; resolve timings measure only this PyTorch composition.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import time
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as F


DEFAULT_STUDY = Path(
    r"D:\.CODEX_Projects\OpenNR-VR\out\native_teacher_resolution_study_20260912"
)
DEFAULT_SEQUENCE = Path(
    r"C:\OpenNR_Captures_FullEyeTemporalStateTranche_20260910"
    r"\seq-1789063628889-1"
)
DEFAULT_SCALES = (100, 90, 85, 75, 50, 33)
FULL_WIDTH = 2496
FULL_HEIGHT = 2688


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_rgba8(path: Path, width: int, height: int) -> np.ndarray:
    payload = path.read_bytes()
    expected = width * height * 4
    if len(payload) != expected:
        raise ValueError(f"{path} has {len(payload)} bytes; expected {expected}")
    return np.frombuffer(payload, dtype=np.uint8).reshape(height, width, 4)[:, :, :3].copy()


def read_rgba8_rgb_tensor(path: Path, width: int, height: int) -> torch.Tensor:
    array = read_rgba8(path, width, height).astype(np.float32) / 255.0
    return torch.from_numpy(array.transpose(2, 0, 1)).unsqueeze(0)


def metric(pred: np.ndarray, target: np.ndarray, source: np.ndarray) -> dict[str, float]:
    error = pred.astype(np.float32) - target.astype(np.float32)
    source_error = source.astype(np.float32) - target.astype(np.float32)
    mae = float(np.mean(np.abs(error)))
    rmse = float(np.sqrt(np.mean(np.square(error))))
    identity_mae = float(np.mean(np.abs(source_error)))
    return {
        "mae": mae,
        "rmse": rmse,
        "psnr_db": float(20.0 * math.log10(1.0 / max(rmse, 1e-12))),
        "identity_mae": identity_mae,
        "improvement_vs_identity_mae": identity_mae - mae,
        "better_fraction_pixels": float(
            np.mean(np.abs(error) < np.abs(source_error))
        ),
        "output_min": float(np.min(pred)),
        "output_max": float(np.max(pred)),
        "finite": int(bool(np.isfinite(pred).all())),
    }


def scaled_dimension(value: int, percent: int) -> int:
    return max(1, (value * percent + 50) // 100)


def as_hwc(tensor: torch.Tensor) -> np.ndarray:
    return tensor.detach().float().cpu()[0].permute(1, 2, 0).numpy()


def make_preview(
    output: Path,
    images: list[tuple[str, np.ndarray]],
    *,
    max_panel_width: int = 480,
) -> None:
    from PIL import Image, ImageDraw

    panel_images: list[tuple[str, Image.Image]] = []
    for label, array in images:
        rgb = np.clip(np.rint(array * 255.0), 0, 255).astype(np.uint8)
        image = Image.fromarray(rgb, mode="RGB")
        scale = min(1.0, max_panel_width / image.width)
        image = image.resize(
            (max(1, int(round(image.width * scale))), max(1, int(round(image.height * scale)))),
            Image.Resampling.BILINEAR,
        )
        panel_images.append((label, image))
    label_height = 30
    panel_width = max(image.width for _, image in panel_images)
    panel_height = max(image.height for _, image in panel_images)
    canvas = Image.new(
        "RGB",
        (panel_width * len(panel_images), panel_height + label_height),
        (24, 24, 24),
    )
    draw = ImageDraw.Draw(canvas)
    for index, (label, image) in enumerate(panel_images):
        left = index * panel_width
        draw.text((left + 8, 7), label, fill=(240, 240, 240))
        canvas.paste(image, (left, label_height))
    output.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output, quality=94)


def time_resolve(
    full_source: torch.Tensor,
    small_input: torch.Tensor,
    small_output: torch.Tensor,
    *,
    warmup: int,
    iterations: int,
) -> dict[str, float | int | None]:
    if full_source.device.type != "cuda":
        started = time.perf_counter()
        for _ in range(warmup):
            edit = F.interpolate(
                small_output - small_input,
                size=full_source.shape[-2:],
                mode="bilinear",
                align_corners=False,
            )
            _ = (full_source + edit).clamp(0.0, 1.0)
        values = []
        for _ in range(iterations):
            begin = time.perf_counter()
            edit = F.interpolate(
                small_output - small_input,
                size=full_source.shape[-2:],
                mode="bilinear",
                align_corners=False,
            )
            _ = (full_source + edit).clamp(0.0, 1.0)
            values.append((time.perf_counter() - begin) * 1000.0)
        array = np.asarray(values, dtype=np.float64)
        return {
            "median_ms": float(np.percentile(array, 50)),
            "p95_ms": float(np.percentile(array, 95)),
            "samples": len(values),
            "scope": "offline residual upsample + full-resolution add/clamp only",
        }

    for _ in range(warmup):
        edit = F.interpolate(
            small_output - small_input,
            size=full_source.shape[-2:],
            mode="bilinear",
            align_corners=False,
        )
        _ = (full_source + edit).clamp(0.0, 1.0)
    torch.cuda.synchronize(full_source.device)
    values: list[float] = []
    for _ in range(iterations):
        start = torch.cuda.Event(enable_timing=True)
        end = torch.cuda.Event(enable_timing=True)
        start.record()
        edit = F.interpolate(
            small_output - small_input,
            size=full_source.shape[-2:],
            mode="bilinear",
            align_corners=False,
        )
        _ = (full_source + edit).clamp(0.0, 1.0)
        end.record()
        end.synchronize()
        values.append(float(start.elapsed_time(end)))
    array = np.asarray(values, dtype=np.float64)
    return {
        "median_ms": float(np.percentile(array, 50)),
        "p95_ms": float(np.percentile(array, 95)),
        "p99_ms": float(np.percentile(array, 99)),
        "min_ms": float(np.min(array)),
        "max_ms": float(np.max(array)),
        "samples": len(values),
        "scope": "offline residual upsample + full-resolution add/clamp only",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--study-root", type=Path, default=DEFAULT_STUDY)
    parser.add_argument("--sequence", type=Path, default=DEFAULT_SEQUENCE)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--scales", type=int, nargs="+", default=list(DEFAULT_SCALES))
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--warmup", type=int, default=10)
    parser.add_argument("--iterations", type=int, default=40)
    parser.add_argument("--save-previews", action="store_true")
    args = parser.parse_args()

    if args.output.exists() and any(args.output.iterdir()):
        raise FileExistsError(f"refusing to use non-empty output directory: {args.output}")
    if any(scale not in DEFAULT_SCALES for scale in args.scales):
        raise ValueError(f"supported scales are {DEFAULT_SCALES}")
    if args.warmup < 0 or args.iterations < 2:
        raise ValueError("warmup must be non-negative and iterations must be at least 2")
    args.output.mkdir(parents=True, exist_ok=True)

    device = torch.device(args.device)
    if device.type == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("CUDA was requested but is unavailable")

    summary_path = args.study_root / "summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary_by_scale = {int(item["scale_percent"]): item for item in summary["scales"]}
    frame = args.sequence / "frames" / "frame_00000001"
    full_input_paths = [frame / f"input_eye{eye}_full.raw.bin" for eye in range(2)]
    full_teacher_paths = [frame / f"teacher_eye{eye}_full.raw.bin" for eye in range(2)]
    for path in [summary_path, *full_input_paths, *full_teacher_paths]:
        if not path.is_file():
            raise FileNotFoundError(path)

    full_inputs = [
        read_rgba8_rgb_tensor(path, FULL_WIDTH, FULL_HEIGHT).to(device)
        for path in full_input_paths
    ]
    full_teachers = [
        read_rgba8_rgb_tensor(path, FULL_WIDTH, FULL_HEIGHT).to(device)
        for path in full_teacher_paths
    ]

    result: dict[str, object] = {
        "schema": "opennr-native-scale-residual-curve-v1",
        "study": "native_feature18_resolution_only",
        "scope": (
            "Stored native Feature 18 outputs are compared to the original full-"
            "resolution native teacher. Direct upsample and matched residual are"
            "offline composition hypotheses; no DLL is called by this tool."
        ),
        "study_root": str(args.study_root.resolve()),
        "study_summary_sha256": sha256(summary_path),
        "sequence": str(args.sequence.resolve()),
        "frame": 1,
        "full_shape": [FULL_WIDTH, FULL_HEIGHT],
        "scales": list(args.scales),
        "device": str(device),
        "gpu": torch.cuda.get_device_name(device) if device.type == "cuda" else None,
        "native_study_dll_sha256": summary.get("dll_sha256"),
        "native_study_driver_core_sha256": summary.get("driver_core_sha256"),
        "eyes": [],
        "scale_aggregate": [],
        "test_used_for_tuning": False,
        "live_runtime_tested": False,
        "promotion": False,
    }

    eye_records: list[dict[str, object]] = []
    for eye in range(2):
        full_source = full_inputs[eye]
        full_target = full_teachers[eye]
        full_source_np = as_hwc(full_source)
        full_target_np = as_hwc(full_target)
        eye_scales: list[dict[str, object]] = []
        for scale in args.scales:
            width = scaled_dimension(FULL_WIDTH, scale)
            height = scaled_dimension(FULL_HEIGHT, scale)
            if scale == 100:
                small_input = full_source
                small_output = full_target
                input_path = full_input_paths[eye]
                output_path = full_teacher_paths[eye]
            else:
                scale_dir = args.study_root / f"scale{scale:03d}"
                input_path = scale_dir / f"input_eye{eye}.rgba"
                output_path = scale_dir / f"teacher_eye{eye}.rgba"
                small_input = read_rgba8_rgb_tensor(input_path, width, height).to(device)
                small_output = read_rgba8_rgb_tensor(output_path, width, height).to(device)

            direct = F.interpolate(
                small_output,
                size=(FULL_HEIGHT, FULL_WIDTH),
                mode="bilinear",
                align_corners=False,
            )
            residual = F.interpolate(
                small_output - small_input,
                size=(FULL_HEIGHT, FULL_WIDTH),
                mode="bilinear",
                align_corners=False,
            )
            matched = (full_source + residual).clamp(0.0, 1.0)
            direct_np = as_hwc(direct)
            matched_np = as_hwc(matched)
            direct_metrics = metric(direct_np, full_target_np, full_source_np)
            matched_metrics = metric(matched_np, full_target_np, full_source_np)
            record: dict[str, object] = {
                "eye": eye,
                "scale_percent": scale,
                "network_dimensions": [width, height],
                "area_fraction": (scale / 100.0) ** 2,
                "input_path": str(input_path),
                "output_path": str(output_path),
                "stored_input_sha256": sha256(input_path),
                "stored_output_sha256": sha256(output_path),
                "native_timing": summary_by_scale[scale]["wall_pair_ms"],
                "native_gpu_timing": summary_by_scale[scale]["gpu_pair_ms"],
                "direct_upsample": direct_metrics,
                "matched_residual": matched_metrics,
                "resolve_timing": time_resolve(
                    full_source,
                    small_input,
                    small_output,
                    warmup=args.warmup,
                    iterations=args.iterations,
                ),
            }
            eye_scales.append(record)

            if args.save_previews and eye == 0 and scale in (100, 75, 50, 33):
                preview_dir = args.output / "previews"
                make_preview(
                    preview_dir / f"eye0_scale{scale:03d}.jpg",
                    [
                        ("Full input", full_source_np),
                        ("Full native teacher", full_target_np),
                        (f"Direct {scale}%", direct_np),
                        (f"Residual {scale}%", matched_np),
                    ],
                )
                make_preview(
                    preview_dir / f"eye0_scale{scale:03d}_diff_x8.jpg",
                    [
                        ("Input-teacher", np.clip(np.abs(full_source_np - full_target_np) * 8.0, 0.0, 1.0)),
                        ("Direct-teacher", np.clip(np.abs(direct_np - full_target_np) * 8.0, 0.0, 1.0)),
                        ("Residual-teacher", np.clip(np.abs(matched_np - full_target_np) * 8.0, 0.0, 1.0)),
                    ],
                )

            if scale != 100:
                del small_input, small_output
            del direct, residual, matched
        eye_records.append({"eye": eye, "scales": eye_scales})

    result["eyes"] = eye_records
    aggregate: list[dict[str, object]] = []
    for scale in args.scales:
        records = [
            item
            for eye in eye_records
            for item in eye["scales"]
            if item["scale_percent"] == scale
        ]
        direct = [item["direct_upsample"] for item in records]
        matched = [item["matched_residual"] for item in records]
        native = [item["native_timing"] for item in records]
        native_gpu = [item["native_gpu_timing"] for item in records]
        resolve = [item["resolve_timing"] for item in records]
        aggregate.append(
            {
                "scale_percent": scale,
                "network_dimensions": records[0]["network_dimensions"],
                "area_fraction": records[0]["area_fraction"],
                "native_wall_pair_median_ms_mean_eyes": float(np.mean([x["median"] for x in native])),
                "native_gpu_pair_median_ms_mean_eyes": float(np.mean([x["median"] for x in native_gpu])),
                "resolve_median_ms_mean_eyes": float(np.mean([x["median_ms"] for x in resolve])),
                "direct_upsample_mae_mean_eyes": float(np.mean([x["mae"] for x in direct])),
                "matched_residual_mae_mean_eyes": float(np.mean([x["mae"] for x in matched])),
                "direct_upsample_psnr_db_mean_eyes": float(np.mean([x["psnr_db"] for x in direct])),
                "matched_residual_psnr_db_mean_eyes": float(np.mean([x["psnr_db"] for x in matched])),
                "direct_improvement_vs_identity_mae_mean_eyes": float(
                    np.mean([x["improvement_vs_identity_mae"] for x in direct])
                ),
                "matched_improvement_vs_identity_mae_mean_eyes": float(
                    np.mean([x["improvement_vs_identity_mae"] for x in matched])
                ),
                "matched_minus_direct_mae": float(
                    np.mean([x["mae"] for x in matched]) - np.mean([x["mae"] for x in direct])
                ),
                "matched_better_than_direct_fraction_eyes": float(
                    np.mean([
                        x["mae"] < y["mae"]
                        for x, y in zip(matched, direct)
                    ])
                ),
            }
        )
    result["scale_aggregate"] = aggregate
    (args.output / "result.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"scale_aggregate": aggregate}, indent=2))
    print(f"result={args.output / 'result.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
