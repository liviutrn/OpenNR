"""Compare a FastStudent-v1 PyTorch checkpoint with its fixed TensorRT engine."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import torch

from benchmark_fast_student_trt import FixedEngine
from fast_student_v1 import load_fast_student


def _metrics(actual: torch.Tensor, reference: torch.Tensor) -> dict[str, float | bool]:
    error = (actual.float() - reference.float()).abs()
    return {
        "finite": bool(torch.isfinite(actual).all().item()),
        "mean_abs": float(error.mean().item()),
        "max_abs": float(error.max().item()),
        "rmse": float(torch.sqrt((actual.float() - reference.float()).square().mean()).item()),
    }


def _copy_random(engine: FixedEngine, seed: int) -> None:
    generator = torch.Generator(device="cuda")
    generator.manual_seed(seed)
    engine.rgb.copy_(torch.rand(engine.rgb.shape, device="cuda", dtype=engine.rgb.dtype, generator=generator))
    engine.guides.copy_(torch.randn(engine.guides.shape, device="cuda", dtype=engine.guides.dtype, generator=generator))
    engine.context_input.copy_(torch.randn(engine.context_input.shape, device="cuda", dtype=engine.context_input.dtype, generator=generator))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--engine", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is required for this comparison")

    model, saved = load_fast_student(args.checkpoint.resolve(), "cuda")
    model.half().eval()
    engine = FixedEngine(args.engine.resolve())
    _copy_random(engine, 120912)

    def run_one(seed: int) -> dict[str, dict[str, float | bool]]:
        _copy_random(engine, seed)
        engine.reset_state()
        engine.stream.synchronize()
        rgb = engine.rgb.clone()
        guides = engine.guides.clone()
        context = engine.context_input.clone()
        hidden = engine.current_hidden.clone()
        previous = engine.current_previous.clone()
        with torch.inference_mode():
            reference, reference_state = model.forward_temporal(
                rgb, guides, context, (hidden, previous)
            )
        torch.cuda.synchronize()
        engine.execute()
        engine.stream.synchronize()
        actual_hidden = engine.current_hidden.clone()
        actual_previous = engine.current_previous.clone()
        actual_prediction = engine.prediction.clone()
        return {
            "prediction": _metrics(actual_prediction, reference),
            "hidden": _metrics(actual_hidden, reference_state[0]),
            "previous": _metrics(actual_previous, reference_state[1]),
        }

    reset = run_one(120913)
    steady = run_one(120914)
    result = {
        "checkpoint": str(args.checkpoint.resolve()),
        "engine": str(args.engine.resolve()),
        "architecture": saved["architecture"],
        "device": torch.cuda.get_device_name(0),
        "reset": reset,
        "steady": steady,
        "note": "FP16 TensorRT versus FP16 PyTorch recurrent numerical check; not quality parity against native DLSS5",
    }
    payload = json.dumps(result, indent=2)
    print(payload, flush=True)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
