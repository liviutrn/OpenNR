#!/usr/bin/env python3
"""Render high-resolution comparison sheets for manually tagged cache patches."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw
import torch

from opennr_student import load_student


def to_image(tensor: torch.Tensor) -> Image.Image:
    array = (
        tensor.detach().float().clamp(0, 1).cpu().numpy()[0].transpose(1, 2, 0) * 255.0
    ).round().astype("uint8")
    return Image.fromarray(array, mode="RGB")


def add_label(image: Image.Image, label: str, width: int = 512, height: int = 552) -> Image.Image:
    sheet = Image.new("RGB", (width, height), "#171b22")
    draw = ImageDraw.Draw(sheet)
    draw.text((8, 8), label, fill="white")
    sheet.paste(image.resize((width, height - 40), Image.Resampling.LANCZOS), (0, 40))
    return sheet


@torch.inference_mode()
def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--tags", type=Path, required=True)
    parser.add_argument("--category", default="faces")
    parser.add_argument("--checkpoint", type=Path, action="append", required=True)
    parser.add_argument("--label", action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-samples", type=int, default=8)
    args = parser.parse_args()

    if len(args.checkpoint) != len(args.label):
        raise ValueError("each --checkpoint requires one matching --label")
    if args.max_samples < 1:
        raise ValueError("--max-samples must be positive")
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is required for tagged gallery rendering")

    cache = args.cache.expanduser().resolve()
    tags_path = args.tags.expanduser().resolve()
    output = args.output.expanduser().resolve()
    if output.exists() and any(output.iterdir()):
        raise FileExistsError(f"refusing to use non-empty output: {output}")
    output.mkdir(parents=True, exist_ok=True)

    tags = json.loads(tags_path.read_text(encoding="utf-8"))
    if tags.get("schema") != "opennr-whitebox-manual-visual-tags-v1":
        raise ValueError("unexpected visual-tag schema")
    plan = json.loads((cache / "patches.json").read_text(encoding="utf-8"))
    rgb_array = np.load(cache / "rgb.npy", mmap_mode="r")
    proxy_array = np.load(cache / "proxy.npy", mmap_mode="r")
    guides_array = np.load(cache / "guides.npy", mmap_mode="r")
    context_array = np.load(cache / "context.npy", mmap_mode="r")

    tagged: dict[int, set[str]] = defaultdict(set)
    for sample in tags.get("samples", []):
        if args.category in sample.get("tags", []):
            tagged[int(sample["patch_index"])].update(sample.get("tags", []))
    if not tagged:
        raise ValueError(f"no patches tagged with category {args.category!r}")

    candidates = sorted(
        tagged,
        key=lambda index: (
            plan[index]["sequence_id"],
            int(plan[index]["frame_id"]),
            int(plan[index]["eye"]),
            index,
        ),
    )
    # Round-robin sequences so the gallery is not eight nearly identical crops.
    by_sequence: dict[str, list[int]] = defaultdict(list)
    for index in candidates:
        by_sequence[plan[index]["sequence_id"]].append(index)
    selected: list[int] = []
    offsets = {sequence: 0 for sequence in by_sequence}
    while len(selected) < min(args.max_samples, len(candidates)):
        advanced = False
        for sequence in sorted(by_sequence):
            values = by_sequence[sequence]
            offset = offsets[sequence]
            if offset >= len(values):
                continue
            selected.append(values[offset])
            offsets[sequence] = offset + 1
            advanced = True
            if len(selected) >= min(args.max_samples, len(candidates)):
                break
        if not advanced:
            break

    models = []
    for label, checkpoint in zip(args.label, args.checkpoint):
        model, saved = load_student(checkpoint.expanduser().resolve(), "cuda")
        models.append((label, model, saved, str(checkpoint.expanduser().resolve())))

    columns = [("Input", None)]
    columns.extend((label, model) for label, model, _saved, _path in models)
    columns.extend((("White-box proxy", "proxy"), ("Native NVIDIA", "native")))
    individual_dir = output / "samples"
    individual_dir.mkdir(parents=True, exist_ok=True)
    gallery_rows: list[Image.Image] = []
    metadata_samples: list[dict[str, object]] = []

    for ordinal, patch_index in enumerate(selected):
        item = plan[patch_index]
        row_index = int(item["row"])
        rgb = torch.from_numpy(rgb_array[patch_index, 0].copy()).float().unsqueeze(0).cuda() / 255.0
        proxy = torch.from_numpy(proxy_array[patch_index].copy()).float().unsqueeze(0).cuda() / 255.0
        native = torch.from_numpy(rgb_array[patch_index, 1].copy()).float().unsqueeze(0).cuda() / 255.0
        guides = torch.from_numpy(guides_array[patch_index].copy()).float().unsqueeze(0).cuda()
        context = torch.from_numpy(context_array[row_index].copy()).float().unsqueeze(0).cuda()

        rendered: dict[str, Image.Image] = {"Input": to_image(rgb)}
        for label, model, _saved, _path in models:
            with torch.autocast(device_type="cuda", dtype=torch.bfloat16):
                prediction = model(rgb, guides, context)
            rendered[label] = to_image(prediction)
            del prediction
        rendered["White-box proxy"] = to_image(proxy)
        rendered["Native NVIDIA"] = to_image(native)

        panels = [add_label(rendered[label], label) for label, _model in columns]
        sheet = Image.new("RGB", (512 * len(panels), 552), "#171b22")
        for column, panel in enumerate(panels):
            sheet.paste(panel, (column * 512, 0))
        stem = (
            f"face_{ordinal:02d}_patch{patch_index:04d}_"
            f"{item['sequence_id']}_f{item['frame_id']}_e{item['eye']}"
        )
        sheet.save(individual_dir / f"{stem}.jpg", quality=95, subsampling=0)
        gallery_rows.append(sheet.resize((512 * len(panels) // 2, 276), Image.Resampling.LANCZOS))
        metadata_samples.append(
            {
                "ordinal": ordinal,
                "patch_index": patch_index,
                "tags": sorted(tagged[patch_index]),
                "sequence_id": item["sequence_id"],
                "frame_id": item["frame_id"],
                "eye": item["eye"],
                "box": item["box"],
                "file": str((individual_dir / f"{stem}.jpg").resolve()),
            }
        )
        del rgb, proxy, native, guides, context

    contact = Image.new("RGB", (gallery_rows[0].width, sum(row.height for row in gallery_rows)), "#171b22")
    y = 0
    for row in gallery_rows:
        contact.paste(row, (0, y))
        y += row.height
    contact.save(output / f"{args.category}_contact_sheet.jpg", quality=95, subsampling=0)

    report = {
        "schema": "opennr-whitebox-tagged-gallery-v1",
        "scope": f"manual {args.category} crops from frozen test cache; visual inspection only",
        "cache": str(cache),
        "tags": str(tags_path),
        "category": args.category,
        "tagging_complete": bool(tags.get("tagging_complete")),
        "models": [
            {
                "label": label,
                "checkpoint": path,
                "checkpoint_step": saved.get("step"),
                "architecture": saved.get("config"),
            }
            for label, _model, saved, path in models
        ],
        "samples": metadata_samples,
        "promotion": False,
        "live_runtime_tested": False,
    }
    (output / "gallery.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
