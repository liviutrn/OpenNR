"""Discover exact current-frame reset/warm candidates in an aligned cache.

This is a read-only discovery step. It hashes only inference-available current
input, guides, context and renderer conditioning. Frozen-test rows are skipped
entirely, including their teacher target channel. The resulting manifest is a
candidate list; ``audit_renderer_state_pairs.py`` remains the acceptance gate.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np


def save(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, allow_nan=False), encoding="utf-8")


def row_key(row: dict[str, Any]) -> tuple[str, int, int]:
    return str(row["sequence_id"]), int(row["frame_id"]), int(row["eye"])


def current_signature(arrays: dict[str, np.ndarray], position: int) -> str:
    digest = hashlib.sha256()
    for name in ("rgb", "guides", "context", "conditioning"):
        value = arrays[name][position, 0] if name == "rgb" else arrays[name][position]
        value = np.ascontiguousarray(value)
        digest.update(name.encode("ascii"))
        digest.update(value.tobytes(order="C"))
    return digest.hexdigest()


def metadata_signature(row: dict[str, Any]) -> tuple[Any, ...]:
    return (
        row.get("eye"),
        row.get("crop_index"),
        row.get("route"),
        row.get("model_resolution_percent"),
        row.get("pass_count"),
        row.get("motion_vector_contract"),
        tuple(row.get("source_color_size", [])),
        tuple(row.get("source_guide_size", [])),
        tuple(row.get("motion_scale", [])),
        json.dumps(row.get("teacher_settings"), sort_keys=True),
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    args.output.mkdir(parents=True)

    cache = args.cache.resolve()
    complete = json.loads((cache / "complete.json").read_text(encoding="utf-8"))
    if complete.get("schema") != "opennr-aligned-renderer-pilot-v1":
        raise ValueError("cache is not an aligned renderer-conditioned cache")
    if int(complete.get("conditioning_channels", 0)) != 17:
        raise ValueError("cache does not contain the required 17 renderer channels")
    rows = json.loads((cache / "rows.json").read_text(encoding="utf-8"))
    arrays = {
        name: np.load(cache / f"{name}.npy", mmap_mode="r")
        for name in ("rgb", "guides", "context", "conditioning")
    }
    if any(value.shape[0] != len(rows) for value in arrays.values()):
        raise ValueError("cache array row count does not match rows.json")

    reset_groups: dict[tuple[str, tuple[Any, ...], str], list[tuple[int, dict[str, Any]]]] = {}
    warm_groups: dict[tuple[str, tuple[Any, ...], str], list[tuple[int, dict[str, Any]]]] = {}
    skipped_test = 0
    signatures = 0
    for position, row in enumerate(rows):
        if row.get("split") == "test":
            skipped_test += 1
            continue
        history = row.get("history_reset_pair")
        if history not in ([True, True], [False, False]):
            continue
        signature = current_signature(arrays, position)
        signatures += 1
        group = (str(row["split"]), metadata_signature(row), signature)
        target = reset_groups if history == [True, True] else warm_groups
        target.setdefault(group, []).append((position, row))

    candidates: list[dict[str, Any]] = []
    used_reset: set[tuple[str, int, int]] = set()
    used_warm: set[tuple[str, int, int]] = set()
    for group in sorted(set(reset_groups) & set(warm_groups), key=repr):
        resets = sorted(reset_groups[group], key=lambda item: row_key(item[1]))
        warms = sorted(warm_groups[group], key=lambda item: row_key(item[1]))
        for reset_position, reset in resets:
            reset_ref = row_key(reset)
            if reset_ref in used_reset:
                continue
            warm_choice = next(
                (
                    item
                    for item in warms
                    if row_key(item[1]) not in used_warm
                    and item[1]["sequence_id"] != reset["sequence_id"]
                ),
                None,
            )
            if warm_choice is None:
                continue
            warm_position, warm = warm_choice
            warm_ref = row_key(warm)
            used_reset.add(reset_ref)
            used_warm.add(warm_ref)
            candidates.append(
                {
                    "pair_id": f"discovered-{len(candidates) + 1:03d}",
                    "reset": {
                        "sequence_id": reset_ref[0],
                        "frame_id": reset_ref[1],
                        "eye": reset_ref[2],
                    },
                    "warm": {
                        "sequence_id": warm_ref[0],
                        "frame_id": warm_ref[1],
                        "eye": warm_ref[2],
                    },
                    "split": reset["split"],
                    "current_signature_sha256": current_signature(arrays, reset_position),
                    "reset_position": reset_position,
                    "warm_position": warm_position,
                }
            )

    manifest = {
        "schema": "opennr-renderer-state-pairs-v1",
        "description": "Candidates discovered by exact equality of current inference inputs; audit before use.",
        "pairs": [
            {key: value for key, value in pair.items() if key not in ("split", "current_signature_sha256", "reset_position", "warm_position")}
            for pair in candidates
        ],
    }
    report = {
        "schema": "opennr-renderer-state-pair-discovery-v1",
        "cache": str(cache),
        "cache_complete_sha256": hashlib.sha256((cache / "complete.json").read_bytes()).hexdigest(),
        "test_used": False,
        "non_test_reset_or_warm_rows_hashed": signatures,
        "test_rows_skipped": skipped_test,
        "candidate_pair_count": len(candidates),
        "candidates": candidates,
        "note": "Candidates still require the state-pair audit, including exact arrays, metadata and teacher-response signal.",
    }
    save(args.output / "state_pairs.json", manifest)
    save(args.output / "discovery.json", report)
    save(args.output / "status.json", {"state": "complete", "candidate_pair_count": len(candidates), "test_used": False})
    print(json.dumps(report), flush=True)


if __name__ == "__main__":
    main()
