"""Train a tiny learned resolver on stateful reduced native outputs.

This is a bounded offline pilot.  It uses existing full-resolution Skyrim
teacher pairs plus saved reduced native outputs, keeps the final head exactly
at the naive residual baseline at step zero, and evaluates a held-out suffix
of the same short sequence.  It is not a temporal or VR promotion test.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import time
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as F

from scale_resolve_student import (
    GuidedScaleResolveStudent,
    ScaleResolveConfig,
    ScaleResolveStudent,
    config_dict,
)


FULL_WIDTH = 2496
FULL_HEIGHT = 2688
GUIDE_WIDTH = 1664
GUIDE_HEIGHT = 1792


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_rgb8(path: Path, width: int, height: int) -> torch.Tensor:
    payload = path.read_bytes()
    expected = width * height * 4
    if len(payload) != expected:
        raise ValueError(f"{path} has {len(payload)} bytes; expected {expected}")
    array = np.frombuffer(payload, dtype=np.uint8).reshape(height, width, 4)[:, :, :3].copy()
    return torch.from_numpy(array.transpose(2, 0, 1)).float() / 255.0


def metrics(pred: torch.Tensor, target: torch.Tensor, source: torch.Tensor) -> dict[str, float]:
    error = pred - target
    source_error = source - target
    mae = float(error.abs().mean().item())
    rmse = float(error.square().mean().sqrt().item())
    identity_mae = float(source_error.abs().mean().item())
    return {
        "mae": mae,
        "rmse": rmse,
        "identity_mae": identity_mae,
        "improvement_vs_identity_mae": identity_mae - mae,
        "psnr_db": float(20.0 * np.log10(1.0 / max(rmse, 1e-12))),
        "finite": int(bool(torch.isfinite(pred).all().item())),
    }


def frame_paths(replay_root: Path, sequence: Path, frame_id: int, eye: int) -> dict[str, Path]:
    frame_dir = sequence / "frames" / f"frame_{frame_id:08d}"
    replay_dir = replay_root / f"frame_{frame_id:08d}"
    return {
        "source": frame_dir / f"input_eye{eye}_full.raw.bin",
        "teacher": frame_dir / f"teacher_eye{eye}_full.raw.bin",
        "depth": frame_dir / f"depth_eye{eye}_full.raw.bin",
        "motion": frame_dir / f"motion_vectors_eye{eye}_full.raw.bin",
        "small_input": replay_dir / f"input_eye{eye}.rgba",
        "small_output": replay_dir / f"teacher_eye{eye}.rgba",
    }


def read_guides(paths: dict[str, Path], device: torch.device) -> torch.Tensor:
    depth_payload = paths["depth"].read_bytes()
    motion_payload = paths["motion"].read_bytes()
    depth_expected = GUIDE_WIDTH * GUIDE_HEIGHT * 4
    motion_expected = GUIDE_WIDTH * GUIDE_HEIGHT * 2 * 2
    if len(depth_payload) != depth_expected:
        raise ValueError(f"{paths['depth']} has {len(depth_payload)} bytes; expected {depth_expected}")
    if len(motion_payload) != motion_expected:
        raise ValueError(f"{paths['motion']} has {len(motion_payload)} bytes; expected {motion_expected}")
    depth = np.frombuffer(depth_payload, dtype="<f4").reshape(GUIDE_HEIGHT, GUIDE_WIDTH, 1)
    motion = np.frombuffer(motion_payload, dtype="<f2").reshape(GUIDE_HEIGHT, GUIDE_WIDTH, 2).astype(np.float32)
    depth = np.nan_to_num(depth, nan=0.0, posinf=0.0, neginf=0.0).clip(0.0, 1.0)
    motion = np.nan_to_num(motion, nan=0.0, posinf=0.0, neginf=0.0).clip(-128.0, 128.0) / 128.0
    guide = torch.from_numpy(np.concatenate((depth, motion), axis=2).transpose(2, 0, 1)).unsqueeze(0)
    return F.interpolate(
        guide.to(device), size=(FULL_HEIGHT, FULL_WIDTH), mode="bilinear", align_corners=False
    )


def load_item(
    replay_root: Path,
    sequence: Path,
    frame_id: int,
    eye: int,
    small_width: int,
    small_height: int,
    device: torch.device,
    guided: bool,
) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor, torch.Tensor | None]:
    paths = frame_paths(replay_root, sequence, frame_id, eye)
    source = read_rgb8(paths["source"], FULL_WIDTH, FULL_HEIGHT).unsqueeze(0).to(device)
    teacher = read_rgb8(paths["teacher"], FULL_WIDTH, FULL_HEIGHT).unsqueeze(0).to(device)
    small_input = read_rgb8(paths["small_input"], small_width, small_height).unsqueeze(0).to(device)
    small_output = read_rgb8(paths["small_output"], small_width, small_height).unsqueeze(0).to(device)
    edit = F.interpolate(
        small_output - small_input,
        size=(FULL_HEIGHT, FULL_WIDTH),
        mode="bilinear",
        align_corners=False,
    )
    guides = read_guides(paths, device) if guided else None
    return source, teacher, edit, guides


def evaluate_split(
    model: ScaleResolveStudent | GuidedScaleResolveStudent,
    items: list[tuple[int, int]],
    replay_root: Path,
    sequence: Path,
    small_width: int,
    small_height: int,
    device: torch.device,
    guided: bool,
) -> dict[str, object]:
    records: list[dict[str, object]] = []
    with torch.inference_mode():
        for frame_id, eye in items:
            source, teacher, edit, guides = load_item(
                replay_root, sequence, frame_id, eye, small_width, small_height, device, guided
            )
            naive = (source + edit).clamp(0.0, 1.0)
            prediction = model(source, edit, guides) if guided else model(source, edit)
            records.append(
                {
                    "frame_id": frame_id,
                    "eye": eye,
                    "naive": metrics(naive, teacher, source),
                    "learned": metrics(prediction, teacher, source),
                }
            )
            del source, teacher, edit, guides, naive, prediction
    naive = [record["naive"] for record in records]
    learned = [record["learned"] for record in records]
    return {
        "sample_count": len(records),
        "records": records,
        "naive_mae_mean": float(np.mean([item["mae"] for item in naive])),
        "learned_mae_mean": float(np.mean([item["mae"] for item in learned])),
        "naive_identity_improvement_mean": float(
            np.mean([item["improvement_vs_identity_mae"] for item in naive])
        ),
        "learned_identity_improvement_mean": float(
            np.mean([item["improvement_vs_identity_mae"] for item in learned])
        ),
        "learned_better_than_naive_samples": int(
            sum(item["mae"] < baseline["mae"] for item, baseline in zip(learned, naive))
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--replay-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--train-through", type=int, default=6)
    parser.add_argument("--steps", type=int, default=600)
    parser.add_argument("--crop-size", type=int, default=512)
    parser.add_argument("--lr", type=float, default=2e-4)
    parser.add_argument("--hidden-channels", type=int, default=24)
    parser.add_argument("--layers", type=int, default=2)
    parser.add_argument("--seed", type=int, default=5012)
    parser.add_argument("--device", default="cuda")
    parser.add_argument(
        "--guided",
        action="store_true",
        help="include exact full-resolution depth and motion guides in the resolver",
    )
    args = parser.parse_args()

    if args.output.exists() and any(args.output.iterdir()):
        raise FileExistsError(f"refusing to use non-empty output directory: {args.output}")
    if args.steps < 1 or args.crop_size < 32 or args.train_through < 1:
        raise ValueError("invalid training arguments")
    args.output.mkdir(parents=True, exist_ok=True)
    replay_root = args.replay_root.resolve()
    manifest_path = replay_root / "input_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    sequence = Path(manifest["sequence"])
    frames = [int(value) for value in manifest["frames"]]
    if args.train_through >= len(frames):
        raise ValueError("train-through must leave at least one held-out frame")
    small_width, small_height = (int(value) for value in manifest["network_dimensions"])
    device = torch.device(args.device)
    if device.type == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("CUDA is unavailable")

    random.seed(args.seed)
    np.random.seed(args.seed)
    torch.manual_seed(args.seed)
    if device.type == "cuda":
        torch.cuda.manual_seed_all(args.seed)

    config = ScaleResolveConfig(
        hidden_channels=args.hidden_channels,
        layers=args.layers,
    )
    model: ScaleResolveStudent | GuidedScaleResolveStudent
    if args.guided:
        model = GuidedScaleResolveStudent(config).to(device).train()
    else:
        model = ScaleResolveStudent(config).to(device).train()
    optimizer = torch.optim.AdamW(model.parameters(), lr=args.lr)
    train_items = [(frame_id, eye) for frame_id in frames[: args.train_through] for eye in range(2)]
    validation_items = [(frame_id, eye) for frame_id in frames[args.train_through :] for eye in range(2)]
    # Cache the small pilot's training tensors on the selected device.  This
    # keeps disk I/O out of the optimization loop; the retained eight-frame
    # pilot is small enough to fit comfortably beside the model.
    train_cache = {
        item: load_item(
            replay_root, sequence, item[0], item[1], small_width, small_height, device, args.guided
        )
        for item in train_items
    }
    history: list[float] = []
    started = time.perf_counter()

    for step in range(args.steps):
        frame_id, eye = train_items[step % len(train_items)]
        source, teacher, edit, guides = train_cache[(frame_id, eye)]
        height, width = source.shape[-2:]
        top = random.randint(0, height - args.crop_size)
        left = random.randint(0, width - args.crop_size)
        source_crop = source[:, :, top : top + args.crop_size, left : left + args.crop_size]
        teacher_crop = teacher[:, :, top : top + args.crop_size, left : left + args.crop_size]
        edit_crop = edit[:, :, top : top + args.crop_size, left : left + args.crop_size]
        guides_crop = (
            guides[:, :, top : top + args.crop_size, left : left + args.crop_size]
            if guides is not None
            else None
        )
        prediction = model(source_crop, edit_crop, guides_crop) if args.guided else model(source_crop, edit_crop)
        naive_crop = (source_crop + edit_crop).clamp(0.0, 1.0)
        loss = (prediction - teacher_crop).abs().mean()
        # Keep the resolver conservative: the initial function is the naive
        # residual, and this penalty discourages gratuitous full-frame edits.
        loss = loss + 0.02 * (prediction - naive_crop).abs().mean()
        if not torch.isfinite(loss):
            raise RuntimeError(f"non-finite loss at step {step}")
        optimizer.zero_grad(set_to_none=True)
        loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
        optimizer.step()
        history.append(float(loss.detach().cpu()))
        del source_crop, teacher_crop, edit_crop, guides_crop, prediction, naive_crop, loss

    model.eval()
    del train_cache
    if device.type == "cuda":
        torch.cuda.empty_cache()
    validation = evaluate_split(
        model, validation_items, replay_root, sequence, small_width, small_height, device, args.guided
    )
    training_fit = evaluate_split(
        model, train_items, replay_root, sequence, small_width, small_height, device, args.guided
    )
    checkpoint = {
        "architecture": "scale_resolve_student_v1",
        "guided": bool(args.guided),
        "config": config_dict(config),
        "model": {name: value.detach().cpu() for name, value in model.state_dict().items()},
        "step": args.steps,
        "seed": args.seed,
        "learning_rate": args.lr,
        "crop_size": args.crop_size,
        "replay_root": str(replay_root),
        "replay_manifest_sha256": sha256(manifest_path),
        "sequence": str(sequence),
        "scale_percent": int(manifest["scale_percent"]),
        "frames": frames,
        "train_through": args.train_through,
        "loss_history": history,
        "validation": validation,
        "training_fit": training_fit,
        "wall_seconds": time.perf_counter() - started,
        "promotion": False,
        "live_runtime_tested": False,
    }
    checkpoint_path = args.output / "best.pt"
    torch.save(checkpoint, checkpoint_path)
    report = {
        "schema": "opennr-scale-resolve-student-training-v1",
        "checkpoint": str(checkpoint_path),
        "checkpoint_sha256": sha256(checkpoint_path),
        "architecture": checkpoint["architecture"],
        "guided": checkpoint["guided"],
        "config": checkpoint["config"],
        "replay_root": str(replay_root),
        "replay_manifest_sha256": checkpoint["replay_manifest_sha256"],
        "scale_percent": checkpoint["scale_percent"],
        "frames": frames,
        "train_through": args.train_through,
        "steps": args.steps,
        "training_fit": training_fit,
        "validation": validation,
        "wall_seconds": checkpoint["wall_seconds"],
        "scope": "bounded offline learned-resolve pilot; not temporal/stereo/VR acceptance",
        "promotion": False,
    }
    (args.output / "result.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
