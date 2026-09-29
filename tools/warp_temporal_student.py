"""Motion-compensated causal extension of the v9 OpenNR student.

The strict capture audit shows that the native Feature-18 motion vectors are
predictive of the next teacher frame.  This class uses those captured vectors
to sample the previous student prediction and recurrent state at the current
coordinates.  The grid sign is the one independently selected by the
read-only teacher-to-teacher warp diagnostic.  No optical flow is inferred and
no captured depth or motion resource is replaced.
"""

from __future__ import annotations

import torch
from dataclasses import dataclass
from torch.nn import functional as F

from student_v4 import StyleContextStudent
from temporal_student import TemporalConfig, TemporalStyleContextStudent
from student_v2 import ReconstructionConfig


class MotionWarpTemporalStyleContextStudent(TemporalStyleContextStudent):
    """v9 temporal student whose history is sampled with exact native MV."""

    architecture = "context_v10_warp_temporal"

    def __init__(
        self,
        config: ReconstructionConfig = ReconstructionConfig(),
        temporal: TemporalConfig = TemporalConfig(),
    ) -> None:
        super().__init__(config, temporal)

    def initialize_v9(self, state: dict[str, torch.Tensor]) -> None:
        """Load a v9 state; this variant adds no learned parameters."""

        incompatible = self.load_state_dict(state, strict=False)
        if incompatible.unexpected_keys or incompatible.missing_keys:
            raise ValueError(f"Unexpected v9 conversion mismatch: {incompatible}")

    @staticmethod
    def _motion_grid(guides, size, image_size):
        """Return an align_corners=False grid using the verified positive sign.

        Cache motion is native color-pixel displacement divided by 128.  At a
        learned grid of width ``w // ds`` the normalized displacement is
        ``motion * 256 / w``; the same expression applies vertically.
        """

        height, width = image_size
        low_h, low_w = size
        yy, xx = torch.meshgrid(
            torch.arange(low_h, device=guides.device, dtype=guides.dtype),
            torch.arange(low_w, device=guides.device, dtype=guides.dtype),
            indexing="ij",
        )
        base = torch.stack(
            (
                (xx + 0.5) / low_w * 2.0 - 1.0,
                (yy + 0.5) / low_h * 2.0 - 1.0,
            ),
            dim=-1,
        )[None]
        mv = F.interpolate(
            guides[:, 1:3], size=size, mode="bilinear", align_corners=False
        )
        displacement = torch.stack(
            (
                mv[:, 0] * (256.0 / float(width)),
                mv[:, 1] * (256.0 / float(height)),
            ),
            dim=-1,
        )
        # The plus sign was selected because grid_sample(previous, base + mv)
        # reduced oracle teacher-to-teacher error on both held-out splits.
        return base + displacement

    def _warp_history(self, history, guides, size, image_size, detach):
        source = history.detach() if detach else history
        if source.shape[-2:] != size:
            source = F.interpolate(source, size=size, mode="area")
        grid = self._motion_grid(guides, size, image_size)
        return F.grid_sample(
            source,
            grid,
            mode="bilinear",
            padding_mode="border",
            align_corners=False,
        )

    def forward_temporal(self, rgb, guides, context, state=None):
        """Process one frame with motion-compensated history and reset state."""

        base = StyleContextStudent.forward(self, rgb, guides, context)
        if state is None:
            hidden, previous = self.initial_state(rgb)
        else:
            hidden, previous = state

        ds = self.temporal_config.downsample
        size = (
            (rgb.shape[-2] + ds - 1) // ds,
            (rgb.shape[-1] + ds - 1) // ds,
        )
        rgb_low = F.interpolate(rgb, size=size, mode="area")
        base_low = F.interpolate(base.detach(), size=size, mode="area")
        previous_low = self._warp_history(
            previous, guides, size, rgb.shape[-2:], detach=True
        )
        guide_low = F.interpolate(
            guides, size=size, mode="bilinear", align_corners=False
        )
        features = self.temporal_input(
            torch.cat((rgb_low, base_low, previous_low, guide_low), dim=1)
        )
        if hidden.shape[-2:] != size or hidden.shape[1] != features.shape[1]:
            hidden = features.new_zeros(features.shape)
        else:
            hidden = self._warp_history(
                hidden, guides, size, rgb.shape[-2:], detach=False
            ).to(dtype=features.dtype)

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
        """Keep frozen spatial evaluation compatible with the v9 checkpoint."""

        return StyleContextStudent.forward(self, rgb, guides, context)


@dataclass
class BlendConfig:
    """Bound for the direct full-resolution warped-history skip."""

    scale: float = 0.25


class MotionWarpBlendTemporalStyleContextStudent(MotionWarpTemporalStyleContextStudent):
    """Motion-warp v10 plus a learned direct warped-history blend.

    The v10 recurrent path only observes warped history after reducing it to
    1/8 resolution.  This extension gives a zero-initialized gate access to a
    full-resolution warped previous prediction, allowing it to preserve useful
    carried detail without forcing the recurrent hidden state to represent
    every pixel.  The first frame after an explicit reset never uses the skip.
    """

    architecture = "context_v11_warp_blend_temporal"

    def __init__(
        self,
        config: ReconstructionConfig = ReconstructionConfig(),
        temporal: TemporalConfig = TemporalConfig(),
        blend: BlendConfig = BlendConfig(),
    ) -> None:
        super().__init__(config, temporal)
        if blend.scale <= 0:
            raise ValueError("Blend scale must be positive")
        self.blend_config = blend
        self.warp_blend_gate = torch.nn.Conv2d(
            temporal.hidden, 1, 3, padding=1
        )
        torch.nn.init.zeros_(self.warp_blend_gate.weight)
        torch.nn.init.zeros_(self.warp_blend_gate.bias)

    def initialize_v9(self, state: dict[str, torch.Tensor]) -> None:
        """Load a v9 state and require only the new gate keys to be missing."""

        incompatible = self.load_state_dict(state, strict=False)
        if incompatible.unexpected_keys:
            raise ValueError(f"Unexpected v9 conversion mismatch: {incompatible}")
        invalid_missing = [
            key for key in incompatible.missing_keys
            if not key.startswith("warp_blend_gate.")
        ]
        if invalid_missing:
            raise ValueError(f"Non-gate parent keys are missing: {invalid_missing}")

    def forward_temporal(self, rgb, guides, context, state=None):
        had_history = state is not None
        base = StyleContextStudent.forward(self, rgb, guides, context)
        if state is None:
            hidden, previous = self.initial_state(rgb)
        else:
            hidden, previous = state

        ds = self.temporal_config.downsample
        size = (
            (rgb.shape[-2] + ds - 1) // ds,
            (rgb.shape[-1] + ds - 1) // ds,
        )
        rgb_low = F.interpolate(rgb, size=size, mode="area")
        base_low = F.interpolate(base.detach(), size=size, mode="area")
        previous_low = self._warp_history(
            previous, guides, size, rgb.shape[-2:], detach=True
        )
        guide_low = F.interpolate(
            guides, size=size, mode="bilinear", align_corners=False
        )
        features = self.temporal_input(
            torch.cat((rgb_low, base_low, previous_low, guide_low), dim=1)
        )
        if hidden.shape[-2:] != size or hidden.shape[1] != features.shape[1]:
            hidden = features.new_zeros(features.shape)
        else:
            hidden = self._warp_history(
                hidden, guides, size, rgb.shape[-2:], detach=False
            ).to(dtype=features.dtype)

        joined = torch.cat((features, hidden), dim=1)
        update, reset = self.temporal_gate(joined).chunk(2, dim=1)
        update = torch.sigmoid(update)
        reset = torch.sigmoid(reset)
        candidate = torch.tanh(
            self.temporal_candidate(torch.cat((features, reset * hidden), dim=1))
        )
        hidden = (1.0 - update) * hidden + update * candidate

        delta = F.pixel_shuffle(self.temporal_output(hidden), 4)
        delta = F.interpolate(
            delta, size=rgb.shape[-2:], mode="bilinear", align_corners=False
        )
        prediction = (
            base + self.temporal_config.delta_scale * torch.tanh(delta)
        ).clamp(0.0, 1.0)
        if had_history:
            previous_full = self._warp_history(
                previous, guides, rgb.shape[-2:], rgb.shape[-2:], detach=True
            )
            gate = torch.tanh(self.warp_blend_gate(hidden))
            gate = F.interpolate(
                gate, size=rgb.shape[-2:], mode="bilinear", align_corners=False
            ) * self.blend_config.scale
            prediction = (
                prediction + gate * (previous_full - prediction)
            ).clamp(0.0, 1.0)
        return prediction, (hidden, prediction)
