"""Build a training cache directly from OpenNR raw crop captures.

The 0.5.3 no-preview capture deliberately leaves ``png_path`` empty while
keeping typed raw color, depth, and motion-vector readbacks.  The historical
cache builder expects full-eye rows whose color paths point at PNG files, so it
cannot consume that capture contract without first recreating the PNG write
pressure that the new capture path removed.

This builder is a separate, source-backed path for the crop contract.  It
keeps the existing ``rgb.npy``, ``guides.npy``, ``context.npy``,
``patches.json``, ``rows.json`` and ``complete.json`` cache schema consumed by
``train_student.py`` and ``train_long_student.py``.  Each audited crop eye is
one 512x512 training item; horizontal augmentation remains the trainer's
responsibility.  The capture tree is never modified.  The normal builder
requires three sequences for an independent train/validation/test split; an
explicit two-sequence pilot flag creates only train/validation and records that
the pilot has no independent test split.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import math
from pathlib import Path
import time
from typing import Any

import numpy as np
from PIL import Image
import torch

from master_dataset import sample_guide


EXPECTED_CROP_SIZE = 512
GUIDE_PATCH_SIZE = 128
CONTEXT_SIZE = 96
REQUIRED_STAGES = ("input", "teacher", "depth", "motion_vectors")
EXPECTED_FORMATS = {
    "input": "R8G8B8A8_UNORM",
    "teacher": "R8G8B8A8_UNORM",
    "depth": "R32_FLOAT",
    "motion_vectors": "R16G16_FLOAT",
}
SPLITS = ("train", "validation", "test")


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"expected a JSON object in {path}")
    return value


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _stable_sha256(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _safe_path(root: Path, relative: Any) -> Path:
    if not isinstance(relative, str) or not relative:
        raise ValueError(f"missing relative path under {root}")
    candidate = (root / relative).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError(f"unsafe path {relative!r} under {root}") from exc
    if not candidate.is_file() or candidate.stat().st_size == 0:
        raise ValueError(f"missing or empty raw artifact {candidate}")
    return candidate


def _split_sequence_ids(
    entries: list[dict[str, Any]], allow_two_sequence_pilot: bool = False
) -> dict[str, Any]:
    """Match the project's deterministic single-session 60/20/20 policy."""

    ordered = sorted(entries, key=lambda item: (int(item["created_utc"]), item["sequence_id"]))
    if len(ordered) < 3:
        if allow_two_sequence_pilot and len(ordered) == 2:
            return {
                "train": [ordered[0]["sequence_id"]],
                "validation": [ordered[1]["sequence_id"]],
                "test": [],
                "policy": "explicit two-sequence temporal pilot; chronological train/validation split; independent test unavailable",
            }
        raise ValueError("at least three sequences are required for train/validation/test")
    test_count = max(1, math.ceil(len(ordered) * 0.2))
    validation_count = max(1, math.ceil((len(ordered) - test_count) * 0.2))
    train = ordered[: -(test_count + validation_count)]
    validation = ordered[-(test_count + validation_count) : -test_count]
    test = ordered[-test_count:]
    if not train or not validation or not test:
        raise ValueError("sequence split did not produce all three non-empty splits")
    return {
        "train": [row["sequence_id"] for row in train],
        "validation": [row["sequence_id"] for row in validation],
        "test": [row["sequence_id"] for row in test],
        "policy": "deterministic chronological sequence-level 60/20/20 split",
    }


def _candidate_entries(candidate: dict[str, Any], capture_root_override: Path | None) -> tuple[Path, list[dict[str, Any]]]:
    if candidate.get("schema") != "opennr-crop-training-candidate-v1":
        raise ValueError("candidate manifest is not opennr-crop-training-candidate-v1")
    root_value = candidate.get("capture_root")
    if capture_root_override is not None:
        root = capture_root_override.resolve()
    elif isinstance(root_value, str) and root_value:
        root = Path(root_value).resolve()
    else:
        raise ValueError("candidate manifest has no capture_root")
    if not root.is_dir():
        raise ValueError(f"capture root does not exist: {root}")

    raw_entries = candidate.get("sequences")
    if not isinstance(raw_entries, list) or not raw_entries:
        raise ValueError("candidate manifest contains no sequences")
    entries: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in raw_entries:
        if not isinstance(raw, dict):
            raise ValueError("candidate sequence entry is not an object")
        sequence_id = str(raw.get("sequence") or raw.get("sequence_id") or "")
        if not sequence_id or sequence_id in seen:
            raise ValueError(f"duplicate or missing candidate sequence id: {sequence_id!r}")
        seen.add(sequence_id)
        try:
            created_utc = int(raw["created_utc"])
            expected_frames = int(raw["frames"])
            expected_complete = int(raw["complete"])
            expected_artifacts = int(raw["artifact_count"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"malformed candidate summary for {sequence_id}") from exc
        if expected_frames < 2 or expected_complete != expected_frames:
            raise ValueError(f"candidate sequence {sequence_id} is not a complete clip")
        entries.append(
            {
                "sequence_id": sequence_id,
                "created_utc": created_utc,
                "expected_frames": expected_frames,
                "expected_complete": expected_complete,
                "expected_artifacts": expected_artifacts,
            }
        )
    if int(candidate.get("candidate_sequences", len(entries))) != len(entries):
        raise ValueError("candidate sequence count does not match its entries")
    return root, sorted(entries, key=lambda item: (item["created_utc"], item["sequence_id"]))


def _artifact_map(
    frame: dict[str, Any], sequence_id: str, selected_crop_index: int = 0
) -> dict[tuple[str, int], dict[str, Any]]:
    artifacts = frame.get("artifacts")
    if not isinstance(artifacts, list):
        raise ValueError(f"{sequence_id} frame {frame.get('frame_id')}: artifacts is not an array")
    result: dict[tuple[str, int], dict[str, Any]] = {}
    for artifact in artifacts:
        if not isinstance(artifact, dict) or artifact.get("full_frame", False):
            continue
        try:
            stage = str(artifact["stage"])
            eye = int(artifact["eye"])
            crop_index = int(artifact["crop_index"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"{sequence_id} frame {frame.get('frame_id')}: malformed crop artifact") from exc
        if crop_index != int(selected_crop_index):
            continue
        key = (stage, eye)
        if key in result:
            raise ValueError(f"{sequence_id} frame {frame.get('frame_id')}: duplicate crop artifact {key}")
        result[key] = artifact
    return result


def _validate_frame_signature(frame: dict[str, Any], sequence_id: str, signature: tuple[Any, ...] | None) -> tuple[Any, ...]:
    if frame.get("status") != "complete":
        raise ValueError(f"{sequence_id} frame {frame.get('frame_id')}: status is not complete")
    if frame.get("route") != "feature18_stereo":
        raise ValueError(f"{sequence_id} frame {frame.get('frame_id')}: route is not feature18_stereo")
    if int(frame.get("model_resolution_percent", 0)) != 100 or int(frame.get("pass_count", 0)) != 1:
        raise ValueError(f"{sequence_id} frame {frame.get('frame_id')}: expected 100% single-pass Feature 18")
    if frame.get("motion_vector_contract") != "exact_feature18_bound_resource":
        raise ValueError(f"{sequence_id} frame {frame.get('frame_id')}: motion-vector contract changed")
    try:
        color_size = (int(frame["color_width"]), int(frame["color_height"]))
        guide_size = (int(frame["guide_width"]), int(frame["guide_height"]))
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"{sequence_id} frame {frame.get('frame_id')}: invalid source dimensions") from exc
    if min(*color_size, *guide_size) <= 0:
        raise ValueError(f"{sequence_id} frame {frame.get('frame_id')}: non-positive source dimensions")
    current = (
        frame.get("route"),
        frame.get("model_resolution_percent"),
        frame.get("pass_count"),
        color_size,
        guide_size,
        json.dumps(frame.get("teacher_settings"), sort_keys=True),
    )
    if signature is not None and current != signature:
        raise ValueError(f"{sequence_id} frame {frame.get('frame_id')}: capture signature changed")
    return current


def _make_row(
    sequence_root: Path,
    sequence_id: str,
    frame: dict[str, Any],
    eye: int,
    split: str,
    crop_index: int = 0,
) -> dict[str, Any]:
    artifacts = _artifact_map(frame, sequence_id, crop_index)
    selected: dict[str, dict[str, Any]] = {}
    for stage in REQUIRED_STAGES:
        artifact = artifacts.get((stage, eye))
        if artifact is None:
            raise ValueError(f"{sequence_id} frame {frame.get('frame_id')}: missing {stage} eye {eye}")
        if not bool(artifact.get("raw_required")) or not bool(artifact.get("raw_written")):
            raise ValueError(f"{sequence_id} frame {frame.get('frame_id')}: {stage} eye {eye} raw is not committed")
        if artifact.get("format_name") != EXPECTED_FORMATS[stage]:
            raise ValueError(
                f"{sequence_id} frame {frame.get('frame_id')}: {stage} format {artifact.get('format_name')!r}"
            )
        if int(artifact.get("width", 0)) != EXPECTED_CROP_SIZE or int(artifact.get("height", 0)) != EXPECTED_CROP_SIZE:
            raise ValueError(f"{sequence_id} frame {frame.get('frame_id')}: {stage} is not 512x512")
        row_pitch = int(artifact.get("row_pitch", 0))
        if row_pitch <= 0:
            raise ValueError(f"{sequence_id} frame {frame.get('frame_id')}: {stage} has invalid row pitch")
        raw_path = _safe_path(sequence_root, artifact.get("raw_path"))
        if raw_path.stat().st_size != row_pitch * EXPECTED_CROP_SIZE:
            raise ValueError(
                f"{sequence_id} frame {frame.get('frame_id')}: {stage} raw size does not match row pitch"
            )
        selected[stage] = {
            "path": str(raw_path),
            "width": EXPECTED_CROP_SIZE,
            "height": EXPECTED_CROP_SIZE,
            "row_pitch": row_pitch,
            "format_name": artifact["format_name"],
            "crop_rect": artifact.get("crop_rect"),
            "source_rect": artifact.get("source_rect"),
        }

    try:
        frame_id = int(frame["frame_id"])
        sample_index = int(frame["sample_index"])
        host_frame = int(frame["host_frame"])
        source_color_size = [int(frame["color_width"]), int(frame["color_height"])]
        source_guide_size = [int(frame["guide_width"]), int(frame["guide_height"])]
        motion_scale = [
            float(frame["motion_vector_scale_x"][eye]),
            float(frame["motion_vector_scale_y"][eye]),
        ]
    except (KeyError, TypeError, ValueError, IndexError) as exc:
        raise ValueError(f"{sequence_id} frame {frame.get('frame_id')}: invalid identity or guide metadata") from exc
    resets = frame.get("history_reset")
    if not isinstance(resets, list) or len(resets) != 2 or not all(isinstance(v, bool) for v in resets):
        raise ValueError(f"{sequence_id} frame {frame_id}: history_reset is not [bool, bool]")

    return {
        "schema_version": 2,
        "source": "opennr_raw_crop_capture",
        "sequence_id": sequence_id,
        "frame_id": frame_id,
        "sample_index": sample_index,
        "host_frame": host_frame,
        "eye": eye,
        "crop_index": int(crop_index),
        "split": split,
        "color_size": [EXPECTED_CROP_SIZE, EXPECTED_CROP_SIZE],
        "guide_size": [EXPECTED_CROP_SIZE, EXPECTED_CROP_SIZE],
        "source_color_size": source_color_size,
        "source_guide_size": source_guide_size,
        "paths": {stage: selected[stage]["path"] for stage in REQUIRED_STAGES},
        "artifacts": selected,
        "motion_scale": motion_scale,
        "history_reset": bool(resets[eye]),
        "history_reset_pair": [bool(v) for v in resets],
        "teacher_settings": frame.get("teacher_settings"),
        "route": frame.get("route"),
        "model_resolution_percent": int(frame.get("model_resolution_percent", 0)),
        "pass_count": int(frame.get("pass_count", 0)),
        "motion_vector_contract": frame.get("motion_vector_contract"),
    }


def build_rows(
    candidate_path: Path,
    capture_root_override: Path | None = None,
    crop_indices: tuple[int, ...] = (0,),
    allow_two_sequence_pilot: bool = False,
) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any]]:
    """Validate the selected sequences and return eye rows, split, and provenance."""

    crop_indices = tuple(sorted(set(int(value) for value in crop_indices)))
    if not crop_indices or any(value < 0 for value in crop_indices):
        raise ValueError("crop_indices must contain at least one non-negative crop index")

    candidate = _read_json(candidate_path)
    root, entries = _candidate_entries(candidate, capture_root_override)
    split = _split_sequence_ids(entries, allow_two_sequence_pilot=allow_two_sequence_pilot)
    membership = {sequence_id: split_name for split_name in SPLITS for sequence_id in split[split_name]}
    rows: list[dict[str, Any]] = []
    source_sequences: list[dict[str, Any]] = []
    capture_signature: tuple[Any, ...] | None = None

    for entry in entries:
        sequence_id = entry["sequence_id"]
        sequence_root = root / sequence_id
        sequence_manifest = sequence_root / "sequence.json"
        frames_manifest = sequence_root / "frames.jsonl"
        if not sequence_manifest.is_file() or not frames_manifest.is_file():
            raise ValueError(f"{sequence_id}: missing sequence.json or frames.jsonl")
        sequence_meta = _read_json(sequence_manifest)
        if str(sequence_meta.get("sequence_id")) != sequence_id:
            raise ValueError(f"{sequence_id}: sequence.json identity mismatch")
        frames: list[dict[str, Any]] = []
        for line_number, line in enumerate(frames_manifest.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            try:
                frame = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{sequence_id}: invalid frames.jsonl line {line_number}") from exc
            if not isinstance(frame, dict):
                raise ValueError(f"{sequence_id}: frame line {line_number} is not an object")
            frames.append(frame)
        if len(frames) != entry["expected_frames"]:
            raise ValueError(
                f"{sequence_id}: candidate expected {entry['expected_frames']} frames, found {len(frames)}"
            )
        complete = sum(frame.get("status") == "complete" for frame in frames)
        if complete != entry["expected_complete"]:
            raise ValueError(f"{sequence_id}: candidate complete count changed")
        previous: tuple[int, int, int] | None = None
        sequence_rows: list[dict[str, Any]] = []
        for index, frame in enumerate(frames):
            capture_signature = _validate_frame_signature(frame, sequence_id, capture_signature)
            identity = (int(frame["frame_id"]), int(frame["sample_index"]), int(frame["host_frame"]))
            if previous is not None and tuple(value - old for value, old in zip(identity, previous)) != (1, 1, 1):
                raise ValueError(f"{sequence_id}: non-contiguous frame/sample/host transition at frame {identity[0]}")
            previous = identity
            resets = frame.get("history_reset")
            if index > 0 and isinstance(resets, list) and any(bool(v) for v in resets):
                raise ValueError(f"{sequence_id}: mid-clip history reset cannot be used as one row group")
            for crop_index in crop_indices:
                frame_rows = [
                    _make_row(
                        sequence_root,
                        sequence_id,
                        frame,
                        eye,
                        membership[sequence_id],
                        crop_index,
                    )
                    for eye in (0, 1)
                ]
                rows.extend(frame_rows)
                sequence_rows.extend(frame_rows)
        expected_artifacts = entry["expected_artifacts"]
        actual_artifacts = len(sequence_rows) * len(REQUIRED_STAGES)
        expected_artifacts *= len(crop_indices)
        if actual_artifacts != expected_artifacts:
            raise ValueError(
                f"{sequence_id}: candidate expected {expected_artifacts} artifacts, found {actual_artifacts}"
            )
        source_sequences.append(
            {
                "sequence_id": sequence_id,
                "created_utc": entry["created_utc"],
                "frames": len(frames),
                "eye_rows": len(sequence_rows),
                "split": membership[sequence_id],
                "sequence_sha256": _sha256_file(sequence_manifest),
                "frames_sha256": _sha256_file(frames_manifest),
                "first_history_reset": frames[0].get("history_reset") if frames else None,
            }
        )

    if int(candidate.get("candidate_frames", sum(item["frames"] for item in source_sequences))) != sum(
        item["frames"] for item in source_sequences
    ):
        raise ValueError("candidate frame count does not match source sequences")
    if len(rows) != sum(item["eye_rows"] for item in source_sequences):
        raise ValueError("internal row count mismatch")
    provenance = {
        "candidate_manifest": str(candidate_path.resolve()),
        "candidate_manifest_sha256": _sha256_file(candidate_path),
        "capture_root": str(root),
        "crop_indices": list(crop_indices),
        "source_sequences": source_sequences,
        "capture_signature": capture_signature,
        "strict_initial_reset": all(item["first_history_reset"] == [True, True] for item in source_sequences),
        "raw_color_contract": "R8G8B8A8_UNORM crop, PNG previews not required",
    }
    return rows, split, provenance


def _raw_memmap(path: str | Path, width: int, height: int, channels: int, dtype: str, row_pitch: int) -> np.ndarray:
    dtype_obj = np.dtype(dtype)
    minimum_pitch = width * channels * dtype_obj.itemsize
    if row_pitch < minimum_pitch or row_pitch % dtype_obj.itemsize:
        raise ValueError(f"invalid row pitch {row_pitch} for {width}x{height}x{channels} {dtype}")
    expected_bytes = row_pitch * height
    actual_bytes = Path(path).stat().st_size
    if actual_bytes != expected_bytes:
        raise ValueError(f"{path}: {actual_bytes} bytes != expected {expected_bytes}")
    row_elements = row_pitch // dtype_obj.itemsize
    mapped = np.memmap(path, mode="r", dtype=dtype_obj, shape=(height, row_elements))
    # Return an owning array so Windows can close the file before a worker
    # advances to the next row (and before temporary-file tests clean up).
    values = np.array(mapped[:, : width * channels].reshape(height, width, channels), copy=True)
    del mapped
    return values


def _color(path: str, artifact: dict[str, Any]) -> np.ndarray:
    raw = _raw_memmap(
        path,
        int(artifact["width"]),
        int(artifact["height"]),
        4,
        "u1",
        int(artifact["row_pitch"]),
    )
    return np.ascontiguousarray(raw[:, :, :3])


def _convert_motion_to_color_pixels(motion: np.ndarray, row: dict[str, Any]) -> np.ndarray:
    """Convert native guide-pixel motion into bounded color-pixel features."""

    color_width, color_height = row["source_color_size"]
    guide_width, guide_height = row["source_guide_size"]
    converted = np.asarray(motion, dtype=np.float32).copy()
    converted[:, :, 0] *= row["motion_scale"][0] * color_width / guide_width
    converted[:, :, 1] *= row["motion_scale"][1] * color_height / guide_height
    return np.clip(converted, -128.0, 128.0) / 128.0


def _guide_arrays(row: dict[str, Any]) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    depth_artifact = row["artifacts"]["depth"]
    motion_artifact = row["artifacts"]["motion_vectors"]
    depth_raw = _raw_memmap(
        row["paths"]["depth"],
        int(depth_artifact["width"]),
        int(depth_artifact["height"]),
        1,
        "<f4",
        int(depth_artifact["row_pitch"]),
    )
    depth = np.asarray(depth_raw, dtype=np.float32)
    depth_valid = np.isfinite(depth[:, :, 0]) & (depth[:, :, 0] >= 0.0) & (depth[:, :, 0] <= 1.0)
    depth = np.where(depth_valid[:, :, None], depth, 0.0)

    motion_raw = _raw_memmap(
        row["paths"]["motion_vectors"],
        int(motion_artifact["width"]),
        int(motion_artifact["height"]),
        2,
        "<f2",
        int(motion_artifact["row_pitch"]),
    )
    motion = np.asarray(motion_raw, dtype=np.float32)
    motion_valid = np.isfinite(motion).all(axis=2) & (np.abs(motion) <= 0.25).all(axis=2)
    motion = np.where(motion_valid[:, :, None], motion, 0.0)

    # The capture stores a 512x512 crop of the native guide texture.  Motion
    # values still use the native Feature 18 guide-pixel convention, so the
    # conversion must use the full source dimensions, not 512/512.  This is
    # the same conversion used by the audited full-resolution cache path.
    motion = _convert_motion_to_color_pixels(motion, row)
    return depth, depth_valid, motion, motion_valid


def _guide_tensor(row: dict[str, Any], depth: np.ndarray, depth_valid: np.ndarray, motion: np.ndarray, motion_valid: np.ndarray, size: int, *, legacy_alignment: bool = False) -> np.ndarray:
    if not legacy_alignment:
        from aligned_native_guides import sample_aligned
        return sample_aligned(row, depth, depth_valid, motion, motion_valid, size)
    box = (0, 0, EXPECTED_CROP_SIZE, EXPECTED_CROP_SIZE)
    depth_patch, depth_mask = sample_guide(depth, box, (EXPECTED_CROP_SIZE, EXPECTED_CROP_SIZE), size, depth_valid)
    motion_patch, motion_mask = sample_guide(motion, box, (EXPECTED_CROP_SIZE, EXPECTED_CROP_SIZE), size, motion_valid)
    return torch.cat((depth_patch * depth_mask, motion_patch * motion_mask, depth_mask, motion_mask), 0).numpy().astype(np.float16)


def _build_cache(
    rows: list[dict[str, Any]],
    split: dict[str, Any],
    provenance: dict[str, Any],
    candidate_path: Path,
    output: Path,
    workers: int,
    spatial_only: bool = False,
    legacy_guide_alignment: bool = False,
) -> dict[str, Any]:
    if output.exists() and any(output.iterdir()):
        raise FileExistsError(f"output directory is not empty: {output}")
    output.mkdir(parents=True, exist_ok=True)
    torch.set_num_threads(1)
    row_count = len(rows)
    colors = np.lib.format.open_memmap(output / "rgb.npy", mode="w+", dtype="u1", shape=(row_count, 2, 3, EXPECTED_CROP_SIZE, EXPECTED_CROP_SIZE))
    guides = np.lib.format.open_memmap(output / "guides.npy", mode="w+", dtype="<f2", shape=(row_count, 5, GUIDE_PATCH_SIZE, GUIDE_PATCH_SIZE))
    contexts = np.lib.format.open_memmap(output / "context.npy", mode="w+", dtype="<f2", shape=(row_count, 8, CONTEXT_SIZE, CONTEXT_SIZE))
    patches = [
        {
            "row": index,
            "box": [0, 0, EXPECTED_CROP_SIZE, EXPECTED_CROP_SIZE],
            "split": row["split"],
            "sequence_id": row["sequence_id"],
            "frame_id": row["frame_id"],
            "eye": row["eye"],
            "crop_index": row["crop_index"],
        }
        for index, row in enumerate(rows)
    ]
    (output / "rows.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")
    (output / "patches.json").write_text(json.dumps(patches, indent=2), encoding="utf-8")

    def work(index: int) -> tuple[int, int, int]:
        row = rows[index]
        input_rgb = _color(row["paths"]["input"], row["artifacts"]["input"])
        teacher_rgb = _color(row["paths"]["teacher"], row["artifacts"]["teacher"])
        depth, depth_valid, motion, motion_valid = _guide_arrays(row)
        colors[index, 0] = input_rgb.transpose(2, 0, 1)
        colors[index, 1] = teacher_rgb.transpose(2, 0, 1)
        guides[index] = _guide_tensor(row, depth, depth_valid, motion, motion_valid, GUIDE_PATCH_SIZE, legacy_alignment=legacy_guide_alignment)
        context_rgb = np.asarray(Image.fromarray(input_rgb, mode="RGB").resize((CONTEXT_SIZE, CONTEXT_SIZE), Image.Resampling.BOX), dtype=np.float32).transpose(2, 0, 1) / 255.0
        context_guides = _guide_tensor(row, depth, depth_valid, motion, motion_valid, CONTEXT_SIZE, legacy_alignment=legacy_guide_alignment).astype(np.float32)
        contexts[index] = np.concatenate((context_rgb, context_guides), axis=0).astype(np.float16)
        return index, int((~depth_valid).sum()), int((~motion_valid).sum())

    started = time.time()
    invalid_depth = 0
    invalid_motion = 0
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        for done, (_, depth_bad, motion_bad) in enumerate(pool.map(work, range(row_count)), 1):
            invalid_depth += depth_bad
            invalid_motion += motion_bad
            if done % 256 == 0 or done == row_count:
                print(f"cache {done}/{row_count} eye rows ({time.time() - started:.1f}s)", flush=True)
    colors.flush()
    guides.flush()
    contexts.flush()

    rows_sha256 = _stable_sha256(rows)
    counts = {name: sum(item["split"] == name for item in patches) for name in SPLITS}
    sequence_counts = {name: len(split[name]) for name in SPLITS}
    report = {
        "schema": 2,
        "source_type": "opennr_raw_crop_capture",
        "source_manifest": str(candidate_path.resolve()),
        "source_manifest_sha256": _sha256_file(candidate_path),
        "source_root": provenance["capture_root"],
        "source_sequences": len(provenance["source_sequences"]),
        "source_frames": sum(item["frames"] for item in provenance["source_sequences"]),
        "source_eye_rows": row_count,
        "crop_indices": provenance["crop_indices"],
        "rows_sha256": rows_sha256,
        "split": split,
        "sequence_counts": sequence_counts,
        "eye_row_counts": counts,
        "patches": row_count,
        "native_patch": EXPECTED_CROP_SIZE,
        "guide_patch": GUIDE_PATCH_SIZE,
        "context": CONTEXT_SIZE,
        "raw_color_contract": "R8G8B8A8_UNORM crop; alpha stripped; PNG previews not used",
        "raw_guide_contract": "R32_FLOAT depth and R16G16_FLOAT exact Feature 18 motion crop",
        "guide_alignment": "legacy_full_native_crop" if legacy_guide_alignment else "teacher_region_native_coordinates_v1",
        "strict_initial_reset": provenance["strict_initial_reset"],
        "invalid_depth_values": invalid_depth,
        "invalid_motion_values": invalid_motion,
        "workers": max(1, workers),
        "seconds": time.time() - started,
        "test_used_for_tuning": False,
        "training_role": "spatial_only_auxiliary" if spatial_only else "strict_temporal_crop_cache",
        "temporal_training_allowed": not spatial_only,
        "provenance": provenance,
    }
    (output / "split.json").write_text(json.dumps(split, indent=2), encoding="utf-8")
    (output / "provenance.json").write_text(json.dumps(provenance, indent=2), encoding="utf-8")
    (output / "complete.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate-manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--capture-root", type=Path, help="override capture_root from the candidate manifest")
    parser.add_argument(
        "--crop-index",
        type=int,
        action="append",
        help="crop index to materialize; may be supplied multiple times (default: 0)",
    )
    parser.add_argument(
        "--all-crops",
        action="store_true",
        help="materialize crop indices 0 through 3 for a spatial cache",
    )
    parser.add_argument(
        "--spatial-only",
        action="store_true",
        help="mark the output as spatial-only auxiliary data; required for multi-crop output",
    )
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--legacy-guide-alignment", action="store_true", help="reproduce historical incorrect full-native-crop mapping; research reproduction only")
    parser.add_argument(
        "--allow-two-sequence-pilot",
        action="store_true",
        help="allow exactly two strict sequences; creates train/validation only and records no independent test split",
    )
    parser.add_argument("--metadata-only", action="store_true", help="validate and print the planned rows without allocating the cache")
    args = parser.parse_args()
    from opennr_paths import require_external_output
    args.output = require_external_output(args.output)
    if args.workers < 1:
        parser.error("--workers must be positive")
    if args.all_crops and args.crop_index:
        parser.error("--all-crops cannot be combined with --crop-index")
    crop_indices = tuple(range(4)) if args.all_crops else tuple(args.crop_index or [0])
    if len(crop_indices) > 1 and not args.spatial_only:
        parser.error("multi-crop output must be marked --spatial-only because it is not a temporal stream")
    rows, split, provenance = build_rows(
        args.candidate_manifest,
        args.capture_root,
        crop_indices=crop_indices,
        allow_two_sequence_pilot=args.allow_two_sequence_pilot,
    )
    summary = {
        "rows": len(rows),
        "frames": len(rows) // (2 * len(crop_indices)),
        "sequences": len(provenance["source_sequences"]),
        "crop_indices": list(crop_indices),
        "sequence_counts": {name: len(split[name]) for name in SPLITS},
        "eye_row_counts": {name: sum(row["split"] == name for row in rows) for name in SPLITS},
        "strict_initial_reset": provenance["strict_initial_reset"],
        "test_available": bool(split["test"]),
        "capture_root": provenance["capture_root"],
    }
    if args.metadata_only:
        print(json.dumps(summary, indent=2))
        return 0
    report = _build_cache(
        rows,
        split,
        provenance,
        args.candidate_manifest,
        args.output,
        args.workers,
        spatial_only=args.spatial_only,
        legacy_guide_alignment=args.legacy_guide_alignment,
    )
    print(json.dumps(report, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
