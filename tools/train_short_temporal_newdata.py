"""Run a bounded new-data-only diagnostic on reset-qualified short streams.

This is intentionally separate from the historical paired continuation.  The
old joint checkpoint records several cohort and parent paths that were removed
during storage triage, so this experiment reconstructs the exact parent from
the labeled recovery checkpoint and trains only on the current raw-capture
cache.  It never reads the held-out validation or test streams for updates.

The input streams remain the real 16-frame captures.  The trainer samples
8-frame windows that stay inside one sequence/eye stream and never joins reset
boundaries or fabricates a 64-frame clip.
"""

from __future__ import annotations

import argparse
import json
import math
import time
from pathlib import Path

import numpy as np
import torch

from joint_parent_tone_model import JointParentToneModel
from prepare_conditioning_pilot import save, sha
from semantic_tone_head import SemanticToneHead
from train_capacity_temporal_student import _load_parent
from train_semantic_newdata_paired import ShortTemporalCache, _restore_optimizer
from train_spatial_tone import frame_objective
from train_temporal_student import _device_batch, evaluate_streaming


WINDOW = 8
BURN_IN = 2
BATCH = 1


def load_recovered_joint(path: Path, device: str):
    payload = torch.load(path, map_location="cpu", weights_only=False)
    recovery = payload.get("run", {}).get("parent_recovery")
    if not recovery:
        raise ValueError("Checkpoint is not labeled as a recovered joint checkpoint")
    parent_path = Path(payload["run"]["parent"])
    parent, *_ = _load_parent(parent_path, device=device)
    parent.load_state_dict(payload["parent_model"], strict=True)
    head = SemanticToneHead(False).to(device)
    head.load_state_dict(payload["head"], strict=True)
    return JointParentToneModel(parent, head), payload


def checkpoint(path: Path, model, optimizer, run, step, validation, baseline, history):
    payload = {
        "architecture": "semantic_joint_parent_v1",
        "head": model.head.state_dict(),
        "parent_model": model.parent.state_dict(),
        "run": run,
        "step": int(step),
        "validation": validation,
        "optimizer": optimizer.state_dict(),
        "torch_rng_state": torch.get_rng_state(),
        "cuda_rng_state": torch.cuda.get_rng_state_all(),
        "baseline_validation": baseline,
        "history": history,
        "new_only_diagnostic": True,
        "test_used_for_tuning": False,
    }
    temporary = path / "last.pt.tmp"
    torch.save(payload, temporary)
    temporary.replace(path / "last.pt")


def evaluate_validation(model, cache, output: Path, step: int):
    save(output / "status.json", {"state": "evaluating", "step": step, "test_used_for_tuning": False})
    metrics = evaluate_streaming(model, cache, device="cuda", batch=4)
    save(output / f"validation_{step}.json", metrics)
    return metrics


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-checkpoint", type=Path, required=True)
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--steps", type=int, default=400)
    parser.add_argument("--eval-every", type=int, default=100)
    parser.add_argument("--status-every", type=int, default=25)
    parser.add_argument("--seed", type=int, default=20260910)
    args = parser.parse_args()

    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is required for the training diagnostic")
    if args.steps < 1 or args.eval_every < 1 or args.status_every < 1:
        raise ValueError("steps, eval-every, and status-every must be positive")

    base = args.base_checkpoint.resolve()
    cache_root = args.cache.resolve()
    output = args.output.resolve()
    if not base.is_file() or not cache_root.is_dir():
        raise FileNotFoundError("Base checkpoint or cache is missing")
    if output.exists():
        raise FileExistsError(output)
    output.mkdir(parents=True)

    base_sha = sha(base)
    complete_sha = sha(cache_root / "complete.json")
    train_cache = ShortTemporalCache(cache_root, "train")
    validation_cache = ShortTemporalCache(cache_root, "validation")
    test_cache = ShortTemporalCache(cache_root, "test")

    np_rng = np.random.default_rng(args.seed)
    model, base_payload = load_recovered_joint(base, "cuda")
    if sha(base) != base_sha:
        raise ValueError("Base checkpoint changed during load")
    model.train()
    optimizer = _restore_optimizer(model, base_payload, restore_state=True)

    run = {
        "architecture": "semantic_joint_parent_v1",
        "experiment": "semantic_full_eye_state_new_only_diagnostic_v1",
        "base_checkpoint": str(base),
        "base_checkpoint_sha256": base_sha,
        "base_step": int(base_payload["step"]),
        "parent_recovery": base_payload["run"].get("parent_recovery"),
        "cache": str(cache_root),
        "cache_complete_sha256": complete_sha,
        "train_sequences": train_cache.sequence_ids,
        "validation_sequences": validation_cache.sequence_ids,
        "test_sequences": test_cache.sequence_ids,
        "window": WINDOW,
        "burn_in": BURN_IN,
        "batch": BATCH,
        "steps": int(args.steps),
        "eval_every": int(args.eval_every),
        "status_every": int(args.status_every),
        "seed": int(args.seed),
        "learning_rate": float(base_payload["run"]["learning_rate"]),
        "parent_learning_rate": float(base_payload["run"]["parent_learning_rate"]),
        "optimizer_restored": True,
        "test_used_for_tuning": False,
        "input_contract": "real reset-qualified 16-frame streams; bounded 8-frame windows; no concatenation",
        "torch": torch.__version__,
        "cuda": torch.version.cuda,
        "gpu": torch.cuda.get_device_name(0),
    }
    save(output / "run.json", run)
    save(output / "base_replay.json", {"base_checkpoint_sha256": base_sha, "base_step": int(base_payload["step"]), "optimizer_restored": True, "test_used_for_tuning": False})

    start_step = int(base_payload["step"])
    end_step = start_step + args.steps
    history = []
    baseline = None
    best_mae = math.inf
    started = time.time()

    def evaluate(step: int):
        nonlocal baseline, best_mae
        metrics = evaluate_validation(model, validation_cache, output, step)
        if baseline is None:
            baseline = metrics
            save(output / "baseline_validation.json", {"step": step, "metrics": metrics, "test_used_for_tuning": False})
        entry = {
            "step": int(step),
            "validation": metrics,
            "mae_ratio_to_baseline": float(metrics["mae"] / baseline["mae"]),
            "temporal_ratio_to_baseline": float(metrics["temporal_delta_mae"] / baseline["temporal_delta_mae"]),
            "best_validation_so_far": bool(metrics["mae"] < best_mae),
            "seconds": time.time() - started,
            "test_used_for_tuning": False,
        }
        history.append(entry)
        if metrics["mae"] < best_mae:
            best_mae = metrics["mae"]
            temporary = output / "best_validation.pt.tmp"
            torch.save({
                "architecture": "semantic_joint_parent_v1",
                "head": model.head.state_dict(),
                "parent_model": model.parent.state_dict(),
                "run": run,
                "step": int(step),
                "validation": metrics,
                "baseline_validation": baseline,
                "test_used_for_tuning": False,
            }, temporary)
            temporary.replace(output / "best_validation.pt")
        save(output / "history.json", history)
        checkpoint(output, model, optimizer, run, step, metrics, baseline, history)
        print(json.dumps({"state": "validation", "step": step, "mae": metrics["mae"], "temporal_delta_mae": metrics["temporal_delta_mae"], "mae_ratio": entry["mae_ratio_to_baseline"]}), flush=True)

    try:
        evaluate(start_step)
        for offset in range(1, args.steps + 1):
            step = start_step + offset
            _, _, ids = train_cache.sample_window(np_rng, BATCH, WINDOW)
            rgb, target, guides, context = _device_batch(train_cache.load_window(ids), "cuda")
            rgb, target = rgb.float() / 255.0, target.float() / 255.0
            guides, context = guides.float(), context.float()
            model.train()
            optimizer.zero_grad(set_to_none=True)
            state = previous = None
            losses = []
            for frame in range(WINDOW):
                with torch.set_grad_enabled(frame >= BURN_IN), torch.autocast("cuda", dtype=torch.bfloat16):
                    prediction, state = model.forward_temporal(rgb[:, frame], guides[:, frame], context[:, frame], state)
                    error = prediction.float() - target[:, frame]
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
            if step == start_step + 1 or step % args.status_every == 0:
                save(output / "status.json", {"state": "training", "step": step, "steps": end_step, "loss": float(loss.detach()), "seconds": time.time() - started, "gpu_peak_gib": torch.cuda.max_memory_allocated() / 2**30, "test_used_for_tuning": False})
                print(json.dumps({"state": "training", "step": step, "loss": float(loss.detach()), "gpu_peak_gib": torch.cuda.max_memory_allocated() / 2**30}), flush=True)
            if step % args.eval_every == 0 or step == end_step:
                evaluate(step)

        model.eval()
        test_metrics = evaluate_streaming(model, test_cache, device="cuda", batch=4)
        save(output / "test_final.json", {"step": end_step, "metrics": test_metrics, "test_used_for_tuning": False})
        save(output / "status.json", {"state": "complete", "step": end_step, "best_validation_mae": best_mae, "test_used_for_tuning": False, "seconds": time.time() - started})
        print(json.dumps({"state": "complete", "step": end_step, "best_validation_mae": best_mae, "test_mae": test_metrics["mae"], "test_temporal_delta_mae": test_metrics["temporal_delta_mae"]}), flush=True)
    except Exception as exc:
        save(output / "status.json", {"state": "failed", "step": int(start_step), "error": repr(exc), "test_used_for_tuning": False})
        raise
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
