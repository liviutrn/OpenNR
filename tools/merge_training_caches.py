"""Merge compatible OpenNR cache directories without touching their sources.

The historical full-resolution cache has multiple aligned crops per eye while
the newer raw-only cache has one already-cropped item per eye.  Both expose the
same trainer tensors, so they can be concatenated while preserving each
source's sequence split and remapping context-row references.  The output is a
new immutable cache identity; source caches remain unchanged.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path: Path, value) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, indent=2), encoding="utf-8")
    tmp.replace(path)


def load_source(root: Path, label: str) -> dict:
    complete_path = root / "complete.json"
    rows_path = root / "rows.json"
    patches_path = root / "patches.json"
    if not complete_path.exists() or not rows_path.exists() or not patches_path.exists():
        raise FileNotFoundError(f"{label} is missing cache metadata")
    complete = json.loads(complete_path.read_text(encoding="utf-8"))
    rows = json.loads(rows_path.read_text(encoding="utf-8"))
    patches = json.loads(patches_path.read_text(encoding="utf-8"))
    arrays = {
        name: np.load(root / f"{name}.npy", mmap_mode="r")
        for name in ("rgb", "guides", "context")
    }
    if arrays["rgb"].shape[0] != len(patches):
        raise ValueError(f"{label}: rgb rows do not match patches")
    if arrays["guides"].shape[0] != len(patches):
        raise ValueError(f"{label}: guide rows do not match patches")
    if arrays["context"].shape[0] != len(rows):
        raise ValueError(f"{label}: context rows do not match rows.json")
    if arrays["rgb"].shape[1:] != (2, 3, 512, 512):
        raise ValueError(f"{label}: unsupported RGB shape {arrays['rgb'].shape}")
    if arrays["guides"].shape[1:] != (5, 128, 128):
        raise ValueError(f"{label}: unsupported guide shape {arrays['guides'].shape}")
    if arrays["context"].shape[1:] != (8, 96, 96):
        raise ValueError(f"{label}: unsupported context shape {arrays['context'].shape}")
    if not np.isfinite(arrays["guides"]).all():
        raise ValueError(f"{label}: guide tensor contains non-finite values")
    if not np.isfinite(arrays["context"]).all():
        raise ValueError(f"{label}: context tensor contains non-finite values")
    # A cache row is normally an eye/frame/crop item, so several rows can
    # legitimately belong to the same capture sequence.  Keep the set for
    # cross-source overlap checks, but do not reject the within-source
    # multiplicity that the merged cache schema preserves.
    sequence_ids = {row.get("sequence_id") for row in rows}
    if not sequence_ids or None in sequence_ids:
        raise ValueError(f"{label}: rows contain missing sequence IDs")
    for patch in patches:
        if not 0 <= int(patch["row"]) < len(rows):
            raise ValueError(f"{label}: patch context row out of range")
        if patch.get("split") not in ("train", "validation", "test"):
            raise ValueError(f"{label}: unsupported split {patch.get('split')!r}")
    return {
        "label": label,
        "root": root.resolve(),
        "complete": complete,
        "complete_sha256": sha256(complete_path),
        "rows": rows,
        "patches": patches,
        "arrays": arrays,
        "sequence_ids": sequence_ids,
    }


def copy_array(destination: np.ndarray, source: np.ndarray, offset: int) -> None:
    chunk = 64
    for start in range(0, source.shape[0], chunk):
        destination[offset + start : offset + min(start + chunk, source.shape[0])] = source[
            start : min(start + chunk, source.shape[0])
        ]
    destination.flush()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", type=Path, action="append", required=True)
    parser.add_argument("--label", action="append", help="Optional label matching each --cache")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if len(args.cache) < 2:
        raise ValueError("At least two caches are required")
    if args.label and len(args.label) != len(args.cache):
        raise ValueError("--label must be supplied once per --cache")
    if args.output.exists() and any(args.output.iterdir()):
        raise ValueError(f"Refusing to reuse non-empty output directory: {args.output}")
    args.output.mkdir(parents=True, exist_ok=True)

    labels = args.label or [f"source_{i:02d}" for i in range(len(args.cache))]
    sources = [load_source(root, label) for root, label in zip(args.cache, labels)]
    strict_initial_reset = all(bool(source["complete"].get("strict_initial_reset")) for source in sources)
    seen_sequences = set()
    for source in sources:
        overlap = seen_sequences.intersection(source["sequence_ids"])
        if overlap:
            raise ValueError(f"Sequence IDs overlap between caches: {sorted(overlap)[:5]}")
        seen_sequences.update(source["sequence_ids"])

    patch_count = sum(source["arrays"]["rgb"].shape[0] for source in sources)
    row_count = sum(len(source["rows"]) for source in sources)
    rgb = np.lib.format.open_memmap(
        args.output / "rgb.npy", mode="w+", dtype=np.uint8, shape=(patch_count, 2, 3, 512, 512)
    )
    guides = np.lib.format.open_memmap(
        args.output / "guides.npy", mode="w+", dtype=np.float16, shape=(patch_count, 5, 128, 128)
    )
    context = np.lib.format.open_memmap(
        args.output / "context.npy", mode="w+", dtype=np.float16, shape=(row_count, 8, 96, 96)
    )

    merged_rows = []
    merged_patches = []
    source_records = []
    patch_offset = 0
    row_offset = 0
    for source in sources:
        arrays = source["arrays"]
        copy_array(rgb, arrays["rgb"], patch_offset)
        copy_array(guides, arrays["guides"], patch_offset)
        copy_array(context, arrays["context"], row_offset)
        for row in source["rows"]:
            enriched = dict(row)
            enriched["cache_source"] = source["label"]
            merged_rows.append(enriched)
        for patch in source["patches"]:
            enriched = dict(patch)
            enriched["row"] = int(patch["row"]) + row_offset
            enriched["cache_source"] = source["label"]
            merged_patches.append(enriched)
        source_records.append(
            {
                "label": source["label"],
                "root": str(source["root"]),
                "complete_sha256": source["complete_sha256"],
                "rows_sha256": source["complete"].get("rows_sha256"),
                "patches": len(source["patches"]),
                "rows": len(source["rows"]),
                "split_counts": {
                    split: sum(patch.get("split") == split for patch in source["patches"])
                    for split in ("train", "validation", "test")
                },
            }
        )
        patch_offset += len(source["patches"])
        row_offset += len(source["rows"])

    del rgb, guides, context
    rows_payload = json.dumps(merged_rows, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    rows_sha256 = hashlib.sha256(rows_payload).hexdigest()
    (args.output / "rows.json").write_bytes(json.dumps(merged_rows, indent=2).encode("utf-8"))
    (args.output / "patches.json").write_bytes(json.dumps(merged_patches, indent=2).encode("utf-8"))
    split_counts = {
        split: sum(patch.get("split") == split for patch in merged_patches)
        for split in ("train", "validation", "test")
    }
    row_split_counts = {
        split: sum(row.get("split") == split for row in merged_rows)
        for split in ("train", "validation", "test")
    }
    write_json(
        args.output / "split.json",
        {
            "policy": "preserve source sequence-level splits; no frame-level reshuffle",
            "source_caches": [record["label"] for record in source_records],
            "patch_counts": split_counts,
            "row_counts": row_split_counts,
        },
    )
    write_json(
        args.output / "provenance.json",
        {
            "schema": "opennr-merged-cache-provenance-v1",
            "source_caches": source_records,
            "rows_sha256": rows_sha256,
            "strict_initial_reset": strict_initial_reset,
            "temporal_training_allowed": strict_initial_reset,
            "test_used_for_tuning": False,
        },
    )
    write_json(
        args.output / "complete.json",
        {
            "schema": 3,
            "source_type": "merged_compatible_spatial_caches",
            "rows_sha256": rows_sha256,
            "patches": patch_count,
            "rows": row_count,
            "counts": split_counts,
            "row_counts": row_split_counts,
            "source_caches": source_records,
            "native_patch": 512,
            "guide_patch": 128,
            "context": 96,
            "strict_initial_reset": strict_initial_reset,
            "training_role": "strict_temporal_combined" if strict_initial_reset else "merged_spatial_only",
            "temporal_training_allowed": strict_initial_reset,
            "test_used_for_tuning": False,
        },
    )
    print(
        json.dumps(
            {
                "state": "completed",
                "output": str(args.output.resolve()),
                "patches": patch_count,
                "rows": row_count,
                "counts": split_counts,
                "row_counts": row_split_counts,
                "rows_sha256": rows_sha256,
            }
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
