"""Render a small stereo A/B gallery for frozen raw-crop checkpoints."""
import argparse
from pathlib import Path
import hashlib
import json

import numpy as np
from PIL import Image, ImageDraw
import torch

from evaluate_student import load_eye, pil
from opennr_student import load_student


def parse_checkpoint(value: str):
    if "=" not in value:
        raise argparse.ArgumentTypeError("checkpoint must be label=path")
    label, path = value.split("=", 1)
    if not label or not path:
        raise argparse.ArgumentTypeError("checkpoint must be label=path")
    return label, Path(path)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--checkpoint", type=parse_checkpoint, action="append", required=True)
    parser.add_argument("--split", choices=("validation", "test"), default="test")
    parser.add_argument("--pairs", type=int, default=3)
    args = parser.parse_args()
    if args.pairs < 1:
        raise ValueError("--pairs must be positive")
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is required for gallery rendering")

    args.output.mkdir(parents=True, exist_ok=True)
    rows = json.loads((args.cache / "rows.json").read_text(encoding="utf-8"))
    context = np.load(args.cache / "context.npy", mmap_mode="r")
    ids = [i for i, row in enumerate(rows) if row["split"] == args.split]
    if not ids:
        raise ValueError(f"No rows in split {args.split!r}")
    by_frame = {}
    for i in ids:
        row = rows[i]
        by_frame.setdefault((row["sequence_id"], row["frame_id"]), []).append(i)
    frame_keys = list(by_frame)
    chosen_positions = np.linspace(0, len(frame_keys) - 1, min(args.pairs, len(frame_keys)), dtype=int)
    chosen = [frame_keys[int(i)] for i in chosen_positions]

    models = []
    candidates = []
    for label, path in args.checkpoint:
        path = path.resolve()
        model, checkpoint = load_student(path, "cuda")
        models.append(model)
        candidates.append({
            "label": label,
            "checkpoint": str(path),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "step": int(checkpoint.get("step", -1)),
            "architecture": checkpoint.get("architecture", "legacy_rgb_or_guided"),
        })

    records = []
    for pair_index, key in enumerate(chosen):
        pair_rows = sorted(by_frame[key], key=lambda i: rows[i]["eye"])
        if len(pair_rows) != 2:
            continue
        for eye_index in pair_rows:
            row = rows[eye_index]
            rgb, target, guides, ctx = load_eye(row, context[eye_index])
            images = [("Input", pil(rgb))]
            with torch.inference_mode():
                for candidate, model in zip(candidates, models):
                    with torch.autocast("cuda", dtype=torch.bfloat16):
                        pred = model(rgb, guides, ctx)
                    images.append((candidate["label"], pil(pred)))
                    del pred
            images.append(("Feature 18 teacher", pil(target)))

            tile_w, tile_h = 512, 552
            sheet = Image.new("RGB", (tile_w * len(images), tile_h), "#171b22")
            draw = ImageDraw.Draw(sheet)
            for tile_index, (label, image) in enumerate(images):
                draw.text((tile_index * tile_w + 8, 8), label, fill="white")
                sheet.paste(image, (tile_index * tile_w, 32))
            name = f"pair{pair_index:02d}_{key[0]}_f{row['frame_id']}_e{row['eye']}.jpg"
            sheet.save(args.output / name, quality=94)
            records.append({
                "file": name,
                "sequence_id": key[0],
                "frame_id": key[1],
                "eye": row["eye"],
                "row": eye_index,
            })
            del rgb, target, guides, ctx

    manifest = {
        "schema": "opennr-frozen-crop-gallery-v1",
        "cache": str(args.cache.resolve()),
        "split": args.split,
        "candidates": candidates,
        "records": records,
        "scope": "Directly viewable 512x512 crop A/B evidence; not a quality, temporal, headset, or runtime gate.",
    }
    (args.output / "gallery.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps({"state": "completed", "files": len(records), "output": str(args.output.resolve())}), flush=True)


if __name__ == "__main__":
    main()
