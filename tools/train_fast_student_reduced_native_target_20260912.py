"""Train FastStudent-v1 directly against a reduced native DLSS-NR target.

This is a bounded diagnostic experiment for the NeuralScreen-style route.  It
uses only the retained 50% native replay and teaches the small network to
reproduce the *reduced native neural output* at the work resolution.  The
full-resolution evaluation remains:

    full_input + upsample(student_work - work_input)

The experiment is deliberately separate from the existing crop-cache student
lineage.  Its held-out frames are from the same short sequence, so it can show
whether the target/objective is learnable but cannot establish generalization,
temporal quality, stereo acceptance, or live VR readiness.
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
            + _resize(
                prediction - item["work_input"],
                FULL_HEIGHT,
                FULL_WIDTH,
            )
        ).clamp(0.0, 1.0)
        native_full = (
            item["full_input"]
            + _resize(
                item["native_work"] - item["work_input"],
                FULL_HEIGHT,
                FULL_WIDTH,
            )
        ).clamp(0.0, 1.0)
        result = _metrics(
            student_full.float().cpu(),
            native_full.float().cpu(),
            item["full_input"].float().cpu(),
        )
        result["work_mae_vs_native"] = float(
            (prediction.float() - item["native_work"].float()).abs().mean().item()
        )
        result["student_full_mae_vs_native50_composite"] = result["mae"]
        result["native50_composite_mae_vs_full_teacher"] = float(
            _metrics(
                native_full.float().cpu(),
                item["full_teacher"].float().cpu(),
                item["full_input"].float().cpu(),
            )["mae"]
        )
        result["student_full_mae_vs_full_teacher"] = float(
            _metrics(
                student_full.float().cpu(),
                item["full_teacher"].float().cpu(),
                item["full_input"].float().cpu(),
            )["mae"]
        )
        return result


def _load_items(
    replay_root: Path,
    sequence: Path,
    frame_ids: list[int],
    work_width: int,
    work_height: int,
    context_size: int,
    device: torch.device,
) -> dict[tuple[int, int], dict[str, torch.Tensor]]:
    items: dict[tuple[int, int], dict[str, torch.Tensor]] = {}
    for frame_id in frame_ids:
        for eye in (0, 1):
            item = _load_frame(
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
            items[(frame_id, eye)] = item
    return items


def _evaluate_sequence(
    model: FastStudentV1,
    items: dict[tuple[int, int], dict[str, torch.Tensor]],
    frame_ids: list[int],
    eyes: tuple[int, ...],
) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    model.eval()
    with torch.inference_mode():
        for eye in eyes:
            state = None
            for frame_id in frame_ids:
                item = items[(frame_id, eye)]
                prediction, state = model.forward_temporal(
                    item["work_input"],
                    item["guides"],
                    item["context"],
                    state,
                )
                metrics = _target_metrics(prediction, item)
                records.append({"frame_id": frame_id, "eye": eye, **metrics})
    def mean(name: str) -> float:
        return float(np.mean([float(record[name]) for record in records]))
    return {
        "frames": frame_ids,
        "eyes": list(eyes),
        "sample_count": len(records),
        "records": records,
        "student_full_mae_vs_native50_mean": mean("student_full_mae_vs_native50_composite"),
        "student_work_mae_vs_native_mean": mean("work_mae_vs_native"),
        "student_full_mae_vs_full_teacher_mean": mean("student_full_mae_vs_full_teacher"),
        "native50_composite_mae_vs_full_teacher_mean": mean(
            "native50_composite_mae_vs_full_teacher"
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--replay-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--train-through", type=int, default=6)
    parser.add_argument("--steps", type=int, default=300)
    parser.add_argument("--lr", type=float, default=2e-4)
    parser.add_argument("--target-weight", type=float, default=1.0)
    parser.add_argument("--delta-weight", type=float, default=0.05)
    parser.add_argument("--eval-every", type=int, default=50)
    parser.add_argument("--base-width", type=int, default=16)
    parser.add_argument("--mid-width", type=int, default=32)
    parser.add_argument("--temporal-hidden", type=int, default=32)
    parser.add_argument("--blocks", type=int, default=1)
    parser.add_argument("--context-size", type=int, default=96)
    parser.add_argument("--seed", type=int, default=120912)
    parser.add_argument("--device", default="cuda")
    args = parser.parse_args()

    if args.output.exists() and any(args.output.iterdir()):
        raise FileExistsError(f"refusing to use non-empty output directory: {args.output}")
    if args.train_through < 1 or args.steps < 1 or args.eval_every < 1:
        raise ValueError("train-through, steps, and eval-every must be positive")
    if not torch.cuda.is_available() and args.device.startswith("cuda"):
        raise RuntimeError("CUDA is required for this training experiment")

    args.output.mkdir(parents=True, exist_ok=True)
    random.seed(args.seed)
    np.random.seed(args.seed)
    torch.manual_seed(args.seed)
    if args.device.startswith("cuda"):
        torch.cuda.manual_seed_all(args.seed)
    torch.backends.cudnn.benchmark = True
    device = torch.device(args.device)

    replay_root = args.replay_root.resolve()
    manifest_path = replay_root / "input_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    sequence = Path(manifest["sequence"])
    frame_ids = [int(value) for value in manifest["frames"]]
    if args.train_through >= len(frame_ids):
        raise ValueError("train-through must leave held-out frames")
    work_width, work_height = (int(value) for value in manifest["network_dimensions"])
    train_frames = frame_ids[: args.train_through]
    heldout_frames = frame_ids[args.train_through :]
    items = _load_items(
        replay_root,
        sequence,
        frame_ids,
        work_width,
        work_height,
        args.context_size,
        device,
    )

    config = FastStudentConfig(
        base_width=args.base_width,
        mid_width=args.mid_width,
        temporal_hidden=args.temporal_hidden,
        blocks=args.blocks,
    )
    model = FastStudentV1(config).to(device).train()
    optimizer = torch.optim.AdamW(model.parameters(), lr=args.lr, weight_decay=1e-4)
    train_eye = 0
    history: list[dict[str, Any]] = []
    best_value = float("inf")
    started = time.perf_counter()

    def run_validation(step: int) -> None:
        nonlocal best_value
        validation = _evaluate_sequence(model, items, heldout_frames, (0, 1))
        history.append({"step": step, "validation": validation})
        if validation["student_work_mae_vs_native_mean"] < best_value:
            best_value = validation["student_work_mae_vs_native_mean"]
            torch.save(
                {
                    "architecture": "fast_student_v1",
                    "config": config_dict(model.config),
                    "model": {name: value.detach().cpu() for name, value in model.state_dict().items()},
                    "step": step,
                    "seed": args.seed,
                    "learning_rate": args.lr,
                    "target": "native_reduced_work_output",
                    "work_scale": float(manifest["scale_percent"]) / 100.0,
                    "replay_root": str(replay_root),
                    "replay_manifest_sha256": _sha256(manifest_path),
                    "train_frames": train_frames,
                    "heldout_frames": heldout_frames,
                    "context_size": args.context_size,
                    "validation": validation,
                    "promotion": False,
                    "live_runtime_tested": False,
                },
                args.output / "best.pt",
            )
        (args.output / "history.jsonl").write_text(
            "\n".join(json.dumps(record) for record in history) + "\n",
            encoding="utf-8",
        )
        print(json.dumps({"step": step, "validation": validation}, indent=2), flush=True)

    run_validation(0)
    for step in range(1, args.steps + 1):
        # Use the same causal sequence beginning at reset for every update;
        # rotate eyes so the two stereo streams both contribute.
        eye = train_eye
        train_eye = 1 - train_eye
        state = None
        previous_prediction: torch.Tensor | None = None
        previous_target: torch.Tensor | None = None
        losses: list[torch.Tensor] = []
        model.train()
        optimizer.zero_grad(set_to_none=True)
        for frame_id in train_frames:
            item = items[(frame_id, eye)]
            prediction, state = model.forward_temporal(
                item["work_input"],
                item["guides"],
                item["context"],
                state,
            )
            loss = args.target_weight * (prediction - item["native_work"]).abs().mean()
            if previous_prediction is not None and previous_target is not None:
                loss = loss + args.delta_weight * (
                    (prediction - previous_prediction) - (item["native_work"] - previous_target)
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
            run_validation(step)

    final = _evaluate_sequence(model, items, frame_ids, (0, 1))
    result = {
        "schema": "opennr-fast-student-reduced-native-target-training-v1",
        "checkpoint": str((args.output / "best.pt").resolve()),
        "replay_root": str(replay_root),
        "replay_manifest_sha256": _sha256(manifest_path),
        "sequence": str(sequence.resolve()),
        "work_dimensions": [work_width, work_height],
        "full_dimensions": [FULL_WIDTH, FULL_HEIGHT],
        "train_frames": train_frames,
        "heldout_frames": heldout_frames,
        "steps": args.steps,
        "config": config_dict(config),
        "parameters": sum(parameter.numel() for parameter in model.parameters()),
        "context_size": args.context_size,
        "best_heldout_work_mae": best_value,
        "final_full_sequence": final,
        "history": history,
        "wall_seconds": time.perf_counter() - started,
        "promotion": False,
        "live_runtime_tested": False,
        "scope": "single-sequence reduced-native target fit; not sequence-disjoint, temporal, stereo, or VR acceptance",
    }
    (args.output / "result.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
