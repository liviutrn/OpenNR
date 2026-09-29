"""Paired identity-safe scratch versus protected-best semantic training.

This experiment answers an initialization question, not a deployment question:
can a freshly initialized OpenNR parent and semantic/tone head learn a better
ordinary-1x teacher match than the protected best semantic-joint checkpoint?

The two arms use the exact same audited cohorts, precomputed temporal-window
schedule, objective, optimizer hyperparameters, and validation protocol.  The
fine-tune arm loads the protected best weights but starts a fresh AdamW state.
The scratch arm constructs the same graph with random trainable OpenNR
weights, while retaining only the frozen, verified pretrained DINOv2 encoder.
All residual/output heads are zero-initialized by the architecture, so scratch
starts as an RGB identity rather than emitting uncontrolled random pixels.

This script never reads test streams and never changes a source checkpoint or
cache.  It is deliberately separate from the production/runtime trainers.
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

from capacity_student import CapacityConfig
from capacity_temporal_student import CapacityTemporalStyleContextStudent
from joint_parent_tone_model import JointParentToneModel, load_joint_checkpoint
from prepare_conditioning_pilot import save, sha
from semantic_tone_head import SemanticToneHead, encoder_provenance
from student_v2 import ReconstructionConfig
from temporal_student import TemporalConfig
from train_semantic_ablation import cohort
from train_spatial_tone import frame_objective
from train_temporal_student import _device_batch, evaluate_streaming


WINDOW = 8
BURN_IN = 2
BATCH = 1
OLD_PROBABILITIES = np.asarray([0.4, 0.15, 0.1, 0.15, 0.1, 0.1], dtype=np.float64)
LABELS = [
    "prior",
    "high_effect",
    "renderer_pilot",
    "fresh_session",
    "renderer_state",
    "new_pairs",
    "full_eye_pilot",
]


def _read_json(path: Path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _write_json(path: Path, value) -> None:
    save(Path(path), value)


def _source_hashes() -> dict[str, str]:
    names = (
        "train_semantic_scratch_vs_finetune.py",
        "joint_parent_tone_model.py",
        "semantic_tone_head.py",
        "stable_oversized_tone_head.py",
        "oversized_tone_head.py",
        "spatial_tone_head.py",
        "capacity_temporal_student.py",
        "capacity_student.py",
        "temporal_student.py",
        "student_v4.py",
        "student_v3.py",
        "student_v2.py",
        "opennr_student.py",
        "aligned_cohort.py",
        "train_semantic_ablation.py",
        "train_temporal_student.py",
        "train_spatial_tone.py",
    )
    return {name: sha(Path(__file__).with_name(name)) for name in names}


def _cache_identity(root: Path) -> dict:
    complete = _read_json(root / "complete.json")
    return {
        "path": str(root.resolve()),
        "complete_sha256": sha(root / "complete.json"),
        "rows_sha256": str(complete.get("rows_sha256", "")),
        "schema": complete.get("schema"),
        "temporal_training_allowed": bool(complete.get("temporal_training_allowed", False)),
        "strict_initial_reset": bool(complete.get("strict_initial_reset", False)),
    }


def _check_split_contract(root: Path) -> None:
    """Check sequence-disjoint train/validation/test metadata without loading test pixels."""

    # The six protected-best cohorts are aligned overlays: their arrays live
    # at the overlay root, while the authoritative row manifest remains in
    # the immutable source cache.  The clean-7 cohort is a strict cache and
    # keeps rows.json at its own root.  Read metadata from the right location
    # without touching any frozen-test arrays.
    complete = _read_json(root / "complete.json")
    rows_root = root
    if not (rows_root / "rows.json").is_file():
        source_cache = complete.get("source_cache")
        if not source_cache:
            raise FileNotFoundError(f"No row manifest for cohort {root}")
        rows_root = Path(source_cache).resolve()
    rows = _read_json(rows_root / "rows.json")
    by_split: dict[str, set[str]] = {}
    for row in rows:
        by_split.setdefault(str(row.get("split")), set()).add(str(row["sequence_id"]))
    train = by_split.get("train", set())
    validation = by_split.get("validation", set())
    test = by_split.get("test", set())
    if train & validation:
        raise ValueError(f"Train/validation sequence leakage in {root}")
    if (train | validation) & test:
        raise ValueError(f"Frozen-test sequence leakage in {root}")


def _validate_cohorts(roots: list[Path]) -> None:
    all_train: set[str] = set()
    all_validation: set[str] = set()
    for root in roots:
        _check_split_contract(root)
        train_cache = cohort(root, "train")
        validation_cache = cohort(root, "validation")
        train_ids = set(train_cache.sequence_ids)
        validation_ids = set(validation_cache.sequence_ids)
        if all_train & train_ids:
            raise ValueError(f"Repeated training sequence across cohorts in {root}")
        if all_validation & validation_ids:
            raise ValueError(f"Repeated validation sequence across cohorts in {root}")
        if (all_train | train_ids) & (all_validation | validation_ids):
            raise ValueError(f"Train/validation sequence collision across cohorts in {root}")
        all_train.update(train_ids)
        all_validation.update(validation_ids)


def _make_schedule(old_train, new_train, new_probability: float, seed: int, steps: int):
    """Precompute identical old/new windows for both initialization arms."""

    if not 0.0 < new_probability < 1.0:
        raise ValueError("New-data probability must be between zero and one")
    old_rng = np.random.default_rng(seed)
    mix_rng = np.random.default_rng(seed + 1)
    new_rng = np.random.default_rng(seed + 2)
    rows = []
    old_draws = [0 for _ in old_train]
    new_draws = 0
    digest = hashlib.sha256()
    probabilities = OLD_PROBABILITIES * (1.0 - new_probability)
    for step in range(1, steps + 1):
        old_index = int(old_rng.choice(len(old_train), p=probabilities / probabilities.sum()))
        _, _, old_ids = old_train[old_index].sample_window(old_rng, BATCH, WINDOW)
        use_new = bool(mix_rng.random() < new_probability)
        new_ids = None
        if use_new:
            _, _, new_ids = new_train.sample_window(new_rng, BATCH, WINDOW)
            new_draws += 1
        old_draws[old_index] += 1
        digest.update(np.asarray([step, old_index, int(use_new)], dtype="<i8").tobytes())
        digest.update(np.asarray(old_ids, dtype="<i8").tobytes())
        if new_ids is not None:
            digest.update(np.asarray(new_ids, dtype="<i8").tobytes())
        rows.append(
            {
                "step": step,
                "old_index": old_index,
                "old_ids": np.asarray(old_ids, dtype=np.int64).tolist(),
                "use_new": use_new,
                "new_ids": None if new_ids is None else np.asarray(new_ids, dtype=np.int64).tolist(),
            }
        )
    metadata = {
        "seed": int(seed),
        "steps": int(steps),
        "window": WINDOW,
        "burn_in": BURN_IN,
        "batch": BATCH,
        "old_probability": OLD_PROBABILITIES.tolist(),
        "new_probability": float(new_probability),
        "old_draws": old_draws,
        "new_draws": int(new_draws),
        "digest_sha256": digest.hexdigest(),
    }
    return rows, metadata


def _base_metadata(base_checkpoint: Path) -> tuple[dict, dict, Path]:
    """Read and verify the protected joint metadata, parent, and architecture."""

    payload = torch.load(base_checkpoint, map_location="cpu", weights_only=False)
    if payload.get("architecture") != "semantic_joint_parent_v1":
        raise ValueError("Expected semantic_joint_parent_v1 protected checkpoint")
    run = payload["run"]
    for name, digest in run.get("source_sha256", {}).items():
        source = Path(__file__).with_name(name)
        if not source.is_file() or sha(source) != digest:
            raise ValueError(f"Protected source changed: {name}")
    parent_path = Path(run["parent"]).resolve()
    if sha(parent_path) != run["parent_sha256"]:
        raise ValueError("Protected parent checkpoint changed")
    for root, digest in zip(run["cohorts"], run["cohort_complete_sha256"]):
        root_path = Path(root).resolve()
        if sha(root_path / "complete.json") != digest:
            raise ValueError(f"Protected cohort changed: {root_path}")
    for relative, digest in run["encoder_provenance"]["source_sha256"].items():
        source = Path(run["encoder_provenance"]["source"]) / relative
        if sha(source) != digest:
            raise ValueError(f"Protected encoder source changed: {relative}")
    parent_payload = torch.load(parent_path, map_location="cpu", weights_only=False)
    if parent_payload.get("architecture") != "context_v7_capacity_temporal":
        raise ValueError("Scratch requires the recorded context_v7_capacity_temporal parent")
    for key in ("base_config", "temporal_config", "capacity_config"):
        if key not in parent_payload:
            raise ValueError(f"Protected parent has no {key}")
    return payload, parent_payload, parent_path


def _new_model(parent_payload: dict, seed: int) -> JointParentToneModel:
    """Construct the exact graph with random trainable OpenNR weights."""

    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)
    config = ReconstructionConfig(**parent_payload["base_config"])
    temporal = TemporalConfig(**parent_payload["temporal_config"])
    capacity = CapacityConfig(**parent_payload["capacity_config"])
    parent = CapacityTemporalStyleContextStudent(config, temporal, capacity).cuda()
    # Only the DINO encoder is retained from the pretrained semantic setup.
    # The U-Net, projection, and affine head are newly initialized here.
    head = SemanticToneHead(pretrained=True).cuda()
    return JointParentToneModel(parent, head).eval()


def _fine_tune_model(base_checkpoint: Path, seed: int) -> JointParentToneModel:
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)
    model, _ = load_joint_checkpoint(base_checkpoint)
    model.parent.requires_grad_(True)
    return model.eval()


def _parameter_counts(model: JointParentToneModel) -> dict[str, int]:
    return {
        "parent_total": int(sum(p.numel() for p in model.parent.parameters())),
        "parent_trainable": int(sum(p.numel() for p in model.parent.parameters() if p.requires_grad)),
        "head_total": int(sum(p.numel() for p in model.head.parameters())),
        "head_trainable": int(sum(p.numel() for p in model.head.parameters() if p.requires_grad)),
        "encoder_frozen": int(sum(p.numel() for p in model.head.encoder.parameters())),
        "total_serialized": int(sum(p.numel() for p in model.parameters())),
    }


@torch.no_grad()
def _identity_check(model: JointParentToneModel) -> dict[str, float | bool]:
    """Check the advertised zero-output initialization on a deterministic batch."""

    torch.manual_seed(910)
    rgb = torch.rand(1, 3, 512, 512, device="cuda")
    guides = torch.rand(1, 5, 512, 512, device="cuda")
    context = torch.rand(1, 8, 96, 96, device="cuda")
    with torch.autocast("cuda", dtype=torch.bfloat16):
        prediction, state = model.forward_temporal(rgb, guides, context, None)
    difference = (prediction.float() - rgb).abs()
    max_error = float(difference.max().item())
    mean_error = float(difference.mean().item())
    return {
        "passed": bool(max_error <= 1e-7),
        "max_abs_error": max_error,
        "mean_abs_error": mean_error,
        "state_present": state is not None,
    }


def _optimizer(model: JointParentToneModel, learning_rate: float, parent_learning_rate: float):
    head_params = [p for p in model.head.parameters() if p.requires_grad]
    parent_params = [p for p in model.parent.parameters() if p.requires_grad]
    if not head_params or not parent_params:
        raise ValueError("Both semantic head and parent must have trainable parameters")
    return torch.optim.AdamW(
        [
            {"params": head_params, "lr": learning_rate},
            {"params": parent_params, "lr": parent_learning_rate},
        ],
        weight_decay=1e-4,
    )


def _run_metadata(
    mode: str,
    args,
    base_run: dict,
    base_checkpoint: Path,
    base_sha: str,
    parent_path: Path,
    old_roots: list[Path],
    new_root: Path,
    train,
    validation,
    schedule_meta: dict,
    output: Path,
    counts: dict[str, int],
    identity: dict,
) -> dict:
    roots = old_roots + [new_root]
    return {
        "architecture": "semantic_scratch_vs_finetune_v1",
        "mode": mode,
        "initialization": (
            "identity_safe_random_trainable_parent_and_head_with_frozen_pretrained_dino"
            if mode == "scratch"
            else "protected_best_weights_with_fresh_adamw"
        ),
        "base_checkpoint": str(base_checkpoint.resolve()),
        "base_checkpoint_sha256": base_sha,
        "base_step": int(torch.load(base_checkpoint, map_location="cpu", weights_only=False)["step"]),
        "parent": str(parent_path.resolve()),
        "parent_sha256": sha(parent_path),
        "base_architecture": base_run.get("architecture", "semantic_joint_parent_v1"),
        "base_config": base_run.get("base_config"),
        "temporal_config": base_run.get("temporal_config"),
        "capacity_config": base_run.get("capacity_config"),
        "cohorts": [str(root.resolve()) for root in roots],
        "cohort_labels": LABELS,
        "cohort_complete_sha256": [sha(root / "complete.json") for root in roots],
        "training_sequences": [cache.sequence_ids for cache in train],
        "validation_sequences": [cache.sequence_ids for cache in validation],
        "probabilities": (OLD_PROBABILITIES * (1.0 - args.new_probability)).tolist()
        + [float(args.new_probability)],
        "new_probability": float(args.new_probability),
        "seed": int(args.seed),
        "steps": int(args.steps),
        "learning_rate": float(args.learning_rate),
        "parent_learning_rate": float(args.parent_learning_rate),
        "eval_every": int(args.eval_every),
        "status_every": int(args.status_every),
        "window": WINDOW,
        "burn_in": BURN_IN,
        "batch": BATCH,
        "loss": "L1",
        "pixel_only": True,
        "pretrained_encoder": True,
        "encoder_provenance": encoder_provenance(),
        "parameter_counts": counts,
        "identity_check": identity,
        "schedule": schedule_meta,
        "schedule_sha256": schedule_meta["digest_sha256"],
        "source_sha256": _source_hashes(),
        "test_used": False,
        "output": str(output.resolve()),
        "protected_best_run": str(base_checkpoint.parent / "run.json"),
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
        "draws": dict(draws),
        "test_used": False,
    }
    tmp = output / (name + ".tmp")
    torch.save(payload, tmp)
    tmp.replace(output / name)
    if name == "last.pt":
        snapshot = output / f"checkpoint_{step}.pt"
        if not snapshot.exists():
            try:
                os.link(output / name, snapshot)
            except OSError:
                snapshot.write_bytes((output / name).read_bytes())
        _write_json(
            output / f"checkpoint_{step}_identity.json",
            {"step": step, "sha256": sha(snapshot), "path": str(snapshot.resolve())},
        )


def _train_one(
    mode: str,
    args,
    base_checkpoint: Path,
    base_sha: str,
    base_payload: dict,
    parent_payload: dict,
    parent_path: Path,
    old_roots: list[Path],
    new_root: Path,
    train,
    validation,
    schedule: list[dict],
    schedule_meta: dict,
    output: Path,
    protected_reference: dict | None,
) -> dict:
    if output.exists():
        raise FileExistsError(output)
    output.mkdir(parents=True)
    model = _new_model(parent_payload, args.seed) if mode == "scratch" else _fine_tune_model(base_checkpoint, args.seed)
    counts = _parameter_counts(model)
    identity = _identity_check(model) if mode == "scratch" else {"passed": None, "not_applicable": True}
    if mode == "scratch" and not identity["passed"]:
        raise ValueError(f"Scratch identity check failed: {identity}")
    base_run = {
        "base_config": parent_payload.get("base_config"),
        "temporal_config": parent_payload.get("temporal_config"),
        "capacity_config": parent_payload.get("capacity_config"),
        "architecture": base_payload.get("architecture"),
    }
    run = _run_metadata(
        mode,
        args,
        base_run,
        base_checkpoint,
        base_sha,
        parent_path,
        old_roots,
        new_root,
        train,
        validation,
        schedule_meta,
        output,
        counts,
        identity,
    )
    if protected_reference is not None:
        run["protected_reference_validation"] = protected_reference
        run["protected_reference_sha256"] = sha(args.reference_path)
    _write_json(output / "run.json", run)
    _write_json(output / "schedule_identity.json", {"metadata": schedule_meta, "test_used": False})

    optimizer = _optimizer(model, args.learning_rate, args.parent_learning_rate)
    history: list[dict] = []
    draws = {label: 0 for label in LABELS}
    baseline = None
    started = time.time()

    def evaluate(step: int) -> None:
        nonlocal baseline
        metrics = {}
        for label, cache in zip(LABELS, validation):
            _write_json(
                output / "status.json",
                {"state": "evaluating", "mode": mode, "step": step, "cohort": label, "test_used": False},
            )
            metrics[label] = evaluate_streaming(model, cache, batch=args.eval_batch)
        if baseline is None:
            baseline = metrics
            _write_json(output / "baseline_validation.json", {"step": step, "metrics": metrics, "test_used": False})
        protected = protected_reference or metrics
        relative_to_protected = {
            label: {
                "mae": metrics[label]["mae"] / protected[label]["mae"],
                "temporal_delta_mae": metrics[label]["temporal_delta_mae"]
                / max(protected[label]["temporal_delta_mae"], 1e-12),
            }
            for label in LABELS
        }
        relative_to_baseline = {
            label: {
                "mae": metrics[label]["mae"] / baseline[label]["mae"],
                "temporal_delta_mae": metrics[label]["temporal_delta_mae"]
                / max(baseline[label]["temporal_delta_mae"], 1e-12),
            }
            for label in LABELS
        }
        broad_mae_gate = None
        broad_temporal_gate = None
        if protected_reference is not None:
            broad_mae_gate = bool(
                all(metrics[label]["mae"] <= protected[label]["mae"] + 1e-9 for label in LABELS[:6])
            )
            broad_temporal_gate = bool(
                all(
                    metrics[label]["temporal_delta_mae"]
                    <= protected[label]["temporal_delta_mae"] + 1e-9
                    for label in LABELS[:6]
                )
            )
        old_metrics = [metrics[label]["mae"] for label in LABELS[:6]]
        old_protected = [protected[label]["mae"] for label in LABELS[:6]]
        entry = {
            "step": int(step),
            "validation": metrics,
            "relative_to_protected": relative_to_protected,
            "relative_to_baseline": relative_to_baseline,
            "ordinary_renderer_pilot_mae": metrics["renderer_pilot"]["mae"],
            "ordinary_target_met": bool(metrics["renderer_pilot"]["mae"] <= 0.007),
            "old_mean_mae": float(np.mean(old_metrics)),
            "protected_old_mean_mae": float(np.mean(old_protected)),
            "old_mean_ratio_to_protected": float(np.mean(old_metrics) / np.mean(old_protected)),
            "old_cohorts_not_worse_than_protected": broad_mae_gate,
            "old_temporal_not_worse_than_protected": broad_temporal_gate,
            "seconds": time.time() - started,
            "draws": dict(draws),
            "test_used": False,
        }
        history.append(entry)
        _write_json(output / "history.json", history)
        _write_json(output / "status.json", {"state": "checkpointing", "mode": mode, "step": step, "test_used": False})
        _checkpoint(output, model, optimizer, run, step, metrics, protected, history, schedule, draws, "last.pt")
        print(
            json.dumps(
                {
                    "mode": mode,
                    "step": step,
                    "ordinary_renderer_pilot_mae": entry["ordinary_renderer_pilot_mae"],
                    "old_mean_mae": entry["old_mean_mae"],
                    "old_mean_ratio_to_protected": entry["old_mean_ratio_to_protected"],
                    "ordinary_target_met": entry["ordinary_target_met"],
                    "old_cohorts_not_worse_than_protected": entry["old_cohorts_not_worse_than_protected"],
                    "mae": {label: metrics[label]["mae"] for label in LABELS},
                }
            ),
            flush=True,
        )

    try:
        evaluate(0)
        for offset, draw in enumerate(schedule, start=1):
            step = offset
            if draw["use_new"]:
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
                    pred, state = model.forward_temporal(rgb[:, frame], guides[:, frame], context[:, frame], state)
                    error = pred.float() - target[:, frame]
                    if frame >= BURN_IN:
                        # Pixel-only L1 matches the protected best's recorded objective.
                        losses.append(frame_objective(error, previous, pixel_only=True))
                    previous = error if frame >= BURN_IN else error.detach()
            loss = torch.stack(losses).mean()
            if not torch.isfinite(loss):
                raise ValueError(f"Nonfinite loss at {mode} step {step}")
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.head.parameters(), 1.0, error_if_nonfinite=True)
            torch.nn.utils.clip_grad_norm_(model.parent.parameters(), 1.0, error_if_nonfinite=True)
            optimizer.step()
            draws[label] += 1
            if step == 1 or step % args.status_every == 0:
                status = {
                    "state": "training",
                    "mode": mode,
                    "step": step,
                    "steps": args.steps,
                    "loss": float(loss.detach()),
                    "draws": dict(draws),
                    "seconds": time.time() - started,
                    "gpu_peak_gib": torch.cuda.max_memory_allocated() / 2**30,
                    "test_used": False,
                }
                _write_json(output / "status.json", status)
                print(json.dumps(status), flush=True)
            if step % args.eval_every == 0 or step == args.steps:
                # The last training window still owns references to its
                # autograd graph until Python rebinds those locals. Release
                # them before the large full-stream evaluator so cuDNN does
                # not see a fragmented/overcommitted workspace allocation.
                del rgb, target, guides, context, pred, error, loss, state, previous, losses
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
                "test_used": False,
                "seconds": time.time() - started,
            },
        )
        return run
    except Exception as exc:
        _write_json(output / "status.json", {"state": "failed", "mode": mode, "error": repr(exc), "test_used": False})
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-checkpoint", type=Path, required=True)
    parser.add_argument("--old-cohort", action="append", type=Path, required=True)
    parser.add_argument("--new-cohort", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--steps", type=int, default=1600)
    parser.add_argument("--eval-every", type=int, default=400)
    parser.add_argument("--status-every", type=int, default=50)
    parser.add_argument(
        "--eval-batch",
        type=int,
        default=1,
        help="Validation stream batch; one is the conservative setting for the large semantic head.",
    )
    parser.add_argument("--new-probability", type=float, default=0.15)
    parser.add_argument("--seed", type=int, default=909)
    parser.add_argument("--learning-rate", type=float, default=1e-4)
    parser.add_argument("--parent-learning-rate", type=float, default=1e-5)
    args = parser.parse_args()
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is required")
    if len(args.old_cohort) != 6:
        raise ValueError("The parity experiment expects the six protected-best cohorts")
    if args.steps < 1 or args.eval_every < 1 or args.status_every < 1 or args.eval_batch < 1:
        raise ValueError("Positive steps, evaluation interval, status interval, and eval batch are required")
    if args.steps % args.eval_every:
        raise ValueError("Steps must be divisible by eval-every for paired checkpoints")
    args.base_checkpoint = args.base_checkpoint.resolve()
    args.new_cohort = args.new_cohort.resolve()
    args.output_root = args.output_root.resolve()
    if not args.base_checkpoint.is_file() or not args.new_cohort.is_dir():
        raise FileNotFoundError("Protected checkpoint or new cohort is missing")
    if args.output_root.exists():
        raise FileExistsError(args.output_root)
    old_roots = [root.resolve() for root in args.old_cohort]
    if any(not root.is_dir() for root in old_roots):
        raise FileNotFoundError("An old cohort is missing")
    roots = old_roots + [args.new_cohort]
    _validate_cohorts(roots)
    base_sha = sha(args.base_checkpoint)
    base_payload, parent_payload, parent_path = _base_metadata(args.base_checkpoint)
    base_run = base_payload["run"]
    if list(map(str, old_roots)) != [str(Path(value).resolve()) for value in base_run["cohorts"]]:
        raise ValueError("Old cohort order/identity does not match the protected best")
    if float(args.learning_rate) <= 0 or float(args.parent_learning_rate) <= 0:
        raise ValueError("Learning rates must be positive")
    train = [cohort(root, "train") for root in roots]
    validation = [cohort(root, "validation") for root in roots]
    schedule, schedule_meta = _make_schedule(
        train[:6], train[-1], args.new_probability, args.seed, args.steps
    )
    schedule_path = args.output_root / "paired_schedule.json"
    args.output_root.mkdir(parents=True)
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
    _write_json(args.output_root / "experiment.json", {
        "architecture": "semantic_scratch_vs_finetune_v1",
        "protected_best": str(args.base_checkpoint),
        "protected_best_sha256": base_sha,
        "parent": str(parent_path),
        "parent_sha256": sha(parent_path),
        "old_cohorts": [str(root) for root in old_roots],
        "new_cohort": str(args.new_cohort),
        "schedule_sha256": schedule_sha,
        "schedule_metadata": schedule_meta,
        "steps": args.steps,
        "eval_every": args.eval_every,
        "seed": args.seed,
        "test_used": False,
        "source_sha256": _source_hashes(),
    })

    # The fine-tune arm is evaluated first to establish an independent replay
    # of the protected reference for the scratch arm's broad acceptance gates.
    finetune_dir = args.output_root / "finetune"
    scratch_dir = args.output_root / "scratch"
    _train_one(
        "finetune",
        args,
        args.base_checkpoint,
        base_sha,
        base_payload,
        parent_payload,
        parent_path,
        old_roots,
        args.new_cohort,
        train,
        validation,
        schedule,
        schedule_meta,
        finetune_dir,
        None,
    )
    finetune_history = _read_json(finetune_dir / "history.json")
    protected_reference = finetune_history[0]["validation"]
    args.reference_path = finetune_dir / "protected_reference_validation.json"
    _write_json(args.reference_path, {"metrics": protected_reference, "source": str(finetune_dir), "test_used": False})
    # Re-write the reference hash-bearing experiment record after the file exists.
    experiment = _read_json(args.output_root / "experiment.json")
    experiment["protected_reference_sha256"] = sha(args.reference_path)
    _write_json(args.output_root / "experiment.json", experiment)
    _train_one(
        "scratch",
        args,
        args.base_checkpoint,
        base_sha,
        base_payload,
        parent_payload,
        parent_path,
        old_roots,
        args.new_cohort,
        train,
        validation,
        schedule,
        schedule_meta,
        scratch_dir,
        protected_reference,
    )
    _write_json(args.output_root / "status.json", {
        "state": "complete",
        "finetune": _read_json(finetune_dir / "status.json"),
        "scratch": _read_json(scratch_dir / "status.json"),
        "test_used": False,
    })


if __name__ == "__main__":
    main()
