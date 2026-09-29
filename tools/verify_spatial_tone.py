"""Reload tone head and its exact frozen parent, replay validation only."""
import argparse
import json
from pathlib import Path
import torch
from spatial_tone_head import SpatialToneHead,FrozenParentToneModel
from aligned_cohort import AlignedCohort
from train_capacity_temporal_student import _load_parent
from train_temporal_student import evaluate_streaming
from prepare_conditioning_pilot import save,sha
from teacher_mode_head import enable_teacher_mode
from multilayer_teacher_mode import enable_multilayer_teacher_mode,set_conditioned_teacher_mode as set_teacher_mode


def load_tone_checkpoint(path):
    payload=torch.load(path,map_location='cpu',weights_only=False)
    run=payload['run'];parent_path=Path(run['parent'])
    if 'cohort_complete_sha256' in run:
        if len(run['cohorts'])!=len(run['cohort_complete_sha256']):raise ValueError('Cohort identity coverage mismatch')
        for root,digest in zip(run['cohorts'],run['cohort_complete_sha256']):
            if sha(Path(root)/'complete.json')!=digest:raise ValueError('Checkpoint cohort identity changed')
    if 'loader_source_sha256' in run and sha(Path(__file__).with_name('aligned_cohort.py'))!=run['loader_source_sha256']:
        raise ValueError('Checkpoint cohort loader implementation changed')
    if sha(parent_path)!=run['parent_sha256']:raise ValueError('Parent mismatch')
    if sha(Path(__file__).with_name('spatial_tone_head.py'))!=run['head_source_sha256']:raise ValueError('Head implementation changed')
    parent,*_=_load_parent(parent_path)
    if run.get('architecture') in ('stable_unet','stable_unet_teacher_mode','stable_unet_teacher_multilayer'):
        for field,filename in [('oversized_source_sha256','oversized_tone_head.py'),('stable_source_sha256','stable_oversized_tone_head.py')]:
            if sha(Path(__file__).with_name(filename))!=run[field]:raise ValueError('U-Net source changed')
        from stable_oversized_tone_head import StableOversizedToneHead
        head=StableOversizedToneHead().cuda()
        if run['architecture'] in ('stable_unet_teacher_mode','stable_unet_teacher_multilayer'):
            if sha(Path(__file__).with_name('teacher_mode_head.py'))!=run['teacher_mode_source_sha256']:raise ValueError('Teacher-mode implementation changed')
            enable_teacher_mode(head)
        if run['architecture']=='stable_unet_teacher_multilayer':
            if sha(Path(__file__).with_name('multilayer_teacher_mode.py'))!=run['multilayer_source_sha256']:raise ValueError('Multilayer implementation changed')
            enable_multilayer_teacher_mode(head)
    elif run.get('architecture')=='multiscale':
        if sha(Path(__file__).with_name('multiscale_tone_head.py'))!=run['multiscale_source_sha256']:raise ValueError('Multiscale implementation changed')
        from multiscale_tone_head import MultiscaleToneHead
        head=MultiscaleToneHead().cuda()
    elif 'grid_downsample' in run:
        if sha(Path(__file__).with_name('resolution_tone_head.py'))!=run['resolution_source_sha256']:raise ValueError('Resolution implementation changed')
        from resolution_tone_head import ResolutionToneHead
        head=ResolutionToneHead(downsample=run['grid_downsample']).cuda()
    else:head=SpatialToneHead(spatial=run['spatial']).cuda()
    head.load_state_dict(payload['head'],strict=True)
    return FrozenParentToneModel(parent,head).eval(),payload


def main():
    p=argparse.ArgumentParser();p.add_argument('--run',type=Path,required=True);p.add_argument('--final-checkpoint',action='store_true');a=p.parse_args()
    if json.loads((a.run/'status.json').read_text())['state']!='complete':raise ValueError('Run not complete')
    torch.set_num_threads(4)
    path=a.run/('last.pt' if a.final_checkpoint else 'best_all_cohorts.pt');model,payload=load_tone_checkpoint(path)
    if a.final_checkpoint:
        history=json.loads((a.run/'history.json').read_text())
        if payload['step']!=payload['run']['steps'] or history[-1]['step']!=payload['step']:raise ValueError('Final step mismatch')
        expected=history[-1]['validation']
    else:expected=payload['validation']
    report={'checkpoint':str(path),'sha256':sha(path),'step':payload['step'],'test_used':False,'cohorts':{}}
    labels=payload['run'].get('cohort_labels',['prior','high_effect','renderer_pilot'])
    if len(labels)!=len(payload['run']['cohorts']) or set(labels)!=set(expected):raise ValueError('Cohort coverage mismatch')
    modes=payload['run'].get('teacher_pass_counts',[1]*len(labels))
    if len(modes)!=len(labels):raise ValueError('Teacher mode coverage mismatch')
    for label,root,mode in zip(labels,payload['run']['cohorts'],modes):
        set_teacher_mode(model.head,mode)
        with torch.no_grad():metrics=evaluate_streaming(model,AlignedCohort(Path(root),'validation',expected_pass_count=mode),batch=4)
        delta={k:abs(metrics[k]-expected[label][k]) for k in ('mae','psnr','temporal_delta_mae')}
        if max(delta.values())>1e-7:raise ValueError('Replay mismatch '+str(delta))
        report['cohorts'][label]={'metrics':metrics,'reproduction_difference':delta}
        print(json.dumps({'cohort':label,'mae':metrics['mae'],'verified':True}),flush=True)
    save(a.run/('final_checkpoint_verification.json' if a.final_checkpoint else 'checkpoint_verification.json'),report)


if __name__=='__main__':main()
