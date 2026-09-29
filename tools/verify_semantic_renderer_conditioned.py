"""Independent replay verifier for the semantic renderer-conditioned pair."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import torch

from prepare_conditioning_pilot import save, sha
from renderer_conditioned_stable import evaluate_renderer_streaming
from semantic_renderer_conditioned import (
    RendererConditioningOverlay,
    RendererZeroCohort,
    load_trained_semantic_renderer_checkpoint,
)
from train_semantic_ablation import cohort


LABELS = [
    "prior",
    "high_effect",
    "renderer_pilot",
    "fresh_session",
    "renderer_state",
    "new_pairs",
    "full_eye_renderer",
]
FIELDS = (
    "mae",
    "psnr",
    "temporal_delta_mae",
    "first_frame_mae",
    "steady_frame_mae",
    "identity_mae",
    "improvement_pct",
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--batch", type=int, default=4)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    if args.batch < 1:
        raise ValueError("Batch must be positive")
    args.checkpoint = args.checkpoint.resolve()
    args.output = args.output.resolve()
    torch.backends.cudnn.benchmark = False
    raw = torch.load(args.checkpoint, map_location="cpu", weights_only=False)
    if raw.get("architecture") != "semantic_renderer_conditioned_joint_v1":
        raise ValueError("Unexpected checkpoint architecture")
    run = raw["run"]
    if run.get("test_used") or raw.get("test_used"):
        raise ValueError("Checkpoint is marked as test-used")
    module_path = Path(__file__).with_name("semantic_renderer_conditioned.py")
    trainer_path = Path(__file__).with_name("train_semantic_renderer_conditioned_pair.py")
    if sha(module_path) != run["renderer_model_source_sha256"]:
        raise ValueError("Renderer model source changed")
    if sha(trainer_path) != run["trainer_source_sha256"]:
        raise ValueError("Trainer source changed")
    checkpoint_sha = sha(args.checkpoint)
    model, loaded = load_trained_semantic_renderer_checkpoint(args.checkpoint)
    if sha(args.checkpoint) != checkpoint_sha:
        raise ValueError("Checkpoint changed during replay")
    overlay = RendererConditioningOverlay(Path(run["renderer_overlay"]), "validation")
    if sha(overlay.root / "complete.json") != run["renderer_overlay_complete_sha256"]:
        raise ValueError("Renderer overlay changed")
    old_roots = [Path(root) for root in run["old_cohorts"]]
    for root, digest in zip(old_roots, run["old_cohort_complete_sha256"]):
        if sha(root / "complete.json") != digest:
            raise ValueError(f"Old cohort changed: {root}")
    old_validation = [RendererZeroCohort(cohort(root, "validation")) for root in old_roots]
    if run.get("conditioning_active"):
        validation = old_validation + [overlay]
    else:
        validation = old_validation + [RendererZeroCohort(overlay.base)]
    metrics = {
        label: evaluate_renderer_streaming(model, cache, batch=args.batch)
        for label, cache in zip(LABELS, validation)
    }
    expected = raw["validation"]
    differences = {}
    for label in LABELS:
        differences[label] = {
            field: abs(metrics[label][field] - expected[label][field]) for field in FIELDS
        }
    max_difference = max(value for group in differences.values() for value in group.values())
    if max_difference > 1e-7:
        raise ValueError(f"Independent replay mismatch: {differences}")
    args.output.mkdir(parents=True)
    save(
        args.output / "result.json",
        {
            "state": "complete",
            "checkpoint": str(args.checkpoint),
            "checkpoint_sha256": checkpoint_sha,
            "step": int(raw["step"]),
            "mode": run["mode"],
            "validation": metrics,
            "differences": differences,
            "max_difference": max_difference,
            "test_used": False,
        },
    )
    save(args.output / "status.json", {"state": "complete", "max_difference": max_difference, "test_used": False})
    print(json.dumps({"state": "complete", "max_difference": max_difference}), flush=True)


if __name__ == "__main__":
    main()
