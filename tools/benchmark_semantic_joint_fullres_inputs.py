"""Run a fixed-shape semantic engine on preserved full-resolution renderer inputs.

This is a read-only bridge benchmark.  It loads one complete OpenNR full-frame
capture per eye, recreates the native CUDA guide/context tensors, downsamples
RGB to the selected fixed model surface, and then measures the TensorRT engine.
It does not touch Skyrim, SteamVR, Community Shaders, or capture/training files.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import torch
from torch.nn import functional as F

from benchmark_semantic_joint_runtime import (
    TensorRTEyeSession,
    _measure_eye,
    _measure_stereo,
    _nvml_memory_report,
)
from native_preprocess import NativePreprocessor
from semantic_joint_runtime import sha256_file


def _frame_record(sequence: Path, frame: int) -> dict:
    frame_path = sequence / "frames.jsonl"
    for line in frame_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if int(row.get("frame_id", -1)) == frame:
            return row
    raise ValueError(f"frame {frame} was not found in {frame_path}")


def _artifact(record: dict, stage: str, eye: int) -> dict:
    for item in record.get("artifacts", []):
        if item.get("stage") == stage and item.get("eye") == eye and item.get("full_frame"):
            return item
    raise ValueError(f"full-frame {stage} artifact for eye {eye} was not found")


def _read_raw(sequence: Path, item: dict, dtype, shape: tuple[int, ...]) -> torch.Tensor:
    path = sequence / item["raw_path"]
    values = np.fromfile(path, dtype=dtype)
    expected = int(np.prod(shape))
    if values.size != expected:
        raise ValueError(f"{path} contains {values.size} values, expected {expected}")
    return torch.from_numpy(values.reshape(shape).copy()).cuda().contiguous()


def _load_eye(sequence: Path, record: dict, eye: int, preprocessor: NativePreprocessor, model_height: int, model_width: int):
    color_item = _artifact(record, "input", eye)
    depth_item = _artifact(record, "depth", eye)
    motion_item = _artifact(record, "motion_vectors", eye)
    color = _read_raw(
        sequence,
        color_item,
        np.uint8,
        (preprocessor.h, preprocessor.w, 4),
    )
    depth = _read_raw(
        sequence,
        depth_item,
        np.float32,
        (preprocessor.gh, preprocessor.gw),
    )
    motion = _read_raw(
        sequence,
        motion_item,
        np.float16,
        (preprocessor.gh, preprocessor.gw, 2),
    )
    scale_x = record.get("motion_vector_scale_x", [float(preprocessor.gw)] * 2)[eye]
    scale_y = record.get("motion_vector_scale_y", [float(preprocessor.gh)] * 2)[eye]
    prepare_start = torch.cuda.Event(enable_timing=True)
    prepare_end = torch.cuda.Event(enable_timing=True)
    prepare_start.record()
    rgb, guides, context = preprocessor(color, depth, motion, (scale_x, scale_y))
    # Renderer.cpp's reduced route downsamples the copied color texture before
    # model evaluation.  The current mode-0 shader is bilinear, so mirror that
    # fixed model-surface operation here while retaining native guide/context
    # extents.
    model_rgb = F.interpolate(
        rgb,
        size=(model_height, model_width),
        mode="bilinear",
        align_corners=False,
    ).contiguous()
    prepare_end.record()
    prepare_end.synchronize()
    return model_rgb.clone(), guides.clone(), context.clone(), {
        "eye": eye,
        "input": str((sequence / color_item["raw_path"]).resolve()),
        "depth": str((sequence / depth_item["raw_path"]).resolve()),
        "motion_vectors": str((sequence / motion_item["raw_path"]).resolve()),
        "source_color_shape": [preprocessor.h, preprocessor.w],
        "source_guide_shape": [preprocessor.gh, preprocessor.gw],
        "model_shape": [model_height, model_width],
        "motion_scale": [float(scale_x), float(scale_y)],
        "gpu_prepare_ms": float(prepare_start.elapsed_time(prepare_end)),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sequence", type=Path, required=True)
    parser.add_argument("--frame", type=int, default=1)
    parser.add_argument("--engine", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model-height", type=int, required=True)
    parser.add_argument("--model-width", type=int, required=True)
    parser.add_argument("--warmup", type=int, default=5)
    parser.add_argument("--iterations", type=int, default=40)
    args = parser.parse_args()
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is required")

    sequence = args.sequence.resolve()
    record = _frame_record(sequence, args.frame)
    preprocessor = NativePreprocessor(w=2496, h=2688, gw=1664, gh=1792)
    left, guides_left, context_left, left_metadata = _load_eye(
        sequence, record, 0, preprocessor, args.model_height, args.model_width
    )
    right, guides_right, context_right, right_metadata = _load_eye(
        sequence, record, 1, preprocessor, args.model_height, args.model_width
    )
    torch.cuda.synchronize()

    session_left = TensorRTEyeSession(args.engine.resolve())
    session_right = TensorRTEyeSession(args.engine.resolve())
    left = left.to(dtype=session_left.input_dtypes["rgb"]).contiguous()
    right = right.to(dtype=session_right.input_dtypes["rgb"]).contiguous()
    guides_left = guides_left.to(dtype=session_left.input_dtypes["guides"]).contiguous()
    guides_right = guides_right.to(dtype=session_right.input_dtypes["guides"]).contiguous()
    context_left = context_left.to(dtype=session_left.input_dtypes["context"]).contiguous()
    context_right = context_right.to(dtype=session_right.input_dtypes["context"]).contiguous()

    before = _nvml_memory_report()
    eye = _measure_eye(
        lambda state: session_left(left, guides_left, context_left),
        session_left.reset,
        args.warmup,
        args.iterations,
    )
    stereo = _measure_stereo(
        lambda state: session_left(left, guides_left, context_left),
        lambda state: session_right(right, guides_right, context_right),
        session_left.reset,
        session_right.reset,
        args.warmup,
        args.iterations,
    )
    result = {
        "state": "passed" if eye["last_output_finite"] and stereo["last_left_finite"] and stereo["last_right_finite"] else "failed",
        "runtime_kind": "tensorrt_fixed_engine_actual_capture_inputs",
        "engine": str(args.engine.resolve()),
        "engine_sha256": sha256_file(args.engine.resolve()),
        "gpu": torch.cuda.get_device_name(0),
        "torch": torch.__version__,
        "cuda": torch.version.cuda,
        "model_shape": {"height": args.model_height, "width": args.model_width},
        "capture": {"sequence": str(sequence), "frame": args.frame, "record": record},
        "eyes": [left_metadata, right_metadata],
        "gpu_prepare_ms": {
            "left": left_metadata["gpu_prepare_ms"],
            "right": right_metadata["gpu_prepare_ms"],
            "sequential_sum": left_metadata["gpu_prepare_ms"] + right_metadata["gpu_prepare_ms"],
        },
        "per_eye": eye,
        "sequential_stereo": stereo,
        "memory": {"before": before, "after": _nvml_memory_report()},
        "scope": "GPU-resident native preprocessing plus model-surface resize is prepared before timing; timing covers fixed TensorRT forward only and excludes D3D interop, compositor, game rendering, and headset acceptance",
    }
    args.output.resolve().parent.mkdir(parents=True, exist_ok=True)
    args.output.resolve().write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2), flush=True)


if __name__ == "__main__":
    main()
