#!/usr/bin/env python3
"""Create simple three-column MGO input / student / teacher comparison sheets."""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

import torch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from train_opennr_poc import (  # noqa: E402
    PairDataset,
    TinyStudent,
    assign_refs,
    autocast_context,
    build_index,
    split_sequences,
)


def get_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = (
        Path(r"C:\Windows\Fonts\segoeuib.ttf"),
        Path(r"C:\Windows\Fonts\segoeui.ttf"),
    ) if bold else (
        Path(r"C:\Windows\Fonts\segoeui.ttf"),
        Path(r"C:\Windows\Fonts\arial.ttf"),
    )
    for candidate in candidates:
        if candidate.is_file():
            return ImageFont.truetype(str(candidate), size=size)
    return ImageFont.load_default()


def to_image(tensor: torch.Tensor, size: int) -> Image.Image:
    value = tensor.detach().float().cpu().clamp(0.0, 1.0)
    array = np.uint8(np.round(value.permute(1, 2, 0).numpy() * 255.0))
    return Image.fromarray(array, mode="RGB").resize(
        (size, size), Image.Resampling.LANCZOS
    )


def centered(draw: ImageDraw.ImageDraw, left: int, right: int, top: int, bottom: int, text: str, font: ImageFont.ImageFont) -> None:
    bounds = draw.textbbox((0, 0), text, font=font)
    width = bounds[2] - bounds[0]
    height = bounds[3] - bounds[1]
    draw.text(
        (left + (right - left - width) / 2, top + (bottom - top - height) / 2 - bounds[1]),
        text,
        font=font,
        fill="#111111",
    )


def make_sheet(
    rows: list[tuple[str, list[Image.Image]]],
    path: Path,
    page_number: int,
    page_count: int,
    tile_size: int,
    model_label: str,
) -> None:
    labels = [
        "A — MGO VANILLA / NO DLSS",
        f"B — OUR MODEL 1x ({model_label})",
        "C — REAL TEACHER (FEATURE 18)",
    ]
    columns = 3
    title_height = 126
    row_label_height = 42
    row_height = row_label_height + tile_size
    canvas = Image.new(
        "RGB",
        (columns * tile_size, title_height + len(rows) * row_height),
        "white",
    )
    draw = ImageDraw.Draw(canvas)
    title_font = get_font(27, bold=True)
    header_font = get_font(18, bold=True)
    body_font = get_font(15)
    draw.text(
        (14, 10),
        f"OpenNR three-way held-out comparison — sheet {page_number}/{page_count}",
        font=title_font,
        fill="#111111",
    )
    draw.text(
        (14, 51),
        "Same crop in every column. A is captured MGO before the teacher pass; C is the real captured reference.",
        font=body_font,
        fill="#333333",
    )
    draw.text(
        (14, 75),
        "‘MGO vanilla’ here means no Feature 18/DLSSNR teacher effect in this capture—not a separate stock-unmodded install.",
        font=body_font,
        fill="#333333",
    )
    for column, label in enumerate(labels):
        left = column * tile_size
        centered(draw, left, left + tile_size, 92, title_height, label, header_font)

    for row_index, (row_label, images) in enumerate(rows):
        top = title_height + row_index * row_height
        draw.rectangle((0, top, canvas.width, top + row_label_height), fill="#eeeeee")
        draw.text((8, top + 11), row_label, font=body_font, fill="#222222")
        for column, image in enumerate(images):
            left = column * tile_size
            image_top = top + row_label_height
            canvas.paste(image, (left, image_top))
            draw.rectangle(
                (left, image_top, left + tile_size - 1, image_top + tile_size - 1),
                outline="#777777",
                width=1,
            )
    canvas.save(path)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture-root", type=Path, required=True)
    parser.add_argument("--checkpoint-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--our-model", choices=("rgb", "guided"), default="rgb")
    parser.add_argument("--examples", type=int, default=24)
    parser.add_argument("--per-sheet", type=int, default=8)
    parser.add_argument("--tile-size", type=int, default=400)
    parser.add_argument("--resolution", type=int, default=128)
    parser.add_argument("--sequence-id")
    parser.add_argument("--frame-id", type=int)
    parser.add_argument("--eye", type=int, choices=(0, 1))
    parser.add_argument("--crop-index", type=int)
    parser.add_argument("--device", default="auto", choices=("auto", "cuda", "cpu"))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.examples <= 0 or args.per_sheet <= 0 or args.tile_size <= 0:
        raise SystemExit("--examples, --per-sheet, and --tile-size must be positive")
    if args.resolution <= 0:
        raise SystemExit("--resolution must be positive")

    device = (
        torch.device("cuda" if torch.cuda.is_available() else "cpu")
        if args.device == "auto"
        else torch.device(args.device)
    )
    if device.type == "cuda" and not torch.cuda.is_available():
        raise SystemExit("CUDA was requested but is not available")

    capture_root = args.capture_root.expanduser().resolve()
    checkpoint_dir = args.checkpoint_dir.expanduser().resolve()
    output_dir = args.output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    refs, sequence_rows, _warnings = build_index(capture_root)
    split_refs = assign_refs(refs, split_sequences(sequence_rows))
    test_refs = split_refs["test"]
    explicit = (args.sequence_id, args.frame_id, args.eye, args.crop_index)
    if any(value is not None for value in explicit):
        if any(value is None for value in explicit):
            raise SystemExit(
                "--sequence-id, --frame-id, --eye, and --crop-index must be supplied together"
            )
        selected = [
            ref
            for ref in test_refs
            if ref.sequence_id == args.sequence_id
            and ref.frame_id == args.frame_id
            and ref.eye == args.eye
            and ref.crop_index == args.crop_index
        ]
        if len(selected) != 1:
            raise SystemExit(f"expected one matching held-out crop, found {len(selected)}")
    else:
        count = min(args.examples, len(test_refs))
        selected_indices = np.linspace(0, len(test_refs) - 1, count, dtype=int).tolist()
        selected = [test_refs[index] for index in selected_indices]

    rgb_dataset = PairDataset(selected, args.resolution, False)
    guided_dataset = PairDataset(selected, args.resolution, True)
    include_guides = args.our_model == "guided"
    channels = 6 if include_guides else 3
    model = TinyStudent(channels).to(device)
    model.load_state_dict(
        torch.load(
            checkpoint_dir / f"model_{args.our_model}_best.pt",
            map_location=device,
            weights_only=True,
        )
    )
    model.eval()

    rows: list[tuple[str, list[Image.Image]]] = []
    with torch.inference_mode():
        for index, ref in enumerate(selected, start=1):
            rgb_sample = rgb_dataset[index - 1]
            guided_sample = guided_dataset[index - 1]
            sample = guided_sample if include_guides else rgb_sample
            features = sample["features"].unsqueeze(0).to(device)
            with autocast_context(device):
                output = model(features).squeeze(0).float().cpu()
            eye_name = "left" if ref.eye == 0 else "right"
            row_label = (
                f"Example {index:02d}  |  {ref.sequence_id}  |  frame {ref.frame_id}  |  "
                f"{eye_name} eye  |  crop {ref.crop_index}"
            )
            rows.append(
                (
                    row_label,
                    [
                        to_image(rgb_sample["features"][:3], args.tile_size),
                        to_image(output, args.tile_size),
                        to_image(rgb_sample["target"], args.tile_size),
                    ],
                )
            )

    page_count = math.ceil(len(rows) / args.per_sheet)
    generated: list[str] = []
    model_label = "RGB ONLY" if args.our_model == "rgb" else "RGB + DEPTH/MV"
    for page_index in range(page_count):
        page_rows = rows[page_index * args.per_sheet : (page_index + 1) * args.per_sheet]
        path = output_dir / f"threeway_{args.our_model}_sheet_{page_index + 1:02d}_of_{page_count:02d}.png"
        make_sheet(page_rows, path, page_index + 1, page_count, args.tile_size, model_label)
        generated.append(str(path))

    manifest = {
        "model": args.our_model,
        "model_label": model_label,
        "examples": len(rows),
        "held_out_split": "test",
        "columns": [
            "MGO pre-NR input (no teacher pass)",
            f"our {model_label.lower()} one-pass output",
            "captured Feature 18 teacher output",
        ],
        "sheets": generated,
    }
    (output_dir / "threeway_sheet_manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(manifest, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
