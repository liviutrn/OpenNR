"""Evaluate low-resolution native intensity and residual-strength combinations.

The native carrier is replayed at 50% and 33% physical color resolution with
three native intensity values.  This evaluator then applies four distinct
post-compositor residual strengths to the same native work output.  It keeps
the full-resolution captured input as the image anchor, and reports full-frame,
face-crop, and temporal metrics plus inspectable face contact sheets.
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
SELECTED_FRAMES = (1, 4, 8, 12, 16)
SCALES = (50, 33)
INTENSITIES = (1.0, 1.7, 2.0)
STRENGTHS = (0.5, 1.0, 1.5, 2.0)
SEQUENCE = Path(
    r"C:\OpenNR_Captures_FullEyeTemporalStateTranche_20260910\seq-1789064397821-5"
)
REPLAY_ROOT = Path(r"C:\OpenNR\NativeSequenceLowResIntensity_20260912")
BASELINE_ROOT = Path(r"C:\OpenNR\NativeSequenceResidualScales_20260912")
OUTPUT = Path(r"C:\OpenNR\NativeSequenceLowResIntensityStrengthEvaluation_20260912")
FACE_CROP = (1480, 700, 1980, 1300)


def intensity_label(intensity: float) -> str:
    return f"intensity_{intensity:.2f}".replace(".", "p")


def strength_key(strength: float) -> str:
    return f"{strength:.2f}"


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
        "better_fraction_pixels": float(np.mean(np.abs(error) < np.abs(source_error))),
    }


def timing_summary(path: Path) -> dict[str, float | int]:
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        raise ValueError(f"no timing rows in {path}")
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


def image(array: np.ndarray) -> Image.Image:
    if array.dtype == np.uint8:
        return Image.fromarray(array, mode="RGB")
    return Image.fromarray(as_u8(array), mode="RGB")


def save_grid(
    path: Path,
    rows: list[tuple[str, list[tuple[str, np.ndarray]]]],
    crop: tuple[int, int, int, int] | None,
    cell_width: int,
) -> None:
    label_height = 30
    row_label_width = 74
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
            draw.rectangle(
                (x, y, x + cell_width - 1, y + label_height - 1),
                fill=(22, 22, 22),
            )
            draw.text((x + 7, y + 8), label, fill=(245, 245, 245))
            canvas.paste(rendered_image, (x, y + label_height))
        y += label_height + cell_height
    path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(path, quality=95, subsampling=0)


def face_metric(pred: np.ndarray, target: np.ndarray, source: np.ndarray) -> dict[str, float]:
    x0, y0, x1, y1 = FACE_CROP
    return metric(
        pred[y0:y1, x0:x1],
        target[y0:y1, x0:x1],
        source[y0:y1, x0:x1],
    )


def aggregate_metrics(items: list[dict[str, float]]) -> dict[str, float]:
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


def temporal_summary(
    source_errors: dict[int, list[float]],
    strength_errors: dict[float, dict[int, list[float]]],
) -> dict[str, object]:
    result: dict[str, object] = {"source": {}}
    for eye, values in source_errors.items():
        result["source"][str(eye)] = {
            "delta_error_mean": float(np.mean(values)),
            "delta_error_p95": float(np.percentile(values, 95)),
        }
    for strength, per_eye in strength_errors.items():
        result[strength_key(strength)] = {}
        for eye, values in per_eye.items():
            result[strength_key(strength)][str(eye)] = {
                "delta_error_mean": float(np.mean(values)),
                "delta_error_p95": float(np.percentile(values, 95)),
            }
    return result


def load_composite(
    source_frame: Path,
    output_path: Path,
    work_input_path: Path,
    work_width: int,
    work_height: int,
    strength: float,
) -> np.ndarray:
    source = as_hwc(read_rgb8(source_frame, FULL_WIDTH, FULL_HEIGHT))
    work_input = read_rgb8(work_input_path, work_width, work_height)
    work_output = read_rgb8(output_path, work_width, work_height)
    residual = as_hwc(
        F.interpolate(
            work_output - work_input,
            size=(FULL_HEIGHT, FULL_WIDTH),
            mode="bilinear",
            align_corners=False,
        )
    )
    return np.clip(source + residual * strength, 0.0, 1.0)


def load_reference_composite(scale: int, frame_id: int, eye: int, strength: float) -> np.ndarray:
    source_frame = SEQUENCE / "frames" / f"frame_{frame_id:08d}"
    replay_frame = BASELINE_ROOT / f"scale{scale:03d}" / "frames" / f"frame_{frame_id:08d}"
    provenance = json.loads(
        (BASELINE_ROOT / f"scale{scale:03d}" / "provenance.json").read_text(encoding="utf-8")
    )
    width, height = (int(value) for value in provenance["network_dimensions"])
    return load_composite(
        source_frame / f"input_eye{eye}_full.raw.bin",
        replay_frame / f"teacher_eye{eye}.rgba",
        replay_frame / f"input_eye{eye}.rgba",
        width,
        height,
        strength,
    )


def main() -> int:
    if OUTPUT.exists() and any(OUTPUT.iterdir()):
        raise FileExistsError(f"refusing to use non-empty output directory: {OUTPUT}")
    OUTPUT.mkdir(parents=True, exist_ok=True)

    all_results: dict[str, object] = {}
    preview_data: dict[tuple[int, float, float], np.ndarray] = {}
    intensity_work_outputs: dict[int, dict[float, dict[tuple[int, int], np.ndarray]]] = {
        scale: {} for scale in SCALES
    }

    for scale in SCALES:
        print(f"evaluating scale {scale}%", flush=True)
        scale_results: dict[str, object] = {}
        for intensity in INTENSITIES:
            branch = (
                REPLAY_ROOT
                / f"scale{scale:03d}"
                / intensity_label(intensity)
            )
            provenance = json.loads((branch / "provenance.json").read_text(encoding="utf-8"))
            work_width, work_height = (
                int(value) for value in provenance["network_dimensions"]
            )
            records: list[dict[str, object]] = []
            aggregate_items: dict[float, list[dict[str, float]]] = {
                strength: [] for strength in STRENGTHS
            }
            aggregate_face_items: dict[float, list[dict[str, float]]] = {
                strength: [] for strength in STRENGTHS
            }
            source_errors: dict[int, list[float]] = {eye: [] for eye in range(2)}
            strength_errors: dict[float, dict[int, list[float]]] = {
                strength: {eye: [] for eye in range(2)} for strength in STRENGTHS
            }
            previous: dict[int, dict[str, np.ndarray] | None] = {eye: None for eye in range(2)}
            branch_work: dict[tuple[int, int], np.ndarray] = {}
            print(f"  intensity {intensity:.2f}", flush=True)

            for frame_id in FRAME_IDS:
                print(f"    frame {frame_id}", flush=True)
                source_frame = SEQUENCE / "frames" / f"frame_{frame_id:08d}"
                replay_frame = branch / "frames" / f"frame_{frame_id:08d}"
                input_frame = (
                    REPLAY_ROOT
                    / f"scale{scale:03d}"
                    / "inputs"
                    / f"frame_{frame_id:08d}"
                )
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
                    work_input_tensor = read_rgb8(
                        input_frame / f"input_eye{eye}.rgba", work_width, work_height
                    )
                    work_output_tensor = read_rgb8(
                        replay_frame / f"teacher_eye{eye}.rgba", work_width, work_height
                    )
                    branch_work[(frame_id, eye)] = as_hwc(work_output_tensor).copy()
                    direct = as_hwc(
                        F.interpolate(
                            work_output_tensor,
                            size=(FULL_HEIGHT, FULL_WIDTH),
                            mode="bilinear",
                            align_corners=False,
                        )
                    )
                    residual = as_hwc(
                        F.interpolate(
                            work_output_tensor - work_input_tensor,
                            size=(FULL_HEIGHT, FULL_WIDTH),
                            mode="bilinear",
                            align_corners=False,
                        )
                    )

                    if frame_id == 8 and eye == 0:
                        for strength in STRENGTHS:
                            preview_data[(scale, intensity, strength)] = as_u8(
                                np.clip(source + residual * strength, 0.0, 1.0)
                            )

                    direct_record = metric(direct, target, source)
                    eye_record: dict[str, object] = {
                        "eye": eye,
                        "direct": direct_record,
                        "strengths": {},
                    }

                    if previous[eye] is not None:
                        old = previous[eye]
                        target_delta = target - old["target"]
                        source_errors[eye].append(
                            float(np.mean(np.abs((source - old["source"]) - target_delta)))
                        )

                    for strength in STRENGTHS:
                        matched = np.clip(source + residual * strength, 0.0, 1.0)
                        full_metric = metric(matched, target, source)
                        face = face_metric(matched, target, source)
                        key = strength_key(strength)
                        eye_record["strengths"][key] = {
                            "matched_residual": full_metric,
                            "face_matched_residual": face,
                        }
                        aggregate_items[strength].append(full_metric)
                        aggregate_face_items[strength].append(face)
                        if previous[eye] is not None:
                            old = previous[eye]
                            old_matched = np.clip(
                                old["source"] + old["residual"] * strength,
                                0.0,
                                1.0,
                            )
                            strength_errors[strength][eye].append(
                                float(
                                    np.mean(
                                        np.abs(
                                            (matched - old_matched)
                                            - (target - old["target"])
                                        )
                                    )
                                )
                            )
                    eye_record["face_direct"] = face_metric(direct, target, source)
                    frame_record["eyes"].append(eye_record)
                    previous[eye] = {
                        "source": source,
                        "target": target,
                        "residual": residual,
                    }
                records.append(frame_record)

            strength_results: dict[str, object] = {}
            for strength in STRENGTHS:
                strength_results[strength_key(strength)] = {
                    "aggregate": aggregate_metrics(aggregate_items[strength]),
                    "face_aggregate": aggregate_metrics(aggregate_face_items[strength]),
                }

            scale_results[strength_key(intensity)] = {
                "scale_percent": scale,
                "intensity": intensity,
                "network_dimensions": [work_width, work_height],
                "timing": timing_summary(branch / "timings.csv"),
                "strengths": strength_results,
                "temporal": temporal_summary(source_errors, strength_errors),
                "frames": records,
            }
            intensity_work_outputs[scale][intensity] = branch_work

        pairwise: dict[str, dict[str, float | int]] = {}
        for left_index, left in enumerate(INTENSITIES):
            for right in INTENSITIES[left_index + 1 :]:
                values = [
                    float(
                        np.mean(
                            np.abs(
                                intensity_work_outputs[scale][left][key]
                                - intensity_work_outputs[scale][right][key]
                            )
                        )
                    )
                    for key in intensity_work_outputs[scale][left]
                ]
                exact = sum(
                    np.array_equal(
                        intensity_work_outputs[scale][left][key],
                        intensity_work_outputs[scale][right][key],
                    )
                    for key in intensity_work_outputs[scale][left]
                )
                pairwise[f"{left:.2f}_vs_{right:.2f}"] = {
                    "work_output_mae_mean": float(np.mean(values)),
                    "work_output_exact_samples": int(exact),
                    "sample_count": len(values),
                }
        all_results[str(scale)] = {
            "scale_percent": scale,
            "network_dimensions": list(
                json.loads(
                    (
                        REPLAY_ROOT
                        / f"scale{scale:03d}"
                        / intensity_label(INTENSITIES[0])
                        / "provenance.json"
                    ).read_text(encoding="utf-8")
                )["network_dimensions"]
            ),
            "intensities": scale_results,
            "pairwise_intensity_work_output": pairwise,
        }

    baseline_json = json.loads(
        (Path(r"C:\OpenNR\NativeSequenceResidualScaleEvaluation_20260912") / "result.json")
        .read_text(encoding="utf-8")
    )
    baseline: dict[str, object] = {}
    for scale in (75, 65, 50):
        entry = baseline_json["scales"][str(scale)]
        baseline[str(scale)] = {
            "scale_percent": scale,
            "intensity": 1.70,
            "network_dimensions": entry["network_dimensions"],
            "timing": entry["timing"],
            "strength_1p00": entry["aggregate"],
            "face_strength_1p00": {
                "mae_mean": entry["aggregate"]["face_matched_mae_mean"],
                "raw_mae_mean": entry["aggregate"]["face_raw_mae_mean"],
                "improvement_vs_raw_mae_mean": entry["aggregate"]["face_raw_mae_mean"]
                - entry["aggregate"]["face_matched_mae_mean"],
            },
        }

    previews = OUTPUT / "previews"
    for scale in SCALES:
        rows: list[tuple[str, list[tuple[str, np.ndarray]]]] = []
        for strength in STRENGTHS:
            rows.append(
                (
                    f"S={strength:.1f}x",
                    [
                        (
                            f"I={intensity:.1f}",
                            preview_data[(scale, intensity, strength)],
                        )
                        for intensity in INTENSITIES
                    ],
                )
            )
        save_grid(
            previews / f"frame_00000008_eye0_face_scale{scale:03d}_intensity_strength_grid.jpg",
            rows,
            FACE_CROP,
            330,
        )

    # A compact cross-route sheet makes the visual tradeoff easy to inspect.
    selected_rows: list[tuple[str, list[tuple[str, np.ndarray]]]] = []
    for frame_id in SELECTED_FRAMES:
        source_frame = SEQUENCE / "frames" / f"frame_{frame_id:08d}"
        raw = as_hwc(
            read_rgb8(
                source_frame / "input_eye0_full.raw.bin",
                FULL_WIDTH,
                FULL_HEIGHT,
            )
        )
        teacher = as_hwc(
            read_rgb8(
                source_frame / "teacher_eye0_full.raw.bin",
                FULL_WIDTH,
                FULL_HEIGHT,
            )
        )
        work_frame_50 = (
            REPLAY_ROOT / "scale050" / intensity_label(1.0) / "frames" / f"frame_{frame_id:08d}"
        )
        work_frame_33 = (
            REPLAY_ROOT / "scale033" / intensity_label(1.0) / "frames" / f"frame_{frame_id:08d}"
        )
        input_frame_50 = (
            REPLAY_ROOT / "scale050" / "inputs" / f"frame_{frame_id:08d}"
        )
        input_frame_33 = (
            REPLAY_ROOT / "scale033" / "inputs" / f"frame_{frame_id:08d}"
        )
        items = [
            ("Raw", raw),
            ("75% S1", load_reference_composite(75, frame_id, 0, 1.0)),
            ("65% S1", load_reference_composite(65, frame_id, 0, 1.0)),
            ("50% S1", load_composite(
                source_frame / "input_eye0_full.raw.bin",
                work_frame_50 / "teacher_eye0.rgba",
                input_frame_50 / "input_eye0.rgba",
                1248,
                1344,
                1.0,
            )),
            ("50% S2", load_composite(
                source_frame / "input_eye0_full.raw.bin",
                work_frame_50 / "teacher_eye0.rgba",
                input_frame_50 / "input_eye0.rgba",
                1248,
                1344,
                2.0,
            )),
            ("33% S1", load_composite(
                source_frame / "input_eye0_full.raw.bin",
                work_frame_33 / "teacher_eye0.rgba",
                input_frame_33 / "input_eye0.rgba",
                824,
                887,
                1.0,
            )),
            ("33% S2", load_composite(
                source_frame / "input_eye0_full.raw.bin",
                work_frame_33 / "teacher_eye0.rgba",
                input_frame_33 / "input_eye0.rgba",
                824,
                887,
                2.0,
            )),
            ("Teacher", teacher),
        ]
        selected_rows.append((f"F{frame_id}", items))
    save_grid(
        previews / "eye0_face_cross_route_strength_comparison.jpg",
        selected_rows,
        FACE_CROP,
        280,
    )

    result = {
        "schema": "opennr-native-sequence-lowres-intensity-strength-evaluation-v1",
        "sequence": str(SEQUENCE),
        "frames": list(FRAME_IDS),
        "full_dimensions": [FULL_WIDTH, FULL_HEIGHT],
        "face_crop_xyxy": list(FACE_CROP),
        "native_scales": list(SCALES),
        "native_intensities": list(INTENSITIES),
        "post_compositor_strengths": list(STRENGTHS),
        "lowres_results": all_results,
        "existing_baseline_results": baseline,
        "residual_definition": "full_input + bilinear(native_work - work_input) * strength",
        "scope": (
            "Offline native Feature 18 replay using one retained 16-frame Skyrim sequence. "
            "Each scale/intensity branch is reset-qualified at frame 1 and contiguous through "
            "frame 16. Captured depth and motion remain exact guides. This does not establish "
            "live game, headset, stereo, temporal-stress, or VR frame-budget acceptance."
        ),
        "promotion": False,
    }
    (OUTPUT / "result.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({scale: item for scale, item in all_results.items()}, indent=2))
    print(f"result={OUTPUT / 'result.json'}")
    print(f"face_grid_50={previews / 'frame_00000008_eye0_face_scale050_intensity_strength_grid.jpg'}")
    print(f"face_grid_33={previews / 'frame_00000008_eye0_face_scale033_intensity_strength_grid.jpg'}")
    print(f"cross_route={previews / 'eye0_face_cross_route_strength_comparison.jpg'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
