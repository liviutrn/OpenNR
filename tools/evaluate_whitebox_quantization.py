#!/usr/bin/env python3
"""Evaluate isolated precision and quantization candidates for the recovered graph.

This is an offline research evaluator.  It reads complete Skyrim eye captures
and the logical recovered DLSSNR weights, but never changes the source weights,
the packed vendor weights, the native DLL, a game profile, or a runtime.

The FP8 and INT8 branches in this first probe are *weight-quantization
feasibility controls*: weights are quantized on CPU and dequantized before the
reference graph consumes them.  They measure output drift and an FP16 compute
control, not a production INT8/FP8 kernel.  A true runtime speed claim requires
fused quantized matrix-multiply kernels or a supported deployment backend.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import sys
import time
from typing import Any, Callable

import numpy as np
from PIL import Image


FP8_DTYPE_NAME = "torch.float8_e4m3fn"
MODEL_MODES = (
    "reference",
    "fast_fp16",
    "weight_fp8_dequant_fp16",
    "weight_int8_dequant_fp16",
    "activation_fp8_fast",
    "compiled_fast_fp16",
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: Path, value: Any) -> None:
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def read_rgba_raw(path: Path, width: int, height: int) -> np.ndarray:
    raw = path.read_bytes()
    expected = width * height * 4
    if len(raw) != expected:
        raise ValueError(f"{path}: {len(raw)} bytes, expected {expected}")
    rgba = np.frombuffer(raw, dtype=np.uint8).reshape(height, width, 4)
    return np.ascontiguousarray(rgba[..., :3], dtype=np.float32) / 255.0


def save_rgb(path: Path, image: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    values = np.rint(np.clip(np.asarray(image), 0.0, 1.0) * 255.0).astype(np.uint8)
    Image.fromarray(values, mode="RGB").save(path)


def metrics(actual: np.ndarray, target: np.ndarray) -> dict[str, float]:
    error = np.asarray(actual, dtype=np.float64) - np.asarray(target, dtype=np.float64)
    absolute = np.abs(error)
    rmse = float(np.sqrt(np.mean(error * error)))
    return {
        "mae": float(absolute.mean()),
        "rmse": rmse,
        "psnr_db": float("inf") if rmse == 0.0 else float(20.0 * np.log10(1.0 / rmse)),
        "max_abs": float(absolute.max()),
        "p99_abs": float(np.percentile(absolute, 99.0)),
        "p999_abs": float(np.percentile(absolute, 99.9)),
    }


def select_rows(rows: list[dict[str, Any]], split: str, frames: set[int], max_rows: int) -> list[tuple[int, dict[str, Any]]]:
    selected = [
        (index, row)
        for index, row in enumerate(rows)
        if row.get("split") == split and int(row.get("frame_id", -1)) in frames
    ]
    selected.sort(key=lambda item: (str(item[1]["sequence_id"]), int(item[1]["frame_id"]), int(item[1]["eye"])))
    if max_rows > 0:
        selected = selected[:max_rows]
    if not selected:
        raise ValueError(f"no rows selected for split={split!r}, frames={sorted(frames)}")
    if any(int(row.get("eye", -1)) not in (0, 1) for _, row in selected):
        raise ValueError("selected rows contain an invalid eye")
    return selected


def is_matrix_weight(value: Any) -> bool:
    # The logical graph's learned projections are [input, output] matrices.
    # Biases, attention tables, cosine vectors, scales, and merge gates stay
    # higher precision in this conservative first probe.
    return getattr(value, "ndim", 0) == 2 and int(value.numel()) >= 64


def quantize_weights(weights: dict[str, Any], mode: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return dequantized tensors plus an auditable storage/error summary."""

    import torch

    if mode not in ("fp8", "int8"):
        raise ValueError(mode)
    quantized: dict[str, Any] = {}
    eligible = 0
    eligible_elements = 0
    original_bytes = 0
    estimated_bytes = 0
    total_abs_error = 0.0
    total_sq_error = 0.0
    total_error_elements = 0
    tensor_records: list[dict[str, Any]] = []

    with torch.no_grad():
        for name, source in weights.items():
            source_cpu = source.detach().to("cpu")
            original_bytes += int(source_cpu.numel() * source_cpu.element_size())
            if not is_matrix_weight(source_cpu):
                quantized[name] = source_cpu
                estimated_bytes += int(source_cpu.numel() * source_cpu.element_size())
                continue

            value = source_cpu.to(torch.float32)
            if mode == "fp8":
                # The recovered logical matrices are already decoded from the
                # vendor's E4M3-oriented representation.  A direct E4M3
                # round-trip is therefore the faithful first control.  A
                # scaled FP8 implementation can be tested later, but scaling
                # every matrix here would make already-representable weights
                # less accurate and would confound this first probe.
                encoded = value.clamp(-448.0, 448.0).to(torch.float8_e4m3fn)
                restored = encoded.to(torch.float32)
                storage_bytes = int(value.numel())
                scale_description = "direct E4M3, symmetric range [-448,448], no extra scale"
                saturated = int((value.abs() > 448.0).sum().item())
            else:
                # Per-output-channel symmetric scales for [input, output].
                scale = value.abs().amax(dim=0, keepdim=True).clamp_min(1e-12) / 127.0
                encoded = torch.round(value / scale).clamp(-127.0, 127.0).to(torch.int8)
                restored = encoded.to(torch.float32) * scale
                storage_bytes = int(encoded.numel() + scale.numel() * 4)
                scale_description = "per-output-channel symmetric INT8 with float32 scales"
                saturated = int((torch.abs(torch.round(value / scale)) > 127.0).sum().item())

            difference = (restored - value).abs()
            total_abs_error += float(difference.sum().item())
            total_sq_error += float(difference.square().sum().item())
            total_error_elements += int(difference.numel())
            eligible += 1
            eligible_elements += int(value.numel())
            estimated_bytes += storage_bytes
            quantized[name] = restored
            tensor_records.append(
                {
                    "name": name,
                    "shape": list(value.shape),
                    "elements": int(value.numel()),
                    "source_dtype": str(source.dtype),
                    "quantized_dtype": "float8_e4m3fn" if mode == "fp8" else "int8",
                    "estimated_storage_bytes": storage_bytes,
                    "mean_abs_weight_error": float(difference.mean().item()),
                    "max_abs_weight_error": float(difference.max().item()),
                    "saturated_or_clipped_values": saturated,
                    "scale": scale_description,
                }
            )

    summary = {
        "mode": mode,
        "scope": "2-D learned projection matrices only; biases, tables, vectors, gates, and scalar scales protected",
        "tensor_count_total": len(weights),
        "tensor_count_quantized": eligible,
        "elements_quantized": eligible_elements,
        "original_dense_bytes": original_bytes,
        "estimated_quantized_storage_bytes": estimated_bytes,
        "estimated_dense_storage_reduction": 1.0 - (estimated_bytes / max(1, original_bytes)),
        "mean_abs_weight_error": total_abs_error / max(1, total_error_elements),
        "rms_weight_error": float((total_sq_error / max(1, total_error_elements)) ** 0.5),
        "tensors": tensor_records,
        "runtime_note": "The evaluator dequantizes before FP16 compute; storage reduction is real, but speed is not a production quantized-kernel measurement.",
    }
    return quantized, summary


def true_fp8_round_trip(value: Any) -> Any:
    import torch

    return value.clamp(-448.0, 448.0).to(torch.float8_e4m3fn).to(value.dtype)


def make_pipeline(mode: str, weights: dict[str, Any], mlx_python: Path, device: str):
    """Build one isolated pipeline and return it with a cleanup callback."""

    if str(mlx_python) not in sys.path:
        sys.path.insert(0, str(mlx_python))
    import torch
    import mlxdlss
    from mlxdlss import NeuralRenderingPipeline

    cleanup: Callable[[], None] = lambda: None
    if mode == "reference":
        pipeline = NeuralRenderingPipeline(weights, device=device, precision="reference")
    elif mode == "fast_fp16":
        pipeline = NeuralRenderingPipeline(weights, device=device, precision="fast")
    elif mode == "weight_fp8_dequant_fp16":
        dequantized, quant_summary = quantize_weights(weights, "fp8")
        pipeline = NeuralRenderingPipeline(dequantized, device=device, precision="fast")
        pipeline._quantization_summary = quant_summary
    elif mode == "weight_int8_dequant_fp16":
        dequantized, quant_summary = quantize_weights(weights, "int8")
        pipeline = NeuralRenderingPipeline(dequantized, device=device, precision="fast")
        pipeline._quantization_summary = quant_summary
    elif mode == "activation_fp8_fast":
        original_round_trip = mlxdlss.model.e4m3_round_trip
        mlxdlss.model.e4m3_round_trip = true_fp8_round_trip
        pipeline = NeuralRenderingPipeline(weights, device=device, precision="fast")

        def restore() -> None:
            mlxdlss.model.e4m3_round_trip = original_round_trip

        cleanup = restore
    elif mode == "compiled_fast_fp16":
        pipeline = NeuralRenderingPipeline(weights, device=device, precision="fast")
        if not hasattr(torch, "compile"):
            raise RuntimeError("this PyTorch build has no torch.compile")
        compile_started = time.perf_counter()
        pipeline.model = torch.compile(
            pipeline.model,
            mode="reduce-overhead",
            fullgraph=False,
            dynamic=False,
        )
        pipeline._compile_setup_seconds = time.perf_counter() - compile_started
    else:
        raise ValueError(mode)
    pipeline.model.eval()
    return pipeline, cleanup


def run_model_timed(pipeline: Any, features: np.ndarray, warmup: int, iterations: int) -> tuple[Any, dict[str, float]]:
    import torch

    tensor = torch.from_numpy(np.ascontiguousarray(features)).to(pipeline.device, pipeline.dtype)[None]
    synchronize = torch.cuda.synchronize if tensor.device.type == "cuda" else lambda: None
    for _ in range(max(0, warmup)):
        _ = pipeline.model(tensor)
    synchronize()
    times: list[float] = []
    output = None
    for _ in range(max(1, iterations)):
        synchronize()
        started = time.perf_counter()
        output = pipeline.model(tensor)
        synchronize()
        times.append((time.perf_counter() - started) * 1000.0)
    return output, {
        "warmup_count": int(max(0, warmup)),
        "iterations": int(max(1, iterations)),
        "model_only_median_ms": float(np.median(times)),
        "model_only_p95_ms": float(np.percentile(times, 95.0)),
        "model_only_min_ms": float(np.min(times)),
        "model_only_max_ms": float(np.max(times)),
    }


def run_one(pipeline: Any, row: dict[str, Any], warmup: int, iterations: int) -> tuple[np.ndarray, dict[str, Any]]:
    width, height = (int(row["color_size"][0]), int(row["color_size"][1]))
    source = read_rgba_raw(Path(row["raw_paths"]["input"]), width, height)
    native = read_rgba_raw(Path(row["raw_paths"]["teacher"]), width, height)
    prepared = pipeline.prepare(
        source,
        profile="standard",
        processing_scale=1.0,
        frame_index=0,
        local_tone_strength=1.0,
        local_structure_strength=1.0,
    )
    head, timing = run_model_timed(pipeline, prepared.features, warmup, iterations)
    head_numpy = head[0].to(torch_float32()).detach().cpu().numpy()
    finish_started = time.perf_counter()
    result = pipeline.finish(
        prepared,
        head_numpy,
        detail_strength=1.0,
        colour_strength=1.0,
        intensity=1.0,
        network_seconds=timing["model_only_median_ms"] / 1000.0,
    )
    finish_ms = (time.perf_counter() - finish_started) * 1000.0
    return np.asarray(result.image, dtype=np.float32), {
        "source": source,
        "native": native,
        "timing": {**timing, "postprocess_ms": float(finish_ms)},
        "shape": list(result.image.shape),
        "preprocess_ms": float(prepared.preprocess_seconds * 1000.0),
    }


def torch_float32():
    import torch

    return torch.float32


def aggregate(records: list[dict[str, Any]], field: str) -> float | None:
    values = [float(item[field]) for item in records if field in item and item[field] is not None]
    return float(np.mean(values)) if values else None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--weights", type=Path, required=True)
    parser.add_argument("--mlx-python", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--split", choices=("train", "validation", "test"), default="test")
    parser.add_argument("--frames", default="1,8,16")
    parser.add_argument("--max-rows", type=int, default=6, help="0 means every selected eye row")
    parser.add_argument("--warmup", type=int, default=1)
    parser.add_argument("--iterations", type=int, default=2)
    parser.add_argument("--skip-compile", action="store_true")
    parser.add_argument("--device", default="cuda")
    args = parser.parse_args()

    cache = args.cache.expanduser().resolve()
    weights_path = args.weights.expanduser().resolve()
    mlx_python = args.mlx_python.expanduser().resolve()
    output = args.output.expanduser().resolve()
    if not cache.is_dir() or not (cache / "rows.json").is_file():
        raise FileNotFoundError(cache)
    for path in (weights_path, mlx_python):
        if not path.exists():
            raise FileNotFoundError(path)
    if output.exists() and any(output.iterdir()):
        raise FileExistsError(f"refusing to overwrite non-empty output: {output}")
    output.mkdir(parents=True, exist_ok=True)

    if str(mlx_python) not in sys.path:
        sys.path.insert(0, str(mlx_python))
    import torch
    from mlxdlss.pipeline import load_weights

    if str(args.device).startswith("cuda") and not torch.cuda.is_available():
        raise RuntimeError("CUDA requested but torch.cuda.is_available() is false")
    torch.set_num_threads(4)
    rows = json.loads((cache / "rows.json").read_text(encoding="utf-8"))
    frames = {int(value.strip()) for value in args.frames.split(",") if value.strip()}
    selected = select_rows(rows, args.split, frames, args.max_rows)
    weights = load_weights(weights_path)

    identity = {
        "schema": "opennr-whitebox-quantization-probe-v1",
        "cache": str(cache),
        "cache_complete_sha256": sha256_file(cache / "complete.json") if (cache / "complete.json").is_file() else None,
        "rows_sha256": sha256_file(cache / "rows.json"),
        "weights": str(weights_path),
        "weights_sha256": sha256_file(weights_path),
        "mlx_python": str(mlx_python),
        "torch_version": torch.__version__,
        "cuda_version": torch.version.cuda,
        "gpu": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
        "device": str(args.device),
        "split": args.split,
        "frames": sorted(frames),
        "selected_rows": [int(index) for index, _ in selected],
        "selected_eye_rows": [
            {
                "row": int(index),
                "sequence_id": row["sequence_id"],
                "frame_id": int(row["frame_id"]),
                "eye": int(row["eye"]),
            }
            for index, row in selected
        ],
        "controls": {
            "profile": "standard",
            "processing_scale": 1.0,
            "frame_index": 0,
            "local_tone_strength": 1.0,
            "local_structure_strength": 1.0,
            "automatic_mask": False,
            "detail_strength": 1.0,
            "colour_strength": 1.0,
            "intensity": 1.0,
        },
        "test_used_for_selection": False,
        "training_started": False,
        "runtime_changed": False,
        "promotion": False,
    }
    write_json(output / "identity.json", identity)

    reference_outputs: dict[int, Path] = {}
    results: dict[str, Any] = {}
    modes = list(MODEL_MODES)
    if args.skip_compile:
        modes.remove("compiled_fast_fp16")

    for mode in modes:
        print(json.dumps({"event": "mode_start", "mode": mode}), flush=True)
        mode_dir = output / mode
        mode_dir.mkdir(parents=True, exist_ok=True)
        mode_result: dict[str, Any] = {
            "mode": mode,
            "status": "starting",
            "records": [],
            "quantization": None,
            "test_used_for_selection": False,
        }
        pipeline = None
        cleanup: Callable[[], None] = lambda: None
        try:
            pipeline, cleanup = make_pipeline(mode, weights, mlx_python, args.device)
            mode_result["quantization"] = getattr(pipeline, "_quantization_summary", None)
            mode_result["compile_setup_seconds"] = getattr(pipeline, "_compile_setup_seconds", None)
            if torch.cuda.is_available():
                torch.cuda.reset_peak_memory_stats()
            started = time.perf_counter()
            for position, (row_index, row) in enumerate(selected):
                recovered, details = run_one(pipeline, row, args.warmup, args.iterations)
                record: dict[str, Any] = {
                    "row": int(row_index),
                    "sequence_id": row["sequence_id"],
                    "frame_id": int(row["frame_id"]),
                    "eye": int(row["eye"]),
                    "split": row["split"],
                    "shape": details["shape"],
                    "preprocess_ms": details["preprocess_ms"],
                    "timing": details["timing"],
                    "recovered_vs_native": metrics(recovered, details["native"]),
                    "source_vs_native": metrics(details["source"], details["native"]),
                }
                if mode == "reference":
                    reference_path = mode_dir / f"row{row_index:05d}_{row['sequence_id']}_f{int(row['frame_id'])}_e{int(row['eye'])}.npy"
                    np.save(reference_path, recovered.astype(np.float32))
                    reference_outputs[row_index] = reference_path
                    if position == 0:
                        save_rgb(mode_dir / "first_recovered.png", recovered)
                else:
                    reference_path = reference_outputs.get(row_index)
                    if reference_path is None:
                        raise RuntimeError(f"reference output missing for row {row_index}")
                    reference = np.load(reference_path)
                    record["recovered_vs_unquantized_reference"] = metrics(recovered, reference)
                    if position == 0:
                        save_rgb(mode_dir / "first_recovered.png", recovered)
                        save_rgb(mode_dir / "first_reference.png", reference)
                        save_rgb(mode_dir / "first_absolute_difference_x8.png", np.clip(np.abs(recovered - reference) * 8.0, 0.0, 1.0))
                mode_result["records"].append(record)
                print(
                    json.dumps(
                        {
                            "event": "row_complete",
                            "mode": mode,
                            "row": int(row_index),
                            "sequence": row["sequence_id"],
                            "frame": int(row["frame_id"]),
                            "eye": int(row["eye"]),
                            "model_only_ms": details["timing"]["model_only_median_ms"],
                            "vs_reference_mae": record.get("recovered_vs_unquantized_reference", {}).get("mae"),
                        }
                    ),
                    flush=True,
                )
                del recovered
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()

            mode_result["status"] = "complete"
            mode_result["elapsed_seconds"] = float(time.perf_counter() - started)
            mode_result["mean_model_only_ms"] = aggregate(
                [item["timing"] for item in mode_result["records"]], "model_only_median_ms"
            )
            mode_result["mean_postprocess_ms"] = aggregate(
                [item["timing"] for item in mode_result["records"]], "postprocess_ms"
            )
            mode_result["mean_recovered_vs_native_mae"] = float(
                np.mean([item["recovered_vs_native"]["mae"] for item in mode_result["records"]])
            )
            if mode != "reference":
                mode_result["mean_vs_unquantized_reference_mae"] = float(
                    np.mean([item["recovered_vs_unquantized_reference"]["mae"] for item in mode_result["records"]])
                )
                mode_result["max_vs_unquantized_reference_p999_abs"] = float(
                    max(item["recovered_vs_unquantized_reference"]["p999_abs"] for item in mode_result["records"])
                )
            mode_result["peak_cuda_memory_allocated_bytes"] = int(torch.cuda.max_memory_allocated()) if torch.cuda.is_available() else None
            mode_result["peak_cuda_memory_reserved_bytes"] = int(torch.cuda.max_memory_reserved()) if torch.cuda.is_available() else None
        except Exception as exc:
            mode_result["status"] = "failed"
            mode_result["error"] = repr(exc)
            print(json.dumps({"event": "mode_failed", "mode": mode, "error": repr(exc)}), flush=True)
        finally:
            try:
                cleanup()
            finally:
                if pipeline is not None:
                    del pipeline
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
        results[mode] = mode_result
        write_json(output / "progress.json", {"identity": identity, "modes": results})
        print(json.dumps({"event": "mode_complete", "mode": mode, "status": mode_result["status"]}), flush=True)

    # Add pair-level sequential stereo estimates from the already measured eye
    # medians.  This is still model-only and not a live compositor measurement.
    for mode, mode_result in results.items():
        if mode_result.get("status") != "complete":
            continue
        pairs: defaultdict[tuple[str, int], list[float]] = defaultdict(list)
        for record in mode_result["records"]:
            pairs[(record["sequence_id"], int(record["frame_id"]))].append(
                float(record["timing"]["model_only_median_ms"])
            )
        pair_values = [sum(values) for values in pairs.values() if len(values) == 2]
        mode_result["stereo_pair_count"] = len(pair_values)
        mode_result["mean_sequential_stereo_model_ms"] = float(np.mean(pair_values)) if pair_values else None

    summary = {
        "schema": "opennr-whitebox-quantization-study-v1",
        "scope": "offline full-eye recovered-graph precision/quantization probe; native teacher is a comparison guardrail; not temporal, live-VR, deployment, or promotion evidence",
        "identity": identity,
        "modes": results,
        "interpretation": {
            "reference": "Current recovered graph in reference precision; the output target for numerical drift.",
            "fast_fp16": "Existing fast FP16 graph control; not claimed to be mixed source-dtype execution.",
            "weight_fp8_dequant_fp16": "FP8 E4M3 matrix-weight round-trip followed by FP16 compute; numerical/storage feasibility only.",
            "weight_int8_dequant_fp16": "Per-output-channel INT8 matrix-weight round-trip followed by FP16 compute; numerical/storage feasibility only.",
            "activation_fp8_fast": "Fast FP16 graph with the recovered activation E4M3 boundaries routed through direct CUDA float8 casts.",
            "compiled_fast_fp16": "torch.compile control around the existing fast graph; compile setup and warm-up are kept separate from steady-state timing.",
            "runtime_warning": "A dequantized FP16 control cannot prove a production quantized kernel speed-up. A true speed win requires a fused backend and end-to-end same-contract measurement.",
            "test_used_for_selection": False,
            "training_started": False,
            "runtime_changed": False,
            "promotion": False,
        },
    }
    write_json(output / "whitebox_quantization_study.json", summary)
    print(
        json.dumps(
            {
                "event": "study_complete",
                "output": str(output),
                "modes": {name: value.get("status") for name, value in results.items()},
            },
            indent=2,
        ),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
