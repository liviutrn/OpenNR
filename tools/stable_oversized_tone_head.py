"""Normalized version of the oversized diagnostic U-Net to control activation growth."""
from torch import nn
from oversized_tone_head import OversizedToneHead


def normalize_sequences(module):
    for name,child in list(module.named_children()):
        normalize_sequences(child)
        if isinstance(child,nn.Sequential):
            layers=[]
            for layer in child:
                layers.append(layer)
                if isinstance(layer,nn.Conv2d):
                    layers.append(nn.GroupNorm(min(8,layer.out_channels),layer.out_channels))
            setattr(module,name,nn.Sequential(*layers))


class StableOversizedToneHead(OversizedToneHead):
    def __init__(self):
        super().__init__()
        normalize_sequences(self)
