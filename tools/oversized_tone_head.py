"""Large residual U-Net for a training-subset capacity diagnostic."""
import torch
from torch import nn
from torch.nn import functional as F


class ResidualBlock(nn.Module):
    def __init__(self,width):
        super().__init__()
        self.layers=nn.Sequential(nn.Conv2d(width,width,3,padding=1),nn.SiLU(),
                                  nn.Conv2d(width,width,3,padding=1))
    def forward(self,x):
        return x+.1*self.layers(x)


class OversizedToneHead(nn.Module):
    def __init__(self):
        super().__init__()
        widths=(16,32,64,128,256,512)
        self.stem=nn.Sequential(nn.Conv2d(19,16,3,padding=1),nn.SiLU(),ResidualBlock(16))
        self.down=nn.ModuleList([nn.Sequential(nn.Conv2d(a,b,3,stride=2,padding=1),nn.SiLU(),
            ResidualBlock(b),ResidualBlock(b)) for a,b in zip(widths[:-1],widths[1:])])
        self.bottleneck=nn.Sequential(*[ResidualBlock(512) for _ in range(4)])
        self.up=nn.ModuleList([nn.Sequential(nn.Conv2d(a+b,b,3,padding=1),nn.SiLU(),
            ResidualBlock(b),ResidualBlock(b)) for a,b in ((512,256),(256,128),(128,64))])
        self.affine=nn.Conv2d(64,12,1)
        nn.init.zeros_(self.affine.weight);nn.init.zeros_(self.affine.bias)

    def forward(self,rgb,parent,guides,context):
        size=parent.shape[-2:]
        x=torch.cat((rgb,parent,F.interpolate(guides,size=size,mode='bilinear',align_corners=False),
                     F.interpolate(context,size=size,mode='bilinear',align_corners=False)),1)
        levels=[self.stem(x)]
        for layer in self.down:levels.append(layer(levels[-1]))
        x=self.bottleneck(levels[-1])
        for layer,skip in zip(self.up,reversed(levels[2:-1])):
            x=layer(torch.cat((F.interpolate(x,size=skip.shape[-2:],mode='bilinear',align_corners=False),skip),1))
        raw=F.interpolate(self.affine(x).float(),size=size,mode='bilinear',align_corners=False)
        n,_,h,w=parent.shape
        matrix=.25*raw[:,:9].tanh().reshape(n,3,3,h,w);bias=.15*raw[:,9:].tanh()
        return (parent.float()+(matrix*parent.float()[:,None]).sum(2)+bias).clamp(0,1)
