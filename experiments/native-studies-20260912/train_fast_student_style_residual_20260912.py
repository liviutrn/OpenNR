"""Train an isolated low-resolution neural-style residual student.

This runner deliberately lives outside the project checkout because the D:
volume is full.  It reuses the streaming replay loader/model, but changes the
training objective to supervise the native luminance gain/residual directly.
The output remains a normal FastStudentV1 checkpoint and is research-only.
"""

from __future__ import annotations

import json
import math
import random
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


def _gradient(value: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
    return value[..., 1:, :] - value[..., :-1, :], value[..., :, 1:] - value[..., :, :-1]


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
    rng: random.Random,
) -> float:
    del luma_loss
    model.train()
    optimizer.zero_grad(set_to_none=True)
    total_chunks = sum(
        math.ceil(len(data["train_frames"]) / bptt_frames) for data in train_data
    )
    if total_chunks < 1:
        raise ValueError("no training chunks")

    loss_sum = 0.0
    total_frames = sum(len(data["train_frames"]) for data in train_data)
    for data_index, data in enumerate(train_data):
        eye = (step - 1 + data_index) % 2
        crop_rng = random.Random(rng.randrange(2**31))
        state = None
        previous_pred_delta = None
        previous_target_delta = None
        chunk_losses: list[torch.Tensor] = []

        for frame_index, frame_id in enumerate(data["train_frames"]):
            cpu_item = trainer._read_item(data, frame_id, eye, context_size)
            cropped = trainer._crop_item(cpu_item, crop_size, crop_rng)
            item = {name: value.to(device=device) for name, value in cropped.items()}
            raw = item["work_input"]
            prediction, next_state = model.forward_temporal(
                raw, item["guides"], item["context"], state
            )
            target = (
                raw + target_strength * (item["native_work"] - raw)
            ).clamp(0.0, 1.0)

            # The luma student is multiplicative.  Comparing normalized luma
            # residuals removes the large identity term and gives dark regions
            # a useful gradient instead of rewarding a near-identity output.
            raw_low = _lowres_luma(raw, model)
            pred_low = _lowres_luma(prediction, model)
            target_low = _lowres_luma(target, model)
            denominator = raw_low.detach().add(0.05).clamp_min(0.05)
            pred_delta = (pred_low - raw_low) / denominator
            target_delta = (target_low - raw_low) / denominator

            loss = (pred_delta - target_delta).abs().mean()

            # Keep the absolute treatment anchored to the teacher and retain
            # local structure after downsampling.  These terms are intentionally
            # modest so the model cannot win by inventing an aggressive grade.
            loss = loss + 0.35 * (pred_low - target_low).abs().mean()
            pred_grad_y, pred_grad_x = _gradient(pred_delta)
            target_grad_y, target_grad_x = _gradient(target_delta)
            loss = loss + 0.20 * (
                (pred_grad_y - target_grad_y).abs().mean()
                + (pred_grad_x - target_grad_x).abs().mean()
            )

            if previous_pred_delta is not None and previous_target_delta is not None:
                loss = loss + delta_weight * (
                    (pred_delta - previous_pred_delta)
                    - (target_delta - previous_target_delta)
                ).square().add(1e-6).sqrt().mean()

            chunk_losses.append(loss)
            loss_sum += float(loss.detach().cpu())
            previous_pred_delta = pred_delta
            previous_target_delta = target_delta
            state = next_state
            del target, item, cropped, cpu_item, raw_low, pred_low, target_low
            del denominator, pred_delta, target_delta, pred_grad_y, pred_grad_x
            del target_grad_y, target_grad_x

            if len(chunk_losses) >= bptt_frames or frame_index == len(data["train_frames"]) - 1:
                torch.stack(chunk_losses).mean().div_(total_chunks).backward()
                state = trainer._detach_state(state)
                previous_pred_delta = previous_pred_delta.detach()
                previous_target_delta = previous_target_delta.detach()
                chunk_losses = []

    gradient = torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
    if not torch.isfinite(gradient):
        raise RuntimeError(f"non-finite gradient at step {step}")
    optimizer.step()
    return loss_sum / total_frames


trainer._train_one_step = _train_one_step

exit_code = trainer.main()
if exit_code == 0:
    try:
        output_index = sys.argv.index("--output") + 1
        output = Path(sys.argv[output_index]).resolve()
        result_path = output / "result.json"
        result = json.loads(result_path.read_text(encoding="utf-8"))
        result["style_residual_loss"] = True
        result["loss_recipe"] = {
            "normalized_luma_residual": 1.0,
            "absolute_lowres_luma": 0.35,
            "lowres_residual_gradient": 0.20,
            "temporal_residual_delta": "trainer_delta_weight",
        }
        result["scope"] += "; direct native residual/gain style objective; offline research only"
        result_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        checkpoint_path = output / "best.pt"
        checkpoint = torch.load(checkpoint_path, map_location="cpu", weights_only=False)
        checkpoint["style_residual_loss"] = True
        checkpoint["loss_recipe"] = result["loss_recipe"]
        torch.save(checkpoint, checkpoint_path)
    except Exception as exc:  # pragma: no cover - metadata is best effort
        print(json.dumps({"metadata_warning": str(exc)}), flush=True)
raise SystemExit(exit_code)
