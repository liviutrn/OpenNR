"""Evaluate the optimizer-fps-dlss5 temporal idea on strict OpenNR captures.

This is an offline reference probe, not a runtime integration.  It models the
useful part of the public project as:

    native full pass -> residual = teacher - input
    skipped pass     -> input + reprojected residual

The reprojected residual uses the existing OpenNR cache contract: exact
Feature 18 motion vectors, current-to-previous motion, the audited positive
grid sign, and captured depth.  A small colour gate and a conservative
low-resolution residual fill mirror the public project's rejection/fill idea.

The tool deliberately does not train a model, replace a teacher capture, or
write into a vendor checkout.  It requires a strict temporal cache and reports
crop-scale results as a research proxy.  In particular, it must not be used to
claim full-eye VR readiness.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from dataclasses import dataclass
import json
import math
from pathlib import Path
import time
from typing import Any

import numpy as np
import torch
from torch.nn import functional as F


MOTION_NORMALIZATION = 128.0
VARIANTS = (
    "input_baseline",
    "native_full",
    "pure_reprojection",
    "guarded_reprojection",
    "guarded_fill",
)


def _json_default(value: Any) -> Any:
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value)
    if isinstance(value, np.ndarray):
        return value.tolist()
    raise TypeError(type(value).__name__)


def _write_json(path: Path, value: Any) -> None:
    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(
        json.dumps(value, indent=2, sort_keys=True, default=_json_default) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _device(value: str) -> torch.device:
    if value == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("CUDA was requested but is not available")
    return torch.device(value)


@dataclass(frozen=True)
class Stream:
    sequence_id: str
    eye: int
    indices: np.ndarray


class StrictCache:
    """Read-only view of the current strict temporal cache contract."""

    def __init__(self, root: Path, split: str) -> None:
        self.root = root.resolve()
        self.split = split
        complete_path = self.root / "complete.json"
        rows_path = self.root / "rows.json"
        if not complete_path.is_file() or not rows_path.is_file():
            raise FileNotFoundError(f"Not a materialized strict cache: {self.root}")
        self.complete = json.loads(complete_path.read_text(encoding="utf-8"))
        if self.complete.get("strict_initial_reset") is not True:
            raise ValueError("The optimizer probe requires strict_initial_reset=true")
        if self.complete.get("temporal_training_allowed") is not True:
            raise ValueError("The selected cache is not marked temporal_training_allowed")
        crop_indices = self.complete.get("crop_indices")
        if not isinstance(crop_indices, list) or len(crop_indices) != 1:
            raise ValueError("The optimizer probe requires exactly one crop index")

        self.rows = json.loads(rows_path.read_text(encoding="utf-8"))
        self.rgb = np.load(self.root / "rgb.npy", mmap_mode="r")
        self.guides = np.load(self.root / "guides.npy", mmap_mode="r")
        if self.rgb.ndim != 5 or self.rgb.shape[1] != 2 or self.rgb.shape[2] != 3:
            raise ValueError(f"Unexpected RGB array shape: {self.rgb.shape}")
        if self.guides.ndim != 4 or self.guides.shape[1] < 5:
            raise ValueError(f"Unexpected guide array shape: {self.guides.shape}")
        if self.rgb.shape[0] != len(self.rows) or self.guides.shape[0] != len(self.rows):
            raise ValueError("Cache arrays do not match rows.json")

        grouped: dict[tuple[str, int], list[tuple[int, int]]] = defaultdict(list)
        for index, row in enumerate(self.rows):
            if row.get("split") != split:
                continue
            if row.get("motion_vector_contract") != "exact_feature18_bound_resource":
                raise ValueError(
                    f"{row.get('sequence_id')}/{row.get('eye')}: non-Feature18 motion contract"
                )
            grouped[(str(row["sequence_id"]), int(row["eye"]))].append(
                (int(row["frame_id"]), index)
            )

        self.streams: dict[tuple[str, int], Stream] = {}
        for key, values in sorted(grouped.items()):
            values.sort()
            frame_ids = [frame_id for frame_id, _ in values]
            expected = list(range(1, len(frame_ids) + 1))
            if frame_ids != expected:
                raise ValueError(f"Non-contiguous stream {key}: {frame_ids[:4]}...")
            if len(frame_ids) < 2:
                raise ValueError(f"Stream {key} is too short for temporal reuse")
            first_row = self.rows[values[0][1]]
            if first_row.get("history_reset") is not True:
                raise ValueError(f"Stream {key} does not begin with a history reset")
            if first_row.get("history_reset_pair") not in ([True, True], None):
                raise ValueError(f"Stream {key} has an invalid initial reset pair")
            for frame_id, row_index in values[1:]:
                if self.rows[row_index].get("history_reset") is True:
                    raise ValueError(f"Stream {key} has a mid-stream history reset")
            self.streams[key] = Stream(
                sequence_id=key[0], eye=key[1], indices=np.asarray(
                    [row_index for _, row_index in values], dtype=np.int64
                )
            )
        if not self.streams:
            raise ValueError(f"No strict streams found for split {split!r}")

    @property
    def sequences(self) -> list[str]:
        return sorted({stream.sequence_id for stream in self.streams.values()})

    def stream(self, sequence_id: str, eye: int) -> Stream:
        try:
            return self.streams[(sequence_id, eye)]
        except KeyError as exc:
            raise ValueError(f"Missing stereo eye {eye} for sequence {sequence_id}") from exc


@dataclass
class Reference:
    base: torch.Tensor | None = None
    depth: torch.Tensor | None = None
    depth_valid: torch.Tensor | None = None
    residual: torch.Tensor | None = None
    accumulated_motion: torch.Tensor | None = None


def _base_grid(height: int, width: int, device: torch.device, dtype: torch.dtype) -> torch.Tensor:
    yy, xx = torch.meshgrid(
        torch.arange(height, device=device, dtype=dtype),
        torch.arange(width, device=device, dtype=dtype),
        indexing="ij",
    )
    return torch.stack(
        (
            (xx + 0.5) / float(width) * 2.0 - 1.0,
            (yy + 0.5) / float(height) * 2.0 - 1.0,
        ),
        dim=-1,
    )[None]


def _pixel_to_grid(displacement: torch.Tensor, height: int, width: int) -> torch.Tensor:
    """Convert [N,2,H,W] pixel displacement to an align_corners=False grid."""

    return torch.stack(
        (
            displacement[:, 0] * (2.0 / float(width)),
            displacement[:, 1] * (2.0 / float(height)),
        ),
        dim=-1,
    )


def _warp(
    source: torch.Tensor,
    grid: torch.Tensor,
    mode: str = "bilinear",
) -> torch.Tensor:
    return F.grid_sample(
        source,
        grid,
        mode=mode,
        padding_mode="border",
        align_corners=False,
    )


def _luma(value: torch.Tensor) -> torch.Tensor:
    return (
        value[:, 0:1] * 0.2126
        + value[:, 1:2] * 0.7152
        + value[:, 2:3] * 0.0722
    )


def _frame_inputs(
    cache: StrictCache,
    index: int,
    device: torch.device,
) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
    rgb = np.array(cache.rgb[index, 0], dtype=np.float32, copy=True) / 255.0
    teacher = np.array(cache.rgb[index, 1], dtype=np.float32, copy=True) / 255.0
    guides = np.array(cache.guides[index], dtype=np.float32, copy=True)
    return (
        torch.from_numpy(rgb).unsqueeze(0).to(device=device),
        torch.from_numpy(teacher).unsqueeze(0).to(device=device),
        torch.from_numpy(guides).unsqueeze(0).to(device=device),
    )


def _guide_fields(
    guides: torch.Tensor,
    height: int,
    width: int,
) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor, torch.Tensor]:
    """Upsample cache guides using the same conservative convention as the student."""

    guide_size = (height, width)
    up = F.interpolate(guides, size=guide_size, mode="bilinear", align_corners=False)
    motion = up[:, 1:3] * MOTION_NORMALIZATION
    depth = up[:, 0:1]
    depth_valid = F.interpolate(guides[:, 3:4], size=guide_size, mode="nearest") > 0.5
    motion_valid = F.interpolate(guides[:, 4:5], size=guide_size, mode="nearest") > 0.5
    return motion, depth, depth_valid, motion_valid


def _inside_grid(grid: torch.Tensor, height: int, width: int) -> torch.Tensor:
    # The normalized grid is for pixel centers.  Convert back to pixel-space
    # coordinates so the test agrees with the actual align_corners=False map.
    x = (grid[..., 0] + 1.0) * float(width) * 0.5 - 0.5
    y = (grid[..., 1] + 1.0) * float(height) * 0.5 - 0.5
    return (x >= 0.0) & (x < float(width)) & (y >= 0.0) & (y < float(height))


def _reprojected_outputs(
    base: torch.Tensor,
    reference: Reference,
    motion: torch.Tensor,
    depth: torch.Tensor,
    depth_valid: torch.Tensor,
    motion_valid: torch.Tensor,
    base_grid: torch.Tensor,
    depth_threshold: float,
    color_tolerance: float,
    resample: str,
    fill_kernel: int,
) -> tuple[dict[str, torch.Tensor], dict[str, int]]:
    if (
        reference.base is None
        or reference.depth is None
        or reference.depth_valid is None
        or reference.residual is None
        or reference.accumulated_motion is None
    ):
        raise ValueError("Reprojection requested before the first full reference frame")

    height, width = base.shape[-2:]
    motion_grid = base_grid + _pixel_to_grid(motion, height, width)
    accumulated = motion + _warp(reference.accumulated_motion, motion_grid)
    q_grid = base_grid + _pixel_to_grid(accumulated, height, width)
    inside = _inside_grid(q_grid, height, width)

    current_depth_valid = depth_valid[:, 0]
    current_motion_valid = motion_valid[:, 0]
    reference_depth = _warp(reference.depth, q_grid)
    reference_depth_valid = _warp(
        reference.depth_valid.float(), q_grid, mode="nearest"
    )[:, 0] > 0.5
    basic = inside & current_depth_valid & current_motion_valid & reference_depth_valid

    guarded = basic.clone()
    if depth_threshold > 0.0:
        denominator = torch.maximum(
            torch.maximum(depth[:, 0].abs(), reference_depth[:, 0].abs()),
            torch.full_like(depth[:, 0], 1e-6),
        )
        relative_depth_error = (depth[:, 0] - reference_depth[:, 0]).abs() / denominator
        guarded &= relative_depth_error <= depth_threshold
    if color_tolerance > 0.0:
        reference_color = _warp(reference.base, q_grid)
        current_luma = _luma(base)
        reference_luma = _luma(reference_color)
        denominator = torch.maximum(
            torch.maximum(current_luma, reference_luma),
            torch.full_like(current_luma, 1e-3),
        )
        relative_color_error = (current_luma - reference_luma).abs() / denominator
        guarded &= relative_color_error[:, 0] <= color_tolerance

    warped_residual = _warp(reference.residual, q_grid, mode=resample)
    zero = torch.zeros_like(warped_residual)
    pure_add = torch.where(basic[:, None], warped_residual, zero)
    guarded_add = torch.where(guarded[:, None], warped_residual, zero)

    if fill_kernel <= 0:
        raise ValueError("fill_kernel must be positive")
    if fill_kernel == 1:
        low_residual = reference.residual
    else:
        low_residual = F.avg_pool2d(
            reference.residual,
            kernel_size=fill_kernel,
            stride=fill_kernel,
            ceil_mode=True,
        )
    fill = _warp(low_residual, q_grid)
    current_luma = _luma(base).clamp_min(1e-3)
    fill_luma = _luma(fill)
    fill = base * (fill_luma / current_luma).clamp(0.25, 4.0)
    fill_add = torch.where(guarded[:, None], warped_residual, fill)

    diagnostics = {
        "in_bounds": int(inside.sum().item()),
        "basic_valid": int(basic.sum().item()),
        "guarded_valid": int(guarded.sum().item()),
        "pixels": int(inside.numel()),
    }
    outputs = {
        "pure_reprojection": (base + pure_add).clamp(0.0, 1.0),
        "guarded_reprojection": (base + guarded_add).clamp(0.0, 1.0),
        "guarded_fill": (base + fill_add).clamp(0.0, 1.0),
    }
    reference.accumulated_motion = accumulated.detach()
    return outputs, diagnostics


def _metric_bucket() -> dict[str, Any]:
    return {
        "all_abs": 0.0,
        "all_sq": 0.0,
        "all_pixels": 0,
        "skip_abs": 0.0,
        "skip_sq": 0.0,
        "skip_pixels": 0,
        "delta_abs": 0.0,
        "delta_pixels": 0,
        "skip_delta_abs": 0.0,
        "skip_delta_pixels": 0,
        "stereo_abs": 0.0,
        "stereo_pixels": 0,
        "skip_stereo_abs": 0.0,
        "skip_stereo_pixels": 0,
    }


def _add_error(
    bucket: dict[str, Any],
    output: torch.Tensor,
    target: torch.Tensor,
    skipped: bool,
    previous_output: torch.Tensor | None,
    previous_target: torch.Tensor | None,
) -> None:
    error = output - target
    pixel_count = int(target.numel())
    bucket["all_abs"] += float(error.abs().sum().item())
    bucket["all_sq"] += float(error.square().sum().item())
    bucket["all_pixels"] += pixel_count
    if skipped:
        bucket["skip_abs"] += float(error.abs().sum().item())
        bucket["skip_sq"] += float(error.square().sum().item())
        bucket["skip_pixels"] += pixel_count
    if previous_output is not None and previous_target is not None:
        delta_error = (output - previous_output) - (target - previous_target)
        delta_count = int(target.numel())
        bucket["delta_abs"] += float(delta_error.abs().sum().item())
        bucket["delta_pixels"] += delta_count
        if skipped:
            bucket["skip_delta_abs"] += float(delta_error.abs().sum().item())
            bucket["skip_delta_pixels"] += delta_count


def _add_stereo_error(
    bucket: dict[str, Any],
    output_pair: tuple[torch.Tensor, torch.Tensor],
    target_pair: tuple[torch.Tensor, torch.Tensor],
    skipped: bool,
) -> None:
    output = output_pair[0] - output_pair[1]
    target = target_pair[0] - target_pair[1]
    error = output - target
    pixel_count = int(target.numel())
    bucket["stereo_abs"] += float(error.abs().sum().item())
    bucket["stereo_pixels"] += pixel_count
    if skipped:
        bucket["skip_stereo_abs"] += float(error.abs().sum().item())
        bucket["skip_stereo_pixels"] += pixel_count


def _finalize_bucket(bucket: dict[str, Any], baseline: dict[str, Any] | None = None) -> dict[str, Any]:
    def mean(total: str, count: str) -> float:
        return float(bucket[total]) / max(1, int(bucket[count]))

    result = {
        "mae": mean("all_abs", "all_pixels"),
        "mse": mean("all_sq", "all_pixels"),
        "psnr": -10.0 * math.log10(max(mean("all_sq", "all_pixels"), 1e-12)),
        "skip_mae": mean("skip_abs", "skip_pixels"),
        "skip_mse": mean("skip_sq", "skip_pixels"),
        "temporal_delta_mae": mean("delta_abs", "delta_pixels"),
        "skip_temporal_delta_mae": mean("skip_delta_abs", "skip_delta_pixels"),
        "stereo_disagreement_mae": mean("stereo_abs", "stereo_pixels"),
        "skip_stereo_disagreement_mae": mean("skip_stereo_abs", "skip_stereo_pixels"),
        "pixels": int(bucket["all_pixels"]),
        "skip_pixels": int(bucket["skip_pixels"]),
        "delta_pixels": int(bucket["delta_pixels"]),
        "stereo_pixels": int(bucket["stereo_pixels"]),
        "skip_stereo_pixels": int(bucket["skip_stereo_pixels"]),
    }
    if baseline is not None:
        for metric in ("mae", "skip_mae", "temporal_delta_mae", "stereo_disagreement_mae"):
            base_value = float(baseline[metric])
            result[f"{metric}_improvement_pct"] = (
                100.0 * (base_value - result[metric]) / max(abs(base_value), 1e-12)
            )
    return result


def _evaluate_sequence(
    cache: StrictCache,
    sequence_id: str,
    cadence: int,
    device: torch.device,
    depth_threshold: float,
    color_tolerance: float,
    resample: str,
    fill_kernel: int,
) -> tuple[dict[str, dict[str, Any]], dict[str, int], int]:
    streams = {eye: cache.stream(sequence_id, eye) for eye in (0, 1)}
    lengths = {len(stream.indices) for stream in streams.values()}
    if len(lengths) != 1:
        raise ValueError(f"Stereo frame counts differ for {sequence_id}: {lengths}")
    frame_count = lengths.pop()
    height, width = cache.rgb.shape[-2:]
    base_grid = _base_grid(height, width, device, torch.float32)
    references = {eye: Reference() for eye in (0, 1)}
    previous_outputs: dict[str, dict[int, torch.Tensor | None]] = {
        variant: {0: None, 1: None} for variant in VARIANTS
    }
    previous_targets: dict[int, torch.Tensor | None] = {0: None, 1: None}
    buckets = {variant: _metric_bucket() for variant in VARIANTS}
    diagnostics = {"in_bounds": 0, "basic_valid": 0, "guarded_valid": 0, "pixels": 0}
    full_count = 0
    skip_count = 0

    for frame_offset in range(frame_count):
        is_full = frame_offset % cadence == 0
        full_count += int(is_full)
        skip_count += int(not is_full)
        outputs_by_variant: dict[str, dict[int, torch.Tensor]] = {
            variant: {} for variant in VARIANTS
        }
        targets: dict[int, torch.Tensor] = {}
        for eye in (0, 1):
            index = int(streams[eye].indices[frame_offset])
            base, teacher, guides = _frame_inputs(cache, index, device)
            targets[eye] = teacher
            outputs_by_variant["input_baseline"][eye] = base
            # The native-full arm is an oracle reference: it uses the captured
            # teacher on every frame and is not a timing measurement.
            outputs_by_variant["native_full"][eye] = teacher
            if is_full:
                outputs_by_variant["pure_reprojection"][eye] = teacher
                outputs_by_variant["guarded_reprojection"][eye] = teacher
                outputs_by_variant["guarded_fill"][eye] = teacher
                motion, depth, depth_valid, _ = _guide_fields(
                    guides, height, width
                )
                del motion
                references[eye] = Reference(
                    base=base.detach(),
                    depth=depth.detach(),
                    depth_valid=depth_valid.detach(),
                    residual=(teacher - base).detach(),
                    accumulated_motion=torch.zeros(
                        (1, 2, height, width), device=device, dtype=torch.float32
                    ),
                )
            else:
                motion, depth, depth_valid, motion_valid = _guide_fields(
                    guides, height, width
                )
                outputs, frame_diagnostics = _reprojected_outputs(
                    base,
                    references[eye],
                    motion,
                    depth,
                    depth_valid,
                    motion_valid,
                    base_grid,
                    depth_threshold,
                    color_tolerance,
                    resample,
                    fill_kernel,
                )
                for variant, output in outputs.items():
                    outputs_by_variant[variant][eye] = output
                for key, value in frame_diagnostics.items():
                    diagnostics[key] += value

        for variant in VARIANTS:
            for eye in (0, 1):
                _add_error(
                    buckets[variant],
                    outputs_by_variant[variant][eye],
                    targets[eye],
                    skipped=not is_full,
                    previous_output=previous_outputs[variant][eye],
                    previous_target=previous_targets[eye],
                )
            _add_stereo_error(
                buckets[variant],
                (outputs_by_variant[variant][0], outputs_by_variant[variant][1]),
                (targets[0], targets[1]),
                skipped=not is_full,
            )
        for variant in VARIANTS:
            for eye in (0, 1):
                previous_outputs[variant][eye] = outputs_by_variant[variant][eye].detach()
        for eye in (0, 1):
            previous_targets[eye] = targets[eye].detach()

    del base_grid, references, previous_outputs, previous_targets
    if device.type == "cuda":
        torch.cuda.empty_cache()
    return buckets, diagnostics, full_count + skip_count


def evaluate(
    cache: StrictCache,
    sequences: list[str],
    cadence: int,
    device: torch.device,
    depth_threshold: float,
    color_tolerance: float,
    resample: str,
    fill_kernel: int,
) -> dict[str, Any]:
    if cadence < 2:
        raise ValueError("cadence must be >= 2; cadence=1 is the native full-pass baseline")
    if resample not in {"bilinear", "bicubic"}:
        raise ValueError(f"Unsupported resample mode: {resample}")
    if not sequences:
        raise ValueError("No sequences selected")

    aggregate = {variant: _metric_bucket() for variant in VARIANTS}
    total_diagnostics = {"in_bounds": 0, "basic_valid": 0, "guarded_valid": 0, "pixels": 0}
    sequence_buckets: dict[str, dict[str, dict[str, Any]]] = {}
    total_frames = 0
    full_frames = 0
    skipped_frames = 0
    for sequence_id in sequences:
        buckets, diagnostics, frame_count = _evaluate_sequence(
            cache,
            sequence_id,
            cadence,
            device,
            depth_threshold,
            color_tolerance,
            resample,
            fill_kernel,
        )
        sequence_buckets[sequence_id] = {
            variant: _finalize_bucket(bucket) for variant, bucket in buckets.items()
        }
        for variant in VARIANTS:
            for key, value in buckets[variant].items():
                aggregate[variant][key] += value
        for key, value in diagnostics.items():
            total_diagnostics[key] += value
        total_frames += frame_count
        full_frames += (frame_count + cadence - 1) // cadence
        skipped_frames += frame_count - ((frame_count + cadence - 1) // cadence)

    baseline = _finalize_bucket(aggregate["input_baseline"])
    variants = {
        variant: _finalize_bucket(aggregate[variant], baseline=baseline)
        for variant in VARIANTS
    }
    return {
        "schema": "opennr-optimizer-temporal-reuse-evaluation-v1",
        "cache": str(cache.root),
        "cache_split": cache.split,
        "cache_complete": {
            "rows_sha256": cache.complete.get("rows_sha256"),
            "strict_initial_reset": cache.complete.get("strict_initial_reset"),
            "temporal_training_allowed": cache.complete.get("temporal_training_allowed"),
            "training_role": cache.complete.get("training_role"),
            "source_type": cache.complete.get("source_type"),
            "capture_signature": cache.complete.get("provenance", {}).get("capture_signature"),
        },
        "sequences": sequences,
        "sequence_count": len(sequences),
        "stereo_required": True,
        "frames_per_sequence": {sequence_id: int(sequence_buckets[sequence_id]["input_baseline"]["pixels"] // (2 * 3 * cache.rgb.shape[-2] * cache.rgb.shape[-1])) for sequence_id in sequences},
        "total_frames": total_frames,
        "full_frames": full_frames,
        "skipped_frames": skipped_frames,
        "cadence": cadence,
        "full_schedule": "frame_1_then_every_cadence_frame",
        "device": str(device),
        "reference_contract": {
            "motion_source": "exact Feature18-bound cache guide",
            "motion_direction": "current_to_previous",
            "motion_sign": "+1 in grid_sample(previous, base + motion)",
            "motion_normalization": "native color-pixel displacement / 128",
            "depth_gate": "relative absolute depth mismatch",
            "color_gate": "relative luma mismatch against reprojected reference input",
            "reprojection_filter": resample,
            "fill": "average-pooled residual, luma-scaled to current input chroma",
            "proxy_limitations": [
                "cache is a 512x512 crop with 128x128 guides, not a full-eye runtime surface",
                "bilinear guide upsampling is a cache-level proxy for typed GPU sampling",
                "depth/color gates are an offline approximation of the public HLSL path",
                "native_full is an oracle schedule using captured teacher output, not an FPS measurement",
            ],
        },
        "diagnostics": {
            **total_diagnostics,
            "in_bounds_fraction": total_diagnostics["in_bounds"] / max(1, total_diagnostics["pixels"]),
            "basic_valid_fraction": total_diagnostics["basic_valid"] / max(1, total_diagnostics["pixels"]),
            "guarded_valid_fraction": total_diagnostics["guarded_valid"] / max(1, total_diagnostics["pixels"]),
        },
        "variants": variants,
        "per_sequence": sequence_buckets,
        "test_used_for_tuning": False,
    }


def _self_test() -> None:
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    height = width = 16
    base_grid = _base_grid(height, width, device, torch.float32)
    base = torch.full((1, 3, height, width), 0.25, device=device)
    teacher = (base + 0.1).clamp(0.0, 1.0)
    guides = torch.zeros((1, 5, height, width), device=device)
    guides[:, 3:5] = 1.0
    motion, depth, depth_valid, motion_valid = _guide_fields(guides, height, width)
    reference = Reference(
        base=base,
        depth=depth,
        depth_valid=depth_valid,
        residual=teacher - base,
        accumulated_motion=torch.zeros((1, 2, height, width), device=device),
    )
    outputs, diagnostics = _reprojected_outputs(
        base,
        reference,
        motion,
        depth,
        depth_valid,
        motion_valid,
        base_grid,
        depth_threshold=0.05,
        color_tolerance=0.08,
        resample="bilinear",
        fill_kernel=4,
    )
    assert diagnostics["basic_valid"] == height * width
    assert diagnostics["guarded_valid"] == height * width
    expected = teacher.expand_as(outputs["guarded_reprojection"])
    assert torch.allclose(outputs["guarded_reprojection"], expected, atol=1e-6)
    assert torch.allclose(outputs["guarded_fill"], expected, atol=1e-6)
    print(f"self-test passed on {device}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", type=Path)
    parser.add_argument("--split", choices=("train", "validation", "test"), default="test")
    parser.add_argument("--cadence", type=int, default=2)
    parser.add_argument("--max-sequences", type=int)
    parser.add_argument("--device", default="cuda" if torch.cuda.is_available() else "cpu")
    parser.add_argument("--depth-threshold", type=float, default=0.05)
    parser.add_argument("--color-tolerance", type=float, default=0.08)
    parser.add_argument("--resample", choices=("bilinear", "bicubic"), default="bilinear")
    parser.add_argument("--fill-kernel", type=int, default=16)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        _self_test()
        if args.cache is None:
            return
    if args.cache is None:
        parser.error("--cache is required unless --self-test is used alone")
    if args.output is None:
        parser.error("--output is required for a cache evaluation")
    if args.output.exists() and not args.overwrite:
        raise FileExistsError(
            f"Output exists: {args.output}. Use a new dated path or --overwrite explicitly."
        )
    if args.cadence < 2:
        raise ValueError("cadence must be >= 2")
    if args.fill_kernel < 1:
        raise ValueError("fill-kernel must be >= 1")

    device = _device(args.device)
    cache = StrictCache(args.cache, args.split)
    sequences = cache.sequences
    if args.max_sequences is not None:
        if args.max_sequences < 1:
            raise ValueError("max-sequences must be positive")
        sequences = sequences[: args.max_sequences]
    started = time.time()
    result = evaluate(
        cache,
        sequences,
        args.cadence,
        device,
        args.depth_threshold,
        args.color_tolerance,
        args.resample,
        args.fill_kernel,
    )
    result["created_epoch"] = time.time()
    result["seconds"] = time.time() - started
    _write_json(args.output, result)
    print(json.dumps(result["variants"], indent=2, sort_keys=True))
    print(f"wrote {args.output.resolve()}")


if __name__ == "__main__":
    main()
