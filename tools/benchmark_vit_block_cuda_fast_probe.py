#!/usr/bin/env python3
"""Benchmark one CUDA-native approximation of a recovered ViT block.

The block keeps the recovered FP8/cubic/normalization boundaries and uses
cuBLAS-backed PyTorch matmul plus the measured BMM attention control.  It is
an offline speed experiment, not a native NVIDIA or full-network replacement.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

import numpy as np
import torch


def read_half(path: Path, shape: tuple[int, ...]) -> torch.Tensor:
    values = np.fromfile(path, dtype=np.float16)
    expected = int(np.prod(shape))
    if values.size != expected:
        raise ValueError(f"{path} has {values.size} values; expected {expected}")
    return torch.from_numpy(values.reshape(shape)).to("cuda").contiguous()


def event_benchmark(fn, *, warmup: int, iterations: int):
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


def describe_output(output: torch.Tensor, expected: torch.Tensor) -> dict[str, object]:
    values = output.detach().float()
    diff = values - expected.detach().float()
    return {
        "shape": list(output.shape),
        "finite": bool(torch.isfinite(values).all().item()),
        "mae_vs_reference": float(diff.abs().mean().item()),
        "rmse_vs_reference": float(torch.sqrt((diff * diff).mean()).item()),
        "max_abs_vs_reference": float(diff.abs().max().item()),
        "min": float(values.min().item()),
        "max": float(values.max().item()),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inputs", type=Path, required=True)
    parser.add_argument("--backend", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--warmup", type=int, default=3)
    parser.add_argument("--iterations", type=int, default=8)
    args = parser.parse_args()

    inputs = args.inputs.resolve()
    backend = args.backend.resolve()
    if str(backend) not in sys.path:
        sys.path.insert(0, str(backend))

    from nr_backend.attention import attention_row_sum64, normalize_c32
    from nr_backend.execution import use_arithmetic_backend
    from nr_backend.pre_mlp import cubic_quantize, quantize_fp8
    from nr_backend.vit_block import VitBlock, vit_exponential
    from nr_backend.weights import load_pinned_records

    manifest = json.loads((inputs / "manifest.json").read_text(encoding="utf-8"))
    tokens = int(manifest["tokens"])
    features = read_half(inputs / "expand_input.bin", (tokens, 1024))
    expand_weight = read_half(inputs / "expand_weight.bin", (1024, 4096))
    contract_weight = read_half(inputs / "contract_weight.bin", (4096, 1024))
    qkv_weight = read_half(inputs / "qkv_weight.bin", (1024, 3072))
    projection_weight = read_half(inputs / "projection_weight.bin", (1024, 1024))
    ffn_skip = read_half(inputs / "ffn_skip.bin", (1024,))
    attn_skip = read_half(inputs / "attn_skip.bin", (1024,))
    query_scale = read_half(inputs / "query_scale.bin", (32,))
    expected_hidden = read_half(inputs / "expand_expected.bin", (tokens, 4096))
    expected_mlp = read_half(inputs / "contract_expected.bin", (tokens, 1024))
    expected_attended = read_half(inputs / "projection_input.bin", (tokens, 1024))
    expected_output = read_half(inputs / "block_output.bin", (tokens, 1024))

    records = load_pinned_records(
        Path(manifest["source_weights"]).resolve()
    )
    exact_model = VitBlock([
        records[f"block{31}.layer{index}.layer"] for index in range(5)
    ]).eval().to("cuda")

    def bmm_native_math(query, key, value):
        scores = torch.bmm(query, key.transpose(1, 2))
        exponential = vit_exponential(scores)
        numerator = torch.bmm(quantize_fp8(exponential), value)
        total = attention_row_sum64(exponential[..., :64])
        for start in range(64, exponential.shape[-1], 64):
            total = (total + attention_row_sum64(
                exponential[..., start:start + 64]
            )).half()
        reciprocal = total.clamp(
            min=0.00006198883056640625
        ).float().reciprocal().half()
        return quantize_fp8((numerator * reciprocal).half())

    def fast_block():
        with use_arithmetic_backend("triton"):
            x = quantize_fp8(features)
            hidden = cubic_quantize(torch.matmul(x, expand_weight).half())
            initial = (features * ffn_skip).half()
            mlp = quantize_fp8(
                (torch.matmul(hidden, contract_weight) + initial).half()
            )
            z = torch.matmul(mlp, qkv_weight).reshape(tokens, 32, 3, 32)
            query = quantize_fp8(
                (normalize_c32(z[:, :, 0]) * 5.65625).half()
                * query_scale[None, :, None]
            )
            key = quantize_fp8(normalize_c32(z[:, :, 1]))
            value = quantize_fp8(z[:, :, 2])
            attended = bmm_native_math(
                query.transpose(0, 1).contiguous(),
                key.transpose(0, 1).contiguous(),
                value.transpose(0, 1).contiguous(),
            ).transpose(0, 1).reshape(tokens, 1024)
            output = quantize_fp8(
                (torch.matmul(attended, projection_weight)
                 + (mlp * attn_skip).half()).half()
            )
            return hidden, mlp, attended, output

    def exact_block():
        with use_arithmetic_backend("triton"):
            return exact_model.forward_boundaries(features)

    exact_times, exact_values = event_benchmark(
        lambda: exact_block()[-1], warmup=args.warmup, iterations=args.iterations
    )
    fast_times, fast_values = event_benchmark(
        fast_block, warmup=args.warmup, iterations=args.iterations
    )
    fast_hidden, fast_mlp, fast_attended, fast_output = fast_values

    result: dict[str, object] = {
        "schema": "opennr-vit-block-cuda-fast-probe-v1",
        "inputs": str(inputs),
        "backend": str(backend),
        "tokens": tokens,
        "cuda_device": torch.cuda.get_device_name(0),
        "torch": torch.__version__,
        "cuda": torch.version.cuda,
        "warmup": args.warmup,
        "iterations": args.iterations,
        "exact_reconstructed_ms": {
            "times": exact_times,
            "median": float(np.median(exact_times)),
            "p95": float(np.percentile(exact_times, 95)),
        },
        "cuda_native_approx_ms": {
            "times": fast_times,
            "median": float(np.median(fast_times)),
            "p95": float(np.percentile(fast_times, 95)),
        },
        "speedup_exact_over_cuda_native_approx": float(
            np.median(exact_times) / max(float(np.median(fast_times)), 1e-9)
        ),
        "boundaries": {
            "hidden": describe_output(fast_hidden, expected_hidden),
            "mlp": describe_output(fast_mlp, expected_mlp),
            "attended": describe_output(fast_attended, expected_attended),
            "output": describe_output(fast_output, expected_output),
        },
        "scope": (
            "one real recovered ViT block; CUDA-native approximation uses "
            "cuBLAS-backed matmul and BMM attention, not native NVIDIA runtime "
            "or full-network parity"
        ),
    }
    args.output.resolve().parent.mkdir(parents=True, exist_ok=True)
    args.output.resolve().write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
