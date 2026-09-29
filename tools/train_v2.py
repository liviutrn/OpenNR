"""Reconstruction-capacity diagnostic and validation-selected v2 training."""
import argparse,json,time,math,random
from pathlib import Path
from dataclasses import asdict
from copy import deepcopy
import numpy as np
import torch
from torch.utils.data import DataLoader,Subset
from train_student import CachedPatches,batch_to_device,evaluate,atomic_json
from student_v2 import ReconstructionStudent,ReconstructionConfig,detail_loss

def main():
    p=argparse.ArgumentParser();p.add_argument('--cache',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--steps',type=int,default=6000);p.add_argument('--diagnostic',action='store_true');p.add_argument('--width',type=int,default=64);p.add_argument('--perceptual',type=float,default=0);p.add_argument('--scale',type=int,choices=[4,8],default=4);a=p.parse_args()
    if (a.output/'run.json').exists():raise ValueError('Use a fresh output directory')
    a.output.mkdir(parents=True,exist_ok=True);torch.set_num_threads(4);torch.manual_seed(73);np.random.seed(73);random.seed(73);torch.backends.cudnn.benchmark=True
    train=CachedPatches(a.cache,'train');val=CachedPatches(a.cache,'validation')
    if a.diagnostic:
        # Four distinct training-eye examples with strongest changes among first 64.
        candidates=range(0,min(len(train),512),8)
        ranked=sorted(candidates,key=lambda i:float((train[i]['rgb'].float()-train[i]['target'].float()).abs().mean()),reverse=True)
        ids=ranked[:4];train=Subset(train,ids);val=train
    else:ids=None
    loader=DataLoader(train,batch_size=4,shuffle=True,pin_memory=True);vl=DataLoader(val,batch_size=8,pin_memory=True)
    config=ReconstructionConfig(width=a.width,scale=a.scale);model=ReconstructionStudent(config).cuda();ema=deepcopy(model);opt=torch.optim.AdamW(model.parameters(),lr=.0003,weight_decay=.0001)
    feature=None
    if a.perceptual:
        from perceptual_features import FeatureDistance
        feature=FeatureDistance().cuda().eval()
    run=dict(architecture='reconstruction_v2',config=asdict(config),steps=a.steps,perceptual_weight=a.perceptual,diagnostic=a.diagnostic,diagnostic_indices=ids,parameters=sum(p.numel() for p in model.parameters()),cache=json.loads((a.cache/'complete.json').read_text()),test_used=False)
    atomic_json(a.output/'run.json',run);best=1.;start=time.time();it=iter(loader)
    for step in range(1,a.steps+1):
        try:b=next(it)
        except StopIteration:it=iter(loader);b=next(it)
        rgb,target,g,c=batch_to_device(b,'cuda',augment=not a.diagnostic)
        lr=.0003*(.1+.9*.5*(1+math.cos(math.pi*(step-1)/a.steps)))
        for group in opt.param_groups:group['lr']=lr
        opt.zero_grad(set_to_none=True)
        with torch.autocast('cuda',dtype=torch.bfloat16):
            pred=model(rgb,g,c);loss=detail_loss(pred.float(),target,rgb)
            if feature is not None:loss=loss+a.perceptual*feature(pred.float(),target)
        if not torch.isfinite(loss):raise RuntimeError('Nonfinite loss')
        loss.backward();norm=torch.nn.utils.clip_grad_norm_(model.parameters(),1.)
        if not torch.isfinite(norm):raise RuntimeError('Nonfinite gradients')
        opt.step()
        with torch.no_grad():
            decay=min(.995,(1+step)/(10+step))
            for ep,mp in zip(ema.parameters(),model.parameters()):ep.lerp_(mp,1-decay)
        if step%50==0:
            status=dict(state='training',step=step,total=a.steps,loss=loss.item(),seconds=time.time()-start,best_mae=best)
            atomic_json(a.output/'status.json',status);print(json.dumps(status),flush=True)
        if step%250==0 or step==a.steps:
            measured=model if a.diagnostic else ema;metrics=evaluate(measured,vl,'cuda');record=dict(step=step,metrics=metrics)
            with (a.output/'history.jsonl').open('a') as log:log.write(json.dumps(record)+'\n')
            if metrics['mae']<best:
                best=metrics['mae'];tmp=a.output/'best.tmp';torch.save(dict(architecture='reconstruction_v2',config=asdict(config),model=measured.state_dict(),step=step,cache=run['cache'],run=run),tmp);tmp.replace(a.output/'best.pt')
            print(json.dumps(record),flush=True)
    atomic_json(a.output/'status.json',dict(state='completed',step=a.steps,best_mae=best,seconds=time.time()-start))

if __name__=='__main__':main()
