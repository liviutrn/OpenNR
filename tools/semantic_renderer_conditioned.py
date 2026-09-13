"""Semantic joint-parent model with a zero-initialized native G-buffer branch.

This module is intentionally separate from the existing semantic head and
joint checkpoint loader.  Existing checkpoints remain loadable and unchanged;
the new head copies their 19-channel stem exactly and appends 17 zero-weight
renderer channels.  A strict renderer overlay supplies those channels only
for the new full-eye pilot cohort.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import torch
from torch import nn
from torch.nn import functional as F

from joint_parent_tone_model import JointParentToneModel, load_joint_checkpoint
from semantic_tone_head import SemanticToneHead
from train_temporal_student import StrictTemporalCache


RENDERER_CHANNELS = 17
BASE_INPUT_CHANNELS = 19
OVERLAY_SCHEMA = "opennr-full-eye-renderer-conditioning-v1"


class SemanticRendererConditionedToneHead(SemanticToneHead):
    """Semantic tone head whose extra input branch is exactly zero at init."""

    def __init__(self, pretrained: bool = False, renderer_channels: int = RENDERER_CHANNELS):
        super().__init__(pretrained=pretrained)
        if renderer_channels <= 0:
            raise ValueError("renderer_channels must be positive")
        original = self.stem[0]
        if not isinstance(original, nn.Conv2d) or original.in_channels != BASE_INPUT_CHANNELS:
            raise ValueError("Semantic stem layout changed")
        replacement = nn.Conv2d(
            BASE_INPUT_CHANNELS + renderer_channels,
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
            replacement.weight[:, :BASE_INPUT_CHANNELS].copy_(original.weight)
            replacement.weight[:, BASE_INPUT_CHANNELS:].zero_()
            if original.bias is not None:
                replacement.bias.copy_(original.bias)
        self.stem[0] = replacement
        self.renderer_channels = int(renderer_channels)

    def load_base_state_dict(self, state_dict: dict[str, torch.Tensor]) -> None:
        """Load an old semantic head while expanding only the first stem weight."""

        expanded = dict(state_dict)
        old_weight = expanded.get("stem.0.weight")
        if old_weight is None or old_weight.ndim != 4 or old_weight.shape[1] != BASE_INPUT_CHANNELS:
            raise ValueError("Base semantic checkpoint has an unexpected stem")
        new_weight = self.stem[0].weight.detach().clone()
        new_weight[:, :BASE_INPUT_CHANNELS].copy_(old_weight)
        new_weight[:, BASE_INPUT_CHANNELS:].zero_()
        expanded["stem.0.weight"] = new_weight
        result = self.load_state_dict(expanded, strict=True)
        if result.missing_keys or result.unexpected_keys:
            raise ValueError(f"Expanded semantic head state mismatch: {result}")

    def forward(self, rgb, parent, guides, context, conditioning):
        if conditioning.ndim != 4 or conditioning.shape[1] != self.renderer_channels:
            raise ValueError(
                f"Expected NCHW conditioning with {self.renderer_channels} channels, "
                f"received {tuple(conditioning.shape)}"
            )
        with torch.no_grad():
            image = (
                F.interpolate(rgb.float(), size=(224, 224), mode="bilinear", align_corners=False)
                - self.encoder_mean
            ) / self.encoder_std
            semantic = self.encoder.get_intermediate_layers(image, n=1, reshape=True)[0]
        size = parent.shape[-2:]
        x = torch.cat(
            (
                rgb,
                parent,
                F.interpolate(guides, size=size, mode="bilinear", align_corners=False),
                F.interpolate(context, size=size, mode="bilinear", align_corners=False),
                F.interpolate(conditioning, size=size, mode="bilinear", align_corners=False),
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
                    (
                        F.interpolate(x, size=skip.shape[-2:], mode="bilinear", align_corners=False),
                        skip,
                    ),
                    1,
                )
            )
        x = x + F.interpolate(self.semantic_projection(semantic), size=x.shape[-2:], mode="bilinear", align_corners=False)
        raw = F.interpolate(self.affine(x).float(), size=size, mode="bilinear", align_corners=False)
        n, _, h, w = parent.shape
        matrix = 0.25 * raw[:, :9].tanh().reshape(n, 3, 3, h, w)
        bias = 0.15 * raw[:, 9:].tanh()
        return (parent.float() + (matrix * parent.float()[:, None]).sum(2) + bias).clamp(0, 1)


class SemanticRendererConditionedJointModel(JointParentToneModel):
    """The ordinary joint-parent contract extended with renderer inputs."""

    def forward_temporal(self, rgb, guides, context, conditioning, state=None):
        base, next_state = self.parent.forward_temporal(rgb, guides, context, state)
        return self.head(rgb, base, guides, context, conditioning), next_state


def load_semantic_renderer_checkpoint(path: Path):
    """Load a verified semantic joint checkpoint with the expanded zero branch."""

    base_model, payload = load_joint_checkpoint(path)
    head = SemanticRendererConditionedToneHead(pretrained=False).cuda()
    head.load_base_state_dict(base_model.head.state_dict())
    model = SemanticRendererConditionedJointModel(base_model.parent, head).eval()
    del base_model
    return model, payload


def load_trained_semantic_renderer_checkpoint(path: Path):
    """Reload a renderer-conditioned experiment checkpoint with base checks."""

    path = Path(path).resolve()
    payload = torch.load(path, map_location="cpu", weights_only=False)
    if payload.get("architecture") != "semantic_renderer_conditioned_joint_v1":
        raise ValueError("Expected a semantic renderer-conditioned checkpoint")
    run = payload["run"]
    base_path = Path(run["base_checkpoint"]).resolve()
    if sha256_file(base_path) != run["base_checkpoint_sha256"]:
        raise ValueError("Base checkpoint changed")
    model, _ = load_semantic_renderer_checkpoint(base_path)
    model.head.load_state_dict(payload["head"], strict=True)
    model.parent.load_state_dict(payload["parent_model"], strict=True)
    return model.eval(), payload


def _stable_sha(value) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


class RendererConditioningOverlay:
    """Strict temporal source cache plus a hash-bound renderer overlay."""

    def __init__(self, root: Path, split: str):
        if split not in ("train", "validation"):
            raise ValueError("Renderer overlay consumers may not access test rows")
        self.root = Path(root).resolve()
        self.complete = json.loads((self.root / "complete.json").read_text(encoding="utf-8"))
        if self.complete.get("schema") != OVERLAY_SCHEMA:
            raise ValueError("Unexpected renderer overlay schema")
        source = Path(self.complete["source_cache"]).resolve()
        if hashlib.sha256((source / "complete.json").read_bytes()).hexdigest() != self.complete["source_complete_sha256"]:
            raise ValueError("Source temporal cache changed")
        source_rows = json.loads((source / "rows.json").read_text(encoding="utf-8"))
        if _stable_sha(source_rows) != self.complete["source_rows_sha256"]:
            raise ValueError("Source temporal rows changed")
        overlay_rows = json.loads((self.root / "rows.json").read_text(encoding="utf-8"))
        if overlay_rows != source_rows:
            raise ValueError("Renderer overlay row order does not match source cache")
        if hashlib.sha256((self.root / "rows.json").read_bytes()).hexdigest() != self.complete["rows_sha256"]:
            raise ValueError("Renderer overlay row manifest changed")
        self.base = StrictTemporalCache(source, split)
        self.conditioning = np.load(self.root / "conditioning.npy", mmap_mode="r")
        if tuple(self.conditioning.shape) != tuple(self.complete["shape"]):
            raise ValueError("Renderer conditioning shape changed")
        if self.conditioning.shape[0] != len(source_rows) or self.conditioning.shape[1] != RENDERER_CHANNELS:
            raise ValueError("Renderer conditioning rows/channels do not match source")
        digest = hashlib.sha256((self.root / "conditioning.npy").read_bytes()).hexdigest()
        if digest != self.complete["array_sha256"]["conditioning"]:
            raise ValueError("Renderer conditioning payload changed")
        if not np.isfinite(self.conditioning[:1]).all() or not np.isfinite(self.conditioning[-1:]).all():
            raise ValueError("Renderer conditioning contains nonfinite values")
        self.split = split
        self.rows = self.base.rows
        self.streams = self.base.streams

    @property
    def sequence_ids(self):
        return self.base.sequence_ids

    @property
    def rows_sha256(self):
        return self.complete["source_rows_sha256"]

    def sample_window(self, rng, batch: int, window: int):
        return self.base.sample_window(rng, batch, window)

    def load_window(self, indices):
        rgb, target, guides, context = self.base.load_window(indices)
        conditioning = np.array(self.conditioning[indices], copy=True)
        return rgb, target, guides, context, conditioning

    def stream_batches(self, batch: int):
        keys = list(self.streams)
        for offset in range(0, len(keys), batch):
            selected = keys[offset : offset + batch]
            indices = np.stack([self.streams[key] for key in selected])
            yield selected, self.load_window(indices)


class RendererZeroCohort:
    """Expose an ordinary cohort through the five-input renderer contract."""

    def __init__(self, base):
        self.base = base
        self.split = base.split
        self.complete = base.complete
        self.rows = base.rows
        self.streams = base.streams

    @property
    def sequence_ids(self):
        return self.base.sequence_ids

    @property
    def rows_sha256(self):
        return getattr(self.base, "rows_sha256", None)

    def sample_window(self, rng, batch: int, window: int):
        return self.base.sample_window(rng, batch, window)

    def load_window(self, indices):
        rgb, target, guides, context = self.base.load_window(indices)
        conditioning = np.zeros(
            (*indices.shape, RENDERER_CHANNELS, *guides.shape[-2:]), dtype=np.float32
        )
        return rgb, target, guides, context, conditioning

    def stream_batches(self, batch: int):
        keys = list(self.streams)
        for offset in range(0, len(keys), batch):
            selected = keys[offset : offset + batch]
            indices = np.stack([self.streams[key] for key in selected])
            yield selected, self.load_window(indices)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()
