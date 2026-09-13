"""Fixed native-eye ONNX/TensorRT FP16 prototype, numerical check and GPU timings.

Uses torch CUDA allocations and stream directly. No CPU image round-trip during
engine execution. NVFP4 is deliberately not claimed by this FP16 prototype.
"""
import argparse,json,time,hashlib
from pathlib import Path
import numpy as np
import torch
from opennr_student import load_student
from evaluate_student import load_eye

def main():
    p=argparse.ArgumentParser();p.add_argument('--checkpoint',type=Path,required=True);p.add_argument('--cache',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--export-only',action='store_true');a=p.parse_args();a.output.mkdir(parents=True,exist_ok=True);torch.set_num_threads(4)
    import tensorrt as trt
    model,_=load_student(a.checkpoint,'cpu');rows=json.loads((a.cache/'rows.json').read_text());idx=next(i for i,r in enumerate(rows) if r['split']=='validation');w,h=rows[idx]['color_size']
    onnx=a.output/'student.onnx'
    identity=hashlib.sha256(a.checkpoint.read_bytes()).hexdigest();meta=a.output/'source.json'
    if meta.exists() and json.loads(meta.read_text())['checkpoint_sha256']!=identity:raise ValueError('Checkpoint changed; use a fresh engine output directory')
    meta.write_text(json.dumps(dict(checkpoint=str(a.checkpoint),checkpoint_sha256=identity,resolution=[w,h]),indent=2))
    if not onnx.exists():
        torch.onnx.export(model,(torch.zeros(1,3,h,w),torch.zeros(1,5,h//4,w//4),torch.zeros(1,8,96,96)),str(onnx),input_names=['rgb','guides','context'],output_names=['prediction'],opset_version=17,dynamo=False)
    import onnx as ox
    ox.checker.check_model(str(onnx));print('ONNX validated',flush=True)
    if a.export_only:return
    logger=trt.Logger(trt.Logger.WARNING);engine_path=a.output/'student_fp16.engine'
    if not engine_path.exists():
        builder=trt.Builder(logger);network=builder.create_network(1<<int(trt.NetworkDefinitionCreationFlag.EXPLICIT_BATCH));parser=trt.OnnxParser(network,logger)
        if not parser.parse(onnx.read_bytes()):raise RuntimeError('\n'.join(str(parser.get_error(i)) for i in range(parser.num_errors)))
        config=builder.create_builder_config();config.set_memory_pool_limit(trt.MemoryPoolType.WORKSPACE,2*2**30);config.set_flag(trt.BuilderFlag.FP16)
        config.profiling_verbosity=trt.ProfilingVerbosity.DETAILED
        # Avoid half-precision variance overflow; allow TRT to fuse safe downstream ops.
        config.set_flag(trt.BuilderFlag.PREFER_PRECISION_CONSTRAINTS)
        for i in range(network.num_layers):
            layer=network.get_layer(i)
            if layer.type==trt.LayerType.REDUCE:layer.precision=trt.float32
        start=time.time();blob=builder.build_serialized_network(network,config)
        if blob is None:raise RuntimeError('TensorRT engine build failed')
        engine_path.write_bytes(bytes(blob));print(f'Engine built in {time.time()-start:.1f}s',flush=True)
    runtime=trt.Runtime(logger);engine=runtime.deserialize_cuda_engine(engine_path.read_bytes());ctx=engine.create_execution_context()
    (a.output/'engine_layers.json').write_text(engine.create_engine_inspector().get_engine_information(trt.LayerInformationFormat.JSON))
    contexts=np.load(a.cache/'context.npy',mmap_mode='r');x,t,g,c=load_eye(rows[idx],contexts[idx]);model=model.cuda().eval()
    tensors={'rgb':x,'guides':g,'context':c,'prediction':torch.empty_like(x)}
    for name,tensor in tensors.items():
        if engine.get_tensor_dtype(name)!=trt.float32:raise RuntimeError(f'Unexpected I/O type for {name}')
        ctx.set_tensor_address(name,tensor.data_ptr())
    stream=torch.cuda.Stream();stream.wait_stream(torch.cuda.current_stream())
    def execute():
        if not ctx.execute_async_v3(stream.cuda_stream):raise RuntimeError('Engine execution failed')
    with torch.cuda.stream(stream),torch.inference_mode():
        # FP32 reference isolates engine conversion error from bf16 rounding.
        ref=model(x,g,c)
        execute();torch.cuda.synchronize();out=tensors['prediction'];delta=(out-ref).abs();finite=bool(torch.isfinite(out).all())
        if not finite:raise RuntimeError('Nonfinite engine output')
        correctness=dict(mean_absolute_difference=delta.mean().item(),max_absolute_difference=delta.max().item(),engine_teacher_mae=(out-t).abs().mean().item(),pytorch_teacher_mae=(ref-t).abs().mean().item(),reference='PyTorch FP32',tolerance_mean=.001,tolerance_max=.05,passed=delta.mean().item()<=.001 and delta.max().item()<=.05)
        # Warm the engine after reference inference and let clocks settle.
        for _ in range(50):execute()
        torch.cuda.synchronize();times=[]
        for _ in range(24):
            t0=torch.cuda.Event(enable_timing=True);t1=torch.cuda.Event(enable_timing=True);t0.record();execute();t1.record();torch.cuda.synchronize();times.append(t0.elapsed_time(t1))
        right=rows[idx+1]
        assert right['sequence_id']==rows[idx]['sequence_id'] and right['frame_id']==rows[idx]['frame_id'] and right['eye']!=rows[idx]['eye']
        rx,rt,rg,rc=load_eye(right,contexts[idx+1]);right_inputs={'rgb':rx,'guides':rg,'context':rc}
        for name,tensor in right_inputs.items():ctx.set_tensor_address(name,tensor.data_ptr())
        rref=model(rx,rg,rc);execute();torch.cuda.synchronize();rd=(tensors['prediction']-rref).abs()
        right_check=dict(mean_absolute_difference=rd.mean().item(),max_absolute_difference=rd.max().item(),passed=bool(torch.isfinite(rd).all()) and rd.mean().item()<=.001 and rd.max().item()<=.05)
        for _ in range(50):execute()
        torch.cuda.synchronize();pairs=[]
        for _ in range(14):
            t0=torch.cuda.Event(enable_timing=True);t1=torch.cuda.Event(enable_timing=True);t0.record()
            for inputs in (tensors,right_inputs):
                for name in ('rgb','guides','context'):ctx.set_tensor_address(name,inputs[name].data_ptr())
                execute()
            t1.record();torch.cuda.synchronize();pairs.append(t0.elapsed_time(t1))
    result=dict(tensorrt=trt.__version__,checkpoint=str(a.checkpoint),engine=str(engine_path),precision='FP16 tactics with FP32 reduce preference, FP32 I/O; not NVFP4',resolution=[w,h],warm_eye_median_ms=float(np.median(times[4:])),warm_eye_p95_ms=float(np.percentile(times[4:],95)),sequential_stereo_estimate_ms=float(2*np.median(times[4:])),numerical_check=correctness,scope='One validation eye, GPU-resident engine only; stereo estimate not actual engine integration or quality acceptance')
    result.update(actual_sequential_stereo_median_ms=float(np.median(pairs[4:])),actual_sequential_stereo_p95_ms=float(np.percentile(pairs[4:],95)),right_eye_numerical_check=right_check)
    result['scope']='One actual validation left/right pair; GPU-resident engine with input rebinding. Excludes capture, guide preparation, engine interop and compositor.'
    (a.output/'runtime_result.json').write_text(json.dumps(result,indent=2));print(json.dumps(result),flush=True)
    if not correctness['passed'] or not right_check['passed']:
        raise RuntimeError('TensorRT conversion failed left/right numerical tolerances; engine is not accepted')

if __name__=='__main__':main()
