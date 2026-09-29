"""Long, resumable continuation with deterministic epoch sampling and both metrics.

Existing v2 checkpoints lack optimizer state: --initialize starts a NEW optimizer
from their EMA weights. --resume resumes this script's exact saved training state.
"""
import argparse,json,math,time,random,os
from pathlib import Path
from copy import deepcopy
from dataclasses import asdict
import numpy as np
import torch
import torch.nn.functional as F
from torch.utils.data import DataLoader,default_collate
from train_student import CachedPatches,batch_to_device,evaluate,atomic_json
from student_v2 import ReconstructionStudent,ReconstructionConfig,detail_loss
from perceptual_features import FeatureDistance

def epoch_indices(length,batch,step,seed=137):
    batches=math.ceil(length/batch);epoch,offset=divmod(step-1,batches)
    order=np.random.default_rng(seed+epoch).permutation(length)
    return order[offset*batch:min((offset+1)*batch,length)].tolist(),epoch


def _round_half_up(value):
    return int(math.floor(float(value)+.5))


def source_weighted_indices(source_labels,batch,step,ratio,seed=137):
    """Sample two source pools at a deterministic target proportion.

    The source pools are independently permuted per sampler epoch. A rounded
    interleave gives the first source the requested aggregate proportion (up
    to one sample) while safely oversampling the smaller pool. This changes
    sampling only; cache rows and frozen splits remain untouched.
    """
    if batch<1 or not source_labels:raise ValueError('source sampler requires non-empty labels')
    names=sorted(set(source_labels))
    if len(names)!=2:raise ValueError('source sampler requires exactly two source labels')
    ratio=float(np.clip(ratio,0.0,1.0))
    if not 0<ratio<1:raise ValueError('source sampler ratio must be between zero and one')
    pools={name:np.asarray([i for i,s in enumerate(source_labels) if s==name],dtype=np.int64) for name in names}
    if any(len(v)==0 for v in pools.values()):raise ValueError('source sampler has an empty source pool')
    batches=math.ceil(len(source_labels)/batch);epoch,offset=divmod(step-1,batches)
    orders={name:np.random.default_rng(np.random.SeedSequence([seed+epoch,idx+1])).permutation(pool) for idx,(name,pool) in enumerate(pools.items())}
    result=[]
    for k in range(batch):
        g=offset*batch+k
        first_before=_round_half_up(g*ratio);first_after=_round_half_up((g+1)*ratio)
        if first_after>first_before:
            pos=first_before%len(pools[names[0]])
            result.append(int(orders[names[0]][pos]))
        else:
            second_before=g-first_before
            pos=second_before%len(pools[names[1]])
            result.append(int(orders[names[1]][pos]))
    return result,epoch


def tone_loss(pred,target):
    """Measure broad RGB tone separately from local/detail reconstruction.

    The existing detail objective includes an 8-pixel coarse term, but the
    visible teacher gap is often a slower exposure or skin/hair shading drift.
    A 16-pixel pooled L1 term gives the optional context-style branch a direct
    signal for that low-frequency component without changing the default loss.
    """
    if pred.shape[-2] < 16 or pred.shape[-1] < 16:
        raise ValueError('Tone loss requires spatial dimensions >= 16')
    return (F.avg_pool2d(pred,16)-F.avg_pool2d(target,16)).abs().mean()

@torch.no_grad()
def feature_score(model,loader,feature):
    total=0.;n=0
    for b in loader:
        x,t,g,c=batch_to_device(b,'cuda')
        with torch.autocast('cuda',dtype=torch.bfloat16):p=model(x,g,c);d=feature(p.float(),t)
        total+=d.item()*len(x);n+=len(x)
    return total/n

def main():
    p=argparse.ArgumentParser();p.add_argument('--cache',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    choice=p.add_mutually_exclusive_group(required=True);choice.add_argument('--initialize',type=Path);choice.add_argument('--resume',type=Path)
    p.add_argument('--allow-new-cache',action='store_true',help='with --initialize only, rebind an existing model to a new cache identity and reset its optimizer')
    p.add_argument('--upgrade-context',action='store_true',help='Initialize spatial context attention from a v2 checkpoint')
    p.add_argument('--upgrade-style',action='store_true',help='Initialize the whole-eye style branch from a context-v3 checkpoint')
    p.add_argument('--dynamic-guides',type=Path,help='Use fresh raw native crops per epoch and this full-eye guide cache')
    p.add_argument('--face-audit',type=Path,help='Optional training-only face audit; two of eight slots target faces')
    p.add_argument('--dynamic-color-io',choices=('mmap','strip'),default='mmap')
    p.add_argument('--source-balance',action='store_true',help='Match merged-cache training-patch source proportions while sampling')
    p.add_argument('--patch-size',type=int,default=512,help='Dynamic training crop size; >=512 and divisible by 4')
    p.add_argument('--batch',type=int,default=4,help='Dynamic training batch size')
    p.add_argument('--workers',type=int,default=0,help='Dynamic native-crop prefetch workers; zero keeps synchronous loading')
    p.add_argument('--vgg-weight',type=float,default=0,help='Additional full-patch VGG appearance loss; zero preserves existing objective')
    p.add_argument('--face-loss-weight',type=float,default=0,help='Extra pixel weighting inside detected training face boxes; zero preserves existing objective')
    p.add_argument('--tone-weight',type=float,default=0,help='Optional 16-pixel pooled RGB tone loss; zero preserves existing objective')
    p.add_argument('--steps',type=int,default=30000);p.add_argument('--lr',type=float,default=.0001);p.add_argument('--feature-weight',type=float,default=.05);p.add_argument('--eval-every',type=int,default=1000);a=p.parse_args()
    if a.initialize and (a.output/'run.json').exists():raise ValueError('Fresh initialization requires a new output directory')
    if a.allow_new_cache and not a.initialize:raise ValueError('--allow-new-cache is valid only with --initialize; resumes must keep the original cache identity')
    if a.workers<0 or (a.workers and not a.dynamic_guides):raise ValueError('Prefetch workers require dynamic guides')
    if a.source_balance and a.workers:raise ValueError('--source-balance currently requires --workers 0')
    if a.patch_size<512 or a.patch_size%4:raise ValueError('--patch-size must be >=512 and divisible by 4')
    if a.batch<1:raise ValueError('--batch must be positive')
    if a.vgg_weight<0:raise ValueError('Negative VGG loss weight')
    if a.face_loss_weight<0:raise ValueError('Negative face loss weight')
    if a.tone_weight<0:raise ValueError('Negative tone loss weight')
    if a.face_audit and not a.dynamic_guides:raise ValueError('Face sampling requires dynamic guides')
    if a.face_loss_weight and not a.face_audit:raise ValueError('Face loss requires --face-audit')
    a.output.mkdir(parents=True,exist_ok=True);torch.set_num_threads(4);torch.manual_seed(137);random.seed(137);np.random.seed(137);torch.backends.cudnn.benchmark=True
    train=CachedPatches(a.cache,'train');val=DataLoader(CachedPatches(a.cache,'validation'),batch_size=8,pin_memory=True)
    sampling=dict(mode='fixed_cache')
    if a.dynamic_guides:
        from dynamic_patches import DynamicPatches
        train=DynamicPatches(a.cache,a.dynamic_guides,color_io=a.dynamic_color_io,patch_size=a.patch_size)
        sampling=dict(mode='dynamic_native',guide_cache=str(a.dynamic_guides.resolve()),sampler_version=2,seed=1947,patch_size=a.patch_size)
        if a.face_audit:
            from face_patches import FacePatches
            train=FacePatches(a.cache,a.dynamic_guides,a.face_audit,color_io=a.dynamic_color_io,patch_size=a.patch_size)
            sampling.update(mode='dynamic_native_faces',face_sha256=train.face_sha256,face_seed=2719,face_slots=2,face_sampler_version=2)
    cache=json.loads((a.cache/'complete.json').read_text())
    source_labels=None;source_ratio=None
    if a.source_balance:
        if not cache.get('source_caches'):
            raise ValueError('--source-balance requires a merged cache with source_caches provenance')
        rows=json.loads((a.cache/'rows.json').read_text())
        plan=json.loads((a.cache/'patches.json').read_text())
        counts={}
        for patch in plan:
            if patch.get('split')!='train':continue
            source=rows[int(patch['row'])].get('cache_source')
            if not source:raise ValueError('Merged row has no cache_source')
            counts[source]=counts.get(source,0)+1
        if len(counts)!=2:raise ValueError('Expected two merged training sources')
        source_names=sorted(counts)
        source_ratio=counts[source_names[0]]/sum(counts.values())
        if hasattr(train,'row_ids'):
            source_labels=[rows[int(ri)].get('cache_source') for ri in train.row_ids for _ in range(8)]
        else:
            source_labels=[rows[int(plan[int(pi)]['row'])].get('cache_source') for pi in train.ids]
        if any(not s for s in source_labels):raise ValueError('Training source label missing')
        sampling.update(source_balance=True,source_patch_counts=counts,source_ratio=source_ratio,source_seed=137)
    saved=torch.load(a.resume or a.initialize,map_location='cuda',weights_only=False)
    if saved.get('architecture') not in ('reconstruction_v2','context_v3','context_v4'):raise ValueError('Expected reconstruction architecture')
    if a.upgrade_context and a.upgrade_style:raise ValueError('Choose one architecture upgrade')
    if a.upgrade_context and (a.resume or saved['architecture']!='reconstruction_v2'):raise ValueError('Context upgrade requires fresh initialization from v2')
    if a.upgrade_style and (a.resume or saved['architecture']!='context_v3'):raise ValueError('Style upgrade requires fresh initialization from context-v3')
    parent_cache=saved.get('cache',{})
    cache_matches=parent_cache.get('rows_sha256')==cache.get('rows_sha256')
    if not cache_matches and not (a.initialize and a.allow_new_cache):raise ValueError('Dataset identity mismatch; use --allow-new-cache only for an intentional --initialize rebind')
    config=ReconstructionConfig(**saved['config']);architecture='context_v4' if a.upgrade_style else ('context_v3' if a.upgrade_context else saved['architecture'])
    if architecture=='context_v4':
        from student_v4 import StyleContextStudent
        model=StyleContextStudent(config).cuda()
    elif architecture=='context_v3':
        from student_v3 import ContextStudent
        model=ContextStudent(config).cuda()
    else:model=ReconstructionStudent(config).cuda()
    if a.upgrade_style:model.initialize_v3(saved['model'])
    elif a.upgrade_context:model.initialize_v2(saved['model'])
    else:model.load_state_dict(saved.get('raw_model',saved['model']) if a.resume else saved['model'])
    ema=deepcopy(model)
    opt=torch.optim.AdamW(model.parameters(),lr=a.lr,weight_decay=.0001);feature=FeatureDistance().cuda().eval()
    appearance=None
    if a.vgg_weight:
        from vgg_appearance_loss import VGGAppearanceLoss
        appearance=VGGAppearanceLoss().cuda().eval()
    schedule=dict(steps=a.steps,lr=a.lr,feature_weight=a.feature_weight)
    if a.vgg_weight:schedule['vgg_weight']=a.vgg_weight
    if a.face_loss_weight:schedule['face_loss_weight']=a.face_loss_weight
    if a.tone_weight:schedule['tone_weight']=a.tone_weight
    start_step=0;best_mae=best_feature=float('inf');seed=137
    if a.resume:
        if saved.get('sampling',dict(mode='fixed_cache'))!=sampling:raise ValueError('Resume sampling contract differs')
        ema.load_state_dict(saved['model']);opt.load_state_dict(saved['optimizer']);start_step=saved['step'];best_mae=saved['best_mae'];best_feature=saved['best_feature']
        random.setstate(saved['python_rng']);np.random.set_state(saved['numpy_rng']);torch.set_rng_state(saved['torch_rng'].cpu());torch.cuda.set_rng_state_all([x.cpu() for x in saved['cuda_rng']])
        expected=saved['schedule']
        if expected!=schedule:raise ValueError('Resume schedule differs; start an explicit new phase instead')
    run=dict(architecture=architecture,config=asdict(config),sampling=sampling,context_upgrade=a.upgrade_context,cache=cache,initialize=str(a.initialize),resume=str(a.resume),parent_step=saved['step'],schedule=schedule,batch=a.batch,patch_size=a.patch_size,training_patches=len(train),additional_epoch_equivalents=a.steps*a.batch/len(train),pid=os.getpid(),test_used=False,optimizer_reset=bool(a.initialize),dataset_rebound=bool(a.initialize and not cache_matches),parent_cache_rows_sha256=parent_cache.get('rows_sha256'),selection='save separate best MAE and best feature checkpoints; do not treat training feature metric as independent quality proof')
    run['dynamic_color_io']=a.dynamic_color_io if a.dynamic_guides else None
    run['workers']=a.workers
    run['vgg_appearance']=appearance.provenance if appearance is not None else None
    run['face_loss_weight']=a.face_loss_weight
    run['tone_loss_weight']=a.tone_weight
    atomic_json(a.output/'run.json',run)
    def checkpoint(name,step):
        payload=dict(architecture=architecture,config=asdict(config),sampling=sampling,cache=cache,model=ema.state_dict(),raw_model=model.state_dict(),optimizer=opt.state_dict(),step=step,best_mae=best_mae,best_feature=best_feature,schedule=schedule,run=run,python_rng=random.getstate(),numpy_rng=np.random.get_state(),torch_rng=torch.get_rng_state(),cuda_rng=torch.cuda.get_rng_state_all())
        tmp=a.output/(name+'.tmp');torch.save(payload,tmp);tmp.replace(a.output/(name+'.pt'))
    started=time.time()
    def validate(step):
        nonlocal best_mae,best_feature
        m=evaluate(ema,val,'cuda');m['feature_distance']=feature_score(ema,val,feature)
        if m['mae']<best_mae:best_mae=m['mae'];checkpoint('best_mae',step)
        if m['feature_distance']<best_feature:best_feature=m['feature_distance'];checkpoint('best_feature',step)
        checkpoint('last',step)
        record=dict(step=step,seconds=time.time()-started,metrics=m)
        with (a.output/'history.jsonl').open('a') as log:log.write(json.dumps(record)+'\n')
        print(json.dumps(record),flush=True)
    if not a.resume:validate(0)
    prefetched=None
    if a.workers:
        from prefetch_dynamic import EpochBatches
        batches=EpochBatches(len(train),a.batch,start_step+1,a.steps,seed)
        prefetched=iter(DataLoader(train,batch_sampler=batches,num_workers=a.workers,pin_memory=True,prefetch_factor=2,generator=torch.Generator().manual_seed(seed)))
    for step in range(start_step+1,a.steps+1):
        ids,epoch=(source_weighted_indices(source_labels,a.batch,step,source_ratio,seed) if source_labels is not None else epoch_indices(len(train),a.batch,step,seed))
        if prefetched is not None:b=next(prefetched)
        else:
            if a.dynamic_guides:train.set_epoch(epoch)
            b=default_collate([train[i] for i in ids])
        x,t,g,c=batch_to_device(b,'cuda',augment=True)
        lr=a.lr*(.1+.9*.5*(1+math.cos(math.pi*(step-1)/a.steps)))
        for group in opt.param_groups:group['lr']=lr
        model.train();opt.zero_grad(set_to_none=True)
        focus=None
        if a.face_loss_weight:
            if 'face_mask' not in b:raise RuntimeError('Face loss requested but batch has no face_mask')
            focus=b['face_mask'].to('cuda',non_blocking=True).float()
        with torch.autocast('cuda',dtype=torch.bfloat16):
            pred=model(x,g,c);loss=detail_loss(pred.float(),t,x,focus=focus,focus_weight=a.face_loss_weight)+a.feature_weight*feature(pred.float(),t)
            if appearance is not None:loss=loss+a.vgg_weight*appearance(pred,t)
            if a.tone_weight:loss=loss+a.tone_weight*tone_loss(pred.float(),t)
        if not torch.isfinite(loss):raise RuntimeError('Nonfinite loss')
        loss.backward();gn=torch.nn.utils.clip_grad_norm_(model.parameters(),1.)
        if not torch.isfinite(gn):raise RuntimeError('Nonfinite gradient')
        opt.step()
        with torch.no_grad():
            for ep,mp in zip(ema.parameters(),model.parameters()):ep.lerp_(mp,.005)
        if step%50==0:
            status=dict(state='training',pid=os.getpid(),step=step,total=a.steps,epoch=epoch,loss=loss.item(),lr=lr,best_mae=best_mae,best_feature=best_feature,seconds=time.time()-started)
            atomic_json(a.output/'status.json',status);print(json.dumps(status),flush=True)
        if step%a.eval_every==0 or step==a.steps:validate(step)
    atomic_json(a.output/'status.json',dict(state='completed',pid=os.getpid(),step=a.steps,best_mae=best_mae,best_feature=best_feature,seconds=time.time()-started))

if __name__=='__main__':main()
