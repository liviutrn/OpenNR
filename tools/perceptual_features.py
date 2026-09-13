"""Frozen ImageNet SqueezeNet features for a training-only perceptual comparison.

This is a normalized feature distance, NOT calibrated LPIPS or a VR quality metric.
Weights come from torchvision's official URL; the student does not embed them.
"""
import torch
from torch import nn
import torch.nn.functional as F

class FeatureDistance(nn.Module):
    def __init__(self):
        super().__init__()
        from torchvision.models import squeezenet1_1,SqueezeNet1_1_Weights
        self.features=squeezenet1_1(weights=SqueezeNet1_1_Weights.IMAGENET1K_V1).features.eval().requires_grad_(False)
        self.register_buffer('mean',torch.tensor([.485,.456,.406])[None,:,None,None]);self.register_buffer('std',torch.tensor([.229,.224,.225])[None,:,None,None])
    def forward(self,pred,target):
        # 256px preserves more local detail than classification center cropping.
        x=(F.interpolate(pred,size=(256,256),mode='bilinear',align_corners=False)-self.mean)/self.std
        y=(F.interpolate(target,size=(256,256),mode='bilinear',align_corners=False)-self.mean)/self.std
        total=0
        for i,layer in enumerate(self.features):
            x=layer(x)
            with torch.no_grad():y=layer(y)
            if i in (3,6,9,12):
                xn=F.normalize(x.float(),dim=1,eps=1e-6);yn=F.normalize(y.float(),dim=1,eps=1e-6)
                total+=(xn-yn).square().sum(1).mean()
        return total/4
