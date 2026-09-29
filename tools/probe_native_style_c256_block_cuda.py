"""Measure one recovered pooled C256 window block with fused CUDA kernels.

The input is produced by the recovered prefix through block 14:

    block0 -> pool -> blocks1-3 -> block4 -> blocks5-7 -> block8
    -> blocks9-13 -> block14 downsample

The measured block is an eight-group branched C256 FFN followed by eight-head
QKV/cosine publication, 8x8 window attention, output projection, and residual.
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
def _fused_c256_branched_mlp(
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
    output_lane = tl.arange(0, 256)
    row_mask = rows[:, None] < rows_total
    x = tl.load(
        X + rows[:, None] * 256 + output_lane[None, :],
        mask=row_mask,
        other=0,
    )

    group0 = tl.full((BM, 32), 0.0, tl.float16)
    group1 = tl.full((BM, 32), 0.0, tl.float16)
    group2 = tl.full((BM, 32), 0.0, tl.float16)
    group3 = tl.full((BM, 32), 0.0, tl.float16)
    group4 = tl.full((BM, 32), 0.0, tl.float16)
    group5 = tl.full((BM, 32), 0.0, tl.float16)
    group6 = tl.full((BM, 32), 0.0, tl.float16)
    group7 = tl.full((BM, 32), 0.0, tl.float16)
    for output_group in tl.static_range(8):
        group_sum = tl.full((BM, 32), 0.0, tl.float16)
        for branch_index in tl.static_range(4):
            expanded = tl.full((BM, 32), 0.0, tl.float16)
            for input_group in tl.static_range(8):
                input_offset = input_group * 32
                source = tl.gather(
                    x,
                    tl.broadcast_to(
                        (input_offset + lane)[None, :],
                        (BM, 32),
                    ),
                    1,
                )
                expand_offset = (
                    ((output_group * 4 + branch_index) * 8 + input_group) * 32 * 32
                )
                expand_weight = tl.load(
                    EXPAND
                    + expand_offset
                    + lane[:, None] * 32
                    + lane[None, :]
                )
                expanded = _half_add(
                    expanded,
                    tl.dot(source, expand_weight, out_dtype=tl.float32).to(tl.float16),
                )

            activated = _round_fp8_half(_quadratic_gate_activation(expanded))
            branch_offset = (output_group * 4 + branch_index) * 32 * 32
            branch_weight = tl.load(
                BRANCH
                + branch_offset
                + lane[:, None] * 32
                + lane[None, :]
            )
            group_sum = _half_add(
                group_sum,
                tl.dot(activated, branch_weight, out_dtype=tl.float32).to(tl.float16),
            )

        group_value = _round_fp8_half(group_sum)
        if output_group == 0:
            group0 = group_value
        elif output_group == 1:
            group1 = group_value
        elif output_group == 2:
            group2 = group_value
        elif output_group == 3:
            group3 = group_value
        elif output_group == 4:
            group4 = group_value
        elif output_group == 5:
            group5 = group_value
        elif output_group == 6:
            group6 = group_value
        else:
            group7 = group_value

    projected = tl.zeros((BM, 256), dtype=tl.float32)
    output_weight0 = tl.load(OUTPUT + lane[:, None] * 256 + output_lane[None, :])
    output_weight1 = tl.load(OUTPUT + (32 + lane)[:, None] * 256 + output_lane[None, :])
    output_weight2 = tl.load(OUTPUT + (64 + lane)[:, None] * 256 + output_lane[None, :])
    output_weight3 = tl.load(OUTPUT + (96 + lane)[:, None] * 256 + output_lane[None, :])
    output_weight4 = tl.load(OUTPUT + (128 + lane)[:, None] * 256 + output_lane[None, :])
    output_weight5 = tl.load(OUTPUT + (160 + lane)[:, None] * 256 + output_lane[None, :])
    output_weight6 = tl.load(OUTPUT + (192 + lane)[:, None] * 256 + output_lane[None, :])
    output_weight7 = tl.load(OUTPUT + (224 + lane)[:, None] * 256 + output_lane[None, :])
    projected += tl.dot(group0, output_weight0, out_dtype=tl.float32)
    projected += tl.dot(group1, output_weight1, out_dtype=tl.float32)
    projected += tl.dot(group2, output_weight2, out_dtype=tl.float32)
    projected += tl.dot(group3, output_weight3, out_dtype=tl.float32)
    projected += tl.dot(group4, output_weight4, out_dtype=tl.float32)
    projected += tl.dot(group5, output_weight5, out_dtype=tl.float32)
    projected += tl.dot(group6, output_weight6, out_dtype=tl.float32)
    projected += tl.dot(group7, output_weight7, out_dtype=tl.float32)

    cosine = tl.load(COSINE + output_lane)
    residual = _half_add(
        projected.to(tl.float16),
        _half_mul(x, cosine[None, :]),
    )
    tl.store(
        OUT + rows[:, None] * 256 + output_lane[None, :],
        _round_fp8_half(residual),
        mask=row_mask,
    )


@triton.jit
def _fused_c256_group_mlp(
    X,
    EXPAND,
    BRANCH,
    GROUPS,
    rows_total: tl.constexpr,
    BM: tl.constexpr,
):
    """Compute one of the eight C256 FFN output groups per program.

    Keeping the output-group loop out of the same program avoids the shared
    memory footprint of a monolithic C256 branch tree.  The stored group is
    still the recovered E4M3-published value, so the split is a scheduling
    boundary rather than a model change.
    """

    rows = tl.program_id(0) * BM + tl.arange(0, BM)
    output_group = tl.program_id(1)
    lane = tl.arange(0, 32)
    row_mask = rows[:, None] < rows_total
    x = tl.load(
        X + rows[:, None] * 256 + tl.arange(0, 256)[None, :],
        mask=rows[:, None] < rows_total,
        other=0,
    )
    group_sum = tl.full((BM, 32), 0.0, tl.float16)
    for branch_index in tl.static_range(4):
        expanded = tl.full((BM, 32), 0.0, tl.float16)
        for input_group in tl.static_range(8):
            input_offset = input_group * 32
            source = tl.gather(
                x,
                tl.broadcast_to(
                    (input_offset + lane)[None, :],
                    (BM, 32),
                ),
                1,
            )
            expand_offset = (
                ((output_group * 4 + branch_index) * 8 + input_group) * 32 * 32
            )
            expand_weight = tl.load(
                EXPAND
                + expand_offset
                + lane[:, None] * 32
                + lane[None, :]
            )
            expanded = _half_add(
                expanded,
                tl.dot(source, expand_weight, out_dtype=tl.float32).to(tl.float16),
            )
        activated = _round_fp8_half(_quadratic_gate_activation(expanded))
        branch_offset = (output_group * 4 + branch_index) * 32 * 32
        branch_weight = tl.load(
            BRANCH
            + branch_offset
            + lane[:, None] * 32
            + lane[None, :]
        )
        group_sum = _half_add(
            group_sum,
            tl.dot(activated, branch_weight, out_dtype=tl.float32).to(tl.float16),
        )

    group_value = _round_fp8_half(group_sum)
    tl.store(
        GROUPS + rows[:, None] * 256 + output_group * 32 + lane[None, :],
        group_value,
        mask=row_mask,
    )


@triton.jit
def _project_c256_ffn(
    X,
    GROUPS,
    OUTPUT,
    COSINE,
    OUT,
    rows_total: tl.constexpr,
    BM: tl.constexpr,
):
    """Project the eight published C256 groups and apply the FFN residual."""

    rows = tl.program_id(0) * BM + tl.arange(0, BM)
    lane = tl.arange(0, 32)
    output_lane = tl.arange(0, 256)
    row_mask = rows[:, None] < rows_total
    x = tl.load(
        X + rows[:, None] * 256 + output_lane[None, :],
        mask=row_mask,
        other=0,
    )
    projected = tl.zeros((BM, 256), dtype=tl.float32)
    for output_group in tl.static_range(8):
        group_value = tl.load(
            GROUPS
            + rows[:, None] * 256
            + output_group * 32
            + lane[None, :],
            mask=row_mask,
            other=0,
        )
        output_weight = tl.load(
            OUTPUT
            + (output_group * 32 + lane)[:, None] * 256
            + output_lane[None, :]
        )
        projected += tl.dot(group_value, output_weight, out_dtype=tl.float32)

    cosine = tl.load(COSINE + output_lane)
    residual = _half_add(
        projected.to(tl.float16),
        _half_mul(x, cosine[None, :]),
    )
    tl.store(
        OUT + rows[:, None] * 256 + output_lane[None, :],
        _round_fp8_half(residual),
        mask=row_mask,
    )


@triton.jit
def _project_c256_qkv(
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
    input_lane = tl.arange(0, 256)
    lane = tl.arange(0, 32)
    row_mask = rows[:, None] < rows_total
    x = tl.load(
        X + rows[:, None] * 256 + input_lane[None, :],
        mask=row_mask,
        other=0,
    )
    for head in tl.static_range(8):
        output_offset = head * 32
        q_weight = tl.load(
            WEIGHT
            + input_lane[:, None] * 768
            + output_offset
            + lane[None, :]
        )
        k_weight = tl.load(
            WEIGHT
            + input_lane[:, None] * 768
            + 256
            + output_offset
            + lane[None, :]
        )
        v_weight = tl.load(
            WEIGHT
            + input_lane[:, None] * 768
            + 512
            + output_offset
            + lane[None, :]
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
        tl.store(
            Q + rows[:, None] * 256 + output_offset + lane[None, :],
            _round_fp8_half(q),
            mask=row_mask,
        )
        tl.store(
            K + rows[:, None] * 256 + output_offset + lane[None, :],
            _round_fp8_half(k),
            mask=row_mask,
        )
        tl.store(
            V + rows[:, None] * 256 + output_offset + lane[None, :],
            _round_fp8_half(v),
            mask=row_mask,
        )


@triton.jit
def _project_c256_qkv_window_packed(
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
    """Project C256 Q/K/V directly into [window, 64, 256] storage."""

    program = tl.program_id(0)
    window = program // (64 // BM)
    tile = program % (64 // BM)
    rows = tile * BM + tl.arange(0, BM)
    input_lane = tl.arange(0, 256)
    lane = tl.arange(0, 32)
    row_mask = rows < 64

    window_row = window // COLUMNS
    window_col = window % COLUMNS
    row_y = window_row * 8 + rows // 8
    row_x = window_col * 8 + rows % 8
    row_index = row_y * WIDTH + row_x
    x = tl.load(
        X + row_index[:, None] * 256 + input_lane[None, :],
        mask=row_mask[:, None],
        other=0,
    )
    base = window * 16384
    for head in tl.static_range(8):
        output_offset = head * 32
        q_weight = tl.load(
            WEIGHT
            + input_lane[:, None] * 768
            + output_offset
            + lane[None, :]
        )
        k_weight = tl.load(
            WEIGHT
            + input_lane[:, None] * 768
            + 256
            + output_offset
            + lane[None, :]
        )
        v_weight = tl.load(
            WEIGHT
            + input_lane[:, None] * 768
            + 512
            + output_offset
            + lane[None, :]
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
        dest = base + rows[:, None] * 256 + output_offset + lane[None, :]
        tl.store(Q + dest, _round_fp8_half(q), mask=row_mask[:, None])
        tl.store(K + dest, _round_fp8_half(k), mask=row_mask[:, None])
        tl.store(V + dest, _round_fp8_half(v), mask=row_mask[:, None])


@triton.jit
def _attention_c256_windows(
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
    output_lane = tl.arange(0, 256)
    row_mask = local_row < 64

    window_row = window // COLUMNS
    window_col = window % COLUMNS
    row_y = window_row * 8 + local_row // 8
    row_x = window_col * 8 + local_row % 8
    key_y = window_row * 8 + local_key // 8
    key_x = window_col * 8 + local_key % 8
    row_index = row_y * WIDTH + row_x
    key_index = key_y * WIDTH + key_x
    x = tl.load(
        X + row_index[:, None] * 256 + output_lane[None, :],
        mask=row_mask[:, None],
        other=0,
    )
    branch = tl.zeros((BM, 256), dtype=tl.float32)

    for head in tl.static_range(8):
        head_offset = head * 32
        q = tl.load(
            Q + row_index[:, None] * 256 + head_offset + lane[None, :],
            mask=row_mask[:, None],
            other=0,
        )
        k = tl.load(
            K + key_index[None, :] * 256 + head_offset + lane[:, None],
        )
        v = tl.load(
            V + key_index[:, None] * 256 + head_offset + lane[None, :],
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
        probabilities = _round_fp8_half(
            _half_mul(weights, reciprocal[:, None])
        )
        attended = _round_fp8_half(
            tl.dot(probabilities, v, out_dtype=tl.float32).to(tl.float16)
        )
        projection = tl.load(
            PROJECTION
            + (head_offset + lane)[:, None] * 256
            + output_lane[None, :]
        )
        branch += tl.dot(attended, projection, out_dtype=tl.float32)

    cosine = tl.load(COSINE + output_lane)
    result = _half_add(
        branch.to(tl.float16),
        _half_mul(x, cosine[None, :]),
    )
    tl.store(
        OUT + row_index[:, None] * 256 + output_lane[None, :],
        result,
        mask=row_mask[:, None],
    )


@triton.jit
def _attention_c256_windows_only(
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
    """Compute one head's 32-wide attended fragment per program.

    The fused C256 attention kernel has to keep eight 256-wide output
    accumulators live while it evaluates the heads.  This split variant keeps
    only one 32-wide head fragment live and leaves the C256 projection to a
    separate token-local kernel.
    """

    program = tl.program_id(0)
    head = program % 8
    tile = (program // 8) % TILES
    window = program // (8 * TILES)
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

    q = tl.load(
        Q + row_index[:, None] * 256 + head_offset + lane[None, :],
        mask=row_mask[:, None],
        other=0,
    )
    k = tl.load(
        K + key_index[None, :] * 256 + head_offset + lane[:, None],
    )
    v = tl.load(
        V + key_index[:, None] * 256 + head_offset + lane[None, :],
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
    probabilities = _round_fp8_half(
        _half_mul(weights, reciprocal[:, None])
    )
    attended = _round_fp8_half(
        tl.dot(probabilities, v, out_dtype=tl.float32).to(tl.float16)
    )
    tl.store(
        ATTENDED + row_index[:, None] * 256 + head_offset + lane[None, :],
        attended,
        mask=row_mask[:, None],
    )


@triton.jit
def _attention_c256_windows_only_packed(
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
    """Consume packed C256 Q/K/V while retaining split per-head attention."""

    program = tl.program_id(0)
    head = program % 8
    tile = (program // 8) % TILES
    window = program // (8 * TILES)
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
    base = window * 16384

    q = tl.load(
        Q + base + local_row[:, None] * 256 + head_offset + lane[None, :],
        mask=row_mask[:, None],
        other=0,
    )
    k = tl.load(
        K + base + local_key[None, :] * 256 + head_offset + lane[:, None]
    )
    v = tl.load(
        V + base + local_key[:, None] * 256 + head_offset + lane[None, :]
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
    probabilities = _round_fp8_half(
        _half_mul(weights, reciprocal[:, None])
    )
    attended = _round_fp8_half(
        tl.dot(probabilities, v, out_dtype=tl.float32).to(tl.float16)
    )
    tl.store(
        ATTENDED + row_index[:, None] * 256 + head_offset + lane[None, :],
        attended,
        mask=row_mask[:, None],
    )


@triton.jit
def _project_c256_attention(
    X,
    ATTENDED,
    PROJECTION,
    COSINE,
    OUT,
    rows_total: tl.constexpr,
    BM: tl.constexpr,
):
    """Project the eight published C32 attention heads to C256."""

    rows = tl.program_id(0) * BM + tl.arange(0, BM)
    lane = tl.arange(0, 32)
    output_lane = tl.arange(0, 256)
    row_mask = rows[:, None] < rows_total
    x = tl.load(
        X + rows[:, None] * 256 + output_lane[None, :],
        mask=row_mask,
        other=0,
    )
    projected = tl.zeros((BM, 256), dtype=tl.float32)
    for head in tl.static_range(8):
        attended = tl.load(
            ATTENDED
            + rows[:, None] * 256
            + head * 32
            + lane[None, :],
            mask=row_mask,
            other=0,
        )
        projection = tl.load(
            PROJECTION
            + (head * 32 + lane)[:, None] * 256
            + output_lane[None, :]
        )
        projected += tl.dot(attended, projection, out_dtype=tl.float32)

    cosine = tl.load(COSINE + output_lane)
    result = _half_add(
        projected.to(tl.float16),
        _half_mul(x, cosine[None, :]),
    )
    tl.store(
        OUT + rows[:, None] * 256 + output_lane[None, :],
        result,
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
    parser.add_argument("--probe-height", type=int, default=0, help="Optional top-left C256 height; 0 means full stage")
    parser.add_argument("--probe-width", type=int, default=0, help="Optional top-left C256 width; 0 means full stage")
    parser.add_argument("--mlp-block-m", type=int, choices=(16, 32), default=16)
    parser.add_argument("--attention-block-m", type=int, choices=(16, 32, 64), default=64)
    parser.add_argument("--attention-mode", choices=("fused", "split"), default="split")
    parser.add_argument(
        "--layout-mode",
        choices=("row", "packed"),
        default="row",
        help="Use the existing row-major path or the direct-window-packed split path",
    )
    parser.add_argument("--warmup", type=int, default=1)
    parser.add_argument("--iterations", type=int, default=2)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is required")
    if args.warmup < 0 or args.iterations <= 0:
        raise ValueError("iterations must be positive; warmup must be nonnegative")
    if args.layout_mode == "packed" and args.attention_mode != "split":
        raise ValueError("the packed C256 experiment currently requires --attention-mode split")

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
        c256_full = prefix_model._downsample_window(value, 14, head_count=4)[0].contiguous()
    del input_tensor, value, prefix_model
    torch.cuda.synchronize()

    logical_height = args.probe_height or int(c256_full.shape[0])
    logical_width = args.probe_width or int(c256_full.shape[1])
    if logical_height <= 0 or logical_width <= 0:
        raise ValueError("C256 probe dimensions must be positive")
    if logical_height > c256_full.shape[0] or logical_width > c256_full.shape[1]:
        raise ValueError("C256 probe dimensions exceed the recovered stage")
    height = triton.cdiv(logical_height, 8) * 8
    width = triton.cdiv(logical_width, 8) * 8
    features = c256_full[:logical_height, :logical_width].contiguous()
    del c256_full
    if height != logical_height or width != logical_width:
        features = torch.nn.functional.pad(
            features,
            (0, 0, 0, width - logical_width, 0, height - logical_height),
        ).contiguous()
    rows_total = height * width
    value = features.reshape(rows_total, 256)

    prefix = "block15.layer0"
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
    group_fragments = torch.empty_like(value)
    q = torch.empty_like(value)
    k = torch.empty_like(value)
    v = torch.empty_like(value)
    attended = torch.empty_like(value)
    fused_output = torch.empty_like(value)
    packed_q = packed_k = packed_v = packed_attended = packed_output = None
    if args.layout_mode == "packed":
        windows = (height // 8) * (width // 8)
        packed_q = torch.empty((windows, 64, 256), device="cuda", dtype=torch.float16)
        packed_k = torch.empty_like(packed_q)
        packed_v = torch.empty_like(packed_q)
        packed_attended = torch.empty_like(value)
        packed_output = torch.empty_like(value)

    def launch_mlp() -> None:
        _fused_c256_group_mlp[(triton.cdiv(rows_total, args.mlp_block_m), 8)](
            value,
            expand,
            branch,
            group_fragments,
            rows_total,
            args.mlp_block_m,
            num_warps=4,
            num_stages=1,
            enable_fp_fusion=False,
        )
        _project_c256_ffn[(triton.cdiv(rows_total, args.mlp_block_m),)](
            value,
            group_fragments,
            output_projection,
            ffn_cosine,
            fused_ffn,
            rows_total,
            args.mlp_block_m,
            num_warps=4,
            num_stages=1,
            enable_fp_fusion=False,
        )

    def launch_attention() -> None:
        _project_c256_qkv[(triton.cdiv(rows_total, 16),)](
            fused_ffn,
            qkv_weight,
            attention_scale,
            q,
            k,
            v,
            rows_total,
            16,
            num_warps=4,
            num_stages=2,
            enable_fp_fusion=False,
        )
        windows = (height // 8) * (width // 8)
        tiles = 64 // args.attention_block_m
        if args.attention_mode == "fused":
            _attention_c256_windows[(windows * tiles,)](
                q,
                k,
                v,
                fused_ffn,
                attention_bias,
                attention_projection,
                attention_cosine,
                fused_output,
                width,
                width // 8,
                args.attention_block_m,
                tiles,
                num_warps=4,
                num_stages=1,
                enable_fp_fusion=False,
            )
        else:
            _attention_c256_windows_only[(windows * tiles * 8,)](
                q,
                k,
                v,
                attention_bias,
                attended,
                width,
                width // 8,
                args.attention_block_m,
                tiles,
                num_warps=4,
                num_stages=1,
                enable_fp_fusion=False,
            )
            _project_c256_attention[(triton.cdiv(rows_total, 16),)](
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

    def launch_packed_attention() -> None:
        if packed_q is None or packed_k is None or packed_v is None or packed_attended is None or packed_output is None:
            raise RuntimeError("packed buffers were not allocated")
        windows = (height // 8) * (width // 8)
        tiles = 64 // args.attention_block_m
        _project_c256_qkv_window_packed[(windows * tiles,)](
            fused_ffn,
            qkv_weight,
            attention_scale,
            packed_q,
            packed_k,
            packed_v,
            width,
            width // 8,
            args.attention_block_m,
            num_warps=4,
            num_stages=2,
            enable_fp_fusion=False,
        )
        _attention_c256_windows_only_packed[(windows * tiles * 8,)](
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
        _project_c256_attention[(triton.cdiv(rows_total, 16),)](
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
        launch_mlp()
        launch_attention()

    def launch_packed_block() -> None:
        launch_mlp()
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
    fused_mlp_times = [_event_time(launch_mlp) for _ in range(args.iterations)]
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
        eager_ffn = recovered_model.branched_feed_forward(
            value,
            expansion_weight=expand,
            branch_projection_weight=branch,
            output_projection_weight=output_projection,
        )
        eager_ffn = recovered_model.e4m3_round_trip(
            recovered_model.cosine_residual(value, eager_ffn, ffn_cosine)
        )
        eager_image = eager_ffn.reshape(1, height, width, 256)
        attended = recovered_model.window_attention(
            eager_image,
            qkv_weight=qkv_weight,
            attention_scale=attention_scale,
            attention_bias=attention_bias.unsqueeze(0),
            projection_weight=attention_projection,
            head_count=8,
            window_size=8,
            window_origin=(0, 0),
        )
        return recovered_model.cosine_residual(
            eager_ffn,
            attended.reshape(rows_total, 256),
            attention_cosine,
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

    fused_compare = fused_output.reshape(1, height, width, 256)[:, :logical_height, :logical_width].reshape(-1, 256)
    eager_compare = eager_output.reshape(1, height, width, 256)[:, :logical_height, :logical_width].reshape(-1, 256)
    difference = (fused_compare.float() - eager_compare.float()).abs()
    packed_difference = None
    packed_vs_row_major = None
    if args.layout_mode == "packed":
        launch_packed_block()
        torch.cuda.synchronize()
        packed_compare = packed_output.reshape(1, height, width, 256)[:, :logical_height, :logical_width].reshape(-1, 256)
        packed_difference = (packed_compare.float() - eager_compare.float()).abs()
        packed_vs_row_major = (packed_compare.float() - fused_compare.float()).abs()
    percentile_sample = difference.reshape(-1)[::max(1, difference.numel() // 1_000_000)]
    args.output.expanduser().resolve().mkdir(parents=True, exist_ok=True)
    result = {
        "schema": "opennr-native-style-c256-block-cuda-probe-v1",
        "scope": "recovered block15 C256 branched MLP plus eight-head QKV/window-attention/projection/residual; offline only",
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
            "recovered_stages": "block0 -> average_pool2 -> blocks1-3 -> block4 downsample -> blocks5-7 -> block8 downsample -> blocks9-13 -> block14 downsample",
            "input_resolution": [source_width, source_height],
        },
        "input": {
            "stage": "block15 C256",
            "probe_resolution": [logical_width, logical_height],
            "kernel_resolution": [width, height],
            "probe_region": "top_left" if (logical_height != int((source_height + 15) // 16) or logical_width != int((source_width + 15) // 16)) else "full_c256_stage",
            "tokens": int(logical_height * logical_width),
            "kernel_tokens": int(rows_total),
            "window_count": int((height // 8) * (width // 8)),
            "padding_right": int(width - logical_width),
            "padding_bottom": int(height - logical_height),
            "channels": 256,
            "heads": 8,
        },
        "kernel": {
            "block": "block15.layer0",
            "operation": "C256 branched MLP + eight-head QKV/normalization + 8x8 attention + E4M3 value publication + projection + residual",
            "mlp_block_m": args.mlp_block_m,
            "attention_block_m": args.attention_block_m,
            "attention_mode": args.attention_mode,
            "layout_mode": args.layout_mode,
            "qkv_block_m": 16,
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
            "packed_vs_row_major_mae": (
                float(packed_vs_row_major.mean().item())
                if packed_vs_row_major is not None
                else None
            ),
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
        "interpretation": "One pooled C256 block proof only; not the NVIDIA DLL, full 71-block timing, exact native parity, temporal/stereo validation, or VR readiness.",
    }
    (args.output.expanduser().resolve() / "result.json").write_text(
        json.dumps(result, indent=2), encoding="utf-8"
    )
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
