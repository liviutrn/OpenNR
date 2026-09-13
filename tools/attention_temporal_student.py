"""Local-window attention refinement attached to the v9 temporal student.

This is an independent ablation inspired by public multiscale/local-attention
reconstruction reports.  It is not a recovered DLSS graph.  The branch starts
with a zero output head, operates at the existing 1/4 grid, and consumes only
the captured RGB, Feature-18 guides, whole-eye context, and the current
student prediction.  Its exact v9 function is preserved at initialization.
"""

from __future__ import annotations

from dataclasses import dataclass

import torch
from torch import nn
from torch.nn import functional as F

from opennr_student import GatedBlock
from student_v2 import ReconstructionConfig
from student_v4 import StyleContextStudent
from temporal_student import TemporalConfig, TemporalStyleContextStudent


class WindowAttentionBlock(nn.Module):
    """A compact local-window transformer block with optional Swin shifting."""

    def __init__(self, width: int, heads: int, window: int, shift_size: int = 0) -> None:
        super().__init__()
        if width % heads:
            raise ValueError("Attention width must be divisible by head count")
        if shift_size < 0 or shift_size >= window:
            raise ValueError("Attention shift must be in [0, window)")
        self.width = width
        self.heads = heads
        self.window = window
        self.shift_size = shift_size
        self.norm1 = nn.LayerNorm(width)
        self.qkv = nn.Linear(width, 3 * width)
        self.projection = nn.Linear(width, width)
        self.norm2 = nn.LayerNorm(width)
        self.mlp = nn.Sequential(
            nn.Linear(width, 4 * width),
            nn.GELU(),
            nn.Linear(4 * width, width),
        )

    def forward(self, x):
        batch, channels, height, width = x.shape
        ws = self.window
        pad_h = (-height) % ws
        pad_w = (-width) % ws
        padded = F.pad(x, (0, pad_w, 0, pad_h))
        padded_height, padded_width = padded.shape[-2:]
        if self.shift_size:
            padded = torch.roll(
                padded,
                shifts=(-self.shift_size, -self.shift_size),
                dims=(-2, -1),
            )
        tokens = padded.permute(0, 2, 3, 1)
        windows = (
            tokens.view(
                batch,
                padded_height // ws,
                ws,
                padded_width // ws,
                ws,
                channels,
            )
            .permute(0, 1, 3, 2, 4, 5)
            .reshape(-1, ws * ws, channels)
        )
        qkv = self.qkv(self.norm1(windows))
        qkv = qkv.view(
            qkv.shape[0], qkv.shape[1], 3, self.heads, channels // self.heads
        ).permute(2, 0, 3, 1, 4)
        query, key, value = qkv.unbind(0)
        attention_mask = None
        if self.shift_size:
            # Standard Swin region labels prevent a shifted window from
            # attending across the artificial cyclic boundary introduced by
            # torch.roll.  The mask is tiny (one 8x8 matrix per window) and
            # is rebuilt only for this resolution.
            mask = padded.new_zeros((1, padded_height, padded_width, 1))
            slices_h = (
                slice(0, -ws),
                slice(-ws, -self.shift_size),
                slice(-self.shift_size, None),
            )
            slices_w = (
                slice(0, -ws),
                slice(-ws, -self.shift_size),
                slice(-self.shift_size, None),
            )
            label = 0
            for h_slice in slices_h:
                for w_slice in slices_w:
                    mask[:, h_slice, w_slice, :] = label
                    label += 1
            mask_windows = (
                mask.view(
                    1,
                    padded_height // ws,
                    ws,
                    padded_width // ws,
                    ws,
                    1,
                )
                .permute(0, 1, 3, 2, 4, 5)
                .reshape(-1, ws * ws)
            )
            attention_mask = mask_windows.unsqueeze(1) - mask_windows.unsqueeze(2)
            attention_mask = attention_mask.masked_fill(
                attention_mask != 0, float("-inf")
            )
            attention_mask = attention_mask.repeat(batch, 1, 1)[:, None]
        attended = F.scaled_dot_product_attention(
            query, key, value, attn_mask=attention_mask
        )
        attended = attended.transpose(1, 2).reshape(-1, ws * ws, channels)
        windows = windows + self.projection(attended)
        windows = windows + self.mlp(self.norm2(windows))
        restored = (
            windows.view(
                batch,
                padded_height // ws,
                padded_width // ws,
                ws,
                ws,
                channels,
            )
            .permute(0, 1, 3, 2, 4, 5)
            .reshape(batch, padded_height, padded_width, channels)
        )
        if self.shift_size:
            restored = torch.roll(
                restored,
                shifts=(self.shift_size, self.shift_size),
                dims=(1, 2),
            )
        return restored[:, :height, :width].permute(0, 3, 1, 2).contiguous()


@dataclass
class AttentionConfig:
    width: int = 64
    blocks: int = 3
    heads: int = 4
    window: int = 8
    delta_scale: float = 0.12
    shifted: bool = False
    multi_scale: bool = False


class AttentionTemporalStyleContextStudent(TemporalStyleContextStudent):
    """v9 temporal student plus a zero-initialized local-attention refiner."""

    architecture = "context_v12_attention_temporal"

    def __init__(
        self,
        config: ReconstructionConfig = ReconstructionConfig(),
        temporal: TemporalConfig = TemporalConfig(),
        attention: AttentionConfig = AttentionConfig(),
    ) -> None:
        super().__init__(config, temporal)
        if attention.width < 16:
            raise ValueError("Attention width is too small")
        if attention.blocks < 1:
            raise ValueError("Attention block count must be positive")
        if attention.heads < 1 or attention.width % attention.heads:
            raise ValueError("Attention heads must divide attention width")
        if attention.window < 2:
            raise ValueError("Attention window is too small")
        if attention.delta_scale <= 0:
            raise ValueError("Attention delta scale must be positive")
        self.attention_config = attention
        self.architecture = (
            "context_v13_multiscale_attention_temporal"
            if attention.multi_scale
            else "context_v12_attention_temporal"
        )
        c = attention.width
        self.attention_input = nn.Conv2d(3 + 3 + 5 + 8, c, 3, padding=1)
        self.attention_blocks = nn.Sequential(
            *(
                WindowAttentionBlock(
                    c,
                    attention.heads,
                    attention.window,
                    shift_size=(
                        attention.window // 2
                        if attention.shifted and index % 2
                        else 0
                    ),
                )
                for index in range(attention.blocks)
            )
        )
        if attention.multi_scale:
            # Keep two spatial scales of the whole-eye context instead of
            # flattening it into one pooled style vector.  The 48x48 and
            # 24x24 maps are queried from a 32x32 coarse crop feature map;
            # this supplies broad lighting/material context without creating
            # a 128x128 by 96x96 attention matrix.
            self.attention_pyramid_context0 = nn.Sequential(
                nn.Conv2d(8, c, 3, padding=1),
                nn.SiLU(),
            )
            self.attention_pyramid_context1 = nn.Sequential(
                nn.Conv2d(c, c, 3, stride=2, padding=1),
                nn.SiLU(),
            )
            self.attention_pyramid_context2 = nn.Sequential(
                nn.Conv2d(c, c, 3, stride=2, padding=1),
                nn.SiLU(),
            )
            self.attention_pyramid_query = nn.Conv2d(c, c, 1)
            self.attention_pyramid_key_mid = nn.Conv2d(c, c, 1)
            self.attention_pyramid_key_low = nn.Conv2d(c, c, 1)
            self.attention_pyramid_value_mid = nn.Conv2d(c, c, 1)
            self.attention_pyramid_value_low = nn.Conv2d(c, c, 1)
            self.attention_pyramid_post = nn.Sequential(
                GatedBlock(c),
                GatedBlock(c),
            )
        self.attention_output = nn.Conv2d(c, 3 * 4 * 4, 3, padding=1)
        nn.init.zeros_(self.attention_output.weight)
        nn.init.zeros_(self.attention_output.bias)

    def initialize_v5(self, state: dict[str, torch.Tensor]) -> None:
        """Load v9 weights and require only attention keys to be new."""

        incompatible = self.load_state_dict(state, strict=False)
        if incompatible.unexpected_keys:
            raise ValueError(f"Unexpected parent keys: {incompatible.unexpected_keys}")
        invalid_missing = [
            key for key in incompatible.missing_keys
            if not key.startswith("attention_")
        ]
        if invalid_missing:
            raise ValueError(f"Non-attention parent keys are missing: {invalid_missing}")

    def _attention_residual(self, rgb, prediction, guides, context):
        height, width = rgb.shape[-2:]
        size = ((height + 3) // 4, (width + 3) // 4)
        features = torch.cat(
            (
                F.interpolate(rgb, size=size, mode="area"),
                F.interpolate(prediction.detach(), size=size, mode="area"),
                F.interpolate(guides, size=size, mode="bilinear", align_corners=False),
                F.interpolate(context, size=size, mode="bilinear", align_corners=False),
            ),
            dim=1,
        )
        features = self.attention_blocks(self.attention_input(features))
        if self.attention_config.multi_scale:
            features = self._multi_scale_context(features, context)
        residual = F.pixel_shuffle(self.attention_output(features), 4)
        if residual.shape[-2:] != (height, width):
            residual = F.interpolate(
                residual, size=(height, width), mode="bilinear", align_corners=False
            )
        return residual

    def _multi_scale_context(self, features, context):
        """Fuse medium/coarse whole-eye tokens into local quarter-grid features."""

        batch, channels, height, width = features.shape
        heads = self.attention_config.heads
        head_dim = channels // heads
        context0 = self.attention_pyramid_context0(context)
        context_mid = self.attention_pyramid_context1(context0)
        context_low = self.attention_pyramid_context2(context_mid)

        query_size = (max(1, (height + 3) // 4), max(1, (width + 3) // 4))
        query_source = F.adaptive_avg_pool2d(features, query_size)
        query = self.attention_pyramid_query(query_source)
        query = query.flatten(2).transpose(1, 2)
        query = query.view(batch, -1, heads, head_dim).permute(0, 2, 1, 3)

        mid_key = self.attention_pyramid_key_mid(context_mid)
        low_key = self.attention_pyramid_key_low(context_low)
        key = torch.cat(
            (
                mid_key.flatten(2).transpose(1, 2),
                low_key.flatten(2).transpose(1, 2),
            ),
            dim=1,
        )
        key = key.view(batch, -1, heads, head_dim).permute(0, 2, 1, 3)

        mid_value = self.attention_pyramid_value_mid(context_mid)
        low_value = self.attention_pyramid_value_low(context_low)
        value = torch.cat(
            (
                mid_value.flatten(2).transpose(1, 2),
                low_value.flatten(2).transpose(1, 2),
            ),
            dim=1,
        )
        value = value.view(batch, -1, heads, head_dim).permute(0, 2, 1, 3)
        attended = F.scaled_dot_product_attention(query, key, value)
        attended = attended.transpose(1, 2).reshape(
            batch, channels, query_size[0], query_size[1]
        )
        attended = F.interpolate(
            attended, size=(height, width), mode="bilinear", align_corners=False
        )
        return self.attention_pyramid_post(features + attended)

    def _refine(self, prediction, rgb, guides, context):
        residual = self._attention_residual(rgb, prediction, guides, context)
        return (
            prediction + self.attention_config.delta_scale * torch.tanh(residual)
        ).clamp(0.0, 1.0)

    def forward_temporal(self, rgb, guides, context, state=None):
        prediction, next_state = super().forward_temporal(
            rgb, guides, context, state
        )
        prediction = self._refine(prediction, rgb, guides, context)
        return prediction, (next_state[0], prediction)

    def forward(self, rgb, guides, context):
        return StyleContextStudent.forward(self, rgb, guides, context)
