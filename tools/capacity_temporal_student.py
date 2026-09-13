"""High-capacity appearance branch attached to the v9 causal student."""

from __future__ import annotations

from dataclasses import dataclass

import torch
from torch import nn
from torch.nn import functional as F

from capacity_student import CapacityConfig
from opennr_student import GatedBlock
from student_v2 import ReconstructionConfig
from temporal_student import TemporalConfig, TemporalStyleContextStudent


class CapacityTemporalStyleContextStudent(TemporalStyleContextStudent):
    """v9 temporal student plus a zero-initialized quarter-resolution refiner."""

    architecture = "context_v7_capacity_temporal"

    def __init__(
        self,
        config: ReconstructionConfig = ReconstructionConfig(),
        temporal: TemporalConfig = TemporalConfig(),
        capacity: CapacityConfig = CapacityConfig(),
    ) -> None:
        super().__init__(config, temporal)
        if capacity.width < 32:
            raise ValueError("Capacity width is too small")
        if capacity.blocks < 1:
            raise ValueError("Capacity block count must be positive")
        if capacity.delta_scale <= 0:
            raise ValueError("Capacity delta scale must be positive")
        if capacity.extra_width < 0 or capacity.extra_blocks < 0:
            raise ValueError("Extra capacity dimensions cannot be negative")
        if (capacity.extra_width == 0) != (capacity.extra_blocks == 0):
            raise ValueError("Extra capacity width and blocks must be enabled together")
        if capacity.extra_blocks and capacity.extra_width < 32:
            raise ValueError("Extra capacity width is too small")
        if not 0.0 < capacity.residual_gate_scale <= 1.0:
            raise ValueError("Residual gate scale must be in (0, 1]")
        if not 0.0 < capacity.final_gate_scale <= 1.0:
            raise ValueError("Final gate scale must be in (0, 1]")
        self.capacity_config = capacity
        c = capacity.width
        self.capacity_context = nn.Sequential(
            nn.Conv2d(8, 64, 3, padding=1),
            nn.SiLU(),
            nn.Conv2d(64, 32, 3, padding=1),
            nn.SiLU(),
        )
        self.capacity_input = nn.Conv2d(3 + 3 + 5 + 32, c, 3, padding=1)
        self.capacity_blocks = nn.Sequential(*(GatedBlock(c) for _ in range(capacity.blocks)))
        self.capacity_style_modulation = bool(capacity.style_modulation)
        if self.capacity_style_modulation:
            # ChannelNorm inside GatedBlock removes much of the absolute
            # activation level. Explicitly expose a global context-derived
            # affine at the branch entrance and exit so lighting/material
            # style can condition the residual without changing the parent
            # function at initialization.
            self.capacity_style = nn.Linear(32, 4 * c)
            nn.init.zeros_(self.capacity_style.weight)
            nn.init.zeros_(self.capacity_style.bias)
        self.capacity_output = nn.Conv2d(c, 3 * 4 * 4, 3, padding=1)
        nn.init.zeros_(self.capacity_output.weight)
        nn.init.zeros_(self.capacity_output.bias)
        self.capacity_residual_gate = bool(capacity.residual_gate)
        if self.capacity_residual_gate:
            # Pixel-shuffled one-channel gate gives native-resolution control.
            # Zero output means 1 + scale*tanh(0) == 1 exactly.
            self.capacity_gate = nn.Conv2d(c, 4 * 4, 3, padding=1)
            nn.init.zeros_(self.capacity_gate.weight)
            nn.init.zeros_(self.capacity_gate.bias)
        self.final_gate_enabled = bool(capacity.final_gate)
        if self.final_gate_enabled:
            # This gate sees the same conditioned capacity features as the
            # residual branch but modulates the complete correction at native
            # resolution, including inherited spatial/temporal output.
            self.capacity_final_gate = nn.Conv2d(c, 4 * 4, 3, padding=1)
            nn.init.zeros_(self.capacity_final_gate.weight)
            nn.init.zeros_(self.capacity_final_gate.bias)
        self.extra_capacity_enabled = bool(capacity.extra_blocks)
        if self.extra_capacity_enabled:
            extra = capacity.extra_width
            self.capacity_extra_context = nn.Sequential(
                nn.Conv2d(8, 64, 3, padding=1),
                nn.SiLU(),
                nn.Conv2d(64, 32, 3, padding=1),
                nn.SiLU(),
            )
            self.capacity_extra_input = nn.Conv2d(3 + 3 + 5 + 32, extra, 3, padding=1)
            self.capacity_extra_blocks = nn.Sequential(
                *(GatedBlock(extra) for _ in range(capacity.extra_blocks))
            )
            self.capacity_extra_output = nn.Conv2d(extra, 3 * 4 * 4, 3, padding=1)
            # The second branch is a strict continuation: it contributes zero
            # until its own output head learns a residual.
            nn.init.zeros_(self.capacity_extra_output.weight)
            nn.init.zeros_(self.capacity_extra_output.bias)
            if self.capacity_residual_gate:
                self.capacity_extra_gate = nn.Conv2d(extra, 4 * 4, 3, padding=1)
                nn.init.zeros_(self.capacity_extra_gate.weight)
                nn.init.zeros_(self.capacity_extra_gate.bias)

    def initialize_v5(
        self,
        state: dict[str, torch.Tensor],
        zero_init_missing_blocks: bool = False,
    ) -> None:
        """Load a temporal parent, allowing a deliberately wider capacity branch.

        Base and temporal tensors must remain shape-compatible. Capacity tensors
        may be skipped when a continuation increases branch width/depth; new
        capacity output heads are zero-initialized, preserving the inherited
        base/temporal function at step 0 while the wider branch learns. A
        learned capacity residual whose shape is skipped is intentionally not
        preserved and is recorded in ``parent_shape_skips``. When
        ``zero_init_missing_blocks`` is enabled for a same-width depth
        expansion, missing block residual scales are set to zero so newly
        appended blocks are exact identity mappings at initialization.
        """

        current = self.state_dict()
        compatible = {
            key: value
            for key, value in state.items()
            if key in current and current[key].shape == value.shape
        }
        skipped = sorted(set(state) - set(compatible))
        invalid_skipped = [key for key in skipped if not key.startswith("capacity_")]
        if invalid_skipped:
            raise ValueError(f"Non-capacity parent keys are shape-incompatible: {invalid_skipped}")
        incompatible = self.load_state_dict(compatible, strict=False)
        if incompatible.unexpected_keys:
            raise ValueError(f"Unexpected parent keys: {incompatible.unexpected_keys}")
        invalid_missing = [
            key for key in incompatible.missing_keys if not key.startswith("capacity_")
        ]
        if invalid_missing:
            raise ValueError(f"Non-capacity parent keys are missing: {invalid_missing}")
        self.parent_shape_skips = skipped
        self.zero_initialized_missing_capacity_gammas = []
        if zero_init_missing_blocks:
            missing = set(incompatible.missing_keys)
            for prefix, blocks in (
                ("capacity_blocks", self.capacity_blocks),
                (
                    "capacity_extra_blocks",
                    getattr(self, "capacity_extra_blocks", None),
                ),
            ):
                if blocks is None:
                    continue
                for index, block in enumerate(blocks):
                    key = f"{prefix}.{index}.gamma"
                    if key in missing:
                        nn.init.zeros_(block.gamma)
                        self.zero_initialized_missing_capacity_gammas.append(key)

    def initialize_base_temporal(self, state: dict[str, torch.Tensor]) -> None:
        """Load only the inherited base/temporal function from a parent.

        This is used for controlled capacity-width experiments. Every
        ``capacity_*`` tensor is deliberately left at the deterministic
        constructor initialization of the new model, while all base and
        temporal tensors must load with matching shapes. Because the capacity
        output heads are zero-initialized, the child starts as the same
        base/temporal function for every tested width.
        """

        current = self.state_dict()
        compatible = {
            key: value
            for key, value in state.items()
            if not key.startswith("capacity_")
            and key in current
            and current[key].shape == value.shape
        }
        skipped = sorted(set(state) - set(compatible))
        invalid_skipped = [key for key in skipped if not key.startswith("capacity_")]
        if invalid_skipped:
            raise ValueError(
                "Non-capacity parent keys are shape-incompatible or unexpected: "
                f"{invalid_skipped}"
            )
        incompatible = self.load_state_dict(compatible, strict=False)
        if incompatible.unexpected_keys:
            raise ValueError(f"Unexpected parent keys: {incompatible.unexpected_keys}")
        invalid_missing = [
            key for key in incompatible.missing_keys if not key.startswith("capacity_")
        ]
        if invalid_missing:
            raise ValueError(f"Non-capacity parent keys are missing: {invalid_missing}")
        self.parent_shape_skips = skipped

    def _capacity_residual(self, rgb, base, guides, context, return_features=False):
        h, w = rgb.shape[-2:]
        size = ((h + 3) // 4, (w + 3) // 4)
        context_features = F.interpolate(
            self.capacity_context(context), size=size, mode="bilinear", align_corners=False
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
        if self.capacity_style_modulation:
            style = self.capacity_style(context_features.mean(dim=(2, 3)))
            in_scale, in_bias, out_scale, out_bias = style.chunk(4, dim=1)
            in_scale = 0.1 * torch.tanh(in_scale)[:, :, None, None]
            in_bias = 0.1 * torch.tanh(in_bias)[:, :, None, None]
            features = features * (1.0 + in_scale) + in_bias
        features = self.capacity_blocks(features)
        if self.capacity_style_modulation:
            out_scale = 0.1 * torch.tanh(out_scale)[:, :, None, None]
            out_bias = 0.1 * torch.tanh(out_bias)[:, :, None, None]
            features = features * (1.0 + out_scale) + out_bias
        residual = F.pixel_shuffle(self.capacity_output(features), 4)
        if residual.shape[-2:] != (h, w):
            residual = F.interpolate(residual, size=(h, w), mode="bilinear", align_corners=False)
        if self.capacity_residual_gate:
            gate = F.pixel_shuffle(self.capacity_gate(features), 4)
            if gate.shape[-2:] != (h, w):
                gate = F.interpolate(gate, size=(h, w), mode="bilinear", align_corners=False)
            gate = 1.0 + self.capacity_config.residual_gate_scale * torch.tanh(gate)
            residual = residual * gate
        if return_features:
            return residual, features
        return residual

    def _final_gate(self, features, size):
        h, w = size
        gate = F.pixel_shuffle(self.capacity_final_gate(features), 4)
        if gate.shape[-2:] != (h, w):
            gate = F.interpolate(gate, size=(h, w), mode="bilinear", align_corners=False)
        return 1.0 + self.capacity_config.final_gate_scale * torch.tanh(gate)

    def _extra_capacity_residual(self, rgb, base, guides, context):
        if not self.extra_capacity_enabled:
            return torch.zeros_like(rgb)
        h, w = rgb.shape[-2:]
        size = ((h + 3) // 4, (w + 3) // 4)
        context_features = F.interpolate(
            self.capacity_extra_context(context), size=size, mode="bilinear", align_corners=False
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
        features = self.capacity_extra_blocks(self.capacity_extra_input(features))
        residual = F.pixel_shuffle(self.capacity_extra_output(features), 4)
        if residual.shape[-2:] != (h, w):
            residual = F.interpolate(residual, size=(h, w), mode="bilinear", align_corners=False)
        if self.capacity_residual_gate:
            gate = F.pixel_shuffle(self.capacity_extra_gate(features), 4)
            if gate.shape[-2:] != (h, w):
                gate = F.interpolate(gate, size=(h, w), mode="bilinear", align_corners=False)
            gate = 1.0 + self.capacity_config.residual_gate_scale * torch.tanh(gate)
            residual = residual * gate
        return residual

    def forward_temporal(self, rgb, guides, context, state=None):
        prediction, next_state = super().forward_temporal(rgb, guides, context, state)
        if self.final_gate_enabled:
            residual, gate_features = self._capacity_residual(
                rgb, prediction, guides, context, return_features=True
            )
        else:
            residual = self._capacity_residual(rgb, prediction, guides, context)
            gate_features = None
        prediction = (
            prediction + self.capacity_config.delta_scale * torch.tanh(residual)
        ).clamp(0.0, 1.0)
        extra_residual = self._extra_capacity_residual(rgb, prediction, guides, context)
        prediction = (
            prediction + self.capacity_config.delta_scale * torch.tanh(extra_residual)
        ).clamp(0.0, 1.0)
        if self.final_gate_enabled:
            prediction = rgb + self._final_gate(gate_features, rgb.shape[-2:]) * (prediction - rgb)
            prediction = prediction.clamp(0.0, 1.0)
        # Carry the refined output so the existing temporal branch sees the
        # same prediction that was delivered to the previous frame.
        return prediction, (next_state[0], prediction)

    def forward(self, rgb, guides, context):
        prediction = super().forward(rgb, guides, context)
        if self.final_gate_enabled:
            residual, gate_features = self._capacity_residual(
                rgb, prediction, guides, context, return_features=True
            )
        else:
            residual = self._capacity_residual(rgb, prediction, guides, context)
            gate_features = None
        prediction = (
            prediction + self.capacity_config.delta_scale * torch.tanh(residual)
        ).clamp(0.0, 1.0)
        if self.final_gate_enabled:
            prediction = rgb + self._final_gate(gate_features, rgb.shape[-2:]) * (prediction - rgb)
        return prediction.clamp(0.0, 1.0)
