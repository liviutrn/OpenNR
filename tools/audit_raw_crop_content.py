#!/usr/bin/env python3
"""Audit raw crop payloads for motion validity and teacher-effect evidence."""

from __future__ import annotations

import argparse
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
from typing import Any

import numpy as np

from build_raw_crop_cache import _raw_memmap, build_rows


def _motion_stats(row: dict[str, Any]) -> dict[str, Any]:
    artifact = row["artifacts"]["motion_vectors"]
    width = int(artifact["width"])
    height = int(artifact["height"])
    row_pitch = int(artifact["row_pitch"])
    values = np.memmap(
        row["paths"]["motion_vectors"],
        mode="r",
        dtype="<f2",
        shape=(height, row_pitch // 2),
    )[:, : width * 2].reshape(height, width, 2)
    component_valid = np.isfinite(values) & (np.abs(values) <= 0.25)
    valid = component_valid.all(axis=2)
    return {
        "sequence": str(row["sequence_id"]),
        "frame": int(row["frame_id"]),
        "eye": int(row["eye"]),
        "crop": int(row.get("crop_index", 0)),
        "zero_motion": bool(np.all(values == 0)),
        "invalid_pixels": int((~valid).sum()),
        "total_pixels": int(valid.size),
        "invalid_pixel_fraction": float((~valid).mean()),
        "invalid_components": int((~component_valid).sum()),
        "total_components": int(values.size),
        "nonzero_components": int(np.count_nonzero(values)),
        "minimum": float(np.nanmin(values)),
        "maximum": float(np.nanmax(values)),
    }


def _teacher_effect(row: dict[str, Any]) -> tuple[float, float]:
    values: dict[str, np.ndarray] = {}
    for stage in ("input", "teacher"):
        artifact = row["artifacts"][stage]
        values[stage] = _raw_memmap(
            row["paths"][stage],
            int(artifact["width"]),
            int(artifact["height"]),
            4,
            "u1",
            int(artifact["row_pitch"]),
        )[:, :, :3]
    difference = np.abs(values["teacher"].astype(np.float32) - values["input"].astype(np.float32)) / 255.0
    return float(difference.mean()), float((difference.mean(axis=2) > 0.05).mean())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument(
        "--crop-index",
        type=int,
        action="append",
        help="crop index to audit; may be supplied multiple times (default: 0)",
    )
    parser.add_argument(
        "--all-crops",
        action="store_true",
        help="audit crop indices 0 through 3",
    )
    parser.add_argument("--severe-invalid-pixel-fraction", type=float, default=0.5)
    parser.add_argument("--teacher-effect-threshold", type=float, default=0.01)
    args = parser.parse_args()
    if args.workers < 1:
        parser.error("--workers must be positive")
    if args.all_crops and args.crop_index:
        parser.error("--all-crops cannot be combined with --crop-index")
    crop_indices = tuple(range(4)) if args.all_crops else tuple(args.crop_index or [0])
    if not 0.0 < args.severe_invalid_pixel_fraction <= 1.0:
        parser.error("--severe-invalid-pixel-fraction must be in (0, 1]")
    rows, split, provenance = build_rows(
        args.manifest.resolve(), crop_indices=crop_indices
    )
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        stats = list(pool.map(_motion_stats, rows))
    by_sequence: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in stats:
        by_sequence[item["sequence"]].append(item)

    affected: list[dict[str, Any]] = []
    excluded_for_temporal: list[str] = []
    for sequence in sorted(by_sequence):
        items = by_sequence[sequence]
        zero_items = [item for item in items if item["zero_motion"]]
        invalid_items = [item for item in items if item["invalid_pixels"]]
        effect_values: list[float] = []
        changed_values: list[float] = []
        if zero_items:
            zero_rows = [
                row
                for row in rows
                if row["sequence_id"] == sequence
                and any(
                    item["frame"] == int(row["frame_id"])
                    and item["eye"] == int(row["eye"])
                    and item["crop"] == int(row.get("crop_index", 0))
                    and item["zero_motion"]
                    for item in zero_items
                )
            ]
            with ThreadPoolExecutor(max_workers=args.workers) as pool:
                effects = list(pool.map(_teacher_effect, zero_rows))
            effect_values = [value[0] for value in effects]
            changed_values = [value[1] for value in effects]
        max_invalid_pixel_fraction = max(
            (item["invalid_pixel_fraction"] for item in items), default=0.0
        )
        temporal_exclusion_reasons: list[str] = []
        if zero_items and max(effect_values, default=0.0) >= args.teacher_effect_threshold:
            temporal_exclusion_reasons.append("zero_motion_with_teacher_effect")
        if max_invalid_pixel_fraction >= args.severe_invalid_pixel_fraction:
            temporal_exclusion_reasons.append("severe_invalid_motion_pixel_fraction")
        if temporal_exclusion_reasons:
            excluded_for_temporal.append(sequence)
        if zero_items or invalid_items:
            affected.append(
                {
                    "sequence": sequence,
                    "split": next(row["split"] for row in rows if row["sequence_id"] == sequence),
                    "eye_rows": len(items),
                    "zero_motion_rows": len(zero_items),
                    "zero_motion_crops": sorted({item["crop"] for item in zero_items}),
                    "zero_motion_frames_by_eye": {
                        str(eye): sorted({item["frame"] for item in zero_items if item["eye"] == eye})
                        for eye in (0, 1)
                    },
                    "invalid_motion_rows": len(invalid_items),
                    "invalid_motion_crops": sorted({item["crop"] for item in invalid_items}),
                    "max_invalid_pixel_fraction": max_invalid_pixel_fraction,
                    "max_invalid_component_fraction": max(
                        (item["invalid_components"] / max(1, item["total_components"]) for item in items),
                        default=0.0,
                    ),
                    "invalid_pixels_total": sum(item["invalid_pixels"] for item in items),
                    "zero_teacher_input_mae_mean": float(np.mean(effect_values)) if effect_values else None,
                    "zero_teacher_input_mae_min": float(np.min(effect_values)) if effect_values else None,
                    "zero_teacher_input_mae_max": float(np.max(effect_values)) if effect_values else None,
                    "zero_changed_fraction_mean": float(np.mean(changed_values)) if changed_values else None,
                    "zero_changed_fraction_max": float(np.max(changed_values)) if changed_values else None,
                    "temporal_exclusion_reasons": temporal_exclusion_reasons,
                }
            )

    report = {
        "schema": "opennr-raw-crop-content-audit-v1",
        "manifest": str(args.manifest.resolve()),
        "capture_root": provenance["capture_root"],
        "sequences": len(provenance["source_sequences"]),
        "frames": sum(int(item["frames"]) for item in provenance["source_sequences"]),
        "eye_rows": len(rows),
        "crop_indices": list(crop_indices),
        "motion_rows_scanned": len(stats),
        "all_zero_motion_eye_rows": sum(item["zero_motion"] for item in stats),
        "invalid_motion_eye_rows": sum(item["invalid_pixels"] > 0 for item in stats),
        "invalid_motion_pixels": sum(item["invalid_pixels"] for item in stats),
        "affected_sequences": affected,
        "temporal_exclusion_sequences": excluded_for_temporal,
        "temporal_exclusion_count": len(excluded_for_temporal),
        "thresholds": {
            "motion_valid_abs_bound": 0.25,
            "severe_invalid_pixel_fraction": args.severe_invalid_pixel_fraction,
            "teacher_effect_threshold": args.teacher_effect_threshold,
        },
        "split_sequences": {name: len(ids) for name, ids in split.items() if name != "policy"},
        "split_eye_rows": {
            name: sum(row["split"] == name for row in rows) for name in ("train", "validation", "test")
        },
        "scope": (
            "Raw motion payload quality and input-teacher effect evidence. "
            "The builder validity mask handles isolated invalid motion pixels; "
            "temporal exclusions are conservative sequence-level decisions."
        ),
    }
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({
        "state": "completed",
        "output": str(output),
        "sequences": report["sequences"],
        "frames": report["frames"],
        "eye_rows": report["eye_rows"],
        "all_zero_motion_eye_rows": report["all_zero_motion_eye_rows"],
        "invalid_motion_eye_rows": report["invalid_motion_eye_rows"],
        "temporal_exclusion_sequences": report["temporal_exclusion_sequences"],
    }, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
