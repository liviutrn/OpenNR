"""Fit and benchmark a very cheap affine scale-resolve baseline.

The fitted resolver is deliberately restricted to a per-pixel affine
correction over ``[1, rgb, upsampled_edit]``.  It is a lower-complexity
reference for deciding whether a learned full-resolution resolver can fit a
VR frame budget.  It is not a temporal or VR acceptance test.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as F

from benchmark_scale_resolve_student_20260912 import read_rgb8
from train_scale_resolve_student_20260912 import load_item


FULL_WIDTH = 2496
FULL_HEIGHT = 2688


def metric(pred: np.ndarray, target: np.ndarray, source: np.ndarray) -> dict[str, float]:
    error = pred - target
    identity_error = source - target
    mae = float(np.abs(error).mean())
    rmse = float(np.sqrt(np.mean(error * error)))
    identity_mae = float(np.abs(identity_error).mean())
    return {
        "mae": mae,
        "rmse": rmse,
        "identity_mae": identity_mae,
        "improvement_vs_identity_mae": identity_mae - mae,
        "psnr_db": float(20.0 * np.log10(1.0 / max(rmse, 1e-12))),
    }


def flat_arrays(
    replay_root: Path,
    sequence: Path,
    frame_id: int,
    eye: int,
    small_width: int,
    small_height: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    source, teacher, edit, _ = load_item(
        replay_root,
        sequence,
        frame_id,
        eye,
        small_width,
        small_height,
        torch.device("cpu"),
        False,
    )
    source_array = source[0].numpy().transpose(1, 2, 0).reshape(-1, 3).astype(np.float64)
    teacher_array = teacher[0].numpy().transpose(1, 2, 0).reshape(-1, 3).astype(np.float64)
    edit_array = edit[0].numpy().transpose(1, 2, 0).reshape(-1, 3).astype(np.float64)
    return source_array, teacher_array, edit_array


def fit_coefficients(
    replay_root: Path,
    sequence: Path,
    frames: list[int],
    small_width: int,
    small_height: int,
    chunk_rows: int = 256,
) -> np.ndarray:
    normal = np.zeros((7, 7), dtype=np.float64)
    cross = np.zeros((7, 3), dtype=np.float64)
    pixels_per_row = FULL_WIDTH
    chunk_pixels = chunk_rows * pixels_per_row
    for frame_id in frames:
        for eye in range(2):
            source, teacher, edit = flat_arrays(
                replay_root, sequence, frame_id, eye, small_width, small_height
            )
            for start in range(0, source.shape[0], chunk_pixels):
                stop = min(start + chunk_pixels, source.shape[0])
                rgb = source[start:stop]
                delta = edit[start:stop]
                features = np.empty((stop - start, 7), dtype=np.float64)
                features[:, 0] = 1.0
                features[:, 1:4] = rgb
                features[:, 4:7] = delta
                normal += features.T @ features
                cross += features.T @ (teacher[start:stop] - rgb)
    return np.linalg.solve(normal + 1e-8 * np.eye(7), cross)


def evaluate(
    replay_root: Path,
    sequence: Path,
    frames: list[int],
    small_width: int,
    small_height: int,
    beta: np.ndarray,
) -> dict[str, object]:
    records: list[dict[str, object]] = []
    for frame_id in frames:
        for eye in range(2):
            source, teacher, edit = flat_arrays(
                replay_root, sequence, frame_id, eye, small_width, small_height
            )
            features = np.concatenate(
                (np.ones((source.shape[0], 1), dtype=np.float64), source, edit), axis=1
            )
            predicted = np.clip(source + features @ beta, 0.0, 1.0)
            naive = np.clip(source + edit, 0.0, 1.0)
            records.append(
                {
                    "frame_id": frame_id,
                    "eye": eye,
                    "naive": metric(naive, teacher, source),
                    "affine": metric(predicted, teacher, source),
                }
            )
    naive_mae = [float(record["naive"]["mae"]) for record in records]
    affine_mae = [float(record["affine"]["mae"]) for record in records]
    return {
        "sample_count": len(records),
        "records": records,
        "naive_mae_mean": float(np.mean(naive_mae)),
        "affine_mae_mean": float(np.mean(affine_mae)),
        "improvement_vs_naive_mae": float(np.mean(naive_mae) - np.mean(affine_mae)),
        "affine_better_than_naive_samples": int(sum(a < n for a, n in zip(affine_mae, naive_mae))),
    }


def timed_pair(
    rgb_items: list[tuple[torch.Tensor, torch.Tensor]],
    beta: torch.Tensor,
    affine: bool,
    dtype: torch.dtype,
    warmup: int,
    iterations: int,
) -> dict[str, float]:
    items = [(rgb.to(dtype=dtype), edit.to(dtype=dtype)) for rgb, edit in rgb_items]
    beta = beta.to(dtype=dtype)

    def run() -> None:
        for rgb, edit in items:
            if affine:
                ones = torch.ones_like(rgb[:, :1])
                features = torch.cat((ones, rgb, edit), dim=1)
                correction = F.conv2d(features, beta.view(3, 7, 1, 1))
                (rgb + correction).clamp(0.0, 1.0)
            else:
                (rgb + edit).clamp(0.0, 1.0)

    with torch.inference_mode():
        for _ in range(warmup):
            run()
    torch.cuda.synchronize()
    values: list[float] = []
    with torch.inference_mode():
        for _ in range(iterations):
            start = torch.cuda.Event(enable_timing=True)
            end = torch.cuda.Event(enable_timing=True)
            start.record()
            run()
            end.record()
            end.synchronize()
            values.append(float(start.elapsed_time(end)))
    array = np.asarray(values, dtype=np.float64)
    return {
        "median_ms": float(np.percentile(array, 50)),
        "p95_ms": float(np.percentile(array, 95)),
        "min_ms": float(np.min(array)),
        "max_ms": float(np.max(array)),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--replay-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--train-through", type=int, default=6)
    parser.add_argument("--warmup", type=int, default=10)
    parser.add_argument("--iterations", type=int, default=40)
    parser.add_argument("--device", default="cuda")
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(f"refusing to overwrite {args.output}")
    if args.device != "cuda" or not torch.cuda.is_available():
        raise RuntimeError("CUDA is required for the timing portion")

    replay_root = args.replay_root.resolve()
    manifest = json.loads((replay_root / "input_manifest.json").read_text(encoding="utf-8"))
    sequence = Path(manifest["sequence"])
    frames = [int(value) for value in manifest["frames"]]
    if args.train_through >= len(frames):
        raise ValueError("train-through must leave at least one validation frame")
    small_width, small_height = (int(value) for value in manifest["network_dimensions"])
    train_frames = frames[: args.train_through]
    validation_frames = frames[args.train_through :]
    beta = fit_coefficients(
        replay_root, sequence, train_frames, small_width, small_height
    )
    validation = evaluate(
        replay_root, sequence, validation_frames, small_width, small_height, beta
    )
    training = evaluate(replay_root, sequence, train_frames, small_width, small_height, beta)

    frame_dir = sequence / "frames" / "frame_00000001"
    runtime_items: list[tuple[torch.Tensor, torch.Tensor]] = []
    for eye in range(2):
        source = read_rgb8(
            frame_dir / f"input_eye{eye}_full.raw.bin", FULL_WIDTH, FULL_HEIGHT
        ).cuda()
        small_input = read_rgb8(
            replay_root / "frame_00000001" / f"input_eye{eye}.rgba", small_width, small_height
        ).cuda()
        small_output = read_rgb8(
            replay_root / "frame_00000001" / f"teacher_eye{eye}.rgba", small_width, small_height
        ).cuda()
        edit = F.interpolate(
            small_output - small_input,
            size=(FULL_HEIGHT, FULL_WIDTH),
            mode="bilinear",
            align_corners=False,
        )
        runtime_items.append((source, edit))
    beta_tensor = torch.from_numpy(beta.T).cuda()
    torch.backends.cudnn.benchmark = True
    timing = {
        "naive_fp32": timed_pair(
            runtime_items, beta_tensor, False, torch.float32, args.warmup, args.iterations
        ),
        "affine_fp32": timed_pair(
            runtime_items, beta_tensor, True, torch.float32, args.warmup, args.iterations
        ),
        "naive_fp16": timed_pair(
            runtime_items, beta_tensor, False, torch.float16, args.warmup, args.iterations
        ),
        "affine_fp16": timed_pair(
            runtime_items, beta_tensor, True, torch.float16, args.warmup, args.iterations
        ),
    }
    result = {
        "schema": "opennr-affine-scale-resolve-v1",
        "replay_root": str(replay_root),
        "sequence": str(sequence),
        "scale_percent": int(manifest["scale_percent"]),
        "full_shape": [FULL_WIDTH, FULL_HEIGHT],
        "network_shape": [small_width, small_height],
        "train_frames": train_frames,
        "validation_frames": validation_frames,
        "coefficients_feature_order": ["bias", "rgb_r", "rgb_g", "rgb_b", "edit_r", "edit_g", "edit_b"],
        "coefficients": beta.tolist(),
        "training": training,
        "validation": validation,
        "timing_device": torch.cuda.get_device_name(),
        "timing_scope": "resident tensors; full-resolution PyTorch affine resolve only; no input conversion, copies, native pass or compositor",
        "timing": timing,
        "promotion": False,
        "live_runtime_tested": False,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
