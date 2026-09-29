"""Measure one recovered C512 split-window block with fused CUDA kernels.

The input is produced by the recovered prefix through block 22.  The measured
block is block23, the first 16-head split-Swin block:

    first projection -> 8 grouped quadratic FFNs -> FFN projection/residual
    -> 16-head QKV/window attention -> output projection/final residual

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

from probe_native_style_c32_cuda import _quadratic_gate_activation, _round_fp8_half
from probe_native_style_c32_attention_cuda import _normalize_c32, _select_row
from probe_native_style_c64_block_cuda import _approx_exp, _half_add, _half_mul


@triton.jit
def _c512_first_projection(
    X,
    WEIGHT,
    OUT,
    rows_total: tl.constexpr,
    BM: tl.constexpr,
    TILES: tl.constexpr,
):
    rows = tl.program_id(0) * BM + tl.arange(0, BM)
    tile = tl.program_id(1)
    lane = tl.arange(0, 512)
    output_lane = tile * 64 + tl.arange(0, 64)
    row_mask = rows[:, None] < rows_total
    x = tl.load(X + rows[:, None] * 512 + lane[None, :], mask=row_mask, other=0)
    weight = tl.load(
        WEIGHT + lane[:, None] * 512 + output_lane[None, :],
    )
    projected = tl.dot(x, weight, out_dtype=tl.float32).to(tl.float16)
    tl.store(
        OUT + rows[:, None] * 512 + output_lane[None, :],
        _round_fp8_half(projected),
        mask=row_mask,
    )


@triton.jit
def _c512_group_feed_forward(
    X,
    EXPAND,
    PROJECT,
    OUT,
    rows_total: tl.constexpr,
    BM: tl.constexpr,
):
    rows = tl.program_id(0) * BM + tl.arange(0, BM)
    group = tl.program_id(1)
    input_lane = tl.arange(0, 64)
    hidden_lane = tl.arange(0, 256)
    output_lane = tl.arange(0, 64)
    row_mask = rows[:, None] < rows_total
    hidden_input = tl.load(
        X + rows[:, None] * 512 + group * 64 + input_lane[None, :],
        mask=row_mask,
        other=0,
    )
    expand_weight = tl.load(
        EXPAND + group * 64 * 256 + input_lane[:, None] * 256 + hidden_lane[None, :]
    )
    expanded = tl.dot(hidden_input, expand_weight, out_dtype=tl.float32).to(tl.float16)
    activated = _quadratic_gate_activation(expanded)
    project_weight = tl.load(
        PROJECT + group * 256 * 64 + hidden_lane[:, None] * 64 + output_lane[None, :]
    )
    projected = tl.dot(activated, project_weight, out_dtype=tl.float32).to(tl.float16)
    tl.store(
        OUT + rows[:, None] * 512 + group * 64 + output_lane[None, :],
        _round_fp8_half(projected),
        mask=row_mask,
    )


@triton.jit
def _c512_ffn_projection_residual(
    X,
    GROUPS,
    WEIGHT,
    COSINE,
    OUT,
    rows_total: tl.constexpr,
    BM: tl.constexpr,
):
    rows = tl.program_id(0) * BM + tl.arange(0, BM)
    tile = tl.program_id(1)
    lane = tl.arange(0, 64)
    output_lane = tile * 64 + lane
    row_mask = rows[:, None] < rows_total
    x = tl.load(X + rows[:, None] * 512 + output_lane[None, :], mask=row_mask, other=0)
    projected = tl.zeros((BM, 64), dtype=tl.float32)
    for group in tl.static_range(8):
        group_value = tl.load(
            GROUPS + rows[:, None] * 512 + group * 64 + lane[None, :],
            mask=row_mask,
            other=0,
        )
        weight = tl.load(
            WEIGHT + (group * 64 + lane)[:, None] * 512 + output_lane[None, :]
        )
        projected += tl.dot(group_value, weight, out_dtype=tl.float32)
    cosine = tl.load(COSINE + output_lane)
    result = _half_add(
        projected.to(tl.float16),
        _half_mul(x, cosine[None, :]),
    )
    tl.store(
        OUT + rows[:, None] * 512 + output_lane[None, :],
        result,
        mask=row_mask,
    )


@triton.jit
def _c512_qkv_projection(
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
    input_lane = tl.arange(0, 512)
    lane = tl.arange(0, 32)
    row_mask = rows[:, None] < rows_total
    x = tl.load(X + rows[:, None] * 512 + input_lane[None, :], mask=row_mask, other=0)
    output_offset = head * 32
    q_weight = tl.load(
        WEIGHT + input_lane[:, None] * 1536 + output_offset + lane[None, :]
    )
    k_weight = tl.load(
        WEIGHT + input_lane[:, None] * 1536 + 512 + output_offset + lane[None, :]
    )
    v_weight = tl.load(
        WEIGHT + input_lane[:, None] * 1536 + 1024 + output_offset + lane[None, :]
    )
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
    tl.store(Q + rows[:, None] * 512 + output_offset + lane[None, :], _round_fp8_half(q), mask=row_mask)
    tl.store(K + rows[:, None] * 512 + output_offset + lane[None, :], _round_fp8_half(k), mask=row_mask)
    tl.store(V + rows[:, None] * 512 + output_offset + lane[None, :], _round_fp8_half(v), mask=row_mask)


@triton.jit
def _c512_qkv_projection_window_packed(
    X,
    WEIGHT,
    SCALE,
    Q,
    K,
    V,
    WIDTH: tl.constexpr,
    COLUMNS: tl.constexpr,
    rows_total: tl.constexpr,
    BM: tl.constexpr,
):
    """Project C512 Q/K/V directly into [window, 64, 512] storage."""

    rows = tl.program_id(0) * BM + tl.arange(0, BM)
    head = tl.program_id(1)
    input_lane = tl.arange(0, 512)
    lane = tl.arange(0, 32)
    row_mask = rows < rows_total
    row_y = rows // WIDTH
    row_x = rows % WIDTH
    window = (row_y // 8) * COLUMNS + (row_x // 8)
    local_row = (row_y % 8) * 8 + (row_x % 8)
    x = tl.load(
        X + rows[:, None] * 512 + input_lane[None, :],
        mask=row_mask[:, None],
        other=0,
    )
    output_offset = head * 32
    q_weight = tl.load(
        WEIGHT + input_lane[:, None] * 1536 + output_offset + lane[None, :]
    )
    k_weight = tl.load(
        WEIGHT + input_lane[:, None] * 1536 + 512 + output_offset + lane[None, :]
    )
    v_weight = tl.load(
        WEIGHT + input_lane[:, None] * 1536 + 1024 + output_offset + lane[None, :]
    )
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
    q = _half_mul(q, tl.load(SCALE + head))
    base = window * 32768
    dest = base[:, None] + local_row[:, None] * 512 + output_offset + lane[None, :]
    tl.store(Q + dest, _round_fp8_half(q), mask=row_mask[:, None])
    tl.store(K + dest, _round_fp8_half(k), mask=row_mask[:, None])
    tl.store(V + dest, _round_fp8_half(v), mask=row_mask[:, None])


@triton.jit
def _c512_attention_windows_only(
    Q,
    K,
    V,
    BIAS,
    ATTENDED,
    WIDTH: tl.constexpr,
    COLUMNS: tl.constexpr,
    BM: tl.constexpr,
    TILES: tl.constexpr,
):
    program = tl.program_id(0)
    head = program % 16
    tile = (program // 16) % TILES
    window = program // (16 * TILES)
    local_row = tile * BM + tl.arange(0, BM)
    local_key = tl.arange(0, 64)
    lane = tl.arange(0, 32)
    row_mask = local_row < 64

    window_row = window // COLUMNS
    window_col = window % COLUMNS
    row_y = window_row * 8 + local_row // 8
    row_x = window_col * 8 + local_row % 8
    key_y = window_row * 8 + local_key // 8
    key_x = window_col * 8 + local_key % 8
    row_index = row_y * WIDTH + row_x
    key_index = key_y * WIDTH + key_x
    head_offset = head * 32
    q = tl.load(Q + row_index[:, None] * 512 + head_offset + lane[None, :], mask=row_mask[:, None], other=0)
    k = tl.load(K + key_index[None, :] * 512 + head_offset + lane[:, None])
    v = tl.load(V + key_index[:, None] * 512 + head_offset + lane[None, :])
    bias = tl.load(
        BIAS + head * 4096 + local_row[:, None] * 64 + local_key[None, :],
        mask=row_mask[:, None],
        other=0,
    )
    scores = tl.dot(q, k, out_dtype=tl.float32).to(tl.float16)
    scores = _half_add(scores, bias)
    weights = _approx_exp(scores, BM)
    denominator = tl.sum(weights.to(tl.float32), axis=1).to(tl.float16)
    reciprocal = (1.0 / denominator.to(tl.float32)).to(tl.float16)
    probabilities = _round_fp8_half(_half_mul(weights, reciprocal[:, None]))
    attended = _round_fp8_half(tl.dot(probabilities, v, out_dtype=tl.float32).to(tl.float16))
    tl.store(
        ATTENDED + row_index[:, None] * 512 + head_offset + lane[None, :],
        attended,
        mask=row_mask[:, None],
    )


@triton.jit
def _c512_attention_windows_only_packed(
    Q,
    K,
    V,
    BIAS,
    ATTENDED,
    WIDTH: tl.constexpr,
    COLUMNS: tl.constexpr,
    BM: tl.constexpr,
    TILES: tl.constexpr,
):
    """Consume packed C512 Q/K/V while retaining split per-head attention."""

    program = tl.program_id(0)
    head = program % 16
    tile = (program // 16) % TILES
    window = program // (16 * TILES)
    local_row = tile * BM + tl.arange(0, BM)
    local_key = tl.arange(0, 64)
    lane = tl.arange(0, 32)
    row_mask = local_row < 64
    window_row = window // COLUMNS
    window_col = window % COLUMNS
    row_y = window_row * 8 + local_row // 8
    row_x = window_col * 8 + local_row % 8
    row_index = row_y * WIDTH + row_x
    head_offset = head * 32
    base = window * 32768

    q = tl.load(
        Q + base + local_row[:, None] * 512 + head_offset + lane[None, :],
        mask=row_mask[:, None],
        other=0,
    )
    k = tl.load(
        K + base + local_key[None, :] * 512 + head_offset + lane[:, None]
    )
    v = tl.load(
        V + base + local_key[:, None] * 512 + head_offset + lane[None, :]
    )
    bias = tl.load(
        BIAS
        + head * 4096
        + local_row[:, None] * 64
        + local_key[None, :],
        mask=row_mask[:, None],
        other=0,
    )
    scores = tl.dot(q, k, out_dtype=tl.float32).to(tl.float16)
    scores = _half_add(scores, bias)
    weights = _approx_exp(scores, BM)
    denominator = tl.sum(weights.to(tl.float32), axis=1).to(tl.float16)
    reciprocal = (1.0 / denominator.to(tl.float32)).to(tl.float16)
    probabilities = _round_fp8_half(_half_mul(weights, reciprocal[:, None]))
    attended = _round_fp8_half(
        tl.dot(probabilities, v, out_dtype=tl.float32).to(tl.float16)
    )
    tl.store(
        ATTENDED + row_index[:, None] * 512 + head_offset + lane[None, :],
        attended,
        mask=row_mask[:, None],
    )


@triton.jit
def _c512_attention_projection_residual(
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
    lane = tl.arange(0, 64)
    head_lane = tl.arange(0, 32)
    output_lane = tile * 64 + lane
    row_mask = rows[:, None] < rows_total
    x = tl.load(X + rows[:, None] * 512 + output_lane[None, :], mask=row_mask, other=0)
    projected0 = tl.zeros((BM, 32), dtype=tl.float32)
    projected1 = tl.zeros((BM, 32), dtype=tl.float32)
    for head in tl.static_range(16):
        attended = tl.load(
            ATTENDED + rows[:, None] * 512 + head * 32 + head_lane[None, :],
            mask=row_mask,
            other=0,
        )
        # The 64-output tile is split into two 32-wide projection fragments.
        output0 = tile * 64 + tl.arange(0, 32)
        output1 = tile * 64 + 32 + tl.arange(0, 32)
        projection0 = tl.load(
            PROJECTION + (head * 32 + head_lane)[:, None] * 512 + output0[None, :]
        )
        projection1 = tl.load(
            PROJECTION + (head * 32 + head_lane)[:, None] * 512 + output1[None, :]
        )
        projected0 += tl.dot(attended, projection0, out_dtype=tl.float32)
        projected1 += tl.dot(attended, projection1, out_dtype=tl.float32)
    projected = tl.reshape(
        tl.permute(tl.join(projected0, projected1), (0, 2, 1)),
        (BM, 64),
    )
    cosine = tl.load(COSINE + output_lane)
    result = _half_add(projected.to(tl.float16), _half_mul(x, cosine[None, :]))
    tl.store(
        OUT + rows[:, None] * 512 + output_lane[None, :],
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
    parser.add_argument("--probe-height", type=int, default=0, help="Optional top-left C512 height; 0 means full stage")
    parser.add_argument("--probe-width", type=int, default=0, help="Optional top-left C512 width; 0 means full stage")
    parser.add_argument("--block-m", type=int, choices=(16, 32), default=16)
    parser.add_argument("--attention-block-m", type=int, choices=(16, 32, 64), default=64)
    parser.add_argument(
        "--layout-mode",
        choices=("row", "packed"),
        default="row",
        help="Use the existing row-major path or direct-window-packed attention",
    )
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

    # Run the genuine recovered prefix through the C512 input of block23.
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
        c512_full = prefix_model._downsample_window(value, 22, head_count=8)[0].contiguous()
    del input_tensor, value, prefix_model
    torch.cuda.synchronize()

    full_stage_height = int(c512_full.shape[0])
    full_stage_width = int(c512_full.shape[1])
    logical_height = args.probe_height or full_stage_height
    logical_width = args.probe_width or full_stage_width
    if logical_height <= 0 or logical_width <= 0:
        raise ValueError("C512 probe dimensions must be positive")
    if logical_height > c512_full.shape[0] or logical_width > c512_full.shape[1]:
        raise ValueError("C512 probe dimensions exceed the recovered stage")
    height = triton.cdiv(logical_height, 8) * 8
    width = triton.cdiv(logical_width, 8) * 8
    features = c512_full[:logical_height, :logical_width].contiguous()
    del c512_full
    if height != logical_height or width != logical_width:
        features = torch.nn.functional.pad(
            features,
            (0, 0, 0, width - logical_width, 0, height - logical_height),
        ).contiguous()
    rows_total = height * width
    value = features.reshape(rows_total, 512)

    first_projection = weights["block23.layer0.first_projection_weight"].to("cuda", torch.float16).contiguous()
    expand = weights["block23.layer0.group_expand_weight"].to("cuda", torch.float16).contiguous()
    group_project = weights["block23.layer0.group_project_weight"].to("cuda", torch.float16).contiguous()
    ffn_projection = weights["block23.layer1.weight3"].to("cuda", torch.float16).contiguous()
    ffn_cosine = weights["block23.layer1.ffn_cos_skip"].to("cuda", torch.float16).contiguous()
    qkv_weight = weights["block23.layer2.qkv_weight"].to("cuda", torch.float16).contiguous()
    attention_scale = weights["block23.layer2.attn_scale"].to("cuda", torch.float32).contiguous()
    attention_bias = recovered_model.recover_attention_bias_layout(
        weights["block23.layer2.attn_bias"]
    ).to("cuda", torch.float16).contiguous()
    attention_projection = weights["block23.layer3.projection_weight"].to("cuda", torch.float16).contiguous()
    attention_cosine = weights["block23.layer3.attn_cos_skip"].to("cuda", torch.float16).contiguous()

    first_published = torch.empty_like(value)
    group_fragments = torch.empty_like(value)
    fused_ffn = torch.empty_like(value)
    q = torch.empty_like(value)
    k = torch.empty_like(value)
    v = torch.empty_like(value)
    attended = torch.empty_like(value)
    fused_output = torch.empty_like(value)
    packed_q = packed_k = packed_v = packed_attended = packed_output = None
    if args.layout_mode == "packed":
        windows = (height // 8) * (width // 8)
        packed_q = torch.empty((windows, 64, 512), device="cuda", dtype=torch.float16)
        packed_k = torch.empty_like(packed_q)
        packed_v = torch.empty_like(packed_q)
        packed_attended = torch.empty_like(value)
        packed_output = torch.empty_like(value)

    def launch_ffn() -> None:
        _c512_first_projection[(triton.cdiv(rows_total, args.block_m), 8)](
            value, first_projection, first_published, rows_total, args.block_m, 8,
            num_warps=4, num_stages=1, enable_fp_fusion=False,
        )
        _c512_group_feed_forward[(triton.cdiv(rows_total, args.block_m), 8)](
            first_published, expand, group_project, group_fragments,
            rows_total, args.block_m,
            num_warps=4, num_stages=1, enable_fp_fusion=False,
        )
        _c512_ffn_projection_residual[(triton.cdiv(rows_total, args.block_m), 8)](
            value, group_fragments, ffn_projection, ffn_cosine, fused_ffn,
            rows_total, args.block_m,
            num_warps=4, num_stages=1, enable_fp_fusion=False,
        )

    def launch_attention() -> None:
        _c512_qkv_projection[(triton.cdiv(rows_total, 16), 16)](
            fused_ffn, qkv_weight, attention_scale, q, k, v,
            rows_total, 16,
            num_warps=4, num_stages=1, enable_fp_fusion=False,
        )
        windows = (height // 8) * (width // 8)
        tiles = 64 // args.attention_block_m
        _c512_attention_windows_only[(windows * tiles * 16,)](
            q, k, v, attention_bias, attended, width, width // 8,
            args.attention_block_m, tiles,
            num_warps=4, num_stages=1, enable_fp_fusion=False,
        )
        _c512_attention_projection_residual[(triton.cdiv(rows_total, 16), 8)](
            fused_ffn, attended, attention_projection, attention_cosine, fused_output,
            rows_total, 16,
            num_warps=4, num_stages=1, enable_fp_fusion=False,
        )

    def launch_packed_attention() -> None:
        if packed_q is None or packed_k is None or packed_v is None or packed_attended is None or packed_output is None:
            raise RuntimeError("packed buffers were not allocated")
        windows = (height // 8) * (width // 8)
        tiles = 64 // args.attention_block_m
        _c512_qkv_projection_window_packed[(triton.cdiv(rows_total, 16), 16)](
            fused_ffn,
            qkv_weight,
            attention_scale,
            packed_q,
            packed_k,
            packed_v,
            width,
            width // 8,
            rows_total,
            16,
            num_warps=4,
            num_stages=1,
            enable_fp_fusion=False,
        )
        _c512_attention_windows_only_packed[(windows * tiles * 16,)](
            packed_q,
            packed_k,
            packed_v,
            attention_bias,
            packed_attended,
            width,
            width // 8,
            args.attention_block_m,
            tiles,
            num_warps=4,
            num_stages=1,
            enable_fp_fusion=False,
        )
        _c512_attention_projection_residual[(triton.cdiv(rows_total, 16), 8)](
            fused_ffn,
            packed_attended,
            attention_projection,
            attention_cosine,
            packed_output,
            rows_total,
            16,
            num_warps=4,
            num_stages=1,
            enable_fp_fusion=False,
        )

    def launch_block() -> None:
        launch_ffn()
        launch_attention()

    def launch_packed_block() -> None:
        launch_ffn()
        launch_packed_attention()

    compile_started = time.perf_counter()
    launch_block()
    if args.layout_mode == "packed":
        launch_packed_block()
    torch.cuda.synchronize()
    compile_seconds = time.perf_counter() - compile_started
    for _ in range(args.warmup):
        launch_block()
        if args.layout_mode == "packed":
            launch_packed_block()
    torch.cuda.synchronize()
    fused_block_times = [_event_time(launch_block) for _ in range(args.iterations)]
    fused_ffn_times = [_event_time(launch_ffn) for _ in range(args.iterations)]
    fused_attention_times = [_event_time(launch_attention) for _ in range(args.iterations)]
    packed_block_times = (
        [_event_time(launch_packed_block) for _ in range(args.iterations)]
        if args.layout_mode == "packed"
        else []
    )
    packed_attention_times = (
        [_event_time(launch_packed_attention) for _ in range(args.iterations)]
        if args.layout_mode == "packed"
        else []
    )

    original_round_trip = recovered_model.e4m3_round_trip

    def direct_fp8(value_tensor):
        return value_tensor.clamp(-448.0, 448.0).to(torch.float8_e4m3fn).to(value_tensor.dtype)

    def eager_block():
        value_image = value.reshape(1, height, width, 512)
        output = recovered_model.split_window_block(
            value_image,
            first_projection_weight=first_projection,
            expand_weight=expand,
            project_weight=group_project,
            feed_forward_projection_weight=ffn_projection,
            feed_forward_cosine=ffn_cosine,
            qkv_weight=qkv_weight,
            attention_scale=attention_scale,
            attention_bias=attention_bias.unsqueeze(0),
            attention_projection_weight=attention_projection,
            attention_cosine=attention_cosine,
            head_count=16,
            window_size=8,
            window_origin=(0, 0),
        )
        return recovered_model.e4m3_round_trip(output).reshape(rows_total, 512)

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

    fused_compare = fused_output.reshape(1, height, width, 512)[:, :logical_height, :logical_width].reshape(-1, 512)
    eager_compare = eager_output.reshape(1, height, width, 512)[:, :logical_height, :logical_width].reshape(-1, 512)
    difference = (fused_compare.float() - eager_compare.float()).abs()
    packed_difference = None
    packed_vs_row_major = None
    if args.layout_mode == "packed":
        launch_packed_block()
        torch.cuda.synchronize()
        packed_compare = packed_output.reshape(1, height, width, 512)[:, :logical_height, :logical_width].reshape(-1, 512)
        packed_difference = (packed_compare.float() - eager_compare.float()).abs()
        packed_vs_row_major = (packed_compare.float() - fused_compare.float()).abs()
    percentile_sample = difference.reshape(-1)[::max(1, difference.numel() // 1_000_000)]
    args.output.expanduser().resolve().mkdir(parents=True, exist_ok=True)
    result = {
        "schema": "opennr-native-style-c512-split-block-cuda-probe-v1",
        "scope": "recovered block23 C512 split-window block with grouped FFN plus sixteen-head window attention; offline only",
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
            "recovered_stages": "block0 -> average_pool2 -> blocks1-3 -> block4 downsample -> blocks5-7 -> block8 downsample -> blocks9-13 -> block14 downsample -> blocks15-21 -> block22 downsample",
            "input_resolution": [source_width, source_height],
        },
        "input": {
            "stage": "block23 C512",
            "probe_resolution": [logical_width, logical_height],
            "kernel_resolution": [width, height],
            "probe_region": "full_c512_stage" if (logical_height == full_stage_height and logical_width == full_stage_width) else "top_left",
            "tokens": int(logical_height * logical_width),
            "kernel_tokens": int(rows_total),
            "window_count": int((height // 8) * (width // 8)),
            "padding_right": int(width - logical_width),
            "padding_bottom": int(height - logical_height),
            "channels": 512,
            "heads": 16,
        },
        "kernel": {
            "block": "block23",
            "operation": "C512 first projection + grouped FFN + FFN projection/residual + sixteen-head QKV/window attention + projection/residual",
            "block_m": args.block_m,
            "attention_block_m": args.attention_block_m,
            "qkv_block_m": 16,
            "attention_mode": "split_attention_and_projection",
            "layout_mode": args.layout_mode,
            "warps": 4,
            "stages": 1,
            "triton": triton.__version__,
        },
        "timing_ms": {
            "compile_and_first_run": compile_seconds * 1000.0,
            "fused_block_median": float(np.median(fused_block_times)),
            "fused_block_p95": float(np.percentile(fused_block_times, 95.0)),
            "fused_block_samples": fused_block_times,
            "fused_ffn_median": float(np.median(fused_ffn_times)),
            "fused_attention_median": float(np.median(fused_attention_times)),
            "eager_block_median": float(np.median(eager_times)),
            "eager_block_p95": float(np.percentile(eager_times, 95.0)),
            "eager_block_samples": eager_times,
            "packed_block_median": float(np.median(packed_block_times)) if packed_block_times else None,
            "packed_block_p95": float(np.percentile(packed_block_times, 95.0)) if packed_block_times else None,
            "packed_attention_median": float(np.median(packed_attention_times)) if packed_attention_times else None,
            "packed_attention_samples": packed_attention_times,
        },
        "speedup": float(np.median(eager_times) / np.median(fused_block_times)),
        "packed_speedup_vs_row_major": (
            float(np.median(fused_block_times) / np.median(packed_block_times))
            if packed_block_times
            else None
        ),
        "drift_vs_eager_direct_fp8": {
            "mae": float(difference.mean().item()),
            "p99_sample": float(torch.quantile(percentile_sample, 0.99).item()),
            "p999_sample": float(torch.quantile(percentile_sample, 0.999).item()),
            "max": float(difference.max().item()),
            "changed_fraction_gt_1e-3": float((difference > 1e-3).float().mean().item()),
            "packed_vs_eager_mae": float(packed_difference.mean().item()) if packed_difference is not None else None,
            "packed_vs_eager_max": float(packed_difference.max().item()) if packed_difference is not None else None,
            "packed_vs_row_major_mae": float(packed_vs_row_major.mean().item()) if packed_vs_row_major is not None else None,
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
        "interpretation": "One C512 split-window block proof only; not the NVIDIA DLL, full 71-block timing, exact native parity, temporal/stereo validation, or VR readiness.",
    }
    (args.output.expanduser().resolve() / "result.json").write_text(
        json.dumps(result, indent=2), encoding="utf-8"
    )
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
