"""Measure one recovered C1024 global-attention block with fused CUDA kernels.

The input is produced by the recovered prefix through block 30's C512->C1024
transition.  The measured block is block31, the first global 32-head block:

    1024->4096 FFN -> quadratic gate -> E4M3 -> 4096->1024 residual
    -> 32-head full-image QKV/cosine attention -> E4M3 -> output residual

The global attention kernel streams 64-key tiles twice (once for the vendor
softmax denominator and once for the value reduction) so it does not allocate
the full query-key matrix.  This is an offline backend experiment.  It does
not call the native NVIDIA DLL, modify Skyrim/MGO, or claim full-model,
temporal, stereo, or VR readiness.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import time

import numpy as np
import torch
import triton
import triton.language as tl

from probe_native_style_c32_cuda import _quadratic_gate_activation, _round_fp8_half
from probe_native_style_c32_attention_cuda import _normalize_c32, _select_row
from probe_native_style_c64_block_cuda import _approx_exp, _half_add, _half_mul


@triton.jit
def _global_ffn_expand(
    X,
    WEIGHT,
    OUT,
    rows_total: tl.constexpr,
    BM: tl.constexpr,
):
    rows = tl.program_id(0) * BM + tl.arange(0, BM)
    tile = tl.program_id(1)
    output_lane = tile * 64 + tl.arange(0, 64)
    row_mask = rows[:, None] < rows_total
    input_lane = tl.arange(0, 256)
    expanded = tl.zeros((BM, 64), dtype=tl.float32)
    # A full 1024-wide dot exceeds the available shared-memory allocation on
    # this GPU.  Four 256-wide tensor-core fragments retain one final FP16
    # boundary and keep the working tile below that limit.
    for group in tl.static_range(4):
        x = tl.load(
            X + rows[:, None] * 1024 + group * 256 + input_lane[None, :],
            mask=row_mask,
            other=0,
        )
        weight = tl.load(
            WEIGHT + (group * 256 + input_lane)[:, None] * 4096 + output_lane[None, :]
        )
        expanded += tl.dot(x, weight, out_dtype=tl.float32)
    expanded = expanded.to(tl.float16)
    activated = _quadratic_gate_activation(expanded)
    tl.store(
        OUT + rows[:, None] * 4096 + output_lane[None, :],
        _round_fp8_half(activated),
        mask=row_mask,
    )


@triton.jit
def _global_ffn_project_residual(
    X,
    HIDDEN,
    WEIGHT,
    COSINE,
    OUT,
    rows_total: tl.constexpr,
    BM: tl.constexpr,
):
    rows = tl.program_id(0) * BM + tl.arange(0, BM)
    tile = tl.program_id(1)
    output_lane = tile * 64 + tl.arange(0, 64)
    hidden_lane = tl.arange(0, 256)
    row_mask = rows[:, None] < rows_total
    x = tl.load(
        X + rows[:, None] * 1024 + output_lane[None, :],
        mask=row_mask,
        other=0,
    )
    projected = tl.zeros((BM, 64), dtype=tl.float32)
    # Split the 4096-wide reduction into 16 natural 256-wide fragments.  This
    # keeps the weight tile and register footprint below the C256-style resource
    # wall while retaining the reference's single final FP16 boundary.
    for group in tl.static_range(16):
        hidden = tl.load(
            HIDDEN + rows[:, None] * 4096 + group * 256 + hidden_lane[None, :],
            mask=row_mask,
            other=0,
        )
        weight = tl.load(
            WEIGHT + (group * 256 + hidden_lane)[:, None] * 1024 + output_lane[None, :]
        )
        projected += tl.dot(hidden, weight, out_dtype=tl.float32)
    cosine = tl.load(COSINE + output_lane)
    result = _half_add(
        projected.to(tl.float16),
        _half_mul(x, cosine[None, :]),
    )
    tl.store(
        OUT + rows[:, None] * 1024 + output_lane[None, :],
        result,
        mask=row_mask,
    )


@triton.jit
def _global_qkv_projection(
    X,
    WEIGHT,
    SCALE,
    Q,
    K,
    V,
    rows_total: tl.constexpr,
    BM: tl.constexpr,
):
    rows = tl.program_id(0) * BM + tl.arange(0, BM)
    head = tl.program_id(1)
    lane = tl.arange(0, 32)
    row_mask = rows[:, None] < rows_total
    output_offset = head * 32
    input_lane = tl.arange(0, 256)
    q_acc = tl.zeros((BM, 32), dtype=tl.float32)
    k_acc = tl.zeros((BM, 32), dtype=tl.float32)
    v_acc = tl.zeros((BM, 32), dtype=tl.float32)
    for group in tl.static_range(4):
        x = tl.load(
            X + rows[:, None] * 1024 + group * 256 + input_lane[None, :],
            mask=row_mask,
            other=0,
        )
        q_weight = tl.load(
            WEIGHT
            + (group * 256 + input_lane)[:, None] * 3072
            + output_offset
            + lane[None, :]
        )
        k_weight = tl.load(
            WEIGHT
            + (group * 256 + input_lane)[:, None] * 3072
            + 1024
            + output_offset
            + lane[None, :]
        )
        v_weight = tl.load(
            WEIGHT
            + (group * 256 + input_lane)[:, None] * 3072
            + 2048
            + output_offset
            + lane[None, :]
        )
        q_acc += tl.dot(x, q_weight, out_dtype=tl.float32)
        k_acc += tl.dot(x, k_weight, out_dtype=tl.float32)
        v_acc += tl.dot(x, v_weight, out_dtype=tl.float32)
    q = _normalize_c32(
        q_acc.to(tl.float16),
        BM,
        0.00006198883056640625,
    )
    k = _normalize_c32(
        k_acc.to(tl.float16),
        BM,
        0.00006198883056640625,
    )
    v = v_acc.to(tl.float16)
    # The recovered scale vector is one scalar per attention head, not one
    # scalar per channel within a head.
    scale = tl.load(SCALE + head)
    q = _half_mul(q, scale)
    tl.store(
        Q + rows[:, None] * 1024 + output_offset + lane[None, :],
        _round_fp8_half(q),
        mask=row_mask,
    )
    tl.store(
        K + rows[:, None] * 1024 + output_offset + lane[None, :],
        _round_fp8_half(k),
        mask=row_mask,
    )
    tl.store(
        V + rows[:, None] * 1024 + output_offset + lane[None, :],
        _round_fp8_half(v),
        mask=row_mask,
    )


@triton.jit
def _global_attention_streaming(
    Q,
    K,
    V,
    ATTENDED,
    TOKENS: tl.constexpr,
    PADDED_TOKENS: tl.constexpr,
    BM: tl.constexpr,
):
    """Compute full-image attention without materializing scores/probabilities."""

    rows = tl.program_id(0) * BM + tl.arange(0, BM)
    head = tl.program_id(1)
    lane = tl.arange(0, 32)
    row_mask = rows < TOKENS
    q = tl.load(
        Q + rows[:, None] * 1024 + head * 32 + lane[None, :],
        mask=row_mask[:, None],
        other=0,
    )

    denominator = tl.zeros((BM,), dtype=tl.float32)
    for key_start in tl.range(0, PADDED_TOKENS, 64):
        key_index = key_start + tl.arange(0, 64)
        key_mask = key_index < TOKENS
        k = tl.load(
            K + key_index[None, :] * 1024 + head * 32 + lane[:, None],
            mask=key_mask[None, :],
            other=0,
        )
        scores = tl.dot(q, k, out_dtype=tl.float32).to(tl.float16)
        scores = tl.minimum(tl.maximum(scores, -3.0), 3.0)
        weights = _approx_exp(scores, BM)
        weights = tl.where(key_mask[None, :], weights, 0)
        tile_sum = tl.sum(weights.to(tl.float32), axis=1)
        denominator += tile_sum

    reciprocal = (1.0 / denominator.to(tl.float32)).to(tl.float16)
    attended = tl.zeros((BM, 32), dtype=tl.float32)
    for key_start in tl.range(0, PADDED_TOKENS, 64):
        key_index = key_start + tl.arange(0, 64)
        key_mask = key_index < TOKENS
        k = tl.load(
            K + key_index[None, :] * 1024 + head * 32 + lane[:, None],
            mask=key_mask[None, :],
            other=0,
        )
        v = tl.load(
            V + key_index[:, None] * 1024 + head * 32 + lane[None, :],
            mask=key_mask[:, None],
            other=0,
        )
        scores = tl.dot(q, k, out_dtype=tl.float32).to(tl.float16)
        scores = tl.minimum(tl.maximum(scores, -3.0), 3.0)
        weights = _approx_exp(scores, BM)
        weights = tl.where(key_mask[None, :], weights, 0)
        probabilities = _round_fp8_half(_half_mul(weights, reciprocal[:, None]))
        attended += tl.dot(probabilities, v, out_dtype=tl.float32)

    tl.store(
        ATTENDED + rows[:, None] * 1024 + head * 32 + lane[None, :],
        _round_fp8_half(attended.to(tl.float16)),
        mask=row_mask[:, None],
    )


@triton.jit
def _global_attention_projection_residual(
    X,
    ATTENDED,
    PROJECTION,
    COSINE,
    OUT,
    rows_total: tl.constexpr,
    BM: tl.constexpr,
):
    rows = tl.program_id(0) * BM + tl.arange(0, BM)
    tile = tl.program_id(1)
    output_lane = tile * 64 + tl.arange(0, 64)
    input_lane = tl.arange(0, 256)
    row_mask = rows[:, None] < rows_total
    x = tl.load(
        X + rows[:, None] * 1024 + output_lane[None, :],
        mask=row_mask,
        other=0,
    )
    projected = tl.zeros((BM, 64), dtype=tl.float32)
    # A 1024-wide projection split into four 256-wide tensor-core fragments.
    # This keeps the working tile below the shared-memory limit while reducing
    # the number of FP32 accumulation groups relative to a 16x64 split.
    for group in tl.static_range(4):
        attended = tl.load(
            ATTENDED + rows[:, None] * 1024 + group * 256 + input_lane[None, :],
            mask=row_mask,
            other=0,
        )
        weight = tl.load(
            PROJECTION + (group * 256 + input_lane)[:, None] * 1024 + output_lane[None, :]
        )
        projected += tl.dot(attended, weight, out_dtype=tl.float32)
    cosine = tl.load(COSINE + output_lane)
    result = _half_add(
        projected.to(tl.float16),
        _half_mul(x, cosine[None, :]),
    )
    tl.store(
        OUT + rows[:, None] * 1024 + output_lane[None, :],
        _round_fp8_half(result),
        mask=row_mask,
    )


def _event_time(callback) -> float:
    start = torch.cuda.Event(enable_timing=True)
    end = torch.cuda.Event(enable_timing=True)
    start.record()
    callback()
    end.record()
    end.synchronize()
    return float(start.elapsed_time(end))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--weights", type=Path, required=True)
    parser.add_argument("--mlx-python", type=Path, required=True)
    parser.add_argument("--split", choices=("train", "validation", "test"), default="test")
    parser.add_argument("--sequence-id", default="seq-1789071762719-5")
    parser.add_argument("--frame", type=int, default=13)
    parser.add_argument("--eye", type=int, choices=(0, 1), default=0)
    parser.add_argument("--probe-height", type=int, default=0, help="Optional top-left global height; 0 means full stage")
    parser.add_argument("--probe-width", type=int, default=0, help="Optional top-left global width; 0 means full stage")
    parser.add_argument("--block-m", type=int, choices=(8, 16, 32), default=16)
    parser.add_argument("--attention-block-m", type=int, choices=(8, 16, 32), default=16)
    parser.add_argument("--warmup", type=int, default=1)
    parser.add_argument("--iterations", type=int, default=2)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is required")
    if args.warmup < 0 or args.iterations <= 0:
        raise ValueError("iterations must be positive; warmup must be nonnegative")

    mlx_python = args.mlx_python.expanduser().resolve()
    if str(mlx_python) not in sys.path:
        sys.path.insert(0, str(mlx_python))
    tools_dir = Path(__file__).resolve().parent
    if str(tools_dir) not in sys.path:
        sys.path.insert(0, str(tools_dir))

    from mlxdlss import NeuralRenderingPipeline
    from mlxdlss import model as recovered_model
    from mlxdlss.pipeline import load_weights
    from profile_whitebox_runtime import read_rgba_raw

    cache = args.cache.expanduser().resolve()
    rows = json.loads((cache / "rows.json").read_text(encoding="utf-8"))
    row = _select_row(rows, args.split, args.sequence_id, args.frame, args.eye)
    source_width, source_height = int(row["color_size"][0]), int(row["color_size"][1])
    source = read_rgba_raw(Path(row["raw_paths"]["input"]), source_width, source_height)
    weights = load_weights(args.weights.expanduser().resolve())

    preparation_pipeline = NeuralRenderingPipeline(weights, device="cpu", precision="reference")
    prepared = preparation_pipeline.prepare(
        source,
        profile="standard",
        processing_scale=1.0,
        frame_index=0,
        local_tone_strength=1.0,
        local_structure_strength=1.0,
    )

    # Run the genuine recovered prefix through the C1024 input of block31.
    prefix_model = recovered_model.NeuralRenderingModel(weights).eval().to(torch.float16).to("cuda")
    input_tensor = torch.from_numpy(np.ascontiguousarray(prepared.features)).to("cuda", torch.float16).unsqueeze(0)
    with torch.inference_mode():
        value = input_tensor @ prefix_model.weight("block0.layer0.input_adapter_weight")
        block0 = prefix_model._window(value, 0, head_count=1)
        value = recovered_model.e4m3_round_trip(recovered_model.average_pool2(block0))
        del block0
        for index in range(1, 4):
            value = prefix_model._window(value, index, head_count=1)
        value = prefix_model._downsample_window(value, 4, head_count=1)
        for index in range(5, 8):
            value = prefix_model._window(value, index, head_count=2)
        value = prefix_model._downsample_window(value, 8, head_count=2)
        for index in range(9, 14):
            value = prefix_model._window(value, index, head_count=4)
        value = prefix_model._downsample_window(value, 14, head_count=4)
        for index in range(15, 22):
            value = prefix_model._window(value, index, head_count=8)
        value = prefix_model._downsample_window(value, 22, head_count=8)
        for index in range(23, 31):
            value = prefix_model._split_window(value, index)
        value = recovered_model.pad_spatial_end(value, 8)
        value = recovered_model.e4m3_round_trip(
            recovered_model.average_pool2(value)
            @ prefix_model.weight("block30.layer4.weight")
        )
        c1024_full = value[0].contiguous()
    del input_tensor, value, prefix_model
    torch.cuda.synchronize()

    full_stage_height = int(c1024_full.shape[0])
    full_stage_width = int(c1024_full.shape[1])
    logical_height = args.probe_height or full_stage_height
    logical_width = args.probe_width or full_stage_width
    if logical_height <= 0 or logical_width <= 0:
        raise ValueError("global probe dimensions must be positive")
    if logical_height > full_stage_height or logical_width > full_stage_width:
        raise ValueError("global probe dimensions exceed the recovered stage")
    features = c1024_full[:logical_height, :logical_width].contiguous()
    del c1024_full
    rows_total = logical_height * logical_width
    padded_tokens = triton.cdiv(rows_total, 64) * 64
    value = features.reshape(rows_total, 1024)

    expand_weight = weights["block31.layer0.weight"].to("cuda", torch.float16).contiguous()
    ffn_projection = weights["block31.layer1.weight"].to("cuda", torch.float16).contiguous()
    ffn_cosine = weights["block31.layer1.ffn_cos_skip"].to("cuda", torch.float16).contiguous()
    qkv_weight = weights["block31.layer2.qkv_weight"].to("cuda", torch.float16).contiguous()
    attention_scale = (
        weights["block31.layer2.attn_scale"].to("cuda", torch.float32) * np.sqrt(32.0)
    ).to(torch.float16).contiguous()
    attention_projection = weights["block31.layer4.projection_weight"].to("cuda", torch.float16).contiguous()
    attention_cosine = weights["block31.layer4.attn_cos_skip"].to("cuda", torch.float16).contiguous()

    hidden = torch.empty((rows_total, 4096), device="cuda", dtype=torch.float16)
    fused_ffn = torch.empty_like(value)
    q = torch.empty_like(value)
    k = torch.empty_like(value)
    v = torch.empty_like(value)
    attended = torch.empty_like(value)
    fused_output = torch.empty_like(value)

    def launch_ffn() -> None:
        _global_ffn_expand[(triton.cdiv(rows_total, args.block_m), 64)](
            value,
            expand_weight,
            hidden,
            rows_total,
            args.block_m,
            num_warps=4,
            num_stages=1,
            enable_fp_fusion=False,
        )
        _global_ffn_project_residual[(triton.cdiv(rows_total, args.block_m), 16)](
            value,
            hidden,
            ffn_projection,
            ffn_cosine,
            fused_ffn,
            rows_total,
            args.block_m,
            num_warps=4,
            num_stages=1,
            enable_fp_fusion=False,
        )

    def launch_attention() -> None:
        _global_qkv_projection[(triton.cdiv(rows_total, 16), 32)](
            fused_ffn,
            qkv_weight,
            attention_scale,
            q,
            k,
            v,
            rows_total,
            16,
            num_warps=4,
            num_stages=1,
            enable_fp_fusion=False,
        )
        _global_attention_streaming[(triton.cdiv(rows_total, args.attention_block_m), 32)](
            q,
            k,
            v,
            attended,
            rows_total,
            padded_tokens,
            args.attention_block_m,
            num_warps=4,
            num_stages=1,
            enable_fp_fusion=False,
        )
        _global_attention_projection_residual[(triton.cdiv(rows_total, 16), 16)](
            fused_ffn,
            attended,
            attention_projection,
            attention_cosine,
            fused_output,
            rows_total,
            16,
            num_warps=4,
            num_stages=1,
            enable_fp_fusion=False,
        )

    def launch_block() -> None:
        launch_ffn()
        launch_attention()

    compile_started = time.perf_counter()
    launch_block()
    torch.cuda.synchronize()
    compile_seconds = time.perf_counter() - compile_started
    for _ in range(args.warmup):
        launch_block()
    torch.cuda.synchronize()
    fused_block_times = [_event_time(launch_block) for _ in range(args.iterations)]
    fused_ffn_times = [_event_time(launch_ffn) for _ in range(args.iterations)]
    fused_attention_times = [_event_time(launch_attention) for _ in range(args.iterations)]

    original_round_trip = recovered_model.e4m3_round_trip

    def direct_fp8(value_tensor):
        return value_tensor.clamp(-448.0, 448.0).to(torch.float8_e4m3fn).to(value_tensor.dtype)

    def eager_block():
        value_image = value.reshape(1, logical_height, logical_width, 1024)
        output = recovered_model.global_block(
            value_image,
            expansion_weight=expand_weight,
            feed_forward_projection_weight=ffn_projection,
            feed_forward_cosine=ffn_cosine,
            qkv_weight=qkv_weight,
            attention_scale=weights["block31.layer2.attn_scale"].to("cuda", torch.float32),
            attention_projection_weight=attention_projection,
            attention_cosine=attention_cosine,
            head_count=32,
            logit_cap=3.0,
        )
        return recovered_model.e4m3_round_trip(output).reshape(rows_total, 1024)

    def drift_summary(left: torch.Tensor, right: torch.Tensor) -> dict[str, float]:
        drift = (left.float() - right.float()).abs()
        return {
            "mae": float(drift.mean().item()),
            "max": float(drift.max().item()),
            "changed_fraction_gt_1e-3": float((drift > 0.001).float().mean().item()),
        }

    intermediate_drift: dict[str, dict[str, float]] = {}
    recovered_model.e4m3_round_trip = direct_fp8
    try:
        for _ in range(args.warmup):
            eager_block()
        torch.cuda.synchronize()
        eager_times = [_event_time(eager_block) for _ in range(args.iterations)]
        eager_output = eager_block().contiguous()
        torch.cuda.synchronize()

        # Reconstruct the direct control's published intermediates so a large
        # final error can be attributed to the FFN, Q/K/V publication, global
        # softmax/value reduction, or the final projection rather than guessed
        # from the end-to-end number alone.
        value_image = value.reshape(1, logical_height, logical_width, 1024)
        tokens = value_image.reshape(1, rows_total, 1024)
        hidden_reference = direct_fp8(
            recovered_model.quadratic_gate_activation(tokens @ expand_weight)
        )
        ffn_reference = (
            hidden_reference @ ffn_projection
            + tokens * ffn_cosine.reshape(1, 1, 1024)
        )
        projected_reference = ffn_reference @ qkv_weight
        query_reference, key_reference, value_reference = projected_reference.chunk(3, dim=-1)
        query_reference = recovered_model.vendor_cosine_publish(
            query_reference.reshape(1, rows_total, 32, 32).permute(0, 2, 1, 3),
            attention_scale,
        )
        key_reference = recovered_model.vendor_cosine_publish(
            key_reference.reshape(1, rows_total, 32, 32).permute(0, 2, 1, 3)
        )
        value_reference = direct_fp8(
            value_reference.reshape(1, rows_total, 32, 32).permute(0, 2, 1, 3)
        )
        score_reference = torch.matmul(
            query_reference,
            key_reference.transpose(-2, -1),
        ).clamp(-3.0, 3.0)
        probability_reference = recovered_model.vendor_approximate_softmax(score_reference)
        attended_reference = direct_fp8(
            torch.matmul(probability_reference, value_reference)
            .permute(0, 2, 1, 3)
            .reshape(1, rows_total, 1024)
        )
        query_reference_rows = query_reference.permute(0, 2, 1, 3).reshape(rows_total, 1024).contiguous()
        key_reference_rows = key_reference.permute(0, 2, 1, 3).reshape(rows_total, 1024).contiguous()
        value_reference_rows = value_reference.permute(0, 2, 1, 3).reshape(rows_total, 1024).contiguous()
        streaming_reference = torch.empty_like(attended)
        _global_attention_streaming[(triton.cdiv(rows_total, args.attention_block_m), 32)](
            query_reference_rows,
            key_reference_rows,
            value_reference_rows,
            streaming_reference,
            rows_total,
            padded_tokens,
            args.attention_block_m,
            num_warps=4,
            num_stages=1,
            enable_fp_fusion=False,
        )
        torch.cuda.synchronize()
        projection_reference = torch.empty_like(fused_output)
        _global_attention_projection_residual[(triton.cdiv(rows_total, 16), 16)](
            ffn_reference.reshape(rows_total, 1024),
            attended_reference.reshape(rows_total, 1024),
            attention_projection,
            attention_cosine,
            projection_reference,
            rows_total,
            16,
            num_warps=4,
            num_stages=1,
            enable_fp_fusion=False,
        )
        torch.cuda.synchronize()
        intermediate_drift = {
            "ffn_output": drift_summary(fused_ffn, ffn_reference.reshape(rows_total, 1024)),
            "q_publication": drift_summary(
                q,
                query_reference_rows,
            ),
            "k_publication": drift_summary(
                k,
                key_reference_rows,
            ),
            "v_publication": drift_summary(
                v,
                value_reference_rows,
            ),
            "attended_publication": drift_summary(
                attended,
                attended_reference.reshape(rows_total, 1024),
            ),
            "streaming_attention_with_reference_qkv": drift_summary(
                streaming_reference,
                attended_reference.reshape(rows_total, 1024),
            ),
            "projection_kernel_with_reference_intermediates": drift_summary(
                projection_reference,
                eager_output,
            ),
            "fused_output_vs_reference_intermediates": drift_summary(
                fused_output,
                projection_reference,
            ),
        }
    finally:
        recovered_model.e4m3_round_trip = original_round_trip

    difference = (fused_output.float() - eager_output.float()).abs()
    percentile_sample = difference.reshape(-1)[::max(1, difference.numel() // 1_000_000)]
    args.output.expanduser().resolve().mkdir(parents=True, exist_ok=True)
    result = {
        "schema": "opennr-native-style-global-block-cuda-probe-v1",
        "scope": "recovered block31 C1024 global 32-head attention block; offline only",
        "promotion": False,
        "training_started": False,
        "new_capture_started": False,
        "row": {
            "split": row["split"],
            "sequence_id": row["sequence_id"],
            "frame": row["frame_id"],
            "eye": row["eye"],
            "source": row["raw_paths"]["input"],
        },
        "prefix": {
            "recovered_stages": "block0 -> average_pool2 -> blocks1-3 -> block4 downsample -> blocks5-7 -> block8 downsample -> blocks9-13 -> block14 downsample -> blocks15-21 -> block22 downsample -> blocks23-30 -> block30 C512->C1024 downsample",
            "input_resolution": [source_width, source_height],
        },
        "input": {
            "stage": "block31 C1024 global",
            "probe_resolution": [logical_width, logical_height],
            "full_stage_resolution": [full_stage_width, full_stage_height],
            "probe_region": "full_global_stage" if (logical_height == full_stage_height and logical_width == full_stage_width) else "top_left",
            "tokens": int(rows_total),
            "attention_key_tokens_padded": int(padded_tokens),
            "channels": 1024,
            "heads": 32,
            "head_channels": 32,
        },
        "kernel": {
            "block": "block31",
            "operation": "C1024->4096 fused FFN + 32-head streaming global attention + output residual",
            "block_m": args.block_m,
            "attention_block_m": args.attention_block_m,
            "attention_key_tile": 64,
            "attention_mode": "two-pass streaming softmax/value reduction",
            "warps": 4,
            "stages": 1,
            "triton": triton.__version__,
        },
        "timing_ms": {
            "compile_and_first_run": compile_seconds * 1000.0,
            "fused_block_median": float(np.median(fused_block_times)),
            "fused_block_p95": float(np.percentile(fused_block_times, 95)),
            "fused_block_samples": [float(value) for value in fused_block_times],
            "fused_ffn_median": float(np.median(fused_ffn_times)),
            "fused_attention_median": float(np.median(fused_attention_times)),
            "eager_block_median": float(np.median(eager_times)),
            "eager_block_p95": float(np.percentile(eager_times, 95)),
            "eager_block_samples": [float(value) for value in eager_times],
        },
        "speedup": float(np.median(eager_times) / np.median(fused_block_times)),
        "drift_vs_eager_direct_fp8": {
            "mae": float(difference.mean().item()),
            "p99_sample": float(torch.quantile(percentile_sample, 0.99).item()),
            "p999_sample": float(torch.quantile(percentile_sample, 0.999).item()),
            "max": float(difference.max().item()),
            "changed_fraction_gt_1e-3": float((difference > 0.001).float().mean().item()),
        },
        "intermediate_drift_vs_eager_direct_fp8": intermediate_drift,
        "memory": {
            "peak_allocated_bytes": int(torch.cuda.max_memory_allocated()),
            "peak_reserved_bytes": int(torch.cuda.max_memory_reserved()),
        },
        "environment": {
            "gpu": torch.cuda.get_device_name(0),
            "torch": torch.__version__,
            "cuda": torch.version.cuda,
            "python": sys.version,
        },
        "interpretation": "One global-block backend proof only; not the NVIDIA DLL, full 71-block timing, exact native parity, temporal/stereo validation, or VR readiness.",
    }
    (args.output.expanduser().resolve() / "result.json").write_text(
        json.dumps(result, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
