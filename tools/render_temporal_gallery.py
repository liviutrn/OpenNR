"""Render sequential temporal A/B sheets for visual teacher validation."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw
import torch

from train_temporal_student import StrictTemporalCache, _device_batch, _load_temporal
from train_student import atomic_json
from opennr_student import load_student


def pil(t):
    return Image.fromarray(
        (t.detach().float().clamp(0, 1).cpu().numpy().transpose(1, 2, 0) * 255)
        .round()
        .astype("u1")
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--split", choices=("validation", "test"), default="validation")
    parser.add_argument("--pairs", type=int, default=3)
    parser.add_argument("--label", default="temporal candidate")
    args = parser.parse_args()
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is required for temporal gallery rendering")
    args.output.mkdir(parents=True, exist_ok=True)
    cache = StrictTemporalCache(args.cache, args.split)
    temporal, temporal_checkpoint = _load_temporal(args.checkpoint)
    baseline, baseline_checkpoint = load_student(args.baseline, "cuda")
    keys = sorted(cache.streams)
    sequence_ids = sorted({key[0] for key in keys})
    chosen_sequences = [
        sequence_ids[int(index)]
        for index in np.linspace(0, len(sequence_ids) - 1, min(args.pairs, len(sequence_ids)), dtype=int)
    ]
    frame_choices = (0, 31, 63)
    records = []
    for sequence_id in chosen_sequences:
        for eye in (0, 1):
            key = (sequence_id, eye)
            indices = cache.streams[key]
            rgb_np, target_np, guides_np, context_np = cache.load_window(indices[None, :])
            rgb, target, guides, context = _device_batch(
                (rgb_np, target_np, guides_np, context_np), "cuda"
            )
            rgb = rgb.float() / 255.0
            target = target.float() / 255.0
            guides = guides.float()
            context = context.float()
            temporal_state = None
            for frame in range(64):
                with torch.inference_mode(), torch.autocast(device_type="cuda", dtype=torch.bfloat16):
                    temporal_prediction, temporal_state = temporal.forward_temporal(
                        rgb[:, frame], guides[:, frame], context[:, frame], temporal_state
                    )
                    baseline_prediction = baseline(rgb[:, frame], guides[:, frame], context[:, frame])
                if frame not in frame_choices:
                    continue
                images = [
                    ("Input", pil(rgb[0, frame])),
                    ("v8 spatial", pil(baseline_prediction[0])),
                    (args.label, pil(temporal_prediction[0])),
                    ("Feature 18 teacher", pil(target[0, frame])),
                ]
                tile_w, tile_h = 512, 552
                sheet = Image.new("RGB", (tile_w * len(images), tile_h), "#171b22")
                draw = ImageDraw.Draw(sheet)
                for tile, (label, image) in enumerate(images):
                    draw.text((tile * tile_w + 8, 8), label, fill="white")
                    sheet.paste(image, (tile * tile_w, 32))
                name = f"{sequence_id}_f{frame + 1:02d}_e{eye}.jpg"
                sheet.save(args.output / name, quality=94)
                records.append({"file": name, "sequence_id": sequence_id, "frame": frame + 1, "eye": eye})
            del rgb, target, guides, context, temporal_state
    atomic_json(
        args.output / "gallery.json",
        {
            "schema": "opennr-temporal-gallery-v1",
            "split": args.split,
            "checkpoint": str(args.checkpoint.resolve()),
            "baseline": str(args.baseline.resolve()),
            "records": records,
            "scope": "Sequential crop A/B sheets; direct visual evidence only, not live headset acceptance.",
        },
    )
    print(json.dumps({"state": "completed", "files": len(records), "output": str(args.output.resolve())}))


if __name__ == "__main__":
    main()
