"""Continue both completed semantic-mixture arms with restored optimizer/RNG."""
import argparse
import hashlib
import json
import time
from pathlib import Path
import numpy as np
import torch

from joint_parent_tone_model import JointParentToneModel
from prepare_conditioning_pilot import save, sha
from semantic_tone_head import SemanticToneHead
from train_capacity_temporal_student import _load_parent
from train_semantic_parent_replication import cohort
from train_spatial_tone import frame_objective
from train_temporal_student import _device_batch, evaluate_streaming


def run_arm(resume, output, steps):
    if output.exists(): raise FileExistsError(output)
    payload = torch.load(resume, map_location='cpu', weights_only=False)
    old = payload['run']; start = int(payload['step'])
    if old.get('architecture') != 'semantic_joint_parent_mixture_v1' or steps <= start:
        raise ValueError('Expected completed semantic mixture arm')
    if json.loads((resume.parent / 'status.json').read_text()).get('state') != 'complete':
        raise ValueError('Arm is not complete')
    parent, *_ = _load_parent(Path(old['parent'])); parent.load_state_dict(payload['parent_model'], strict=True)
    head = SemanticToneHead(False).cuda(); head.load_state_dict(payload['head'], strict=True)
    model = JointParentToneModel(parent, head)
    optimizer = torch.optim.AdamW([
        {'params': [v for v in head.parameters() if v.requires_grad], 'lr': old['learning_rate']},
        {'params': list(parent.parameters()), 'lr': old['parent_learning_rate']}], weight_decay=1e-4)
    optimizer.load_state_dict(payload['optimizer'])
    rng = np.random.default_rng(); rng.bit_generator.state = payload['numpy_rng_state']
    torch.set_rng_state(payload['torch_rng_state'].cpu()); torch.cuda.set_rng_state_all([v.cpu() for v in payload['cuda_rng_state']])
    labels = old['cohort_labels']; probabilities = old['mixture_probabilities']
    train = [cohort(Path(root), 'train') for root in old['cohorts']]; validation = [cohort(Path(root), 'validation') for root in old['cohorts']]
    if [c.sequence_ids for c in train] != old['training_sequences'] or [c.sequence_ids for c in validation] != old['validation_sequences']:
        raise ValueError('Sequence membership changed')
    baseline = payload['common_start_validation']; digest = hashlib.sha256(); draws = {label: 0 for label in labels}
    run = dict(old, steps=steps, continuation_start_step=start, resume=str(resume.resolve()), resume_sha256=sha(resume),
               predecessor_history_sha256=sha(resume.parent / 'history.json'), optimizer_restored=True, rng_restored=True,
               continuation_source_sha256=sha(Path(__file__)), test_used=False)
    output.mkdir(parents=True); save(output / 'run.json', run)
    save(output / 'resume_verification.json', {'resume_sha256': sha(resume), 'step': start,
         'optimizer_restored': True, 'numpy_rng_restored': True, 'torch_cuda_rng_restored': True, 'test_used': False})
    history=[]; started=time.time()

    def checkpoint(step, metrics):
        torch.save({'architecture': run['architecture'], 'head': head.state_dict(), 'parent_model': parent.state_dict(),
                    'run': run, 'step': step, 'validation': metrics, 'optimizer': optimizer.state_dict(),
                    'numpy_rng_state': rng.bit_generator.state, 'torch_rng_state': torch.get_rng_state(),
                    'cuda_rng_state': torch.cuda.get_rng_state_all(), 'common_start_validation': baseline,
                    'sample_sha256': digest.hexdigest(), 'draws': dict(draws)}, output / 'last.pt.tmp')
        (output / 'last.pt.tmp').replace(output / 'last.pt')
        save(output / f'checkpoint_{step}_identity.json', {'step': step, 'sha256': sha(output / 'last.pt'), 'test_used': False})

    def evaluate(step):
        metrics={}
        for label, cache in zip(labels, validation):
            save(output / 'status.json', {'state':'evaluating','step':step,'cohort':label})
            metrics[label]=evaluate_streaming(model, cache, batch=4)
        if step==start:
            diff={label:{k:abs(metrics[label][k]-payload['validation'][label][k]) for k in ('mae','psnr','temporal_delta_mae','first_frame_mae')} for label in labels}
            if any(v>1e-7 for d in diff.values() for v in d.values()): raise ValueError('Predecessor replay mismatch: '+str(diff))
            save(output/'predecessor_replay.json',{'step':step,'differences':diff,'test_used':False})
        ratios=[metrics[label]['mae']/baseline[label]['mae'] for label in labels]
        history.append({'step':step,'validation':metrics,'ratios':ratios,'all_cohorts_improved':all(v<1 for v in ratios),
                        'sample_sha256':digest.hexdigest(),'draws':dict(draws),'seconds':time.time()-started})
        save(output/'history.json',history); checkpoint(step,metrics)
        print(json.dumps({'role':run['mixture_role'],'step':step,'mae':{l:m['mae'] for l,m in metrics.items()},'all_cohorts_improved':all(v<1 for v in ratios)}),flush=True)

    evaluate(start)
    for step in range(start+1,steps+1):
        index=int(rng.choice(len(train),p=probabilities)); _,_,ids=train[index].sample_window(rng,1,8)
        digest.update(np.asarray([index],dtype='<i8').tobytes()); digest.update(np.asarray(ids,dtype='<i8').tobytes())
        rgb,target,guides,context=_device_batch(train[index].load_window(ids)); rgb,target=rgb.float()/255,target.float()/255; guides,context=guides.float(),context.float()
        model.train(); optimizer.zero_grad(set_to_none=True); state=previous=None; losses=[]
        for frame in range(8):
            with torch.set_grad_enabled(frame>=2),torch.autocast('cuda',dtype=torch.bfloat16):
                pred,state=model.forward_temporal(rgb[:,frame],guides[:,frame],context[:,frame],state); error=pred.float()-target[:,frame]
                if frame>=2: losses.append(frame_objective(error,previous))
                previous=error if frame>=2 else error.detach()
        loss=torch.stack(losses).mean()
        if not torch.isfinite(loss): raise ValueError('Nonfinite continuation loss')
        loss.backward(); torch.nn.utils.clip_grad_norm_(head.parameters(),1,error_if_nonfinite=True); torch.nn.utils.clip_grad_norm_(parent.parameters(),1,error_if_nonfinite=True); optimizer.step(); draws[labels[index]]+=1
        if step==start+1 or step%25==0: save(output/'status.json',{'state':'training','step':step,'steps':steps,'loss':float(loss.detach()),'seconds':time.time()-started,'gpu_peak_gib':torch.cuda.max_memory_allocated()/2**30})
        if step==steps: evaluate(step)
    save(output/'status.json',{'state':'complete','steps':steps,'test_used':False,'seconds':time.time()-started})
    del model,parent,head,optimizer; torch.cuda.empty_cache()


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--root',type=Path,required=True);p.add_argument('--steps',type=int,default=3200);a=p.parse_args()
    if a.steps<=1600: raise ValueError('Continuation must extend update1600')
    run_arm(a.root/'original_control'/'last.pt',a.root/'continuation_3200_original',a.steps)
    run_arm(a.root/'rebalanced_candidate'/'last.pt',a.root/'continuation_3200_rebalanced',a.steps)
    save(a.root/'continuation_pair.json',{'steps':a.steps,'test_used':False,'original':str((a.root/'continuation_3200_original').resolve()),'rebalanced':str((a.root/'continuation_3200_rebalanced').resolve())})
    save(a.root/'continuation_status.json',{'state':'complete','test_used':False})


if __name__=='__main__': main()
