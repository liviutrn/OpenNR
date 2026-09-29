"""Train the paired-eye OpenNR capacity-temporal continuation."""

from __future__ import annotations

import argparse
from copy import deepcopy
from dataclasses import asdict
import hashlib
import json
import math
from pathlib import Path
import random
import time

import numpy as np
import torch

from binocular_temporal_student import (
    BinocularCapacityTemporalStyleContextStudent,
    BinocularConfig,
)
from capacity_student import CapacityConfig
from perceptual_features import FeatureDistance
from student_v2 import ReconstructionConfig, detail_loss
from temporal_student import TemporalConfig
from train_student import atomic_json
from train_temporal_student import SpatialCache, StrictTemporalCache, _device_batch


def tone_loss(pred, target):
    return (torch.nn.functional.avg_pool2d(pred, 16) - torch.nn.functional.avg_pool2d(target, 16)).abs().mean()


class PairedStrictTemporalCache(StrictTemporalCache):
    """Strict cache view that samples synchronized left/right eye streams."""

    def __init__(self, root: Path, split: str):
        super().__init__(root, split)
        self.paired_sequence_ids = [
            sequence_id
            for sequence_id in self.sequence_ids
            if (sequence_id, 0) in self.streams and (sequence_id, 1) in self.streams
        ]
        if len(self.paired_sequence_ids) != len(self.sequence_ids):
            raise ValueError("Paired temporal cache has a missing eye stream")

    def sample_pair_window(self, rng: np.random.Generator, batch: int, window: int):
        if window < 2 or window > 64:
            raise ValueError("Temporal window must be between 2 and 64")
        selected = [
            self.paired_sequence_ids[int(rng.integers(len(self.paired_sequence_ids)))]
            for _ in range(batch)
        ]
        starts = [int(rng.integers(0, 65 - window)) for _ in range(batch)]
        indices = np.stack(
            [
                np.stack(
                    [
                        self.streams[(sequence_id, eye)][start : start + window]
                        for eye in (0, 1)
                    ]
                )
                for sequence_id, start in zip(selected, starts)
            ]
        )
        return selected, starts, indices

    def load_pair_window(self, indices: np.ndarray):
        return (
            np.array(self.rgb[indices, 0], copy=True),
            np.array(self.rgb[indices, 1], copy=True),
            np.array(self.guides[indices], copy=True),
            np.array(self.context[indices], copy=True),
        )

    def stream_batches(self, batch: int):
        for offset in range(0, len(self.paired_sequence_ids), batch):
            selected = self.paired_sequence_ids[offset : offset + batch]
            indices = np.stack(
                [
                    np.stack([self.streams[(sequence_id, eye)] for eye in (0, 1)])
                    for sequence_id in selected
                ]
            )
            yield selected, self.load_pair_window(indices)


def _augment_pair(rgb, target, guides, context, rng):
    if float(rng.random()) >= 0.5:
        return rgb, target, guides, context
    rgb = rgb.flip(-1)
    target = target.flip(-1)
    guides = guides.flip(-1)
    context = context.flip(-1)
    guides[:, :, :, 1] *= -1
    context[:, :, :, 4] *= -1
    return rgb, target, guides, context


@torch.no_grad()
def evaluate_pair_streaming(model, cache, device="cuda", batch=4):
    model.eval()
    total_abs = total_sq = identity_abs = identity_sq = 0.0
    delta_abs = identity_delta_abs = 0.0
    pixels = delta_pixels = 0
    warm_abs = warm_pixels = steady_abs = steady_pixels = 0.0
    by_sequence = {}
    by_eye = {"0": [], "1": []}
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
        previous_pred = previous_target = previous_rgb = None
        stream_values = [[ ] for _ in selected]
        for frame in range(rgb_all.shape[2]):
            with torch.autocast(device_type="cuda", dtype=torch.bfloat16):
                pred, state = model.forward_pair_temporal(
                    rgb_all[:, :, frame],
                    guides_all[:, :, frame],
                    context_all[:, :, frame],
                    state,
                )
            pred = pred.float()
            target = target_all[:, :, frame]
            rgb = rgb_all[:, :, frame]
            # The binocular model returns predictions already flattened across
            # the two eyes; only the paired cache tensors need reshaping.
            pred_flat = pred
            target_flat = target.reshape(-1, *target.shape[2:])
            rgb_flat = rgb.reshape(-1, *rgb.shape[2:])
            error = pred_flat - target_flat
            baseline = rgb_flat - target_flat
            eye_values = error.abs().mean((1, 2, 3)).reshape(len(selected), 2).cpu().tolist()
            for index, values in enumerate(eye_values):
                stream_values[index].extend(float(value) for value in values)
                by_eye["0"].append(float(values[0]))
                by_eye["1"].append(float(values[1]))
            total_abs += error.abs().sum().item()
            total_sq += error.square().sum().item()
            identity_abs += baseline.abs().sum().item()
            identity_sq += baseline.square().sum().item()
            pixels += target_flat.numel()
            if frame == 0:
                warm_abs += error.abs().sum().item()
                warm_pixels += target_flat.numel()
            else:
                steady_abs += error.abs().sum().item()
                steady_pixels += target_flat.numel()
                pred_delta = pred_flat - previous_pred
                target_delta = target_flat - previous_target
                baseline_delta = rgb_flat - previous_rgb
                delta_abs += (pred_delta - target_delta).abs().sum().item()
                identity_delta_abs += (baseline_delta - target_delta).abs().sum().item()
                delta_pixels += target_flat.numel()
            previous_pred = pred_flat
            previous_target = target_flat
            previous_rgb = rgb_flat
        for sequence_id, values in zip(selected, stream_values):
            by_sequence.setdefault(sequence_id, []).extend(values)
        del rgb_all, target_all, guides_all, context_all, state
    return {
        "split": cache.split,
        "sequence_count": len(cache.paired_sequence_ids),
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
    architecture = saved.get("architecture")
    if architecture not in ("context_v7_capacity_temporal", "context_v8_binocular_capacity_temporal"):
        raise ValueError("Binocular phase expects a capacity-temporal parent checkpoint")
    config = ReconstructionConfig(**saved["base_config"])
    temporal = TemporalConfig(**saved["temporal_config"])
    capacity = CapacityConfig(**saved["capacity_config"])
    return saved, config, temporal, capacity


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--initialize", type=Path, required=True)
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--spatial-cache", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--steps", type=int, default=2000)
    parser.add_argument("--window", type=int, default=8)
    parser.add_argument("--burn-in", type=int, default=2)
    parser.add_argument("--batch", type=int, default=1)
    parser.add_argument("--base-lr", type=float, default=1e-7)
    parser.add_argument("--temporal-lr", type=float, default=1e-6)
    parser.add_argument("--capacity-lr", type=float, default=5e-6)
    parser.add_argument("--binocular-lr", type=float, default=5e-6)
    parser.add_argument("--feature-weight", type=float, default=0.05)
    parser.add_argument("--vgg-weight", type=float, default=0.10)
    parser.add_argument("--tone-weight", type=float, default=0.10)
    parser.add_argument("--delta-weight", type=float, default=0.12)
    parser.add_argument("--spatial-prob", type=float, default=0.25)
    parser.add_argument("--binocular-width", type=int, default=128)
    parser.add_argument("--binocular-blocks", type=int, default=6)
    parser.add_argument("--binocular-delta-scale", type=float, default=0.12)
    parser.add_argument("--eval-every", type=int, default=250)
    parser.add_argument("--seed", type=int, default=991)
    args = parser.parse_args()
    if args.steps < 1 or args.window < 2 or args.batch < 1:
        raise ValueError("steps, window, and batch must be positive")
    if not 0 <= args.burn_in < args.window - 1:
        raise ValueError("burn-in must leave at least one supervised frame")
    if not 0 <= args.spatial_prob <= 1:
        raise ValueError("spatial probability must be between zero and one")
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is required for binocular training")
    if (args.output / "run.json").exists():
        raise ValueError("Fresh initialization requires a new output directory")
    args.output.mkdir(parents=True, exist_ok=True)
    torch.set_num_threads(4)
    torch.manual_seed(args.seed)
    np.random.seed(args.seed)
    random.seed(args.seed)
    torch.backends.cudnn.benchmark = True

    cache = PairedStrictTemporalCache(args.cache, "train")
    validation = PairedStrictTemporalCache(args.cache, "validation")
    spatial = SpatialCache(args.spatial_cache) if args.spatial_cache else None
    parent_path = args.initialize.resolve()
    parent_sha256 = hashlib.sha256(parent_path.read_bytes()).hexdigest()
    saved, config, temporal, capacity = _load_parent(parent_path)
    binocular = BinocularConfig(
        width=args.binocular_width,
        blocks=args.binocular_blocks,
        delta_scale=args.binocular_delta_scale,
    )
    model = BinocularCapacityTemporalStyleContextStudent(
        config, temporal, capacity, binocular
    ).cuda()
    model.initialize_v5(saved["model"])
    ema = deepcopy(model)
    binocular_params = [
        parameter
        for name, parameter in model.named_parameters()
        if name.startswith("binocular_")
    ]
    capacity_params = [
        parameter
        for name, parameter in model.named_parameters()
        if name.startswith("capacity_")
    ]
    temporal_params = [
        parameter
        for name, parameter in model.named_parameters()
        if name.startswith("temporal_")
    ]
    base_params = [
        parameter
        for name, parameter in model.named_parameters()
        if not name.startswith(("binocular_", "capacity_", "temporal_"))
    ]
    optimizer = torch.optim.AdamW(
        [
            {"params": base_params, "lr": args.base_lr},
            {"params": temporal_params, "lr": args.temporal_lr},
            {"params": capacity_params, "lr": args.capacity_lr},
            {"params": binocular_params, "lr": args.binocular_lr},
        ],
        weight_decay=1e-4,
    )
    feature = FeatureDistance().cuda().eval()
    appearance = None
    if args.vgg_weight:
        from vgg_appearance_loss import VGGAppearanceLoss

        appearance = VGGAppearanceLoss().cuda().eval()
    rng = np.random.default_rng(args.seed)
    schedule = {
        "steps": args.steps,
        "window": args.window,
        "burn_in": args.burn_in,
        "batch": args.batch,
        "base_lr": args.base_lr,
        "temporal_lr": args.temporal_lr,
        "capacity_lr": args.capacity_lr,
        "binocular_lr": args.binocular_lr,
        "feature_weight": args.feature_weight,
        "vgg_weight": args.vgg_weight,
        "tone_weight": args.tone_weight,
        "delta_weight": args.delta_weight,
        "spatial_prob": args.spatial_prob,
        "binocular_width": args.binocular_width,
        "binocular_blocks": args.binocular_blocks,
        "binocular_delta_scale": args.binocular_delta_scale,
        "eval_every": args.eval_every,
    }
    run = {
        "architecture": BinocularCapacityTemporalStyleContextStudent.architecture,
        "base_config": asdict(config),
        "temporal_config": asdict(temporal),
        "capacity_config": asdict(capacity),
        "binocular_config": asdict(binocular),
        "parent_checkpoint": str(parent_path),
        "parent_sha256": parent_sha256,
        "cache_path": str(Path(args.cache).resolve()),
        "cache": cache.complete,
        "validation_cache": validation.complete,
        "spatial_cache": spatial.complete if spatial else None,
        "training_sequences": len(cache.paired_sequence_ids),
        "validation_sequences": len(validation.paired_sequence_ids),
        "parameters": sum(parameter.numel() for parameter in model.parameters()),
        "parameter_partition": {
            "base": sum(parameter.numel() for parameter in base_params),
            "temporal": sum(parameter.numel() for parameter in temporal_params),
            "capacity": sum(parameter.numel() for parameter in capacity_params),
            "binocular": sum(parameter.numel() for parameter in binocular_params),
        },
        "schedule": schedule,
        "test_used": False,
        "spatial_pair_policy": "duplicate single-eye spatial sample across both pair slots; no teacher or opposite-eye target is used",
        "selection": "paired strict sequence streaming MAE and first-frame feature distance; test remains untouched",
    }
    atomic_json(args.output / "run.json", run)
    best_mae = float("inf")
    best_feature = float("inf")
    started = time.time()

    def checkpoint(path, step):
        payload = {
            "architecture": BinocularCapacityTemporalStyleContextStudent.architecture,
            "base_config": run["base_config"],
            "temporal_config": run["temporal_config"],
            "capacity_config": run["capacity_config"],
            "binocular_config": run["binocular_config"],
            "model": ema.state_dict(),
            "raw_model": model.state_dict(),
            "optimizer": optimizer.state_dict(),
            "step": step,
            "best_mae": best_mae,
            "best_feature": best_feature,
            "run": run,
            "schedule": schedule,
            "cache": run["cache"],
            "spatial_cache": run["spatial_cache"],
            "parent_checkpoint": run["parent_checkpoint"],
            "parent_sha256": run["parent_sha256"],
            "python_rng": random.getstate(),
            "numpy_rng": np.random.get_state(),
            "torch_rng": torch.get_rng_state(),
            "cuda_rng": torch.cuda.get_rng_state_all(),
        }
        tmp = path.with_suffix(".tmp")
        torch.save(payload, tmp)
        tmp.replace(path)

    def validate(step):
        nonlocal best_mae, best_feature
        metrics = evaluate_pair_streaming(
            ema, validation, "cuda", batch=max(1, min(4, args.batch * 4))
        )
        feature_total = feature_count = 0
        with torch.no_grad():
            for selected, arrays in validation.stream_batches(max(1, min(4, args.batch * 4))):
                rgb_np, target_np, guides_np, context_np = arrays
                rgb, target, guides, context = _device_batch(
                    (
                        rgb_np[:, :, 0],
                        target_np[:, :, 0],
                        guides_np[:, :, 0],
                        context_np[:, :, 0],
                    ),
                    "cuda",
                )
                rgb = rgb.float() / 255.0
                target = target.float() / 255.0
                with torch.autocast(device_type="cuda", dtype=torch.bfloat16):
                    prediction, _ = ema.forward_pair_temporal(
                        rgb, guides.float(), context.float(), None
                    )
                feature_total += feature(
                    prediction.float(), target.reshape(-1, *target.shape[2:])
                ).item() * len(selected) * 2
                feature_count += len(selected) * 2
        metrics["feature_distance_first_frame"] = feature_total / max(1, feature_count)
        if metrics["mae"] < best_mae:
            best_mae = metrics["mae"]
            checkpoint(args.output / "best_mae.pt", step)
        if metrics["feature_distance_first_frame"] < best_feature:
            best_feature = metrics["feature_distance_first_frame"]
            checkpoint(args.output / "best_feature.pt", step)
        checkpoint(args.output / "last.pt", step)
        record = {"step": step, "seconds": time.time() - started, "validation": metrics}
        with (args.output / "history.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record) + "\n")
        print(json.dumps(record), flush=True)

    validate(0)
    loss_window = []
    for step in range(1, args.steps + 1):
        use_spatial = spatial is not None and float(rng.random()) < args.spatial_prob
        optimizer.zero_grad(set_to_none=True)
        if use_spatial:
            arrays = spatial.sample(rng, args.batch)
            rgb, target, guides, context = _device_batch(arrays, "cuda")
            rgb = rgb.float() / 255.0
            target = target.float() / 255.0
            guides = guides.float()
            context = context.float()
            rgb = rgb[:, None].expand(-1, 2, -1, -1, -1).contiguous()
            target = target[:, None].expand(-1, 2, -1, -1, -1).contiguous()
            guides = guides[:, None].expand(-1, 2, -1, -1, -1).contiguous()
            context = context[:, None].expand(-1, 2, -1, -1, -1).contiguous()
            with torch.autocast(device_type="cuda", dtype=torch.bfloat16):
                prediction, _ = model.forward_pair_temporal(rgb, guides, context, None)
                prediction = prediction.float()
                flat_target = target.reshape(-1, *target.shape[2:])
                flat_rgb = rgb.reshape(-1, *rgb.shape[2:])
                loss = detail_loss(prediction, flat_target, flat_rgb)
                loss = loss + args.feature_weight * feature(prediction, flat_target)
                if appearance is not None:
                    loss = loss + args.vgg_weight * appearance(prediction, flat_target)
                if args.tone_weight:
                    loss = loss + args.tone_weight * tone_loss(prediction, flat_target)
        else:
            selected, starts, indices = cache.sample_pair_window(rng, args.batch, args.window)
            arrays = cache.load_pair_window(indices)
            rgb, target, guides, context = _device_batch(arrays, "cuda")
            rgb = rgb.float() / 255.0
            target = target.float() / 255.0
            guides = guides.float()
            context = context.float()
            rgb, target, guides, context = _augment_pair(
                rgb, target, guides, context, rng
            )
            state = None
            previous_prediction = previous_target = None
            sequence_loss = []
            for frame in range(args.window):
                if frame < args.burn_in:
                    with torch.no_grad(), torch.autocast(
                        device_type="cuda", dtype=torch.bfloat16
                    ):
                        prediction, state = model.forward_pair_temporal(
                            rgb[:, :, frame],
                            guides[:, :, frame],
                            context[:, :, frame],
                            state,
                        )
                    previous_prediction = prediction.detach().float()
                    previous_target = target[:, :, frame].reshape(-1, *target.shape[3:])
                    continue
                with torch.autocast(device_type="cuda", dtype=torch.bfloat16):
                    prediction, state = model.forward_pair_temporal(
                        rgb[:, :, frame],
                        guides[:, :, frame],
                        context[:, :, frame],
                        state,
                    )
                    flat_target = target[:, :, frame].reshape(-1, *target.shape[3:])
                    flat_rgb = rgb[:, :, frame].reshape(-1, *rgb.shape[3:])
                    prediction = prediction.float()
                    frame_loss = detail_loss(prediction, flat_target, flat_rgb)
                    frame_loss = frame_loss + args.feature_weight * feature(
                        prediction, flat_target
                    )
                    if previous_prediction is not None:
                        target_delta = flat_target - previous_target
                        prediction_delta = prediction - previous_prediction
                        frame_loss = frame_loss + args.delta_weight * torch.sqrt(
                            (prediction_delta - target_delta).square() + 1e-6
                        ).mean()
                    if appearance is not None and frame == args.window - 1:
                        frame_loss = frame_loss + args.vgg_weight * appearance(
                            prediction, flat_target
                        )
                    if args.tone_weight:
                        frame_loss = frame_loss + args.tone_weight * tone_loss(
                            prediction, flat_target
                        )
                sequence_loss.append(frame_loss)
                previous_prediction = prediction
                previous_target = flat_target
            if not sequence_loss:
                raise RuntimeError("Temporal window has no supervised frame")
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
    print("BINOCULAR TEMPORAL TRAINING COMPLETE", flush=True)


if __name__ == "__main__":
    main()
