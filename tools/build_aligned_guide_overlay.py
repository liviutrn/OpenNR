"""Rebuild only train/validation guide/context arrays; reference immutable RGB.

Test rows remain zero and are explicitly forbidden to overlay consumers.
No original file is changed. Relocations are explicit old-root=new-root pairs.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import copy
import hashlib
import json
from pathlib import Path
import time
import numpy as np
import torch
from aligned_native_guides import sample_aligned
from build_raw_crop_cache import _guide_arrays
from prepare_conditioning_pilot import save,sha


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--cache',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--relocate',action='append',default=[])
    p.add_argument('--workers',type=int,default=4)
    a=p.parse_args()
    if a.output.exists(): raise FileExistsError(a.output)
    rows=json.loads((a.cache/'rows.json').read_text())
    source_sha=sha(a.cache/'complete.json')
    rows_sha=sha(a.cache/'rows.json')
    relocations=[tuple(s.split('=',1)) for s in a.relocate]
    def resolve(path):
        path=Path(path)
        if path.is_file(): return path
        for old,new in relocations:
            try: relative=path.relative_to(Path(old))
            except ValueError: continue
            relocated=Path(new)/relative
            if relocated.is_file(): return relocated
        raise FileNotFoundError(path)
    selected=[i for i,r in enumerate(rows) if r['split'] in ('train','validation')]
    for i in selected:
        for stage in ('depth','motion_vectors'):
            rows[i]['paths'][stage]=str(resolve(rows[i]['paths'][stage]))
    a.output.mkdir(parents=True)
    torch.set_num_threads(1)
    n=len(rows)
    guides=np.lib.format.open_memmap(a.output/'guides.npy',mode='w+',dtype='<f2',shape=(n,5,128,128))
    contexts=np.lib.format.open_memmap(a.output/'context.npy',mode='w+',dtype='<f2',shape=(n,8,96,96))
    old_context=np.load(a.cache/'context.npy',mmap_mode='r')
    started=time.time()
    def work(i):
        row=rows[i]
        values=_guide_arrays(row)
        g=sample_aligned(row,*values,128)
        c=sample_aligned(row,*values,96)
        if not np.isfinite(g).all() or not np.isfinite(c).all(): raise ValueError('Nonfinite corrected guide')
        guides[i]=g
        contexts[i,:3]=old_context[i,:3]
        contexts[i,3:]=c
        hashes=[sha(row['paths'][stage]) for stage in ('depth','motion_vectors')]
        return i,hashes
    digest=hashlib.sha256()
    with ThreadPoolExecutor(max_workers=a.workers) as pool:
        for done,(i,hashes) in enumerate(pool.map(work,selected),1):
            digest.update(json.dumps([i,hashes]).encode())
            if done%512==0 or done==len(selected):
                status={'rows_done':done,'rows_total':len(selected),'seconds':time.time()-started}
                save(a.output/'status.json',status)
                print(json.dumps(status),flush=True)
    guides.flush();contexts.flush()
    if sha(a.cache/'complete.json')!=source_sha or sha(a.cache/'rows.json')!=rows_sha:
        raise ValueError('Source identity changed')
    complete={'schema':'opennr-aligned-native-guide-overlay-v1','source_cache':str(a.cache.resolve()),
        'source_complete_sha256':source_sha,'source_rows_sha256':rows_sha,'rows':n,
        'populated_splits':['train','validation'],'test_allowed':False,'test_rows':'unpopulated; prohibited',
        'source_guide_payloads_sha256':digest.hexdigest(),'relocations':relocations,
        'array_sha256':{name:sha(a.output/(name+'.npy')) for name in ('guides','context')},
        'sampling':'same bilinear/strict-valid support as legacy sampler; corrected native crop box; RGB context unchanged',
        'seconds':time.time()-started}
    save(a.output/'complete.json',complete)
    print(json.dumps(complete),flush=True)


if __name__=='__main__': main()
