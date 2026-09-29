"""Validate reusable output-buffer stream ordering on a real validation stereo pair."""
import json
from pathlib import Path
import numpy as np
import torch
from trt_inference import TensorRTStudent
from opennr_student import load_student
from evaluate_student import load_eye

torch.set_num_threads(4);base=Path('out/student_v2_20260904');cache=Path('C:/OpenNR/TrainingCache/student_v1');rows=json.loads((cache/'rows.json').read_text());contexts=np.load(cache/'context.npy',mmap_mode='r');i=next(i for i,r in enumerate(rows) if r['split']=='validation')
engine=TensorRTStudent(base/'runtime_v2_fast/student_fp16.engine');model,_=load_student(base/'fast/best.pt','cuda');eyes=[]
with torch.inference_mode():
    for index in (i,i+1):
        x,_,g,c=load_eye(rows[index],contexts[index]);eyes.append((x,g,c))
    left=engine(*eyes[0]).clone();right=engine(*eyes[1]).clone()
    errors=[]
    for inputs,output in zip(eyes,(left,right)):
        ref=model(*inputs);delta=(ref-output).abs();assert torch.isfinite(output).all();assert delta.mean()<.001 and delta.max()<.05;errors.append(delta.mean().item())
    try:engine(eyes[0][0][:,:,:128,:128],eyes[0][1],eyes[0][2])
    except ValueError:pass
    else:raise AssertionError('Engine accepted wrong shape')
report=dict(state='passed',left_right_mean_errors=errors,reusable_buffer_clone_order=True,wrong_shape_rejected=True)
(base/'runtime_wrapper_test.json').write_text(json.dumps(report,indent=2));print(json.dumps(report))
