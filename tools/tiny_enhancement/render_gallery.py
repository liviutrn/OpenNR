"""Render fixed validation crop galleries for visual teacher comparison."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import torch
from PIL import Image, ImageDraw, ImageFont

from .dataset import TinyPairedCache
from .models import build_model


def _to_image(tensor: torch.Tensor, size: int = 224) -> Image.Image:
    value = (tensor.detach().float().clamp(0.0, 1.0).mul(255.0).round().byte().permute(1, 2, 0).cpu().numpy())
    return Image.fromarray(value, mode="RGB").resize((size, size), Image.Resampling.LANCZOS)


def _label_tile(image: Image.Image, label: str) -> Image.Image:
    tile = Image.new("RGB", (image.width, image.height + 24), "#151515")
    tile.paste(image, (0, 24))
    draw = ImageDraw.Draw(tile)
    draw.text((4, 4), label, fill="white")
    return tile


def _parse_checkpoints(values: list[str]) -> list[tuple[str, Path]]:
    result = []
    for value in values:
        if "=" not in value:
            raise ValueError(f"checkpoint must be LABEL=PATH: {value}")
        label, path = value.split("=", 1)
        result.append((label, Path(path).resolve()))
    if not result:
        raise ValueError("at least one checkpoint is required")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--checkpoint", action="append", default=[])
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--split", choices=["validation", "test"], default="validation")
    parser.add_argument("--per-cohort-sequences", type=int, default=3)
    parser.add_argument("--frame", type=int, default=32)
    parser.add_argument("--tile-size", type=int, default=224)
    parser.add_argument("--device", default="cuda")
    args = parser.parse_args()
    if args.device == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("CUDA was requested but is not available")
    device = torch.device(args.device)
    checkpoints = _parse_checkpoints(args.checkpoint)
    cache = TinyPairedCache(args.manifest.resolve(), args.split)
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)

    selected_groups: list[dict] = []
    seen_sequences: dict[str, int] = {}
    for group in cache.groups:
        cohort = str(group["cache_source"])
        if seen_sequences.get(cohort, 0) >= args.per_cohort_sequences:
            continue
        # Select both eyes for each fixed sequence so binocular layout can be
        # inspected without changing the model input.
        if group["eye"] == 0:
            selected_groups.append(group)
            seen_sequences[cohort] = seen_sequences.get(cohort, 0) + 1
            sibling = next((candidate for candidate in cache.groups if candidate["sequence_id"] == group["sequence_id"] and candidate["eye"] == 1), None)
            if sibling is not None:
                selected_groups.append(sibling)
    samples: list[dict] = []
    for group in selected_groups:
        frame_ids = group["frame_ids"]
        frame = args.frame if args.frame in frame_ids else frame_ids[len(frame_ids) // 2]
        absolute_index = group["indices"][frame_ids.index(frame)]
        samples.append({
            "sequence_id": group["sequence_id"],
            "eye": group["eye"],
            "frame_id": frame,
            "cache_source": group["cache_source"],
            "absolute_index": absolute_index,
        })

    base_images: list[tuple[Image.Image, Image.Image]] = []
    for sample in samples:
        inputs, targets = cache.load_batch([sample["absolute_index"]], device)
        base_images.append((_to_image(inputs[0], args.tile_size), _to_image(targets[0], args.tile_size)))

    columns = [("Input", [pair[0] for pair in base_images]), ("Teacher", [pair[1] for pair in base_images])]
    for label, checkpoint_path in checkpoints:
        checkpoint = torch.load(checkpoint_path, map_location=device, weights_only=False)
        model = build_model(checkpoint["architecture"], checkpoint.get("config")).to(device).eval()
        model.load_state_dict(checkpoint["model"])
        predictions = []
        with torch.inference_mode():
            for sample in samples:
                inputs, _ = cache.load_batch([sample["absolute_index"]], device)
                predictions.append(_to_image(model(inputs)[0], args.tile_size))
        columns.append((label, predictions))

    rows = len(samples)
    tile_height = args.tile_size + 24
    sheet = Image.new("RGB", (len(columns) * args.tile_size, rows * tile_height), "#151515")
    draw = ImageDraw.Draw(sheet)
    for col_index, (label, images) in enumerate(columns):
        for row_index, image in enumerate(images):
            sheet.paste(_label_tile(image, label), (col_index * args.tile_size, row_index * tile_height))
            sample = samples[row_index]
            draw.text((col_index * args.tile_size + 4, row_index * tile_height + tile_height - 14), f"{sample['cache_source']} {sample['sequence_id']} e{sample['eye']} f{sample['frame_id']}", fill="#bdbdbd")
    sheet_path = output / f"{args.split}_gallery.png"
    sheet.save(sheet_path)
    (output / "samples.json").write_text(json.dumps(samples, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"gallery": str(sheet_path), "samples": len(samples), "columns": [label for label, _ in columns]}, indent=2))


if __name__ == "__main__":
    main()
