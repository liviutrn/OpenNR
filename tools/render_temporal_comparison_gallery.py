#!/usr/bin/env python3
"""Render side-by-side sequential temporal checkpoints for visual QA."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw
import torch

from train_student import atomic_json
from train_temporal_student import StrictTemporalCache, _device_batch, _load_temporal


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _pil(value: torch.Tensor) -> Image.Image:
    return Image.fromarray(
        (value.detach().float().clamp(0, 1).cpu().numpy().transpose(1, 2, 0) * 255)
        .round()
        .astype("u1")
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--split", choices=("validation", "test"), default="validation")
    parser.add_argument("--pairs", type=int, default=4)
    parser.add_argument("--baseline-label", default="v33 anchor")
    parser.add_argument("--candidate-label", default="v45 extra capacity")
    args = parser.parse_args()
    if args.pairs < 1:
        parser.error("--pairs must be positive")
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is required for temporal gallery rendering")
    args.output.mkdir(parents=True, exist_ok=True)
    cache = StrictTemporalCache(args.cache.resolve(), args.split)
    baseline, baseline_checkpoint = _load_temporal(args.baseline.resolve(), "cuda")
    candidate, candidate_checkpoint = _load_temporal(args.candidate.resolve(), "cuda")
    sequence_ids = sorted({key[0] for key in cache.streams})
    chosen = [
        sequence_ids[int(index)]
        for index in np.linspace(0, len(sequence_ids) - 1, min(args.pairs, len(sequence_ids)), dtype=int)
    ]
    frame_choices = (0, 31, 63)
    records = []
    for sequence_id in chosen:
        for eye in (0, 1):
            indices = cache.streams[(sequence_id, eye)]
            rgb_np, target_np, guides_np, context_np = cache.load_window(indices[None, :])
            rgb, target, guides, context = _device_batch(
                (rgb_np, target_np, guides_np, context_np), "cuda"
            )
            rgb = rgb.float() / 255.0
            target = target.float() / 255.0
            guides = guides.float()
            context = context.float()
            baseline_state = candidate_state = None
            for frame in range(64):
                with torch.inference_mode(), torch.autocast(device_type="cuda", dtype=torch.bfloat16):
                    baseline_prediction, baseline_state = baseline.forward_temporal(
                        rgb[:, frame], guides[:, frame], context[:, frame], baseline_state
                    )
                    candidate_prediction, candidate_state = candidate.forward_temporal(
                        rgb[:, frame], guides[:, frame], context[:, frame], candidate_state
                    )
                if frame not in frame_choices:
                    continue
                images = [
                    ("Input", _pil(rgb[0, frame])),
                    (args.baseline_label, _pil(baseline_prediction[0])),
                    (args.candidate_label, _pil(candidate_prediction[0])),
                    ("Feature 18 teacher", _pil(target[0, frame])),
                ]
                tile_w, tile_h = 512, 552
                sheet = Image.new("RGB", (tile_w * len(images), tile_h), "#171b22")
                draw = ImageDraw.Draw(sheet)
                for tile, (label, image) in enumerate(images):
                    draw.text((tile * tile_w + 8, 8), label, fill="white")
                    sheet.paste(image, (tile * tile_w, 32))
                name = f"{sequence_id}_f{frame + 1:02d}_e{eye}.jpg"
                sheet.save(args.output / name, quality=94)
                records.append(
                    {"file": name, "sequence_id": sequence_id, "frame": frame + 1, "eye": eye}
                )
            del rgb, target, guides, context, baseline_state, candidate_state
    payload = {
        "schema": "opennr-temporal-comparison-gallery-v1",
        "split": args.split,
        "cache": str(args.cache.resolve()),
        "baseline": str(args.baseline.resolve()),
        "baseline_sha256": _sha256(args.baseline.resolve()),
        "candidate": str(args.candidate.resolve()),
        "candidate_sha256": _sha256(args.candidate.resolve()),
        "baseline_architecture": baseline_checkpoint.get("architecture"),
        "candidate_architecture": candidate_checkpoint.get("architecture"),
        "records": records,
        "scope": "Sequential temporal A/B sheets for direct visual QA; not live headset acceptance.",
    }
    atomic_json(args.output / "gallery.json", payload)
    print(json.dumps({"state": "completed", "files": len(records), "output": str(args.output.resolve())}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
