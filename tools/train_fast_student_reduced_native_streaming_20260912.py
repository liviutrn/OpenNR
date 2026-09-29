"""Memory-bounded training for a reduced-native FastStudent.

This is an offline experiment only. It streams one frame at a time from the
retained native replay set, carries the causal state through each sequence,
and truncates back-propagation through time so the 16 GB GPU is not asked to
hold a complete multi-sequence batch.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import time
from pathlib import Path
from typing import Any

import numpy as np
import torch

from evaluate_fast_student_trt_full_eye import (
    FULL_HEIGHT,
    FULL_WIDTH,
    _load_frame,
    _metrics,
    _resize,
)
from fast_student_v1 import FastStudentConfig, FastStudentV1, config_dict


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_metadata(replay_root: Path, train_fraction: float) -> dict[str, Any]:
    replay_root = replay_root.resolve()
    manifest_path = replay_root / "input_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    sequence = Path(manifest["sequence"]).resolve()
    frame_ids = [int(value) for value in manifest["frames"]]
    dimensions = tuple(int(value) for value in manifest["network_dimensions"])
    if len(dimensions) != 2:
        raise ValueError(f"invalid network_dimensions in {manifest_path}")
    split = max(1, min(len(frame_ids) - 1, int(len(frame_ids) * train_fraction)))
    return {
        "replay_root": replay_root,
        "manifest": manifest,
        "manifest_path": manifest_path,
        "manifest_sha256": _sha256(manifest_path),
        "sequence": sequence,
        "frames": frame_ids,
        "train_frames": frame_ids[:split],
        "heldout_frames": frame_ids[split:],
        "work_dimensions": dimensions,
    }


def _descriptor(data: dict[str, Any]) -> dict[str, Any]:
    return {
        "replay_root": str(data["replay_root"]),
        "manifest_sha256": data["manifest_sha256"],
        "sequence": str(data["sequence"]),
        "frames": data["frames"],
        "train_frames": data["train_frames"],
        "heldout_frames": data["heldout_frames"],
        "work_dimensions": list(data["work_dimensions"]),
    }


def _read_item(
    data: dict[str, Any],
    frame_id: int,
    eye: int,
    context_size: int,
) -> dict[str, torch.Tensor]:
    work_width, work_height = data["work_dimensions"]
    return _load_frame(
        data["replay_root"],
        data["sequence"],
        frame_id,
        eye,
        work_width,
        work_height,
        context_size,
        context_size,
        torch.device("cpu"),
        torch.float32,
    )


def _crop_item(
    item: dict[str, torch.Tensor],
    crop_size: int,
    rng: random.Random,
) -> dict[str, torch.Tensor]:
    """Crop work-resolution tensors while keeping whole-eye context intact."""

    if crop_size <= 0:
        return item
    height, width = item["work_input"].shape[-2:]
    if crop_size > height or crop_size > width:
        raise ValueError(
            f"crop_size {crop_size} does not fit work surface {(width, height)}"
        )
    top = rng.randrange(height - crop_size + 1)
    left = rng.randrange(width - crop_size + 1)
    result = dict(item)
    for name in ("work_input", "native_work"):
        result[name] = item[name][..., top : top + crop_size, left : left + crop_size]
    guide_height, guide_width = item["guides"].shape[-2:]
    guide_top = int(round(top * guide_height / height))
    guide_left = int(round(left * guide_width / width))
    guide_size_h = max(1, int(round(crop_size * guide_height / height)))
    guide_size_w = max(1, int(round(crop_size * guide_width / width)))
    result["guides"] = item["guides"][
        ...,
        guide_top : guide_top + guide_size_h,
        guide_left : guide_left + guide_size_w,
    ]
    return result


def _detach_state(
    state: tuple[torch.Tensor, torch.Tensor] | None,
) -> tuple[torch.Tensor, torch.Tensor] | None:
    if state is None:
        return None
    return state[0].detach(), state[1].detach()


def _target_metrics(
    prediction: torch.Tensor,
    item: dict[str, torch.Tensor],
) -> dict[str, float | bool]:
    with torch.inference_mode():
        student_full = (
            item["full_input"]
            + _resize(prediction - item["work_input"], FULL_HEIGHT, FULL_WIDTH)
        ).clamp(0.0, 1.0)
        native_full = (
            item["full_input"]
            + _resize(item["native_work"] - item["work_input"], FULL_HEIGHT, FULL_WIDTH)
        ).clamp(0.0, 1.0)
        native_teacher = _metrics(
            native_full.float(), item["full_teacher"].float(), item["full_input"].float()
        )
        student_teacher = _metrics(
            student_full.float(), item["full_teacher"].float(), item["full_input"].float()
        )
        return {
            "student_full_mae_vs_native50": float(
                (student_full.float() - native_full.float()).abs().mean().item()
            ),
            "student_work_mae_vs_native": float(
                (prediction.float() - item["native_work"].float()).abs().mean().item()
            ),
            "student_full_mae_vs_full_teacher": float(student_teacher["mae"]),
            "native50_composite_mae_vs_full_teacher": float(native_teacher["mae"]),
            "identity_mae_vs_full_teacher": float(student_teacher["identity_mae"]),
            "student_improvement_vs_identity": float(
                student_teacher["identity_mae"] - student_teacher["mae"]
            ),
            "finite": bool(
                torch.isfinite(student_full).all().item()
                and torch.isfinite(native_full).all().item()
            ),
        }


def _evaluate_sequence(
    model: FastStudentV1,
    data: dict[str, Any],
    frame_ids: list[int],
    context_size: int,
    device: torch.device,
) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    model.eval()
    with torch.inference_mode():
        for eye in (0, 1):
            state: tuple[torch.Tensor, torch.Tensor] | None = None
            for frame_id in frame_ids:
                cpu_item = _read_item(data, frame_id, eye, context_size)
                item = {name: value.to(device=device) for name, value in cpu_item.items()}
                prediction, state = model.forward_temporal(
                    item["work_input"], item["guides"], item["context"], state
                )
                records.append(
                    {"frame_id": frame_id, "eye": eye, **_target_metrics(prediction, item)}
                )
                del item, cpu_item, prediction

    def mean(name: str) -> float:
        return float(np.mean([float(record[name]) for record in records]))

    return {
        "frames": frame_ids,
        "eyes": [0, 1],
        "sample_count": len(records),
        "records": records,
        "student_full_mae_vs_native50_mean": mean("student_full_mae_vs_native50"),
        "student_work_mae_vs_native_mean": mean("student_work_mae_vs_native"),
        "student_full_mae_vs_full_teacher_mean": mean("student_full_mae_vs_full_teacher"),
        "native50_composite_mae_vs_full_teacher_mean": mean(
            "native50_composite_mae_vs_full_teacher"
        ),
        "identity_mae_vs_full_teacher_mean": mean("identity_mae_vs_full_teacher"),
        "student_improvement_vs_identity_mean": mean("student_improvement_vs_identity"),
        "student_better_than_identity_samples": int(
            sum(record["student_improvement_vs_identity"] > 0 for record in records)
        ),
    }


def _train_one_step(
    model: FastStudentV1,
    optimizer: torch.optim.Optimizer,
    train_data: list[dict[str, Any]],
    step: int,
    context_size: int,
    bptt_frames: int,
    crop_size: int,
    delta_weight: float,
    target_strength: float,
    luma_loss: bool,
    device: torch.device,
    rng: random.Random,
) -> float:
    model.train()
    optimizer.zero_grad(set_to_none=True)
    total_chunks = sum(
        math.ceil(len(data["train_frames"]) / bptt_frames) for data in train_data
    )
    loss_sum = 0.0
    for data_index, data in enumerate(train_data):
        eye = (step - 1 + data_index) % 2
        crop_rng = random.Random(rng.randrange(2**31))
        state: tuple[torch.Tensor, torch.Tensor] | None = None
        previous_prediction: torch.Tensor | None = None
        previous_target: torch.Tensor | None = None
        chunk_losses: list[torch.Tensor] = []
        frame_ids = data["train_frames"]
        for frame_index, frame_id in enumerate(frame_ids):
            cpu_item = _read_item(data, frame_id, eye, context_size)
            cropped = _crop_item(cpu_item, crop_size, crop_rng)
            item = {name: value.to(device=device) for name, value in cropped.items()}
            prediction, next_state = model.forward_temporal(
                item["work_input"], item["guides"], item["context"], state
            )
            target = (
                item["work_input"]
                + target_strength * (item["native_work"] - item["work_input"])
            ).clamp(0.0, 1.0)
            if luma_loss:
                prediction_luma = (
                    0.2126 * prediction[:, 0:1]
                    + 0.7152 * prediction[:, 1:2]
                    + 0.0722 * prediction[:, 2:3]
                )
                target_luma = (
                    0.2126 * target[:, 0:1]
                    + 0.7152 * target[:, 1:2]
                    + 0.0722 * target[:, 2:3]
                )
                loss = (prediction_luma - target_luma).abs().mean()
            else:
                prediction_luma = prediction
                target_luma = target
                loss = (prediction - target).abs().mean()
            if previous_prediction is not None and previous_target is not None:
                loss = loss + delta_weight * (
                    (prediction_luma - previous_prediction)
                    - (target_luma - previous_target)
                ).square().add(1e-6).sqrt().mean()
            chunk_losses.append(loss)
            loss_sum += float(loss.detach().cpu())
            previous_prediction = prediction_luma
            previous_target = target_luma
            state = next_state
            del target, item, cropped, cpu_item, prediction_luma, target_luma
            if len(chunk_losses) >= bptt_frames or frame_index == len(frame_ids) - 1:
                torch.stack(chunk_losses).mean().div_(total_chunks).backward()
                state = _detach_state(state)
                previous_prediction = previous_prediction.detach()
                previous_target = previous_target.detach()
                chunk_losses = []
    gradient = torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
    if not torch.isfinite(gradient):
        raise RuntimeError(f"non-finite gradient at step {step}")
    optimizer.step()
    return loss_sum / sum(len(data["train_frames"]) for data in train_data)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--train-replay-root", type=Path, action="append", required=True)
    parser.add_argument("--test-replay-root", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--train-fraction", type=float, default=0.75)
    parser.add_argument("--steps", type=int, default=50)
    parser.add_argument("--lr", type=float, default=2e-4)
    parser.add_argument("--delta-weight", type=float, default=0.05)
    parser.add_argument("--target-strength", type=float, default=1.0)
    parser.add_argument("--eval-every", type=int, default=10)
    parser.add_argument("--base-width", type=int, default=16)
    parser.add_argument("--mid-width", type=int, default=32)
    parser.add_argument("--temporal-hidden", type=int, default=32)
    parser.add_argument("--blocks", type=int, default=1)
    parser.add_argument("--model-scale", type=int, default=4)
    parser.add_argument("--residual-scale", type=float, default=None)
    parser.add_argument("--residual-mode", choices=("rgb", "luma"), default="rgb")
    parser.add_argument("--luma-loss", action="store_true")
    parser.add_argument("--context-size", type=int, default=96)
    parser.add_argument("--bptt-frames", type=int, default=4)
    parser.add_argument("--crop-size", type=int, default=0)
    parser.add_argument("--seed", type=int, default=120913)
    parser.add_argument("--device", default="cuda")
    args = parser.parse_args()

    if len(args.train_replay_root) < 2:
        raise ValueError("pass at least two --train-replay-root values")
    if args.output.exists() and any(args.output.iterdir()):
        raise FileExistsError(f"refusing to use non-empty output directory: {args.output}")
    if args.steps < 1 or args.eval_every < 1 or args.bptt_frames < 1:
        raise ValueError("steps, eval-every, and bptt-frames must be positive")
    if not 0.0 < args.target_strength <= 1.5:
        raise ValueError("target-strength must be in (0, 1.5]")
    if args.residual_scale is not None and not 0.0 < args.residual_scale <= 1.0:
        raise ValueError("residual-scale must be in (0, 1]")
    if args.model_scale < 1 or not 0.0 < args.train_fraction < 1.0:
        raise ValueError("model-scale must be positive and train-fraction must be between zero and one")
    if args.device.startswith("cuda") and not torch.cuda.is_available():
        raise RuntimeError("CUDA is required for this training experiment")

    args.output.mkdir(parents=True, exist_ok=True)
    random.seed(args.seed)
    np.random.seed(args.seed)
    torch.manual_seed(args.seed)
    if args.device.startswith("cuda"):
        torch.cuda.manual_seed_all(args.seed)
    torch.backends.cudnn.benchmark = True
    device = torch.device(args.device)
    rng = random.Random(args.seed)
    train_data = [_load_metadata(root, args.train_fraction) for root in args.train_replay_root]
    dimensions = {tuple(data["work_dimensions"]) for data in train_data}
    if len(dimensions) != 1:
        raise ValueError(f"all training replays must have the same work dimensions: {dimensions}")
    work_width, work_height = next(iter(dimensions))

    config = FastStudentConfig(
        base_width=args.base_width,
        mid_width=args.mid_width,
        temporal_hidden=args.temporal_hidden,
        blocks=args.blocks,
        model_scale=args.model_scale,
        temporal_downsample=args.model_scale * 2,
        residual_scale=(
            FastStudentConfig().residual_scale
            if args.residual_scale is None
            else args.residual_scale
        ),
        residual_mode=args.residual_mode,
    )
    model = FastStudentV1(config).to(device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=args.lr, weight_decay=1e-4)
    history: list[dict[str, Any]] = []
    best_value = float("inf")
    started = time.perf_counter()

    def validation_bundle(step: int) -> dict[str, Any]:
        nonlocal best_value
        validations = [
            _evaluate_sequence(model, data, data["heldout_frames"], args.context_size, device)
            for data in train_data
        ]
        aggregate = {
            "sequence_count": len(validations),
            "sample_count": int(sum(item["sample_count"] for item in validations)),
            "student_work_mae_vs_native_mean": float(
                np.mean([item["student_work_mae_vs_native_mean"] for item in validations])
            ),
            "student_full_mae_vs_native50_mean": float(
                np.mean([item["student_full_mae_vs_native50_mean"] for item in validations])
            ),
            "student_full_mae_vs_full_teacher_mean": float(
                np.mean([item["student_full_mae_vs_full_teacher_mean"] for item in validations])
            ),
            "identity_mae_vs_full_teacher_mean": float(
                np.mean([item["identity_mae_vs_full_teacher_mean"] for item in validations])
            ),
            "student_better_than_identity_samples": int(
                sum(item["student_better_than_identity_samples"] for item in validations)
            ),
            "validations": validations,
        }
        history.append({"step": step, "validation": aggregate})
        if aggregate["student_work_mae_vs_native_mean"] < best_value:
            best_value = aggregate["student_work_mae_vs_native_mean"]
            torch.save(
                {
                    "architecture": "fast_student_v1",
                    "config": config_dict(model.config),
                    "model": {name: value.detach().cpu() for name, value in model.state_dict().items()},
                    "step": step,
                    "seed": args.seed,
                    "learning_rate": args.lr,
                    "target": "look_strength_blended_native_reduced_work_output",
                    "target_strength": args.target_strength,
                    "luma_loss": args.luma_loss,
                    "work_scale": 0.5,
                    "train_replays": [_descriptor(data) for data in train_data],
                    "context_size": args.context_size,
                    "bptt_frames": args.bptt_frames,
                    "crop_size": args.crop_size,
                    "validation": aggregate,
                    "promotion": False,
                    "live_runtime_tested": False,
                },
                args.output / "best.pt",
            )
        (args.output / "history.jsonl").write_text(
            "\n".join(json.dumps(record) for record in history) + "\n", encoding="utf-8"
        )
        print(json.dumps({"step": step, "validation": aggregate}, indent=2), flush=True)
        return aggregate

    validation_bundle(0)
    for step in range(1, args.steps + 1):
        loss = _train_one_step(
            model,
            optimizer,
            train_data,
            step,
            args.context_size,
            args.bptt_frames,
            args.crop_size,
            args.delta_weight,
            args.target_strength,
            args.luma_loss,
            device,
            rng,
        )
        if step == 1 or step % 5 == 0:
            print(json.dumps({"step": step, "loss": loss, "seconds": time.perf_counter() - started}), flush=True)
        if step % args.eval_every == 0 or step == args.steps:
            validation_bundle(step)

    best_path = args.output / "best.pt"
    best_checkpoint = torch.load(best_path, map_location=device, weights_only=True)
    model.load_state_dict(best_checkpoint["model"])
    final_training_validations = [
        _evaluate_sequence(model, data, data["heldout_frames"], args.context_size, device)
        for data in train_data
    ]
    test_descriptor: dict[str, Any] | None = None
    test_result: dict[str, Any] | None = None
    if args.test_replay_root is not None:
        test_data = _load_metadata(args.test_replay_root, args.train_fraction)
        test_descriptor = _descriptor(test_data)
        test_result = _evaluate_sequence(model, test_data, test_data["frames"], args.context_size, device)
    result = {
        "schema": "opennr-fast-student-reduced-native-streaming-training-v1",
        "checkpoint": str(best_path.resolve()),
        "train_replays": [_descriptor(data) for data in train_data],
        "test_replay": test_descriptor,
        "test_result": test_result,
        "work_dimensions": [work_width, work_height],
        "full_dimensions": [FULL_WIDTH, FULL_HEIGHT],
        "steps": args.steps,
        "config": config_dict(config),
        "parameters": sum(parameter.numel() for parameter in model.parameters()),
        "context_size": args.context_size,
        "bptt_frames": args.bptt_frames,
        "crop_size": args.crop_size,
        "target_strength": args.target_strength,
        "luma_loss": args.luma_loss,
        "residual_scale": config.residual_scale,
        "best_heldout_work_mae": best_value,
        "final_training_validations": final_training_validations,
        "history": history,
        "wall_seconds": time.perf_counter() - started,
        "promotion": False,
        "live_runtime_tested": False,
        "scope": "streamed multi-sequence reduced-native target fit with truncated BPTT; not live temporal, stereo, headset, or VR acceptance",
    }
    (args.output / "result.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
