"""Evaluate a temporal checkpoint on a sequence-held-out strict cache."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from train_temporal_student import StrictTemporalCache, _load_temporal, evaluate_streaming
from train_student import atomic_json


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--split", choices=("train", "validation", "test"), default="validation")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    cache = StrictTemporalCache(args.cache, args.split)
    model, checkpoint = _load_temporal(args.checkpoint)
    metrics = evaluate_streaming(model, cache, "cuda", batch=8)
    result = {
        "checkpoint": str(args.checkpoint.resolve()),
        "checkpoint_sha256": hashlib.sha256(args.checkpoint.read_bytes()).hexdigest(),
        "step": checkpoint.get("step"),
        "cache": str(args.cache.resolve()),
        "cache_rows_sha256": cache.rows_sha256,
        "metrics": metrics,
        "scope": "Streaming sequence evaluation with explicit reset at every eye stream; no live VR or headset acceptance.",
    }
    atomic_json(args.output / "result.json", result)
    atomic_json(args.output / "status.json", {"state": "completed", "split": args.split})
    print(json.dumps(result, indent=2), flush=True)


if __name__ == "__main__":
    main()

