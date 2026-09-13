"""Render and score the native 90/75/65/50/33% residual ladder."""

from __future__ import annotations

import csv
import json
import math
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as F
from PIL import Image, ImageDraw


FULL_WIDTH = 2496
FULL_HEIGHT = 2688
CAPTURE = Path(
    r"C:\OpenNR_Captures_FullEyeTemporalStateTranche_20260910"
    r"\seq-1789063628889-1\frames\frame_00000001"
)
STUDY = Path(
    r"D:\.CODEX_Projects\OpenNR-VR\out"
    r"\native_teacher_resolution_renderer_contract_20260912"
)
STUDY_SUMMARY = STUDY / "summary.json"
STUDY_65 = Path(r"C:\OpenNR\NativeResolutionStudy65_20260912")
OUTPUT = Path(r"C:\OpenNR\native_residual_scale65_comparison_20260912")
SCALES = (90, 75, 65, 50, 33)


def read_rgba8(path: Path, width: int, height: int) -> torch.Tensor:
    payload = path.read_bytes()
    expected = width * height * 4
    if len(payload) != expected:
        raise ValueError(f"{path} has {len(payload)} bytes; expected {expected}")
    array = np.frombuffer(payload, dtype=np.uint8).reshape(height, width, 4)
    rgb = np.ascontiguousarray(array[:, :, :3].transpose(2, 0, 1))
    return torch.from_numpy(rgb).float().unsqueeze(0).div_(255.0)


def scaled_dimension(value: int, percent: int) -> int:
    return max(1, (value * percent + 50) // 100)


def to_hwc(tensor: torch.Tensor) -> np.ndarray:
    return tensor.detach().float().cpu()[0].permute(1, 2, 0).numpy()


def image_from_tensor(tensor: torch.Tensor) -> Image.Image:
    array = np.clip(np.rint(to_hwc(tensor) * 255.0), 0, 255).astype(np.uint8)
    return Image.fromarray(array, mode="RGB")


def panel(images: list[tuple[str, Image.Image]], path: Path, crop=None) -> None:
    display_width = 400
    caption_height = 32
    prepared: list[tuple[str, Image.Image]] = []
    for label, image in images:
        if crop is not None:
            image = image.crop(crop)
        ratio = display_width / image.width
        image = image.resize(
            (display_width, max(1, round(image.height * ratio))),
            Image.Resampling.LANCZOS,
        )
        prepared.append((label, image))
    canvas = Image.new(
        "RGB",
        (display_width * len(prepared), caption_height + max(i.height for _, i in prepared)),
        (20, 20, 20),
    )
    draw = ImageDraw.Draw(canvas)
    for index, (label, image) in enumerate(prepared):
        left = index * display_width
        draw.rectangle((left, 0, left + display_width - 1, caption_height - 1), fill=(20, 20, 20))
        draw.text((left + 8, 8), label, fill=(245, 245, 245))
        canvas.paste(image, (left, caption_height))
    path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(path, quality=94, subsampling=0)


def metrics(pred: torch.Tensor, target: torch.Tensor, source: torch.Tensor) -> dict[str, float | int]:
    error = (pred - target).float()
    source_error = (source - target).float()
    mae = float(error.abs().mean().item())
    rmse = float(error.square().mean().sqrt().item())
    identity_mae = float(source_error.abs().mean().item())
    return {
        "mae_vs_full_native": mae,
        "rmse_vs_full_native": rmse,
        "psnr_db_vs_full_native": 20.0 * math.log10(1.0 / max(rmse, 1e-12)),
        "raw_identity_mae": identity_mae,
        "improvement_vs_raw_mae": identity_mae - mae,
        "better_fraction_pixels_vs_raw": float((error.abs() < source_error.abs()).float().mean().item()),
        "residual_energy_vs_raw": float((pred - source).float().abs().mean().item()),
        "finite": int(bool(torch.isfinite(pred).all().item())),
    }


def timing(path: Path) -> dict[str, float | int]:
    with path.open(newline="", encoding="utf-8") as handle:
        rows = [row for row in csv.DictReader(handle) if row.get("warm") == "1"]
    values_gpu = np.asarray([float(row["pair_gpu_ms"]) for row in rows], dtype=np.float64)
    values_wall = np.asarray([float(row["pair_wall_ms"]) for row in rows], dtype=np.float64)
    return {
        "samples": int(values_gpu.size),
        "gpu_median_ms": float(np.percentile(values_gpu, 50)),
        "gpu_p95_ms": float(np.percentile(values_gpu, 95)),
        "wall_median_ms": float(np.percentile(values_wall, 50)),
        "wall_p95_ms": float(np.percentile(values_wall, 95)),
    }


def main() -> None:
    full_input = read_rgba8(CAPTURE / "input_eye0_full.raw.bin", FULL_WIDTH, FULL_HEIGHT)
    full_teacher = read_rgba8(CAPTURE / "teacher_eye0_full.raw.bin", FULL_WIDTH, FULL_HEIGHT)
    rendered: list[tuple[str, torch.Tensor]] = [("Raw input", full_input)]
    records: list[dict[str, object]] = []
    native_summary = json.loads(STUDY_SUMMARY.read_text(encoding="utf-8"))
    summary_by_scale = {int(item["scale_percent"]): item for item in native_summary["scales"]}

    for scale in SCALES:
        width = scaled_dimension(FULL_WIDTH, scale)
        height = scaled_dimension(FULL_HEIGHT, scale)
        if scale == 65:
            root = STUDY_65
        else:
            root = STUDY / f"scale{scale:03d}"
        small_input = read_rgba8(root / "input_eye0.rgba", width, height)
        small_output = read_rgba8(root / "teacher_eye0.rgba", width, height)
        residual = F.interpolate(
            small_output - small_input,
            size=(FULL_HEIGHT, FULL_WIDTH),
            mode="bilinear",
            align_corners=False,
        )
        composite = (full_input + residual).clamp(0.0, 1.0)
        rendered.append((f"Residual {scale}%", composite))
        record: dict[str, object] = {
            "scale_percent": scale,
            "network_dimensions": [width, height],
            "area_fraction": (scale / 100.0) ** 2,
            "metrics": metrics(composite, full_teacher, full_input),
            "native_timing": (
                (
                    {
                        "median": timing(root / "timings.csv")["wall_median_ms"],
                        "p95": timing(root / "timings.csv")["wall_p95_ms"],
                        "count": timing(root / "timings.csv")["samples"],
                    }
                    if scale == 65
                    else summary_by_scale[scale]["wall_pair_ms"]
                )
            ),
            "native_gpu_timing": (
                (
                    {
                        "median": timing(root / "timings.csv")["gpu_median_ms"],
                        "p95": timing(root / "timings.csv")["gpu_p95_ms"],
                        "count": timing(root / "timings.csv")["samples"],
                    }
                    if scale == 65
                    else summary_by_scale[scale]["gpu_pair_ms"]
                )
            ),
            "source": str(root),
        }
        records.append(record)

    rendered.append(("Full native teacher", full_teacher))
    OUTPUT.mkdir(parents=True, exist_ok=True)
    panel_images = [(label, image_from_tensor(tensor)) for label, tensor in rendered]
    panel(panel_images, OUTPUT / "eye0_full_residual_ladder.jpg")
    # This is a neutral image-detail crop, not a face-specific claim.
    crop = (700, 500, 1800, 1600)
    panel(panel_images, OUTPUT / "eye0_detail_crop_residual_ladder.jpg", crop=crop)

    result = {
        "schema": "opennr-native-residual-scale65-comparison-v1",
        "scope": (
            "One retained Skyrim eye, frame 1. Native reduced outputs are composed "
            "offline as full_input + bilinear(native_work - work_input). The 65% "
            "native output was newly measured; all other scales are the existing "
            "native ladder. This is not live Skyrim or VR acceptance."
        ),
        "source_frame": str(CAPTURE),
        "full_shape": [FULL_HEIGHT, FULL_WIDTH],
        "scales": records,
        "raw_vs_full_native": metrics(full_input, full_teacher, full_input),
        "promotion": False,
    }
    (OUTPUT / "result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))
    print(OUTPUT / "eye0_full_residual_ladder.jpg")
    print(OUTPUT / "eye0_detail_crop_residual_ladder.jpg")


if __name__ == "__main__":
    main()
