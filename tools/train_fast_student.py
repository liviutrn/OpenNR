"""Train FastStudent-v1 on the immutable strict temporal cache.

This entry point is intentionally independent of the existing temporal-student
checkpoints.  It reuses only the cache validator and streaming evaluator, so a
new run cannot overwrite or reinterpret the current joint-model training.
"""

from __future__ import annotations

import argparse
from copy import deepcopy
import json
from pathlib import Path
import random
import time

import numpy as np
import torch

from fast_student_v1 import (
    FastStudentConfig,
    FastStudentV1,
    ScaleConditionedFastStudent,
    config_dict,
)
from student_v2 import detail_loss
from train_student import atomic_json
from train_temporal_student import (
    SpatialCache,
    StrictTemporalCache,
    _augment_sequence,
    _device_batch,
    evaluate_streaming,
)


def _save_checkpoint(
    path: Path,
    model: FastStudentV1,
    ema: FastStudentV1,
    optimizer: torch.optim.Optimizer,
    step: int,
    best_mae: float,
    run: dict,
    schedule: dict,
) -> None:
    payload = {
        "architecture": "fast_student_v1",
        "config": config_dict(model.config),
        "model": ema.state_dict(),
        "raw_model": model.state_dict(),
        "optimizer": optimizer.state_dict(),
        "step": step,
        "best_mae": best_mae,
        "run": run,
        "schedule": schedule,
        "cache": run["cache"],
        "python_rng": random.getstate(),
        "numpy_rng": np.random.get_state(),
        "torch_rng": torch.get_rng_state(),
        "cuda_rng": torch.cuda.get_rng_state_all(),
    }
    temporary = path.with_suffix(".tmp")
    torch.save(payload, temporary)
    temporary.replace(path)


def _autocast():
    return torch.autocast(device_type="cuda", dtype=torch.bfloat16)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--spatial-cache", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--steps", type=int, default=4000)
    parser.add_argument("--window", type=int, default=8)
    parser.add_argument("--burn-in", type=int, default=1)
    parser.add_argument("--batch", type=int, default=2)
    parser.add_argument("--lr", type=float, default=2e-4)
    parser.add_argument("--delta-weight", type=float, default=0.12)
    parser.add_argument("--spatial-prob", type=float, default=0.0)
    parser.add_argument("--eval-every", type=int, default=500)
    parser.add_argument("--seed", type=int, default=1200)
    parser.add_argument("--base-width", type=int, default=32)
    parser.add_argument("--mid-width", type=int, default=64)
    parser.add_argument("--temporal-hidden", type=int, default=64)
    parser.add_argument("--blocks", type=int, default=2)
    parser.add_argument(
        "--work-scale",
        type=float,
        default=1.0,
        help="run the student at this fraction of the input size and resolve its residual at full size",
    )
    parser.add_argument("--resume", type=Path)
    args = parser.parse_args()

    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is required for FastStudent-v1 training")
    if args.steps < 1 or args.window < 2 or args.batch < 1:
        raise ValueError("steps, window, and batch must be positive")
    if not 0 <= args.burn_in < args.window - 1:
        raise ValueError("burn-in must leave at least one supervised frame")
    if not 0 <= args.spatial_prob <= 1:
        raise ValueError("spatial probability must be between zero and one")
    if not 0.0 < args.work_scale <= 1.0:
        raise ValueError("work-scale must be in (0, 1]")
    if args.spatial_prob and not args.spatial_cache:
        raise ValueError("--spatial-prob requires --spatial-cache")
    if args.resume is None and (args.output / "run.json").exists():
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
    cache_manifest = json.loads((args.cache / "complete.json").read_text(encoding="utf-8"))

    config = FastStudentConfig(
        base_width=args.base_width,
        mid_width=args.mid_width,
        temporal_hidden=args.temporal_hidden,
        blocks=args.blocks,
    )
    model = FastStudentV1(config).cuda()
    ema = deepcopy(model)
    runtime_model = ScaleConditionedFastStudent(model, args.work_scale)
    runtime_ema = ScaleConditionedFastStudent(ema, args.work_scale)
    optimizer = torch.optim.AdamW(model.parameters(), lr=args.lr, weight_decay=1e-4)
    start_step = 0
    best_mae = float("inf")

    schedule = {
        "steps": args.steps,
        "window": args.window,
        "burn_in": args.burn_in,
        "batch": args.batch,
        "lr": args.lr,
        "delta_weight": args.delta_weight,
        "spatial_prob": args.spatial_prob,
        "eval_every": args.eval_every,
        "work_scale": args.work_scale,
    }

    if args.resume:
        saved = torch.load(args.resume, map_location="cuda", weights_only=False)
        if saved.get("architecture") != "fast_student_v1":
            raise ValueError("Resume checkpoint is not a fast_student_v1 checkpoint")
        if saved.get("config") != config_dict(config):
            raise ValueError("Resume model config differs; start a separate output directory")
        if saved.get("schedule") != schedule:
            raise ValueError("Resume schedule differs; start an explicit new phase")
        if saved.get("cache", {}).get("rows_sha256") != cache.rows_sha256:
            raise ValueError("Resume cache identity differs")
        model.load_state_dict(saved["raw_model"])
        ema.load_state_dict(saved["model"])
        optimizer.load_state_dict(saved["optimizer"])
        start_step = int(saved["step"])
        best_mae = float(saved["best_mae"])
        random.setstate(saved["python_rng"])
        np.random.set_state(saved["numpy_rng"])
        torch.set_rng_state(saved["torch_rng"].cpu())
        torch.cuda.set_rng_state_all([value.cpu() for value in saved["cuda_rng"]])

    run = {
        "architecture": "fast_student_v1",
        "config": config_dict(config),
        "cache": cache_manifest,
        "validation_cache": cache_manifest,
        "spatial_cache": spatial.complete if spatial else None,
        "training_streams": len(cache.streams),
        "validation_streams": len(validation.streams),
        "parameters": sum(parameter.numel() for parameter in model.parameters()),
        "parent_model": "none; fresh identity-initialized FastStudent-v1",
        "test_used": False,
        "selection": "validation streaming MAE; test remains untouched",
        "work_scale": args.work_scale,
        "target_definition": "full-resolution teacher supervised through full-resolution matched residual composition",
        "schedule": schedule,
    }
    atomic_json(args.output / "run.json", run)

    def save(name: str, step: int) -> None:
        _save_checkpoint(
            args.output / f"{name}.pt",
            model,
            ema,
            optimizer,
            step,
            best_mae,
            run,
            schedule,
        )

    def validate(step: int) -> None:
        nonlocal best_mae
        metrics = evaluate_streaming(
            runtime_ema,
            validation,
            "cuda",
            batch=max(1, min(8, args.batch * 4)),
        )
        if metrics["mae"] < best_mae:
            best_mae = metrics["mae"]
            save("best_mae", step)
        save("last", step)
        record = {"step": step, "seconds": time.time() - started, "validation": metrics}
        with (args.output / "history.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record) + "\n")
        print(json.dumps(record), flush=True)

    rng = np.random.default_rng(args.seed)
    started = time.time()
    if not args.resume:
        validate(0)

    loss_window: list[float] = []
    for step in range(start_step + 1, args.steps + 1):
        runtime_model.train()
        use_spatial = spatial is not None and float(rng.random()) < args.spatial_prob
        optimizer.zero_grad(set_to_none=True)
        if use_spatial:
            rgb_np, target_np, guides_np, context_np = spatial.sample(rng, args.batch)
            rgb, target, guides, context = _device_batch(
                (rgb_np, target_np, guides_np, context_np), "cuda"
            )
            rgb = rgb.float() / 255.0
            target = target.float() / 255.0
            guides = guides.float()
            context = context.float()
            with _autocast():
                prediction, _ = runtime_model.forward_temporal(rgb, guides, context, None)
                loss = detail_loss(prediction.float(), target, rgb)
        else:
            _, _, indices = cache.sample_window(rng, args.batch, args.window)
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
            sequence_losses = []
            for frame in range(args.window):
                if frame < args.burn_in:
                    with torch.no_grad(), _autocast():
                        prediction, state = runtime_model.forward_temporal(
                            rgb[:, frame], guides[:, frame], context[:, frame], state
                        )
                    previous_prediction = prediction.detach().float()
                    previous_target = target[:, frame]
                    continue
                with _autocast():
                    prediction, state = runtime_model.forward_temporal(
                        rgb[:, frame], guides[:, frame], context[:, frame], state
                    )
                    frame_loss = detail_loss(
                        prediction.float(), target[:, frame], rgb[:, frame]
                    )
                    if previous_prediction is not None:
                        target_delta = target[:, frame] - previous_target
                        prediction_delta = prediction.float() - previous_prediction
                        frame_loss = frame_loss + args.delta_weight * torch.sqrt(
                            (prediction_delta - target_delta).square() + 1e-6
                        ).mean()
                sequence_losses.append(frame_loss)
                previous_prediction = prediction.float()
                previous_target = target[:, frame]
            if not sequence_losses:
                raise RuntimeError("temporal window has no supervised frames")
            loss = torch.stack(sequence_losses).mean()
            if state is not None:
                state = (state[0].detach(), state[1].detach())

        if not torch.isfinite(loss):
            raise RuntimeError(f"non-finite loss at step {step}")
        loss.backward()
        gradient = torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
        if not torch.isfinite(gradient):
            raise RuntimeError(f"non-finite gradient at step {step}")
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
            "seconds": time.time() - started,
        },
    )
    print("FAST STUDENT TRAINING COMPLETE", flush=True)


if __name__ == "__main__":
    main()
