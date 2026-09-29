"""Build a TensorRT engine from an explicit-Q/DQ semantic ONNX candidate."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from semantic_joint_runtime import sha256_file


def build_engine(
    onnx_path: Path,
    output: Path,
    engine_name: str,
    workspace_gib: float,
    fp16_io: bool,
    builder_optimization_level: int | None,
) -> Path:
    import tensorrt as trt

    output.mkdir(parents=True, exist_ok=True)
    engine_path = output / engine_name
    if engine_path.exists():
        return engine_path

    logger = trt.Logger(trt.Logger.WARNING)
    builder = trt.Builder(logger)
    network = builder.create_network(1 << int(trt.NetworkDefinitionCreationFlag.EXPLICIT_BATCH))
    parser = trt.OnnxParser(network, logger)
    if not parser.parse(onnx_path.read_bytes()):
        errors = "\n".join(str(parser.get_error(index)) for index in range(parser.num_errors))
        raise RuntimeError("TensorRT ONNX parse failed:\n" + errors)

    if fp16_io:
        for index in range(network.num_inputs):
            network.get_input(index).dtype = trt.float16
        for index in range(network.num_outputs):
            network.get_output(index).dtype = trt.float16

    config = builder.create_builder_config()
    config.set_memory_pool_limit(trt.MemoryPoolType.WORKSPACE, int(workspace_gib * 2**30))
    config.set_flag(trt.BuilderFlag.FP16)
    config.set_flag(trt.BuilderFlag.PREFER_PRECISION_CONSTRAINTS)
    if builder_optimization_level is not None:
        if not 0 <= builder_optimization_level <= 5:
            raise ValueError("builder optimization level must be between 0 and 5")
        config.builder_optimization_level = builder_optimization_level
    for index in range(network.num_layers):
        layer = network.get_layer(index)
        if layer.type == trt.LayerType.REDUCE:
            layer.precision = trt.float32
    if hasattr(trt, "ProfilingVerbosity"):
        config.profiling_verbosity = trt.ProfilingVerbosity.DETAILED

    started = time.time()
    blob = builder.build_serialized_network(network, config)
    if blob is None:
        raise RuntimeError("TensorRT quantized engine build failed")
    engine_path.write_bytes(bytes(blob))

    runtime = trt.Runtime(logger)
    engine = runtime.deserialize_cuda_engine(engine_path.read_bytes())
    if engine is None:
        raise RuntimeError("TensorRT built an unserializable quantized engine")
    inspector = engine.create_engine_inspector()
    (output / "engine_layers.json").write_text(
        inspector.get_engine_information(trt.LayerInformationFormat.JSON), encoding="utf-8"
    )
    manifest = {
        "format": "opennr-semantic-joint-quantized-tensorrt-v1",
        "onnx": str(onnx_path.resolve()),
        "onnx_sha256": sha256_file(onnx_path),
        "engine": str(engine_path.resolve()),
        "engine_sha256": sha256_file(engine_path),
        "engine_bytes": engine_path.stat().st_size,
        "tensorrt": trt.__version__,
        "precision": "explicit FP8 Q/DQ with FP16 high-precision fallback and FP16 I/O" if fp16_io else "explicit FP8 Q/DQ with FP16 high-precision fallback and FP32 I/O",
        "builder_optimization_level": builder_optimization_level,
        "tensor_names": [engine.get_tensor_name(i) for i in range(engine.num_io_tensors)],
        "build_seconds": time.time() - started,
        "status": "candidate_only",
    }
    (output / "engine_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, indent=2), flush=True)
    return engine_path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--onnx", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--engine-name", default="semantic_joint_fp8_fp16_io.engine")
    parser.add_argument("--workspace-gib", type=float, default=4.0)
    parser.add_argument("--builder-optimization-level", type=int, default=5)
    parser.add_argument("--fp16-io", action="store_true")
    args = parser.parse_args()
    build_engine(
        args.onnx.resolve(),
        args.output.resolve(),
        args.engine_name,
        args.workspace_gib,
        args.fp16_io,
        args.builder_optimization_level,
    )


if __name__ == "__main__":
    main()
