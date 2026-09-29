"""Actual left/right native-eye timing, separately from offline data preparation."""
import argparse,json,time
from pathlib import Path
import numpy as np
import torch
from evaluate_student import load_eye
from opennr_student import load_student

@torch.inference_mode()
def main():
    p=argparse.ArgumentParser();p.add_argument('--cache',type=Path,required=True);p.add_argument('--checkpoint',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--channels-last',action='store_true');p.add_argument('--split',choices=['validation','test'],default='test');a=p.parse_args()
    torch.set_num_threads(4);torch.backends.cudnn.benchmark=True
    rows=json.loads((a.cache/'rows.json').read_text());context=np.load(a.cache/'context.npy',mmap_mode='r');ids=[i for i,r in enumerate(rows) if r['split']==a.split][:2]
    start=time.perf_counter();model,_=load_student(a.checkpoint,'cuda');torch.cuda.synchronize();load_ms=(time.perf_counter()-start)*1000
    if a.channels_last:model=model.to(memory_format=torch.channels_last)
    start=time.perf_counter();eyes=[]
    for i in ids:
        x,y,g,c=load_eye(rows[i],context[i]);eyes.append(tuple(t.contiguous(memory_format=torch.channels_last) if a.channels_last else t for t in (x,g,c)));del y
    torch.cuda.synchronize();prep=(time.perf_counter()-start)*1000
    def measure(fn):
        vals=[]
        for _ in range(14):
            t0=torch.cuda.Event(enable_timing=True);t1=torch.cuda.Event(enable_timing=True);t0.record()
            with torch.autocast('cuda',dtype=torch.bfloat16):fn()
            t1.record();torch.cuda.synchronize();vals.append(t0.elapsed_time(t1))
        return dict(first_ms=vals[0],warm_median_ms=float(np.median(vals[4:])),warm_p95_ms=float(np.percentile(vals[4:],95)))
    def stereo():
        for eye in eyes:model(*eye)
    result=dict(gpu=torch.cuda.get_device_name(),torch=torch.__version__,channels_last=a.channels_last,resolution=rows[ids[0]]['color_size'],model_load_with_cuda_init_ms=load_ms,offline_stereo_read_prepare_upload_ms=prep,per_eye=measure(lambda:model(*eyes[0])),sequential_stereo=measure(stereo))
    batch=tuple(torch.cat((eyes[0][j],eyes[1][j]),0) for j in range(3))
    result['batched_stereo']=measure(lambda:model(*batch));result['peak_allocated_gib']=torch.cuda.max_memory_allocated()/2**30
    result['scope']='Model forward includes native RGB reconstruction; CUDA-resident inputs. Runtime interop, capture, transfers and compositor excluded. Offline loading is measured separately, not a proposed runtime path.'
    a.output.write_text(json.dumps(result,indent=2));print(json.dumps(result,indent=2))

if __name__=='__main__':main()
