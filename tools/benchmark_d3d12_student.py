"""Actual shared D3D12 textures -> CUDA preparation -> TRT -> D3D12 textures."""
import argparse,ctypes as C,json,time
from pathlib import Path
import numpy as np
import torch
from native_preprocess import NativePreprocessor
from trt_inference import TensorRTStudent

def main():
    p=argparse.ArgumentParser();p.add_argument('--inputs',type=Path,required=True);p.add_argument('--engine',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--iterations',type=int,default=50);p.add_argument('--warmup',type=int,default=20);p.add_argument('--contended-smoke',action='store_true');a=p.parse_args();a.output.mkdir(parents=True,exist_ok=True);torch.set_num_threads(4)
    metadata=json.loads((a.inputs.parent/'provenance.json').read_text());rows=metadata['rows'];w,h=rows[0]['color_size'];gw,gh=rows[0]['guide_size'];prepare=NativePreprocessor(w,h,gw,gh);engine=TensorRTStudent(a.engine)
    dll=C.CDLL(str(Path('out/teacher_bench_build/opennr_texture_bridge.dll').resolve()))
    dll.OnrError.restype=C.c_char_p;dll.OnrCreate.argtypes=[C.c_wchar_p];dll.OnrCreate.restype=C.c_void_p;dll.OnrDestroy.argtypes=[C.c_void_p]
    for name in ('OnrBegin','OnrEnd'):getattr(dll,name).argtypes=[C.c_void_p,C.c_void_p]
    dll.OnrRead.argtypes=[C.c_void_p,C.c_int,C.c_uint64,C.c_uint64,C.c_uint64,C.c_void_p];dll.OnrWrite.argtypes=[C.c_void_p,C.c_int,C.c_uint64,C.c_void_p];dll.OnrSave.argtypes=[C.c_void_p,C.c_int,C.c_wchar_p]
    def check(value):
        if not value:raise RuntimeError(dll.OnrError().decode())
        return value
    handle=check(dll.OnrCreate(str(a.inputs.resolve())));color=torch.empty((h,w,4),device='cuda',dtype=torch.uint8);depth=torch.empty((gh,gw),device='cuda');motion=torch.empty((gh,gw,2),device='cuda',dtype=torch.float16);stream=torch.cuda.Stream();stream.wait_stream(torch.cuda.current_stream());expected=[];source_checks=[]
    def cycle(validation=False):
        start=time.perf_counter();begin=torch.cuda.Event(enable_timing=True);end=torch.cuda.Event(enable_timing=True);begin.record();check(dll.OnrBegin(handle,stream.cuda_stream))
        for eye,row in enumerate(rows):
            check(dll.OnrRead(handle,eye,color.data_ptr(),depth.data_ptr(),motion.data_ptr(),stream.cuda_stream))
            if validation:
                for stage,tensor in (('input',color),('depth',depth),('motion_vectors',motion)):
                    raw=Path(row['paths'][stage]);raw=raw.with_suffix('.raw.bin') if stage=='input' else raw
                    equal=np.array_equal(tensor.view(torch.uint8).cpu().numpy().reshape(-1),np.fromfile(raw,dtype='u1'));source_checks.append(dict(eye=eye,stage=stage,exact_bytes=equal));assert equal,(eye,stage)
            rgb,g,c=prepare(color,depth,motion,row['motion_scale']);pred=engine(rgb,g,c);rgba=prepare.pack(pred)
            if validation:expected.append(rgba.clone())
            check(dll.OnrWrite(handle,eye,rgba.data_ptr(),stream.cuda_stream))
        end.record();check(dll.OnrEnd(handle,stream.cuda_stream));return dict(wall_ms=(time.perf_counter()-start)*1000,cuda_ms=begin.elapsed_time(end))
    try:
        with torch.inference_mode(),torch.cuda.stream(stream):
            times=[]
            for i in range(a.warmup+a.iterations):
                measured=cycle()
                if i>=a.warmup:times.append(measured)
            cycle(True)
            for eye in (0,1):
                path=a.output/f'student_eye{eye}.rgba';check(dll.OnrSave(handle,eye,str(path.resolve())))
                actual=np.fromfile(path,dtype='u1').reshape(h,w,4);assert np.array_equal(actual,expected[eye].cpu().numpy()),'D3D12 output differs from CUDA packed pixels'
        result=dict(state='passed',resolution=[w,h],engine=str(a.engine),iterations=a.iterations,warmup=a.warmup,contended_smoke=a.contended_smoke,wall_median_ms=float(np.median([x['wall_ms'] for x in times])),wall_p95_ms=float(np.percentile([x['wall_ms'] for x in times],95)),cuda_median_ms=float(np.median([x['cuda_ms'] for x in times])),input_copy_checks=source_checks,output_exact_bytes=True,scope='Actual D3D12 shared resources and fences; includes GPU array/buffer copies, RGB/guide/context preparation, TensorRT, RGBA packing and return to graphics. Excludes disk upload and Skyrim renderer/compositor.')
        (a.output/'result.json').write_text(json.dumps(result,indent=2));(a.output/'timings.json').write_text(json.dumps(times));print(json.dumps(result),flush=True)
    finally:
        torch.cuda.synchronize();dll.OnrDestroy(handle)

if __name__=='__main__':main()
