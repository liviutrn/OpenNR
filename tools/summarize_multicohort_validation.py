"""Reconcile sequence-level validation changes; never reads test examples."""
import argparse
import json
from pathlib import Path
import numpy as np
from prepare_conditioning_pilot import save,sha


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--run',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    history=json.loads((a.run/'history.json').read_text())
    baseline=history[0]['validation']
    records=[]
    for entry in history[1:]:
        domains={}
        for name,current in entry['validation'].items():
            original=baseline[name]
            keys=sorted(original['sequence_mae'])
            if set(keys)!=set(current['sequence_mae']): raise ValueError('Sequence denominator changed')
            if current['frames']!=original['frames']: raise ValueError('Frame denominator changed')
            changes=np.array([current['sequence_mae'][k]-original['sequence_mae'][k] for k in keys])
            point=current['mae']-original['mae']
            # All audited streams have the same 64-frame length and two eyes.
            if abs(changes.mean()-point)>1e-8: raise ValueError('Sequence mean does not reconcile')
            rng=np.random.default_rng(700)
            bootstrap=changes[rng.integers(len(keys),size=(10000,len(keys)))].mean(1)
            domains[name]={'sequences':len(keys),'eye_frames':current['frames'],
                'parent_mae':original['mae'],'candidate_mae':current['mae'],'mae_change':point,
                'improved_sequences':int((changes<0).sum()),'regressed_sequences':int((changes>0).sum()),
                'median_sequence_change':float(np.median(changes)),
                'descriptive_paired_sequence_bootstrap_95':np.quantile(bootstrap,[.025,.975]).tolist(),
                'temporal_delta_change':current['temporal_delta_mae']-original['temporal_delta_mae'],
                'worst_regressions':sorted([{'sequence':k,'change':float(v)} for k,v in zip(keys,changes)],
                                           key=lambda x:x['change'],reverse=True)[:5]}
        records.append({'step':entry['step'],'domains':domains,'all_cohorts_improved':entry['all_cohorts_improved']})
    result={'source_history_sha256':sha(a.run/'history.json'),'records':records,
            'scope':'validation only; paired sequence changes; descriptive bootstrap not adjusted for checkpoint selection',
            'caveats':'latest cohort has only two validation sequences; related scenes and repeated validation limit independence'}
    save(a.output,result)
    for record in records:
        print(json.dumps({'step':record['step'],'domains':{k:{x:v[x] for x in
            ('mae_change','improved_sequences','regressed_sequences','descriptive_paired_sequence_bootstrap_95')}
            for k,v in record['domains'].items()}}),flush=True)


if __name__=='__main__': main()
