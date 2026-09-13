"""Matched direct-RGB versus target-residual training on an immutable view.

The two arms use one serialized schedule, one seed, identical temporal windows,
optimizer, learning-rate schedule, crop size, and validation cadence.  The
direct arm learns the existing current model's output against ``T``.  The
residual arm copies the current protected head body, replaces its logical
output with a zero-initialized three-channel residual head, and delivers::

    P = clamp(B + R_hat, 0, 1)

where ``B`` is the captured pre-DLSS5/base RGB.  Its first 200 updates train
only the new residual output; the copied head body and causal parent are then
unfrozen.  Test rows are loaded by neither training nor validation in this
script.  A separate post-selection evaluator is required before making any
test-set or runtime claim.

This tool is deliberately separate from the production Feature-18 route.  It
writes only to a new research output directory and verifies the residual-view
manifest plus the source-array hashes before touching CUDA.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
import hashlib
import json
import math
import os
from pathlib import Path
import time
from typing import Any

import numpy as np
import torch
from torch import nn
from torch.nn import functional as F

from joint_parent_tone_model import JointParentToneModel, load_joint_checkpoint
from prepare_conditioning_pilot import sha
from semantic_tone_head import SemanticToneHead, encoder_provenance
from train_spatial_tone import frame_objective


WINDOW = 8
BURN_IN = 2
BATCH = 1
WARMUP_STEPS = 200
MIN_LR_FACTOR = 0.20
HEAD_LR = 1e-4
PARENT_LR = 1e-5
WEIGHT_DECAY = 1e-4
EXPECTED_PROTECTED_SHA256 = (
    "40C214A9C0BC214C6E1366872E6D9270BFE7C00D63797AEFB6B3896865C15756"
)
DEFAULT_PROTECTED = Path(
    r"C:\OpenNR\Training\semantic_pixel_l1_pair_20260909\joint\best_all_cohorts.pt"
)
DEFAULT_RUNTIME_CLONE = Path(
    r"C:\OpenNR\Training\recovery\semantic_full_eye_state_short_20260910\recovered_best_all_cohorts.pt"
)


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(
        json.dumps(value, indent=2, sort_keys=True, default=_json_default) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _json_default(value: Any):
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value)
    if isinstance(value, np.ndarray):
        return value.tolist()
    raise TypeError(type(value).__name__)


def _sha256_file(path: Path, chunk_bytes: int = 16 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(chunk_bytes)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _stable_json_sha(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), default=_json_default).encode()
    ).hexdigest()


def _state_digest(state: dict[str, torch.Tensor]) -> str:
    digest = hashlib.sha256()
    for key in sorted(state):
        tensor = state[key].detach().cpu().contiguous()
        digest.update(key.encode("utf-8"))
        digest.update(str(tensor.dtype).encode("ascii"))
        digest.update(np.asarray(tensor.shape, dtype="<i8").tobytes())
        digest.update(tensor.view(torch.uint8).numpy().tobytes())
    return digest.hexdigest()


def _verify_checkpoint_identity(protected: Path, runtime: Path) -> dict[str, Any]:
    if not protected.is_file():
        raise FileNotFoundError(protected)
    if not runtime.is_file():
        raise FileNotFoundError(runtime)
    protected_sha = _sha256_file(protected)
    runtime_sha = _sha256_file(runtime)
    if protected_sha.lower() != EXPECTED_PROTECTED_SHA256.lower():
        raise ValueError(
            f"Protected checkpoint SHA changed: {protected_sha}; "
            f"expected {EXPECTED_PROTECTED_SHA256}"
        )
    protected_payload = torch.load(protected, map_location="cpu", weights_only=False)
    protected_head = _state_digest(protected_payload["head"])
    protected_parent = _state_digest(protected_payload["parent_model"])
    del protected_payload
    runtime_payload = torch.load(runtime, map_location="cpu", weights_only=False)
    runtime_head = _state_digest(runtime_payload["head"])
    runtime_parent = _state_digest(runtime_payload["parent_model"])
    if protected_head != runtime_head or protected_parent != runtime_parent:
        raise ValueError(
            "Recovered runtime clone is not an exact tensor clone of the protected checkpoint"
        )
    return {
        "protected_path": str(protected.resolve()),
        "protected_sha256": protected_sha,
        "runtime_clone_path": str(runtime.resolve()),
        "runtime_clone_sha256": runtime_sha,
        "head_tensor_digest": protected_head,
        "parent_tensor_digest": protected_parent,
        "head_exact_match": True,
        "parent_exact_match": True,
        "verified_before_training": True,
    }


def _hash_array_data(path: Path, chunk_rows: int = 16) -> str:
    array = np.load(path, mmap_mode="r")
    digest = hashlib.sha256()
    for start in range(0, array.shape[0], chunk_rows):
        digest.update(np.ascontiguousarray(array[start : start + chunk_rows]).tobytes())
    return digest.hexdigest()


class ViewSource:
    def __init__(self, label: str, root: Path, offset: int, rows: list[dict[str, Any]], split: str):
        self.label = label
        self.root = root
        self.offset = int(offset)
        self.split = split
        self.rows = rows
        self.rgb = np.load(root / "rgb.npy", mmap_mode="r")
        self.guides = np.load(root / "guides.npy", mmap_mode="r")
        self.context = np.load(root / "context.npy", mmap_mode="r")
        self.streams: dict[tuple[str, int], np.ndarray] = {}
        grouped: dict[tuple[str, int], list[tuple[int, int]]] = defaultdict(list)
        for local_index, row in enumerate(rows):
            if row.get("split") != split:
                continue
            grouped[(str(row["sequence_id"]), int(row["eye"]))].append(
                (int(row["frame_id"]), local_index)
            )
        for key, values in grouped.items():
            values.sort(key=lambda item: item[0])
            frames = [frame for frame, _ in values]
            if frames != list(range(1, 65)):
                raise ValueError(f"{label}/{split}: invalid stream {key}: {frames[:4]}...{frames[-4:]}")
            first = rows[values[0][1]]
            if first.get("history_reset") is not True:
                raise ValueError(f"{label}/{split}: stream {key} lacks initial reset")
            self.streams[key] = np.asarray(
                [self.offset + local for _, local in values], dtype=np.int64
            )
        if not self.streams:
            raise ValueError(f"{label}/{split}: no streams")
        self.sequence_ids = sorted({key[0] for key in self.streams})

    def sample_window(self, rng: np.random.Generator) -> tuple[tuple[str, int], np.ndarray]:
        keys = list(self.streams)
        key = keys[int(rng.integers(len(keys)))]
        start = int(rng.integers(0, 65 - WINDOW))
        return key, self.streams[key][start : start + WINDOW][None, :]

    def local_from_global(self, global_indices: np.ndarray) -> np.ndarray:
        local = np.asarray(global_indices, dtype=np.int64) - self.offset
        if (local < 0).any() or (local >= self.rgb.shape[0]).any():
            raise ValueError(f"{self.label}: global index outside source")
        return local


class ResidualView:
    def __init__(self, root: Path, verify_hashes: bool = True):
        self.root = root.resolve()
        self.manifest = json.loads((self.root / "manifest.json").read_text(encoding="utf-8"))
        if self.manifest.get("schema") != "opennr-residual-target-view-v1":
            raise ValueError("Unexpected residual view schema")
        if self.manifest.get("test_used_for_tuning") is True:
            raise ValueError("Residual view is marked test-used-for-tuning")
        self.rows = json.loads((self.root / "rows.json").read_text(encoding="utf-8"))
        if len(self.rows) != int(self.manifest["rows"]):
            raise ValueError("Residual view rows count mismatch")
        expected_rows_sha = str(self.manifest["rows_sha256"])
        if _stable_json_sha(self.rows) != expected_rows_sha:
            raise ValueError("Residual view rows identity mismatch")
        complete = json.loads((self.root / "complete.json").read_text(encoding="utf-8"))
        if complete.get("manifest_sha256") != _sha256_file(self.root / "manifest.json"):
            raise ValueError("Residual view complete.json does not match manifest")
        self.residual = np.load(self.root / "residual_i16.npy", mmap_mode="r")
        expected_shape = tuple(self.manifest["residual_file"]["shape"])
        if tuple(self.residual.shape) != expected_shape or self.residual.dtype != np.dtype("<i2"):
            raise ValueError(
                f"Residual storage mismatch: {self.residual.shape}/{self.residual.dtype} "
                f"vs {expected_shape}/int16"
            )
        if verify_hashes:
            print("verifying residual view file hash...", flush=True)
            if _sha256_file(self.root / "residual_i16.npy") != self.manifest["residual_file"]["sha256"]:
                raise ValueError("Residual file hash mismatch")
        self.sources: list[ViewSource] = []
        offsets = self.manifest["source_offsets"]
        manifest_source_info = {
            str(info["label"]): info for info in self.manifest["sources"]
        }
        source_rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in self.rows:
            source_rows[str(row["source_label"])].append(row)
        for info in self.manifest["sources"]:
            label = str(info["label"])
            root_path = Path(info["root"]).resolve()
            if not root_path.is_dir():
                raise FileNotFoundError(f"Source disappeared: {root_path}")
            rows = source_rows[label]
            if len(rows) != int(info["rows"]):
                raise ValueError(f"Source row count mismatch for {label}")
            source = ViewSource(label, root_path, int(offsets[label]), rows, "train")
            validation = ViewSource(label, root_path, int(offsets[label]), rows, "validation")
            test = ViewSource(label, root_path, int(offsets[label]), rows, "test")
            source.validation = validation
            source.test = test
            source.manifest_info = manifest_source_info[label]
            self.sources.append(source)
            if verify_hashes:
                print(f"verifying source array hashes: {label}", flush=True)
                for array_name in ("rgb", "guides", "context"):
                    expected = info.get("array_sha256", {}).get(array_name)
                    if expected and _hash_array_data(root_path / f"{array_name}.npy") != expected:
                        raise ValueError(f"Source {label} {array_name} data hash mismatch")
        self.tail_threshold = float(
            json.loads((self.root / "residual_stats.json").read_text(encoding="utf-8"))
            ["groups"]["global"]["aggregate"]["absolute_percentiles"]["p99"]
        )
        self.source_labels = [source.label for source in self.sources]
        self.train_probabilities = np.full(len(self.sources), 1.0 / len(self.sources))

    def load_window(self, global_indices: np.ndarray):
        global_indices = np.asarray(global_indices, dtype=np.int64)
        if global_indices.ndim != 2:
            raise ValueError("window indices must be [batch,window]")
        source_indices = np.searchsorted(
            np.asarray([int(self.manifest["source_offsets"][s.label]) for s in self.sources] + [len(self.rows)]),
            global_indices,
            side="right",
        ) - 1
        if not np.all(source_indices == source_indices.flat[0]):
            raise ValueError("One training window spans multiple source caches")
        source_index = int(source_indices.flat[0])
        source = self.sources[source_index]
        local = source.local_from_global(global_indices)
        rgb = np.array(source.rgb[local, 0], copy=True)
        teacher = np.array(source.rgb[local, 1], copy=True)
        guides = np.array(source.guides[local], copy=True)
        context = np.array(source.context[local], copy=True)
        residual = np.array(self.residual[global_indices], copy=True).astype(np.float32) / 255.0
        return rgb, teacher, guides, context, residual


class ResidualTargetToneHead(SemanticToneHead):
    """Copied current head body with a zero-initialized three-channel R head."""

    def __init__(self, base_state: dict[str, torch.Tensor]):
        super().__init__(pretrained=False)
        # The inherited affine layer is intentionally removed from the logical
        # forward path; its 12-channel parameters are not part of this arm.
        del self.affine
        self.residual_output = nn.Conv2d(64, 3, 1)
        nn.init.zeros_(self.residual_output.weight)
        nn.init.zeros_(self.residual_output.bias)
        copied = {
            key: value.detach().cpu()
            for key, value in base_state.items()
            if not key.startswith("affine.")
        }
        incompatible = self.load_state_dict(copied, strict=False)
        if incompatible.unexpected_keys or set(incompatible.missing_keys) != {
            "residual_output.weight",
            "residual_output.bias",
        }:
            raise ValueError(f"Residual head copy mismatch: {incompatible}")

    def forward(self, rgb, parent, guides, context):
        with torch.no_grad():
            image = (
                F.interpolate(rgb.float(), size=(224, 224), mode="bilinear", align_corners=False)
                - self.encoder_mean
            ) / self.encoder_std
            semantic = self.encoder.get_intermediate_layers(image, n=1, reshape=True)[0]
        size = parent.shape[-2:]
        x = torch.cat(
            (
                rgb,
                parent,
                F.interpolate(guides, size=size, mode="bilinear", align_corners=False),
                F.interpolate(context, size=size, mode="bilinear", align_corners=False),
            ),
            1,
        )
        levels = [self.stem(x)]
        for layer in self.down:
            levels.append(layer(levels[-1]))
        x = self.bottleneck(levels[-1])
        for layer, skip in zip(self.up, reversed(levels[2:-1])):
            x = layer(
                torch.cat(
                    (F.interpolate(x, size=skip.shape[-2:], mode="bilinear", align_corners=False), skip),
                    1,
                )
            )
        x = x + F.interpolate(
            self.semantic_projection(semantic), size=x.shape[-2:], mode="bilinear", align_corners=False
        )
        return F.interpolate(self.residual_output(x).float(), size=size, mode="bilinear", align_corners=False)


class ResidualTargetJointModel(JointParentToneModel):
    def forward_temporal_residual(self, rgb, guides, context, state=None):
        parent_output, next_state = self.parent.forward_temporal(rgb, guides, context, state)
        residual = self.head(rgb, parent_output, guides, context)
        prediction = (rgb.float() + residual.float()).clamp(0.0, 1.0)
        return prediction, residual, next_state

    def forward_temporal(self, rgb, guides, context, state=None):
        prediction, _, next_state = self.forward_temporal_residual(rgb, guides, context, state)
        return prediction, next_state


def _make_residual_model(runtime_checkpoint: Path) -> ResidualTargetJointModel:
    base, _ = load_joint_checkpoint(runtime_checkpoint)
    base_state = {key: value.detach().cpu().clone() for key, value in base.head.state_dict().items()}
    residual_head = ResidualTargetToneHead(base_state).cuda()
    parent = base.parent
    del base
    return ResidualTargetJointModel(parent, residual_head).cuda().eval()


def _learning_rate_factor(step: int, steps: int) -> float:
    if step <= 200:
        return MIN_LR_FACTOR + (1.0 - MIN_LR_FACTOR) * step / 200.0
    progress = (step - 200) / max(steps - 200, 1)
    cosine = 0.5 * (1.0 + math.cos(math.pi * min(max(progress, 0.0), 1.0)))
    return MIN_LR_FACTOR + (1.0 - MIN_LR_FACTOR) * cosine


def _make_schedule(view: ResidualView, steps: int, seed: int) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rng = np.random.default_rng(seed)
    schedule = []
    digest = hashlib.sha256()
    draws = {label: 0 for label in view.source_labels}
    for step in range(1, steps + 1):
        source_index = int(rng.choice(len(view.sources), p=view.train_probabilities))
        source = view.sources[source_index]
        key, ids = source.sample_window(rng)
        digest.update(np.asarray([step, source_index], dtype="<i8").tobytes())
        digest.update(ids.astype("<i8", copy=False).tobytes())
        draws[source.label] += 1
        schedule.append(
            {
                "step": step,
                "source_index": source_index,
                "source_label": source.label,
                "sequence_id": key[0],
                "eye": key[1],
                "ids": ids.tolist(),
            }
        )
    metadata = {
        "seed": seed,
        "steps": steps,
        "window": WINDOW,
        "burn_in": BURN_IN,
        "batch": BATCH,
        "source_labels": view.source_labels,
        "source_probabilities": view.train_probabilities.tolist(),
        "draws": draws,
        "digest_sha256": digest.hexdigest(),
        "same_schedule_for_direct_and_residual": True,
        "test_used": False,
    }
    return schedule, metadata


def _motion_grid(guides: torch.Tensor, image_size: tuple[int, int]) -> torch.Tensor:
    """The existing verified-positive-sign OpenNR guide warp convention."""

    height, width = image_size
    batch = guides.shape[0]
    device = guides.device
    dtype = guides.dtype
    yy, xx = torch.meshgrid(
        torch.arange(height, device=device, dtype=dtype),
        torch.arange(width, device=device, dtype=dtype),
        indexing="ij",
    )
    base = torch.stack(
        ((xx + 0.5) / width * 2.0 - 1.0, (yy + 0.5) / height * 2.0 - 1.0), -1
    )[None].expand(batch, -1, -1, -1)
    mv = F.interpolate(guides[:, 1:3], size=image_size, mode="bilinear", align_corners=False)
    displacement = torch.stack(
        (mv[:, 0] * (256.0 / width), mv[:, 1] * (256.0 / height)), -1
    )
    return base + displacement


def _category_add(
    categories: dict[str, dict[str, float]],
    masks: dict[str, torch.Tensor],
    error: torch.Tensor,
    identity_error: torch.Tensor,
) -> None:
    for name, mask in masks.items():
        count = int(mask.sum().item()) * error.shape[1]
        if count == 0:
            continue
        bucket = categories[name]
        bucket["abs"] += float((error.abs() * mask[:, None]).sum().item())
        bucket["identity_abs"] += float((identity_error.abs() * mask[:, None]).sum().item())
        bucket["pixels"] += count


@torch.no_grad()
def evaluate_source(
    model,
    source: ViewSource,
    residual_storage,
    tail_threshold: float,
    arm: str,
    *,
    autocast_dtype: torch.dtype = torch.bfloat16,
    instrumentation=None,
) -> dict[str, Any]:
    model.eval()
    total_abs = total_sq = identity_abs = identity_sq = 0.0
    residual_abs = 0.0
    delta_abs = identity_delta_abs = 0.0
    warp_abs = identity_warp_abs = teacher_warp_abs = 0.0
    pixels = delta_pixels = warp_pixels = residual_pixels = 0
    stereo_abs = stereo_identity_abs = 0.0
    stereo_pixels = 0
    warm_abs = steady_abs = warm_pixels = steady_pixels = 0.0
    motion_valid_pixels = 0
    categories = {
        "all": {"abs": 0.0, "identity_abs": 0.0, "pixels": 0},
        "bright_luma_ge_0.8": {"abs": 0.0, "identity_abs": 0.0, "pixels": 0},
        "clipped_rgb_channel": {"abs": 0.0, "identity_abs": 0.0, "pixels": 0},
        "large_residual_abs_ge_global_p99": {"abs": 0.0, "identity_abs": 0.0, "pixels": 0},
    }
    sequence_abs: dict[str, float] = defaultdict(float)
    sequence_pixels: dict[str, int] = defaultdict(int)
    eye_abs: dict[str, float] = defaultdict(float)
    eye_pixels: dict[str, int] = defaultdict(int)
    sequences = source.sequence_ids
    for sequence in sequences:
        keys = [(sequence, 0), (sequence, 1)]
        if any(key not in source.streams for key in keys):
            raise ValueError(f"{source.label}/{source.split}: missing stereo eye for {sequence}")
        global_indices = np.stack([source.streams[key] for key in keys])
        local_indices = source.local_from_global(global_indices)
        rgb_np = np.array(source.rgb[local_indices, 0], copy=True)
        target_np = np.array(source.rgb[local_indices, 1], copy=True)
        guides_np = np.array(source.guides[local_indices], copy=True)
        context_np = np.array(source.context[local_indices], copy=True)
        residual_np = np.array(residual_storage[global_indices], copy=True).astype(np.float32) / 255.0
        rgb_all = torch.from_numpy(rgb_np).cuda(non_blocking=True).float() / 255.0
        target_all = torch.from_numpy(target_np).cuda(non_blocking=True).float() / 255.0
        guides_all = torch.from_numpy(guides_np).cuda(non_blocking=True).float()
        context_all = torch.from_numpy(context_np).cuda(non_blocking=True).float()
        residual_all = torch.from_numpy(residual_np).cuda(non_blocking=True)
        state = None
        previous_pred = previous_target = previous_rgb = None
        for frame in range(64):
            if instrumentation is not None:
                instrumentation.begin_frame(
                    target_all[:, frame], residual_all[:, frame], tail_threshold
                )
            with torch.autocast(device_type="cuda", dtype=autocast_dtype):
                if arm == "direct":
                    pred, state = model.forward_temporal(
                        rgb_all[:, frame], guides_all[:, frame], context_all[:, frame], state
                    )
                    residual_hat = pred.float() - rgb_all[:, frame]
                    target_for_loss = target_all[:, frame]
                else:
                    pred, residual_hat, state = model.forward_temporal_residual(
                        rgb_all[:, frame], guides_all[:, frame], context_all[:, frame], state
                    )
                    target_for_loss = residual_all[:, frame]
            pred = pred.float()
            residual_hat = residual_hat.float()
            target = target_all[:, frame]
            rgb = rgb_all[:, frame]
            target_residual = residual_all[:, frame]
            if not torch.isfinite(pred).all() or not torch.isfinite(residual_hat).all():
                raise ValueError(f"Nonfinite {arm} prediction in {source.label}/{sequence} frame {frame + 1}")
            error = pred - target
            baseline = rgb - target
            total_abs += float(error.abs().sum().item())
            total_sq += float(error.square().sum().item())
            identity_abs += float(baseline.abs().sum().item())
            identity_sq += float(baseline.square().sum().item())
            pixels += target.numel()
            sequence_abs[sequence] += float(error.abs().sum().item())
            sequence_pixels[sequence] += target.numel()
            for eye in range(2):
                eye_abs[str(eye)] += float(error[eye].abs().sum().item())
                eye_pixels[str(eye)] += target[eye].numel()
            luma = 0.2126 * target[:, 0] + 0.7152 * target[:, 1] + 0.0722 * target[:, 2]
            masks = {
                "all": torch.ones_like(luma, dtype=torch.bool),
                "bright_luma_ge_0.8": luma >= 0.8,
                "clipped_rgb_channel": target.max(dim=1).values >= (254.5 / 255.0),
                "large_residual_abs_ge_global_p99": target_residual.abs().max(dim=1).values >= tail_threshold,
            }
            _category_add(categories, masks, error, baseline)
            if arm == "residual":
                residual_abs += float((residual_hat - target_residual).abs().sum().item())
                residual_pixels += target_residual.numel()
            if frame == 0:
                warm_abs += float(error.abs().sum().item())
                warm_pixels += target.numel()
            else:
                delta = (pred - previous_pred) - (target - previous_target)
                identity_delta = (rgb - previous_rgb) - (target - previous_target)
                delta_abs += float(delta.abs().sum().item())
                identity_delta_abs += float(identity_delta.abs().sum().item())
                delta_pixels += target.numel()
                grid = _motion_grid(guides_all[:, frame], target.shape[-2:])
                motion_valid = F.interpolate(
                    guides_all[:, frame, 4:5], size=target.shape[-2:], mode="nearest"
                ) > 0.5
                valid_count = int(motion_valid.sum().item())
                if valid_count:
                    warped_pred = F.grid_sample(
                        previous_pred, grid, mode="bilinear", padding_mode="border", align_corners=False
                    )
                    warped_identity = F.grid_sample(
                        previous_rgb, grid, mode="bilinear", padding_mode="border", align_corners=False
                    )
                    warped_teacher = F.grid_sample(
                        previous_target, grid, mode="bilinear", padding_mode="border", align_corners=False
                    )
                    warp_abs += float(((warped_pred - target).abs() * motion_valid).sum().item())
                    identity_warp_abs += float(((warped_identity - target).abs() * motion_valid).sum().item())
                    teacher_warp_abs += float(((warped_teacher - target).abs() * motion_valid).sum().item())
                    warp_pixels += valid_count * target.shape[1]
                    motion_valid_pixels += valid_count
                steady_abs += float(error.abs().sum().item())
                steady_pixels += target.numel()
            # Each eye's recurrent state is carried independently in the batch.
            previous_pred = pred
            previous_target = target
            previous_rgb = rgb
        stereo_error = (pred[0] - pred[1]) - (target[0] - target[1])
        stereo_identity = (rgb[0] - rgb[1]) - (target[0] - target[1])
        stereo_abs += float(stereo_error.abs().sum().item())
        stereo_identity_abs += float(stereo_identity.abs().sum().item())
        stereo_pixels += target[0].numel()
        del rgb_all, target_all, guides_all, context_all, residual_all, state
        torch.cuda.empty_cache()

    category_metrics = {}
    for name, bucket in categories.items():
        category_metrics[name] = {
            "mae": bucket["abs"] / max(1, bucket["pixels"]),
            "identity_mae": bucket["identity_abs"] / max(1, bucket["pixels"]),
            "pixels": int(bucket["pixels"]),
            "status": "measured" if bucket["pixels"] else "empty",
            "diagnostic_only": name != "all",
        }
    metrics = {
        "source": source.label,
        "split": source.split,
        "sequence_count": len(sequences),
        "eye_streams": len(source.streams),
        "frames": pixels // (3 * 512 * 512),
        "pixels": pixels,
        "mae": total_abs / max(1, pixels),
        "mse": total_sq / max(1, pixels),
        "psnr": -10.0 * math.log10(max(total_sq / max(1, pixels), 1e-12)),
        "identity_mae": identity_abs / max(1, pixels),
        "identity_mse": identity_sq / max(1, pixels),
        "identity_psnr": -10.0 * math.log10(max(identity_sq / max(1, pixels), 1e-12)),
        "improvement_pct": 100.0 * (identity_abs - total_abs) / max(identity_abs, 1e-12),
        "temporal_delta_mae": delta_abs / max(1, delta_pixels),
        "identity_temporal_delta_mae": identity_delta_abs / max(1, delta_pixels),
        "delta_pixels": delta_pixels,
        "first_frame_mae": warm_abs / max(1, warm_pixels),
        "steady_frame_mae": steady_abs / max(1, steady_pixels),
        "temporal_warp_mae": warp_abs / max(1, warp_pixels),
        "identity_temporal_warp_mae": identity_warp_abs / max(1, warp_pixels),
        "teacher_warp_delta_mae": teacher_warp_abs / max(1, warp_pixels),
        "warp_pixels": warp_pixels,
        "motion_valid_fraction": motion_valid_pixels / max(1, delta_pixels // 3),
        "stereo_disagreement_mae": stereo_abs / max(1, stereo_pixels),
        "identity_stereo_disagreement_mae": stereo_identity_abs / max(1, stereo_pixels),
        "stereo_pixels": stereo_pixels,
        "residual_mae": residual_abs / max(1, residual_pixels) if arm == "residual" else None,
        "residual_pixels": residual_pixels,
        "category_metrics": category_metrics,
        "sequence_mae": {
            key: value / max(1, sequence_pixels[key]) for key, value in sequence_abs.items()
        },
        "eye_mae": {key: value / max(1, eye_pixels[key]) for key, value in eye_abs.items()},
        "face_metrics": {
            "status": "unavailable",
            "reason": "no validated face-mask manifest in the selected intact sources",
        },
        "fire_metrics": {
            "status": "unavailable",
            "reason": "no validated fire-category labels in the selected intact sources",
        },
        "hdr_metrics": {
            "status": "unavailable",
            "reason": "captures are uint8 SDR-contract RGB; clipped_rgb_channel is only a diagnostic heuristic",
        },
        "warp_contract": {
            "status": "measured_proxy",
            "motion_source": "captured exact Feature-18-bound motion guide channel",
            "grid_sign": "positive, matching existing audited MotionWarpTemporalStyleContextStudent",
            "normalization": "guide motion is color-pixel displacement divided by 128; grid uses 256/width",
            "padding": "border",
            "validity": "current-frame guide channel 4 > 0.5",
            "not_a_calibrated_reprojection_claim": True,
        },
    }
    return metrics


def _aggregate(metrics_by_source: dict[str, dict[str, Any]]) -> dict[str, Any]:
    def weighted(field: str, denominator: str = "pixels"):
        total = sum(int(value.get(denominator, 0)) for value in metrics_by_source.values())
        if not total:
            return None
        return sum(float(value[field]) * int(value[denominator]) for value in metrics_by_source.values()) / total

    pixels = sum(int(value["pixels"]) for value in metrics_by_source.values())
    mse = weighted("mse")
    identity_mse = weighted("identity_mse")
    delta_pixels = sum(int(value["delta_pixels"]) for value in metrics_by_source.values())
    warp_pixels = sum(int(value["warp_pixels"]) for value in metrics_by_source.values())
    stereo_pixels = sum(int(value["stereo_pixels"]) for value in metrics_by_source.values())
    residual_pixels = sum(int(value["residual_pixels"]) for value in metrics_by_source.values())
    result = {
        "source_count": len(metrics_by_source),
        "pixels": pixels,
        "sequence_count": sum(int(value["sequence_count"]) for value in metrics_by_source.values()),
        "eye_streams": sum(int(value["eye_streams"]) for value in metrics_by_source.values()),
        "mae": weighted("mae"),
        "mse": mse,
        "psnr": -10.0 * math.log10(max(mse or 0.0, 1e-12)),
        "identity_mae": weighted("identity_mae"),
        "identity_mse": identity_mse,
        "identity_psnr": -10.0 * math.log10(max(identity_mse or 0.0, 1e-12)),
        "improvement_pct": 100.0 * (weighted("identity_mae") - weighted("mae")) / max(weighted("identity_mae"), 1e-12),
        "temporal_delta_mae": weighted("temporal_delta_mae", "delta_pixels"),
        "identity_temporal_delta_mae": weighted("identity_temporal_delta_mae", "delta_pixels"),
        "delta_pixels": delta_pixels,
        "first_frame_mae": weighted("first_frame_mae"),
        "steady_frame_mae": weighted("steady_frame_mae"),
        "temporal_warp_mae": weighted("temporal_warp_mae", "warp_pixels"),
        "identity_temporal_warp_mae": weighted("identity_temporal_warp_mae", "warp_pixels"),
        "teacher_warp_delta_mae": weighted("teacher_warp_delta_mae", "warp_pixels"),
        "warp_pixels": warp_pixels,
        "stereo_disagreement_mae": weighted("stereo_disagreement_mae", "stereo_pixels"),
        "identity_stereo_disagreement_mae": weighted("identity_stereo_disagreement_mae", "stereo_pixels"),
        "stereo_pixels": stereo_pixels,
        "residual_mae": weighted("residual_mae", "residual_pixels") if residual_pixels else None,
        "residual_pixels": residual_pixels,
        "face_metrics": {"status": "unavailable", "reason": "no validated face masks"},
        "fire_metrics": {"status": "unavailable", "reason": "no validated fire labels"},
        "hdr_metrics": {"status": "unavailable", "reason": "uint8 SDR-contract capture; heuristic only"},
    }
    # Keep the measured diagnostic partitions available at the aggregate level.
    category_names = sorted(next(iter(metrics_by_source.values()))["category_metrics"])
    result["category_metrics"] = {}
    for name in category_names:
        buckets = [value["category_metrics"][name] for value in metrics_by_source.values()]
        count = sum(int(bucket["pixels"]) for bucket in buckets)
        if count:
            result["category_metrics"][name] = {
                "mae": sum(float(bucket["mae"]) * int(bucket["pixels"]) for bucket in buckets) / count,
                "identity_mae": sum(float(bucket["identity_mae"]) * int(bucket["pixels"]) for bucket in buckets) / count,
                "pixels": count,
                "status": "measured",
                "diagnostic_only": name != "all",
            }
    return result


@torch.no_grad()
def evaluate_all(
    model,
    view: ResidualView,
    split: str,
    arm: str,
    *,
    autocast_dtype: torch.dtype = torch.bfloat16,
) -> dict[str, Any]:
    per_source = {}
    for source in view.sources:
        cache = source if split == "train" else getattr(source, split)
        per_source[source.label] = evaluate_source(
            model,
            cache,
            view.residual,
            view.tail_threshold,
            arm,
            autocast_dtype=autocast_dtype,
        )
    return {
        "split": split,
        "arm": arm,
        "sources": per_source,
        "aggregate": _aggregate(per_source),
        "test_used": False,
    }


def _trainable_parameters(model):
    return [parameter for parameter in model.parameters() if parameter.requires_grad]


def _make_optimizer(model):
    head = [parameter for parameter in model.head.parameters() if parameter.requires_grad]
    parent = [parameter for parameter in model.parent.parameters() if parameter.requires_grad]
    if not head or not parent:
        raise ValueError("Direct arm must have trainable head and parent parameters")
    return torch.optim.AdamW(
        [{"params": head, "lr": HEAD_LR}, {"params": parent, "lr": PARENT_LR}],
        weight_decay=WEIGHT_DECAY,
    )


def _make_residual_optimizer(model):
    # Frozen parameters are included so the optimizer contract is identical
    # after the warm phase; AdamW creates their state only once they receive a
    # gradient.  The two groups retain the direct arm's nominal LRs.
    head = list(model.head.parameters())
    parent = list(model.parent.parameters())
    return torch.optim.AdamW(
        [{"params": head, "lr": HEAD_LR}, {"params": parent, "lr": PARENT_LR}],
        weight_decay=WEIGHT_DECAY,
    )


def _set_lr(optimizer, factor: float) -> None:
    optimizer.param_groups[0]["lr"] = HEAD_LR * factor
    optimizer.param_groups[1]["lr"] = PARENT_LR * factor


def _set_residual_phase(model, warm: bool) -> None:
    if warm:
        for parameter in model.head.parameters():
            parameter.requires_grad_(False)
        for parameter in model.parent.parameters():
            parameter.requires_grad_(False)
        model.head.residual_output.weight.requires_grad_(True)
        model.head.residual_output.bias.requires_grad_(True)
    else:
        for parameter in model.head.parameters():
            parameter.requires_grad_(True)
        model.head.encoder.requires_grad_(False)
        for parameter in model.parent.parameters():
            parameter.requires_grad_(True)


def _checkpoint(
    path: Path,
    model,
    arm: str,
    step: int,
    run: dict[str, Any],
    validation: dict[str, Any],
    history: list[dict[str, Any]],
) -> str:
    payload = {
        "architecture": "semantic_residual_target_experiment_v1",
        "arm": arm,
        "step": step,
        "head": model.head.state_dict(),
        "parent_model": model.parent.state_dict(),
        "run": run,
        "validation": validation,
        "history": history,
        "test_used": False,
    }
    temporary = path.with_suffix(path.suffix + ".tmp")
    torch.save(payload, temporary)
    temporary.replace(path)
    return _sha256_file(path)


def _train_arm(
    arm: str,
    args,
    view: ResidualView,
    schedule: list[dict[str, Any]],
    schedule_meta: dict[str, Any],
    identity: dict[str, Any],
    source_hashes: dict[str, Any],
    output: Path,
) -> dict[str, Any]:
    output.mkdir(parents=True)
    torch.manual_seed(args.seed)
    torch.cuda.manual_seed_all(args.seed)
    if arm == "direct":
        model, _ = load_joint_checkpoint(args.runtime_checkpoint)
        optimizer = _make_optimizer(model)
    else:
        model = _make_residual_model(args.runtime_checkpoint)
        _set_residual_phase(model, warm=True)
        optimizer = _make_residual_optimizer(model)
    model.cuda()
    run = {
        "architecture": "semantic_residual_target_experiment_v1",
        "arm": arm,
        "initialization": "protected current exact-weight recovered clone",
        "protected_checkpoint_identity": identity,
        "runtime_checkpoint": str(args.runtime_checkpoint.resolve()),
        "view_root": str(view.root),
        "view_manifest_sha256": _sha256_file(view.root / "manifest.json"),
        "view_complete_sha256": _sha256_file(view.root / "complete.json"),
        "source_hashes": source_hashes,
        "source_labels": view.source_labels,
        "source_probabilities": view.train_probabilities.tolist(),
        "training_sequences": {source.label: source.sequence_ids for source in view.sources},
        "validation_sequences": {
            source.label: source.validation.sequence_ids for source in view.sources
        },
        "test_sequences_preserved": {
            source.label: source.test.sequence_ids for source in view.sources
        },
        "steps": args.steps,
        "window": WINDOW,
        "burn_in": BURN_IN,
        "batch": BATCH,
        "seed": args.seed,
        "optimizer": "AdamW",
        "weight_decay": WEIGHT_DECAY,
        "head_learning_rate": HEAD_LR,
        "parent_learning_rate": PARENT_LR,
        "learning_rate_schedule": {
            "type": "linear_warmup_then_cosine_decay",
            "warmup_steps": 200,
            "minimum_factor": MIN_LR_FACTOR,
        },
        "loss": "frame_objective(error, previous_error, pixel_only=True); direct error=P-T; residual error=R_hat-R",
        "residual_target": "R=T-B; final P=clamp(B+R_hat,0,1)",
        "residual_warmup": {
            "steps": WARMUP_STEPS,
            "trainable": "new residual_output only",
            "unfreeze_at_step": WARMUP_STEPS + 1,
        }
        if arm == "residual"
        else None,
        "schedule": schedule_meta,
        "schedule_sha256": schedule_meta["digest_sha256"],
        "encoder_provenance": encoder_provenance(),
        "test_used": False,
        "selection": "validation aggregate MAE is the primary descriptive ranking; temporal, stereo, warp and per-source guardrails remain separate",
        "source_code_sha256": {
            name: _sha256_file(Path(__file__).with_name(name))
            for name in (
                "train_residual_target_pair.py",
                "joint_parent_tone_model.py",
                "semantic_tone_head.py",
                "stable_oversized_tone_head.py",
                "oversized_tone_head.py",
                "train_spatial_tone.py",
            )
        },
    }
    _write_json(output / "run.json", run)
    history: list[dict[str, Any]] = []
    best_step = 0
    best_mae = float("inf")
    started = time.time()

    def evaluate_and_save(step: int):
        nonlocal best_step, best_mae
        _write_json(
            output / "status.json",
            {"state": "evaluating", "arm": arm, "step": step, "steps": args.steps, "test_used": False},
        )
        validation = evaluate_all(model, view, "validation", arm)
        aggregate = validation["aggregate"]
        if float(aggregate["mae"]) < best_mae:
            best_mae = float(aggregate["mae"])
            best_step = step
        entry = {
            "step": step,
            "validation": validation,
            "learning_rate_factor": _learning_rate_factor(step, args.steps) if step else None,
            "best_step_so_far": best_step,
            "best_validation_mae_so_far": best_mae,
            "seconds": time.time() - started,
            "test_used": False,
        }
        history.append(entry)
        _write_json(output / "history.json", history)
        checkpoint = output / f"checkpoint_{step:04d}.pt"
        checkpoint_sha = _checkpoint(checkpoint, model, arm, step, run, validation, history)
        _write_json(
            output / f"checkpoint_{step:04d}_identity.json",
            {"step": step, "sha256": checkpoint_sha, "path": str(checkpoint.resolve())},
        )
        print(
            json.dumps(
                {
                    "arm": arm,
                    "step": step,
                    "validation_mae": aggregate["mae"],
                    "validation_psnr": aggregate["psnr"],
                    "validation_temporal_delta_mae": aggregate["temporal_delta_mae"],
                    "validation_temporal_warp_mae": aggregate["temporal_warp_mae"],
                    "validation_stereo_disagreement_mae": aggregate["stereo_disagreement_mae"],
                    "best_step": best_step,
                    "seconds": time.time() - started,
                    "test_used": False,
                }
            ),
            flush=True,
        )

    try:
        evaluate_and_save(0)
        for item in schedule:
            step = int(item["step"])
            if arm == "residual" and step == WARMUP_STEPS + 1:
                _set_residual_phase(model, warm=False)
                print(json.dumps({"arm": arm, "step": step, "event": "residual_body_parent_unfrozen"}), flush=True)
            factor = _learning_rate_factor(step, args.steps)
            _set_lr(optimizer, factor)
            ids = np.asarray(item["ids"], dtype=np.int64)
            rgb_np, teacher_np, guides_np, context_np, residual_np = view.load_window(ids)
            rgb = torch.from_numpy(rgb_np).cuda(non_blocking=True).float() / 255.0
            teacher = torch.from_numpy(teacher_np).cuda(non_blocking=True).float() / 255.0
            guides = torch.from_numpy(guides_np).cuda(non_blocking=True).float()
            context = torch.from_numpy(context_np).cuda(non_blocking=True).float()
            residual_target = torch.from_numpy(residual_np).cuda(non_blocking=True)
            model.train()
            optimizer.zero_grad(set_to_none=True)
            state = None
            previous_error = None
            losses = []
            for frame in range(WINDOW):
                with torch.set_grad_enabled(frame >= BURN_IN), torch.autocast(
                    device_type="cuda", dtype=torch.bfloat16
                ):
                    if arm == "direct":
                        prediction, state = model.forward_temporal(
                            rgb[:, frame], guides[:, frame], context[:, frame], state
                        )
                        error = prediction.float() - teacher[:, frame]
                    else:
                        prediction, residual_hat, state = model.forward_temporal_residual(
                            rgb[:, frame], guides[:, frame], context[:, frame], state
                        )
                        error = residual_hat.float() - residual_target[:, frame]
                    if frame >= BURN_IN:
                        losses.append(frame_objective(error, previous_error, pixel_only=True))
                    previous_error = error if frame >= BURN_IN else error.detach()
            loss = torch.stack(losses).mean()
            if not torch.isfinite(loss):
                raise ValueError(f"Nonfinite {arm} loss at step {step}")
            loss.backward()
            trainable = [parameter for parameter in _trainable_parameters(model) if parameter.grad is not None]
            if not trainable:
                raise ValueError(f"No gradient at {arm} step {step}")
            torch.nn.utils.clip_grad_norm_(trainable, 1.0, error_if_nonfinite=True)
            optimizer.step()
            if step == 1 or step % args.status_every == 0:
                _write_json(
                    output / "status.json",
                    {
                        "state": "training",
                        "arm": arm,
                        "step": step,
                        "steps": args.steps,
                        "source_label": item["source_label"],
                        "sequence_id": item["sequence_id"],
                        "loss": float(loss.detach().cpu()),
                        "learning_rate_factor": factor,
                        "learning_rates": [group["lr"] for group in optimizer.param_groups],
                        "trainable_parameter_count": sum(parameter.numel() for parameter in _trainable_parameters(model)),
                        "seconds": time.time() - started,
                        "gpu_peak_gib": torch.cuda.max_memory_allocated() / 2**30,
                        "test_used": False,
                    },
                )
                print(
                    json.dumps(
                        {
                            "arm": arm,
                            "step": step,
                            "loss": float(loss.detach().cpu()),
                            "source_label": item["source_label"],
                            "learning_rate_factor": factor,
                        }
                    ),
                    flush=True,
                )
            del rgb, teacher, guides, context, residual_target, prediction, error, loss, state, previous_error, losses
            torch.cuda.empty_cache()
            if step % args.eval_every == 0 or step == args.steps:
                evaluate_and_save(step)
        _write_json(
            output / "status.json",
            {
                "state": "complete",
                "arm": arm,
                "steps": args.steps,
                "best_step": best_step,
                "best_validation_mae": best_mae,
                "gpu_peak_gib": torch.cuda.max_memory_allocated() / 2**30,
                "seconds": time.time() - started,
                "test_used": False,
            },
        )
        return {
            "arm": arm,
            "output": str(output.resolve()),
            "best_step": best_step,
            "best_validation_mae": best_mae,
            "history": str((output / "history.json").resolve()),
            "final_checkpoint": str((output / f"checkpoint_{args.steps:04d}.pt").resolve()),
            "final_checkpoint_sha256": _sha256_file(output / f"checkpoint_{args.steps:04d}.pt"),
            "test_used": False,
        }
    except Exception as exc:
        _write_json(output / "status.json", {"state": "failed", "arm": arm, "error": repr(exc), "test_used": False})
        raise
    finally:
        del model, optimizer
        torch.cuda.empty_cache()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--view", type=Path, required=True)
    parser.add_argument("--protected-checkpoint", type=Path, default=DEFAULT_PROTECTED)
    parser.add_argument("--runtime-checkpoint", type=Path, default=DEFAULT_RUNTIME_CLONE)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--steps", type=int, default=1600, choices=(1200, 1600, 2000))
    parser.add_argument("--eval-every", type=int, default=400)
    parser.add_argument("--status-every", type=int, default=50)
    parser.add_argument("--seed", type=int, default=911)
    parser.add_argument("--skip-source-hash-verification", action="store_true")
    args = parser.parse_args()
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is required")
    if args.eval_every < 1 or args.steps % args.eval_every:
        raise ValueError("steps must be divisible by eval-every")
    args.view = args.view.resolve()
    args.protected_checkpoint = args.protected_checkpoint.resolve()
    args.runtime_checkpoint = args.runtime_checkpoint.resolve()
    args.output_root = args.output_root.resolve()
    if args.output_root.exists():
        raise FileExistsError(args.output_root)
    args.output_root.mkdir(parents=True)
    _write_json(args.output_root / "status.json", {"state": "starting", "test_used": False})
    identity = _verify_checkpoint_identity(args.protected_checkpoint, args.runtime_checkpoint)
    view = ResidualView(args.view, verify_hashes=not args.skip_source_hash_verification)
    source_hashes = {
        source.label: {
            "root": str(source.root),
            "complete_sha256": _sha256_file(source.root / "complete.json"),
            "rows_sha256_file": _sha256_file(source.root / "rows.json"),
            # ResidualView already verified these data hashes.  Reuse the
            # values from its immutable manifest rather than reading 20 GB of
            # source arrays a second time before model loading.
            "rgb_data_sha256": source.manifest_info.get("array_sha256", {}).get("rgb"),
            "guides_data_sha256": source.manifest_info.get("array_sha256", {}).get("guides"),
            "context_data_sha256": source.manifest_info.get("array_sha256", {}).get("context"),
        }
        for source in view.sources
    }
    schedule, schedule_meta = _make_schedule(view, args.steps, args.seed)
    _write_json(
        args.output_root / "paired_schedule.json",
        {"metadata": schedule_meta, "rows": schedule, "test_used": False},
    )
    experiment = {
        "architecture": "semantic_residual_target_experiment_v1",
        "view": str(view.root),
        "view_manifest_sha256": _sha256_file(view.root / "manifest.json"),
        "protected_checkpoint_identity": identity,
        "source_hashes": source_hashes,
        "schedule_sha256": schedule_meta["digest_sha256"],
        "steps": args.steps,
        "window": WINDOW,
        "burn_in": BURN_IN,
        "batch": BATCH,
        "same_schedule_for_direct_and_residual": True,
        "test_used": False,
        "face_labels": "unavailable in selected sources; preserved null",
        "high_effect_labels": "unavailable in selected sources; preserved null",
        "legacy_corpus_boundary": "available four-source view; not the original six-cohort protected corpus",
    }
    _write_json(args.output_root / "experiment_identity.json", experiment)
    print(json.dumps({"event": "identity_verified", **identity}), flush=True)
    print(json.dumps({"event": "schedule_ready", **schedule_meta}), flush=True)
    direct = _train_arm(
        "direct",
        args,
        view,
        schedule,
        schedule_meta,
        identity,
        source_hashes,
        args.output_root / "direct",
    )
    residual = _train_arm(
        "residual",
        args,
        view,
        schedule,
        schedule_meta,
        identity,
        source_hashes,
        args.output_root / "residual",
    )
    _write_json(
        args.output_root / "summary.json",
        {
            "architecture": "semantic_residual_target_experiment_v1",
            "direct": direct,
            "residual": residual,
            "selection_status": "validation_only; test and runtime acceptance pending",
            "test_used": False,
        },
    )
    _write_json(
        args.output_root / "status.json",
        {
            "state": "complete",
            "direct_state": "complete",
            "residual_state": "complete",
            "steps": args.steps,
            "test_used": False,
        },
    )


if __name__ == "__main__":
    main()
