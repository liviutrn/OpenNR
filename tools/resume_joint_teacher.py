"""Strict continuation of a completed, verified uniform joint-teacher run."""
import json
from pathlib import Path
import numpy as np
import torch
from prepare_conditioning_pilot import save,sha


def restore_resume(source, output, run, model_head, optimizer, caches, rng, sample_digest, base_digest):
    source=Path(source)
    status=json.loads((source/'status.json').read_text())
    verification=json.loads((source/'final_checkpoint_verification.json').read_text())
    if status['state']!='complete' or verification['test_used']:
        raise ValueError('Resume requires completed no-test verified source')
    checkpoint=source/'last_resumable.pt'; checkpoint_sha=sha(checkpoint)
    payload=torch.load(checkpoint,map_location='cpu',weights_only=False)
    old=payload['run']; step=payload['step']
    if old.get('architecture')!='stable_unet_teacher_mode' or old.get('hard_manifest'):
        raise ValueError('Only uniform joint teacher continuation supported')
    if run['steps']<=step or step!=old['steps'] or step!=verification['step']:
        raise ValueError('Invalid continuation endpoint')
    allowed={'steps','trainer_source_sha256'}
    differences={key for key in set(old)|set(run) if old.get(key)!=run.get(key)}
    if differences-allowed:
        raise ValueError(f'Continuation would change recipe: {sorted(differences-allowed)}')
    if sha(source/'last.pt')!=verification['sha256']:
        raise ValueError('Final checkpoint identity changed')
    final=torch.load(source/'last.pt',map_location='cpu',weights_only=False)
    if set(payload['head'])!=set(final['head']) or any(not torch.equal(value,final['head'][key]) for key,value in payload['head'].items()):
        raise ValueError('Resumable weights differ from verified final weights')
    history=payload['history']
    if history!=json.loads((source/'history.json').read_text()) or history[-1]['step']!=step:
        raise ValueError('Resume history mismatch')
    for label,record in verification['cohorts'].items():
        for metric in ('mae','psnr','temporal_delta_mae'):
            if abs(history[-1]['validation'][label][metric]-record['metrics'][metric])>1e-7:
                raise ValueError('Verified resume metrics mismatch')
    # SHA256 internal state is not serialized. Rebuild it from the exact sampler.
    replay=np.random.default_rng(run['seed']); recorded={entry['step']:entry for entry in history}
    draws={label:0 for label in run['cohort_labels']}
    for update in range(1,step+1):
        j=int(replay.choice(len(caches),p=run['probabilities']))
        _,_,ids=caches[j].sample_window(replay,1,8)
        for digest in (sample_digest,base_digest):
            digest.update(np.asarray([j],dtype='<i8').tobytes())
            digest.update(np.asarray(ids,dtype='<i8').tobytes())
        draws[run['cohort_labels'][j]]+=1
        if update in recorded:
            entry=recorded[update]
            if sample_digest.hexdigest()!=entry['sample_schedule_sha256'] or base_digest.hexdigest()!=entry['baseline_sample_schedule_sha256'] or draws!=entry['cohort_draws']:
                raise ValueError('Historical sample replay mismatch')
    if replay.bit_generator.state!=payload['numpy_rng_state']:
        raise ValueError('Sampler RNG state mismatch')
    model_head.load_state_dict(payload['head'],strict=True)
    optimizer.load_state_dict(payload['optimizer'])
    if any(group['lr']!=run['learning_rate'] for group in optimizer.param_groups):
        raise ValueError('Resumed optimizer learning rate mismatch')
    rng.bit_generator.state=payload['numpy_rng_state']
    torch.set_rng_state(payload['torch_rng_state'])
    torch.cuda.set_rng_state_all(payload['cuda_rng_state'])
    if sha(checkpoint)!=checkpoint_sha:raise ValueError('Resume checkpoint changed')
    selected=torch.load(source/'best_all_cohorts.pt',map_location='cpu',weights_only=False)
    run.update(resume_checkpoint=str(checkpoint),resume_checkpoint_sha256=checkpoint_sha,
               resume_step=step,resume_helper_sha256=sha(Path(__file__)),
               optimizer_initialization='restored moments and RNG; continuation of verified control')
    selected['run']=run
    torch.save(selected,output/'best_all_cohorts.pt')
    save(output/'run.json',run);save(output/'history.json',history)
    save(output/'resume_preflight.json',dict(step=step,sample_schedule_sha256=sample_digest.hexdigest(),
         source_final_sha256=verification['sha256'],resume_sha256=checkpoint_sha,
         optimizer_restored=True,rng_restored=True,baseline_replay_pending=True,test_used=False))
    return step,history,status['best_score'],draws,payload['hard_rng_state']
