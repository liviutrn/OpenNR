#!/usr/bin/env python3
"""Export a fixed-shape white-box graph control for TensorRT probing."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
import time

import torch


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--weights", type=Path, required=True)
    parser.add_argument("--mlx-python", type=Path, required=True)
    parser.add_argument("--height", type=int, required=True)
    parser.add_argument("--width", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--mode", choices=("fp16_graph", "direct_fp8"), default="fp16_graph")
    args = parser.parse_args()

    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is required")
    if args.height <= 0 or args.width <= 0 or args.height % 64 or args.width % 64:
        raise ValueError("height and width must be positive multiples of 64")
    mlx_python = args.mlx_python.expanduser().resolve()
    if str(mlx_python) not in sys.path:
        sys.path.insert(0, str(mlx_python))

    from mlxdlss import NeuralRenderingPipeline
    from mlxdlss import model as recovered_model
    from mlxdlss.pipeline import load_weights

    original_round_trip = recovered_model.e4m3_round_trip
    if args.mode == "fp16_graph":
        # TensorRT control: keep the graph FP16 while removing the Python/bitwise
        # implementation of the E4M3 publication boundaries. This is a backend
        # ceiling probe, not a claim of numerical parity.
        recovered_model.e4m3_round_trip = lambda value: value
    else:
        def direct_fp8(value):
            return value.clamp(-448.0, 448.0).to(torch.float8_e4m3fn).to(value.dtype)

        recovered_model.e4m3_round_trip = direct_fp8

    output_dir = args.output.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    onnx_path = output_dir / f"whitebox_{args.mode}_{args.height}x{args.width}.onnx"
    manifest_path = output_dir / "export_manifest.json"
    try:
        weights = load_weights(args.weights.expanduser().resolve())
        pipeline = NeuralRenderingPipeline(weights, device="cuda", precision="fast")
        model = pipeline.model.eval()
        dummy = torch.zeros((1, args.height, args.width, 16), device="cuda", dtype=torch.float16)
        started = time.perf_counter()
        with torch.no_grad():
            # Run once before export so tracing sees the actual static shape and
            # so an unsupported graph fails before a large exporter transaction.
            reference_output = model(dummy)
            torch.cuda.synchronize()
        warmup_seconds = time.perf_counter() - started
        started = time.perf_counter()
        with torch.no_grad():
            torch.onnx.export(
                model,
                (dummy,),
                str(onnx_path),
                input_names=["features"],
                output_names=["head"],
                opset_version=19,
                do_constant_folding=True,
                dynamo=False,
                verbose=False,
            )
        export_seconds = time.perf_counter() - started
        manifest = {
            "schema": "opennr-whitebox-onnx-export-v1",
            "mode": args.mode,
            "height": args.height,
            "width": args.width,
            "input_shape": list(dummy.shape),
            "output_shape": list(reference_output.shape),
            "onnx": str(onnx_path),
            "onnx_sha256": hashlib.sha256(onnx_path.read_bytes()).hexdigest(),
            "weights": str(args.weights.expanduser().resolve()),
            "weights_sha256": hashlib.sha256(args.weights.expanduser().resolve().read_bytes()).hexdigest(),
            "torch": torch.__version__,
            "cuda": torch.version.cuda,
            "gpu": torch.cuda.get_device_name(0),
            "warmup_model_seconds": warmup_seconds,
            "export_seconds": export_seconds,
            "peak_cuda_memory_allocated_bytes": int(torch.cuda.max_memory_allocated()),
            "numerical_warning": "fp16_graph removes E4M3 boundaries for a backend ceiling probe; direct_fp8 export may not be supported by ONNX/TensorRT. Neither mode is live-runtime evidence.",
        }
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    finally:
        recovered_model.e4m3_round_trip = original_round_trip

    print(json.dumps(manifest, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
