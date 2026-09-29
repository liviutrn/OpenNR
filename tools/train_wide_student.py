"""Train a wider spatial student on strict native Feature-18 supervision."""

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

from perceptual_features import FeatureDistance
from train_capacity_student import MergedSpatialPool, StrictSpatialPool, evaluate_strict, tone_loss
from student_v2 import detail_loss
from train_student import atomic_json
from wide_student import WideConfig, WideStyleContextStudent


def _checkpoint(path, model, ema, optimizer, step, best_mae, best_feature, run, schedule):
    payload = {
        "architecture": "context_v8_wide",
        "wide_config": run["wide_config"],
        "model": ema.state_dict(),
        "raw_model": model.state_dict(),
        "optimizer": optimizer.state_dict(),
        "step": step,
        "best_mae": best_mae,
        "best_feature": best_feature,
        "run": run,
        "schedule": schedule,
        "strict_cache": run["strict_cache"],
        "merged_cache": run.get("merged_cache"),
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
    parser.add_argument("--strict-cache", type=Path, required=True)
    parser.add_argument("--merged-cache", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--steps", type=int, default=12000)
    parser.add_argument("--batch", type=int, default=2)
    parser.add_argument("--width", type=int, default=96)
    parser.add_argument("--blocks", type=int, default=5)
    parser.add_argument("--lr", type=float, default=2e-4)
    parser.add_argument("--feature-weight", type=float, default=0.05)
    parser.add_argument("--vgg-weight", type=float, default=0.05)
    parser.add_argument("--tone-weight", type=float, default=0.05)
    parser.add_argument("--merged-probability", type=float, default=0.0)
    parser.add_argument("--eval-every", type=int, default=512)
    parser.add_argument("--seed", type=int, default=503)
    args = parser.parse_args()
    if args.steps < 1 or args.batch < 1:
        raise ValueError("steps and batch must be positive")
    if not 0 <= args.merged_probability <= 1:
        raise ValueError("merged probability must be between zero and one")
    if args.merged_probability and not args.merged_cache:
        raise ValueError("merged probability requires --merged-cache")
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is required for wide training")
    if (args.output / "run.json").exists():
        raise ValueError("Output directory already contains a run")
    args.output.mkdir(parents=True, exist_ok=True)
    torch.set_num_threads(4)
    torch.manual_seed(args.seed)
    np.random.seed(args.seed)
    random.seed(args.seed)
    torch.backends.cudnn.benchmark = True

    strict_train = StrictSpatialPool(args.strict_cache)
    strict_validation = strict_train.cache.__class__(args.strict_cache, "validation")
    merged = MergedSpatialPool(args.merged_cache) if args.merged_cache else None
    wide_config = WideConfig(width=args.width, blocks=args.blocks, scale=4)
    model = WideStyleContextStudent(wide_config).cuda()
    ema = deepcopy(model)
    optimizer = torch.optim.AdamW(model.parameters(), lr=args.lr, weight_decay=1e-4)
    feature = FeatureDistance().cuda().eval()
    appearance = None
    if args.vgg_weight:
        from vgg_appearance_loss import VGGAppearanceLoss

        appearance = VGGAppearanceLoss().cuda().eval()
    rng = np.random.default_rng(args.seed)
    strict_manifest = json.loads((Path(args.strict_cache) / "complete.json").read_text())
    schedule = {
        "steps": args.steps,
        "batch": args.batch,
        "width": args.width,
        "blocks": args.blocks,
        "lr": args.lr,
        "feature_weight": args.feature_weight,
        "vgg_weight": args.vgg_weight,
        "tone_weight": args.tone_weight,
        "merged_probability": args.merged_probability,
        "eval_every": args.eval_every,
    }
    run = {
        "architecture": "context_v8_wide",
        "wide_config": asdict(wide_config),
        "strict_cache": strict_manifest,
        "strict_rows_sha256": strict_train.cache.rows_sha256,
        "merged_cache": merged.complete if merged else None,
        "strict_training_rows": int(len(strict_train.rows)),
        "merged_training_patches": int(len(merged.ids)) if merged else 0,
        "parameters": sum(parameter.numel() for parameter in model.parameters()),
        "schedule": schedule,
        "vgg_appearance": appearance.provenance if appearance is not None else None,
        "test_used": False,
        "selection": "strict validation streaming spatial MAE and first-frame feature distance; test remains untouched",
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
        metrics = evaluate_strict(
            ema, strict_validation, "cuda", batch=args.batch, feature=feature
        )
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
        values = [
            (
                merged.sample(rng)
                if merged is not None and float(rng.random()) < args.merged_probability
                else strict_train.sample(rng)
            )
            for _ in range(args.batch)
        ]
        arrays = tuple(np.stack([value[column] for value in values]) for column in range(4))
        rgb, target, guides, context = (
            torch.from_numpy(value).cuda(non_blocking=True) for value in arrays
        )
        rgb = rgb.float() / 255.0
        target = target.float() / 255.0
        guides = guides.float()
        context = context.float()
        if float(rng.random()) < 0.5:
            rgb = rgb.flip(-1)
            target = target.flip(-1)
            guides = guides.flip(-1)
            context = context.flip(-1)
            guides[:, 1] *= -1
            context[:, 4] *= -1
        model.train()
        optimizer.zero_grad(set_to_none=True)
        lr = args.lr * (0.1 + 0.9 * 0.5 * (1.0 + math.cos(math.pi * (step - 1) / args.steps)))
        for group in optimizer.param_groups:
            group["lr"] = lr
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
    print("WIDE TRAINING COMPLETE", flush=True)


if __name__ == "__main__":
    main()
