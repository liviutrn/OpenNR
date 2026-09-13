#!/usr/bin/env python3
"""Build a strict temporal crop candidate manifest from an audit report.

The temporal audit intentionally reports metadata/path readiness independently
from the configured burst length.  This helper applies the training contract
on top: exact 64-frame clips, strict initial history reset, and an optional
created-time window for selecting a fresh capture session.  It only writes a
manifest; the capture tree and source audit remain immutable.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


AUDIT_SCHEMA = "opennr-temporal-capture-audit-v1"
CANDIDATE_SCHEMA = "opennr-crop-training-candidate-v1"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _read_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected a JSON object in {path}")
    return value


def _capture_root(audit: dict[str, Any], override: Path | None) -> Path:
    if override is not None:
        root = override.resolve()
    else:
        reports = audit.get("reports")
        if not isinstance(reports, list) or not reports:
            raise ValueError("audit has no reports from which to infer capture root")
        first = reports[0]
        if not isinstance(first, dict) or not isinstance(first.get("path"), str):
            raise ValueError("audit report has no sequence path")
        root = Path(first["path"]).resolve().parent
    if not root.is_dir():
        raise ValueError(f"capture root does not exist: {root}")
    return root


def _entry(root: Path, report: dict[str, Any], expected_frames: int) -> dict[str, Any]:
    sequence_id = str(report.get("sequence") or "")
    if not sequence_id:
        raise ValueError("audit report has no sequence id")
    sequence_root = root / sequence_id
    metadata = _read_object(sequence_root / "sequence.json")
    if str(metadata.get("sequence_id")) != sequence_id:
        raise ValueError(f"sequence.json identity mismatch for {sequence_id}")
    created_utc = int(metadata["created_utc"])
    frames = int(report.get("frames", 0))
    complete = int(report.get("complete_frames", 0))
    if frames != expected_frames or complete != expected_frames:
        raise ValueError(f"candidate entry {sequence_id} is not an exact {expected_frames}-frame clip")
    if report.get("first_frame_resets") != [True, True]:
        raise ValueError(f"candidate entry {sequence_id} does not have strict initial reset")
    return {
        "sequence": sequence_id,
        "frames": frames,
        "complete": complete,
        "artifact_count": frames * 2 * 4,
        "created_utc": created_utc,
        "source_status": "strict-temporal-ready-exact-frame-count",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audit", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--capture-root", type=Path)
    parser.add_argument("--min-created-utc", type=int)
    parser.add_argument("--max-created-utc", type=int)
    parser.add_argument("--exclude-sequence", action="append", default=[])
    parser.add_argument("--expected-frames", type=int, default=64)
    parser.add_argument(
        "--allow-two-sequence-pilot",
        action="store_true",
        help="allow exactly two strict sequences; writes train/validation only and no independent test split",
    )
    args = parser.parse_args()
    if args.expected_frames < 2:
        parser.error("--expected-frames must be at least two")
    audit_path = args.audit.resolve()
    audit = _read_object(audit_path)
    if audit.get("schema") != AUDIT_SCHEMA:
        raise ValueError(f"unexpected audit schema: {audit.get('schema')!r}")
    reports = audit.get("reports")
    if not isinstance(reports, list):
        raise ValueError("audit reports is not an array")
    root = _capture_root(audit, args.capture_root)
    excluded = set(args.exclude_sequence)
    entries: list[dict[str, Any]] = []
    skipped: dict[str, int] = {}
    for report in reports:
        if not isinstance(report, dict):
            skipped["malformed_report"] = skipped.get("malformed_report", 0) + 1
            continue
        sequence_id = str(report.get("sequence") or "")
        if not bool(report.get("temporal_ready")):
            skipped["audit_not_ready"] = skipped.get("audit_not_ready", 0) + 1
            continue
        if sequence_id in excluded:
            skipped["explicit_exclusion"] = skipped.get("explicit_exclusion", 0) + 1
            continue
        if int(report.get("frames", 0)) != args.expected_frames:
            skipped["wrong_frame_count"] = skipped.get("wrong_frame_count", 0) + 1
            continue
        try:
            candidate = _entry(root, report, args.expected_frames)
        except (KeyError, OSError, TypeError, ValueError) as exc:
            raise ValueError(f"cannot promote {sequence_id}: {exc}") from exc
        created_utc = int(candidate["created_utc"])
        if args.min_created_utc is not None and created_utc < args.min_created_utc:
            skipped["before_min_created_utc"] = skipped.get("before_min_created_utc", 0) + 1
            continue
        if args.max_created_utc is not None and created_utc > args.max_created_utc:
            skipped["after_max_created_utc"] = skipped.get("after_max_created_utc", 0) + 1
            continue
        entries.append(candidate)
    entries.sort(key=lambda item: (int(item["created_utc"]), str(item["sequence"])))
    if len(entries) < 3:
        if not args.allow_two_sequence_pilot or len(entries) != 2:
            raise ValueError("fewer than three exact strict sequences survived selection")
        split = {
            "train": [str(entries[0]["sequence"])],
            "validation": [str(entries[1]["sequence"])],
            "test": [],
            "policy": "explicit two-sequence temporal pilot; chronological train/validation split; independent test unavailable",
        }
    else:
        split = None
    sequence_ids = [str(item["sequence"]) for item in entries]
    if len(set(sequence_ids)) != len(sequence_ids):
        raise ValueError("selected sequence IDs are not unique")
    candidate = {
        "schema": CANDIDATE_SCHEMA,
        "capture_root": str(root),
        "source_audit": str(audit_path),
        "source_audit_sha256": _sha256(audit_path),
        "selection": (
            "audit-temporal-ready sequences with exact configured frame count and strict initial reset; "
            "optional created-time bounds applied; source capture remains immutable"
        ),
        "temporal_reset_policy": "strict_initial_reset",
        "expected_frames": args.expected_frames,
        "candidate_sequences": len(entries),
        "candidate_frames": sum(int(item["frames"]) for item in entries),
        "candidate_eye_pairs": sum(int(item["frames"]) * 2 for item in entries),
        "candidate_artifacts": sum(int(item["artifact_count"]) for item in entries),
        "sequences": entries,
        "selection_skips": skipped,
    }
    if split is not None:
        candidate["split"] = split
        candidate["test_available"] = False
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(candidate, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "state": "completed",
                "output": str(output),
                "capture_root": str(root),
                "candidate_sequences": candidate["candidate_sequences"],
                "candidate_frames": candidate["candidate_frames"],
                "candidate_eye_pairs": candidate["candidate_eye_pairs"],
                "split": split,
                "selection_skips": skipped,
            },
            indent=2,
        ),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
