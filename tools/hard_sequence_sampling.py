"""Training-only sequence replacement preserving baseline eyes and window starts."""
import json
import numpy as np
from prepare_conditioning_pilot import sha
from pathlib import Path


def load_hard_sets(path,checkpoint_sha,train):
    manifest=json.loads(Path(path).read_text())
    if manifest['schema']!='opennr-hard-training-sequences-v1' or manifest['test_used']:
        raise ValueError('Invalid mining manifest')
    if manifest['checkpoint_sha256']!=checkpoint_sha or sha(Path(manifest['fit_report']))!=manifest['fit_report_sha256']:
        raise ValueError('Mining provenance mismatch')
    result=[]
    for label,cache in zip(('prior','high_effect','renderer_pilot'),train):
        entry=manifest['cohorts'][label]
        ranked=[r['sequence_id'] for r in entry['ranked_training_mae']]
        hard=entry['hard_sequence_ids']
        if cache.split!='train' or set(ranked)!=set(cache.sequence_ids) or len(ranked)!=len(set(ranked)):
            raise ValueError('Mining membership mismatch')
        if not hard or len(hard)!=len(set(hard)) or not set(hard)<=set(ranked):raise ValueError('Invalid hard set')
        if sha(cache.root/'complete.json')!=entry['overlay_complete_sha256']:raise ValueError('Mining overlay changed')
        if any((seq,eye) not in cache.streams for seq in hard for eye in (0,1)):raise ValueError('Hard set missing eye')
        result.append(hard)
    return result


def replace_sequences(cache,selected,starts,ids,hard,rng,probability=.5):
    replaced=ids.copy();count=0
    for index,((seq,eye),start) in enumerate(zip(selected,starts)):
        if rng.random()<probability:
            seq=hard[int(rng.integers(len(hard)))]
            replaced[index]=cache.streams[seq,eye][start:start+ids.shape[1]]
            count+=1
    return replaced,count
