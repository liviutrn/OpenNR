"""Evaluate frozen raw-crop checkpoints on the held-out sequence split.

This evaluator is deliberately separate from training and validation selection.
It consumes the cache's immutable ``test`` rows once a checkpoint is frozen,
checks the cache identity carried by every checkpoint, and records both the
model error and the input-to-teacher identity baseline.  The result is a
spatial crop metric; it is not a temporal, headset, or live-runtime gate.
"""
import argparse
from pathlib import Path
import hashlib
import json
import math
import time

import torch
from torch.utils.data import DataLoader, Subset

from opennr_student import load_student
from train_student import CachedPatches, evaluate, atomic_json


def label_for(path: Path) -> str:
    """Return a stable human-readable label for a checkpoint path."""
    return path.stem


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--checkpoint",
        type=Path,
        action="append",
        required=True,
        help="Frozen checkpoint to evaluate; repeat for multiple candidates.",
    )
    parser.add_argument("--batch", type=int, default=8)
    parser.add_argument("--workers", type=int, default=0)
    args = parser.parse_args()

    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is required for the frozen checkpoint evaluation")
    if args.batch < 1:
        raise ValueError("--batch must be positive")
    if args.workers < 0:
        raise ValueError("--workers cannot be negative")

    args.output.mkdir(parents=True, exist_ok=True)
    torch.set_num_threads(4)
    torch.backends.cudnn.benchmark = True

    cache_path = args.cache / "complete.json"
    if not cache_path.exists():
        raise FileNotFoundError(f"Missing cache completion metadata: {cache_path}")
    cache = json.loads(cache_path.read_text(encoding="utf-8"))
    if cache.get("schema") not in (2, 3):
        raise ValueError(f"Unsupported cache schema: {cache.get('schema')!r}")
    if cache.get("test_used_for_tuning"):
        raise ValueError("Cache is marked as having used the test split for tuning")

    test = CachedPatches(args.cache, "test")
    if not len(test):
        raise ValueError("The frozen test split is empty")
    loader = DataLoader(
        test,
        batch_size=args.batch,
        shuffle=False,
        num_workers=args.workers,
        pin_memory=True,
    )

    started = time.time()
    candidates = {}
    for checkpoint_path in args.checkpoint:
        checkpoint_path = checkpoint_path.resolve()
        if not checkpoint_path.exists():
            raise FileNotFoundError(checkpoint_path)
        model, checkpoint = load_student(checkpoint_path, "cuda")
        checkpoint_cache = checkpoint.get("cache", {})
        expected_rows = cache.get("rows_sha256")
        if checkpoint_cache.get("rows_sha256") != expected_rows:
            raise ValueError(
                "Dataset identity mismatch for "
                f"{checkpoint_path}: {checkpoint_cache.get('rows_sha256')} != {expected_rows}"
            )
        metrics = evaluate(model, loader, "cuda")
        source_metrics = {}
        if cache.get("schema") == 3:
            source_names = sorted({
                str(test.plan[i].get("cache_source", "unknown"))
                for i in test.ids
            })
            for source_name in source_names:
                positions = [
                    pos for pos, plan_index in enumerate(test.ids)
                    if str(test.plan[plan_index].get("cache_source", "unknown")) == source_name
                ]
                if not positions:
                    continue
                source_loader = DataLoader(
                    Subset(test, positions),
                    batch_size=args.batch,
                    shuffle=False,
                    num_workers=args.workers,
                    pin_memory=True,
                )
                source_metrics[source_name] = evaluate(model, source_loader, "cuda")
        label = label_for(checkpoint_path)
        if label in candidates:
            raise ValueError(f"Duplicate checkpoint label: {label}")
        candidates[label] = {
            "checkpoint": str(checkpoint_path),
            "checkpoint_sha256": hashlib.sha256(checkpoint_path.read_bytes()).hexdigest(),
            "architecture": checkpoint.get("architecture", "legacy_rgb_or_guided"),
            "step": int(checkpoint.get("step", -1)),
            "metrics": metrics,
            "source_metrics": source_metrics,
        }
        print(json.dumps({"label": label, **candidates[label]}), flush=True)
        del model, checkpoint

    result = {
        "schema": "opennr-frozen-raw-crop-test-v1",
        "selection": "frozen checkpoints evaluated after validation-only selection",
        "cache": {
            "path": str(args.cache.resolve()),
            "schema": cache.get("schema"),
            "rows_sha256": cache.get("rows_sha256"),
            "source_root": cache.get("source_root"),
            "test_sequences": cache.get("sequence_counts", {}).get("test"),
            "test_eye_rows": cache.get("eye_row_counts", {}).get(
                "test", cache.get("row_counts", {}).get("test")
            ),
            "source_caches": cache.get("source_caches", []),
        },
        "split": "test",
        "test_used_for_tuning": False,
        "scope": (
            "Held-out raw-backed 512x512 eye crops grouped by sequence; "
            "spatial numeric quality only, not temporal, stereo-headset, "
            "or live-runtime acceptance."
        ),
        "batch": args.batch,
        "workers": args.workers,
        "candidates": candidates,
        "seconds": time.time() - started,
    }
    atomic_json(args.output / "result.json", result)
    atomic_json(args.output / "status.json", {
        "state": "completed",
        "split": "test",
        "candidates": len(candidates),
        "seconds": result["seconds"],
    })
    print(json.dumps({
        "state": "completed",
        "test_eye_rows": result["cache"]["test_eye_rows"],
        "candidates": list(candidates),
        "seconds": result["seconds"],
    }), flush=True)


if __name__ == "__main__":
    main()
