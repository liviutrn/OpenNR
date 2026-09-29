"""Frozen DINOv2 spatial features condition a warm stable affine U-Net.

Random-encoder and pretrained-encoder arms share architecture and zero initial
conditioning. Teacher pixels never enter the encoder or inference features.
"""
from pathlib import Path
import sys
import torch
from torch import nn
from torch.nn import functional as F
from stable_oversized_tone_head import StableOversizedToneHead
from prepare_conditioning_pilot import sha

ENCODER_SOURCE = Path(r'C:\Users\oleks\.cache\torch\hub\facebookresearch_dinov2_main')
ENCODER_WEIGHTS = Path(r'C:\Users\oleks\.cache\torch\hub\checkpoints\dinov2_vits14_pretrain.pth')


def encoder_provenance():
    return {'source': str(ENCODER_SOURCE), 'weights': str(ENCODER_WEIGHTS),
            'weights_sha256': sha(ENCODER_WEIGHTS),
            'source_sha256': {str(p.relative_to(ENCODER_SOURCE)): sha(p)
                              for p in sorted((ENCODER_SOURCE / 'dinov2').rglob('*.py'))},
            'input': 'current input RGB only, resized224 bilinear and ImageNet mean/std',
            'features': 'final normalized patch tokens, 384 channels at16x16',
            'frozen': True}


class SemanticToneHead(StableOversizedToneHead):
    def __init__(self, pretrained=False):
        super().__init__()
        if str(ENCODER_SOURCE) not in sys.path:
            sys.path.insert(0, str(ENCODER_SOURCE))
        from dinov2.hub.backbones import dinov2_vits14
        self.encoder = dinov2_vits14(pretrained=False)
        if pretrained:
            self.encoder.load_state_dict(torch.load(ENCODER_WEIGHTS, map_location='cpu', weights_only=True), strict=True)
        self.encoder.eval().requires_grad_(False)
        self.semantic_projection = nn.Conv2d(384, 64, 1)
        nn.init.zeros_(self.semantic_projection.weight)
        nn.init.zeros_(self.semantic_projection.bias)
        self.register_buffer('encoder_mean', torch.tensor([.485, .456, .406])[None, :, None, None])
        self.register_buffer('encoder_std', torch.tensor([.229, .224, .225])[None, :, None, None])

    def train(self, mode=True):
        super().train(mode)
        self.encoder.eval()
        return self

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
            x = layer(torch.cat((F.interpolate(x, size=skip.shape[-2:], mode='bilinear', align_corners=False), skip), 1))
        x = x + F.interpolate(self.semantic_projection(semantic), size=x.shape[-2:], mode='bilinear', align_corners=False)
        raw = F.interpolate(self.affine(x).float(), size=size, mode='bilinear', align_corners=False)
        n, _, h, w = parent.shape
        matrix = .25 * raw[:, :9].tanh().reshape(n, 3, 3, h, w)
        bias = .15 * raw[:, 9:].tanh()
        return (parent.float() + (matrix * parent.float()[:, None]).sum(2) + bias).clamp(0, 1)


def load_semantic_warm_head(path, pretrained=False, device='cuda'):
    payload = torch.load(path, map_location='cpu', weights_only=False)
    if payload['run']['architecture'] != 'stable_unet':
        raise ValueError('Expected plain stable U-Net warm start')
    head = SemanticToneHead(pretrained).to(device)
    result = head.load_state_dict(payload['head'], strict=False)
    if result.unexpected_keys or any(not (k.startswith(('encoder.', 'semantic_projection.')) or
                                         k in ('encoder_mean', 'encoder_std')) for k in result.missing_keys):
        raise ValueError('Semantic warm-start identity mismatch')
    return head, payload
