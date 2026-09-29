"""Probe a fused C32 projection/window-attention path on recovered DLSS5 data.

This is an offline CUDA backend experiment.  It uses one real Skyrim feature
tensor and the recovered logical weights, but it does not call the native
NVIDIA DLL and it does not modify Skyrim, MGO, or any packaged runtime.

The probe covers one block's attention half:

    C32 input -> Q/K/V projection and cosine publication -> 8x8 attention
    -> E4M3 value publication -> output projection -> residual

The feed-forward input to this stage is produced by the direct-FP8 eager
control from ``probe_native_style_c32_cuda.py``.  The comparison is therefore
an implementation control, not native NVIDIA parity.
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

from probe_native_style_c32_cuda import _reference_block, _round_fp8_half


COSINE_NORM_FLOOR = 0.00006198883056640625


@triton.jit
def _half_mul(left, right):
    return (left.to(tl.float32) * right.to(tl.float32)).to(tl.float16)


@triton.jit
def _half_add(left, right):
    return (left.to(tl.float32) + right.to(tl.float32)).to(tl.float16)


@triton.jit
def _half_fma(left, right, accumulator):
    return (
        left.to(tl.float32) * right.to(tl.float32) + accumulator.to(tl.float32)
    ).to(tl.float16)


@triton.jit
def _normalize_c32(value, BM: tl.constexpr, NORM_FLOOR: tl.constexpr):
    lane8 = tl.arange(0, 8)
    x0 = tl.gather(value, tl.broadcast_to(lane8[None, :], (BM, 8)), 1)
    x8 = tl.gather(value, tl.broadcast_to((lane8 + 8)[None, :], (BM, 8)), 1)
    x16 = tl.gather(value, tl.broadcast_to((lane8 + 16)[None, :], (BM, 8)), 1)
    x24 = tl.gather(value, tl.broadcast_to((lane8 + 24)[None, :], (BM, 8)), 1)
    first = _half_fma(x8, x8, _half_mul(x0, x0))
    second = _half_fma(x24, x24, _half_mul(x16, x16))
    total = _half_add(first, second)
    for mask in tl.static_range(3):
        other = tl.gather(
            total,
            tl.broadcast_to((lane8 ^ (4 >> mask))[None, :], (BM, 8)),
            1,
        )
        total = _half_add(total, other)
    denominator = tl.gather(
        total,
        tl.full((BM, 1), 0, tl.int32),
        1,
    )
    denominator = tl.maximum(denominator, NORM_FLOOR)
    reciprocal = tl.rsqrt(denominator.to(tl.float32)).to(tl.float16)
    return _half_mul(value, reciprocal)


@triton.jit
def _project_qkv(X, WEIGHT, SCALE, Q, K, V, rows_total: tl.constexpr, BM: tl.constexpr):
    rows = tl.program_id(0) * BM + tl.arange(0, BM)
    channels = tl.arange(0, 32)
    mask = rows[:, None] < rows_total
    x = tl.load(X + rows[:, None] * 32 + channels[None, :], mask=mask, other=0)
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
    q = _half_mul(q, scale)
    tl.store(Q + rows[:, None] * 32 + channels[None, :], _round_fp8_half(q), mask=mask)
    tl.store(K + rows[:, None] * 32 + channels[None, :], _round_fp8_half(k), mask=mask)
    tl.store(V + rows[:, None] * 32 + channels[None, :], _round_fp8_half(v), mask=mask)


@triton.jit
def _approx_exp(value, BM: tl.constexpr):
    """Apply the recovered two-half packed affine exponential exactly."""
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
def _attention_windows(
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
    channels = tl.arange(0, 32)
    row_mask = local_row < 64

    window_row = window // COLUMNS
    window_col = window % COLUMNS
    row_y = window_row * 8 + local_row // 8
    row_x = window_col * 8 + local_row % 8
    key_y = window_row * 8 + local_key // 8
    key_x = window_col * 8 + local_key % 8
    row_index = row_y * WIDTH + row_x
    key_index = key_y * WIDTH + key_x

    q = tl.load(Q + row_index[:, None] * 32 + channels[None, :], mask=row_mask[:, None], other=0)
    # Load K transposed so the dot is [BM,32] x [32,64].
    k = tl.load(K + key_index[None, :] * 32 + channels[:, None])
    v = tl.load(V + key_index[:, None] * 32 + channels[None, :])
    bias = tl.load(BIAS + local_row[:, None] * 64 + local_key[None, :], mask=row_mask[:, None], other=0)

    scores = tl.dot(q, k, out_dtype=tl.float32).to(tl.float16)
    scores = _half_add(scores, bias)
    weights = _approx_exp(scores, BM)
    denominator = tl.sum(weights.to(tl.float32), axis=1).to(tl.float16)
    reciprocal = (1.0 / denominator.to(tl.float32)).to(tl.float16)
    probabilities = _round_fp8_half(_half_mul(weights, reciprocal[:, None]))
    attended = tl.dot(probabilities, v, out_dtype=tl.float32).to(tl.float16)
    attended = _round_fp8_half(attended)

    projection = tl.load(PROJECTION + channels[:, None] * 32 + channels[None, :])
    branch = tl.dot(attended, projection, out_dtype=tl.float32).to(tl.float16)
    x = tl.load(X + row_index[:, None] * 32 + channels[None, :], mask=row_mask[:, None], other=0)
    cosine = tl.load(COSINE + channels)
    result = _half_add(branch, _half_mul(x, cosine[None, :]))
    tl.store(OUT + row_index[:, None] * 32 + channels[None, :], result, mask=row_mask[:, None])


def _select_row(rows: list[dict], split: str, sequence_id: str, frame: int, eye: int) -> dict:
    selected = [
        row
        for row in rows
        if row.get("split") == split
        and str(row.get("sequence_id")) == sequence_id
        and int(row.get("frame_id", -1)) == frame
        and int(row.get("eye", -1)) == eye
    ]
    if len(selected) != 1:
        raise ValueError(f"expected one row, found {len(selected)}")
    return selected[0]


def _event_time(callback) -> float:
    start = torch.cuda.Event(enable_timing=True)
    end = torch.cuda.Event(enable_timing=True)
    start.record()
    callback()
    end.record()
    end.synchronize()
    return float(start.elapsed_time(end))


def _fused_call(q, k, v, x, bias, projection, cosine, out, height, width, block_m):
    windows = (height // 8) * (width // 8)
    tiles = 64 // block_m
    _attention_windows[(tiles * windows,)](
        q,
        k,
        v,
        x,
        bias,
        projection,
        cosine,
        out,
        width,
        width // 8,
        block_m,
        tiles,
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
    parser.add_argument("--block-m", type=int, choices=(16, 32, 64), default=16)
    parser.add_argument("--probe-height", type=int, default=0, help="Optional top-left region height; 0 means full eye")
    parser.add_argument("--probe-width", type=int, default=0, help="Optional top-left region width; 0 means full eye")
    parser.add_argument("--warmup", type=int, default=1)
    parser.add_argument("--iterations", type=int, default=2)
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
    full_features = torch.from_numpy(np.ascontiguousarray(prepared.features)).to("cuda", torch.float16)
    height = args.probe_height or int(full_features.shape[0])
    width = args.probe_width or int(full_features.shape[1])
    if height <= 0 or width <= 0 or height % 8 or width % 8:
        raise ValueError("probe dimensions must be positive multiples of eight")
    if height > full_features.shape[0] or width > full_features.shape[1]:
        raise ValueError("probe dimensions exceed the feature tensor")
    features = full_features[:height, :width].contiguous()
    feature_matrix = features.reshape(height * width, 16)
    feature_rows = feature_matrix.shape[0]

    adapter = weights["block0.layer0.input_adapter_weight"].to("cuda", torch.float16).contiguous()
    value = (feature_matrix @ adapter).contiguous()
    w1 = weights["block0.layer0.weight1"].to("cuda", torch.float16).contiguous()
    w2 = weights["block0.layer0.weight2"].to("cuda", torch.float16).contiguous()
    ffn_cosine = weights["block0.layer0.ffn_cos_skip"].to("cuda", torch.float16).contiguous()
    # The eager control performs only the direct CUDA FP8 publication here.
    ffn_output = _reference_block(value, w1, w2, ffn_cosine, 32768).contiguous()
    torch.cuda.synchronize()

    qkv_weight = weights["block0.layer0.qkv_weight"].to("cuda", torch.float16).contiguous()
    attention_scale = weights["block0.layer0.attn_scale"].to("cuda", torch.float32).contiguous()
    stored_bias = weights["block0.layer0.attn_bias"]
    logical_bias = recovered_model.recover_attention_bias_layout(stored_bias).to("cuda", torch.float16).contiguous()
    projection = weights["block0.layer0.projection_weight"].to("cuda", torch.float16).contiguous()
    attention_cosine = weights["block0.layer0.attn_cos_skip"].to("cuda", torch.float16).contiguous()

    q = torch.empty_like(ffn_output)
    k = torch.empty_like(ffn_output)
    v = torch.empty_like(ffn_output)
    fused_output = torch.empty_like(ffn_output)

    compile_started = time.perf_counter()
    _project_qkv[(triton.cdiv(feature_rows, 32),)](
        ffn_output,
        qkv_weight,
        attention_scale,
        q,
        k,
        v,
        feature_rows,
        32,
        num_warps=4,
        num_stages=2,
        enable_fp_fusion=False,
    )
    _fused_call(q, k, v, ffn_output, logical_bias[0], projection, attention_cosine, fused_output, height, width, args.block_m)
    torch.cuda.synchronize()
    compile_seconds = time.perf_counter() - compile_started

    for _ in range(args.warmup):
        _project_qkv[(triton.cdiv(feature_rows, 32),)](
            ffn_output, qkv_weight, attention_scale, q, k, v, feature_rows, 32,
            num_warps=4, num_stages=2, enable_fp_fusion=False,
        )
        _fused_call(q, k, v, ffn_output, logical_bias[0], projection, attention_cosine, fused_output, height, width, args.block_m)
    torch.cuda.synchronize()
    fused_times = [
        _event_time(lambda: (
            _project_qkv[(triton.cdiv(feature_rows, 32),)](
                ffn_output, qkv_weight, attention_scale, q, k, v, feature_rows, 32,
                num_warps=4, num_stages=2, enable_fp_fusion=False,
            ),
            _fused_call(q, k, v, ffn_output, logical_bias[0], projection, attention_cosine, fused_output, height, width, args.block_m),
        ))
        for _ in range(args.iterations)
    ]

    original_round_trip = recovered_model.e4m3_round_trip

    def direct_fp8(value_tensor):
        return value_tensor.clamp(-448.0, 448.0).to(torch.float8_e4m3fn).to(value_tensor.dtype)

    recovered_model.e4m3_round_trip = direct_fp8
    try:
        ffn_image = ffn_output.reshape(1, height, width, 32)

        def eager_attention():
            branch = recovered_model.window_attention(
                ffn_image,
                qkv_weight=qkv_weight,
                attention_scale=attention_scale,
                attention_bias=logical_bias,
                projection_weight=projection,
                head_count=1,
                window_size=8,
                window_origin=(0, 0),
            )
            return branch.reshape(feature_rows, 32) + ffn_output * attention_cosine

        eager_output = eager_attention()
        torch.cuda.synchronize()
        for _ in range(args.warmup):
            eager_output = eager_attention()
        torch.cuda.synchronize()
        eager_times = [_event_time(eager_attention) for _ in range(args.iterations)]
        eager_output = eager_attention().contiguous()
        torch.cuda.synchronize()
    finally:
        recovered_model.e4m3_round_trip = original_round_trip

    difference = (fused_output.float() - eager_output.float()).abs()
    percentile_sample = difference.reshape(-1)[::max(1, difference.numel() // 1_000_000)]
    args.output.expanduser().resolve().mkdir(parents=True, exist_ok=True)
    result = {
        "schema": "opennr-native-style-c32-attention-cuda-probe-v1",
        "scope": "one block0 C32 QKV/normalization/window-attention/projection/residual path; offline only",
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
            "probe_resolution": [width, height],
            "probe_region": "top_left" if (height != source_height or width != source_width) else "full_eye",
            "tokens": int(feature_rows),
            "window_count": int((height // 8) * (width // 8)),
        },
        "kernel": {
            "block": "block0.layer0",
            "operation": "QKV projection + C32 cosine publication + 8x8 attention + E4M3 value publication + projection + residual",
            "attention_block_m": args.block_m,
            "projection_block_m": 32,
            "warps": 4,
            "stages": 2,
            "triton": triton.__version__,
        },
        "timing_ms": {
            "compile_and_first_run": compile_seconds * 1000.0,
            "fused_median": float(np.median(fused_times)),
            "fused_p95": float(np.percentile(fused_times, 95.0)),
            "fused_samples": fused_times,
            "eager_direct_fp8_median": float(np.median(eager_times)),
            "eager_direct_fp8_p95": float(np.percentile(eager_times, 95.0)),
            "eager_samples": eager_times,
        },
        "speedup": float(np.median(eager_times) / np.median(fused_times)),
        "drift_vs_eager_direct_fp8": {
            "mae": float(difference.mean().item()),
            "p99_sample": float(torch.quantile(percentile_sample, 0.99).item()),
            "p999_sample": float(torch.quantile(percentile_sample, 0.999).item()),
            "max": float(difference.max().item()),
            "changed_fraction_gt_1e-3": float((difference > 1e-3).float().mean().item()),
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
        "interpretation": "This is a backend proof for one block. It is not the NVIDIA DLL, full 71-block timing, exact native parity, temporal/stereo validation, or VR readiness.",
    }
    (args.output.expanduser().resolve() / "result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
