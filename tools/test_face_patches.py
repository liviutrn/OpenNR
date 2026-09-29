"""Real training-row geometry, raw alignment and Windows worker checks."""
import argparse,json,pickle
from pathlib import Path
import numpy as np
import torch
from torch.utils.data import DataLoader,Subset
from face_patches import FacePatches
from dynamic_patches import DynamicPatches,raw_color_path

def main():
    p=argparse.ArgumentParser();p.add_argument('--cache',default='C:/OpenNR/TrainingCache/student_v1');p.add_argument('--dynamic-guides',default='C:/OpenNR/TrainingCache/dynamic_guides_v1');p.add_argument('--faces',default='out/quality_phase_20260905/face_audit_all/result.json');p.add_argument('--patch-size',type=int,default=512);a=p.parse_args()
    torch.set_num_threads(2)
    cache=a.cache;guides=a.dynamic_guides
    data=FacePatches(cache,guides,a.faces,patch_size=a.patch_size)
    base=DynamicPatches(cache,guides,patch_size=a.patch_size);targeted=0;checks=0
    for epoch in (0,1,5):
        for index in range(len(data)):
            box=data.box(index,epoch);assert box==data.box(index,epoch)
            x,y,w,h=box;ri=data.row_ids[index//8];width,height=data.rows[ri]['color_size']
            assert x%4==y%4==0 and 0<=x<=width-w and 0<=y<=height-h
            faces=data.faces[ri]
            if index%8>=2 or not faces:assert box==base.box(index,epoch)
            else:
                assert any(min(x+w,b['xyxy'][2])>max(x,b['xyxy'][0]) and min(y+h,b['xyxy'][3])>max(y,b['xyxy'][1]) for b in faces)
                targeted+=1
            expected_mask=np.zeros((h,w),dtype=np.float32)
            for face in faces:
                fx1,fy1,fx2,fy2=face['xyxy']
                ix1=max(x,int(np.ceil(fx1)));iy1=max(y,int(np.ceil(fy1)))
                ix2=min(x+w,int(np.floor(fx2)));iy2=min(y+h,int(np.floor(fy2)))
                if ix2>ix1 and iy2>iy1:expected_mask[iy1-y:iy2-y,ix1-x:ix2-x]=1
            sample=data[(epoch,index)]
            assert sample['face_mask'].shape==(1,h,w)
            assert np.array_equal(sample['face_mask'].numpy()[0],expected_mask)
            checks+=1
    assert len(pickle.dumps(data))<4096
    indices=[j*8 for j,ri in enumerate(data.row_ids) if data.faces[ri]][::100]
    for index,batch in zip(indices,DataLoader(Subset(data,indices),batch_size=1,num_workers=2)):
        expected=data[index]
        for key in ('rgb','target','guides','context','face_mask'):assert torch.equal(batch[key][0],expected[key])
        x,y,w,h=expected['box'];ri=data.row_ids[index//8];row=data.rows[ri];width,height=row['color_size']
        for stage,key in [('input','rgb'),('teacher','target')]:
            raw=np.memmap(raw_color_path(row['paths'][stage]),mode='r',dtype='u1',shape=(height,width,4))
            assert np.array_equal(expected[key].numpy(),raw[y:y+h,x:x+w,:3].transpose(2,0,1))
        gi,slot=data.guide_lookup[index//8]
        assert np.array_equal(expected['guides'].numpy(),data.guide_groups[gi][slot,:,y//4:(y+h)//4,x//4:(x+w)//4])
    result=dict(state='passed',geometry_cases=checks,targeted_intersections=targeted,raw_and_worker_cases=len(indices),serialized_bytes=len(pickle.dumps(data)))
    Path('out/quality_phase_20260905/face_sampler_validation.json').write_text(json.dumps(result,indent=2));print(result)

if __name__=='__main__':main()
