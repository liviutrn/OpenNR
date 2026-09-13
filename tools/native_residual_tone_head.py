"""Native-resolution residual ablation on the verified stable affine U-Net."""
import torch
from torch import nn
from torch.nn import functional as F
from stable_oversized_tone_head import StableOversizedToneHead


class NativeResidualToneHead(StableOversizedToneHead):
    def __init__(self):
        super().__init__()
        self.native_residual = nn.Conv2d(64, 48, 3, padding=1)
        nn.init.zeros_(self.native_residual.weight)
        nn.init.zeros_(self.native_residual.bias)

    def forward(self, rgb, parent, guides, context):
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
        raw = F.interpolate(self.affine(x).float(), size=size, mode='bilinear', align_corners=False)
        n, _, h, w = parent.shape
        matrix = .25 * raw[:, :9].tanh().reshape(n, 3, 3, h, w)
        bias = .15 * raw[:, 9:].tanh()
        affine = (parent.float() + (matrix * parent.float()[:, None]).sum(2) + bias).clamp(0, 1)
        residual = F.pixel_shuffle(self.native_residual(x).float(), 4)
        if residual.shape[-2:] != size:
            residual = F.interpolate(residual, size=size, mode='bilinear', align_corners=False)
        return (affine + .15 * residual.tanh()).clamp(0, 1)


def load_warm_head(path, native=False, device='cuda'):
    payload = torch.load(path, map_location='cpu', weights_only=False)
    if payload['run']['architecture'] != 'stable_unet':
        raise ValueError('Expected plain stable U-Net warm start')
    head = (NativeResidualToneHead() if native else StableOversizedToneHead()).to(device)
    result = head.load_state_dict(payload['head'], strict=not native)
    if native and (result.unexpected_keys or set(result.missing_keys) !=
                   {'native_residual.weight', 'native_residual.bias'}):
        raise ValueError('Warm-start identity mismatch')
    return head, payload
