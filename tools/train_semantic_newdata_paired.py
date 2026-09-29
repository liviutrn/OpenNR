"""Paired semantic-joint continuation with a new strict temporal cohort.

The control and the new-data arm start from the exact same verified semantic
joint checkpoint and optimizer state.  Both receive the same old-cohort
windows.  The arm replaces a bounded fraction of those updates with windows
from the new strict full-eye-temporal pilot.  The pilot's validation and test
sequences are never sampled for training; the test split is never read.

This is a training experiment, not a promotion or runtime-deployment tool.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
import hashlib
import json
import math
import os
import time
from pathlib import Path

import numpy as np
import torch

from joint_parent_tone_model import load_joint_checkpoint
from prepare_conditioning_pilot import save, sha
from train_semantic_ablation import cohort as legacy_cohort
from train_spatial_tone import frame_objective
from train_temporal_student import _device_batch, evaluate_streaming


WINDOW = 8
BURN_IN = 2
BATCH = 1


class ShortTemporalCache:
    """Read a reset-qualified raw crop cache with streams shorter than 64 frames.

    The original strict cache loader was written for the older 64-frame pilot.
    The current full-eye capture intentionally uses bounded 16-frame bursts to
    avoid full-resolution backpressure.  This loader preserves each capture as
    its own stream and only samples windows that fit inside that stream; it
    never concatenates separate reset boundaries or fabricates frames.
    """

    def __init__(self, root: Path, split: str):
        self.root = Path(root).resolve()
        self.split = split
        if split == "train_validation":
            allowed_splits = {"train", "validation"}
        elif split in {"train", "validation", "test"}:
            allowed_splits = {split}
        else:
            raise ValueError(f"Unknown short temporal cache split {split!r}")

        self.complete = json.loads((self.root / "complete.json").read_text(encoding="utf-8"))
        if self.complete.get("source_type") != "opennr_raw_crop_capture":
            raise ValueError("ShortTemporalCache requires an OpenNR raw crop cache")
        if not self.complete.get("strict_initial_reset"):
            raise ValueError("Short temporal training requires a strict-initial-reset cache")
        if self.complete.get("temporal_training_allowed") is False:
            raise ValueError("Cache is marked spatial-only auxiliary data")
        crop_indices = self.complete.get("crop_indices")
        if isinstance(crop_indices, list) and len(crop_indices) != 1:
            raise ValueError("Short temporal training requires exactly one crop index")

        self.rows = json.loads((self.root / "rows.json").read_text(encoding="utf-8"))
        self.rgb = np.load(self.root / "rgb.npy", mmap_mode="r")
        self.guides = np.load(self.root / "guides.npy", mmap_mode="r")
        self.context = np.load(self.root / "context.npy", mmap_mode="r")
        if any(array.shape[0] != len(self.rows) for array in (self.rgb, self.guides, self.context)):
            raise ValueError("Short cache arrays do not match row manifest")

        grouped: dict[tuple[str, int], list[tuple[int, int]]] = defaultdict(list)
        for index, row in enumerate(self.rows):
            if row.get("split") in allowed_splits:
                grouped[(str(row["sequence_id"]), int(row["eye"]))].append(
                    (int(row["frame_id"]), index)
                )

        self.streams: dict[tuple[str, int], np.ndarray] = {}
        for key, values in grouped.items():
            values.sort()
            frames = [frame for frame, _ in values]
            if frames != list(range(1, len(frames) + 1)):
                raise ValueError(f"Non-contiguous short stream {key}: {frames[:3]}...{frames[-3:]}")
            if len(frames) < WINDOW:
                raise ValueError(f"Short stream {key} has only {len(frames)} frames; need {WINDOW}")
            first = self.rows[values[0][1]]
            if not bool(first.get("history_reset")):
                raise ValueError(f"Short stream {key} has no initial history reset")
            if any(bool(self.rows[index].get("history_reset")) for _, index in values[1:]):
                raise ValueError(f"Short stream {key} has a mid-stream reset")
            self.streams[key] = np.asarray([index for _, index in values], dtype=np.int64)
        if not self.streams:
            raise ValueError(f"No short temporal streams in split {split!r}")

    @property
    def sequence_ids(self) -> list[str]:
        return sorted({key[0] for key in self.streams})

    def sample_window(self, rng: np.random.Generator, batch: int, window: int):
        if window < 2:
            raise ValueError("Temporal window must be at least two frames")
        keys = list(self.streams)
        selected = [keys[int(rng.integers(len(keys)))] for _ in range(batch)]
        starts = [
            int(rng.integers(len(self.streams[key]) - window + 1))
            for key in selected
        ]
        indices = np.stack(
            [self.streams[key][start : start + window] for key, start in zip(selected, starts)]
        )
        return selected, starts, indices

    def load_window(self, indices: np.ndarray):
        return (
            np.array(self.rgb[indices, 0], copy=True),
            np.array(self.rgb[indices, 1], copy=True),
            np.array(self.guides[indices], copy=True),
            np.array(self.context[indices], copy=True),
        )

    def stream_batches(self, batch: int):
        keys = list(self.streams)
        for offset in range(0, len(keys), batch):
            selected = keys[offset : offset + batch]
            indices = np.stack([self.streams[key] for key in selected])
            yield selected, self.load_window(indices)


def cohort(path: Path, split: str):
    """Use the legacy exact-64 loader for controls and the bounded loader for new data."""

    metadata = json.loads((Path(path) / "complete.json").read_text(encoding="utf-8"))
    if metadata.get("source_type") == "opennr_raw_crop_capture":
        return ShortTemporalCache(path, split)
    return legacy_cohort(path, split)


def _read_json(path: Path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _write_json(path: Path, value) -> None:
    save(Path(path), value)


def _cache_identity(root: Path) -> dict:
    complete = _read_json(root / "complete.json")
    return {
        "path": str(root.resolve()),
        "complete_sha256": sha(root / "complete.json"),
        "schema": complete.get("schema"),
        "role": "strict_temporal_cache",
        "temporal_training_allowed": bool(complete.get("temporal_training_allowed", False)),
    }


def _make_schedule(old_train, new_train, old_probabilities, new_probability, seed, steps):
    """Make paired draws without consuming a model RNG or touching validation."""

    old_rng = np.random.default_rng(seed)
    mix_rng = np.random.default_rng(seed + 1)
    new_rng = np.random.default_rng(seed + 2)
    rows = []
    old_draws = [0 for _ in old_train]
    new_draws = 0
    digest = hashlib.sha256()
    for step in range(1, steps + 1):
        old_index = int(old_rng.choice(len(old_train), p=old_probabilities))
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
    return rows, {
        "seed": seed,
        "steps": steps,
        "window": WINDOW,
        "burn_in": BURN_IN,
        "old_probability": [float(v) for v in old_probabilities],
        "new_probability": float(new_probability),
        "old_draws": old_draws,
        "new_draws": new_draws,
        "digest_sha256": digest.hexdigest(),
    }


def _restore_optimizer(model, payload, restore_state=True):
    optimizer = torch.optim.AdamW(
        [
            {"params": [p for p in model.head.parameters() if p.requires_grad], "lr": payload["run"]["learning_rate"]},
            {"params": list(model.parent.parameters()), "lr": payload["run"]["parent_learning_rate"]},
        ],
        weight_decay=1e-4,
    )
    if restore_state:
        optimizer.load_state_dict(payload["optimizer"])
        for state in optimizer.state.values():
            for key, value in state.items():
                if torch.is_tensor(value):
                    state[key] = value.cuda(non_blocking=True)
        torch.set_rng_state(payload["torch_rng_state"].cpu())
        torch.cuda.set_rng_state_all([value.cpu() for value in payload["cuda_rng_state"]])
    return optimizer


def _base_run(payload: dict, old_roots: list[Path], new_root: Path, labels: list[str], probabilities: list[float],
              output: Path, base_checkpoint: Path, base_sha: str, schedule_meta: dict, new_probability: float,
              control_path: Path | None):
    old = payload["run"]
    roots = old_roots + [new_root]
    source_sha256 = dict(old["source_sha256"])
    source_sha256[Path(__file__).name] = sha(Path(__file__))
    run = {
        "architecture": "semantic_joint_parent_v1",
        "warm_head": old["warm_head"],
        "warm_head_sha256": old["warm_head_sha256"],
        "parent": old["parent"],
        "parent_sha256": old["parent_sha256"],
        "cohorts": [str(root.resolve()) for root in roots],
        "cohort_labels": labels,
        "cohort_complete_sha256": [sha(root / "complete.json") for root in roots],
        "probabilities": probabilities,
        "seed": old["seed"],
        "steps": int(payload["step"] + schedule_meta["steps"]),
        "learning_rate": old["learning_rate"],
        "parent_learning_rate": old["parent_learning_rate"],
        "eval_every": schedule_meta["eval_every"],
        "window": WINDOW,
        "burn_in": BURN_IN,
        "batch": BATCH,
        "loss": old["loss"],
        "training_sequences": [cache.sequence_ids for cache in []],
        "validation_sequences": [cache.sequence_ids for cache in []],
        "test_used": False,
        "pretrained_encoder": old["pretrained_encoder"],
        "head_parameters": old["head_parameters"],
        "joint_parent": True,
        "freeze_parent": False,
        "trainable_parent_parameters": old["trainable_parent_parameters"],
        "trainable_head_parameters": old["trainable_head_parameters"],
        "encoder_provenance": old["encoder_provenance"],
        "base_checkpoint": str(base_checkpoint.resolve()),
        "base_checkpoint_sha256": base_sha,
        "base_step": int(payload["step"]),
        "new_temporal_cohort": _cache_identity(new_root),
        "new_temporal_probability": float(new_probability),
        "schedule": schedule_meta,
        "source_sha256": source_sha256,
    }
    if control_path is not None:
        run["control"] = str(control_path.resolve())
    return run


def _checkpoint(path: Path, model, optimizer, run, step, metrics, baseline, history, schedule, draws, name):
    tmp = path / (name + ".tmp")
    payload = {
        "architecture": "semantic_joint_parent_v1",
        "head": model.head.state_dict(),
        "parent_model": model.parent.state_dict(),
        "run": run,
        "step": int(step),
        "validation": metrics,
        "optimizer": optimizer.state_dict(),
        "numpy_rng_state": np.random.default_rng(0).bit_generator.state,
        "torch_rng_state": torch.get_rng_state(),
        "cuda_rng_state": torch.cuda.get_rng_state_all(),
        "common_start_validation": baseline,
        "history": history,
        "schedule_position": int(step - run["base_step"]),
        "draws": draws,
    }
    torch.save(payload, tmp)
    tmp.replace(path / name)
    if name == "last.pt":
        snapshot = path / f"checkpoint_{step}.pt"
        if not snapshot.exists():
            try:
                os.link(path / name, snapshot)
            except OSError:
                snapshot.write_bytes((path / name).read_bytes())
        _write_json(path / f"checkpoint_{step}_identity.json", {"step": step, "sha256": sha(snapshot), "path": str(snapshot.resolve())})


def _train_one(mode: str, args, old_train, old_validation, new_train, new_validation, schedule, schedule_meta,
               base_checkpoint: Path, base_sha: str, old_roots: list[Path], new_root: Path, labels: list[str],
               old_probabilities: list[float], output: Path, control_path: Path | None,
               context_checkpoint: Path | None, context_sha: str | None):
    if output.exists():
        raise FileExistsError(output)
    output.mkdir(parents=True)
    model, base_payload = load_joint_checkpoint(base_checkpoint)
    if sha(base_checkpoint) != base_sha:
        raise ValueError("Base checkpoint changed during load")
    context_payload = None
    if context_checkpoint is not None:
        context_payload = torch.load(context_checkpoint, map_location="cpu", weights_only=False)
        if context_payload.get("architecture") != "semantic_context_pair_v1":
            raise ValueError("Context initializer must be a semantic_context_pair_v1 checkpoint")
        if context_sha is None or sha(context_checkpoint) != context_sha:
            raise ValueError("Context initializer changed during load")
        model.parent.load_state_dict(context_payload["parent_model"], strict=True)
        model.head.load_state_dict(context_payload["head"], strict=True)
    optimizer = _restore_optimizer(model, base_payload, restore_state=context_payload is None)
    start_step = int(base_payload["step"])
    end_step = start_step + schedule_meta["steps"]
    new_probability = schedule_meta["new_probability"] if mode == "arm" else 0.0
    probabilities = [float(v) * (1.0 - new_probability) for v in old_probabilities] + [float(new_probability)]
    run = _base_run(
        base_payload, old_roots, new_root, labels, probabilities, output, base_checkpoint, base_sha,
        dict(schedule_meta, eval_every=args.eval_every, mode=mode), new_probability, control_path,
    )
    run["training_sequences"] = [cache.sequence_ids for cache in old_train] + [new_train.sequence_ids]
    run["validation_sequences"] = [cache.sequence_ids for cache in old_validation] + [new_validation.sequence_ids]
    run["paired_control_schedule"] = True
    run["mode"] = mode
    run["training_test_used"] = False
    run["optimizer_restored"] = context_payload is None
    if context_checkpoint is not None:
        run["context_initializer"] = str(context_checkpoint.resolve())
        run["context_initializer_sha256"] = context_sha
        run["context_initializer_step"] = int(context_payload["step"])
    _write_json(output / "run.json", run)
    _write_json(output / "base_replay.json", {"base_checkpoint_sha256": base_sha, "base_step": start_step, "optimizer_restored": True, "test_used": False})

    validation = old_validation + [new_validation]
    train = old_train + [new_train]
    baseline = None
    history = []
    draws = {label: 0 for label in labels}
    started = time.time()

    def evaluate(step: int):
        nonlocal baseline
        metrics = {}
        for label, cache in zip(labels, validation):
            _write_json(output / "status.json", {"state": "evaluating", "mode": mode, "step": step, "cohort": label, "test_used": False})
            metrics[label] = evaluate_streaming(model, cache, batch=4)
        if baseline is None:
            baseline = metrics
            _write_json(output / "baseline_validation.json", {"step": step, "metrics": metrics, "test_used": False})
        ratios = {label: metrics[label]["mae"] / baseline[label]["mae"] for label in labels}
        temporal_ratios = {label: metrics[label]["temporal_delta_mae"] / baseline[label]["temporal_delta_mae"] for label in labels}
        entry = {
            "step": step,
            "validation": metrics,
            "mae_ratios": ratios,
            "temporal_ratios": temporal_ratios,
            "all_mae_improved": all(value < 1.0 for value in ratios.values()),
            "all_mae_not_worse": all(value <= 1.0 for value in ratios.values()),
            "old_mean_mae": float(np.mean([metrics[label]["mae"] for label in labels[:-1]])),
            "new_mae": metrics[labels[-1]]["mae"],
            "seconds": time.time() - started,
            "draws": dict(draws),
            "test_used": False,
        }
        history.append(entry)
        _write_json(output / "history.json", history)
        _write_json(output / "status.json", {"state": "checkpointing", "mode": mode, "step": step, "test_used": False})
        _checkpoint(output, model, optimizer, run, step, metrics, baseline, history, schedule, draws, "last.pt")
        print(json.dumps({"mode": mode, "step": step, "all_mae_improved": entry["all_mae_improved"], "mae": {label: metrics[label]["mae"] for label in labels}, "new_mae": entry["new_mae"]}), flush=True)

    try:
        evaluate(start_step)
        for offset, draw in enumerate(schedule, start=1):
            step = start_step + offset
            use_new = bool(draw["use_new"]) and mode == "arm"
            if use_new:
                dataset = new_train
                ids = np.asarray(draw["new_ids"], dtype=np.int64)
                label = labels[-1]
            else:
                index = int(draw["old_index"])
                dataset = old_train[index]
                ids = np.asarray(draw["old_ids"], dtype=np.int64)
                label = labels[index]
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
                        losses.append(frame_objective(error, previous))
                    previous = error if frame >= BURN_IN else error.detach()
            loss = torch.stack(losses).mean()
            if not torch.isfinite(loss):
                raise ValueError("Nonfinite loss")
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.head.parameters(), 1.0, error_if_nonfinite=True)
            torch.nn.utils.clip_grad_norm_(model.parent.parameters(), 1.0, error_if_nonfinite=True)
            optimizer.step()
            draws[label] += 1
            if step == start_step + 1 or step % args.status_every == 0:
                _write_json(output / "status.json", {"state": "training", "mode": mode, "step": step, "steps": end_step, "loss": float(loss.detach()), "draws": draws, "seconds": time.time() - started, "gpu_peak_gib": torch.cuda.max_memory_allocated() / 2**30, "test_used": False})
            if step % args.eval_every == 0 or step == end_step:
                evaluate(step)
        _write_json(output / "status.json", {"state": "complete", "mode": mode, "steps": end_step, "best_all_mae_improved": any(row["all_mae_improved"] for row in history), "test_used": False, "seconds": time.time() - started})
    except Exception as exc:
        _write_json(output / "status.json", {"state": "failed", "mode": mode, "error": repr(exc), "test_used": False})
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-checkpoint", type=Path, required=True)
    parser.add_argument("--old-cohort", action="append", type=Path, required=True)
    parser.add_argument("--new-cohort", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--steps", type=int, default=800)
    parser.add_argument("--eval-every", type=int, default=400)
    parser.add_argument("--status-every", type=int, default=25)
    parser.add_argument("--new-probability", type=float, default=0.15)
    parser.add_argument("--seed", type=int, default=909)
    parser.add_argument("--mode", choices=("control", "arm", "both"), default="both")
    parser.add_argument("--initialize-context", type=Path, help="Optional semantic_context_pair_v1 weights; uses a fresh temporal optimizer")
    args = parser.parse_args()
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is required")
    if args.steps < 1 or args.eval_every < 1 or args.status_every < 1:
        raise ValueError("Positive steps/evaluation/status intervals required")
    if not 0.0 < args.new_probability < 1.0:
        raise ValueError("New-data probability must be between zero and one")
    if len(args.old_cohort) != 6:
        raise ValueError("This paired pilot expects the six verified semantic cohorts")
    args.base_checkpoint = args.base_checkpoint.resolve()
    args.new_cohort = args.new_cohort.resolve()
    if args.initialize_context is not None:
        args.initialize_context = args.initialize_context.resolve()
    if not args.base_checkpoint.is_file() or not args.new_cohort.is_dir():
        raise FileNotFoundError("Base checkpoint or new cohort is missing")
    if args.initialize_context is not None and not args.initialize_context.is_file():
        raise FileNotFoundError(args.initialize_context)
    base_sha = sha(args.base_checkpoint)
    context_sha = sha(args.initialize_context) if args.initialize_context is not None else None
    old_roots = [root.resolve() for root in args.old_cohort]
    old_train = [cohort(root, "train") for root in old_roots]
    old_validation = [cohort(root, "validation") for root in old_roots]
    new_train = cohort(args.new_cohort, "train")
    new_validation = cohort(args.new_cohort, "validation")
    old_probabilities = np.asarray([0.4, 0.15, 0.1, 0.15, 0.1, 0.1], dtype=np.float64)
    schedule, schedule_meta = _make_schedule(old_train, new_train, old_probabilities, args.new_probability, args.seed, args.steps)
    schedule_meta["eval_every"] = args.eval_every
    schedule_meta["status_every"] = args.status_every
    schedule_meta["base_checkpoint_sha256"] = base_sha
    args.output_root.resolve().mkdir(parents=True, exist_ok=True)
    schedule_path = args.output_root.resolve() / "paired_schedule.json"
    _write_json(schedule_path, {"metadata": schedule_meta, "rows": schedule, "test_used": False})
    if sha(schedule_path) != sha(schedule_path):
        raise ValueError("Schedule changed while writing")
    labels = ["prior", "high_effect", "renderer_pilot", "fresh_session", "renderer_state", "new_pairs", "full_eye_pilot"]
    if args.mode in ("control", "both"):
        _train_one("control", args, old_train, old_validation, new_train, new_validation, schedule, schedule_meta,
                   args.base_checkpoint, base_sha, old_roots, args.new_cohort, labels, old_probabilities,
                   args.output_root.resolve() / "control", None, args.initialize_context, context_sha)
    if args.mode in ("arm", "both"):
        control_path = args.output_root.resolve() / "control"
        if not (control_path / "status.json").is_file() or _read_json(control_path / "status.json").get("state") != "complete":
            raise ValueError("Completed paired control is required before the arm")
        _train_one("arm", args, old_train, old_validation, new_train, new_validation, schedule, schedule_meta,
                   args.base_checkpoint, base_sha, old_roots, args.new_cohort, labels, old_probabilities,
                   args.output_root.resolve() / "arm", control_path, args.initialize_context, context_sha)


if __name__ == "__main__":
    main()
