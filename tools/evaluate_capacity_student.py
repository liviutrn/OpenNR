"""Evaluate a capacity-student checkpoint on a strict sequence split."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import torch

from perceptual_features import FeatureDistance
from opennr_student import load_student
from train_capacity_student import evaluate_strict
from train_temporal_student import StrictTemporalCache
from train_student import atomic_json


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--strict-cache", type=Path, required=True)
    parser.add_argument("--split", choices=("train", "validation", "test"), default="test")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is required for capacity evaluation")
    args.output.mkdir(parents=True, exist_ok=True)
    model, checkpoint = load_student(args.checkpoint, "cuda")
    cache = StrictTemporalCache(args.strict_cache, args.split)
    feature = FeatureDistance().cuda().eval()
    metrics = evaluate_strict(model, cache, "cuda", batch=2, feature=feature)
    result = {
        "checkpoint": str(args.checkpoint.resolve()),
        "checkpoint_sha256": hashlib.sha256(args.checkpoint.read_bytes()).hexdigest(),
        "step": int(checkpoint.get("step", -1)),
        "strict_cache": str(args.strict_cache.resolve()),
        "strict_rows_sha256": cache.rows_sha256,
        "metrics": metrics,
        "scope": "Strict sequence evaluation; spatial numeric quality only, not live VR or headset acceptance.",
    }
    atomic_json(args.output / "result.json", result)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
