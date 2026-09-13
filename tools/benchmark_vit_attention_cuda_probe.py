#!/usr/bin/env python3
"""Compare the recovered ViT attention path with CUDA SDPA on real inputs.

This is a bounded operator benchmark.  SDPA uses ordinary softmax semantics,
so it is a speed control and not a native-arithmetic replacement claim.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import time

import numpy as np
import torch
import torch.nn.functional as F


def read_half(path: Path, shape: tuple[int, ...]) -> torch.Tensor:
    values = np.fromfile(path, dtype=np.float16)
    expected = int(np.prod(shape))
    if values.size != expected:
        raise ValueError(f"{path} has {values.size} values; expected {expected}")
    return torch.from_numpy(values.reshape(shape)).to("cuda").contiguous()


def event_benchmark(fn, *, warmup: int, iterations: int) -> tuple[list[float], torch.Tensor]:
    output = None
    for _ in range(warmup):
        output = fn()
    torch.cuda.synchronize()
    times: list[float] = []
    for _ in range(iterations):
        start = torch.cuda.Event(enable_timing=True)
        stop = torch.cuda.Event(enable_timing=True)
        start.record()
        output = fn()
        stop.record()
        stop.synchronize()
        times.append(float(start.elapsed_time(stop)))
    assert output is not None
    return times, output


def summarize(times: list[float], output: torch.Tensor) -> dict[str, object]:
    values = output.detach().float()
    return {
        "times_ms": times,
        "median_ms": float(np.median(times)),
        "p95_ms": float(np.percentile(times, 95)),
        "output_shape": list(output.shape),
        "output_finite": bool(torch.isfinite(values).all().item()),
        "output_min": float(values.min().item()),
        "output_max": float(values.max().item()),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inputs", type=Path, required=True)
    parser.add_argument("--backend", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--warmup", type=int, default=3)
    parser.add_argument("--iterations", type=int, default=10)
    args = parser.parse_args()

    inputs = args.inputs.resolve()
    backend = args.backend.resolve()
    if str(backend) not in sys.path:
        sys.path.insert(0, str(backend))
    from nr_backend.execution import use_arithmetic_backend
    from nr_backend.pre_mlp import quantize_fp8
    from nr_backend.attention import attention_row_sum64
    from nr_backend.vit_block import vit_attention, vit_exponential

    manifest = json.loads((inputs / "manifest.json").read_text(encoding="utf-8"))
    tokens = int(manifest["tokens"])
    query = read_half(inputs / "query.bin", (tokens, 32, 32))
    key = read_half(inputs / "key.bin", (tokens, 32, 32))
    value = read_half(inputs / "value.bin", (tokens, 32, 32))
    expected = read_half(inputs / "projection_input.bin", (tokens, 1024))

    # The reconstructed function uses [heads,tokens,channels].  SDPA uses a
    # batch dimension followed by the same head-major convention.
    q_heads = query.transpose(0, 1).contiguous()
    k_heads = key.transpose(0, 1).contiguous()
    v_heads = value.transpose(0, 1).contiguous()

    def exact_attention() -> torch.Tensor:
        with use_arithmetic_backend("triton"):
            return vit_attention(q_heads, k_heads, v_heads).transpose(0, 1).reshape(tokens, 1024)

    def sdpa_default() -> torch.Tensor:
        result = F.scaled_dot_product_attention(
            q_heads.unsqueeze(0), k_heads.unsqueeze(0), v_heads.unsqueeze(0),
            dropout_p=0.0, scale=1.0,
        )
        return result.squeeze(0).transpose(0, 1).reshape(tokens, 1024).half()

    def sdpa_quantized() -> torch.Tensor:
        result = F.scaled_dot_product_attention(
            q_heads.unsqueeze(0), k_heads.unsqueeze(0), v_heads.unsqueeze(0),
            dropout_p=0.0, scale=1.0,
        )
        with use_arithmetic_backend("triton"):
            result = quantize_fp8(result)
        return result.squeeze(0).transpose(0, 1).reshape(tokens, 1024).half()

    def bmm_native_math() -> torch.Tensor:
        # Keep the recovered score transform, FP8 boundary, and 64-key
        # reduction order, but replace the two independent reconstructed
        # batched-dot calls with CUDA Tensor-Core batched GEMMs.  This is a
        # closer speed control than ordinary SDPA, though it still differs in
        # the accumulator/rounding behavior of the recovered QMMA path.
        with use_arithmetic_backend("triton"):
            scores = torch.bmm(q_heads, k_heads.transpose(1, 2))
            exponential = vit_exponential(scores)
            numerator = torch.bmm(quantize_fp8(exponential), v_heads)
            total = attention_row_sum64(exponential[..., :64])
            for start in range(64, exponential.shape[-1], 64):
                total = (total + attention_row_sum64(
                    exponential[..., start:start + 64]
                )).half()
            reciprocal = total.clamp(
                min=0.00006198883056640625
            ).float().reciprocal().half()
            return quantize_fp8(
                (numerator * reciprocal).half()
            ).transpose(0, 1).reshape(tokens, 1024)

    results: dict[str, object] = {
        "schema": "opennr-vit-attention-cuda-probe-v1",
        "inputs": str(inputs),
        "backend": str(backend),
        "tokens": tokens,
        "heads": 32,
        "head_dim": 32,
        "warmup": args.warmup,
        "iterations": args.iterations,
        "cuda_device": torch.cuda.get_device_name(0),
        "torch": torch.__version__,
        "cuda": torch.version.cuda,
        "cases": {},
        "scope": (
            "real recovered ViT Q/K/V attention inputs; exact case uses the "
            "public reconstructed arithmetic, SDPA is a speed control and "
            "not a native-parity replacement"
        ),
    }

    exact_times, exact_output = event_benchmark(
        exact_attention, warmup=args.warmup, iterations=args.iterations
    )
    exact_values = exact_output.detach().float()
    exact_diff = exact_values - expected.detach().float()
    results["cases"]["reconstructed_triton"] = summarize(exact_times, exact_output)
    results["cases"]["reconstructed_triton"].update({
        "mae_vs_exported_attention": float(exact_diff.abs().mean().item()),
        "max_abs_vs_exported_attention": float(exact_diff.abs().max().item()),
    })

    sdpa_times, sdpa_output = event_benchmark(
        sdpa_default, warmup=args.warmup, iterations=args.iterations
    )
    sdpa_values = sdpa_output.detach().float()
    sdpa_diff = sdpa_values - expected.detach().float()
    results["cases"]["sdpa_default"] = summarize(sdpa_times, sdpa_output)
    results["cases"]["sdpa_default"].update({
        "mae_vs_exported_attention": float(sdpa_diff.abs().mean().item()),
        "max_abs_vs_exported_attention": float(sdpa_diff.abs().max().item()),
    })

    sdpa_quantized_times, sdpa_quantized_output = event_benchmark(
        sdpa_quantized, warmup=args.warmup, iterations=args.iterations
    )
    sdpa_quantized_values = sdpa_quantized_output.detach().float()
    sdpa_quantized_diff = sdpa_quantized_values - expected.detach().float()
    results["cases"]["sdpa_fp8_quantized"] = summarize(
        sdpa_quantized_times, sdpa_quantized_output
    )
    results["cases"]["sdpa_fp8_quantized"].update({
        "mae_vs_exported_attention": float(sdpa_quantized_diff.abs().mean().item()),
        "max_abs_vs_exported_attention": float(sdpa_quantized_diff.abs().max().item()),
    })

    bmm_times, bmm_output = event_benchmark(
        bmm_native_math, warmup=args.warmup, iterations=args.iterations
    )
    bmm_values = bmm_output.detach().float()
    bmm_diff = bmm_values - expected.detach().float()
    results["cases"]["bmm_native_math"] = summarize(bmm_times, bmm_output)
    results["cases"]["bmm_native_math"].update({
        "mae_vs_exported_attention": float(bmm_diff.abs().mean().item()),
        "max_abs_vs_exported_attention": float(bmm_diff.abs().max().item()),
    })

    args.output.resolve().parent.mkdir(parents=True, exist_ok=True)
    args.output.resolve().write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(results, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
