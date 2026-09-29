"""Render a face crop comparing 50% native residual at 1x and 2x strength."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as F
from PIL import Image, ImageDraw


FULL_WIDTH = 2496
FULL_HEIGHT = 2688
FRAME = Path(
    r"C:\OpenNR_Captures_FullEyeTemporalStateTranche_20260910"
    r"\seq-1789064397821-5\frames\frame_00000008"
)
WORK_ROOT = Path(r"C:\OpenNR\NativeFaceResidualLadder_20260912\scale050")
OUTPUT = Path(r"C:\OpenNR\NativeFaceResidual50Strength2x_20260912")
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


def panel(items, path: Path, crop):
    display_width = 620
    caption_height = 40
    prepared = []
    for label, image in items:
        image = image.crop(crop)
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
    work_input = read_rgba8(WORK_ROOT / "input_eye0.rgba", 1248, 1344)
    work_output = read_rgba8(WORK_ROOT / "teacher_eye0.rgba", 1248, 1344)
    residual_1x = composite(full_input, work_input, work_output, 1.0)
    residual_2x = composite(full_input, work_input, work_output, 2.0)
    images = [
        ("Raw input", to_image(full_input)),
        ("50% residual 1x", to_image(residual_1x)),
        ("50% residual 2x", to_image(residual_2x)),
        ("Full native teacher", to_image(full_native)),
    ]
    OUTPUT.mkdir(parents=True, exist_ok=True)
    panel(images, OUTPUT / "frame_00000008_eye0_face_50_strength2x.jpg", FACE_CROP)
    panel(images, OUTPUT / "frame_00000008_eye0_portrait_50_strength2x.jpg", PORTRAIT_CROP)
    result = {
        "schema": "opennr-native-face-residual-50-strength2x-v1",
        "source_frame": str(FRAME),
        "face_crop_xyxy": list(FACE_CROP),
        "residual_definition": "full_input + bilinear(native50_work - work_input) * strength",
        "metrics": {
            "raw_mae_vs_full_native": float((full_input - full_native).abs().mean().item()),
            "residual_1x_mae_vs_full_native": float((residual_1x - full_native).abs().mean().item()),
            "residual_2x_mae_vs_full_native": float((residual_2x - full_native).abs().mean().item()),
            "residual_1x_vs_2x_mae": float((residual_1x - residual_2x).abs().mean().item()),
        },
    }
    (OUTPUT / "result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))
    print(OUTPUT / "frame_00000008_eye0_face_50_strength2x.jpg")
    print(OUTPUT / "frame_00000008_eye0_portrait_50_strength2x.jpg")


if __name__ == "__main__":
    main()
