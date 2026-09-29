"""Full-eye validation including teacher-changed regions; no test rows selected."""
import argparse
import hashlib
import json
import math
import time
from pathlib import Path
import numpy as np
import torch
from evaluate_student import load_eye
from opennr_student import load_student
from train_student import atomic_json


@torch.inference_mode()
def main():
    p=argparse.ArgumentParser()
    p.add_argument('--checkpoint',type=Path,required=True)
    p.add_argument('--cache',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();a.output.mkdir(parents=True,exist_ok=True);torch.set_num_threads(4)
    fingerprint=hashlib.sha256(a.checkpoint.read_bytes()).hexdigest()
    model,ckpt=load_student(a.checkpoint,'cuda')
    cache=json.loads((a.cache/'complete.json').read_text())
    if ckpt['cache']['rows_sha256']!=cache['rows_sha256']:raise ValueError('Dataset mismatch')
    rows=json.loads((a.cache/'rows.json').read_text());contexts=np.load(a.cache/'context.npy',mmap_mode='r')
    ids=[i for i,r in enumerate(rows) if r['split']=='validation']
    totals=np.zeros(7,dtype='f8');records=[];start=time.time()
    for index,i in enumerate(ids):
        row=rows[i];x,t,g,c=load_eye(row,contexts[i])
        with torch.autocast('cuda',dtype=torch.bfloat16):pred=model(x,g,c)
        err=(pred.float()-t);base=(x-t)
        if not torch.isfinite(err).all():raise ValueError('Nonfinite prediction')
        mask=base.abs().mean(1,keepdim=True)>.05
        changed_count=int(mask.sum())*3
        values=np.array([err.abs().sum().item(),err.square().sum().item(),base.abs().sum().item(),err.numel(),(err.abs()*mask).sum().item(),(base.abs()*mask).sum().item(),changed_count])
        totals+=values
        records.append(dict(row=i,sequence=row['sequence_id'],eye=row['eye'],frame=row['frame_id'],mae=values[0]/values[3],identity_mae=values[2]/values[3],changed_region_mae=values[4]/max(1,values[6])))
        atomic_json(a.output/'status.json',dict(state='evaluating',completed=index+1,total=len(ids),seconds=time.time()-start))
        del x,t,g,c,pred,err,base,mask
    result=dict(checkpoint=str(a.checkpoint),checkpoint_sha256=fingerprint,step=ckpt['step'],split='validation',eye_count=len(ids),sequence_count=len({rows[i]['sequence_id'] for i in ids}),mae=totals[0]/totals[3],psnr=-10*math.log10(max(totals[1]/totals[3],1e-12)),identity_mae=totals[2]/totals[3],changed_region_mae=totals[4]/max(1,totals[6]),changed_region_identity_mae=totals[5]/max(1,totals[6]),changed_region_fraction=totals[6]/totals[3],mask_definition='Mean absolute teacher-input RGB difference > 0.05; all three output channels evaluated',records=records,seconds=time.time()-start,scope='All native validation eyes; spatial numeric quality, not temporal or independent test acceptance')
    atomic_json(a.output/'result.json',result);atomic_json(a.output/'status.json',dict(state='completed',eye_count=len(ids)))
    print(json.dumps({k:v for k,v in result.items() if k!='records'}),flush=True)


if __name__=='__main__':main()
