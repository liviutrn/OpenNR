"""Render full-frame and tight-face views of the native residual scale ladder."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as F
from PIL import Image, ImageDraw


FULL_WIDTH = 2496
FULL_HEIGHT = 2688
FRAME_NUMBER = 8
SEQUENCE = Path(
    r"C:\OpenNR_Captures_FullEyeTemporalStateTranche_20260910\seq-1789064397821-5"
)
FRAME = SEQUENCE / "frames" / f"frame_{FRAME_NUMBER:08d}"
STUDY = Path(r"C:\OpenNR\NativeFaceResidualLadder_20260912")
OUTPUT = STUDY / "visuals"
SCALES = (90, 75, 65, 50, 33)
FACE_CROP = (1480, 700, 1980, 1300)
PORTRAIT_CROP = (1250, 620, 2300, 1730)


def read_rgba8(path: Path, width: int, height: int) -> torch.Tensor:
    payload = path.read_bytes()
    expected = width * height * 4
    if len(payload) != expected:
        raise ValueError(f"{path} has {len(payload)} bytes; expected {expected}")
    array = np.frombuffer(payload, dtype=np.uint8).reshape(height, width, 4)
    rgb = np.ascontiguousarray(array[:, :, :3].transpose(2, 0, 1))
    return torch.from_numpy(rgb).float().unsqueeze(0).div_(255.0)


def scaled_dimension(value: int, scale: int) -> int:
    return max(1, (value * scale + 50) // 100)


def residual_composite(
    full_input: torch.Tensor,
    work_input: torch.Tensor,
    work_output: torch.Tensor,
    strength: float = 1.0,
) -> torch.Tensor:
    residual = (work_output - work_input) * strength
    residual = F.interpolate(
        residual,
        size=(FULL_HEIGHT, FULL_WIDTH),
        mode="bilinear",
        align_corners=False,
    )
    return (full_input + residual).clamp(0.0, 1.0)


def to_image(value: torch.Tensor) -> Image.Image:
    array = value[0].permute(1, 2, 0).mul(255.0).round().byte().numpy()
    return Image.fromarray(array, mode="RGB")


def make_panel(
    items: list[tuple[str, Image.Image]],
    path: Path,
    crop: tuple[int, int, int, int] | None,
    display_width: int,
) -> None:
    caption_height = 38
    prepared: list[tuple[str, Image.Image]] = []
    for label, image in items:
        if crop is not None:
            image = image.crop(crop)
        ratio = display_width / image.width
        resized = image.resize(
            (display_width, max(1, round(image.height * ratio))),
            Image.Resampling.LANCZOS,
        )
        prepared.append((label, resized))
    height = caption_height + max(image.height for _, image in prepared)
    result = Image.new("RGB", (display_width * len(prepared), height), (20, 20, 20))
    draw = ImageDraw.Draw(result)
    for index, (label, image) in enumerate(prepared):
        x = index * display_width
        result.paste(image, (x, caption_height))
        draw.rectangle((x, 0, x + display_width - 1, caption_height - 1), fill=(20, 20, 20))
        draw.text((x + 10, 11), label, fill=(245, 245, 245))
    path.parent.mkdir(parents=True, exist_ok=True)
    result.save(path, quality=95, subsampling=0)


def timing(path: Path) -> dict[str, float]:
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    row = rows[-1]
    return {
        "pair_gpu_ms": float(row["pair_gpu_ms"]),
        "pair_wall_ms": float(row["pair_wall_ms"]),
    }


def main() -> None:
    full_input = read_rgba8(FRAME / "input_eye0_full.raw.bin", FULL_WIDTH, FULL_HEIGHT)
    full_native = read_rgba8(FRAME / "teacher_eye0_full.raw.bin", FULL_WIDTH, FULL_HEIGHT)
    images: list[tuple[str, Image.Image]] = [("Raw input", to_image(full_input))]
    records: list[dict[str, object]] = []

    for scale in SCALES:
        width = scaled_dimension(FULL_WIDTH, scale)
        height = scaled_dimension(FULL_HEIGHT, scale)
        root = STUDY / f"scale{scale:03d}"
        composite = residual_composite(
            full_input,
            read_rgba8(root / "input_eye0.rgba", width, height),
            read_rgba8(root / "teacher_eye0.rgba", width, height),
        )
        images.append((f"Residual {scale}%", to_image(composite)))
        record: dict[str, object] = {
            "scale_percent": scale,
            "work_dimensions": [width, height],
            "timing": timing(root / "timings.csv"),
            "full_frame_mae_vs_native_teacher": float((composite - full_native).abs().mean().item()),
            "full_frame_mae_vs_raw": float((composite - full_input).abs().mean().item()),
        }
        records.append(record)

    images.append(("Full native teacher", to_image(full_native)))
    OUTPUT.mkdir(parents=True, exist_ok=True)
    make_panel(images, OUTPUT / "frame_00000008_eye0_full_residual_ladder.jpg", None, 420)
    make_panel(images, OUTPUT / "frame_00000008_eye0_portrait_residual_ladder.jpg", PORTRAIT_CROP, 520)
    make_panel(images, OUTPUT / "frame_00000008_eye0_face_residual_ladder.jpg", FACE_CROP, 520)

    result = {
        "schema": "opennr-native-face-residual-ladder-visual-v1",
        "source_sequence": str(SEQUENCE),
        "source_frame": FRAME_NUMBER,
        "eye": 0,
        "face_crop_xyxy": list(FACE_CROP),
        "portrait_crop_xyxy": list(PORTRAIT_CROP),
        "residual_definition": "full_input + bilinear(native_work - work_input), strength=1.0",
        "scales": records,
        "quality_note": (
            "Each reduced output is a separate reset-qualified native replay. The full native "
            "teacher is the captured full-resolution frame; small temporal-state differences "
            "are possible between the two paths."
        ),
    }
    (OUTPUT / "result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))
    for name in (
        "frame_00000008_eye0_full_residual_ladder.jpg",
        "frame_00000008_eye0_portrait_residual_ladder.jpg",
        "frame_00000008_eye0_face_residual_ladder.jpg",
    ):
        print(OUTPUT / name)


if __name__ == "__main__":
    main()
