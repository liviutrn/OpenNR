"""Render a broad raw/teacher/enhanced three-way static GEN gallery."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


def _font() -> ImageFont.ImageFont:
    try:
        return ImageFont.truetype("arial.ttf", 16)
    except OSError:
        return ImageFont.load_default()


def _tile(path: Path | None, size: int, label: str) -> Image.Image:
    tile = Image.new("RGB", (size, size), (25, 25, 25))
    if path is not None and path.exists():
        with Image.open(path) as image:
            tile.paste(image.convert("RGB").resize((size, size), Image.Resampling.LANCZOS))
    draw = ImageDraw.Draw(tile)
    draw.rectangle((0, 0, size - 1, 28), fill=(0, 0, 0))
    draw.text((4, 4), label, fill=(255, 255, 255), font=_font())
    return tile


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--review", type=Path)
    parser.add_argument("--tile-size", type=int, default=192)
    args = parser.parse_args()

    manifest = json.loads(args.manifest.resolve().read_text(encoding="utf-8"))
    review = {}
    if args.review and args.review.exists():
        review_payload = json.loads(args.review.resolve().read_text(encoding="utf-8"))
        review = {
            item["sample_id"]: item.get("decision", "pending")
            for item in review_payload.get("samples", [])
        }
    samples_by_pair: dict[str, list[dict]] = {}
    for sample in manifest["samples"]:
        samples_by_pair.setdefault(sample["pair_id"], []).append(sample)
    pairs = [samples_by_pair[key] for key in sorted(samples_by_pair)]
    for pair in pairs:
        pair.sort(key=lambda item: int(item["eye"]))
    pair_columns = 4
    tile_size = args.tile_size
    canvas = Image.new(
        "RGB",
        (pair_columns * 3 * tile_size, math.ceil(len(pairs) / pair_columns) * 2 * tile_size),
        (18, 18, 18),
    )
    for pair_index, pair in enumerate(pairs):
        x0 = (pair_index % pair_columns) * 3 * tile_size
        y0 = (pair_index // pair_columns) * 2 * tile_size
        for eye_index, sample in enumerate(pair):
            y = y0 + eye_index * tile_size
            decision = review.get(sample["sample_id"], "pending")
            tiles = [
                (Path(sample["raw_input_path"]), f"{sample['pair_id']} e{sample['eye']} raw"),
                (Path(sample["teacher_path"]), f"{sample['pair_id']} e{sample['eye']} teacher"),
                (Path(sample["enhanced_target_path"]), f"target {decision}"),
            ]
            for column, (path, label) in enumerate(tiles):
                canvas.paste(_tile(path, tile_size, label), (x0 + column * tile_size, y))
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output, format="PNG", optimize=True)
    print(json.dumps({"gallery": str(output), "pairs": len(pairs), "eyes": len(manifest["samples"])}, indent=2))


if __name__ == "__main__":
    main()

