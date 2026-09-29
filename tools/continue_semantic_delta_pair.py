"""Matched temporal-delta continuation from the rebalanced semantic endpoint.

Both arms start from the same absolute step-3200 rebalanced checkpoint and use
the same restored sample schedule.  The baseline keeps the existing temporal
error weight (0.12); the intervention doubles it to 0.24.  All six ordinary
validation streams are evaluated at the start, midpoint, and endpoint.  No
test rows are used.
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as F

from aligned_cohort import AlignedCohort
from evaluate_temporal_cohorts import named_path
from joint_parent_tone_model import JointParentToneModel
from prepare_conditioning_pilot import save, sha
from semantic_tone_head import SemanticToneHead
from train_capacity_temporal_student import _load_parent
from train_semantic_parent_replication import cohort
from train_temporal_student import _device_batch, evaluate_streaming


BASELINE_PROBABILITIES = [0.25, 0.10, 0.10, 0.15, 0.20, 0.20]


def load_arm(payload):
    old = payload["run"]
    parent, *_ = _load_parent(Path(old["parent"]))
    parent.load_state_dict(payload["parent_model"], strict=True)
    head = SemanticToneHead(False).cuda()
    head.load_state_dict(payload["head"], strict=True)
    model = JointParentToneModel(parent, head)
    optimizer = torch.optim.AdamW(
        [
            {"params": [p for p in head.parameters() if p.requires_grad], "lr": old["learning_rate"]},
            {"params": list(parent.parameters()), "lr": old["parent_learning_rate"]},
        ],
        weight_decay=1e-4,
    )
    optimizer.load_state_dict(payload["optimizer"])
    torch.set_rng_state(payload["torch_rng_state"].cpu())
    torch.cuda.set_rng_state_all([value.cpu() for value in payload["cuda_rng_state"]])
    return model, parent, head, optimizer


def build_schedule(payload, train, labels, steps):
    rng = np.random.default_rng()
    rng.bit_generator.state = payload["numpy_rng_state"]
    digest = hashlib.sha256()
    draws = {label: 0 for label in labels}
    schedule = []
    for _ in range(steps):
        index = int(rng.choice(len(train), p=BASELINE_PROBABILITIES))
        _, _, ids = train[index].sample_window(rng, 1, 8)
        ids = np.asarray(ids, dtype=np.int64)
        digest.update(np.asarray([index], dtype="<i8").tobytes())
        digest.update(ids.tobytes())
        draws[labels[index]] += 1
        schedule.append((index, ids))
    return schedule, rng.bit_generator.state, digest.hexdigest(), draws


def objective(error, previous, delta_weight):
    return (
        error.abs().mean()
        + 0.5 * F.avg_pool2d(error, 16).abs().mean()
        + delta_weight * (error - previous).abs().mean()
    )


def run_arm(payload, train, validation, labels, schedule, final_rng_state, schedule_sha, schedule_draws, output, role, delta_weight, args):
    output.mkdir(parents=True)
    model, parent, head, optimizer = load_arm(payload)
    baseline = payload["validation"]
    old = payload["run"]
    run = dict(
        old,
        architecture="semantic_joint_parent_delta_pair_v1",
        role=role,
        delta_weight=delta_weight,
        continuation_start_step=int(payload["step"]),
        continuation_end_step=args.end_step,
        resume=str(args.initialize.resolve()),
        resume_sha256=sha(args.initialize),
        mixture_probabilities=BASELINE_PROBABILITIES,
        schedule_sha256=schedule_sha,
        schedule_draws=schedule_draws,
        trainer_source_sha256=sha(Path(__file__)),
        test_used=False,
    )
    save(output / "run.json", run)
    save(output / "resume_verification.json", {
        "resume_sha256": sha(args.initialize),
        "start_step": int(payload["step"]),
        "delta_weight": delta_weight,
        "schedule_sha256": schedule_sha,
        "schedule_draws": schedule_draws,
        "optimizer_restored": True,
        "rng_restored": True,
        "test_used": False,
    })
    history = []
    started = time.time()

    def checkpoint(name, step, metrics):
        torch.save(
            {
                "architecture": run["architecture"],
                "role": role,
                "head": head.state_dict(),
                "parent_model": parent.state_dict(),
                "run": run,
                "step": step,
                "validation": metrics,
                "optimizer": optimizer.state_dict(),
                "numpy_rng_state": final_rng_state,
                "torch_rng_state": torch.get_rng_state(),
                "cuda_rng_state": torch.cuda.get_rng_state_all(),
                "common_start_validation": old.get("common_start_validation"),
                "candidate_start_validation": baseline,
                "schedule_sha256": schedule_sha,
                "schedule_draws": schedule_draws,
            },
            output / (name + ".tmp"),
        )
        (output / (name + ".tmp")).replace(output / name)

    def evaluate(step):
        metrics = {}
        for label, cache in zip(labels, validation):
            save(output / "status.json", {"state": "evaluating", "step": step, "cohort": label, "test_used": False})
            metrics[label] = evaluate_streaming(model, cache, batch=4)
        ratios = [metrics[label]["mae"] / baseline[label]["mae"] for label in labels]
        history.append({
            "step": step,
            "validation": metrics,
            "ratios_vs_candidate_start": ratios,
            "all_cohorts_improved_vs_candidate_start": all(value < 1 for value in ratios),
            "seconds": time.time() - started,
            "test_used": False,
        })
        save(output / "history.json", history)
        checkpoint("last.pt", step, metrics)

    evaluate(int(payload["step"]))
    for offset, (index, ids) in enumerate(schedule, start=1):
        step = int(payload["step"]) + offset
        rgb, target, guides, context = _device_batch(train[index].load_window(ids))
        rgb, target = rgb.float() / 255, target.float() / 255
        guides, context = guides.float(), context.float()
        model.train()
        optimizer.zero_grad(set_to_none=True)
        state = None
        previous = None
        losses = []
        for frame in range(8):
            with torch.set_grad_enabled(frame >= 2), torch.autocast("cuda", dtype=torch.bfloat16):
                prediction, state = model.forward_temporal(rgb[:, frame], guides[:, frame], context[:, frame], state)
                error = prediction.float() - target[:, frame]
                if frame >= 2:
                    losses.append(objective(error, previous, delta_weight))
                previous = error if frame >= 2 else error.detach()
        loss = torch.stack(losses).mean()
        if not torch.isfinite(loss):
            raise ValueError(f"Nonfinite loss at step {step}")
        loss.backward()
        torch.nn.utils.clip_grad_norm_(head.parameters(), 1, error_if_nonfinite=True)
        torch.nn.utils.clip_grad_norm_(parent.parameters(), 1, error_if_nonfinite=True)
        optimizer.step()
        if offset == 1 or offset % 25 == 0:
            save(output / "status.json", {
                "state": "training",
                "step": step,
                "steps": args.end_step,
                "loss": float(loss.detach()),
                "seconds": time.time() - started,
                "gpu_peak_gib": torch.cuda.max_memory_allocated() / 2**30,
                "test_used": False,
            })
        if step == args.end_step or (args.eval_every and step % args.eval_every == 0):
            evaluate(step)
    save(output / "status.json", {"state": "complete", "steps": args.end_step, "test_used": False, "seconds": time.time() - started})
    del model, parent, head, optimizer
    torch.cuda.empty_cache()


def main():
    import argparse

    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--initialize", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--end-step", type=int, default=4000)
    p.add_argument("--eval-every", type=int, default=400)
    args = p.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    payload = torch.load(args.initialize, map_location="cpu", weights_only=False)
    if payload.get("architecture") != "semantic_joint_parent_mixture_v1" or int(payload["step"]) >= args.end_step:
        raise ValueError("Expected the absolute step-3200 rebalanced mixture checkpoint")
    if args.eval_every < 1:
        raise ValueError("Positive evaluation interval required")
    torch.set_num_threads(4)
    torch.backends.cudnn.benchmark = False
    labels = payload["run"]["cohort_labels"]
    train = [cohort(Path(root), "train") for root in payload["run"]["cohorts"]]
    validation = [cohort(Path(root), "validation") for root in payload["run"]["cohorts"]]
    if [c.sequence_ids for c in train] != payload["run"]["training_sequences"]:
        raise ValueError("Training sequence membership changed")
    if [c.sequence_ids for c in validation] != payload["run"]["validation_sequences"]:
        raise ValueError("Validation sequence membership changed")
    start = int(payload["step"])
    steps = args.end_step - start
    schedule, final_rng_state, schedule_sha, schedule_draws = build_schedule(payload, train, labels, steps)
    args.output.mkdir(parents=True)
    save(args.output / "run.json", {
        "architecture": "semantic_joint_parent_delta_pair_v1",
        "initialize": str(args.initialize.resolve()),
        "initialize_sha256": sha(args.initialize),
        "start_step": start,
        "end_step": args.end_step,
        "steps": steps,
        "eval_every": args.eval_every,
        "base_delta_weight": 0.12,
        "boosted_delta_weight": 0.24,
        "probabilities": BASELINE_PROBABILITIES,
        "schedule_sha256": schedule_sha,
        "schedule_draws": schedule_draws,
        "test_used": False,
        "source_sha256": sha(Path(__file__)),
    })
    run_arm(payload, train, validation, labels, schedule, final_rng_state, schedule_sha, schedule_draws, args.output / "baseline", "baseline_delta_0.12", 0.12, args)
    run_arm(payload, train, validation, labels, schedule, final_rng_state, schedule_sha, schedule_draws, args.output / "delta_boost", "delta_boost_0.24", 0.24, args)
    save(args.output / "pair.json", {
        "initialize": str(args.initialize.resolve()),
        "initialize_sha256": sha(args.initialize),
        "start_step": start,
        "end_step": args.end_step,
        "baseline": str((args.output / "baseline").resolve()),
        "delta_boost": str((args.output / "delta_boost").resolve()),
        "schedule_sha256": schedule_sha,
        "test_used": False,
    })
    save(args.output / "status.json", {"state": "complete", "test_used": False})


if __name__ == "__main__":
    main()
