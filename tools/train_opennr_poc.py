#!/usr/bin/env python3
"""Run a small, sequence-held-out OpenNR-VR distillation proof of concept.

This is intentionally a compact exploratory experiment.  It learns a spatial
mapping from the captured pre-NR RGB crop to the captured Feature 18 teacher
RGB crop.  The guided model additionally receives the captured depth and a
bounded, model-ready representation of the captured motion-vector tensors. The
raw native guide files remain untouched. With ``--input-scale`` below 1.0 it
also exercises a simple scale-aware baseline: convolutions run at the smaller
input size and a single bilinear reconstruction brings the residual back to the
target size. It is not a temporal recurrent model and it does not claim live VR
suitability.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import time
from collections import Counter, defaultdict
from contextlib import nullcontext
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

import numpy as np
from PIL import Image, ImageDraw

import torch
from torch import nn
from torch.utils.data import DataLoader, Dataset
import torch.nn.functional as F


SESSION_GAP_MS = 10 * 60 * 1000
EXPECTED_CROP_SIZE = 512
REQUIRED_STAGES = ("input", "teacher", "depth", "motion_vectors")
MIN_INPUT_RESOLUTION = 8
# Native Feature 18 motion vectors are retained verbatim on disk.  The values
# below only define the separate representation presented to the exploratory
# student.  128 pixels covers the observed valid motion distribution while
# preventing a malformed half-float (for example 65504) from dominating the
# RGB/depth channels after MVecScaleX/Y is applied.
MOTION_VECTOR_RAW_OUTLIER_LIMIT = 0.25
MOTION_VECTOR_CLIP_PIXELS = 128.0
MOTION_VECTOR_PREPROCESS_VERSION = "bounded_scaled_pixels_v1"


@dataclass(frozen=True)
class SampleRef:
    sequence_id: str
    sequence_root: str
    session_id: int
    frame_id: int
    sample_index: int
    host_frame: int
    eye: int
    crop_index: int
    input_path: str
    teacher_path: str
    depth_path: str
    motion_vectors_path: str
    motion_vector_scale_x: float
    motion_vector_scale_y: float
    history_reset: bool
    route: str
    model_resolution_percent: int
    pass_count: int
    motion_vector_contract: str


def read_json(path: Path) -> dict[str, Any]:
    loaded = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ValueError(f"Expected an object in {path}")
    return loaded


def safe_path(sequence_root: Path, relative: Any) -> Path | None:
    if not isinstance(relative, str) or not relative.strip():
        return None
    candidate = (sequence_root / relative).resolve()
    try:
        candidate.relative_to(sequence_root.resolve())
    except ValueError:
        return None
    return candidate


def as_float_pair(value: Any) -> tuple[float, float]:
    if isinstance(value, (list, tuple)) and len(value) >= 2:
        try:
            return float(value[0]), float(value[1])
        except (TypeError, ValueError):
            pass
    return 1.0, 1.0


def build_index(root: Path) -> tuple[list[SampleRef], list[dict[str, Any]], list[str]]:
    sequence_paths = list(root.glob("*/sequence.json"))
    if not sequence_paths:
        raise FileNotFoundError(f"No sequence.json files found under {root}")

    sequence_entries: list[dict[str, Any]] = []
    warnings: list[str] = []
    for sequence_path in sequence_paths:
        meta = read_json(sequence_path)
        try:
            created = int(meta["created_utc"])
            sequence_id = str(meta["sequence_id"])
        except (KeyError, TypeError, ValueError) as exc:
            warnings.append(f"Skipped malformed sequence metadata: {sequence_path}: {exc}")
            continue
        sequence_entries.append(
            {
                "path": sequence_path,
                "root": sequence_path.parent,
                "meta": meta,
                "created_utc": created,
                "sequence_id": sequence_id,
            }
        )

    sequence_entries.sort(key=lambda item: (item["created_utc"], item["sequence_id"]))
    previous_created: int | None = None
    session_id = -1
    for entry in sequence_entries:
        if previous_created is None or entry["created_utc"] - previous_created > SESSION_GAP_MS:
            session_id += 1
        entry["session_id"] = session_id
        previous_created = entry["created_utc"]

    refs: list[SampleRef] = []
    sequence_rows: list[dict[str, Any]] = []
    for entry in sequence_entries:
        sequence_root: Path = entry["root"]
        meta: dict[str, Any] = entry["meta"]
        frames_path = sequence_root / "frames.jsonl"
        row: dict[str, Any] = {
            "sequence_id": entry["sequence_id"],
            "created_utc": entry["created_utc"],
            "session_id": entry["session_id"],
            "frame_records": 0,
            "usable_frame_records": 0,
            "pair_records": 0,
            "status_counts": Counter(),
        }
        if not frames_path.is_file():
            warnings.append(f"Missing {frames_path}")
            sequence_rows.append(row)
            continue

        for line_number, line in enumerate(
            frames_path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            if not line.strip():
                continue
            try:
                frame = json.loads(line)
            except json.JSONDecodeError as exc:
                warnings.append(f"{frames_path}:{line_number}: invalid JSON: {exc.msg}")
                continue
            row["frame_records"] += 1
            status = str(frame.get("status", "unknown"))
            row["status_counts"][status] += 1
            if status != "complete":
                continue
            if (
                frame.get("route") != "feature18_stereo"
                or int(frame.get("model_resolution_percent", 0)) != 100
                or int(frame.get("pass_count", 0)) != 1
            ):
                warnings.append(
                    f"{entry['sequence_id']} frame {frame.get('frame_id')}: "
                    "not the expected Full 100% single-pass Feature 18 route"
                )
                continue

            artifacts: dict[tuple[str, int, int], dict[str, Any]] = {}
            for artifact in frame.get("artifacts", []):
                if not isinstance(artifact, dict) or artifact.get("full_frame", False):
                    continue
                try:
                    key = (
                        str(artifact["stage"]),
                        int(artifact["eye"]),
                        int(artifact["crop_index"]),
                    )
                except (KeyError, TypeError, ValueError):
                    continue
                artifacts[key] = artifact

            scale_x, scale_y = as_float_pair(frame.get("motion_vector_scale_x"))
            history_reset = frame.get("history_reset", [False, False])
            contract = str(frame.get("motion_vector_contract", ""))
            made_pairs = 0
            for eye in (0, 1):
                for crop_index in range(4):
                    selected = {
                        stage: artifacts.get((stage, eye, crop_index))
                        for stage in REQUIRED_STAGES
                    }
                    if any(value is None for value in selected.values()):
                        continue
                    paths: dict[str, Path] = {}
                    valid = True
                    for stage, artifact in selected.items():
                        assert artifact is not None
                        relative = (
                            artifact.get("png_path")
                            if stage in ("input", "teacher")
                            else artifact.get("raw_path")
                        )
                        resolved = safe_path(sequence_root, relative)
                        if resolved is None or not resolved.is_file():
                            warnings.append(
                                f"{frames_path}:{line_number}: missing or unsafe {stage} path"
                            )
                            valid = False
                            break
                        if (
                            int(artifact.get("width", 0)) != EXPECTED_CROP_SIZE
                            or int(artifact.get("height", 0)) != EXPECTED_CROP_SIZE
                        ):
                            valid = False
                            break
                        paths[stage] = resolved
                    if not valid:
                        continue

                    reset_value = False
                    if isinstance(history_reset, list) and len(history_reset) > eye:
                        reset_value = bool(history_reset[eye])
                    refs.append(
                        SampleRef(
                            sequence_id=entry["sequence_id"],
                            sequence_root=str(sequence_root),
                            session_id=int(entry["session_id"]),
                            frame_id=int(frame["frame_id"]),
                            sample_index=int(frame["sample_index"]),
                            host_frame=int(frame.get("host_frame", -1)),
                            eye=eye,
                            crop_index=crop_index,
                            input_path=str(paths["input"]),
                            teacher_path=str(paths["teacher"]),
                            depth_path=str(paths["depth"]),
                            motion_vectors_path=str(paths["motion_vectors"]),
                            motion_vector_scale_x=scale_x,
                            motion_vector_scale_y=scale_y,
                            history_reset=reset_value,
                            route=str(frame.get("route", "")),
                            model_resolution_percent=int(
                                frame.get("model_resolution_percent", 0)
                            ),
                            pass_count=int(frame.get("pass_count", 0)),
                            motion_vector_contract=contract,
                        )
                    )
                    made_pairs += 1
            if made_pairs:
                row["usable_frame_records"] += 1
                row["pair_records"] += made_pairs
        row["status_counts"] = dict(row["status_counts"])
        sequence_rows.append(row)

    if not refs:
        raise RuntimeError("The capture root contains no usable paired crops")
    return refs, sequence_rows, warnings


def split_sequences(sequence_rows: list[dict[str, Any]]) -> dict[str, list[str]]:
    ordered = sorted(sequence_rows, key=lambda row: (row["created_utc"], row["sequence_id"]))
    sessions = sorted({int(row["session_id"]) for row in ordered})
    if len(sessions) >= 2:
        test_session = sessions[-1]
        train_val = [row for row in ordered if int(row["session_id"]) != test_session]
        test = [row for row in ordered if int(row["session_id"]) == test_session]
        val_count = max(1, math.ceil(len(train_val) * 0.2))
        train = train_val[:-val_count]
        val = train_val[-val_count:]
    else:
        test_count = max(1, math.ceil(len(ordered) * 0.2))
        val_count = max(1, math.ceil((len(ordered) - test_count) * 0.2))
        train = ordered[: -(test_count + val_count)]
        val = ordered[-(test_count + val_count) : -test_count]
        test = ordered[-test_count:]
    if not train or not val or not test:
        raise RuntimeError("Sequence split did not produce train, validation, and test groups")
    return {
        "train": [row["sequence_id"] for row in train],
        "validation": [row["sequence_id"] for row in val],
        "test": [row["sequence_id"] for row in test],
        "policy": (
            "hold out the latest capture session for test; "
            "last 20% of the earlier session for validation"
            if len(sessions) >= 2
            else "deterministic sequence-level 60/20/20 split"
        ),
    }


def assign_refs(
    refs: Iterable[SampleRef], split: dict[str, list[str]]
) -> dict[str, list[SampleRef]]:
    membership = {
        sequence_id: name
        for name, sequence_ids in split.items()
        if name in ("train", "validation", "test")
        for sequence_id in sequence_ids
    }
    result: dict[str, list[SampleRef]] = {"train": [], "validation": [], "test": []}
    for ref in refs:
        name = membership.get(ref.sequence_id)
        if name is not None:
            result[name].append(ref)
    if any(not result[name] for name in result):
        raise RuntimeError("At least one data split has no paired crops")
    return result


def load_rgb(path: str) -> torch.Tensor:
    with Image.open(path) as image:
        array = np.asarray(image.convert("RGB"), dtype=np.float32).copy() / 255.0
    return torch.from_numpy(array).permute(2, 0, 1).contiguous()


def load_raw(path: str, stage: str) -> torch.Tensor:
    if stage == "depth":
        array = np.fromfile(path, dtype="<f4")
        expected = EXPECTED_CROP_SIZE * EXPECTED_CROP_SIZE
        if array.size != expected:
            raise ValueError(f"{path}: expected {expected} float32 values, got {array.size}")
        array = array.reshape(1, EXPECTED_CROP_SIZE, EXPECTED_CROP_SIZE)
    elif stage == "motion_vectors":
        array = np.fromfile(path, dtype="<f2")
        expected = EXPECTED_CROP_SIZE * EXPECTED_CROP_SIZE * 2
        if array.size != expected:
            raise ValueError(f"{path}: expected {expected} float16 values, got {array.size}")
        array = array.reshape(EXPECTED_CROP_SIZE, EXPECTED_CROP_SIZE, 2)
        array = np.transpose(array, (2, 0, 1))
    else:
        raise ValueError(f"Unsupported raw stage: {stage}")
    return torch.from_numpy(array.astype(np.float32, copy=True))


def prepare_motion_vectors(motion: torch.Tensor, ref: SampleRef) -> torch.Tensor:
    """Build a bounded model input without rewriting the native raw guide.

    The capture keeps the exact R16G16 resource and records MVecScaleX/Y.  For
    this small spatial student, however, a direct multiplication can turn a
    malformed finite half-float into a huge feature value.  Remove non-finite
    and implausibly large raw values, convert the remaining values to the
    recorded pixel-space scale, clip to a generous 128-pixel range, and
    normalize to approximately [-1, 1].
    """
    finite = torch.isfinite(motion)
    raw_outlier = finite & (motion.abs() > MOTION_VECTOR_RAW_OUTLIER_LIMIT)
    motion = torch.where(finite & ~raw_outlier, motion, torch.zeros_like(motion))
    scaled = torch.stack(
        (
            motion[0] * float(ref.motion_vector_scale_x),
            motion[1] * float(ref.motion_vector_scale_y),
        ),
        dim=0,
    )
    scaled = torch.nan_to_num(scaled, nan=0.0, posinf=0.0, neginf=0.0)
    return scaled.clamp(-MOTION_VECTOR_CLIP_PIXELS, MOTION_VECTOR_CLIP_PIXELS) / MOTION_VECTOR_CLIP_PIXELS


def resize_tensor(tensor: torch.Tensor, resolution: int) -> torch.Tensor:
    if tensor.shape[-2:] == (resolution, resolution):
        return tensor
    return F.interpolate(
        tensor.unsqueeze(0),
        size=(resolution, resolution),
        mode="bilinear",
        align_corners=False,
    ).squeeze(0)


class PairDataset(Dataset[dict[str, Any]]):
    def __init__(
        self,
        refs: list[SampleRef],
        resolution: int,
        include_guides: bool,
        input_resolution: int | None = None,
    ) -> None:
        self.refs = refs
        self.output_resolution = int(resolution)
        self.input_resolution = int(input_resolution or resolution)
        self.include_guides = include_guides

    def __len__(self) -> int:
        return len(self.refs)

    def __getitem__(self, index: int) -> dict[str, Any]:
        ref = self.refs[index]
        input_rgb = load_rgb(ref.input_path)
        target = load_rgb(ref.teacher_path)
        input_rgb = resize_tensor(input_rgb, self.input_resolution)
        target = resize_tensor(target, self.output_resolution)
        if self.include_guides:
            depth = load_raw(ref.depth_path, "depth")
            motion = load_raw(ref.motion_vectors_path, "motion_vectors")
            depth = torch.nan_to_num(depth, nan=0.0, posinf=0.0, neginf=0.0).clamp(0.0, 1.0)
            motion = prepare_motion_vectors(motion, ref)
            depth = resize_tensor(depth, self.input_resolution)
            motion = resize_tensor(motion, self.input_resolution)
            features = torch.cat((input_rgb, depth, motion), dim=0)
        else:
            features = input_rgb
        return {"features": features, "target": target, "index": index}


class ResidualBlock(nn.Module):
    def __init__(self, width: int) -> None:
        super().__init__()
        self.conv1 = nn.Conv2d(width, width, 3, padding=1)
        self.conv2 = nn.Conv2d(width, width, 3, padding=1)
        self.activation = nn.SiLU()

    def forward(self, value: torch.Tensor) -> torch.Tensor:
        update = self.conv2(self.activation(self.conv1(value)))
        return value + 0.2 * update


class TinyStudent(nn.Module):
    def __init__(
        self,
        input_channels: int,
        width: int = 48,
        blocks: int = 4,
        output_resolution: int | None = None,
    ) -> None:
        super().__init__()
        self.output_resolution = output_resolution
        self.input = nn.Conv2d(input_channels, width, 3, padding=1)
        self.body = nn.Sequential(*(ResidualBlock(width) for _ in range(blocks)))
        self.output = nn.Conv2d(width, 3, 3, padding=1)
        nn.init.zeros_(self.output.weight)
        nn.init.zeros_(self.output.bias)

    def forward(self, features: torch.Tensor) -> torch.Tensor:
        rgb = features[:, :3]
        value = self.body(torch.relu(self.input(features)))
        residual = self.output(value)
        if self.output_resolution is not None:
            target_size = (self.output_resolution, self.output_resolution)
            if residual.shape[-2:] != target_size:
                rgb = F.interpolate(rgb, size=target_size, mode="bilinear", align_corners=False)
                residual = F.interpolate(residual, size=target_size, mode="bilinear", align_corners=False)
        return (rgb + residual).clamp(0.0, 1.0)


def seed_everything(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)


def autocast_context(device: torch.device):
    if device.type == "cuda":
        return torch.autocast(device_type="cuda", dtype=torch.bfloat16)
    return nullcontext()


@torch.no_grad()
def evaluate(
    model: nn.Module,
    loader: DataLoader[dict[str, Any]],
    device: torch.device,
) -> dict[str, float]:
    model.eval()
    identity_abs = 0.0
    student_abs = 0.0
    identity_sq = 0.0
    student_sq = 0.0
    prediction_delta = 0.0
    pixels = 0
    identity_per_sample: list[float] = []
    student_per_sample: list[float] = []
    for batch in loader:
        features = batch["features"].to(device, non_blocking=True)
        target = batch["target"].to(device, non_blocking=True)
        with autocast_context(device):
            prediction = model(features)
        prediction = prediction.float()
        target = target.float()
        identity = features[:, :3].float()
        if identity.shape[-2:] != target.shape[-2:]:
            identity = F.interpolate(identity, size=target.shape[-2:], mode="bilinear", align_corners=False)
        identity_error = (identity - target).abs()
        student_error = (prediction - target).abs()
        identity_abs += float(identity_error.sum())
        student_abs += float(student_error.sum())
        identity_sq += float(identity_error.square().sum())
        student_sq += float((prediction - target).square().sum())
        prediction_delta += float((prediction - identity).abs().sum())
        pixels += int(target.numel())
        identity_per_sample.extend(identity_error.mean(dim=(1, 2, 3)).cpu().tolist())
        student_per_sample.extend(student_error.mean(dim=(1, 2, 3)).cpu().tolist())
    identity_mae = identity_abs / pixels
    student_mae = student_abs / pixels
    identity_mse = identity_sq / pixels
    student_mse = student_sq / pixels
    return {
        "pairs": float(len(identity_per_sample)),
        "pixels": float(pixels),
        "identity_mae": identity_mae,
        "identity_psnr": 10.0 * math.log10(1.0 / max(identity_mse, 1e-12)),
        "student_mae": student_mae,
        "student_psnr": 10.0 * math.log10(1.0 / max(student_mse, 1e-12)),
        "mae_improvement": identity_mae - student_mae,
        "mae_improvement_pct": 100.0 * (identity_mae - student_mae) / max(identity_mae, 1e-12),
        "prediction_vs_input_mae": prediction_delta / pixels,
        "identity_mae_p95": float(np.percentile(identity_per_sample, 95)),
        "student_mae_p95": float(np.percentile(student_per_sample, 95)),
    }


def make_loader(
    refs: list[SampleRef],
    output_resolution: int,
    input_resolution: int,
    include_guides: bool,
    batch_size: int,
    shuffle: bool,
    seed: int,
    device: torch.device,
) -> DataLoader[dict[str, Any]]:
    generator = torch.Generator()
    generator.manual_seed(seed)
    return DataLoader(
        PairDataset(refs, output_resolution, include_guides, input_resolution),
        batch_size=batch_size,
        shuffle=shuffle,
        num_workers=0,
        pin_memory=device.type == "cuda",
        generator=generator,
        drop_last=False,
    )


def train_model(
    name: str,
    refs: dict[str, list[SampleRef]],
    output_dir: Path,
    output_resolution: int,
    input_resolution: int,
    batch_size: int,
    max_steps: int,
    eval_interval: int,
    learning_rate: float,
    seed: int,
    device: torch.device,
) -> tuple[nn.Module, list[dict[str, Any]]]:
    include_guides = name == "guided"
    seed_everything(seed)
    channels = 6 if include_guides else 3
    model = TinyStudent(channels, output_resolution=output_resolution).to(device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=learning_rate, weight_decay=1e-4)
    train_loader = make_loader(
        refs["train"],
        output_resolution,
        input_resolution,
        include_guides,
        batch_size,
        True,
        seed,
        device,
    )
    validation_loader = make_loader(
        refs["validation"],
        output_resolution,
        input_resolution,
        include_guides,
        batch_size,
        False,
        seed,
        device,
    )
    iterator = iter(train_loader)
    history: list[dict[str, Any]] = []
    best_mae = float("inf")
    best_path = output_dir / f"model_{name}_best.pt"
    start = time.perf_counter()
    for step in range(1, max_steps + 1):
        try:
            batch = next(iterator)
        except StopIteration:
            iterator = iter(train_loader)
            batch = next(iterator)
        model.train()
        features = batch["features"].to(device, non_blocking=True)
        target = batch["target"].to(device, non_blocking=True)
        optimizer.zero_grad(set_to_none=True)
        with autocast_context(device):
            prediction = model(features)
            loss_l1 = (prediction - target).abs().mean()
            loss_mse = (prediction - target).square().mean()
            loss = 0.8 * loss_l1 + 0.2 * loss_mse
        loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
        optimizer.step()

        if step == 1 or step % eval_interval == 0 or step == max_steps:
            validation = evaluate(model, validation_loader, device)
            record = {
                "step": step,
                "train_loss": float(loss.detach().float().cpu()),
                "validation": validation,
                "elapsed_seconds": time.perf_counter() - start,
            }
            history.append(record)
            if validation["student_mae"] < best_mae:
                best_mae = validation["student_mae"]
                torch.save(model.state_dict(), best_path)
            print(
                f"[{name}] step {step}/{max_steps} "
                f"loss={record['train_loss']:.6f} "
                f"val_mae={validation['student_mae']:.6f} "
                f"val_identity={validation['identity_mae']:.6f}"
            )

    last_path = output_dir / f"model_{name}_last.pt"
    torch.save(model.state_dict(), last_path)
    model.load_state_dict(torch.load(best_path, map_location=device))
    model.eval()
    return model, history


def tensor_image(tensor: torch.Tensor, resolution: int) -> Image.Image:
    value = tensor.detach().float().cpu().clamp(0.0, 1.0)
    value = value.permute(1, 2, 0).numpy()
    image = Image.fromarray(np.uint8(np.round(value * 255.0)), mode="RGB")
    if image.size != (resolution, resolution):
        image = image.resize((resolution, resolution), Image.Resampling.BILINEAR)
    return image


def scalar_image(tensor: torch.Tensor, resolution: int) -> Image.Image:
    value = tensor.detach().float().cpu()
    value = torch.nan_to_num(value, nan=0.0, posinf=0.0, neginf=0.0)
    value = value - value.min()
    value = value / max(float(value.max()), 1e-8)
    array = np.uint8(np.round(value.numpy() * 255.0))
    image = Image.fromarray(array, mode="L").convert("RGB")
    if image.size != (resolution, resolution):
        image = image.resize((resolution, resolution), Image.Resampling.BILINEAR)
    return image


def placeholder_image(text: str, resolution: int) -> Image.Image:
    image = Image.new("RGB", (resolution, resolution), "#d9d9d9")
    draw = ImageDraw.Draw(image)
    draw.multiline_text((resolution // 2, resolution // 2), text, fill="black", anchor="mm", align="center")
    return image


@torch.no_grad()
def save_previews(
    refs: list[SampleRef],
    models: dict[str, nn.Module],
    output_dir: Path,
    output_resolution: int,
    input_resolution: int,
    device: torch.device,
) -> None:
    if not refs:
        return
    chosen = [refs[index] for index in np.linspace(0, len(refs) - 1, min(12, len(refs)), dtype=int)]
    guided_dataset = PairDataset(chosen, output_resolution, True, input_resolution)
    rgb_dataset = PairDataset(chosen, output_resolution, False, input_resolution)
    scale = 2
    tile = output_resolution * scale
    has_rgb_model = "rgb" in models
    labels = ["input", "rgb_only" if has_rgb_model else "rgb_only NOT RUN", "guided", "teacher"]
    canvas = Image.new("RGB", (len(labels) * tile, len(chosen) * (tile + 24)), "white")
    draw = ImageDraw.Draw(canvas)
    for row, ref in enumerate(chosen):
        guided_sample = guided_dataset[row]
        rgb_sample = rgb_dataset[row]
        guided_input = guided_sample["features"].unsqueeze(0).to(device)
        rgb_input = rgb_sample["features"].unsqueeze(0).to(device)
        with autocast_context(device):
            guided_output = models["guided"](guided_input).squeeze(0).float().cpu()
            rgb_output = models["rgb"](rgb_input).squeeze(0).float().cpu() if has_rgb_model else None
        images = [
            tensor_image(guided_sample["features"][:3], tile),
            tensor_image(rgb_output, tile) if rgb_output is not None else placeholder_image("RGB\nmodel not run", tile),
            tensor_image(guided_output, tile),
            tensor_image(guided_sample["target"], tile),
        ]
        for column, image in enumerate(images):
            left = column * tile
            top = row * (tile + 24) + 24
            canvas.paste(image.resize((tile, tile), Image.Resampling.BILINEAR), (left, top))
            if row == 0:
                draw.text((left + 4, 4), labels[column], fill="black")
    canvas.save(output_dir / "qualitative_preview.png")

    guide_canvas = Image.new("RGB", (4 * tile, min(8, len(chosen)) * (tile + 24)), "white")
    guide_draw = ImageDraw.Draw(guide_canvas)
    guide_labels = ["input", "depth", "motion_magnitude", "teacher"]
    for row in range(min(8, len(chosen))):
        sample = guided_dataset[row]
        features = sample["features"]
        depth = features[3]
        motion = torch.sqrt(features[4].square() + features[5].square())
        images = [
            tensor_image(features[:3], tile),
            scalar_image(depth, tile),
            scalar_image(motion, tile),
            tensor_image(sample["target"], tile),
        ]
        for column, image in enumerate(images):
            left = column * tile
            top = row * (tile + 24) + 24
            guide_canvas.paste(image.resize((tile, tile), Image.Resampling.BILINEAR), (left, top))
            if row == 0:
                guide_draw.text((left + 4, 4), guide_labels[column], fill="black")
    guide_canvas.save(output_dir / "guide_preview.png")


def guide_audit(refs: list[SampleRef]) -> dict[str, Any]:
    selected = [refs[index] for index in np.linspace(0, len(refs) - 1, min(6, len(refs)), dtype=int)]
    rows: list[dict[str, Any]] = []
    for ref in selected:
        depth = np.fromfile(ref.depth_path, dtype="<f4")
        motion = np.fromfile(ref.motion_vectors_path, dtype="<f2")
        motion_finite = np.isfinite(motion)
        motion_outlier = motion_finite & (np.abs(motion) > MOTION_VECTOR_RAW_OUTLIER_LIMIT)
        model_ready_motion = prepare_motion_vectors(
            torch.from_numpy(motion.astype(np.float32, copy=True).reshape(2, EXPECTED_CROP_SIZE, EXPECTED_CROP_SIZE)),
            ref,
        ).numpy()
        rows.append(
            {
                "sequence_id": ref.sequence_id,
                "frame_id": ref.frame_id,
                "eye": ref.eye,
                "crop_index": ref.crop_index,
                "history_reset": ref.history_reset,
                "motion_vector_scale": [
                    ref.motion_vector_scale_x,
                    ref.motion_vector_scale_y,
                ],
                "depth": {
                    "min": float(np.nanmin(depth)),
                    "max": float(np.nanmax(depth)),
                    "mean": float(np.nanmean(depth)),
                    "finite_fraction": float(np.isfinite(depth).mean()),
                    "zero_fraction": float((depth == 0).mean()),
                },
                "motion_vectors": {
                    "min": float(np.nanmin(motion)),
                    "max": float(np.nanmax(motion)),
                    "mean": float(np.nanmean(motion)),
                    "finite_fraction": float(motion_finite.mean()),
                    "zero_fraction": float((motion == 0).mean()),
                    "raw_outlier_fraction": float(motion_outlier.mean()),
                },
                "model_ready_motion_vectors": {
                    "min": float(model_ready_motion.min()),
                    "max": float(model_ready_motion.max()),
                    "mean": float(model_ready_motion.mean()),
                    "zero_fraction": float((model_ready_motion == 0).mean()),
                },
            }
        )
    return {"sample_count": len(rows), "samples": rows}


def fingerprint(root: Path, sequence_rows: list[dict[str, Any]]) -> str:
    digest = hashlib.sha256()
    for row in sorted(sequence_rows, key=lambda item: item["sequence_id"]):
        sequence_root = root / row["sequence_id"]
        for name in ("sequence.json", "frames.jsonl"):
            path = sequence_root / name
            digest.update(name.encode("utf-8"))
            digest.update(path.read_bytes())
    return digest.hexdigest()


def write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--resolution",
        type=int,
        default=128,
        help="target/output crop resolution",
    )
    parser.add_argument(
        "--input-scale",
        type=float,
        default=1.0,
        help="input spatial scale relative to --resolution; 1.0 preserves the original POC",
    )
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--max-steps", type=int, default=600)
    parser.add_argument("--eval-interval", type=int, default=100)
    parser.add_argument("--learning-rate", type=float, default=1e-3)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--models", default="guided,rgb")
    parser.add_argument("--device", default="auto", choices=("auto", "cuda", "cpu"))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.resolution <= 0 or args.resolution % 8:
        raise SystemExit("--resolution must be positive and divisible by 8")
    if not 0.0 < args.input_scale <= 1.0:
        raise SystemExit("--input-scale must be greater than 0 and no greater than 1")
    input_resolution = max(
        MIN_INPUT_RESOLUTION,
        int(round(args.resolution * args.input_scale)),
    )
    if input_resolution % 8:
        raise SystemExit(
            f"--input-scale produces input resolution {input_resolution}; "
            "choose a scale that produces a resolution divisible by 8"
        )
    if args.max_steps <= 0 or args.batch_size <= 0:
        raise SystemExit("--max-steps and --batch-size must be positive")
    model_names = [name.strip() for name in args.models.split(",") if name.strip()]
    if not model_names or any(name not in {"guided", "rgb"} for name in model_names):
        raise SystemExit("--models must contain only guided and/or rgb")
    if "guided" not in model_names:
        raise SystemExit("guided is required for qualitative previews")

    capture_root = args.capture_root.expanduser().resolve()
    output_dir = args.output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    device = (
        torch.device("cuda" if torch.cuda.is_available() else "cpu")
        if args.device == "auto"
        else torch.device(args.device)
    )
    if device.type == "cuda" and not torch.cuda.is_available():
        raise SystemExit("CUDA was requested but is not available")
    if device.type == "cuda":
        torch.set_float32_matmul_precision("high")
        torch.backends.cudnn.benchmark = True

    refs, sequence_rows, warnings = build_index(capture_root)
    split = split_sequences(sequence_rows)
    split_refs = assign_refs(refs, split)
    audit = {
        "capture_root": str(capture_root),
        "source_manifest_fingerprint": fingerprint(capture_root, sequence_rows),
        "sequence_count": len(sequence_rows),
        "pair_count": len(refs),
        "sequence_rows": sequence_rows,
        "split": split,
        "split_pair_counts": {name: len(value) for name, value in split_refs.items()},
        "history_reset_counts": dict(Counter(ref.history_reset for ref in refs)),
        "motion_vector_contracts": dict(Counter(ref.motion_vector_contract for ref in refs)),
        "guide_preprocessing": {
            "version": MOTION_VECTOR_PREPROCESS_VERSION,
            "raw_outlier_limit": MOTION_VECTOR_RAW_OUTLIER_LIMIT,
            "clip_pixels": MOTION_VECTOR_CLIP_PIXELS,
            "raw_capture_preserved": True,
        },
        "route_counts": dict(Counter(ref.route for ref in refs)),
        "guide_audit": guide_audit(refs),
        "warnings": warnings,
    }
    write_json(output_dir / "dataset_audit.json", audit)
    write_json(
        output_dir / "split_manifest.json",
        {
            **split,
            "sequence_rows": sequence_rows,
            "pair_counts": {name: len(value) for name, value in split_refs.items()},
        },
    )
    write_json(
        output_dir / "run_config.json",
        {
            "capture_root": str(capture_root),
            "output_dir": str(output_dir),
            "resolution": args.resolution,
            "output_resolution": args.resolution,
            "input_scale": args.input_scale,
            "input_resolution": input_resolution,
            "batch_size": args.batch_size,
            "max_steps": args.max_steps,
            "eval_interval": args.eval_interval,
            "learning_rate": args.learning_rate,
            "seed": args.seed,
            "models": model_names,
            "guide_preprocessing": {
                "version": MOTION_VECTOR_PREPROCESS_VERSION,
                "raw_outlier_limit": MOTION_VECTOR_RAW_OUTLIER_LIMIT,
                "clip_pixels": MOTION_VECTOR_CLIP_PIXELS,
                "raw_capture_preserved": True,
            },
            "device": str(device),
            "torch": torch.__version__,
            "cuda": torch.version.cuda,
            "gpu": torch.cuda.get_device_name(0) if device.type == "cuda" else None,
        },
    )
    print(
        json.dumps(
            {
                "sequences": len(sequence_rows),
                "pairs": len(refs),
                "split_pair_counts": audit["split_pair_counts"],
                "device": str(device),
                "output_dir": str(output_dir),
            },
            indent=2,
        )
    )

    baseline_loader = make_loader(
        split_refs["test"],
        args.resolution,
        input_resolution,
        False,
        args.batch_size,
        False,
        args.seed,
        device,
    )
    baseline_model = TinyStudent(3, output_resolution=args.resolution).to(device)
    baseline_metrics = evaluate(baseline_model, baseline_loader, device)
    results: dict[str, Any] = {"identity_vs_teacher_test": baseline_metrics, "models": {}}
    trained: dict[str, nn.Module] = {}
    histories: dict[str, Any] = {}
    for name in model_names:
        model, history = train_model(
            name=name,
            refs=split_refs,
            output_dir=output_dir,
            output_resolution=args.resolution,
            input_resolution=input_resolution,
            batch_size=args.batch_size,
            max_steps=args.max_steps,
            eval_interval=args.eval_interval,
            learning_rate=args.learning_rate,
            seed=args.seed,
            device=device,
        )
        trained[name] = model
        histories[name] = history
        test_loader = make_loader(
            split_refs["test"],
            args.resolution,
            input_resolution,
            name == "guided",
            args.batch_size,
            False,
            args.seed,
            device,
        )
        results["models"][name] = evaluate(model, test_loader, device)
    write_json(output_dir / "metrics.json", results)
    write_json(output_dir / "training_history.json", histories)
    save_previews(
        split_refs["test"],
        trained,
        output_dir,
        args.resolution,
        input_resolution,
        device,
    )

    results["status"] = "complete"
    results["limitations"] = [
        "Sequence-level holdout prevents frame/crop leakage, but both capture sessions may still share game content.",
        "The student is spatial and per-frame; it does not model recurrent history, reset transitions, or temporal clips.",
        "Teacher agreement is an offline distillation signal, not proof of perceptual quality, Feature 18 equivalence, headset delivery, or VR frame time.",
        "The captured motion-vector tensors remain native on disk; the exploratory student uses bounded_scaled_pixels_v1 after applying the recorded MVecScaleX/Y values.",
    ]
    write_json(output_dir / "metrics.json", results)
    print(json.dumps(results, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
