"""Read-only matched conditioning-arm audit; never reads test pixels or uses GPU."""
import argparse
import json
import math
from pathlib import Path
from prepare_conditioning_pilot import save, sha


def compare(control, arm, left, right):
    if control['architecture'] != 'stable_unet_teacher_mode' or arm['architecture'] != 'stable_unet_teacher_multilayer':
        raise ValueError('Wrong conditioning architectures')
    allowed = {'architecture', 'head_parameters', 'trainer_source_sha256', 'multilayer_source_sha256',
               'optimizer_initialization', 'resume_checkpoint', 'resume_checkpoint_sha256',
               'resume_step', 'resume_helper_sha256', 'conditioning_control', 'conditioning_control_history_sha256'}
    differences = {k for k in set(control)|set(arm) if control.get(k)!=arm.get(k)}
    if differences-allowed:
        raise ValueError('Scientific configuration changed: '+str(sorted(differences-allowed)))
    if arm['head_parameters']-control['head_parameters'] != 22688 or control['test_used'] or arm['test_used']:
        raise ValueError('Parameter count or test-use mismatch')
    labels = control['cohort_labels']
    if len(labels)!=5 or control['teacher_pass_counts']!=[1,1,1,1,2]:
        raise ValueError('Wrong cohort coverage')
    def keyed(rows):
        result={r['step']:r for r in rows}
        if len(result)!=len(rows) or 0 not in result:raise ValueError('Missing baseline or duplicate step')
        return result
    c,a=keyed(left),keyed(right)
    if set(a)-set(c):raise ValueError('Missing matched control step')
    for label in labels:
        for key in ('mae','psnr','temporal_delta_mae'):
            x,y=c[0]['validation'][label][key],a[0]['validation'][label][key]
            if not math.isfinite(x+y) or abs(x-y)>1e-7:raise ValueError('Baseline mismatch')
    paired=[]
    for step in sorted(a):
        for key in ('sample_schedule_sha256','baseline_sample_schedule_sha256','cohort_draws','hard_draws'):
            if c[step][key]!=a[step][key]:raise ValueError(f'Sample/exposure mismatch: {step}/{key}')
        cohorts={}
        for label in labels:
            x,y,b=c[step]['validation'][label],a[step]['validation'][label],c[0]['validation'][label]
            if not all(math.isfinite(row[key]) for row in (x,y,b) for key in ('mae','psnr','temporal_delta_mae')) or b['mae']<=0:
                raise ValueError('Invalid metric')
            cohorts[label]={'control_mae':x['mae'],'arm_mae':y['mae'],
                'arm_minus_control_mae':y['mae']-x['mae'],
                'control_relative_to_start':x['mae']/b['mae'],'arm_relative_to_start':y['mae']/b['mae'],
                'arm_minus_control_temporal':y['temporal_delta_mae']-x['temporal_delta_mae']}
        paired.append({'step':step,'sample_hash':a[step]['sample_schedule_sha256'],'cohorts':cohorts,
                       'all_cohort_mae_eligible':all(v['arm_relative_to_start']<1 for v in cohorts.values())})
    return {'test_used':False,'configuration_differences':sorted(differences),'paired':paired,
            'scope':'Recorded validation trajectories only; not independent checkpoint replay, training-fit or visual acceptance.'}


def main():
    p=argparse.ArgumentParser()
    for key in ('control','arm','output'):p.add_argument('--'+key,type=Path,required=True)
    args=p.parse_args()
    paths=[args.control/'run.json',args.arm/'run.json',args.control/'history.json',args.arm/'history.json']
    hashes=[sha(path) for path in paths]
    contents=[json.loads(path.read_text()) for path in paths]
    if contents[1]['conditioning_control_history_sha256']!=hashes[2]:raise ValueError('Control history identity changed')
    report=compare(*contents)
    if hashes!=[sha(path) for path in paths]:raise ValueError('Live snapshot changed; retry')
    report['sources']={str(p):h for p,h in zip(paths,hashes)}
    report['script_sha256']=sha(Path(__file__))
    save(args.output,report)
    print(json.dumps(report),flush=True)


if __name__=='__main__':main()
