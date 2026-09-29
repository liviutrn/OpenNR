"""Compare identical raw crop readers with alternating order; training can contend."""
import json
from pathlib import Path
import time
import numpy as np
import torch
from dynamic_patches import DynamicPatches

torch.set_num_threads(2)
datasets={mode:DynamicPatches('C:/OpenNR/TrainingCache/student_v1','C:/OpenNR/TrainingCache/dynamic_guides_v1',color_io=mode) for mode in ('mmap','strip')}
ids=np.random.default_rng(991).choice(len(datasets['mmap']),32,replace=False).tolist()
times={mode:[] for mode in datasets}
for n,index in enumerate(ids):
    samples={}
    for mode in (('mmap','strip') if n%2==0 else ('strip','mmap')):
        t=time.perf_counter();samples[mode]=datasets[mode][index];times[mode].append((time.perf_counter()-t)*1000)
    for key in ('rgb','target','guides','context'):assert torch.equal(samples['mmap'][key],samples['strip'][key]),(index,key)
result=dict(state='passed',exact_tensors=True,samples=32,indices=ids,median_ms={k:float(np.median(v)) for k,v in times.items()},mean_ms={k:float(np.mean(v)) for k,v in times.items()},scope='CPU sample loading, alternating reader order; filesystem cache and live training may influence performance. Same tensors verified.')
Path('out/quality_phase_20260905/dynamic_io_benchmark.json').write_text(json.dumps(result,indent=2));print(json.dumps(result))
