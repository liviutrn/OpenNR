"""Train the v10 motion-compensated temporal student on strict clips."""

from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
import random
import time

import numpy as np
import torch

from perceptual_features import FeatureDistance
from student_v2 import ReconstructionConfig, detail_loss
from temporal_student import TemporalConfig
from train_student import atomic_json
from train_temporal_student import (
    SpatialCache,
    StrictTemporalCache,
    _augment_sequence,
    _device_batch,
    evaluate_streaming,
)
from warp_temporal_student import (
    BlendConfig,
    MotionWarpBlendTemporalStyleContextStudent,
    MotionWarpTemporalStyleContextStudent,
)


def _checkpoint(path, model, ema, optimizer, step, best_mae, best_feature, run, schedule):
    payload = {
        "architecture": run["architecture"],
        "base_config": run["base_config"],
        "temporal_config": run["temporal_config"],
        "blend_config": run.get("blend_config"),
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


def _load_parent(path: Path, device="cuda", blend=None):
    saved = torch.load(path, map_location=device, weights_only=False)
    if saved.get("architecture") != "context_v5_temporal":
        raise ValueError("Warp phase expects a context_v5_temporal parent checkpoint")
    config = ReconstructionConfig(**saved["base_config"])
    temporal = TemporalConfig(**saved["temporal_config"])
    if blend is None:
        model = MotionWarpTemporalStyleContextStudent(config, temporal).to(device)
    else:
        model = MotionWarpBlendTemporalStyleContextStudent(
            config, temporal, blend
        ).to(device)
    model.initialize_v9(saved["model"])
    return model, saved, config, temporal


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--initialize", type=Path, required=True)
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--spatial-cache", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--steps", type=int, default=512)
    parser.add_argument("--window", type=int, default=8)
    parser.add_argument("--burn-in", type=int, default=2)
    parser.add_argument("--batch", type=int, default=2)
    parser.add_argument("--base-lr", type=float, default=1e-6)
    parser.add_argument("--temporal-lr", type=float, default=2e-5)
    parser.add_argument("--blend-lr", type=float, default=1e-3)
    parser.add_argument("--feature-weight", type=float, default=0.05)
    parser.add_argument("--vgg-weight", type=float, default=0.05)
    parser.add_argument("--delta-weight", type=float, default=0.12)
    parser.add_argument("--spatial-probability", type=float, default=0.0)
    parser.add_argument(
        "--blend",
        action="store_true",
        help="Add a zero-initialized direct full-resolution warped-history gate",
    )
    parser.add_argument("--blend-scale", type=float, default=0.25)
    parser.add_argument("--eval-every", type=int, default=128)
    parser.add_argument("--seed", type=int, default=719)
    args = parser.parse_args()

    if args.steps < 1 or args.window < 2 or args.batch < 1:
        raise ValueError("steps, window, and batch must be positive")
    if not 0 <= args.burn_in < args.window - 1:
        raise ValueError("burn-in must leave at least one supervised frame")
    if not 0 <= args.spatial_probability <= 1:
        raise ValueError("spatial probability must be between zero and one")
    if args.blend_scale <= 0:
        raise ValueError("blend scale must be positive")
    if args.blend_lr < 0:
        raise ValueError("blend learning rate must not be negative")
    if args.spatial_probability and not args.spatial_cache:
        raise ValueError("spatial probability requires --spatial-cache")
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

    cache = StrictTemporalCache(args.cache, "train")
    validation = StrictTemporalCache(args.cache, "validation")
    spatial = SpatialCache(args.spatial_cache) if args.spatial_cache else None
    rng = np.random.default_rng(args.seed)
    parent_path = args.initialize.resolve()
    parent_sha256 = hashlib.sha256(parent_path.read_bytes()).hexdigest()
    blend_config = BlendConfig(scale=args.blend_scale) if args.blend else None
    model, parent, config, temporal = _load_parent(parent_path, blend=blend_config)
    ema = deepcopy(model)
    temporal_params = [
        parameter for name, parameter in model.named_parameters()
        if name.startswith("temporal_")
    ]
    blend_params = [
        parameter for name, parameter in model.named_parameters()
        if name.startswith("warp_blend_gate.")
    ] if args.blend else []
    base_params = [
        parameter for name, parameter in model.named_parameters()
        if not name.startswith("temporal_") and not name.startswith("warp_blend_gate.")
    ]
    parameter_groups = [
        {"params": base_params, "lr": args.base_lr},
        {"params": temporal_params, "lr": args.temporal_lr},
    ]
    if args.blend:
        parameter_groups.append({"params": blend_params, "lr": args.blend_lr})
    optimizer = torch.optim.AdamW(parameter_groups, weight_decay=1e-4)
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
        "blend_lr": args.blend_lr,
        "feature_weight": args.feature_weight,
        "vgg_weight": args.vgg_weight,
        "delta_weight": args.delta_weight,
        "spatial_probability": args.spatial_probability,
        "blend": args.blend,
        "blend_scale": args.blend_scale,
        "eval_every": args.eval_every,
    }
    architecture = (
        "context_v11_warp_blend_temporal"
        if args.blend
        else "context_v10_warp_temporal"
    )
    run = {
        "architecture": architecture,
        "base_config": vars(config),
        "temporal_config": vars(temporal),
        "blend_config": vars(blend_config) if blend_config else None,
        "parent_checkpoint": str(parent_path),
        "parent_sha256": parent_sha256,
        "parent_architecture": parent.get("architecture"),
        "parent_step": int(parent.get("step", -1)),
        "motion_warp_contract": {
            "source": "strict cache guides channels 1/2",
            "sign": "grid_sample previous at base + displacement",
            "normalization": "cache motion is native color-pixel displacement / 128",
            "padding": "border",
            "optical_flow_inferred": False,
        },
        "cache": json.loads((Path(args.cache) / "complete.json").read_text()),
        "validation_cache": json.loads((Path(args.cache) / "complete.json").read_text()),
        "spatial_cache": spatial.complete if spatial else None,
        "training_streams": len(cache.streams),
        "validation_streams": len(validation.streams),
        "parameters": sum(parameter.numel() for parameter in model.parameters()),
        "parameter_partition": {
            "base": sum(parameter.numel() for parameter in base_params),
            "temporal": sum(parameter.numel() for parameter in temporal_params),
            "blend": sum(parameter.numel() for parameter in blend_params),
        },
        "schedule": schedule,
        "test_used": False,
        "selection": "strict streaming validation MAE and first-frame feature distance; test remains untouched",
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
        metrics = evaluate_streaming(
            ema, validation, "cuda", batch=max(1, min(8, args.batch * 4))
        )
        feature_total = feature_count = 0
        with torch.no_grad():
            for selected, arrays in validation.stream_batches(
                max(1, min(8, args.batch * 4))
            ):
                rgb_np, target_np, guides_np, context_np = arrays
                rgb, target, guides, context = _device_batch(
                    (rgb_np[:, 0], target_np[:, 0], guides_np[:, 0], context_np[:, 0]),
                    "cuda",
                )
                rgb = rgb.float() / 255.0
                target = target.float() / 255.0
                with torch.autocast(device_type="cuda", dtype=torch.bfloat16):
                    prediction, _ = ema.forward_temporal(
                        rgb, guides.float(), context.float(), None
                    )
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

    validate(0)
    loss_window = []
    for step in range(1, args.steps + 1):
        use_spatial = spatial is not None and float(rng.random()) < args.spatial_probability
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
            selected, starts, indices = cache.sample_window(
                rng, args.batch, args.window
            )
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
                    with torch.no_grad(), torch.autocast(
                        device_type="cuda", dtype=torch.bfloat16
                    ):
                        prediction, state = model.forward_temporal(
                            rgb[:, frame], guides[:, frame], context[:, frame], state
                        )
                    previous_prediction = prediction.detach().float()
                    previous_target = target[:, frame]
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
    print("MOTION-WARP TEMPORAL TRAINING COMPLETE", flush=True)


if __name__ == "__main__":
    main()
