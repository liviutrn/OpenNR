"""Semantic affine head with a zero-initialized native-resolution residual."""
import torch
from torch import nn
from torch.nn import functional as F
from semantic_tone_head import SemanticToneHead


class SemanticNativeResidualToneHead(SemanticToneHead):
    """Add full-resolution RGB capacity while preserving the affine start exactly."""

    def __init__(self, pretrained=False):
        super().__init__(pretrained=pretrained)
        self.native_residual = nn.Conv2d(64, 48, 3, padding=1)
        nn.init.zeros_(self.native_residual.weight)
        nn.init.zeros_(self.native_residual.bias)

    def forward(self, rgb, parent, guides, context):
        with torch.no_grad():
            image = (F.interpolate(rgb.float(), size=(224, 224), mode='bilinear', align_corners=False)
                     - self.encoder_mean) / self.encoder_std
            semantic = self.encoder.get_intermediate_layers(image, n=1, reshape=True)[0]
        size = parent.shape[-2:]
        x = torch.cat((rgb, parent,
                       F.interpolate(guides, size=size, mode='bilinear', align_corners=False),
                       F.interpolate(context, size=size, mode='bilinear', align_corners=False)), 1)
        levels = [self.stem(x)]
        for layer in self.down:
            levels.append(layer(levels[-1]))
        x = self.bottleneck(levels[-1])
        for layer, skip in zip(self.up, reversed(levels[2:-1])):
            x = layer(torch.cat((F.interpolate(x, size=skip.shape[-2:], mode='bilinear',
                                               align_corners=False), skip), 1))
        x = x + F.interpolate(self.semantic_projection(semantic), size=x.shape[-2:],
                              mode='bilinear', align_corners=False)
        raw = F.interpolate(self.affine(x).float(), size=size, mode='bilinear', align_corners=False)
        n, _, h, w = parent.shape
        matrix = .25 * raw[:, :9].tanh().reshape(n, 3, 3, h, w)
        bias = .15 * raw[:, 9:].tanh()
        affine = (parent.float() + (matrix * parent.float()[:, None]).sum(2) + bias).clamp(0, 1)
        residual = F.pixel_shuffle(self.native_residual(x).float(), 4)
        if residual.shape[-2:] != size:
            residual = F.interpolate(residual, size=size, mode='bilinear', align_corners=False)
        return (affine + .15 * residual.tanh()).clamp(0, 1)

