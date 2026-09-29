"""Build and numerically check a TensorRT engine from an explicit-QDQ ONNX graph."""
import argparse
import hashlib
import json
import time
from pathlib import Path

import numpy as np
import torch
from evaluate_student import load_eye
from opennr_student import load_student


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--onnx', type=Path, required=True)
    p.add_argument('--checkpoint', type=Path, required=True, help='FP32/FP16 PyTorch source used for numerical reference')
    p.add_argument('--cache', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--workspace-gib', type=float, default=2.0)
    a = p.parse_args()
    a.onnx = a.onnx.resolve(); a.checkpoint = a.checkpoint.resolve(); a.cache = a.cache.resolve(); a.output = a.output.resolve()
    a.output.mkdir(parents=True, exist_ok=True)
    import onnx
    import tensorrt as trt

    graph = onnx.load(str(a.onnx), load_external_data=True)
    onnx.checker.check_model(graph)
    source_hash = hashlib.sha256(a.onnx.read_bytes()).hexdigest()
    model_hash = hashlib.sha256(a.checkpoint.read_bytes()).hexdigest()
    engine_path = a.output / 'student_fp8.engine'
    logger = trt.Logger(trt.Logger.WARNING)
    if not engine_path.exists():
        builder = trt.Builder(logger)
        network = builder.create_network(1 << int(trt.NetworkDefinitionCreationFlag.EXPLICIT_BATCH))
        parser = trt.OnnxParser(network, logger)
        if not parser.parse(a.onnx.read_bytes()):
            raise RuntimeError('\n'.join(str(parser.get_error(i)) for i in range(parser.num_errors)))
        config = builder.create_builder_config()
        config.set_memory_pool_limit(trt.MemoryPoolType.WORKSPACE, int(a.workspace_gib * 2**30))
        # ModelOpt keeps non-quantized graph regions in FP16; the explicit
        # FP8 Q/DQ nodes still control quantized tensors.
        config.set_flag(trt.BuilderFlag.FP16)
        start = time.time()
        blob = builder.build_serialized_network(network, config)
        if blob is None:
            raise RuntimeError('TensorRT explicit-FP8 engine build failed')
        engine_path.write_bytes(bytes(blob))
        print(f'Engine built in {time.time()-start:.1f}s', flush=True)

    runtime = trt.Runtime(logger)
    engine = runtime.deserialize_cuda_engine(engine_path.read_bytes())
    if engine is None:
        raise RuntimeError('Cannot deserialize explicit-FP8 engine')
    ctx = engine.create_execution_context()
    (a.output / 'engine_layers.json').write_text(engine.create_engine_inspector().get_engine_information(trt.LayerInformationFormat.JSON))
    rows = json.loads((a.cache / 'rows.json').read_text())
    contexts = np.load(a.cache / 'context.npy', mmap_mode='r')
    idx = next(i for i, row in enumerate(rows) if row['split'] == 'validation')
    x, target, guides, context = load_eye(rows[idx], contexts[idx])
    model, ckpt = load_student(a.checkpoint, 'cuda')
    model.eval()
    out = torch.empty_like(x)
    for name, tensor in (('rgb', x), ('guides', guides), ('context', context), ('prediction', out)):
        if engine.get_tensor_dtype(name) != trt.float32:
            raise RuntimeError(f'Expected FP32 I/O for {name}, got {engine.get_tensor_dtype(name)}')
        ctx.set_tensor_address(name, tensor.data_ptr())
    stream = torch.cuda.Stream(); stream.wait_stream(torch.cuda.current_stream())

    def execute():
        if not ctx.execute_async_v3(stream.cuda_stream):
            raise RuntimeError('Engine execution failed')

    with torch.cuda.stream(stream), torch.inference_mode():
        ref = model(x, guides, context)
        execute(); torch.cuda.synchronize()
        delta = (out - ref).abs()
        left = dict(mean_absolute_difference=delta.mean().item(), max_absolute_difference=delta.max().item(), passed=bool(torch.isfinite(out).all()) and delta.mean().item() <= .002 and delta.max().item() <= .1)
        for _ in range(50): execute()
        torch.cuda.synchronize(); times = []
        for _ in range(24):
            t0 = torch.cuda.Event(enable_timing=True); t1 = torch.cuda.Event(enable_timing=True); t0.record(); execute(); t1.record(); torch.cuda.synchronize(); times.append(t0.elapsed_time(t1))
        right = rows[idx + 1]
        if right['sequence_id'] != rows[idx]['sequence_id'] or right['frame_id'] != rows[idx]['frame_id'] or right['eye'] == rows[idx]['eye']:
            raise ValueError('Validation rows are not a stereo pair')
        rx, rt, rg, rc = load_eye(right, contexts[idx + 1])
        for name, tensor in (('rgb', rx), ('guides', rg), ('context', rc)):
            ctx.set_tensor_address(name, tensor.data_ptr())
        rref = model(rx, rg, rc); execute(); torch.cuda.synchronize(); rdelta = (out - rref).abs()
        right_check = dict(mean_absolute_difference=rdelta.mean().item(), max_absolute_difference=rdelta.max().item(), passed=bool(torch.isfinite(rdelta).all()) and rdelta.mean().item() <= .002 and rdelta.max().item() <= .1)
        for _ in range(50): execute()
        torch.cuda.synchronize(); pairs = []
        for _ in range(14):
            t0 = torch.cuda.Event(enable_timing=True); t1 = torch.cuda.Event(enable_timing=True); t0.record()
            for inputs in ((x, guides, context), (rx, rg, rc)):
                for name, tensor in zip(('rgb', 'guides', 'context'), inputs): ctx.set_tensor_address(name, tensor.data_ptr())
                execute()
            t1.record(); torch.cuda.synchronize(); pairs.append(t0.elapsed_time(t1))
    result = dict(
        state='passed' if left['passed'] and right_check['passed'] else 'failed',
        tensorrt=trt.__version__, precision='Explicit FP8 Q/DQ activations/weights with FP16 high-precision remainder, FP32 I/O',
        onnx=str(a.onnx), onnx_sha256=source_hash, checkpoint=str(a.checkpoint), checkpoint_sha256=model_hash,
        engine=str(engine_path), resolution=rows[idx]['color_size'],
        warm_eye_median_ms=float(np.median(times[4:])), warm_eye_p95_ms=float(np.percentile(times[4:], 95)),
        sequential_stereo_estimate_ms=float(2*np.median(times[4:])), actual_sequential_stereo_median_ms=float(np.median(pairs[4:])), actual_sequential_stereo_p95_ms=float(np.percentile(pairs[4:], 95)),
        numerical_check=left, right_eye_numerical_check=right_check,
        scope='One validation stereo pair; GPU-resident explicit-FP8 TensorRT engine. Excludes capture, guide preparation, interop and compositor.',
    )
    (a.output / 'runtime_result.json').write_text(json.dumps(result, indent=2)); print(json.dumps(result, indent=2), flush=True)
    if result['state'] != 'passed':
        raise RuntimeError('Explicit-FP8 TensorRT numerical parity failed')


if __name__ == '__main__':
    main()
