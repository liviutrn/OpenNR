"""Causal temporal extension of the context-v4 OpenNR student.

The inherited spatial/context path is kept unchanged.  A small, zero-initialized
recurrent residual branch is added so a v8 checkpoint is an exact step-0
functional baseline.  The branch consumes the current RGB, current spatial
prediction, the previous student prediction, and the captured native guides.
It carries a low-resolution ConvGRU state and never replaces the captured
Feature-18 depth or motion-vector resources.
"""

from __future__ import annotations

from dataclasses import dataclass

import torch
from torch import nn
from torch.nn import functional as F

from student_v2 import ReconstructionConfig
from student_v4 import StyleContextStudent


@dataclass
class TemporalConfig:
    hidden: int = 64
    downsample: int = 8
    delta_scale: float = 0.12


class TemporalStyleContextStudent(StyleContextStudent):
    """Context-v4 plus a streaming causal residual branch."""

    architecture = "context_v5_temporal"

    def __init__(
        self,
        config: ReconstructionConfig = ReconstructionConfig(),
        temporal: TemporalConfig = TemporalConfig(),
    ) -> None:
        super().__init__(config)
        if temporal.downsample not in (4, 8, 16):
            raise ValueError("Temporal downsample must be 4, 8, or 16")
        if temporal.hidden < 8:
            raise ValueError("Temporal hidden width is too small")
        self.temporal_config = temporal
        h = temporal.hidden
        # RGB + current spatial output + previous student output + 5 guide maps.
        self.temporal_input = nn.Sequential(
            nn.Conv2d(14, h, 3, padding=1),
            nn.SiLU(),
            nn.Conv2d(h, h, 3, padding=1),
            nn.SiLU(),
        )
        self.temporal_gate = nn.Conv2d(h * 2, h * 2, 3, padding=1)
        self.temporal_candidate = nn.Conv2d(h * 2, h, 3, padding=1)
        # Four-times pixel shuffle gives the branch useful local detail while
        # keeping recurrent state and most compute at 1/8 input resolution.
        self.temporal_output = nn.Conv2d(h, 3 * 4 * 4, 3, padding=1)
        nn.init.zeros_(self.temporal_output.weight)
        nn.init.zeros_(self.temporal_output.bias)

    def initialize_v4(self, state: dict[str, torch.Tensor]) -> None:
        """Load a context-v4 EMA state and require only temporal keys missing."""

        incompatible = self.load_state_dict(state, strict=False)
        if incompatible.unexpected_keys:
            raise ValueError(f"Unexpected parent keys: {incompatible.unexpected_keys}")
        invalid_missing = [
            key for key in incompatible.missing_keys if not key.startswith("temporal_")
        ]
        if invalid_missing:
            raise ValueError(f"Non-temporal parent keys are missing: {invalid_missing}")

    def initial_state(self, rgb: torch.Tensor):
        """Return a zero history state for a batch of current RGB frames."""

        h, w = rgb.shape[-2:]
        ds = self.temporal_config.downsample
        low_h = (h + ds - 1) // ds
        low_w = (w + ds - 1) // ds
        hidden = rgb.new_zeros(
            (rgb.shape[0], self.temporal_config.hidden, low_h, low_w)
        )
        return hidden, rgb

    def forward_temporal(self, rgb, guides, context, state=None):
        """Process one frame and return ``(prediction, next_state)``.

        Passing ``state=None`` is an explicit history reset.  The previous
        prediction is detached before it enters the next-step input so the
        recurrent branch does not create an unnecessary full-resolution graph.
        The hidden state itself remains differentiable within a training
        window; the trainer truncates it at window boundaries.
        """

        base = super().forward(rgb, guides, context)
        if state is None:
            hidden, previous = self.initial_state(rgb)
        else:
            hidden, previous = state

        ds = self.temporal_config.downsample
        size = ((rgb.shape[-2] + ds - 1) // ds, (rgb.shape[-1] + ds - 1) // ds)
        rgb_low = F.interpolate(rgb, size=size, mode="area")
        base_low = F.interpolate(base.detach(), size=size, mode="area")
        previous_low = F.interpolate(previous.detach(), size=size, mode="area")
        guide_low = F.interpolate(guides, size=size, mode="bilinear", align_corners=False)
        features = self.temporal_input(
            torch.cat((rgb_low, base_low, previous_low, guide_low), dim=1)
        )
        if hidden.shape[-2:] != size or hidden.shape[1] != features.shape[1]:
            hidden = features.new_zeros(features.shape)
        else:
            hidden = hidden.to(dtype=features.dtype)

        joined = torch.cat((features, hidden), dim=1)
        update, reset = self.temporal_gate(joined).chunk(2, dim=1)
        update = torch.sigmoid(update)
        reset = torch.sigmoid(reset)
        candidate = torch.tanh(
            self.temporal_candidate(torch.cat((features, reset * hidden), dim=1))
        )
        hidden = (1.0 - update) * hidden + update * candidate

        delta = F.pixel_shuffle(self.temporal_output(hidden), 4)
        delta = F.interpolate(delta, size=rgb.shape[-2:], mode="bilinear", align_corners=False)
        prediction = (
            base + self.temporal_config.delta_scale * torch.tanh(delta)
        ).clamp(0.0, 1.0)
        return prediction, (hidden, prediction)

    def forward(self, rgb, guides, context):
        """Keep normal inference compatible with the inherited spatial model."""

        return super().forward(rgb, guides, context)

