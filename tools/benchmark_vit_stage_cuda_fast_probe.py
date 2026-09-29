#!/usr/bin/env python3
"""Benchmark a CUDA-native approximation of the complete recovered ViT stage.

This is an offline probe on one existing Skyrim frame.  It deliberately keeps
the public reconstructed prefix and exact eight-block reference available for
comparison, while replacing the ViT block's fine-grained dense arithmetic with
cuBLAS-backed matmul and the measured CUDA BMM attention control.

The ``split`` variant preserves the recovered K-partition/half-merge boundary
for the larger projections.  Neither variant is a native NVIDIA runtime or a
full-network replacement.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

import numpy as np
import torch


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


def describe(output: torch.Tensor, reference: torch.Tensor) -> dict[str, object]:
    values = output.detach().float()
    target = reference.detach().float()
    diff = values - target
    return {
        "shape": list(output.shape),
        "finite": bool(torch.isfinite(values).all().item()),
        "mae_vs_exact_stage": float(diff.abs().mean().item()),
        "rmse_vs_exact_stage": float(torch.sqrt((diff * diff).mean()).item()),
        "max_abs_vs_exact_stage": float(diff.abs().max().item()),
        "min": float(values.min().item()),
        "max": float(values.max().item()),
    }


def split_matmul(
    features: torch.Tensor,
    weight: torch.Tensor,
    initial: torch.Tensor | None = None,
    *,
    parts: int,
    matmul,
) -> torch.Tensor:
    """Approximate recovered partitioned dot with cuBLAS GEMMs.

    Each partition is a mature dense GEMM, and each merge is explicitly
    rounded to half.  This does not reproduce the recovered shared-exponent
    Tensor-Core accumulator, but it retains its observed partition boundary.
    """
    k = int(features.shape[-1])
    if weight.shape[0] != k or k % parts:
        raise ValueError("incompatible split matmul shapes")
    part = k // parts
    result = matmul(features[..., :part], weight[:part])
    if initial is not None:
        result = (result + initial).half()
    for index in range(1, parts):
        start = index * part
        result = (
            result
            + matmul(features[..., start : start + part], weight[start : start + part])
        ).half()
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend", type=Path, required=True)
    parser.add_argument("--weights", type=Path, required=True)
    parser.add_argument("--rgb-png", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--height", type=int, default=1080)
    parser.add_argument("--width", type=int, default=1920)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--warmup", type=int, default=2)
    parser.add_argument("--iterations", type=int, default=5)
    parser.add_argument("--dense-mode", choices=("fp16", "fp8"), default="fp16")
    parser.add_argument("--include-graph", action="store_true")
    args = parser.parse_args()

    if (args.height, args.width) not in {
        (256, 256), (512, 512), (480, 864), (1080, 1920), (1439, 2559)
    }:
        raise ValueError("use one of the observed public RGB contracts")

    backend = args.backend.resolve()
    if str(backend) not in sys.path:
        sys.path.insert(0, str(backend))

    from PIL import Image

    from nr_backend.attention import attention_row_sum64, normalize_c32
    from nr_backend.execution import use_arithmetic_backend
    from nr_backend.front import reset_front_features
    from nr_backend.pre_mlp import cubic_quantize, quantize_fp8
    from nr_backend.vit_block import VitBlock, vit_attention, vit_exponential
    from nr_backend.weights import load_pinned_records
    from nr_backend.executor import ResetNR

    image = Image.open(args.rgb_png.resolve()).convert("RGB").resize(
        (args.width, args.height), Image.Resampling.BOX
    )
    rgb = torch.from_numpy(
        np.asarray(image, dtype=np.float32) / 255.0
    ).to("cuda", dtype=torch.float16).contiguous()
    records = load_pinned_records(args.weights.resolve())
    model = ResetNR(records, None).eval().to("cuda")
    padded_size = model.PADDED_SIZES[(args.height, args.width)]
    fp8_weight_cache: dict[int, tuple[torch.Tensor, torch.Tensor]] = {}

    def fp8_matmul(input_features: torch.Tensor, weight: torch.Tensor) -> torch.Tensor:
        """Use cached column-major cuBLASLt FP8 GEMM for a 2-D projection."""
        if input_features.ndim != 2 or weight.ndim != 2:
            raise ValueError("FP8 probe expects 2-D matrices")
        activation = input_features.half().contiguous().to(
            torch.float8_e4m3fn
        )
        item = fp8_weight_cache.get(id(weight))
        if item is None or item[0] is not weight:
            logical = weight.half().contiguous().to(torch.float8_e4m3fn)
            packed = torch.empty_strided(
                logical.shape,
                (1, logical.shape[0]),
                device=logical.device,
                dtype=torch.float8_e4m3fn,
            )
            packed.copy_(logical)
            item = (weight, packed)
            fp8_weight_cache[id(weight)] = item
        scale = torch.ones((1,), device=activation.device, dtype=torch.float32)
        result = torch._scaled_mm(
            activation,
            item[1],
            scale_a=scale,
            scale_b=scale,
            out_dtype=torch.float16,
        )
        output = result[0] if isinstance(result, tuple) else result
        return output.reshape(input_features.shape[0], weight.shape[1])

    dense_matmul = torch.matmul if args.dense_mode == "fp16" else fp8_matmul

    with torch.inference_mode():
        front = reset_front_features(
            rgb, padded_size=padded_size, seed=args.seed, noise_source=None
        )
        x = model.pre.forward_features_outputs(front)[1]
        for group in model.encoder:
            for block in group:
                skip, down = block.forward_outputs(x)
                x = down if down is not None else skip
        for block in model.encoder512:
            x = block.forward_boundaries(x)[-1]
        features = x.reshape(-1, 1024).contiguous()
        exact_blocks = list(model.vit)
        if len(exact_blocks) != 8:
            raise ValueError("expected the recovered eight-block ViT stage")

        # Materialize exact per-block boundaries once for drift reporting.
        exact_boundaries: list[torch.Tensor] = []
        exact_x = features
        with use_arithmetic_backend("triton"):
            for block in exact_blocks:
                exact_x = block.forward_boundaries(exact_x)[-1]
                exact_boundaries.append(exact_x)
        exact_final = exact_x

    def bmm_native_math(query, key, value):
        scores = torch.bmm(query, key.transpose(1, 2))
        exponential = vit_exponential(scores)
        numerator = torch.bmm(quantize_fp8(exponential), value)
        total = attention_row_sum64(exponential[..., :64])
        for start in range(64, exponential.shape[-1], 64):
            total = (total + attention_row_sum64(
                exponential[..., start : start + 64]
            )).half()
        reciprocal = total.clamp(
            min=0.00006198883056640625
        ).float().reciprocal().half()
        return quantize_fp8((numerator * reciprocal).half())

    def fast_block(block, input_features, *, split: bool, exact_attention: bool):
        x = quantize_fp8(input_features)
        hidden = cubic_quantize(dense_matmul(x, block.expand).half())
        initial = (input_features * block.ffn_skip).half()
        if split:
            mlp = quantize_fp8(
                split_matmul(
                    hidden, block.contract, initial, parts=4, matmul=dense_matmul
                )
            )
        else:
            mlp = quantize_fp8(
                (dense_matmul(hidden, block.contract) + initial).half()
            )
        if split:
            z = split_matmul(
                mlp, block.qkv_weight, parts=2, matmul=dense_matmul
            )
        else:
            z = dense_matmul(mlp, block.qkv_weight)
        z = z.reshape(features.shape[0], 32, 3, 32)
        query = quantize_fp8(
            (normalize_c32(z[:, :, 0]) * 5.65625).half()
            * block.query_scale[None, :, None]
        )
        key = quantize_fp8(normalize_c32(z[:, :, 1]))
        value = quantize_fp8(z[:, :, 2])
        if exact_attention:
            attended = vit_attention(
                query.transpose(0, 1).contiguous(),
                key.transpose(0, 1).contiguous(),
                value.transpose(0, 1).contiguous(),
            ).transpose(0, 1).reshape(features.shape[0], 1024)
        else:
            attended = bmm_native_math(
                query.transpose(0, 1).contiguous(),
                key.transpose(0, 1).contiguous(),
                value.transpose(0, 1).contiguous(),
            ).transpose(0, 1).reshape(features.shape[0], 1024)
        initial = (mlp * block.attn_skip).half()
        if split:
            output = quantize_fp8(
                split_matmul(
                    attended,
                    block.projection,
                    initial,
                    parts=4,
                    matmul=dense_matmul,
                )
            )
        else:
            output = quantize_fp8(
                (dense_matmul(attended, block.projection) + initial).half()
            )
        return output

    def fast_stage(
        *, split: bool, exact_attention: bool, collect: bool = False
    ):
        values: list[torch.Tensor] = []
        current = features
        with use_arithmetic_backend("triton"):
            for block in exact_blocks:
                current = fast_block(
                    block, current, split=split, exact_attention=exact_attention
                )
                if collect:
                    values.append(current)
        return (current, values) if collect else current

    with torch.inference_mode():
        exact_times, _ = event_benchmark(
            lambda: model_vit_exact(exact_blocks, features, use_arithmetic_backend),
            warmup=args.warmup,
            iterations=args.iterations,
        )
        full_times, full_values = event_benchmark(
            lambda: fast_stage(split=False, exact_attention=False),
            warmup=args.warmup,
            iterations=args.iterations,
        )
        split_times, split_values = event_benchmark(
            lambda: fast_stage(split=True, exact_attention=False),
            warmup=args.warmup,
            iterations=args.iterations,
        )
        full_exact_attention_times, _ = event_benchmark(
            lambda: fast_stage(split=False, exact_attention=True),
            warmup=args.warmup,
            iterations=args.iterations,
        )
        split_exact_attention_times, _ = event_benchmark(
            lambda: fast_stage(split=True, exact_attention=True),
            warmup=args.warmup,
            iterations=args.iterations,
        )
        full_final, full_boundaries = fast_stage(
            split=False, exact_attention=False, collect=True
        )
        split_final, split_boundaries = fast_stage(
            split=True, exact_attention=False, collect=True
        )
        full_exact_attention_final, full_exact_attention_boundaries = fast_stage(
            split=False, exact_attention=True, collect=True
        )
        split_exact_attention_final, split_exact_attention_boundaries = fast_stage(
            split=True, exact_attention=True, collect=True
        )

        graph_times: list[float] = []
        graph_final = None
        if args.include_graph:
            torch.cuda.synchronize()
            graph = torch.cuda.CUDAGraph()
            with torch.cuda.graph(graph):
                graph_final = fast_stage(split=False, exact_attention=False)
            torch.cuda.synchronize()

            def replay_graph():
                graph.replay()
                return graph_final

            graph_times, graph_final = event_benchmark(
                replay_graph,
                warmup=args.warmup,
                iterations=args.iterations,
            )

    def timing(times: list[float]) -> dict[str, object]:
        return {
            "times": times,
            "median": float(np.median(times)),
            "p95": float(np.percentile(times, 95)),
        }

    result: dict[str, object] = {
        "schema": "opennr-vit-stage-cuda-fast-probe-v1",
        "source_rgb": str(args.rgb_png.resolve()),
        "source_weights": str(args.weights.resolve()),
        "backend": str(backend),
        "rgb_contract": [args.height, args.width, 3],
        "tokens": int(features.shape[0]),
        "blocks": len(exact_blocks),
        "dense_mode": args.dense_mode,
        "cuda_device": torch.cuda.get_device_name(0),
        "torch": torch.__version__,
        "cuda": torch.version.cuda,
        "warmup": args.warmup,
        "iterations": args.iterations,
        "include_graph": args.include_graph,
        "exact_reconstructed_ms": timing(exact_times),
        "cuda_native_approx_dense_ms": timing(full_times),
        "cuda_native_approx_partitioned_ms": timing(split_times),
        "cuda_native_approx_dense_exact_attention_ms": timing(
            full_exact_attention_times
        ),
        "cuda_native_approx_partitioned_exact_attention_ms": timing(
            split_exact_attention_times
        ),
        "speedup_exact_over_dense": float(
            np.median(exact_times) / max(float(np.median(full_times)), 1e-9)
        ),
        "speedup_exact_over_partitioned": float(
            np.median(exact_times) / max(float(np.median(split_times)), 1e-9)
        ),
        "speedup_exact_over_dense_exact_attention": float(
            np.median(exact_times)
            / max(float(np.median(full_exact_attention_times)), 1e-9)
        ),
        "speedup_exact_over_partitioned_exact_attention": float(
            np.median(exact_times)
            / max(float(np.median(split_exact_attention_times)), 1e-9)
        ),
        "final_dense": describe(full_final, exact_final),
        "final_partitioned": describe(split_final, exact_final),
        "final_dense_exact_attention": describe(
            full_exact_attention_final, exact_final
        ),
        "final_partitioned_exact_attention": describe(
            split_exact_attention_final, exact_final
        ),
        "per_block_final_mae": {
            "dense": [
                float((value.float() - reference.float()).abs().mean().item())
                for value, reference in zip(full_boundaries, exact_boundaries)
            ],
            "partitioned": [
                float((value.float() - reference.float()).abs().mean().item())
                for value, reference in zip(split_boundaries, exact_boundaries)
            ],
            "dense_exact_attention": [
                float((value.float() - reference.float()).abs().mean().item())
                for value, reference in zip(
                    full_exact_attention_boundaries, exact_boundaries
                )
            ],
            "partitioned_exact_attention": [
                float((value.float() - reference.float()).abs().mean().item())
                for value, reference in zip(
                    split_exact_attention_boundaries, exact_boundaries
                )
            ],
        },
        "scope": (
            "all eight recovered ViT blocks on one real Skyrim-derived token "
            "boundary; exact reference uses reconstructed Triton arithmetic; "
            "approximations use cuBLAS matmul and recovered BMM attention; "
            "not native NVIDIA runtime or full-network parity"
        ),
    }
    if args.include_graph:
        if graph_final is None:
            raise RuntimeError("graph output was not captured")
        result["cuda_graph_replay_ms"] = timing(graph_times)
        result["final_cuda_graph"] = describe(graph_final, exact_final)
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    return 0


def model_vit_exact(exact_blocks, features, use_arithmetic_backend):
    current = features
    with use_arithmetic_backend("triton"):
        for block in exact_blocks:
            current = block(current)
    return current


if __name__ == "__main__":
    raise SystemExit(main())
