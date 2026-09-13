"""Chroma-preserving luminance-gain branch for a bounded OpenNR ablation.

The head keeps the existing stable U-Net body, warm-start RGB-affine output and
input contract, then adds one zero-initialized luminance-gain branch. At step
zero it is exactly the verified warm head. The new branch applies a bounded
gain to the warm head's RGB ratios, so it cannot invent a hue shift as a side
effect of fixing broad brightness.
This is an offline research model; it is not a runtime replacement.
"""

import torch
from torch import nn
from torch.nn import functional as F

from stable_oversized_tone_head import StableOversizedToneHead


class ChromaPreservingLumaToneHead(StableOversizedToneHead):
    """Warm stable U-Net plus a zero-initialized chroma-preserving luma branch."""

    LUMA_WEIGHTS = (0.2126, 0.7152, 0.0722)

    def __init__(self):
        super().__init__()
        self.luma_affine = nn.Conv2d(
            self.affine.in_channels,
            1,
            self.affine.kernel_size,
            stride=self.affine.stride,
            padding=self.affine.padding,
            dilation=self.affine.dilation,
            groups=self.affine.groups,
            bias=True,
            device=self.affine.weight.device,
            dtype=self.affine.weight.dtype,
        )
        nn.init.zeros_(self.luma_affine.weight)
        nn.init.zeros_(self.luma_affine.bias)
        # The trainer enables this only for the step-zero replay. Keeping the
        # gate explicit preserves an exact warm-start replay without cutting
        # the luma branch out of the autograd graph during optimization.
        self.exact_zero_bypass = True

    def _features(self, rgb, parent, guides, context):
        size = parent.shape[-2:]
        x = torch.cat(
            (
                rgb,
                parent,
                F.interpolate(guides, size=size, mode="bilinear", align_corners=False),
                F.interpolate(context, size=size, mode="bilinear", align_corners=False),
            ),
            1,
        )
        levels = [self.stem(x)]
        for layer in self.down:
            levels.append(layer(levels[-1]))
        x = self.bottleneck(levels[-1])
        for layer, skip in zip(self.up, reversed(levels[2:-1])):
            x = layer(
                torch.cat(
                    (
                        F.interpolate(x, size=skip.shape[-2:], mode="bilinear", align_corners=False),
                        skip,
                    ),
                    1,
                )
            )
        return (
            F.interpolate(self.affine(x).float(), size=size, mode="bilinear", align_corners=False),
            F.interpolate(self.luma_affine(x).float(), size=size, mode="bilinear", align_corners=False),
        )

    def forward(self, rgb, parent, guides, context, conditioning=None):
        del conditioning
        raw, luma_raw = self._features(rgb, parent, guides, context)
        n, _, h, w = parent.shape
        matrix = 0.25 * raw[:, :9].tanh().reshape(n, 3, 3, h, w)
        bias = 0.15 * raw[:, 9:].tanh()
        base = (parent.float() + (matrix * parent.float()[:, None]).sum(2) + bias).clamp(0, 1)
        if self.exact_zero_bypass:
            return base
        gain_delta = 0.5 * luma_raw.tanh()
        weights = parent.new_tensor(self.LUMA_WEIGHTS).reshape(1, 3, 1, 1)
        luma = (base * weights).sum(1, keepdim=True)
        target_luma = luma * (1.0 + gain_delta)
        ratio = torch.where(
            luma > 1e-4,
            target_luma / luma.clamp_min(1e-4),
            torch.ones_like(luma),
        )
        return (base * ratio).clamp(0.0, 1.0)
