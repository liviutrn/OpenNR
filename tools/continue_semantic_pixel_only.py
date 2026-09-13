"""Continue a verified pixel-only semantic joint checkpoint with full state restoration."""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path
import shutil

import numpy as np
import torch

from joint_parent_tone_model import load_joint_checkpoint
from prepare_conditioning_pilot import save, sha
from train_semantic_ablation import cohort
from train_spatial_tone import frame_objective
from train_temporal_student import _device_batch, evaluate_streaming


WINDOW = 8
BURN_IN = 2
BATCH = 1


def move_optimizer_state_to_cuda(optimizer) -> None:
    for state in optimizer.state.values():
        for key, value in state.items():
            if torch.is_tensor(value):
                state[key] = value.cuda(non_blocking=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--resume", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--additional-steps", type=int, default=800)
    parser.add_argument("--eval-every", type=int, default=400)
    args = parser.parse_args()

    if args.output.exists():
        raise FileExistsError(args.output)
    if args.additional_steps < 1 or args.eval_every < 1:
        raise ValueError("Positive continuation steps and evaluation interval required")

    resume_sha = sha(args.resume)
    model, payload = load_joint_checkpoint(args.resume)
    old_run = payload["run"]
    if old_run.get("loss") != "L1" or not old_run.get("pixel_only"):
        raise ValueError("The continuation requires a verified pixel-only checkpoint")
    if not old_run.get("joint_parent"):
        raise ValueError("The continuation requires a joint-parent checkpoint")
    start_step = int(payload["step"])
    if start_step != int(old_run["steps"]):
        raise ValueError("Resume checkpoint step does not match its run metadata")
    if payload.get("test_used") or old_run.get("test_used"):
        raise ValueError("Refusing to continue a checkpoint marked as using test data")

    labels = list(old_run["cohort_labels"])
    probabilities = [float(value) for value in old_run["probabilities"]]
    train = [cohort(Path(root), "train") for root in old_run["cohorts"]]
    validation = [cohort(Path(root), "validation") for root in old_run["cohorts"]]
    if [cache.sequence_ids for cache in train] != old_run["training_sequences"]:
        raise ValueError("Training sequence membership changed")
    if [cache.sequence_ids for cache in validation] != old_run["validation_sequences"]:
        raise ValueError("Validation sequence membership changed")

    optimizer = torch.optim.AdamW(
        [
            {"params": [parameter for parameter in model.head.parameters() if parameter.requires_grad],
             "lr": old_run["learning_rate"]},
            {"params": list(model.parent.parameters()), "lr": old_run["parent_learning_rate"]},
        ],
        weight_decay=1e-4,
    )
    optimizer.load_state_dict(payload["optimizer"])
    move_optimizer_state_to_cuda(optimizer)
    torch.set_rng_state(payload["torch_rng_state"].cpu())
    torch.cuda.set_rng_state_all([value.cpu() for value in payload["cuda_rng_state"]])
    rng = np.random.default_rng()
    rng.bit_generator.state = payload["numpy_rng_state"]

    args.output.mkdir(parents=True)
    source_hashes = dict(old_run["source_sha256"])
    source_hashes[Path(__file__).name] = sha(Path(__file__))
    source_hashes["train_semantic_ablation.py"] = sha(Path(__file__).with_name("train_semantic_ablation.py"))
    run = dict(
        old_run,
        steps=start_step + args.additional_steps,
        eval_every=args.eval_every,
        continuation_start_step=start_step,
        continuation_steps=args.additional_steps,
        resume=str(args.resume.resolve()),
        resume_sha256=resume_sha,
        optimizer_restored=True,
        rng_restored=True,
        source_sha256=source_hashes,
        test_used=False,
    )
    save(args.output / "run.json", run)

    baseline = payload["validation"]
    history = []
    draws = {label: 0 for label in labels}
    digest = hashlib.sha256()
    best_score = None
    started = time.time()

    def checkpoint(path: Path, step: int, metrics: dict) -> None:
        tmp = path.with_suffix(path.suffix + ".tmp")
        torch.save(
            {
                "architecture": "semantic_joint_parent_v1",
                "head": model.head.state_dict(),
                "parent_model": model.parent.state_dict(),
                "run": run,
                "step": int(step),
                "validation": metrics,
                "optimizer": optimizer.state_dict(),
                "numpy_rng_state": rng.bit_generator.state,
                "torch_rng_state": torch.get_rng_state(),
                "cuda_rng_state": torch.cuda.get_rng_state_all(),
                "common_start_validation": baseline,
                "history": history,
            },
            tmp,
        )
        tmp.replace(path)

    def evaluate(step: int) -> None:
        nonlocal best_score
        metrics = {}
        for label, cache in zip(labels, validation):
            save(args.output / "status.json", {"state": "evaluating", "step": step, "cohort": label})
            metrics[label] = evaluate_streaming(model, cache, batch=4)
            print(json.dumps({"step": step, "cohort": label, "mae": metrics[label]["mae"]}), flush=True)
        if step == start_step:
            differences = {
                label: {
                    key: abs(metrics[label][key] - baseline[label][key])
                    for key in ("mae", "psnr", "temporal_delta_mae")
                }
                for label in labels
            }
            if any(value > 1e-7 for values in differences.values() for value in values.values()):
                raise ValueError(f"Resume replay mismatch: {differences}")
            save(args.output / "resume_replay.json", {"step": step, "differences": differences, "test_used": False})
        ratios = [metrics[label]["mae"] / baseline[label]["mae"] for label in labels]
        temporal_ratios = [
            metrics[label]["temporal_delta_mae"] / baseline[label]["temporal_delta_mae"]
            for label in labels
        ]
        eligible = step > start_step and all(ratio < 1.0 for ratio in ratios)
        score = float(np.mean(ratios))
        history.append(
            {
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
        )
        save(args.output / "history.json", history)
        if eligible and (best_score is None or score < best_score):
            best_score = score
            checkpoint(args.output / "best.pt", step, metrics)
        checkpoint(args.output / "last.pt", step, metrics)

    try:
        torch.cuda.reset_peak_memory_stats()
        evaluate(start_step)
        for offset in range(1, args.additional_steps + 1):
            step = start_step + offset
            index = int(rng.choice(len(train), p=probabilities))
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
                    losses.append(frame_objective(error, previous, True))
                previous = error if frame >= BURN_IN else error.detach()
            loss = torch.stack(losses).mean()
            if not torch.isfinite(loss):
                raise ValueError("Nonfinite continuation loss")
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.head.parameters(), 1.0, error_if_nonfinite=True)
            torch.nn.utils.clip_grad_norm_(model.parent.parameters(), 1.0, error_if_nonfinite=True)
            optimizer.step()
            draws[labels[index]] += 1
            if offset == 1 or offset % 25 == 0:
                status = {
                    "state": "training",
                    "step": step,
                    "steps": run["steps"],
                    "loss": float(loss.detach()),
                    "seconds": time.time() - started,
                    "gpu_peak_gib": torch.cuda.max_memory_allocated() / 2**30,
                    "draws": dict(draws),
                }
                save(args.output / "status.json", status)
                print(json.dumps(status), flush=True)
            if offset % args.eval_every == 0 or offset == args.additional_steps:
                evaluate(step)
        save(
            args.output / "status.json",
            {
                "state": "complete",
                "steps": run["steps"],
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
