"""Compare native model intensity against the same 65% residual compositor."""

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
WORK_WIDTH = 1622
WORK_HEIGHT = 1747
FRAME = Path(
    r"C:\OpenNR_Captures_FullEyeTemporalStateTranche_20260910"
    r"\seq-1789063628889-1\frames\frame_00000001"
)
RESET_ROOT = Path(r"C:\OpenNR\Native65IntensityResetSweep_20260912")
TIMING_ROOT = Path(r"C:\OpenNR\Native65IntensitySweep_20260912")
OUTPUT = Path(r"C:\OpenNR\Native65IntensityComparison_20260912")
INTENSITIES = (1.0, 1.7, 2.0)
DETAIL_CROP = (700, 500, 1800, 1600)


def read_rgba8(path: Path, width: int, height: int) -> torch.Tensor:
    payload = path.read_bytes()
    expected = width * height * 4
    if len(payload) != expected:
        raise ValueError(f"{path} has {len(payload)} bytes; expected {expected}")
    array = np.frombuffer(payload, dtype=np.uint8).reshape(height, width, 4)
    rgb = np.ascontiguousarray(array[:, :, :3].transpose(2, 0, 1))
    return torch.from_numpy(rgb).float().unsqueeze(0).div_(255.0)


def composite(full_input: torch.Tensor, work_input: torch.Tensor, work_output: torch.Tensor) -> torch.Tensor:
    residual = F.interpolate(
        work_output - work_input,
        size=(FULL_HEIGHT, FULL_WIDTH),
        mode="bilinear",
        align_corners=False,
    )
    return (full_input + residual).clamp(0.0, 1.0)


def to_image(value: torch.Tensor) -> Image.Image:
    array = value[0].permute(1, 2, 0).mul(255.0).round().byte().numpy()
    return Image.fromarray(array, mode="RGB")


def panel(items: list[tuple[str, Image.Image]], path: Path, crop=None) -> None:
    display_width = 560
    caption_height = 38
    prepared = []
    for label, image in items:
        if crop is not None:
            image = image.crop(crop)
        ratio = display_width / image.width
        prepared.append((label, image.resize((display_width, max(1, round(image.height * ratio))), Image.Resampling.LANCZOS)))
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


def warm_timing(root: Path) -> dict[str, float | int]:
    with (root / "timings.csv").open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    warm = rows[1:] if len(rows) > 1 else rows
    gpu = np.array([float(row["pair_gpu_ms"]) for row in warm], dtype=np.float64)
    wall = np.array([float(row["pair_wall_ms"]) for row in warm], dtype=np.float64)
    return {
        "samples_excluding_first": int(len(warm)),
        "pair_gpu_median_ms": float(np.median(gpu)),
        "pair_gpu_p95_ms": float(np.percentile(gpu, 95)),
        "pair_wall_median_ms": float(np.median(wall)),
        "pair_wall_p95_ms": float(np.percentile(wall, 95)),
    }


def main() -> None:
    full_input = read_rgba8(FRAME / "input_eye0_full.raw.bin", FULL_WIDTH, FULL_HEIGHT)
    full_native = read_rgba8(FRAME / "teacher_eye0_full.raw.bin", FULL_WIDTH, FULL_HEIGHT)
    work_input = read_rgba8(
        Path(r"C:\OpenNR\NativeResolutionStudy65_20260912") / "input_eye0.rgba",
        WORK_WIDTH,
        WORK_HEIGHT,
    )
    images = [("Raw input", to_image(full_input))]
    records = []
    outputs = []
    for intensity in INTENSITIES:
        label = f"intensity_{intensity:.2f}".replace(".", "p")
        work_output = read_rgba8(RESET_ROOT / label / "teacher_eye0.rgba", WORK_WIDTH, WORK_HEIGHT)
        value = composite(full_input, work_input, work_output)
        outputs.append(value)
        images.append((f"Intensity {intensity:.2f}", to_image(value)))
        records.append(
            {
                "intensity": intensity,
                "timing_warm": warm_timing(TIMING_ROOT / label),
                "full_frame_mae_vs_native_teacher": float((value - full_native).abs().mean().item()),
                "full_frame_mae_vs_raw": float((value - full_input).abs().mean().item()),
            }
        )
    images.append(("Full native teacher", to_image(full_native)))
    OUTPUT.mkdir(parents=True, exist_ok=True)
    panel(images, OUTPUT / "frame_00000001_eye0_full_intensity_ladder.jpg")
    panel(images, OUTPUT / "frame_00000001_eye0_detail_intensity_ladder.jpg", DETAIL_CROP)

    pairwise = {}
    for left_index, left_intensity in enumerate(INTENSITIES):
        for right_index in range(left_index + 1, len(INTENSITIES)):
            right_intensity = INTENSITIES[right_index]
            pairwise[f"{left_intensity:.2f}_vs_{right_intensity:.2f}_mae"] = float(
                (outputs[left_index] - outputs[right_index]).abs().mean().item()
            )
    result = {
        "schema": "opennr-native65-intensity-comparison-v1",
        "source_frame": str(FRAME),
        "work_dimensions": [WORK_WIDTH, WORK_HEIGHT],
        "residual_definition": "full_input + bilinear(native_work - work_input), strength=1.0",
        "records": records,
        "pairwise_composite_mae": pairwise,
        "interpretation": (
            "Intensity changes the native model output before the residual compositor; it is "
            "not equivalent to multiplying the already-composited residual by the same number."
        ),
    }
    (OUTPUT / "result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))
    print(OUTPUT / "frame_00000001_eye0_full_intensity_ladder.jpg")
    print(OUTPUT / "frame_00000001_eye0_detail_intensity_ladder.jpg")


if __name__ == "__main__":
    main()
