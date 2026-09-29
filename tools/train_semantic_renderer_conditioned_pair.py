"""Matched semantic joint-parent training with native renderer conditioning.

The control and arm share one precomputed sequence/window schedule and the
same zero-initialized 17-channel head.  The control receives zeros for every
renderer input.  The arm receives the verified full-eye G-buffer overlay only
for the new strict temporal cohort; all six existing cohorts also receive
zeros.  This isolates the value of the renderer channels while preserving the
ordinary temporal objective and the existing six-cohort contract.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path

import numpy as np
import torch

from joint_parent_tone_model import load_joint_checkpoint
from prepare_conditioning_pilot import save, sha
from semantic_renderer_conditioned import (
    RENDERER_CHANNELS,
    RendererConditioningOverlay,
    RendererZeroCohort,
    load_semantic_renderer_checkpoint,
)
from renderer_conditioned_stable import evaluate_renderer_streaming
from train_semantic_ablation import cohort
from train_spatial_tone import frame_objective


LABELS = [
    "prior",
    "high_effect",
    "renderer_pilot",
    "fresh_session",
    "renderer_state",
    "new_pairs",
    "full_eye_renderer",
]
OLD_PROBABILITIES = np.asarray([0.40, 0.15, 0.10, 0.15, 0.10, 0.10], dtype=np.float64)
WINDOW = 8
BURN_IN = 2


def _device_batch(arrays):
    return tuple(torch.from_numpy(value).to("cuda", non_blocking=True) for value in arrays)


def _schedule(train, steps: int, seed: int, new_probability: float):
    if not 0.0 < new_probability < 1.0:
        raise ValueError("new probability must be in (0, 1)")
    probabilities = np.concatenate((OLD_PROBABILITIES * (1.0 - new_probability), [new_probability]))
    if not np.isclose(probabilities.sum(), 1.0):
        raise ValueError("probabilities do not sum to one")
    rng = np.random.default_rng(seed)
    digest = hashlib.sha256()
    rows = []
    draws = [0 for _ in train]
    for step in range(1, steps + 1):
        index = int(rng.choice(len(train), p=probabilities))
        _, _, ids = train[index].sample_window(rng, 1, WINDOW)
        ids = np.asarray(ids, dtype=np.int64)
        digest.update(np.asarray([step, index], dtype="<i8").tobytes())
        digest.update(ids.tobytes())
        draws[index] += 1
        rows.append({"step": step, "cohort_index": index, "ids": ids.tolist()})
    metadata = {
        "seed": int(seed),
        "steps": int(steps),
        "window": WINDOW,
        "burn_in": BURN_IN,
        "probabilities": probabilities.tolist(),
        "labels": LABELS,
        "draws": draws,
        "digest_sha256": digest.hexdigest(),
        "test_used": False,
    }
    return rows, metadata


def _trainable_named(module):
    return [(name, parameter) for name, parameter in module.named_parameters() if parameter.requires_grad]


def _make_optimizer(model, base_payload):
    learning_rate = float(base_payload["run"]["learning_rate"])
    parent_learning_rate = float(base_payload["run"]["parent_learning_rate"])
    head_named = _trainable_named(model.head)
    parent_named = list(model.parent.named_parameters())
    optimizer = torch.optim.AdamW(
        [
            {"params": [parameter for _, parameter in head_named], "lr": learning_rate},
            {"params": [parameter for _, parameter in parent_named], "lr": parent_learning_rate},
        ],
        weight_decay=1e-4,
    )
    old_optimizer = base_payload.get("optimizer")
    if old_optimizer is None:
        raise ValueError("Base checkpoint has no optimizer state")
    new_state = optimizer.state_dict()
    if len(new_state["param_groups"]) != len(old_optimizer["param_groups"]):
        raise ValueError("Base optimizer group count changed")
    named_groups = [head_named, parent_named]
    for group_index, (new_group, old_group) in enumerate(
        zip(new_state["param_groups"], old_optimizer["param_groups"])
    ):
        names = named_groups[group_index]
        if len(new_group["params"]) != len(old_group["params"]) or len(names) != len(new_group["params"]):
            raise ValueError(f"Base optimizer parameter count changed in group {group_index}")
        for key, value in old_group.items():
            if key != "params":
                new_group[key] = value
        for new_id, old_id, (name, parameter) in zip(
            new_group["params"], old_group["params"], names
        ):
            old_values = old_optimizer["state"].get(old_id)
            if old_values is None:
                continue
            copied = {}
            for key, value in old_values.items():
                if not torch.is_tensor(value):
                    copied[key] = value
                    continue
                if value.ndim > 0 and tuple(value.shape) != tuple(parameter.shape):
                    if (
                        group_index == 0
                        and name == "stem.0.weight"
                        and value.ndim == 4
                        and value.shape[1] == 19
                        and parameter.shape[1] == 19 + RENDERER_CHANNELS
                    ):
                        expanded = torch.zeros(tuple(parameter.shape), dtype=value.dtype)
                        expanded[:, : value.shape[1]].copy_(value)
                        copied[key] = expanded
                    else:
                        raise ValueError(
                            f"Cannot adapt optimizer state for {group_index}:{name}: "
                            f"{tuple(value.shape)} -> {tuple(parameter.shape)}"
                        )
                else:
                    copied[key] = value.clone()
            new_state["state"][new_id] = copied
    optimizer.load_state_dict(new_state)
    return optimizer


def _check_sequences(train_caches, validation_caches):
    all_train = set()
    all_validation = set()
    all_test = set()
    for cache in train_caches:
        train_ids = set(cache.sequence_ids)
        if all_train & train_ids:
            raise ValueError("Repeated training sequence across cohorts")
        all_train |= train_ids
        all_test.update(row["sequence_id"] for row in cache.rows if row["split"] == "test")
    for cache in validation_caches:
        validation_ids = set(cache.sequence_ids)
        if all_validation & validation_ids:
            raise ValueError("Repeated validation sequence across cohorts")
        all_validation |= validation_ids
        all_test.update(row["sequence_id"] for row in cache.rows if row["split"] == "test")
    if all_train & all_validation:
        raise ValueError("Training/validation sequence leakage")
    if all_test & (all_train | all_validation):
        raise ValueError("Frozen-test sequence leakage")


def _run_metadata(
    base_payload,
    base_path,
    overlay_train,
    overlay_validation,
    old_roots,
    old_train,
    old_validation,
    schedule_meta,
    args,
    mode,
):
    return {
        "architecture": "semantic_renderer_conditioned_joint_v1",
        "mode": mode,
        "base_checkpoint": str(base_path.resolve()),
        "base_checkpoint_sha256": sha(base_path),
        "base_step": int(base_payload["step"]),
        "old_cohorts": [str(root.resolve()) for root in old_roots],
        "old_cohort_labels": LABELS[:6],
        "old_cohort_complete_sha256": [sha(root / "complete.json") for root in old_roots],
        "renderer_overlay": str(overlay_train.root.resolve()),
        "renderer_overlay_complete_sha256": sha(overlay_train.root / "complete.json"),
        "probabilities": schedule_meta["probabilities"],
        "seed": int(args.seed),
        "steps": int(base_payload["step"] + args.steps),
        "learning_rate": float(base_payload["run"]["learning_rate"]),
        "parent_learning_rate": float(base_payload["run"]["parent_learning_rate"]),
        "eval_every": int(args.eval_every),
        "status_every": int(args.status_every),
        "window": WINDOW,
        "burn_in": BURN_IN,
        "batch": 1,
        "loss": "L1 + .5 pooled16 RGB L1 + .12 temporal error delta",
        "renderer_channels": RENDERER_CHANNELS,
        "conditioning_active": mode == "arm",
        "training_sequences": [cache.sequence_ids for cache in old_train] + [overlay_train.base.sequence_ids],
        "validation_sequences": [cache.sequence_ids for cache in old_validation] + [overlay_validation.base.sequence_ids],
        "test_used": False,
        "optimizer_state": "base AdamW state copied; stem renderer moments zero-padded",
        "renderer_model_source_sha256": sha(Path(__file__).with_name("semantic_renderer_conditioned.py")),
        "trainer_source_sha256": sha(Path(__file__)),
        "base_validation": base_payload.get("validation"),
    }


def _checkpoint(output, model, optimizer, run, step, validation, history_entry, schedule_meta):
    temporary = output / "last.pt.tmp"
    torch.save(
        {
            "architecture": "semantic_renderer_conditioned_joint_v1",
            "head": model.head.state_dict(),
            "parent_model": model.parent.state_dict(),
            "run": run,
            "step": int(step),
            "validation": validation,
            "history_entry": history_entry,
            "optimizer": optimizer.state_dict(),
            "schedule_metadata": schedule_meta,
            "torch_rng_state": torch.get_rng_state(),
            "cuda_rng_state": torch.cuda.get_rng_state_all(),
            "test_used": False,
        },
        temporary,
    )
    temporary.replace(output / "last.pt")


def _save_named_checkpoint(output, name, model, optimizer, run, step, validation, history_entry, schedule_meta):
    temporary = output / (name + ".tmp")
    torch.save(
        {
            "architecture": "semantic_renderer_conditioned_joint_v1",
            "head": model.head.state_dict(),
            "parent_model": model.parent.state_dict(),
            "run": run,
            "step": int(step),
            "validation": validation,
            "history_entry": history_entry,
            "optimizer": optimizer.state_dict(),
            "schedule_metadata": schedule_meta,
            "torch_rng_state": torch.get_rng_state(),
            "cuda_rng_state": torch.cuda.get_rng_state_all(),
            "test_used": False,
        },
        temporary,
    )
    temporary.replace(output / name)


def _train_one(
    mode,
    args,
    base_path,
    overlay_train,
    overlay_validation,
    old_roots,
    old_train_base,
    old_validation_base,
    schedule,
    schedule_meta,
    output,
    control_history=None,
):
    if output.exists():
        raise FileExistsError(output)
    output.mkdir(parents=True)
    model, base_payload = load_semantic_renderer_checkpoint(base_path)
    base_sha = sha(base_path)
    if base_sha != schedule_meta["base_checkpoint_sha256"]:
        raise ValueError("Base checkpoint changed during training")
    if "torch_rng_state" in base_payload:
        torch.set_rng_state(base_payload["torch_rng_state"])
    if "cuda_rng_state" in base_payload:
        torch.cuda.set_rng_state_all(base_payload["cuda_rng_state"])
    optimizer = _make_optimizer(model, base_payload)

    old_train = [RendererZeroCohort(cache) for cache in old_train_base]
    old_validation = [RendererZeroCohort(cache) for cache in old_validation_base]
    renderer_train = overlay_train if mode == "arm" else RendererZeroCohort(overlay_train.base)
    renderer_validation = overlay_validation if mode == "arm" else RendererZeroCohort(overlay_validation.base)
    train = old_train + [renderer_train]
    validation = old_validation + [renderer_validation]
    run = _run_metadata(
        base_payload,
        base_path,
        overlay_train,
        overlay_validation,
        old_roots,
        old_train,
        old_validation,
        schedule_meta,
        args,
        mode,
    )
    save(output / "run.json", run)
    save(output / "schedule_metadata.json", schedule_meta)

    history = []
    baseline = None
    best_score = float("inf")
    best_step = None
    started = time.time()
    draws = [0 for _ in train]

    def evaluate(step):
        nonlocal baseline, best_score, best_step
        metrics = {}
        for label, cache in zip(LABELS, validation):
            save(
                output / "status.json",
                {"state": "evaluating", "mode": mode, "step": step, "cohort": label, "test_used": False},
            )
            metrics[label] = evaluate_renderer_streaming(model, cache, batch=args.eval_batch)
        if baseline is None:
            baseline = metrics
            save(output / "baseline_validation.json", {"validation": baseline, "test_used": False})
        ratios = {label: metrics[label]["mae"] / baseline[label]["mae"] for label in LABELS}
        eligible = all(ratio < 1.0 for ratio in ratios.values()) and step > int(base_payload["step"])
        score = float(np.mean(list(ratios.values())))
        entry = {
            "step": int(step),
            "validation": metrics,
            "mae_ratios": ratios,
            "all_seven_cohorts_improved": eligible,
            "score": score,
            "draws": list(draws),
            "schedule_digest_sha256": schedule_meta["digest_sha256"],
            "seconds": time.time() - started,
            "test_used": False,
        }
        if control_history is not None and step == int(base_payload["step"]):
            reference = control_history[0]["validation"]
            differences = {
                label: {
                    key: abs(metrics[label][key] - reference[label][key])
                    for key in ("mae", "psnr", "temporal_delta_mae")
                }
                for label in LABELS
            }
            max_difference = max(value for group in differences.values() for value in group.values())
            if max_difference > 5e-6:
                raise ValueError(f"Step-zero control identity failed: {max_difference}")
            entry["control_step_zero_max_difference"] = max_difference
            save(output / "step_zero_control_replay.json", {"differences": differences, "max_difference": max_difference})
        history.append(entry)
        save(output / "history.json", history)
        _checkpoint(output, model, optimizer, run, step, metrics, entry, schedule_meta)
        if eligible and score < best_score:
            best_score = score
            best_step = int(step)
            _save_named_checkpoint(
                output,
                "best_all_seven_cohorts.pt",
                model,
                optimizer,
                run,
                step,
                metrics,
                entry,
                schedule_meta,
            )
        print(
            json.dumps(
                {
                    "mode": mode,
                    "step": int(step),
                    "all_seven_cohorts_improved": eligible,
                    "mae": {label: metrics[label]["mae"] for label in LABELS},
                }
            ),
            flush=True,
        )

    try:
        evaluate(int(base_payload["step"]))
        for offset, draw in enumerate(schedule, start=1):
            step = int(base_payload["step"] + offset)
            index = int(draw["cohort_index"])
            ids = np.asarray(draw["ids"], dtype=np.int64)
            rgb, target, guides, context, conditioning = _device_batch(train[index].load_window(ids))
            rgb = rgb.float() / 255.0
            target = target.float() / 255.0
            guides = guides.float()
            context = context.float()
            conditioning = conditioning.float()
            optimizer.zero_grad(set_to_none=True)
            model.train()
            state = None
            previous = None
            losses = []
            for frame in range(WINDOW):
                with torch.set_grad_enabled(frame >= BURN_IN), torch.autocast("cuda", dtype=torch.bfloat16):
                    prediction, state = model.forward_temporal(
                        rgb[:, frame],
                        guides[:, frame],
                        context[:, frame],
                        conditioning[:, frame],
                        state,
                    )
                    error = prediction.float() - target[:, frame]
                    if frame >= BURN_IN:
                        losses.append(frame_objective(error, previous))
                    previous = error if frame >= BURN_IN else error.detach()
            loss = torch.stack(losses).mean()
            if not torch.isfinite(loss):
                raise ValueError(f"Nonfinite loss at step {step}")
            loss.backward()
            torch.nn.utils.clip_grad_norm_([p for p in model.head.parameters() if p.requires_grad], 1.0, error_if_nonfinite=True)
            torch.nn.utils.clip_grad_norm_(list(model.parent.parameters()), 1.0, error_if_nonfinite=True)
            optimizer.step()
            draws[index] += 1
            if step == int(base_payload["step"]) + 1 or step % args.status_every == 0:
                save(
                    output / "status.json",
                    {
                        "state": "training",
                        "mode": mode,
                        "step": step,
                        "steps": int(base_payload["step"] + len(schedule)),
                        "loss": float(loss.detach()),
                        "draws": list(draws),
                        "seconds": time.time() - started,
                        "gpu_peak_gib": torch.cuda.max_memory_allocated() / 2**30,
                        "test_used": False,
                    },
                )
            if offset % args.eval_every == 0 or offset == len(schedule):
                evaluate(step)
        save(
            output / "status.json",
            {
                "state": "complete",
                "mode": mode,
                "steps": int(base_payload["step"] + len(schedule)),
                "best_step": best_step,
                "best_score": None if best_step is None else best_score,
                "test_used": False,
                "seconds": time.time() - started,
            },
        )
    except Exception as exc:
        save(output / "status.json", {"state": "failed", "mode": mode, "error": repr(exc), "test_used": False})
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-checkpoint", type=Path, required=True)
    parser.add_argument("--old-cohort", action="append", type=Path, required=True)
    parser.add_argument("--renderer-overlay", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--steps", type=int, default=800)
    parser.add_argument("--eval-every", type=int, default=400)
    parser.add_argument("--status-every", type=int, default=25)
    parser.add_argument("--eval-batch", type=int, default=4)
    parser.add_argument("--new-probability", type=float, default=0.15)
    parser.add_argument("--seed", type=int, default=912)
    args = parser.parse_args()
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is required")
    if len(args.old_cohort) != 6:
        raise ValueError("Exactly six old cohorts are required")
    if args.steps < 1 or args.eval_every < 1 or args.status_every < 1 or args.eval_batch < 1:
        raise ValueError("Positive steps/evaluation/status/batch required")
    if args.output_root.exists():
        raise FileExistsError(args.output_root)
    args.base_checkpoint = args.base_checkpoint.resolve()
    args.renderer_overlay = args.renderer_overlay.resolve()
    args.output_root = args.output_root.resolve()
    if not args.base_checkpoint.is_file() or not args.renderer_overlay.is_dir():
        raise FileNotFoundError("Base checkpoint or renderer overlay missing")
    base_sha = sha(args.base_checkpoint)
    base_payload = torch.load(args.base_checkpoint, map_location="cpu", weights_only=False)
    if base_payload.get("architecture") != "semantic_joint_parent_v1":
        raise ValueError("Base must be a semantic joint-parent checkpoint")
    if int(base_payload.get("step", 0)) < 1:
        raise ValueError("Base checkpoint must be trained")
    old_roots = [root.resolve() for root in args.old_cohort]
    old_train_base = [cohort(root, "train") for root in old_roots]
    old_validation_base = [cohort(root, "validation") for root in old_roots]
    overlay_train = RendererConditioningOverlay(args.renderer_overlay, "train")
    overlay_validation = RendererConditioningOverlay(args.renderer_overlay, "validation")
    if overlay_train.base.root != overlay_validation.base.root:
        raise ValueError("Renderer train/validation source mismatch")
    if set(overlay_train.sequence_ids) & set(overlay_validation.sequence_ids):
        raise ValueError("Renderer train/validation sequence leakage")
    _check_sequences(
        old_train_base + [overlay_train.base],
        old_validation_base + [overlay_validation.base],
    )
    for train_cache, validation_cache in zip(old_train_base, old_validation_base):
        if set(train_cache.sequence_ids) & set(validation_cache.sequence_ids):
            raise ValueError("Old cohort train/validation sequence leakage")
    torch.set_num_threads(4)
    torch.backends.cudnn.benchmark = False
    torch.manual_seed(args.seed)
    torch.cuda.manual_seed_all(args.seed)
    # The schedule uses the source cache only for its deterministic stream keys.
    schedule_train = [RendererZeroCohort(cache) for cache in old_train_base] + [RendererZeroCohort(overlay_train.base)]
    schedule, schedule_meta = _schedule(schedule_train, args.steps, args.seed, args.new_probability)
    schedule_meta["base_checkpoint_sha256"] = base_sha
    schedule_meta["renderer_overlay_complete_sha256"] = sha(args.renderer_overlay / "complete.json")
    args.output_root.mkdir(parents=True)
    save(args.output_root / "paired_schedule.json", {"metadata": schedule_meta, "rows": schedule, "test_used": False})

    _train_one(
        "control",
        args,
        args.base_checkpoint,
        overlay_train,
        overlay_validation,
        old_roots,
        old_train_base,
        old_validation_base,
        schedule,
        schedule_meta,
        args.output_root / "control",
    )
    control_history = json.loads((args.output_root / "control" / "history.json").read_text(encoding="utf-8"))
    _train_one(
        "arm",
        args,
        args.base_checkpoint,
        overlay_train,
        overlay_validation,
        old_roots,
        old_train_base,
        old_validation_base,
        schedule,
        schedule_meta,
        args.output_root / "arm",
        control_history=control_history,
    )
    save(
        args.output_root / "status.json",
        {"state": "complete", "steps": args.steps, "test_used": False},
    )


if __name__ == "__main__":
    main()
