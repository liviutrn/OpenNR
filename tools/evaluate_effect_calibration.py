"""Evaluate a train-fitted scalar correction of a temporal student's effect.

The calibrated output is ``rgb + alpha * (prediction - rgb)``.  Alpha is fit
only on the supplied training caches with squared error, then the frozen value
is reported on the prior and new validation caches.  This is an offline
diagnostic: it does not alter the checkpoint or use the frozen test split.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

import numpy as np
import torch

from opennr_student import load_student
from train_student import atomic_json
from train_temporal_student import StrictTemporalCache, _device_batch


def _stream_effect_sums(model, cache: StrictTemporalCache, device: str, batch: int):
    """Return L2 fit sums and per-alpha absolute-error sums for one split."""

    model.eval()
    fit_num = 0.0
    fit_den = 0.0
    pixels = 0
    identity_abs = 0.0
    alphas = np.linspace(0.85, 1.15, 31, dtype=np.float64)
    alpha_abs = np.zeros_like(alphas)
    for _selected, arrays in cache.stream_batches(batch):
        rgb_np, target_np, guides_np, context_np = arrays
        rgb_all, target_all, guides_all, context_all = _device_batch(
            (rgb_np, target_np, guides_np, context_np), device
        )
        rgb_all = rgb_all.float() / 255.0
        target_all = target_all.float() / 255.0
        guides_all = guides_all.float()
        context_all = context_all.float()
        state = None
        with torch.no_grad():
            for frame in range(rgb_all.shape[1]):
                with torch.autocast(device_type="cuda", dtype=torch.bfloat16):
                    prediction, state = model.forward_temporal(
                        rgb_all[:, frame],
                        guides_all[:, frame],
                        context_all[:, frame],
                        state,
                    )
                prediction = prediction.float()
                rgb = rgb_all[:, frame]
                target = target_all[:, frame]
                effect = prediction - rgb
                target_effect = target - rgb
                fit_num += float((effect * target_effect).sum().item())
                fit_den += float(effect.square().sum().item())
                identity_abs += float((rgb - target).abs().sum().item())
                pixels += int(target.numel())
                for index, alpha in enumerate(alphas):
                    calibrated = (rgb + float(alpha) * effect).clamp(0.0, 1.0)
                    alpha_abs[index] += float((calibrated - target).abs().sum().item())
        del rgb_all, target_all, guides_all, context_all, state
    return {
        "fit_num": fit_num,
        "fit_den": fit_den,
        "pixels": pixels,
        "identity_mae": identity_abs / max(1, pixels),
        "grid": {
            f"{float(alpha):.3f}": float(value / max(1, pixels))
            for alpha, value in zip(alphas, alpha_abs)
        },
    }


def _evaluate_fixed_alpha(
    model, cache: StrictTemporalCache, device: str, batch: int, alpha: float
):
    model.eval()
    total_abs = 0.0
    identity_abs = 0.0
    pixels = 0
    with torch.no_grad():
        for _selected, arrays in cache.stream_batches(batch):
            rgb_np, target_np, guides_np, context_np = arrays
            rgb_all, target_all, guides_all, context_all = _device_batch(
                (rgb_np, target_np, guides_np, context_np), device
            )
            rgb_all = rgb_all.float() / 255.0
            target_all = target_all.float() / 255.0
            guides_all = guides_all.float()
            context_all = context_all.float()
            state = None
            for frame in range(rgb_all.shape[1]):
                with torch.autocast(device_type="cuda", dtype=torch.bfloat16):
                    prediction, state = model.forward_temporal(
                        rgb_all[:, frame],
                        guides_all[:, frame],
                        context_all[:, frame],
                        state,
                    )
                prediction = prediction.float()
                rgb = rgb_all[:, frame]
                target = target_all[:, frame]
                calibrated = (rgb + float(alpha) * (prediction - rgb)).clamp(0.0, 1.0)
                total_abs += float((calibrated - target).abs().sum().item())
                identity_abs += float((rgb - target).abs().sum().item())
                pixels += int(target.numel())
            del rgb_all, target_all, guides_all, context_all, state
    mae = total_abs / max(1, pixels)
    identity_mae = identity_abs / max(1, pixels)
    return {
        "alpha": float(alpha),
        "mae": mae,
        "identity_mae": identity_mae,
        "improvement_pct": 100.0 * (identity_mae - mae) / max(identity_mae, 1e-12),
        "pixels": pixels,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--train-cache", type=Path, action="append", required=True)
    parser.add_argument("--prior-cache", type=Path, required=True)
    parser.add_argument("--new-cache", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--batch", type=int, default=2)
    args = parser.parse_args()
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is required for effect calibration")
    if args.batch < 1:
        raise ValueError("batch must be positive")
    args.output.mkdir(parents=True, exist_ok=True)
    checkpoint_path = args.checkpoint.resolve()
    model, checkpoint = load_student(checkpoint_path, "cuda")
    train_sums = []
    fit_num = fit_den = 0.0
    for path in args.train_cache:
        cache = StrictTemporalCache(path, "train")
        sums = _stream_effect_sums(model, cache, "cuda", args.batch)
        train_sums.append(
            {
                "cache": str(Path(path).resolve()),
                "rows_sha256": cache.rows_sha256,
                "pixels": sums["pixels"],
                "identity_mae": sums["identity_mae"],
            }
        )
        fit_num += sums["fit_num"]
        fit_den += sums["fit_den"]
    alpha_l2 = float(np.clip(fit_num / max(fit_den, 1e-12), 0.85, 1.15))
    prior = StrictTemporalCache(args.prior_cache, "validation")
    new = StrictTemporalCache(args.new_cache, "validation")
    prior_grid = _stream_effect_sums(model, prior, "cuda", args.batch)
    new_grid = _stream_effect_sums(model, new, "cuda", args.batch)
    prior_fixed = _evaluate_fixed_alpha(model, prior, "cuda", args.batch, alpha_l2)
    new_fixed = _evaluate_fixed_alpha(model, new, "cuda", args.batch, alpha_l2)
    result = {
        "checkpoint": str(checkpoint_path),
        "checkpoint_sha256": hashlib.sha256(checkpoint_path.read_bytes()).hexdigest(),
        "step": int(checkpoint.get("step", -1)),
        "fit": {
            "train_caches": train_sums,
            "l2_alpha_unclamped": fit_num / max(fit_den, 1e-12),
            "alpha_l2_clamped": alpha_l2,
            "fit_num": fit_num,
            "fit_den": fit_den,
        },
        "validation": {
            "prior": {
                "cache": str(args.prior_cache.resolve()),
                "rows_sha256": prior.rows_sha256,
                "grid": prior_grid["grid"],
                "fixed_alpha": prior_fixed,
                "baseline_alpha_1": prior_grid["grid"]["1.000"],
            },
            "new": {
                "cache": str(args.new_cache.resolve()),
                "rows_sha256": new.rows_sha256,
                "grid": new_grid["grid"],
                "fixed_alpha": new_fixed,
                "baseline_alpha_1": new_grid["grid"]["1.000"],
            },
        },
        "scope": "Train-fitted scalar effect calibration; validation only; frozen test untouched.",
    }
    atomic_json(args.output / "result.json", result)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
