"""Replay sampling RNG only; require recorded hashes before reporting exposure."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import numpy as np
from aligned_cohort import AlignedCohort
from hard_sequence_sampling import load_hard_sets,replace_sequences
from prepare_conditioning_pilot import save,sha


def update(digest,index,ids):
    digest.update(np.asarray([index],dtype='<i8').tobytes())
    digest.update(np.asarray(ids,dtype='<i8').tobytes())


def main():
    p=argparse.ArgumentParser();p.add_argument('--run',type=Path,required=True);p.add_argument('--control',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    if a.output.exists():raise FileExistsError(a.output)
    run=json.loads((a.run/'run.json').read_text())
    if json.loads((a.run/'status.json').read_text())['state']!='complete':raise ValueError('Run incomplete')
    if sha(Path(__file__).with_name('hard_sequence_sampling.py'))!=run['hard_sampler_source_sha256']:raise ValueError('Sampler source changed')
    if sha(Path(run['hard_manifest']))!=run['hard_manifest_sha256']:raise ValueError('Manifest changed')
    history={r['step']:r for r in json.loads((a.run/'history.json').read_text())}
    control={r['step']:r for r in json.loads((a.control/'history.json').read_text())}
    caches=[AlignedCohort(Path(root),'train') for root in run['cohorts']]
    hard=load_hard_sets(Path(run['hard_manifest']),run['initial_head_sha256'],caches)
    rng=np.random.default_rng(run['seed']);hrng=np.random.default_rng(run['hard_rng_seed'])
    baseline=hashlib.sha256();actual=hashlib.sha256();draws=[0]*3;replacements=[0]*3
    before=[Counter() for _ in caches];after=[Counter() for _ in caches]
    for step in range(1,run['steps']+1):
        index=int(rng.choice(3,p=run['probabilities']));cache=caches[index]
        selected,starts,ids=cache.sample_window(rng,1,8)
        update(baseline,index,ids)
        replaced,count=replace_sequences(cache,selected,starts,ids,hard[index],hrng,run['hard_probability'])
        update(actual,index,replaced)
        draws[index]+=1;replacements[index]+=count
        before[index][selected[0][0]]+=1
        after[index][cache.rows[int(replaced[0,0])]['sequence_id']]+=1
        if step in history:
            h=history[step]
            if baseline.hexdigest()!=h['baseline_sample_schedule_sha256'] or baseline.hexdigest()!=control[step]['sample_schedule_sha256'] or actual.hexdigest()!=h['sample_schedule_sha256'] or sum(replacements)!=h['hard_draws']:
                raise ValueError('Sampling replay mismatch at '+str(step))
    result={'run':str(a.run),'run_sha256':sha(a.run/'run.json'),'test_used':False,'sampling_replay_verified':True,'cohorts':{}}
    for index,label in enumerate(('prior','high_effect','renderer_pilot')):
        hard_draws=sum(after[index][s] for s in hard[index])
        result['cohorts'][label]={'draws':draws[index],'replacement_branch_draws':replacements[index],
            'actual_hard_set_draws':hard_draws,'hard_set_fraction':hard_draws/draws[index],
            'sequences':[{'sequence_id':s,'hard':s in hard[index],'uniform_draws':before[index][s],
                          'actual_draws':after[index][s],'actual_to_uniform_ratio':after[index][s]/before[index][s] if before[index][s] else None}
                         for s in caches[index].sequence_ids]}
        print(json.dumps({'cohort':label,**{k:v for k,v in result['cohorts'][label].items() if k!='sequences'}}),flush=True)
    save(a.output,result)


if __name__=='__main__':main()
