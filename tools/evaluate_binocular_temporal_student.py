"""Evaluate paired-eye binocular checkpoints on a frozen strict test split."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import time

import torch

from opennr_student import load_student
from train_binocular_temporal_student import (
    PairedStrictTemporalCache,
    evaluate_pair_streaming,
)
from train_student import atomic_json


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--checkpoint", type=Path, action="append", required=True)
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--batch", type=int, default=1)
    args = parser.parse_args()
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is required for paired frozen-test evaluation")
    if args.batch < 1:
        raise ValueError("--batch must be positive")
    args.output.mkdir(parents=True, exist_ok=True)
    cache = PairedStrictTemporalCache(args.cache, "test")
    candidates = {}
    started = time.time()
    for path in args.checkpoint:
        path = path.resolve()
        model, checkpoint = load_student(path, "cuda")
        if checkpoint.get("architecture") != "context_v8_binocular_capacity_temporal":
            raise ValueError(f"Not a binocular checkpoint: {path}")
        checkpoint_cache = checkpoint.get("cache", {})
        if checkpoint_cache.get("rows_sha256") != cache.rows_sha256:
            raise ValueError(
                f"Dataset identity mismatch: {checkpoint_cache.get('rows_sha256')} != {cache.rows_sha256}"
            )
        metrics = evaluate_pair_streaming(model, cache, "cuda", batch=args.batch)
        label = path.stem
        if label in candidates:
            raise ValueError(f"Duplicate checkpoint label: {label}")
        candidates[label] = {
            "checkpoint": str(path),
            "checkpoint_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "step": int(checkpoint.get("step", -1)),
            "metrics": metrics,
        }
        print(json.dumps({"label": label, **candidates[label]}), flush=True)
        del model, checkpoint
    result = {
        "schema": "opennr-frozen-paired-temporal-test-v1",
        "selection": "Frozen paired-eye sequence test after validation-only selection",
        "cache": str(args.cache.resolve()),
        "cache_rows_sha256": cache.rows_sha256,
        "split": "test",
        "paired_sequences": len(cache.paired_sequence_ids),
        "eye_streams": len(cache.streams),
        "test_used_for_tuning": False,
        "scope": "Synchronized left/right strict streaming crop evaluation; not live stereo-headset or runtime acceptance.",
        "batch": args.batch,
        "candidates": candidates,
        "seconds": time.time() - started,
    }
    atomic_json(args.output / "result.json", result)
    atomic_json(
        args.output / "status.json",
        {"state": "completed", "split": "test", "candidates": len(candidates), "seconds": result["seconds"]},
    )
    print(json.dumps({"state": "completed", "candidates": list(candidates), "seconds": result["seconds"]}))


if __name__ == "__main__":
    main()
