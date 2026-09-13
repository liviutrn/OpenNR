"""Export FastStudent-v1 to a fixed-shape ONNX graph and optional TensorRT engine."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
import time

import torch
from torch import nn

from fast_student_v1 import load_fast_student


# torch.onnx's dynamo exporter emits a Unicode check mark on success.  The
# standard Windows PowerShell stream can still be cp1252, so make this
# standalone exporter safe to run directly from the user's normal shell.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class FastStudentOnnxWrapper(nn.Module):
    """Expose the recurrent state as explicit ONNX bindings."""

    def __init__(self, model: nn.Module):
        super().__init__()
        self.model = model

    def forward(
        self,
        rgb: torch.Tensor,
        guides: torch.Tensor,
        context: torch.Tensor,
        hidden: torch.Tensor,
        previous: torch.Tensor,
    ):
        prediction, (next_hidden, next_previous) = self.model.forward_temporal(
            rgb, guides, context, (hidden, previous)
        )
        # The Skyrim bridge requires distinct `prediction` and
        # `next_previous` TensorRT I/O bindings.  The PyTorch state naturally
        # aliases them, but TensorRT is allowed to collapse aliased outputs;
        # clone here so the named output contract survives engine building.
        return prediction, next_hidden, next_previous.clone()


def export_onnx(
    checkpoint: Path,
    output: Path,
    height: int,
    width: int,
    guide_height: int,
    guide_width: int,
    context_height: int,
    context_width: int,
    device: str,
) -> Path:
    output.mkdir(parents=True, exist_ok=True)
    onnx_path = output / "fast_student_v1_runtime.onnx"
    model, saved = load_fast_student(checkpoint, device)
    model.eval()
    wrapper = FastStudentOnnxWrapper(model).eval()
    hidden_shape = model.state_shapes(height, width)["hidden"]
    inputs = (
        torch.zeros(1, 3, height, width, device=device, dtype=torch.float32),
        torch.zeros(1, 5, guide_height, guide_width, device=device, dtype=torch.float32),
        torch.zeros(1, 8, context_height, context_width, device=device, dtype=torch.float32),
        torch.zeros(*hidden_shape, device=device, dtype=torch.float32),
        torch.zeros(1, 3, height, width, device=device, dtype=torch.float32),
    )
    started = time.time()
    with torch.inference_mode():
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
    manifest = {
        "format": "opennr-fast-student-v1-onnx-v1",
        "checkpoint": str(checkpoint.resolve()),
        "checkpoint_sha256": sha256_file(checkpoint),
        "architecture": saved["architecture"],
        "config": saved["config"],
        "onnx": str(onnx_path.resolve()),
        "onnx_sha256": sha256_file(onnx_path),
        "onnx_bytes": onnx_path.stat().st_size,
        "opset": 18,
        "export_seconds": time.time() - started,
        "shape": {
            "height": height,
            "width": width,
            "guide_height": guide_height,
            "guide_width": guide_width,
            "context_height": context_height,
            "context_width": context_width,
            "hidden": list(hidden_shape),
        },
        "inputs": ["rgb", "guides", "context", "hidden", "previous"],
        "outputs": ["prediction", "next_hidden", "next_previous"],
        "precision": "FP32 ONNX graph; TensorRT build requests FP16 tactics with optional FP16 I/O",
        "guide_note": "guide binding dimensions are explicit and may differ from the learned grid; the model resizes native Feature-18 channels internally",
    }
    (output / "onnx_manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(manifest, indent=2), flush=True)
    return onnx_path


def build_tensorrt(
    onnx_path: Path,
    output: Path,
    workspace_gib: float,
    fp16_io: bool,
    builder_optimization_level: int | None,
) -> Path:
    import tensorrt as trt

    engine_name = (
        "fast_student_v1_fp16_io.engine" if fp16_io else "fast_student_v1_fp16.engine"
    )
    engine_path = output / engine_name
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
    if hasattr(trt, "ProfilingVerbosity"):
        config.profiling_verbosity = trt.ProfilingVerbosity.DETAILED

    started = time.time()
    blob = builder.build_serialized_network(network, config)
    if blob is None:
        raise RuntimeError("TensorRT FP16 engine build failed")
    engine_path.write_bytes(bytes(blob))
    runtime = trt.Runtime(logger)
    engine = runtime.deserialize_cuda_engine(engine_path.read_bytes())
    if engine is None:
        raise RuntimeError("TensorRT built an unserializable engine")
    inspector = engine.create_engine_inspector()
    (output / "engine_layers.json").write_text(
        inspector.get_engine_information(trt.LayerInformationFormat.JSON), encoding="utf-8"
    )
    manifest = {
        "format": "opennr-fast-student-v1-tensorrt-v1",
        "onnx": str(onnx_path.resolve()),
        "onnx_sha256": sha256_file(onnx_path),
        "engine": str(engine_path.resolve()),
        "engine_sha256": sha256_file(engine_path),
        "engine_bytes": engine_path.stat().st_size,
        "build_seconds": time.time() - started,
        "tensorrt": trt.__version__,
        "precision": (
            "FP16 tactics with FP16 I/O"
            if fp16_io
            else "FP16 tactics with FP32 I/O"
        ),
        "builder_optimization_level": builder_optimization_level,
        "tensor_names": [engine.get_tensor_name(i) for i in range(engine.num_io_tensors)],
    }
    (output / "engine_manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(manifest, indent=2), flush=True)
    return engine_path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--height", type=int, default=512)
    parser.add_argument("--width", type=int, default=512)
    parser.add_argument("--guide-height", type=int)
    parser.add_argument("--guide-width", type=int)
    parser.add_argument("--context-height", type=int, default=96)
    parser.add_argument("--context-width", type=int, default=96)
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--workspace-gib", type=float, default=4.0)
    parser.add_argument("--builder-optimization-level", type=int)
    parser.add_argument("--fp16-io", action="store_true")
    parser.add_argument("--export-only", action="store_true")
    args = parser.parse_args()
    from opennr_paths import require_external_output
    args.output = require_external_output(args.output)
    guide_height = args.guide_height or (args.height + 3) // 4
    guide_width = args.guide_width or (args.width + 3) // 4
    dimensions = (
        args.height,
        args.width,
        guide_height,
        guide_width,
        args.context_height,
        args.context_width,
    )
    if min(dimensions) < 1:
        raise ValueError("all dimensions must be positive")
    if args.device.startswith("cuda") and not torch.cuda.is_available():
        raise RuntimeError("CUDA is unavailable; use --device cpu for ONNX-only export")
    onnx_path = export_onnx(
        args.checkpoint.resolve(),
        args.output.resolve(),
        args.height,
        args.width,
        guide_height,
        guide_width,
        args.context_height,
        args.context_width,
        args.device,
    )
    if not args.export_only:
        build_tensorrt(
            onnx_path,
            args.output.resolve(),
            args.workspace_gib,
            fp16_io=args.fp16_io,
            builder_optimization_level=args.builder_optimization_level,
        )


if __name__ == "__main__":
    main()
