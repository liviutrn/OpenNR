"""Build a spatial-only cache from otherwise excluded complete crop rows.

The strict temporal manifest intentionally excludes sequences with an
eye-specific zero-motion-vector anomaly and an interrupted final burst.  Their
complete RGB/teacher pairs are still useful for feed-forward appearance
regularization, but they must never be admitted to a recurrent motion loss or
silently folded into the strict temporal cache.  This helper creates an
explicitly labelled auxiliary cache from selected complete frames and forces
all selected rows into its training split.  The source capture remains
immutable.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from build_raw_crop_cache import _build_cache, build_rows


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object in {path}")
    return value


def _complete_frames(sequence_root: Path) -> list[dict[str, Any]]:
    frames_path = sequence_root / "frames.jsonl"
    if not frames_path.is_file():
        raise ValueError(f"missing frames.jsonl: {frames_path}")
    frames: list[dict[str, Any]] = []
    for line_number, line in enumerate(
        frames_path.read_text(encoding="utf-8").splitlines(), 1
    ):
        try:
            frame = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid JSON at {frames_path}:{line_number}") from exc
        if isinstance(frame, dict) and frame.get("status") == "complete":
            frames.append(frame)
    frames.sort(key=lambda item: int(item["frame_id"]))
    if len(frames) < 2:
        raise ValueError(f"{sequence_root.name}: fewer than two complete frames")
    expected = list(range(1, len(frames) + 1))
    actual = [int(frame["frame_id"]) for frame in frames]
    if actual != expected:
        raise ValueError(
            f"{sequence_root.name}: complete frame IDs are not contiguous from one: "
            f"{actual[:3]} ... {actual[-3:]}"
        )
    return frames


def _write_candidate(
    capture_root: Path, sequence_ids: list[str], manifest_path: Path
) -> dict[str, Any]:
    entries: list[dict[str, Any]] = []
    for sequence_id in sequence_ids:
        sequence_root = capture_root / sequence_id
        metadata = _read_json(sequence_root / "sequence.json")
        if str(metadata.get("sequence_id")) != sequence_id:
            raise ValueError(f"sequence.json identity mismatch for {sequence_id}")
        frames = _complete_frames(sequence_root)
        entries.append(
            {
                "sequence": sequence_id,
                "frames": len(frames),
                "complete": len(frames),
                "artifact_count": len(frames) * 2 * 4,
                "created_utc": int(metadata["created_utc"]),
                "source_status": "complete-rows-only",
            }
        )
    entries.sort(key=lambda item: (item["created_utc"], item["sequence"]))
    candidate = {
        "schema": "opennr-crop-training-candidate-v1",
        "capture_root": str(capture_root.resolve()),
        "selection": (
            "explicit complete rows from excluded strict-capture sequences; "
            "spatial-only auxiliary training; never valid for recurrent temporal loss"
        ),
        "temporal_reset_policy": "not-a-temporal-candidate",
        "strict_temporal_note": (
            "motion anomalies and/or an interrupted source burst are preserved; "
            "this cache is not accepted by StrictTemporalCache"
        ),
        "candidate_sequences": len(entries),
        "candidate_frames": sum(item["frames"] for item in entries),
        "candidate_eye_pairs": sum(item["frames"] * 2 for item in entries),
        "candidate_artifacts": sum(item["artifact_count"] for item in entries),
        "sequences": entries,
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(candidate, indent=2), encoding="utf-8")
    return candidate


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture-root", type=Path, required=True)
    parser.add_argument("--sequence-id", action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--workers", type=int, default=3)
    args = parser.parse_args()
    if args.workers < 1:
        parser.error("--workers must be positive")
    capture_root = args.capture_root.resolve()
    sequence_ids = list(dict.fromkeys(args.sequence_id))
    if len(sequence_ids) < 3:
        parser.error("at least three selected sequences are required")
    output = args.output.resolve()
    if output.exists() and any(output.iterdir()):
        raise FileExistsError(f"output directory is not empty: {output}")
    manifest = (
        args.manifest.resolve()
        if args.manifest
        else output.parent / f"{output.name}_candidate.json"
    )
    candidate = _write_candidate(capture_root, sequence_ids, manifest)
    rows, _, provenance = build_rows(manifest)
    # This cache is deliberately all-train.  It is a regularizer only; strict
    # temporal validation and frozen test evaluation continue to use the
    # separate 73-sequence cache and its immutable split.
    for row in rows:
        row["split"] = "train"
    split = {
        "train": sequence_ids,
        "validation": [],
        "test": [],
        "policy": "explicit all-selected complete rows for spatial-only regularization",
    }
    for source_sequence in provenance["source_sequences"]:
        source_sequence["split"] = "train"
    provenance["strict_initial_reset"] = False
    provenance["training_role"] = "spatial_only_auxiliary"
    provenance["temporal_training_allowed"] = False
    report = _build_cache(rows, split, provenance, manifest, output, args.workers)
    report["strict_initial_reset"] = False
    report["training_role"] = "spatial_only_auxiliary"
    report["temporal_training_allowed"] = False
    report["selected_complete_frames"] = int(candidate["candidate_frames"])
    report["selected_sequences"] = sequence_ids
    report["test_used_for_tuning"] = False
    (output / "complete.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
