"""Create a train-only manifest from an audited full-resolution master sequence.

This is an explicit spatial-only bridge.  It validates that the source files
still match the audit hashes, references the lossless RGB PNGs and native guide
readbacks, and refuses frames with audit errors.  It never labels the result as
temporal supervision.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _read_frames(sequence_root: Path) -> dict[int, dict[str, Any]]:
    return {
        int(frame["frame_id"]): frame
        for line in (sequence_root / "frames.jsonl").read_text(
            encoding="utf-8"
        ).splitlines()
        if (frame := json.loads(line))
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audit", type=Path, required=True)
    parser.add_argument("--sequence-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    audit_root = args.audit.resolve()
    summary = json.loads((audit_root / "summary.json").read_text(encoding="utf-8"))
    source_root = Path(summary["root"]).resolve()
    report_path = audit_root / "sequences" / f"{args.sequence_id}.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    sequence_root = source_root / args.sequence_id
    if _sha256(sequence_root / "sequence.json") != report["sequence_sha256"]:
        raise ValueError(f"sequence metadata changed after audit: {sequence_root}")
    if _sha256(sequence_root / "frames.jsonl") != report["manifest_sha256"]:
        raise ValueError(f"frame manifest changed after audit: {sequence_root}")

    frames = _read_frames(sequence_root)
    rows: list[dict[str, Any]] = []
    for audited in report["frames"]:
        if audited.get("errors"):
            continue
        frame_id = int(audited["frame_id"])
        frame = frames[frame_id]
        artifacts = {
            (str(artifact["stage"]), int(artifact["eye"])): artifact
            for artifact in frame["artifacts"]
            if artifact.get("full_frame")
        }
        for eye in (0, 1):
            selected = {}
            for stage in ("input", "teacher", "depth", "motion_vectors"):
                artifact = artifacts.get((stage, eye))
                if artifact is None:
                    raise ValueError(f"{args.sequence_id} frame {frame_id}: missing {stage} eye {eye}")
                selected[stage] = artifact
            paths = {
                "input": str((sequence_root / selected["input"]["png_path"]).resolve()),
                "teacher": str((sequence_root / selected["teacher"]["png_path"]).resolve()),
                "depth": str((sequence_root / selected["depth"]["raw_path"]).resolve()),
                "motion_vectors": str(
                    (sequence_root / selected["motion_vectors"]["raw_path"]).resolve()
                ),
            }
            for path in paths.values():
                if not Path(path).is_file() or Path(path).stat().st_size == 0:
                    raise ValueError(f"missing or empty audited source file: {path}")
            rows.append(
                {
                    "schema_version": 1,
                    "sequence_id": args.sequence_id,
                    "frame_id": frame_id,
                    "host_frame": int(frame["host_frame"]),
                    "eye": eye,
                    "split": "train",
                    "color_size": [int(frame["color_width"]), int(frame["color_height"])],
                    "guide_size": [int(frame["guide_width"]), int(frame["guide_height"])],
                    "paths": paths,
                    "motion_scale": [
                        float(frame["motion_vector_scale_x"][eye]),
                        float(frame["motion_vector_scale_y"][eye]),
                    ],
                    "history_reset": bool(frame["history_reset"][eye]),
                    "teacher_settings": frame["teacher_settings"],
                    "temporal_training_eligible": False,
                    "source": "fullres_temporal_master_spatial_aux",
                    "source_audit": str(report_path),
                }
            )

    rows.sort(key=lambda row: (int(row["frame_id"]), int(row["eye"])))
    if not rows:
        raise ValueError("audit yielded no error-free full-resolution rows")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        "".join(json.dumps(row, separators=(",", ":")) + "\n" for row in rows),
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "state": "completed",
                "sequence_id": args.sequence_id,
                "frames": len(rows) // 2,
                "eye_rows": len(rows),
                "output": str(args.output.resolve()),
                "temporal_training_allowed": False,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
