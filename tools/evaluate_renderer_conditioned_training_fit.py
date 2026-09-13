"""Training-split replay for the renderer-conditioned experiment only."""

import argparse
import json
from pathlib import Path

from multilayer_teacher_mode import set_conditioned_teacher_mode as set_teacher_mode
from prepare_conditioning_pilot import save, sha
from renderer_conditioned_stable import (
    RendererFeatureAlignedCohort,
    evaluate_renderer_streaming,
    load_renderer_checkpoint,
)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--final-checkpoint", action="store_true")
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    args.output.mkdir(parents=True)
    checkpoint = args.run / ("last.pt" if args.final_checkpoint else "best_all_cohorts.pt")
    model, payload = load_renderer_checkpoint(checkpoint)
    verified = json.loads((args.run / "final_checkpoint_verification.json").read_text())
    if sha(checkpoint) != verified["sha256"]:
        raise ValueError("Selected checkpoint is not the verified checkpoint")
    report = {
        "checkpoint": str(checkpoint),
        "sha256": sha(checkpoint),
        "step": payload["step"],
        "scope": "training-fit diagnostic, no optimizer, no test access",
        "test_used": False,
        "cohorts": {},
    }
    run = payload["run"]
    for label, root, mode, expected in zip(
        run["cohort_labels"],
        run["cohorts"],
        run["teacher_pass_counts"],
        verified["cohorts"].values(),
    ):
        cache = RendererFeatureAlignedCohort(Path(root), "train", expected_pass_count=mode)
        if cache.sequence_ids != run["training_sequences"][run["cohort_labels"].index(label)]:
            raise ValueError(f"Training sequence membership mismatch for {label}")
        set_teacher_mode(model.head, mode)
        save(args.output / "status.json", {"state": "evaluating", "cohort": label, "sequences": len(cache.sequence_ids)})
        metrics = evaluate_renderer_streaming(model, cache, device="cuda", batch=4)
        report["cohorts"][label] = {
            "train": metrics,
            "validation": expected["metrics"],
            "training_sequences": cache.sequence_ids,
            "overlay_complete_sha256": sha(cache.root / "complete.json"),
        }
        save(args.output / "partial.json", report)
        print(json.dumps({"cohort": label, "training_sequences": metrics["sequence_count"], "train_mae": metrics["mae"], "validation_mae": expected["metrics"]["mae"]}), flush=True)
    save(args.output / "result.json", report)
    save(args.output / "status.json", {"state": "complete", "test_used": False})


if __name__ == "__main__":
    main()
