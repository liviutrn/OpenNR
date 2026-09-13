#!/usr/bin/env python3
"""Build a strict crop cache from reset-qualified windows in longer captures.

The capture pilot intentionally records 240-frame bursts so that there is a
periodic full-resolution anchor.  The recurrent trainer consumes independent
64-frame streams, therefore this helper selects only the first reset-qualified
64-frame window from each sequence reported as ``temporal_ready`` by the
temporal audit.  The source capture tree is never copied or modified.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from build_raw_crop_cache import (
    REQUIRED_STAGES,
    _build_cache,
    _make_row,
    _read_json,
    _sha256_file,
    _split_sequence_ids,
    _stable_sha256,
    _validate_frame_signature,
)


AUDIT_SCHEMA = "opennr-temporal-capture-audit-v1"
SELECTION_SCHEMA = "opennr-full-eye-temporal-window-selection-v1"


def _load_frames(path: Path) -> list[dict[str, Any]]:
    frames: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid frames.jsonl line {line_number} in {path}") from exc
        if not isinstance(value, dict):
            raise ValueError(f"frames.jsonl line {line_number} in {path} is not an object")
        frames.append(value)
    return frames


def _capture_root(audit: dict[str, Any], override: Path | None) -> Path:
    if override is not None:
        root = override.resolve()
    else:
        reports = audit.get("reports")
        if not isinstance(reports, list) or not reports:
            raise ValueError("audit has no reports")
        first = reports[0]
        if not isinstance(first, dict) or not isinstance(first.get("path"), str):
            raise ValueError("audit has no sequence path")
        root = Path(first["path"]).resolve().parent
    if not root.is_dir():
        raise ValueError(f"capture root does not exist: {root}")
    return root


def _select_windows(
    audit_path: Path,
    capture_root_override: Path | None,
    start_frame: int,
    window_frames: int,
) -> tuple[Path, dict[str, Any], dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    audit = _read_json(audit_path)
    if audit.get("schema") != AUDIT_SCHEMA:
        raise ValueError(f"unexpected temporal audit schema: {audit.get('schema')!r}")
    reports = audit.get("reports")
    if not isinstance(reports, list):
        raise ValueError("temporal audit reports is not an array")
    if start_frame < 1 or window_frames < 2:
        raise ValueError("start_frame must be >=1 and window_frames must be >=2")

    root = _capture_root(audit, capture_root_override)
    ready: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    for raw in reports:
        if not isinstance(raw, dict):
            excluded.append({"sequence_id": "<malformed>", "reason": "malformed audit report"})
            continue
        sequence_id = str(raw.get("sequence") or "")
        if not sequence_id:
            excluded.append({"sequence_id": "<missing>", "reason": "missing sequence id"})
            continue
        if not bool(raw.get("temporal_ready")):
            excluded.append(
                {
                    "sequence_id": sequence_id,
                    "reason": "temporal_audit_not_ready",
                    "frames": int(raw.get("frames", 0)),
                    "host_frame_gap_max": raw.get("host_frame_gap_max"),
                    "backpressure_events": int(raw.get("backpressure_events", 0)),
                }
            )
            continue
        ready.append(raw)
    ready.sort(key=lambda item: (str(item.get("sequence")),))

    entries: list[dict[str, Any]] = []
    frame_windows: dict[str, list[dict[str, Any]]] = {}
    signature: tuple[Any, ...] | None = None
    for report in ready:
        sequence_id = str(report["sequence"])
        sequence_root = root / sequence_id
        sequence_meta_path = sequence_root / "sequence.json"
        frames_path = sequence_root / "frames.jsonl"
        if not sequence_meta_path.is_file() or not frames_path.is_file():
            raise ValueError(f"{sequence_id}: missing sequence.json or frames.jsonl")
        sequence_meta = _read_json(sequence_meta_path)
        if str(sequence_meta.get("sequence_id")) != sequence_id:
            raise ValueError(f"{sequence_id}: sequence.json identity mismatch")
        frames = _load_frames(frames_path)
        if len(frames) < start_frame - 1 + window_frames:
            raise ValueError(f"{sequence_id}: capture has only {len(frames)} frames")
        window = frames[start_frame - 1 : start_frame - 1 + window_frames]
        if len(window) != window_frames:
            raise ValueError(f"{sequence_id}: selected window length changed")
        identities = []
        for index, frame in enumerate(window):
            signature = _validate_frame_signature(frame, sequence_id, signature)
            identities.append((int(frame["frame_id"]), int(frame["sample_index"]), int(frame["host_frame"])))
            if frame.get("status") != "complete":
                raise ValueError(f"{sequence_id}: selected frame {index + start_frame} is not complete")
            if index > 0 and any(bool(v) for v in frame.get("history_reset", [])):
                raise ValueError(f"{sequence_id}: reset appears inside selected window")
        if window[0].get("history_reset") != [True, True]:
            raise ValueError(f"{sequence_id}: selected window does not start with [true, true]")
        for previous, current in zip(identities, identities[1:]):
            if tuple(b - a for a, b in zip(previous, current)) != (1, 1, 1):
                raise ValueError(f"{sequence_id}: selected window is not contiguous")
        entries.append(
            {
                "sequence_id": sequence_id,
                "sequence": sequence_id,
                "created_utc": int(sequence_meta["created_utc"]),
                "frames": window_frames,
                "complete": window_frames,
                "artifact_count": window_frames * 2 * len(REQUIRED_STAGES),
                "source_frame_range": [start_frame, start_frame + window_frames - 1],
                "source_sequence_frames": len(frames),
                "source_sequence_sha256": _sha256_file(sequence_meta_path),
                "source_frames_sha256": _sha256_file(frames_path),
                "source_temporal_report": report,
            }
        )
        frame_windows[sequence_id] = window

    if len(entries) < 3:
        raise ValueError("fewer than three strict sequences survived window selection")
    split = _split_sequence_ids(entries)
    membership = {sequence_id: name for name in ("train", "validation", "test") for sequence_id in split[name]}
    rows: list[dict[str, Any]] = []
    source_sequences: list[dict[str, Any]] = []
    for entry in sorted(entries, key=lambda item: (int(item["created_utc"]), item["sequence_id"])):
        sequence_id = entry["sequence_id"]
        sequence_root = root / sequence_id
        sequence_rows: list[dict[str, Any]] = []
        for frame in frame_windows[sequence_id]:
            for eye in (0, 1):
                row = _make_row(sequence_root, sequence_id, frame, eye, membership[sequence_id], crop_index=0)
                rows.append(row)
                sequence_rows.append(row)
        source_sequences.append(
            {
                "sequence_id": sequence_id,
                "created_utc": entry["created_utc"],
                "frames": window_frames,
                "source_sequence_frames": entry["source_sequence_frames"],
                "eye_rows": len(sequence_rows),
                "split": membership[sequence_id],
                "sequence_sha256": entry["source_sequence_sha256"],
                "frames_sha256": entry["source_frames_sha256"],
                "source_frame_range": entry["source_frame_range"],
                "first_history_reset": frame_windows[sequence_id][0].get("history_reset"),
                "temporal_report": entry["source_temporal_report"],
            }
        )
    selection = {
        "schema": SELECTION_SCHEMA,
        "capture_root": str(root),
        "source_audit": str(audit_path.resolve()),
        "source_audit_sha256": _sha256_file(audit_path),
        "window_start_frame": start_frame,
        "window_frames": window_frames,
        "selection_policy": "temporal_ready audit reports; first reset-qualified contiguous window; failed full clips are preserved and excluded",
        "selected_sequences": [item["sequence_id"] for item in source_sequences],
        "selected_sequence_count": len(source_sequences),
        "selected_frames": len(source_sequences) * window_frames,
        "excluded_sequences": excluded,
        "split": split,
        "source_sequences": source_sequences,
        "raw_validator": "capture_validate.json is required separately; this helper validates selected required crop artifacts and metadata",
    }
    candidate = {
        "schema": "opennr-crop-training-candidate-v1",
        "capture_root": str(root),
        "source_audit": str(audit_path.resolve()),
        "source_audit_sha256": _sha256_file(audit_path),
        "selection": selection["selection_policy"],
        "temporal_reset_policy": "strict_initial_reset",
        "expected_frames": window_frames,
        "candidate_sequences": len(entries),
        "candidate_frames": len(entries) * window_frames,
        "candidate_eye_pairs": len(entries) * window_frames * 2,
        "candidate_artifacts": len(entries) * window_frames * 2 * len(REQUIRED_STAGES),
        "sequences": [
            {
                "sequence": item["sequence_id"],
                "frames": window_frames,
                "complete": window_frames,
                "artifact_count": window_frames * 2 * len(REQUIRED_STAGES),
                "created_utc": item["created_utc"],
                "source_status": "strict-temporal-ready-window",
                "source_frame_range": item["source_frame_range"],
            }
            for item in source_sequences
        ],
    }
    provenance = {
        "candidate_manifest": "",
        "candidate_manifest_sha256": "",
        "capture_root": str(root),
        "crop_indices": [0],
        "source_audit": str(audit_path.resolve()),
        "source_audit_sha256": _sha256_file(audit_path),
        "window_start_frame": start_frame,
        "window_frames": window_frames,
        "selected_sequences": [item["sequence_id"] for item in source_sequences],
        "excluded_sequences": excluded,
        "source_sequences": source_sequences,
        "capture_signature": signature,
        "strict_initial_reset": True,
        "raw_color_contract": "R8G8B8A8_UNORM crop, PNG previews not required",
        "full_frame_anchor_policy": "periodic full-eye anchor remains spatial/context supervision only; not part of temporal rows",
    }
    return root, selection, candidate, rows, {"split": split, "provenance": provenance}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audit", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--selection-output", type=Path, required=True)
    parser.add_argument("--candidate-output", type=Path, required=True)
    parser.add_argument("--capture-root", type=Path)
    parser.add_argument("--start-frame", type=int, default=1)
    parser.add_argument("--window-frames", type=int, default=64)
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--metadata-only", action="store_true")
    args = parser.parse_args()
    if args.workers < 1:
        parser.error("--workers must be positive")
    audit_path = args.audit.resolve()
    root, selection, candidate, rows, details = _select_windows(
        audit_path, args.capture_root, args.start_frame, args.window_frames
    )
    selection_output = args.selection_output.resolve()
    candidate_output = args.candidate_output.resolve()
    selection_output.parent.mkdir(parents=True, exist_ok=True)
    candidate_output.parent.mkdir(parents=True, exist_ok=True)
    selection_output.write_text(json.dumps(selection, indent=2), encoding="utf-8")
    candidate_output.write_text(json.dumps(candidate, indent=2), encoding="utf-8")
    split = details["split"]
    provenance = details["provenance"]
    provenance["candidate_manifest"] = str(candidate_output)
    provenance["candidate_manifest_sha256"] = _sha256_file(candidate_output)
    summary = {
        "state": "validated_metadata_only" if args.metadata_only else "building",
        "capture_root": str(root),
        "selection_output": str(selection_output),
        "candidate_output": str(candidate_output),
        "output": str(args.output.resolve()),
        "sequences": len(provenance["source_sequences"]),
        "frames": len(provenance["source_sequences"]) * args.window_frames,
        "rows": len(rows),
        "sequence_counts": {name: len(split[name]) for name in ("train", "validation", "test")},
        "eye_row_counts": {name: sum(row["split"] == name for row in rows) for name in ("train", "validation", "test")},
        "excluded_sequences": selection["excluded_sequences"],
        "strict_initial_reset": True,
    }
    if args.metadata_only:
        print(json.dumps(summary, indent=2), flush=True)
        return 0
    report = _build_cache(
        rows,
        split,
        provenance,
        candidate_output,
        args.output.resolve(),
        args.workers,
        spatial_only=False,
        legacy_guide_alignment=False,
    )
    report["window_selection"] = str(selection_output)
    report["window_selection_sha256"] = _sha256_file(selection_output)
    report["full_frame_anchor_policy"] = provenance["full_frame_anchor_policy"]
    (args.output.resolve() / "complete.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
