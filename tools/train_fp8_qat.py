"""Short clamp-E4M3 fake-quantization-aware fine-tune.

This is a research-only QAT arm.  It starts from the selected direct step-0
checkpoint, applies the same symmetric ``clamp(-448,448) -> E4M3 -> dequant``
activation transform measured by :mod:`instrument_fp8_activation_pair`, and
uses the already serialized 1,200-window schedule from the matched residual
experiment.  Test rows remain untouched.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import time

import numpy as np
import torch
from torch import nn

from joint_parent_tone_model import load_joint_checkpoint
from prepare_conditioning_pilot import sha
from train_residual_target_pair import (
    ResidualView,
    _aggregate,
    _sha256_file,
    evaluate_all,
)
from train_spatial_tone import frame_objective


FP8_DTYPE = torch.float8_e4m3fn
WINDOW = 8
BURN_IN = 2
HEAD_LR = 5e-5
PARENT_LR = 5e-6
WEIGHT_DECAY = 1e-4
MIN_LR_FACTOR = 0.20


def _json_default(value):
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value)
    if isinstance(value, np.ndarray):
        return value.tolist()
    raise TypeError(type(value).__name__)


def _write_json(path: Path, value) -> None:
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(
        json.dumps(value, indent=2, sort_keys=True, default=_json_default) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _immediate_next(root: nn.Module, relative: str):
    """Return the next sibling in a sequential-like parent, if there is one."""

    parts = relative.split(".")
    if len(parts) < 2:
        return None
    parent = root
    for part in parts[:-1]:
        child = parent._modules.get(part)
        if child is None:
            return None
        parent = child
    child_name = parts[-1]
    names = list(parent._modules)
    if child_name not in names:
        return None
    index = names.index(child_name)
    if index + 1 >= len(names):
        return None
    next_name = names[index + 1]
    return next_name, parent._modules[next_name]


def _parameter_count(module: nn.Module) -> int:
    return sum(parameter.numel() for parameter in module.parameters())


class ClampE4M3QAT:
    """Straight-through fake activation quantization with an auditable scope.

    ``broad`` preserves the original diagnostic arm. ``selective`` is the
    causal QAT arm: it covers expensive spatial convolutions and DINO
    attention/FFN/projection linears, while explicitly leaving normalization
    inputs, final/gate outputs, the temporal branch, and tiny operations in
    FP16/BF16.
    """

    def __init__(self, selection: str = "broad"):
        if selection not in ("broad", "selective"):
            raise ValueError(f"Unknown QAT selection: {selection}")
        self.selection = selection
        self.handles = []
        self.module_names = []
        self.decisions = []

    def _decision(self, root_name: str, root: nn.Module, relative: str, module: nn.Module):
        full_name = f"{root_name}.{relative}"
        params = _parameter_count(module)
        type_name = type(module).__name__
        if self.selection == "broad":
            if full_name.startswith("head.encoder."):
                return "exclude", "frozen_encoder_diagnostic_scope"
            return "include", "broad_mutable_conv_or_linear"

        # Frozen DINO is still an expensive inference path. Its attention and
        # FFN/projection outputs are useful activation candidates even though
        # the encoder weights themselves remain frozen.
        if full_name.startswith("head.encoder."):
            if full_name == "head.encoder.patch_embed.proj":
                return "exclude", "encoder_stem_feeds_normalization_path"
            if any(
                token in relative
                for token in (".attn.qkv", ".attn.proj", ".mlp.fc1", ".mlp.fc2")
            ):
                return "include", "frozen_encoder_qkv_ffn_or_projection"
            return "exclude", "frozen_encoder_non_candidate"

        # These outputs either become the externally delivered image, a
        # native-resolution gate, or the temporal recurrent branch. They are
        # intentionally left at the surrounding compute precision.
        if root_name == "parent" and relative.startswith("temporal_"):
            return "exclude", "temporal_state_path"
        if root_name == "parent" and relative in {
            "output",
            "capacity_output",
            "capacity_extra_output",
            "capacity_gate",
            "capacity_extra_gate",
            "capacity_final_gate",
        }:
            return "exclude", "final_or_gate_output"
        if root_name == "head" and relative == "affine":
            return "exclude", "final_output_affine"

        # The outputs of these reducers are consumed by ChannelNorm/GroupNorm
        # at the next block boundary. Quantizing before the sensitive
        # normalization would confound this QAT arm with normalization error.
        if root_name == "parent" and relative in {
            "stem",
            "d1",
            "d2",
            "u1",
            "u2",
            "capacity_input",
            "capacity_extra_input",
        }:
            return "exclude", "feeds_sensitive_channel_normalization"
        next_sibling = _immediate_next(root, relative)
        if isinstance(module, nn.Conv2d) and next_sibling is not None:
            if isinstance(next_sibling[1], nn.GroupNorm):
                return "exclude", "feeds_sensitive_group_normalization"

        # Control gates and small projections are deliberately deferred. A
        # depthwise spatial convolution can have few parameters but still be
        # a material compute point, so retain wide depthwise candidates.
        depthwise_expensive = (
            isinstance(module, nn.Conv2d)
            and module.groups == module.in_channels
            and module.out_channels >= 128
        )
        explicit_projection = full_name == "head.semantic_projection"
        if params < 16000 and not depthwise_expensive and not explicit_projection:
            return "exclude", "tiny_operation_deferred"

        if explicit_projection:
            return "include", "trainable_semantic_projection"
        if isinstance(module, nn.Linear) and ".attn." in relative:
            return "include", "attention_projection"
        if isinstance(module, nn.Linear) and ".mlp." in relative:
            return "include", "ffn_projection"
        if isinstance(module, nn.Conv2d) and depthwise_expensive:
            return "include", "wide_depthwise_spatial_conv"
        return "include", "expensive_conv_or_projection"

    def attach(self, model) -> None:
        for root_name, root in (("parent", model.parent), ("head", model.head)):
            for relative, module in root.named_modules():
                if not relative or not isinstance(module, (nn.Conv2d, nn.Linear)):
                    continue
                action, reason = self._decision(root_name, root, relative, module)
                full_name = f"{root_name}.{relative}"
                self.decisions.append(
                    {
                        "name": full_name,
                        "type": type(module).__name__,
                        "parameters": _parameter_count(module),
                        "requires_grad": any(p.requires_grad for p in module.parameters()),
                        "action": action,
                        "reason": reason,
                    }
                )
                if action != "include":
                    continue
                self.module_names.append(full_name)
                self.handles.append(module.register_forward_hook(self._hook))

    @staticmethod
    def _hook(_module, _inputs, output):
        if not torch.is_tensor(output):
            return output
        quantized = output.detach().float().clamp(-448.0, 448.0).to(FP8_DTYPE).to(output.dtype)
        # Forward uses the fake-quantized value; backward sees the identity.
        return output + (quantized - output).detach()

    def remove(self) -> None:
        for handle in self.handles:
            handle.remove()
        self.handles.clear()


def _load_selected_direct(candidate: Path, runtime: Path):
    payload = torch.load(candidate, map_location="cpu", weights_only=False)
    if payload.get("arm") != "direct" or int(payload.get("step", -1)) != 0:
        raise ValueError("QAT requires the selected direct step-0 candidate")
    model, _ = load_joint_checkpoint(runtime)
    model.parent.load_state_dict(payload["parent_model"], strict=True)
    model.head.load_state_dict(payload["head"], strict=True)
    return model.cuda().eval(), payload


def _factor(step: int, steps: int) -> float:
    if step <= 200:
        return MIN_LR_FACTOR + (1.0 - MIN_LR_FACTOR) * step / 200.0
    progress = (step - 200) / max(steps - 200, 1)
    return MIN_LR_FACTOR + (1.0 - MIN_LR_FACTOR) * (0.5 * (1.0 + math.cos(math.pi * progress)))


def _load_schedule(path: Path, steps: int, view: ResidualView):
    payload = json.loads(path.read_text(encoding="utf-8"))
    metadata = payload["metadata"]
    if int(metadata["steps"]) != steps or int(metadata["window"]) != WINDOW or int(metadata["burn_in"]) != BURN_IN:
        raise ValueError("Serialized schedule does not match QAT settings")
    if metadata["source_labels"] != view.source_labels:
        raise ValueError("Serialized schedule source labels differ")
    if not metadata.get("same_schedule_for_direct_and_residual"):
        raise ValueError("Schedule was not declared paired")
    if len(payload["rows"]) != steps:
        raise ValueError("Serialized schedule length mismatch")
    return payload["rows"], metadata


def _checkpoint(path: Path, model, run, step, validation, history):
    payload = {
        "architecture": "semantic_fp8_qat_experiment_v1",
        "arm": run["arm"],
        "step": step,
        "head": model.head.state_dict(),
        "parent_model": model.parent.state_dict(),
        "run": run,
        "validation": validation,
        "history": history,
        "test_used": False,
    }
    temporary = path.with_suffix(path.suffix + ".tmp")
    torch.save(payload, temporary)
    temporary.replace(path)
    return _sha256_file(path)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--view", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--runtime-checkpoint", type=Path, required=True)
    parser.add_argument("--schedule", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--steps", type=int, default=1200, choices=(1000, 1200, 1600, 2000))
    parser.add_argument("--eval-every", type=int, default=400)
    parser.add_argument("--status-every", type=int, default=50)
    parser.add_argument("--seed", type=int, default=911)
    parser.add_argument(
        "--selection",
        choices=("broad", "selective"),
        default="broad",
        help="Activation scope; selective is the compliant causal QAT arm.",
    )
    parser.add_argument(
        "--autocast-dtype",
        choices=("bf16", "fp16"),
        default="bf16",
        help="Compute dtype used for the QAT gate comparison.",
    )
    args = parser.parse_args()
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is required")
    if args.steps % args.eval_every:
        raise ValueError("steps must be divisible by eval-every")
    output = args.output.resolve()
    if output.exists() and any(output.iterdir()):
        raise FileExistsError(output)
    output.mkdir(parents=True, exist_ok=True)
    view = ResidualView(args.view.resolve(), verify_hashes=False)
    schedule, schedule_meta = _load_schedule(args.schedule.resolve(), args.steps, view)
    model, candidate_payload = _load_selected_direct(args.candidate.resolve(), args.runtime_checkpoint.resolve())
    autocast_dtype = torch.bfloat16 if args.autocast_dtype == "bf16" else torch.float16
    qat = ClampE4M3QAT(args.selection)
    qat.attach(model)
    arm = "qat_clamp448" if args.selection == "broad" else "qat_clamp448_selective"
    run = {
        "schema": "opennr-fp8-qat-run-v1",
        "architecture": "semantic_fp8_qat_experiment_v1",
        "arm": arm,
        "selection": args.selection,
        "initial_candidate": str(args.candidate.resolve()),
        "initial_candidate_sha256": _sha256_file(args.candidate.resolve()),
        "initial_candidate_step": int(candidate_payload["step"]),
        "runtime_checkpoint": str(args.runtime_checkpoint.resolve()),
        "runtime_checkpoint_sha256": _sha256_file(args.runtime_checkpoint.resolve()),
        "view": str(view.root),
        "view_manifest_sha256": _sha256_file(view.root / "manifest.json"),
        "schedule_path": str(args.schedule.resolve()),
        "schedule_sha256": _sha256_file(args.schedule.resolve()),
        "schedule_digest_sha256": schedule_meta["digest_sha256"],
        "steps": args.steps,
        "window": WINDOW,
        "burn_in": BURN_IN,
        "autocast_dtype": args.autocast_dtype,
        "seed": args.seed,
        "optimizer": "AdamW",
        "head_learning_rate": HEAD_LR,
        "parent_learning_rate": PARENT_LR,
        "weight_decay": WEIGHT_DECAY,
        "learning_rate_schedule": {
            "type": "linear_warmup_then_cosine_decay",
            "warmup_steps": 200,
            "minimum_factor": MIN_LR_FACTOR,
        },
        "fake_quant": {
            "dtype": "torch.float8_e4m3fn",
            "pre_transform": "clamp(-448,448)",
            "dequant_dtype": "module output dtype",
            "backward": "straight-through identity",
            "insertion_points": (
                "parent/head expensive Conv2d and Linear outputs with explicit "
                "normalization/final/temporal/tiny exclusions"
                if args.selection == "selective"
                else "parent/head Conv2d and Linear outputs; head.encoder excluded"
            ),
            "module_count": len(qat.module_names),
            "selected_modules": qat.module_names,
            "candidate_decisions": qat.decisions,
        },
        "loss": "frame_objective(prediction-T, previous_error, pixel_only=True)",
        "test_used": False,
        "source_code_sha256": {
            name: _sha256_file(Path(__file__).with_name(name))
            for name in ("train_fp8_qat.py", "train_residual_target_pair.py")
        },
    }
    _write_json(output / "run.json", run)
    optimizer = torch.optim.AdamW(
        [
            {"params": [p for p in model.head.parameters() if p.requires_grad], "lr": HEAD_LR},
            {"params": [p for p in model.parent.parameters() if p.requires_grad], "lr": PARENT_LR},
        ],
        weight_decay=WEIGHT_DECAY,
    )
    history = []
    best_step = 0
    best_mae = float("inf")
    started = time.time()

    def evaluate_and_save(step: int):
        nonlocal best_step, best_mae
        _write_json(output / "status.json", {"state": "evaluating", "step": step, "steps": args.steps, "test_used": False})
        validation = evaluate_all(
            model, view, "validation", "direct", autocast_dtype=autocast_dtype
        )
        mae = float(validation["aggregate"]["mae"])
        if mae < best_mae:
            best_mae = mae
            best_step = step
        entry = {
            "step": step,
            "validation": validation,
            "learning_rate_factor": _factor(step, args.steps) if step else None,
            "best_step_so_far": best_step,
            "best_validation_mae_so_far": best_mae,
            "seconds": time.time() - started,
            "test_used": False,
        }
        history.append(entry)
        _write_json(output / "history.json", history)
        checkpoint = output / f"checkpoint_{step:04d}.pt"
        checkpoint_sha = _checkpoint(checkpoint, model, run, step, validation, history)
        _write_json(output / f"checkpoint_{step:04d}_identity.json", {"step": step, "sha256": checkpoint_sha, "path": str(checkpoint.resolve())})
        aggregate = validation["aggregate"]
        print(
            json.dumps(
                {
                    "step": step,
                    "mae": aggregate["mae"],
                    "psnr": aggregate["psnr"],
                    "temporal_delta_mae": aggregate["temporal_delta_mae"],
                    "temporal_warp_mae": aggregate["temporal_warp_mae"],
                    "stereo_disagreement_mae": aggregate["stereo_disagreement_mae"],
                    "best_step": best_step,
                    "seconds": time.time() - started,
                    "test_used": False,
                }
            ),
            flush=True,
        )

    try:
        evaluate_and_save(0)
        for item in schedule:
            step = int(item["step"])
            factor = _factor(step, args.steps)
            optimizer.param_groups[0]["lr"] = HEAD_LR * factor
            optimizer.param_groups[1]["lr"] = PARENT_LR * factor
            ids = np.asarray(item["ids"], dtype=np.int64)
            rgb_np, teacher_np, guides_np, context_np, _ = view.load_window(ids)
            rgb = torch.from_numpy(rgb_np).cuda(non_blocking=True).float() / 255.0
            teacher = torch.from_numpy(teacher_np).cuda(non_blocking=True).float() / 255.0
            guides = torch.from_numpy(guides_np).cuda(non_blocking=True).float()
            context = torch.from_numpy(context_np).cuda(non_blocking=True).float()
            model.train()
            optimizer.zero_grad(set_to_none=True)
            state = None
            previous_error = None
            losses = []
            for frame in range(WINDOW):
                with torch.autocast(device_type="cuda", dtype=autocast_dtype):
                    prediction, state = model.forward_temporal(
                        rgb[:, frame], guides[:, frame], context[:, frame], state
                    )
                    error = prediction.float() - teacher[:, frame]
                    if frame >= BURN_IN:
                        losses.append(frame_objective(error, previous_error, pixel_only=True))
                    previous_error = error if frame >= BURN_IN else error.detach()
            loss = torch.stack(losses).mean()
            if not torch.isfinite(loss):
                raise ValueError(f"Nonfinite QAT loss at step {step}")
            loss.backward()
            trainable = [parameter for parameter in model.parameters() if parameter.requires_grad and parameter.grad is not None]
            torch.nn.utils.clip_grad_norm_(trainable, 1.0, error_if_nonfinite=True)
            optimizer.step()
            if step == 1 or step % args.status_every == 0:
                _write_json(
                    output / "status.json",
                    {
                        "state": "training",
                        "step": step,
                        "steps": args.steps,
                        "loss": float(loss.detach().cpu()),
                        "learning_rate_factor": factor,
                        "gpu_peak_gib": torch.cuda.max_memory_allocated() / 2**30,
                        "test_used": False,
                    },
                )
                print(json.dumps({"step": step, "loss": float(loss.detach().cpu()), "learning_rate_factor": factor}), flush=True)
            del rgb, teacher, guides, context, prediction, error, loss, state, previous_error, losses
            torch.cuda.empty_cache()
            if step % args.eval_every == 0 or step == args.steps:
                evaluate_and_save(step)
        _write_json(
            output / "status.json",
            {
                "state": "complete",
                "steps": args.steps,
                "best_step": best_step,
                "best_validation_mae": best_mae,
                "gpu_peak_gib": torch.cuda.max_memory_allocated() / 2**30,
                "seconds": time.time() - started,
                "test_used": False,
            },
        )
    except Exception as exc:
        _write_json(output / "status.json", {"state": "failed", "error": repr(exc), "test_used": False})
        raise
    finally:
        qat.remove()
        del optimizer
        del model
        torch.cuda.empty_cache()


if __name__ == "__main__":
    main()
