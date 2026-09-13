"""Evaluate whole-eye versus crop-thumbnail RGB context on the current semantic model.

This is an inference-only spatial diagnostic on the audited full-resolution pilot.
The input crop, teacher crop, native guides, context-guide planes, model weights,
and reset state are identical; only the three RGB context channels differ.  The
validation split is sequence-disjoint from training and the test split is never
read.
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

import numpy as np
from PIL import Image
import torch

from joint_parent_tone_model import load_joint_checkpoint
from prepare_conditioning_pilot import save, sha


def thumbnail(array: np.ndarray) -> np.ndarray:
    image = Image.fromarray(np.ascontiguousarray(array))
    return (
        np.asarray(image.resize((96, 96), Image.Resampling.BOX), dtype=np.float32)
        .transpose(2, 0, 1)
        / 255.0
    ).astype(np.float16)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--split", choices=("train", "validation"), default="validation")
    parser.add_argument("--batch", type=int, default=2)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    if args.split == "test":
        raise ValueError("The test split is intentionally unavailable to this diagnostic")
    if args.batch < 1:
        raise ValueError("Batch must be positive")

    torch.set_num_threads(4)
    torch.backends.cudnn.benchmark = False
    meta = json.loads((args.cache / "complete.json").read_text())
    rows = json.loads((args.cache / "rows.json").read_text())
    patches = json.loads((args.cache / "patches.json").read_text())
    selected = [
        (index, patch)
        for index, patch in enumerate(patches)
        if patch["split"] == args.split
    ]
    if not selected:
        raise ValueError("No patches selected")
    if any(patch["split"] == "test" for _, patch in selected):
        raise ValueError("Test patch selected")

    rgb = np.load(args.cache / "rgb.npy", mmap_mode="r")
    guides = np.load(args.cache / "guides.npy", mmap_mode="r")
    contexts = np.load(args.cache / "context.npy", mmap_mode="r")
    input_values = []
    target_values = []
    guide_values = []
    full_context_values = []
    crop_context_values = []
    sequence_ids = []
    eyes = []
    for index, patch in selected:
        row = rows[patch["row"]]
        if row["split"] != args.split:
            raise ValueError("Patch/row split mismatch")
        input_patch = np.array(rgb[index, 0], copy=True)
        input_values.append(input_patch)
        target_values.append(np.array(rgb[index, 1], copy=True))
        guide_values.append(np.array(guides[index], copy=True))
        full = np.array(contexts[patch["row"]], copy=True)
        crop = full.copy()
        crop[:3] = thumbnail(input_patch.transpose(1, 2, 0))
        full_context_values.append(full)
        crop_context_values.append(crop)
        sequence_ids.append(patch["sequence_id"])
        eyes.append(int(patch["eye"]))

    device = "cuda" if torch.cuda.is_available() else "cpu"
    if device != "cuda":
        raise RuntimeError("CUDA is required for this diagnostic")
    model, checkpoint = load_joint_checkpoint(args.checkpoint)
    model = model.to(device).eval()
    metrics = {
        "full_eye_rgb": {"abs": 0.0, "sq": 0.0, "count": 0, "by_sequence": defaultdict(list), "by_eye": defaultdict(list)},
        "crop_rgb": {"abs": 0.0, "sq": 0.0, "count": 0, "by_sequence": defaultdict(list), "by_eye": defaultdict(list)},
    }
    args.output.mkdir(parents=True)
    save(args.output / "status.json", {"state": "evaluating", "split": args.split, "done": 0, "total": len(selected), "test_used": False})
    with torch.no_grad():
        for begin in range(0, len(selected), args.batch):
            end = min(begin + args.batch, len(selected))
            value = torch.from_numpy(np.stack(input_values[begin:end])).to(device).float() / 255.0
            target = torch.from_numpy(np.stack(target_values[begin:end])).to(device).float() / 255.0
            guide = torch.from_numpy(np.stack(guide_values[begin:end])).to(device).float()
            for name, context_values in (("full_eye_rgb", full_context_values), ("crop_rgb", crop_context_values)):
                context = torch.from_numpy(np.stack(context_values[begin:end])).to(device).float()
                with torch.autocast(device_type="cuda", dtype=torch.bfloat16):
                    prediction, _ = model.forward_temporal(value, guide, context, None)
                error = (prediction.float() - target).abs()
                squared = (prediction.float() - target).square()
                metrics[name]["abs"] += float(error.sum().item())
                metrics[name]["sq"] += float(squared.sum().item())
                metrics[name]["count"] += int(target.numel())
                per_patch = error.mean((1, 2, 3)).cpu().tolist()
                for offset, patch_mae in enumerate(per_patch):
                    metrics[name]["by_sequence"][sequence_ids[begin + offset]].append(float(patch_mae))
                    metrics[name]["by_eye"][str(eyes[begin + offset])].append(float(patch_mae))
            save(args.output / "status.json", {"state": "evaluating", "split": args.split, "done": end, "total": len(selected), "test_used": False})

    result_metrics = {}
    for name, value in metrics.items():
        result_metrics[name] = {
            "mae": value["abs"] / value["count"],
            "rmse": (value["sq"] / value["count"]) ** 0.5,
            "sequence_mae": {key: float(np.mean(vals)) for key, vals in value["by_sequence"].items()},
            "eye_mae": {key: float(np.mean(vals)) for key, vals in value["by_eye"].items()},
            "patches": len(selected),
            "pixels": value["count"],
        }
    result = {
        "scope": __doc__,
        "checkpoint": str(args.checkpoint.resolve()),
        "checkpoint_sha256": sha(args.checkpoint),
        "cache": str(args.cache.resolve()),
        "cache_complete_sha256": sha(args.cache / "complete.json"),
        "split": args.split,
        "sequence_count": len(set(sequence_ids)),
        "patches": len(selected),
        "test_used": False,
        "input_target_guides_identical": True,
        "context_guide_planes_identical": True,
        "reset_state": "None for each independent spatial patch",
        "source_sha256": sha(Path(__file__)),
        "metrics": result_metrics,
        "full_minus_crop_mae": result_metrics["full_eye_rgb"]["mae"] - result_metrics["crop_rgb"]["mae"],
        "full_relative_change_pct": 100.0 * (result_metrics["full_eye_rgb"]["mae"] - result_metrics["crop_rgb"]["mae"]) / result_metrics["crop_rgb"]["mae"],
    }
    save(args.output / "result.json", result)
    save(args.output / "status.json", {"state": "complete", "split": args.split, "test_used": False})
    print(json.dumps({key: value for key, value in result.items() if key != "metrics"}, indent=2), flush=True)


if __name__ == "__main__":
    main()
