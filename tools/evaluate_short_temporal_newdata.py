"""Evaluate a recovered semantic joint checkpoint on bounded short streams.

This evaluator deliberately bypasses the deleted historical cohort paths only
for model loading.  It reconstructs the exact parent from the joint checkpoint
and evaluates the new raw-crop cache without using any old cohort as a source
of metrics or tuning decisions.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path

import torch

from joint_parent_tone_model import JointParentToneModel
from prepare_conditioning_pilot import save
from semantic_tone_head import SemanticToneHead
from train_capacity_temporal_student import _load_parent
from train_semantic_newdata_paired import ShortTemporalCache
from train_temporal_student import evaluate_streaming


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_recovered_joint(path: Path, device: str):
    payload = torch.load(path, map_location="cpu", weights_only=False)
    recovery = payload.get("run", {}).get("parent_recovery")
    if not recovery:
        raise ValueError("Checkpoint is not labeled as a recovered joint checkpoint")
    parent_path = Path(payload["run"]["parent"])
    parent, *_ = _load_parent(parent_path, device=device)
    parent.load_state_dict(payload["parent_model"], strict=True)
    head = SemanticToneHead(False).to(device)
    head.load_state_dict(payload["head"], strict=True)
    return JointParentToneModel(parent, head).eval(), payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--device", choices=("cpu", "cuda"), default="cpu")
    args = parser.parse_args()

    if args.device == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("CUDA was requested but is not available")
    checkpoint = args.checkpoint.resolve()
    cache_root = args.cache.resolve()
    output = args.output.resolve()
    if output.exists():
        raise FileExistsError(output)
    output.mkdir(parents=True)

    model, payload = load_recovered_joint(checkpoint, args.device)
    report = {
        "checkpoint": str(checkpoint),
        "checkpoint_sha256": sha(checkpoint),
        "step": int(payload.get("step", 0)),
        "cache": str(cache_root),
        "cache_complete_sha256": sha(cache_root / "complete.json"),
        "device": args.device,
        "selection_policy": "validation is descriptive; test is held out and not used for tuning",
        "splits": {},
        "started_utc": int(time.time()),
    }
    for split in ("train", "validation", "test"):
        cache = ShortTemporalCache(cache_root, split)
        print(json.dumps({"state": "evaluating", "split": split, "sequences": cache.sequence_ids}), flush=True)
        metrics = evaluate_streaming(model, cache, device=args.device, batch=4)
        report["splits"][split] = {
            "sequence_ids": cache.sequence_ids,
            "stream_count": len(cache.streams),
            "metrics": metrics,
        }
        save(output / f"{split}.json", report["splits"][split])
        print(json.dumps({"split": split, "mae": metrics["mae"], "temporal_delta_mae": metrics["temporal_delta_mae"]}), flush=True)
    report["completed_utc"] = int(time.time())
    report["gpu_peak_gib"] = (
        torch.cuda.max_memory_allocated() / 2**30 if args.device == "cuda" else 0.0
    )
    save(output / "result.json", report)
    save(output / "status.json", {"state": "complete", "test_used_for_tuning": False})
    print(json.dumps(report, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
