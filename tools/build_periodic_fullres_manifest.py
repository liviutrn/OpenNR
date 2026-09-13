"""Build a verified spatial-only manifest from periodic full-eye anchors.

The temporal pilot writes one complete full-resolution frame at its periodic
anchor (frame 240 in the current 80 FPS / three-second setup) and crop rows
for every frame.  This helper selects only the full-frame anchor, validates its
native RGB/guide artifacts and hashes, and writes a sequence-disjoint spatial
manifest.  It never treats the sparse anchors as recurrent temporal data.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def artifact(frame: dict[str, Any], stage: str, eye: int) -> dict[str, Any]:
    values = [
        value
        for value in frame.get("artifacts", [])
        if value.get("stage") == stage and int(value.get("eye", -1)) == eye and bool(value.get("full_frame"))
    ]
    if len(values) != 1:
        raise ValueError(f"frame {frame.get('frame_id')}: expected one full {stage} eye {eye}, got {len(values)}")
    return values[0]


def validate_artifact(sequence: Path, frame: dict[str, Any], value: dict[str, Any], stage: str, eye: int) -> dict[str, Any]:
    width, height = int(value["width"]), int(value["height"])
    source = value["source_rect"]
    crop = value["crop_rect"]
    if crop != source or [width, height] != [int(source["width"]), int(source["height"])]:
        raise ValueError(f"{sequence.name} frame {frame.get('frame_id')}: incomplete full {stage} eye {eye}")
    raw_rel = value.get("raw_path")
    raw = (sequence / raw_rel).resolve()
    if not raw.is_file() or raw.stat().st_size == 0 or not raw.is_relative_to(sequence.resolve()):
        raise ValueError(f"missing or unsafe full {stage} raw for eye {eye}: {raw}")
    expected = width * height * {28: 4, 41: 4, 34: 4}.get(int(value["format"]), 0)
    if expected <= 0 or raw.stat().st_size != expected:
        raise ValueError(f"full {stage} raw size mismatch: {raw} ({raw.stat().st_size} != {expected})")
    result = {
        "raw_path": str(raw),
        "raw_sha256": sha(raw),
        "width": width,
        "height": height,
        "format": int(value["format"]),
        "format_name": value.get("format_name"),
    }
    if stage in ("input", "teacher"):
        png_rel = value.get("png_path")
        png = (sequence / png_rel).resolve()
        if not png.is_file() or not png.is_relative_to(sequence.resolve()):
            raise ValueError(f"missing or unsafe full {stage} PNG for eye {eye}: {png}")
        result.update({"png_path": str(png), "png_sha256": sha(png)})
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--frame-id", type=int, default=240)
    args = parser.parse_args()
    root = args.capture_root.resolve()
    if not root.is_dir():
        raise FileNotFoundError(root)
    sequences = sorted((path for path in root.glob("*/sequence.json") if path.is_file()), key=lambda path: json.loads(path.read_text())["created_utc"])
    if len(sequences) < 5:
        raise ValueError("Expected at least five sequences")
    rows: list[dict[str, Any]] = []
    sequence_records: list[dict[str, Any]] = []
    train_count = max(1, int(round(len(sequences) * 0.60)))
    validation_count = max(1, int(round(len(sequences) * 0.20)))
    for index, sequence_meta_path in enumerate(sequences):
        sequence = sequence_meta_path.parent
        metadata = json.loads(sequence_meta_path.read_text(encoding="utf-8"))
        frames_path = sequence / "frames.jsonl"
        frames = [json.loads(line) for line in frames_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        matches = [frame for frame in frames if int(frame.get("frame_id", -1)) == args.frame_id]
        if len(matches) != 1:
            raise ValueError(f"{sequence.name}: expected exactly one frame {args.frame_id}, got {len(matches)}")
        frame = matches[0]
        if frame.get("status") != "complete" or frame.get("route") != "feature18_stereo" or int(frame.get("pass_count", 1)) != 1:
            raise ValueError(f"{sequence.name}: anchor has wrong status/route/pass")
        split = "train" if index < train_count else "validation" if index < train_count + validation_count else "test"
        selected: dict[str, dict[int, dict[str, Any]]] = {stage: {} for stage in ("input", "teacher", "depth", "motion_vectors")}
        for eye in (0, 1):
            for stage in selected:
                selected[stage][eye] = validate_artifact(sequence, frame, artifact(frame, stage, eye), stage, eye)
            rows.append({
                    "schema_version": 1,
                    "sequence_id": sequence.name,
                    "frame_id": args.frame_id,
                    "host_frame": int(frame["host_frame"]),
                    "eye": eye,
                    "split": split,
                    "color_size": [int(frame["color_width"]), int(frame["color_height"])],
                    "guide_size": [int(frame["guide_width"]), int(frame["guide_height"])],
                    "paths": {
                        "input": selected["input"][eye]["png_path"],
                        "teacher": selected["teacher"][eye]["png_path"],
                        "depth": selected["depth"][eye]["raw_path"],
                        "motion_vectors": selected["motion_vectors"][eye]["raw_path"],
                    },
                    "source_hashes": {
                        key: selected[key][eye]["raw_sha256"]
                        for key in ("input", "teacher", "depth", "motion_vectors")
                    },
                    "png_sha256": {
                        key: selected[key][eye]["png_sha256"]
                        for key in ("input", "teacher")
                    },
                    "motion_scale": [float(frame["motion_vector_scale_x"][eye]), float(frame["motion_vector_scale_y"][eye])],
                    "history_reset": bool(frame["history_reset"][eye]),
                    "teacher_settings": frame["teacher_settings"],
                    "temporal_training_eligible": False,
                    "source": "periodic_full_eye_master_spatial_only",
                    "source_sequence_sha256": sha(sequence_meta_path),
                    "source_frames_sha256": sha(frames_path),
            })
        sequence_records.append({
            "sequence_id": sequence.name,
            "created_utc": int(metadata["created_utc"]),
            "frame_id": args.frame_id,
            "split": split,
            "sequence_sha256": sha(sequence_meta_path),
            "frames_sha256": sha(frames_path),
            "source_frame": int(frame["sample_index"]),
            "host_frame": int(frame["host_frame"]),
            "full_artifacts": 16,
        })
    rows.sort(key=lambda row: (row["sequence_id"], int(row["eye"])) )
    args.output.resolve().parent.mkdir(parents=True, exist_ok=True)
    args.output.resolve().write_text("".join(json.dumps(row, separators=(",", ":")) + "\n" for row in rows), encoding="utf-8")
    manifest_sha = sha(args.output.resolve())
    summary = {
        "schema": "opennr-periodic-full-eye-spatial-manifest-v1",
        "root": str(root),
        "frame_id": args.frame_id,
        "capture_rate_fps": 80.0,
        "sequence_count": len(sequence_records),
        "eye_rows": len(rows),
        "sequence_splits": {split: [item["sequence_id"] for item in sequence_records if item["split"] == split] for split in ("train", "validation", "test")},
        "sequence_records": sequence_records,
        "manifest": str(args.output.resolve()),
        "manifest_sha256": manifest_sha,
        "spatial_only": True,
        "temporal_training_allowed": False,
        "test_used_for_tuning": False,
    }
    summary_path = args.output.with_suffix(".summary.json")
    summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
