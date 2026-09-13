"""Create a small immutable manifest that references an existing OpenNR cache."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

import numpy as np


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            block = handle.read(chunk_size)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-cache", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    source = args.source_cache.resolve()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    complete_path = source / "complete.json"
    rows_path = source / "rows.json"
    patches_path = source / "patches.json"
    rgb_path = source / "rgb.npy"
    for path in (complete_path, rows_path, patches_path, rgb_path):
        if not path.exists():
            raise FileNotFoundError(path)

    complete = json.loads(complete_path.read_text(encoding="utf-8"))
    if complete.get("test_used_for_tuning") is not False:
        raise ValueError("source cache does not explicitly protect its test split")
    rows = json.loads(rows_path.read_text(encoding="utf-8"))
    patches = json.loads(patches_path.read_text(encoding="utf-8"))
    rgb = np.load(rgb_path, mmap_mode="r")
    if len(rows) != len(patches) or len(rows) != rgb.shape[0]:
        raise ValueError("source row, patch, and RGB counts disagree")
    if rgb.ndim != 5 or tuple(rgb.shape[1:3]) != (2, 3):
        raise ValueError(f"unexpected RGB array shape: {rgb.shape}")
    required = {"sequence_id", "frame_id", "eye", "split", "cache_source"}
    missing = sorted(required.difference(rows[0]))
    if missing:
        raise ValueError(f"source rows miss required provenance keys: {missing}")

    row_indices: dict[str, list[int]] = {"train": [], "validation": [], "test": []}
    sequence_splits: dict[str, set[str]] = defaultdict(set)
    cohort_counts: dict[str, Counter] = defaultdict(Counter)
    eye_counts: dict[str, Counter] = defaultdict(Counter)
    for index, row in enumerate(rows):
        split = row["split"]
        if split not in row_indices:
            raise ValueError(f"unexpected row split {split!r} at {index}")
        if int(row["eye"]) not in (0, 1):
            raise ValueError(f"unexpected eye at {index}")
        row_indices[split].append(index)
        sequence_splits[str(row["sequence_id"])].add(split)
        cohort_counts[split][str(row["cache_source"])] += 1
        eye_counts[split][str(row["eye"])] += 1
    crossed = {sequence: sorted(splits) for sequence, splits in sequence_splits.items() if len(splits) != 1}
    if crossed:
        raise ValueError(f"sequence-level split violation: {list(crossed.items())[:3]}")

    split_sequences = {
        split: sorted({str(rows[index]["sequence_id"]) for index in indices})
        for split, indices in row_indices.items()
    }
    payload = {
        "schema": "opennr-tiny-enhancement-manifest-v1",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "source_cache": str(source),
        "source_complete_sha256": sha256_file(complete_path),
        "source_rows_file_sha256": sha256_file(rows_path),
        "source_patches_file_sha256": sha256_file(patches_path),
        "source_complete_rows_sha256": complete.get("rows_sha256"),
        "rgb_file_size": rgb_path.stat().st_size,
        "rgb_file_mtime_ns": rgb_path.stat().st_mtime_ns,
        "rgb_shape": list(rgb.shape),
        "rgb_dtype": str(rgb.dtype),
        "row_count": len(rows),
        "split_counts": {split: len(indices) for split, indices in row_indices.items()},
        "sequence_counts": {split: len(value) for split, value in split_sequences.items()},
        "cohort_counts": {split: dict(sorted(value.items())) for split, value in cohort_counts.items()},
        "eye_counts": {split: dict(sorted(value.items())) for split, value in eye_counts.items()},
        "split_sequences": split_sequences,
        "row_indices": row_indices,
        "test_used_for_tuning": False,
        "selection_policy": "checkpoint selection uses validation only; test is evaluated once after freeze",
        "unused_channels": ["depth", "native_motion_vectors", "renderer_conditioning", "history_reset", "stereo_partner"],
        "source_contract": {
            "input": "rgb.npy[:,0]",
            "teacher": "rgb.npy[:,1]",
            "normalization": "uint8 / 255.0",
            "resolution": list(rgb.shape[-2:]),
        },
    }
    signature = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    payload["manifest_sha256"] = signature
    manifest_path = output / "manifest.json"
    manifest_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    (output / "manifest.sha256").write_text(signature + "  manifest.json\n", encoding="utf-8")
    print(json.dumps({
        "manifest": str(manifest_path),
        "manifest_sha256": signature,
        "source_cache": str(source),
        "rgb_shape": list(rgb.shape),
        "split_counts": payload["split_counts"],
        "sequence_counts": payload["sequence_counts"],
        "cohort_counts": payload["cohort_counts"],
        "test_used_for_tuning": False,
    }, indent=2))


if __name__ == "__main__":
    main()

