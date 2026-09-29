"""Train the zero-initialized high-capacity appearance refinement branch.

Training mixes the merged spatial corpus with strict reset-qualified frames.
The held-out strict sequence split is the selection authority; no test rows are
read by the training loop.
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

from capacity_student import CapacityConfig, CapacityStyleContextStudent
from perceptual_features import FeatureDistance
from student_v2 import ReconstructionConfig, detail_loss
from train_student import atomic_json
from train_temporal_student import StrictTemporalCache, _device_batch


class MergedSpatialPool:
    """Training-only sampler over merged-cache patches."""

    def __init__(self, root: Path):
        self.root = Path(root).resolve()
        self.complete = json.loads((self.root / "complete.json").read_text(encoding="utf-8"))
        if self.complete.get("test_used_for_tuning"):
            raise ValueError("Merged spatial cache is marked as test-used-for-tuning")
        self.plan = json.loads((self.root / "patches.json").read_text(encoding="utf-8"))
        self.ids = np.asarray(
            [i for i, patch in enumerate(self.plan) if patch.get("split") == "train"],
            dtype=np.int64,
        )
        self.rgb = np.load(self.root / "rgb.npy", mmap_mode="r")
        self.guides = np.load(self.root / "guides.npy", mmap_mode="r")
        self.context = np.load(self.root / "context.npy", mmap_mode="r")
        self.row_for_patch = np.asarray(
            [int(patch["row"]) for patch in self.plan], dtype=np.int64
        )

    def sample(self, rng: np.random.Generator):
        patch = int(self.ids[int(rng.integers(len(self.ids)))])
        row = int(self.row_for_patch[patch])
        return (
            np.array(self.rgb[patch, 0], copy=True),
            np.array(self.rgb[patch, 1], copy=True),
            np.array(self.guides[patch], copy=True),
            np.array(self.context[row], copy=True),
        )


class StrictSpatialPool:
    """Training-only single-frame view of the strict temporal cache."""

    def __init__(self, root: Path):
        self.cache = StrictTemporalCache(root, "train")
        self.complete = self.cache.complete
        self.rows = np.asarray(
            [index for index, row in enumerate(self.cache.rows) if row.get("split") == "train"],
            dtype=np.int64,
        )

    def sample(self, rng: np.random.Generator):
        index = int(self.rows[int(rng.integers(len(self.rows)))])
        return (
            np.array(self.cache.rgb[index, 0], copy=True),
            np.array(self.cache.rgb[index, 1], copy=True),
            np.array(self.cache.guides[index], copy=True),
            np.array(self.cache.context[index], copy=True),
        )


def _sample_batch(
    merged: MergedSpatialPool,
    strict: StrictSpatialPool,
    rng: np.random.Generator,
    batch: int,
    strict_probability: float,
):
    values = [
        strict.sample(rng) if float(rng.random()) < strict_probability else merged.sample(rng)
        for _ in range(batch)
    ]
    return tuple(np.stack([value[column] for value in values]) for column in range(4))


def _augment(rgb, target, guides, context, rng: np.random.Generator):
    if float(rng.random()) >= 0.5:
        return rgb, target, guides, context
    rgb = rgb.flip(-1)
    target = target.flip(-1)
    guides = guides.flip(-1)
    context = context.flip(-1)
    guides[:, 1] *= -1
    context[:, 4] *= -1
    return rgb, target, guides, context


def tone_loss(pred, target):
    return (F.avg_pool2d(pred, 16) - F.avg_pool2d(target, 16)).abs().mean()


@torch.no_grad()
def evaluate_strict(model, cache: StrictTemporalCache, device="cuda", batch=4, feature=None):
    """Evaluate all frames in strict streams as independent spatial inputs."""

    model.eval()
    total_abs = total_sq = identity_abs = identity_sq = 0.0
    pixels = 0
    feature_total = feature_count = 0.0
    by_sequence: dict[str, list[float]] = defaultdict(list)
    for selected, arrays in cache.stream_batches(max(1, batch)):
        rgb_np, target_np, guides_np, context_np = arrays
        # Small frame chunks keep the 512x512 activation footprint bounded.
        for start in range(0, 64, 2):
            stop = min(64, start + 2)
            count = stop - start
            rgb, target, guides, context = _device_batch(
                (
                    rgb_np[:, start:stop].reshape(-1, 3, 512, 512),
                    target_np[:, start:stop].reshape(-1, 3, 512, 512),
                    guides_np[:, start:stop].reshape(-1, 5, 128, 128),
                    context_np[:, start:stop].reshape(-1, 8, 96, 96),
                ),
                device,
            )
            rgb = rgb.float() / 255.0
            target = target.float() / 255.0
            with torch.autocast(device_type="cuda", dtype=torch.bfloat16):
                prediction = model(rgb, guides.float(), context.float())
            error = prediction.float() - target
            baseline = rgb - target
            total_abs += error.abs().sum().item()
            total_sq += error.square().sum().item()
            identity_abs += baseline.abs().sum().item()
            identity_sq += baseline.square().sum().item()
            pixels += target.numel()
            values = error.abs().mean((1, 2, 3)).cpu().numpy().reshape(len(selected), count)
            for index, key in enumerate(selected):
                by_sequence[key[0]].extend(values[index].tolist())
            if start == 0 and feature is not None:
                prediction_frames = prediction.view(len(selected), count, *prediction.shape[1:])
                target_frames = target.view(len(selected), count, *target.shape[1:])
                feature_total += feature(
                    prediction_frames[:, 0].float(), target_frames[:, 0]
                ).item() * len(selected)
                feature_count += len(selected)
            del rgb, target, guides, context, prediction, error, baseline
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
        "sequence_mae": {key: float(np.mean(values)) for key, values in by_sequence.items()},
        "feature_distance_first_frame": feature_total / max(1.0, feature_count),
        "pixels": pixels,
    }


def _load_parent(path: Path, device="cuda"):
    saved = torch.load(path, map_location=device, weights_only=False)
    if saved.get("architecture") != "context_v4":
        raise ValueError("Capacity phase expects a context_v4 parent checkpoint")
    config = ReconstructionConfig(**saved["config"])
    capacity = CapacityConfig()
    model = CapacityStyleContextStudent(config, capacity).to(device)
    model.initialize_v4(saved["model"])
    return model, saved, config, capacity


def _checkpoint(path, model, ema, optimizer, step, best_mae, best_feature, run, schedule):
    payload = {
        "architecture": "context_v6_capacity",
        "config": run["config"],
        "capacity_config": run["capacity_config"],
        "model": ema.state_dict(),
        "raw_model": model.state_dict(),
        "optimizer": optimizer.state_dict(),
        "step": step,
        "best_mae": best_mae,
        "best_feature": best_feature,
        "run": run,
        "schedule": schedule,
        "merged_cache": run["merged_cache"],
        "strict_cache": run["strict_cache"],
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
    parser.add_argument("--initialize", type=Path, required=True)
    parser.add_argument("--merged-cache", type=Path, required=True)
    parser.add_argument("--strict-cache", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--steps", type=int, default=8000)
    parser.add_argument("--batch", type=int, default=2)
    parser.add_argument("--base-lr", type=float, default=1e-6)
    parser.add_argument("--capacity-lr", type=float, default=1e-5)
    parser.add_argument("--feature-weight", type=float, default=0.05)
    parser.add_argument("--vgg-weight", type=float, default=0.10)
    parser.add_argument("--tone-weight", type=float, default=0.10)
    parser.add_argument("--strict-probability", type=float, default=0.40)
    parser.add_argument("--capacity-width", type=int, default=128)
    parser.add_argument("--capacity-blocks", type=int, default=6)
    parser.add_argument("--delta-scale", type=float, default=0.12)
    parser.add_argument("--eval-every", type=int, default=500)
    parser.add_argument("--seed", type=int, default=241)
    args = parser.parse_args()
    if args.steps < 1 or args.batch < 1:
        raise ValueError("steps and batch must be positive")
    if not 0 <= args.strict_probability <= 1:
        raise ValueError("strict probability must be between zero and one")
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is required for this training phase")
    if (args.output / "run.json").exists():
        raise ValueError("Fresh initialization requires a new output directory")
    args.output.mkdir(parents=True, exist_ok=True)
    torch.set_num_threads(4)
    torch.manual_seed(args.seed)
    np.random.seed(args.seed)
    random.seed(args.seed)
    torch.backends.cudnn.benchmark = True

    merged = MergedSpatialPool(args.merged_cache)
    strict_train = StrictSpatialPool(args.strict_cache)
    strict_validation = StrictTemporalCache(args.strict_cache, "validation")
    parent_path = args.initialize.resolve()
    parent_sha256 = hashlib.sha256(parent_path.read_bytes()).hexdigest()
    model, parent, config, default_capacity = _load_parent(parent_path)
    capacity = CapacityConfig(
        width=args.capacity_width, blocks=args.capacity_blocks, delta_scale=args.delta_scale
    )
    # Rebuild with the requested capacity if the CLI differs from defaults.
    if capacity != default_capacity:
        model = CapacityStyleContextStudent(config, capacity).cuda()
        model.initialize_v4(parent["model"])
    ema = deepcopy(model)
    capacity_params = [
        parameter for name, parameter in model.named_parameters() if name.startswith("capacity_")
    ]
    base_params = [
        parameter for name, parameter in model.named_parameters() if not name.startswith("capacity_")
    ]
    optimizer = torch.optim.AdamW(
        [
            {"params": base_params, "lr": args.base_lr},
            {"params": capacity_params, "lr": args.capacity_lr},
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
        "batch": args.batch,
        "base_lr": args.base_lr,
        "capacity_lr": args.capacity_lr,
        "feature_weight": args.feature_weight,
        "vgg_weight": args.vgg_weight,
        "tone_weight": args.tone_weight,
        "strict_probability": args.strict_probability,
        "capacity_width": args.capacity_width,
        "capacity_blocks": args.capacity_blocks,
        "delta_scale": args.delta_scale,
        "eval_every": args.eval_every,
    }
    run = {
        "architecture": "context_v6_capacity",
        "config": vars(config),
        "capacity_config": vars(capacity),
        "parent_checkpoint": str(parent_path),
        "parent_sha256": parent_sha256,
        "merged_cache": merged.complete,
        "strict_cache": strict_train.complete,
        "strict_validation_rows_sha256": strict_validation.rows_sha256,
        "merged_training_patches": int(len(merged.ids)),
        "strict_training_rows": int(len(strict_train.rows)),
        "parameters": sum(parameter.numel() for parameter in model.parameters()),
        "parameter_partition": {
            "base": sum(parameter.numel() for parameter in base_params),
            "capacity": sum(parameter.numel() for parameter in capacity_params),
        },
        "schedule": schedule,
        "vgg_appearance": appearance.provenance if appearance is not None else None,
        "test_used": False,
        "selection": "strict validation streaming MAE and first-frame feature distance; test remains untouched",
    }
    atomic_json(args.output / "run.json", run)

    best_mae = float("inf")
    best_feature = float("inf")
    started = time.time()

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
        metrics = evaluate_strict(ema, strict_validation, "cuda", batch=args.batch, feature=feature)
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

    validate(0)
    loss_window = []
    for step in range(1, args.steps + 1):
        arrays = _sample_batch(
            merged, strict_train, rng, args.batch, args.strict_probability
        )
        rgb, target, guides, context = _device_batch(arrays, "cuda")
        rgb = rgb.float() / 255.0
        target = target.float() / 255.0
        guides = guides.float()
        context = context.float()
        rgb, target, guides, context = _augment(rgb, target, guides, context, rng)
        model.train()
        optimizer.zero_grad(set_to_none=True)
        lr = args.base_lr * (0.1 + 0.9 * 0.5 * (1.0 + math.cos(math.pi * (step - 1) / args.steps)))
        capacity_lr = args.capacity_lr * (
            0.1 + 0.9 * 0.5 * (1.0 + math.cos(math.pi * (step - 1) / args.steps))
        )
        optimizer.param_groups[0]["lr"] = lr
        optimizer.param_groups[1]["lr"] = capacity_lr
        with torch.autocast(device_type="cuda", dtype=torch.bfloat16):
            prediction = model(rgb, guides, context)
            loss = detail_loss(prediction.float(), target, rgb)
            loss = loss + args.feature_weight * feature(prediction.float(), target)
            if appearance is not None:
                loss = loss + args.vgg_weight * appearance(prediction, target)
            if args.tone_weight:
                loss = loss + args.tone_weight * tone_loss(prediction.float(), target)
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
                    "lr": lr,
                    "capacity_lr": capacity_lr,
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
    print("CAPACITY TRAINING COMPLETE", flush=True)


if __name__ == "__main__":
    main()
