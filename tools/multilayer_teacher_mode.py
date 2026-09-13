"""Mode2 residual affine controls after normalization; backbone dimensions unchanged."""
import torch
from torch import nn
from teacher_mode_head import TeacherModeConv,enable_teacher_mode,set_teacher_mode


class TeacherModeGroupNorm(nn.GroupNorm):
    def __init__(self, original):
        if not original.affine:
            raise ValueError('Expected learned affine normalization')
        super().__init__(original.num_groups,original.num_channels,eps=original.eps,affine=True,
                         device=original.weight.device,dtype=original.weight.dtype)
        with torch.no_grad():
            self.weight.copy_(original.weight)
            self.bias.copy_(original.bias)
        self.mode_scale=nn.Parameter(torch.zeros_like(original.weight))
        self.mode_bias=nn.Parameter(torch.zeros_like(original.bias))
        self.teacher_pass_count=1

    def forward(self,x):
        value=super().forward(x)
        if self.teacher_pass_count==1:
            return value
        # Preserve dtype and exact zero-init output; accumulate modulation in FP32.
        scale=self.mode_scale.float()[None,:,None,None]
        bias=self.mode_bias.float()[None,:,None,None]
        return (value.float()*(1+scale)+bias).to(value.dtype)


def enable_multilayer_teacher_mode(head):
    if any(isinstance(module,TeacherModeGroupNorm) for module in head.modules()):
        raise ValueError('Multi-layer conditioning already enabled')
    if not isinstance(head.stem[0],TeacherModeConv):
        enable_teacher_mode(head)
    def replace(module):
        for name,child in list(module.named_children()):
            if isinstance(child,nn.GroupNorm):
                setattr(module,name,TeacherModeGroupNorm(child))
            else:
                replace(child)
    replace(head)
    if sum(isinstance(module,TeacherModeGroupNorm) for module in head.modules())!=51:
        raise ValueError('Unexpected normalization layout')
    return head


def set_conditioned_teacher_mode(head,pass_count):
    """Dispatch across old and multi-layer heads without modifying old implementation."""
    set_teacher_mode(head,pass_count)
    for module in head.modules():
        if isinstance(module,TeacherModeGroupNorm):
            module.teacher_pass_count=pass_count
