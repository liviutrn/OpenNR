"""Train a causal OpenNR student on reset-qualified Feature-18 clips.

This is a new, resumable phase rather than a rewrite of the frozen spatial
experiments.  Sequence holdouts stay immutable.  The temporal stream uses the
strict crop cache; an optional merged spatial cache supplies single-frame
regularization examples from the earlier and new spatial corpora.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
import random
import time

import numpy as np
import torch
import torch.nn.functional as F

from perceptual_features import FeatureDistance
from student_v2 import ReconstructionConfig, detail_loss
from temporal_student import TemporalConfig, TemporalStyleContextStudent
from train_student import atomic_json


class StrictTemporalCache:
    """Memory-mapped strict cache with sequence/eye stream indexing."""

    def __init__(self, root: Path, split: str):
        self.root = Path(root).resolve()
        self.split = split
        if split == "train_validation":
            allowed_splits = {"train", "validation"}
        elif split in {"train", "validation", "test"}:
            allowed_splits = {split}
        else:
            raise ValueError(f"Unknown strict cache split {split!r}")
        self.complete = json.loads((self.root / "complete.json").read_text(encoding="utf-8"))
        if not self.complete.get("strict_initial_reset"):
            raise ValueError("Temporal training requires a strict-initial-reset cache")
        if self.complete.get("temporal_training_allowed") is False:
            raise ValueError("Cache is marked spatial-only auxiliary data and cannot be used as a temporal stream")
        crop_indices = self.complete.get("crop_indices")
        if isinstance(crop_indices, list) and len(crop_indices) != 1:
            raise ValueError("Temporal training requires exactly one crop index per cache")
        self.rows = json.loads((self.root / "rows.json").read_text(encoding="utf-8"))
        self.rgb = np.load(self.root / "rgb.npy", mmap_mode="r")
        self.guides = np.load(self.root / "guides.npy", mmap_mode="r")
        self.context = np.load(self.root / "context.npy", mmap_mode="r")
        if self.rgb.shape[0] != len(self.rows):
            raise ValueError("RGB rows do not match row manifest")
        if self.guides.shape[0] != len(self.rows):
            raise ValueError("Guide rows do not match row manifest")
        self.streams: dict[tuple[str, int], np.ndarray] = {}
        grouped: dict[tuple[str, int], list[tuple[int, int]]] = defaultdict(list)
        for index, row in enumerate(self.rows):
            if row.get("split") not in allowed_splits:
                continue
            grouped[(row["sequence_id"], int(row["eye"]))].append(
                (int(row["frame_id"]), index)
            )
        for key, values in grouped.items():
            values.sort()
            frames = [frame for frame, _ in values]
            if frames != list(range(1, len(frames) + 1)):
                raise ValueError(f"Non-contiguous stream {key}: {frames[:3]}...{frames[-3:]}")
            if len(frames) != 64:
                raise ValueError(f"Expected 64 frames in {key}, found {len(frames)}")
            first = self.rows[values[0][1]]
            if not first.get("history_reset"):
                raise ValueError(f"Stream {key} has no initial history reset")
            self.streams[key] = np.asarray([index for _, index in values], dtype=np.int64)
        if not self.streams:
            raise ValueError(f"No strict streams in split {split!r}")

    @property
    def rows_sha256(self) -> str:
        return str(self.complete["rows_sha256"])

    @property
    def sequence_ids(self) -> list[str]:
        return sorted({key[0] for key in self.streams})

    def sample_window(self, rng: np.random.Generator, batch: int, window: int):
        keys = list(self.streams)
        if window < 2 or window > 64:
            raise ValueError("Temporal window must be between 2 and 64")
        selected = [keys[int(rng.integers(len(keys)))] for _ in range(batch)]
        starts = [int(rng.integers(0, 65 - window)) for _ in range(batch)]
        indices = np.stack(
            [self.streams[key][start : start + window] for key, start in zip(selected, starts)]
        )
        return selected, starts, indices

    def load_window(self, indices: np.ndarray):
        # Advanced indexing returns a copy, protecting the memmap from accidental
        # in-place augmentation and keeping the batch lifetime explicit.
        rgb = np.array(self.rgb[indices, 0], copy=True)
        target = np.array(self.rgb[indices, 1], copy=True)
        guides = np.array(self.guides[indices], copy=True)
        row_context = np.array(self.context[indices], copy=True)
        return rgb, target, guides, row_context

    def stream_batches(self, batch: int):
        keys = list(self.streams)
        for offset in range(0, len(keys), batch):
            selected = keys[offset : offset + batch]
            indices = np.stack([self.streams[key] for key in selected])
            yield selected, self.load_window(indices)


class SpatialCache:
    """Training-only patch sampler for an optional merged spatial cache."""

    def __init__(self, root: Path, include_validation: bool = False):
        self.root = Path(root).resolve()
        allowed_splits = {"train", "validation"} if include_validation else {"train"}
        self.complete = json.loads((self.root / "complete.json").read_text(encoding="utf-8"))
        if self.complete.get("test_used_for_tuning"):
            raise ValueError("Spatial cache is marked as test-used-for-tuning")
        plan = json.loads((self.root / "patches.json").read_text(encoding="utf-8"))
        self.ids = np.asarray(
            [
                index
                for index, patch in enumerate(plan)
                if patch.get("split") in allowed_splits
            ],
            dtype=np.int64,
        )
        if not len(self.ids):
            raise ValueError("Merged spatial cache has no training patches")
        self.rgb = np.load(self.root / "rgb.npy", mmap_mode="r")
        self.guides = np.load(self.root / "guides.npy", mmap_mode="r")
        self.context = np.load(self.root / "context.npy", mmap_mode="r")
        self.row_for_patch = np.asarray([int(patch["row"]) for patch in plan], dtype=np.int64)
        if self.rgb.shape[0] != len(plan) or self.guides.shape[0] != len(plan):
            raise ValueError("Spatial patch arrays do not match patches.json")

    @property
    def rows_sha256(self) -> str:
        return str(self.complete["rows_sha256"])

    def sample(self, rng: np.random.Generator, batch: int):
        ids = self.ids[rng.integers(0, len(self.ids), size=batch)]
        rows = self.row_for_patch[ids]
        return (
            np.array(self.rgb[ids, 0], copy=True),
            np.array(self.rgb[ids, 1], copy=True),
            np.array(self.guides[ids], copy=True),
            np.array(self.context[rows], copy=True),
        )


class MultiSpatialCache:
    """Sample several immutable spatial caches without concatenating arrays."""

    def __init__(self, roots: list[Path], include_validation: bool = False):
        if not roots:
            raise ValueError("At least one spatial cache is required")
        self.caches = [SpatialCache(root, include_validation=include_validation) for root in roots]
        sizes = np.asarray([len(cache.ids) for cache in self.caches], dtype=np.float64)
        self.probabilities = sizes / sizes.sum()

    @property
    def complete(self):
        values = [cache.complete for cache in self.caches]
        return values[0] if len(values) == 1 else values

    @property
    def rows_sha256(self):
        values = [cache.rows_sha256 for cache in self.caches]
        return values[0] if len(values) == 1 else values

    @property
    def ids(self):
        return np.asarray([len(cache.ids) for cache in self.caches], dtype=np.int64)

    def sample(self, rng: np.random.Generator, batch: int):
        index = int(rng.choice(len(self.caches), p=self.probabilities))
        return self.caches[index].sample(rng, batch)


def _device_batch(values, device="cuda"):
    return tuple(torch.from_numpy(value).to(device, non_blocking=True) for value in values)


def _augment_sequence(rgb, target, guides, context, rng: np.random.Generator):
    if float(rng.random()) >= 0.5:
        return rgb, target, guides, context
    rgb = rgb.flip(-1)
    target = target.flip(-1)
    guides = guides.flip(-1)
    context = context.flip(-1)
    # Cache guide order is depth, MV-X, MV-Y, depth-valid, MV-valid.
    guides[:, :, 1] *= -1
    # Context carries the same MV-X convention at channel four.
    context[:, :, 4] *= -1
    return rgb, target, guides, context


@torch.no_grad()
def evaluate_streaming(model, cache: StrictTemporalCache, device="cuda", batch=8):
    """Evaluate complete streams with state reset at every sequence/eye."""

    model.eval()
    total_abs = total_sq = identity_abs = identity_sq = 0.0
    delta_abs = identity_delta_abs = 0.0
    pixels = delta_pixels = 0
    by_sequence: dict[str, list[float]] = defaultdict(list)
    by_eye: dict[str, list[float]] = defaultdict(list)
    warm_abs = warm_pixels = steady_abs = steady_pixels = 0.0
    for selected, arrays in cache.stream_batches(batch):
        rgb_np, target_np, guides_np, context_np = arrays
        rgb_all, target_all, guides_all, context_all = _device_batch(
            (rgb_np, target_np, guides_np, context_np), device
        )
        rgb_all = rgb_all.float() / 255.0
        target_all = target_all.float() / 255.0
        guides_all = guides_all.float()
        context_all = context_all.float()
        state = None
        previous_pred = previous_target = None
        stream_values = [[] for _ in selected]
        for frame in range(rgb_all.shape[1]):
            with torch.autocast(device_type="cuda", dtype=torch.bfloat16):
                pred, state = model.forward_temporal(
                    rgb_all[:, frame],
                    guides_all[:, frame],
                    context_all[:, frame],
                    state,
                )
            pred = pred.float()
            target = target_all[:, frame]
            rgb = rgb_all[:, frame]
            error = pred - target
            baseline = rgb - target
            values = error.abs().mean((1, 2, 3)).cpu().tolist()
            for index, value in enumerate(values):
                stream_values[index].append(float(value))
            total_abs += error.abs().sum().item()
            total_sq += error.square().sum().item()
            identity_abs += baseline.abs().sum().item()
            identity_sq += baseline.square().sum().item()
            pixels += target.numel()
            if frame == 0:
                warm_abs += error.abs().sum().item()
                warm_pixels += target.numel()
            else:
                steady_abs += error.abs().sum().item()
                steady_pixels += target.numel()
                pred_delta = pred - previous_pred
                target_delta = target - previous_target
                baseline_delta = rgb - previous_rgb
                delta_abs += (pred_delta - target_delta).abs().sum().item()
                identity_delta_abs += (baseline_delta - target_delta).abs().sum().item()
                delta_pixels += target.numel()
            previous_pred = pred
            previous_target = target
            previous_rgb = rgb
        for key, values in zip(selected, stream_values):
            by_sequence[key[0]].extend(values)
            by_eye[str(key[1])].extend(values)
        del rgb_all, target_all, guides_all, context_all, state
    return {
        "split": cache.split,
        "sequence_count": len(cache.sequence_ids),
        "eye_streams": len(cache.streams),
        "frames": pixels // (3 * 512 * 512),
        "mae": total_abs / pixels,
        "psnr": -10.0 * math.log10(max(total_sq / pixels, 1e-12)),
        "identity_mae": identity_abs / pixels,
        "identity_psnr": -10.0 * math.log10(max(identity_sq / pixels, 1e-12)),
        "improvement_pct": 100.0 * (identity_abs - total_abs) / identity_abs,
        "temporal_delta_mae": delta_abs / max(1, delta_pixels),
        "identity_temporal_delta_mae": identity_delta_abs / max(1, delta_pixels),
        "first_frame_mae": warm_abs / max(1, warm_pixels),
        "steady_frame_mae": steady_abs / max(1, steady_pixels),
        "sequence_mae": {key: float(np.mean(values)) for key, values in by_sequence.items()},
        "eye_mae": {key: float(np.mean(values)) for key, values in by_eye.items()},
        "pixels": pixels,
    }


def _load_parent(path: Path, device="cuda"):
    saved = torch.load(path, map_location=device, weights_only=False)
    if saved.get("architecture") != "context_v4":
        raise ValueError("Temporal phase expects a context_v4 parent checkpoint")
    config = ReconstructionConfig(**saved["config"])
    temporal = TemporalConfig()
    model = TemporalStyleContextStudent(config, temporal).to(device)
    model.initialize_v4(saved["model"])
    return model, saved, config, temporal


def _load_temporal(path: Path, device="cuda"):
    saved = torch.load(path, map_location=device, weights_only=False)
    architecture = saved.get("architecture")
    if architecture not in (
        "context_v5_temporal",
        "context_v7_capacity_temporal",
        "context_v8_binocular_capacity_temporal",
        "context_v9_detail_temporal",
        "context_v10_warp_temporal",
        "context_v11_warp_blend_temporal",
        "context_v12_attention_temporal",
        "context_v13_multiscale_attention_temporal",
    ):
        raise ValueError("Checkpoint is not a supported temporal model")
    config = ReconstructionConfig(**saved["base_config"])
    temporal = TemporalConfig(**saved["temporal_config"])
    if architecture == "context_v8_binocular_capacity_temporal":
        from binocular_temporal_student import (
            BinocularCapacityTemporalStyleContextStudent,
            BinocularConfig,
        )
        from capacity_student import CapacityConfig

        capacity = CapacityConfig(**saved["capacity_config"])
        binocular = BinocularConfig(**saved["binocular_config"])
        model = BinocularCapacityTemporalStyleContextStudent(
            config, temporal, capacity, binocular
        ).to(device)
    elif architecture == "context_v7_capacity_temporal":
        from capacity_student import CapacityConfig
        from capacity_temporal_student import CapacityTemporalStyleContextStudent

        capacity = CapacityConfig(**saved["capacity_config"])
        model = CapacityTemporalStyleContextStudent(config, temporal, capacity).to(device)
    elif architecture == "context_v9_detail_temporal":
        from detail_temporal_student import DetailConfig
        from detail_temporal_student import DetailTemporalStyleContextStudent

        detail = DetailConfig(**saved["detail_config"])
        model = DetailTemporalStyleContextStudent(config, temporal, detail).to(device)
    elif architecture == "context_v10_warp_temporal":
        from warp_temporal_student import MotionWarpTemporalStyleContextStudent

        model = MotionWarpTemporalStyleContextStudent(config, temporal).to(device)
    elif architecture == "context_v11_warp_blend_temporal":
        from warp_temporal_student import BlendConfig
        from warp_temporal_student import MotionWarpBlendTemporalStyleContextStudent

        blend = BlendConfig(**saved["blend_config"])
        model = MotionWarpBlendTemporalStyleContextStudent(config, temporal, blend).to(device)
    elif architecture in (
        "context_v12_attention_temporal",
        "context_v13_multiscale_attention_temporal",
    ):
        from attention_temporal_student import AttentionConfig
        from attention_temporal_student import AttentionTemporalStyleContextStudent

        attention = AttentionConfig(**saved["attention_config"])
        model = AttentionTemporalStyleContextStudent(config, temporal, attention).to(device)
    else:
        model = TemporalStyleContextStudent(config, temporal).to(device)
    model.load_state_dict(saved["model"])
    model.eval()
    return model, saved


def _checkpoint(path, model, ema, optimizer, step, best_mae, best_feature, run, schedule):
    payload = {
        "architecture": "context_v5_temporal",
        "base_config": run["base_config"],
        "temporal_config": run["temporal_config"],
        "model": ema.state_dict(),
        "raw_model": model.state_dict(),
        "optimizer": optimizer.state_dict(),
        "step": step,
        "best_mae": best_mae,
        "best_feature": best_feature,
        "run": run,
        "schedule": schedule,
        "cache": run["cache"],
        "spatial_cache": run.get("spatial_cache"),
        "python_rng": random.getstate(),
        "numpy_rng": np.random.get_state(),
        "torch_rng": torch.get_rng_state(),
        "cuda_rng": torch.cuda.get_rng_state_all(),
    }
    tmp = path.with_suffix(".tmp")
    torch.save(payload, tmp)
    tmp.replace(path)


def main() -> None:
    parser = argparse.ArgumentParser()
    choice = parser.add_mutually_exclusive_group(required=True)
    choice.add_argument("--initialize", type=Path)
    choice.add_argument("--resume", type=Path)
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--spatial-cache", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--steps", type=int, default=4000)
    parser.add_argument("--window", type=int, default=8)
    parser.add_argument("--burn-in", type=int, default=2)
    parser.add_argument("--batch", type=int, default=2)
    parser.add_argument("--base-lr", type=float, default=2e-6)
    parser.add_argument("--temporal-lr", type=float, default=2e-5)
    parser.add_argument("--feature-weight", type=float, default=0.05)
    parser.add_argument("--vgg-weight", type=float, default=0.05)
    parser.add_argument("--delta-weight", type=float, default=0.12)
    parser.add_argument("--spatial-prob", type=float, default=0.25)
    parser.add_argument("--eval-every", type=int, default=500)
    parser.add_argument("--seed", type=int, default=137)
    args = parser.parse_args()

    if args.steps < 1 or args.window < 2 or args.batch < 1:
        raise ValueError("steps, window, and batch must be positive")
    if not 0 <= args.burn_in < args.window - 1:
        raise ValueError("burn-in must leave at least one supervised frame")
    if not 0 <= args.spatial_prob <= 1:
        raise ValueError("spatial probability must be between zero and one")
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is required for this training phase")
    if args.initialize and (args.output / "run.json").exists():
        raise ValueError("Fresh initialization requires a new output directory")
    args.output.mkdir(parents=True, exist_ok=True)
    torch.set_num_threads(4)
    torch.manual_seed(args.seed)
    np.random.seed(args.seed)
    random.seed(args.seed)
    torch.backends.cudnn.benchmark = True

    cache = StrictTemporalCache(args.cache, "train")
    validation = StrictTemporalCache(args.cache, "validation")
    spatial = SpatialCache(args.spatial_cache) if args.spatial_cache else None
    rng = np.random.default_rng(args.seed)
    optimizer = None
    if args.initialize:
        model, parent, config, temporal = _load_parent(args.initialize)
        start_step = 0
        best_mae = float("inf")
        best_feature = float("inf")
        optimizer = None
    else:
        saved = torch.load(args.resume, map_location="cuda", weights_only=False)
        if saved.get("architecture") != "context_v5_temporal":
            raise ValueError("Resume checkpoint is not a temporal checkpoint")
        saved_cache = saved.get("cache", {})
        current_cache = json.loads((Path(args.cache) / "complete.json").read_text())
        if saved_cache.get("rows_sha256") != current_cache.get("rows_sha256"):
            raise ValueError("Resume cache identity differs")
        config = ReconstructionConfig(**saved["base_config"])
        temporal = TemporalConfig(**saved["temporal_config"])
        model = TemporalStyleContextStudent(config, temporal).cuda()
        model.load_state_dict(saved["raw_model"])
        start_step = int(saved["step"])
        best_mae = float(saved["best_mae"])
        best_feature = float(saved["best_feature"])
        parent = saved
    ema = deepcopy(model)
    temporal_params = [
        parameter for name, parameter in model.named_parameters() if name.startswith("temporal_")
    ]
    base_params = [
        parameter for name, parameter in model.named_parameters() if not name.startswith("temporal_")
    ]
    if not temporal_params or not base_params:
        raise ValueError("Temporal model parameter partition is empty")
    optimizer = torch.optim.AdamW(
        [
            {"params": base_params, "lr": args.base_lr},
            {"params": temporal_params, "lr": args.temporal_lr},
        ],
        weight_decay=1e-4,
    ) if args.initialize else optimizer
    feature = FeatureDistance().cuda().eval()
    appearance = None
    if args.vgg_weight:
        from vgg_appearance_loss import VGGAppearanceLoss

        appearance = VGGAppearanceLoss().cuda().eval()

    schedule = {
        "steps": args.steps,
        "window": args.window,
        "burn_in": args.burn_in,
        "batch": args.batch,
        "base_lr": args.base_lr,
        "temporal_lr": args.temporal_lr,
        "feature_weight": args.feature_weight,
        "vgg_weight": args.vgg_weight,
        "delta_weight": args.delta_weight,
        "spatial_prob": args.spatial_prob,
        "eval_every": args.eval_every,
    }
    run = {
        "architecture": "context_v5_temporal",
        "base_config": vars(config),
        "temporal_config": vars(temporal),
        "parent_checkpoint": str(args.initialize or args.resume),
        "parent_sha256": hashlib.sha256((args.initialize or args.resume).read_bytes()).hexdigest(),
        "cache": json.loads((Path(args.cache) / "complete.json").read_text()),
        "validation_cache": json.loads((Path(args.cache) / "complete.json").read_text()),
        "spatial_cache": spatial.complete if spatial else None,
        "training_streams": len(cache.streams),
        "validation_streams": len(validation.streams),
        "parameters": sum(parameter.numel() for parameter in model.parameters()),
        "parameter_partition": {
            "base": sum(parameter.numel() for parameter in base_params),
            "temporal": sum(parameter.numel() for parameter in temporal_params),
        },
        "schedule": schedule,
        "test_used": False,
        "selection": "validation streaming MAE and feature distance; test remains untouched",
    }
    if args.resume:
        if saved.get("schedule") != schedule:
            raise ValueError("Resume schedule differs; start an explicit new phase")
        saved_spatial = saved.get("spatial_cache") or {}
        if saved_spatial.get("rows_sha256") != (spatial.rows_sha256 if spatial else None):
            raise ValueError("Resume spatial-cache identity differs")
        ema.load_state_dict(saved["model"])
        optimizer.load_state_dict(saved["optimizer"])
        random.setstate(saved["python_rng"])
        np.random.set_state(saved["numpy_rng"])
        torch.set_rng_state(saved["torch_rng"].cpu())
        torch.cuda.set_rng_state_all([value.cpu() for value in saved["cuda_rng"]])
    atomic_json(args.output / "run.json", run)

    def save(name, step):
        _checkpoint(
            args.output / f"{name}.pt",
            model,
            ema,
            optimizer,
            step,
            best_mae,
            best_feature,
            run,
            schedule,
        )

    def validate(step):
        nonlocal best_mae, best_feature
        metrics = evaluate_streaming(ema, validation, "cuda", batch=max(1, min(8, args.batch * 4)))
        # Feature scoring is intentionally evaluated on a deterministic first
        # frame subset; it is a training metric, not independent acceptance.
        feature_total = feature_count = 0
        with torch.no_grad():
            for selected, arrays in validation.stream_batches(max(1, min(8, args.batch * 4))):
                rgb_np, target_np, guides_np, context_np = arrays
                rgb, target, guides, context = _device_batch(
                    (rgb_np[:, 0], target_np[:, 0], guides_np[:, 0], context_np[:, 0]), "cuda"
                )
                rgb = rgb.float() / 255.0
                target = target.float() / 255.0
                with torch.autocast(device_type="cuda", dtype=torch.bfloat16):
                    prediction, _ = ema.forward_temporal(rgb, guides.float(), context.float(), None)
                feature_total += feature(prediction.float(), target).item() * len(selected)
                feature_count += len(selected)
        metrics["feature_distance_first_frame"] = feature_total / max(1, feature_count)
        if metrics["mae"] < best_mae:
            best_mae = metrics["mae"]
            save("best_mae", step)
        if metrics["feature_distance_first_frame"] < best_feature:
            best_feature = metrics["feature_distance_first_frame"]
            save("best_feature", step)
        save("last", step)
        record = {"step": step, "seconds": time.time() - started, "validation": metrics}
        with (args.output / "history.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record) + "\n")
        print(json.dumps(record), flush=True)

    started = time.time()
    if not args.resume:
        validate(0)
    loss_window = []
    for step in range(start_step + 1, args.steps + 1):
        use_spatial = spatial is not None and float(rng.random()) < args.spatial_prob
        optimizer.zero_grad(set_to_none=True)
        if use_spatial:
            arrays = spatial.sample(rng, args.batch)
            rgb, target, guides, context = _device_batch(arrays, "cuda")
            rgb = rgb.float() / 255.0
            target = target.float() / 255.0
            guides = guides.float()
            context = context.float()
            with torch.autocast(device_type="cuda", dtype=torch.bfloat16):
                prediction, _ = model.forward_temporal(rgb, guides, context, None)
                loss = detail_loss(prediction.float(), target, rgb)
                loss = loss + args.feature_weight * feature(prediction.float(), target)
                if appearance is not None:
                    loss = loss + args.vgg_weight * appearance(prediction, target)
        else:
            selected, starts, indices = cache.sample_window(rng, args.batch, args.window)
            arrays = cache.load_window(indices)
            rgb, target, guides, context = _device_batch(arrays, "cuda")
            rgb = rgb.float() / 255.0
            target = target.float() / 255.0
            guides = guides.float()
            context = context.float()
            rgb, target, guides, context = _augment_sequence(
                rgb, target, guides, context, rng
            )
            state = None
            previous_prediction = previous_target = None
            sequence_loss = []
            for frame in range(args.window):
                if frame < args.burn_in:
                    with torch.no_grad(), torch.autocast(device_type="cuda", dtype=torch.bfloat16):
                        prediction, state = model.forward_temporal(
                            rgb[:, frame], guides[:, frame], context[:, frame], state
                        )
                    previous_prediction = prediction.detach().float()
                    previous_target = target[:, frame]
                    previous_rgb = rgb[:, frame]
                    continue
                with torch.autocast(device_type="cuda", dtype=torch.bfloat16):
                    prediction, state = model.forward_temporal(
                        rgb[:, frame], guides[:, frame], context[:, frame], state
                    )
                    frame_loss = detail_loss(
                        prediction.float(), target[:, frame], rgb[:, frame]
                    )
                    frame_loss = frame_loss + args.feature_weight * feature(
                        prediction.float(), target[:, frame]
                    )
                    if previous_prediction is not None:
                        target_delta = target[:, frame] - previous_target
                        prediction_delta = prediction.float() - previous_prediction
                        frame_loss = frame_loss + args.delta_weight * torch.sqrt(
                            (prediction_delta - target_delta).square() + 1e-6
                        ).mean()
                    if appearance is not None and frame == args.window - 1:
                        frame_loss = frame_loss + args.vgg_weight * appearance(
                            prediction, target[:, frame]
                        )
                sequence_loss.append(frame_loss)
                previous_prediction = prediction.float()
                previous_target = target[:, frame]
                previous_rgb = rgb[:, frame]
            if not sequence_loss:
                raise RuntimeError("Temporal window has no supervised frames")
            loss = torch.stack(sequence_loss).mean()
            if state is not None:
                state = (state[0].detach(), state[1].detach())
        if not torch.isfinite(loss):
            raise RuntimeError(f"Non-finite loss at step {step}")
        loss.backward()
        gradient = torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
        if not torch.isfinite(gradient):
            raise RuntimeError(f"Non-finite gradient at step {step}")
        optimizer.step()
        with torch.no_grad():
            for ema_parameter, model_parameter in zip(ema.parameters(), model.parameters()):
                ema_parameter.lerp_(model_parameter, 0.005)
        loss_window.append(float(loss.item()))
        if step % 25 == 0 or step == 1:
            atomic_json(
                args.output / "status.json",
                {
                    "state": "training",
                    "step": step,
                    "total": args.steps,
                    "loss": float(np.mean(loss_window)),
                    "spatial_step": use_spatial,
                    "best_mae": best_mae,
                    "best_feature": best_feature,
                    "seconds": time.time() - started,
                    "gpu_peak_gib": torch.cuda.max_memory_allocated() / 2**30,
                },
            )
            print(
                json.dumps(
                    {
                        "state": "training",
                        "step": step,
                        "total": args.steps,
                        "loss": float(np.mean(loss_window)),
                        "spatial_step": use_spatial,
                        "seconds": time.time() - started,
                    }
                ),
                flush=True,
            )
            loss_window = []
        if step % args.eval_every == 0 or step == args.steps:
            validate(step)
    atomic_json(
        args.output / "status.json",
        {
            "state": "completed",
            "step": args.steps,
            "best_mae": best_mae,
            "best_feature": best_feature,
            "seconds": time.time() - started,
        },
    )
    print("TEMPORAL TRAINING COMPLETE", flush=True)


if __name__ == "__main__":
    main()
