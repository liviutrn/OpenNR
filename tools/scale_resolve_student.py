"""Tiny learned full-resolution resolver for a reduced native neural edit."""

from __future__ import annotations

from dataclasses import asdict, dataclass

import torch
from torch import nn
from torch.nn import functional as F


@dataclass
class ScaleResolveConfig:
    hidden_channels: int = 24
    layers: int = 2
    correction_scale: float = 0.25
    gate_scale: float = 0.5

    def validate(self) -> None:
        if self.hidden_channels < 4 or self.layers < 1:
            raise ValueError("hidden_channels and layers must be positive")
        if not 0.0 < self.correction_scale <= 1.0:
            raise ValueError("correction_scale must be in (0, 1]")
        if not 0.0 < self.gate_scale <= 1.0:
            raise ValueError("gate_scale must be in (0, 1]")


class ScaleResolveStudent(nn.Module):
    """Per-pixel residual gate/correction with exact naive-resolve startup.

    ``rgb`` is the original full-resolution source and ``edit`` is the
    upsampled reduced-neural edit ``small_output - small_input``.  At step zero
    the output is exactly ``clamp(rgb + edit)`` because the final head is
    zero-initialized and the gate is centered at one.

    The current pilot deliberately uses only RGB and the neural edit.  A
    separately trained guide-conditioned variant can be added after this
    minimal path demonstrates a held-out gain.
    """

    def __init__(self, config: ScaleResolveConfig | None = None):
        super().__init__()
        self.config = config or ScaleResolveConfig()
        self.config.validate()
        hidden = self.config.hidden_channels
        layers: list[nn.Module] = [nn.Conv2d(6, hidden, 1), nn.SiLU()]
        for _ in range(self.config.layers - 1):
            layers.extend((nn.Conv2d(hidden, hidden, 1), nn.SiLU()))
        self.body = nn.Sequential(*layers)
        self.head = nn.Conv2d(hidden, 6, 1)
        for module in self.body:
            if isinstance(module, nn.Conv2d):
                nn.init.kaiming_normal_(module.weight, mode="fan_out", nonlinearity="relu")
                nn.init.zeros_(module.bias)
        nn.init.zeros_(self.head.weight)
        nn.init.zeros_(self.head.bias)

    def forward(self, rgb: torch.Tensor, edit: torch.Tensor) -> torch.Tensor:
        if rgb.ndim != 4 or rgb.shape[1] != 3:
            raise ValueError("rgb must be [N,3,H,W]")
        if edit.shape != rgb.shape:
            raise ValueError("edit must have the same shape as rgb")
        hidden = self.body(torch.cat((rgb, edit), dim=1))
        gate_raw, correction_raw = self.head(hidden).chunk(2, dim=1)
        gate = 1.0 + self.config.gate_scale * torch.tanh(gate_raw)
        correction = self.config.correction_scale * torch.tanh(correction_raw)
        return (rgb + gate * edit + correction).clamp(0.0, 1.0)

    def from_small(
        self,
        rgb: torch.Tensor,
        small_input: torch.Tensor,
        small_output: torch.Tensor,
    ) -> torch.Tensor:
        edit = F.interpolate(
            small_output - small_input,
            size=rgb.shape[-2:],
            mode="bilinear",
            align_corners=False,
        )
        return self(rgb, edit)


class GuidedScaleResolveStudent(nn.Module):
    """Cheap spatial resolver conditioned on full-resolution depth and motion.

    The guide bundle is ``[depth, motion_x, motion_y]`` after the caller has
    validated and resized the exact Feature 18 resources.  A depthwise 3x3
    layer supplies local silhouette context while pointwise layers keep the
    parameter count and expected full-resolution cost small.  Like the RGB
    baseline, the zero-initialized head makes step zero exactly equal to the
    naive matched residual.
    """

    def __init__(self, config: ScaleResolveConfig | None = None):
        super().__init__()
        self.config = config or ScaleResolveConfig()
        self.config.validate()
        hidden = self.config.hidden_channels
        self.stem = nn.Conv2d(9, hidden, 1)
        self.body = nn.Sequential(
            nn.SiLU(),
            nn.Conv2d(hidden, hidden, 3, padding=1, groups=hidden),
            nn.SiLU(),
            nn.Conv2d(hidden, hidden, 1),
            nn.SiLU(),
        )
        self.head = nn.Conv2d(hidden, 6, 1)
        for module in (self.stem, self.body[1], self.body[3]):
            nn.init.kaiming_normal_(module.weight, mode="fan_out", nonlinearity="relu")
            nn.init.zeros_(module.bias)
        nn.init.zeros_(self.head.weight)
        nn.init.zeros_(self.head.bias)

    def forward(
        self,
        rgb: torch.Tensor,
        edit: torch.Tensor,
        guides: torch.Tensor,
    ) -> torch.Tensor:
        if rgb.ndim != 4 or rgb.shape[1] != 3:
            raise ValueError("rgb must be [N,3,H,W]")
        if edit.shape != rgb.shape:
            raise ValueError("edit must have the same shape as rgb")
        if guides.ndim != 4 or guides.shape[1] != 3 or guides.shape[-2:] != rgb.shape[-2:]:
            raise ValueError("guides must be [N,3,H,W] at the RGB resolution")
        hidden = self.body(self.stem(torch.cat((rgb, edit, guides), dim=1)))
        gate_raw, correction_raw = self.head(hidden).chunk(2, dim=1)
        gate = 1.0 + self.config.gate_scale * torch.tanh(gate_raw)
        correction = self.config.correction_scale * torch.tanh(correction_raw)
        return (rgb + gate * edit + correction).clamp(0.0, 1.0)

    def from_small(
        self,
        rgb: torch.Tensor,
        small_input: torch.Tensor,
        small_output: torch.Tensor,
        guides: torch.Tensor,
    ) -> torch.Tensor:
        edit = F.interpolate(
            small_output - small_input,
            size=rgb.shape[-2:],
            mode="bilinear",
            align_corners=False,
        )
        return self(rgb, edit, guides)


def config_dict(config: ScaleResolveConfig) -> dict[str, int | float]:
    config.validate()
    return asdict(config)
