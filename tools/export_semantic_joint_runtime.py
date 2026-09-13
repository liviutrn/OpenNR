"""Export/build a fixed-shape FP16 TensorRT candidate from an inference bundle."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import torch

from semantic_joint_runtime import OnnxTemporalWrapper, load_bundle, sha256_file, state_shapes


def export_onnx(bundle_path: Path, output: Path, height: int, width: int, guide_height: int, guide_width: int, context_height: int, context_width: int) -> Path:
    output.mkdir(parents=True, exist_ok=True)
    onnx_path = output / "semantic_joint_runtime.onnx"
    if onnx_path.exists():
        return onnx_path
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is required for the fixed-shape export")
    model, bundle = load_bundle(bundle_path, "cuda")
    model.eval()
    wrapper = OnnxTemporalWrapper(model).eval()
    inputs = (
        torch.zeros(1, 3, height, width, device="cuda", dtype=torch.float32),
        torch.zeros(1, 5, guide_height, guide_width, device="cuda", dtype=torch.float32),
        torch.zeros(1, 8, context_height, context_width, device="cuda", dtype=torch.float32),
        torch.zeros(1, 64, (height + 7) // 8, (width + 7) // 8, device="cuda", dtype=torch.float32),
        torch.zeros(1, 3, height, width, device="cuda", dtype=torch.float32),
    )
    torch.cuda.synchronize()
    started = time.time()
    with torch.inference_mode():
        # The legacy tracer loses the fixed context-grid size through the
        # parent adaptive pool.  The torch.export path retains the static
        # shape and is the supported exporter in the pinned Torch 2.10 stack.
        torch.onnx.export(
            wrapper,
            inputs,
            str(onnx_path),
            input_names=["rgb", "guides", "context", "hidden", "previous"],
            output_names=["prediction", "next_hidden", "next_previous"],
            opset_version=18,
            dynamo=True,
            external_data=False,
        )
    import onnx

    graph = onnx.load(str(onnx_path), load_external_data=True)
    onnx.checker.check_model(graph)
    manifest_shapes = state_shapes(height, width)
    # OpenNR's reduced-resolution route keeps the native Feature-18 guide
    # tensors at the renderer's guide extent while the RGB/model surface is
    # downscaled.  Record the actual fixed engine input rather than assuming
    # guides are always exactly one quarter of the model surface.
    manifest_shapes["guides"] = (1, 5, guide_height, guide_width)
    manifest = {
        "format": "opennr-semantic-joint-onnx-v1",
        "bundle": str(bundle_path.resolve()),
        "bundle_sha256": sha256_file(bundle_path),
        "onnx": str(onnx_path.resolve()),
        "onnx_sha256": sha256_file(onnx_path),
        "onnx_bytes": onnx_path.stat().st_size,
        "opset": 18,
        "export_seconds": time.time() - started,
        "source_step": bundle["source_step"],
        "shape": {
            "height": height,
            "width": width,
            "guide_height": guide_height,
            "guide_width": guide_width,
            "context_height": context_height,
            "context_width": context_width,
            "state_shapes": {name: list(shape) for name, shape in manifest_shapes.items()},
        },
        "inputs": ["rgb", "guides", "context", "hidden", "previous"],
        "outputs": ["prediction", "next_hidden", "next_previous"],
        "precision": "FP32 ONNX graph; TensorRT build requests FP16 tactics with FP32 I/O",
    }
    (output / "onnx_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, indent=2), flush=True)
    return onnx_path


def build_engine(
    onnx_path: Path,
    output: Path,
    workspace_gib: float,
    fp16_io: bool = False,
    builder_optimization_level: int | None = None,
) -> Path:
    import tensorrt as trt

    engine_name = "semantic_joint_fp16_io.engine" if fp16_io else "semantic_joint_fp16.engine"
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
        # The ONNX graph remains FP32 for the reference/export contract.  The
        # TensorRT engine can bind FP16 directly and avoid the per-binding
        # reformat/cast nodes that otherwise surround the FP16 tactics.
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
        raise RuntimeError("TensorRT FP16 engine build failed")
    engine_path.write_bytes(bytes(blob))
    print(json.dumps({"engine": str(engine_path), "bytes": engine_path.stat().st_size, "build_seconds": time.time() - started}), flush=True)
    runtime = trt.Runtime(logger)
    engine = runtime.deserialize_cuda_engine(engine_path.read_bytes())
    if engine is None:
        raise RuntimeError("TensorRT built an unserializable engine")
    inspector = engine.create_engine_inspector()
    (output / "engine_layers.json").write_text(
        inspector.get_engine_information(trt.LayerInformationFormat.JSON), encoding="utf-8"
    )
    (output / "engine_manifest.json").write_text(
        json.dumps(
            {
                "format": "opennr-semantic-joint-tensorrt-v1",
                "onnx": str(onnx_path.resolve()),
                "onnx_sha256": sha256_file(onnx_path),
                "engine": str(engine_path.resolve()),
                "engine_sha256": sha256_file(engine_path),
                "engine_bytes": engine_path.stat().st_size,
                "tensorrt": trt.__version__,
                "precision": (
                    "FP16 tactics with FP16 I/O and FP32 reduction preference"
                    if fp16_io
                    else "FP16 tactics with FP32 I/O and FP32 reduction preference"
                ),
                "builder_optimization_level": builder_optimization_level,
                "tensor_names": [engine.get_tensor_name(i) for i in range(engine.num_io_tensors)],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return engine_path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--height", type=int, default=512)
    parser.add_argument("--width", type=int, default=512)
    parser.add_argument("--guide-height", type=int)
    parser.add_argument("--guide-width", type=int)
    parser.add_argument("--context-height", type=int, default=96)
    parser.add_argument("--context-width", type=int, default=96)
    parser.add_argument("--workspace-gib", type=float, default=4.0)
    parser.add_argument("--builder-optimization-level", type=int)
    parser.add_argument("--fp16-io", action="store_true")
    parser.add_argument("--export-only", action="store_true")
    args = parser.parse_args()
    guide_height = args.guide_height or (args.height + 3) // 4
    guide_width = args.guide_width or (args.width + 3) // 4
    if min(args.height, args.width, guide_height, guide_width, args.context_height, args.context_width) < 1:
        raise ValueError("All dimensions must be positive")
    onnx_path = export_onnx(
        args.bundle.resolve(),
        args.output.resolve(),
        args.height,
        args.width,
        guide_height,
        guide_width,
        args.context_height,
        args.context_width,
    )
    if not args.export_only:
        print(
            json.dumps(
                {
                    "engine": str(
                        build_engine(
                            onnx_path,
                            args.output.resolve(),
                            args.workspace_gib,
                            fp16_io=args.fp16_io,
                            builder_optimization_level=args.builder_optimization_level,
                        )
                    )
                },
                indent=2,
            ),
            flush=True,
        )


if __name__ == "__main__":
    main()
