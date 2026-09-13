"""Validation/test metrics for spatial tiny enhancement models."""

from __future__ import annotations

import math
from collections import defaultdict
from typing import Any

import torch

from .dataset import TinyPairedCache


def _empty() -> dict[str, float]:
    return {
        "rows": 0.0,
        "pixels": 0.0,
        "abs_sum": 0.0,
        "sq_sum": 0.0,
        "input_abs_sum": 0.0,
        "input_sq_sum": 0.0,
        "delta_pixels": 0.0,
        "delta_abs_sum": 0.0,
        "input_delta_abs_sum": 0.0,
    }


def _finish(acc: dict[str, float]) -> dict[str, float | int | None]:
    pixels = max(acc["pixels"], 1.0)
    delta_pixels = acc["delta_pixels"]
    mae = acc["abs_sum"] / pixels
    input_mae = acc["input_abs_sum"] / pixels
    mse = acc["sq_sum"] / pixels
    input_mse = acc["input_sq_sum"] / pixels
    result: dict[str, float | int | None] = {
        "rows": int(acc["rows"]),
        "mae": mae,
        "mse": mse,
        "psnr": 10.0 * math.log10(1.0 / max(mse, 1e-12)),
        "input_mae": input_mae,
        "input_mse": input_mse,
        "input_psnr": 10.0 * math.log10(1.0 / max(input_mse, 1e-12)),
        "improvement_vs_input": input_mae - mae,
        "temporal_delta_mae": None,
        "input_temporal_delta_mae": None,
    }
    if delta_pixels:
        result["temporal_delta_mae"] = acc["delta_abs_sum"] / delta_pixels
        result["input_temporal_delta_mae"] = acc["input_delta_abs_sum"] / delta_pixels
    return result


def evaluate_model(
    model: torch.nn.Module,
    cache: TinyPairedCache,
    device: torch.device,
    batch_size: int = 2,
    use_autocast: bool = False,
) -> dict[str, Any]:
    """Evaluate one split without retaining predictions in host memory."""

    model.eval()
    total = _empty()
    cohorts: dict[str, dict[str, float]] = defaultdict(_empty)
    autocast_context = (
        torch.autocast(device_type="cuda", dtype=torch.float16)
        if use_autocast and device.type == "cuda"
        else torch.autocast(device_type=device.type, enabled=False)
    )
    with torch.inference_mode():
        for group in cache.groups:
            previous_pred: torch.Tensor | None = None
            previous_target: torch.Tensor | None = None
            previous_input: torch.Tensor | None = None
            cohort = str(group["cache_source"])
            group_indices = group["indices"]
            for start in range(0, len(group_indices), batch_size):
                ids = group_indices[start : start + batch_size]
                inputs, targets = cache.load_batch(ids, device)
                with autocast_context:
                    predictions = model(inputs)
                predictions = predictions.float()
                targets = targets.float()
                inputs = inputs.float()
                error = predictions - targets
                input_error = inputs - targets
                rows = float(inputs.shape[0])
                pixels = float(inputs.shape[0] * inputs.shape[1] * inputs.shape[2] * inputs.shape[3])
                values = {
                    "rows": rows,
                    "pixels": pixels,
                    "abs_sum": float(error.abs().sum().item()),
                    "sq_sum": float(error.square().sum().item()),
                    "input_abs_sum": float(input_error.abs().sum().item()),
                    "input_sq_sum": float(input_error.square().sum().item()),
                    "delta_pixels": 0.0,
                    "delta_abs_sum": 0.0,
                    "input_delta_abs_sum": 0.0,
                }
                for index in range(inputs.shape[0]):
                    if previous_pred is not None:
                        delta_pixels = float(inputs.shape[1] * inputs.shape[2] * inputs.shape[3])
                        values["delta_pixels"] += delta_pixels
                        values["delta_abs_sum"] += float(
                            (predictions[index] - previous_pred - targets[index] + previous_target).abs().sum().item()
                        )
                        values["input_delta_abs_sum"] += float(
                            (inputs[index] - previous_input - targets[index] + previous_target).abs().sum().item()
                        )
                    previous_pred = predictions[index].detach()
                    previous_target = targets[index].detach()
                    previous_input = inputs[index].detach()
                for key, value in values.items():
                    total[key] += value
                    cohorts[cohort][key] += value
    return {
        "split": cache.split,
        "rows": len(cache),
        "groups": len(cache.groups),
        "cohort_counts": cache.cohort_counts(),
        "overall": _finish(total),
        "cohorts": {name: _finish(value) for name, value in sorted(cohorts.items())},
        "evaluation": {
            "device": str(device),
            "batch_size": batch_size,
            "quality_precision": "fp16_autocast" if use_autocast else "fp32",
            "test_used_for_tuning": cache.split == "test",
        },
    }

