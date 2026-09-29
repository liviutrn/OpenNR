"""Target-assisted per-image fitting diagnostic. Not an inference model or validation score."""
import argparse
import json
from pathlib import Path
import numpy as np
import torch
from torch.nn import functional as F
from aligned_cohort import AlignedCohort
from prepare_conditioning_pilot import save, sha
from train_capacity_temporal_student import _load_parent
from audit_conditioning_content import picture, sheet


def apply_coefficients(parent, raw):
    coefficients=F.interpolate(raw,size=parent.shape[-2:],mode='bilinear',align_corners=False)
    n,_,h,w=parent.shape
    matrix=.25*coefficients[:,:9].tanh().reshape(n,3,3,h,w)
    bias=.15*coefficients[:,9:].tanh()
    return (parent+(matrix*parent[:,None]).sum(2)+bias).clamp(0,1)


def fit_image(parent,target,downsample,steps=200):
    raw=torch.zeros(parent.shape[0],12,*(d//downsample for d in parent.shape[-2:]),device=parent.device,requires_grad=True)
    optimizer=torch.optim.Adam([raw],lr=.03)
    best=float((parent-target).abs().mean());best_image=parent.detach().clone();history=[]
    for step in range(steps+1):
        prediction=apply_coefficients(parent,raw)
        loss=(prediction-target).abs().mean()
        if not torch.isfinite(loss):raise ValueError('Nonfinite oracle loss')
        value=float(loss.detach())
        if value<best:best=value;best_image=prediction.detach().clone()
        if step%50==0 or step==steps:history.append({'step':step,'mae':value,'best_mae':best})
        if step<steps:
            optimizer.zero_grad(set_to_none=True);loss.backward();optimizer.step()
    return best_image,history


def main():
    p=argparse.ArgumentParser();p.add_argument('--fit-report',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    if a.output.exists():raise FileExistsError(a.output)
    a.output.mkdir(parents=True);torch.set_num_threads(4)
    fit=json.loads(a.fit_report.read_text());path=Path(fit['checkpoint'])
    if sha(path)!=fit['sha256']:raise ValueError('Parent mismatch')
    model,payload,*_=_load_parent(path);model.eval().requires_grad_(False)
    report={'scope':'TRAINING ONLY, TARGET-ASSISTED PER-IMAGE FIT; NOT DEPLOYABLE OR HELD-OUT PERFORMANCE',
        'parent_sha256':sha(path),'fit_report_sha256':sha(a.fit_report),'source_sha256':sha(Path(__file__)),
        'test_used':False,'frame':32,'steps':200,'learning_rate':.03,'images':[],
        'caveat':'A good fit demonstrates attainable representation on these images, not predictability from inputs. A poor fit does not prove a representation limit because optimization is finite.'}
    try:
        for label,root in zip(('prior','high_effect','renderer_pilot'),payload['run']['cohorts']):
            cache=AlignedCohort(Path(root),'train');errors=fit['cohorts'][label]['train']['sequence_mae']
            if set(errors)!=set(cache.sequence_ids):raise ValueError('Train membership mismatch')
            ordered=sorted(errors,key=lambda s:(errors[s],s));picks=[ordered[len(ordered)//2],ordered[-1]]
            for seq in picks:
                for eye in (0,1):
                    state=None
                    with torch.no_grad():
                        for i in cache.streams[seq,eye][:32]:
                            def tensor(x):return torch.from_numpy(np.array(x,copy=True)).cuda().float()
                            color=tensor(cache.rgb[i:i+1])/255;rgb,target=color[:,0],color[:,1]
                            g=tensor(cache.guides[i:i+1]);c=tensor(cache.context[i:i+1])
                            with torch.autocast('cuda',dtype=torch.bfloat16):base,state=model.forward_temporal(rgb,g,c,state)
                    base=base.float().detach();row={'cohort':label,'sequence':seq,'eye':eye,'parent_mae':float((base-target).abs().mean()),'fits':{}}
                    views=[('input',rgb),('teacher',target),('parent',base)]
                    for grid in (16,4):
                        fitted,history=fit_image(base,target,grid)
                        row['fits'][str(grid)]=history;views.append((f'TARGET-FITTED 1/{grid} NOT MODEL',fitted))
                    sheet([(name,picture(value[0].cpu().numpy().transpose(1,2,0))) for name,value in views],5,a.output/f'{seq}-eye{eye}.png',512)
                    report['images'].append(row);save(a.output/'partial.json',report)
                    print(json.dumps({'sequence':seq,'eye':eye,'parent':row['parent_mae'],'oracle_best':{k:v[-1]['best_mae'] for k,v in row['fits'].items()}}),flush=True)
        save(a.output/'result.json',report);save(a.output/'status.json',{'state':'complete','test_used':False})
    except Exception as e:
        save(a.output/'status.json',{'state':'failed','error':repr(e)});raise


if __name__=='__main__':main()
