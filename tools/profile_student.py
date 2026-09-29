"""Record operator costs for one native validation eye; no test-set tuning."""
import argparse,json
from pathlib import Path
import numpy as np
import torch
from opennr_student import load_student
from evaluate_student import load_eye

p=argparse.ArgumentParser();p.add_argument('--checkpoint',required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();a.output.mkdir(parents=True,exist_ok=True);torch.set_num_threads(4)
cache=Path('C:/OpenNR/TrainingCache/student_v1');rows=json.loads((cache/'rows.json').read_text());contexts=np.load(cache/'context.npy',mmap_mode='r');i=next(i for i,r in enumerate(rows) if r['split']=='validation');x,_,g,c=load_eye(rows[i],contexts[i]);m,_=load_student(a.checkpoint,'cuda')
with torch.inference_mode(),torch.autocast('cuda',dtype=torch.bfloat16):
    for _ in range(3):m(x,g,c)
    torch.cuda.synchronize()
    with torch.profiler.profile(activities=[torch.profiler.ProfilerActivity.CPU,torch.profiler.ProfilerActivity.CUDA],record_shapes=True) as prof:
        for _ in range(5):m(x,g,c)
        torch.cuda.synchronize()
(a.output/'operators.txt').write_text(prof.key_averages().table(sort_by='self_cuda_time_total',row_limit=35));prof.export_chrome_trace(str(a.output/'trace.json'));print((a.output/'operators.txt').read_text())
