"""Spatial context attention extension initialized as an exact v2 function.

Queries retain local spatial locations; keys/values retain the 24x24 whole-eye
context grid instead of compressing it to one pooled vector. This is spatial
cross-attention, not temporal memory or access to teacher features.
"""
import torch
from torch import nn
from torch.nn import functional as F
from student_v2 import ReconstructionStudent, ReconstructionConfig
from opennr_student import ChannelNorm


class ContextStudent(ReconstructionStudent):
    def __init__(self, config=ReconstructionConfig()):
        super().__init__(config)
        channels = 4 * config.width
        self.context_grid = nn.Sequential(nn.Conv2d(8,64,3,2,1), nn.GELU(), nn.Conv2d(64,128,3,2,1), nn.GELU())
        self.query_norm = ChannelNorm(channels)
        self.query = nn.Conv2d(channels,128,1)
        self.key_value = nn.Conv2d(128,256,1)
        self.context_output = nn.Conv2d(128,channels,1)
        nn.init.zeros_(self.context_output.weight)
        nn.init.zeros_(self.context_output.bias)

    def condition(self,z,context):
        b,_,h,w=z.shape
        q=self.query(self.query_norm(z)).reshape(b,4,32,h*w).transpose(-1,-2)
        k,v=self.key_value(self.context_grid(context)).chunk(2,1)
        k=k.reshape(b,4,32,-1).transpose(-1,-2)
        v=v.reshape(b,4,32,-1).transpose(-1,-2)
        # SDPA avoids materializing the native-resolution attention matrix.
        value=F.scaled_dot_product_attention(q,k,v).transpose(-1,-2).reshape(b,128,h,w)
        return z+self.context_output(value)

    def initialize_v2(self, state):
        incompatible=self.load_state_dict(state,strict=False)
        prefixes=('context_grid.','query_norm.','query.','key_value.','context_output.')
        if incompatible.unexpected_keys or any(not key.startswith(prefixes) for key in incompatible.missing_keys):
            raise ValueError(f'Unexpected v2 conversion mismatch: {incompatible}')
