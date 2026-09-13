"""Compare completed, reloaded grid arms without accessing datasets or tests."""
import argparse
import json
from pathlib import Path
from prepare_conditioning_pilot import sha, save


def compare(coarse, fine):
    roots={'coarse':coarse,'fine':fine}
    runs={};histories={};verified={}
    for name,root in roots.items():
        if json.loads((root/'status.json').read_text())['state']!='complete':
            raise ValueError(f'{name} not complete')
        runs[name]=json.loads((root/'run.json').read_text())
        histories[name]=json.loads((root/'history.json').read_text())
        verified[name]=json.loads((root/'checkpoint_verification.json').read_text())
        if sha(root/'best_all_cohorts.pt')!=verified[name]['sha256']:
            raise ValueError(f'{name} checkpoint changed')
        if runs[name]['test_used'] or verified[name]['test_used']:
            raise ValueError('Test exposure is not allowed')
        for entry in verified[name]['cohorts'].values():
            if max(entry['reproduction_difference'].values())>1e-7:
                raise ValueError('Checkpoint replay failed')
    if (runs['coarse']['grid_downsample'],runs['fine']['grid_downsample'])!=(16,4):
        raise ValueError('Wrong grid pair')
    matched={k:v for k,v in runs['coarse'].items() if k!='grid_downsample'}
    if matched!={k:v for k,v in runs['fine'].items() if k!='grid_downsample'}:
        raise ValueError('Other recorded configuration differs')
    indexed={name:{row['step']:row['validation'] for row in hist}
             for name,hist in histories.items()}
    if set(indexed['coarse'])!=set(indexed['fine']):
        raise ValueError('Evaluation steps differ')
    rows=[]
    for step in sorted(indexed['coarse']):
        for cohort in ('prior','high_effect','renderer_pilot'):
            c=indexed['coarse'][step][cohort];f=indexed['fine'][step][cohort]
            if c['sequence_mae'].keys()!=f['sequence_mae'].keys():
                raise ValueError('Validation sequences differ')
            if step==0 and any(abs(c[k]-f[k])>1e-7 for k in ('mae','temporal_delta_mae')):
                raise ValueError('Initial baseline differs')
            rows.append({'step':step,'cohort':cohort,'coarse_mae':c['mae'],
                'fine_mae':f['mae'],'fine_minus_coarse_mae':f['mae']-c['mae'],
                'fine_relative_mae_change_percent':100*(f['mae']/c['mae']-1),
                'fine_minus_coarse_temporal_error':f['temporal_delta_mae']-c['temporal_delta_mae'],
                'sequences_improved':sum(f['sequence_mae'][s]<c['sequence_mae'][s] for s in c['sequence_mae']),
                'sequences_total':len(c['sequence_mae'])})
    return {'matched_recorded_configuration':True,'test_used':False,'same_step_comparison':rows,
        'selected_steps':{k:v['step'] for k,v in verified.items()},
        'checkpoint_sha256':{k:v['sha256'] for k,v in verified.items()},
        'caveats':['Single seed and reused validation cohorts; not independent generalization.',
                   'Grid resolution also changes the full-image receptive field.',
                   'MAE and temporal error do not prove facial visual acceptance.']}


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--coarse',type=Path,required=True)
    p.add_argument('--fine',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    if a.output.exists():raise FileExistsError(a.output)
    report=compare(a.coarse,a.fine);save(a.output,report)
    print(json.dumps(report,indent=2))
