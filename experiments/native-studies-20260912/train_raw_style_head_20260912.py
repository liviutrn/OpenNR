"""Train a tiny guide-conditioned RGB style head without using native output as input."""

from __future__ import annotations

import json
import random
import sys
import time
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as F
from PIL import Image, ImageDraw
from torch import nn

TOOLS = Path(r"D:\.CODEX_Projects\OpenNR-VR\tools")
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from evaluate_fast_student_trt_full_eye import (  # noqa: E402
    FULL_HEIGHT,
    FULL_WIDTH,
    _read_full_rgb,
    _read_guides,
)


DATA_ROOT = Path(r"C:\OpenNR\NativeReplays50_20260912")
TEST_NAME = "seq-1789064397821-5_f1-16"
VALID_NAME = "seq-1789064544626-6_f1-16"
OUTPUT = Path(r"C:\OpenNR\OpenNR_RawStyleHeadPilot_20260912")
FACE_CROP = (1480, 700, 1980, 1300)


class RawStyleHead(nn.Module):
    """A small local residual head using only RGB and native guide channels."""

    def __init__(self, channels: int = 32):
        super().__init__()
        self.features = nn.Sequential(
            nn.Conv2d(8, channels, 3, padding=1),
            nn.SiLU(),
            nn.Conv2d(channels, channels, 5, padding=2, groups=channels),
            nn.SiLU(),
            nn.Conv2d(channels, channels, 1),
            nn.SiLU(),
        )
        self.output = nn.Conv2d(channels, 3, 1)
        nn.init.zeros_(self.output.weight)
        nn.init.zeros_(self.output.bias)

    def forward(self, raw: torch.Tensor, guides: torch.Tensor) -> torch.Tensor:
        return self.output(self.features(torch.cat((raw, guides), dim=1)))


def _manifest(root: Path) -> dict:
    value = json.loads((root / "input_manifest.json").read_text(encoding="utf-8"))
    return {
        "root": root.resolve(),
        "sequence": Path(value["sequence"]).resolve(),
        "frames": [int(item) for item in value["frames"]],
    }


def _item(manifest: dict, frame_id: int, eye: int) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
    frame_dir = manifest["sequence"] / "frames" / f"frame_{frame_id:08d}"
    raw = _read_full_rgb(frame_dir / f"input_eye{eye}_full.raw.bin").float()
    teacher = _read_full_rgb(frame_dir / f"teacher_eye{eye}_full.raw.bin").float()
    guides = _read_guides(frame_dir, eye).float()
    guides = F.interpolate(guides, size=(FULL_HEIGHT, FULL_WIDTH), mode="bilinear", align_corners=False)
    return raw, teacher, guides


def _crop(raw: torch.Tensor, teacher: torch.Tensor, guides: torch.Tensor, size: int, rng: random.Random):
    top = rng.randrange(FULL_HEIGHT - size + 1)
    left = rng.randrange(FULL_WIDTH - size + 1)
    window = (..., slice(top, top + size), slice(left, left + size))
    return raw[window], teacher[window], guides[window]


def _gradient(value: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
    return value[..., :, 1:] - value[..., :, :-1], value[..., 1:, :] - value[..., :-1, :]


def _loss(prediction: torch.Tensor, target: torch.Tensor) -> torch.Tensor:
    value = (prediction - target).abs().mean()
    pred_x, pred_y = _gradient(prediction)
    target_x, target_y = _gradient(target)
    return value + 0.25 * ((pred_x - target_x).abs().mean() + (pred_y - target_y).abs().mean())


def _metrics(prediction: torch.Tensor, teacher: torch.Tensor, raw: torch.Tensor) -> dict[str, float]:
    error = prediction.float() - teacher.float()
    identity = raw.float() - teacher.float()
    mae = float(error.abs().mean().item())
    identity_mae = float(identity.abs().mean().item())
    return {
        "mae": mae,
        "identity_mae": identity_mae,
        "improvement": identity_mae - mae,
        "rmse": float(error.square().mean().sqrt().item()),
    }


def _evaluate(model: RawStyleHead, manifest: dict, frames: list[int], device: torch.device) -> dict:
    model.eval()
    values: list[dict[str, float]] = []
    with torch.inference_mode():
        for frame_id in frames:
            for eye in (0, 1):
                raw, teacher, guides = _item(manifest, frame_id, eye)
                raw_gpu, teacher_gpu, guides_gpu = raw.to(device), teacher.to(device), guides.to(device)
                prediction = (raw_gpu + model(raw_gpu, guides_gpu)).clamp(0.0, 1.0)
                values.append(_metrics(prediction, teacher_gpu, raw_gpu))
    return {
        "sample_count": len(values),
        "mae": float(np.mean([item["mae"] for item in values])),
        "identity_mae": float(np.mean([item["identity_mae"] for item in values])),
        "improvement": float(np.mean([item["improvement"] for item in values])),
        "rmse": float(np.mean([item["rmse"] for item in values])),
        "better_samples": int(sum(item["improvement"] > 0 for item in values)),
    }


def _to_image(value: torch.Tensor) -> Image.Image:
    array = value.detach().float().clamp(0.0, 1.0)[0].permute(1, 2, 0).mul(255.0).round().byte().cpu().numpy()
    return Image.fromarray(array, mode="RGB")


def _panel(images: list[tuple[str, Image.Image]], path: Path, crop: tuple[int, int, int, int] | None) -> None:
    width = 560
    caption = 38
    prepared: list[tuple[str, Image.Image]] = []
    for label, image in images:
        if crop is not None:
            image = image.crop(crop)
        scale = width / image.width
        prepared.append((label, image.resize((width, max(1, round(image.height * scale))), Image.Resampling.LANCZOS)))
    height = caption + max(image.height for _, image in prepared)
    result = Image.new("RGB", (width * len(prepared), height), (20, 20, 20))
    draw = ImageDraw.Draw(result)
    for index, (label, image) in enumerate(prepared):
        x = index * width
        result.paste(image, (x, caption))
        draw.rectangle((x, 0, x + width - 1, caption - 1), fill=(20, 20, 20))
        draw.text((x + 10, 11), label, fill=(245, 245, 245))
    path.parent.mkdir(parents=True, exist_ok=True)
    result.save(path, quality=94, subsampling=0)


def main() -> int:
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is required")
    OUTPUT.mkdir(parents=True, exist_ok=True)
    if any(OUTPUT.iterdir()):
        raise FileExistsError(f"refusing non-empty output directory: {OUTPUT}")
    device = torch.device("cuda")
    random.seed(20260912)
    np.random.seed(20260912)
    torch.manual_seed(20260912)
    torch.cuda.manual_seed_all(20260912)
    train_roots = sorted(DATA_ROOT.glob("seq-*_f1-16"))
    test_root = (DATA_ROOT / TEST_NAME).resolve()
    valid_root = (DATA_ROOT / VALID_NAME).resolve()
    train_roots = [root for root in train_roots if root.resolve() not in {test_root, valid_root}][:10]
    train = [_manifest(root) for root in train_roots]
    valid = _manifest(valid_root)
    test = _manifest(test_root)
    model = RawStyleHead().to(device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=1e-3, weight_decay=1e-4)
    rng = random.Random(20260912)
    history: list[dict] = []
    best = float("inf")
    started = time.perf_counter()

    def validate(step: int) -> None:
        nonlocal best
        result = _evaluate(model, valid, [13, 14, 15, 16], device)
        history.append({"step": step, "validation": result})
        if result["mae"] < best:
            best = result["mae"]
            torch.save(
                {
                    "architecture": "raw_style_head_v1",
                    "model": {name: value.detach().cpu() for name, value in model.state_dict().items()},
                    "channels": 32,
                    "input": "raw_rgb_plus_upsampled_native_depth_motion_validity",
                    "target": "full_native_teacher",
                    "train_roots": [str(item["root"]) for item in train],
                    "validation_root": str(valid["root"]),
                    "step": step,
                    "promotion": False,
                    "live_runtime_tested": False,
                },
                OUTPUT / "best.pt",
            )
        (OUTPUT / "history.jsonl").write_text("\n".join(json.dumps(item) for item in history) + "\n", encoding="utf-8")
        print(json.dumps({"step": step, "validation": result}), flush=True)

    validate(0)
    for step in range(1, 301):
        model.train()
        optimizer.zero_grad(set_to_none=True)
        losses: list[torch.Tensor] = []
        for _ in range(2):
            manifest = train[rng.randrange(len(train))]
            frame_id = rng.randrange(1, 13)
            eye = rng.randrange(2)
            raw, teacher, guides = _crop(*_item(manifest, frame_id, eye), 512, rng)
            raw, teacher, guides = raw.to(device), teacher.to(device), guides.to(device)
            prediction = raw + model(raw, guides)
            losses.append(_loss(prediction, teacher))
        loss = torch.stack(losses).mean()
        loss.backward()
        gradient = torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
        if not torch.isfinite(gradient):
            raise RuntimeError(f"non-finite gradient at step {step}")
        optimizer.step()
        if step == 1 or step % 50 == 0:
            print(json.dumps({"step": step, "loss": float(loss.detach().cpu()), "seconds": time.perf_counter() - started}), flush=True)
        if step % 50 == 0 or step == 300:
            validate(step)

    checkpoint = torch.load(OUTPUT / "best.pt", map_location=device, weights_only=True)
    model.load_state_dict(checkpoint["model"])
    test_result = _evaluate(model, test, test["frames"], device)
    raw, teacher, guides = _item(test, 8, 0)
    raw_gpu, teacher_gpu, guides_gpu = raw.to(device), teacher.to(device), guides.to(device)
    with torch.inference_mode():
        enhanced = (raw_gpu + model(raw_gpu, guides_gpu)).clamp(0.0, 1.0)
    images = [("Raw input", _to_image(raw_gpu)), ("Raw style head", _to_image(enhanced)), ("Full native teacher", _to_image(teacher_gpu))]
    _panel(images, OUTPUT / "frame_00000008_eye0_face_comparison.jpg", FACE_CROP)
    _panel(images, OUTPUT / "frame_00000008_eye0_full_comparison.jpg", None)
    final = {
        "schema": "opennr-raw-style-head-pilot-v1",
        "checkpoint": str((OUTPUT / "best.pt").resolve()),
        "parameters": sum(parameter.numel() for parameter in model.parameters()),
        "steps": 300,
        "test": test_result,
        "validation_best_mae": best,
        "wall_seconds": time.perf_counter() - started,
        "promotion": False,
        "live_runtime_tested": False,
        "scope": "offline raw-plus-real-guides style probe; no native output is used as an inference input and no temporal/stereo/VR acceptance",
    }
    (OUTPUT / "result.json").write_text(json.dumps(final, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(final, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
