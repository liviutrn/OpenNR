"""Run one isolated FastStudent fit with low-resolution luminance supervision.

The project checkout is on a full volume, so this runner lives beside the
derived C: experiment artifacts and reuses the checkout trainer without
modifying it.  It replaces only the optimizer-step loss: both prediction and
target are downsampled to the student's first spatial grid before luminance
error is measured.
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import torch

TOOLS = Path(r"D:\.CODEX_Projects\OpenNR-VR\tools")
sys.path.insert(0, str(TOOLS))

import train_fast_student_reduced_native_streaming_20260912 as trainer  # noqa: E402


def _luma(value: torch.Tensor) -> torch.Tensor:
    return (
        0.2126 * value[:, 0:1]
        + 0.7152 * value[:, 1:2]
        + 0.0722 * value[:, 2:3]
    )


def _lowres_luma(value: torch.Tensor, model: torch.nn.Module) -> torch.Tensor:
    scale = int(model.config.model_scale)
    height = max(1, (value.shape[-2] + scale - 1) // scale)
    width = max(1, (value.shape[-1] + scale - 1) // scale)
    return _luma(trainer._resize(value, height, width))


def _train_one_step(
    model: trainer.FastStudentV1,
    optimizer: torch.optim.Optimizer,
    train_data: list[dict[str, object]],
    step: int,
    context_size: int,
    bptt_frames: int,
    crop_size: int,
    delta_weight: float,
    target_strength: float,
    luma_loss: bool,
    device: torch.device,
    rng: object,
) -> float:
    del luma_loss  # This runner always uses the explicitly named low-res loss.
    model.train()
    optimizer.zero_grad(set_to_none=True)
    total_chunks = sum(
        math.ceil(len(data["train_frames"]) / bptt_frames) for data in train_data
    )
    if total_chunks < 1:
        raise ValueError("no training chunks")
    loss_sum = 0.0
    for data_index, data in enumerate(train_data):
        eye = (step - 1 + data_index) % 2
        frame_ids = data["train_frames"]
        crop_rng = __import__("random").Random(rng.randrange(2**31))
        state = None
        previous_prediction_luma = None
        previous_target_luma = None
        chunk_losses: list[torch.Tensor] = []
        for frame_index, frame_id in enumerate(frame_ids):
            cpu_item = trainer._read_item(data, frame_id, eye, context_size)
            cropped = trainer._crop_item(cpu_item, crop_size, crop_rng)
            item = {name: value.to(device=device) for name, value in cropped.items()}
            prediction, next_state = model.forward_temporal(
                item["work_input"], item["guides"], item["context"], state
            )
            target = (
                item["work_input"]
                + target_strength * (item["native_work"] - item["work_input"])
            ).clamp(0.0, 1.0)
            prediction_luma = _lowres_luma(prediction, model)
            target_luma = _lowres_luma(target, model)
            loss = (prediction_luma - target_luma).abs().mean()
            if previous_prediction_luma is not None and previous_target_luma is not None:
                loss = loss + delta_weight * (
                    (prediction_luma - previous_prediction_luma)
                    - (target_luma - previous_target_luma)
                ).square().add(1e-6).sqrt().mean()
            chunk_losses.append(loss)
            loss_sum += float(loss.detach().cpu())
            previous_prediction_luma = prediction_luma
            previous_target_luma = target_luma
            state = next_state
            del target, item, cropped, cpu_item, prediction_luma, target_luma
            at_chunk_end = (
                len(chunk_losses) >= bptt_frames or frame_index == len(frame_ids) - 1
            )
            if at_chunk_end:
                torch.stack(chunk_losses).mean().div_(total_chunks).backward()
                state = trainer._detach_state(state)
                previous_prediction_luma = previous_prediction_luma.detach()
                previous_target_luma = previous_target_luma.detach()
                chunk_losses = []
    gradient = torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
    if not torch.isfinite(gradient):
        raise RuntimeError(f"non-finite gradient at step {step}")
    optimizer.step()
    return loss_sum / sum(len(data["train_frames"]) for data in train_data)


trainer._train_one_step = _train_one_step

exit_code = trainer.main()
if exit_code == 0:
    try:
        output_index = sys.argv.index("--output") + 1
        output = Path(sys.argv[output_index]).resolve()
        result_path = output / "result.json"
        result = json.loads(result_path.read_text(encoding="utf-8"))
        result["luma_lowres_loss"] = True
        result["scope"] += "; luminance loss measured after downsampling to the student spatial grid"
        result_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        checkpoint_path = output / "best.pt"
        checkpoint = torch.load(checkpoint_path, map_location="cpu", weights_only=False)
        checkpoint["luma_lowres_loss"] = True
        torch.save(checkpoint, checkpoint_path)
    except Exception as exc:  # pragma: no cover - metadata is best effort
        print(json.dumps({"metadata_warning": str(exc)}), flush=True)
raise SystemExit(exit_code)
