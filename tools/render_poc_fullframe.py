#!/usr/bin/env python3
"""Render a captured full frame through the OpenNR-VR POC model.

This deliberately supports repeated application of the same one-pass student
so the visual effect of a 4x cascade can be inspected. The student was trained
on 128x128 crops, so full-frame output is an exploratory stress test rather
than a trained full-resolution renderer.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from contextlib import nullcontext
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageDraw

import torch
import torch.nn.functional as F

sys.path.insert(0, str(Path(__file__).resolve().parent))
from train_opennr_poc import TinyStudent  # noqa: E402


def read_frame(sequence_root: Path, frame_id: int) -> dict[str, Any]:
    frames_path = sequence_root / "frames.jsonl"
    for line in frames_path.read_text(encoding="utf-8").splitlines():
        record = json.loads(line)
        if int(record.get("frame_id", -1)) == frame_id:
            return record
    raise FileNotFoundError(f"frame_id={frame_id} not found in {frames_path}")


def full_artifacts(
    sequence_root: Path, record: dict[str, Any], eye: int
) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for artifact in record.get("artifacts", []):
        if artifact.get("full_frame") and int(artifact.get("eye", -1)) == eye:
            result[str(artifact["stage"])] = artifact
    required = {"input", "teacher", "depth", "motion_vectors"}
    missing = required.difference(result)
    if missing:
        raise ValueError(f"eye {eye} is missing full-frame stages: {sorted(missing)}")
    return result


def artifact_path(sequence_root: Path, artifact: dict[str, Any], field: str) -> Path:
    relative = artifact.get(field)
    if not isinstance(relative, str) or not relative:
        raise ValueError(f"missing {field} for {artifact.get('stage')}")
    path = (sequence_root / relative).resolve()
    path.relative_to(sequence_root.resolve())
    if not path.is_file():
        raise FileNotFoundError(path)
    return path


def load_rgb(path: Path) -> torch.Tensor:
    with Image.open(path) as image:
        array = np.asarray(image.convert("RGB"), dtype=np.float32).copy() / 255.0
    return torch.from_numpy(array).permute(2, 0, 1).contiguous()


def load_guides(
    depth_path: Path,
    motion_path: Path,
    guide_width: int,
    guide_height: int,
    color_width: int,
    color_height: int,
    scale_x: float,
    scale_y: float,
) -> torch.Tensor:
    depth = np.fromfile(depth_path, dtype="<f4")
    expected_depth = guide_width * guide_height
    if depth.size != expected_depth:
        raise ValueError(f"{depth_path}: expected {expected_depth} depth values, got {depth.size}")
    depth = depth.reshape(1, guide_height, guide_width).astype(np.float32, copy=True)

    motion = np.fromfile(motion_path, dtype="<f2")
    expected_motion = guide_width * guide_height * 2
    if motion.size != expected_motion:
        raise ValueError(
            f"{motion_path}: expected {expected_motion} motion values, got {motion.size}"
        )
    motion = motion.reshape(guide_height, guide_width, 2)
    motion = np.transpose(motion, (2, 0, 1)).astype(np.float32, copy=True)

    depth = np.nan_to_num(depth, nan=0.0, posinf=0.0, neginf=0.0).clip(0.0, 1.0)
    motion = np.nan_to_num(motion, nan=0.0, posinf=0.0, neginf=0.0)
    motion[0] *= scale_x
    motion[1] *= scale_y

    guides = torch.from_numpy(np.concatenate((depth, motion), axis=0))
    return F.interpolate(
        guides.unsqueeze(0),
        size=(color_height, color_width),
        mode="bilinear",
        align_corners=False,
    ).squeeze(0)


def autocast_context(device: torch.device):
    if device.type == "cuda":
        return torch.autocast(device_type="cuda", dtype=torch.bfloat16)
    return nullcontext()


def synchronize(device: torch.device) -> None:
    if device.type == "cuda":
        torch.cuda.synchronize(device)


def tensor_to_image(tensor: torch.Tensor) -> Image.Image:
    value = tensor.detach().float().cpu().clamp(0.0, 1.0)
    array = np.uint8(np.round(value.permute(1, 2, 0).numpy() * 255.0))
    return Image.fromarray(array, mode="RGB")


def image_metrics(output: torch.Tensor, target: torch.Tensor, source: torch.Tensor) -> dict[str, float]:
    prediction = output.detach().float().cpu().numpy()
    teacher = target.detach().float().cpu().numpy()
    input_rgb = source.detach().float().cpu().numpy()
    error = prediction - teacher
    mae = float(np.abs(error).mean())
    mse = float(np.square(error).mean())
    return {
        "mae_vs_teacher": mae,
        "psnr_vs_teacher": 10.0 * math.log10(1.0 / max(mse, 1e-12)),
        "mean_change_vs_input": float(np.abs(prediction - input_rgb).mean()),
    }


def render_model(
    model: torch.nn.Module,
    source: torch.Tensor,
    target: torch.Tensor,
    guides: torch.Tensor | None,
    passes: int,
    name: str,
    eye: int,
    output_dir: Path,
    device: torch.device,
) -> tuple[dict[str, Any], dict[int, Image.Image]]:
    current = source.unsqueeze(0).to(device)
    guide_gpu = guides.unsqueeze(0).to(device) if guides is not None else None
    metrics: list[dict[str, Any]] = []
    images: dict[int, Image.Image] = {}

    for pass_index in range(1, passes + 1):
        synchronize(device)
        started = time.perf_counter()
        with torch.inference_mode(), autocast_context(device):
            features = torch.cat((current, guide_gpu), dim=1) if guide_gpu is not None else current
            current = model(features)
        synchronize(device)
        elapsed_ms = (time.perf_counter() - started) * 1000.0

        rendered = current.squeeze(0).float().cpu()
        metrics.append(
            {
                "pass": pass_index,
                "time_ms": elapsed_ms,
                **image_metrics(rendered, target, source),
            }
        )
        image = tensor_to_image(rendered)
        images[pass_index] = image
        image.save(output_dir / f"fullframe_{name}_eye{eye}_pass{pass_index}x.png")

    return {
        "model": name,
        "eye": eye,
        "passes": metrics,
    }, images


def make_sheet(
    images: list[Image.Image],
    labels: list[str],
    output_path: Path,
    row_labels: list[str] | None = None,
) -> None:
    if len(images) != len(labels):
        raise ValueError("sheet image and label counts differ")
    original_width, original_height = images[0].size
    tile_width = max(1, original_width // len(images))
    tile_height = max(1, round(original_height * tile_width / original_width))
    label_height = 32
    rows = len(row_labels) if row_labels else 1
    canvas = Image.new("RGB", (tile_width * len(images), rows * (tile_height + label_height)), "white")
    draw = ImageDraw.Draw(canvas)
    for row in range(rows):
        row_name = row_labels[row] if row_labels else ""
        for column, (image, label) in enumerate(zip(images, labels)):
            left = column * tile_width
            top = row * (tile_height + label_height)
            if row == 0:
                draw.text((left + 6, top + 7), label, fill="black")
            if row_labels:
                draw.text((left + 6, top + 18), row_name, fill="black")
            resized = image.resize((tile_width, tile_height), Image.Resampling.BILINEAR)
            canvas.paste(resized, (left, top + label_height))
    canvas.save(output_path)


def make_stereo_sheet(
    rows: list[tuple[str, Image.Image, Image.Image, Image.Image, Image.Image]],
    output_path: Path,
) -> None:
    labels = ["pre-NR input", "captured teacher", "our 1x", "our 4x"]
    original_width, original_height = rows[0][1].size
    tile_width = original_width // 4
    tile_height = round(original_height * tile_width / original_width)
    label_height = 34
    row_height = tile_height + label_height
    canvas = Image.new("RGB", (tile_width * 4, row_height * len(rows)), "white")
    draw = ImageDraw.Draw(canvas)
    for row_index, (eye_name, source, teacher, pass_one, pass_four) in enumerate(rows):
        top = row_index * row_height
        draw.text((6, top + 5), eye_name, fill="black")
        for column, (label, image) in enumerate(
            zip(labels, (source, teacher, pass_one, pass_four))
        ):
            left = column * tile_width
            if row_index == 0:
                draw.text((left + 6, top + 18), label, fill="black")
            canvas.paste(
                image.resize((tile_width, tile_height), Image.Resampling.BILINEAR),
                (left, top + label_height),
            )
    canvas.save(output_path)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture-root", type=Path, required=True)
    parser.add_argument("--checkpoint-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--sequence-id", required=True)
    parser.add_argument("--frame-id", type=int, required=True)
    parser.add_argument("--passes", type=int, default=4)
    parser.add_argument("--models", default="rgb,guided")
    parser.add_argument("--device", default="auto", choices=("auto", "cuda", "cpu"))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.passes <= 0:
        raise SystemExit("--passes must be positive")
    model_names = [name.strip() for name in args.models.split(",") if name.strip()]
    if not model_names or any(name not in {"rgb", "guided"} for name in model_names):
        raise SystemExit("--models must contain only rgb and/or guided")

    device = (
        torch.device("cuda" if torch.cuda.is_available() else "cpu")
        if args.device == "auto"
        else torch.device(args.device)
    )
    if device.type == "cuda" and not torch.cuda.is_available():
        raise SystemExit("CUDA was requested but is not available")
    if device.type == "cuda":
        torch.set_float32_matmul_precision("high")

    capture_root = args.capture_root.expanduser().resolve()
    checkpoint_dir = args.checkpoint_dir.expanduser().resolve()
    output_dir = args.output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    sequence_root = capture_root / args.sequence_id
    record = read_frame(sequence_root, args.frame_id)

    source_images: dict[int, torch.Tensor] = {}
    teacher_images: dict[int, torch.Tensor] = {}
    guides: dict[int, torch.Tensor] = {}
    for eye in (0, 1):
        artifacts = full_artifacts(sequence_root, record, eye)
        source_path = artifact_path(sequence_root, artifacts["input"], "png_path")
        teacher_path = artifact_path(sequence_root, artifacts["teacher"], "png_path")
        source = load_rgb(source_path)
        teacher = load_rgb(teacher_path)
        if source.shape != teacher.shape:
            raise ValueError(f"eye {eye}: input and teacher shapes differ")
        color_height, color_width = source.shape[-2:]
        guide_width = int(artifacts["depth"]["width"])
        guide_height = int(artifacts["depth"]["height"])
        scale_x = float(record["motion_vector_scale_x"][eye])
        scale_y = float(record["motion_vector_scale_y"][eye])
        guide = load_guides(
            artifact_path(sequence_root, artifacts["depth"], "raw_path"),
            artifact_path(sequence_root, artifacts["motion_vectors"], "raw_path"),
            guide_width,
            guide_height,
            color_width,
            color_height,
            scale_x,
            scale_y,
        )
        source_images[eye] = source
        teacher_images[eye] = teacher
        guides[eye] = guide

    all_results: dict[str, Any] = {
        "source_frame": {
            "sequence_id": args.sequence_id,
            "frame_id": args.frame_id,
            "status": record.get("status"),
            "route": record.get("route"),
            "color_resolution": [int(source_images[0].shape[-1]), int(source_images[0].shape[-2])],
            "guide_resolution": [
                int(full_artifacts(sequence_root, record, 0)["depth"]["width"]),
                int(full_artifacts(sequence_root, record, 0)["depth"]["height"]),
            ],
        },
        "device": str(device),
        "torch": torch.__version__,
        "gpu": torch.cuda.get_device_name(0) if device.type == "cuda" else None,
        "note": (
            "The same one-pass student was applied repeatedly. It was trained on "
            "128x128 crops, so 4x full-frame output is exploratory and not a trained cascade."
        ),
        "models": {},
    }

    for name in model_names:
        include_guides = name == "guided"
        channels = 6 if include_guides else 3
        model = TinyStudent(channels).to(device)
        checkpoint = checkpoint_dir / f"model_{name}_best.pt"
        model.load_state_dict(torch.load(checkpoint, map_location=device, weights_only=True))
        model.eval()
        eye_results: list[dict[str, Any]] = []
        rendered_by_eye: list[tuple[str, Image.Image, Image.Image, Image.Image, Image.Image]] = []
        for eye in (0, 1):
            result, images = render_model(
                model,
                source_images[eye],
                teacher_images[eye],
                guides[eye] if include_guides else None,
                args.passes,
                name,
                eye,
                output_dir,
                device,
            )
            eye_results.append(result)
            rendered_by_eye.append(
                (
                    f"eye {eye}",
                    tensor_to_image(source_images[eye]),
                    tensor_to_image(teacher_images[eye]),
                    images[1],
                    images[args.passes],
                )
            )
            progression = [
                tensor_to_image(source_images[eye]),
                tensor_to_image(teacher_images[eye]),
                images[1],
                *[images[index] for index in range(2, args.passes + 1)],
            ]
            make_sheet(
                progression,
                ["pre-NR input", "captured teacher", "our 1x"]
                + [f"our {index}x" for index in range(2, args.passes + 1)],
                output_dir / f"fullframe_{name}_eye{eye}_progression.png",
            )
        make_stereo_sheet(
            rendered_by_eye,
            output_dir / f"fullframe_{name}_stereo_1x_4x.png",
        )
        all_results["models"][name] = {"eyes": eye_results}
        del model
        if device.type == "cuda":
            torch.cuda.empty_cache()

    (output_dir / "fullframe_render_metrics.json").write_text(
        json.dumps(all_results, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(all_results, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
