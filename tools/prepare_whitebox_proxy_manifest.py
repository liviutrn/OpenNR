#!/usr/bin/env python3
"""Prepare a sequence-disjoint full-eye manifest for white-box proxy targets.

The manifest is intentionally separate from the native OpenNR manifests.  It
selects a small, deterministic set of full-frame Skyrim samples, keeps the
native input/teacher/depth/motion provenance, and assigns entire sequences to
train, validation, or test.  It does not modify the capture tree.

The default pilot uses frame IDs 1, 8, and 16 from every selected sequence.
The white-box target generator later runs on the complete eye image and crops
the result, preserving the recovered graph's whole-frame context.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any


COLOR_FORMAT = "R8G8B8A8_UNORM"
DEPTH_FORMAT = "R32_FLOAT"
MOTION_FORMAT = "R16G16_FLOAT"
REQUIRED_STAGES = ("input", "teacher", "depth", "motion_vectors")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def read_frames(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise ValueError(f"{path}:{line_number}: expected JSON object")
        rows.append(value)
    return rows


def split_sequence_ids(entries: list[dict[str, Any]]) -> dict[str, list[str] | str]:
    """Use the repository's deterministic chronological 60/20/20 policy."""

    ordered = sorted(entries, key=lambda item: (int(item["created_utc"]), item["sequence_id"]))
    if len(ordered) < 3:
        raise ValueError("at least three sequences are required for an independent test split")
    test_count = max(1, math.ceil(len(ordered) * 0.2))
    validation_count = max(1, math.ceil((len(ordered) - test_count) * 0.2))
    train = ordered[: -(test_count + validation_count)]
    validation = ordered[-(test_count + validation_count) : -test_count]
    test = ordered[-test_count:]
    if not train or not validation or not test:
        raise ValueError("sequence split did not produce all three non-empty splits")
    return {
        "train": [item["sequence_id"] for item in train],
        "validation": [item["sequence_id"] for item in validation],
        "test": [item["sequence_id"] for item in test],
        "policy": "deterministic chronological sequence-level 60/20/20 split",
    }


def artifact_map(frame: dict[str, Any], sequence_id: str) -> dict[tuple[str, int], dict[str, Any]]:
    values = frame.get("artifacts")
    if not isinstance(values, list):
        raise ValueError(f"{sequence_id} frame {frame.get('frame_id')}: artifacts is not an array")
    result: dict[tuple[str, int], dict[str, Any]] = {}
    for item in values:
        if not isinstance(item, dict) or not item.get("full_frame"):
            continue
        try:
            key = (str(item["stage"]), int(item["eye"]))
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"{sequence_id} frame {frame.get('frame_id')}: malformed artifact") from exc
        if key in result:
            raise ValueError(f"{sequence_id} frame {frame.get('frame_id')}: duplicate full artifact {key}")
        result[key] = item
    return result


def safe_relative_path(sequence: Path, value: Any) -> Path:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{sequence}: missing artifact path")
    path = (sequence / value).resolve()
    try:
        path.relative_to(sequence.resolve())
    except ValueError as exc:
        raise ValueError(f"unsafe artifact path {value!r} under {sequence}") from exc
    if not path.is_file() or path.stat().st_size == 0:
        raise ValueError(f"missing or empty artifact: {path}")
    return path


def require_artifact(
    sequence: Path,
    maps: dict[tuple[str, int], dict[str, Any]],
    stage: str,
    eye: int,
    expected_format: str,
) -> tuple[dict[str, Any], Path]:
    artifact = maps.get((stage, eye))
    if artifact is None:
        raise ValueError(f"{sequence.name} frame: missing full {stage} eye {eye}")
    if artifact.get("format_name") != expected_format:
        raise ValueError(
            f"{sequence.name} frame: {stage} eye {eye} has format "
            f"{artifact.get('format_name')!r}, expected {expected_format!r}"
        )
    if not artifact.get("raw_written") or not artifact.get("raw_path"):
        raise ValueError(f"{sequence.name} frame: {stage} eye {eye} raw artifact is not committed")
    raw_path = safe_relative_path(sequence, artifact["raw_path"])
    expected_bytes = int(artifact["row_pitch"]) * int(artifact["height"])
    if raw_path.stat().st_size != expected_bytes:
        raise ValueError(f"{raw_path}: size does not match row pitch and height")
    return artifact, raw_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True, help="JSONL manifest to create")
    parser.add_argument(
        "--sequence",
        action="append",
        help="sequence directory name; repeat to limit the pilot (default: every sequence)",
    )
    parser.add_argument(
        "--frame-id",
        type=int,
        action="append",
        help="full-frame ID to select; repeat as needed (default: 1, 8, 16)",
    )
    parser.add_argument(
        "--all-frames",
        action="store_true",
        help="select frame IDs 1 through 16 from every sequence",
    )
    args = parser.parse_args()

    root = args.capture_root.expanduser().resolve()
    output = args.output.expanduser().resolve()
    if not root.is_dir():
        raise FileNotFoundError(root)
    if output.exists():
        raise FileExistsError(f"refusing to overwrite existing manifest: {output}")
    if args.all_frames and args.frame_id:
        raise ValueError("--all-frames cannot be combined with --frame-id")
    frame_ids = list(range(1, 17)) if args.all_frames else sorted(set(args.frame_id or [1, 8, 16]))
    if not frame_ids or any(value < 1 for value in frame_ids):
        raise ValueError("frame IDs must be positive")

    requested = set(args.sequence or [])
    sequence_dirs = [path for path in root.iterdir() if path.is_dir() and (path / "sequence.json").is_file()]
    if requested:
        unknown = requested - {path.name for path in sequence_dirs}
        if unknown:
            raise ValueError(f"requested sequence(s) not found: {sorted(unknown)}")
        sequence_dirs = [path for path in sequence_dirs if path.name in requested]
    sequence_dirs.sort(key=lambda path: path.name)
    if len(sequence_dirs) < 3:
        raise ValueError("the pilot needs at least three sequence directories")

    sequence_entries: list[dict[str, Any]] = []
    loaded: dict[str, tuple[Path, dict[str, Any], dict[int, dict[str, Any]]]] = {}
    reference_signature: tuple[Any, ...] | None = None
    reference_teacher_settings: Any = None
    for sequence in sequence_dirs:
        metadata = read_json(sequence / "sequence.json")
        sequence_id = str(metadata.get("sequence_id") or sequence.name)
        if sequence_id != sequence.name:
            raise ValueError(f"{sequence}: sequence identity mismatch")
        frames = read_frames(sequence / "frames.jsonl")
        by_id = {int(frame.get("frame_id", -1)): frame for frame in frames}
        missing = [frame_id for frame_id in frame_ids if frame_id not in by_id]
        if missing:
            raise ValueError(f"{sequence_id}: requested frame IDs missing: {missing}")
        if 1 not in by_id or by_id[1].get("history_reset") != [True, True]:
            raise ValueError(f"{sequence_id}: sequence does not begin with [true,true] history reset")
        for frame_id in frame_ids:
            frame = by_id[frame_id]
            if frame.get("status") != "complete":
                raise ValueError(f"{sequence_id} frame {frame_id}: status is not complete")
            if frame.get("route") != "feature18_stereo":
                raise ValueError(f"{sequence_id} frame {frame_id}: route is not feature18_stereo")
            if int(frame.get("pass_count", 0)) != 1 or int(frame.get("model_resolution_percent", 0)) != 100:
                raise ValueError(f"{sequence_id} frame {frame_id}: expected 100% single-pass Feature 18")
            if frame.get("motion_vector_contract") != "exact_feature18_bound_resource":
                raise ValueError(f"{sequence_id} frame {frame_id}: motion-vector contract changed")
            signature = (
                int(frame["color_width"]),
                int(frame["color_height"]),
                int(frame["guide_width"]),
                int(frame["guide_height"]),
                json.dumps(frame.get("teacher_settings"), sort_keys=True),
            )
            if reference_signature is None:
                reference_signature = signature
                reference_teacher_settings = frame.get("teacher_settings")
            elif signature != reference_signature:
                raise ValueError(f"{sequence_id} frame {frame_id}: capture signature differs from the pilot")
            if frame_id != 1 and any(bool(value) for value in frame.get("history_reset", [])):
                raise ValueError(f"{sequence_id} frame {frame_id}: mid-sequence reset is not allowed")
            maps = artifact_map(frame, sequence_id)
            for eye in (0, 1):
                input_artifact, input_raw = require_artifact(sequence, maps, "input", eye, COLOR_FORMAT)
                teacher_artifact, teacher_raw = require_artifact(sequence, maps, "teacher", eye, COLOR_FORMAT)
                depth_artifact, depth_raw = require_artifact(sequence, maps, "depth", eye, DEPTH_FORMAT)
                motion_artifact, motion_raw = require_artifact(sequence, maps, "motion_vectors", eye, MOTION_FORMAT)
                if not input_artifact.get("png_path") or not teacher_artifact.get("png_path"):
                    raise ValueError(f"{sequence_id} frame {frame_id} eye {eye}: color PNG preview is required by the base cache builder")
                input_png = safe_relative_path(sequence, input_artifact["png_path"])
                teacher_png = safe_relative_path(sequence, teacher_artifact["png_path"])
                if input_png.with_suffix(".raw.bin") != input_raw or teacher_png.with_suffix(".raw.bin") != teacher_raw:
                    raise ValueError(f"{sequence_id} frame {frame_id} eye {eye}: PNG/raw artifact pairing is not canonical")
                if [int(input_artifact["width"]), int(input_artifact["height"])] != [int(frame["color_width"]), int(frame["color_height"])]:
                    raise ValueError(f"{sequence_id} frame {frame_id} eye {eye}: input dimensions do not match frame contract")
                if [int(depth_artifact["width"]), int(depth_artifact["height"])] != [int(frame["guide_width"]), int(frame["guide_height"])] or [int(motion_artifact["width"]), int(motion_artifact["height"])] != [int(frame["guide_width"]), int(frame["guide_height"])] :
                    raise ValueError(f"{sequence_id} frame {frame_id} eye {eye}: guide dimensions do not match frame contract")
        sequence_entries.append(
            {
                "sequence_id": sequence_id,
                "created_utc": int(metadata.get("created_utc", 0)),
                "source_sequence": str(sequence),
                "source_sequence_sha256": sha256_file(sequence / "sequence.json"),
                "source_frames_sha256": sha256_file(sequence / "frames.jsonl"),
                "selected_frame_ids": frame_ids,
            }
        )
        loaded[sequence_id] = (sequence, metadata, by_id)

    split = split_sequence_ids(sequence_entries)
    membership = {sequence_id: split_name for split_name in ("train", "validation", "test") for sequence_id in split[split_name]}
    rows: list[dict[str, Any]] = []
    for entry in sorted(sequence_entries, key=lambda item: (int(item["created_utc"]), item["sequence_id"])):
        sequence_id = entry["sequence_id"]
        sequence, _metadata, by_id = loaded[sequence_id]
        split_name = membership[sequence_id]
        for frame_id in frame_ids:
            frame = by_id[frame_id]
            maps = artifact_map(frame, sequence_id)
            for eye in (0, 1):
                input_artifact, input_raw = require_artifact(sequence, maps, "input", eye, COLOR_FORMAT)
                teacher_artifact, teacher_raw = require_artifact(sequence, maps, "teacher", eye, COLOR_FORMAT)
                _depth_artifact, depth_raw = require_artifact(sequence, maps, "depth", eye, DEPTH_FORMAT)
                _motion_artifact, motion_raw = require_artifact(sequence, maps, "motion_vectors", eye, MOTION_FORMAT)
                rows.append(
                    {
                        "schema_version": 1,
                        "source": "opennr_full_eye_whitebox_proxy_pilot",
                        "sequence_id": sequence_id,
                        "sequence_root": str(sequence),
                        "frame_id": int(frame["frame_id"]),
                        "sample_index": int(frame["sample_index"]),
                        "host_frame": int(frame["host_frame"]),
                        "eye": eye,
                        "split": split_name,
                        "color_size": [int(frame["color_width"]), int(frame["color_height"])],
                        "guide_size": [int(frame["guide_width"]), int(frame["guide_height"])],
                        "paths": {
                            "input": str(safe_relative_path(sequence, input_artifact["png_path"])),
                            "teacher": str(safe_relative_path(sequence, teacher_artifact["png_path"])),
                            "depth": str(depth_raw),
                            "motion_vectors": str(motion_raw),
                        },
                        "raw_paths": {
                            "input": str(input_raw),
                            "teacher": str(teacher_raw),
                            "depth": str(depth_raw),
                            "motion_vectors": str(motion_raw),
                        },
                        "motion_scale": [
                            float(frame["motion_vector_scale_x"][eye]),
                            float(frame["motion_vector_scale_y"][eye]),
                        ],
                        "history_reset": bool(frame["history_reset"][eye]),
                        "history_reset_pair": [bool(value) for value in frame["history_reset"]],
                        "teacher_settings": frame.get("teacher_settings"),
                        "route": frame["route"],
                        "model_resolution_percent": int(frame["model_resolution_percent"]),
                        "pass_count": int(frame["pass_count"]),
                        "motion_vector_contract": frame["motion_vector_contract"],
                    }
                )

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(json.dumps(row, sort_keys=True) for row in rows) + "\n", encoding="utf-8")
    summary = {
        "schema": "opennr-whitebox-proxy-source-manifest-v1",
        "capture_root": str(root),
        "manifest": str(output),
        "manifest_sha256": sha256_file(output),
        "selected_frame_ids": frame_ids,
        "all_frames_requested": bool(args.all_frames),
        "sequence_count": len(sequence_entries),
        "frame_count": len(sequence_entries) * len(frame_ids),
        "eye_rows": len(rows),
        "split": split,
        "eye_rows_by_split": {name: sum(row["split"] == name for row in rows) for name in ("train", "validation", "test")},
        "capture_signature": reference_signature,
        "teacher_settings": reference_teacher_settings,
        "source_sequences": sequence_entries,
        "target_policy": "run recovered graph on complete full eye; crop only after inference",
        "native_teacher_retained": True,
        "training_started": False,
    }
    summary_path = output.with_suffix(".summary.json")
    summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
