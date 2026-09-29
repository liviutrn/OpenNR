"""Independent validation replay for the dual-context semantic experiment."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from joint_parent_tone_model import load_joint_checkpoint
from prepare_conditioning_pilot import save, sha
from train_semantic_context_pair import PatchSet, metric
from train_semantic_ablation import cohort
from train_temporal_student import evaluate_streaming


LABELS = [
    "prior",
    "high_effect",
    "renderer_pilot",
    "fresh_session",
    "renderer_state",
    "new_pairs",
]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--split", choices=("validation",), default="validation")
    parser.add_argument("--spatial-batch", type=int, default=1)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    args.checkpoint = args.checkpoint.resolve()
    args.output = args.output.resolve()
    import torch

    checkpoint_sha = sha(args.checkpoint)
    raw = torch.load(args.checkpoint, map_location="cpu", weights_only=False)
    if raw.get("architecture") != "semantic_joint_parent_v1":
        raise ValueError("Unexpected checkpoint architecture")
    run = raw["run"]
    model, loaded = load_joint_checkpoint(args.checkpoint)
    if sha(args.checkpoint) != checkpoint_sha:
        raise ValueError("Checkpoint changed during replay")
    old_roots = [Path(root) for root in run["cohorts"]]
    if run.get("cohort_labels") != LABELS:
        raise ValueError("Unexpected old cohort labels")
    validation = [cohort(root, args.split) for root in old_roots]
    old_metrics = {
        label: evaluate_streaming(model, cache, batch=4)
        for label, cache in zip(LABELS, validation)
    }
    spatial_root = Path(run["spatial_cache"])
    complete = json.loads((spatial_root / "complete.json").read_text(encoding="utf-8"))
    if complete.get("temporal_training_allowed", True):
        raise ValueError("Spatial cache is not explicitly spatial-only")
    patches = json.loads((spatial_root / "patches.json").read_text(encoding="utf-8"))
    spatial = PatchSet(spatial_root, patches, args.split)
    spatial_metrics = metric(model, spatial, "full", args.spatial_batch, "cuda")
    expected_old = raw["validation"]
    expected_spatial = raw.get("context_validation")
    if expected_spatial is None:
        raise ValueError("Checkpoint has no spatial validation record")
    differences = {}
    for label in LABELS:
        differences[label] = {
            key: abs(old_metrics[label][key] - expected_old[label][key])
            for key in ("mae", "psnr", "temporal_delta_mae", "first_frame_mae")
        }
    differences["full_eye_spatial"] = {
        key: abs(spatial_metrics[key] - expected_spatial[key])
        for key in ("mae", "rmse")
    }
    max_difference = max(value for group in differences.values() for value in group.values())
    if max_difference > 1e-7:
        raise ValueError(f"Independent replay mismatch: {differences}")
    args.output.mkdir(parents=True)
    save(args.output / "result.json", {
        "state": "complete",
        "checkpoint": str(args.checkpoint),
        "checkpoint_sha256": sha(args.checkpoint),
        "step": raw["step"],
        "split": args.split,
        "validation": old_metrics,
        "full_eye_spatial_validation": spatial_metrics,
        "differences": differences,
        "max_difference": max_difference,
        "test_used": False,
    })
    save(args.output / "status.json", {"state": "complete", "test_used": False})
    print(json.dumps({"state": "complete", "max_difference": max_difference}), flush=True)


if __name__ == "__main__":
    main()
