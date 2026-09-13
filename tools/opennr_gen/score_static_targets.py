"""Compute advisory RGB/structure scores for generated GEN targets.

These numbers are evidence for review, not an automatic realism gate.  A
target can have a favorable teacher MAE while changing identity or materials,
so the paired visual review remains mandatory.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from PIL import Image


def _rgb(path: str | Path) -> np.ndarray:
    with Image.open(path) as image:
        return np.asarray(image.convert("RGB"), dtype=np.float32) / 255.0


def _edge(image: np.ndarray) -> np.ndarray:
    gray = 0.299 * image[..., 0] + 0.587 * image[..., 1] + 0.114 * image[..., 2]
    padded = np.pad(gray, 1, mode="edge")
    gx = padded[1:-1, 2:] - padded[1:-1, :-2]
    gy = padded[2:, 1:-1] - padded[:-2, 1:-1]
    return np.sqrt(gx * gx + gy * gy)


def _summary(source: np.ndarray, teacher: np.ndarray, target: np.ndarray) -> dict[str, float]:
    source_edge = _edge(source)
    teacher_edge = _edge(teacher)
    target_edge = _edge(target)
    source_luma = 0.299 * source[..., 0] + 0.587 * source[..., 1] + 0.114 * source[..., 2]
    teacher_luma = 0.299 * teacher[..., 0] + 0.587 * teacher[..., 1] + 0.114 * teacher[..., 2]
    target_luma = 0.299 * target[..., 0] + 0.587 * target[..., 1] + 0.114 * target[..., 2]
    return {
        "raw_teacher_mae": float(np.abs(source - teacher).mean()),
        "target_teacher_mae": float(np.abs(target - teacher).mean()),
        "target_raw_mae": float(np.abs(target - source).mean()),
        "target_teacher_edge_mae": float(np.abs(target_edge - teacher_edge).mean()),
        "target_raw_edge_mae": float(np.abs(target_edge - source_edge).mean()),
        "teacher_target_luma_mean_delta": float(target_luma.mean() - teacher_luma.mean()),
        "teacher_target_luma_std_delta": float(target_luma.std() - teacher_luma.std()),
        "target_clip_fraction": float(((target <= 1e-5) | (target >= 1.0 - 1e-5)).mean()),
        "target_saturation_mean": float((target.max(axis=2) - target.min(axis=2)).mean()),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--target-records", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    manifest = json.loads(args.manifest.resolve().read_text(encoding="utf-8"))
    records = json.loads(args.target_records.resolve().read_text(encoding="utf-8"))
    if records.get("manifest_sha256") != manifest.get("manifest_sha256"):
        raise ValueError("target records and static manifest differ")
    per_sample = {}
    for sample in manifest["samples"]:
        sample_id = sample["sample_id"]
        record = records.get("samples", {}).get(sample_id, {})
        if record.get("status") not in {"generated", "skipped_existing"}:
            continue
        target_path = Path(sample["enhanced_target_path"])
        if not target_path.exists():
            continue
        per_sample[sample_id] = {
            "pair_id": sample["pair_id"],
            "eye": sample["eye"],
            "student_split": sample["student_split"],
            **_summary(_rgb(sample["raw_input_path"]), _rgb(sample["teacher_path"]), _rgb(target_path)),
        }
    if not per_sample:
        raise ValueError("no generated targets to score")
    numeric_keys = [key for key in next(iter(per_sample.values())) if key.endswith(("mae", "delta", "fraction", "mean"))]
    mean = {
        key: float(np.mean([row[key] for row in per_sample.values()]))
        for key in numeric_keys
    }
    result = {
        "schema": "opennr-gen-static-target-scores-v1",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "manifest": str(args.manifest.resolve()),
        "manifest_sha256": manifest.get("manifest_sha256"),
        "target_records": str(args.target_records.resolve()),
        "target_count": len(per_sample),
        "mean": mean,
        "per_sample": per_sample,
        "interpretation": "advisory numeric evidence only; visual identity/material/stereo review remains mandatory",
    }
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(output), "target_count": len(per_sample), "mean": mean}, indent=2))


if __name__ == "__main__":
    main()

