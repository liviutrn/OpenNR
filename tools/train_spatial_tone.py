"""Matched local/global tone heads on frozen verified parent, no test access."""
import argparse
import hashlib
import json
from pathlib import Path
import numpy as np
import torch
from torch.nn import functional as F
from aligned_cohort import AlignedCohort
from spatial_tone_head import SpatialToneHead,FrozenParentToneModel
from prepare_conditioning_pilot import save,sha
from train_capacity_temporal_student import _load_parent
from train_temporal_student import _device_batch,evaluate_streaming
from teacher_mode_head import enable_teacher_mode
from multilayer_teacher_mode import enable_multilayer_teacher_mode,set_conditioned_teacher_mode as set_teacher_mode


def frame_objective(error,previous,pixel_only=False):
    loss=error.abs().mean()
    if not pixel_only:loss=loss+.5*F.avg_pool2d(error,16).abs().mean()+.12*(error-previous).abs().mean()
    return loss


def main():
    p=argparse.ArgumentParser();p.add_argument('--run',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--global-only',action='store_true');p.add_argument('--grid-downsample',type=int,choices=(4,16));p.add_argument('--multiscale',action='store_true');p.add_argument('--stable-unet',action='store_true');p.add_argument('--steps',type=int,default=1200)
    p.add_argument('--initial-head-run',type=Path);p.add_argument('--pixel-only',action='store_true');p.add_argument('--seed',type=int,default=356);p.add_argument('--hard-manifest',type=Path)
    p.add_argument('--additional-cohort',type=Path);p.add_argument('--two-pass-cohort',type=Path)
    p.add_argument('--multilayer-conditioning',action='store_true');p.add_argument('--conditioning-control',type=Path)
    p.add_argument('--learning-rate',type=float,default=1e-4);p.add_argument('--resume-run',type=Path);a=p.parse_args()
    if a.multilayer_conditioning and (not a.two_pass_cohort or not a.stable_unet or a.resume_run or not a.conditioning_control):p.error('Multilayer arm requires joint stable U-Net, common fresh warm start, and conditioning control')
    if a.conditioning_control and not a.multilayer_conditioning:p.error('Conditioning control requires multilayer arm')
    if a.resume_run and (not a.two_pass_cohort or not a.stable_unet or a.hard_manifest):p.error('Resume supports uniform joint-teacher U-Net only')
    if not np.isfinite(a.learning_rate) or a.learning_rate<=0:p.error('Learning rate must be positive and finite')
    if a.two_pass_cohort and not a.additional_cohort:p.error('Two-pass joint recipe requires the fresh one-pass cohort')
    if a.additional_cohort and (not a.initial_head_run or a.hard_manifest):p.error('New cohort requires verified warm start and uniform sampling')
    if a.hard_manifest and not a.initial_head_run:p.error('Hard sampling requires verified initial head')
    if a.initial_head_run and not a.stable_unet:p.error('Warm-start comparison requires stable U-Net')
    if a.steps<400 or a.steps%400:p.error('Steps must be positive and divisible by400')
    if a.stable_unet and (a.multiscale or a.global_only or a.grid_downsample):p.error('Choose one architecture')
    if a.global_only and (a.grid_downsample is not None or a.multiscale):p.error('Incompatible head options')
    if a.grid_downsample is not None and a.multiscale:p.error('Choose grid or multiscale')
    if a.output.exists():raise FileExistsError(a.output)
    a.output.mkdir(parents=True);torch.set_num_threads(4);torch.manual_seed(a.seed);torch.cuda.manual_seed_all(a.seed);rng=np.random.default_rng(a.seed)
    path=a.run/'best_all_cohorts.pt';verified=json.loads((a.run/'checkpoint_verification.json').read_text())['arms']['continuation']
    if sha(path)!=verified['sha256']:raise ValueError('Unverified parent')
    parent,payload,*_=_load_parent(path)
    if a.stable_unet:
        from stable_oversized_tone_head import StableOversizedToneHead
        head=StableOversizedToneHead().cuda()
    elif a.multiscale:
        from multiscale_tone_head import MultiscaleToneHead
        head=MultiscaleToneHead().cuda()
    elif a.grid_downsample is None:head=SpatialToneHead(spatial=not a.global_only).cuda()
    else:
        from resolution_tone_head import ResolutionToneHead
        head=ResolutionToneHead(downsample=a.grid_downsample).cuda()
    initial=None;initial_path=None
    if a.initial_head_run:
        initial_path=a.initial_head_run/'best_all_cohorts.pt'
        iv=json.loads((a.initial_head_run/'checkpoint_verification.json').read_text())
        if json.loads((a.initial_head_run/'status.json').read_text())['state']!='complete':raise ValueError('Initial run not complete')
        if sha(initial_path)!=iv['sha256']:raise ValueError('Unverified initial head')
        initial=torch.load(initial_path,map_location='cpu',weights_only=False)
        ir=initial['run']
        if ir.get('architecture')!='stable_unet' or ir['parent_sha256']!=sha(path):raise ValueError('Initial architecture/parent mismatch')
        if ir['cohorts']!=payload['run']['cohorts']:raise ValueError('Initial cohort roots mismatch')
        for field,filename in [('head_source_sha256','spatial_tone_head.py'),('oversized_source_sha256','oversized_tone_head.py'),('stable_source_sha256','stable_oversized_tone_head.py')]:
            if ir[field]!=sha(Path(__file__).with_name(filename)):raise ValueError('Initial head source changed')
        head.load_state_dict(initial['head'],strict=True)
    if a.two_pass_cohort:enable_teacher_mode(head)
    if a.multilayer_conditioning:enable_multilayer_teacher_mode(head)
    model=FrozenParentToneModel(parent,head)
    train=[AlignedCohort(Path(r),'train') for r in payload['run']['cohorts']];val=[AlignedCohort(Path(r),'validation') for r in payload['run']['cohorts']]
    labels=['prior','high_effect','renderer_pilot'];probabilities=[.5,.3,.2]
    if a.additional_cohort:
        train.append(AlignedCohort(a.additional_cohort,'train'));val.append(AlignedCohort(a.additional_cohort,'validation'))
        labels.append('fresh_session');probabilities=[.375,.225,.15,.25]
        if a.two_pass_cohort:
            train.append(AlignedCohort(a.two_pass_cohort,'train',expected_pass_count=2));val.append(AlignedCohort(a.two_pass_cohort,'validation',expected_pass_count=2))
            labels.append('two_pass');probabilities=[.30,.18,.12,.20,.20]
        all_train=set();all_validation=set();all_test=set()
        for t,v in zip(train,val):
            if all_train.intersection(t.sequence_ids) or all_validation.intersection(v.sequence_ids):raise ValueError('Repeated sequence across cohorts')
            all_train.update(t.sequence_ids);all_validation.update(v.sequence_ids)
            all_test.update(r['sequence_id'] for r in t.rows if r['split']=='test')
        if all_train.intersection(all_validation):raise ValueError('Train/validation sequence leakage')
        if all_test.intersection(all_train|all_validation):raise ValueError('Frozen-test sequence leakage')
    run={'parent':str(path),'parent_sha256':sha(path),'cohorts':payload['run']['cohorts'],'seed':356,'spatial':not a.global_only,'steps':1200,'probabilities':[.5,.3,.2],'learning_rate':1e-4,'loss':'L1 + .5 pooled16 RGB L1 + .12 temporal error delta','test_used':False,'head_source_sha256':sha(Path(__file__).with_name('spatial_tone_head.py'))}
    if a.grid_downsample is not None:
        run.update(grid_downsample=a.grid_downsample,resolution_source_sha256=sha(Path(__file__).with_name('resolution_tone_head.py')))
    if a.multiscale:
        run.update(architecture='multiscale',multiscale_source_sha256=sha(Path(__file__).with_name('multiscale_tone_head.py')),head_parameters=sum(p.numel() for p in head.parameters()))
    run['trainer_source_sha256']=sha(Path(__file__))
    run['learning_rate']=a.learning_rate
    run['steps']=a.steps
    run['seed']=a.seed
    run['cohort_labels']=labels;run['probabilities']=probabilities
    run['teacher_pass_counts']=[c.teacher_pass_count for c in train]
    run['cohorts']=[str(c.root) for c in train]
    run['cohort_complete_sha256']=[sha(c.root/'complete.json') for c in train]
    run['training_sequences']=[c.sequence_ids for c in train]
    run['validation_sequences']=[c.sequence_ids for c in val]
    run['loader_source_sha256']=sha(Path(__file__).with_name('aligned_cohort.py'))
    if a.additional_cohort:run['new_data_policy']='25% fresh session; 75% original mixture; uniform sequences; renderer features retained but not input to unchanged U-Net'
    if a.pixel_only:run['loss']='L1'
    if initial is not None:
        run.update(initial_head=str(initial_path),initial_head_sha256=sha(initial_path),initial_head_step=initial['step'],optimizer_initialization='fresh AdamW in both comparison arms',initial_validation=initial['validation'])
    if a.stable_unet:
        run.update(architecture='stable_unet',oversized_source_sha256=sha(Path(__file__).with_name('oversized_tone_head.py')),stable_source_sha256=sha(Path(__file__).with_name('stable_oversized_tone_head.py')),head_parameters=sum(p.numel() for p in head.parameters()))
    if a.two_pass_cohort:
        run.update(architecture='stable_unet_teacher_mode',teacher_mode_source_sha256=sha(Path(__file__).with_name('teacher_mode_head.py')),
                   new_data_policy='Explicit teacher mode; 60% old cohorts,20% fresh one-pass,20% two-pass; uniform within each cohort; no test tuning')
    conditioning_history=None
    if a.multilayer_conditioning:
        run.update(architecture='stable_unet_teacher_multilayer',multilayer_source_sha256=sha(Path(__file__).with_name('multilayer_teacher_mode.py')))
        control=json.loads((a.conditioning_control/'run.json').read_text())
        if json.loads((a.conditioning_control/'status.json').read_text())['state']!='complete':raise ValueError('Conditioning control incomplete')
        control_verification=json.loads((a.conditioning_control/'final_checkpoint_verification.json').read_text())
        if sha(a.conditioning_control/'last.pt')!=control_verification['sha256']:raise ValueError('Unverified conditioning control')
        allowed={'architecture','head_parameters','trainer_source_sha256','multilayer_source_sha256','optimizer_initialization','resume'}
        # Resume bookkeeping is checked separately; all scientific settings must match.
        for key in set(run)|set(control):
            if key not in allowed and not key.startswith('resume_') and run.get(key)!=control.get(key):raise ValueError('Conditioning comparison mismatch: '+key)
        if control['architecture']!='stable_unet_teacher_mode':raise ValueError('Expected weak-conditioning control')
        conditioning_history={row['step']:row for row in json.loads((a.conditioning_control/'history.json').read_text())}
        run['conditioning_control']=str(a.conditioning_control)
        run['conditioning_control_history_sha256']=sha(a.conditioning_control/'history.json')
    hard_sets=None;hard_rng=np.random.default_rng(a.seed+10000);hard_draws=0;base_digest=hashlib.sha256()
    if a.hard_manifest:
        from hard_sequence_sampling import load_hard_sets,replace_sequences
        hard_sets=load_hard_sets(a.hard_manifest,run['initial_head_sha256'],train)
        run.update(hard_manifest=str(a.hard_manifest),hard_manifest_sha256=sha(a.hard_manifest),hard_probability=.5,hard_rng_seed=a.seed+10000,hard_sampler_source_sha256=sha(Path(__file__).with_name('hard_sequence_sampling.py')))
    save(a.output/'run.json',run);opt=torch.optim.AdamW(head.parameters(),lr=a.learning_rate,weight_decay=1e-4);hist=[];baseline=None;best=1.;sample_digest=hashlib.sha256();cohort_draws={label:0 for label in labels}
    start_step=0;resume_replayed=False
    if a.resume_run:
        from resume_joint_teacher import restore_resume
        start_step,hist,best,cohort_draws,hard_state=restore_resume(a.resume_run,a.output,run,head,opt,train,rng,sample_digest,base_digest)
        hard_rng.bit_generator.state=hard_state;baseline=hist[0]['validation']
    def evaluate(step):
        nonlocal baseline,best,resume_replayed
        metrics={}
        for label,cache in zip(labels,val):
            set_teacher_mode(head,cache.teacher_pass_count)
            save(a.output/'status.json',{'state':'evaluating','step':step,'cohort':label})
            with torch.no_grad():metrics[label]=evaluate_streaming(model,cache,batch=4)
        if a.resume_run and step==start_step and not resume_replayed:
            differences={label:{key:abs(metrics[label][key]-hist[-1]['validation'][label][key]) for key in ('mae','psnr','temporal_delta_mae')} for label in labels}
            if any(value>1e-7 for group in differences.values() for value in group.values()):raise ValueError('Resumed checkpoint replay mismatch')
            resume_replayed=True
            save(a.output/'resume_replay.json',{'step':step,'differences':differences,'test_used':False})
            print(json.dumps({'step':step,'state':'resume_verified','differences':differences}),flush=True)
            return
        if baseline is None:baseline=metrics
        if conditioning_history is not None:
            matched=conditioning_history[step]
            if sample_digest.hexdigest()!=matched['sample_schedule_sha256'] or cohort_draws!=matched['cohort_draws']:raise ValueError('Conditioning sample schedule mismatch')
            if step==0 and any(abs(metrics[label][key]-matched['validation'][label][key])>1e-7 for label in labels for key in ('mae','psnr','temporal_delta_mae')):raise ValueError('Conditioning initial replay mismatch')
        if step==0 and initial is not None:
            for label in initial['validation']:
                for key in ('mae','psnr','temporal_delta_mae'):
                    if abs(metrics[label][key]-initial['validation'][label][key])>1e-7:raise ValueError('Warm-start replay mismatch')
            torch.save({'head':head.state_dict(),'run':run,'step':0,'validation':metrics},a.output/'best_all_cohorts.pt')
        ratios=[metrics[k]['mae']/baseline[k]['mae'] for k in metrics];score=float(np.mean(ratios))
        hist.append({'step':step,'validation':metrics,'relative_mae':ratios,'sample_schedule_sha256':sample_digest.hexdigest(),'baseline_sample_schedule_sha256':base_digest.hexdigest(),'hard_draws':hard_draws,'cohort_draws':dict(cohort_draws)});save(a.output/'history.json',hist)
        if all(v<1 for v in ratios) and score<best:
            best=score;torch.save({'head':head.state_dict(),'run':run,'step':step,'validation':metrics},a.output/'best_all_cohorts.pt')
        if a.stable_unet:
            torch.save({'head':head.state_dict(),'optimizer':opt.state_dict(),'run':run,'step':step,'history':hist,'numpy_rng_state':rng.bit_generator.state,'hard_rng_state':hard_rng.bit_generator.state,'torch_rng_state':torch.get_rng_state(),'cuda_rng_state':torch.cuda.get_rng_state_all()},a.output/'last_resumable.pt')
        print(json.dumps({'step':step,'mae':{k:v['mae'] for k,v in metrics.items()}}),flush=True)
    try:
        evaluate(start_step)
        for step in range(start_step+1,a.steps+1):
            cohort_index=int(rng.choice(len(train),p=probabilities));cache=train[cohort_index];selected,starts,ids=cache.sample_window(rng,1,8)
            set_teacher_mode(head,cache.teacher_pass_count)
            base_digest.update(np.asarray([cohort_index],dtype='<i8').tobytes());base_digest.update(np.asarray(ids,dtype='<i8').tobytes())
            if hard_sets is not None:
                ids,count=replace_sequences(cache,selected,starts,ids,hard_sets[cohort_index],hard_rng);hard_draws+=count
            sample_digest.update(np.asarray([cohort_index],dtype='<i8').tobytes());sample_digest.update(np.asarray(ids,dtype='<i8').tobytes())
            rgb,t,g,c=_device_batch(cache.load_window(ids));rgb=rgb.float()/255;t=t.float()/255;g=g.float();c=c.float()
            model.train();opt.zero_grad(set_to_none=True);state=None;previous=None;losses=[]
            for f in range(8):
                with torch.autocast('cuda',dtype=torch.bfloat16):pred,state=model.forward_temporal(rgb[:,f],g[:,f],c[:,f],state)
                error=pred.float()-t[:,f]
                if f>=2:
                    losses.append(frame_objective(error,previous,a.pixel_only))
                previous=error if f>=2 else error.detach()
            loss=torch.stack(losses).mean()
            if not torch.isfinite(loss):raise ValueError('Nonfinite loss')
            loss.backward();torch.nn.utils.clip_grad_norm_(head.parameters(),1.,error_if_nonfinite=True);opt.step()
            cohort_draws[labels[cohort_index]]+=1
            if step%50==0:
                status={'state':'training','step':step,'loss':float(loss.detach()),'cohort_draws':dict(cohort_draws)};save(a.output/'status.json',status);print(json.dumps(status),flush=True)
            if step%400==0:evaluate(step)
        torch.save({'head':head.state_dict(),'run':run,'step':a.steps},a.output/'last.pt');save(a.output/'status.json',{'state':'complete','best_score':best,'test_used':False})
    except Exception as e:
        save(a.output/'status.json',{'state':'failed','error':repr(e)});raise


if __name__=='__main__':main()
