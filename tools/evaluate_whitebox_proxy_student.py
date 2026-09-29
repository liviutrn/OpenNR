#!/usr/bin/env python3
"""Evaluate a frozen white-box-proxy student against proxy and native RGB."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import time

import numpy as np
import torch
from PIL import Image, ImageDraw

from opennr_student import load_student
from train_whitebox_proxy_student import ProxyPatches, evaluate_proxy


def to_image(tensor: torch.Tensor) -> Image.Image:
    array = tensor.detach().float().cpu().numpy()
    if array.ndim == 4:
        array = array[0]
    if array.max() <= 1.01:
        array = array * 255.0
    return Image.fromarray(np.rint(np.clip(array, 0.0, 255.0)).astype(np.uint8).transpose(1, 2, 0), mode="RGB")


def save_sheet(images: list[tuple[str, Image.Image]], output: Path) -> None:
    width = 320
    label_height = 28
    canvas = Image.new("RGB", (width * len(images), width + label_height), (24, 24, 24))
    draw = ImageDraw.Draw(canvas)
    for index, (label, image) in enumerate(images):
        left = index * width
        draw.text((left + 6, 6), label, fill=(240, 240, 240))
        canvas.paste(image.resize((width, width), Image.Resampling.BILINEAR), (left, label_height))
    output.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output, quality=94)


@torch.no_grad()
def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--split", choices=("validation", "test"), default="test")
    parser.add_argument("--preview-count", type=int, default=12)
    args = parser.parse_args()

    cache = args.cache.expanduser().resolve()
    checkpoint = args.checkpoint.expanduser().resolve()
    output = args.output.expanduser().resolve()
    if output.exists() and any(output.iterdir()):
        raise FileExistsError(f"refusing to use non-empty evaluation output: {output}")
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is required for this evaluation")
    output.mkdir(parents=True, exist_ok=True)
    dataset = ProxyPatches(cache, args.split)
    if not dataset:
        raise ValueError(f"split {args.split!r} is empty")
    loader = torch.utils.data.DataLoader(dataset, batch_size=8, num_workers=0, pin_memory=True)
    model, saved = load_student(checkpoint, "cuda")
    metrics = evaluate_proxy(model, loader, "cuda")
    preview_root = output / "previews"
    preview_indices = np.linspace(0, len(dataset) - 1, num=min(max(0, args.preview_count), len(dataset)), dtype=int).tolist()
    started = time.perf_counter()
    for local_index in sorted(set(preview_indices)):
        item = dataset[local_index]
        rgb = item["rgb"].float().unsqueeze(0).cuda() / 255.0
        target = item["target"].float().unsqueeze(0).cuda() / 255.0
        native = item["native_teacher"].float().unsqueeze(0).cuda() / 255.0
        guides = item["guides"].float().unsqueeze(0).cuda()
        context = item["context"].float().unsqueeze(0).cuda()
        with torch.autocast(device_type="cuda", dtype=torch.bfloat16):
            prediction = model(rgb, guides, context)
        plan_index = int(item["index"])
        save_sheet(
            [
                ("Input", to_image(rgb)),
                ("Student", to_image(prediction)),
                ("White-box proxy", to_image(target)),
                ("Native NVIDIA", to_image(native)),
            ],
            preview_root / f"sample_{local_index:04d}_patch_{plan_index:05d}.jpg",
        )
    report = {
        "schema": "opennr-whitebox-proxy-student-evaluation-v1",
        "scope": f"frozen {args.split} split; proxy imitation plus native guardrail; not runtime acceptance",
        "cache": str(cache),
        "checkpoint": str(checkpoint),
        "checkpoint_step": saved.get("step"),
        "target_kind": saved.get("target_kind", "whitebox_recovered_rgb_proxy"),
        "architecture": saved.get("config"),
        "split": args.split,
        "metrics": metrics,
        "preview_count": len(set(preview_indices)),
        "seconds": time.perf_counter() - started,
        "test_used_for_tuning": False,
        "test_evaluated_after_checkpoint_selection": args.split == "test",
        "live_runtime_tested": False,
        "promotion": False,
    }
    (output / "evaluation.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
