"""Estimate whether the teacher gap is color-only or spatially irreducible.

This diagnostic never opens the test split.  It fits a global RGB affine map on
a deterministic subset of the training rows, measures that map on validation,
and computes an optimistic per-image affine oracle plus the high-frequency
share of the teacher-minus-input residual.  The latter is useful because a LUT
can change colors but cannot recover arbitrary spatial detail or geometry.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import torch
import torch.nn.functional as F

from .dataset import TinyPairedCache, sha256_file


def _select_indices(indices: np.ndarray, count: int, seed: int) -> np.ndarray:
    if count <= 0 or count >= len(indices):
        return indices.copy()
    rng = np.random.default_rng(seed)
    positions = np.sort(rng.choice(len(indices), size=count, replace=False))
    return indices[positions]


def _fit_global_affine(
    cache: TinyPairedCache,
    indices: np.ndarray,
    device: torch.device,
    batch_size: int,
) -> torch.Tensor:
    normal = torch.zeros((4, 4), dtype=torch.float64, device=device)
    cross = torch.zeros((4, 3), dtype=torch.float64, device=device)
    with torch.inference_mode():
        for start in range(0, len(indices), batch_size):
            inputs, targets = cache.load_batch(indices[start : start + batch_size], device)
            x = inputs.permute(0, 2, 3, 1).reshape(-1, 3).double()
            y = targets.permute(0, 2, 3, 1).reshape(-1, 3).double()
            ones = torch.ones((x.shape[0], 1), dtype=torch.float64, device=device)
            augmented = torch.cat((x, ones), dim=1)
            normal.add_(augmented.transpose(0, 1) @ augmented)
            cross.add_(augmented.transpose(0, 1) @ y)
    return torch.linalg.solve(normal, cross)


def _evaluate_affine(
    cache: TinyPairedCache,
    indices: np.ndarray,
    coefficient: torch.Tensor,
    device: torch.device,
    batch_size: int,
) -> dict[str, float | int]:
    abs_sum = 0.0
    square_sum = 0.0
    pixels = 0
    with torch.inference_mode():
        for start in range(0, len(indices), batch_size):
            inputs, targets = cache.load_batch(indices[start : start + batch_size], device)
            x = inputs.permute(0, 2, 3, 1).reshape(-1, 3).double()
            ones = torch.ones((x.shape[0], 1), dtype=torch.float64, device=device)
            prediction = torch.cat((x, ones), dim=1) @ coefficient
            y = targets.permute(0, 2, 3, 1).reshape(-1, 3).double()
            error = prediction - y
            abs_sum += float(error.abs().sum().item())
            square_sum += float(error.square().sum().item())
            pixels += int(error.numel())
    mae = abs_sum / max(pixels, 1)
    mse = square_sum / max(pixels, 1)
    return {"rows": len(indices), "mae": mae, "mse": mse, "psnr": 10.0 * math.log10(1.0 / max(mse, 1e-12))}


def _evaluate_per_image_affine_oracle(
    cache: TinyPairedCache,
    indices: np.ndarray,
    device: torch.device,
) -> dict[str, float | int]:
    abs_sum = 0.0
    square_sum = 0.0
    pixels = 0
    with torch.inference_mode():
        for absolute_index in indices.tolist():
            inputs, targets = cache.load_batch([int(absolute_index)], device)
            x = inputs[0].permute(1, 2, 0).reshape(-1, 3).double()
            y = targets[0].permute(1, 2, 0).reshape(-1, 3).double()
            ones = torch.ones((x.shape[0], 1), dtype=torch.float64, device=device)
            augmented = torch.cat((x, ones), dim=1)
            coefficient = torch.linalg.solve(augmented.transpose(0, 1) @ augmented, augmented.transpose(0, 1) @ y)
            error = augmented @ coefficient - y
            abs_sum += float(error.abs().sum().item())
            square_sum += float(error.square().sum().item())
            pixels += int(error.numel())
    mae = abs_sum / max(pixels, 1)
    mse = square_sum / max(pixels, 1)
    return {"rows": len(indices), "mae": mae, "mse": mse, "psnr": 10.0 * math.log10(1.0 / max(mse, 1e-12))}


def _residual_frequency_summary(
    cache: TinyPairedCache,
    indices: np.ndarray,
    device: torch.device,
    batch_size: int,
    pool_factor: int,
) -> dict[str, float | int]:
    residual_abs = 0.0
    high_abs = 0.0
    residual_square = 0.0
    high_square = 0.0
    pixels = 0
    with torch.inference_mode():
        for start in range(0, len(indices), batch_size):
            inputs, targets = cache.load_batch(indices[start : start + batch_size], device)
            residual = targets - inputs
            low = F.avg_pool2d(residual, kernel_size=pool_factor, stride=pool_factor)
            low = F.interpolate(low, size=residual.shape[-2:], mode="bilinear", align_corners=False)
            high = residual - low
            residual_abs += float(residual.abs().sum().item())
            high_abs += float(high.abs().sum().item())
            residual_square += float(residual.square().sum().item())
            high_square += float(high.square().sum().item())
            pixels += int(residual.numel())
    return {
        "rows": len(indices),
        "pool_factor": pool_factor,
        "residual_mae": residual_abs / max(pixels, 1),
        "high_frequency_residual_mae": high_abs / max(pixels, 1),
        "high_frequency_l1_fraction": high_abs / max(residual_abs, 1e-12),
        "residual_mse": residual_square / max(pixels, 1),
        "high_frequency_mse": high_square / max(pixels, 1),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--fit-rows", type=int, default=512)
    parser.add_argument("--eval-rows", type=int, default=256)
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--seed", type=int, default=812)
    parser.add_argument("--pool-factor", type=int, default=8)
    parser.add_argument("--device", default="cuda")
    args = parser.parse_args()

    if args.device == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("CUDA was requested but is not available")
    device = torch.device(args.device)
    manifest_path = args.manifest.resolve()
    manifest_hash = sha256_file(manifest_path)
    train = TinyPairedCache(manifest_path, "train")
    validation = TinyPairedCache(manifest_path, "validation")
    fit_indices = _select_indices(train.indices, args.fit_rows, args.seed)
    eval_indices = _select_indices(validation.indices, args.eval_rows, args.seed + 1)

    coefficient = _fit_global_affine(train, fit_indices, device, args.batch_size)
    global_affine = _evaluate_affine(validation, eval_indices, coefficient, device, args.batch_size)
    per_image = _evaluate_per_image_affine_oracle(validation, eval_indices, device)
    frequency = _residual_frequency_summary(validation, eval_indices, device, args.batch_size, args.pool_factor)
    result: dict[str, Any] = {
        "schema": "opennr-tiny-enhancement-capacity-diagnostic-v1",
        "manifest": str(manifest_path),
        "manifest_sha256": manifest_hash,
        "test_used_for_tuning": False,
        "fit_scope": {"split": "train", "rows": len(fit_indices), "seed": args.seed},
        "evaluation_scope": {"split": "validation", "rows": len(eval_indices), "seed": args.seed + 1},
        "global_rgb_affine": {
            "coefficient_rows_rgb_bias": coefficient.detach().cpu().tolist(),
            "validation": global_affine,
        },
        "per_image_rgb_affine_oracle": per_image,
        "teacher_minus_input_frequency": frequency,
        "notes": [
            "The per-image affine result is optimistic: it fits a separate RGB affine transform using the target pixels of each validation image.",
            "The frequency result measures residual structure a color-only LUT cannot directly reproduce.",
            "Only train and validation rows were opened; the test split was not read.",
        ],
    }
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(output), "global_affine": global_affine, "per_image_affine_oracle": per_image, "frequency": frequency}, indent=2))


if __name__ == "__main__":
    main()
