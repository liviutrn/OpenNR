"""Benchmark the semantic joint candidate as a causal GPU runtime.

The benchmark separates cold first-frame/reset cost from warm steady temporal
frames and reports GPU-resident per-eye and sequential stereo timings.  It does
not touch Skyrim, SteamVR, Community Shaders, or training artifacts.
"""

from __future__ import annotations

import argparse
import gc
import json
import math
import time
from contextlib import nullcontext
from pathlib import Path

import numpy as np
import torch

from semantic_joint_runtime import load_bundle, state_shapes


def summarize(values: list[float]) -> dict[str, float | int]:
    if not values:
        raise ValueError("No timing samples")
    values = [float(value) for value in values]
    return {
        "count": len(values),
        "min_ms": float(np.min(values)),
        "median_ms": float(np.median(values)),
        "p95_ms": float(np.percentile(values, 95)),
        "p99_ms": float(np.percentile(values, 99)),
        "max_ms": float(np.max(values)),
        "mean_ms": float(np.mean(values)),
    }


def _event_time(fn) -> tuple[float, object]:
    start = torch.cuda.Event(enable_timing=True)
    end = torch.cuda.Event(enable_timing=True)
    start.record()
    value = fn()
    end.record()
    end.synchronize()
    return float(start.elapsed_time(end)), value


def _autocast(precision: str):
    if precision == "fp16":
        return torch.autocast(device_type="cuda", dtype=torch.float16)
    if precision == "fp32":
        return nullcontext()
    raise ValueError(f"Unsupported PyTorch precision: {precision}")


def _load_cache_inputs(cache: Path, row_index: int | None) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor, torch.Tensor, dict]:
    cache = cache.resolve()
    rows = json.loads((cache / "rows.json").read_text(encoding="utf-8"))
    if row_index is None:
        row_index = next((i for i, row in enumerate(rows) if row.get("split") == "validation"), 0)
    if not 0 <= row_index < len(rows):
        raise IndexError(f"Row {row_index} is outside {len(rows)} rows")
    rgb_array = np.load(cache / "rgb.npy", mmap_mode="r")
    guides_array = np.load(cache / "guides.npy", mmap_mode="r")
    context_array = np.load(cache / "context.npy", mmap_mode="r")
    rgb = np.array(rgb_array[row_index, 0] if rgb_array.ndim == 5 else rgb_array[row_index], copy=True)
    guides = np.array(guides_array[row_index], copy=True)
    context = np.array(context_array[row_index], copy=True)
    if rgb.dtype == np.uint8:
        rgb = rgb.astype(np.float32) / 255.0
    else:
        rgb = rgb.astype(np.float32, copy=False)
    guides = guides.astype(np.float32, copy=False)
    context = context.astype(np.float32, copy=False)
    if rgb.ndim != 3 or guides.ndim != 3 or context.ndim != 3:
        raise ValueError("Cache row has unexpected tensor ranks")
    right = None
    if rgb_array.ndim == 5:
        right = np.array(rgb_array[row_index, 1], copy=True)
        right = right.astype(np.float32) / 255.0 if right.dtype == np.uint8 else right.astype(np.float32, copy=False)
    else:
        right = rgb.copy()
    metadata = {
        "source": str(cache),
        "row": row_index,
        "row_metadata": rows[row_index],
        "input_source": "validation row, left/right when the cache stores stereo RGB",
    }
    left = torch.from_numpy(rgb).unsqueeze(0)
    right_tensor = torch.from_numpy(right).unsqueeze(0)
    return left, right_tensor, torch.from_numpy(guides).unsqueeze(0), torch.from_numpy(context).unsqueeze(0), metadata


def _synthetic_inputs(height: int, width: int, guide_height: int, guide_width: int, context_height: int, context_width: int):
    generator = torch.Generator(device="cpu").manual_seed(812)
    left = torch.rand((1, 3, height, width), generator=generator)
    right = torch.rand((1, 3, height, width), generator=generator)
    guides = torch.rand((1, 5, guide_height, guide_width), generator=generator) * 0.25
    context = torch.rand((1, 8, context_height, context_width), generator=generator)
    return left, right, guides, context, {"input_source": "deterministic synthetic tensors"}


def prepare_inputs(args):
    if args.cache:
        values = _load_cache_inputs(args.cache, args.row)
        left, right, guides, context, metadata = values
        if left.shape[-2:] != (args.height, args.width):
            raise ValueError(f"Cache RGB is {tuple(left.shape[-2:])}, requested {(args.height, args.width)}")
        if guides.shape[-2:] != (args.guide_height, args.guide_width):
            raise ValueError(
                f"Cache guides are {tuple(guides.shape[-2:])}, requested {(args.guide_height, args.guide_width)}"
            )
        if context.shape[-2:] != (args.context_height, args.context_width):
            raise ValueError(
                f"Cache context is {tuple(context.shape[-2:])}, requested {(args.context_height, args.context_width)}"
            )
    else:
        left, right, guides, context, metadata = _synthetic_inputs(
            args.height,
            args.width,
            args.guide_height,
            args.guide_width,
            args.context_height,
            args.context_width,
        )
    return (
        left.contiguous().cuda(),
        right.contiguous().cuda(),
        guides.contiguous().cuda(),
        context.contiguous().cuda(),
        metadata,
    )


class TensorRTEyeSession:
    """One fixed-shape causal eye chain with ping-ponged state buffers."""

    def __init__(self, engine_path: Path):
        import tensorrt as trt

        self.trt = trt
        self.logger = trt.Logger(trt.Logger.WARNING)
        self.runtime = trt.Runtime(self.logger)
        self.engine = self.runtime.deserialize_cuda_engine(Path(engine_path).read_bytes())
        if self.engine is None:
            raise RuntimeError("Could not deserialize TensorRT engine")
        self.context = self.engine.create_execution_context()
        names = [self.engine.get_tensor_name(i) for i in range(self.engine.num_io_tensors)]
        expected = {"rgb", "guides", "context", "hidden", "previous", "prediction", "next_hidden", "next_previous"}
        if set(names) != expected:
            raise ValueError(f"Unexpected TensorRT I/O names: {names}")
        self.input_shapes = {name: tuple(self.engine.get_tensor_shape(name)) for name in ("rgb", "guides", "context", "hidden", "previous")}
        self.output_slots = []
        for _ in range(2):
            slot = {
                name: torch.empty(
                    tuple(self.engine.get_tensor_shape(name)),
                    device="cuda",
                    dtype=self._torch_dtype(self.engine.get_tensor_dtype(name)),
                )
                for name in ("prediction", "next_hidden", "next_previous")
            }
            self.output_slots.append(slot)
        self.input_dtypes = {
            name: self._torch_dtype(self.engine.get_tensor_dtype(name))
            for name in ("rgb", "guides", "context", "hidden", "previous")
        }
        self.zero_hidden = torch.zeros(
            self.input_shapes["hidden"], device="cuda", dtype=self.input_dtypes["hidden"]
        )
        self.state_slot: int | None = None
        for name, dtype in self.input_dtypes.items():
            if dtype not in (torch.float16, torch.float32):
                raise ValueError(f"Expected FP16 or FP32 TensorRT input for {name}")

    @staticmethod
    def _torch_dtype(dtype):
        import tensorrt as trt

        if dtype == trt.float32:
            return torch.float32
        if dtype == trt.float16:
            return torch.float16
        raise ValueError(f"Unsupported TensorRT output dtype: {dtype}")

    def reset(self) -> None:
        self.state_slot = None

    def __call__(self, rgb, guides, context):
        if tuple(rgb.shape) != self.input_shapes["rgb"]:
            raise ValueError(f"RGB shape mismatch: {tuple(rgb.shape)} != {self.input_shapes['rgb']}")
        if self.state_slot is None:
            hidden = self.zero_hidden
            previous = rgb
            output_slot = 0
        else:
            current = self.output_slots[self.state_slot]
            hidden = current["next_hidden"]
            previous = current["next_previous"]
            output_slot = 1 - self.state_slot
        output = self.output_slots[output_slot]
        for name, tensor in (("rgb", rgb), ("guides", guides), ("context", context), ("hidden", hidden), ("previous", previous)):
            if tensor.dtype != self.input_dtypes[name] or not tensor.is_cuda or not tensor.is_contiguous():
                raise ValueError(f"{name} must be a contiguous CUDA {self.input_dtypes[name]} tensor")
            self.context.set_tensor_address(name, tensor.data_ptr())
        for name, tensor in output.items():
            self.context.set_tensor_address(name, tensor.data_ptr())
        if not self.context.execute_async_v3(torch.cuda.current_stream().cuda_stream):
            raise RuntimeError("TensorRT execution failed")
        self.state_slot = output_slot
        return output["prediction"], (output["next_hidden"], output["next_previous"])


def _call_eager(model, rgb, guides, context, state, precision):
    with torch.inference_mode(), _autocast(precision):
        return model.forward_temporal(rgb, guides, context, state)


def _call_engine(session: TensorRTEyeSession, rgb, guides, context, state):
    return session(rgb, guides, context)


def _measure_eye(call, reset, warmup: int, iterations: int):
    state = None
    for _ in range(warmup):
        state = call(state)[1]
    torch.cuda.synchronize()

    reset_times = []
    first_time, value = _event_time(lambda: call(None))
    reset_times.append(first_time)
    state = value[1]
    for _ in range(max(0, iterations // 10 - 1)):
        reset()
        measured, value = _event_time(lambda: call(None))
        reset_times.append(measured)
        state = value[1]
    reset()
    _, value = _event_time(lambda: call(None))
    state = value[1]
    steady_times = []
    last_prediction = value[0]
    for _ in range(iterations):
        measured, value = _event_time(lambda state=state: call(state))
        steady_times.append(measured)
        state = value[1]
        last_prediction = value[0]
    return {
        "first_reset_ms": reset_times[0],
        "warm_reset": summarize(reset_times[1:] or reset_times),
        "steady": summarize(steady_times),
        "last_output_finite": bool(torch.isfinite(last_prediction).all().item()),
    }


def _measure_stereo(call_left, call_right, reset_left, reset_right, warmup: int, iterations: int):
    state_left = state_right = None
    for _ in range(warmup):
        state_left = call_left(state_left)[1]
        state_right = call_right(state_right)[1]
    torch.cuda.synchronize()

    reset_times = []
    reset_left()
    reset_right()
    measured, values = _event_time(lambda: (call_left(None), call_right(None)))
    reset_times.append(measured)
    state_left, state_right = values[0][1], values[1][1]
    for _ in range(max(0, iterations // 10 - 1)):
        reset_left()
        reset_right()
        measured, values = _event_time(lambda: (call_left(None), call_right(None)))
        reset_times.append(measured)
        state_left, state_right = values[0][1], values[1][1]

    reset_left()
    reset_right()
    _, values = _event_time(lambda: (call_left(None), call_right(None)))
    state_left, state_right = values[0][1], values[1][1]
    steady_times = []
    last_left = values[0][0]
    last_right = values[1][0]
    for _ in range(iterations):
        measured, values = _event_time(
            lambda state_left=state_left, state_right=state_right: (call_left(state_left), call_right(state_right))
        )
        steady_times.append(measured)
        state_left, state_right = values[0][1], values[1][1]
        last_left, last_right = values[0][0], values[1][0]
    return {
        "first_reset_ms": reset_times[0],
        "warm_reset": summarize(reset_times[1:] or reset_times),
        "steady": summarize(steady_times),
        "last_left_finite": bool(torch.isfinite(last_left).all().item()),
        "last_right_finite": bool(torch.isfinite(last_right).all().item()),
    }


def _memory_report() -> dict:
    return {
        "allocated_gib": torch.cuda.memory_allocated() / 2**30,
        "reserved_gib": torch.cuda.memory_reserved() / 2**30,
        "peak_allocated_gib": torch.cuda.max_memory_allocated() / 2**30,
        "peak_reserved_gib": torch.cuda.max_memory_reserved() / 2**30,
        "device_total_gib": torch.cuda.get_device_properties(0).total_memory / 2**30,
    }


def _nvml_memory_report() -> dict:
    """Report device-wide VRAM as well as the PyTorch allocator counters.

    TensorRT allocations are not included in ``torch.cuda.memory_*``.  NVML is
    therefore the useful cross-runtime measurement for the engine path.  The
    call is deliberately best-effort so a missing NVML binding does not hide a
    valid latency result.
    """

    try:
        import pynvml

        pynvml.nvmlInit()
        try:
            handle = pynvml.nvmlDeviceGetHandleByIndex(0)
            info = pynvml.nvmlDeviceGetMemoryInfo(handle)
            return {
                "available": True,
                "used_mib": float(info.used / 2**20),
                "free_mib": float(info.free / 2**20),
                "total_mib": float(info.total / 2**20),
            }
        finally:
            pynvml.nvmlShutdown()
    except Exception as exc:  # pragma: no cover - depends on installed driver bindings
        return {"available": False, "error": f"{type(exc).__name__}: {exc}"}


def _eager_numerical_reference(bundle: Path, inputs):
    model, _ = load_bundle(bundle, "cuda")
    model.eval()
    left, _, guides, context, _ = inputs
    with torch.inference_mode():
        first, state = model.forward_temporal(left, guides, context, None)
        second, next_state = model.forward_temporal(left, guides, context, state)
    return first, second, state, next_state


def _engine_numerical_check(bundle: Path, engine_path: Path, inputs):
    ref_first, ref_second, ref_state, ref_next_state = _eager_numerical_reference(bundle, inputs)
    session = TensorRTEyeSession(engine_path)
    left, _, guides, context, _ = inputs
    engine_dtype = session.input_dtypes["rgb"]
    left = left.to(dtype=engine_dtype).contiguous()
    guides = guides.to(dtype=session.input_dtypes["guides"]).contiguous()
    context = context.to(dtype=session.input_dtypes["context"]).contiguous()
    session.reset()
    with torch.inference_mode():
        first, state = session(left, guides, context)
        second, next_state = session(left, guides, context)
    torch.cuda.synchronize()

    def compare(actual, expected):
        delta = (actual.float() - expected.float()).abs()
        return {
            "mean_absolute_difference": float(delta.mean().item()),
            "max_absolute_difference": float(delta.max().item()),
            "finite": bool(torch.isfinite(actual).all().item()),
        }

    rows = {
        "first_prediction": compare(first, ref_first),
        "steady_prediction": compare(second, ref_second),
        "first_hidden": compare(state[0], ref_state[0]),
        "steady_hidden": compare(next_state[0], ref_next_state[0]),
    }
    for row in rows.values():
        row["passed"] = row["finite"] and row["mean_absolute_difference"] <= 0.002 and row["max_absolute_difference"] <= 0.1
    return {
        "tolerance": {"mean_absolute_difference": 0.002, "max_absolute_difference": 0.1},
        "checks": rows,
        "passed": all(row["passed"] for row in rows.values()),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    # A TensorRT run may optionally carry the frozen bundle as a numerical
    # reference.  Keep the two source arguments independent so
    # ``--engine ... --bundle ... --compare`` is valid, while still requiring
    # at least one runtime source below.
    parser.add_argument("--bundle", type=Path)
    parser.add_argument("--engine", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cache", type=Path)
    parser.add_argument("--row", type=int)
    parser.add_argument("--height", type=int, default=512)
    parser.add_argument("--width", type=int, default=512)
    parser.add_argument("--guide-height", type=int)
    parser.add_argument("--guide-width", type=int)
    parser.add_argument("--context-height", type=int, default=96)
    parser.add_argument("--context-width", type=int, default=96)
    parser.add_argument("--precision", choices=("fp16", "fp32"), default="fp16")
    parser.add_argument("--warmup", type=int, default=4)
    parser.add_argument("--iterations", type=int, default=80)
    parser.add_argument("--compare", action="store_true", help="For TensorRT, compare first/steady outputs with the bundle reference")
    args = parser.parse_args()
    if args.bundle is None and args.engine is None:
        parser.error("one of --bundle or --engine is required")
    if args.compare and args.engine is None:
        parser.error("--compare requires --engine and a frozen --bundle reference")
    if args.compare and args.bundle is None:
        parser.error("--compare requires --bundle")
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is required")
    args.guide_height = args.guide_height or (args.height + 3) // 4
    args.guide_width = args.guide_width or (args.width + 3) // 4
    inputs = prepare_inputs(args)
    left, right, guides, context, input_metadata = inputs
    if tuple(left.shape) != (1, 3, args.height, args.width):
        raise ValueError("Prepared RGB shape does not match requested dimensions")
    torch.cuda.synchronize()
    torch.cuda.reset_peak_memory_stats()
    started = time.time()
    runtime_started = started
    nvml_before = _nvml_memory_report()

    if args.engine is None:
        model, bundle = load_bundle(args.bundle.resolve(), "cuda")
        model.eval()
        call_left = lambda state: _call_eager(model, left, guides, context, state, args.precision)
        call_right = lambda state: _call_eager(model, right, guides, context, state, args.precision)
        reset_left = lambda: None
        reset_right = lambda: None
        eye = _measure_eye(call_left, reset_left, args.warmup, args.iterations)
        stereo = _measure_stereo(call_left, call_right, reset_left, reset_right, args.warmup, args.iterations)
        runtime_kind = "pytorch_eager_autocast_" + args.precision
        source_path = args.bundle.resolve()
        source_sha = __import__("semantic_joint_runtime").sha256_file(source_path)
        numerical = None
        step = bundle["source_step"]
    else:
        numerical = _engine_numerical_check(args.bundle.resolve(), args.engine.resolve(), inputs) if args.compare and args.bundle else None
        # The numerical gate temporarily loads the eager reference model.  Do
        # not let that reference allocation contaminate the engine VRAM peak or
        # the measured TensorRT allocator state.
        gc.collect()
        torch.cuda.synchronize()
        torch.cuda.empty_cache()
        torch.cuda.reset_peak_memory_stats()
        runtime_started = time.time()
        session_left = TensorRTEyeSession(args.engine.resolve())
        session_right = TensorRTEyeSession(args.engine.resolve())
        left_engine = left.to(dtype=session_left.input_dtypes["rgb"]).contiguous()
        right_engine = right.to(dtype=session_right.input_dtypes["rgb"]).contiguous()
        guides_left = guides.to(dtype=session_left.input_dtypes["guides"]).contiguous()
        guides_right = guides.to(dtype=session_right.input_dtypes["guides"]).contiguous()
        context_left = context.to(dtype=session_left.input_dtypes["context"]).contiguous()
        context_right = context.to(dtype=session_right.input_dtypes["context"]).contiguous()
        call_left = lambda state: _call_engine(session_left, left_engine, guides_left, context_left, state)
        call_right = lambda state: _call_engine(session_right, right_engine, guides_right, context_right, state)
        reset_left = session_left.reset
        reset_right = session_right.reset
        eye = _measure_eye(call_left, reset_left, args.warmup, args.iterations)
        stereo = _measure_stereo(call_left, call_right, reset_left, reset_right, args.warmup, args.iterations)
        runtime_kind = (
            "tensorrt_fp16_tactics_fp16_io"
            if session_left.input_dtypes["rgb"] == torch.float16
            else "tensorrt_fp16_tactics_fp32_io"
        )
        source_path = args.engine.resolve()
        source_sha = __import__("semantic_joint_runtime").sha256_file(source_path)
        step = None
        if args.bundle:
            reference_bundle = torch.load(args.bundle.resolve(), map_location="cpu", weights_only=False)
            step = reference_bundle.get("source_step")

    result = {
        "state": "passed" if eye["last_output_finite"] and stereo["last_left_finite"] and stereo["last_right_finite"] and (numerical is None or numerical["passed"]) else "failed",
        "runtime_kind": runtime_kind,
        "source": str(source_path),
        "source_sha256": source_sha,
        "checkpoint_step": step,
        "gpu": torch.cuda.get_device_name(0),
        "torch": torch.__version__,
        "cuda": torch.version.cuda,
        "precision": args.precision if args.engine is None else (
            "FP16 TensorRT tactics, FP16 I/O"
            if runtime_kind.endswith("fp16_io")
            else "FP16 TensorRT tactics, FP32 I/O"
        ),
        "shape": {
            "height": args.height,
            "width": args.width,
            "guide_height": args.guide_height,
            "guide_width": args.guide_width,
            "context_height": args.context_height,
        },
        "input": input_metadata,
        "per_eye": eye,
        "sequential_stereo": stereo,
        "numerical_check": numerical,
        "memory": _memory_report(),
        "nvml_memory": {"before": nvml_before, "after": _nvml_memory_report()},
        "elapsed_wall_seconds": time.time() - runtime_started,
        "scope": "GPU-resident forward only; excludes CPU decode, guide preparation, D3D interop, compositor, game rendering and headset acceptance",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2), flush=True)
    if result["state"] != "passed":
        raise RuntimeError("Runtime benchmark failed numerical/finite-output gate")


if __name__ == "__main__":
    main()
