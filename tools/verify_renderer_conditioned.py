"""Replay and verify the renderer-conditioned U-Net without test access."""

import argparse
import json
from pathlib import Path

from prepare_conditioning_pilot import save, sha
from renderer_conditioned_stable import (
    RendererFeatureAlignedCohort,
    load_renderer_checkpoint,
    evaluate_renderer_streaming,
)
from multilayer_teacher_mode import set_conditioned_teacher_mode as set_teacher_mode


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--final-checkpoint", action="store_true")
    args = parser.parse_args()
    status = json.loads((args.run / "status.json").read_text())
    if status.get("state") != "complete":
        raise ValueError("Renderer run is not complete")
    checkpoint = args.run / ("last.pt" if args.final_checkpoint else "best_all_cohorts.pt")
    model, payload = load_renderer_checkpoint(checkpoint)
    history = json.loads((args.run / "history.json").read_text())
    expected = history[-1] if args.final_checkpoint else next(
        item for item in history if item["step"] == payload["step"]
    )
    if payload["step"] != expected["step"]:
        raise ValueError("Checkpoint/history step mismatch")
    labels = payload["run"]["cohort_labels"]
    roots = payload["run"]["cohorts"]
    modes = payload["run"]["teacher_pass_counts"]
    if not (len(labels) == len(roots) == len(modes) == len(expected["validation"])):
        raise ValueError("Renderer cohort coverage mismatch")
    report = {
        "checkpoint": str(checkpoint),
        "sha256": sha(checkpoint),
        "step": payload["step"],
        "test_used": False,
        "cohorts": {},
    }
    for label, root, mode in zip(labels, roots, modes):
        set_teacher_mode(model.head, mode)
        cache = RendererFeatureAlignedCohort(Path(root), "validation", expected_pass_count=mode)
        metrics = evaluate_renderer_streaming(model, cache, device="cuda", batch=4)
        delta = {
            key: abs(metrics[key] - expected["validation"][label][key])
            for key in ("mae", "psnr", "temporal_delta_mae")
        }
        if max(delta.values()) > 1e-7:
            raise ValueError(f"Replay mismatch for {label}: {delta}")
        report["cohorts"][label] = {
            "metrics": metrics,
            "reproduction_difference": delta,
            "conditioning_schema": cache.complete.get("schema"),
        }
        print(json.dumps({"cohort": label, "mae": metrics["mae"], "verified": True}), flush=True)
    save(
        args.run / ("final_checkpoint_verification.json" if args.final_checkpoint else "checkpoint_verification.json"),
        report,
    )


if __name__ == "__main__":
    main()
