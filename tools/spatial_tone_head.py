"""Identity-initialized local RGB affine head; no teacher inputs at inference."""
import torch
from torch import nn
from torch.nn import functional as F


class SpatialToneHead(nn.Module):
    def __init__(self,width=48,spatial=True):
        super().__init__()
        self.spatial=spatial
        # Avoid normalization that removes absolute color/brightness information.
        self.features=nn.Sequential(nn.Conv2d(19,width,3,padding=1),nn.SiLU(),
            nn.Conv2d(width,width,3,padding=2,dilation=2),nn.SiLU(),
            nn.Conv2d(width,width,3,padding=4,dilation=4),nn.SiLU())
        self.affine=nn.Conv2d(width,12,1)
        nn.init.zeros_(self.affine.weight);nn.init.zeros_(self.affine.bias)

    def forward(self,rgb,parent,guides,context):
        size=(max(1,parent.shape[-2]//16),max(1,parent.shape[-1]//16))
        features=torch.cat((F.adaptive_avg_pool2d(rgb,size),F.adaptive_avg_pool2d(parent,size),
            F.interpolate(guides,size=size,mode='bilinear',align_corners=False),
            F.interpolate(context,size=size,mode='bilinear',align_corners=False)),1)
        coefficients=self.affine(self.features(features)).float()
        if not self.spatial:coefficients=coefficients.mean((-2,-1),keepdim=True)
        coefficients=F.interpolate(coefficients,size=parent.shape[-2:],mode='bilinear',align_corners=False)
        n,_,h,w=parent.shape
        matrix=.25*coefficients[:,:9].tanh().reshape(n,3,3,h,w)
        bias=.15*coefficients[:,9:].tanh()
        correction=(matrix*parent.float()[:,None]).sum(2)+bias
        return (parent.float()+correction).clamp(0,1)


class FrozenParentToneModel(nn.Module):
    """Return original parent state: the tone head does not alter causal feedback."""
    def __init__(self,parent,head):
        super().__init__()
        self.parent=parent.eval().requires_grad_(False)
        self.head=head

    def train(self,mode=True):
        super().train(mode)
        self.parent.eval()
        return self

    def forward_temporal(self,rgb,guides,context,state=None):
        with torch.no_grad():base,next_state=self.parent.forward_temporal(rgb,guides,context,state)
        return self.head(rgb,base,guides,context),next_state
