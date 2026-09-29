"""Explicit one/two-pass request conditioning, never inferred from teacher pixels.

Adds a learned 16-channel offset before the first normalization for mode2.
Mode1 is exactly the original stem path. All shared U-Net weights remain trainable.
This small architectural hypothesis requires evaluation; it is not a quality claim.
"""
import torch
from torch import nn


class TeacherModeConv(nn.Conv2d):
    def __init__(self, original):
        super().__init__(original.in_channels, original.out_channels, original.kernel_size,
                         stride=original.stride, padding=original.padding,
                         device=original.weight.device, dtype=original.weight.dtype)
        with torch.no_grad():
            self.weight.copy_(original.weight)
            self.bias.copy_(original.bias)
        self.mode_bias=nn.Parameter(torch.zeros(original.out_channels,device=original.weight.device,dtype=original.weight.dtype))
        self.teacher_pass_count=1

    def forward(self,x):
        result=super().forward(x)
        if self.teacher_pass_count==1:return result
        return result+self.mode_bias.to(result.dtype)[None,:,None,None]


def enable_teacher_mode(head):
    if isinstance(head.stem[0],TeacherModeConv):raise ValueError('Mode conditioning already enabled')
    head.stem[0]=TeacherModeConv(head.stem[0])
    return head


def set_teacher_mode(head,pass_count):
    if pass_count not in (1,2):raise ValueError('Unknown teacher pass count')
    stem=getattr(head,'stem',None)
    layer=stem[0] if stem is not None else None
    if isinstance(layer,TeacherModeConv):layer.teacher_pass_count=pass_count
    elif pass_count!=1:raise ValueError('Two-pass data requires explicitly conditioned model')
