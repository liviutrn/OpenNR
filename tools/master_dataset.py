"""Aligned spatial training patches from audited full-resolution masters.

The prepared JSONL preserves stereo/frame grouping. Each item supplies RGB,
teacher, depth, motion, and validity masks at the same pixel-center coordinates.
Motion is a bounded spatial feature, NOT calibrated temporal reprojection.
"""
from __future__ import annotations
import json
from pathlib import Path
import numpy as np
import torch
from torch.utils.data import Dataset
import torch.nn.functional as F
from PIL import Image


def sample_guide(array, box, color_size, size, valid):
    """Map color pixel centers to normalized guide coordinates (align_corners=False).

    Weighted interpolation prevents invalid native pixels contaminating neighbors.
    A sample is valid only if essentially all interpolation support is valid.
    """
    x,y,w,h=box; cw,ch=color_size
    sh,sw=(size,size) if isinstance(size,int) else size
    xs=(x+(torch.arange(sw,dtype=torch.float32)+.5)*w/sw)/cw*2-1
    ys=(y+(torch.arange(sh,dtype=torch.float32)+.5)*h/sh)/ch*2-1
    yy,xx=torch.meshgrid(ys,xs,indexing='ij'); grid=torch.stack((xx,yy),-1)[None]
    values=torch.from_numpy(np.ascontiguousarray(array.transpose(2,0,1))).float()[None]
    mask=torch.from_numpy(np.ascontiguousarray(valid.astype(np.float32)))[None,None]
    support=F.grid_sample(mask,grid,align_corners=False,padding_mode='border')
    result=F.grid_sample(values*mask,grid,align_corners=False,padding_mode='border') / support.clamp_min(1e-6)
    return result[0],(support[0] > .999).float()


class MasterPatchDataset(Dataset):
    def __init__(self,manifest,split='train',patch_size=512,patches_per_eye=4):
        self.rows=[json.loads(l) for l in Path(manifest).read_text().splitlines() if l.strip()]
        self.rows=[r for r in self.rows if r['split']==split]
        self.patch_size=patch_size; self.patches_per_eye=patches_per_eye
    def __len__(self): return len(self.rows)*self.patches_per_eye
    def __getitem__(self,index):
        row=self.rows[index//self.patches_per_eye]; patch=index%self.patches_per_eye
        size=self.patch_size; w,h=row['color_size']
        # Fixed spatial coverage is deterministic for validation and reproducibility.
        # The frame/eye identity remains in the result for grouped metrics.
        centers=((.5,.5),(.25,.5),(.75,.5),(.5,.25),(.5,.75))
        cx,cy=centers[patch%len(centers)]
        if size>min(w,h): raise ValueError('patch exceeds native color dimensions')
        x=int(round((w-size)*cx)); y=int(round((h-size)*cy)); box=(x,y,size,size)
        color=[]
        for stage in ('input','teacher'):
            with Image.open(row['paths'][stage]) as im:
                rgb=np.asarray(im.crop((x,y,x+size,y+size))).copy()
            color.append(torch.from_numpy(rgb.transpose(2,0,1)).float()/255)
        gw,gh=row['guide_size']
        depth=np.memmap(row['paths']['depth'],dtype='<f4',mode='r',shape=(gh,gw,1))
        dv=np.isfinite(depth[:,:,0]) & (depth[:,:,0]>=0) & (depth[:,:,0]<=1)
        dep,dm=sample_guide(np.where(dv[:,:,None],depth,0),box,(w,h),size,dv)
        motion=np.memmap(row['paths']['motion_vectors'],dtype='<f2',mode='r',shape=(gh,gw,2)).astype(np.float32)
        mv=np.isfinite(motion).all(2) & (np.abs(motion)<=.25).all(2)
        motion=np.where(mv[:,:,None],motion,0)
        # Scales are per eye, then guide pixels are converted to color pixels.
        motion[:,:,0]*=row['motion_scale'][0]*w/gw
        motion[:,:,1]*=row['motion_scale'][1]*h/gh
        mot,mm=sample_guide(np.clip(motion,-128,128)/128,box,(w,h),size,mv)
        color_mask=((color[0].amax(0)>0)&(color[1].amax(0)>0)).float()[None]
        return dict(input=color[0],teacher=color[1],depth=dep,motion=mot,depth_valid=dm,motion_valid=mm,color_valid=color_mask,sequence_id=row['sequence_id'],frame_id=row['frame_id'],eye=row['eye'],box=box,history_reset=row['history_reset'])
