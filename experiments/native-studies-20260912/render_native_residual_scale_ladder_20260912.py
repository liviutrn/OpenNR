"""Render visual comparisons for the native reduced-resolution residual ladder."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as F
from PIL import Image, ImageDraw


FULL_WIDTH = 2496
FULL_HEIGHT = 2688
FACE_CROP = (1250, 620, 2300, 1730)
ROOT = Path(r"D:\.CODEX_Projects\OpenNR-VR\out\native_teacher_resolution_renderer_contract_20260912")
FRAME = Path(
    r"C:\OpenNR_Captures_FullEyeTemporalStateTranche_20260910\seq-1789063628889-1\frames\frame_00000001"
)
OUTPUT = Path(r"C:\OpenNR\native_residual_scale_ladder_visual_20260912")


def read_rgba8(path: Path, width: int, height: int) -> torch.Tensor:
    payload = path.read_bytes()
    expected = width * height * 4
    if len(payload) != expected:
        raise ValueError(f"{path} has {len(payload)} bytes; expected {expected}")
    array = np.frombuffer(payload, dtype=np.uint8).reshape(height, width, 4)
    rgb = np.ascontiguousarray(array[:, :, :3].transpose(2, 0, 1))
    return torch.from_numpy(rgb).float().unsqueeze(0).div_(255.0)


def composite(
    full: torch.Tensor,
    work_input: torch.Tensor,
    native_work: torch.Tensor,
    strength: float = 1.0,
) -> torch.Tensor:
    residual = (native_work - work_input) * strength
    residual = F.interpolate(
        residual,
        size=(full.shape[-2], full.shape[-1]),
        mode="bilinear",
        align_corners=False,
    )
    return (full + residual).clamp(0.0, 1.0)


def to_image(value: torch.Tensor) -> Image.Image:
    array = value[0].permute(1, 2, 0).mul(255.0).round().byte().numpy()
    return Image.fromarray(array, mode="RGB")


def panel(items: list[tuple[str, Image.Image]], crop: tuple[int, int, int, int] | None, path: Path) -> None:
    display_width = 560
    caption_height = 34
    prepared: list[tuple[str, Image.Image]] = []
    for label, image in items:
        if crop is not None:
            image = image.crop(crop)
        ratio = display_width / image.width
        resized = image.resize((display_width, max(1, round(image.height * ratio))), Image.Resampling.LANCZOS)
        prepared.append((label, resized))
    height = caption_height + max(image.height for _, image in prepared)
    result = Image.new("RGB", (display_width * len(prepared), height), (20, 20, 20))
    draw = ImageDraw.Draw(result)
    for index, (label, image) in enumerate(prepared):
        x = index * display_width
        result.paste(image, (x, caption_height))
        draw.rectangle((x, 0, x + display_width - 1, caption_height - 1), fill=(20, 20, 20))
        draw.text((x + 10, 9), label, fill=(245, 245, 245))
    path.parent.mkdir(parents=True, exist_ok=True)
    result.save(path, quality=94, subsampling=0)


def main() -> None:
    full = read_rgba8(FRAME / "input_eye0_full.raw.bin", FULL_WIDTH, FULL_HEIGHT)
    native_full = read_rgba8(ROOT / "scale100" / "teacher_eye0.rgba", FULL_WIDTH, FULL_HEIGHT)

    native50_input = read_rgba8(ROOT / "scale050" / "input_eye0.rgba", 1248, 1344)
    native50_output = read_rgba8(ROOT / "scale050" / "teacher_eye0.rgba", 1248, 1344)
    native33_input = read_rgba8(ROOT / "scale033" / "input_eye0.rgba", 824, 887)
    native33_output = read_rgba8(ROOT / "scale033" / "teacher_eye0.rgba", 824, 887)

    native50 = composite(full, native50_input, native50_output)
    native33 = composite(full, native33_input, native33_output)
    native33_2x = composite(full, native33_input, native33_output, strength=2.0)
    images = [
        ("Raw input", to_image(full)),
        ("Native 33% 1x", to_image(native33)),
        ("Native 33% 2x", to_image(native33_2x)),
        ("Native 50% 1x", to_image(native50)),
        ("Full native teacher", to_image(native_full)),
    ]
    target = native_full.float()
    metrics = {
        "full_input_vs_full_native_mae": float((full.float() - target).abs().mean().item()),
        "native50_residual_vs_full_native_mae": float((native50.float() - target).abs().mean().item()),
        "native33_residual_vs_full_native_mae": float((native33.float() - target).abs().mean().item()),
        "native33_residual_2x_vs_full_native_mae": float((native33_2x.float() - target).abs().mean().item()),
        "native50_residual_vs_raw_mae": float((native50.float() - full.float()).abs().mean().item()),
        "native33_residual_vs_raw_mae": float((native33.float() - full.float()).abs().mean().item()),
        "native33_residual_2x_vs_raw_mae": float((native33_2x.float() - full.float()).abs().mean().item()),
        "native50_residual_vs_native33_residual_mae": float((native50.float() - native33.float()).abs().mean().item()),
        "native33_residual_2x_vs_native33_residual_mae": float(
            (native33_2x.float() - native33.float()).abs().mean().item()
        ),
    }
    panel(images, None, OUTPUT / "frame_00000001_eye0_full_scale_strength2x.jpg")
    panel(images, FACE_CROP, OUTPUT / "frame_00000001_eye0_face_scale_strength2x.jpg")
    OUTPUT.mkdir(parents=True, exist_ok=True)
    (OUTPUT / "metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    print(OUTPUT / "frame_00000001_eye0_full_scale_ladder.jpg")
    print(OUTPUT / "frame_00000001_eye0_face_scale_ladder.jpg")
    print(json.dumps(metrics, indent=2))


if __name__ == "__main__":
    main()
