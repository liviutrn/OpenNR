"""Render fixed validation-stream visual samples for a capacity-temporal checkpoint.

The renderer replays selected validation eye streams from their strict reset,
then captures the same steady-state frames for every checkpoint.  It is visual
evidence only: it never reads the frozen test split and does not alter model
selection.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw
import torch

from capacity_student import CapacityConfig
from capacity_temporal_student import CapacityTemporalStyleContextStudent
from student_v2 import ReconstructionConfig
from temporal_student import TemporalConfig
from train_temporal_student import StrictTemporalCache


def _image(value: torch.Tensor, size: int) -> Image.Image:
    array = (
        value.detach().float().clamp(0, 1).cpu().numpy().transpose(1, 2, 0) * 255.0
    ).round().astype("uint8")
    return Image.fromarray(array, mode="RGB").resize(
        (size, size), Image.Resampling.LANCZOS
    )


def _load_model(path: Path):
    saved = torch.load(path, map_location="cuda", weights_only=False)
    if saved.get("architecture") != "context_v7_capacity_temporal":
        raise ValueError(f"Expected context_v7_capacity_temporal, got {saved.get('architecture')!r}")
    config = ReconstructionConfig(**saved["base_config"])
    temporal = TemporalConfig(**saved["temporal_config"])
    capacity = CapacityConfig(**saved["capacity_config"])
    model = CapacityTemporalStyleContextStudent(config, temporal, capacity).cuda()
    model.load_state_dict(saved["model"])
    model.eval()
    return model, saved


@torch.inference_mode()
def _capture(model, cache: StrictTemporalCache, sequence_ids: list[str], frame: int):
    captured = []
    for sequence_id in sequence_ids:
        for eye in (0, 1):
            indices = cache.streams[(sequence_id, eye)]
            rgb_np, target_np, guides_np, context_np = cache.load_window(indices[None, :])
            rgb = torch.from_numpy(rgb_np).cuda(non_blocking=True).float() / 255.0
            target = torch.from_numpy(target_np).cuda(non_blocking=True).float() / 255.0
            guides = torch.from_numpy(guides_np).cuda(non_blocking=True).float()
            context = torch.from_numpy(context_np).cuda(non_blocking=True).float()
            state = None
            prediction = None
            for offset in range(rgb.shape[1]):
                with torch.autocast(device_type="cuda", dtype=torch.bfloat16):
                    prediction, state = model.forward_temporal(
                        rgb[:, offset], guides[:, offset], context[:, offset], state
                    )
                if offset + 1 == frame:
                    captured.append(
                        {
                            "sequence_id": sequence_id,
                            "eye": eye,
                            "frame": frame,
                            "input": rgb[0, offset].float().cpu(),
                            "student": prediction[0].float().cpu(),
                            "teacher": target[0, offset].float().cpu(),
                        }
                    )
                    break
            del rgb, target, guides, context, prediction
    return captured


def _sheet(samples, label: str, output: Path, checkpoint: Path, cache: StrictTemporalCache):
    cell = 360
    header = 42
    row_height = cell + header + 24
    sheet = Image.new("RGB", (cell * 4, row_height * len(samples)), "#171b22")
    draw = ImageDraw.Draw(sheet)
    columns = ("Input", f"{label} student", "Feature 18 teacher", "Abs diff x4")
    for row_index, sample in enumerate(samples):
        y = row_index * row_height
        title = f"{sample['sequence_id']}  eye {sample['eye']}  frame {sample['frame']}"
        draw.text((8, y + 4), title, fill="white")
        input_image = _image(sample["input"], cell)
        student_image = _image(sample["student"], cell)
        teacher_image = _image(sample["teacher"], cell)
        diff = (sample["student"] - sample["teacher"]).abs().mul(4.0).clamp(0, 1)
        diff_image = _image(diff, cell)
        for column, (name, image) in enumerate(
            zip(columns, (input_image, student_image, teacher_image, diff_image))
        ):
            x = column * cell
            draw.rectangle((x, y + header, x + cell - 1, y + row_height - 1), fill="#222833")
            draw.text((x + 8, y + header + 5), name, fill="#d7e2f0")
            sheet.paste(image, (x, y + header + 24))
    output.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(output, quality=94)
    manifest = {
        "checkpoint": str(checkpoint.resolve()),
        "checkpoint_sha256": hashlib.sha256(checkpoint.read_bytes()).hexdigest(),
        "cache": str(cache.root),
        "cache_rows_sha256": cache.rows_sha256,
        "split": "validation",
        "sequence_ids": sorted({sample["sequence_id"] for sample in samples}),
        "frame": samples[0]["frame"] if samples else None,
        "samples": [
            {
                "sequence_id": sample["sequence_id"],
                "eye": sample["eye"],
                "frame": sample["frame"],
            }
            for sample in samples
        ],
        "scope": "Fixed validation-stream visual evidence; replayed from strict reset; test split untouched; not live VR acceptance.",
    }
    output.with_suffix(".json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--label", required=True)
    parser.add_argument("--frame", type=int, default=32)
    args = parser.parse_args()
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is required for visual checkpoint rendering")
    if not 1 <= args.frame <= 64:
        raise ValueError("frame must be between 1 and 64")
    torch.set_float32_matmul_precision("high")
    cache = StrictTemporalCache(args.cache, "validation")
    sequence_ids = cache.sequence_ids
    chosen = [sequence_ids[0], sequence_ids[len(sequence_ids) // 2], sequence_ids[-1]]
    model, _ = _load_model(args.checkpoint.resolve())
    samples = _capture(model, cache, chosen, args.frame)
    _sheet(samples, args.label, args.output.resolve(), args.checkpoint.resolve(), cache)
    print(
        json.dumps(
            {
                "state": "complete",
                "output": str(args.output.resolve()),
                "sequence_ids": chosen,
                "samples": len(samples),
                "split": "validation",
            }
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
