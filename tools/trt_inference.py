"""Reusable GPU-resident fixed-shape TensorRT student inference.

Caller owns input CUDA tensors. The returned output is owned by this instance
and overwritten on the next call; clone or consume it before submitting again.
"""
import json,hashlib
from pathlib import Path
import torch

class TensorRTStudent:
    def __init__(self,engine_path):
        import tensorrt as trt
        self.trt=trt;self.logger=trt.Logger(trt.Logger.WARNING);self.runtime=trt.Runtime(self.logger)
        self.engine=self.runtime.deserialize_cuda_engine(Path(engine_path).read_bytes())
        if self.engine is None:raise RuntimeError('Cannot deserialize engine')
        self.context=self.engine.create_execution_context();self.stream=torch.cuda.Stream()
        shape=tuple(self.engine.get_tensor_shape('prediction'));self.output=torch.empty(shape,device='cuda',dtype=torch.float32)
        if any(self.engine.get_tensor_dtype(name)!=trt.float32 for name in ('rgb','guides','context','prediction')):raise ValueError('This wrapper requires FP32 engine I/O')
        self.context.set_tensor_address('prediction',self.output.data_ptr())
    def __call__(self,rgb,guides,context):
        current=torch.cuda.current_stream();self.stream.wait_stream(current)
        # Preserve any prior consumer of the reusable output on the caller stream.
        for name,value in (('rgb',rgb),('guides',guides),('context',context)):
            if not value.is_cuda or value.device!=self.output.device or value.dtype!=torch.float32 or not value.is_contiguous():raise ValueError(f'{name}: contiguous FP32 tensor on the engine CUDA device required')
            if tuple(value.shape)!=tuple(self.engine.get_tensor_shape(name)):raise ValueError(f'{name}: fixed engine shape mismatch')
            self.context.set_tensor_address(name,value.data_ptr());value.record_stream(self.stream)
        if not self.context.execute_async_v3(self.stream.cuda_stream):raise RuntimeError('TensorRT enqueue failed')
        current.wait_stream(self.stream);return self.output

def main():
    import argparse,numpy as np
    from evaluate_student import load_eye,pil
    p=argparse.ArgumentParser();p.add_argument('--engine',type=Path,required=True);p.add_argument('--cache',type=Path,required=True);p.add_argument('--row',type=int,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();torch.set_num_threads(4)
    rows=json.loads((a.cache/'rows.json').read_text());contexts=np.load(a.cache/'context.npy',mmap_mode='r');engine=TensorRTStudent(a.engine)
    with torch.inference_mode():
        rgb,_,g,c=load_eye(rows[a.row],contexts[a.row]);pred=engine(rgb,g,c);a.output.parent.mkdir(parents=True,exist_ok=True);pil(pred).save(a.output)
    print(json.dumps(dict(output=str(a.output.resolve()),engine=str(a.engine),row=a.row)))

if __name__=='__main__':main()
