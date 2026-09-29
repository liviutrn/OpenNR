"""Matched temporal versus full-eye-context semantic continuation.

The six ordinary cohorts remain the temporal quality contract.  The arm
replaces a bounded fraction of its temporal updates with sequence-disjoint
periodic full-eye spatial anchors, using the real whole-eye RGB thumbnail in
the context channels.  The control consumes the same old-cohort schedule and
never sees the spatial anchors.  Frozen-test rows are never loaded.

This is an offline context-information experiment.  It does not make a
temporal or runtime claim about the spatial-only anchor cache.
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
from train_semantic_ablation import cohort
from train_semantic_context_pair import PatchSet, metric, spatial_loss
from train_spatial_tone import frame_objective
from train_temporal_student import _device_batch, evaluate_streaming


LABELS = [
    "prior",
    "high_effect",
    "renderer_pilot",
    "fresh_session",
    "renderer_state",
    "new_pairs",
]
OLD_PROBABILITIES = np.asarray([0.40, 0.15, 0.10, 0.15, 0.10, 0.10], dtype=np.float64)
WINDOW = 8
BURN_IN = 2


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _make_schedule(old_train, spatial_train: PatchSet, steps: int, seed: int, spatial_probability: float):
    """Precompute paired old/spatial draws without touching model RNG state."""

    if not 0.0 <= spatial_probability < 1.0:
        raise ValueError("spatial probability must be in [0, 1)")
    rng = np.random.default_rng(seed)
    rows = []
    digest = hashlib.sha256()
    old_draws = [0 for _ in old_train]
    spatial_draws = 0
    for step in range(1, steps + 1):
        old_index = int(rng.choice(len(old_train), p=OLD_PROBABILITIES))
        _, _, old_ids = old_train[old_index].sample_window(rng, 1, WINDOW)
        use_spatial = bool(rng.random() < spatial_probability)
        spatial_index = None
        if use_spatial:
            spatial_index = int(rng.integers(len(spatial_train)))
            spatial_draws += 1
        old_draws[old_index] += 1
        digest.update(np.asarray([step, old_index, int(use_spatial)], dtype="<i8").tobytes())
        digest.update(np.asarray(old_ids, dtype="<i8").tobytes())
        if spatial_index is not None:
            digest.update(np.asarray([spatial_index], dtype="<i8").tobytes())
        rows.append(
            {
                "step": step,
                "old_index": old_index,
                "old_ids": np.asarray(old_ids, dtype=np.int64).tolist(),
                "use_spatial": use_spatial,
                "spatial_index": spatial_index,
            }
        )
    metadata = {
        "seed": int(seed),
        "steps": int(steps),
        "window": WINDOW,
        "burn_in": BURN_IN,
        "old_probabilities": OLD_PROBABILITIES.tolist(),
        "spatial_probability": float(spatial_probability),
        "old_draws": old_draws,
        "spatial_draws": spatial_draws,
        "digest_sha256": digest.hexdigest(),
        "test_used": False,
    }
    return rows, metadata


def _tensor_spatial_batch(data: PatchSet, index: int, device: str = "cuda"):
    input_np, target_np, guide_np, context_np = data.batch([index], "full")
    value = torch.from_numpy(input_np).to(device, non_blocking=True).float() / 255.0
    target = torch.from_numpy(target_np).to(device, non_blocking=True).float() / 255.0
    guide = torch.from_numpy(guide_np).to(device, non_blocking=True).float()
    context = torch.from_numpy(context_np).to(device, non_blocking=True).float()
    return value, target, guide, context


def _build_run(base_payload: dict, base_checkpoint: Path, base_sha: str, old_roots, spatial_root: Path,
               spatial_meta: dict, schedule_meta: dict, output: Path, mode: str, spatial_probability: float):
    old = dict(base_payload["run"])
    run = dict(old)
    run.update(
        {
            "architecture": "semantic_joint_parent_v1",
            "base_checkpoint": str(base_checkpoint.resolve()),
            "base_checkpoint_sha256": base_sha,
            "base_step": int(base_payload["step"]),
            "cohorts": [str(root.resolve()) for root in old_roots],
            "cohort_labels": LABELS,
            "cohort_complete_sha256": [sha(root / "complete.json") for root in old_roots],
            "probabilities": OLD_PROBABILITIES.tolist(),
            "steps": int(base_payload["step"] + schedule_meta["steps"]),
            "eval_every": int(schedule_meta["eval_every"]),
            "loss": "temporal L1 + .5 pooled16 RGB L1 + .12 temporal error delta; full-eye anchors use RGB L1 + .5 pooled16",
            "training_sequences": [cache.sequence_ids for cache in []],
            "validation_sequences": [cache.sequence_ids for cache in []],
            "test_used": False,
            "mode": mode,
            "spatial_probability": float(spatial_probability if mode == "arm" else 0.0),
            "spatial_cache": str(spatial_root.resolve()),
            "spatial_cache_complete_sha256": sha(spatial_root / "complete.json"),
            "spatial_cache_rows_sha256": spatial_meta["rows_sha256"],
            "spatial_cache_patches_sha256": sha(spatial_root / "patches.json"),
            "paired_schedule": schedule_meta,
            "source_sha256": dict(old.get("source_sha256", {})),
        }
    )
    run["source_sha256"][Path(__file__).name] = sha(Path(__file__))
    run["training_sequences"] = [cache.sequence_ids for cache in []]
    run["validation_sequences"] = [cache.sequence_ids for cache in []]
    return run


def _train_one(mode: str, args, base_checkpoint: Path, base_sha: str, old_roots, old_train, old_validation,
               spatial_root: Path, spatial_meta: dict, spatial_train: PatchSet,
               spatial_validation: PatchSet, schedule, schedule_meta: dict,
               output: Path, spatial_probability: float):
    if output.exists():
        raise FileExistsError(output)
    output.mkdir(parents=True)
    model, base_payload = load_joint_checkpoint(base_checkpoint)
    if sha(base_checkpoint) != base_sha:
        raise ValueError("Base checkpoint changed during load")
    # The model loader starts in eval mode; a new optimizer is deliberately
    # avoided so the matched pair continues the exact candidate trajectory.
    optimizer = torch.optim.AdamW(
        [
            {"params": [p for p in model.head.parameters() if p.requires_grad],
             "lr": base_payload["run"]["learning_rate"]},
            {"params": list(model.parent.parameters()),
             "lr": base_payload["run"]["parent_learning_rate"]},
        ],
        weight_decay=1e-4,
    )
    optimizer.load_state_dict(base_payload["optimizer"])
    run = _build_run(
        base_payload,
        base_checkpoint,
        base_sha,
        old_roots,
        spatial_root,
        spatial_meta,
        dict(schedule_meta, eval_every=args.eval_every),
        output,
        mode,
        spatial_probability,
    )
    run["training_sequences"] = [cache.sequence_ids for cache in old_train]
    run["validation_sequences"] = [cache.sequence_ids for cache in old_validation]
    run["spatial_training_sequences"] = sorted(set(spatial_train.sequence))
    run["spatial_validation_sequences"] = sorted(set(spatial_validation.sequence))
    run["base_validation"] = base_payload["validation"]
    save(output / "run.json", run)
    save(output / "schedule_metadata.json", schedule_meta)

    history = []
    baseline_old = None
    baseline_spatial = None
    best_score = float("inf")
    started = time.time()
    old_draws = {label: 0 for label in LABELS}
    spatial_draws = 0

    def checkpoint(name: str, step: int, old_metrics: dict, spatial_metrics: dict, entry: dict):
        tmp = output / (name + ".tmp")
        torch.save(
            {
                "architecture": "semantic_joint_parent_v1",
                "head": model.head.state_dict(),
                "parent_model": model.parent.state_dict(),
                "run": run,
                "step": int(step),
                "validation": old_metrics,
                "context_validation": spatial_metrics,
                "context_history": entry,
                "optimizer": optimizer.state_dict(),
                "numpy_rng_state": np.random.default_rng(0).bit_generator.state,
                "torch_rng_state": torch.get_rng_state(),
                "cuda_rng_state": torch.cuda.get_rng_state_all(),
                "test_used": False,
            },
            tmp,
        )
        tmp.replace(output / name)

    def evaluate(step: int):
        nonlocal baseline_old, baseline_spatial, best_score
        old_metrics = {}
        for label, cache in zip(LABELS, old_validation):
            save(output / "status.json", {"state": "evaluating", "mode": mode, "step": step,
                                           "cohort": label, "test_used": False})
            old_metrics[label] = evaluate_streaming(model, cache, batch=4)
        save(output / "status.json", {"state": "evaluating", "mode": mode, "step": step,
                                       "cohort": "full_eye_spatial", "test_used": False})
        spatial_metrics = metric(model, spatial_validation, "full", args.spatial_batch, "cuda")
        if baseline_old is None:
            baseline_old = old_metrics
            baseline_spatial = spatial_metrics
            save(output / "baseline_validation.json", {
                "old": baseline_old,
                "full_eye_spatial": baseline_spatial,
                "test_used": False,
            })
        old_ratios = {label: old_metrics[label]["mae"] / baseline_old[label]["mae"] for label in LABELS}
        spatial_ratio = spatial_metrics["mae"] / baseline_spatial["mae"]
        old_improved = all(value < 1.0 for value in old_ratios.values())
        spatial_improved = spatial_ratio < 1.0
        eligible = old_improved and spatial_improved
        score = float((np.mean(list(old_ratios.values())) + spatial_ratio) / 2.0)
        entry = {
            "step": int(step),
            "validation": old_metrics,
            "full_eye_spatial_validation": spatial_metrics,
            "old_mae_ratios": old_ratios,
            "full_eye_spatial_mae_ratio": float(spatial_ratio),
            "all_old_cohorts_improved": old_improved,
            "full_eye_spatial_improved": spatial_improved,
            "all_context_gates": eligible,
            "score": score,
            "old_draws": dict(old_draws),
            "spatial_draws": int(spatial_draws),
            "seconds": time.time() - started,
            "test_used": False,
        }
        history.append(entry)
        save(output / "history.json", history)
        checkpoint("last.pt", step, old_metrics, spatial_metrics, entry)
        if eligible and score < best_score:
            best_score = score
            checkpoint("best_all_context.pt", step, old_metrics, spatial_metrics, entry)
        print(json.dumps({
            "mode": mode,
            "step": step,
            "all_old_cohorts_improved": old_improved,
            "full_eye_spatial_improved": spatial_improved,
            "mae": {label: old_metrics[label]["mae"] for label in LABELS},
            "full_eye_spatial_mae": spatial_metrics["mae"],
        }), flush=True)

    try:
        evaluate(0)
        for offset, draw in enumerate(schedule, start=1):
            step = int(base_payload["step"] + offset)
            use_spatial = bool(draw["use_spatial"]) and mode == "arm"
            if use_spatial:
                value, target, guide, context = _tensor_spatial_batch(spatial_train, int(draw["spatial_index"]))
                optimizer.zero_grad(set_to_none=True)
                model.train()
                with torch.autocast(device_type="cuda", dtype=torch.bfloat16):
                    prediction, _ = model.forward_temporal(value, guide, context, None)
                    loss = spatial_loss(prediction.float() - target)
                spatial_draws += 1
            else:
                index = int(draw["old_index"])
                ids = np.asarray(draw["old_ids"], dtype=np.int64)
                rgb, target, guides, context = _device_batch(old_train[index].load_window(ids))
                rgb, target = rgb.float() / 255.0, target.float() / 255.0
                guides, context = guides.float(), context.float()
                optimizer.zero_grad(set_to_none=True)
                model.train()
                state = None
                previous = None
                losses = []
                with torch.autocast(device_type="cuda", dtype=torch.bfloat16):
                    for frame in range(WINDOW):
                        prediction, state = model.forward_temporal(
                            rgb[:, frame], guides[:, frame], context[:, frame], state
                        )
                        error = prediction.float() - target[:, frame]
                        if frame >= BURN_IN:
                            losses.append(frame_objective(error, previous))
                        previous = error if frame >= BURN_IN else error.detach()
                loss = torch.stack(losses).mean()
                old_draws[LABELS[index]] += 1
            if not torch.isfinite(loss):
                raise ValueError(f"Nonfinite loss at step {step}")
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.head.parameters(), 1.0, error_if_nonfinite=True)
            torch.nn.utils.clip_grad_norm_(model.parent.parameters(), 1.0, error_if_nonfinite=True)
            optimizer.step()
            if step == base_payload["step"] + 1 or step % args.status_every == 0:
                save(output / "status.json", {
                    "state": "training",
                    "mode": mode,
                    "step": step,
                    "steps": base_payload["step"] + len(schedule),
                    "loss": float(loss.detach()),
                    "old_draws": dict(old_draws),
                    "spatial_draws": int(spatial_draws),
                    "seconds": time.time() - started,
                    "gpu_peak_gib": torch.cuda.max_memory_allocated() / 2**30,
                    "test_used": False,
                })
            if offset % args.eval_every == 0 or offset == len(schedule):
                evaluate(step)
        save(output / "status.json", {
            "state": "complete",
            "mode": mode,
            "steps": base_payload["step"] + len(schedule),
            "best_score": None if best_score == float("inf") else best_score,
            "test_used": False,
            "seconds": time.time() - started,
        })
    except Exception as exc:
        save(output / "status.json", {"state": "failed", "mode": mode, "error": repr(exc), "test_used": False})
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-checkpoint", type=Path, required=True)
    parser.add_argument("--old-cohort", action="append", type=Path, required=True)
    parser.add_argument("--spatial-cache", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--steps", type=int, default=800)
    parser.add_argument("--eval-every", type=int, default=400)
    parser.add_argument("--status-every", type=int, default=25)
    parser.add_argument("--spatial-probability", type=float, default=0.10)
    parser.add_argument("--spatial-batch", type=int, default=1)
    parser.add_argument("--seed", type=int, default=911)
    args = parser.parse_args()
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is required")
    if len(args.old_cohort) != 6:
        raise ValueError("Exactly six old cohorts are required")
    if args.steps < 1 or args.eval_every < 1 or args.status_every < 1 or args.spatial_batch < 1:
        raise ValueError("Positive steps/evaluation/status/batch required")
    if not 0.0 <= args.spatial_probability < 1.0:
        raise ValueError("Spatial probability must be in [0, 1)")
    args.base_checkpoint = args.base_checkpoint.resolve()
    args.spatial_cache = args.spatial_cache.resolve()
    args.output_root = args.output_root.resolve()
    if args.output_root.exists():
        raise FileExistsError(args.output_root)
    if not args.base_checkpoint.is_file() or not args.spatial_cache.is_dir():
        raise FileNotFoundError("Base checkpoint or spatial cache missing")
    base_sha = sha(args.base_checkpoint)
    base_payload = torch.load(args.base_checkpoint, map_location="cpu", weights_only=False)
    if base_payload.get("architecture") != "semantic_joint_parent_v1":
        raise ValueError("Base must be a semantic joint-parent checkpoint")
    if int(base_payload.get("step", 0)) < 1:
        raise ValueError("Base checkpoint must be trained")
    old_roots = [root.resolve() for root in args.old_cohort]
    old_train = [cohort(root, "train") for root in old_roots]
    old_validation = [cohort(root, "validation") for root in old_roots]
    spatial_meta = _read_json(args.spatial_cache / "complete.json")
    if spatial_meta.get("temporal_training_allowed", True):
        raise ValueError("The spatial cache must explicitly prohibit temporal training")
    patches = _read_json(args.spatial_cache / "patches.json")
    spatial_train = PatchSet(args.spatial_cache, patches, "train")
    spatial_validation = PatchSet(args.spatial_cache, patches, "validation")
    if set(spatial_train.sequence) & set(spatial_validation.sequence):
        raise ValueError("Spatial train/validation sequence leakage")
    torch.set_num_threads(4)
    torch.backends.cudnn.benchmark = False
    torch.manual_seed(args.seed)
    torch.cuda.manual_seed_all(args.seed)
    schedule, schedule_meta = _make_schedule(
        old_train, spatial_train, args.steps, args.seed, args.spatial_probability
    )
    args.output_root.mkdir(parents=True)
    schedule_meta["eval_every"] = args.eval_every
    schedule_meta["status_every"] = args.status_every
    schedule_meta["base_checkpoint_sha256"] = base_sha
    save(args.output_root / "paired_schedule.json", {"metadata": schedule_meta, "rows": schedule, "test_used": False})
    _train_one(
        "control",
        args,
        args.base_checkpoint,
        base_sha,
        old_roots,
        old_train,
        old_validation,
        args.spatial_cache,
        spatial_meta,
        spatial_train,
        spatial_validation,
        schedule,
        schedule_meta,
        args.output_root / "control",
        args.spatial_probability,
    )
    _train_one(
        "arm",
        args,
        args.base_checkpoint,
        base_sha,
        old_roots,
        old_train,
        old_validation,
        args.spatial_cache,
        spatial_meta,
        spatial_train,
        spatial_validation,
        schedule,
        schedule_meta,
        args.output_root / "arm",
        args.spatial_probability,
    )
    save(args.output_root / "status.json", {"state": "complete", "steps": args.steps, "test_used": False})


if __name__ == "__main__":
    main()
