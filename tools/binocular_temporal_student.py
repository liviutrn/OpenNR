"""Zero-initialized binocular conditioning for the capacity-temporal student.

The existing capacity-temporal model processes each eye independently.  This
module adds a separate residual branch that consumes the current opposite-eye
RGB crop as an auxiliary appearance cue.  The branch is zero-initialized, so
loading a prior single-eye checkpoint preserves its function exactly until the
new branch learns a residual.
"""

from __future__ import annotations

from dataclasses import dataclass

import torch
from torch import nn
from torch.nn import functional as F

from capacity_student import CapacityConfig
from capacity_temporal_student import CapacityTemporalStyleContextStudent
from opennr_student import GatedBlock
from student_v2 import ReconstructionConfig
from temporal_student import TemporalConfig


@dataclass
class BinocularConfig:
    width: int = 128
    blocks: int = 6
    delta_scale: float = 0.12


class BinocularCapacityTemporalStyleContextStudent(
    CapacityTemporalStyleContextStudent
):
    """Capacity-temporal student with a paired-eye appearance residual."""

    architecture = "context_v8_binocular_capacity_temporal"

    def __init__(
        self,
        config: ReconstructionConfig = ReconstructionConfig(),
        temporal: TemporalConfig = TemporalConfig(),
        capacity: CapacityConfig = CapacityConfig(),
        binocular: BinocularConfig = BinocularConfig(),
    ) -> None:
        super().__init__(config, temporal, capacity)
        if binocular.width < 32:
            raise ValueError("Binocular width is too small")
        if binocular.blocks < 1:
            raise ValueError("Binocular block count must be positive")
        if binocular.delta_scale <= 0:
            raise ValueError("Binocular delta scale must be positive")
        self.binocular_config = binocular
        c = binocular.width

        self.binocular_context = nn.Sequential(
            nn.Conv2d(8, 64, 3, padding=1),
            nn.SiLU(),
            nn.Conv2d(64, 32, 3, padding=1),
            nn.SiLU(),
        )
        # Current RGB, current single-eye prediction, opposite-eye RGB and
        # current native guides, plus whole-eye context.
        self.binocular_input = nn.Conv2d(3 + 3 + 3 + 5 + 32, c, 3, padding=1)
        self.binocular_blocks = nn.Sequential(*(GatedBlock(c) for _ in range(binocular.blocks)))
        self.binocular_output = nn.Conv2d(c, 3 * 4 * 4, 3, padding=1)
        nn.init.zeros_(self.binocular_output.weight)
        nn.init.zeros_(self.binocular_output.bias)

    def initialize_v5(self, state: dict[str, torch.Tensor]) -> None:
        """Load a single-eye parent, allowing only capacity/binocular additions."""

        incompatible = self.load_state_dict(state, strict=False)
        if incompatible.unexpected_keys:
            raise ValueError(f"Unexpected parent keys: {incompatible.unexpected_keys}")
        allowed_prefixes = ("capacity_", "binocular_")
        invalid_missing = [
            key
            for key in incompatible.missing_keys
            if not key.startswith(allowed_prefixes)
        ]
        if invalid_missing:
            raise ValueError(f"Non-extension parent keys are missing: {invalid_missing}")

    def _binocular_residual(self, rgb, base, opposite_rgb, guides, context):
        h, w = rgb.shape[-2:]
        size = ((h + 3) // 4, (w + 3) // 4)
        context_features = F.interpolate(
            self.binocular_context(context),
            size=size,
            mode="bilinear",
            align_corners=False,
        )
        features = torch.cat(
            (
                F.interpolate(rgb, size=size, mode="area"),
                F.interpolate(base.detach(), size=size, mode="area"),
                F.interpolate(opposite_rgb, size=size, mode="area"),
                F.interpolate(guides, size=size, mode="bilinear", align_corners=False),
                context_features,
            ),
            dim=1,
        )
        features = self.binocular_blocks(self.binocular_input(features))
        residual = F.pixel_shuffle(self.binocular_output(features), 4)
        if residual.shape[-2:] != (h, w):
            residual = F.interpolate(residual, size=(h, w), mode="bilinear", align_corners=False)
        return residual

    def forward_pair_temporal(self, rgb, guides, context, state=None):
        """Process a pair shaped ``[batch, 2, channels, height, width]``.

        The recurrent parent state is flattened across the two eyes, while the
        opposite-eye RGB remains paired for the new residual branch.  The
        returned state carries the refined output so the next frame receives
        the same delivered image as the single-eye capacity model.
        """

        if rgb.ndim != 5 or rgb.shape[1] != 2:
            raise ValueError("Binocular forward expects RGB shaped [batch, 2, 3, height, width]")
        batch = rgb.shape[0]
        flat_rgb = rgb.reshape(batch * 2, *rgb.shape[2:])
        flat_guides = guides.reshape(batch * 2, *guides.shape[2:])
        flat_context = context.reshape(batch * 2, *context.shape[2:])
        prediction, next_state = super().forward_temporal(
            flat_rgb, flat_guides, flat_context, state
        )
        prediction_pair = prediction.reshape(batch, 2, *prediction.shape[1:])
        residual = self._binocular_residual(
            flat_rgb,
            prediction,
            flat_rgb.reshape(batch, 2, *flat_rgb.shape[1:]).flip(1).reshape(
                batch * 2, *flat_rgb.shape[1:]
            ),
            flat_guides,
            flat_context,
        )
        refined = (
            prediction + self.binocular_config.delta_scale * torch.tanh(residual)
        ).clamp(0.0, 1.0)
        return refined, (next_state[0], refined)
