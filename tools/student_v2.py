"""Detail-preserving reconstruction student; lossless pixel unshuffle input."""
from dataclasses import dataclass
import torch
from torch import nn
import torch.nn.functional as F
from opennr_student import GatedBlock

@dataclass
class ReconstructionConfig:
    width:int=64
    blocks:int=3
    scale:int=4

class ReconstructionStudent(nn.Module):
    def __init__(self,config=ReconstructionConfig()):
        super().__init__();self.config=config;c=config.width;n=config.blocks;s=config.scale
        if s not in (4,8):raise ValueError('Supported packing scales are 4 and 8')
        self.stem=nn.Conv2d(3*s*s+5,c,3,padding=1)
        self.e1=nn.Sequential(*(GatedBlock(c) for _ in range(n)))
        self.d1=nn.Conv2d(c,2*c,2,2);self.e2=nn.Sequential(*(GatedBlock(2*c) for _ in range(n)))
        self.d2=nn.Conv2d(2*c,4*c,2,2);self.mid=nn.Sequential(*(GatedBlock(4*c) for _ in range(n+2)))
        self.context=nn.Sequential(nn.Conv2d(8,32,3,2,1),nn.SiLU(),nn.Conv2d(32,64,3,2,1),nn.SiLU(),nn.AdaptiveAvgPool2d(1),nn.Conv2d(64,8*c,1))
        self.u2=nn.Conv2d(4*c,2*c,1);self.r2=nn.Sequential(*(GatedBlock(2*c) for _ in range(n)))
        self.u1=nn.Conv2d(2*c,c,1);self.r1=nn.Sequential(*(GatedBlock(c) for _ in range(n)))
        self.output=nn.Conv2d(c,3*s*s,3,padding=1)
        nn.init.zeros_(self.output.weight);nn.init.zeros_(self.output.bias)
    def forward(self,rgb,guides,context):
        h,w=rgb.shape[-2:];s=self.config.scale;multiple=4*s;x=F.pad(rgb,(0,(-w)%multiple,0,(-h)%multiple),mode='replicate');x=F.pixel_unshuffle(x,s)
        # Resize guides to the ORIGINAL color domain before padding the learned grid.
        g=F.interpolate(guides,size=((h+s-1)//s,(w+s-1)//s),mode='bilinear',align_corners=False)
        g=F.pad(g,(0,x.shape[-1]-g.shape[-1],0,x.shape[-2]-g.shape[-2]),mode='replicate')
        e1=self.e1(self.stem(torch.cat((x,g),1)));e2=self.e2(self.d1(e1));z=self.d2(e2)
        gain,bias=self.context(context).chunk(2,1);z=self.mid(self.condition(z*(1+.1*torch.tanh(gain))+.1*bias,context))
        z=self.r2(self.u2(F.interpolate(z,size=e2.shape[-2:],mode='bilinear',align_corners=False))+e2)
        z=self.r1(self.u1(F.interpolate(z,size=e1.shape[-2:],mode='bilinear',align_corners=False))+e1)
        # Unbounded learned residual; unlike v1 there is no +/-0.1 residual ceiling.
        return rgb+F.pixel_shuffle(self.output(z),s)[:,:,:h,:w]

    def condition(self,z,context):
        return z

def detail_loss(pred,target,rgb,focus=None,focus_weight=0.,change_scale=3.0):
    err=torch.sqrt((pred-target).square()+1e-6)
    # Training-only target change weighting gives transformed regions more influence.
    if change_scale<0:raise ValueError('Negative target-change loss scale')
    weight=1+float(change_scale)*((target-rgb).abs().mean(1,keepdim=True)/.15).clamp(0,1)
    if focus_weight<0:raise ValueError('Negative focus loss weight')
    if focus is not None:
        if focus.ndim!=4 or focus.shape[0]!=pred.shape[0] or focus.shape[1]!=1 or focus.shape[-2:]!=pred.shape[-2:]:
            raise ValueError('Focus mask must have shape [batch,1,height,width] matching prediction')
        weight=weight+float(focus_weight)*focus.to(dtype=weight.dtype).clamp(0,1)
    pixel=(err*weight).sum()/(3*weight.sum())
    edge=0
    for k in (1,2,4):
        p=F.avg_pool2d(pred,k) if k>1 else pred;t=F.avg_pool2d(target,k) if k>1 else target
        edge+=((p[:,:,:,1:]-p[:,:,:,:-1])-(t[:,:,:,1:]-t[:,:,:,:-1])).abs().mean()
        edge+=((p[:,:,1:,:]-p[:,:,:-1,:])-(t[:,:,1:,:]-t[:,:,:-1,:])).abs().mean()
    coarse=(F.avg_pool2d(pred,8)-F.avg_pool2d(target,8)).abs().mean()
    return pixel+.15*edge/6+.15*coarse
