"""Small hybrid CNN/window-attention students for OpenNR-GEN static distillation.

The attention core always operates after three stride-2 reductions, so a
512x512 sample becomes a 64x64 feature map before tokenization.  Attention is
windowed; no full-resolution global attention is used.
"""

from __future__ import annotations

from dataclasses import dataclass

import torch
from torch import nn
from torch.nn import functional as F


@dataclass(frozen=True)
class CapacitySpec:
    name: str
    channels: int
    blocks: int
    feedforward_multiplier: int
    heads: int


CAPACITIES = {
    # Counts are approximately 0.25M, 1M, and 4M trainable parameters,
    # including the identity-safe residual scale.
    "0.25m": CapacitySpec("0.25m", channels=40, blocks=2, feedforward_multiplier=4, heads=4),
    "1m": CapacitySpec("1m", channels=80, blocks=3, feedforward_multiplier=4, heads=4),
    "4m": CapacitySpec("4m", channels=160, blocks=3, feedforward_multiplier=4, heads=8),
}


class WindowAttentionBlock(nn.Module):
    """Windowed self-attention at reduced spatial resolution."""

    def __init__(self, channels: int, heads: int, feedforward_multiplier: int, window_size: int = 8):
        super().__init__()
        if channels % heads:
            raise ValueError("channels must be divisible by heads")
        self.window_size = window_size
        self.norm1 = nn.LayerNorm(channels)
        self.attn = nn.MultiheadAttention(channels, heads, batch_first=True)
        self.norm2 = nn.LayerNorm(channels)
        hidden = channels * feedforward_multiplier
        self.ffn = nn.Sequential(
            nn.Linear(channels, hidden),
            nn.GELU(),
            nn.Linear(hidden, channels),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        batch, channels, height, width = x.shape
        window = self.window_size
        pad_h = (window - height % window) % window
        pad_w = (window - width % window) % window
        if pad_h or pad_w:
            x = F.pad(x, (0, pad_w, 0, pad_h), mode="replicate")
        padded_h, padded_w = x.shape[-2:]
        windows = x.view(batch, channels, padded_h // window, window, padded_w // window, window)
        windows = windows.permute(0, 2, 4, 3, 5, 1).reshape(-1, window * window, channels)
        attended = self.attn(self.norm1(windows), self.norm1(windows), self.norm1(windows), need_weights=False)[0]
        windows = windows + attended
        windows = windows + self.ffn(self.norm2(windows))
        x = windows.view(batch, padded_h // window, padded_w // window, window, window, channels)
        x = x.permute(0, 5, 1, 3, 2, 4).reshape(batch, channels, padded_h, padded_w)
        return x[..., :height, :width]


class HybridStudent(nn.Module):
    """A residual RGB student with a reduced-resolution window transformer."""

    def __init__(self, capacity: str = "1m"):
        super().__init__()
        if capacity not in CAPACITIES:
            raise ValueError(f"unknown capacity {capacity!r}; choose {sorted(CAPACITIES)}")
        self.capacity = CAPACITIES[capacity]
        channels = self.capacity.channels
        stem_hidden = max(8, channels // 2)
        self.stem = nn.Sequential(
            nn.Conv2d(3, stem_hidden, 3, stride=2, padding=1),
            nn.GELU(),
            nn.Conv2d(stem_hidden, channels, 3, stride=2, padding=1),
            nn.GELU(),
            nn.Conv2d(channels, channels, 3, stride=2, padding=1),
            nn.GELU(),
        )
        self.core = nn.Sequential(
            *[
                WindowAttentionBlock(
                    channels,
                    self.capacity.heads,
                    self.capacity.feedforward_multiplier,
                )
                for _ in range(self.capacity.blocks)
            ]
        )
        self.reconstruction = nn.Sequential(
            nn.Conv2d(channels, channels * 4, 3, padding=1),
            nn.PixelShuffle(2),
            nn.GELU(),
            nn.Conv2d(channels, channels * 4, 3, padding=1),
            nn.PixelShuffle(2),
            nn.GELU(),
            nn.Conv2d(channels, channels * 4, 3, padding=1),
            nn.PixelShuffle(2),
            nn.GELU(),
            nn.Conv2d(channels, 3, 3, padding=1),
        )
        # Identity-safe residual initialization: every capacity starts as the
        # raw RGB input, so a failed or interrupted run cannot emit garbage.
        nn.init.zeros_(self.reconstruction[-1].weight)
        nn.init.zeros_(self.reconstruction[-1].bias)
        self.residual_scale = nn.Parameter(torch.tensor(0.25))

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        if x.ndim != 4 or x.shape[1] != 3:
            raise ValueError(f"expected BCHW RGB input, got {tuple(x.shape)}")
        features = self.core(self.stem(x))
        residual = torch.tanh(self.reconstruction(features)) * self.residual_scale
        return (x + residual).clamp(0.0, 1.0)


def parameter_count(model: nn.Module) -> int:
    return sum(parameter.numel() for parameter in model.parameters())
