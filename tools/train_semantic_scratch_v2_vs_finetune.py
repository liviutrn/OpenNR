"""Run the bounded scratch-v2 versus protected-best finetune pair.

Scratch-v1 showed that a random parent/head was behind the learned
initialization, while the later renderer-focus arm showed that a narrow
renderer gain traded away broad temporal behavior.  This runner tests one
predeclared compromise: the exact current graph, six protected old cohorts,
identity-safe scratch initialization, and a broad -> target-balanced -> broad
restoration schedule.  The finetune arm consumes the exact same serialized
windows and learning-rate schedule.

The protected checkpoint and source caches are read-only inputs.  Test rows are
never loaded.  The script is deliberately separate from production/runtime
trainers and writes only to a new output root.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import time
from pathlib import Path

import numpy as np
import torch

from joint_parent_tone_model import JointParentToneModel
from prepare_conditioning_pilot import save, sha
from train_semantic_ablation import cohort
from train_semantic_scratch_vs_finetune import (
    _base_metadata,
    _fine_tune_model,
    _identity_check,
    _new_model,
    _parameter_counts,
    _source_hashes,
    _validate_cohorts,
)
from train_spatial_tone import frame_objective
from train_temporal_student import _device_batch, evaluate_streaming


WINDOW = 8
BURN_IN = 2
BATCH = 1
WARMUP_STEPS = 200
MIN_LR_FACTOR = 0.20
NOMINAL_HEAD_LR = 1e-4
NOMINAL_PARENT_LR = 1e-5
LABELS = [
    "prior",
    "high_effect",
    "renderer_pilot",
    "fresh_session",
    "renderer_state",
    "new_pairs",
]
PROTECTED_BEST_SHA256 = (
    "40C214A9C0BC214C6E1366872E6D9270BFE7C00D63797AEFB6B3896865C15756"
)
STAGE_PROBABILITIES = {
    "broad_acquisition": np.asarray([0.40, 0.15, 0.10, 0.15, 0.10, 0.10], dtype=np.float64),
    "target_balanced": np.asarray([0.30, 0.15, 0.20, 0.15, 0.15, 0.05], dtype=np.float64),
    "broad_restoration": np.asarray([0.35, 0.15, 0.15, 0.15, 0.15, 0.05], dtype=np.float64),
}


def _read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, value) -> None:
    save(Path(path), value)


def _v2_source_hashes() -> dict[str, str]:
    result = dict(_source_hashes())
    result[Path(__file__).name] = sha(Path(__file__))
    return result


def _stage_layout(steps: int) -> list[dict]:
    if steps == 400:
        return [{"name": "broad_acquisition", "start": 1, "end": 400}]
    if steps != 3200:
        raise ValueError("The predeclared v2 runner accepts only 400-step calibration or 3200-step primary runs")
    return [
        {"name": "broad_acquisition", "start": 1, "end": 1600},
        {"name": "target_balanced", "start": 1601, "end": 2400},
        {"name": "broad_restoration", "start": 2401, "end": 3200},
    ]


def _stage_for_step(step: int, stages: list[dict]) -> dict:
    for stage in stages:
        if int(stage["start"]) <= step <= int(stage["end"]):
            return stage
    raise ValueError(f"No v2 stage for step {step}")


def _make_schedule(train, steps: int, seed: int) -> tuple[list[dict], dict]:
    """Create one deterministic stage-aware window schedule for both arms."""

    stages = _stage_layout(steps)
    rng = np.random.default_rng(seed)
    rows: list[dict] = []
    digest = hashlib.sha256()
    stage_draws = {stage["name"]: [0 for _ in train] for stage in stages}
    for step in range(1, steps + 1):
        stage = _stage_for_step(step, stages)
        probabilities = STAGE_PROBABILITIES[stage["name"]]
        index = int(rng.choice(len(train), p=probabilities))
        _, _, ids = train[index].sample_window(rng, BATCH, WINDOW)
        ids = np.asarray(ids, dtype=np.int64)
        stage_draws[stage["name"]][index] += 1
        digest.update(np.asarray([step, stages.index(stage), index], dtype="<i8").tobytes())
        digest.update(ids.astype("<i8", copy=False).tobytes())
        rows.append(
            {
                "step": int(step),
                "stage": stage["name"],
                "old_index": index,
                "old_label": LABELS[index],
                "ids": ids.tolist(),
            }
        )
    metadata = {
        "seed": int(seed),
        "steps": int(steps),
        "window": WINDOW,
        "burn_in": BURN_IN,
        "batch": BATCH,
        "stages": [
            {
                "name": stage["name"],
                "start": int(stage["start"]),
                "end": int(stage["end"]),
                "probabilities": STAGE_PROBABILITIES[stage["name"]].tolist(),
                "draws": stage_draws[stage["name"]],
            }
            for stage in stages
        ],
        "digest_sha256": digest.hexdigest(),
    }
    return rows, metadata


def _learning_rate_factor(step: int, steps: int) -> float:
    if step <= WARMUP_STEPS:
        return MIN_LR_FACTOR + (1.0 - MIN_LR_FACTOR) * (step / WARMUP_STEPS)
    progress = (step - WARMUP_STEPS) / max(steps - WARMUP_STEPS, 1)
    cosine = 0.5 * (1.0 + math.cos(math.pi * min(max(progress, 0.0), 1.0)))
    return MIN_LR_FACTOR + (1.0 - MIN_LR_FACTOR) * cosine


def _make_optimizer(model: JointParentToneModel):
    head_params = [parameter for parameter in model.head.parameters() if parameter.requires_grad]
    parent_params = [parameter for parameter in model.parent.parameters() if parameter.requires_grad]
    if not head_params or not parent_params:
        raise ValueError("Both the semantic head and parent must have trainable parameters")
    return torch.optim.AdamW(
        [
            {"params": head_params, "lr": NOMINAL_HEAD_LR},
            {"params": parent_params, "lr": NOMINAL_PARENT_LR},
        ],
        weight_decay=1e-4,
    )


def _set_learning_rates(optimizer, factor: float) -> None:
    optimizer.param_groups[0]["lr"] = NOMINAL_HEAD_LR * factor
    optimizer.param_groups[1]["lr"] = NOMINAL_PARENT_LR * factor


def _run_metadata(
    mode: str,
    args,
    base_payload: dict,
    base_sha: str,
    parent_path: Path,
    old_roots: list[Path],
    train,
    validation,
    schedule_meta: dict,
    output: Path,
    counts: dict[str, int],
    identity: dict,
) -> dict:
    base_run = base_payload["run"]
    return {
        "architecture": "semantic_scratch_vs_finetune_v2",
        "mode": mode,
        "initialization": (
            "identity_safe_random_trainable_parent_and_head_with_frozen_pretrained_dino"
            if mode == "scratch_v2"
            else "protected_best_weights_with_fresh_adamw"
        ),
        "base_checkpoint": str(args.base_checkpoint.resolve()),
        "base_checkpoint_sha256": base_sha,
        "base_step": int(torch.load(args.base_checkpoint, map_location="cpu", weights_only=False)["step"]),
        "parent": str(parent_path.resolve()),
        "parent_sha256": sha(parent_path),
        "base_architecture": base_run.get("architecture"),
        "base_config": base_run.get("base_config"),
        "temporal_config": base_run.get("temporal_config"),
        "capacity_config": base_run.get("capacity_config"),
        "cohorts": [str(root.resolve()) for root in old_roots],
        "cohort_labels": LABELS,
        "cohort_complete_sha256": [sha(root / "complete.json") for root in old_roots],
        "training_sequences": [cache.sequence_ids for cache in train],
        "validation_sequences": [cache.sequence_ids for cache in validation],
        "seed": int(args.seed),
        "steps": int(args.steps),
        "learning_rate": NOMINAL_HEAD_LR,
        "parent_learning_rate": NOMINAL_PARENT_LR,
        "learning_rate_schedule": {
            "type": "linear_warmup_then_cosine_decay",
            "warmup_steps": WARMUP_STEPS,
            "minimum_factor": MIN_LR_FACTOR,
            "factor_at_step_1": _learning_rate_factor(1, args.steps),
            "factor_at_final_step": _learning_rate_factor(args.steps, args.steps),
        },
        "eval_every": int(args.eval_every),
        "status_every": int(args.status_every),
        "window": WINDOW,
        "burn_in": BURN_IN,
        "batch": BATCH,
        "loss": "L1",
        "pixel_only": True,
        "pretrained_encoder": True,
        "encoder_provenance": base_run.get("encoder_provenance"),
        "parameter_counts": counts,
        "identity_check": identity,
        "schedule": schedule_meta,
        "schedule_sha256": schedule_meta["digest_sha256"],
        "source_sha256": _v2_source_hashes(),
        "test_used": False,
        "output": str(output.resolve()),
        "protected_best_run": str(args.base_checkpoint.parent / "run.json"),
        "clean7_training": False,
    }


def _checkpoint(
    output: Path,
    model: JointParentToneModel,
    optimizer,
    run: dict,
    step: int,
    metrics: dict,
    protected_reference: dict,
    history: list[dict],
    schedule: list[dict],
    draws: dict[str, int],
    stage_draws: dict[str, dict[str, int]],
    name: str,
) -> None:
    payload = {
        "architecture": "semantic_joint_parent_v1",
        "head": model.head.state_dict(),
        "parent_model": model.parent.state_dict(),
        "run": run,
        "step": int(step),
        "validation": metrics,
        "optimizer": optimizer.state_dict(),
        "torch_rng_state": torch.get_rng_state(),
        "cuda_rng_state": torch.cuda.get_rng_state_all(),
        "protected_reference_validation": protected_reference,
        "history": history,
        "schedule_position": int(step),
        "schedule_sha256": run["schedule_sha256"],
        "draws": dict(draws),
        "stage_draws": stage_draws,
        "test_used": False,
    }
    tmp = output / (name + ".tmp")
    torch.save(payload, tmp)
    tmp.replace(output / name)
    snapshot = output / f"checkpoint_{step}.pt"
    if not snapshot.exists():
        try:
            os.link(output / name, snapshot)
        except OSError:
            snapshot.write_bytes((output / name).read_bytes())
    _write_json(
        output / f"checkpoint_{step}_identity.json",
        {"step": int(step), "sha256": sha(snapshot), "path": str(snapshot.resolve())},
    )


def _train_one(
    mode: str,
    args,
    base_payload: dict,
    base_sha: str,
    parent_payload: dict,
    parent_path: Path,
    old_roots: list[Path],
    train,
    validation,
    schedule: list[dict],
    schedule_meta: dict,
    protected_reference: dict,
    output: Path,
) -> dict:
    if output.exists():
        raise FileExistsError(output)
    output.mkdir(parents=True)
    torch.cuda.reset_peak_memory_stats()
    if mode == "scratch_v2":
        model = _new_model(parent_payload, args.seed)
    else:
        model = _fine_tune_model(args.base_checkpoint, args.seed)
    counts = _parameter_counts(model)
    identity = _identity_check(model) if mode == "scratch_v2" else {"passed": None, "not_applicable": True}
    if mode == "scratch_v2" and not identity["passed"]:
        raise ValueError(f"Scratch identity check failed: {identity}")
    run = _run_metadata(
        mode,
        args,
        base_payload,
        base_sha,
        parent_path,
        old_roots,
        train,
        validation,
        schedule_meta,
        output,
        counts,
        identity,
    )
    _write_json(output / "run.json", run)
    _write_json(output / "schedule_identity.json", {"metadata": schedule_meta, "test_used": False})

    optimizer = _make_optimizer(model)
    history: list[dict] = []
    draws = {label: 0 for label in LABELS}
    stage_draws = {
        stage["name"]: {label: 0 for label in LABELS}
        for stage in schedule_meta["stages"]
    }
    baseline = None
    started = time.time()
    step_zero_max_abs_difference = None

    def evaluate(step: int) -> None:
        nonlocal baseline, step_zero_max_abs_difference
        metrics = {}
        for label, cache in zip(LABELS, validation):
            _write_json(
                output / "status.json",
                {"state": "evaluating", "mode": mode, "step": int(step), "cohort": label, "test_used": False},
            )
            metrics[label] = evaluate_streaming(model, cache, batch=args.eval_batch)
        if baseline is None:
            baseline = metrics
            _write_json(output / "baseline_validation.json", {"step": int(step), "metrics": metrics, "test_used": False})
        if step == 0:
            differences = []
            for label in LABELS:
                for key in ("mae", "psnr", "temporal_delta_mae"):
                    differences.append(abs(float(metrics[label][key]) - float(protected_reference[label][key])))
            step_zero_max_abs_difference = max(differences)
            _write_json(
                output / "step_zero_protected_replay.json",
                {"max_abs_difference": step_zero_max_abs_difference, "mode": mode, "test_used": False},
            )
        relative_to_protected = {
            label: {
                "mae": metrics[label]["mae"] / max(protected_reference[label]["mae"], 1e-12),
                "temporal_delta_mae": metrics[label]["temporal_delta_mae"]
                / max(protected_reference[label]["temporal_delta_mae"], 1e-12),
            }
            for label in LABELS
        }
        relative_to_baseline = {
            label: {
                "mae": metrics[label]["mae"] / max(baseline[label]["mae"], 1e-12),
                "temporal_delta_mae": metrics[label]["temporal_delta_mae"]
                / max(baseline[label]["temporal_delta_mae"], 1e-12),
            }
            for label in LABELS
        }
        broad_mae_gate = bool(
            all(metrics[label]["mae"] <= protected_reference[label]["mae"] + 1e-9 for label in LABELS)
        )
        broad_temporal_gate = bool(
            all(
                metrics[label]["temporal_delta_mae"]
                <= protected_reference[label]["temporal_delta_mae"] + 1e-9
                for label in LABELS
            )
        )
        old_metrics = [metrics[label]["mae"] for label in LABELS]
        protected_old = [protected_reference[label]["mae"] for label in LABELS]
        entry = {
            "step": int(step),
            "validation": metrics,
            "relative_to_protected": relative_to_protected,
            "relative_to_baseline": relative_to_baseline,
            "ordinary_renderer_pilot_mae": metrics["renderer_pilot"]["mae"],
            "ordinary_target_met": bool(metrics["renderer_pilot"]["mae"] <= 0.007),
            "old_mean_mae": float(np.mean(old_metrics)),
            "protected_old_mean_mae": float(np.mean(protected_old)),
            "old_mean_ratio_to_protected": float(np.mean(old_metrics) / max(np.mean(protected_old), 1e-12)),
            "old_cohorts_not_worse_than_protected": broad_mae_gate,
            "old_temporal_not_worse_than_protected": broad_temporal_gate,
            "step_zero_protected_replay_max_abs_difference": step_zero_max_abs_difference,
            "learning_rate_factor": _learning_rate_factor(step, args.steps) if step else None,
            "seconds": time.time() - started,
            "draws": dict(draws),
            "stage_draws": {name: dict(values) for name, values in stage_draws.items()},
            "test_used": False,
        }
        history.append(entry)
        _write_json(output / "history.json", history)
        _write_json(output / "status.json", {"state": "checkpointing", "mode": mode, "step": int(step), "test_used": False})
        _checkpoint(
            output,
            model,
            optimizer,
            run,
            step,
            metrics,
            protected_reference,
            history,
            schedule,
            draws,
            stage_draws,
            "last.pt",
        )
        print(
            json.dumps(
                {
                    "mode": mode,
                    "step": int(step),
                    "ordinary_renderer_pilot_mae": entry["ordinary_renderer_pilot_mae"],
                    "old_mean_mae": entry["old_mean_mae"],
                    "old_mean_ratio_to_protected": entry["old_mean_ratio_to_protected"],
                    "ordinary_target_met": entry["ordinary_target_met"],
                    "old_cohorts_not_worse_than_protected": broad_mae_gate,
                    "old_temporal_not_worse_than_protected": broad_temporal_gate,
                    "mae": {label: metrics[label]["mae"] for label in LABELS},
                }
            ),
            flush=True,
        )

    try:
        evaluate(0)
        for row in schedule:
            step = int(row["step"])
            index = int(row["old_index"])
            dataset = train[index]
            ids = np.asarray(row["ids"], dtype=np.int64)
            factor = _learning_rate_factor(step, args.steps)
            _set_learning_rates(optimizer, factor)
            rgb, target, guides, context = _device_batch(dataset.load_window(ids))
            rgb, target = rgb.float() / 255.0, target.float() / 255.0
            guides, context = guides.float(), context.float()
            model.train()
            optimizer.zero_grad(set_to_none=True)
            state = None
            previous = None
            losses = []
            for frame in range(WINDOW):
                with torch.set_grad_enabled(frame >= BURN_IN), torch.autocast("cuda", dtype=torch.bfloat16):
                    pred, state = model.forward_temporal(rgb[:, frame], guides[:, frame], context[:, frame], state)
                    error = pred.float() - target[:, frame]
                    if frame >= BURN_IN:
                        losses.append(frame_objective(error, previous, pixel_only=True))
                    previous = error if frame >= BURN_IN else error.detach()
            loss = torch.stack(losses).mean()
            if not torch.isfinite(loss):
                raise ValueError(f"Nonfinite loss at {mode} step {step}")
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.head.parameters(), 1.0, error_if_nonfinite=True)
            torch.nn.utils.clip_grad_norm_(model.parent.parameters(), 1.0, error_if_nonfinite=True)
            optimizer.step()
            draws[LABELS[index]] += 1
            stage_draws[row["stage"]][LABELS[index]] += 1
            loss_value = float(loss.detach())
            if step == 1 or step % args.status_every == 0:
                status = {
                    "state": "training",
                    "mode": mode,
                    "step": step,
                    "steps": int(args.steps),
                    "stage": row["stage"],
                    "loss": loss_value,
                    "learning_rate_factor": factor,
                    "learning_rates": [group["lr"] for group in optimizer.param_groups],
                    "draws": dict(draws),
                    "stage_draws": {name: dict(values) for name, values in stage_draws.items()},
                    "seconds": time.time() - started,
                    "gpu_peak_gib": torch.cuda.max_memory_allocated() / 2**30,
                    "test_used": False,
                }
                _write_json(output / "status.json", status)
                print(json.dumps(status), flush=True)
            if step % args.eval_every == 0 or step == args.steps:
                del rgb, target, guides, context, pred, error, loss, state, previous, losses
                torch.cuda.empty_cache()
                evaluate(step)
            else:
                del rgb, target, guides, context, pred, error, loss, state, previous, losses
        _write_json(
            output / "status.json",
            {
                "state": "complete",
                "mode": mode,
                "steps": int(args.steps),
                "ordinary_target_met": any(row["ordinary_target_met"] for row in history),
                "old_broad_gate": any(
                    row["step"] > 0
                    and row["old_cohorts_not_worse_than_protected"]
                    and row["old_temporal_not_worse_than_protected"]
                    for row in history
                ),
                "gpu_peak_gib": torch.cuda.max_memory_allocated() / 2**30,
                "test_used": False,
                "seconds": time.time() - started,
            },
        )
        return run
    except Exception as exc:
        _write_json(output / "status.json", {"state": "failed", "mode": mode, "error": repr(exc), "test_used": False})
        raise
    finally:
        del model, optimizer
        torch.cuda.empty_cache()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-checkpoint", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--steps", type=int, default=3200)
    parser.add_argument("--eval-every", type=int, default=400)
    parser.add_argument("--status-every", type=int, default=50)
    parser.add_argument("--eval-batch", type=int, default=1)
    parser.add_argument("--seed", type=int, default=909)
    args = parser.parse_args()
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is required")
    if args.steps not in (400, 3200):
        raise ValueError("Use the predeclared 400-step calibration or 3200-step primary budget")
    if args.eval_every < 1 or args.status_every < 1 or args.eval_batch < 1:
        raise ValueError("Evaluation/status intervals and eval batch must be positive")
    if args.steps % args.eval_every:
        raise ValueError("Steps must be divisible by eval-every")
    args.base_checkpoint = args.base_checkpoint.resolve()
    args.output_root = args.output_root.resolve()
    if not args.base_checkpoint.is_file():
        raise FileNotFoundError(args.base_checkpoint)
    if args.output_root.exists():
        raise FileExistsError(args.output_root)
    base_sha = sha(args.base_checkpoint)
    if base_sha.lower() != PROTECTED_BEST_SHA256.lower():
        raise ValueError(f"The supplied checkpoint is not the immutable protected best: {base_sha}")
    base_payload, parent_payload, parent_path = _base_metadata(args.base_checkpoint)
    base_run = base_payload["run"]
    old_roots = [Path(value).resolve() for value in base_run["cohorts"]]
    if len(old_roots) != 6:
        raise ValueError("The protected-best parity corpus must contain exactly six old cohorts")
    _validate_cohorts(old_roots)
    train = [cohort(root, "train") for root in old_roots]
    validation = [cohort(root, "validation") for root in old_roots]
    protected_reference = base_payload.get("validation")
    if not isinstance(protected_reference, dict) or any(label not in protected_reference for label in LABELS):
        raise ValueError("Protected checkpoint does not contain the six-cohort validation reference")
    schedule, schedule_meta = _make_schedule(train, args.steps, args.seed)
    args.output_root.mkdir(parents=True)
    _write_json(
        args.output_root / "paired_schedule.json",
        {
            "metadata": schedule_meta,
            "rows": schedule,
            "cohort_labels": LABELS,
            "cohort_complete_sha256": [sha(root / "complete.json") for root in old_roots],
            "test_used": False,
        },
    )
    _write_json(
        args.output_root / "experiment_identity.json",
        {
            "architecture": "semantic_scratch_vs_finetune_v2",
            "base_checkpoint": str(args.base_checkpoint),
            "base_checkpoint_sha256": base_sha,
            "parent": str(parent_path),
            "parent_sha256": sha(parent_path),
            "cohorts": [str(root) for root in old_roots],
            "cohort_labels": LABELS,
            "schedule_sha256": schedule_meta["digest_sha256"],
            "steps": int(args.steps),
            "test_used": False,
            "source_sha256": _v2_source_hashes(),
        },
    )
    _write_json(args.output_root / "status.json", {"state": "starting", "test_used": False})
    scratch = _train_one(
        "scratch_v2",
        args,
        base_payload,
        base_sha,
        parent_payload,
        parent_path,
        old_roots,
        train,
        validation,
        schedule,
        schedule_meta,
        protected_reference,
        args.output_root / "scratch_v2",
    )
    finetune = _train_one(
        "finetune_v2",
        args,
        base_payload,
        base_sha,
        parent_payload,
        parent_path,
        old_roots,
        train,
        validation,
        schedule,
        schedule_meta,
        protected_reference,
        args.output_root / "finetune_v2",
    )
    scratch_history = _read_json(args.output_root / "scratch_v2" / "history.json")
    finetune_history = _read_json(args.output_root / "finetune_v2" / "history.json")
    _write_json(
        args.output_root / "summary.json",
        {
            "architecture": "semantic_scratch_vs_finetune_v2",
            "protected_best": str(args.base_checkpoint),
            "protected_best_sha256": base_sha,
            "schedule_sha256": schedule_meta["digest_sha256"],
            "scratch": {
                "run": scratch,
                "final": scratch_history[-1],
                "checkpoint": str((args.output_root / "scratch_v2" / f"checkpoint_{args.steps}.pt").resolve()),
                "checkpoint_sha256": sha(args.output_root / "scratch_v2" / f"checkpoint_{args.steps}.pt"),
            },
            "finetune": {
                "run": finetune,
                "final": finetune_history[-1],
                "checkpoint": str((args.output_root / "finetune_v2" / f"checkpoint_{args.steps}.pt").resolve()),
                "checkpoint_sha256": sha(args.output_root / "finetune_v2" / f"checkpoint_{args.steps}.pt"),
            },
            "test_used": False,
        },
    )
    _write_json(
        args.output_root / "status.json",
        {
            "state": "complete",
            "steps": int(args.steps),
            "scratch_state": "complete",
            "finetune_state": "complete",
            "test_used": False,
        },
    )


if __name__ == "__main__":
    main()
