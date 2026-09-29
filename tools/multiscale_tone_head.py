"""Local, coarse-spatial, and crop-global features predict bounded RGB corrections."""
import torch
from torch import nn
from torch.nn import functional as F


class MultiscaleToneHead(nn.Module):
    def __init__(self):
        super().__init__()
        self.local=nn.Sequential(nn.Conv2d(19,48,3,padding=1),nn.SiLU(),
            nn.Conv2d(48,48,3,padding=2,dilation=2),nn.SiLU())
        self.coarse=nn.Sequential(nn.Conv2d(19,32,3,padding=1),nn.SiLU(),
            nn.Conv2d(32,32,3,padding=2,dilation=2),nn.SiLU(),
            nn.Conv2d(32,32,3,padding=4,dilation=4),nn.SiLU())
        self.global_features=nn.Sequential(nn.Conv2d(19,32,1),nn.SiLU(),nn.Conv2d(32,32,1),nn.SiLU())
        self.fusion=nn.Sequential(nn.Conv2d(112,48,3,padding=1),nn.SiLU())
        self.affine=nn.Conv2d(48,12,1)
        nn.init.zeros_(self.affine.weight);nn.init.zeros_(self.affine.bias)

    def forward(self,rgb,parent,guides,context):
        def features(size):
            return torch.cat((F.adaptive_avg_pool2d(rgb,size),F.adaptive_avg_pool2d(parent,size),
                F.interpolate(guides,size=size,mode='bilinear',align_corners=False),
                F.interpolate(context,size=size,mode='bilinear',align_corners=False)),1)
        size=tuple(max(1,d//4) for d in parent.shape[-2:])
        fine=features(size);coarse=features(tuple(max(1,d//32) for d in parent.shape[-2:]))
        local=self.local(fine)
        broad=F.interpolate(self.coarse(coarse),size=size,mode='bilinear',align_corners=False)
        glob=self.global_features(F.adaptive_avg_pool2d(fine,1)).expand(-1,-1,*size)
        raw=self.affine(self.fusion(torch.cat((local,broad,glob),1))).float()
        raw=F.interpolate(raw,size=parent.shape[-2:],mode='bilinear',align_corners=False)
        n,_,h,w=parent.shape
        matrix=.25*raw[:,:9].tanh().reshape(n,3,3,h,w);bias=.15*raw[:,9:].tanh()
        return (parent.float()+(matrix*parent.float()[:,None]).sum(2)+bias).clamp(0,1)
