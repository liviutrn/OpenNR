"""Train a tiny full-resolution detail correction over a native 50% residual.

This is an upper-bound diagnostic for a two-band design.  The base image is
the *actual* native 50% residual composite, not the learned student, so a
positive result only says that a cheap detail head can recover information
from the raw frame when the coarse neural base is already correct.

All outputs live on C:.  The captured replay files are read-only inputs and
the live OpenNR/Skyrim runtime is not touched.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np
import torch
import torch.nn.functional as F
from PIL import Image, ImageDraw
from torch import nn


FULL_WIDTH = 2496
FULL_HEIGHT = 2688
DEFAULT_REPLAY_ROOT = Path(r"C:\OpenNR\NativeReplays50_20260912")
DEFAULT_TEST_NAME = "seq-1789064397821-5_f1-16"
DEFAULT_VALID_NAME = "seq-1789064544626-6_f1-16"
DEFAULT_OUTPUT = Path(r"C:\OpenNR\Native50DetailHeadPilot_20260912")


def _add_tools_path() -> None:
    tools_path = Path(r"D:\.CODEX_Projects\OpenNR-VR\tools")
    if str(tools_path) not in sys.path:
        sys.path.insert(0, str(tools_path))


_add_tools_path()
from evaluate_fast_student_trt_full_eye import _read_full_rgb, _read_rgba8  # noqa: E402


class DetailHead(nn.Module):
    """Very small local full-resolution residual correction network."""

    def __init__(self, channels: int = 24):
        super().__init__()
        self.features = nn.Sequential(
            nn.Conv2d(6, channels, 3, padding=1),
            nn.SiLU(),
            nn.Conv2d(channels, channels, 5, padding=2, groups=channels),
            nn.SiLU(),
            nn.Conv2d(channels, channels, 1),
            nn.SiLU(),
        )
        self.output = nn.Conv2d(channels, 3, 1)
        nn.init.zeros_(self.output.weight)
        nn.init.zeros_(self.output.bias)

    def forward(self, raw: torch.Tensor, base: torch.Tensor) -> torch.Tensor:
        return self.output(self.features(torch.cat((raw, base), dim=1)))


def _manifest(root: Path) -> dict[str, Any]:
    value = json.loads((root / "input_manifest.json").read_text(encoding="utf-8"))
    sequence = Path(value["sequence"]).resolve()
    frames = [int(item) for item in value["frames"]]
    work_width, work_height = (int(item) for item in value["network_dimensions"])
    return {
        "root": root.resolve(),
        "sequence": sequence,
        "frames": frames,
        "work_width": work_width,
        "work_height": work_height,
    }


def _item(manifest: dict[str, Any], frame_id: int, eye: int) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
    frame_dir = manifest["sequence"] / "frames" / f"frame_{frame_id:08d}"
    replay_dir = manifest["root"] / f"frame_{frame_id:08d}"
    full_input = _read_full_rgb(frame_dir / f"input_eye{eye}_full.raw.bin").float()
    full_teacher = _read_full_rgb(frame_dir / f"teacher_eye{eye}_full.raw.bin").float()
    work_input = _read_rgba8(
        replay_dir / f"input_eye{eye}.rgba",
        manifest["work_width"],
        manifest["work_height"],
    ).float()
    native_work = _read_rgba8(
        replay_dir / f"teacher_eye{eye}.rgba",
        manifest["work_width"],
        manifest["work_height"],
    ).float()
    native_residual = native_work - work_input
    native_residual = F.interpolate(
        native_residual,
        size=(FULL_HEIGHT, FULL_WIDTH),
        mode="bilinear",
        align_corners=False,
    )
    base = (full_input + native_residual).clamp(0.0, 1.0)
    return full_input, full_teacher, base


def _crop(
    full_input: torch.Tensor,
    full_teacher: torch.Tensor,
    base: torch.Tensor,
    crop_size: int,
    rng: random.Random,
) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
    top = rng.randrange(FULL_HEIGHT - crop_size + 1)
    left = rng.randrange(FULL_WIDTH - crop_size + 1)
    crop = (..., slice(top, top + crop_size), slice(left, left + crop_size))
    return full_input[crop], full_teacher[crop], base[crop]


def _gradient(value: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
    return value[..., :, 1:] - value[..., :, :-1], value[..., 1:, :] - value[..., :-1, :]


def _loss(prediction: torch.Tensor, target: torch.Tensor) -> torch.Tensor:
    value = (prediction - target).abs().mean()
    pred_x, pred_y = _gradient(prediction)
    target_x, target_y = _gradient(target)
    value = value + 0.25 * ((pred_x - target_x).abs().mean() + (pred_y - target_y).abs().mean())
    return value


def _metrics(prediction: torch.Tensor, teacher: torch.Tensor, raw: torch.Tensor) -> dict[str, float]:
    error = prediction.float() - teacher.float()
    identity = raw.float() - teacher.float()
    return {
        "mae": float(error.abs().mean().item()),
        "identity_mae": float(identity.abs().mean().item()),
        "improvement": float(identity.abs().mean().item() - error.abs().mean().item()),
        "rmse": float(error.square().mean().sqrt().item()),
    }


def _validation(
    model: DetailHead,
    manifest: dict[str, Any],
    frame_ids: list[int],
    crop_size: int,
    device: torch.device,
) -> dict[str, float]:
    model.eval()
    values: list[dict[str, float]] = []
    with torch.inference_mode():
        for frame_id in frame_ids:
            for eye in (0, 1):
                full_input, full_teacher, base = _item(manifest, frame_id, eye)
                # The fixed center crop is deliberately deterministic and
                # sequence-disjoint from the random training crops.
                top = (FULL_HEIGHT - crop_size) // 2
                left = (FULL_WIDTH - crop_size) // 2
                crop = (..., slice(top, top + crop_size), slice(left, left + crop_size))
                raw = full_input[crop].to(device)
                teacher = full_teacher[crop].to(device)
                base_gpu = base[crop].to(device)
                correction = model(raw, base_gpu)
                enhanced = (base_gpu + correction).clamp(0.0, 1.0)
                values.append(_metrics(enhanced, teacher, raw))

    return {
        "sample_count": len(values),
        "mae": float(np.mean([item["mae"] for item in values])),
        "identity_mae": float(np.mean([item["identity_mae"] for item in values])),
        "improvement": float(np.mean([item["improvement"] for item in values])),
        "better_samples": int(sum(item["improvement"] > 0 for item in values)),
    }


def _to_image(value: torch.Tensor) -> Image.Image:
    array = value.detach().float().clamp(0.0, 1.0)[0].permute(1, 2, 0).mul(255.0).round().byte().cpu().numpy()
    return Image.fromarray(array, mode="RGB")


def _panel(items: list[tuple[str, Image.Image]], path: Path, crop: tuple[int, int, int, int] | None = None) -> None:
    display_width = 560
    caption_height = 34
    prepared: list[tuple[str, Image.Image]] = []
    for label, image in items:
        if crop is not None:
            image = image.crop(crop)
        scale = display_width / image.width
        prepared.append((label, image.resize((display_width, max(1, round(image.height * scale))), Image.Resampling.LANCZOS)))
    height = caption_height + max(image.height for _, image in prepared)
    result = Image.new("RGB", (display_width * len(prepared), height), (20, 20, 20))
    draw = ImageDraw.Draw(result)
    for index, (label, image) in enumerate(prepared):
        x = index * display_width
        result.paste(image, (x, caption_height))
        draw.rectangle((x, 0, x + display_width - 1, caption_height - 1), fill=(20, 20, 20))
        draw.text((x + 10, 9), label, fill=(245, 245, 245))
    path.parent.mkdir(parents=True, exist_ok=True)
    result.save(path, quality=94, subsampling=0)


def _evaluate_full_frame(
    model: DetailHead,
    manifest: dict[str, Any],
    frame_id: int,
    eye: int,
    device: torch.device,
) -> tuple[dict[str, float], list[tuple[str, Image.Image]]]:
    model.eval()
    with torch.inference_mode():
        full_input, full_teacher, base = _item(manifest, frame_id, eye)
        raw = full_input.to(device)
        teacher = full_teacher.to(device)
        base_gpu = base.to(device)
        enhanced = (base_gpu + model(raw, base_gpu)).clamp(0.0, 1.0)
        metrics = _metrics(enhanced, teacher, raw)
        images = [
            ("Raw input", _to_image(raw)),
            ("Native 50% residual", _to_image(base_gpu)),
            ("+ detail head", _to_image(enhanced)),
            ("Full native teacher", _to_image(teacher)),
        ]
    return metrics, images


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--replay-root", type=Path, default=DEFAULT_REPLAY_ROOT)
    parser.add_argument("--test-name", default=DEFAULT_TEST_NAME)
    parser.add_argument("--validation-name", default=DEFAULT_VALID_NAME)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--steps", type=int, default=300)
    parser.add_argument("--batch-size", type=int, default=2)
    parser.add_argument("--crop-size", type=int, default=512)
    parser.add_argument("--lr", type=float, default=1e-3)
    parser.add_argument("--eval-every", type=int, default=50)
    parser.add_argument("--seed", type=int, default=20260912)
    parser.add_argument("--device", default="cuda")
    args = parser.parse_args()

    if args.device.startswith("cuda") and not torch.cuda.is_available():
        raise RuntimeError("CUDA is unavailable")
    if args.output.exists() and any(args.output.iterdir()):
        raise FileExistsError(f"refusing non-empty output: {args.output}")
    if args.crop_size < 32 or args.crop_size > min(FULL_HEIGHT, FULL_WIDTH):
        raise ValueError("invalid crop size")

    args.output.mkdir(parents=True, exist_ok=True)
    random.seed(args.seed)
    np.random.seed(args.seed)
    torch.manual_seed(args.seed)
    if args.device.startswith("cuda"):
        torch.cuda.manual_seed_all(args.seed)
        torch.backends.cudnn.benchmark = True
    device = torch.device(args.device)

    roots = sorted(args.replay_root.glob("seq-*_f1-16"))
    test_root = (args.replay_root / args.test_name).resolve()
    valid_root = (args.replay_root / args.validation_name).resolve()
    train_roots = [root.resolve() for root in roots if root.resolve() not in {test_root, valid_root}][:10]
    if len(train_roots) < 4:
        raise RuntimeError(f"not enough training replay roots: {train_roots}")
    train_manifests = [_manifest(root) for root in train_roots]
    valid_manifest = _manifest(valid_root)
    test_manifest = _manifest(test_root)
    train_frames = list(range(1, 13))
    valid_frames = list(range(13, 17))
    test_frames = test_manifest["frames"]

    model = DetailHead().to(device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=args.lr, weight_decay=1e-4)
    train_rng = random.Random(args.seed)
    best_value = float("inf")
    history: list[dict[str, Any]] = []
    started = time.perf_counter()

    def evaluate_and_save(step: int) -> dict[str, float]:
        nonlocal best_value
        result = _validation(model, valid_manifest, valid_frames, args.crop_size, device)
        record = {"step": step, "validation": result}
        history.append(record)
        if result["mae"] < best_value:
            best_value = result["mae"]
            torch.save(
                {
                    "architecture": "native50_detail_head_v1",
                    "model": {name: value.detach().cpu() for name, value in model.state_dict().items()},
                    "channels": 24,
                    "crop_size": args.crop_size,
                    "step": step,
                    "seed": args.seed,
                    "learning_rate": args.lr,
                    "base": "actual_native_50_percent_residual_composite",
                    "target": "full_native_teacher_minus_native50_composite",
                    "train_roots": [str(item["root"]) for item in train_manifests],
                    "validation_root": str(valid_manifest["root"]),
                    "promotion": False,
                    "live_runtime_tested": False,
                },
                args.output / "best.pt",
            )
        (args.output / "history.jsonl").write_text(
            "\n".join(json.dumps(item) for item in history) + "\n", encoding="utf-8"
        )
        print(json.dumps(record), flush=True)
        return result

    evaluate_and_save(0)
    for step in range(1, args.steps + 1):
        model.train()
        optimizer.zero_grad(set_to_none=True)
        losses: list[torch.Tensor] = []
        for _ in range(args.batch_size):
            manifest = train_manifests[train_rng.randrange(len(train_manifests))]
            frame_id = train_frames[train_rng.randrange(len(train_frames))]
            eye = train_rng.randrange(2)
            full_input, full_teacher, base = _item(manifest, frame_id, eye)
            raw, teacher, base = _crop(full_input, full_teacher, base, args.crop_size, train_rng)
            raw = raw.to(device)
            teacher = teacher.to(device)
            base = base.to(device)
            prediction = model(raw, base)
            losses.append(_loss(prediction, teacher - base))
        loss = torch.stack(losses).mean()
        loss.backward()
        gradient = torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
        if not torch.isfinite(gradient):
            raise RuntimeError(f"non-finite gradient at step {step}")
        optimizer.step()
        if step == 1 or step % 25 == 0:
            print(json.dumps({"step": step, "loss": float(loss.detach().cpu()), "seconds": time.perf_counter() - started}), flush=True)
        if step % args.eval_every == 0 or step == args.steps:
            evaluate_and_save(step)

    checkpoint = torch.load(args.output / "best.pt", map_location=device, weights_only=True)
    model.load_state_dict(checkpoint["model"])
    test_records: list[dict[str, float | int]] = []
    with torch.inference_mode():
        for frame_id in test_frames:
            for eye in (0, 1):
                metrics, images = _evaluate_full_frame(model, test_manifest, frame_id, eye, device)
                test_records.append({"frame_id": frame_id, "eye": eye, **metrics})
                if frame_id == 8 and eye == 0:
                    _panel(images, args.output / "frame_00000008_eye0_comparison.jpg")
                    _panel(images, args.output / "frame_00000008_eye0_face_comparison.jpg", (1250, 620, 2300, 1730))

    final = {
        "schema": "opennr-native50-detail-head-pilot-v1",
        "checkpoint": str((args.output / "best.pt").resolve()),
        "parameters": sum(parameter.numel() for parameter in model.parameters()),
        "steps": args.steps,
        "batch_size": args.batch_size,
        "crop_size": args.crop_size,
        "train_roots": [str(item["root"]) for item in train_manifests],
        "validation_root": str(valid_manifest["root"]),
        "test_root": str(test_manifest["root"]),
        "validation_best": history[-1]["validation"] if history else None,
        "test_records": test_records,
        "test_mae": float(np.mean([item["mae"] for item in test_records])),
        "test_identity_mae": float(np.mean([item["identity_mae"] for item in test_records])),
        "test_improvement": float(np.mean([item["improvement"] for item in test_records])),
        "test_better_samples": int(sum(item["improvement"] > 0 for item in test_records)),
        "wall_seconds": time.perf_counter() - started,
        "promotion": False,
        "live_runtime_tested": False,
        "scope": "upper-bound full-resolution detail head over actual native 50% residual; not a student/runtime/VR acceptance result",
    }
    (args.output / "result.json").write_text(json.dumps(final, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(final, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
