"""Run a bounded paired recovery continuation from the best finetune candidate.

The control and arm start from the same experimental finetune checkpoint.  The
control ignores the new clean7 cohort; the arm uses the same precomputed old
windows but replaces a small fraction with clean7 windows.  Both use a fresh,
lower-rate AdamW state and the protected-best validation as the acceptance
reference.  The script is deliberately separate from the protected production
trainer and never reads test pixels.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path

import numpy as np
import torch

import train_semantic_scratch_vs_finetune as scratch
from joint_parent_tone_model import JointParentToneModel
from prepare_conditioning_pilot import save, sha
from semantic_tone_head import SemanticToneHead
from train_semantic_ablation import cohort
from train_capacity_temporal_student import _load_parent
from train_spatial_tone import frame_objective
from train_temporal_student import _device_batch, evaluate_streaming


WINDOW = scratch.WINDOW
BURN_IN = scratch.BURN_IN
BATCH = scratch.BATCH
OLD_PROBABILITIES = scratch.OLD_PROBABILITIES
LABELS = scratch.LABELS


def _read_json(path: Path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _write_json(path: Path, value) -> None:
    save(Path(path), value)


def _source_hashes() -> dict[str, str]:
    names = (
        "train_semantic_recovery_pair.py",
        "train_semantic_scratch_vs_finetune.py",
        "joint_parent_tone_model.py",
        "semantic_tone_head.py",
        "capacity_temporal_student.py",
        "capacity_student.py",
        "temporal_student.py",
        "student_v2.py",
        "aligned_cohort.py",
        "train_semantic_ablation.py",
        "train_temporal_student.py",
        "train_spatial_tone.py",
    )
    return {name: sha(Path(__file__).with_name(name)) for name in names}


def _check_base_contract(
    base_checkpoint: Path,
    old_roots: list[Path],
    new_root: Path,
) -> tuple[dict, dict, Path, dict, dict]:
    """Verify the experimental starting checkpoint and its immutable inputs."""

    payload = torch.load(base_checkpoint, map_location="cpu", weights_only=False)
    if payload.get("architecture") != "semantic_joint_parent_v1":
        raise ValueError("Recovery requires a semantic_joint_parent_v1 checkpoint")
    run = payload.get("run", {})
    if int(payload.get("step", -1)) < 1:
        raise ValueError("Recovery checkpoint has no completed training step")
    recorded_roots = [Path(value).resolve() for value in run.get("cohorts", [])]
    expected_roots = old_roots + [new_root]
    if recorded_roots != expected_roots:
        raise ValueError("Recovery cohorts do not match the starting checkpoint")
    recorded_labels = list(run.get("cohort_labels", []))
    if recorded_labels != LABELS:
        raise ValueError("Recovery cohort labels do not match the starting checkpoint")
    for root, digest in zip(recorded_roots, run.get("cohort_complete_sha256", [])):
        if sha(root / "complete.json") != digest:
            raise ValueError(f"Starting cohort changed: {root}")

    source_mismatches = []
    for name, digest in run.get("source_sha256", {}).items():
        source = Path(__file__).with_name(name)
        actual = sha(source)
        if actual != digest:
            # The only expected mismatch is the scratch-vs-finetune trainer's
            # post-run bookkeeping correction.  It changed reporting/replay
            # metadata only; the model graph and objective are unchanged.  All
            # model, data-loader, encoder, and parent sources remain strict.
            if name != "train_semantic_scratch_vs_finetune.py":
                raise ValueError(f"Starting training source changed: {name}")
            source_mismatches.append(
                {"name": name, "recorded_sha256": digest, "current_sha256": actual, "reason": "post_run_bookkeeping_fix"}
            )

    parent_path = Path(run["parent"]).resolve()
    if sha(parent_path) != run["parent_sha256"]:
        raise ValueError("Starting parent checkpoint changed")
    protected_path = Path(run["base_checkpoint"]).resolve()
    if sha(protected_path) != run["base_checkpoint_sha256"]:
        raise ValueError("Protected-best checkpoint referenced by the candidate changed")
    protected_reference = payload.get("protected_reference_validation")
    if not isinstance(protected_reference, dict) or set(protected_reference) != set(LABELS):
        raise ValueError("Starting checkpoint has no complete protected validation reference")
    validation = payload.get("validation")
    if not isinstance(validation, dict) or set(validation) != set(LABELS):
        raise ValueError("Starting checkpoint has no complete validation record")
    run = dict(run)
    run["source_compatibility_mismatches"] = source_mismatches
    return payload, run, parent_path, protected_reference, validation


def _load_candidate_checkpoint(path: Path):
    """Load the candidate while allowing only the known audit-only source delta."""

    payload = torch.load(path, map_location="cpu", weights_only=False)
    run = payload["run"]
    parent, *_ = _load_parent(Path(run["parent"]))
    parent.load_state_dict(payload["parent_model"], strict=True)
    head = SemanticToneHead(False).cuda()
    head.load_state_dict(payload["head"], strict=True)
    return JointParentToneModel(parent, head).eval()


def _max_metric_difference(left: dict, right: dict) -> float:
    maximum = 0.0
    for label in LABELS:
        for key in ("mae", "temporal_delta_mae", "first_frame_mae", "steady_frame_mae"):
            maximum = max(maximum, abs(float(left[label][key]) - float(right[label][key])))
        for eye in left[label]["eye_mae"]:
            maximum = max(maximum, abs(float(left[label]["eye_mae"][eye]) - float(right[label]["eye_mae"][eye])))
    return maximum


def _optimizer(model, learning_rate: float, parent_learning_rate: float):
    """Create AdamW while allowing a deliberate frozen-parent arm."""

    head_params = [p for p in model.head.parameters() if p.requires_grad]
    parent_params = [p for p in model.parent.parameters() if p.requires_grad]
    if not head_params:
        raise ValueError("Semantic head has no trainable parameters")
    groups = [{"params": head_params, "lr": learning_rate}]
    if parent_params:
        groups.append({"params": parent_params, "lr": parent_learning_rate})
    return torch.optim.AdamW(groups, weight_decay=1e-4)


def _ratios(metrics: dict, reference: dict) -> dict:
    return {
        label: {
            "mae": float(metrics[label]["mae"] / max(reference[label]["mae"], 1e-12)),
            "temporal_delta_mae": float(
                metrics[label]["temporal_delta_mae"]
                / max(reference[label]["temporal_delta_mae"], 1e-12)
            ),
        }
        for label in LABELS
    }


def _make_run(
    mode: str,
    args,
    base_payload: dict,
    base_run: dict,
    base_checkpoint: Path,
    base_sha: str,
    parent_path: Path,
    roots: list[Path],
    train,
    validation,
    schedule_meta: dict,
    output: Path,
    counts: dict[str, int],
    start_match_max_abs: float,
) -> dict:
    effective_new_probability = float(args.new_probability if mode == "arm" else 0.0)
    return {
        "architecture": "semantic_recovery_pair_v1",
        "checkpoint_architecture": "semantic_joint_parent_v1",
        "mode": mode,
        "initialization": "finetune_candidate_step1600_weights_with_fresh_adamw",
        "parent_frozen": bool(getattr(args, "freeze_parent", False)),
        "base_checkpoint": str(base_checkpoint.resolve()),
        "base_checkpoint_sha256": base_sha,
        "base_step": int(base_payload["step"]),
        "protected_checkpoint": str(Path(base_run["base_checkpoint"]).resolve()),
        "protected_checkpoint_sha256": base_run["base_checkpoint_sha256"],
        "parent": str(parent_path.resolve()),
        "parent_sha256": sha(parent_path),
        "base_config": base_run.get("base_config"),
        "temporal_config": base_run.get("temporal_config"),
        "capacity_config": base_run.get("capacity_config"),
        "cohorts": [str(root.resolve()) for root in roots],
        "cohort_labels": LABELS,
        "cohort_complete_sha256": [sha(root / "complete.json") for root in roots],
        "training_sequences": [cache.sequence_ids for cache in train],
        "validation_sequences": [cache.sequence_ids for cache in validation],
        "old_probability": list(schedule_meta.get("old_probability", OLD_PROBABILITIES.tolist())),
        "scheduled_new_probability": float(args.new_probability),
        "effective_new_probability": effective_new_probability,
        "paired_schedule": True,
        "seed": int(args.seed),
        "steps": int(args.steps),
        "learning_rate": float(args.learning_rate),
        "parent_learning_rate": float(args.parent_learning_rate),
        "optimizer_initialization": "fresh_adamw",
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
        "starting_checkpoint_validation_max_abs_difference": start_match_max_abs,
        "schedule": schedule_meta,
        "schedule_sha256": schedule_meta["serialized_sha256"],
        "source_sha256": _source_hashes(),
        "test_used": False,
        "output": str(output.resolve()),
    }


def _train_arm(
    mode: str,
    args,
    base_checkpoint: Path,
    base_sha: str,
    base_payload: dict,
    base_run: dict,
    parent_path: Path,
    protected_reference: dict,
    base_validation: dict,
    roots: list[Path],
    train,
    validation,
    schedule: list[dict],
    schedule_meta: dict,
    output: Path,
) -> dict:
    if output.exists():
        raise FileExistsError(output)
    output.mkdir(parents=True)
    torch.manual_seed(args.seed)
    torch.cuda.manual_seed_all(args.seed)
    model = _load_candidate_checkpoint(base_checkpoint)
    model.parent.requires_grad_(not bool(getattr(args, "freeze_parent", False)))
    model.eval()
    counts = scratch._parameter_counts(model)
    optimizer = _optimizer(model, args.learning_rate, args.parent_learning_rate)
    history: list[dict] = []
    draws = {label: 0 for label in LABELS}
    baseline = None
    started = time.time()
    start_match_max_abs = None
    run = None

    def evaluate(step: int) -> None:
        nonlocal baseline, start_match_max_abs, run
        metrics = {}
        for label, cache in zip(LABELS, validation):
            _write_json(
                output / "status.json",
                {
                    "state": "evaluating",
                    "mode": mode,
                    "step": step,
                    "cohort": label,
                    "test_used": False,
                },
            )
            metrics[label] = evaluate_streaming(model, cache, batch=args.eval_batch)
        if baseline is None:
            baseline = metrics
            start_match_max_abs = _max_metric_difference(metrics, base_validation)
            run = _make_run(
                mode,
                args,
                base_payload,
                base_run,
                base_checkpoint,
                base_sha,
                parent_path,
                roots,
                train,
                validation,
                schedule_meta,
                output,
                counts,
                start_match_max_abs,
            )
            _write_json(output / "run.json", run)
        relative_to_start = _ratios(metrics, base_validation)
        relative_to_protected = _ratios(metrics, protected_reference)
        broad_mae_gate = bool(
            all(metrics[label]["mae"] <= protected_reference[label]["mae"] + 1e-9 for label in LABELS[:6])
        )
        broad_temporal_gate = bool(
            all(
                metrics[label]["temporal_delta_mae"]
                <= protected_reference[label]["temporal_delta_mae"] + 1e-9
                for label in LABELS[:6]
            )
        )
        old_values = [metrics[label]["mae"] for label in LABELS[:6]]
        protected_values = [protected_reference[label]["mae"] for label in LABELS[:6]]
        entry = {
            "step": int(step),
            "validation": metrics,
            "relative_to_start": relative_to_start,
            "relative_to_protected": relative_to_protected,
            "ordinary_renderer_pilot_mae": metrics["renderer_pilot"]["mae"],
            "ordinary_target_met": bool(metrics["renderer_pilot"]["mae"] <= 0.007),
            "old_mean_mae": float(np.mean(old_values)),
            "protected_old_mean_mae": float(np.mean(protected_values)),
            "old_mean_ratio_to_protected": float(np.mean(old_values) / np.mean(protected_values)),
            "old_cohorts_not_worse_than_protected": broad_mae_gate,
            "old_temporal_not_worse_than_protected": broad_temporal_gate,
            "start_match_max_abs_difference": start_match_max_abs,
            "seconds": time.time() - started,
            "draws": dict(draws),
            "test_used": False,
        }
        history.append(entry)
        _write_json(output / "history.json", history)
        _write_json(
            output / "status.json",
            {"state": "checkpointing", "mode": mode, "step": step, "test_used": False},
        )
        scratch._checkpoint(
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
            "last.pt",
        )
        print(
            json.dumps(
                {
                    "mode": mode,
                    "step": step,
                    "ordinary_renderer_pilot_mae": entry["ordinary_renderer_pilot_mae"],
                    "old_mean_mae": entry["old_mean_mae"],
                    "old_mean_ratio_to_protected": entry["old_mean_ratio_to_protected"],
                    "ordinary_target_met": entry["ordinary_target_met"],
                    "old_broad_mae_gate": broad_mae_gate,
                    "old_broad_temporal_gate": broad_temporal_gate,
                    "mae": {label: metrics[label]["mae"] for label in LABELS},
                }
            ),
            flush=True,
        )

    try:
        evaluate(0)
        for step, draw in enumerate(schedule, start=1):
            if mode == "arm" and draw["use_new"]:
                dataset = train[-1]
                ids = np.asarray(draw["new_ids"], dtype=np.int64)
                label = LABELS[-1]
            else:
                index = int(draw["old_index"])
                dataset = train[index]
                ids = np.asarray(draw["old_ids"], dtype=np.int64)
                label = LABELS[index]
            rgb, target, guides, context = _device_batch(dataset.load_window(ids))
            rgb, target = rgb.float() / 255.0, target.float() / 255.0
            guides, context = guides.float(), context.float()
            model.train()
            optimizer.zero_grad(set_to_none=True)
            state = previous = None
            losses = []
            for frame in range(WINDOW):
                with torch.set_grad_enabled(frame >= BURN_IN), torch.autocast("cuda", dtype=torch.bfloat16):
                    prediction, state = model.forward_temporal(
                        rgb[:, frame], guides[:, frame], context[:, frame], state
                    )
                    error = prediction.float() - target[:, frame]
                    if frame >= BURN_IN:
                        losses.append(frame_objective(error, previous, pixel_only=True))
                    previous = error if frame >= BURN_IN else error.detach()
            loss = torch.stack(losses).mean()
            if not torch.isfinite(loss):
                raise ValueError(f"Nonfinite loss at {mode} step {step}")
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.head.parameters(), 1.0, error_if_nonfinite=True)
            parent_params = [p for p in model.parent.parameters() if p.grad is not None]
            if parent_params:
                torch.nn.utils.clip_grad_norm_(parent_params, 1.0, error_if_nonfinite=True)
            optimizer.step()
            draws[label] += 1
            if step == 1 or step % args.status_every == 0:
                _write_json(
                    output / "status.json",
                    {
                        "state": "training",
                        "mode": mode,
                        "step": step,
                        "steps": args.steps,
                        "loss": float(loss.detach()),
                        "draws": dict(draws),
                        "seconds": time.time() - started,
                        "gpu_peak_gib": torch.cuda.max_memory_allocated() / 2**30,
                        "test_used": False,
                    },
                )
                print(
                    json.dumps(
                        {
                            "state": "training",
                            "mode": mode,
                            "step": step,
                            "steps": args.steps,
                            "loss": float(loss.detach()),
                            "draws": dict(draws),
                        }
                    ),
                    flush=True,
                )
            if step % args.eval_every == 0 or step == args.steps:
                del rgb, target, guides, context, prediction, error, loss, state, previous, losses
                torch.cuda.empty_cache()
                evaluate(step)
        _write_json(
            output / "status.json",
            {
                "state": "complete",
                "mode": mode,
                "steps": args.steps,
                "ordinary_target_met": any(row["ordinary_target_met"] for row in history),
                "old_broad_gate": any(
                    row["step"] > 0
                    and row["old_cohorts_not_worse_than_protected"] is True
                    and row["old_temporal_not_worse_than_protected"] is True
                    for row in history
                ),
                "start_match_max_abs_difference": start_match_max_abs,
                "test_used": False,
                "seconds": time.time() - started,
            },
        )
        return {"run": run, "history": history, "status": _read_json(output / "status.json")}
    except Exception as exc:
        _write_json(
            output / "status.json",
            {"state": "failed", "mode": mode, "error": repr(exc), "test_used": False},
        )
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-checkpoint", type=Path, required=True)
    parser.add_argument("--old-cohort", action="append", type=Path, required=True)
    parser.add_argument("--new-cohort", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--steps", type=int, default=800)
    parser.add_argument("--eval-every", type=int, default=400)
    parser.add_argument("--status-every", type=int, default=50)
    parser.add_argument("--eval-batch", type=int, default=1)
    parser.add_argument("--new-probability", type=float, default=0.05)
    parser.add_argument("--seed", type=int, default=909)
    parser.add_argument("--learning-rate", type=float, default=5e-5)
    parser.add_argument("--parent-learning-rate", type=float, default=5e-6)
    args = parser.parse_args()
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is required")
    if len(args.old_cohort) != 6:
        raise ValueError("Recovery expects the six older cohorts")
    if args.steps < 1 or args.eval_every < 1 or args.status_every < 1 or args.eval_batch < 1:
        raise ValueError("Steps, intervals, and eval batch must be positive")
    if args.steps % args.eval_every:
        raise ValueError("Steps must be divisible by eval-every")
    if not 0.0 < args.new_probability < 1.0:
        raise ValueError("New probability must be between zero and one")
    if args.learning_rate <= 0 or args.parent_learning_rate <= 0:
        raise ValueError("Learning rates must be positive")

    args.base_checkpoint = args.base_checkpoint.resolve()
    args.new_cohort = args.new_cohort.resolve()
    args.output_root = args.output_root.resolve()
    old_roots = [root.resolve() for root in args.old_cohort]
    if not args.base_checkpoint.is_file() or not args.new_cohort.is_dir():
        raise FileNotFoundError("Starting checkpoint or new cohort is missing")
    if any(not root.is_dir() for root in old_roots):
        raise FileNotFoundError("An older cohort is missing")
    if args.output_root.exists():
        raise FileExistsError(args.output_root)

    roots = old_roots + [args.new_cohort]
    scratch._validate_cohorts(roots)
    base_sha = sha(args.base_checkpoint)
    base_payload, base_run, parent_path, protected_reference, base_validation = _check_base_contract(
        args.base_checkpoint, old_roots, args.new_cohort
    )
    train = [cohort(root, "train") for root in roots]
    validation = [cohort(root, "validation") for root in roots]
    schedule, schedule_meta = scratch._make_schedule(
        train[:6], train[-1], args.new_probability, args.seed, args.steps
    )

    args.output_root.mkdir(parents=True)
    schedule_path = args.output_root / "paired_schedule.json"
    _write_json(
        schedule_path,
        {
            "metadata": schedule_meta,
            "rows": schedule,
            "cohort_labels": LABELS,
            "cohort_complete_sha256": [sha(root / "complete.json") for root in roots],
            "test_used": False,
        },
    )
    schedule_sha = sha(schedule_path)
    schedule_meta = dict(schedule_meta, serialized_sha256=schedule_sha)
    _write_json(
        args.output_root / "experiment.json",
        {
            "architecture": "semantic_recovery_pair_v1",
            "base_checkpoint": str(args.base_checkpoint),
            "base_checkpoint_sha256": base_sha,
            "base_step": int(base_payload["step"]),
            "protected_checkpoint": str(Path(base_run["base_checkpoint"]).resolve()),
            "protected_checkpoint_sha256": base_run["base_checkpoint_sha256"],
            "parent": str(parent_path),
            "parent_sha256": sha(parent_path),
            "old_cohorts": [str(root) for root in old_roots],
            "new_cohort": str(args.new_cohort),
            "cohort_labels": LABELS,
            "steps": int(args.steps),
            "eval_every": int(args.eval_every),
            "eval_batch": int(args.eval_batch),
            "status_every": int(args.status_every),
            "seed": int(args.seed),
            "new_probability": float(args.new_probability),
            "learning_rate": float(args.learning_rate),
            "parent_learning_rate": float(args.parent_learning_rate),
            "schedule_sha256": schedule_sha,
            "schedule_metadata": schedule_meta,
            "source_sha256": _source_hashes(),
            "protected_reference_source": "base_checkpoint_payload.protected_reference_validation",
            "source_compatibility_mismatches": base_run.get("source_compatibility_mismatches", []),
            "test_used": False,
        },
    )
    _write_json(args.output_root / "status.json", {"state": "starting", "test_used": False})

    control = _train_arm(
        "control",
        args,
        args.base_checkpoint,
        base_sha,
        base_payload,
        base_run,
        parent_path,
        protected_reference,
        base_validation,
        roots,
        train,
        validation,
        schedule,
        schedule_meta,
        args.output_root / "control",
    )
    _write_json(
        args.output_root / "status.json",
        {"state": "control_complete", "control": control["status"], "test_used": False},
    )
    arm = _train_arm(
        "arm",
        args,
        args.base_checkpoint,
        base_sha,
        base_payload,
        base_run,
        parent_path,
        protected_reference,
        base_validation,
        roots,
        train,
        validation,
        schedule,
        schedule_meta,
        args.output_root / "arm",
    )
    _write_json(
        args.output_root / "status.json",
        {
            "state": "complete",
            "control": control["status"],
            "arm": arm["status"],
            "test_used": False,
            "seconds": time.time(),
        },
    )


if __name__ == "__main__":
    main()
