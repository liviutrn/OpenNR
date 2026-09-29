"""Read-only temporal cohort with optional corrected native guide overlay."""
from collections import defaultdict
import json
from pathlib import Path
import numpy as np
from prepare_conditioning_pilot import sha

_VERIFIED_OVERLAYS=set()


class AlignedCohort:
    def __init__(self,root,split,use_legacy_guides=False,expected_pass_count=1):
        if expected_pass_count not in (1,2):raise ValueError('Unsupported teacher mode')
        self.teacher_pass_count=expected_pass_count
        if split not in ('train','validation'):
            raise ValueError('This experiment prohibits frozen-test access')
        self.root=Path(root).resolve()
        self.split=split
        self.complete=json.loads((self.root/'complete.json').read_text())
        renderer_cache=self.complete['schema']=='opennr-aligned-renderer-pilot-v1'
        if not renderer_cache and self.complete['schema']!='opennr-aligned-native-guide-overlay-v1':
            raise ValueError('Expected completed aligned guide overlay')
        if renderer_cache and use_legacy_guides:
            raise ValueError('Renderer cache has no legacy guide variant')
        identity=(str(self.root),sha(self.root/'complete.json'))
        if identity not in _VERIFIED_OVERLAYS:
            for name,digest in self.complete['array_sha256'].items():
                if sha(self.root/(name+'.npy'))!=digest:
                    raise ValueError('Overlay payload identity mismatch')
            _VERIFIED_OVERLAYS.add(identity)
        base=self.root if renderer_cache else Path(self.complete['source_cache'])
        if renderer_cache:
            if sha(base/'rows.json')!=self.complete['rows_sha256']:
                raise ValueError('Renderer row identity changed')
        elif sha(base/'complete.json')!=self.complete['source_complete_sha256'] or sha(base/'rows.json')!=self.complete['source_rows_sha256']:
            raise ValueError('Original cache identity changed')
        self.rows=json.loads((base/'rows.json').read_text())
        if self.complete.get('teacher_pass_count',1)!=expected_pass_count:raise ValueError('Cache teacher mode mismatch')
        if any(r.get('pass_count',1)!=expected_pass_count for r in self.rows):raise ValueError('Row teacher mode mismatch')
        self.rgb=np.load(base/'rgb.npy',mmap_mode='r')
        guide_root=base if use_legacy_guides else self.root
        self.guides=np.load(guide_root/'guides.npy',mmap_mode='r')
        self.context=np.load(guide_root/'context.npy',mmap_mode='r')
        for v in (self.rgb,self.guides,self.context):
            if len(v)!=len(self.rows): raise ValueError('Array/row mismatch')
        groups=defaultdict(list)
        for i,r in enumerate(self.rows):
            if r['split']==split: groups[r['sequence_id'],r['eye']].append(i)
        self.streams={}
        for key,ids in groups.items():
            ids.sort(key=lambda i:self.rows[i]['frame_id'])
            if [self.rows[i]['frame_id'] for i in ids]!=list(range(1,65)):
                raise ValueError('Expected exact contiguous 64-frame stream')
            if not self.rows[ids[0]]['history_reset'] or any(self.rows[i]['history_reset'] for i in ids[1:]):
                raise ValueError('Incorrect reset contract')
            self.streams[key]=np.asarray(ids,dtype=np.int64)
        if not self.streams: raise ValueError('Empty cohort split')

    @property
    def sequence_ids(self): return sorted({k[0] for k in self.streams})

    def load_window(self,indices):
        return (np.array(self.rgb[indices,0],copy=True),np.array(self.rgb[indices,1],copy=True),
                np.array(self.guides[indices],copy=True),np.array(self.context[indices],copy=True))

    def sample_window(self,rng,batch,window):
        if not 2<=window<=64: raise ValueError('Bad window')
        keys=list(self.streams)
        selected=[keys[int(rng.integers(len(keys)))] for _ in range(batch)]
        starts=[int(rng.integers(65-window)) for _ in range(batch)]
        ids=np.stack([self.streams[k][s:s+window] for k,s in zip(selected,starts)])
        return selected,starts,ids

    def stream_batches(self,batch):
        keys=list(self.streams)
        for start in range(0,len(keys),batch):
            selected=keys[start:start+batch]
            ids=np.stack([self.streams[k] for k in selected])
            yield selected,self.load_window(ids)
