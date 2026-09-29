"""Bounded six-training-clip fit probe. Never a held-out or production result."""
import argparse
from pathlib import Path
import json
import time
import numpy as np
import torch
from aligned_cohort import AlignedCohort
from prepare_conditioning_pilot import save,sha
from train_capacity_temporal_student import _load_parent
from train_temporal_student import evaluate_streaming,_device_batch
from train_aligned_multicohort import checkpoint


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--fit-report',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    if a.output.exists():raise FileExistsError(a.output)
    a.output.mkdir(parents=True)
    torch.set_num_threads(4);torch.manual_seed(354);torch.cuda.manual_seed_all(354)
    rng=np.random.default_rng(354)
    fit=json.loads(a.fit_report.read_text())
    parent=Path(fit['checkpoint'])
    if sha(parent)!=fit['sha256']:raise ValueError('Fit report checkpoint mismatch')
    model,payload,*_=_load_parent(parent)
    caches=[];selected={}
    for label,root in zip(('prior','high_effect','renderer_pilot'),payload['run']['cohorts']):
        cache=AlignedCohort(Path(root),'train')
        errors=fit['cohorts'][label]['train']['sequence_mae']
        if set(errors)!=set(cache.sequence_ids):raise ValueError('Training membership mismatch')
        ordered=sorted(errors,key=lambda seq:(errors[seq],seq))
        picks=[ordered[len(ordered)//2],ordered[-1]]
        selected[label]=picks
        cache.streams={key:ids for key,ids in cache.streams.items() if key[0] in picks}
        caches.append(cache)
    run={'parent':str(parent),'parent_sha256':sha(parent),'fit_report_sha256':sha(a.fit_report),
         'seed':354,'steps':600,'learning_rate':1e-5,'window':8,'burn_in':2,
         'loss':'L1 only; no augmentation, no EMA','selection':selected,'test_used':False,
         'scope':'concentrated training-only fitting diagnostic; not deployable or held-out success',
         'source_sha256':sha(Path(__file__))}
    save(a.output/'run.json',run)
    optimizer=torch.optim.AdamW(model.parameters(),lr=1e-5,weight_decay=0.)
    started=time.time();history=[]
    def evaluate(step):
        metrics={}
        for label,cache in zip(selected,caches):
            with torch.no_grad():metrics[label]=evaluate_streaming(model,cache,batch=4)
        history.append({'step':step,'training':metrics})
        save(a.output/'history.json',history)
        print(json.dumps({'step':step,'training_mae':{k:v['mae'] for k,v in metrics.items()}}),flush=True)
    try:
        evaluate(0)
        for step in range(1,601):
            cache=caches[(step-1)%3]
            _,_,ids=cache.sample_window(rng,1,8)
            rgb,target,g,c=_device_batch(cache.load_window(ids))
            rgb=rgb.float()/255;target=target.float()/255;g=g.float();c=c.float()
            model.train();optimizer.zero_grad(set_to_none=True)
            state=None;losses=[]
            for f in range(8):
                if f<2:
                    with torch.no_grad(),torch.autocast('cuda',dtype=torch.bfloat16):
                        _,state=model.forward_temporal(rgb[:,f],g[:,f],c[:,f],state)
                    continue
                with torch.autocast('cuda',dtype=torch.bfloat16):
                    pred,state=model.forward_temporal(rgb[:,f],g[:,f],c[:,f],state)
                    losses.append((pred.float()-target[:,f]).abs().mean())
            loss=torch.stack(losses).mean()
            if not torch.isfinite(loss):raise ValueError('Nonfinite loss')
            loss.backward();torch.nn.utils.clip_grad_norm_(model.parameters(),1.,error_if_nonfinite=True)
            optimizer.step()
            if step%25==0:
                status={'state':'training','step':step,'loss':float(loss.detach()),'seconds':time.time()-started}
                save(a.output/'status.json',status);print(json.dumps(status),flush=True)
            if step%200==0:evaluate(step)
        checkpoint(a.output/'diagnostic_only.pt',model,optimizer,600,run,{},rng)
        save(a.output/'status.json',{'state':'complete','test_used':False,'seconds':time.time()-started})
    except Exception as e:
        save(a.output/'status.json',{'state':'failed','error':repr(e)})
        raise


if __name__=='__main__':main()
