"""OpenNR spatial student: multiscale gated features and native-resolution detail.

Learned processing runs on a quarter-resolution grid. Whole-eye context conditions
the bottleneck, while local gain, bias, and detail coefficients modify native RGB.
This has no temporal state, inferred optical flow, or trained binocular fusion.
"""
from dataclasses import dataclass,asdict
import torch
from torch import nn
import torch.nn.functional as F

@dataclass
class StudentConfig:
    width:int=32
    guided:bool=True
    blocks:int=2
    scale:int=4

class ChannelNorm(nn.Module):
    def __init__(self,c):
        super().__init__();self.weight=nn.Parameter(torch.ones(1,c,1,1));self.bias=nn.Parameter(torch.zeros(1,c,1,1))
    def forward(self,x):
        mean=x.mean(1,keepdim=True);var=(x-mean).square().mean(1,keepdim=True)
        return (x-mean)*torch.rsqrt(var+1e-5)*self.weight+self.bias

class GatedBlock(nn.Module):
    def __init__(self,c):
        super().__init__();self.norm=ChannelNorm(c);self.expand=nn.Conv2d(c,2*c,1);self.spatial=nn.Conv2d(2*c,2*c,5,padding=2,groups=2*c);self.project=nn.Conv2d(c,c,1);self.gamma=nn.Parameter(torch.full((1,c,1,1),.1))
    def forward(self,x):
        a,b=self.spatial(self.expand(self.norm(x))).chunk(2,1)
        return x+self.gamma*self.project(a*torch.sigmoid(b))

class OpenNRStudent(nn.Module):
    def __init__(self,config=StudentConfig()):
        super().__init__();self.config=config;c=config.width;n=config.blocks;cin=8 if config.guided else 3
        self.stem=nn.Conv2d(cin,c,3,padding=1)
        self.enc1=nn.Sequential(*(GatedBlock(c) for _ in range(n)))
        self.down1=nn.Conv2d(c,2*c,2,stride=2)
        self.enc2=nn.Sequential(*(GatedBlock(2*c) for _ in range(n)))
        self.down2=nn.Conv2d(2*c,4*c,2,stride=2)
        self.middle=nn.Sequential(*(GatedBlock(4*c) for _ in range(n+1)))
        self.context=nn.Sequential(nn.Conv2d(cin,16,5,stride=2,padding=2),nn.SiLU(),nn.Conv2d(16,32,3,stride=2,padding=1),nn.SiLU(),nn.Conv2d(32,48,3,stride=2,padding=1),nn.SiLU(),nn.AdaptiveAvgPool2d(1),nn.Conv2d(48,8*c,1))
        self.up2=nn.Conv2d(4*c,2*c,1);self.dec2=nn.Sequential(*(GatedBlock(2*c) for _ in range(n)))
        self.up1=nn.Conv2d(2*c,c,1);self.dec1=nn.Sequential(*(GatedBlock(c) for _ in range(n)))
        self.head=nn.Conv2d(c,9,3,padding=1)
        self.reconstruct=nn.Sequential(nn.Conv2d(c,3*config.scale*config.scale,3,padding=1),nn.PixelShuffle(config.scale))
        nn.init.zeros_(self.head.weight);nn.init.zeros_(self.head.bias)
        nn.init.zeros_(self.reconstruct[0].weight);nn.init.zeros_(self.reconstruct[0].bias)
    def forward(self,rgb,guides,context):
        h,w=rgb.shape[-2:];size=(max(4,h//self.config.scale),max(4,w//self.config.scale))
        low=F.interpolate(rgb,size=size,mode='bilinear',align_corners=False)
        if self.config.guided:
            g=F.interpolate(guides,size=size,mode='bilinear',align_corners=False)
            low=torch.cat((low,g),1)
        else: context=context[:,:3]
        # Pad only the low-resolution learned grid; original RGB stays native.
        ph=(-size[0])%4;pw=(-size[1])%4
        low=F.pad(low,(0,pw,0,ph),mode='replicate')
        e1=self.enc1(self.stem(low));e2=self.enc2(self.down1(e1));z=self.down2(e2)
        gain,bias=self.context(context).chunk(2,1);z=z*(1+.1*torch.tanh(gain))+.1*bias
        z=self.middle(z)
        z=self.dec2(self.up2(F.interpolate(z,size=e2.shape[-2:],mode='bilinear',align_corners=False))+e2)
        z=self.dec1(self.up1(F.interpolate(z,size=e1.shape[-2:],mode='bilinear',align_corners=False))+e1)
        coef=self.head(z)[:,:,:size[0],:size[1]]
        residual=self.reconstruct(z)[:,:,:size[0]*self.config.scale,:size[1]*self.config.scale]
        if residual.shape[-2:]!=(h,w):residual=F.interpolate(residual,size=(h,w),mode='bilinear',align_corners=False)
        coef=F.interpolate(coef,size=(h,w),mode='bilinear',align_corners=False)
        gain,bias,detail=coef.chunk(3,1)
        # Native RGB skip preserves fine structures absent from the learned grid.
        high=rgb-F.avg_pool2d(F.pad(rgb,(2,2,2,2),mode='replicate'),5,stride=1)
        return (rgb*(1+.5*torch.tanh(gain))+.25*torch.tanh(bias)+.5*torch.tanh(detail)*high+.1*torch.tanh(residual)).clamp(0,1)

def load_student(path,device='cpu'):
    ckpt=torch.load(path,map_location=device,weights_only=False)
    if ckpt.get('architecture') in ('context_v12_attention_temporal','context_v13_multiscale_attention_temporal'):
        from attention_temporal_student import AttentionConfig,AttentionTemporalStyleContextStudent
        from student_v2 import ReconstructionConfig
        from temporal_student import TemporalConfig
        model=AttentionTemporalStyleContextStudent(ReconstructionConfig(**ckpt['base_config']),TemporalConfig(**ckpt['temporal_config']),AttentionConfig(**ckpt['attention_config'])).to(device)
    elif ckpt.get('architecture')=='context_v11_warp_blend_temporal':
        from warp_temporal_student import BlendConfig,MotionWarpBlendTemporalStyleContextStudent
        from student_v2 import ReconstructionConfig
        from temporal_student import TemporalConfig
        model=MotionWarpBlendTemporalStyleContextStudent(ReconstructionConfig(**ckpt['base_config']),TemporalConfig(**ckpt['temporal_config']),BlendConfig(**ckpt['blend_config'])).to(device)
    elif ckpt.get('architecture')=='context_v10_warp_temporal':
        from warp_temporal_student import MotionWarpTemporalStyleContextStudent
        from student_v2 import ReconstructionConfig
        from temporal_student import TemporalConfig
        model=MotionWarpTemporalStyleContextStudent(ReconstructionConfig(**ckpt['base_config']),TemporalConfig(**ckpt['temporal_config'])).to(device)
    elif ckpt.get('architecture')=='context_v9_detail_temporal':
        from detail_temporal_student import DetailTemporalStyleContextStudent,DetailConfig
        from student_v2 import ReconstructionConfig
        from temporal_student import TemporalConfig
        model=DetailTemporalStyleContextStudent(ReconstructionConfig(**ckpt['base_config']),TemporalConfig(**ckpt['temporal_config']),DetailConfig(**ckpt['detail_config'])).to(device)
    elif ckpt.get('architecture')=='context_v5_temporal':
        from student_v2 import ReconstructionConfig
        from temporal_student import TemporalConfig,TemporalStyleContextStudent
        model=TemporalStyleContextStudent(ReconstructionConfig(**ckpt['base_config']),TemporalConfig(**ckpt['temporal_config'])).to(device)
    elif ckpt.get('architecture')=='context_v8_wide':
        from wide_student import WideStyleContextStudent,WideConfig
        model=WideStyleContextStudent(WideConfig(**ckpt['wide_config'])).to(device)
    elif ckpt.get('architecture')=='context_v8_binocular_capacity_temporal':
        from binocular_temporal_student import BinocularConfig,BinocularCapacityTemporalStyleContextStudent
        from capacity_student import CapacityConfig
        from student_v2 import ReconstructionConfig
        from temporal_student import TemporalConfig
        model=BinocularCapacityTemporalStyleContextStudent(ReconstructionConfig(**ckpt['base_config']),TemporalConfig(**ckpt['temporal_config']),CapacityConfig(**ckpt['capacity_config']),BinocularConfig(**ckpt['binocular_config'])).to(device)
    elif ckpt.get('architecture')=='context_v7_capacity_temporal':
        from capacity_temporal_student import CapacityTemporalStyleContextStudent,CapacityConfig
        from student_v2 import ReconstructionConfig
        from temporal_student import TemporalConfig
        model=CapacityTemporalStyleContextStudent(ReconstructionConfig(**ckpt['base_config']),TemporalConfig(**ckpt['temporal_config']),CapacityConfig(**ckpt['capacity_config'])).to(device)
    elif ckpt.get('architecture')=='context_v6_capacity':
        from capacity_student import CapacityStyleContextStudent,CapacityConfig
        from student_v2 import ReconstructionConfig
        model=CapacityStyleContextStudent(ReconstructionConfig(**ckpt['config']),CapacityConfig(**ckpt['capacity_config'])).to(device)
    elif ckpt.get('architecture')=='context_v4':
        from student_v4 import StyleContextStudent,ReconstructionConfig
        model=StyleContextStudent(ReconstructionConfig(**ckpt['config'])).to(device)
    elif ckpt.get('architecture')=='context_v3':
        from student_v3 import ContextStudent,ReconstructionConfig
        model=ContextStudent(ReconstructionConfig(**ckpt['config'])).to(device)
    elif ckpt.get('architecture')=='reconstruction_v2':
        from student_v2 import ReconstructionStudent,ReconstructionConfig
        model=ReconstructionStudent(ReconstructionConfig(**ckpt['config'])).to(device)
    else:model=OpenNRStudent(StudentConfig(**ckpt['config'])).to(device)
    model.load_state_dict(ckpt['model']);model.eval();return model,ckpt
