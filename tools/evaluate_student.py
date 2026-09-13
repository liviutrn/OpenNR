"""Frozen-test evaluation, native-eye inference, visual evidence and warm timings."""
import argparse,json,time,hashlib,math
from pathlib import Path
from collections import defaultdict
import numpy as np
from PIL import Image,ImageDraw
import torch
from torch.utils.data import DataLoader
from master_dataset import sample_guide
from opennr_student import load_student
from train_student import CachedPatches,evaluate,atomic_json

def raw_path(value):
    """Accept either a raw artifact path or a legacy stem/path."""
    path=Path(value)
    return path if path.name.endswith('.raw.bin') else path.with_suffix('.raw.bin')

def load_eye(row,context):
    w,h=row['color_size'];gw,gh=row['guide_size'];colors=[]
    for s in ('input','teacher'):
        a=np.memmap(raw_path(row['paths'][s]),mode='r',dtype='u1',shape=(h,w,4))
        colors.append(torch.from_numpy(np.ascontiguousarray(a[:,:,:3].transpose(2,0,1))).float()[None]/255)
    d=np.memmap(row['paths']['depth'],mode='r',dtype='<f4',shape=(gh,gw,1));dv=np.isfinite(d[:,:,0])&(d[:,:,0]>=0)&(d[:,:,0]<=1)
    m=np.memmap(row['paths']['motion_vectors'],mode='r',dtype='<f2',shape=(gh,gw,2)).astype('f4');mv=np.isfinite(m).all(2)&(np.abs(m)<=.25).all(2)
    d=np.where(dv[:,:,None],d,0);m=np.where(mv[:,:,None],m,0)
    m[:,:,0]*=row['motion_scale'][0]*w/gw;m[:,:,1]*=row['motion_scale'][1]*h/gh
    d,dm=sample_guide(d,(0,0,w,h),(w,h),(h//4,w//4),dv)
    m,mm=sample_guide(np.clip(m,-128,128)/128,(0,0,w,h),(w,h),(h//4,w//4),mv)
    return colors[0].cuda(),colors[1].cuda(),torch.cat((d*dm,m*mm,dm,mm),0)[None].cuda(),torch.from_numpy(np.array(context,copy=True)).float()[None].cuda()

def pil(t):return Image.fromarray((t[0].detach().float().clamp(0,1).cpu().numpy().transpose(1,2,0)*255).round().astype('u1'))

@torch.inference_mode()
def main():
    p=argparse.ArgumentParser();p.add_argument('--cache',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    torch.set_num_threads(4);torch.backends.cudnn.benchmark=True
    pipeline=json.loads((a.output/'pipeline_status.json').read_text())
    if pipeline['state']!='training_completed':raise ValueError('Finish validation selection before test evaluation')
    checkpoints={v['label']:v['checkpoint'] for v in pipeline['comparisons']};checkpoints['selected']=pipeline['best_checkpoint']
    report={'selection':'validation only; test evaluated after checkpoint frozen','patch_test':{},'full_test':{},'timings':{}}
    test=DataLoader(CachedPatches(a.cache,'test'),batch_size=8,pin_memory=True)
    for label,path in checkpoints.items():
        model,ckpt=load_student(path,'cuda');metrics=evaluate(model,test,'cuda');report['patch_test'][label]=dict(checkpoint=path,step=ckpt['step'],parameters=sum(p.numel() for p in model.parameters()),**metrics)
        print(label,json.dumps({k:v for k,v in metrics.items() if k not in ('sequence_mae','eye_mae')}),flush=True)
        del model
    model,ckpt=load_student(pipeline['best_checkpoint'],'cuda')
    # Small portable inference-only state. Raw training/optimizer state remains in best.pt.
    portable=a.output/'OpenNR_Student_v1.pt';torch.save(dict(config=ckpt['config'],model=ckpt['model'],step=ckpt['step'],cache=ckpt['cache'],selection='validation_only'),portable)
    report['checkpoint_sha256']=hashlib.sha256(portable.read_bytes()).hexdigest()
    rows=json.loads((a.cache/'rows.json').read_text());context=np.load(a.cache/'context.npy',mmap_mode='r');ids=[i for i,r in enumerate(rows) if r['split']=='test']
    sums=np.zeros(5);perseq=defaultdict(list);pereye=defaultdict(list);records=[];start=time.time()
    preview=a.output/'previews';preview.mkdir(exist_ok=True)
    chosen={0,1,len(ids)//2//2*2,len(ids)//2//2*2+1,len(ids)-2,len(ids)-1}
    for n,i in enumerate(ids):
        row=rows[i];rgb,target,g,c=load_eye(row,context[i]);torch.cuda.synchronize()
        begin=time.perf_counter()
        with torch.autocast('cuda',dtype=torch.bfloat16):pred=model(rgb,g,c)
        torch.cuda.synchronize();elapsed=(time.perf_counter()-begin)*1000
        err=pred.float()-target;base=rgb-target
        stats=np.array([err.abs().sum().item(),err.square().sum().item(),base.abs().sum().item(),base.square().sum().item(),target.numel()]);sums+=stats
        item=dict(sequence_id=row['sequence_id'],frame_id=row['frame_id'],eye=row['eye'],mae=stats[0]/stats[4],identity_mae=stats[2]/stats[4],inference_ms=elapsed)
        perseq[row['sequence_id']].append(item['mae']);pereye[str(row['eye'])].append(item['mae']);records.append(item)
        if n==0:
            report['timings']['first_native_eye_ms']=elapsed;times=[]
            for _ in range(12):
                t0=torch.cuda.Event(enable_timing=True);t1=torch.cuda.Event(enable_timing=True);t0.record()
                with torch.autocast('cuda',dtype=torch.bfloat16):model(rgb,g,c)
                t1.record();torch.cuda.synchronize();times.append(t0.elapsed_time(t1))
            report['timings'].update(warm_eye_median_ms=float(np.median(times[2:])),warm_eye_p95_ms=float(np.percentile(times[2:],95)),sequential_stereo_estimate_ms=float(2*np.median(times[2:])),scope='CUDA model forward, bf16 autocast, resident tensors; excludes CPU guide loading, capture, compositor and runtime integration',resolution=row['color_size'])
        if n in chosen:
            tag=f'{n:03d}_{row["sequence_id"]}_f{row["frame_id"]}_e{row["eye"]}'
            inp,out,teacher=pil(rgb),pil(pred),pil(target);out.save(preview/(tag+'_prediction.png'))
            sheet=Image.new('RGB',(1440,555),'#171b22');draw=ImageDraw.Draw(sheet)
            for j,(label,im) in enumerate((('Input',inp),('OpenNR student',out),('Feature 18 teacher',teacher))):
                draw.text((j*480+8,8),label,fill='white');im.thumbnail((480,518));sheet.paste(im,(j*480,32))
            sheet.save(preview/(tag+'_comparison.jpg'),quality=94)
        if (n+1)%16==0:
            print(f'full native test {n+1}/{len(ids)} eyes, {time.time()-start:.1f}s',flush=True)
            atomic_json(a.output/'evaluation_status.json',dict(state='full_test',eyes=n+1,total=len(ids)))
        del rgb,target,g,c,pred,err,base
    report['full_test']=dict(eyes=len(ids),stereo_frames=len(ids)//2,mae=sums[0]/sums[4],psnr=-10*math.log10(sums[1]/sums[4]),identity_mae=sums[2]/sums[4],identity_psnr=-10*math.log10(sums[3]/sums[4]),improvement_pct=100*(sums[2]-sums[0])/sums[2],sequence_mae={s:float(np.mean(v)) for s,v in perseq.items()},eye_mae={s:float(np.mean(v)) for s,v in pereye.items()},seconds=time.time()-start)
    report['timings']['gpu_peak_gib']=torch.cuda.max_memory_allocated()/2**30
    atomic_json(a.output/'evaluation.json',report);atomic_json(a.output/'full_test_frames.json',records);atomic_json(a.output/'evaluation_status.json',dict(state='completed',eyes=len(ids)))
    print(json.dumps(report),flush=True)

if __name__=='__main__':main()
