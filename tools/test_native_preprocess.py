import json
from pathlib import Path
import numpy as np
import torch
from native_preprocess import NativePreprocessor
from evaluate_student import load_eye
from trt_inference import TensorRTStudent

torch.set_num_threads(4);cache=Path('C:/OpenNR/TrainingCache/student_v1');rows=json.loads((cache/'rows.json').read_text());contexts=np.load(cache/'context.npy',mmap_mode='r');i=next(i for i,r in enumerate(rows) if r['split']=='validation');r=rows[i];w,h=r['color_size'];gw,gh=r['guide_size']
color=torch.from_numpy(np.fromfile(Path(r['paths']['input']).with_suffix('.raw.bin'),dtype='u1').reshape(h,w,4)).cuda();depth=torch.from_numpy(np.fromfile(r['paths']['depth'],dtype='<f4').reshape(gh,gw)).cuda();motion=torch.from_numpy(np.fromfile(r['paths']['motion_vectors'],dtype='<f2').reshape(gh,gw,2)).cuda()
prepare=NativePreprocessor(w,h,gw,gh);rgb,g,c=prepare(color,depth,motion,r['motion_scale']);reference,_,rg,rc=load_eye(r,contexts[i]);torch.cuda.synchronize()
differences={name:dict(mean=(x-y).abs().mean().item(),maximum=(x-y).abs().max().item()) for name,x,y in [('rgb',rgb,reference),('guides',g,rg),('context',c,rc)]};print(json.dumps(differences),flush=True)
assert differences['rgb']['maximum']<1e-6
assert differences['guides']['maximum']<.001
assert differences['context']['maximum']<.005
engine=TensorRTStudent('out/student_v2_20260904/runtime_v2_fast/student_fp16.engine')
with torch.inference_mode():
    expected=engine(reference,rg,rc).clone();actual=engine(rgb,g,c).clone();error=(expected-actual).abs();packed=prepare.pack(actual);torch.cuda.synchronize()
    assert torch.isfinite(actual).all() and packed.dtype==torch.uint8 and bool((packed[:,:,3]==255).all())
    differences['engine_output']=dict(mean=error.mean().item(),maximum=error.max().item());assert error.mean()<.001 and error.max()<.05
out=Path('out/native_preprocess_20260905');out.mkdir(exist_ok=True);(out/'validation.json').write_text(json.dumps(differences,indent=2));print('PASS',json.dumps(differences))
