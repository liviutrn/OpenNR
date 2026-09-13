"""Full-parent continuation across three preserved training/validation cohorts.

All weights train. No frozen-test access. Fixed seed/recipe compares existing
guide caches with corrected native-coordinate overlays. Selection requires
improvement on every validation cohort over the arm's parent baseline.
"""
import argparse
from copy import deepcopy
from dataclasses import asdict
import json
import math
from pathlib import Path
import time
import numpy as np
import torch
import torch.nn.functional as F
from aligned_cohort import AlignedCohort
from prepare_conditioning_pilot import save,sha
from train_capacity_temporal_student import _load_parent
from train_temporal_student import evaluate_streaming,_device_batch,_augment_sequence


def checkpoint(path,model,optimizer,step,run,metrics,rng):
    payload={'architecture':model.architecture,'base_config':asdict(model.config),
             'temporal_config':asdict(model.temporal_config),'capacity_config':asdict(model.capacity_config),
             'model':model.state_dict(),'optimizer':optimizer.state_dict(),'step':step,
             'run':run,'validation':metrics,'rng':rng.bit_generator.state,
             'torch_rng':torch.get_rng_state(),'cuda_rng':torch.cuda.get_rng_state_all()}
    tmp=path.with_suffix('.tmp')
    torch.save(payload,tmp)
    tmp.replace(path)


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--parent',type=Path,required=True)
    p.add_argument('--cohort',action='append',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--legacy-guides',action='store_true')
    p.add_argument('--steps',type=int,default=1200)
    p.add_argument('--seed',type=int,default=351)
    p.add_argument('--eval-every',type=int,default=400)
    p.add_argument('--probabilities',type=float,nargs=3,default=[.5,.3,.2])
    p.add_argument('--learning-rate',type=float,default=2e-6)
    p.add_argument('--selection-baseline',type=Path,help='Recorded original-parent validation baseline; never test metrics')
    a=p.parse_args()
    if len(a.cohort)!=3 or a.steps<1: raise ValueError('Exactly three cohorts and positive steps required')
    if any(not math.isfinite(v) or v<0 for v in a.probabilities) or not math.isclose(sum(a.probabilities),1.):
        raise ValueError('Three nonnegative probabilities must sum to one')
    if not math.isfinite(a.learning_rate) or a.learning_rate<=0: raise ValueError('Positive finite learning rate required')
    if a.output.exists(): raise FileExistsError(a.output)
    a.output.mkdir(parents=True)
    try:
        torch.set_num_threads(4)
        torch.manual_seed(a.seed);torch.cuda.manual_seed_all(a.seed)
        torch.backends.cudnn.benchmark=False
        rng=np.random.default_rng(a.seed)
        train=[AlignedCohort(r,'train',a.legacy_guides) for r in a.cohort]
        val=[AlignedCohort(r,'validation',a.legacy_guides) for r in a.cohort]
        memberships={}
        for dataset in train+val:
            for seq in dataset.sequence_ids:
                if seq in memberships and memberships[seq]!=dataset.split:
                    raise ValueError('Cross-cohort split leakage')
                memberships[seq]=dataset.split
        model,parent,base,temporal,capacity=_load_parent(a.parent)
        # The full existing model is loaded strictly, without branch reinitialization.
        optimizer=torch.optim.AdamW(model.parameters(),lr=a.learning_rate,weight_decay=1e-4)
        scheduler=torch.optim.lr_scheduler.CosineAnnealingLR(optimizer,a.steps,eta_min=a.learning_rate/10)
        ema=deepcopy(model).eval()
        run={'parent':str(a.parent.resolve()),'parent_sha256':sha(a.parent),
             'cohorts':[str(r.resolve()) for r in a.cohort],
             'cohort_complete_sha256':[sha(r/'complete.json') for r in a.cohort],
             'guide_mode':'existing-cache' if a.legacy_guides else 'corrected-native-coordinates',
             'probabilities':a.probabilities,'steps':a.steps,'seed':a.seed,'window':8,'burn_in':2,'batch':1,
             'trainable_parameters':sum(p.numel() for p in model.parameters()),
             'learning_rate':[a.learning_rate,a.learning_rate/10],'loss':'L1 + .12 adjacent error-delta L1 + .1 pooled tone L1',
             'ema_update':.01,'selection':'all three validation cohorts improve parent, then mean relative MAE',
             'test_used':False,'source_sha256':sha(Path(__file__)),
             'training_sequences':[c.sequence_ids for c in train],
             'validation_sequences':[c.sequence_ids for c in val]}
        selection_reference=None
        if a.selection_baseline:
            selection_reference=json.loads(a.selection_baseline.read_text())
            for label,cache in zip(('prior','high_effect','renderer_pilot'),val):
                reference=selection_reference[label]
                if reference['split']!='validation' or set(reference['sequence_mae'])!=set(cache.sequence_ids):
                    raise ValueError('Selection baseline must match exact validation sequences')
            run['selection_baseline']={'path':str(a.selection_baseline.resolve()),'sha256':sha(a.selection_baseline)}
            save(a.output/'selection_baseline.json',selection_reference)
        save(a.output/'run.json',run)
        started=time.time()
        baseline=None;best_score=math.inf;best_all_score=1.;best_all_step=0
        history=[]
        def validate(step):
            nonlocal baseline,best_score,best_all_score,best_all_step
            metrics={}
            for label,cache in zip(('prior','high_effect','renderer_pilot'),val):
                save(a.output/'status.json',{'state':'evaluating','step':step,'domain':label,'seconds':time.time()-started})
                metrics[label]=evaluate_streaming(ema,cache,batch=4)
                print(json.dumps({'step':step,'domain':label,'mae':metrics[label]['mae']}),flush=True)
            if baseline is None:
                baseline=metrics
                save(a.output/'baseline.json',baseline)
            reference=selection_reference if selection_reference is not None else baseline
            ratio={key:metrics[key]['mae']/reference[key]['mae'] for key in metrics}
            score=float(np.mean(list(ratio.values())))
            record={'step':step,'validation':metrics,'relative_mae':ratio,'mean_relative_mae':score,
                    'all_cohorts_improved':all(v<1 for v in ratio.values()),'seconds':time.time()-started}
            history.append(record)
            save(a.output/'history.json',history)
            if score<best_score:
                best_score=score
                checkpoint(a.output/'best_mean.pt',ema,optimizer,step,run,metrics,rng)
            if record['all_cohorts_improved'] and score<best_all_score:
                best_all_score=score;best_all_step=step
                checkpoint(a.output/'best_all_cohorts.pt',ema,optimizer,step,run,metrics,rng)
            checkpoint(a.output/'last.pt',model,optimizer,step,run,metrics,rng)
            save(a.output/'selection.json',{'best_all_step':best_all_step,'best_all_score':best_all_score,
                 'best_mean_score':best_score,'promotion':False,'test_used':False})
        validate(0)
        for step in range(1,a.steps+1):
            domain=int(rng.choice(3,p=a.probabilities))
            cache=train[domain]
            _,_,ids=cache.sample_window(rng,1,8)
            rgb,target,g,c=_device_batch(cache.load_window(ids))
            rgb=rgb.float()/255;target=target.float()/255;g=g.float();c=c.float()
            rgb,target,g,c=_augment_sequence(rgb,target,g,c,rng)
            model.train();optimizer.zero_grad(set_to_none=True)
            state=None;previous_error=None;losses=[]
            for f in range(8):
                if f<2:
                    with torch.no_grad(),torch.autocast('cuda',dtype=torch.bfloat16):
                        pred,state=model.forward_temporal(rgb[:,f],g[:,f],c[:,f],state)
                    previous_error=pred.float()-target[:,f]
                    continue
                with torch.autocast('cuda',dtype=torch.bfloat16):
                    pred,state=model.forward_temporal(rgb[:,f],g[:,f],c[:,f],state)
                    error=pred.float()-target[:,f]
                    loss=error.abs().mean()+.1*F.avg_pool2d(error,16).abs().mean()
                    loss=loss+.12*(error-previous_error).abs().mean()
                losses.append(loss);previous_error=error
            loss=torch.stack(losses).mean()
            if not torch.isfinite(loss): raise ValueError('Nonfinite loss')
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(),1.,error_if_nonfinite=True)
            optimizer.step();scheduler.step()
            with torch.no_grad():
                for e,m in zip(ema.parameters(),model.parameters()): e.lerp_(m,.01)
            if step%25==0 or step==1:
                status={'state':'training','step':step,'steps':a.steps,'domain':domain,
                        'loss':float(loss.detach()),'seconds':time.time()-started,
                        'peak_allocated_gib':torch.cuda.max_memory_allocated()/2**30}
                save(a.output/'status.json',status);print(json.dumps(status),flush=True)
            if step%a.eval_every==0 or step==a.steps: validate(step)
        save(a.output/'status.json',{'state':'complete','step':a.steps,'best_all_step':best_all_step,
                                   'seconds':time.time()-started,'test_used':False})
    except Exception as e:
        save(a.output/'status.json',{'state':'failed','error':repr(e)})
        raise


if __name__=='__main__': main()
