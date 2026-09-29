"""Measure temporal student error by teacher-effect magnitude bands."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import torch

from train_temporal_student import StrictTemporalCache, _device_batch, _load_temporal
from train_student import atomic_json


@torch.inference_mode()
def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--split", choices=("train", "validation", "test"), default="validation")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--batch", type=int, default=8)
    args = parser.parse_args()
    if args.batch < 1:
        parser.error("--batch must be positive")
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is required for temporal effect-band evaluation")

    args.output.mkdir(parents=True, exist_ok=True)
    cache = StrictTemporalCache(args.cache.resolve(), args.split)
    checkpoint_path = args.checkpoint.resolve()
    model, checkpoint = _load_temporal(checkpoint_path, "cuda")
    # Boundaries are mean absolute teacher-input RGB effect per pixel.
    edges = (0.0, 0.01, 0.025, 0.05, 0.10, 1.01)
    stats = [
        {
            "lower": edges[index],
            "upper": edges[index + 1],
            "pixels": 0,
            "student_abs": 0.0,
            "identity_abs": 0.0,
            "student_effect_abs": 0.0,
            "teacher_effect_abs": 0.0,
        }
        for index in range(len(edges) - 1)
    ]
    total_pixels = 0
    for _selected, arrays in cache.stream_batches(args.batch):
        rgb_np, target_np, guides_np, context_np = arrays
        rgb_all, target_all, guides_all, context_all = _device_batch(
            (rgb_np, target_np, guides_np, context_np), "cuda"
        )
        rgb_all = rgb_all.float() / 255.0
        target_all = target_all.float() / 255.0
        guides_all = guides_all.float()
        context_all = context_all.float()
        state = None
        for frame in range(rgb_all.shape[1]):
            rgb = rgb_all[:, frame]
            target = target_all[:, frame]
            with torch.autocast(device_type="cuda", dtype=torch.bfloat16):
                prediction, state = model.forward_temporal(
                    rgb, guides_all[:, frame], context_all[:, frame], state
                )
            prediction = prediction.float()
            effect = (target - rgb).abs().mean(1)
            student_error = (prediction - target).abs().mean(1)
            identity_error = (rgb - target).abs().mean(1)
            student_effect = (prediction - rgb).abs().mean(1)
            teacher_effect = (target - rgb).abs().mean(1)
            total_pixels += effect.numel()
            for index, record in enumerate(stats):
                if index == len(stats) - 1:
                    mask = effect >= record["lower"]
                else:
                    mask = (effect >= record["lower"]) & (effect < record["upper"])
                count = int(mask.sum().item())
                if not count:
                    continue
                record["pixels"] += count
                record["student_abs"] += float(student_error[mask].sum().item())
                record["identity_abs"] += float(identity_error[mask].sum().item())
                record["student_effect_abs"] += float(student_effect[mask].sum().item())
                record["teacher_effect_abs"] += float(teacher_effect[mask].sum().item())
        del rgb_all, target_all, guides_all, context_all, state

    for record in stats:
        pixels = max(1, record.pop("pixels"))
        record["pixel_fraction"] = pixels / max(1, total_pixels)
        record["student_mae"] = record.pop("student_abs") / pixels
        record["identity_mae"] = record.pop("identity_abs") / pixels
        record["student_effect_mae"] = record.pop("student_effect_abs") / pixels
        record["teacher_effect_mae"] = record.pop("teacher_effect_abs") / pixels
        record["improvement_pct"] = 100.0 * (
            record["identity_mae"] - record["student_mae"]
        ) / max(record["identity_mae"], 1e-12)

    result = {
        "checkpoint": str(checkpoint_path),
        "checkpoint_sha256": hashlib.sha256(checkpoint_path.read_bytes()).hexdigest(),
        "step": checkpoint.get("step"),
        "cache": str(cache.root),
        "cache_rows_sha256": cache.rows_sha256,
        "split": args.split,
        "sequence_count": len(cache.sequence_ids),
        "eye_streams": len(cache.streams),
        "frames": total_pixels // (512 * 512),
        "total_pixels": total_pixels,
        "effect_edges": edges,
        "bands": stats,
        "scope": "Streaming temporal evaluation grouped by mean absolute teacher-input RGB effect; not live VR acceptance.",
    }
    atomic_json(args.output / "result.json", result)
    print(json.dumps(result, indent=2), flush=True)


if __name__ == "__main__":
    main()
