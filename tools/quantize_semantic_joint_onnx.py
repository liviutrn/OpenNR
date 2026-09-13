"""Create an isolated ModelOpt ONNX quantization candidate.

The default arm is FP8 Q/DQ on Conv and MatMul nodes with FP16 high-precision
fallback operations and unchanged FP32 network I/O. The resulting graph is a
candidate only; it must be built, numerically compared, and benchmarked before
any renderer work.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from modelopt.onnx.quantization import quantize

from semantic_joint_runtime import sha256_file


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--onnx", type=Path, required=True)
    parser.add_argument("--calibration", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--mode", choices=("fp8", "int8", "int4"), default="fp8")
    parser.add_argument("--log-file", type=Path)
    parser.add_argument(
        "--op-type",
        dest="op_types",
        action="append",
        default=["Conv", "MatMul"],
        help="repeat to select quantized ONNX operator types",
    )
    args = parser.parse_args()
    onnx_path = args.onnx.resolve()
    calibration_path = args.calibration.resolve()
    output_path = args.output.resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with np.load(calibration_path, allow_pickle=False) as data:
        calibration = {name: np.asarray(data[name], dtype=np.float32) for name in data.files}

    if not calibration:
        raise ValueError("calibration archive contains no tensors")
    sample_counts = {int(value.shape[0]) for value in calibration.values()}
    if len(sample_counts) != 1:
        raise ValueError(f"calibration tensors have mismatched sample counts: {sample_counts}")

    log_file = args.log_file.resolve() if args.log_file else output_path.with_suffix(".log")
    quantize(
        str(onnx_path),
        quantize_mode=args.mode,
        calibration_data=calibration,
        calibration_method="max",
        calibration_eps=["cuda:0", "trt", "cpu"],
        op_types_to_quantize=args.op_types,
        high_precision_dtype="fp16",
        mha_accumulation_dtype="fp16",
        output_path=str(output_path),
        log_file=str(log_file),
        log_level="INFO",
        keep_intermediate_files=True,
    )
    manifest = {
        "format": "opennr-semantic-joint-modelopt-quantized-onnx-v1",
        "mode": args.mode,
        "source_onnx": str(onnx_path),
        "source_onnx_sha256": sha256_file(onnx_path),
        "calibration": str(calibration_path),
        "calibration_sha256": sha256_file(calibration_path),
        "calibration_samples": next(iter(sample_counts)),
        "output": str(output_path),
        "output_sha256": sha256_file(output_path),
        "op_types_to_quantize": args.op_types,
        "high_precision_dtype": "fp16",
        "network_io_policy": "unchanged FP32 ONNX I/O; later TensorRT engine may bind FP16 I/O",
        "status": "candidate_only",
    }
    output_path.with_suffix(".json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, indent=2), flush=True)


if __name__ == "__main__":
    main()
