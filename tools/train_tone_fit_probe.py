"""Shared-head fitting on twelve training images; diagnostic only, no held-out access."""
import argparse
import json
from pathlib import Path
import numpy as np
import torch
from aligned_cohort import AlignedCohort
from prepare_conditioning_pilot import save,sha
from train_capacity_temporal_student import _load_parent
from resolution_tone_head import ResolutionToneHead


def main():
    p=argparse.ArgumentParser();p.add_argument('--oracle',type=Path,required=True)
    p.add_argument('--fit-report',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--verify-run',type=Path)
    p.add_argument('--multiscale',action='store_true')
    p.add_argument('--oversized',action='store_true')
    p.add_argument('--stable-oversized',action='store_true')
    p.add_argument('--steps',type=int,default=1200)
    p.add_argument('--learning-rate',type=float,default=1e-3)
    p.add_argument('--plateau-schedule',action='store_true')
    p.add_argument('--resume-run',type=Path)
    a=p.parse_args()
    if a.stable_oversized:a.oversized=True
    if a.multiscale and a.oversized:p.error('Choose one architecture')
    if a.resume_run and a.verify_run:p.error('Resume and verify are separate operations')
    if a.steps<200 or a.steps%200 or a.learning_rate<=0:p.error('Positive learning rate and steps divisible by200 required')
    if a.output.exists():raise FileExistsError(a.output)
    a.output.mkdir(parents=True);torch.set_num_threads(4);torch.manual_seed(358)
    oracle=json.loads(a.oracle.read_text());fit=json.loads(a.fit_report.read_text());path=Path(fit['checkpoint'])
    if sha(path)!=fit['sha256'] or sha(path)!=oracle['parent_sha256']:raise ValueError('Parent mismatch')
    if oracle['test_used'] or oracle['fit_report_sha256']!=sha(a.fit_report):raise ValueError('Oracle provenance mismatch')
    model,payload,*_=_load_parent(path);model.eval().requires_grad_(False);samples=[]
    for label,root in zip(('prior','high_effect','renderer_pilot'),payload['run']['cohorts']):
        cache=AlignedCohort(Path(root),'train')
        for row in (r for r in oracle['images'] if r['cohort']==label):
            seq,eye=row['sequence'],row['eye'];state=None
            if seq not in cache.sequence_ids:raise ValueError('Nontraining sequence')
            with torch.no_grad():
                for i in cache.streams[seq,eye][:32]:
                    def tensor(x):return torch.from_numpy(np.array(x,copy=True)).cuda().float()
                    color=tensor(cache.rgb[i:i+1])/255;rgb,target=color[:,0],color[:,1]
                    g=tensor(cache.guides[i:i+1]);c=tensor(cache.context[i:i+1])
                    with torch.autocast('cuda',dtype=torch.bfloat16):base,state=model.forward_temporal(rgb,g,c,state)
            if abs(float((base.float()-target).abs().mean())-row['parent_mae'])>1e-7:raise ValueError('Frame replay mismatch')
            samples.append((row,rgb,base.float().detach(),g,c,target))
    if len(samples)!=12:raise ValueError('Expected twelve diagnostic images')
    del model,state;torch.cuda.empty_cache()
    head=ResolutionToneHead(4).cuda()
    if a.multiscale:
        from multiscale_tone_head import MultiscaleToneHead
        head=MultiscaleToneHead().cuda()
    if a.oversized:
        from oversized_tone_head import OversizedToneHead
        head=OversizedToneHead().cuda()
        if a.stable_oversized:
            from stable_oversized_tone_head import StableOversizedToneHead
            head=StableOversizedToneHead().cuda()
    if a.verify_run is not None:
        from audit_conditioning_content import picture,sheet
        if json.loads((a.verify_run/'status.json').read_text())['state']!='complete':raise ValueError('Run incomplete')
        checkpoint_path=a.verify_run/'diagnostic_only.pt'
        checkpoint=torch.load(checkpoint_path,map_location='cpu',weights_only=False);saved=checkpoint['run']
        if saved.get('architecture')=='oversized_unet':
            from oversized_tone_head import OversizedToneHead
            if saved['oversized_source_sha256']!=sha(Path(__file__).with_name('oversized_tone_head.py')):raise ValueError('Oversized source mismatch')
            head=OversizedToneHead().cuda()
            if saved.get('stable_oversized'):
                from stable_oversized_tone_head import StableOversizedToneHead
                if saved['stable_source_sha256']!=sha(Path(__file__).with_name('stable_oversized_tone_head.py')):raise ValueError('Stable source mismatch')
                head=StableOversizedToneHead().cuda()
        if saved.get('architecture')=='multiscale':
            from multiscale_tone_head import MultiscaleToneHead
            if saved['multiscale_source_sha256']!=sha(Path(__file__).with_name('multiscale_tone_head.py')):raise ValueError('Multiscale source mismatch')
            head=MultiscaleToneHead().cuda()
        if saved['test_used'] or saved['parent_sha256']!=sha(path) or saved['oracle_sha256']!=sha(a.oracle):raise ValueError('Checkpoint provenance mismatch')
        for field,filename in [('head_source_sha256','resolution_tone_head.py'),('base_head_source_sha256','spatial_tone_head.py')]:
            if saved[field]!=sha(Path(__file__).with_name(filename)):raise ValueError('Head source mismatch')
        head.load_state_dict(checkpoint['head'],strict=True);head.eval();rows=[]
        expected={(r['sequence'],r['eye']):r['mae'] for r in checkpoint['training']}
        if set(expected)!={(r['sequence'],r['eye']) for r,*_ in samples}:raise ValueError('Image set mismatch')
        with torch.no_grad():
            for meta,rgb,base,g,c,target in samples:
                pred=head(rgb,base,g,c);mae=float((pred-target).abs().mean())
                delta=abs(mae-expected[meta['sequence'],meta['eye']])
                if delta>1e-7:raise ValueError('Head replay mismatch')
                rows.append({'sequence':meta['sequence'],'eye':meta['eye'],'mae':mae,'replay_difference':delta})
                views=[('input',rgb),('teacher',target),('parent',base),('TRAINING FIT ONLY',pred)]
                sheet([(name,picture(value[0].cpu().numpy().transpose(1,2,0))) for name,value in views],4,a.output/f"{meta['sequence']}-eye{meta['eye']}.png",512)
        report={'checkpoint_sha256':sha(checkpoint_path),'step':checkpoint['step'],'test_used':False,'images':rows,'mean_training_mae':float(np.mean([r['mae'] for r in rows]))}
        save(a.output/'verification.json',report);print(json.dumps(report),flush=True)
        return
    opt=torch.optim.AdamW(head.parameters(),lr=a.learning_rate,weight_decay=0.)
    scheduler=torch.optim.lr_scheduler.ReduceLROnPlateau(opt,mode='min',factor=.5,patience=2,threshold=2e-5,threshold_mode='abs',min_lr=1e-6) if a.plateau_schedule else None
    run={'scope':'TWELVE TRAINING IMAGES ONLY; NOT PROMOTABLE OR HELD-OUT PERFORMANCE',
        'parent':str(path),'parent_sha256':sha(path),'oracle_sha256':sha(a.oracle),'test_used':False,
        'seed':358,'steps':a.steps,'learning_rate':a.learning_rate,'loss':'L1 only, no temporal loss on static frame32',
        'head_source_sha256':sha(Path(__file__).with_name('resolution_tone_head.py')),
        'base_head_source_sha256':sha(Path(__file__).with_name('spatial_tone_head.py')),
        'trainer_sha256':sha(Path(__file__))}
    run['architecture']='oversized_unet' if a.oversized else ('multiscale' if a.multiscale else 'local')
    run['plateau_schedule']=a.plateau_schedule
    run['head_parameters']=sum(p.numel() for p in head.parameters())
    if a.multiscale:run['multiscale_source_sha256']=sha(Path(__file__).with_name('multiscale_tone_head.py'))
    if a.oversized:run['oversized_source_sha256']=sha(Path(__file__).with_name('oversized_tone_head.py'))
    if a.stable_oversized:run.update(stable_oversized=True,stable_source_sha256=sha(Path(__file__).with_name('stable_oversized_tone_head.py')))
    history=[];best=float('inf');start_step=0
    if a.resume_run:
        if json.loads((a.resume_run/'status.json').read_text())['state']!='complete':raise ValueError('Resume requires a completed bounded run')
        resume_path=a.resume_run/'last_resumable.pt'
        resumed=torch.load(resume_path,map_location='cpu',weights_only=False)
        for key,value in run.items():
            if key not in ('steps','trainer_sha256') and resumed['run'].get(key)!=value:
                raise ValueError('Resume configuration mismatch: '+key)
        start_step=resumed['step']
        if a.steps<=start_step:raise ValueError('New total-step cap must exceed saved step')
        head.load_state_dict(resumed['head'],strict=True);opt.load_state_dict(resumed['optimizer'])
        if scheduler is not None:scheduler.load_state_dict(resumed['scheduler'])
        history=resumed['history'];best=min(r['mean_training_mae'] for r in history)
        expected={(r['sequence'],r['eye']):r['mae'] for r in history[-1]['images']}
        if history[-1]['step']!=start_step or set(expected)!={(r['sequence'],r['eye']) for r,*_ in samples}:raise ValueError('Resume history mismatch')
        with torch.no_grad():
            differences=[]
            for meta,rgb,base,g,c,target in samples:
                mae=float((head(rgb,base,g,c)-target).abs().mean())
                differences.append(abs(mae-expected[meta['sequence'],meta['eye']]))
        if max(differences)>1e-7:raise ValueError('Resume replay mismatch')
        run.update(resume_checkpoint_sha256=sha(resume_path),resume_step=start_step)
        saved_best=torch.load(a.resume_run/'diagnostic_only.pt',map_location='cpu',weights_only=False)
        if abs(float(np.mean([r['mae'] for r in saved_best['training']]))-best)>1e-7:raise ValueError('Saved best mismatch')
        saved_best['run']=run;torch.save(saved_best,a.output/'diagnostic_only.pt')
        save(a.output/'resume_verification.json',{'step':start_step,'max_replay_difference':max(differences),'learning_rate':opt.param_groups[0]['lr'],'scheduler_last_epoch':scheduler.last_epoch if scheduler else None})
        save(a.output/'history.json',history)
        del resumed,saved_best
    save(a.output/'run.json',run)
    def evaluate(step):
        nonlocal best
        rows=[]
        with torch.no_grad():
            for meta,rgb,base,g,c,target in samples:
                pred=head(rgb,base,g,c)
                rows.append({'sequence':meta['sequence'],'eye':meta['eye'],'cohort':meta['cohort'],'mae':float((pred-target).abs().mean())})
        mean=float(np.mean([r['mae'] for r in rows]));history.append({'step':step,'mean_training_mae':mean,'images':rows})
        save(a.output/'history.json',history)
        if scheduler is not None:scheduler.step(mean)
        if mean<best:
            best=mean;torch.save({'head':head.state_dict(),'run':run,'step':step,'training':rows},a.output/'diagnostic_only.pt')
        if a.oversized:
            torch.save({'head':head.state_dict(),'optimizer':opt.state_dict(),'scheduler':scheduler.state_dict() if scheduler else None,'run':run,'step':step,'history':history},a.output/'last_resumable.pt')
        print(json.dumps({'step':step,'mean_training_mae':mean,'learning_rate':opt.param_groups[0]['lr']}),flush=True)
    try:
        if start_step==0:evaluate(0)
        near_converged=False
        for step in range(start_step+1,a.steps+1):
            _,rgb,base,g,c,target=samples[(step-1)%len(samples)]
            opt.zero_grad(set_to_none=True);pred=head(rgb,base,g,c);loss=(pred-target).abs().mean()
            if not torch.isfinite(loss):raise ValueError('Nonfinite loss')
            loss.backward();torch.nn.utils.clip_grad_norm_(head.parameters(),1.,error_if_nonfinite=True);opt.step()
            if step%50==0:save(a.output/'status.json',{'state':'training','step':step,'best_training_mae':best})
            if step%200==0:
                evaluate(step)
                if scheduler is not None and step>=2400 and opt.param_groups[0]['lr']<=1e-5:
                    previous_best=min(r['mean_training_mae'] for r in history[:-5])
                    near_converged=previous_best-best<5e-5
                    if near_converged:break
        save(a.output/'status.json',{'state':'complete','step':step,'near_converged':near_converged,'best_training_mae':best,'test_used':False})
    except Exception as e:
        save(a.output/'status.json',{'state':'failed','error':repr(e)});raise


if __name__=='__main__':main()
