#!/usr/bin/env python3
"""Create labeled contact sheets and a manual visual-tag template.

This helper never assigns semantic labels.  It only exposes the exact frozen
test patch IDs and metadata so a reviewer can fill ``tags`` by inspection.
The resulting tag file can be consumed by the category evaluator.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont


CATEGORIES = ("faces", "hair", "armor", "foliage", "dark_interiors", "bright_exteriors")


def to_image(array: np.ndarray) -> Image.Image:
    return Image.fromarray(np.asarray(array).transpose(1, 2, 0).clip(0, 255).astype(np.uint8), mode="RGB")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--split", choices=("validation", "test"), default="test")
    parser.add_argument("--samples-per-sheet", type=int, default=18)
    parser.add_argument("--thumb-size", type=int, default=192)
    args = parser.parse_args()

    cache = args.cache.expanduser().resolve()
    output = args.output.expanduser().resolve()
    if output.exists() and any(output.iterdir()):
        raise FileExistsError(f"refusing to use non-empty output: {output}")
    if args.samples_per_sheet < 1 or args.thumb_size < 64:
        raise ValueError("samples-per-sheet must be positive and thumb-size must be at least 64")
    output.mkdir(parents=True, exist_ok=True)
    plan = json.loads((cache / "patches.json").read_text(encoding="utf-8"))
    rgb = np.load(cache / "rgb.npy", mmap_mode="r")
    selected = [
        (index, item)
        for index, item in enumerate(plan)
        if item.get("split") == args.split
    ]
    if not selected:
        raise ValueError(f"no patches in split {args.split!r}")
    samples = []
    for patch_index, item in selected:
        samples.append(
            {
                "sample_id": len(samples),
                "patch_index": patch_index,
                "sequence_id": item["sequence_id"],
                "frame_id": int(item["frame_id"]),
                "eye": int(item["eye"]),
                "box": item.get("box"),
                "split": item["split"],
                "tags": [],
            }
        )

    columns = 6
    label_height = 34
    cell_height = args.thumb_size + label_height
    for sheet_number, start in enumerate(range(0, len(samples), args.samples_per_sheet)):
        chunk = samples[start : start + args.samples_per_sheet]
        rows = (len(chunk) + columns - 1) // columns
        canvas = Image.new("RGB", (columns * args.thumb_size, rows * cell_height), (24, 24, 24))
        draw = ImageDraw.Draw(canvas)
        for offset, sample in enumerate(chunk):
            column = offset % columns
            row = offset // columns
            left = column * args.thumb_size
            top = row * cell_height
            image = to_image(rgb[int(sample["patch_index"]), 0]).resize((args.thumb_size, args.thumb_size), Image.Resampling.BILINEAR)
            canvas.paste(image, (left, top))
            label = f"id{sample['sample_id']:02d} p{sample['patch_index']:03d}\nf{sample['frame_id']} e{sample['eye']}"
            draw.rectangle((left, top + args.thumb_size, left + args.thumb_size, top + cell_height), fill=(24, 24, 24))
            draw.multiline_text((left + 3, top + args.thumb_size + 2), label, fill=(240, 240, 240), spacing=1)
        canvas.save(output / f"input_sheet_{sheet_number:02d}.jpg", quality=94)

    template = {
        "schema": "opennr-whitebox-manual-visual-tags-v1",
        "source_cache": str(cache),
        "source_cache_complete": str((cache / "complete.json").resolve()),
        "split": args.split,
        "instructions": "Manually add one or more category names to each sample tags array. Leave unrelated samples empty. Do not tag based on the student or native output; tag the input content only.",
        "allowed_categories": list(CATEGORIES),
        "samples": samples,
        "tagging_complete": False,
    }
    (output / "visual_tags_template.json").write_text(json.dumps(template, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"cache": str(cache), "split": args.split, "samples": len(samples), "sheets": (len(samples) + args.samples_per_sheet - 1) // args.samples_per_sheet, "template": str(output / 'visual_tags_template.json')}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
