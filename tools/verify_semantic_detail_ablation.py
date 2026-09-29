"""Independently replay a semantic detail ablation checkpoint."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import torch

from joint_parent_tone_model import load_joint_checkpoint
from prepare_conditioning_pilot import save, sha
from semantic_detail_head import SemanticDetailOnlyModel
from train_semantic_ablation import cohort
from train_temporal_student import evaluate_streaming


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)

    payload = torch.load(args.checkpoint, map_location="cpu", weights_only=False)
    if payload.get("architecture") != "semantic_detail_only_v1":
        raise ValueError("Expected semantic detail checkpoint")
    run = payload["run"]
    base_path = Path(run["base_checkpoint"])
    if sha(base_path) != run["base_checkpoint_sha256"]:
        raise ValueError("Base checkpoint identity changed")
    base_model, base_payload = load_joint_checkpoint(base_path)
    if int(base_payload["step"]) != int(run["base_step"]):
        raise ValueError("Base step mismatch")
    model = SemanticDetailOnlyModel(
        base_model.parent,
        base_model.head,
        width=int(run["width"]),
        scale=float(run["detail_scale"]),
    ).cuda()
    model.detail_head.detail.load_state_dict(payload["detail"], strict=True)
    model.eval()
    args.output.mkdir(parents=True)
    report = {
        "architecture": "semantic_detail_only_v1",
        "checkpoint": str(args.checkpoint.resolve()),
        "sha256": sha(args.checkpoint),
        "step": int(payload["step"]),
        "base_checkpoint": str(base_path.resolve()),
        "base_checkpoint_sha256": run["base_checkpoint_sha256"],
        "cohorts": {},
        "test_used": False,
    }
    for label, root in zip(run["cohort_labels"], run["cohorts"]):
        save(args.output / "status.json", {"state": "evaluating", "cohort": label})
        cache = cohort(Path(root), "validation")
        metrics = evaluate_streaming(model, cache, batch=4)
        expected = payload["validation"][label]
        differences = {
            key: abs(metrics[key] - expected[key])
            for key in ("mae", "psnr", "temporal_delta_mae")
        }
        if max(differences.values()) > 1e-7:
            raise ValueError(f"Independent replay mismatch for {label}: {differences}")
        report["cohorts"][label] = {"metrics": metrics, "replay_difference": differences}
        save(args.output / "result.json", report)
        print(json.dumps({"cohort": label, "mae": metrics["mae"]}), flush=True)
    save(args.output / "status.json", {"state": "complete", "test_used": False})


if __name__ == "__main__":
    main()
