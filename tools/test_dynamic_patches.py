"""Verify epoch sampling, raw RGB equality and direct native-guide alignment."""
import json
from pathlib import Path
import numpy as np
import torch
from dynamic_patches import DynamicPatches
from master_dataset import sample_guide

torch.set_num_threads(2)
d=DynamicPatches('C:/OpenNR/TrainingCache/student_v1','C:/OpenNR/TrainingCache/dynamic_guides_v1')
assert len(d)==7712 and all(d.rows[i]['split']=='train' for i in d.row_ids)
checks=[]
for index in (0,17,len(d)-1):
    boxes=[]
    for epoch in (0,1):
        d.set_epoch(epoch);item=d[index];box=d.box(index);boxes.append(box)
        assert box==d.box(index) and box[0]%4==box[1]%4==0
        row=d.rows[d.row_ids[index//8]];w,h=row['color_size'];gw,gh=row['guide_size'];x,y,pw,ph=box
        for stage,key in (('input','rgb'),('teacher','target')):
            raw=np.memmap(Path(row['paths'][stage]).with_suffix('.raw.bin'),dtype='u1',mode='r',shape=(h,w,4))
            assert np.array_equal(item[key].numpy(),raw[y:y+ph,x:x+pw,:3].transpose(2,0,1))
        dep=np.memmap(row['paths']['depth'],dtype='<f4',mode='r',shape=(gh,gw,1));dv=np.isfinite(dep[...,0])&(dep[...,0]>=0)&(dep[...,0]<=1)
        mv=np.memmap(row['paths']['motion_vectors'],dtype='<f2',mode='r',shape=(gh,gw,2)).astype('f4');valid=np.isfinite(mv).all(2)&(np.abs(mv)<=.25).all(2);mv=np.where(valid[...,None],mv,0)
        mv[...,0]*=row['motion_scale'][0]*w/gw;mv[...,1]*=row['motion_scale'][1]*h/gh
        a,am=sample_guide(np.where(dv[...,None],dep,0),box,(w,h),128,dv);b,bm=sample_guide(np.clip(mv,-128,128)/128,box,(w,h),128,valid)
        expected=torch.cat((a*am,b*bm,am,bm),0)
        error=(expected-item['guides'].float()).abs().max().item()
        assert error<.001,error
        assert torch.equal(expected[3:],item['guides'][3:].float())
        checks.append(dict(index=index,epoch=epoch,box=box,max_guide_error=error))
    assert boxes[0]!=boxes[1]
d.set_epoch(0);assert d.box(0)==tuple(checks[0]['box'])
Path('out/dynamic_patch_validation.json').write_text(json.dumps(dict(state='passed',checks=checks),indent=2))
print('PASS: changing/reproducible epoch crops, training-only rows, exact RGB, direct guide alignment and masks')
