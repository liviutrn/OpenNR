"""Train a high-capacity causal refinement on top of the v9 temporal student."""

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
import torch.nn.functional as F

from capacity_student import CapacityConfig
from capacity_temporal_student import CapacityTemporalStyleContextStudent
from perceptual_features import FeatureDistance
from student_v2 import ReconstructionConfig, detail_loss
from temporal_student import TemporalConfig
from train_student import atomic_json
from train_temporal_student import (
    MultiSpatialCache,
    StrictTemporalCache,
    _augment_sequence,
    _device_batch,
    evaluate_streaming,
)


def tone_loss(pred, target):
    return (F.avg_pool2d(pred, 16) - F.avg_pool2d(target, 16)).abs().mean()


def effect_high_frequency_loss(pred, target, rgb, kernel_size=5):
    """Compare high-frequency portions of the learned teacher effect.

    Comparing ``prediction - rgb`` with ``target - rgb`` keeps unchanged input
    detail out of this auxiliary term.  It is intentionally opt-in because a
    high-frequency effect penalty can trade whole-frame MAE for sharper-looking
    residuals on a small corpus.
    """

    if kernel_size < 3 or kernel_size % 2 == 0:
        raise ValueError("kernel_size must be an odd integer >= 3")
    padding = kernel_size // 2

    def high_frequency(value):
        low = F.avg_pool2d(
            value,
            kernel_size,
            stride=1,
            padding=padding,
            count_include_pad=False,
        )
        return value - low

    predicted_effect = high_frequency(pred - rgb)
    target_effect = high_frequency(target - rgb)
    return (predicted_effect - target_effect).abs().mean()


def identity_preservation_loss(pred, target, rgb, threshold=0.05):
    """Discourage needless changes where the teacher leaves the input alone."""

    if threshold < 0:
        raise ValueError("Identity threshold must be non-negative")
    target_change = (target - rgb).abs().mean(1, keepdim=True)
    unchanged = (target_change <= float(threshold)).to(dtype=pred.dtype)
    denominator = (3.0 * unchanged.sum()).clamp_min(1.0)
    return ((pred - rgb).abs() * unchanged).sum() / denominator


def effect_power_loss(pred, target, rgb, power=3.0):
    """Match signed teacher effects after a small-magnitude power mapping.

    The loss operates on ``prediction - rgb`` and ``target - rgb`` rather than
    on absolute RGB. A root mapping makes small residual errors visible to the
    optimizer while preserving their sign; it is opt-in because it can trade
    high-effect pixel accuracy for low-effect fidelity.
    """

    if power < 1.0:
        raise ValueError("Effect power must be at least one")

    def mapped(value):
        return torch.sign(value) * (value.abs() + 1e-6).pow(1.0 / float(power))

    predicted_effect = mapped(pred - rgb)
    target_effect = mapped(target - rgb)
    return (predicted_effect - target_effect).abs().mean()


def _load_parent(path: Path, device="cuda"):
    saved = torch.load(path, map_location=device, weights_only=False)
    architecture = saved.get("architecture")
    if architecture == "context_v7_capacity_temporal":
        config = ReconstructionConfig(**saved["base_config"])
        temporal = TemporalConfig(**saved["temporal_config"])
        capacity = CapacityConfig(**saved["capacity_config"])
        model = CapacityTemporalStyleContextStudent(config, temporal, capacity).to(device)
        model.load_state_dict(saved["model"])
        return model, saved, config, temporal, capacity
    if architecture != "context_v5_temporal":
        raise ValueError(
            "Capacity-temporal phase expects a context_v5_temporal or "
            "context_v7_capacity_temporal parent"
        )
    config = ReconstructionConfig(**saved["base_config"])
    temporal = TemporalConfig(**saved["temporal_config"])
    capacity = CapacityConfig()
    model = CapacityTemporalStyleContextStudent(config, temporal, capacity).to(device)
    model.initialize_v5(saved["model"])
    return model, saved, config, temporal, capacity


def _checkpoint(
    path,
    model,
    ema,
    optimizer,
    step,
    best_mae,
    best_feature,
    run,
    schedule,
    best_old_mae=None,
    best_new_mae=None,
):
    payload = {
        "architecture": "context_v7_capacity_temporal",
        "base_config": run["base_config"],
        "temporal_config": run["temporal_config"],
        "capacity_config": run["capacity_config"],
        "model": ema.state_dict(),
        "raw_model": model.state_dict(),
        "optimizer": optimizer.state_dict(),
        "step": step,
        "best_mae": best_mae,
        "best_feature": best_feature,
        "best_old_mae": best_old_mae,
        "best_new_mae": best_new_mae,
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
    parser.add_argument("--initialize", type=Path, required=True)
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument(
        "--new-temporal-cache",
        type=Path,
        help=(
            "Optional second strict temporal cache for a deliberately oversampled new domain. "
            "The original --cache remains the old domain and both validation splits are reported separately."
        ),
    )
    parser.add_argument(
        "--new-temporal-prob",
        type=float,
        default=0.0,
        help="Probability of selecting the new temporal cache on a non-spatial step.",
    )
    parser.add_argument(
        "--spatial-cache",
        type=Path,
        action="append",
        help="Spatial cache to sample; may be supplied multiple times without concatenating sources.",
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--steps", type=int, default=4000)
    parser.add_argument("--window", type=int, default=8)
    parser.add_argument("--burn-in", type=int, default=2)
    parser.add_argument("--batch", type=int, default=2)
    parser.add_argument("--base-lr", type=float, default=5e-7)
    parser.add_argument("--temporal-lr", type=float, default=5e-6)
    parser.add_argument("--capacity-lr", type=float, default=2e-5)
    parser.add_argument("--feature-weight", type=float, default=0.05)
    parser.add_argument("--vgg-weight", type=float, default=0.10)
    parser.add_argument("--tone-weight", type=float, default=0.10)
    parser.add_argument("--effect-high-frequency-weight", type=float, default=0.0)
    parser.add_argument(
        "--effect-power-weight",
        type=float,
        default=0.0,
        help="Optional signed residual power-mapped loss weight.",
    )
    parser.add_argument(
        "--effect-power",
        type=float,
        default=3.0,
        help="Root exponent denominator for the residual power loss; must be >= 1.",
    )
    parser.add_argument(
        "--identity-weight",
        type=float,
        default=0.0,
        help="Penalize student changes on pixels with small teacher effect.",
    )
    parser.add_argument("--identity-threshold", type=float, default=0.05)
    parser.add_argument(
        "--micro-identity-weight",
        type=float,
        default=0.0,
        help="Additional identity loss weight for very small teacher effects.",
    )
    parser.add_argument(
        "--micro-identity-threshold",
        type=float,
        default=0.01,
        help="Teacher-effect threshold for the optional micro-identity loss.",
    )
    parser.add_argument("--delta-weight", type=float, default=0.12)
    parser.add_argument("--spatial-prob", type=float, default=0.25)
    parser.add_argument("--capacity-width", type=int, default=128)
    parser.add_argument(
        "--inherit-parent-capacity", action="store_true",
        help="Use the complete saved parent capacity configuration for an exact continuation.",
    )
    parser.add_argument("--capacity-blocks", type=int, default=6)
    parser.add_argument("--delta-scale", type=float, default=0.12)
    parser.add_argument(
        "--style-modulation",
        action="store_true",
        help="Add a zero-initialized global context-FiLM path to the capacity branch.",
    )
    parser.add_argument("--extra-capacity-width", type=int, default=0)
    parser.add_argument("--extra-capacity-blocks", type=int, default=0)
    parser.add_argument(
        "--residual-gate",
        action="store_true",
        help="Add zero-initialized native-resolution gates to the capacity residual branches.",
    )
    parser.add_argument(
        "--residual-gate-scale",
        type=float,
        default=0.8,
        help="Maximum fractional residual-gate modulation; must be in (0, 1].",
    )
    parser.add_argument(
        "--final-gate",
        action="store_true",
        help="Add a zero-initialized gate around the complete student correction.",
    )
    parser.add_argument(
        "--final-gate-scale",
        type=float,
        default=0.8,
        help="Maximum fractional final-gate modulation; must be in (0, 1].",
    )
    parser.add_argument(
        "--freeze-base-capacity",
        action="store_true",
        help="Freeze the inherited spatial and capacity branches and train only temporal parameters.",
    )
    parser.add_argument(
        "--freeze-parent",
        action="store_true",
        help="Freeze all inherited branches and train only the optional capacity_extra branch.",
    )
    parser.add_argument(
        "--fresh-capacity-init",
        action="store_true",
        help=(
            "Rebuild the requested capacity branches from their deterministic "
            "constructor initialization and inherit only the parent base/temporal "
            "function; use this for fair width comparisons."
        ),
    )
    parser.add_argument(
        "--zero-init-missing-capacity-blocks",
        action="store_true",
        help=(
            "For a same-width depth expansion, zero the residual scale of each "
            "new capacity block so the child starts as the exact parent function."
        ),
    )
    parser.add_argument(
        "--fit-all-nontest",
        action="store_true",
        help="Use train and validation strict streams plus non-test spatial patches for a fixed final fit; disable validation selection.",
    )
    parser.add_argument("--eval-every", type=int, default=500)
    parser.add_argument("--seed", type=int, default=337)
    args = parser.parse_args()
    if args.steps < 1 or args.window < 2 or args.batch < 1:
        raise ValueError("steps, window, and batch must be positive")
    if not 0 <= args.burn_in < args.window - 1:
        raise ValueError("burn-in must leave at least one supervised frame")
    if not 0 <= args.spatial_prob <= 1:
        raise ValueError("spatial probability must be between zero and one")
    if not 0 <= args.new_temporal_prob <= 1:
        raise ValueError("new temporal probability must be between zero and one")
    if args.new_temporal_cache is None and args.new_temporal_prob:
        raise ValueError("new temporal probability requires --new-temporal-cache")
    if args.effect_high_frequency_weight < 0:
        raise ValueError("effect high-frequency weight must be non-negative")
    if args.effect_power_weight < 0:
        raise ValueError("effect power weight must be non-negative")
    if args.effect_power < 1.0:
        raise ValueError("effect power must be at least one")
    if args.identity_weight < 0:
        raise ValueError("identity weight must be non-negative")
    if args.identity_threshold < 0:
        raise ValueError("identity threshold must be non-negative")
    if args.micro_identity_weight < 0:
        raise ValueError("micro-identity weight must be non-negative")
    if args.micro_identity_threshold < 0:
        raise ValueError("micro-identity threshold must be non-negative")
    if not 0.0 < args.residual_gate_scale <= 1.0:
        raise ValueError("residual gate scale must be in (0, 1]")
    if not 0.0 < args.final_gate_scale <= 1.0:
        raise ValueError("final gate scale must be in (0, 1]")
    if args.freeze_base_capacity and args.freeze_parent:
        raise ValueError("freeze modes are mutually exclusive")
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

    training_split = "train_validation" if args.fit_all_nontest else "train"
    cache = StrictTemporalCache(args.cache, training_split)
    validation = None if args.fit_all_nontest else StrictTemporalCache(args.cache, "validation")
    new_cache = (
        StrictTemporalCache(args.new_temporal_cache, training_split)
        if args.new_temporal_cache is not None
        else None
    )
    new_validation = (
        None
        if args.fit_all_nontest or new_cache is None
        else StrictTemporalCache(args.new_temporal_cache, "validation")
    )
    spatial = (
        MultiSpatialCache(args.spatial_cache, include_validation=args.fit_all_nontest)
        if args.spatial_cache
        else None
    )
    parent_path = args.initialize.resolve()
    parent_sha256 = hashlib.sha256(parent_path.read_bytes()).hexdigest()
    model, parent, config, temporal, default_capacity = _load_parent(parent_path)
    capacity = CapacityConfig(
        width=args.capacity_width,
        blocks=args.capacity_blocks,
        delta_scale=args.delta_scale,
        style_modulation=args.style_modulation,
        extra_width=args.extra_capacity_width,
        extra_blocks=args.extra_capacity_blocks,
        residual_gate=args.residual_gate,
        residual_gate_scale=args.residual_gate_scale,
        final_gate=args.final_gate,
        final_gate_scale=args.final_gate_scale,
    )
    if args.inherit_parent_capacity:
        capacity = default_capacity
    if args.freeze_base_capacity and (capacity != default_capacity or args.fresh_capacity_init):
        raise ValueError(
            "Temporal-only continuation must preserve the parent capacity configuration and weights. "
            "Use --inherit-parent-capacity and do not request fresh capacity initialization."
        )
    if args.zero_init_missing_capacity_blocks:
        if args.fresh_capacity_init:
            raise ValueError(
                "Zero-initialized missing blocks require a parent-preserving initialization"
            )
        if (
            capacity.width != default_capacity.width
            or capacity.extra_width != default_capacity.extra_width
            or capacity.blocks < default_capacity.blocks
            or capacity.extra_blocks < default_capacity.extra_blocks
        ):
            raise ValueError(
                "Zero-initialized missing blocks require unchanged widths and non-decreasing depths"
            )
    if args.fresh_capacity_init:
        model = CapacityTemporalStyleContextStudent(config, temporal, capacity).cuda()
        model.initialize_base_temporal(parent["model"])
    elif capacity != default_capacity:
        model = CapacityTemporalStyleContextStudent(config, temporal, capacity).cuda()
        model.initialize_v5(
            parent["model"],
            zero_init_missing_blocks=args.zero_init_missing_capacity_blocks,
        )
    if args.freeze_base_capacity:
        for name, parameter in model.named_parameters():
            if not name.startswith("temporal_"):
                parameter.requires_grad_(False)
    if args.freeze_parent:
        extra_names = [
            name
            for name, parameter in model.named_parameters()
            if name.startswith("capacity_extra_") and parameter.requires_grad
        ]
        if not extra_names:
            raise ValueError("--freeze-parent requires a non-empty extra capacity branch")
        for name, parameter in model.named_parameters():
            parameter.requires_grad_(name.startswith("capacity_extra_"))
    ema = deepcopy(model)
    temporal_params = [
        parameter for name, parameter in model.named_parameters() if name.startswith("temporal_")
    ]
    capacity_params = [
        parameter for name, parameter in model.named_parameters() if name.startswith("capacity_")
    ]
    extra_capacity_params = [
        parameter
        for name, parameter in model.named_parameters()
        if name.startswith("capacity_extra_")
    ]
    base_params = [
        parameter
        for name, parameter in model.named_parameters()
        if not name.startswith("temporal_") and not name.startswith("capacity_")
    ]
    optimizer_groups = []
    if not args.freeze_base_capacity and not args.freeze_parent:
        optimizer_groups.append({"params": base_params, "lr": args.base_lr})
    # ``--freeze-base-capacity`` is intended to leave the temporal branch
    # trainable while freezing the inherited spatial/capacity branches.  The
    # old condition accidentally omitted the temporal group in that mode,
    # producing an empty optimizer when ``--freeze-base-capacity`` was used.
    if not args.freeze_parent:
        optimizer_groups.append({"params": temporal_params, "lr": args.temporal_lr})
    if args.freeze_parent:
        optimizer_groups.append({"params": extra_capacity_params, "lr": args.capacity_lr})
    elif not args.freeze_base_capacity:
        optimizer_groups.append({"params": capacity_params, "lr": args.capacity_lr})
    optimizer = torch.optim.AdamW(optimizer_groups, weight_decay=1e-4)
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
        "feature_weight": args.feature_weight,
        "vgg_weight": args.vgg_weight,
        "tone_weight": args.tone_weight,
        "effect_high_frequency_weight": args.effect_high_frequency_weight,
        "effect_power_weight": args.effect_power_weight,
        "effect_power": args.effect_power,
        "identity_weight": args.identity_weight,
        "identity_threshold": args.identity_threshold,
        "micro_identity_weight": args.micro_identity_weight,
        "micro_identity_threshold": args.micro_identity_threshold,
        "delta_weight": args.delta_weight,
        "spatial_prob": args.spatial_prob,
        "new_temporal_prob": args.new_temporal_prob,
        "capacity_width": capacity.width,
        "capacity_blocks": capacity.blocks,
        "delta_scale": capacity.delta_scale,
        "style_modulation": capacity.style_modulation,
        "extra_capacity_width": capacity.extra_width,
        "extra_capacity_blocks": capacity.extra_blocks,
        "residual_gate": capacity.residual_gate,
        "residual_gate_scale": capacity.residual_gate_scale,
        "final_gate": capacity.final_gate,
        "final_gate_scale": capacity.final_gate_scale,
        "inherit_parent_capacity": args.inherit_parent_capacity,
        "freeze_base_capacity": args.freeze_base_capacity,
        "freeze_parent": args.freeze_parent,
        "fresh_capacity_init": args.fresh_capacity_init,
        "seed": args.seed,
        "eval_every": args.eval_every,
    }
    run = {
        "architecture": "context_v7_capacity_temporal",
        "base_config": asdict(config),
        "temporal_config": asdict(temporal),
        "capacity_config": asdict(capacity),
        "parent_checkpoint": str(parent_path),
        "parent_sha256": parent_sha256,
        "parent_shape_skipped_capacity_keys": getattr(model, "parent_shape_skips", []),
        "cache": json.loads((Path(args.cache) / "complete.json").read_text()),
        "validation_cache": (
            json.loads((Path(args.cache) / "complete.json").read_text())
            if validation is not None
            else None
        ),
        "new_temporal_cache": (
            json.loads((Path(args.new_temporal_cache) / "complete.json").read_text())
            if new_cache is not None
            else None
        ),
        "new_validation_cache": (
            json.loads((Path(args.new_temporal_cache) / "complete.json").read_text())
            if new_validation is not None
            else None
        ),
        "new_temporal_probability": args.new_temporal_prob,
        "spatial_cache": spatial.complete if spatial else None,
        "training_split": training_split,
        "fit_all_nontest": args.fit_all_nontest,
        "capacity_initialization": (
            "fresh_constructor_from_parent_base_temporal"
            if args.fresh_capacity_init
            else "parent_exact_or_shape_compatible"
        ),
        "zero_init_missing_capacity_blocks": args.zero_init_missing_capacity_blocks,
        "zero_initialized_missing_capacity_gammas": getattr(
            model, "zero_initialized_missing_capacity_gammas", []
        ),
        "capacity_init_seed": args.seed if args.fresh_capacity_init else None,
        "training_streams": len(cache.streams),
        "validation_streams": len(validation.streams) if validation is not None else 0,
        "new_training_streams": len(new_cache.streams) if new_cache is not None else 0,
        "new_validation_streams": (
            len(new_validation.streams) if new_validation is not None else 0
        ),
        "parameters": sum(parameter.numel() for parameter in model.parameters()),
        "parameter_partition": {
            "base": sum(parameter.numel() for parameter in base_params),
            "temporal": sum(parameter.numel() for parameter in temporal_params),
            "capacity": sum(parameter.numel() for parameter in capacity_params),
            "capacity_extra": sum(parameter.numel() for parameter in extra_capacity_params),
        },
        "trainable_parameters": sum(
            parameter.numel() for parameter in model.parameters() if parameter.requires_grad
        ),
        "schedule": schedule,
        "test_used": False,
        "selection": (
            "fixed final fit on train+validation strict streams and non-test spatial patches; no validation or test selection"
            if args.fit_all_nontest
            else (
                "merged old/new strict validation MAE and first-frame feature distance; "
                "old and new domain metrics are retained separately; test remains untouched"
                if new_validation is not None
                else "strict sequence streaming MAE and first-frame feature distance; test remains untouched"
            )
        ),
    }
    atomic_json(args.output / "run.json", run)
    best_mae = float("inf")
    best_feature = float("inf")
    best_old_mae = float("inf")
    best_new_mae = float("inf")
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
            best_old_mae,
            best_new_mae,
        )

    def validate(step):
        nonlocal best_mae, best_feature, best_old_mae, best_new_mae

        def evaluate_domain(domain_cache):
            metrics = evaluate_streaming(
                ema, domain_cache, "cuda", batch=max(1, min(8, args.batch * 4))
            )
            feature_total = feature_count = 0
            with torch.no_grad():
                for selected, arrays in domain_cache.stream_batches(
                    max(1, min(8, args.batch * 4))
                ):
                    rgb_np, target_np, guides_np, context_np = arrays
                    rgb, target, guides, context = _device_batch(
                        (
                            rgb_np[:, 0],
                            target_np[:, 0],
                            guides_np[:, 0],
                            context_np[:, 0],
                        ),
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
            return metrics

        old_metrics = evaluate_domain(validation)
        if new_validation is None:
            validation_record = old_metrics
            selection_mae = old_metrics["mae"]
            selection_feature = old_metrics["feature_distance_first_frame"]
        else:
            new_metrics = evaluate_domain(new_validation)
            old_pixels = max(1, old_metrics["pixels"])
            new_pixels = max(1, new_metrics["pixels"])
            total_pixels = old_pixels + new_pixels
            merged = {
                "split": "old_plus_new_validation",
                "sequence_count": old_metrics["sequence_count"]
                + new_metrics["sequence_count"],
                "eye_streams": old_metrics["eye_streams"] + new_metrics["eye_streams"],
                "frames": old_metrics["frames"] + new_metrics["frames"],
                "mae": (
                    old_metrics["mae"] * old_pixels + new_metrics["mae"] * new_pixels
                )
                / total_pixels,
                "psnr": -10.0
                * math.log10(
                    max(
                        (
                            10 ** (-old_metrics["psnr"] / 10.0) * old_pixels
                            + 10 ** (-new_metrics["psnr"] / 10.0) * new_pixels
                        )
                        / total_pixels,
                        1e-12,
                    )
                ),
                "feature_distance_first_frame": (
                    old_metrics["feature_distance_first_frame"] * old_pixels
                    + new_metrics["feature_distance_first_frame"] * new_pixels
                )
                / total_pixels,
                "pixels": total_pixels,
                "old_domain_pixels": old_pixels,
                "new_domain_pixels": new_pixels,
            }
            validation_record = {
                "old_domain": old_metrics,
                "new_domain": new_metrics,
                "merged": merged,
            }
            selection_mae = merged["mae"]
            selection_feature = merged["feature_distance_first_frame"]

            if new_metrics["mae"] < best_new_mae:
                best_new_mae = new_metrics["mae"]
                save("best_new_domain", step)

        if old_metrics["mae"] < best_old_mae:
            best_old_mae = old_metrics["mae"]
            save("best_old_domain", step)
        if selection_mae < best_mae:
            best_mae = selection_mae
            save("best_mae", step)
        if selection_feature < best_feature:
            best_feature = selection_feature
            save("best_feature", step)
        save("last", step)
        record = {
            "step": step,
            "seconds": time.time() - started,
            "validation": validation_record,
            "best_old_mae": best_old_mae,
            "best_new_mae": best_new_mae if new_validation is not None else None,
            "selection_mae": selection_mae,
        }
        with (args.output / "history.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record) + "\n")
        print(json.dumps(record), flush=True)

    if validation is not None:
        validate(0)
    else:
        save("initial", 0)
    loss_window = []
    for step in range(1, args.steps + 1):
        use_spatial = spatial is not None and float(rng.random()) < args.spatial_prob
        use_new_temporal = (
            not use_spatial
            and new_cache is not None
            and float(rng.random()) < args.new_temporal_prob
        )
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
                if args.tone_weight:
                    loss = loss + args.tone_weight * tone_loss(prediction.float(), target)
                if args.effect_high_frequency_weight:
                    loss = loss + args.effect_high_frequency_weight * effect_high_frequency_loss(
                        prediction.float(), target, rgb
                    )
                if args.effect_power_weight:
                    loss = loss + args.effect_power_weight * effect_power_loss(
                        prediction.float(), target, rgb, args.effect_power
                    )
                if args.identity_weight:
                    loss = loss + args.identity_weight * identity_preservation_loss(
                        prediction.float(), target, rgb, args.identity_threshold
                    )
                if args.micro_identity_weight:
                    loss = loss + args.micro_identity_weight * identity_preservation_loss(
                        prediction.float(), target, rgb, args.micro_identity_threshold
                    )
        else:
            temporal_cache = new_cache if use_new_temporal else cache
            selected, starts, indices = temporal_cache.sample_window(
                rng, args.batch, args.window
            )
            arrays = temporal_cache.load_window(indices)
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
                    if args.tone_weight:
                        frame_loss = frame_loss + args.tone_weight * tone_loss(
                            prediction.float(), target[:, frame]
                        )
                    if args.effect_high_frequency_weight:
                        frame_loss = frame_loss + args.effect_high_frequency_weight * effect_high_frequency_loss(
                            prediction.float(), target[:, frame], rgb[:, frame]
                        )
                    if args.effect_power_weight:
                        frame_loss = frame_loss + args.effect_power_weight * effect_power_loss(
                            prediction.float(), target[:, frame], rgb[:, frame], args.effect_power
                        )
                    if args.identity_weight:
                        frame_loss = frame_loss + args.identity_weight * identity_preservation_loss(
                            prediction.float(), target[:, frame], rgb[:, frame], args.identity_threshold
                        )
                    if args.micro_identity_weight:
                        frame_loss = frame_loss + args.micro_identity_weight * identity_preservation_loss(
                            prediction.float(),
                            target[:, frame],
                            rgb[:, frame],
                            args.micro_identity_threshold,
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
                    "temporal_domain": (
                        "spatial" if use_spatial else "new" if use_new_temporal else "old"
                    ),
                    "best_mae": best_mae if math.isfinite(best_mae) else None,
                    "best_feature": best_feature if math.isfinite(best_feature) else None,
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
                        "temporal_domain": (
                            "spatial" if use_spatial else "new" if use_new_temporal else "old"
                        ),
                        "seconds": time.time() - started,
                    }
                ),
                flush=True,
            )
            loss_window = []
        if step % args.eval_every == 0 or step == args.steps:
            if validation is not None:
                validate(step)
            else:
                save("last", step)
    atomic_json(
        args.output / "status.json",
        {
            "state": "completed",
            "step": args.steps,
            "best_mae": best_mae if math.isfinite(best_mae) else None,
            "best_feature": best_feature if math.isfinite(best_feature) else None,
            "best_old_mae": best_old_mae if math.isfinite(best_old_mae) else None,
            "best_new_mae": best_new_mae if math.isfinite(best_new_mae) else None,
            "fit_all_nontest": args.fit_all_nontest,
            "seconds": time.time() - started,
        },
    )
    print("CAPACITY TEMPORAL TRAINING COMPLETE", flush=True)


if __name__ == "__main__":
    main()
