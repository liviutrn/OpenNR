"""Zero-initialized high-capacity spatial refinement for the OpenNR student.

The inherited context-v4 path remains the control.  A separate quarter-resolution
refinement branch consumes RGB, the inherited prediction, native guides, and
whole-eye context, then produces a native-resolution residual.  Its output head
starts at zero, so a v8 checkpoint has an exact step-0 function while the added
capacity can learn the broad tone and local detail that remained visibly
different from the Feature-18 teacher.
"""

from __future__ import annotations

from dataclasses import dataclass

import torch
from torch import nn
from torch.nn import functional as F

from opennr_student import GatedBlock
from student_v2 import ReconstructionConfig
from student_v4 import StyleContextStudent


@dataclass
class CapacityConfig:
    width: int = 128
    blocks: int = 6
    delta_scale: float = 0.12
    # Optional global context modulation for the capacity branch. The default
    # remains disabled so existing checkpoints keep their exact architecture.
    style_modulation: bool = False
    # Optional second zero-initialized refinement branch.  Keeping the default
    # at zero preserves the serialized v6/v7 model shapes and exact function.
    extra_width: int = 0
    extra_blocks: int = 0
    # Optional per-pixel gates on the learned residuals. The heads are
    # zero-initialized, so enabling them preserves the inherited function at
    # step 0 while allowing the branch to suppress low-effect corrections.
    residual_gate: bool = False
    residual_gate_scale: float = 0.8
    # Optional gate around the complete student correction (including the
    # inherited spatial and temporal branches). It is also parent-preserving.
    final_gate: bool = False
    final_gate_scale: float = 0.8


class CapacityStyleContextStudent(StyleContextStudent):
    """Context-v4 plus a wider native-detail/appearance residual branch."""

    architecture = "context_v6_capacity"

    def __init__(
        self,
        config: ReconstructionConfig = ReconstructionConfig(),
        capacity: CapacityConfig = CapacityConfig(),
    ) -> None:
        super().__init__(config)
        if capacity.width < 32:
            raise ValueError("Capacity width is too small")
        if capacity.blocks < 1:
            raise ValueError("Capacity block count must be positive")
        if capacity.delta_scale <= 0:
            raise ValueError("Capacity delta scale must be positive")
        self.capacity_config = capacity
        c = capacity.width

        # Retain a spatial context feature map instead of pooling it away.  The
        # context tensor is already an audited whole-eye signal from the cache.
        self.capacity_context = nn.Sequential(
            nn.Conv2d(8, 64, 3, padding=1),
            nn.SiLU(),
            nn.Conv2d(64, 32, 3, padding=1),
            nn.SiLU(),
        )
        # RGB + inherited prediction + five native guide planes + context.
        self.capacity_input = nn.Conv2d(3 + 3 + 5 + 32, c, 3, padding=1)
        self.capacity_blocks = nn.Sequential(*(GatedBlock(c) for _ in range(capacity.blocks)))
        self.capacity_output = nn.Conv2d(c, 3 * 4 * 4, 3, padding=1)
        # Exact parent-function preservation at initialization.
        nn.init.zeros_(self.capacity_output.weight)
        nn.init.zeros_(self.capacity_output.bias)

    def initialize_v4(self, state: dict[str, torch.Tensor]) -> None:
        """Load a context-v4 EMA state and require only capacity keys missing."""

        incompatible = self.load_state_dict(state, strict=False)
        if incompatible.unexpected_keys:
            raise ValueError(f"Unexpected parent keys: {incompatible.unexpected_keys}")
        invalid_missing = [
            key for key in incompatible.missing_keys if not key.startswith("capacity_")
        ]
        if invalid_missing:
            raise ValueError(f"Non-capacity parent keys are missing: {invalid_missing}")

    def forward(self, rgb, guides, context):
        base = super().forward(rgb, guides, context)
        h, w = rgb.shape[-2:]
        size = ((h + 3) // 4, (w + 3) // 4)
        context_features = self.capacity_context(context)
        context_features = F.interpolate(
            context_features, size=size, mode="bilinear", align_corners=False
        )
        features = torch.cat(
            (
                F.interpolate(rgb, size=size, mode="area"),
                F.interpolate(base.detach(), size=size, mode="area"),
                F.interpolate(guides, size=size, mode="bilinear", align_corners=False),
                context_features,
            ),
            dim=1,
        )
        features = self.capacity_input(features)
        features = self.capacity_blocks(features)
        residual = F.pixel_shuffle(self.capacity_output(features), 4)
        if residual.shape[-2:] != (h, w):
            residual = F.interpolate(residual, size=(h, w), mode="bilinear", align_corners=False)
        return (base + self.capacity_config.delta_scale * torch.tanh(residual)).clamp(0, 1)
