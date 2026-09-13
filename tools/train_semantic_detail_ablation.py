"""Train a zero-initialized native-resolution detail residual on a verified semantic parent."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import time
from pathlib import Path

import numpy as np
import torch

from joint_parent_tone_model import load_joint_checkpoint
from prepare_conditioning_pilot import save, sha
from semantic_detail_head import SemanticDetailOnlyModel
from train_semantic_ablation import cohort
from train_semantic_joint_parent import named_path
from train_semantic_joint_parent import _device_batch, evaluate_streaming
from train_spatial_tone import frame_objective


WINDOW = 8
BURN_IN = 2
BATCH = 1


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-checkpoint", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--width", type=int, default=32)
    parser.add_argument("--detail-scale", type=float, default=0.08)
    parser.add_argument("--steps", type=int, default=800)
    parser.add_argument("--eval-every", type=int, default=400)
    parser.add_argument("--learning-rate", type=float, default=1e-4)
    parser.add_argument("--seed", type=int, default=910)
    parser.add_argument("--pixel-only", action="store_true")
    parser.add_argument("--cohort", action="append", type=named_path, required=True)
    parser.add_argument("--probabilities", type=float, nargs="+", required=True)
    args = parser.parse_args()

    if args.output.exists():
        raise FileExistsError(args.output)
    if len(args.cohort) != len(args.probabilities):
        raise ValueError("Cohort probability mismatch")
    if any(value < 0 for value in args.probabilities) or not np.isclose(sum(args.probabilities), 1.0):
        raise ValueError("Cohort probabilities must be non-negative and sum to one")
    if args.steps < 1 or args.eval_every < 1 or args.learning_rate <= 0:
        raise ValueError("Positive steps, evaluation interval and learning rate required")
    if len({label for label, _ in args.cohort}) != len(args.cohort):
        raise ValueError("Duplicate cohort label")

    base_sha = sha(args.base_checkpoint)
    base_model, base_payload = load_joint_checkpoint(args.base_checkpoint)
    base_run = base_payload["run"]
    expected_labels = list(base_run["cohort_labels"])
    supplied_labels = [label for label, _ in args.cohort]
    if supplied_labels != expected_labels:
        raise ValueError(f"Cohort labels must match the base checkpoint: {expected_labels}")
    if list(map(float, args.probabilities)) != list(map(float, base_run["probabilities"])):
        raise ValueError("Cohort probabilities must match the base checkpoint")
    if base_run.get("test_used"):
        raise ValueError("Base checkpoint is marked as using test data")

    torch.set_num_threads(4)
    torch.manual_seed(args.seed)
    torch.cuda.manual_seed_all(args.seed)
    torch.backends.cudnn.benchmark = False
    rng = np.random.default_rng(args.seed)
    train = [cohort(path, "train") for _, path in args.cohort]
    validation = [cohort(path, "validation") for _, path in args.cohort]
    model = SemanticDetailOnlyModel(
        base_model.parent,
        base_model.head,
        width=args.width,
        scale=args.detail_scale,
    ).cuda()
    trainable = list(model.detail_head.detail.parameters())
    if not trainable or any(parameter.requires_grad is False for parameter in trainable):
        raise ValueError("Detail branch is not trainable")
    if any(parameter.requires_grad for parameter in model.parent.parameters()):
        raise ValueError("Causal parent must remain frozen")
    if any(parameter.requires_grad for parameter in model.detail_head.base_head.parameters()):
        raise ValueError("Inherited semantic head must remain frozen")

    args.output.mkdir(parents=True)
    loss_name = "L1" if args.pixel_only else "L1 + .5 pooled16 RGB L1 + .12 temporal error delta"
    run = {
        "architecture": "semantic_detail_only_v1",
        "base_checkpoint": str(args.base_checkpoint.resolve()),
        "base_checkpoint_sha256": base_sha,
        "base_step": int(base_payload["step"]),
        "cohorts": [str(path.resolve()) for _, path in args.cohort],
        "cohort_labels": supplied_labels,
        "cohort_complete_sha256": [sha(path / "complete.json") for _, path in args.cohort],
        "probabilities": [float(value) for value in args.probabilities],
        "training_sequences": [cache.sequence_ids for cache in train],
        "validation_sequences": [cache.sequence_ids for cache in validation],
        "window": WINDOW,
        "burn_in": BURN_IN,
        "batch": BATCH,
        "steps": args.steps,
        "eval_every": args.eval_every,
        "seed": args.seed,
        "learning_rate": args.learning_rate,
        "loss": loss_name,
        "pixel_only": bool(args.pixel_only),
        "width": args.width,
        "detail_scale": args.detail_scale,
        "trainable_parameters": sum(parameter.numel() for parameter in trainable),
        "base_architecture": base_run.get("architecture"),
        "test_used": False,
        "source_sha256": {
            "semantic_detail_head.py": sha(Path(__file__).with_name("semantic_detail_head.py")),
            "train_semantic_detail_ablation.py": sha(Path(__file__)),
        },
    }
    save(args.output / "run.json", run)
    optimizer = torch.optim.AdamW(trainable, lr=args.learning_rate, weight_decay=1e-4)
    labels = supplied_labels
    draws = {label: 0 for label in labels}
    digest = hashlib.sha256()
    history = []
    baseline = None
    best_score = None
    started = time.time()

    def checkpoint(path: Path, step: int, metrics: dict) -> None:
        tmp = path.with_suffix(path.suffix + ".tmp")
        torch.save(
            {
                "architecture": "semantic_detail_only_v1",
                "detail": model.detail_head.detail.state_dict(),
                "run": run,
                "step": int(step),
                "validation": metrics,
                "optimizer": optimizer.state_dict(),
                "numpy_rng_state": rng.bit_generator.state,
                "torch_rng_state": torch.get_rng_state(),
                "cuda_rng_state": torch.cuda.get_rng_state_all(),
                "history": history,
            },
            tmp,
        )
        tmp.replace(path)

    def evaluate(step: int) -> None:
        nonlocal baseline, best_score
        metrics = {}
        for label, cache in zip(labels, validation):
            save(args.output / "status.json", {"state": "evaluating", "step": step, "cohort": label})
            metrics[label] = evaluate_streaming(model, cache, batch=4)
            print(json.dumps({"step": step, "cohort": label, "mae": metrics[label]["mae"]}), flush=True)
        if baseline is None:
            baseline = metrics
            save(args.output / "baseline_validation.json", {"step": step, "metrics": baseline, "test_used": False})
            checkpoint(args.output / "baseline.pt", step, metrics)
        ratios = [metrics[label]["mae"] / baseline[label]["mae"] for label in labels]
        temporal_ratios = [
            metrics[label]["temporal_delta_mae"] / baseline[label]["temporal_delta_mae"]
            for label in labels
        ]
        eligible = all(ratio < 1.0 for ratio in ratios)
        score = float(np.mean(ratios))
        entry = {
            "step": step,
            "validation": metrics,
            "ratios": ratios,
            "temporal_ratios": temporal_ratios,
            "all_cohorts_improved": eligible,
            "all_temporal_deltas_not_worse": all(ratio <= 1.0 for ratio in temporal_ratios),
            "sample_sha256": digest.hexdigest(),
            "draws": dict(draws),
            "seconds": time.time() - started,
        }
        history.append(entry)
        save(args.output / "history.json", history)
        if eligible and (best_score is None or score < best_score):
            best_score = score
            checkpoint(args.output / "best.pt", step, metrics)
        checkpoint(args.output / "last.pt", step, metrics)

    try:
        torch.cuda.reset_peak_memory_stats()
        evaluate(0)
        for step in range(1, args.steps + 1):
            index = int(rng.choice(len(train), p=args.probabilities))
            _, _, ids = train[index].sample_window(rng, BATCH, WINDOW)
            digest.update(np.asarray([index], dtype="<i8").tobytes())
            digest.update(np.asarray(ids, dtype="<i8").tobytes())
            rgb, target, guides, context = _device_batch(train[index].load_window(ids))
            rgb, target = rgb.float() / 255.0, target.float() / 255.0
            guides, context = guides.float(), context.float()
            model.train()
            optimizer.zero_grad(set_to_none=True)
            state = None
            previous = None
            losses = []
            for frame in range(WINDOW):
                with torch.autocast("cuda", dtype=torch.bfloat16):
                    prediction, state = model.forward_temporal(
                        rgb[:, frame], guides[:, frame], context[:, frame], state
                    )
                error = prediction.float() - target[:, frame]
                if frame >= BURN_IN:
                    losses.append(frame_objective(error, previous, args.pixel_only))
                previous = error if frame >= BURN_IN else error.detach()
            loss = torch.stack(losses).mean()
            if not torch.isfinite(loss):
                raise ValueError("Nonfinite detail loss")
            loss.backward()
            torch.nn.utils.clip_grad_norm_(trainable, 1.0, error_if_nonfinite=True)
            optimizer.step()
            draws[labels[index]] += 1
            if step == 1 or step % 25 == 0:
                status = {
                    "state": "training",
                    "step": step,
                    "steps": args.steps,
                    "loss": float(loss.detach()),
                    "seconds": time.time() - started,
                    "gpu_peak_gib": torch.cuda.max_memory_allocated() / 2**30,
                    "draws": dict(draws),
                }
                save(args.output / "status.json", status)
                print(json.dumps(status), flush=True)
            if step % args.eval_every == 0 or step == args.steps:
                evaluate(step)
        save(
            args.output / "status.json",
            {
                "state": "complete",
                "steps": args.steps,
                "best_score": best_score,
                "test_used": False,
                "gpu_peak_gib": torch.cuda.max_memory_allocated() / 2**30,
                "seconds": time.time() - started,
            },
        )
    except Exception as exc:
        save(args.output / "status.json", {"state": "failed", "error": repr(exc), "test_used": False})
        raise


if __name__ == "__main__":
    main()
