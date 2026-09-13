"""Render one ordered vanilla/SDXL/teacher face comparison gallery."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


def _font() -> ImageFont.ImageFont:
    try:
        return ImageFont.truetype("arial.ttf", 18)
    except OSError:
        return ImageFont.load_default()


def _tile(path: Path, size: int, label: str) -> Image.Image:
    with Image.open(path) as image:
        tile = image.convert("RGB").resize((size, size), Image.Resampling.LANCZOS)
    draw = ImageDraw.Draw(tile)
    draw.rectangle((0, 0, size - 1, 38), fill=(0, 0, 0))
    draw.text((8, 8), label, fill=(255, 255, 255), font=_font())
    return tile


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--sample-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--tile-size", type=int, default=512)
    args = parser.parse_args()

    manifest_path = args.manifest.resolve()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    sample = next(
        (item for item in manifest["samples"] if item["sample_id"] == args.sample_id),
        None,
    )
    if sample is None:
        raise ValueError(f"sample not found: {args.sample_id}")

    ordered = [
        (Path(sample["raw_input_path"]), "1 vanilla input (no added effects)"),
        (Path(sample["enhanced_target_path"]), "2 SDXL output"),
        (Path(sample["teacher_path"]), "3 DLSS5 teacher"),
    ]
    missing = [str(path) for path, _ in ordered if not path.is_file()]
    if missing:
        raise FileNotFoundError("missing comparison image(s): " + ", ".join(missing))

    size = args.tile_size
    gallery = Image.new("RGB", (size * len(ordered), size), (18, 18, 18))
    for index, (path, label) in enumerate(ordered):
        gallery.paste(_tile(path, size, label), (index * size, 0))

    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    gallery.save(output, format="PNG", optimize=True)
    print(
        json.dumps(
            {
                "gallery": str(output),
                "sample_id": args.sample_id,
                "order": [label for _, label in ordered],
                "manifest": str(manifest_path),
                "manifest_sha256": manifest.get("manifest_sha256"),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
