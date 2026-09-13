"""Create audited native RGB patches and aligned guide/context cache on a roomy disk."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import time
import numpy as np
from PIL import Image
import torch
import torch.nn.functional as F
from master_dataset import sample_guide

def extend_manifest(base, supplemental):
    rows=[json.loads(l) for l in base.read_text().splitlines() if l]
    wanted=rows[0]['teacher_settings']; seen={r['sequence_id'] for r in rows}
    root=Path(json.loads((supplemental/'summary.json').read_text())['root'])
    added=[]
    for path in sorted((supplemental/'sequences').glob('*.json')):
        audit=json.loads(path.read_text()); seq=root/audit['sequence_id']
        if seq.name in seen or not (seq/'frames.jsonl').exists(): continue
        if hashlib.sha256((seq/'frames.jsonl').read_bytes()).hexdigest()!=audit['manifest_sha256']: raise ValueError('changed manifest')
        frames={f['frame_id']:f for f in map(json.loads,(seq/'frames.jsonl').read_text().splitlines())}
        for a in audit['frames']:
            if a['errors'] or a['teacher_settings']!=wanted or (a['color_width'],a['color_height'])!=(2496,2688): continue
            f=frames[a['frame_id']]
            for eye in (0,1):
                arts={x['stage']:x for x in f['artifacts'] if x.get('full_frame') and x['eye']==eye}
                paths={s:str(seq/arts[s]['png_path' if s in ('input','teacher') else 'raw_path']) for s in ('input','teacher','depth','motion_vectors')}
                added.append(dict(sequence_id=seq.name,frame_id=f['frame_id'],host_frame=f['host_frame'],eye=eye,split='train',color_size=[f['color_width'],f['color_height']],guide_size=[f['guide_width'],f['guide_height']],paths=paths,motion_scale=[f['motion_vector_scale_x'][eye],f['motion_vector_scale_y'][eye]],history_reset=f['history_reset'][eye],teacher_settings=wanted,source='audited_supplemental'))
    return rows+added

def main():
    p=argparse.ArgumentParser();p.add_argument('--manifest',type=Path,required=True);p.add_argument('--supplemental',type=Path);p.add_argument('--output',type=Path,required=True);p.add_argument('--workers',type=int,default=3);p.add_argument('--training-role',default='spatial_only_auxiliary');a=p.parse_args()
    from opennr_paths import require_external_output
    a.output=require_external_output(a.output)
    torch.set_num_threads(1)
    a.output.mkdir(parents=True,exist_ok=True)
    if (a.output/'complete.json').exists(): print('Completed cache exists; use a new output to change data');return
    rows=extend_manifest(a.manifest,a.supplemental) if a.supplemental else [json.loads(l) for l in a.manifest.read_text().splitlines()]
    fingerprint=hashlib.sha256(json.dumps(rows,sort_keys=True).encode()).hexdigest()
    plan=[]; offsets=[]
    for ri,row in enumerate(rows):
        offsets.append(len(plan)); w,h=row['color_size']; centers=((.5,.5),(.25,.5),(.75,.5),(.5,.25))
        boxes=[(round((w-512)*x),round((h-512)*y),512,512) for x,y in centers]
        if row['split']=='train':
            rng=np.random.default_rng(1947+ri)
            boxes += [(int(rng.integers(0,w-511)),int(rng.integers(0,h-511)),512,512) for _ in range(4)]
        for box in boxes: plan.append(dict(row=ri,box=box,split=row['split'],sequence_id=row['sequence_id'],frame_id=row['frame_id'],eye=row['eye']))
    n=len(plan)
    colors=np.lib.format.open_memmap(a.output/'rgb.npy',mode='w+',dtype='u1',shape=(n,2,3,512,512))
    guides=np.lib.format.open_memmap(a.output/'guides.npy',mode='w+',dtype='<f2',shape=(n,5,128,128))
    contexts=np.lib.format.open_memmap(a.output/'context.npy',mode='w+',dtype='<f2',shape=(len(rows),8,96,96))
    (a.output/'rows.json').write_text(json.dumps(rows));(a.output/'patches.json').write_text(json.dumps(plan))
    start=time.time()
    def work(ri):
        row=rows[ri];w,h=row['color_size'];gw,gh=row['guide_size']
        images=[]
        for s in ('input','teacher'):
            raw=Path(row['paths'][s]).with_suffix('.raw.bin')
            if raw.stat().st_size!=w*h*4: raise ValueError(f'raw size {raw}')
            images.append(np.memmap(raw,mode='r',dtype='u1',shape=(h,w,4))[:,:,:3])
        dep=np.memmap(row['paths']['depth'],mode='r',dtype='<f4',shape=(gh,gw,1))
        dv=np.isfinite(dep[:,:,0])&(dep[:,:,0]>=0)&(dep[:,:,0]<=1)
        dep=np.where(dv[:,:,None],dep,0)
        mv=np.memmap(row['paths']['motion_vectors'],mode='r',dtype='<f2',shape=(gh,gw,2)).astype(np.float32)
        valid=np.isfinite(mv).all(2)&(np.abs(mv)<=.25).all(2)
        mv=np.where(valid[:,:,None],mv,0)
        mv[:,:,0]*=row['motion_scale'][0]*w/gw;mv[:,:,1]*=row['motion_scale'][1]*h/gh
        mv=np.clip(mv,-128,128)/128
        count=8 if row['split']=='train' else 4
        for index in range(offsets[ri],offsets[ri]+count):
            box=plan[index]['box'];x,y,pw,ph=box
            for j,im in enumerate(images):colors[index,j]=im[y:y+ph,x:x+pw].transpose(2,0,1)
            d,dm=sample_guide(dep,box,(w,h),128,dv); m,mm=sample_guide(mv,box,(w,h),128,valid)
            guides[index]=torch.cat((d*dm,m*mm,dm,mm),0).numpy().astype(np.float16)
        rgb=np.asarray(Image.fromarray(np.ascontiguousarray(images[0])).resize((96,96),Image.Resampling.BOX)).astype(np.float32).transpose(2,0,1)/255
        d,dm=sample_guide(dep,(0,0,w,h),(w,h),96,dv);m,mm=sample_guide(mv,(0,0,w,h),(w,h),96,valid)
        contexts[ri]=np.concatenate((rgb,torch.cat((d*dm,m*mm,dm,mm),0).numpy())).astype(np.float16)
        return ri
    with ThreadPoolExecutor(max_workers=a.workers) as pool:
        for done,_ in enumerate(pool.map(work,range(len(rows))),1):
            if done%32==0: print(f'cache {done}/{len(rows)} eyes, {time.time()-start:.1f}s',flush=True)
    colors.flush();guides.flush();contexts.flush()
    counts={s:sum(x['split']==s for x in plan) for s in ('train','validation','test')}
    report=dict(schema=1,source_manifest=str(a.manifest.resolve()),source_manifest_sha256=hashlib.sha256(a.manifest.read_bytes()).hexdigest(),rows_sha256=fingerprint,eye_rows=len(rows),patches=n,counts=counts,seconds=time.time()-start,native_patch=512,guide_patch=128,context=96,supplemental=str(a.supplemental),training_role=a.training_role,temporal_training_allowed=False if a.training_role=='spatial_only_auxiliary' else None,test_used_for_tuning=False)
    (a.output/'complete.json').write_text(json.dumps(report,indent=2));print(json.dumps(report),flush=True)

if __name__=='__main__':main()
