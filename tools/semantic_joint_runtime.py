"""Inference-only loader for the verified seed-812 semantic joint checkpoint.

This module deliberately contains no optimizer, sampler, validation, or RNG
state.  The serialized bundle contains only the causal parent and semantic
head weights plus the architecture contract needed to reconstruct them.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import torch
from torch import nn
from torch.nn import functional as F

from capacity_student import CapacityConfig
from capacity_temporal_student import CapacityTemporalStyleContextStudent
from stable_oversized_tone_head import StableOversizedToneHead
from student_v2 import ReconstructionConfig
from temporal_student import TemporalConfig


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def tensor_digest(state: dict[str, torch.Tensor]) -> str:
    """Hash state tensors independently of torch.save/pickle serialization."""

    digest = hashlib.sha256()
    for name in sorted(state):
        value = state[name].detach().cpu().contiguous()
        digest.update(name.encode("utf-8"))
        digest.update(str(value.dtype).encode("ascii"))
        digest.update(json.dumps(list(value.shape), separators=(",", ":")).encode("ascii"))
        digest.update(value.view(torch.uint8).numpy().tobytes())
    return digest.hexdigest()


class RuntimeSemanticHead(StableOversizedToneHead):
    """The trained semantic head without training-time provenance machinery."""

    def __init__(self, encoder_source: Path):
        super().__init__()
        encoder_source = Path(encoder_source).resolve()
        if str(encoder_source) not in sys.path:
            sys.path.insert(0, str(encoder_source))
        from dinov2.hub.backbones import dinov2_vits14

        self.encoder = dinov2_vits14(pretrained=False)
        self.encoder.eval().requires_grad_(False)
        self.semantic_projection = nn.Conv2d(384, 64, 1)
        self.register_buffer(
            "encoder_mean", torch.tensor([0.485, 0.456, 0.406])[None, :, None, None]
        )
        self.register_buffer(
            "encoder_std", torch.tensor([0.229, 0.224, 0.225])[None, :, None, None]
        )

    def train(self, mode: bool = True):
        super().train(mode)
        self.encoder.eval()
        return self

    def forward(self, rgb, parent, guides, context):
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
        x = x + F.interpolate(self.semantic_projection(semantic), size=x.shape[-2:], mode="bilinear", align_corners=False)
        raw = F.interpolate(self.affine(x).float(), size=size, mode="bilinear", align_corners=False)
        n, _, h, w = parent.shape
        matrix = 0.25 * raw[:, :9].tanh().reshape(n, 3, 3, h, w)
        bias = 0.15 * raw[:, 9:].tanh()
        return (parent.float() + (matrix * parent.float()[:, None]).sum(2) + bias).clamp(0, 1)


class RuntimeJointModel(nn.Module):
    """Causal parent plus the exact trained semantic output head."""

    def __init__(self, parent: nn.Module, head: nn.Module):
        super().__init__()
        self.parent = parent.requires_grad_(False)
        self.head = head.requires_grad_(False)

    def forward_temporal(self, rgb, guides, context, state=None):
        base, next_state = self.parent.forward_temporal(rgb, guides, context, state)
        return self.head(rgb, base, guides, context), next_state


class OnnxTemporalWrapper(nn.Module):
    """Make the explicit recurrent state an ONNX input/output contract."""

    def __init__(self, model: RuntimeJointModel):
        super().__init__()
        self.model = model

    def forward(self, rgb, guides, context, hidden, previous):
        prediction, (next_hidden, next_previous) = self.model.forward_temporal(
            rgb, guides, context, (hidden, previous)
        )
        return prediction, next_hidden, next_previous


def _parent_from_bundle(bundle: dict, device: str | torch.device) -> nn.Module:
    config = bundle["parent_config"]
    parent = CapacityTemporalStyleContextStudent(
        ReconstructionConfig(**config["base_config"]),
        TemporalConfig(**config["temporal_config"]),
        CapacityConfig(**config["capacity_config"]),
    ).to(device)
    parent.load_state_dict(bundle["parent_state_dict"], strict=True)
    return parent


def load_bundle(bundle_path: Path, device: str | torch.device = "cpu") -> tuple[RuntimeJointModel, dict]:
    """Load a bundle and validate its two exact state-dict identities."""

    bundle_path = Path(bundle_path).resolve()
    bundle = torch.load(bundle_path, map_location="cpu", weights_only=False)
    if bundle.get("format") != "opennr-semantic-joint-inference-v1":
        raise ValueError("Unsupported semantic joint inference bundle")
    if bundle.get("parent_state_digest") != tensor_digest(bundle["parent_state_dict"]):
        raise ValueError("Parent tensor digest mismatch")
    if bundle.get("head_state_digest") != tensor_digest(bundle["head_state_dict"]):
        raise ValueError("Head tensor digest mismatch")

    parent = _parent_from_bundle(bundle, device)
    head = RuntimeSemanticHead(Path(bundle["encoder_source"])).to(device)
    head.load_state_dict(bundle["head_state_dict"], strict=True)
    model = RuntimeJointModel(parent, head).to(device).eval()
    return model, bundle


def state_shapes(height: int, width: int, downsample: int = 8) -> dict[str, tuple[int, ...]]:
    return {
        "rgb": (1, 3, height, width),
        "guides": (1, 5, (height + 3) // 4, (width + 3) // 4),
        "context": (1, 8, 96, 96),
        "hidden": (1, 64, (height + downsample - 1) // downsample, (width + downsample - 1) // downsample),
        "previous": (1, 3, height, width),
    }


def reset_state(model: RuntimeJointModel, rgb: torch.Tensor):
    """Return the exact state represented by ``state=None`` in the parent."""

    hidden, previous = model.parent.initial_state(rgb)
    return hidden, previous

