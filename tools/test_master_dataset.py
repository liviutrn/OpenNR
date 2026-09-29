"""Numerical geometry regression checks and real-data loading/training smoke test."""
import argparse
import json
from pathlib import Path
import numpy as np
import torch
from master_dataset import sample_guide, MasterPatchDataset

def geometry_tests():
    # Analytic normalized pixel-center ramp on a lower-resolution guide.
    gw,gh,cw,ch=16,12,24,18
    x=(np.arange(gw,dtype=np.float32)+.5)/gw
    y=(np.arange(gh,dtype=np.float32)+.5)/gh
    xx,yy=np.meshgrid(x,y); arr=np.stack((xx,yy),-1)
    box=(6,3,9,9); n=9
    result,mask=sample_guide(arr,box,(cw,ch),n,np.ones((gh,gw),bool))
    tx=(6+torch.arange(n)+.5)/cw; ty=(3+torch.arange(n)+.5)/ch
    assert torch.allclose(result[0],tx[None,:].expand(n,n),atol=1e-6)
    assert torch.allclose(result[1],ty[:,None].expand(n,n),atol=1e-6)
    assert mask.min()==1
    result,mask=sample_guide(arr,(0,0,cw,ch),(cw,ch),(6,8),np.ones((gh,gw),bool))
    assert result.shape==(2,6,8) and mask.shape==(1,6,8)
    assert torch.allclose(result[0],((torch.arange(8)+.5)/8)[None,:].expand(6,8),atol=1e-6)
    assert torch.allclose(result[1],((torch.arange(6)+.5)/6)[:,None].expand(6,8),atol=1e-6)
    valid=np.ones((gh,gw),bool); valid[4:7,5:8]=False
    arr[~valid]=0
    result,mask=sample_guide(arr,box,(cw,ch),n,valid)
    assert torch.isfinite(result).all() and mask.min()==0
    return 'passed: mismatched-resolution pixel centers and invalid-guide mask'

def main():
    p=argparse.ArgumentParser(); p.add_argument('--manifest',type=Path); args=p.parse_args()
    torch.set_num_threads(2)
    report=dict(geometry=geometry_tests(),loader_samples=0,per_split={},optimizer_steps=0)
    if args.manifest:
        first=None
        for split in ('train','validation','test'):
            ds=MasterPatchDataset(args.manifest,split)
            seen=set(); checked=0
            for i,row in enumerate(ds.rows):
                key=(row['sequence_id'],row['eye'])
                if key in seen: continue
                seen.add(key)
                # Two patch locations per eye per sequence check center and edge.
                for patch in (0,2):
                    item=ds[i*ds.patches_per_eye+patch]
                    for name in ('input','teacher','depth','motion','color_valid','depth_valid','motion_valid'):
                        t=item[name]; assert torch.isfinite(t).all(),(key,name)
                        assert t.shape[-2:]==(512,512)
                    assert item['motion'].abs().max()<=1.00001
                    checked+=1
                    if first is None: first=item
            report['per_split'][split]=dict(eye_pairs=len(ds.rows),patches=len(ds),checked=checked)
            report['loader_samples']+=checked
            print(split,report['per_split'][split],flush=True)
        # Exercise a masked loss and gradient update; no checkpoint or quality claim.
        from train_opennr_poc import TinyStudent
        device='cuda' if torch.cuda.is_available() else 'cpu'
        model=TinyStudent(6,width=8,blocks=1,output_resolution=512).to(device)
        opt=torch.optim.AdamW(model.parameters(),lr=1e-4)
        features=torch.cat((first['input'],first['depth']*first['depth_valid'],first['motion']*first['motion_valid']),0)[None].to(device)
        features=torch.nn.functional.interpolate(features,size=(128,128),mode='bilinear',align_corners=False)
        target=first['teacher'][None].to(device); mask=first['color_valid'][None].to(device)
        out=model(features); loss=((out-target).abs()*mask).sum()/(mask.sum()*3).clamp_min(1)
        loss.backward(); assert all(torch.isfinite(p.grad).all() for p in model.parameters() if p.grad is not None)
        opt.step(); report.update(optimizer_steps=1,smoke_loss=float(loss.detach()),device=device)
        (args.manifest.parent/'loader_validation.json').write_text(json.dumps(report,indent=2))
    print(json.dumps(report,indent=2))

if __name__=='__main__': main()
