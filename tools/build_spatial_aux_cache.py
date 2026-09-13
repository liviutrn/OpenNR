"""Build an auditable spatial-only cache from retained non-strict captures.

Legacy OpenNR captures can contain complete input/teacher/guide crop pairs even
when host-frame gaps or a missing initial history reset make them unsafe for
recurrent temporal training.  This builder deliberately admits those rows only
as spatial data, records the cadence/reset caveats, and reuses the raw-crop
cache conversion so the guide and context contracts stay identical.
"""

from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
from typing import Any

from build_raw_crop_cache import (
    _artifact_map,
    _build_cache,
    _make_row,
    _sha256_file,
    _validate_frame_signature,
)


def _read_frames(path: Path) -> list[dict[str, Any]]:
    frames: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            frame = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}: invalid JSON on line {line_number}") from exc
        if not isinstance(frame, dict):
            raise ValueError(f"{path}: line {line_number} is not an object")
        frames.append(frame)
    return frames


def _split_sequences(records: list[dict[str, Any]]) -> dict[str, list[str]]:
    ordered = sorted(records, key=lambda item: (item["created_utc"], item["sequence_id"]))
    if len(ordered) == 1:
        return {"train": [ordered[0]["sequence_id"]], "validation": [], "test": []}
    train_count = max(1, int(len(ordered) * 0.6))
    validation_count = max(1, int(len(ordered) * 0.2))
    if train_count + validation_count >= len(ordered):
        validation_count = max(1, len(ordered) - train_count - 1)
    return {
        "train": [item["sequence_id"] for item in ordered[:train_count]],
        "validation": [
            item["sequence_id"] for item in ordered[train_count : train_count + validation_count]
        ],
        "test": [item["sequence_id"] for item in ordered[train_count + validation_count :]],
    }


def build_rows(roots: list[Path]) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any]]:
    sequence_records: list[dict[str, Any]] = []
    rows_by_sequence: dict[str, list[dict[str, Any]]] = {}
    seen: set[str] = set()
    signature: tuple[Any, ...] | None = None

    for root in roots:
        sequence_dirs = sorted(path for path in root.glob("seq-*") if path.is_dir())
        if not sequence_dirs:
            raise ValueError(f"{root}: no seq-* directories found")
        for sequence_root in sequence_dirs:
            sequence_id = sequence_root.name
            if sequence_id in seen:
                raise ValueError(f"duplicate sequence id across roots: {sequence_id}")
            seen.add(sequence_id)
            sequence_manifest = sequence_root / "sequence.json"
            frames_manifest = sequence_root / "frames.jsonl"
            if not sequence_manifest.is_file() or not frames_manifest.is_file():
                raise ValueError(f"{sequence_id}: missing sequence.json or frames.jsonl")
            sequence_meta = json.loads(sequence_manifest.read_text(encoding="utf-8"))
            if sequence_meta.get("sequence_id") != sequence_id:
                raise ValueError(f"{sequence_id}: sequence.json identity mismatch")
            frames = _read_frames(frames_manifest)
            if not frames:
                raise ValueError(f"{sequence_id}: no frame records")
            previous: tuple[int, int, int] | None = None
            frame_gaps = 0
            host_gaps = 0
            mid_resets = 0
            sequence_rows: list[dict[str, Any]] = []
            for index, frame in enumerate(frames):
                signature = _validate_frame_signature(frame, sequence_id, signature)
                identity = (
                    int(frame["frame_id"]),
                    int(frame["sample_index"]),
                    int(frame["host_frame"]),
                )
                if previous is not None:
                    if identity[0] - previous[0] != 1 or identity[1] - previous[1] != 1:
                        frame_gaps += 1
                    if identity[2] - previous[2] != 1:
                        host_gaps += 1
                previous = identity
                resets = frame.get("history_reset")
                if index > 0 and isinstance(resets, list) and any(bool(value) for value in resets):
                    mid_resets += 1
                frame_rows = [_make_row(sequence_root, sequence_id, frame, eye, "train") for eye in (0, 1)]
                sequence_rows.extend(frame_rows)
            first = frames[0]
            created_utc = int(
                sequence_meta.get("created_utc")
                or first.get("written_utc")
                or first.get("host_frame")
                or 0
            )
            sequence_records.append(
                {
                    "sequence_id": sequence_id,
                    "created_utc": created_utc,
                    "frames": len(frames),
                    "eye_rows": len(sequence_rows),
                    "sequence_sha256": _sha256_file(sequence_manifest),
                    "frames_sha256": _sha256_file(frames_manifest),
                    "first_history_reset": first.get("history_reset"),
                    "frame_gaps": frame_gaps,
                    "host_gaps": host_gaps,
                    "mid_clip_resets": mid_resets,
                    "source_root": str(root),
                }
            )
            rows_by_sequence[sequence_id] = sequence_rows

    split = _split_sequences(sequence_records)
    membership = {
        sequence_id: split_name
        for split_name, sequence_ids in split.items()
        for sequence_id in sequence_ids
    }
    rows: list[dict[str, Any]] = []
    for record in sorted(sequence_records, key=lambda item: (item["created_utc"], item["sequence_id"])):
        sequence_id = record["sequence_id"]
        for row in rows_by_sequence[sequence_id]:
            row["split"] = membership[sequence_id]
            rows.append(row)
        record["split"] = membership[sequence_id]

    provenance = {
        "source_type": "opennr_legacy_capture_spatial_only",
        "capture_root": ";".join(str(root) for root in roots),
        "capture_roots": [str(root) for root in roots],
        "source_sequences": sequence_records,
        "strict_initial_reset": all(
            record.get("first_history_reset") == [True, True] for record in sequence_records
        ),
        "temporal_training_allowed": False,
        "host_gaps_allowed_for_spatial_only": True,
        "reset_policy": "retained as spatial-only because legacy captures lack strict initial reset",
        "raw_color_contract": "R8G8B8A8_UNORM crop; alpha stripped; PNG previews not required",
    }
    return rows, split, provenance


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture-root", type=Path, action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--manifest-output", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--metadata-only", action="store_true")
    args = parser.parse_args()
    if args.workers < 1:
        raise ValueError("workers must be positive")
    roots = [root.resolve() for root in args.capture_root]
    rows, split, provenance = build_rows(roots)
    candidate = {
        "schema": "opennr-spatial-aux-candidate-v1",
        "selection": "complete input/teacher/depth/exact-MV crop-0 pairs; host gaps and missing initial reset are spatial-only caveats",
        "capture_roots": [str(root) for root in roots],
        "sequence_count": len(provenance["source_sequences"]),
        "frame_count": sum(item["frames"] for item in provenance["source_sequences"]),
        "eye_rows": len(rows),
        "split": split,
        "provenance": provenance,
    }
    args.manifest_output.parent.mkdir(parents=True, exist_ok=True)
    args.manifest_output.write_text(json.dumps(candidate, indent=2), encoding="utf-8")
    if args.metadata_only:
        print(json.dumps({"state": "metadata_only", **{key: candidate[key] for key in ("sequence_count", "frame_count", "eye_rows", "split")}}, indent=2))
        return
    report = _build_cache(
        rows,
        split,
        provenance,
        args.manifest_output,
        args.output.resolve(),
        args.workers,
    )
    report["temporal_training_allowed"] = False
    report["spatial_only_reason"] = provenance["reset_policy"]
    (args.output / "complete.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
