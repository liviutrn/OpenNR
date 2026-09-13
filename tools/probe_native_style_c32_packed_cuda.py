"""Compare row-major and direct-window-packed C32 attention on real data.

This is an offline CUDA backend experiment.  It independently implements the
layout idea used by the public NR-B580 research snapshot: Q/K/V are projected,
normalized, FP8-published, and written directly in 8x8-window order so the
attention kernel does not remap a row-major feature image.  It does not call
the NVIDIA DLL and does not modify Skyrim, MGO, or any packaged runtime.

The comparison is against the existing row-major Triton probe and the local
eager direct-FP8 control.  It is not native NVIDIA parity.
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
    _fused_c32_mlp,
    _quadratic_gate_activation,
    _reference_block,
    _round_fp8_half,
)
from probe_native_style_c32_attention_cuda import (
    _approx_exp,
    _fused_call,
    _normalize_c32,
    _project_qkv,
    _select_row,
)


@triton.jit
def _half_mul_packed(left, right):
    return (left.to(tl.float32) * right.to(tl.float32)).to(tl.float16)


@triton.jit
def _half_add_packed(left, right):
    return (left.to(tl.float32) + right.to(tl.float32)).to(tl.float16)


@triton.jit
def _project_qkv_window_packed(
    X,
    WEIGHT,
    SCALE,
    Q,
    K,
    V,
    WIDTH: tl.constexpr,
    COLUMNS: tl.constexpr,
    BM: tl.constexpr,
):
    """Project row-major C32 input directly into [window, 64, 32] tensors."""

    program = tl.program_id(0)
    window = program // (64 // BM)
    tile = program % (64 // BM)
    local_row = tile * BM + tl.arange(0, BM)
    channels = tl.arange(0, 32)

    window_row = window // COLUMNS
    window_col = window % COLUMNS
    row_y = window_row * 8 + local_row // 8
    row_x = window_col * 8 + local_row % 8
    row_index = row_y * WIDTH + row_x
    row_mask = local_row < 64

    x = tl.load(
        X + row_index[:, None] * 32 + channels[None, :],
        mask=row_mask[:, None],
        other=0,
    )
    output_channels = tl.arange(0, 32)
    q_weight = tl.load(WEIGHT + channels[:, None] * 96 + output_channels[None, :])
    k_weight = tl.load(WEIGHT + channels[:, None] * 96 + 32 + output_channels[None, :])
    v_weight = tl.load(WEIGHT + channels[:, None] * 96 + 64 + output_channels[None, :])

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
    scale = tl.load(SCALE)
    q = _half_mul_packed(q, scale)

    dest = window * 2048 + local_row[:, None] * 32 + channels[None, :]
    tl.store(Q + dest, _round_fp8_half(q), mask=row_mask[:, None])
    tl.store(K + dest, _round_fp8_half(k), mask=row_mask[:, None])
    tl.store(V + dest, _round_fp8_half(v), mask=row_mask[:, None])


@triton.jit
def _attention_windows_packed(
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
):
    """Read direct-window-packed Q/K/V and write the row-major residual."""

    program = tl.program_id(0)
    window = program // (64 // BM)
    tile = program % (64 // BM)
    local_row = tile * BM + tl.arange(0, BM)
    local_key = tl.arange(0, 64)
    channels = tl.arange(0, 32)
    row_mask = local_row < 64

    window_row = window // COLUMNS
    window_col = window % COLUMNS
    row_y = window_row * 8 + local_row // 8
    row_x = window_col * 8 + local_row % 8
    row_index = row_y * WIDTH + row_x

    base = window * 2048
    q = tl.load(Q + base + local_row[:, None] * 32 + channels[None, :], mask=row_mask[:, None], other=0)
    k = tl.load(K + base + local_key[None, :] * 32 + channels[:, None])
    v = tl.load(V + base + local_key[:, None] * 32 + channels[None, :])
    bias = tl.load(
        BIAS + local_row[:, None] * 64 + local_key[None, :],
        mask=row_mask[:, None],
        other=0,
    )

    scores = tl.dot(q, k, out_dtype=tl.float32).to(tl.float16)
    scores = _half_add_packed(scores, bias)
    weights = _approx_exp(scores, BM)
    denominator = tl.sum(weights.to(tl.float32), axis=1).to(tl.float16)
    reciprocal = (1.0 / denominator.to(tl.float32)).to(tl.float16)
    probabilities = _round_fp8_half(_half_mul_packed(weights, reciprocal[:, None]))
    attended = tl.dot(probabilities, v, out_dtype=tl.float32).to(tl.float16)
    attended = _round_fp8_half(attended)

    projection = tl.load(PROJECTION + channels[:, None] * 32 + channels[None, :])
    branch = tl.dot(attended, projection, out_dtype=tl.float32).to(tl.float16)
    x = tl.load(X + row_index[:, None] * 32 + channels[None, :], mask=row_mask[:, None], other=0)
    cosine = tl.load(COSINE + channels)
    result = _half_add_packed(branch, _half_mul_packed(x, cosine[None, :]))
    tl.store(OUT + row_index[:, None] * 32 + channels[None, :], result, mask=row_mask[:, None])


@triton.jit
def _fused_c32_mlp_qkv_window_packed(
    X,
    W1,
    W2,
    COSINE,
    QKV_WEIGHT,
    SCALE,
    FFN,
    Q,
    K,
    V,
    WIDTH: tl.constexpr,
    COLUMNS: tl.constexpr,
    BM: tl.constexpr,
):
    """Fuse the C32 MLP output directly into packed Q/K/V publication."""

    program = tl.program_id(0)
    window = program // (64 // BM)
    tile = program % (64 // BM)
    local_row = tile * BM + tl.arange(0, BM)
    channels = tl.arange(0, 32)
    hidden_channels = tl.arange(0, 128)
    row_mask = local_row < 64

    window_row = window // COLUMNS
    window_col = window % COLUMNS
    row_y = window_row * 8 + local_row // 8
    row_x = window_col * 8 + local_row % 8
    row_index = row_y * WIDTH + row_x

    x = tl.load(
        X + row_index[:, None] * 32 + channels[None, :],
        mask=row_mask[:, None],
        other=0,
    )
    w1 = tl.load(W1 + channels[:, None] * 128 + hidden_channels[None, :])
    expanded = tl.dot(x, w1, out_dtype=tl.float32).to(tl.float16)
    hidden = _round_fp8_half(_quadratic_gate_activation(expanded))
    w2 = tl.load(W2 + hidden_channels[:, None] * 32 + channels[None, :])
    branch = tl.dot(hidden, w2, out_dtype=tl.float32)
    cosine = tl.load(COSINE + channels)
    ffn = (branch + x.to(tl.float32) * cosine[None, :].to(tl.float32)).to(tl.float16)
    tl.store(
        FFN + row_index[:, None] * 32 + channels[None, :],
        ffn,
        mask=row_mask[:, None],
    )

    q_weight = tl.load(QKV_WEIGHT + channels[:, None] * 96 + channels[None, :])
    k_weight = tl.load(QKV_WEIGHT + channels[:, None] * 96 + 32 + channels[None, :])
    v_weight = tl.load(QKV_WEIGHT + channels[:, None] * 96 + 64 + channels[None, :])
    q = _normalize_c32(
        tl.dot(ffn, q_weight, out_dtype=tl.float32).to(tl.float16),
        BM,
        0.00006198883056640625,
    )
    k = _normalize_c32(
        tl.dot(ffn, k_weight, out_dtype=tl.float32).to(tl.float16),
        BM,
        0.00006198883056640625,
    )
    v = tl.dot(ffn, v_weight, out_dtype=tl.float32).to(tl.float16)
    scale = tl.load(SCALE)
    q = _half_mul_packed(q, scale)
    base = window * 2048
    dest = base + local_row[:, None] * 32 + channels[None, :]
    tl.store(Q + dest, _round_fp8_half(q), mask=row_mask[:, None])
    tl.store(K + dest, _round_fp8_half(k), mask=row_mask[:, None])
    tl.store(V + dest, _round_fp8_half(v), mask=row_mask[:, None])


@triton.jit
def _fused_c32_window_block(
    X,
    W1,
    W2,
    FFN_COSINE,
    QKV_WEIGHT,
    ATTN_SCALE,
    ATTN_BIAS,
    PROJECTION,
    ATTN_COSINE,
    OUT,
    WIDTH: tl.constexpr,
    COLUMNS: tl.constexpr,
):
    """Fuse one complete C32 MLP+attention window without global Q/K/V."""

    window = tl.program_id(0)
    local_row = tl.arange(0, 64)
    channels = tl.arange(0, 32)
    hidden_channels = tl.arange(0, 128)
    window_row = window // COLUMNS
    window_col = window % COLUMNS
    row_y = window_row * 8 + local_row // 8
    row_x = window_col * 8 + local_row % 8
    row_index = row_y * WIDTH + row_x

    x = tl.load(X + row_index[:, None] * 32 + channels[None, :])
    w1 = tl.load(W1 + channels[:, None] * 128 + hidden_channels[None, :])
    expanded = tl.dot(x, w1, out_dtype=tl.float32).to(tl.float16)
    hidden = _round_fp8_half(_quadratic_gate_activation(expanded))
    w2 = tl.load(W2 + hidden_channels[:, None] * 32 + channels[None, :])
    branch = tl.dot(hidden, w2, out_dtype=tl.float32)
    ffn_cosine = tl.load(FFN_COSINE + channels)
    ffn = (branch + x.to(tl.float32) * ffn_cosine[None, :].to(tl.float32)).to(tl.float16)

    q_weight = tl.load(QKV_WEIGHT + channels[:, None] * 96 + channels[None, :])
    k_weight = tl.load(QKV_WEIGHT + channels[:, None] * 96 + 32 + channels[None, :])
    v_weight = tl.load(QKV_WEIGHT + channels[:, None] * 96 + 64 + channels[None, :])
    q = _normalize_c32(
        tl.dot(ffn, q_weight, out_dtype=tl.float32).to(tl.float16),
        64,
        0.00006198883056640625,
    )
    k = _normalize_c32(
        tl.dot(ffn, k_weight, out_dtype=tl.float32).to(tl.float16),
        64,
        0.00006198883056640625,
    )
    v = tl.dot(ffn, v_weight, out_dtype=tl.float32).to(tl.float16)
    q = _half_mul_packed(q, tl.load(ATTN_SCALE))

    # Keep K in [channel,key] order so the tensor-core dot consumes the same
    # logical matrix as the packed attention probe, but do not publish Q/K/V.
    q_published = _round_fp8_half(q)
    k_for_dot = tl.trans(_round_fp8_half(k))
    v_published = _round_fp8_half(v)
    bias = tl.load(ATTN_BIAS + local_row[:, None] * 64 + local_row[None, :])
    scores = _half_add_packed(
        tl.dot(q_published, k_for_dot, out_dtype=tl.float32).to(tl.float16),
        bias,
    )
    weights = _approx_exp(scores, 64)
    denominator = tl.sum(weights.to(tl.float32), axis=1).to(tl.float16)
    probabilities = _round_fp8_half(
        _half_mul_packed(
            weights,
            (1.0 / denominator.to(tl.float32)).to(tl.float16)[:, None],
        )
    )
    attended = _round_fp8_half(
        tl.dot(probabilities, v_published, out_dtype=tl.float32).to(tl.float16)
    )
    projection = tl.load(PROJECTION + channels[:, None] * 32 + channels[None, :])
    projected = tl.dot(attended, projection, out_dtype=tl.float32).to(tl.float16)
    attention_cosine = tl.load(ATTN_COSINE + channels)
    result = _half_add_packed(
        projected,
        _half_mul_packed(ffn, attention_cosine[None, :]),
    )
    tl.store(OUT + row_index[:, None] * 32 + channels[None, :], result)


def _event_time(callback) -> float:
    start = torch.cuda.Event(enable_timing=True)
    end = torch.cuda.Event(enable_timing=True)
    start.record()
    callback()
    end.record()
    end.synchronize()
    return float(start.elapsed_time(end))


def _launch_packed_projection(q, k, v, x, weight, scale, height, width, block_m):
    del q, k, v
    _project_qkv_window_packed[(height // 8 * (width // 8) * (64 // block_m),)](
        x,
        weight,
        scale,
        _launch_packed_projection.q,
        _launch_packed_projection.k,
        _launch_packed_projection.v,
        width,
        width // 8,
        block_m,
        num_warps=4,
        num_stages=2,
        enable_fp_fusion=False,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--weights", type=Path, required=True)
    parser.add_argument("--mlx-python", type=Path, required=True)
    parser.add_argument("--split", choices=("train", "validation", "test"), default="test")
    parser.add_argument("--sequence-id", default="seq-1789071762719-5")
    parser.add_argument("--frame", type=int, default=13)
    parser.add_argument("--eye", type=int, choices=(0, 1), default=0)
    parser.add_argument("--block-m", type=int, choices=(16, 32, 64), default=64)
    parser.add_argument("--fused-block-m", type=int, choices=(16, 32, 64), default=16)
    parser.add_argument("--probe-height", type=int, default=0)
    parser.add_argument("--probe-width", type=int, default=0)
    parser.add_argument("--window-fused", action="store_true")
    parser.add_argument("--warmup", type=int, default=1)
    parser.add_argument("--iterations", type=int, default=3)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is required")
    if args.warmup < 0 or args.iterations <= 0:
        raise ValueError("warmup must be nonnegative and iterations must be positive")

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

    rows = json.loads((args.cache.expanduser().resolve() / "rows.json").read_text(encoding="utf-8"))
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
    full_features = torch.from_numpy(np.ascontiguousarray(prepared.features)).to("cuda", torch.float16)
    height = args.probe_height or int(full_features.shape[0])
    width = args.probe_width or int(full_features.shape[1])
    if height <= 0 or width <= 0 or height > full_features.shape[0] or width > full_features.shape[1]:
        raise ValueError("probe dimensions must be positive and within the prepared feature extent")
    if height % 8 or width % 8:
        raise ValueError("prepared feature dimensions must be divisible by eight")
    feature_matrix = full_features[:height, :width].contiguous().reshape(height * width, 16)

    adapter = weights["block0.layer0.input_adapter_weight"].to("cuda", torch.float16).contiguous()
    value = (feature_matrix @ adapter).contiguous()
    w1 = weights["block0.layer0.weight1"].to("cuda", torch.float16).contiguous()
    w2 = weights["block0.layer0.weight2"].to("cuda", torch.float16).contiguous()
    ffn_cosine = weights["block0.layer0.ffn_cos_skip"].to("cuda", torch.float16).contiguous()
    ffn_output = _reference_block(value, w1, w2, ffn_cosine, 32768).contiguous()

    qkv_weight = weights["block0.layer0.qkv_weight"].to("cuda", torch.float16).contiguous()
    attention_scale = weights["block0.layer0.attn_scale"].to("cuda", torch.float32).contiguous()
    logical_bias = recovered_model.recover_attention_bias_layout(
        weights["block0.layer0.attn_bias"]
    ).to("cuda", torch.float16).contiguous()
    projection = weights["block0.layer0.projection_weight"].to("cuda", torch.float16).contiguous()
    attention_cosine = weights["block0.layer0.attn_cos_skip"].to("cuda", torch.float16).contiguous()

    q = torch.empty_like(ffn_output)
    k = torch.empty_like(ffn_output)
    v = torch.empty_like(ffn_output)
    packed_q = torch.empty((height // 8 * (width // 8), 64, 32), device="cuda", dtype=torch.float16)
    packed_k = torch.empty_like(packed_q)
    packed_v = torch.empty_like(packed_q)
    packed_output = torch.empty_like(ffn_output)
    fused_mlp_qkv_ffn = torch.empty_like(ffn_output)
    fused_mlp_qkv_output = torch.empty_like(ffn_output)
    fused_mlp_qkv_q = torch.empty_like(packed_q)
    fused_mlp_qkv_k = torch.empty_like(packed_q)
    fused_mlp_qkv_v = torch.empty_like(packed_q)
    window_fused_output = torch.empty_like(ffn_output)
    _launch_packed_projection.q = packed_q
    _launch_packed_projection.k = packed_k
    _launch_packed_projection.v = packed_v

    def launch_row_major() -> None:
        _project_qkv[(triton.cdiv(height * width, 32),)](
            ffn_output,
            qkv_weight,
            attention_scale,
            q,
            k,
            v,
            height * width,
            32,
            num_warps=4,
            num_stages=2,
            enable_fp_fusion=False,
        )
        _fused_call(
            q,
            k,
            v,
            ffn_output,
            logical_bias[0],
            projection,
            attention_cosine,
            packed_output,
            height,
            width,
            args.block_m,
        )

    def launch_packed() -> None:
        _project_qkv_window_packed[
            (height // 8 * (width // 8) * (64 // args.block_m),)
        ](
            ffn_output,
            qkv_weight,
            attention_scale,
            packed_q,
            packed_k,
            packed_v,
            width,
            width // 8,
            args.block_m,
            num_warps=4,
            num_stages=2,
            enable_fp_fusion=False,
        )
        _attention_windows_packed[
            (height // 8 * (width // 8) * (64 // args.block_m),)
        ](
            packed_q,
            packed_k,
            packed_v,
            ffn_output,
            logical_bias[0],
            projection,
            attention_cosine,
            packed_output,
            width,
            width // 8,
            args.block_m,
            num_warps=4,
            num_stages=2,
            enable_fp_fusion=False,
        )

    def launch_packed_block() -> None:
        _fused_c32_mlp[(triton.cdiv(height * width, 16),)](
            value,
            w1,
            w2,
            ffn_cosine,
            ffn_output,
            height * width,
            16,
            num_warps=4,
            num_stages=2,
            enable_fp_fusion=False,
        )
        launch_packed()

    def launch_fused_mlp_qkv_attention() -> None:
        _fused_c32_mlp_qkv_window_packed[
            (height // 8 * (width // 8) * (64 // args.fused_block_m),)
        ](
            value,
            w1,
            w2,
            ffn_cosine,
            qkv_weight,
            attention_scale,
            fused_mlp_qkv_ffn,
            fused_mlp_qkv_q,
            fused_mlp_qkv_k,
            fused_mlp_qkv_v,
            width,
            width // 8,
            args.fused_block_m,
            num_warps=4,
            num_stages=2,
            enable_fp_fusion=False,
        )
        _attention_windows_packed[
            (height // 8 * (width // 8) * (64 // args.block_m),)
        ](
            fused_mlp_qkv_q,
            fused_mlp_qkv_k,
            fused_mlp_qkv_v,
            fused_mlp_qkv_ffn,
            logical_bias[0],
            projection,
            attention_cosine,
            fused_mlp_qkv_output,
            width,
            width // 8,
            args.block_m,
            num_warps=4,
            num_stages=2,
            enable_fp_fusion=False,
        )

    def launch_window_fused_block() -> None:
        _fused_c32_window_block[(height // 8 * (width // 8),)](
            value,
            w1,
            w2,
            ffn_cosine,
            qkv_weight,
            attention_scale,
            logical_bias[0],
            projection,
            attention_cosine,
            window_fused_output,
            width,
            width // 8,
            num_warps=4,
            num_stages=2,
            enable_fp_fusion=False,
        )

    compile_started = time.perf_counter()
    launch_row_major()
    launch_packed()
    launch_packed_block()
    launch_fused_mlp_qkv_attention()
    if args.window_fused:
        launch_window_fused_block()
    torch.cuda.synchronize()
    compile_seconds = time.perf_counter() - compile_started

    for _ in range(args.warmup):
        launch_row_major()
        launch_packed()
        launch_packed_block()
        launch_fused_mlp_qkv_attention()
        if args.window_fused:
            launch_window_fused_block()
    torch.cuda.synchronize()

    row_times = [_event_time(launch_row_major) for _ in range(args.iterations)]
    packed_times = [_event_time(launch_packed) for _ in range(args.iterations)]
    packed_block_times = [_event_time(launch_packed_block) for _ in range(args.iterations)]
    fused_mlp_qkv_times = [_event_time(launch_fused_mlp_qkv_attention) for _ in range(args.iterations)]
    window_fused_times = (
        [_event_time(launch_window_fused_block) for _ in range(args.iterations)]
        if args.window_fused
        else []
    )

    original_round_trip = recovered_model.e4m3_round_trip

    def direct_fp8(value_tensor):
        return value_tensor.clamp(-448.0, 448.0).to(torch.float8_e4m3fn).to(value_tensor.dtype)

    recovered_model.e4m3_round_trip = direct_fp8
    try:
        eager_ffn = _reference_block(value, w1, w2, ffn_cosine, 32768).contiguous()
        eager_image = eager_ffn.reshape(1, height, width, 32)

        def eager_attention():
            branch = recovered_model.window_attention(
                eager_image,
                qkv_weight=qkv_weight,
                attention_scale=attention_scale,
                attention_bias=logical_bias,
                projection_weight=projection,
                head_count=1,
                window_size=8,
                window_origin=(0, 0),
            )
            return branch.reshape(height * width, 32) + eager_ffn * attention_cosine

        for _ in range(args.warmup):
            eager_attention()
        torch.cuda.synchronize()
        eager_times = [_event_time(eager_attention) for _ in range(args.iterations)]
        eager_output = eager_attention().contiguous()
        torch.cuda.synchronize()
    finally:
        recovered_model.e4m3_round_trip = original_round_trip

    # Re-run a final packed block so the output comparison is from the complete
    # block, not from whichever isolated timing callback ran last.
    launch_packed_block()
    torch.cuda.synchronize()
    difference = (packed_output.float() - eager_output.float()).abs()
    launch_fused_mlp_qkv_attention()
    torch.cuda.synchronize()
    fused_mlp_qkv_difference = (fused_mlp_qkv_output.float() - eager_output.float()).abs()
    window_fused_difference = None
    if args.window_fused:
        launch_window_fused_block()
        torch.cuda.synchronize()
        window_fused_difference = (window_fused_output.float() - eager_output.float()).abs()
    # The row-major and packed paths should be equivalent after the same FP8
    # publication.  Keep both comparisons because layout changes can expose
    # a hidden rounding or address-order issue.
    packed_difference = difference
    percentile_sample = packed_difference.reshape(-1)[::max(1, packed_difference.numel() // 1_000_000)]

    args.output.expanduser().resolve().mkdir(parents=True, exist_ok=True)
    result = {
        "schema": "opennr-native-style-c32-packed-cuda-probe-v1",
        "scope": "one block0 C32 direct-window-packed QKV/attention path; offline only",
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
        "input": {
            "source_resolution": [source_width, source_height],
            "feature_resolution": [width, height],
            "tokens": height * width,
            "windows": (height // 8) * (width // 8),
            "packed_shape": [int(packed_q.shape[0]), 64, 32],
        },
        "kernel": {
            "operation": "row-major baseline versus direct-window-packed QKV + 8x8 attention + projection/residual",
            "block_m": args.block_m,
            "warps": 4,
            "stages": 2,
            "triton": triton.__version__,
        },
        "timing_ms": {
            "row_major_attention_median": float(np.median(row_times)),
            "row_major_attention_p95": float(np.percentile(row_times, 95.0)),
            "packed_attention_median": float(np.median(packed_times)),
            "packed_attention_p95": float(np.percentile(packed_times, 95.0)),
            "packed_complete_block_median": float(np.median(packed_block_times)),
            "packed_complete_block_p95": float(np.percentile(packed_block_times, 95.0)),
            "eager_attention_median": float(np.median(eager_times)),
            "row_major_samples": row_times,
            "packed_attention_samples": packed_times,
            "packed_complete_block_samples": packed_block_times,
            "fused_mlp_qkv_attention_median": float(np.median(fused_mlp_qkv_times)),
            "fused_mlp_qkv_attention_p95": float(np.percentile(fused_mlp_qkv_times, 95.0)),
            "fused_mlp_qkv_attention_samples": fused_mlp_qkv_times,
            "window_fused_block_median": float(np.median(window_fused_times)) if window_fused_times else None,
            "window_fused_block_p95": float(np.percentile(window_fused_times, 95.0)) if window_fused_times else None,
            "window_fused_block_samples": window_fused_times,
            "eager_attention_samples": eager_times,
            "compile_seconds": compile_seconds,
        },
        "speed": {
            "attention_layout_speedup": float(np.median(row_times) / np.median(packed_times)),
            "eager_to_packed_attention_speedup": float(np.median(eager_times) / np.median(packed_times)),
            "eager_to_packed_complete_block_speedup": float(np.median(eager_times) / np.median(packed_block_times)),
            "fused_mlp_qkv_vs_packed_complete_block_speedup": float(np.median(packed_block_times) / np.median(fused_mlp_qkv_times)),
            "window_fused_vs_packed_complete_block_speedup": (
                float(np.median(packed_block_times) / np.median(window_fused_times))
                if window_fused_times
                else None
            ),
        },
        "parity": {
            "packed_vs_eager_mae": float(packed_difference.mean().item()),
            "packed_vs_eager_p99_sample": float(torch.quantile(percentile_sample, 0.99).item()),
            "packed_vs_eager_max": float(packed_difference.max().item()),
            "packed_vs_eager_changed_gt_1e3_fraction": float((packed_difference > 1e-3).float().mean().item()),
            "fused_mlp_qkv_vs_eager_mae": float(fused_mlp_qkv_difference.mean().item()),
            "fused_mlp_qkv_vs_eager_max": float(fused_mlp_qkv_difference.max().item()),
            "window_fused_vs_eager_mae": (
                float(window_fused_difference.mean().item())
                if window_fused_difference is not None
                else None
            ),
            "window_fused_vs_eager_max": (
                float(window_fused_difference.max().item())
                if window_fused_difference is not None
                else None
            ),
        },
        "environment": {
            "gpu": torch.cuda.get_device_name(0),
            "torch": torch.__version__,
            "cuda": torch.version.cuda,
        },
        "contract_warning": "The packed and row-major paths are independent CUDA probes compared with the local eager direct-FP8 control; this is not native NVIDIA parity or live VR evidence.",
    }
    (args.output.expanduser().resolve() / "result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
