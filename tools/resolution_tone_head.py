"""Grid-resolution ablation, preserving the original tone-head implementation."""
import torch
from torch.nn import functional as F
from spatial_tone_head import SpatialToneHead


class ResolutionToneHead(SpatialToneHead):
    def __init__(self, downsample=16, width=48):
        if downsample not in (4, 16):
            raise ValueError('Only matched quarter/sixteenth grids are supported')
        super().__init__(width=width, spatial=True)
        self.downsample = downsample

    def forward(self, rgb, parent, guides, context):
        size = tuple(max(1, d // self.downsample) for d in parent.shape[-2:])
        features = torch.cat((F.adaptive_avg_pool2d(rgb, size),
            F.adaptive_avg_pool2d(parent, size),
            F.interpolate(guides, size=size, mode='bilinear', align_corners=False),
            F.interpolate(context, size=size, mode='bilinear', align_corners=False)), 1)
        coefficients = self.affine(self.features(features)).float()
        coefficients = F.interpolate(coefficients, size=parent.shape[-2:],
                                     mode='bilinear', align_corners=False)
        n, _, h, w = parent.shape
        matrix = .25 * coefficients[:, :9].tanh().reshape(n, 3, 3, h, w)
        bias = .15 * coefficients[:, 9:].tanh()
        correction = (matrix * parent.float()[:, None]).sum(2) + bias
        return (parent.float() + correction).clamp(0, 1)
