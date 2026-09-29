"""Run a matched renderer-focus pair with a conservative retention objective.

The focus control and retention arm start from the immutable protected-best
checkpoint, consume one serialized six-cohort schedule, and never load frozen
test rows.  The retention arm adds pooled/temporal reconstruction terms and a
training-only normalized parameter-drift anchor to the protected weights.  It
is deliberately separate from the production trainer and writes only to a
new output root.
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
from torch.nn import functional as F

import train_semantic_scratch_v2_vs_finetune as v2
import train_semantic_scratch_vs_finetune as scratch
from prepare_conditioning_pilot import save, sha
from train_semantic_ablation import cohort
from train_spatial_tone import frame_objective
from train_temporal_student import _device_batch, evaluate_streaming


WINDOW = 8
BURN_IN = 2
BATCH = 1
WARMUP_STEPS = 200
MIN_LR_FACTOR = 0.20
HEAD_LR = 1e-4
PARENT_LR = 1e-5
POOL_WEIGHT = 0.25
TEMPORAL_WEIGHT = 0.12
ANCHOR_WEIGHT = 0.25
TARGET_ANCHOR_RELAXATION = 0.25
LABELS = list(v2.LABELS)
PROTECTED_BEST_SHA256 = v2.PROTECTED_BEST_SHA256

STAGE_PROBABILITIES = {
    "broad_acquisition": np.asarray([0.35, 0.15, 0.15, 0.15, 0.15, 0.05], dtype=np.float64),
    "target_focus": np.asarray([0.25, 0.15, 0.25, 0.15, 0.15, 0.05], dtype=np.float64),
    "broad_restoration": np.asarray([0.35, 0.15, 0.15, 0.15, 0.15, 0.05], dtype=np.float64),
}


def _read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, value) -> None:
    save(Path(path), value)


def _source_hashes() -> dict[str, str]:
    result = dict(v2._v2_source_hashes())
    result[Path(__file__).name] = sha(Path(__file__))
    return result


def _stage_layout(steps: int) -> list[dict]:
    if steps == 400:
        return [{"name": "broad_acquisition", "start": 1, "end": 400}]
    if steps != 2400:
        raise ValueError("This preregistered runner accepts only 400-step calibration or 2400-step primary runs")
    return [
        {"name": "broad_acquisition", "start": 1, "end": 800},
        {"name": "target_focus", "start": 801, "end": 1600},
        {"name": "broad_restoration", "start": 1601, "end": 2400},
    ]


def _stage_for_step(step: int, stages: list[dict]) -> dict:
    for stage in stages:
        if int(stage["start"]) <= step <= int(stage["end"]):
            return stage
    raise ValueError(f"No stage for step {step}")


def _make_schedule(train, steps: int, seed: int) -> tuple[list[dict], dict]:
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


def _set_learning_rates(optimizer, factor: float) -> None:
    optimizer.param_groups[0]["lr"] = HEAD_LR * factor
    optimizer.param_groups[1]["lr"] = PARENT_LR * factor


def _make_optimizer(model):
    head_params = [p for p in model.head.parameters() if p.requires_grad]
    parent_params = [p for p in model.parent.parameters() if p.requires_grad]
    if not head_params or not parent_params:
        raise ValueError("Both the semantic head and parent must have trainable parameters")
    return torch.optim.AdamW(
        [{"params": head_params, "lr": HEAD_LR}, {"params": parent_params, "lr": PARENT_LR}],
        weight_decay=1e-4,
    )


def _make_anchor(model):
    """Keep immutable GPU-side references for trainable parameters only."""

    references = []
    denominator = 0.0
    for parameter in model.parameters():
        if not parameter.requires_grad:
            continue
        reference = parameter.detach().float().clone()
        references.append((parameter, reference))
        denominator += float(reference.abs().sum().item())
    if not references or denominator <= 0.0:
        raise ValueError("Could not construct a non-empty parameter retention anchor")
    return references, denominator


def _anchor_loss(references, denominator: float) -> torch.Tensor:
    numerator = None
    for parameter, reference in references:
        term = (parameter.float() - reference).abs().sum()
        numerator = term if numerator is None else numerator + term
    return numerator / denominator


def _retention_objective(error, previous, anchor, anchor_scale: float) -> tuple[torch.Tensor, dict[str, float]]:
    pixel = error.abs().mean()
    pooled = F.avg_pool2d(error, 16).abs().mean()
    temporal = (error - previous).abs().mean()
    anchor_term = anchor * float(anchor_scale)
    loss = pixel + POOL_WEIGHT * pooled + TEMPORAL_WEIGHT * temporal + ANCHOR_WEIGHT * anchor_term
    return loss, {
        "pixel": float(pixel.detach()),
        "pooled": float(pooled.detach()),
        "temporal": float(temporal.detach()),
        "anchor": float(anchor_term.detach()),
        "total": float(loss.detach()),
    }


def _run_metadata(mode, args, base_payload, base_sha, parent_path, old_roots, train, validation, schedule_meta, output, counts):
    base_run = base_payload["run"]
    return {
        "architecture": "semantic_retention_renderer_pair_v1",
        "mode": mode,
        "initialization": "protected_best_weights_with_fresh_adamw",
        "base_checkpoint": str(args.base_checkpoint.resolve()),
        "base_checkpoint_sha256": base_sha,
        "base_step": int(base_payload["step"]),
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
        "learning_rate": HEAD_LR,
        "parent_learning_rate": PARENT_LR,
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
        "loss": (
            "pixel L1" if mode == "focus_control" else
            "pixel L1 + 0.25 pooled16 RGB L1 + 0.12 residual temporal L1 + 0.25 normalized parameter drift"
        ),
        "pixel_only": bool(mode == "focus_control"),
        "pool_weight": POOL_WEIGHT if mode == "retention_focus" else 0.0,
        "temporal_weight": TEMPORAL_WEIGHT if mode == "retention_focus" else 0.0,
        "anchor_weight": ANCHOR_WEIGHT if mode == "retention_focus" else 0.0,
        "target_anchor_relaxation": TARGET_ANCHOR_RELAXATION if mode == "retention_focus" else None,
        "anchor_definition": "sum_abs_trainable_parameter_drift / sum_abs_protected_trainable_parameters",
        "weight_decay": 1e-4,
        "gradient_clip": 1.0,
        "pretrained_encoder": True,
        "encoder_provenance": base_run.get("encoder_provenance"),
        "parameter_counts": counts,
        "schedule": schedule_meta,
        "schedule_sha256": schedule_meta["digest_sha256"],
        "source_sha256": _source_hashes(),
        "test_used": False,
        "output": str(output.resolve()),
        "protected_best_run": str(args.base_checkpoint.parent / "run.json"),
    }


def _train_one(mode, args, base_payload, base_sha, parent_path, old_roots, train, validation, schedule, schedule_meta, protected_reference, output):
    if output.exists():
        raise FileExistsError(output)
    output.mkdir(parents=True)
    torch.cuda.reset_peak_memory_stats()
    model = v2._fine_tune_model(args.base_checkpoint, args.seed)
    model.parent.requires_grad_(True)
    counts = v2._parameter_counts(model)
    run = _run_metadata(mode, args, base_payload, base_sha, parent_path, old_roots, train, validation, schedule_meta, output, counts)
    _write_json(output / "run.json", run)
    _write_json(output / "schedule_identity.json", {"metadata": schedule_meta, "test_used": False})
    optimizer = _make_optimizer(model)
    references, anchor_denominator = _make_anchor(model) if mode == "retention_focus" else ([], 0.0)
    history = []
    draws = {label: 0 for label in LABELS}
    stage_draws = {stage["name"]: {label: 0 for label in LABELS} for stage in schedule_meta["stages"]}
    baseline = None
    step_zero_max_abs_difference = None
    started = time.time()

    def evaluate(step: int) -> None:
        nonlocal baseline, step_zero_max_abs_difference
        metrics = {}
        for label, cache in zip(LABELS, validation):
            _write_json(output / "status.json", {"state": "evaluating", "mode": mode, "step": int(step), "cohort": label, "test_used": False})
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
            _write_json(output / "step_zero_protected_replay.json", {"max_abs_difference": step_zero_max_abs_difference, "mode": mode, "test_used": False})
        broad_mae_gate = all(metrics[label]["mae"] <= protected_reference[label]["mae"] + 1e-9 for label in LABELS)
        broad_temporal_gate = all(metrics[label]["temporal_delta_mae"] <= protected_reference[label]["temporal_delta_mae"] + 1e-9 for label in LABELS)
        entry = {
            "step": int(step),
            "validation": metrics,
            "relative_to_protected": {
                label: {
                    "mae": float(metrics[label]["mae"] / max(protected_reference[label]["mae"], 1e-12)),
                    "temporal_delta_mae": float(metrics[label]["temporal_delta_mae"] / max(protected_reference[label]["temporal_delta_mae"], 1e-12)),
                }
                for label in LABELS
            },
            "ordinary_renderer_pilot_mae": metrics["renderer_pilot"]["mae"],
            "ordinary_target_met": bool(metrics["renderer_pilot"]["mae"] <= 0.007),
            "old_mean_mae": float(np.mean([metrics[label]["mae"] for label in LABELS])),
            "protected_old_mean_mae": float(np.mean([protected_reference[label]["mae"] for label in LABELS])),
            "old_cohorts_not_worse_than_protected": bool(broad_mae_gate),
            "old_temporal_not_worse_than_protected": bool(broad_temporal_gate),
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
        v2._checkpoint(output, model, optimizer, run, step, metrics, protected_reference, history, schedule, draws, stage_draws, "last.pt")
        print(json.dumps({"mode": mode, "step": int(step), "ordinary_renderer_pilot_mae": entry["ordinary_renderer_pilot_mae"], "old_mean_mae": entry["old_mean_mae"], "ordinary_target_met": entry["ordinary_target_met"], "old_broad_mae_gate": broad_mae_gate, "old_broad_temporal_gate": broad_temporal_gate, "mae": {label: metrics[label]["mae"] for label in LABELS}}, separators=(",", ":")), flush=True)

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
            components = {"pixel": 0.0, "pooled": 0.0, "temporal": 0.0, "anchor": 0.0, "total": 0.0}
            for frame in range(WINDOW):
                with torch.set_grad_enabled(frame >= BURN_IN), torch.autocast("cuda", dtype=torch.bfloat16):
                    prediction, state = model.forward_temporal(rgb[:, frame], guides[:, frame], context[:, frame], state)
                    error = prediction.float() - target[:, frame]
                    if frame >= BURN_IN:
                        if mode == "focus_control":
                            losses.append(error.abs().mean())
                        else:
                            anchor = _anchor_loss(references, anchor_denominator)
                            scale = TARGET_ANCHOR_RELAXATION if LABELS[index] == "renderer_pilot" else 1.0
                            objective, values = _retention_objective(error, previous, anchor, scale)
                            losses.append(objective)
                            for key, value in values.items():
                                components[key] += value
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
            if mode == "retention_focus":
                count = WINDOW - BURN_IN
                components = {key: value / count for key, value in components.items()}
            if step == 1 or step % args.status_every == 0:
                _write_json(output / "status.json", {"state": "training", "mode": mode, "step": step, "steps": int(args.steps), "stage": row["stage"], "loss": float(loss.detach()), "loss_components": components, "learning_rate_factor": factor, "draws": dict(draws), "stage_draws": {name: dict(values) for name, values in stage_draws.items()}, "seconds": time.time() - started, "gpu_peak_gib": torch.cuda.max_memory_allocated() / 2**30, "test_used": False})
                print(json.dumps({"state": "training", "mode": mode, "step": step, "steps": int(args.steps), "loss": float(loss.detach()), "loss_components": components, "draws": dict(draws)}, separators=(",", ":")), flush=True)
            if step % args.eval_every == 0 or step == args.steps:
                del rgb, target, guides, context, prediction, error, loss, state, previous, losses
                torch.cuda.empty_cache()
                evaluate(step)
            else:
                del rgb, target, guides, context, prediction, error, loss, state, previous, losses
        _write_json(output / "status.json", {"state": "complete", "mode": mode, "steps": int(args.steps), "ordinary_target_met": any(row["ordinary_target_met"] for row in history), "old_broad_gate": any(row["step"] > 0 and row["old_cohorts_not_worse_than_protected"] and row["old_temporal_not_worse_than_protected"] for row in history), "gpu_peak_gib": torch.cuda.max_memory_allocated() / 2**30, "test_used": False, "seconds": time.time() - started})
        return {"run": run, "history": history, "status": _read_json(output / "status.json")}
    except Exception as exc:
        _write_json(output / "status.json", {"state": "failed", "mode": mode, "error": repr(exc), "test_used": False})
        raise
    finally:
        if mode == "retention_focus":
            del references
        del model, optimizer
        torch.cuda.empty_cache()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-checkpoint", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--steps", type=int, default=2400)
    parser.add_argument("--eval-every", type=int, default=400)
    parser.add_argument("--status-every", type=int, default=50)
    parser.add_argument("--eval-batch", type=int, default=1)
    parser.add_argument("--seed", type=int, default=910)
    args = parser.parse_args()
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is required")
    if args.steps not in (400, 2400):
        raise ValueError("Use the preregistered 400-step calibration or 2400-step primary run")
    if args.eval_every < 1 or args.status_every < 1 or args.eval_batch < 1 or args.steps % args.eval_every:
        raise ValueError("Invalid evaluation/status interval")
    args.base_checkpoint = args.base_checkpoint.resolve()
    args.output_root = args.output_root.resolve()
    if not args.base_checkpoint.is_file():
        raise FileNotFoundError(args.base_checkpoint)
    if args.output_root.exists():
        raise FileExistsError(args.output_root)
    base_sha = sha(args.base_checkpoint)
    if base_sha.lower() != PROTECTED_BEST_SHA256.lower():
        raise ValueError(f"The supplied checkpoint is not the immutable protected best: {base_sha}")
    base_payload, parent_payload, parent_path = v2._base_metadata(args.base_checkpoint)
    old_roots = [Path(value).resolve() for value in base_payload["run"]["cohorts"]]
    if len(old_roots) != 6:
        raise ValueError("The protected-best corpus must contain exactly six cohorts")
    scratch._validate_cohorts(old_roots)
    train = [cohort(root, "train") for root in old_roots]
    validation = [cohort(root, "validation") for root in old_roots]
    protected_reference = base_payload.get("validation")
    if not isinstance(protected_reference, dict) or any(label not in protected_reference for label in LABELS):
        raise ValueError("Protected checkpoint has no complete six-cohort validation reference")
    schedule, schedule_meta = _make_schedule(train, args.steps, args.seed)
    args.output_root.mkdir(parents=True)
    _write_json(args.output_root / "paired_schedule.json", {"metadata": schedule_meta, "rows": schedule, "cohort_labels": LABELS, "cohort_complete_sha256": [sha(root / "complete.json") for root in old_roots], "test_used": False})
    _write_json(args.output_root / "experiment_identity.json", {"architecture": "semantic_retention_renderer_pair_v1", "base_checkpoint": str(args.base_checkpoint), "base_checkpoint_sha256": base_sha, "parent": str(parent_path), "parent_sha256": sha(parent_path), "cohorts": [str(root) for root in old_roots], "cohort_labels": LABELS, "schedule_sha256": schedule_meta["digest_sha256"], "steps": int(args.steps), "loss": {"control": "pixel L1", "retention": "pixel L1 + pooled + residual temporal + parameter anchor"}, "test_used": False, "source_sha256": _source_hashes()})
    _write_json(args.output_root / "status.json", {"state": "starting", "test_used": False})
    control = _train_one("focus_control", args, base_payload, base_sha, parent_path, old_roots, train, validation, schedule, schedule_meta, protected_reference, args.output_root / "focus_control")
    retention = _train_one("retention_focus", args, base_payload, base_sha, parent_path, old_roots, train, validation, schedule, schedule_meta, protected_reference, args.output_root / "retention_focus")
    control_history = _read_json(args.output_root / "focus_control" / "history.json")
    retention_history = _read_json(args.output_root / "retention_focus" / "history.json")
    _write_json(args.output_root / "summary.json", {"architecture": "semantic_retention_renderer_pair_v1", "protected_best": str(args.base_checkpoint), "protected_best_sha256": base_sha, "schedule_sha256": schedule_meta["digest_sha256"], "focus_control": {"final": control_history[-1], "checkpoint": str((args.output_root / "focus_control" / f"checkpoint_{args.steps}.pt").resolve()), "checkpoint_sha256": sha(args.output_root / "focus_control" / f"checkpoint_{args.steps}.pt")}, "retention_focus": {"final": retention_history[-1], "checkpoint": str((args.output_root / "retention_focus" / f"checkpoint_{args.steps}.pt").resolve()), "checkpoint_sha256": sha(args.output_root / "retention_focus" / f"checkpoint_{args.steps}.pt")}, "test_used": False})
    _write_json(args.output_root / "status.json", {"state": "complete", "steps": int(args.steps), "focus_control_state": "complete", "retention_focus_state": "complete", "test_used": False})


if __name__ == "__main__":
    main()
