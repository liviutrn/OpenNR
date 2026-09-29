#!/usr/bin/env python3
"""Monitor an OpenNR capture root without changing the capture files.

This is a live-progress aid, not the acceptance gate.  It reads committed
JSONL records, ignores an incomplete final line, and reports the counters that
matter for a temporal clip: frame/sample/host gaps, reset boundaries,
backpressure, drops, and complete full-frame stage/eye coverage.  Run the
normal validators after the game exits.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REQUIRED_STAGES = {"input", "teacher", "depth", "motion_vectors"}


def sequence_roots(root: Path) -> list[Path]:
    if root.is_file() and root.name == "frames.jsonl":
        return [root.parent]
    if not root.is_dir():
        return []
    return sorted({path.parent.resolve() for path in root.rglob("frames.jsonl")})


def read_rows(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return rows
    for line in lines:
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            # A writer may be in the middle of appending the current record.
            continue
        if isinstance(value, dict):
            rows.append(value)
    return rows


def gaps(rows: list[dict[str, Any]], key: str) -> list[int]:
    values = [int(row[key]) for row in rows if isinstance(row.get(key), (int, float))]
    return [b - a for a, b in zip(values, values[1:])]


def full_keys(row: dict[str, Any]) -> set[tuple[str, int]]:
    result: set[tuple[str, int]] = set()
    for artifact in row.get("artifacts", []):
        if not isinstance(artifact, dict) or not artifact.get("full_frame", False):
            continue
        try:
            result.add((str(artifact["stage"]), int(artifact["eye"])))
        except (KeyError, TypeError, ValueError):
            continue
    return result


def is_complete_full(row: dict[str, Any]) -> bool:
    if row.get("status") != "complete":
        return False
    keys = full_keys(row)
    return all((stage, eye) in keys for stage in REQUIRED_STAGES for eye in (0, 1))


def summarize_sequence(path: Path, expected_frames: int) -> dict[str, Any]:
    rows = read_rows(path / "frames.jsonl")
    frame_gaps = gaps(rows, "frame_id")
    sample_gaps = gaps(rows, "sample_index")
    host_gaps = gaps(rows, "host_frame")
    complete = [row for row in rows if row.get("status") == "complete"]
    resets = [row.get("history_reset") for row in rows if isinstance(row.get("history_reset"), list)]
    initial_reset = resets[0] if resets else None
    mid_resets = [index + 1 for index, reset in enumerate(resets[1:], start=1) if any(reset)]
    return {
        "sequence": path.name,
        "path": str(path),
        "records": len(rows),
        "complete_records": len(complete),
        "expected_frames": expected_frames or None,
        "full_frame_complete": sum(is_complete_full(row) for row in complete),
        "initial_reset": initial_reset,
        "mid_reset_indices": mid_resets,
        "frame_gaps": sorted(set(frame_gaps)),
        "sample_gaps": sorted(set(sample_gaps)),
        "host_gaps": sorted(set(host_gaps)),
        "max_backpressure_events": max(
            (int(row.get("backpressure_events_before", 0) or 0) for row in rows), default=0
        ),
        "max_dropped_frames": max(
            (int(row.get("dropped_frames_before", 0) or 0) for row in rows), default=0
        ),
        "last_status": rows[-1].get("status") if rows else None,
        "ready_shape": (
            bool(rows)
            and len(complete) == len(rows)
            and (not expected_frames or len(complete) == expected_frames)
            and len(complete) >= 2
            and all(value == 1 for value in frame_gaps + sample_gaps + host_gaps)
            and initial_reset == [True, True]
            and not mid_resets
            and max(int(row.get("backpressure_events_before", 0) or 0) for row in rows) == 0
            and max(int(row.get("dropped_frames_before", 0) or 0) for row in rows) == 0
            and sum(is_complete_full(row) for row in complete) == len(complete)
        )
        if rows
        else False,
    }


def summarize(root: Path, expected_frames: int) -> dict[str, Any]:
    sequences = [summarize_sequence(path, expected_frames) for path in sequence_roots(root)]
    return {
        "schema": "opennr-temporal-capture-monitor-v1",
        "observed_utc": datetime.now(timezone.utc).isoformat(),
        "root": str(root),
        "sequences": len(sequences),
        "total_records": sum(item["records"] for item in sequences),
        "total_complete_records": sum(item["complete_records"] for item in sequences),
        "ready_shape_sequences": sum(item["ready_shape"] for item in sequences),
        "sequences_with_backpressure": sum(item["max_backpressure_events"] > 0 for item in sequences),
        "sequences_with_drops": sum(item["max_dropped_frames"] > 0 for item in sequences),
        "sequences_with_host_gaps": sum(item["host_gaps"] != [1] for item in sequences if item["records"] > 1),
        "reports": sequences,
    }


def print_human(summary: dict[str, Any]) -> None:
    print(
        f"[{summary['observed_utc']}] sequences={summary['sequences']} "
        f"records={summary['total_records']} complete={summary['total_complete_records']} "
        f"shape_ready={summary['ready_shape_sequences']} "
        f"backpressure={summary['sequences_with_backpressure']} "
        f"drops={summary['sequences_with_drops']} "
        f"host_gap_sequences={summary['sequences_with_host_gaps']}",
        flush=True,
    )
    for report in summary["reports"][-3:]:
        print(
            f"  {report['sequence']}: {report['complete_records']} records "
            f"full={report['full_frame_complete']} reset={report['initial_reset']} "
            f"host={report['host_gaps']} bp={report['max_backpressure_events']} "
            f"drop={report['max_dropped_frames']} ready={report['ready_shape']}",
            flush=True,
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path, help="capture root or one sequence directory")
    parser.add_argument("--expected-frames", type=int, default=64)
    parser.add_argument("--watch", action="store_true", help="poll until interrupted")
    parser.add_argument("--interval", type=float, default=2.0)
    parser.add_argument("--json", action="store_true", help="print one machine-readable report")
    args = parser.parse_args()
    if args.interval <= 0:
        parser.error("--interval must be positive")
    while True:
        summary = summarize(args.root, args.expected_frames)
        if args.json:
            print(json.dumps(summary, indent=2))
        else:
            print_human(summary)
        if not args.watch:
            return 0 if summary["sequences"] else 1
        try:
            time.sleep(args.interval)
        except KeyboardInterrupt:
            return 0


if __name__ == "__main__":
    raise SystemExit(main())
