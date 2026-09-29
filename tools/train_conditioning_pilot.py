"""Bounded renderer-feature ablation on a frozen causal parent.

The refiner is feed-forward: its output never feeds the frozen parent's state.
Parent predictions are generated causally over complete 64-frame streams.
Both arms have identical architecture, initialization, samples and schedule;
the control substitutes zero for the 17 renderer-feature channels.
"""
import argparse
from collections import defaultdict
import copy
import json
import math
from pathlib import Path
import time

import numpy as np
import torch
from torch import nn
from torch.nn import functional as F

from audit_conditioning_content import picture, sheet
from opennr_student import GatedBlock
from prepare_conditioning_pilot import save, sha
from train_capacity_temporal_student import _load_parent


class RendererRefiner(nn.Module):
    def __init__(self, width=48, blocks=3):
        super().__init__()
        self.stem = nn.Conv2d(28, width, 3, padding=1)
        self.blocks = nn.Sequential(*(GatedBlock(width) for _ in range(blocks)))
        self.head = nn.Conv2d(width, 48, 3, padding=1)
        nn.init.zeros_(self.head.weight)
        nn.init.zeros_(self.head.bias)

    def forward(self, rgb, parent, guides, conditioning, control=False):
        if conditioning is None:
            return parent  # explicit missing-feature bypass, never guessed material data
        low = torch.cat((F.avg_pool2d(rgb,4),F.avg_pool2d(parent,4),guides,
                         torch.zeros_like(conditioning) if control else conditioning),1)
        delta = F.pixel_shuffle(self.head(self.blocks(self.stem(low))),4)
        return (parent + .1*torch.tanh(delta.float())).clamp(0,1)


class Cache:
    def __init__(self, root):
        self.root = root
        self.complete = json.loads((root/'complete.json').read_text())
        if self.complete['schema'] != 'opennr-aligned-renderer-pilot-v1':
            raise ValueError('Wrong cache schema')
        if sha(root/'rows.json') != self.complete['rows_sha256']:
            raise ValueError('Row identity mismatch')
        self.rows = json.loads((root/'rows.json').read_text())
        self.arrays = {n:np.load(root/(n+'.npy'),mmap_mode='r')
                       for n in ('rgb','guides','context','conditioning')}
        for name,digest in self.complete['array_sha256'].items():
            if sha(root/(name+'.npy')) != digest:
                raise ValueError('Cache payload changed: '+name)
        self.streams = defaultdict(list)
        for i,r in enumerate(self.rows):
            self.streams[(r['split'],r['sequence_id'],r['eye'])].append(i)
        for key,ids in self.streams.items():
            if [self.rows[i]['frame_id'] for i in ids] != list(range(1,65)):
                raise ValueError('Noncontiguous stream '+str(key))
        self.parent = None

    def batch(self, ids):
        def tensor(x):
            return torch.from_numpy(np.array(x,copy=True)).cuda().float()
        colors = tensor(self.arrays['rgb'][ids])/255
        return (colors[:,0], colors[:,1], tensor(self.arrays['guides'][ids]),
                tensor(self.arrays['conditioning'][ids]), tensor(self.parent[ids]))


@torch.no_grad()
def prepare_parent(cache, checkpoint, output):
    model,_,_,_,_ = _load_parent(checkpoint)
    model.eval().requires_grad_(False)
    mapped = np.lib.format.open_memmap(output/'parent.npy',mode='w+',dtype='<f4',
                                      shape=(len(cache.rows),3,512,512))
    # Each eye is independent and starts with an explicit reset.
    for number,(key,ids) in enumerate(cache.streams.items(),1):
        state = None
        for i in ids:
            def tensor(name):
                return torch.from_numpy(np.array(cache.arrays[name][i:i+1],copy=True)).cuda().float()
            rgb = tensor('rgb')[:,0]/255
            with torch.autocast('cuda',dtype=torch.bfloat16):
                pred,state = model.forward_temporal(rgb,tensor('guides'),tensor('context'),state)
            if not torch.isfinite(pred).all():
                raise ValueError('Nonfinite parent output')
            mapped[i] = pred[0].float().cpu().numpy()
        mapped.flush()
        save(output/'status.json',{'status':'preparing_parent','streams_complete':number,
                                  'streams_total':len(cache.streams)})
        print(json.dumps({'parent_stream':number,'of':len(cache.streams),'sequence':key[1],'eye':key[2]}),flush=True)
    del model,mapped
    torch.cuda.empty_cache()
    save(output/'parent_provenance.json',{'checkpoint':str(checkpoint.resolve()),
        'checkpoint_sha256':sha(checkpoint),'parent_sha256':sha(output/'parent.npy'),
        'state':'causal parent only; refiner output not fed back','precision':'BF16 inference, lossless FP32 prediction cache'})
    cache.parent = np.load(output/'parent.npy',mmap_mode='r')


@torch.no_grad()
def evaluate(model,cache,split,control=False):
    if model is not None: model.eval()
    by_seq = defaultdict(list)
    abs_sum=sq_sum=delta_sum=identity_abs=0.0
    pixels=delta_pixels=0
    for (s,seq,eye),ids in cache.streams.items():
        if s != split: continue
        previous = None
        for start in range(0,len(ids),4):
            rgb,target,g,c,parent = cache.batch(ids[start:start+4])
            with torch.autocast('cuda',dtype=torch.bfloat16):
                pred = parent if model is None else model(rgb,parent,g,c,control)
            error = pred.float()-target
            if not torch.isfinite(error).all(): raise ValueError('Nonfinite evaluation')
            abs_sum += error.abs().sum().item()
            sq_sum += error.square().sum().item()
            identity_abs += (rgb-target).abs().sum().item()
            pixels += error.numel()
            by_seq[seq].extend(error.abs().mean((1,2,3)).tolist())
            for e in error:
                if previous is not None:
                    delta_sum += (e-previous).abs().sum().item()
                    delta_pixels += e.numel()
                previous = e
    return {'mae':abs_sum/pixels,'identity_mae':identity_abs/pixels,
            'psnr':-10*math.log10(max(sq_sum/pixels,1e-20)),
            'temporal_delta_mae':delta_sum/delta_pixels,
            'by_sequence':{k:float(np.mean(v)) for k,v in by_seq.items()},
            'eye_frames':pixels//(3*512*512)}


def train_arm(cache,output,steps,seed,control):
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)
    rng = np.random.default_rng(seed)
    model = RendererRefiner().cuda()
    optimizer = torch.optim.AdamW(model.parameters(),lr=1e-4,weight_decay=1e-4)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer,steps,eta_min=1e-5)
    keys = [k for k in cache.streams if k[0]=='train']
    name = 'control' if control else 'conditioned'
    arm = output/name
    arm.mkdir()
    best = evaluate(model,cache,'validation',control)
    best_step = 0
    initial = copy.deepcopy(model.state_dict())
    torch.save({'model':initial,'step':0,'validation':best},arm/'best.pt')
    started = time.time()
    for step in range(1,steps+1):
        model.train()
        pairs=[]
        for _ in range(2):
            stream = cache.streams[keys[int(rng.integers(len(keys)))]]
            start = int(rng.integers(63))
            pairs.extend(stream[start:start+2])
        rgb,target,g,c,parent = cache.batch(pairs)
        optimizer.zero_grad(set_to_none=True)
        with torch.autocast('cuda',dtype=torch.bfloat16):
            pred = model(rgb,parent,g,c,control)
            error = pred.float()-target
            delta = (error[1::2]-error[0::2]).abs().mean()
            tone = F.avg_pool2d(error,16).abs().mean()
            loss = error.abs().mean()+.12*delta+.1*tone
        if not torch.isfinite(loss): raise ValueError('Nonfinite training loss')
        loss.backward()
        norm = torch.nn.utils.clip_grad_norm_(model.parameters(),1.0,error_if_nonfinite=True)
        optimizer.step()
        scheduler.step()
        if step%50==0:
            status={'arm':name,'step':step,'steps':steps,'loss':float(loss.detach()),
                    'seconds':time.time()-started,'best_step':best_step,'best_validation_mae':best['mae'],
                    'peak_allocated_gib':torch.cuda.max_memory_allocated()/2**30}
            save(output/'status.json',status)
            print(json.dumps(status),flush=True)
        if step%200==0 or step==steps:
            metric=evaluate(model,cache,'validation',control)
            with (arm/'history.jsonl').open('a',encoding='utf-8') as f:
                f.write(json.dumps({'step':step,'validation':metric})+'\n')
            if metric['mae'] < best['mae']:
                best,best_step=metric,step
                torch.save({'model':model.state_dict(),'step':step,'validation':best},arm/'best.pt')
            torch.save({'model':model.state_dict(),'optimizer':optimizer.state_dict(),
                        'scheduler':scheduler.state_dict(),'step':step,'rng':rng.bit_generator.state},arm/'last.pt')
            print(json.dumps({'arm':name,'step':step,'validation':metric}),flush=True)
    selected=torch.load(arm/'best.pt',map_location='cuda',weights_only=False)
    model.load_state_dict(selected['model'])
    return model,{'selected_step':best_step,'validation':best,
                  'parameters':sum(p.numel() for p in model.parameters()),'seconds':time.time()-started}


@torch.no_grad()
def gallery(cache, models, output):
    cells=[]
    for key,ids in cache.streams.items():
        if key[0]!='validation': continue
        i=ids[31]
        rgb,target,g,c,parent=cache.batch([i])
        views=[('input',rgb),('teacher',target),('parent',parent)]
        for name,m in models.items():
            with torch.autocast('cuda',dtype=torch.bfloat16):
                pred=m(rgb,parent,g,c,name=='control')
            views.append((name,pred))
        for name,value in views:
            cells.append((f'{key[1].rsplit("-",1)[1]} E{key[2]} F32 {name}',
                          picture(value[0].float().cpu().numpy().transpose(1,2,0))))
    sheet(cells,3+len(models),output/'validation_samples.png',256)


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--cache',type=Path,required=True)
    p.add_argument('--parent',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--steps',type=int,default=1000)
    p.add_argument('--seed',type=int,default=347)
    a=p.parse_args()
    if a.steps<1: raise ValueError('Positive bounded steps required')
    if a.output.exists(): raise FileExistsError(a.output)
    a.output.mkdir(parents=True)
    torch.set_num_threads(4)
    torch.backends.cudnn.benchmark=False
    try:
        cache=Cache(a.cache)
        save(a.output/'run.json',{'architecture':'frozen_causal_parent_plus_renderer_refiner_v1',
            'parent':str(a.parent.resolve()),'parent_sha256':sha(a.parent),
            'cache':str(a.cache.resolve()),'cache_identity':sha(a.cache/'complete.json'),
            'steps_per_arm':a.steps,'seed':a.seed,'split':cache.complete['split'],
            'loss':'L1 + 0.12 adjacent temporal error delta + 0.10 pooled tone L1',
            'width':48,'blocks':3,'batch':'two consecutive pairs; 4 images',
            'selection':'validation MAE only; step zero eligible; test only after both selections',
            'legacy_gate':'parent frozen; missing conditionings bypass adapter exactly; no claim of old-cohort improvement',
            'limitations':'same-session holdouts; small feed-forward refiner not end-to-end conditioned recurrent training',
            'source_sha256':{n:sha(Path(__file__).parent/n) for n in
                             ('train_conditioning_pilot.py','prepare_conditioning_pilot.py','audit_conditioning_content.py')}})
        prepare_parent(cache,a.parent,a.output)
        baseline=evaluate(None,cache,'validation')
        save(a.output/'parent_validation.json',baseline)
        models,results={},{}
        for name in ('control','conditioned'):
            models[name],results[name]=train_arm(cache,a.output,a.steps,a.seed,name=='control')
            gallery(cache,models,a.output)
        # Frozen test is opened for metrics only once, after both selections.
        results['parent']={'validation':baseline,'test':evaluate(None,cache,'test')}
        for name,model in models.items():
            results[name]['test']=evaluate(model,cache,'test',name=='control')
        results['interpretation']={
            'conditioned_beats_parent_test':results['conditioned']['test']['mae']<results['parent']['test']['mae'],
            'conditioned_beats_control_test':results['conditioned']['test']['mae']<results['control']['test']['mae'],
            'promotion':False,'reason':'bounded same-session feature pilot; no independent conditioned cohort or live runtime acceptance'}
        save(a.output/'result.json',results)
        save(a.output/'status.json',{'status':'complete','steps_per_arm':a.steps,'result':'result.json'})
        print(json.dumps(results),flush=True)
    except Exception as e:
        save(a.output/'status.json',{'status':'failed','error':repr(e)})
        raise


if __name__=='__main__': main()
