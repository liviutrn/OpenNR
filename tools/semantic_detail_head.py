"""Zero-initialized native-resolution detail refinement for the semantic student."""

from __future__ import annotations

import torch
from torch import nn
from torch.nn import functional as F


class SemanticDetailHead(nn.Module):
    """Add a small current-frame residual without changing the causal state.

    The inherited semantic head remains frozen in this ablation.  The last
    convolution is zero-initialized, so the child is exactly the inherited
    semantic output before optimization.  The branch is intentionally native
    resolution and current-frame-only: it tests high-frequency capacity while
    leaving the parent's recurrent feedback contract unchanged.
    """

    def __init__(self, base_head: nn.Module, width: int = 32, scale: float = 0.08) -> None:
        super().__init__()
        if width < 8:
            raise ValueError("detail width is too small")
        if not 0.0 < scale <= 1.0:
            raise ValueError("detail scale must be in (0, 1]")
        self.base_head = base_head.eval().requires_grad_(False)
        self.width = int(width)
        self.scale = float(scale)
        self.detail = nn.Sequential(
            nn.Conv2d(19, self.width, 3, padding=1),
            nn.SiLU(),
            nn.Conv2d(self.width, self.width, 3, padding=1),
            nn.SiLU(),
            nn.Conv2d(self.width, 3, 3, padding=1),
        )
        nn.init.zeros_(self.detail[-1].weight)
        nn.init.zeros_(self.detail[-1].bias)

    def train(self, mode: bool = True):
        super().train(mode)
        self.base_head.eval()
        return self

    def forward(self, rgb, parent, guides, context):
        with torch.no_grad():
            inherited = self.base_head(rgb, parent, guides, context)
        size = rgb.shape[-2:]
        features = torch.cat(
            (
                rgb,
                inherited,
                F.interpolate(guides, size=size, mode="bilinear", align_corners=False),
                F.interpolate(context, size=size, mode="bilinear", align_corners=False),
            ),
            dim=1,
        )
        residual = self.detail(features).float()
        return (inherited + self.scale * torch.tanh(residual)).clamp(0.0, 1.0)


class SemanticDetailOnlyModel(nn.Module):
    """Frozen causal parent plus frozen semantic head and trainable detail."""

    def __init__(self, parent: nn.Module, base_head: nn.Module, width: int = 32, scale: float = 0.08) -> None:
        super().__init__()
        self.parent = parent.eval().requires_grad_(False)
        self.detail_head = SemanticDetailHead(base_head, width=width, scale=scale)

    def train(self, mode: bool = True):
        super().train(mode)
        self.parent.eval()
        self.detail_head.base_head.eval()
        return self

    def forward_temporal(self, rgb, guides, context, state=None):
        with torch.no_grad():
            base, next_state = self.parent.forward_temporal(rgb, guides, context, state)
        return self.detail_head(rgb, base, guides, context), next_state
