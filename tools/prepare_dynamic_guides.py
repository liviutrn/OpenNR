"""Cache full-eye quarter-resolution guides for fresh training crops each epoch.

Color remains in the audited raw files; validation/test rows are not processed.
Only the guide cache is new. Crop origins must be divisible by four.

The merged spatial corpus can contain multiple native color resolutions.  The
cache therefore stores one memory-mapped guide tensor per resolution and keeps
the row-to-group mapping in ``complete.json``.  The older single-tensor format
remains supported by :mod:`dynamic_patches`.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import time
import numpy as np
import torch
from master_dataset import sample_guide
from train_student import atomic_json


def main():
    p=argparse.ArgumentParser();p.add_argument('--cache',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    base=json.loads((a.cache/'complete.json').read_text());rows=json.loads((a.cache/'rows.json').read_text())
    ids=[i for i,r in enumerate(rows) if r['split']=='train']
    if not ids:raise ValueError('No training rows in cache')
    sizes=sorted({tuple(rows[i]['color_size']) for i in ids})
    if any(w%4 or h%4 for w,h in sizes):raise ValueError('Expected dimensions divisible by four')
    if (a.output/'complete.json').exists():
        completed=json.loads((a.output/'complete.json').read_text())
        if completed['rows_sha256']!=base['rows_sha256']:raise ValueError('Existing cache identity differs')
        print('Completed dynamic guide cache already exists');return
    if a.output.exists() and any(a.output.iterdir()):raise ValueError('Incomplete output exists; preserve it and use a fresh directory')
    a.output.mkdir(parents=True,exist_ok=True);torch.set_num_threads(1)
    # Each group is a separate memmap because native rows in the merged cache
    # are not all the same size.  Keep the global training-row order in the
    # top-level row_ids file and the local group order in each group record.
    groups=[]
    group_by_size={}
    for w,h in sizes:
        group_ids=[i for i in ids if tuple(rows[i]['color_size'])==(w,h)]
        filename=f'guides_{w}x{h}.npy'
        dst=np.lib.format.open_memmap(a.output/filename,mode='w+',dtype='<f2',shape=(len(group_ids),5,h//4,w//4))
        groups.append(dict(color_size=[w,h],row_ids=group_ids,file=filename,shape=[len(group_ids),5,h//4,w//4],dtype='float16'))
        group_by_size[(w,h)]=(dst,group_ids)
    (a.output/'row_ids.json').write_text(json.dumps(ids));started=time.time()
    def work(item):
        j,i=item;row=rows[i];w,h=row['color_size'];gw,gh=row['guide_size']
        dp=Path(row['paths']['depth']);mp=Path(row['paths']['motion_vectors'])
        if dp.stat().st_size!=gw*gh*4 or mp.stat().st_size!=gw*gh*4:raise ValueError('Raw guide size changed')
        depth=np.memmap(dp,dtype='<f4',mode='r',shape=(gh,gw,1));dv=np.isfinite(depth[...,0])&(depth[...,0]>=0)&(depth[...,0]<=1)
        motion=np.memmap(mp,dtype='<f2',mode='r',shape=(gh,gw,2)).astype('f4');mv=np.isfinite(motion).all(2)&(np.abs(motion)<=.25).all(2)
        motion=np.where(mv[...,None],motion,0)
        motion[...,0]*=row['motion_scale'][0]*w/gw;motion[...,1]*=row['motion_scale'][1]*h/gh
        d,dm=sample_guide(np.where(dv[...,None],depth,0),(0,0,w,h),(w,h),(h//4,w//4),dv)
        m,mm=sample_guide(np.clip(motion,-128,128)/128,(0,0,w,h),(w,h),(h//4,w//4),mv)
        value=torch.cat((d*dm,m*mm,dm,mm),0).numpy().astype('f2')
        if not np.isfinite(value).all():raise ValueError('Nonfinite prepared guides')
        dst,group_ids=group_by_size[(w,h)]
        dst[group_ids.index(i)]=value
    with ThreadPoolExecutor(max_workers=2) as pool:
        for done,_ in enumerate(pool.map(work,enumerate(ids)),1):
            if done%32==0:
                state=dict(state='preparing',completed=done,total=len(ids),seconds=time.time()-started)
                atomic_json(a.output/'status.json',state);print(json.dumps(state),flush=True)
    for dst,_ in group_by_size.values():dst.flush()
    atomic_json(a.output/'complete.json',dict(schema=2,rows_sha256=base['rows_sha256'],base_cache=str(a.cache.resolve()),training_eyes=len(ids),groups=groups,guide_stride=4,training_only=True,seconds=time.time()-started))
    atomic_json(a.output/'status.json',dict(state='completed',training_eyes=len(ids)))
    print('Dynamic guide cache complete',flush=True)


if __name__=='__main__':main()
