"""Monitored, resumable spatial distillation with frozen sequence holdouts."""
import argparse
from collections import defaultdict
from copy import deepcopy
from dataclasses import asdict
import hashlib
import json
import math
from pathlib import Path
import random
import time
import numpy as np
import torch
from torch.utils.data import Dataset,DataLoader
import torch.nn.functional as F
from opennr_student import OpenNRStudent,StudentConfig

class CachedPatches(Dataset):
    def __init__(self,root,split):
        self.root=Path(root);self.plan=json.loads((self.root/'patches.json').read_text());self.ids=[i for i,p in enumerate(self.plan) if p['split']==split];self.split=split
        self.rgb=np.load(self.root/'rgb.npy',mmap_mode='r');self.guides=np.load(self.root/'guides.npy',mmap_mode='r');self.context=np.load(self.root/'context.npy',mmap_mode='r')
    def __len__(self):return len(self.ids)
    def __getitem__(self,index):
        i=self.ids[index];r=self.plan[i]
        return dict(rgb=torch.from_numpy(self.rgb[i,0].copy()),target=torch.from_numpy(self.rgb[i,1].copy()),guides=torch.from_numpy(self.guides[i].copy()),context=torch.from_numpy(self.context[r['row']].copy()),seq=r['sequence_id'],eye=r['eye'],index=i)

def atomic_json(path,obj):
    tmp=path.with_suffix('.tmp');tmp.write_text(json.dumps(obj,indent=2))
    # Windows readers/indexers can briefly deny replacement of the destination.
    # Keep the previous complete JSON visible and retry only permission failures.
    for attempt in range(21):
        try:
            tmp.replace(path)
            break
        except PermissionError:
            if attempt == 20:raise
            time.sleep(.05)

def batch_to_device(b,device,augment=False):
    rgb=b['rgb'].to(device,non_blocking=True).float()/255;target=b['target'].to(device,non_blocking=True).float()/255
    guide=b['guides'].to(device,non_blocking=True).float();context=b['context'].to(device,non_blocking=True).float()
    if augment and random.random()<.5:
        rgb=rgb.flip(-1);target=target.flip(-1);guide=guide.flip(-1);context=context.flip(-1)
        guide[:,1]*=-1;context[:,4]*=-1
    return rgb,target,guide,context

def loss_fn(pred,target):
    error=pred-target
    pixel=torch.sqrt(error.square()+1e-6).mean()
    coarse=sum((F.avg_pool2d(pred,k)-F.avg_pool2d(target,k)).abs().mean() for k in (4,16))/2
    dx=(pred[:,:,:,1:]-pred[:,:,:,:-1])-(target[:,:,:,1:]-target[:,:,:,:-1])
    dy=(pred[:,:,1:,:]-pred[:,:,:-1,:])-(target[:,:,1:,:]-target[:,:,:-1,:])
    edge=(dx.abs().mean()+dy.abs().mean())/2
    return pixel+.25*coarse+.1*edge

@torch.no_grad()
def evaluate(model,loader,device):
    model.eval();abs_sum=sq_sum=base_abs=base_sq=0.;pixels=0;by_seq=defaultdict(list);by_eye=defaultdict(list)
    for b in loader:
        rgb,target,g,c=batch_to_device(b,device)
        with torch.autocast(device_type='cuda',dtype=torch.bfloat16,enabled=device=='cuda'):pred=model(rgb,g,c)
        err=pred.float()-target;baseline=rgb-target
        abs_sum+=err.abs().sum().item();sq_sum+=err.square().sum().item();base_abs+=baseline.abs().sum().item();base_sq+=baseline.square().sum().item();pixels+=target.numel()
        for s,e,v in zip(b['seq'],b['eye'].tolist(),err.abs().mean((1,2,3)).cpu().tolist()):by_seq[s].append(v);by_eye[str(e)].append(v)
    return dict(mae=abs_sum/pixels,psnr=-10*math.log10(max(sq_sum/pixels,1e-12)),identity_mae=base_abs/pixels,identity_psnr=-10*math.log10(max(base_sq/pixels,1e-12)),improvement_pct=100*(base_abs-abs_sum)/base_abs,sequence_mae={s:float(np.mean(v)) for s,v in by_seq.items()},eye_mae={s:float(np.mean(v)) for s,v in by_eye.items()},pixels=pixels)

def main():
    p=argparse.ArgumentParser();p.add_argument('--cache',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--name',default='guided');p.add_argument('--width',type=int,default=32);p.add_argument('--blocks',type=int,default=2);p.add_argument('--steps',type=int,default=2000);p.add_argument('--batch',type=int,default=8);p.add_argument('--eval-every',type=int,default=250);p.add_argument('--lr',type=float,default=.0003);p.add_argument('--resume',type=Path);p.add_argument('--seed',type=int,default=42);p.add_argument('--workers',type=int,default=0);a=p.parse_args()
    torch.set_num_threads(4);torch.manual_seed(a.seed);np.random.seed(a.seed);random.seed(a.seed)
    if not torch.cuda.is_available():raise RuntimeError('CUDA required for this training run')
    torch.backends.cudnn.benchmark=True;device='cuda';a.output.mkdir(parents=True,exist_ok=True)
    cache=json.loads((a.cache/'complete.json').read_text());train=CachedPatches(a.cache,'train');val=CachedPatches(a.cache,'validation')
    generator=torch.Generator().manual_seed(a.seed)
    loader=DataLoader(train,batch_size=a.batch,shuffle=True,generator=generator,num_workers=a.workers,pin_memory=True)
    vloader=DataLoader(val,batch_size=a.batch,num_workers=a.workers,pin_memory=True)
    config=StudentConfig(width=a.width,guided=a.name!='rgb',blocks=a.blocks)
    model=OpenNRStudent(config).to(device);ema=deepcopy(model);opt=torch.optim.AdamW(model.parameters(),lr=a.lr,weight_decay=.0001)
    start_step=0;best=float('inf')
    if a.resume:
        saved=torch.load(a.resume,map_location=device,weights_only=False)
        if saved['config']!=asdict(config):raise ValueError('resume architecture mismatch')
        if saved['cache']['rows_sha256']!=cache['rows_sha256']:raise ValueError('resume dataset mismatch')
        model.load_state_dict(saved.get('raw_model',saved['model']));ema.load_state_dict(saved['model']);opt.load_state_dict(saved['optimizer']);start_step=saved['step'];best=saved['best_mae']
    run=dict(config=asdict(config),args={k:str(v) if isinstance(v,Path) else v for k,v in vars(a).items()},cache=cache,parameters=sum(p.numel() for p in model.parameters()),training_pairs=len(train),validation_pairs=len(val),test_used=False,started=time.time())
    atomic_json(a.output/'run.json',run)
    def save(name,step):
        payload=dict(config=asdict(config),model=ema.state_dict(),raw_model=model.state_dict(),optimizer=opt.state_dict(),step=step,best_mae=best,cache=cache,run=run)
        tmp=a.output/(name+'.tmp');torch.save(payload,tmp);tmp.replace(a.output/(name+'.pt'))
    it=iter(loader);started=time.time();last=time.time();loss_acc=[]
    print(json.dumps(dict(event='start',**run)),flush=True)
    for step in range(start_step+1,a.steps+1):
        try:b=next(it)
        except StopIteration:it=iter(loader);b=next(it)
        rgb,target,g,c=batch_to_device(b,device,True);model.train();opt.zero_grad(set_to_none=True)
        lr=a.lr*(.1+.9*.5*(1+math.cos(math.pi*(step-1)/a.steps)))
        for group in opt.param_groups:group['lr']=lr
        with torch.autocast(device_type='cuda',dtype=torch.bfloat16):pred=model(rgb,g,c);loss=loss_fn(pred.float(),target)
        if not torch.isfinite(loss):raise RuntimeError(f'nonfinite loss at {step}')
        loss.backward();grad=torch.nn.utils.clip_grad_norm_(model.parameters(),1.)
        if not torch.isfinite(grad):raise RuntimeError(f'nonfinite gradient at {step}')
        opt.step()
        with torch.no_grad():
            decay=min(.995,(1+step)/(10+step))
            for ep,mp in zip(ema.parameters(),model.parameters()):ep.lerp_(mp,1-decay)
        loss_acc.append(loss.item())
        if step%25==0 or step==1:
            status=dict(state='training',step=step,total=a.steps,loss=float(np.mean(loss_acc)),lr=lr,seconds=time.time()-started,best_validation_mae=best if math.isfinite(best) else None,gpu_peak_gib=torch.cuda.max_memory_allocated()/2**30)
            atomic_json(a.output/'status.json',status);print(json.dumps(status),flush=True);loss_acc=[]
        if step%a.eval_every==0 or step==a.steps:
            metrics=evaluate(ema,vloader,device);record=dict(step=step,seconds=time.time()-started,validation=metrics)
            with (a.output/'history.jsonl').open('a') as log:log.write(json.dumps(record)+'\n')
            if metrics['mae']<best:best=metrics['mae'];save('best',step)
            save('last',step);print(json.dumps(record),flush=True)
    atomic_json(a.output/'status.json',dict(state='completed',step=a.steps,best_validation_mae=best,seconds=time.time()-started));print('TRAINING COMPLETE',flush=True)

if __name__=='__main__':main()
