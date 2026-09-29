"""Measure BF16/FP16 versus fake E4M3 activation behavior on a frozen model.

The selected direct step-0 candidate is reconstructed from the exact recovered
protected clone.  Each mode runs the complete validation split of the residual
view.  Fake E4M3 is inserted at every parent/head Conv2d and Linear output;
the frozen DINO encoder is excluded because it is a feature extractor, not the
candidate's mutable OpenNR reconstruction path.

``e4m3_unsaturated`` deliberately does not clamp before conversion.  CUDA's
E4M3 conversion therefore exposes out-of-range behavior as it really is.  The
``e4m3_clamp448`` mode applies the requested symmetric clamp before the same
conversion.  This is instrumentation/evaluation only; no QAT or runtime file
is produced here.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
import json
from pathlib import Path
import time

import numpy as np
import torch
from torch import nn

from joint_parent_tone_model import load_joint_checkpoint
from train_residual_target_pair import (
    ResidualView,
    _aggregate,
    _sha256_file,
    evaluate_source,
)


FP8_DTYPE = torch.float8_e4m3fn


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


def _new_bucket() -> dict[str, float | int]:
    return {
        "calls": 0,
        "frames": 0,
        "elements": 0,
        "finite_pre": 0,
        "nonfinite_pre": 0,
        "above_448_pre": 0,
        "max_abs_pre": 0.0,
        "sum_abs_pre": 0.0,
        "sum_sq_pre": 0.0,
        "finite_post": 0,
        "nonfinite_post": 0,
        "max_abs_post": 0.0,
        "sum_abs_post": 0.0,
        "quantization_abs_error_sum": 0.0,
        "quantization_abs_error_max": 0.0,
        "quantized_at_fp8_max": 0,
    }


class ActivationInstrumentation:
    def __init__(self, mode: str):
        self.mode = mode
        self.active_groups = ["all"]
        self.frame_counts = defaultdict(int)
        self.buckets: dict[str, dict[str, dict[str, float | int]]] = defaultdict(dict)
        self.handles = []
        self.module_names: list[str] = []

    def attach(self, model) -> None:
        for root_name, root in (("parent", model.parent), ("head", model.head)):
            for relative, module in root.named_modules():
                if not relative:
                    continue
                full_name = f"{root_name}.{relative}"
                if full_name.startswith("head.encoder."):
                    continue
                if not isinstance(module, (nn.Conv2d, nn.Linear)):
                    continue
                self.module_names.append(full_name)
                self.handles.append(
                    module.register_forward_hook(self._make_hook(full_name))
                )

    def remove(self) -> None:
        for handle in self.handles:
            handle.remove()
        self.handles.clear()

    def begin_frame(self, target: torch.Tensor, residual: torch.Tensor, tail_threshold: float) -> None:
        luma = 0.2126 * target[:, 0] + 0.7152 * target[:, 1] + 0.0722 * target[:, 2]
        groups = ["all"]
        if bool((luma >= 0.8).any().item()):
            groups.append("bright_luma_ge_0.8")
        if bool((target.max(dim=1).values >= (254.5 / 255.0)).any().item()):
            groups.append("clipped_rgb_channel")
        if bool((residual.abs().max(dim=1).values >= tail_threshold).any().item()):
            groups.append("large_residual_abs_ge_global_p99")
        self.active_groups = groups
        for group in groups:
            self.frame_counts[group] += 1

    def _bucket(self, module_name: str, group: str):
        if group not in self.buckets[module_name]:
            self.buckets[module_name][group] = _new_bucket()
        return self.buckets[module_name][group]

    def _make_hook(self, module_name: str):
        def hook(_module, _inputs, output):
            if not torch.is_tensor(output):
                return output
            pre = output.detach().float()
            finite_pre = torch.isfinite(pre)
            finite_values = pre[finite_pre]
            if self.mode == "e4m3_unsaturated":
                quantized = pre.to(FP8_DTYPE).to(output.dtype)
            elif self.mode == "e4m3_clamp448":
                quantized = pre.clamp(-448.0, 448.0).to(FP8_DTYPE).to(output.dtype)
            else:
                quantized = output
            post = quantized.detach().float()
            finite_post = torch.isfinite(post)
            for group in self.active_groups:
                bucket = self._bucket(module_name, group)
                bucket["calls"] += 1
                bucket["frames"] = self.frame_counts[group]
                bucket["elements"] += int(pre.numel())
                bucket["finite_pre"] += int(finite_pre.sum().item())
                bucket["nonfinite_pre"] += int((~finite_pre).sum().item())
                bucket["above_448_pre"] += int((finite_pre & (pre.abs() > 448.0)).sum().item())
                if finite_values.numel():
                    bucket["max_abs_pre"] = max(bucket["max_abs_pre"], float(finite_values.abs().max().item()))
                    bucket["sum_abs_pre"] += float(finite_values.abs().sum().item())
                    bucket["sum_sq_pre"] += float(finite_values.square().sum().item())
                bucket["finite_post"] += int(finite_post.sum().item())
                bucket["nonfinite_post"] += int((~finite_post).sum().item())
                finite_post_values = post[finite_post]
                if finite_post_values.numel():
                    bucket["max_abs_post"] = max(bucket["max_abs_post"], float(finite_post_values.abs().max().item()))
                    bucket["sum_abs_post"] += float(finite_post_values.abs().sum().item())
                    bucket["quantized_at_fp8_max"] += int(
                        (finite_post_values.abs() >= 448.0).sum().item()
                    )
                both = finite_pre & finite_post
                if both.any():
                    difference = (post[both] - pre[both]).abs()
                    bucket["quantization_abs_error_sum"] += float(difference.sum().item())
                    bucket["quantization_abs_error_max"] = max(
                        bucket["quantization_abs_error_max"], float(difference.max().item())
                    )
            return quantized

        return hook

    def as_json(self) -> dict:
        modules = {}
        for module_name in sorted(self.buckets):
            modules[module_name] = {}
            for group, raw in sorted(self.buckets[module_name].items()):
                bucket = dict(raw)
                elements = max(1, int(bucket["elements"]))
                finite_pre = max(1, int(bucket["finite_pre"]))
                bucket.update(
                    {
                        "finite_pre_fraction": bucket["finite_pre"] / elements,
                        "nonfinite_pre_fraction": bucket["nonfinite_pre"] / elements,
                        "above_448_pre_fraction": bucket["above_448_pre"] / elements,
                        "finite_post_fraction": bucket["finite_post"] / elements,
                        "nonfinite_post_fraction": bucket["nonfinite_post"] / elements,
                        "mean_abs_pre_finite": bucket["sum_abs_pre"] / finite_pre,
                        "rms_pre_finite": (bucket["sum_sq_pre"] / finite_pre) ** 0.5,
                        "mean_abs_post_finite": bucket["sum_abs_post"] / max(1, int(bucket["finite_post"])),
                        "mean_quantization_abs_error_finite": bucket["quantization_abs_error_sum"] / max(1, int(bucket["finite_pre"])),
                    }
                )
                modules[module_name][group] = bucket
        return {
            "mode": self.mode,
            "module_count": len(self.module_names),
            "modules": modules,
            "frame_counts": dict(self.frame_counts),
            "insertion_points": "parent/head Conv2d and Linear outputs; head.encoder excluded",
        }


def _load_direct_candidate(candidate: Path, runtime_checkpoint: Path):
    payload = torch.load(candidate, map_location="cpu", weights_only=False)
    if payload.get("arm") != "direct" or int(payload.get("step", -1)) != 0:
        raise ValueError("Precision study requires the selected direct step-0 candidate")
    model, _ = load_joint_checkpoint(runtime_checkpoint)
    model.parent.load_state_dict(payload["parent_model"], strict=True)
    model.head.load_state_dict(payload["head"], strict=True)
    return model.eval(), payload


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--view", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--runtime-checkpoint", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--skip-view-hash", action="store_true")
    args = parser.parse_args()
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is required")
    output = args.output.resolve()
    if output.exists() and any(output.iterdir()):
        raise FileExistsError(output)
    output.mkdir(parents=True, exist_ok=True)
    view = ResidualView(args.view.resolve(), verify_hashes=not args.skip_view_hash)
    candidate = args.candidate.resolve()
    runtime = args.runtime_checkpoint.resolve()
    identity = {
        "candidate": str(candidate),
        "candidate_sha256": _sha256_file(candidate),
        "runtime_checkpoint": str(runtime),
        "runtime_checkpoint_sha256": _sha256_file(runtime),
        "view_manifest": str(view.root / "manifest.json"),
        "view_manifest_sha256": _sha256_file(view.root / "manifest.json"),
        "test_used": False,
    }
    modes = [
        ("bf16", torch.bfloat16, "native autocast BF16; no fake quantization"),
        ("fp16", torch.float16, "native autocast FP16; no fake quantization"),
        ("e4m3_unsaturated", torch.bfloat16, "BF16 compute with fake E4M3 activation dequantization and no pre-clamp"),
        ("e4m3_clamp448", torch.bfloat16, "BF16 compute with clamp(-448,448) then fake E4M3 activation dequantization"),
    ]
    result = {
        "schema": "opennr-fp8-activation-instrumentation-v1",
        "identity": identity,
        "target": "selected direct step-0 checkpoint; validation split only",
        "modes": {},
        "difficult_case_contract": {
            "bright": "measured heuristic: any frame eye has teacher luma >= 0.8",
            "hdr_like": "measured heuristic: any teacher channel >= 254.5/255; not an HDR claim",
            "large_residual": "measured diagnostic: any frame eye has |R| max >= global residual p99",
            "fire": "unavailable; no validated fire-category labels in selected sources",
            "face": "unavailable; no validated face-mask manifest in selected sources",
            "activation_grouping": "if any pixel in either eye of a frame meets a heuristic, the full module activation for that frame is counted in that group",
        },
        "test_used": False,
        "created_epoch": time.time(),
    }
    _write_json(output / "identity.json", result["identity"])
    for mode, autocast_dtype, description in modes:
        print(f"starting mode {mode}", flush=True)
        instrumentation = ActivationInstrumentation(mode)
        model = None
        mode_result = {
            "mode": mode,
            "description": description,
            "autocast_dtype": str(autocast_dtype),
            "test_used": False,
            "status": "starting",
        }
        try:
            model, payload = _load_direct_candidate(candidate, runtime)
            instrumentation.attach(model)
            per_source = {}
            for source in view.sources:
                print(f"validation {mode}/{source.label}", flush=True)
                per_source[source.label] = evaluate_source(
                    model,
                    source.validation,
                    view.residual,
                    view.tail_threshold,
                    "direct",
                    autocast_dtype=autocast_dtype,
                    instrumentation=instrumentation,
                )
            mode_result.update(
                {
                    "status": "complete",
                    "sources": per_source,
                    "aggregate": _aggregate(per_source),
                }
            )
        except Exception as exc:
            mode_result.update(
                {
                    "status": "failed_nonfinite_or_runtime",
                    "error": repr(exc),
                    "sources_completed": list(mode_result.get("sources", {})),
                }
            )
            print(json.dumps({"mode": mode, "status": mode_result["status"], "error": repr(exc)}), flush=True)
        finally:
            instrumentation.remove()
            mode_result["activation_instrumentation"] = instrumentation.as_json()
            if model is not None:
                del model
            torch.cuda.empty_cache()
        result["modes"][mode] = mode_result
        _write_json(output / "progress.json", result)
        print(
            json.dumps(
                {
                    "mode": mode,
                    "status": mode_result["status"],
                    "aggregate_mae": mode_result.get("aggregate", {}).get("mae"),
                    "aggregate_psnr": mode_result.get("aggregate", {}).get("psnr"),
                    "nonfinite_module_events": sum(
                        bucket.get("nonfinite_post", 0)
                        for groups in mode_result["activation_instrumentation"]["modules"].values()
                        for bucket in groups.values()
                    ),
                }
            ),
            flush=True,
        )
    _write_json(output / "results.json", result)
    _write_json(
        output / "status.json",
        {
            "state": "complete",
            "modes": {name: value["status"] for name, value in result["modes"].items()},
            "test_used": False,
        },
    )
    print(json.dumps({"state": "complete", "modes": list(result["modes"]), "test_used": False}), flush=True)


if __name__ == "__main__":
    main()
