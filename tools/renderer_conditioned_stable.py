"""Renderer-context-conditioned stable U-Net experiment.

This module deliberately keeps the existing 19-channel tone-head path intact
and adds the 17 verified renderer channels as a zero-initialized input branch.
At step zero the new model is therefore the same function as the warm-start
model; only the new renderer evidence can move it away from that baseline.
"""

from collections import defaultdict
import math
from pathlib import Path

import numpy as np
import torch
from torch import nn
from torch.nn import functional as F

from aligned_cohort import AlignedCohort
from prepare_conditioning_pilot import sha
from stable_oversized_tone_head import StableOversizedToneHead
from train_capacity_temporal_student import _load_parent


RENDERER_CHANNELS = 17
BASE_HEAD_INPUT_CHANNELS = 19
RENDERER_SCHEMA = "opennr-aligned-renderer-pilot-v1"


class RendererConditionedStableOversizedToneHead(StableOversizedToneHead):
    """Stable U-Net with a zero-initialized renderer-context input branch."""

    def __init__(self, renderer_channels: int = RENDERER_CHANNELS):
        super().__init__()
        if renderer_channels <= 0:
            raise ValueError("renderer_channels must be positive")
        original = self.stem[0]
        if not isinstance(original, nn.Conv2d):
            raise ValueError("Stable U-Net stem layout changed")
        if original.in_channels != BASE_HEAD_INPUT_CHANNELS:
            raise ValueError("Unexpected stable U-Net input width")
        replacement = nn.Conv2d(
            BASE_HEAD_INPUT_CHANNELS + renderer_channels,
            original.out_channels,
            original.kernel_size,
            stride=original.stride,
            padding=original.padding,
            dilation=original.dilation,
            groups=original.groups,
            bias=original.bias is not None,
            padding_mode=original.padding_mode,
            device=original.weight.device,
            dtype=original.weight.dtype,
        )
        with torch.no_grad():
            replacement.weight[:, :BASE_HEAD_INPUT_CHANNELS].copy_(original.weight)
            replacement.weight[:, BASE_HEAD_INPUT_CHANNELS:].zero_()
            if original.bias is not None:
                replacement.bias.copy_(original.bias)
        self.stem[0] = replacement
        self.renderer_channels = renderer_channels

    def forward(self, rgb, parent, guides, context, conditioning):
        if conditioning.shape[1] != self.renderer_channels:
            raise ValueError(
                f"Expected {self.renderer_channels} renderer channels, "
                f"received {conditioning.shape[1]}"
            )
        size = parent.shape[-2:]
        x = torch.cat(
            (
                rgb,
                parent,
                F.interpolate(guides, size=size, mode="bilinear", align_corners=False),
                F.interpolate(context, size=size, mode="bilinear", align_corners=False),
                F.interpolate(
                    conditioning, size=size, mode="bilinear", align_corners=False
                ),
            ),
            1,
        )
        levels = [self.stem(x)]
        for layer in self.down:
            levels.append(layer(levels[-1]))
        x = self.bottleneck(levels[-1])
        for layer, skip in zip(self.up, reversed(levels[2:-1])):
            x = layer(
                torch.cat(
                    (F.interpolate(x, size=skip.shape[-2:], mode="bilinear", align_corners=False), skip),
                    1,
                )
            )
        raw = F.interpolate(self.affine(x).float(), size=size, mode="bilinear", align_corners=False)
        n, _, h, w = parent.shape
        matrix = 0.25 * raw[:, :9].tanh().reshape(n, 3, 3, h, w)
        bias = 0.15 * raw[:, 9:].tanh()
        return (parent.float() + (matrix * parent.float()[:, None]).sum(2) + bias).clamp(0, 1)


class RendererConditionedToneModel(nn.Module):
    """Frozen causal parent plus the renderer-conditioned refinement head."""

    def __init__(self, parent, head):
        super().__init__()
        self.parent = parent.eval().requires_grad_(False)
        self.head = head

    def train(self, mode=True):
        super().train(mode)
        self.parent.eval()
        return self

    def forward_temporal(self, rgb, guides, context, conditioning, state=None):
        with torch.no_grad():
            base, next_state = self.parent.forward_temporal(rgb, guides, context, state)
        return self.head(rgb, base, guides, context, conditioning), next_state


class RendererFeatureAlignedCohort(AlignedCohort):
    """Aligned cohort that exposes verified renderer conditioning when present."""

    def __init__(self, root, split, expected_pass_count=1):
        super().__init__(root, split, expected_pass_count=expected_pass_count)
        self.renderer_conditioning = None
        if self.complete.get("schema") == RENDERER_SCHEMA:
            path = self.root / "conditioning.npy"
            self.renderer_conditioning = np.load(path, mmap_mode="r")
            if self.renderer_conditioning.ndim != 4:
                raise ValueError("Renderer conditioning must be NCHW")
            if self.renderer_conditioning.shape[0] != len(self.rows):
                raise ValueError("Renderer conditioning rows do not match manifest")
            if self.renderer_conditioning.shape[1] != RENDERER_CHANNELS:
                raise ValueError("Unexpected renderer conditioning channel count")
            if not np.isfinite(self.renderer_conditioning[:1]).all():
                raise ValueError("Renderer conditioning contains non-finite values")
        self.conditioning_channels = RENDERER_CHANNELS

    def load_window(self, indices):
        rgb, target, guides, context = super().load_window(indices)
        if self.renderer_conditioning is None:
            conditioning = np.zeros(
                (*indices.shape, RENDERER_CHANNELS, *guides.shape[-2:]), dtype=np.float32
            )
        else:
            conditioning = np.array(self.renderer_conditioning[indices], copy=True)
        return rgb, target, guides, context, conditioning


@torch.no_grad()
def evaluate_renderer_streaming(model, cache, device="cuda", batch=4):
    """Evaluate complete reset-qualified streams without frozen-test access."""

    model.eval()
    total_abs = total_sq = identity_abs = identity_sq = 0.0
    delta_abs = identity_delta_abs = 0.0
    pixels = delta_pixels = 0
    by_sequence = defaultdict(list)
    by_eye = defaultdict(list)
    warm_abs = warm_pixels = steady_abs = steady_pixels = 0.0
    for selected, arrays in cache.stream_batches(batch):
        rgb_np, target_np, guides_np, context_np, conditioning_np = arrays
        tensors = tuple(
            torch.from_numpy(value).to(device, non_blocking=True)
            for value in (rgb_np, target_np, guides_np, context_np, conditioning_np)
        )
        rgb_all, target_all, guides_all, context_all, conditioning_all = tensors
        rgb_all = rgb_all.float() / 255.0
        target_all = target_all.float() / 255.0
        guides_all = guides_all.float()
        context_all = context_all.float()
        conditioning_all = conditioning_all.float()
        state = None
        previous_pred = previous_target = previous_rgb = None
        stream_values = [[] for _ in selected]
        for frame in range(rgb_all.shape[1]):
            with torch.autocast(device_type=device, dtype=torch.bfloat16):
                pred, state = model.forward_temporal(
                    rgb_all[:, frame],
                    guides_all[:, frame],
                    context_all[:, frame],
                    conditioning_all[:, frame],
                    state,
                )
            pred = pred.float()
            target = target_all[:, frame]
            rgb = rgb_all[:, frame]
            error = pred - target
            baseline = rgb - target
            values = error.abs().mean((1, 2, 3)).cpu().tolist()
            for index, value in enumerate(values):
                stream_values[index].append(float(value))
            total_abs += error.abs().sum().item()
            total_sq += error.square().sum().item()
            identity_abs += baseline.abs().sum().item()
            identity_sq += baseline.square().sum().item()
            pixels += target.numel()
            if frame == 0:
                warm_abs += error.abs().sum().item()
                warm_pixels += target.numel()
            else:
                steady_abs += error.abs().sum().item()
                steady_pixels += target.numel()
                pred_delta = pred - previous_pred
                target_delta = target - previous_target
                baseline_delta = rgb - previous_rgb
                delta_abs += (pred_delta - target_delta).abs().sum().item()
                identity_delta_abs += (baseline_delta - target_delta).abs().sum().item()
                delta_pixels += target.numel()
            previous_pred = pred
            previous_target = target
            previous_rgb = rgb
        for key, values in zip(selected, stream_values):
            by_sequence[key[0]].extend(values)
            by_eye[str(key[1])].extend(values)
        del tensors, state
    return {
        "split": cache.split,
        "sequence_count": len(cache.sequence_ids),
        "eye_streams": len(cache.streams),
        "frames": pixels // (3 * 512 * 512),
        "mae": total_abs / pixels,
        "psnr": -10.0 * math.log10(max(total_sq / pixels, 1e-12)),
        "identity_mae": identity_abs / pixels,
        "identity_psnr": -10.0 * math.log10(max(identity_sq / pixels, 1e-12)),
        "improvement_pct": 100.0 * (identity_abs - total_abs) / identity_abs,
        "temporal_delta_mae": delta_abs / max(1, delta_pixels),
        "identity_temporal_delta_mae": identity_delta_abs / max(1, delta_pixels),
        "first_frame_mae": warm_abs / max(1, warm_pixels),
        "steady_frame_mae": steady_abs / max(1, steady_pixels),
        "sequence_mae": {key: float(np.mean(values)) for key, values in by_sequence.items()},
        "eye_mae": {key: float(np.mean(values)) for key, values in by_eye.items()},
        "pixels": pixels,
    }


def load_renderer_checkpoint(path: Path, device="cuda"):
    """Reload a renderer-conditioned checkpoint with all provenance checks."""

    payload = torch.load(path, map_location="cpu", weights_only=False)
    run = payload["run"]
    if run.get("architecture") not in (
        "stable_unet_renderer_conditioned",
        "stable_unet_chroma_luma",
    ):
        raise ValueError("Checkpoint is not a supported stable U-Net research arm")
    parent_path = Path(run["parent"])
    if sha(parent_path) != run["parent_sha256"]:
        raise ValueError("Parent mismatch")
    source = Path(__file__)
    if sha(source) != run["renderer_conditioned_source_sha256"]:
        raise ValueError("Renderer-conditioned implementation changed")
    for field, filename in (
        ("oversized_source_sha256", "oversized_tone_head.py"),
        ("stable_source_sha256", "stable_oversized_tone_head.py"),
        ("teacher_mode_source_sha256", "teacher_mode_head.py"),
    ):
        if sha(source.with_name(filename)) != run[field]:
            raise ValueError(f"{filename} changed")
    parent, *_ = _load_parent(parent_path, device=device)
    if run["architecture"] == "stable_unet_chroma_luma":
        from luma_tone_head import ChromaPreservingLumaToneHead

        if sha(source.with_name("luma_tone_head.py")) != run["luma_head_source_sha256"]:
            raise ValueError("Luma head implementation changed")
        head = ChromaPreservingLumaToneHead().to(device)
    else:
        head = RendererConditionedStableOversizedToneHead().to(device)
    from teacher_mode_head import enable_teacher_mode

    enable_teacher_mode(head)
    head.load_state_dict(payload["head"], strict=True)
    if hasattr(head, "exact_zero_bypass"):
        # best_all_cohorts.pt is the exact step-zero warm replay; trained
        # checkpoints must expose the learned luma branch when reloaded.
        head.exact_zero_bypass = int(payload.get("step", 0)) == 0
    return RendererConditionedToneModel(parent, head).eval(), payload
