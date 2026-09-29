"""Evaluate separate low-frequency colour and high-frequency detail strengths.

This is an offline compositor study over the already captured native Feature 18
low-resolution replays.  It does not change the native runtime or collect new
frames.  The native work residual is upsampled to the full-resolution input,
then split into a Gaussian low-pass band and a high-pass detail band:

    result = source + colour_strength * low(change)
                    + detail_strength * high(change)

The split is a research control inspired by public MLX-DLSS and wrapper
implementations.  It is not asserted to be NVIDIA's internal composition.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as F
from PIL import Image, ImageDraw


FULL_WIDTH = 2496
FULL_HEIGHT = 2688
FRAME_IDS = tuple(range(1, 17))
SELECTED_FRAMES = (1, 4, 8, 12, 16)
SCALES = (50, 33)
INTENSITY = 1.0
REPLAY_ROOT = Path(r"C:\OpenNR\NativeSequenceLowResIntensity_20260912")
SEQUENCE = Path(r"C:\OpenNR_Captures_FullEyeTemporalStateTranche_20260910\seq-1789064397821-5")
OUTPUT = Path(r"C:\OpenNR\NativeSequenceLowResBandStrengthEvaluation_20260912")
FACE_CROP = (1480, 700, 1980, 1300)
SIGMA = 4.0
BLUR_DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")


CONDITIONS: tuple[tuple[str, float, float], ...] = (
    ("C1_D1_baseline", 1.0, 1.0),
    ("C050_D100", 0.50, 1.00),
    ("C000_D100_detail_only", 0.00, 1.00),
    ("C050_D150", 0.50, 1.50),
    ("C000_D150_detail_only", 0.00, 1.50),
    ("C100_D150", 1.00, 1.50),
    ("C025_D200", 0.25, 2.00),
    ("C125_D125", 1.25, 1.25),
)


def intensity_label(value: float) -> str:
    return f"intensity_{value:.2f}".replace(".", "p")


def read_rgb8(path: Path, width: int, height: int) -> torch.Tensor:
    payload = path.read_bytes()
    expected = width * height * 4
    if len(payload) != expected:
        raise ValueError(f"{path} has {len(payload)} bytes; expected {expected}")
    array = np.frombuffer(payload, dtype=np.uint8).reshape(height, width, 4)[:, :, :3].copy()
    return torch.from_numpy(array.transpose(2, 0, 1)).unsqueeze(0).float().div_(255.0)


def as_hwc(tensor: torch.Tensor) -> np.ndarray:
    return tensor.detach().float()[0].permute(1, 2, 0).numpy()


def as_u8(array: np.ndarray) -> np.ndarray:
    return np.clip(np.rint(array * 255.0), 0, 255).astype(np.uint8)


def gaussian_kernel(sigma: float) -> np.ndarray:
    extent = int(math.ceil(3.0 * sigma))
    offsets = np.arange(-extent, extent + 1, dtype=np.float32)
    kernel = np.exp(-(offsets * offsets) / np.float32(2.0 * sigma * sigma))
    return kernel / kernel.sum()


def blur(array: np.ndarray, kernel: np.ndarray) -> np.ndarray:
    try:
        import cv2
    except ImportError:
        # The training environment does not include OpenCV.  Use a separable
        # depthwise torch convolution so the full-frame diagnostic stays fast
        # enough to run on the available CUDA device.
        extent = (len(kernel) - 1) // 2
        tensor = torch.from_numpy(np.ascontiguousarray(array.transpose(2, 0, 1))).unsqueeze(0).to(BLUR_DEVICE)
        weights = torch.from_numpy(np.asarray(kernel, dtype=np.float32)).to(BLUR_DEVICE)
        horizontal_kernel = weights.reshape(1, 1, 1, -1).repeat(3, 1, 1, 1)
        vertical_kernel = weights.reshape(1, 1, -1, 1).repeat(3, 1, 1, 1)
        horizontal = F.conv2d(F.pad(tensor, (extent, extent, 0, 0), mode="replicate"), horizontal_kernel, groups=3)
        vertical = F.conv2d(F.pad(horizontal, (0, 0, extent, extent), mode="replicate"), vertical_kernel, groups=3)
        return vertical[0].permute(1, 2, 0).detach().cpu().numpy()
    return cv2.sepFilter2D(array.astype(np.float32), -1, kernel, kernel, borderType=cv2.BORDER_REPLICATE)


def metric(pred: np.ndarray, target: np.ndarray, source: np.ndarray) -> dict[str, float]:
    error = pred - target
    source_error = source - target
    mae = float(np.mean(np.abs(error)))
    rmse = float(np.sqrt(np.mean(np.square(error))))
    raw_mae = float(np.mean(np.abs(source_error)))
    return {
        "mae": mae,
        "rmse": rmse,
        "psnr_db": float(20.0 * math.log10(1.0 / max(rmse, 1e-12))),
        "raw_mae": raw_mae,
        "improvement_vs_raw_mae": raw_mae - mae,
        "better_fraction_pixels": float(np.mean(np.abs(error) < np.abs(source_error))),
    }


def face_metric(pred: np.ndarray, target: np.ndarray, source: np.ndarray) -> dict[str, float]:
    x0, y0, x1, y1 = FACE_CROP
    return metric(pred[y0:y1, x0:x1], target[y0:y1, x0:x1], source[y0:y1, x0:x1])


def aggregate(items: list[dict[str, float]]) -> dict[str, float | int]:
    return {
        "sample_count": len(items),
        "mae_mean": float(np.mean([item["mae"] for item in items])),
        "rmse_mean": float(np.mean([item["rmse"] for item in items])),
        "psnr_db_mean": float(np.mean([item["psnr_db"] for item in items])),
        "raw_mae_mean": float(np.mean([item["raw_mae"] for item in items])),
        "improvement_vs_raw_mae_mean": float(
            np.mean([item["improvement_vs_raw_mae"] for item in items])
        ),
        "better_fraction_pixels_mean": float(
            np.mean([item["better_fraction_pixels"] for item in items])
        ),
        "better_than_raw_samples": int(
            sum(item["improvement_vs_raw_mae"] > 0 for item in items)
        ),
    }


def image(array: np.ndarray) -> Image.Image:
    return Image.fromarray(as_u8(array), mode="RGB")


def save_grid(path: Path, rows: list[tuple[str, list[tuple[str, np.ndarray]]]], crop: tuple[int, int, int, int] | None) -> None:
    cell_width = 320
    label_height = 30
    row_label_width = 155
    rendered_rows: list[tuple[str, list[tuple[str, Image.Image]]]] = []
    max_columns = 0
    cell_height = 0
    for row_label, items in rows:
        rendered: list[tuple[str, Image.Image]] = []
        for label, array in items:
            rendered_image = image(array)
            if crop is not None:
                rendered_image = rendered_image.crop(crop)
            ratio = cell_width / rendered_image.width
            rendered_image = rendered_image.resize(
                (cell_width, max(1, round(rendered_image.height * ratio))), Image.Resampling.LANCZOS
            )
            rendered.append((label, rendered_image))
            cell_height = max(cell_height, rendered_image.height)
        rendered_rows.append((row_label, rendered))
        max_columns = max(max_columns, len(rendered))
    canvas = Image.new(
        "RGB",
        (row_label_width + max_columns * cell_width, sum(label_height + cell_height for _ in rendered_rows)),
        (22, 22, 22),
    )
    draw = ImageDraw.Draw(canvas)
    y = 0
    for row_label, rendered in rendered_rows:
        draw.text((8, y + 9), row_label, fill=(245, 245, 245))
        for index, (label, rendered_image) in enumerate(rendered):
            x = row_label_width + index * cell_width
            draw.text((x + 7, y + 8), label, fill=(245, 245, 245))
            canvas.paste(rendered_image, (x, y + label_height))
        y += label_height + cell_height
    path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(path, quality=95, subsampling=0)


def load_sample(scale: int, frame_id: int, eye: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    source_frame = SEQUENCE / "frames" / f"frame_{frame_id:08d}"
    branch = REPLAY_ROOT / f"scale{scale:03d}" / intensity_label(INTENSITY)
    provenance = json.loads((branch / "provenance.json").read_text(encoding="utf-8"))
    work_width, work_height = (int(value) for value in provenance["network_dimensions"])
    replay_frame = branch / "frames" / f"frame_{frame_id:08d}"
    source = as_hwc(read_rgb8(source_frame / f"input_eye{eye}_full.raw.bin", FULL_WIDTH, FULL_HEIGHT))
    target = as_hwc(read_rgb8(source_frame / f"teacher_eye{eye}_full.raw.bin", FULL_WIDTH, FULL_HEIGHT))
    work_input = read_rgb8(
        REPLAY_ROOT / f"scale{scale:03d}" / "inputs" / f"frame_{frame_id:08d}" / f"input_eye{eye}.rgba",
        work_width,
        work_height,
    )
    work_output = read_rgb8(replay_frame / f"teacher_eye{eye}.rgba", work_width, work_height)
    residual = as_hwc(
        F.interpolate(work_output - work_input, size=(FULL_HEIGHT, FULL_WIDTH), mode="bilinear", align_corners=False)
    )
    return source, target, residual


def main() -> int:
    if OUTPUT.exists() and any(OUTPUT.iterdir()):
        raise FileExistsError(f"refusing to use non-empty output directory: {OUTPUT}")
    OUTPUT.mkdir(parents=True, exist_ok=True)
    kernel = gaussian_kernel(SIGMA)
    all_results: dict[str, object] = {
        "schema": "opennr-native-lowres-band-strength-evaluation-v1",
        "scope": "offline static compositor diagnostic over existing reset-qualified native low-resolution replays; not temporal, live, headset, or VR-budget acceptance",
        "sequence": str(SEQUENCE),
        "replay_root": str(REPLAY_ROOT),
        "scales": list(SCALES),
        "native_intensity": INTENSITY,
        "gaussian_sigma": SIGMA,
        "face_crop_xyxy": list(FACE_CROP),
        "conditions": [
            {"name": name, "colour_strength": colour, "detail_strength": detail}
            for name, colour, detail in CONDITIONS
        ],
        "results": {},
    }

    sample_bands: dict[tuple[int, int, int], tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]] = {}
    for scale in SCALES:
        print(f"loading and splitting scale {scale}%", flush=True)
        for frame_id in FRAME_IDS:
            for eye in (0, 1):
                source, target, change = load_sample(scale, frame_id, eye)
                low = blur(change, kernel)
                sample_bands[(scale, frame_id, eye)] = (source, target, low, change - low)

    for scale in SCALES:
        print(f"scale {scale}%", flush=True)
        per_condition: dict[str, object] = {}
        previews: dict[str, dict[int, np.ndarray]] = {name: {} for name, _, _ in CONDITIONS}
        for name, colour_strength, detail_strength in CONDITIONS:
            full_items: list[dict[str, float]] = []
            face_items: list[dict[str, float]] = []
            temporal_values: dict[int, list[float]] = {0: [], 1: []}
            previous: dict[int, tuple[np.ndarray, np.ndarray] | None] = {0: None, 1: None}
            frame_records: list[dict[str, object]] = []
            for frame_id in FRAME_IDS:
                eyes: list[dict[str, object]] = []
                for eye in (0, 1):
                    source, target, low, high = sample_bands[(scale, frame_id, eye)]
                    pred = np.clip(source + np.float32(colour_strength) * low + np.float32(detail_strength) * high, 0.0, 1.0)
                    full = metric(pred, target, source)
                    face = face_metric(pred, target, source)
                    full_items.append(full)
                    face_items.append(face)
                    if frame_id == 8:
                        previews[name][eye] = pred
                    if previous[eye] is not None:
                        old_pred, old_target = previous[eye]
                        temporal_values[eye].append(float(np.mean(np.abs((pred - old_pred) - (target - old_target)))))
                    previous[eye] = (pred, target)
                    eyes.append({"eye": eye, "full": full, "face": face})
                frame_records.append({"frame_id": frame_id, "eyes": eyes})
            per_condition[name] = {
                "colour_strength": colour_strength,
                "detail_strength": detail_strength,
                "aggregate": aggregate(full_items),
                "face_aggregate": aggregate(face_items),
                "temporal_delta_error_mean": {str(eye): float(np.mean(values)) for eye, values in temporal_values.items()},
                "frames": frame_records,
            }

        rows: list[tuple[str, list[tuple[str, np.ndarray]]]] = []
        for name, _, _ in CONDITIONS:
            rows.append((name, [("eye0", previews[name][0]), ("eye1", previews[name][1])]))
        save_grid(OUTPUT / "previews" / f"scale{scale:03d}_frame00000008_full.jpg", rows, None)
        save_grid(OUTPUT / "previews" / f"scale{scale:03d}_frame00000008_face.jpg", rows, FACE_CROP)
        all_results["results"][str(scale)] = per_condition

    (OUTPUT / "result.json").write_text(json.dumps(all_results, indent=2), encoding="utf-8")
    print(f"wrote {OUTPUT / 'result.json'}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
