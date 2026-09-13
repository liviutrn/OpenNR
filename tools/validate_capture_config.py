#!/usr/bin/env python3
"""Validate an OpenNR Capture settings JSON before launching Skyrim VR."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


LIMITS = {
    "capture_rate_fps": (0.0, 240.0),
    "burst_frames": (1, 100_000),
    "crop_size": (16, 4096),
    "crop_count": (1, 4),
    "queue_capacity": (1, 64),
    "full_frame_every_samples": (0, 100_000_000),
    "max_samples": (0, 100_000_000),
}

BOOLEAN_KEYS = (
    "enable_capture",
    "capture_pre_nr",
    "capture_post_nr",
    "capture_raw_teacher",
    "capture_renderer_conditionings",
    "capture_depth",
    "capture_motion_vectors",
    "capture_full_frame",
    "capture_full_frame_sequence",
    "capture_left_eye",
    "capture_right_eye",
)


def _number(value: Any, key: str, errors: list[str]) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        errors.append(f"{key} must be numeric")
        return None
    return float(value)


def validate(document: Any) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    if not isinstance(document, dict):
        return {"valid": False, "errors": ["top-level JSON must be an object"], "warnings": []}

    settings = document.get("OpenNR Capture")
    if not isinstance(settings, dict):
        return {
            "valid": False,
            "errors": ["missing object: OpenNR Capture"],
            "warnings": [],
        }

    for key in BOOLEAN_KEYS:
        if key in settings and not isinstance(settings[key], bool):
            errors.append(f"{key} must be boolean")

    for key, (lower, upper) in LIMITS.items():
        if key not in settings:
            continue
        value = _number(settings[key], key, errors)
        if value is None:
            continue
        if value < lower or value > upper:
            errors.append(f"{key}={settings[key]!r} is outside [{lower}, {upper}]")
        if key != "capture_rate_fps" and value != int(value):
            errors.append(f"{key} must be an integer")

    for key in ("toggle_capture_key", "single_capture_key", "burst_capture_key"):
        if key not in settings:
            continue
        value = _number(settings[key], key, errors)
        if value is not None and (value < 0 or value > 255 or value != int(value)):
            errors.append(f"{key} must be an integer virtual-key code in [0, 255]")

    output = settings.get("output_directory")
    if output is not None and (not isinstance(output, str) or not output.strip()):
        errors.append("output_directory must be a non-empty string")

    crops = settings.get("crops")
    crop_count = settings.get("crop_count", 4)
    if crops is not None:
        if not isinstance(crops, list):
            errors.append("crops must be an array")
        else:
            if not crops:
                errors.append("crops must contain at least one preset")
            if len(crops) > 4:
                errors.append("crops may contain at most four presets")
            if isinstance(crop_count, int) and not isinstance(crop_count, bool) and len(crops) < crop_count:
                warnings.append("crop_count exceeds the preset count; the runtime will fill missing presets at center")
            for index, crop in enumerate(crops):
                if not isinstance(crop, dict):
                    errors.append(f"crops[{index}] must be an object")
                    continue
                for axis in ("center_x", "center_y"):
                    value = _number(crop.get(axis), f"crops[{index}].{axis}", errors)
                    if value is not None and not 0.0 <= value <= 1.0:
                        errors.append(f"crops[{index}].{axis} must be in [0, 1]")

    if settings.get("capture_full_frame_sequence", False) and not settings.get("capture_full_frame", True):
        warnings.append(
            "capture_full_frame_sequence is enabled while capture_full_frame is false; "
            "the runtime will not write full-frame artifacts"
        )

    return {"valid": not errors, "errors": errors, "warnings": warnings}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", type=Path, help="Open Shaders settings JSON")
    parser.add_argument("--json", action="store_true", dest="as_json", help="emit JSON (default output is also JSON)")
    args = parser.parse_args(argv)
    try:
        document = json.loads(args.config.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(json.dumps({"valid": False, "errors": [str(exc)], "warnings": []}, indent=2))
        return 1
    report = validate(document)
    print(json.dumps(report, indent=2))
    return 0 if report["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
