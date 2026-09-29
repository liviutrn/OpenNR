"""Evaluate an isolated FastStudent-v1 checkpoint on a strict cache split."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import torch

from fast_student_v1 import FastStudentConfig, FastStudentV1, ScaleConditionedFastStudent
from train_temporal_student import StrictTemporalCache, evaluate_streaming


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--split", choices=("train", "validation", "test"), default="test")
    parser.add_argument("--work-scale", type=float)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is required for evaluation")

    saved = torch.load(args.checkpoint.resolve(), map_location="cuda", weights_only=False)
    if saved.get("architecture") != "fast_student_v1":
        raise ValueError("checkpoint is not a fast_student_v1 checkpoint")
    model = FastStudentV1(FastStudentConfig(**saved["config"])).cuda().eval()
    model.load_state_dict(saved["model"])
    work_scale = args.work_scale
    if work_scale is None:
        work_scale = float(saved.get("run", {}).get("work_scale", 1.0))
    runtime = ScaleConditionedFastStudent(model, work_scale).eval()
    cache = StrictTemporalCache(args.cache.resolve(), args.split)
    metrics = evaluate_streaming(runtime, cache, "cuda", batch=8)
    result = {
        "checkpoint": str(args.checkpoint.resolve()),
        "cache": str(args.cache.resolve()),
        "split": args.split,
        "work_scale": work_scale,
        "step": saved.get("step"),
        "best_mae": saved.get("best_mae"),
        "metrics": metrics,
        "note": "strict cache evaluation; test is not used for training or selection",
    }
    payload = json.dumps(result, indent=2)
    print(payload, flush=True)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
