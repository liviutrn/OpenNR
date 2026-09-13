"""Train a low-work FastStudent on multiple retained native replays.

This is a bounded follow-up to the single-sequence reduced-native target
experiment.  Each replay is an independent stateful sequence: the model state
is reset at the start of every sequence/eye and is unrolled through that
sequence's training frames.  A separate replay may be held out entirely for
the final sequence-disjoint check.

The learned output is always evaluated as:

    full_input + upsample(student_work - work_input)

No live OpenNR or Skyrim runtime is touched by this script.
"""

from __future__ import annotations

import argparse
import hashlib
import json
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
        against_native50 = _metrics(
            student_full.float().cpu(),
            native_full.float().cpu(),
            item["full_input"].float().cpu(),
        )
        native_teacher = _metrics(
            native_full.float().cpu(),
            item["full_teacher"].float().cpu(),
            item["full_input"].float().cpu(),
        )
        student_teacher = _metrics(
            student_full.float().cpu(),
            item["full_teacher"].float().cpu(),
            item["full_input"].float().cpu(),
        )
        return {
            "student_full_mae_vs_native50": float(against_native50["mae"]),
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
                against_native50["finite"]
                and native_teacher["finite"]
                and student_teacher["finite"]
            ),
        }


def _load_sequence(
    replay_root: Path,
    context_size: int,
    device: torch.device,
    train_fraction: float,
) -> dict[str, Any]:
    replay_root = replay_root.resolve()
    manifest_path = replay_root / "input_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    sequence = Path(manifest["sequence"])
    frame_ids = [int(value) for value in manifest["frames"]]
    if len(frame_ids) < 4:
        raise ValueError(f"replay must contain at least four frames: {replay_root}")
    train_count = max(1, min(len(frame_ids) - 1, int(len(frame_ids) * train_fraction)))
    train_frames = frame_ids[:train_count]
    heldout_frames = frame_ids[train_count:]
    work_width, work_height = (int(value) for value in manifest["network_dimensions"])
    items: dict[tuple[int, int], dict[str, torch.Tensor]] = {}
    for frame_id in frame_ids:
        for eye in (0, 1):
            items[(frame_id, eye)] = _load_frame(
                replay_root,
                sequence,
                frame_id,
                eye,
                work_width,
                work_height,
                context_size,
                context_size,
                device,
                torch.float32,
            )
    return {
        "replay_root": replay_root,
        "manifest_path": manifest_path,
        "manifest_sha256": _sha256(manifest_path),
        "sequence": sequence.resolve(),
        "frames": frame_ids,
        "train_frames": train_frames,
        "heldout_frames": heldout_frames,
        "work_dimensions": [work_width, work_height],
        "items": items,
    }


def _evaluate_sequence(
    model: FastStudentV1,
    data: dict[str, Any],
    frame_ids: list[int],
    device: torch.device,
) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    model.eval()
    with torch.inference_mode():
        for eye in (0, 1):
            state = None
            for frame_id in frame_ids:
                item = data["items"][(frame_id, eye)]
                prediction, state = model.forward_temporal(
                    item["work_input"], item["guides"], item["context"], state
                )
                metrics = _target_metrics(prediction, item)
                records.append({"frame_id": frame_id, "eye": eye, **metrics})

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


def _descriptor(data: dict[str, Any]) -> dict[str, Any]:
    return {
        "replay_root": str(data["replay_root"]),
        "manifest_sha256": data["manifest_sha256"],
        "sequence": str(data["sequence"]),
        "frames": data["frames"],
        "train_frames": data["train_frames"],
        "heldout_frames": data["heldout_frames"],
        "work_dimensions": data["work_dimensions"],
    }


def _release_items(data: dict[str, Any]) -> None:
    for item in data["items"].values():
        for value in item.values():
            if isinstance(value, torch.Tensor):
                del value
    data["items"].clear()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--train-replay-root",
        type=Path,
        action="append",
        required=True,
        help="retained native replay used for fitting; pass at least two times",
    )
    parser.add_argument(
        "--test-replay-root",
        type=Path,
        help="optional sequence-disjoint native replay evaluated only after fitting",
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--resume-checkpoint",
        type=Path,
        help="optional saved best.pt; --steps then means additional steps",
    )
    parser.add_argument("--train-fraction", type=float, default=0.75)
    parser.add_argument("--steps", type=int, default=300)
    parser.add_argument("--lr", type=float, default=2e-4)
    parser.add_argument("--delta-weight", type=float, default=0.05)
    parser.add_argument("--eval-every", type=int, default=50)
    parser.add_argument("--base-width", type=int, default=16)
    parser.add_argument("--mid-width", type=int, default=32)
    parser.add_argument("--temporal-hidden", type=int, default=32)
    parser.add_argument("--blocks", type=int, default=1)
    parser.add_argument("--context-size", type=int, default=96)
    parser.add_argument("--seed", type=int, default=120913)
    parser.add_argument("--device", default="cuda")
    args = parser.parse_args()

    if len(args.train_replay_root) < 2:
        raise ValueError("pass at least two --train-replay-root values")
    if args.output.exists() and any(args.output.iterdir()):
        raise FileExistsError(f"refusing to use non-empty output directory: {args.output}")
    if args.steps < 1 or args.eval_every < 1:
        raise ValueError("steps and eval-every must be positive")
    if not 0.0 < args.train_fraction < 1.0:
        raise ValueError("train-fraction must be between zero and one")
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

    train_data = [
        _load_sequence(root, args.context_size, device, args.train_fraction)
        for root in args.train_replay_root
    ]
    dimensions = {tuple(data["work_dimensions"]) for data in train_data}
    if len(dimensions) != 1:
        raise ValueError(f"all training replays must have the same work dimensions: {dimensions}")
    work_width, work_height = next(iter(dimensions))

    config = FastStudentConfig(
        base_width=args.base_width,
        mid_width=args.mid_width,
        temporal_hidden=args.temporal_hidden,
        blocks=args.blocks,
    )
    model = FastStudentV1(config).to(device).train()
    optimizer = torch.optim.AdamW(model.parameters(), lr=args.lr, weight_decay=1e-4)
    history: list[dict[str, Any]] = []
    best_value = float("inf")
    start_step = 0
    if args.resume_checkpoint is not None:
        resume_path = args.resume_checkpoint.resolve()
        saved = torch.load(resume_path, map_location=device, weights_only=True)
        if saved.get("architecture") != "fast_student_v1":
            raise ValueError(f"resume checkpoint is not a fast_student_v1 model: {resume_path}")
        if saved.get("config") != config_dict(config):
            raise ValueError("resume checkpoint config does not match the requested model config")
        model.load_state_dict(saved["model"])
        start_step = int(saved.get("step", 0))
        prior_validation = saved.get("validation", {})
        if isinstance(prior_validation, dict):
            best_value = float(
                prior_validation.get("student_work_mae_vs_native_mean", float("inf"))
            )
        print(
            json.dumps(
                {
                    "resuming": str(resume_path),
                    "start_step": start_step,
                    "best_validation_work_mae": best_value,
                }
            ),
            flush=True,
        )
    started = time.perf_counter()

    def validation_bundle(step: int) -> dict[str, Any]:
        nonlocal best_value
        validations = [
            _evaluate_sequence(model, data, data["heldout_frames"], device)
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
                    "model": {
                        name: value.detach().cpu()
                        for name, value in model.state_dict().items()
                    },
                    "step": step,
                    "seed": args.seed,
                    "learning_rate": args.lr,
                    "target": "native_reduced_work_output",
                    "work_scale": 0.5,
                    "train_replays": [_descriptor(data) for data in train_data],
                    "context_size": args.context_size,
                    "validation": aggregate,
                    "promotion": False,
                    "live_runtime_tested": False,
                },
                args.output / "best.pt",
            )
        (args.output / "history.jsonl").write_text(
            "\n".join(json.dumps(record) for record in history) + "\n",
            encoding="utf-8",
        )
        print(json.dumps({"step": step, "validation": aggregate}, indent=2), flush=True)
        return aggregate

    validation_bundle(start_step)
    for step in range(start_step + 1, start_step + args.steps + 1):
        losses: list[torch.Tensor] = []
        model.train()
        optimizer.zero_grad(set_to_none=True)
        for data_index, data in enumerate(train_data):
            eye = (step - 1 + data_index) % 2
            state = None
            previous_prediction: torch.Tensor | None = None
            previous_target: torch.Tensor | None = None
            for frame_id in data["train_frames"]:
                item = data["items"][(frame_id, eye)]
                prediction, state = model.forward_temporal(
                    item["work_input"], item["guides"], item["context"], state
                )
                loss = (prediction - item["native_work"]).abs().mean()
                if previous_prediction is not None and previous_target is not None:
                    loss = loss + args.delta_weight * (
                        (prediction - previous_prediction)
                        - (item["native_work"] - previous_target)
                    ).square().add(1e-6).sqrt().mean()
                losses.append(loss)
                previous_prediction = prediction
                previous_target = item["native_work"]
        total_loss = torch.stack(losses).mean()
        if not torch.isfinite(total_loss):
            raise RuntimeError(f"non-finite loss at step {step}")
        total_loss.backward()
        gradient = torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
        if not torch.isfinite(gradient):
            raise RuntimeError(f"non-finite gradient at step {step}")
        optimizer.step()
        if step == 1 or step % 25 == 0:
            print(
                json.dumps(
                    {
                        "step": step,
                        "loss": float(total_loss.detach().cpu()),
                        "seconds": time.perf_counter() - started,
                    }
                ),
                flush=True,
            )
        if step % args.eval_every == 0 or step == args.steps:
            validation_bundle(step)

    best_path = args.output / "best.pt"
    best_checkpoint = torch.load(best_path, map_location=device, weights_only=True)
    model.load_state_dict(best_checkpoint["model"])
    final_training_validations = [
        _evaluate_sequence(model, data, data["heldout_frames"], device)
        for data in train_data
    ]

    test_descriptor: dict[str, Any] | None = None
    test_result: dict[str, Any] | None = None
    if args.test_replay_root is not None:
        # Release the training tensors before loading the independent test
        # replay; full-eye inputs are intentionally retained for metrics.
        for data in train_data:
            _release_items(data)
        if device.type == "cuda":
            torch.cuda.empty_cache()
        test_data = _load_sequence(
            args.test_replay_root, args.context_size, device, args.train_fraction
        )
        test_descriptor = _descriptor(test_data)
        test_result = _evaluate_sequence(model, test_data, test_data["frames"], device)
        _release_items(test_data)

    result = {
        "schema": "opennr-fast-student-reduced-native-multiseq-training-v1",
        "checkpoint": str(best_path.resolve()),
        "train_replays": [_descriptor(data) for data in train_data],
        "test_replay": test_descriptor,
        "test_result": test_result,
        "work_dimensions": [work_width, work_height],
        "full_dimensions": [FULL_WIDTH, FULL_HEIGHT],
        "start_step": start_step,
        "additional_steps": args.steps,
        "steps": start_step + args.steps,
        "config": config_dict(config),
        "parameters": sum(parameter.numel() for parameter in model.parameters()),
        "context_size": args.context_size,
        "best_heldout_work_mae": best_value,
        "final_training_validations": final_training_validations,
        "history": history,
        "wall_seconds": time.perf_counter() - started,
        "promotion": False,
        "live_runtime_tested": False,
        "scope": (
            "multi-sequence reduced-native target fit with an optional sequence-disjoint test; "
            "not live temporal, stereo, headset, or VR acceptance"
        ),
    }
    (args.output / "result.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
