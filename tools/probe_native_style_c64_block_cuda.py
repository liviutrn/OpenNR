"""Measure one recovered pooled C64 window block with fused CUDA kernels.

The input is produced by the recovered model's real block0 -> block4 prefix,
then block5 is evaluated twice:

    local C64 branched FFN -> two-head QKV/window attention -> residual

This is an offline backend experiment.  It does not call the native NVIDIA
DLL, modify Skyrim/MGO, or claim full-model, temporal, stereo, or VR readiness.
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

from probe_native_style_c32_cuda import (
    _quadratic_gate_activation,
    _reference_block,
    _round_fp8_half,
)
from probe_native_style_c32_attention_cuda import _normalize_c32, _select_row


@triton.jit
def _half_mul(left, right):
    return (left.to(tl.float32) * right.to(tl.float32)).to(tl.float16)


@triton.jit
def _half_add(left, right):
    return (left.to(tl.float32) + right.to(tl.float32)).to(tl.float16)


@triton.jit
def _fused_c64_branched_mlp(
    X,
    EXPAND,
    BRANCH,
    OUTPUT,
    COSINE,
    OUT,
    rows_total: tl.constexpr,
    BM: tl.constexpr,
):
    rows = tl.program_id(0) * BM + tl.arange(0, BM)
    lane = tl.arange(0, 32)
    mask = rows[:, None] < rows_total
    x0 = tl.load(X + rows[:, None] * 64 + lane[None, :], mask=mask, other=0)
    x1 = tl.load(X + rows[:, None] * 64 + 32 + lane[None, :], mask=mask, other=0)

    # The recovered reference exposes a half result after each input-head
    # matmul and after each branch sum.  Keep those boundaries explicit here;
    # carrying the whole branch tree in FP32 is faster-looking but changes the
    # nonlinear input enough to make the C64 block fail its parity check.
    group0 = tl.full((BM, 32), 0.0, tl.float16)
    group1 = tl.full((BM, 32), 0.0, tl.float16)
    for output_group in tl.static_range(2):
        group_sum = tl.full((BM, 32), 0.0, tl.float16)
        for branch_index in tl.static_range(4):
            expanded = tl.full((BM, 32), 0.0, tl.float16)
            for input_group in tl.static_range(2):
                source = tl.where(input_group == 0, x0, x1)
                expand_offset = (((output_group * 4 + branch_index) * 2 + input_group) * 32)
                expand_weight = tl.load(
                    EXPAND + expand_offset * 32 + lane[:, None] * 32 + lane[None, :]
                )
                expanded = _half_add(
                    expanded,
                    tl.dot(source, expand_weight, out_dtype=tl.float32).to(tl.float16),
                )
            activated = _round_fp8_half(_quadratic_gate_activation(expanded))
            branch_offset = (output_group * 4 + branch_index) * 32
            branch_weight = tl.load(
                BRANCH + branch_offset * 32 + lane[:, None] * 32 + lane[None, :]
            )
            group_sum = _half_add(
                group_sum,
                tl.dot(activated, branch_weight, out_dtype=tl.float32).to(tl.float16),
            )
        group_value = _round_fp8_half(group_sum)
        if output_group == 0:
            group0 = group_value
        else:
            group1 = group_value

    output_lane = tl.arange(0, 64)
    output_weight = tl.load(OUTPUT + output_lane[:, None] * 64 + output_lane[None, :])
    groups = tl.reshape(
        tl.permute(tl.join(group0, group1), (0, 2, 1)),
        (BM, 64),
    )
    # This is one C64 -> C64 projection, matching the recovered graph.  The
    # earlier two C32 projections changed the reduction order and obscured the
    # actual parity of the branch tree.
    projected = tl.dot(groups, output_weight, out_dtype=tl.float32)
    x_full = tl.load(X + rows[:, None] * 64 + output_lane[None, :], mask=mask, other=0)
    cosine = tl.load(COSINE + output_lane)
    residual = _half_add(projected.to(tl.float16), _half_mul(
        x_full, cosine[None, :]
    ))
    tl.store(OUT + rows[:, None] * 64 + output_lane[None, :], _round_fp8_half(residual), mask=mask)


@triton.jit
def _project_c64_qkv(
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
    input_lane = tl.arange(0, 64)
    lane = tl.arange(0, 32)
    mask = rows[:, None] < rows_total
    x = tl.load(X + rows[:, None] * 64 + input_lane[None, :], mask=mask, other=0)
    for head in tl.static_range(2):
        output_offset = head * 32
        q_weight = tl.load(WEIGHT + input_lane[:, None] * 192 + output_offset + lane[None, :])
        k_weight = tl.load(WEIGHT + input_lane[:, None] * 192 + 64 + output_offset + lane[None, :])
        v_weight = tl.load(WEIGHT + input_lane[:, None] * 192 + 128 + output_offset + lane[None, :])
        q = _normalize_c32(
            tl.dot(x, q_weight, out_dtype=tl.float32).to(tl.float16),
            BM,
            0.00006198883056640625,
        )
        k = _normalize_c32(
            tl.dot(x, k_weight, out_dtype=tl.float32).to(tl.float16),
            BM,
            0.00006198883056640625,
        )
        v = tl.dot(x, v_weight, out_dtype=tl.float32).to(tl.float16)
        scale = tl.load(SCALE + head)
        q = _half_mul(q, scale)
        tl.store(Q + rows[:, None] * 64 + output_offset + lane[None, :], _round_fp8_half(q), mask=mask)
        tl.store(K + rows[:, None] * 64 + output_offset + lane[None, :], _round_fp8_half(k), mask=mask)
        tl.store(V + rows[:, None] * 64 + output_offset + lane[None, :], _round_fp8_half(v), mask=mask)


@triton.jit
def _approx_exp(value, BM: tl.constexpr):
    """Apply the recovered two-half packed affine exponential exactly.

    The reference forms pairs of half bit patterns, shifts the packed 32-bit
    value, and adds one 32-bit constant.  Doing the transform independently
    per half loses the carry from the low half into the high half; that was the
    source of the large attention-tail error in the first C64 probe.
    """
    pair = tl.arange(0, 32)
    even = tl.gather(value, tl.broadcast_to((pair * 2)[None, :], (BM, 32)), 1)
    odd = tl.gather(value, tl.broadcast_to((pair * 2 + 1)[None, :], (BM, 32)), 1)

    even_affine = (even.to(tl.float32) * 0.044921875 + 1.30078125).to(tl.float16)
    odd_affine = (odd.to(tl.float32) * 0.044921875 + 1.30078125).to(tl.float16)
    even_affine = tl.minimum(
        tl.maximum(even_affine.to(tl.float32), 1.03125), 1.5693359375
    ).to(tl.float16)
    odd_affine = tl.minimum(
        tl.maximum(odd_affine.to(tl.float32), 1.03125), 1.5693359375
    ).to(tl.float16)
    even_bits = even_affine.to(tl.uint16, bitcast=True).to(tl.int32)
    odd_bits = odd_affine.to(tl.uint16, bitcast=True).to(tl.int32)
    packed = even_bits | (odd_bits << 16)
    transformed = (packed << 5) + 0x7FF88000
    low_bits = (transformed & 0xFFFF).to(tl.uint16)
    high_bits = ((transformed >> 16) & 0xFFFF).to(tl.uint16)
    columns = tl.arange(0, 64)
    pair_index = columns // 2
    low = tl.gather(low_bits, tl.broadcast_to(pair_index[None, :], (BM, 64)), 1)
    high = tl.gather(high_bits, tl.broadcast_to(pair_index[None, :], (BM, 64)), 1)
    result_bits = tl.where((columns[None, :] & 1) == 0, low, high)
    return result_bits.to(tl.float16, bitcast=True)


@triton.jit
def _attention_c64_windows(
    Q,
    K,
    V,
    X,
    BIAS,
    PROJECTION,
    COSINE,
    OUT,
    WIDTH: tl.constexpr,
    COLUMNS: tl.constexpr,
    BM: tl.constexpr,
    TILES: tl.constexpr,
):
    program = tl.program_id(0)
    tile = program % TILES
    window = program // TILES
    local_row = tile * BM + tl.arange(0, BM)
    local_key = tl.arange(0, 64)
    lane = tl.arange(0, 32)
    output_lane = tl.arange(0, 64)
    row_mask = local_row < 64

    window_row = window // COLUMNS
    window_col = window % COLUMNS
    row_y = window_row * 8 + local_row // 8
    row_x = window_col * 8 + local_row % 8
    key_y = window_row * 8 + local_key // 8
    key_x = window_col * 8 + local_key % 8
    row_index = row_y * WIDTH + row_x
    key_index = key_y * WIDTH + key_x

    q0 = tl.load(Q + row_index[:, None] * 64 + lane[None, :], mask=row_mask[:, None], other=0)
    q1 = tl.load(Q + row_index[:, None] * 64 + 32 + lane[None, :], mask=row_mask[:, None], other=0)
    k0 = tl.load(K + key_index[None, :] * 64 + lane[:, None])
    k1 = tl.load(K + key_index[None, :] * 64 + 32 + lane[:, None])
    v0 = tl.load(V + key_index[:, None] * 64 + lane[None, :])
    v1 = tl.load(V + key_index[:, None] * 64 + 32 + lane[None, :])
    bias0 = tl.load(BIAS + local_row[:, None] * 64 + local_key[None, :], mask=row_mask[:, None], other=0)
    bias1 = tl.load(BIAS + 4096 + local_row[:, None] * 64 + local_key[None, :], mask=row_mask[:, None], other=0)

    score0 = _half_add(tl.dot(q0, k0, out_dtype=tl.float32).to(tl.float16), bias0)
    score1 = _half_add(tl.dot(q1, k1, out_dtype=tl.float32).to(tl.float16), bias1)
    weight0 = _approx_exp(score0, BM)
    weight1 = _approx_exp(score1, BM)
    denominator0 = tl.sum(weight0.to(tl.float32), axis=1).to(tl.float16)
    denominator1 = tl.sum(weight1.to(tl.float32), axis=1).to(tl.float16)
    probability0 = _round_fp8_half(_half_mul(weight0, (1.0 / denominator0.to(tl.float32)).to(tl.float16)[:, None]))
    probability1 = _round_fp8_half(_half_mul(weight1, (1.0 / denominator1.to(tl.float32)).to(tl.float16)[:, None]))
    attended0 = _round_fp8_half(tl.dot(probability0, v0, out_dtype=tl.float32).to(tl.float16))
    attended1 = _round_fp8_half(tl.dot(probability1, v1, out_dtype=tl.float32).to(tl.float16))

    projection = tl.load(PROJECTION + output_lane[:, None] * 64 + output_lane[None, :])
    attended = tl.reshape(
        tl.permute(tl.join(attended0, attended1), (0, 2, 1)),
        (BM, 64),
    )
    # Match the single C64 -> C64 projection in cosine_attention rather than
    # summing two independently reduced C32 projections.
    branch = tl.dot(attended, projection, out_dtype=tl.float32)
    x = tl.load(X + row_index[:, None] * 64 + output_lane[None, :], mask=row_mask[:, None], other=0)
    cosine = tl.load(COSINE + output_lane)
    result = _half_add(branch.to(tl.float16), _half_mul(x, cosine[None, :]))
    tl.store(OUT + row_index[:, None] * 64 + output_lane[None, :], result, mask=row_mask[:, None])


def _event_time(callback) -> float:
    start = torch.cuda.Event(enable_timing=True)
    end = torch.cuda.Event(enable_timing=True)
    start.record()
    callback()
    end.record()
    end.synchronize()
    return float(start.elapsed_time(end))


def _prepare_c64_input(source, weights, recovered_model):
    """Run the recovered prefix through block 4 and return its C64 output."""

    prefix_model = recovered_model.NeuralRenderingModel(weights).eval().to(torch.float16).to("cuda")
    tensor = torch.from_numpy(np.ascontiguousarray(source)).to("cuda", torch.float16).unsqueeze(0)
    with torch.inference_mode():
        value = tensor @ prefix_model.weight("block0.layer0.input_adapter_weight")
        block0 = prefix_model._window(value, 0, head_count=1)
        value = recovered_model.e4m3_round_trip(recovered_model.average_pool2(block0))
        for index in range(1, 4):
            value = prefix_model._window(value, index, head_count=1)
        value = prefix_model._downsample_window(value, 4, head_count=1)
    del tensor, value
    return block0, prefix_model


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--weights", type=Path, required=True)
    parser.add_argument("--mlx-python", type=Path, required=True)
    parser.add_argument("--split", choices=("train", "validation", "test"), default="test")
    parser.add_argument("--sequence-id", default="seq-1789071762719-5")
    parser.add_argument("--frame", type=int, default=13)
    parser.add_argument("--eye", type=int, choices=(0, 1), default=0)
    parser.add_argument("--probe-height", type=int, default=0, help="Optional top-left C64 height; 0 means full C64 stage")
    parser.add_argument("--probe-width", type=int, default=0, help="Optional top-left C64 width; 0 means full C64 stage")
    parser.add_argument("--mlp-block-m", type=int, choices=(16, 32, 64, 128), default=16)
    parser.add_argument("--attention-block-m", type=int, choices=(16, 32, 64), default=64)
    parser.add_argument("--chunk-rows", type=int, default=32768)
    parser.add_argument("--warmup", type=int, default=1)
    parser.add_argument("--iterations", type=int, default=3)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is required")
    if args.chunk_rows <= 0 or args.warmup < 0 or args.iterations <= 0:
        raise ValueError("chunk-rows and iterations must be positive; warmup must be nonnegative")

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

    # The prefix is a real recovered block0->block4 path.  It is intentionally
    # outside the timed region because this probe measures block5 only.
    preparation_pipeline = NeuralRenderingPipeline(weights, device="cpu", precision="reference")
    prepared = preparation_pipeline.prepare(
        source,
        profile="standard",
        processing_scale=1.0,
        frame_index=0,
        local_tone_strength=1.0,
        local_structure_strength=1.0,
    )
    prefix_model = recovered_model.NeuralRenderingModel(weights).eval().to(torch.float16).to("cuda")
    input_tensor = torch.from_numpy(np.ascontiguousarray(prepared.features)).to("cuda", torch.float16).unsqueeze(0)
    with torch.inference_mode():
        value = input_tensor @ prefix_model.weight("block0.layer0.input_adapter_weight")
        block0 = prefix_model._window(value, 0, head_count=1)
        value = recovered_model.e4m3_round_trip(recovered_model.average_pool2(block0))
        del block0
        for index in range(1, 4):
            value = prefix_model._window(value, index, head_count=1)
        c64_full = prefix_model._downsample_window(value, 4, head_count=1)[0].contiguous()
    del input_tensor, value, prefix_model
    torch.cuda.synchronize()

    height = args.probe_height or int(c64_full.shape[0])
    width = args.probe_width or int(c64_full.shape[1])
    if height <= 0 or width <= 0 or height % 8 or width % 8:
        raise ValueError("C64 probe dimensions must be positive multiples of eight")
    if height > c64_full.shape[0] or width > c64_full.shape[1]:
        raise ValueError("C64 probe dimensions exceed the recovered stage")
    features = c64_full[:height, :width].contiguous()
    del c64_full
    rows_total = height * width
    value = features.reshape(rows_total, 64)

    prefix = "block5.layer0"
    expand = weights[f"{prefix}.ffn_expand_weight"].to("cuda", torch.float16).contiguous()
    branch = weights[f"{prefix}.ffn_branch_projection_weight"].to("cuda", torch.float16).contiguous()
    output_projection = weights[f"{prefix}.ffn_output_projection_weight"].to("cuda", torch.float16).contiguous()
    ffn_cosine = weights[f"{prefix}.ffn_cos_skip"].to("cuda", torch.float16).contiguous()
    qkv_weight = weights[f"{prefix}.qkv_weight"].to("cuda", torch.float16).contiguous()
    attention_scale = weights[f"{prefix}.attn_scale"].to("cuda", torch.float32).contiguous()
    attention_bias = weights[f"{prefix}.attn_bias"].to("cuda", torch.float16).contiguous()
    attention_projection = weights[f"{prefix}.projection_weight"].to("cuda", torch.float16).contiguous()
    attention_cosine = weights[f"{prefix}.attn_cos_skip"].to("cuda", torch.float16).contiguous()

    fused_ffn = torch.empty_like(value)
    q = torch.empty_like(value)
    k = torch.empty_like(value)
    v = torch.empty_like(value)
    fused_output = torch.empty_like(value)

    def launch_mlp() -> None:
        _fused_c64_branched_mlp[(triton.cdiv(rows_total, args.mlp_block_m),)](
            value, expand, branch, output_projection, ffn_cosine, fused_ffn,
            rows_total, args.mlp_block_m, num_warps=4, num_stages=2,
            enable_fp_fusion=False,
        )

    def launch_attention() -> None:
        _project_c64_qkv[(triton.cdiv(rows_total, 32),)](
            fused_ffn, qkv_weight, attention_scale, q, k, v,
            rows_total, 32, num_warps=4, num_stages=2,
            enable_fp_fusion=False,
        )
        windows = (height // 8) * (width // 8)
        tiles = 64 // args.attention_block_m
        _attention_c64_windows[(windows * tiles,)](
            q, k, v, fused_ffn, attention_bias, attention_projection,
            attention_cosine, fused_output, width, width // 8,
            args.attention_block_m, tiles, num_warps=4, num_stages=2,
            enable_fp_fusion=False,
        )

    def launch_block() -> None:
        launch_mlp()
        launch_attention()

    compile_started = time.perf_counter()
    launch_block()
    torch.cuda.synchronize()
    compile_seconds = time.perf_counter() - compile_started
    for _ in range(args.warmup):
        launch_block()
    torch.cuda.synchronize()
    fused_block_times = [_event_time(launch_block) for _ in range(args.iterations)]
    fused_mlp_times = [_event_time(launch_mlp) for _ in range(args.iterations)]
    fused_attention_times = [_event_time(launch_attention) for _ in range(args.iterations)]

    original_round_trip = recovered_model.e4m3_round_trip

    def direct_fp8(value_tensor):
        return value_tensor.clamp(-448.0, 448.0).to(torch.float8_e4m3fn).to(value_tensor.dtype)

    recovered_model.e4m3_round_trip = direct_fp8
    try:
        with torch.inference_mode():
            eager_ffn_diagnostic = recovered_model.branched_feed_forward(
                value,
                expansion_weight=expand,
                branch_projection_weight=branch,
                output_projection_weight=output_projection,
            )
            eager_ffn_diagnostic = recovered_model.e4m3_round_trip(
                recovered_model.cosine_residual(value, eager_ffn_diagnostic, ffn_cosine)
            ).contiguous()
            eager_projected = (eager_ffn_diagnostic @ qkv_weight).contiguous()
            projected_shape = (1, rows_total, 2, 32)
            eager_q = recovered_model.vendor_cosine_publish(
                eager_projected[:, :64].reshape(projected_shape).permute(0, 2, 1, 3),
                attention_scale,
            ).permute(0, 2, 1, 3).reshape(rows_total, 64).contiguous()
            eager_k = recovered_model.vendor_cosine_publish(
                eager_projected[:, 64:128].reshape(projected_shape).permute(0, 2, 1, 3)
            ).permute(0, 2, 1, 3).reshape(rows_total, 64).contiguous()
            eager_v = recovered_model.e4m3_round_trip(
                eager_projected[:, 128:].reshape(projected_shape).permute(0, 2, 1, 3)
            ).permute(0, 2, 1, 3).reshape(rows_total, 64).contiguous()
    finally:
        recovered_model.e4m3_round_trip = original_round_trip

    ffn_difference = (fused_ffn.float() - eager_ffn_diagnostic.float()).abs()
    q_difference = (q.float() - eager_q.float()).abs()
    k_difference = (k.float() - eager_k.float()).abs()
    v_difference = (v.float() - eager_v.float()).abs()
    del eager_projected, eager_ffn_diagnostic, eager_q, eager_k, eager_v

    def eager_block():
        eager_ffn = recovered_model.branched_feed_forward(
            value,
            expansion_weight=expand,
            branch_projection_weight=branch,
            output_projection_weight=output_projection,
        )
        eager_ffn = recovered_model.e4m3_round_trip(
            recovered_model.cosine_residual(value, eager_ffn, ffn_cosine)
        )
        eager_image = eager_ffn.reshape(1, height, width, 64)
        attended = recovered_model.window_attention(
            eager_image,
            qkv_weight=qkv_weight,
            attention_scale=attention_scale,
            attention_bias=attention_bias.unsqueeze(0),
            projection_weight=attention_projection,
            head_count=2,
            window_size=8,
            window_origin=(0, 0),
        )
        return recovered_model.cosine_residual(
            eager_ffn, attended.reshape(rows_total, 64), attention_cosine
        )

    recovered_model.e4m3_round_trip = direct_fp8
    try:
        for _ in range(args.warmup):
            eager_block()
        torch.cuda.synchronize()
        eager_times = [_event_time(eager_block) for _ in range(args.iterations)]
        eager_output = eager_block().contiguous()
        torch.cuda.synchronize()
    finally:
        recovered_model.e4m3_round_trip = original_round_trip

    difference = (fused_output.float() - eager_output.float()).abs()
    percentile_sample = difference.reshape(-1)[::max(1, difference.numel() // 1_000_000)]
    args.output.expanduser().resolve().mkdir(parents=True, exist_ok=True)
    result = {
        "schema": "opennr-native-style-c64-block-cuda-probe-v1",
        "scope": "recovered block5 C64 branched MLP plus two-head QKV/window-attention/projection/residual; offline only",
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
            "recovered_stages": "block0 -> average_pool2 -> block1 -> block2 -> block3 -> block4 downsample",
            "input_resolution": [source_width, source_height],
        },
        "input": {
            "stage": "block5 C64",
            "probe_resolution": [width, height],
            "probe_region": "top_left" if (height != int((source_height + 3) // 4) or width != int((source_width + 3) // 4)) else "full_c64_stage",
            "tokens": int(rows_total),
            "window_count": int((height // 8) * (width // 8)),
            "channels": 64,
            "heads": 2,
        },
        "kernel": {
            "block": "block5.layer0",
            "operation": "C64 branched MLP + two-head QKV/normalization + 8x8 attention + projection + residual",
            "mlp_block_m": args.mlp_block_m,
            "attention_block_m": args.attention_block_m,
            "warps": 4,
            "stages": 2,
            "triton": triton.__version__,
        },
        "timing_ms": {
            "compile_and_first_run": compile_seconds * 1000.0,
            "fused_block_median": float(np.median(fused_block_times)),
            "fused_block_p95": float(np.percentile(fused_block_times, 95.0)),
            "fused_block_samples": fused_block_times,
            "fused_mlp_median": float(np.median(fused_mlp_times)),
            "fused_attention_median": float(np.median(fused_attention_times)),
            "eager_block_median": float(np.median(eager_times)),
            "eager_block_p95": float(np.percentile(eager_times, 95.0)),
            "eager_block_samples": eager_times,
        },
        "speedup": float(np.median(eager_times) / np.median(fused_block_times)),
        "drift_vs_eager_direct_fp8": {
            "mae": float(difference.mean().item()),
            "p99_sample": float(torch.quantile(percentile_sample, 0.99).item()),
            "p999_sample": float(torch.quantile(percentile_sample, 0.999).item()),
            "max": float(difference.max().item()),
            "changed_fraction_gt_1e-3": float((difference > 1e-3).float().mean().item()),
        },
        "intermediate_drift_vs_eager_direct_fp8": {
            "ffn_output_mae": float(ffn_difference.mean().item()),
            "q_publication_mae": float(q_difference.mean().item()),
            "k_publication_mae": float(k_difference.mean().item()),
            "v_publication_mae": float(v_difference.mean().item()),
        },
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
        "interpretation": "One pooled C64 block proof only; not the NVIDIA DLL, full 71-block timing, exact native parity, temporal/stereo validation, or VR readiness.",
    }
    (args.output.expanduser().resolve() / "result.json").write_text(
        json.dumps(result, indent=2), encoding="utf-8"
    )
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
