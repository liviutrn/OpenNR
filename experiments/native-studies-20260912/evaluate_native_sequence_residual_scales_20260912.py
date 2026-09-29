"""Evaluate 16-frame native reduced-resolution residual replays.

The evaluator compares direct upsampling and matched residual composition on
the saved full-eye sequence.  It also measures temporal delta error and emits
face contact sheets so a speed/quality tradeoff is inspectable rather than
being reduced to a single scalar.
"""

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
FRAME_IDS = tuple(range(1, 17))
SEQUENCE = Path(
    r"C:\OpenNR_Captures_FullEyeTemporalStateTranche_20260910\seq-1789064397821-5"
)
REPLAY_ROOT = Path(r"C:\OpenNR\NativeSequenceResidualScales_20260912")
OUTPUT = Path(r"C:\OpenNR\NativeSequenceResidualScaleEvaluation_20260912")
SCALES = (75, 65, 50)
FACE_CROP = (1480, 700, 1980, 1300)
SELECTED_FRAMES = (1, 4, 8, 12, 16)


def read_rgb8(path: Path, width: int, height: int) -> torch.Tensor:
    payload = path.read_bytes()
    expected = width * height * 4
    if len(payload) != expected:
        raise ValueError(f"{path} has {len(payload)} bytes; expected {expected}")
    array = np.frombuffer(payload, dtype=np.uint8).reshape(height, width, 4)[:, :, :3].copy()
    return torch.from_numpy(array.transpose(2, 0, 1)).unsqueeze(0).float().div_(255.0)


def as_hwc(tensor: torch.Tensor) -> np.ndarray:
    return tensor.detach().float()[0].permute(1, 2, 0).numpy()


def metric(pred: np.ndarray, target: np.ndarray, source: np.ndarray) -> dict[str, float]:
    error = pred - target
    source_error = source - target
    mae = float(np.mean(np.abs(error)))
    rmse = float(np.sqrt(np.mean(np.square(error))))
    identity_mae = float(np.mean(np.abs(source_error)))
    return {
        "mae": mae,
        "rmse": rmse,
        "psnr_db": float(20.0 * math.log10(1.0 / max(rmse, 1e-12))),
        "raw_mae": identity_mae,
        "improvement_vs_raw_mae": identity_mae - mae,
        "better_fraction_pixels": float(
            np.mean(np.abs(error) < np.abs(source_error))
        ),
    }


def timing_summary(path: Path) -> dict[str, float | int]:
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        raise ValueError(f"no timing rows in {path}")
    # Frame 1 includes allocation and reset work.  The sequence steady-state
    # number is frames 2..16, which is the relevant per-frame VR figure.
    warm_rows = rows[1:] if len(rows) > 1 else rows
    gpu = np.asarray([float(row["pair_gpu_ms"]) for row in warm_rows], dtype=np.float64)
    wall = np.asarray([float(row["pair_wall_ms"]) for row in warm_rows], dtype=np.float64)
    return {
        "first_frame_pair_gpu_ms": float(rows[0]["pair_gpu_ms"]),
        "first_frame_pair_wall_ms": float(rows[0]["pair_wall_ms"]),
        "steady_frame_count": int(len(warm_rows)),
        "steady_pair_gpu_median_ms": float(np.median(gpu)),
        "steady_pair_gpu_p95_ms": float(np.percentile(gpu, 95)),
        "steady_pair_gpu_mean_ms": float(np.mean(gpu)),
        "steady_pair_wall_median_ms": float(np.median(wall)),
        "steady_pair_wall_p95_ms": float(np.percentile(wall, 95)),
        "steady_pair_wall_mean_ms": float(np.mean(wall)),
    }


def resolve(full_source: torch.Tensor, small_input: torch.Tensor, small_output: torch.Tensor) -> tuple[np.ndarray, np.ndarray]:
    direct = F.interpolate(
        small_output,
        size=(FULL_HEIGHT, FULL_WIDTH),
        mode="bilinear",
        align_corners=False,
    )
    matched = (
        full_source
        + F.interpolate(
            small_output - small_input,
            size=(FULL_HEIGHT, FULL_WIDTH),
            mode="bilinear",
            align_corners=False,
        )
    ).clamp(0.0, 1.0)
    return as_hwc(direct), as_hwc(matched)


def image(array: np.ndarray) -> Image.Image:
    return Image.fromarray(
        np.clip(np.rint(array * 255.0), 0, 255).astype(np.uint8), mode="RGB"
    )


def save_grid(
    path: Path,
    rows: list[tuple[str, list[tuple[str, np.ndarray]]]],
    crop: tuple[int, int, int, int] | None,
    cell_width: int,
) -> None:
    label_height = 30
    row_label_width = 68
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
                (cell_width, max(1, round(rendered_image.height * ratio))),
                Image.Resampling.LANCZOS,
            )
            rendered.append((label, rendered_image))
            cell_height = max(cell_height, rendered_image.height)
        rendered_rows.append((row_label, rendered))
        max_columns = max(max_columns, len(rendered))

    total_width = row_label_width + max_columns * cell_width
    total_height = sum(label_height + cell_height for _ in rendered_rows)
    canvas = Image.new("RGB", (total_width, total_height), (22, 22, 22))
    draw = ImageDraw.Draw(canvas)
    y = 0
    for row_label, rendered in rendered_rows:
        draw.text((8, y + 9), row_label, fill=(245, 245, 245))
        for index, (label, rendered_image) in enumerate(rendered):
            x = row_label_width + index * cell_width
            draw.rectangle((x, y, x + cell_width - 1, y + label_height - 1), fill=(22, 22, 22))
            draw.text((x + 7, y + 8), label, fill=(245, 245, 245))
            canvas.paste(rendered_image, (x, y + label_height))
        y += label_height + cell_height
    path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(path, quality=95, subsampling=0)


def main() -> int:
    if OUTPUT.exists() and any(OUTPUT.iterdir()):
        raise FileExistsError(f"refusing to use non-empty output directory: {OUTPUT}")
    OUTPUT.mkdir(parents=True, exist_ok=True)
    per_scale: dict[int, dict[str, object]] = {}
    preview_data: dict[int, dict[int, dict[str, np.ndarray]]] = {
        scale: {} for scale in SCALES
    }

    for scale in SCALES:
        scale_root = REPLAY_ROOT / f"scale{scale:03d}"
        provenance = json.loads((scale_root / "provenance.json").read_text(encoding="utf-8"))
        small_width, small_height = (int(value) for value in provenance["network_dimensions"])
        records: list[dict[str, object]] = []
        eye_sequences: dict[int, dict[str, list[np.ndarray]]] = {
            eye: {"matched": [], "direct": [], "target": [], "source": []}
            for eye in range(2)
        }

        for frame_id in FRAME_IDS:
            source_frame = SEQUENCE / "frames" / f"frame_{frame_id:08d}"
            replay_frame = scale_root / "frames" / f"frame_{frame_id:08d}"
            frame_record: dict[str, object] = {"frame_id": frame_id, "eyes": []}
            for eye in range(2):
                source = as_hwc(
                    read_rgb8(
                        source_frame / f"input_eye{eye}_full.raw.bin",
                        FULL_WIDTH,
                        FULL_HEIGHT,
                    )
                )
                target = as_hwc(
                    read_rgb8(
                        source_frame / f"teacher_eye{eye}_full.raw.bin",
                        FULL_WIDTH,
                        FULL_HEIGHT,
                    )
                )
                small_input = read_rgb8(
                    replay_frame / f"input_eye{eye}.rgba", small_width, small_height
                )
                small_output = read_rgb8(
                    replay_frame / f"teacher_eye{eye}.rgba", small_width, small_height
                )
                direct, matched = resolve(
                    torch.from_numpy(source.transpose(2, 0, 1)).unsqueeze(0),
                    small_input,
                    small_output,
                )
                eye_sequences[eye]["source"].append(source)
                eye_sequences[eye]["target"].append(target)
                eye_sequences[eye]["direct"].append(direct)
                eye_sequences[eye]["matched"].append(matched)
                if eye == 0 and frame_id in SELECTED_FRAMES:
                    preview_data[scale][frame_id] = {
                        "source": source,
                        "target": target,
                        "direct": direct,
                        "matched": matched,
                    }
                frame_record["eyes"].append(
                    {
                        "eye": eye,
                        "direct": metric(direct, target, source),
                        "matched_residual": metric(matched, target, source),
                        "face_direct": metric(
                            direct[FACE_CROP[1] : FACE_CROP[3], FACE_CROP[0] : FACE_CROP[2]],
                            target[FACE_CROP[1] : FACE_CROP[3], FACE_CROP[0] : FACE_CROP[2]],
                            source[FACE_CROP[1] : FACE_CROP[3], FACE_CROP[0] : FACE_CROP[2]],
                        ),
                        "face_matched_residual": metric(
                            matched[FACE_CROP[1] : FACE_CROP[3], FACE_CROP[0] : FACE_CROP[2]],
                            target[FACE_CROP[1] : FACE_CROP[3], FACE_CROP[0] : FACE_CROP[2]],
                            source[FACE_CROP[1] : FACE_CROP[3], FACE_CROP[0] : FACE_CROP[2]],
                        ),
                    }
                )
            records.append(frame_record)

        all_direct = [
            eye_record["direct"]
            for frame_record in records
            for eye_record in frame_record["eyes"]
        ]
        all_matched = [
            eye_record["matched_residual"]
            for frame_record in records
            for eye_record in frame_record["eyes"]
        ]
        all_face_direct = [
            eye_record["face_direct"]
            for frame_record in records
            for eye_record in frame_record["eyes"]
        ]
        all_face_matched = [
            eye_record["face_matched_residual"]
            for frame_record in records
            for eye_record in frame_record["eyes"]
        ]
        temporal: dict[int, dict[str, float]] = {}
        for eye, sequences in eye_sequences.items():
            target = sequences["target"]
            temporal[eye] = {}
            for name in ("source", "direct", "matched"):
                values = [
                    float(
                        np.mean(
                            np.abs(
                                (sequences[name][index] - sequences[name][index - 1])
                                - (target[index] - target[index - 1])
                            )
                        )
                    )
                    for index in range(1, len(FRAME_IDS))
                ]
                temporal[eye][f"{name}_delta_error_mean"] = float(np.mean(values))
                temporal[eye][f"{name}_delta_error_p95"] = float(np.percentile(values, 95))
        aggregate = {
            "sample_count": len(all_matched),
            "direct_mae_mean": float(np.mean([item["mae"] for item in all_direct])),
            "matched_mae_mean": float(np.mean([item["mae"] for item in all_matched])),
            "raw_mae_mean": float(np.mean([item["raw_mae"] for item in all_matched])),
            "direct_improvement_vs_raw_mean": float(
                np.mean([item["improvement_vs_raw_mae"] for item in all_direct])
            ),
            "matched_improvement_vs_raw_mean": float(
                np.mean([item["improvement_vs_raw_mae"] for item in all_matched])
            ),
            "matched_better_than_direct_samples": int(
                sum(
                    matched["mae"] < direct["mae"]
                    for matched, direct in zip(all_matched, all_direct)
                )
            ),
            "matched_better_than_raw_samples": int(
                sum(item["improvement_vs_raw_mae"] > 0 for item in all_matched)
            ),
            "face_direct_mae_mean": float(np.mean([item["mae"] for item in all_face_direct])),
            "face_matched_mae_mean": float(np.mean([item["mae"] for item in all_face_matched])),
            "face_raw_mae_mean": float(np.mean([item["raw_mae"] for item in all_face_matched])),
            "temporal": temporal,
        }
        per_scale[scale] = {
            "scale_percent": scale,
            "network_dimensions": [small_width, small_height],
            "timing": timing_summary(scale_root / "timings.csv"),
            "aggregate": aggregate,
            "frames": records,
        }

    # Face sequence sheet: each row is a real frame, each column is a route.
    face_rows: list[tuple[str, list[tuple[str, np.ndarray]]]] = []
    for frame_id in SELECTED_FRAMES:
        first = preview_data[75][frame_id]
        face_rows.append(
            (
                f"F{frame_id}",
                [
                    ("Raw", first["source"]),
                    ("Residual 75%", preview_data[75][frame_id]["matched"]),
                    ("Residual 65%", preview_data[65][frame_id]["matched"]),
                    ("Residual 50%", preview_data[50][frame_id]["matched"]),
                    ("Teacher", first["target"]),
                ],
            )
        )
    save_grid(
        OUTPUT / "previews" / "eye0_face_sequence_residual_scales.jpg",
        face_rows,
        FACE_CROP,
        330,
    )
    full_rows = [
        (
            f"F{frame_id}",
            [
                ("Raw", preview_data[75][frame_id]["source"]),
                ("Residual 75%", preview_data[75][frame_id]["matched"]),
                ("Residual 65%", preview_data[65][frame_id]["matched"]),
                ("Residual 50%", preview_data[50][frame_id]["matched"]),
                ("Teacher", preview_data[75][frame_id]["target"]),
            ],
        )
        for frame_id in SELECTED_FRAMES
    ]
    save_grid(
        OUTPUT / "previews" / "eye0_full_sequence_residual_scales.jpg",
        full_rows,
        None,
        300,
    )

    result = {
        "schema": "opennr-native-sequence-residual-scale-evaluation-v1",
        "sequence": str(SEQUENCE),
        "frames": list(FRAME_IDS),
        "scales": per_scale,
        "face_crop_xyxy": list(FACE_CROP),
        "residual_definition": "full_input + bilinear(native_work - work_input), strength=1.0",
        "scope": (
            "One reset-qualified 16-frame native Feature 18 replay on a retained Skyrim "
            "sequence. This is an offline replay study; it does not establish live game, "
            "headset, stereo, or VR frame-budget acceptance."
        ),
        "promotion": False,
    }
    (OUTPUT / "result.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({scale: item["aggregate"] for scale, item in per_scale.items()}, indent=2))
    print(f"result={OUTPUT / 'result.json'}")
    print(f"face_preview={OUTPUT / 'previews' / 'eye0_face_sequence_residual_scales.jpg'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
