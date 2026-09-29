"""Full-patch frozen VGG LPIPS supervision; AlexNet remains evaluation-only."""
import importlib.metadata
import torch
from torch import nn


class VGGAppearanceLoss(nn.Module):
    def __init__(self):
        super().__init__()
        import lpips
        self.metric=lpips.LPIPS(net='vgg',version='0.1').eval().requires_grad_(False)
        self.provenance=dict(network='LPIPS VGG v0.1',package_version=importlib.metadata.version('lpips'),backbone='torchvision ImageNet pretrained VGG16',resolution='Full training patch, no resize',normalization='Clamp displayed RGB to [0,1], then map to [-1,1]',role='Training only; not embedded in student or used as independent acceptance')

    def forward(self,pred,target):
        return self.metric(pred.float().clamp(0,1)*2-1,target.float()*2-1).mean()
