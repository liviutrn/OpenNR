"""Full causal training-split replay; diagnostic only, never held-out success."""
import argparse
import json
from pathlib import Path
import torch
from aligned_cohort import AlignedCohort
from train_capacity_temporal_student import _load_parent
from train_temporal_student import evaluate_streaming
from prepare_conditioning_pilot import save,sha


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--run',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--tone-head',action='store_true')
    p.add_argument('--final-checkpoint',action='store_true')
    a=p.parse_args()
    if a.final_checkpoint and not a.tone_head:p.error('Final checkpoint requires tone-head mode')
    if a.output.exists():raise FileExistsError(a.output)
    a.output.mkdir(parents=True)
    torch.set_num_threads(4)
    checkpoint=a.run/('last.pt' if a.final_checkpoint else 'best_all_cohorts.pt')
    verification=json.loads((a.run/('final_checkpoint_verification.json' if a.final_checkpoint else 'checkpoint_verification.json')).read_text())
    verified=verification if a.tone_head else verification['arms']['continuation']
    if sha(checkpoint)!=verified['sha256']:raise ValueError('Selected checkpoint differs from verified model')
    if a.tone_head:
        from verify_spatial_tone import load_tone_checkpoint
        if json.loads((a.run/'status.json').read_text())['state']!='complete':raise ValueError('Training run not complete')
        model,payload=load_tone_checkpoint(checkpoint)
    else:model,payload,*_=_load_parent(checkpoint)
    if payload['step']!=verified['step']:raise ValueError('Verified step mismatch')
    model.eval().requires_grad_(False)
    report={'checkpoint':str(checkpoint),'sha256':sha(checkpoint),'step':payload['step'],
            'scope':'training-fit diagnostic, no optimizer, no test access',
            'warning':'Training and validation scenes differ; their aggregate gap alone cannot establish overfitting or a capacity limit.',
            'test_used':False,'cohorts':{}}
    try:
        labels=payload['run'].get('cohort_labels',['prior','high_effect','renderer_pilot'])
        if len(labels)!=len(payload['run']['cohorts']) or set(labels)!=set(verified['cohorts']):raise ValueError('Cohort coverage mismatch')
        modes=payload['run'].get('teacher_pass_counts',[1]*len(labels))
        if len(modes)!=len(labels):raise ValueError('Teacher mode coverage mismatch')
        for j,(label,root) in enumerate(zip(labels,payload['run']['cohorts'])):
            cache=AlignedCohort(Path(root),'train',expected_pass_count=modes[j])
            if a.tone_head:
                from multilayer_teacher_mode import set_conditioned_teacher_mode as set_teacher_mode
                set_teacher_mode(model.head,modes[j])
            if 'training_sequences' in payload['run'] and cache.sequence_ids!=payload['run']['training_sequences'][j]:raise ValueError('Recorded training membership mismatch')
            if not a.tone_head and cache.sequence_ids!=payload['run']['training_sequences'][j]:raise ValueError('Training membership mismatch')
            if a.tone_head:
                val=AlignedCohort(Path(root),'validation',expected_pass_count=modes[j])
                if set(cache.sequence_ids)&set(val.sequence_ids):raise ValueError('Training/validation sequence overlap')
                if set(val.sequence_ids)!=set(verified['cohorts'][label]['metrics']['sequence_mae']):raise ValueError('Validation membership mismatch')
            save(a.output/'status.json',{'state':'evaluating','cohort':label,'sequences':len(cache.sequence_ids)})
            with torch.no_grad():metrics=evaluate_streaming(model,cache,batch=4)
            report['cohorts'][label]={'train':metrics,'validation':verified['cohorts'][label]['metrics']}
            report['cohorts'][label]['training_sequences']=cache.sequence_ids
            report['cohorts'][label]['overlay_complete_sha256']=sha(Path(root)/'complete.json')
            save(a.output/'partial.json',report)
            print(json.dumps({'cohort':label,'training_sequences':metrics['sequence_count'],'train_mae':metrics['mae'],'validation_mae':verified['cohorts'][label]['metrics']['mae']}),flush=True)
        save(a.output/'result.json',report)
        save(a.output/'status.json',{'state':'complete','test_used':False})
    except Exception as e:
        save(a.output/'status.json',{'state':'failed','error':repr(e)})
        raise


if __name__=='__main__':main()
