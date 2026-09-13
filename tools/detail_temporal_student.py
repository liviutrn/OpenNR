"""Native-detail refinement attached to the causal OpenNR student.

The v9 temporal student still does most learned work on a quarter-resolution
grid.  This extension adds a small half-resolution path that sees the current
RGB, the delivered temporal prediction, native guides, and the whole-eye
context.  Its output head is zero-initialized, so loading a v9 checkpoint is
an exact functional baseline at step zero.  The branch is deliberately a
residual refinement; it does not replace captured Feature-18 depth or motion
vectors and it does not invent optical flow.
"""

from __future__ import annotations

from dataclasses import dataclass

import torch
from torch import nn
from torch.nn import functional as F

from opennr_student import GatedBlock
from student_v2 import ReconstructionConfig
from temporal_student import TemporalConfig, TemporalStyleContextStudent


@dataclass
class DetailConfig:
    width: int = 48
    blocks: int = 4
    downsample: int = 2
    delta_scale: float = 0.12


class DetailTemporalStyleContextStudent(TemporalStyleContextStudent):
    """v9 temporal student plus a zero-initialized native-detail refiner."""

    architecture = "context_v9_detail_temporal"

    def __init__(
        self,
        config: ReconstructionConfig = ReconstructionConfig(),
        temporal: TemporalConfig = TemporalConfig(),
        detail: DetailConfig = DetailConfig(),
    ) -> None:
        super().__init__(config, temporal)
        if detail.width < 16:
            raise ValueError("Detail width is too small")
        if detail.blocks < 1:
            raise ValueError("Detail block count must be positive")
        if detail.downsample not in (2, 4):
            raise ValueError("Detail downsample must be 2 or 4")
        if detail.delta_scale <= 0:
            raise ValueError("Detail delta scale must be positive")
        self.detail_config = detail
        c = detail.width
        ds = detail.downsample
        # RGB + temporal prediction + five native guide planes + eight context
        # planes.  The context is spatially resized only inside this branch.
        self.detail_input = nn.Conv2d(3 + 3 + 5 + 8, c, 3, padding=1)
        self.detail_blocks = nn.Sequential(
            *(GatedBlock(c) for _ in range(detail.blocks))
        )
        self.detail_output = nn.Conv2d(c, 3 * ds * ds, 3, padding=1)
        nn.init.zeros_(self.detail_output.weight)
        nn.init.zeros_(self.detail_output.bias)

    def initialize_v5(self, state: dict[str, torch.Tensor]) -> None:
        """Load a v9 temporal state and require only detail keys to be new."""

        incompatible = self.load_state_dict(state, strict=False)
        if incompatible.unexpected_keys:
            raise ValueError(f"Unexpected parent keys: {incompatible.unexpected_keys}")
        invalid_missing = [
            key for key in incompatible.missing_keys if not key.startswith("detail_")
        ]
        if invalid_missing:
            raise ValueError(f"Non-detail parent keys are missing: {invalid_missing}")

    def _detail_residual(self, rgb, prediction, guides, context):
        h, w = rgb.shape[-2:]
        ds = self.detail_config.downsample
        size = ((h + ds - 1) // ds, (w + ds - 1) // ds)
        features = torch.cat(
            (
                F.interpolate(rgb, size=size, mode="area"),
                F.interpolate(prediction.detach(), size=size, mode="area"),
                F.interpolate(guides, size=size, mode="bilinear", align_corners=False),
                F.interpolate(context, size=size, mode="bilinear", align_corners=False),
            ),
            dim=1,
        )
        features = self.detail_blocks(self.detail_input(features))
        residual = F.pixel_shuffle(self.detail_output(features), ds)
        if residual.shape[-2:] != (h, w):
            residual = F.interpolate(
                residual, size=(h, w), mode="bilinear", align_corners=False
            )
        return residual

    def _refine(self, prediction, rgb, guides, context):
        residual = self._detail_residual(rgb, prediction, guides, context)
        return (
            prediction + self.detail_config.delta_scale * torch.tanh(residual)
        ).clamp(0.0, 1.0)

    def forward_temporal(self, rgb, guides, context, state=None):
        prediction, next_state = super().forward_temporal(
            rgb, guides, context, state
        )
        prediction = self._refine(prediction, rgb, guides, context)
        # The recurrent path must consume the same refined frame that was
        # delivered to the caller on the next step.
        return prediction, (next_state[0], prediction)

    def forward(self, rgb, guides, context):
        prediction = super().forward(rgb, guides, context)
        return self._refine(prediction, rgb, guides, context)
