"""AlexNet LPIPS v0.1 on unchanged validation patches, separate from training loss."""
import argparse
from collections import defaultdict
import hashlib
import importlib.metadata
import json
from pathlib import Path
import numpy as np
import torch
from torch.utils.data import DataLoader
import lpips
from train_student import CachedPatches,batch_to_device,atomic_json
from opennr_student import load_student


@torch.inference_mode()
def main():
    p=argparse.ArgumentParser();p.add_argument('--cache',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--models',nargs='+',required=True);a=p.parse_args()
    a.output.mkdir(parents=True,exist_ok=True);torch.set_num_threads(4)
    metric=lpips.LPIPS(net='alex',version='0.1').eval().requires_grad_(False).cuda()
    # Check the actual metric runtime, input normalization and nontrivial response.
    zero=torch.zeros(1,3,64,64,device='cuda');noise=torch.rand_like(zero)
    assert metric(zero,zero).abs().max()<1e-7 and metric(zero,noise).min()>0
    loader=DataLoader(CachedPatches(a.cache,'validation'),batch_size=4,pin_memory=True)
    cache=json.loads((a.cache/'complete.json').read_text());results={}
    for path in a.models:
        model,checkpoint=load_student(path,'cuda')
        if checkpoint['cache']['rows_sha256']!=cache['rows_sha256']:raise ValueError('Dataset identity mismatch')
        values=[];identity=[];by_seq=defaultdict(list)
        for b in loader:
            x,t,g,c=batch_to_device(b,'cuda')
            with torch.autocast('cuda',dtype=torch.bfloat16):pred=model(x,g,c)
            if not torch.isfinite(pred).all():raise ValueError('Nonfinite prediction')
            # Evaluate displayed RGB in [-1,1], full 512x512 patches, no resize.
            scores=metric(pred.float().clamp(0,1)*2-1,t*2-1).flatten().cpu().tolist()
            base=metric(x*2-1,t*2-1).flatten().cpu().tolist()
            values.extend(scores);identity.extend(base)
            for seq,value in zip(b['seq'],scores):by_seq[seq].append(value)
        results[path]=dict(step=checkpoint['step'],checkpoint_sha256=hashlib.sha256(Path(path).read_bytes()).hexdigest(),lpips=float(np.mean(values)),identity_lpips=float(np.mean(identity)),patch_count=len(values),per_sequence={k:float(np.mean(v)) for k,v in by_seq.items()})
        print(path,json.dumps(results[path]),flush=True)
        del model,checkpoint
        atomic_json(a.output/'result.json',dict(metric='LPIPS AlexNet v0.1',package_version=importlib.metadata.version('lpips'),scope='352 unchanged validation 512x512 patches; display clamp; not used in student loss; not independent test or VR acceptance',results=results))


if __name__=='__main__':main()
