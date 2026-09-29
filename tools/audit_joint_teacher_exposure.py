"""Reproduce recorded sampling from metadata; no image loads, optimizer or GPU."""
import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import numpy as np
from aligned_cohort import AlignedCohort
from prepare_conditioning_pilot import save, sha


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--run',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    run=json.loads((args.run/'run.json').read_text())
    history=json.loads((args.run/'history.json').read_text())
    if run.get('hard_manifest') or run['test_used']:
        raise ValueError('Only uniform no-test runs supported')
    if sha(Path(__file__).with_name('aligned_cohort.py'))!=run['loader_source_sha256']:
        raise ValueError('Sampler source changed')
    caches=[]; sources={}
    for j,root in enumerate(run['cohorts']):
        root=Path(root); complete=json.loads((root/'complete.json').read_text())
        if sha(root/'complete.json')!=run['cohort_complete_sha256'][j]:
            raise ValueError('Cache identity changed')
        renderer=complete['schema']=='opennr-aligned-renderer-pilot-v1'
        rows_path=(root if renderer else Path(complete['source_cache']))/'rows.json'
        expected=complete['rows_sha256'] if renderer else complete['source_rows_sha256']
        if sha(rows_path)!=expected:raise ValueError('Row identity changed')
        sources[str(rows_path)]=expected
        rows=json.loads(rows_path.read_text()); groups=defaultdict(list)
        for i,row in enumerate(rows):
            if row['split']=='train':groups[row['sequence_id'],row['eye']].append(i)
        streams={}
        for key,indices in groups.items():
            indices.sort(key=lambda i:rows[i]['frame_id'])
            if [rows[i]['frame_id'] for i in indices]!=list(range(1,65)):
                raise ValueError('Non64 stream')
            streams[key]=np.asarray(indices,dtype=np.int64)
        if sorted({key[0] for key in streams})!=run['training_sequences'][j]:
            raise ValueError('Training membership changed')
        caches.append(SimpleNamespace(streams=streams))
    counts=[Counter() for _ in caches]; draws=[0]*len(caches)
    digest=hashlib.sha256(); rng=np.random.default_rng(run['seed'])
    recorded={entry['step']:entry for entry in history}
    checks=[]
    for step in range(1,max(recorded)+1):
        j=int(rng.choice(len(caches),p=run['probabilities']))
        _,_,indices=AlignedCohort.sample_window(caches[j],rng,1,8)
        digest.update(np.asarray([j],dtype='<i8').tobytes())
        digest.update(np.asarray(indices,dtype='<i8').tobytes())
        counts[j].update(map(int,indices[:,2:].ravel()));draws[j]+=1
        if step in recorded:
            expected=recorded[step]
            if digest.hexdigest()!=expected['sample_schedule_sha256'] or digest.hexdigest()!=expected['baseline_sample_schedule_sha256']:
                raise ValueError(f'Sample replay mismatch at{step}')
            if dict(zip(run['cohort_labels'],draws))!=expected['cohort_draws']:
                raise ValueError('Draw mismatch')
            checks.append(dict(step=step,sha256=digest.hexdigest()))
    report=dict(scope='Direct loss-bearing frame exposure in this bounded run only; not all historic pretraining',
                caveats=['Adjacent video frames are correlated; frame counts are not independent-example counts',
                         'Probe and broad recipes differ; exposure is not a causal explanation or convergence proof',
                         'First two frames of each stream cannot receive direct head loss with this burn-in/window scheme'],
                run_sha256=sha(args.run/'run.json'),history_sha256=sha(args.run/'history.json'),
                script_sha256=sha(Path(__file__)),rows_sha256=sources,checks=checks,test_used=False,cohorts={})
    for j,label in enumerate(run['cohort_labels']):
        eligible=[int(i) for ids in caches[j].streams.values() for i in ids[2:]]
        values=np.array([counts[j][i] for i in eligible])
        if int(values.sum())!=draws[j]*6:raise ValueError('Exposure sum mismatch')
        report['cohorts'][label]=dict(window_draws=draws[j],eligible_eye_frames=len(eligible),
            direct_frame_presentations=int(values.sum()),unique_direct_frames=int((values>0).sum()),
            unique_coverage_fraction=float((values>0).mean()),mean_presentations=float(values.mean()),
            max_presentations=int(values.max()),median_presentations=float(np.median(values)))
    save(args.output,report);print(json.dumps(report),flush=True)


if __name__=='__main__':main()
