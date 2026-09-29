"""Benchmark a fused reduced-neural affine resolve with Triton.

The kernel reads the full-resolution RGB source and the reduced native input
and output, performs the matched bilinear residual, applies the fitted affine
correction, and writes the final RGB in one dispatch.  This is an offline
runtime-shape probe; it is not a replacement for the native Feature 18
integration or a live VR test.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import torch
import triton
import triton.language as tl

from benchmark_scale_resolve_student_20260912 import read_rgb8


FULL_WIDTH = 2496
FULL_HEIGHT = 2688


@triton.jit
def bilinear_sample(
    ptr,
    channel,
    p00,
    p01,
    p10,
    p11,
    wx,
    wy,
    small_plane,
    valid,
):
    base = channel * small_plane
    v00 = tl.load(ptr + base + p00, mask=valid, other=0.0).to(tl.float32)
    v01 = tl.load(ptr + base + p01, mask=valid, other=0.0).to(tl.float32)
    v10 = tl.load(ptr + base + p10, mask=valid, other=0.0).to(tl.float32)
    v11 = tl.load(ptr + base + p11, mask=valid, other=0.0).to(tl.float32)
    top = v00 + wx * (v01 - v00)
    bottom = v10 + wx * (v11 - v10)
    return top + wy * (bottom - top)


@triton.jit
def fused_affine_resolve_kernel(
    full_ptr,
    small_input_ptr,
    small_output_ptr,
    beta_ptr,
    result_ptr,
    full_height,
    full_width,
    small_height,
    small_width,
    n_pixels,
    BLOCK: tl.constexpr,
):
    offsets = tl.program_id(0) * BLOCK + tl.arange(0, BLOCK)
    valid = offsets < n_pixels
    y = offsets // full_width
    x = offsets - y * full_width

    fy = (y.to(tl.float32) + 0.5) * small_height / full_height - 0.5
    fx = (x.to(tl.float32) + 0.5) * small_width / full_width - 0.5
    fy = tl.maximum(fy, 0.0)
    fx = tl.maximum(fx, 0.0)
    y0 = tl.minimum(tl.cast(tl.floor(fy), tl.int32), small_height - 1)
    x0 = tl.minimum(tl.cast(tl.floor(fx), tl.int32), small_width - 1)
    y1 = tl.minimum(y0 + 1, small_height - 1)
    x1 = tl.minimum(x0 + 1, small_width - 1)
    wy = fy - y0.to(tl.float32)
    wx = fx - x0.to(tl.float32)

    full_plane = full_height * full_width
    small_plane = small_height * small_width
    p00 = y0 * small_width + x0
    p01 = y0 * small_width + x1
    p10 = y1 * small_width + x0
    p11 = y1 * small_width + x1
    full_p = y * full_width + x

    rgb_r = tl.load(full_ptr + full_p, mask=valid, other=0.0).to(tl.float32)
    rgb_g = tl.load(full_ptr + full_plane + full_p, mask=valid, other=0.0).to(tl.float32)
    rgb_b = tl.load(full_ptr + 2 * full_plane + full_p, mask=valid, other=0.0).to(tl.float32)
    edit_r = bilinear_sample(
        small_output_ptr, 0, p00, p01, p10, p11, wx, wy, small_plane, valid
    ) - bilinear_sample(small_input_ptr, 0, p00, p01, p10, p11, wx, wy, small_plane, valid)
    edit_g = bilinear_sample(
        small_output_ptr, 1, p00, p01, p10, p11, wx, wy, small_plane, valid
    ) - bilinear_sample(small_input_ptr, 1, p00, p01, p10, p11, wx, wy, small_plane, valid)
    edit_b = bilinear_sample(
        small_output_ptr, 2, p00, p01, p10, p11, wx, wy, small_plane, valid
    ) - bilinear_sample(small_input_ptr, 2, p00, p01, p10, p11, wx, wy, small_plane, valid)

    b0 = tl.load(beta_ptr + 0 * 3 + 0).to(tl.float32)
    b1 = tl.load(beta_ptr + 0 * 3 + 1).to(tl.float32)
    b2 = tl.load(beta_ptr + 0 * 3 + 2).to(tl.float32)
    beta_rgb_r = tl.load(beta_ptr + 1 * 3 + 0).to(tl.float32)
    beta_rgb_g = tl.load(beta_ptr + 2 * 3 + 0).to(tl.float32)
    beta_rgb_b = tl.load(beta_ptr + 3 * 3 + 0).to(tl.float32)
    beta_edit_r = tl.load(beta_ptr + 4 * 3 + 0).to(tl.float32)
    beta_edit_g = tl.load(beta_ptr + 5 * 3 + 0).to(tl.float32)
    beta_edit_b = tl.load(beta_ptr + 6 * 3 + 0).to(tl.float32)
    correction_r = b0 + beta_rgb_r * rgb_r + beta_rgb_g * rgb_g + beta_rgb_b * rgb_b
    correction_r += beta_edit_r * edit_r + beta_edit_g * edit_g + beta_edit_b * edit_b

    b0 = tl.load(beta_ptr + 0 * 3 + 1).to(tl.float32)
    beta_rgb_r = tl.load(beta_ptr + 1 * 3 + 1).to(tl.float32)
    beta_rgb_g = tl.load(beta_ptr + 2 * 3 + 1).to(tl.float32)
    beta_rgb_b = tl.load(beta_ptr + 3 * 3 + 1).to(tl.float32)
    beta_edit_r = tl.load(beta_ptr + 4 * 3 + 1).to(tl.float32)
    beta_edit_g = tl.load(beta_ptr + 5 * 3 + 1).to(tl.float32)
    beta_edit_b = tl.load(beta_ptr + 6 * 3 + 1).to(tl.float32)
    correction_g = b0 + beta_rgb_r * rgb_r + beta_rgb_g * rgb_g + beta_rgb_b * rgb_b
    correction_g += beta_edit_r * edit_r + beta_edit_g * edit_g + beta_edit_b * edit_b

    b0 = tl.load(beta_ptr + 0 * 3 + 2).to(tl.float32)
    beta_rgb_r = tl.load(beta_ptr + 1 * 3 + 2).to(tl.float32)
    beta_rgb_g = tl.load(beta_ptr + 2 * 3 + 2).to(tl.float32)
    beta_rgb_b = tl.load(beta_ptr + 3 * 3 + 2).to(tl.float32)
    beta_edit_r = tl.load(beta_ptr + 4 * 3 + 2).to(tl.float32)
    beta_edit_g = tl.load(beta_ptr + 5 * 3 + 2).to(tl.float32)
    beta_edit_b = tl.load(beta_ptr + 6 * 3 + 2).to(tl.float32)
    correction_b = b0 + beta_rgb_r * rgb_r + beta_rgb_g * rgb_g + beta_rgb_b * rgb_b
    correction_b += beta_edit_r * edit_r + beta_edit_g * edit_g + beta_edit_b * edit_b

    result_r = tl.maximum(tl.minimum(rgb_r + correction_r, 1.0), 0.0)
    result_g = tl.maximum(tl.minimum(rgb_g + correction_g, 1.0), 0.0)
    result_b = tl.maximum(tl.minimum(rgb_b + correction_b, 1.0), 0.0)
    tl.store(result_ptr + full_p, result_r, mask=valid)
    tl.store(result_ptr + full_plane + full_p, result_g, mask=valid)
    tl.store(result_ptr + 2 * full_plane + full_p, result_b, mask=valid)


def launch(full, small_input, small_output, beta, block: int = 256, warps: int = 4):
    result = torch.empty_like(full)
    grid = (triton.cdiv(FULL_HEIGHT * FULL_WIDTH, block),)
    fused_affine_resolve_kernel[grid](
        full,
        small_input,
        small_output,
        beta,
        result,
        FULL_HEIGHT,
        FULL_WIDTH,
        small_input.shape[-2],
        small_input.shape[-1],
        FULL_HEIGHT * FULL_WIDTH,
        BLOCK=block,
        num_warps=warps,
    )
    return result


def stats(values: list[float]) -> dict[str, float]:
    array = np.asarray(values, dtype=np.float64)
    return {
        "median_ms": float(np.percentile(array, 50)),
        "p95_ms": float(np.percentile(array, 95)),
        "min_ms": float(np.min(array)),
        "max_ms": float(np.max(array)),
    }


def time_pair(items, beta, block, warps, warmup, iterations):
    def run():
        for full, small_input, small_output in items:
            launch(full, small_input, small_output, beta, block, warps)

    with torch.inference_mode():
        for _ in range(warmup):
            run()
    torch.cuda.synchronize()
    values = []
    with torch.inference_mode():
        for _ in range(iterations):
            start = torch.cuda.Event(enable_timing=True)
            end = torch.cuda.Event(enable_timing=True)
            start.record()
            run()
            end.record()
            end.synchronize()
            values.append(float(start.elapsed_time(end)))
    return stats(values)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--replay-root", type=Path, required=True)
    parser.add_argument("--affine-result", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--frame", type=int, default=1)
    parser.add_argument(
        "--validate-frames",
        type=int,
        nargs="*",
        default=[],
        help="also compute fused-vs-teacher quality for these saved replay frames",
    )
    parser.add_argument(
        "--temporal-frames",
        type=int,
        nargs="*",
        default=[],
        help="compute frame-to-frame delta statistics for these saved replay frames",
    )
    parser.add_argument("--block", type=int, default=256)
    parser.add_argument("--warps", type=int, default=4)
    parser.add_argument("--warmup", type=int, default=10)
    parser.add_argument("--iterations", type=int, default=40)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(f"refusing to overwrite {args.output}")
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is required")

    replay_root = args.replay_root.resolve()
    manifest = json.loads((replay_root / "input_manifest.json").read_text(encoding="utf-8"))
    small_width, small_height = (int(value) for value in manifest["network_dimensions"])
    sequence = Path(manifest["sequence"])
    frame_dir = sequence / "frames" / f"frame_{args.frame:08d}"
    replay_frame = replay_root / f"frame_{args.frame:08d}"
    affine = json.loads(args.affine_result.resolve().read_text(encoding="utf-8"))
    beta = torch.tensor(affine["coefficients"], device="cuda", dtype=torch.float32).contiguous()

    items = []
    for eye in range(2):
        full = read_rgb8(
            frame_dir / f"input_eye{eye}_full.raw.bin", FULL_WIDTH, FULL_HEIGHT
        ).cuda().contiguous()
        small_input = read_rgb8(
            replay_frame / f"input_eye{eye}.rgba", small_width, small_height
        ).cuda().contiguous()
        small_output = read_rgb8(
            replay_frame / f"teacher_eye{eye}.rgba", small_width, small_height
        ).cuda().contiguous()
        items.append((full, small_input, small_output))

    # Compile and validate against the same formula in the affine result.
    with torch.inference_mode():
        fused = launch(items[0][0], items[0][1], items[0][2], beta, args.block, args.warps)
        torch.cuda.synchronize()
        fused_again = launch(items[0][0], items[0][1], items[0][2], beta, args.block, args.warps)
        torch.cuda.synchronize()
    if not bool(torch.isfinite(fused).all().item()):
        raise RuntimeError("fused output is non-finite")
    result = {
        "schema": "opennr-affine-fused-triton-v1",
        "replay_root": str(replay_root),
        "affine_result": str(args.affine_result.resolve()),
        "frame": args.frame,
        "scale_percent": int(manifest["scale_percent"]),
        "full_shape": [FULL_WIDTH, FULL_HEIGHT],
        "network_shape": [small_width, small_height],
        "device": torch.cuda.get_device_name(),
        "torch": torch.__version__,
        "triton": triton.__version__,
        "launch": {"block": args.block, "warps": args.warps},
        "timing_scope": "resident CUDA tensors; one fused bilinear affine resolve dispatch per eye; no input conversion, copies, native pass or compositor",
        "timing_fp32": time_pair(
            [(a.float(), b.float(), c.float()) for a, b, c in items],
            beta,
            args.block,
            args.warps,
            args.warmup,
            args.iterations,
        ),
        "timing_fp16": time_pair(
            [(a.half(), b.half(), c.half()) for a, b, c in items],
            beta,
            args.block,
            args.warps,
            args.warmup,
            args.iterations,
        ),
        "output_finite": bool(torch.isfinite(fused).all().item()),
        "repeat_max_abs_difference": float((fused - fused_again).abs().max().item()),
        "promotion": False,
        "live_runtime_tested": False,
    }
    if args.validate_frames:
        quality_records = []
        for frame_id in args.validate_frames:
            validation_frame_dir = sequence / "frames" / f"frame_{frame_id:08d}"
            validation_replay_frame = replay_root / f"frame_{frame_id:08d}"
            for eye in range(2):
                full = read_rgb8(
                    validation_frame_dir / f"input_eye{eye}_full.raw.bin",
                    FULL_WIDTH,
                    FULL_HEIGHT,
                ).cuda().contiguous().half()
                small_input = read_rgb8(
                    validation_replay_frame / f"input_eye{eye}.rgba",
                    small_width,
                    small_height,
                ).cuda().contiguous().half()
                small_output = read_rgb8(
                    validation_replay_frame / f"teacher_eye{eye}.rgba",
                    small_width,
                    small_height,
                ).cuda().contiguous().half()
                teacher = read_rgb8(
                    validation_frame_dir / f"teacher_eye{eye}_full.raw.bin",
                    FULL_WIDTH,
                    FULL_HEIGHT,
                ).cuda().contiguous()
                with torch.inference_mode():
                    prediction = launch(
                        full, small_input, small_output, beta, args.block, args.warps
                    )
                naive_edit = torch.nn.functional.interpolate(
                    small_output - small_input,
                    size=(FULL_HEIGHT, FULL_WIDTH),
                    mode="bilinear",
                    align_corners=False,
                )
                naive = (full + naive_edit).clamp(0.0, 1.0)
                prediction_error = prediction.float() - teacher
                naive_error = naive.float() - teacher
                quality_records.append(
                    {
                        "frame": frame_id,
                        "eye": eye,
                        "fused_mae": float(prediction_error.abs().mean().item()),
                        "naive_mae": float(naive_error.abs().mean().item()),
                        "identity_mae": float((full.float() - teacher).abs().mean().item()),
                        "gain_vs_naive": float(
                            naive_error.abs().mean().item() - prediction_error.abs().mean().item()
                        ),
                        "finite": bool(torch.isfinite(prediction).all().item()),
                    }
                )
        result["quality"] = {
            "records": quality_records,
            "fused_mae_mean": float(np.mean([item["fused_mae"] for item in quality_records])),
            "naive_mae_mean": float(np.mean([item["naive_mae"] for item in quality_records])),
            "gain_vs_naive_mean": float(
                np.mean([item["gain_vs_naive"] for item in quality_records])
            ),
        }
    if len(args.temporal_frames) >= 2:
        temporal_records = []
        for eye in range(2):
            previous_fused = None
            previous_naive = None
            previous_teacher = None
            fused_deltas = []
            naive_deltas = []
            teacher_deltas = []
            fused_delta_errors = []
            naive_delta_errors = []
            for frame_id in args.temporal_frames:
                temporal_frame_dir = sequence / "frames" / f"frame_{frame_id:08d}"
                temporal_replay_frame = replay_root / f"frame_{frame_id:08d}"
                full = read_rgb8(
                    temporal_frame_dir / f"input_eye{eye}_full.raw.bin",
                    FULL_WIDTH,
                    FULL_HEIGHT,
                ).cuda().contiguous().half()
                small_input = read_rgb8(
                    temporal_replay_frame / f"input_eye{eye}.rgba",
                    small_width,
                    small_height,
                ).cuda().contiguous().half()
                small_output = read_rgb8(
                    temporal_replay_frame / f"teacher_eye{eye}.rgba",
                    small_width,
                    small_height,
                ).cuda().contiguous().half()
                teacher = read_rgb8(
                    temporal_frame_dir / f"teacher_eye{eye}_full.raw.bin",
                    FULL_WIDTH,
                    FULL_HEIGHT,
                ).cuda().contiguous()
                with torch.inference_mode():
                    current_fused = launch(
                        full, small_input, small_output, beta, args.block, args.warps
                    )
                    current_naive = (
                        full
                        + torch.nn.functional.interpolate(
                            small_output - small_input,
                            size=(FULL_HEIGHT, FULL_WIDTH),
                            mode="bilinear",
                            align_corners=False,
                        )
                    ).clamp(0.0, 1.0)
                if previous_fused is not None:
                    fused_delta = current_fused.float() - previous_fused.float()
                    naive_delta = current_naive.float() - previous_naive.float()
                    teacher_delta = teacher - previous_teacher
                    fused_deltas.append(float(fused_delta.abs().mean().item()))
                    naive_deltas.append(float(naive_delta.abs().mean().item()))
                    teacher_deltas.append(float(teacher_delta.abs().mean().item()))
                    fused_delta_errors.append(float((fused_delta - teacher_delta).abs().mean().item()))
                    naive_delta_errors.append(float((naive_delta - teacher_delta).abs().mean().item()))
                previous_fused = current_fused
                previous_naive = current_naive
                previous_teacher = teacher
            temporal_records.append(
                {
                    "eye": eye,
                    "fused_delta_mae_mean": float(np.mean(fused_deltas)),
                    "naive_delta_mae_mean": float(np.mean(naive_deltas)),
                    "teacher_delta_mae_mean": float(np.mean(teacher_deltas)),
                    "fused_vs_teacher_delta_error_mean": float(np.mean(fused_delta_errors)),
                    "naive_vs_teacher_delta_error_mean": float(np.mean(naive_delta_errors)),
                }
            )
        result["temporal"] = {
            "frames": args.temporal_frames,
            "records": temporal_records,
            "fused_delta_mae_mean": float(
                np.mean([item["fused_delta_mae_mean"] for item in temporal_records])
            ),
            "naive_delta_mae_mean": float(
                np.mean([item["naive_delta_mae_mean"] for item in temporal_records])
            ),
            "teacher_delta_mae_mean": float(
                np.mean([item["teacher_delta_mae_mean"] for item in temporal_records])
            ),
            "fused_vs_teacher_delta_error_mean": float(
                np.mean([item["fused_vs_teacher_delta_error_mean"] for item in temporal_records])
            ),
            "naive_vs_teacher_delta_error_mean": float(
                np.mean([item["naive_vs_teacher_delta_error_mean"] for item in temporal_records])
            ),
        }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
