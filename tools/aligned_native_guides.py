"""Sample native depth/MV crops in the actual teacher-color crop coordinates."""
import numpy as np
import torch
from master_dataset import sample_guide


def native_box(guide, color):
    gs, gc = guide['source_rect'], guide['crop_rect']
    cs, cc = color['source_rect'], color['crop_rect']
    sx,sy=gs['width']/cs['width'],gs['height']/cs['height']
    box=(cc['x']*sx-gc['x'],cc['y']*sy-gc['y'],cc['width']*sx,cc['height']*sy)
    x,y,w,h=box
    if x < -1e-5 or y < -1e-5 or x+w>guide['width']+1e-5 or y+h>guide['height']+1e-5:
        raise ValueError('Native crop does not cover requested teacher region')
    return box


def sample_aligned(row,depth,depth_valid,motion,motion_valid,size):
    parts=[]
    for stage,value,valid in [('depth',depth,depth_valid),('motion_vectors',motion,motion_valid)]:
        guide=row['artifacts'][stage]
        box=native_box(guide,row['artifacts']['teacher'])
        tensor,mask=sample_guide(value,box,(guide['width'],guide['height']),size,valid)
        parts.append((tensor*mask,mask))
    return torch.cat((parts[0][0],parts[1][0],parts[0][1],parts[1][1])).numpy().astype(np.float16)
