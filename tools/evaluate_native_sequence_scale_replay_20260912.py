"""Evaluate a stateful reduced native replay with direct and residual resolves."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as F


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
    return torch.from_numpy(array.transpose(2, 0, 1)).unsqueeze(0).float() / 255.0


def metrics(pred: np.ndarray, target: np.ndarray, source: np.ndarray) -> dict[str, float | int]:
    error = pred - target
    source_error = source - target
    mae = float(np.mean(np.abs(error)))
    rmse = float(np.sqrt(np.mean(np.square(error))))
    identity_mae = float(np.mean(np.abs(source_error)))
    return {
        "mae": mae,
        "rmse": rmse,
        "psnr_db": float(20.0 * math.log10(1.0 / max(rmse, 1e-12))),
        "identity_mae": identity_mae,
        "improvement_vs_identity_mae": identity_mae - mae,
        "better_fraction_pixels": float(np.mean(np.abs(error) < np.abs(source_error))),
        "finite": int(bool(np.isfinite(pred).all())),
    }


def as_hwc(tensor: torch.Tensor) -> np.ndarray:
    return tensor.detach().float().cpu()[0].permute(1, 2, 0).numpy()


def save_preview(path: Path, images: list[tuple[str, np.ndarray]]) -> None:
    from PIL import Image, ImageDraw

    max_width = 480
    rendered: list[tuple[str, Image.Image]] = []
    for label, array in images:
        image = Image.fromarray(np.clip(np.rint(array * 255.0), 0, 255).astype(np.uint8), mode="RGB")
        scale = min(1.0, max_width / image.width)
        image = image.resize(
            (max(1, int(image.width * scale)), max(1, int(image.height * scale))),
            Image.Resampling.BILINEAR,
        )
        rendered.append((label, image))
    label_height = 30
    width = max(image.width for _, image in rendered)
    height = max(image.height for _, image in rendered)
    canvas = Image.new("RGB", (width * len(rendered), height + label_height), (24, 24, 24))
    draw = ImageDraw.Draw(canvas)
    for index, (label, image) in enumerate(rendered):
        left = index * width
        draw.text((left + 8, 7), label, fill=(240, 240, 240))
        canvas.paste(image, (left, label_height))
    path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(path, quality=94)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--replay-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--save-previews", action="store_true")
    args = parser.parse_args()

    if args.output.exists() and any(args.output.iterdir()):
        raise FileExistsError(f"refusing to use non-empty output directory: {args.output}")
    args.output.mkdir(parents=True, exist_ok=True)
    replay_root = args.replay_root.resolve()
    manifest_path = replay_root / "input_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    sequence = Path(manifest["sequence"])
    frames = [int(value) for value in manifest["frames"]]
    scale = int(manifest["scale_percent"])
    full_width, full_height = FULL_WIDTH, FULL_HEIGHT
    small_width, small_height = (int(value) for value in manifest["network_dimensions"])
    device = torch.device(args.device)
    if device.type == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("CUDA was requested but is unavailable")

    timing_rows: list[dict[str, str]] = []
    timing_path = replay_root / "timings.csv"
    if timing_path.is_file():
        with timing_path.open(newline="", encoding="utf-8") as handle:
            timing_rows = list(csv.DictReader(handle))

    result: dict[str, object] = {
        "schema": "opennr-native-sequence-scale-replay-evaluation-v1",
        "replay_root": str(replay_root),
        "replay_manifest_sha256": sha256(manifest_path),
        "sequence": str(sequence),
        "frames": frames,
        "scale_percent": scale,
        "full_shape": [full_width, full_height],
        "network_shape": [small_width, small_height],
        "device": str(device),
        "gpu": torch.cuda.get_device_name(device) if device.type == "cuda" else None,
        "scope": (
            "Low-resolution native outputs were generated in one process with a"
            " reset only on the first frame. Direct and matched-residual resolves"
            " are offline comparisons against captured full-resolution teachers."
        ),
        "eyes": [],
        "aggregate": {},
        "native_timing": timing_rows,
        "promotion": False,
        "live_runtime_tested": False,
    }

    eye_predictions: dict[int, list[np.ndarray]] = {0: [], 1: []}
    eye_targets: dict[int, list[np.ndarray]] = {0: [], 1: []}
    eye_records: list[dict[str, object]] = []
    for eye in range(2):
        records: list[dict[str, object]] = []
        for frame_id in frames:
            frame_dir = sequence / "frames" / f"frame_{frame_id:08d}"
            replay_dir = replay_root / f"frame_{frame_id:08d}"
            full_source = read_rgb8(
                frame_dir / f"input_eye{eye}_full.raw.bin", full_width, full_height
            ).to(device)
            full_target = read_rgb8(
                frame_dir / f"teacher_eye{eye}_full.raw.bin", full_width, full_height
            ).to(device)
            small_input = read_rgb8(
                replay_dir / f"input_eye{eye}.rgba", small_width, small_height
            ).to(device)
            small_output = read_rgb8(
                replay_dir / f"teacher_eye{eye}.rgba", small_width, small_height
            ).to(device)
            direct = F.interpolate(
                small_output,
                size=(full_height, full_width),
                mode="bilinear",
                align_corners=False,
            )
            matched = (
                full_source
                + F.interpolate(
                    small_output - small_input,
                    size=(full_height, full_width),
                    mode="bilinear",
                    align_corners=False,
                )
            ).clamp(0.0, 1.0)
            source_np = as_hwc(full_source)
            target_np = as_hwc(full_target)
            direct_np = as_hwc(direct)
            matched_np = as_hwc(matched)
            eye_predictions[eye].append(matched_np)
            eye_targets[eye].append(target_np)
            records.append(
                {
                    "frame_id": frame_id,
                    "direct_upsample": metrics(direct_np, target_np, source_np),
                    "matched_residual": metrics(matched_np, target_np, source_np),
                }
            )
            if args.save_previews and eye == 0 and frame_id in (frames[0], frames[-1]):
                save_preview(
                    args.output / "previews" / f"eye0_frame{frame_id:08d}_scale{scale:03d}.jpg",
                    [
                        ("Full input", source_np),
                        ("Full teacher", target_np),
                        (f"Direct {scale}%", direct_np),
                        (f"Residual {scale}%", matched_np),
                    ],
                )
            del full_source, full_target, small_input, small_output, direct, matched
        temporal_direct: list[float] = []
        temporal_matched: list[float] = []
        for index in range(1, len(frames)):
            target_delta = eye_targets[eye][index] - eye_targets[eye][index - 1]
            matched_delta = eye_predictions[eye][index] - eye_predictions[eye][index - 1]
            temporal_matched.append(float(np.mean(np.abs(matched_delta - target_delta))))
            # Reconstruct direct predictions only for the delta diagnostic. This
            # is intentionally not retained as a second full sequence cache.
            frame_id = frames[index]
            previous_id = frames[index - 1]
            direct_now = as_hwc(
                F.interpolate(
                    read_rgb8(
                        replay_root / f"frame_{frame_id:08d}" / f"teacher_eye{eye}.rgba",
                        small_width,
                        small_height,
                    ).to(device),
                    size=(full_height, full_width),
                    mode="bilinear",
                    align_corners=False,
                )
            )
            direct_previous = as_hwc(
                F.interpolate(
                    read_rgb8(
                        replay_root / f"frame_{previous_id:08d}" / f"teacher_eye{eye}.rgba",
                        small_width,
                        small_height,
                    ).to(device),
                    size=(full_height, full_width),
                    mode="bilinear",
                    align_corners=False,
                )
            )
            temporal_direct.append(float(np.mean(np.abs((direct_now - direct_previous) - target_delta))))
        eye_records.append(
            {
                "eye": eye,
                "frames": records,
                "temporal": {
                    "direct_delta_mae_mean": float(np.mean(temporal_direct)) if temporal_direct else None,
                    "matched_delta_mae_mean": float(np.mean(temporal_matched)) if temporal_matched else None,
                    "direct_delta_mae_values": temporal_direct,
                    "matched_delta_mae_values": temporal_matched,
                },
            }
        )

    result["eyes"] = eye_records
    all_direct = [
        record["direct_upsample"]
        for eye in eye_records
        for record in eye["frames"]
    ]
    all_matched = [
        record["matched_residual"]
        for eye in eye_records
        for record in eye["frames"]
    ]
    result["aggregate"] = {
        "sample_count": len(all_matched),
        "direct_mae_mean": float(np.mean([item["mae"] for item in all_direct])),
        "matched_mae_mean": float(np.mean([item["mae"] for item in all_matched])),
        "direct_identity_improvement_mean": float(
            np.mean([item["improvement_vs_identity_mae"] for item in all_direct])
        ),
        "matched_identity_improvement_mean": float(
            np.mean([item["improvement_vs_identity_mae"] for item in all_matched])
        ),
        "direct_better_than_identity_samples": int(
            sum(item["improvement_vs_identity_mae"] > 0 for item in all_direct)
        ),
        "matched_better_than_identity_samples": int(
            sum(item["improvement_vs_identity_mae"] > 0 for item in all_matched)
        ),
        "matched_better_than_direct_samples": int(
            sum(
                matched["mae"] < direct["mae"]
                for matched, direct in zip(all_matched, all_direct)
            )
        ),
        "matched_minus_direct_mae": float(
            np.mean([item["mae"] for item in all_matched])
            - np.mean([item["mae"] for item in all_direct])
        ),
    }
    (args.output / "result.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result["aggregate"], indent=2))
    print(f"result={args.output / 'result.json'}")
    return 0


FULL_WIDTH = 2496
FULL_HEIGHT = 2688


if __name__ == "__main__":
    raise SystemExit(main())
