"""Render held-out full-eye comparisons for a reduced-work FastStudent checkpoint.

This is an offline inspection helper.  It carries the recurrent state through
the complete replay for each eye, but only keeps selected frames for PNGs and
comparison panels so that a 16 GB GPU is not asked to hold the whole sequence.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
import torch
from PIL import Image, ImageDraw

from evaluate_fast_student_trt_full_eye import (
    FULL_HEIGHT,
    FULL_WIDTH,
    _load_frame,
    _metrics,
    _resize,
    _save_png,
)
from fast_student_v1 import load_fast_student


FACE_CROP = (1250, 620, 2300, 1730)
SELECTED_FRAMES = (1, 8, 16)


def _to_pil(value: torch.Tensor) -> Image.Image:
    array = (
        value.detach()
        .float()
        .clamp(0.0, 1.0)[0]
        .permute(1, 2, 0)
        .mul(255.0)
        .round()
        .to(torch.uint8)
        .cpu()
        .numpy()
    )
    return Image.fromarray(array, mode="RGB")


def _panel(
    images: list[tuple[str, Image.Image]],
    output_path: Path,
    crop: tuple[int, int, int, int] | None,
) -> None:
    display_width = 520
    caption_height = 34
    prepared: list[tuple[str, Image.Image]] = []
    for label, image in images:
        if crop is not None:
            image = image.crop(crop)
        scale = display_width / image.width
        display_height = max(1, round(image.height * scale))
        prepared.append((label, image.resize((display_width, display_height), Image.Resampling.LANCZOS)))

    panel_width = display_width * len(prepared)
    panel_height = caption_height + max(image.height for _, image in prepared)
    panel = Image.new("RGB", (panel_width, panel_height), (20, 20, 20))
    draw = ImageDraw.Draw(panel)
    for index, (label, image) in enumerate(prepared):
        x = index * display_width
        panel.paste(image, (x, caption_height))
        draw.rectangle((x, 0, x + display_width - 1, caption_height - 1), fill=(20, 20, 20))
        draw.text((x + 10, 9), label, fill=(245, 245, 245))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    panel.save(output_path, quality=92, subsampling=0)


def _student_composite(item: dict[str, torch.Tensor], prediction: torch.Tensor) -> torch.Tensor:
    residual = _resize(
        prediction - item["work_input"],
        item["full_input"].shape[-2],
        item["full_input"].shape[-1],
    )
    return (item["full_input"] + residual).clamp(0.0, 1.0)


def _native_composite(item: dict[str, torch.Tensor]) -> torch.Tensor:
    residual = _resize(
        item["native_work"] - item["work_input"],
        item["full_input"].shape[-2],
        item["full_input"].shape[-1],
    )
    return (item["full_input"] + residual).clamp(0.0, 1.0)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--replay-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--context-size", type=int, default=96)
    parser.add_argument("--device", default="cuda")
    args = parser.parse_args()

    if args.device.startswith("cuda") and not torch.cuda.is_available():
        raise RuntimeError("CUDA is required for this visual evaluation")
    if args.output.exists() and any(args.output.iterdir()):
        raise FileExistsError(f"refusing to use non-empty output directory: {args.output}")
    args.output.mkdir(parents=True, exist_ok=True)

    replay_root = args.replay_root.resolve()
    manifest = json.loads((replay_root / "input_manifest.json").read_text(encoding="utf-8"))
    sequence = Path(manifest["sequence"]).resolve()
    frame_ids = [int(value) for value in manifest["frames"]]
    work_width, work_height = (int(value) for value in manifest["network_dimensions"])
    device = torch.device(args.device)
    model, saved = load_fast_student(args.checkpoint.resolve(), device)
    model.eval()

    preview_root = args.output / "previews"
    png_root = args.output / "student_png"
    records: list[dict[str, Any]] = []

    with torch.inference_mode():
        for eye in (0, 1):
            state = None
            for frame_id in frame_ids:
                item = _load_frame(
                    replay_root,
                    sequence,
                    frame_id,
                    eye,
                    work_width,
                    work_height,
                    args.context_size,
                    args.context_size,
                    device,
                    torch.float32,
                )
                prediction, state = model.forward_temporal(
                    item["work_input"], item["guides"], item["context"], state
                )
                student = _student_composite(item, prediction)
                native50 = _native_composite(item)
                record = {
                    "frame_id": frame_id,
                    "eye": eye,
                    "reset": frame_id == frame_ids[0],
                    "student_mae_vs_full_teacher": float(
                        _metrics(student.float().cpu(), item["full_teacher"].float().cpu(), item["full_input"].float().cpu())["mae"]
                    ),
                    "native50_mae_vs_full_teacher": float(
                        _metrics(native50.float().cpu(), item["full_teacher"].float().cpu(), item["full_input"].float().cpu())["mae"]
                    ),
                    "identity_mae_vs_full_teacher": float(
                        (item["full_input"].float() - item["full_teacher"].float()).abs().mean().item()
                    ),
                }
                records.append(record)

                if frame_id in SELECTED_FRAMES and eye == 0:
                    input_cpu = item["full_input"].float().cpu()
                    teacher_cpu = item["full_teacher"].float().cpu()
                    student_cpu = student.float().cpu()
                    native_cpu = native50.float().cpu()
                    prefix = preview_root / f"frame_{frame_id:08d}_eye{eye}"
                    _save_png(png_root / f"frame_{frame_id:08d}_eye{eye}_luma_student.png", student_cpu)
                    input_pil = _to_pil(input_cpu)
                    student_pil = _to_pil(student_cpu)
                    native_pil = _to_pil(native_cpu)
                    teacher_pil = _to_pil(teacher_cpu)
                    labels = [
                        ("Raw input", input_pil),
                        ("Luma student", student_pil),
                        ("Native 50% residual", native_pil),
                        ("Full native teacher", teacher_pil),
                    ]
                    _panel(labels, prefix.with_name(prefix.name + "_full_comparison.jpg"), None)
                    _panel(labels, prefix.with_name(prefix.name + "_face_comparison.jpg"), FACE_CROP)

                del item, prediction, student, native50
                if device.type == "cuda":
                    torch.cuda.empty_cache()

            # Do not accidentally carry one eye's temporal state into the other.
            state = None

    result = {
        "schema": "opennr-fast-student-luma-visual-evaluation-v1",
        "checkpoint": str(args.checkpoint.resolve()),
        "replay_root": str(replay_root),
        "sequence": str(sequence),
        "frames": frame_ids,
        "eyes": [0, 1],
        "selected_frames": list(SELECTED_FRAMES),
        "face_crop_xyxy": list(FACE_CROP),
        "model_config": saved.get("config"),
        "parameters": sum(value.numel() for value in saved["model"].values()),
        "records": records,
        "promotion": False,
        "live_runtime_tested": False,
        "scope": "offline visual inspection with sequential state carry; no live Skyrim, stereo, headset, temporal, or VR acceptance",
    }
    (args.output / "result.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
