"""Render a face grid over native intensity and post-compositor strength."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as F
from PIL import Image, ImageDraw


FULL_WIDTH = 2496
FULL_HEIGHT = 2688
WORK_WIDTH = 1248
WORK_HEIGHT = 1344
FRAME = Path(
    r"C:\OpenNR_Captures_FullEyeTemporalStateTranche_20260910"
    r"\seq-1789064397821-5\frames\frame_00000008"
)
ROOT = Path(r"C:\OpenNR\NativeFace50IntensityResetSweep_20260912")
OUTPUT = Path(r"C:\OpenNR\NativeFace50IntensityStrengthGrid_20260912")
INTENSITIES = (1.0, 1.7, 2.0)
STRENGTHS = (0.5, 1.0, 1.5, 2.0)
FACE_CROP = (1480, 700, 1980, 1300)


def read_rgba8(path: Path, width: int, height: int) -> torch.Tensor:
    payload = path.read_bytes()
    expected = width * height * 4
    if len(payload) != expected:
        raise ValueError(f"{path} has {len(payload)} bytes; expected {expected}")
    array = np.frombuffer(payload, dtype=np.uint8).reshape(height, width, 4)
    rgb = np.ascontiguousarray(array[:, :, :3].transpose(2, 0, 1))
    return torch.from_numpy(rgb).float().unsqueeze(0).div_(255.0)


def composite(full_input, work_input, work_output, strength: float):
    residual = F.interpolate(
        (work_output - work_input) * strength,
        size=(FULL_HEIGHT, FULL_WIDTH),
        mode="bilinear",
        align_corners=False,
    )
    return (full_input + residual).clamp(0.0, 1.0)


def to_image(value: torch.Tensor) -> Image.Image:
    array = value[0].permute(1, 2, 0).mul(255.0).round().byte().numpy()
    return Image.fromarray(array, mode="RGB")


def crop_tensor(value: torch.Tensor) -> torch.Tensor:
    left, top, right, bottom = FACE_CROP
    return value[:, :, top:bottom, left:right]


def make_grid(cells: dict[tuple[float, float], Image.Image], path: Path) -> None:
    cell_width = 600
    caption_height = 42
    cell_images = {}
    for key, image in cells.items():
        image = image.crop(FACE_CROP)
        ratio = cell_width / image.width
        cell_images[key] = image.resize(
            (cell_width, round(image.height * ratio)), Image.Resampling.LANCZOS
        )
    cell_height = caption_height + next(iter(cell_images.values())).height
    label_width = 88
    result = Image.new(
        "RGB",
        (label_width + cell_width * len(INTENSITIES), cell_height * len(STRENGTHS)),
        (20, 20, 20),
    )
    draw = ImageDraw.Draw(result)
    for row, strength in enumerate(STRENGTHS):
        y = row * cell_height
        draw.text((8, y + 14), f"S={strength:.1f}x", fill=(245, 245, 245))
        for column, intensity in enumerate(INTENSITIES):
            x = label_width + column * cell_width
            image = cell_images[(intensity, strength)]
            result.paste(image, (x, y + caption_height))
            draw.rectangle((x, y, x + cell_width - 1, y + caption_height - 1), fill=(20, 20, 20))
            draw.text((x + 10, y + 12), f"I={intensity:.2f}  S={strength:.1f}x", fill=(245, 245, 245))
    path.parent.mkdir(parents=True, exist_ok=True)
    result.save(path, quality=96, subsampling=0)


def make_reference_panel(images: list[tuple[str, Image.Image]], path: Path) -> None:
    display_width = 620
    caption_height = 40
    prepared = []
    for label, image in images:
        image = image.crop(FACE_CROP)
        ratio = display_width / image.width
        prepared.append((label, image.resize((display_width, round(image.height * ratio)), Image.Resampling.LANCZOS)))
    height = caption_height + max(image.height for _, image in prepared)
    result = Image.new("RGB", (display_width * len(prepared), height), (20, 20, 20))
    draw = ImageDraw.Draw(result)
    for index, (label, image) in enumerate(prepared):
        x = index * display_width
        result.paste(image, (x, caption_height))
        draw.rectangle((x, 0, x + display_width - 1, caption_height - 1), fill=(20, 20, 20))
        draw.text((x + 10, 12), label, fill=(245, 245, 245))
    path.parent.mkdir(parents=True, exist_ok=True)
    result.save(path, quality=96, subsampling=0)


def main() -> None:
    full_input = read_rgba8(FRAME / "input_eye0_full.raw.bin", FULL_WIDTH, FULL_HEIGHT)
    full_native = read_rgba8(FRAME / "teacher_eye0_full.raw.bin", FULL_WIDTH, FULL_HEIGHT)
    work_input = read_rgba8(
        Path(r"C:\OpenNR\NativeFaceResidualLadder_20260912\scale050") / "input_eye0.rgba",
        WORK_WIDTH,
        WORK_HEIGHT,
    )
    outputs = {}
    cells = {}
    records = []
    for intensity in INTENSITIES:
        label = f"intensity_{intensity:.2f}".replace(".", "p")
        work_output = read_rgba8(ROOT / label / "teacher_eye0.rgba", WORK_WIDTH, WORK_HEIGHT)
        for strength in STRENGTHS:
            value = composite(full_input, work_input, work_output, strength)
            outputs[(intensity, strength)] = value
            cells[(intensity, strength)] = to_image(value)
            face_value = crop_tensor(value)
            face_target = crop_tensor(full_native)
            face_raw = crop_tensor(full_input)
            records.append(
                {
                    "intensity": intensity,
                    "strength": strength,
                    "full_frame_mae_vs_native_teacher": float((value - full_native).abs().mean().item()),
                    "face_crop_mae_vs_native_teacher": float((face_value - face_target).abs().mean().item()),
                    "full_frame_mae_vs_raw": float((value - full_input).abs().mean().item()),
                    "face_crop_mae_vs_raw": float((face_value - face_raw).abs().mean().item()),
                }
            )

    OUTPUT.mkdir(parents=True, exist_ok=True)
    make_grid(cells, OUTPUT / "frame_00000008_eye0_face_intensity_strength_grid.jpg")
    reference = [
        ("Raw input", to_image(full_input)),
        ("I=1.00 S=1.0x", to_image(outputs[(1.0, 1.0)])),
        ("I=1.00 S=2.0x", to_image(outputs[(1.0, 2.0)])),
        ("I=2.00 S=1.0x", to_image(outputs[(2.0, 1.0)])),
        ("I=2.00 S=2.0x", to_image(outputs[(2.0, 2.0)])),
        ("Full native teacher", to_image(full_native)),
    ]
    make_reference_panel(reference, OUTPUT / "frame_00000008_eye0_face_intensity_strength_references.jpg")
    result = {
        "schema": "opennr-native-face50-intensity-strength-grid-v1",
        "source_frame": str(FRAME),
        "face_crop_xyxy": list(FACE_CROP),
        "work_dimensions": [WORK_WIDTH, WORK_HEIGHT],
        "residual_definition": "full_input + bilinear(native50_work - work_input) * strength",
        "native_intensity_values": list(INTENSITIES),
        "post_compositor_strength_values": list(STRENGTHS),
        "records": records,
        "note": (
            "The three intensity columns use separate reset-qualified native calls. If they "
            "are identical, this carrier/harness is not exposing intensity as an effective "
            "model-output control; strength remains a distinct post-compositor operation."
        ),
    }
    (OUTPUT / "result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))
    print(OUTPUT / "frame_00000008_eye0_face_intensity_strength_grid.jpg")
    print(OUTPUT / "frame_00000008_eye0_face_intensity_strength_references.jpg")


if __name__ == "__main__":
    main()
