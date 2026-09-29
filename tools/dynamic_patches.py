"""Deterministic epoch-varying native crops with aligned cached native guides."""
from collections import OrderedDict
import hashlib
import json
from pathlib import Path
import numpy as np
import torch
from torch.utils.data import Dataset


def row_manifest_digest(rows, meta):
    """Reproduce the row-hash convention used by the source cache.

    Legacy caches use sorted JSON; merged schema-3 caches preserve the
    compact merge-time encoding so downstream dynamic caches bind to the same
    immutable row identity.
    """
    if meta.get('schema') == 3 and meta.get('source_type') == 'merged_compatible_spatial_caches':
        payload=json.dumps(rows,separators=(',',':'),ensure_ascii=False).encode('utf-8')
    else:
        payload=json.dumps(rows,sort_keys=True).encode('utf-8')
    return hashlib.sha256(payload).hexdigest()


def raw_color_path(path):
    """Return the committed RGBA raw path for PNG-backed or raw-backed rows."""
    path=Path(path)
    return path if path.name.endswith('.raw.bin') else path.with_suffix('.raw.bin')


class DynamicPatches(Dataset):
    def __init__(self,cache,guides,color_io='mmap',patch_size=512):
        if color_io not in ('mmap','strip'):raise ValueError('Unknown color I/O strategy')
        if patch_size < 512 or patch_size % 4:raise ValueError('patch_size must be >=512 and divisible by 4')
        self.color_io=color_io
        self.patch_size=int(patch_size)
        self.root=Path(cache);self.guide_root=Path(guides)
        base=json.loads((self.root/'complete.json').read_text());meta=json.loads((self.guide_root/'complete.json').read_text())
        if meta['rows_sha256']!=base['rows_sha256'] or not meta['training_only'] or meta['guide_stride']!=4:raise ValueError('Dynamic guide contract mismatch')
        self.rows=json.loads((self.root/'rows.json').read_text());self.row_ids=json.loads((self.guide_root/'row_ids.json').read_text())
        if row_manifest_digest(self.rows,base)!=base['rows_sha256']:raise ValueError('Source row manifest changed')
        if self.row_ids!=[i for i,r in enumerate(self.rows) if r['split']=='train']:raise ValueError('Training row mapping mismatch')
        self.context=np.load(self.root/'context.npy',mmap_mode='r')
        self.guide_groups=[]
        self.guide_lookup=[]
        if meta.get('schema',1)>=2 and 'groups' in meta:
            # Mixed-resolution guide cache.  Group row IDs are absolute source
            # row IDs; lookup is in top-level training-row order.
            group_by_row={}
            for gi,group in enumerate(meta['groups']):
                ids=list(group['row_ids']); w,h=group['color_size']
                arr=np.load(self.guide_root/group['file'],mmap_mode='r')
                expected=tuple(group['shape'])
                if arr.shape!=expected or arr.dtype!=np.float16 or expected!=(len(ids),5,h//4,w//4):
                    raise ValueError('Dynamic guide group shape/type mismatch')
                self.guide_groups.append(arr)
                for slot,ri in enumerate(ids):
                    if ri in group_by_row:raise ValueError('Duplicate dynamic guide row')
                    group_by_row[ri]=(gi,slot)
            if set(group_by_row)!=set(self.row_ids):raise ValueError('Dynamic guide groups do not cover training rows')
            self.guide_lookup=[group_by_row[ri] for ri in self.row_ids]
        else:
            self.guides=np.load(self.guide_root/'guides.npy',mmap_mode='r');w,h=meta['color_size']
            if self.guides.shape!=(len(self.row_ids),5,h//4,w//4) or self.guides.dtype!=np.float16:raise ValueError('Dynamic guide tensor shape/type mismatch')
            self.guide_groups=[self.guides]
            self.guide_lookup=[(0,j) for j in range(len(self.row_ids))]
        if self.context.shape!=(len(self.rows),8,96,96):raise ValueError('Whole-eye context shape mismatch')
        self.epoch=0;self.maps=OrderedDict()

    def __len__(self):return len(self.row_ids)*8

    def __getstate__(self):
        # Windows workers must reopen mappings, never pickle the multi-GB arrays.
        return dict(cache=str(self.root),guides=str(self.guide_root),color_io=self.color_io,patch_size=self.patch_size,epoch=self.epoch)

    def __setstate__(self,state):
        self.__init__(state['cache'],state['guides'],state['color_io'],state['patch_size']);self.epoch=state['epoch']

    def set_epoch(self,epoch):
        if epoch<0:raise ValueError('Negative epoch')
        self.epoch=epoch

    def box(self,index,epoch=None):
        if not 0<=index<len(self):raise IndexError(index)
        row=self.rows[self.row_ids[index//8]];w,h=row['color_size'];size=self.patch_size
        if size > min(w,h):raise ValueError('patch_size exceeds native color dimensions')
        rng=np.random.default_rng(np.random.SeedSequence([1947,self.epoch if epoch is None else epoch,index]))
        return int(rng.integers((w-size)//4+1))*4,int(rng.integers((h-size)//4+1))*4,size,size

    def __getitem__(self,index):
        epoch=self.epoch
        if isinstance(index,tuple):epoch,index=index
        x,y,pw,ph=self.box(index,epoch);j=index//8;ri=self.row_ids[j];row=self.rows[ri];w,h=row['color_size']
        if self.color_io=='strip':
            images=[]
            for stage in ('input','teacher'):
                path=raw_color_path(row['paths'][stage])
                if path.stat().st_size!=w*h*4:raise ValueError('Raw color size changed')
                strip=np.fromfile(path,dtype='u1',count=ph*w*4,offset=y*w*4)
                if strip.size!=ph*w*4:raise ValueError('Truncated raw color strip')
                crop=strip.reshape(ph,w,4)[:,x:x+pw,:3]
                images.append(torch.from_numpy(np.ascontiguousarray(crop.transpose(2,0,1))))
        elif ri not in self.maps:
            images=[]
            for stage in ('input','teacher'):
                path=raw_color_path(row['paths'][stage])
                if path.stat().st_size!=w*h*4:raise ValueError('Raw color size changed')
                images.append(np.memmap(path,mode='r',dtype='u1',shape=(h,w,4)))
            self.maps[ri]=images
            if len(self.maps)>16:self.maps.popitem(last=False)
        if self.color_io=='mmap':
            self.maps.move_to_end(ri)
            images=[torch.from_numpy(np.ascontiguousarray(im[y:y+ph,x:x+pw,:3].transpose(2,0,1))) for im in self.maps[ri]]
        gi,slot=self.guide_lookup[j]
        guides=self.guide_groups[gi]
        return dict(rgb=images[0],target=images[1],guides=torch.from_numpy(np.array(guides[slot,:,y//4:(y+ph)//4,x//4:(x+pw)//4],copy=True)),context=torch.from_numpy(np.array(self.context[ri],copy=True)),seq=row['sequence_id'],eye=row['eye'],index=index,box=(x,y,pw,ph))
