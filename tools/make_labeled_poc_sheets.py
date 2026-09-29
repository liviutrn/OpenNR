#!/usr/bin/env python3
"""Create persistent, clearly labeled visual sheets for the OpenNR POC."""

from __future__ import annotations

import argparse
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


def draw_centered(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], text: str, font: ImageFont.ImageFont, fill: str) -> None:
    left, top, right, bottom = box
    bounds = draw.textbbox((0, 0), text, font=font)
    width = bounds[2] - bounds[0]
    height = bounds[3] - bounds[1]
    draw.text(
        (left + (right - left - width) / 2, top + (bottom - top - height) / 2 - bounds[1]),
        text,
        font=font,
        fill=fill,
    )


def make_sheet(
    rows: list[tuple[str, list[Image.Image]]],
    output_path: Path,
    page_number: int,
    page_count: int,
    tile_size: int,
) -> None:
    labels = [
        "A — PRE-NR INPUT",
        "B — CAPTURED TEACHER",
        "C — OUR MODEL 1x: RGB ONLY",
        "D — OUR MODEL 1x: RGB + DEPTH/MV",
    ]
    columns = len(labels)
    title_height = 112
    row_label_height = 42
    row_height = row_label_height + tile_size
    canvas = Image.new(
        "RGB",
        (columns * tile_size, title_height + len(rows) * row_height),
        "white",
    )
    draw = ImageDraw.Draw(canvas)
    title_font = get_font(26, bold=True)
    header_font = get_font(17, bold=True)
    row_font = get_font(15, bold=False)

    title = f"OpenNR POC held-out examples — sheet {page_number}/{page_count}"
    draw.text((14, 10), title, font=title_font, fill="#111111")
    draw.text(
        (14, 48),
        "Every row is the same crop. Lower visual difference from B means closer to the real teacher.",
        font=row_font,
        fill="#333333",
    )
    draw.text(
        (14, 72),
        "B is the captured Feature 18/DLSSNR reference; A is MGO pre-NR input, not a separate stock-vanilla capture.",
        font=row_font,
        fill="#333333",
    )

    for column, label in enumerate(labels):
        left = column * tile_size
        draw_centered(draw, (left, 84, left + tile_size, title_height), label, header_font, "#000000")

    for row_index, (row_label, images) in enumerate(rows):
        top = title_height + row_index * row_height
        draw.rectangle((0, top, canvas.width, top + row_label_height), fill="#eeeeee")
        draw.text((8, top + 11), row_label, font=row_font, fill="#222222")
        for column, image in enumerate(images):
            left = column * tile_size
            image_top = top + row_label_height
            canvas.paste(image, (left, image_top))
            draw.rectangle(
                (left, image_top, left + tile_size - 1, image_top + tile_size - 1),
                outline="#777777",
                width=1,
            )

    canvas.save(output_path)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture-root", type=Path, required=True)
    parser.add_argument("--checkpoint-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--examples", type=int, default=24)
    parser.add_argument("--per-sheet", type=int, default=8)
    parser.add_argument("--tile-size", type=int, default=320)
    parser.add_argument("--resolution", type=int, default=128)
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
    count = min(args.examples, len(test_refs))
    selected_indices = np.linspace(0, len(test_refs) - 1, count, dtype=int).tolist()
    selected = [test_refs[index] for index in selected_indices]

    rgb_dataset = PairDataset(selected, args.resolution, False)
    guided_dataset = PairDataset(selected, args.resolution, True)
    rgb_model = TinyStudent(3).to(device)
    guided_model = TinyStudent(6).to(device)
    rgb_model.load_state_dict(
        torch.load(checkpoint_dir / "model_rgb_best.pt", map_location=device, weights_only=True)
    )
    guided_model.load_state_dict(
        torch.load(checkpoint_dir / "model_guided_best.pt", map_location=device, weights_only=True)
    )
    rgb_model.eval()
    guided_model.eval()

    rows: list[tuple[str, list[Image.Image]]] = []
    with torch.inference_mode():
        for index, ref in enumerate(selected, start=1):
            rgb_sample = rgb_dataset[index - 1]
            guided_sample = guided_dataset[index - 1]
            rgb_input = rgb_sample["features"].unsqueeze(0).to(device)
            guided_input = guided_sample["features"].unsqueeze(0).to(device)
            with autocast_context(device):
                rgb_output = rgb_model(rgb_input).squeeze(0).float().cpu()
                guided_output = guided_model(guided_input).squeeze(0).float().cpu()

            eye_name = "left" if ref.eye == 0 else "right"
            row_label = (
                f"Example {index:02d}  |  sequence {ref.sequence_id}  |  frame {ref.frame_id}  |  "
                f"{eye_name} eye  |  crop {ref.crop_index}"
            )
            images = [
                to_image(rgb_sample["features"][:3], args.tile_size),
                to_image(rgb_sample["target"], args.tile_size),
                to_image(rgb_output, args.tile_size),
                to_image(guided_output, args.tile_size),
            ]
            rows.append((row_label, images))

    page_count = math.ceil(len(rows) / args.per_sheet)
    generated: list[str] = []
    for page_index in range(page_count):
        page_rows = rows[page_index * args.per_sheet : (page_index + 1) * args.per_sheet]
        path = output_dir / f"labeled_examples_sheet_{page_index + 1:02d}_of_{page_count:02d}.png"
        make_sheet(page_rows, path, page_index + 1, page_count, args.tile_size)
        generated.append(str(path))

    print(
        {
            "device": str(device),
            "test_examples": len(rows),
            "sheets": generated,
        }
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
