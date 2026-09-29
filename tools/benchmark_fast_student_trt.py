"""Benchmark the fixed-shape FastStudent-v1 TensorRT engine with recurrent state."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import torch


REQUIRED_INPUTS = ("rgb", "guides", "context", "hidden", "previous")
REQUIRED_OUTPUTS = ("prediction", "next_hidden", "next_previous")


def _summary(values: list[float]) -> dict[str, float]:
    array = np.asarray(values, dtype=np.float64)
    return {
        "median_ms": float(np.percentile(array, 50)),
        "p95_ms": float(np.percentile(array, 95)),
        "p99_ms": float(np.percentile(array, 99)),
        "mean_ms": float(array.mean()),
        "min_ms": float(array.min()),
        "max_ms": float(array.max()),
    }


class FixedEngine:
    def __init__(self, path: Path):
        import tensorrt as trt

        self.trt = trt
        self.runtime = trt.Runtime(trt.Logger(trt.Logger.ERROR))
        self.engine = self.runtime.deserialize_cuda_engine(path.read_bytes())
        if self.engine is None:
            raise RuntimeError("TensorRT engine deserialization failed")
        self.context = self.engine.create_execution_context()
        if self.context is None:
            raise RuntimeError("TensorRT execution context creation failed")
        names = [self.engine.get_tensor_name(i) for i in range(self.engine.num_io_tensors)]
        if not all(name in names for name in REQUIRED_INPUTS + REQUIRED_OUTPUTS):
            raise RuntimeError(f"engine tensor contract is incomplete: {names}")
        for name in REQUIRED_INPUTS + REQUIRED_OUTPUTS:
            if self.engine.get_tensor_dtype(name) != trt.DataType.HALF:
                raise RuntimeError(f"{name} is not FP16")
        self.stream = torch.cuda.Stream()
        self.rgb = self._allocate("rgb")
        self.guides = self._allocate("guides")
        self.context_input = self._allocate("context")
        self.prediction = self._allocate("prediction")
        self.hidden_a = self._allocate("hidden")
        self.hidden_b = self._allocate("next_hidden")
        self.previous_a = self._allocate("previous")
        self.previous_b = self._allocate("next_previous")
        self.current_hidden = self.hidden_a
        self.next_hidden = self.hidden_b
        self.current_previous = self.previous_a
        self.next_previous = self.previous_b

    def _allocate(self, name: str) -> torch.Tensor:
        shape = tuple(self.engine.get_tensor_shape(name))
        return torch.empty(shape, device="cuda", dtype=torch.float16)

    def _bind(self) -> None:
        bindings = {
            "rgb": self.rgb,
            "guides": self.guides,
            "context": self.context_input,
            "hidden": self.current_hidden,
            "previous": self.current_previous,
            "prediction": self.prediction,
            "next_hidden": self.next_hidden,
            "next_previous": self.next_previous,
        }
        for name, value in bindings.items():
            self.context.set_tensor_address(name, value.data_ptr())

    def execute(self) -> None:
        self._bind()
        if not self.context.execute_async_v3(self.stream.cuda_stream):
            raise RuntimeError("TensorRT enqueueV3 failed")
        self.current_hidden, self.next_hidden = self.next_hidden, self.current_hidden
        self.current_previous, self.next_previous = self.next_previous, self.current_previous

    def reset_state(self) -> None:
        self.current_hidden.zero_()
        self.current_previous.copy_(self.rgb)


def measure(engine: FixedEngine, warmup: int, iterations: int, reset: bool) -> list[float]:
    for _ in range(warmup):
        if reset:
            engine.reset_state()
        engine.execute()
    engine.stream.synchronize()
    values = []
    for _ in range(iterations):
        if reset:
            engine.reset_state()
        start = torch.cuda.Event(enable_timing=True)
        end = torch.cuda.Event(enable_timing=True)
        start.record(engine.stream)
        engine.execute()
        end.record(engine.stream)
        end.synchronize()
        values.append(float(start.elapsed_time(end)))
    return values


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine", type=Path, required=True)
    parser.add_argument("--warmup", type=int, default=50)
    parser.add_argument("--iterations", type=int, default=200)
    args = parser.parse_args()
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is required for TensorRT benchmarking")
    if args.warmup < 1 or args.iterations < 2:
        raise ValueError("warmup must be positive and iterations must be at least two")

    engine = FixedEngine(args.engine.resolve())
    engine.rgb.uniform_(0.0, 1.0)
    engine.guides.normal_()
    engine.context_input.normal_()
    engine.reset_state()
    torch.cuda.reset_peak_memory_stats()
    with torch.inference_mode():
        reset_values = measure(engine, args.warmup, args.iterations, reset=True)
        steady_values = measure(engine, args.warmup, args.iterations, reset=False)
    engine.stream.synchronize()
    if not torch.isfinite(engine.prediction).all() or not torch.isfinite(engine.next_hidden).all():
        raise RuntimeError("TensorRT produced non-finite output")
    print(
        json.dumps(
            {
                "engine": str(args.engine.resolve()),
                "device": torch.cuda.get_device_name(0),
                "reset": _summary(reset_values),
                "steady": _summary(steady_values),
                "peak_vram_gib": torch.cuda.max_memory_allocated() / 2**30,
                "warmup": args.warmup,
                "iterations": args.iterations,
                "finite_output": True,
                "note": "isolated TensorRT enqueue timing; not Skyrim frame-time acceptance",
            },
            indent=2,
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()

