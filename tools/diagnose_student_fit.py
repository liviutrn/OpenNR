"""Compare training fit with validation, emphasizing teacher-changed pixels."""
import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import numpy as np
import torch
from torch.utils.data import DataLoader,Subset
from opennr_student import load_student
from train_student import CachedPatches,batch_to_device,atomic_json


@torch.inference_mode()
def main():
    p=argparse.ArgumentParser();p.add_argument('--cache',type=Path,required=True);p.add_argument('--checkpoint',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    a.output.mkdir(parents=True,exist_ok=True);torch.set_num_threads(4)
    model,ckpt=load_student(a.checkpoint,'cuda');cache=json.loads((a.cache/'complete.json').read_text())
    if cache['rows_sha256']!=ckpt['cache']['rows_sha256']:raise ValueError('Dataset mismatch')
    result=dict(checkpoint=str(a.checkpoint),sha256=hashlib.sha256(a.checkpoint.read_bytes()).hexdigest(),step=ckpt['step'],selection='Training: up to 8 evenly spaced cached patches per sequence. Validation: all patches. Training examples are not a holdout. No test use.',splits={})
    for split in ('train','validation'):
        dataset=CachedPatches(a.cache,split);group=defaultdict(list)
        for i,j in enumerate(dataset.ids):group[dataset.plan[j]['sequence_id']].append(i)
        if split=='train':ids=[items[j] for items in group.values() for j in np.linspace(0,len(items)-1,min(8,len(items)),dtype=int)]
        else:ids=list(range(len(dataset)))
        sums=np.zeros(7);residual_stats=np.zeros(3);by_seq=defaultdict(list)
        for batch in DataLoader(Subset(dataset,ids),batch_size=4,pin_memory=True):
            x,t,g,c=batch_to_device(batch,'cuda')
            with torch.autocast('cuda',dtype=torch.bfloat16):pred=model(x,g,c)
            error=pred.float()-t;change=(x-t).abs();mask=change.mean(1,keepdim=True)>.05
            if not torch.isfinite(error).all():raise ValueError('Nonfinite prediction')
            sums+=np.array([error.abs().sum().item(),change.sum().item(),error.numel(),(error.abs()*mask).sum().item(),(change*mask).sum().item(),mask.sum().item()*3,error.square().sum().item()])
            residual=pred.float()-x;target_residual=t-x
            residual_stats+=np.array([residual.square().sum().item(),target_residual.square().sum().item(),(residual*target_residual).sum().item()])
            for seq,score in zip(batch['seq'],error.abs().mean((1,2,3)).cpu().tolist()):by_seq[seq].append(score)
        result['splits'][split]=dict(patches=len(ids),sequences=len(group),mae=sums[0]/sums[2],identity_mae=sums[1]/sums[2],changed_mae=sums[3]/max(1,sums[5]),changed_identity_mae=sums[4]/max(1,sums[5]),changed_fraction=sums[5]/sums[2],per_sequence_mae={k:float(np.mean(v)) for k,v in by_seq.items()},cache_patch_indices=[dataset.ids[i] for i in ids])
        result['splits'][split].update(residual_rms_ratio=float(np.sqrt(residual_stats[0]/max(1e-12,residual_stats[1]))),residual_cosine=float(residual_stats[2]/max(1e-12,np.sqrt(residual_stats[0]*residual_stats[1]))))
        if split=='train':
            result['training_only_least_squares_residual_gain']=float(residual_stats[2]/max(1e-12,residual_stats[0]))
        else:
            gain=result['training_only_least_squares_residual_gain']
            result['validation_mse_with_training_gain']=float((gain*gain*residual_stats[0]-2*gain*residual_stats[2]+residual_stats[1])/sums[2])
            result['validation_mse_unscaled']=float(sums[6]/sums[2])
        print(split,json.dumps({k:v for k,v in result['splits'][split].items() if k not in ('per_sequence_mae','cache_patch_indices')}),flush=True)
    atomic_json(a.output/'result.json',result)


if __name__=='__main__':main()
