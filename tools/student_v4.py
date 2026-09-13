"""Context-v4 spatial student with a zero-initialized whole-eye style branch.

The v3 student already uses whole-eye context for bottleneck cross-attention,
but its output is produced entirely by the local crop path.  This extension
adds a small, smooth residual predicted from the complete context tensor.  It
is deliberately zero-initialized so loading a v3 checkpoint preserves the v3
function exactly at step zero.  The branch can therefore be evaluated as a
controlled appearance ablation rather than a replacement teacher architecture.

The branch is spatial-only.  It carries no temporal state and does not infer or
replace native Feature 18 motion/depth resources.
"""

import torch
from torch import nn
from torch.nn import functional as F

from student_v2 import ReconstructionConfig
from student_v3 import ContextStudent


class StyleContextStudent(ContextStudent):
    """Context-v3 plus a smooth context-conditioned appearance residual."""

    def __init__(self, config=ReconstructionConfig()):
        super().__init__(config)
        # Keep this branch inexpensive: it operates on the fixed 96x96
        # context grid and is upsampled only once at the output boundary.
        self.style_grid = nn.Sequential(
            nn.Conv2d(8, 32, 3, padding=1),
            nn.SiLU(),
            nn.Conv2d(32, 32, 3, stride=2, padding=1),
            nn.SiLU(),
            nn.Conv2d(32, 16, 3, padding=1),
            nn.SiLU(),
            nn.Conv2d(16, 3, 3, padding=1),
        )
        # Exact v3 compatibility at initialization.  Training is free to
        # learn the branch after the copied v3 weights have been checked.
        nn.init.zeros_(self.style_grid[-1].weight)
        nn.init.zeros_(self.style_grid[-1].bias)

    def forward(self, rgb, guides, context):
        base = super().forward(rgb, guides, context)
        style = self.style_grid(context)
        style = F.interpolate(style, size=rgb.shape[-2:], mode="bilinear", align_corners=False)
        # The bounded coefficient prevents the new branch from overwhelming
        # the learned local reconstruction while still allowing broad tone
        # changes that a crop-only residual cannot represent reliably.
        return (base + 0.12 * torch.tanh(style)).clamp(0, 1)

    def initialize_v3(self, state):
        """Load a v3 EMA state and require only the new style keys to differ."""
        incompatible = self.load_state_dict(state, strict=False)
        if incompatible.unexpected_keys or any(
            not key.startswith("style_grid.") for key in incompatible.missing_keys
        ):
            raise ValueError(f"Unexpected v3 conversion mismatch: {incompatible}")

