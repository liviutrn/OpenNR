"""Evaluate released photorealism models on unseen Skyrim RGB frames.

The models in this experiment receive only the frozen input RGB.  The paired
DLSS5-NR teacher is used after inference for similarity metrics and gallery
context; it is never passed into a model and is not used to choose a released
checkpoint.  This keeps the OOD test honest: HyPER-GAN and REGEN were trained
for synthetic driving imagery, not Skyrim.

The quality scope is a deterministic held-out frame from every test sequence
and both eyes.  Temporal/stereo sanity uses three consecutive frames from
every test sequence.  The benchmark reports FP16 GPU-only and CPU-to-GPU plus
GPU inference timing at 512x512, stereo batch-2 at 512x512, and an attempted
representative per-eye resolution.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import math
import re
import sys
from pathlib import Path
from typing import Any

import torch
import torch.nn as nn
from PIL import Image, ImageDraw

from .dataset import TinyPairedCache


def _load_module(module_name: str, path: Path):
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"could not load module from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


class HyperResBlock(nn.Module):
    """Exact HyPER-GAN ResBlock from the released reference implementation."""

    def __init__(self, channels: int):
        super().__init__()
        self.block = nn.Sequential(
            nn.Conv2d(channels, channels, 3, 1, 1),
            nn.InstanceNorm2d(channels),
            nn.ReLU(True),
            nn.Conv2d(channels, channels, 3, 1, 1),
            nn.InstanceNorm2d(channels),
        )

    def forward(self, image: torch.Tensor) -> torch.Tensor:
        return image + self.block(image)


class HyperUNetGenerator(nn.Module):
    """Exact released HyPER-GAN U-Net generator."""

    def __init__(self, in_channels: int = 3, base_channels: int = 64):
        super().__init__()
        self.enc1 = nn.Sequential(
            nn.Conv2d(in_channels, base_channels, 4, 2, 1),
            nn.ReLU(True),
        )
        self.enc2 = nn.Sequential(
            nn.Conv2d(base_channels, base_channels * 2, 4, 2, 1),
            nn.InstanceNorm2d(base_channels * 2),
            nn.ReLU(True),
        )
        self.enc3 = nn.Sequential(
            nn.Conv2d(base_channels * 2, base_channels * 4, 4, 2, 1),
            nn.InstanceNorm2d(base_channels * 4),
            nn.ReLU(True),
        )
        self.middle = nn.Sequential(*[HyperResBlock(base_channels * 4) for _ in range(4)])
        self.dec3 = nn.Sequential(
            nn.ConvTranspose2d(base_channels * 4, base_channels * 2, 4, 2, 1),
            nn.InstanceNorm2d(base_channels * 2),
            nn.ReLU(True),
        )
        self.dec2 = nn.Sequential(
            nn.ConvTranspose2d(base_channels * 4, base_channels, 4, 2, 1),
            nn.InstanceNorm2d(base_channels),
            nn.ReLU(True),
        )
        self.dec1 = nn.Sequential(
            nn.ConvTranspose2d(base_channels * 2, in_channels, 4, 2, 1),
            nn.Tanh(),
        )

    def forward(self, image: torch.Tensor) -> torch.Tensor:
        e1 = self.enc1(image)
        e2 = self.enc2(e1)
        e3 = self.enc3(e2)
        middle = self.middle(e3)
        d3 = self.dec3(middle)
        d2 = self.dec2(torch.cat([d3, e2], 1))
        return self.dec1(torch.cat([d2, e1], 1))


class HyperModel(nn.Module):
    def __init__(self, checkpoint: Path):
        super().__init__()
        self.generator = HyperUNetGenerator()
        state = torch.load(checkpoint, map_location="cpu", weights_only=False)
        self.generator.load_state_dict(state, strict=True)

    def forward(self, image: torch.Tensor) -> torch.Tensor:
        normalized = image.mul(2.0).sub(1.0)
        return self.generator(normalized).mul(0.5).add(0.5).clamp(0.0, 1.0)


class RegenModel(nn.Module):
    def __init__(self, source_dir: Path, checkpoint: Path):
        super().__init__()
        networks = _load_module("official_regen_networks", source_dir / "models" / "networks.py")
        norm_layer = networks.get_norm_layer(norm_type="instance")
        self.generator = networks.GlobalGenerator(
            input_nc=3,
            output_nc=3,
            ngf=64,
            n_downsampling=4,
            n_blocks=9,
            norm_layer=norm_layer,
        )
        state = torch.load(checkpoint, map_location="cpu", weights_only=False)
        if not isinstance(state, dict):
            raise TypeError(f"unexpected REGEN checkpoint type: {type(state)}")
        if state and all(str(key).startswith("module.") for key in state):
            state = {str(key)[len("module.") :]: value for key, value in state.items()}
        self.generator.load_state_dict(state, strict=True)

    def forward(self, image: torch.Tensor) -> torch.Tensor:
        normalized = image.mul(2.0).sub(1.0)
        return self.generator(normalized).mul(0.5).add(0.5).clamp(0.0, 1.0)


def _safe_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value)


def _new_accumulator() -> dict[str, float]:
    return {
        "rows": 0.0,
        "pixels": 0.0,
        "abs_sum": 0.0,
        "sq_sum": 0.0,
        "input_abs_sum": 0.0,
        "input_sq_sum": 0.0,
        "prediction_mean_sum": 0.0,
        "prediction_std_sum": 0.0,
        "clip_sum": 0.0,
    }


def _finish_accumulator(acc: dict[str, float]) -> dict[str, Any]:
    rows = max(acc["rows"], 1.0)
    pixels = max(acc["pixels"], 1.0)
    mae = acc["abs_sum"] / pixels
    mse = acc["sq_sum"] / pixels
    input_mae = acc["input_abs_sum"] / pixels
    input_mse = acc["input_sq_sum"] / pixels
    return {
        "rows": int(acc["rows"]),
        "mae": mae,
        "mse": mse,
        "psnr": 10.0 * math.log10(1.0 / max(mse, 1e-12)),
        "input_mae": input_mae,
        "input_mse": input_mse,
        "input_psnr": 10.0 * math.log10(1.0 / max(input_mse, 1e-12)),
        "improvement_vs_input": input_mae - mae,
        "prediction_mean": acc["prediction_mean_sum"] / rows,
        "prediction_std": acc["prediction_std_sum"] / rows,
        "clip_fraction": acc["clip_sum"] / rows,
    }


def _finish_pair_accumulator(acc: dict[str, float]) -> dict[str, Any]:
    pixels = max(acc["pixels"], 1.0)
    return {
        "pairs": int(acc["pairs"]),
        "error_of_output_delta_vs_teacher_delta": acc["error_sum"] / pixels,
        "output_delta_l1": acc["output_sum"] / pixels,
        "teacher_delta_l1": acc["teacher_sum"] / pixels,
        "input_delta_l1": acc["input_sum"] / pixels,
    }


def _new_pair_accumulator() -> dict[str, float]:
    return {"pairs": 0.0, "pixels": 0.0, "error_sum": 0.0, "output_sum": 0.0, "teacher_sum": 0.0, "input_sum": 0.0}


def _record_pair(
    acc: dict[str, float],
    current: torch.Tensor,
    previous: torch.Tensor,
    current_teacher: torch.Tensor,
    previous_teacher: torch.Tensor,
    current_input: torch.Tensor,
    previous_input: torch.Tensor,
) -> None:
    output_delta = current - previous
    teacher_delta = current_teacher - previous_teacher
    input_delta = current_input - previous_input
    pixels = float(current.numel())
    acc["pairs"] += 1.0
    acc["pixels"] += pixels
    acc["error_sum"] += float((output_delta - teacher_delta).abs().sum().item())
    acc["output_sum"] += float(output_delta.abs().sum().item())
    acc["teacher_sum"] += float(teacher_delta.abs().sum().item())
    acc["input_sum"] += float(input_delta.abs().sum().item())


def _parse_frames(value: str) -> list[int]:
    frames = sorted({int(part.strip()) for part in value.split(",") if part.strip()})
    if not frames:
        raise ValueError("at least one frame is required")
    return frames


def _records_for_frames(cache: TinyPairedCache, frames: list[int]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    requested = set(frames)
    for group in cache.groups:
        for frame_id, absolute_index in zip(group["frame_ids"], group["indices"]):
            if int(frame_id) in requested:
                records.append(
                    {
                        "sequence_id": str(group["sequence_id"]),
                        "eye": int(group["eye"]),
                        "frame_id": int(frame_id),
                        "cache_source": str(group["cache_source"]),
                        "absolute_index": int(absolute_index),
                    }
                )
    if not records:
        raise ValueError(f"no rows found for frames {frames}")
    return records


def _gallery_records(cache: TinyPairedCache, frame_id: int, per_cohort: int) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: dict[str, int] = {}
    by_sequence_eye = {(str(g["sequence_id"]), int(g["eye"])): g for g in cache.groups}
    for group in cache.groups:
        cohort = str(group["cache_source"])
        if int(group["eye"]) != 0 or seen.get(cohort, 0) >= per_cohort:
            continue
        if frame_id not in group["frame_ids"]:
            continue
        seen[cohort] = seen.get(cohort, 0) + 1
        for eye in (0, 1):
            sibling = by_sequence_eye.get((str(group["sequence_id"]), eye))
            if sibling is None or frame_id not in sibling["frame_ids"]:
                continue
            position = sibling["frame_ids"].index(frame_id)
            result.append(
                {
                    "sequence_id": str(sibling["sequence_id"]),
                    "eye": eye,
                    "frame_id": frame_id,
                    "cache_source": str(sibling["cache_source"]),
                    "absolute_index": int(sibling["indices"][position]),
                }
            )
    return result


def _tensor_to_image(tensor: torch.Tensor, tile_size: int | None = None) -> Image.Image:
    value = tensor.detach().float().clamp(0.0, 1.0).mul(255.0).round().byte().permute(1, 2, 0).cpu().numpy()
    image = Image.fromarray(value, mode="RGB")
    if tile_size is not None:
        image = image.resize((tile_size, tile_size), Image.Resampling.LANCZOS)
    return image


def _label_tile(image: Image.Image, label: str, sample: dict[str, Any], tile_size: int) -> Image.Image:
    tile = Image.new("RGB", (tile_size, tile_size + 34), "#151515")
    tile.paste(image, (0, 24))
    draw = ImageDraw.Draw(tile)
    draw.text((4, 4), label, fill="white")
    draw.text(
        (4, tile_size + 8),
        f"{sample['cache_source']} {sample['sequence_id']} e{sample['eye']} f{sample['frame_id']}",
        fill="#bdbdbd",
    )
    return tile


def _save_gallery(
    path: Path,
    samples: list[dict[str, Any]],
    columns: list[tuple[str, list[Image.Image]]],
    tile_size: int,
) -> None:
    tile_height = tile_size + 34
    sheet = Image.new("RGB", (len(columns) * tile_size, len(samples) * tile_height), "#151515")
    for column_index, (_, images) in enumerate(columns):
        for row_index, image in enumerate(images):
            sheet.paste(
                _label_tile(image, columns[column_index][0], samples[row_index], tile_size),
                (column_index * tile_size, row_index * tile_height),
            )
    sheet.save(path)


def _metrics_for_model(
    model: nn.Module,
    cache: TinyPairedCache,
    records: list[dict[str, Any]],
    quality_frames: set[int],
    gallery_lookup: dict[int, int],
    gallery_images: dict[str, list[Image.Image]],
    model_label: str,
    output_dir: Path,
    device: torch.device,
    batch_size: int,
) -> dict[str, Any]:
    model.eval()
    quality = _new_accumulator()
    quality_by_cohort: dict[str, dict[str, float]] = {}
    temporal = _new_pair_accumulator()
    stereo = _new_pair_accumulator()
    previous: dict[tuple[str, int], tuple[torch.Tensor, torch.Tensor, torch.Tensor, int]] = {}
    stereo_pending: dict[tuple[str, int], tuple[torch.Tensor, torch.Tensor, torch.Tensor]] = {}
    model_output_dir = output_dir / "quality_outputs" / model_label
    model_output_dir.mkdir(parents=True, exist_ok=True)

    with torch.inference_mode():
        for start in range(0, len(records), batch_size):
            batch_records = records[start : start + batch_size]
            ids = [record["absolute_index"] for record in batch_records]
            inputs, teachers = cache.load_batch(ids, device)
            predictions = model(inputs).float().clamp(0.0, 1.0)
            inputs = inputs.float()
            teachers = teachers.float()
            if not bool(torch.isfinite(predictions).all().item()):
                raise RuntimeError(f"{model_label} produced a non-finite prediction")

            for batch_index, record in enumerate(batch_records):
                prediction = predictions[batch_index]
                image_input = inputs[batch_index]
                teacher = teachers[batch_index]
                gallery_position = gallery_lookup.get(record["absolute_index"])
                if gallery_position is not None:
                    gallery_images[model_label][gallery_position] = _tensor_to_image(prediction)
                    sample_name = _safe_name(
                        f"{gallery_position:02d}_{record['cache_source']}_{record['sequence_id']}_e{record['eye']}_f{record['frame_id']}"
                    )
                    _tensor_to_image(prediction).save(model_output_dir / f"{sample_name}.png")

                if record["frame_id"] in quality_frames:
                    accumulator = quality_by_cohort.setdefault(record["cache_source"], _new_accumulator())
                    for target in (quality, accumulator):
                        error = prediction - teacher
                        input_error = image_input - teacher
                        target["rows"] += 1.0
                        target["pixels"] += float(error.numel())
                        target["abs_sum"] += float(error.abs().sum().item())
                        target["sq_sum"] += float(error.square().sum().item())
                        target["input_abs_sum"] += float(input_error.abs().sum().item())
                        target["input_sq_sum"] += float(input_error.square().sum().item())
                        target["prediction_mean_sum"] += float(prediction.mean().item())
                        target["prediction_std_sum"] += float(prediction.std().item())
                        target["clip_sum"] += float(((prediction <= 1e-6) | (prediction >= 1.0 - 1e-6)).float().mean().item())

                stream_key = (record["sequence_id"], record["eye"])
                prior = previous.get(stream_key)
                if prior is not None:
                    prior_prediction, prior_teacher, prior_input, prior_frame = prior
                    if record["frame_id"] == prior_frame + 1:
                        _record_pair(
                            temporal,
                            prediction,
                            prior_prediction,
                            teacher,
                            prior_teacher,
                            image_input,
                            prior_input,
                        )
                previous[stream_key] = (prediction.detach(), teacher.detach(), image_input.detach(), record["frame_id"])

                stereo_key = (record["sequence_id"], record["frame_id"])
                if record["eye"] == 0:
                    stereo_pending[stereo_key] = (prediction.detach(), teacher.detach(), image_input.detach())
                else:
                    prior_stereo = stereo_pending.pop(stereo_key, None)
                    if prior_stereo is not None:
                        prior_prediction, prior_teacher, prior_input = prior_stereo
                        _record_pair(
                            stereo,
                            prediction,
                            prior_prediction,
                            teacher,
                            prior_teacher,
                            image_input,
                            prior_input,
                        )

    return {
        "quality": _finish_accumulator(quality),
        "quality_by_cohort": {name: _finish_accumulator(value) for name, value in sorted(quality_by_cohort.items())},
        "temporal": _finish_pair_accumulator(temporal),
        "stereo": _finish_pair_accumulator(stereo),
        "evaluation": {
            "quality_frames": sorted(quality_frames),
            "rows_evaluated": len(records),
            "quality_rows": int(quality["rows"]),
            "temporally_chained_rows": len(records),
            "precision": "fp32",
            "teacher_used_for_inference": False,
            "teacher_used_for_selection": False,
            "reset_behavior": "stateless; reset metadata is preserved in the manifest but not consumed by the released model",
        },
    }


def _percentiles(values: list[float]) -> dict[str, float]:
    if not values:
        return {}
    ordered = sorted(values)

    def percentile(q: float) -> float:
        index = (len(ordered) - 1) * q
        lower = math.floor(index)
        upper = math.ceil(index)
        if lower == upper:
            return ordered[lower]
        fraction = index - lower
        return ordered[lower] * (1.0 - fraction) + ordered[upper] * fraction

    return {
        "median_ms": percentile(0.50),
        "p95_ms": percentile(0.95),
        "p99_ms": percentile(0.99),
        "min_ms": ordered[0],
        "max_ms": ordered[-1],
    }


def _timed_pass(
    model: nn.Module,
    shape: tuple[int, int, int, int],
    device: torch.device,
    iterations: int,
    warmup: int,
    include_h2d: bool,
) -> dict[str, Any]:
    if device.type != "cuda":
        return {"status": "skipped", "reason": "FP16 CUDA benchmark requires CUDA"}
    model.half().eval()
    gpu_input = torch.rand(shape, device=device, dtype=torch.float16)
    host_input = torch.rand(shape, dtype=torch.float16)
    timings: list[float] = []
    torch.cuda.reset_peak_memory_stats(device)
    try:
        with torch.inference_mode():
            for _ in range(warmup):
                model(host_input.to(device) if include_h2d else gpu_input)
            torch.cuda.synchronize(device)
            for _ in range(iterations):
                start = torch.cuda.Event(enable_timing=True)
                end = torch.cuda.Event(enable_timing=True)
                start.record()
                if include_h2d:
                    pass_input = host_input.to(device, non_blocking=False)
                else:
                    pass_input = gpu_input
                model(pass_input)
                end.record()
                end.synchronize()
                timings.append(float(start.elapsed_time(end)))
        peak_gib = float(torch.cuda.max_memory_allocated(device) / (1024**3))
        return {
            "status": "ok",
            "shape": list(shape),
            "precision": "fp16",
            "cost_definition": "CPU-to-GPU copy plus forward" if include_h2d else "forward with input resident on GPU",
            "iterations": iterations,
            "warmup": warmup,
            "timing_ms": _percentiles(timings),
            "peak_memory_allocated_gib": peak_gib,
        }
    except RuntimeError as error:
        message = str(error)
        if "out of memory" in message.lower():
            torch.cuda.empty_cache()
            return {
                "status": "oom",
                "shape": list(shape),
                "precision": "fp16",
                "error": message.splitlines()[0],
            }
        raise
    finally:
        del gpu_input, host_input
        torch.cuda.empty_cache()


def _benchmark_model(
    model: nn.Module,
    device: torch.device,
    full_height: int,
    full_width: int,
    iterations: int,
    warmup: int,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "gpu": torch.cuda.get_device_name(device) if device.type == "cuda" else str(device),
        "single_eye_512": _timed_pass(model, (1, 3, 512, 512), device, iterations, warmup, False),
        "single_eye_512_total": _timed_pass(model, (1, 3, 512, 512), device, iterations, warmup, True),
        "stereo_batch2_512": _timed_pass(model, (2, 3, 512, 512), device, iterations, warmup, False),
        "stereo_batch2_512_total": _timed_pass(model, (2, 3, 512, 512), device, iterations, warmup, True),
        "single_eye_representative": _timed_pass(
            model,
            (1, 3, full_height, full_width),
            device,
            max(3, min(iterations, 10)),
            max(1, min(warmup, 3)),
            False,
        ),
        "representative_resolution": {"height": full_height, "width": full_width},
    }
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--split", choices=["validation", "test"], default="test")
    parser.add_argument("--quality-frame", type=int, default=32)
    parser.add_argument("--temporal-frames", default="31,32,33")
    parser.add_argument("--gallery-per-cohort", type=int, default=3)
    parser.add_argument("--tile-size", type=int, default=224)
    parser.add_argument("--batch-size", type=int, default=1)
    parser.add_argument("--full-height", type=int, default=2496)
    parser.add_argument("--full-width", type=int, default=2688)
    parser.add_argument("--benchmark-iterations", type=int, default=20)
    parser.add_argument("--benchmark-warmup", type=int, default=10)
    parser.add_argument("--device", default="cuda")
    args = parser.parse_args()

    if args.device == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("CUDA is required for the photorealism evaluation")
    device = torch.device(args.device)
    source_root = args.source_root.resolve()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)

    quality_frames = {int(args.quality_frame)}
    temporal_frames = _parse_frames(args.temporal_frames)
    evaluation_frames = sorted(quality_frames | set(temporal_frames))
    cache = TinyPairedCache(args.manifest.resolve(), args.split)
    records = _records_for_frames(cache, evaluation_frames)
    gallery_samples = _gallery_records(cache, args.quality_frame, args.gallery_per_cohort)
    gallery_lookup = {sample["absolute_index"]: index for index, sample in enumerate(gallery_samples)}
    gallery_inputs: list[Image.Image | None] = [None] * len(gallery_samples)
    gallery_teachers: list[Image.Image | None] = [None] * len(gallery_samples)
    for index, sample in enumerate(gallery_samples):
        inputs, teachers = cache.load_batch([sample["absolute_index"]], device=None)
        gallery_inputs[index] = _tensor_to_image(inputs[0])
        gallery_teachers[index] = _tensor_to_image(teachers[0])

    model_specs = [
        {
            "label": "hypergan_gta2cityscapes",
            "family": "HyPER-GAN",
            "architecture": "lightweight U-Net generator, 64 base channels, 4 residual blocks",
            "checkpoint": str((source_root / "hypergan" / "pretrained_models" / "gta2cs.pth").resolve()),
            "training_domain": "GTA-V to Cityscapes; released OOD street-scene checkpoint",
            "license": "MIT (official repository snapshot)",
            "factory": lambda: HyperModel(source_root / "hypergan" / "pretrained_models" / "gta2cs.pth"),
        },
        {
            "label": "hypergan_gta2vistas",
            "family": "HyPER-GAN",
            "architecture": "lightweight U-Net generator, 64 base channels, 4 residual blocks",
            "checkpoint": str((source_root / "hypergan" / "pretrained_models" / "gta2vistas.pth").resolve()),
            "training_domain": "GTA-V to Mapillary Vistas; released OOD street-scene checkpoint",
            "license": "MIT (official repository snapshot)",
            "factory": lambda: HyperModel(source_root / "hypergan" / "pretrained_models" / "gta2vistas.pth"),
        },
        {
            "label": "regen_gta2cityscapes",
            "family": "REGEN",
            "architecture": "Pix2PixHD GlobalGenerator, 64 base channels, 4 downsampling layers, 9 residual blocks",
            "checkpoint": str((source_root / "regen" / "weights" / "gta2cityscapes_latest_net_G.pth").resolve()),
            "training_domain": "GTA-V to Cityscapes; released OOD street-scene checkpoint",
            "license": "BSD 2-Clause root license plus included upstream notices",
            "factory": lambda: RegenModel(source_root / "regen" / "code", source_root / "regen" / "weights" / "gta2cityscapes_latest_net_G.pth"),
        },
    ]

    gallery_model_images: dict[str, list[Image.Image]] = {
        spec["label"]: [None] * len(gallery_samples) for spec in model_specs  # type: ignore[list-item]
    }
    all_metrics: dict[str, Any] = {}
    all_benchmarks: dict[str, Any] = {}
    metadata: list[dict[str, Any]] = []

    for spec in model_specs:
        label = str(spec["label"])
        print(json.dumps({"loading": {key: value for key, value in spec.items() if key != "factory"}}), flush=True)
        model = spec["factory"]().to(device).eval()
        parameter_count = sum(parameter.numel() for parameter in model.parameters())
        metadata.append(
            {
                **{key: value for key, value in spec.items() if key != "factory"},
                "parameters": parameter_count,
            }
        )
        all_metrics[label] = _metrics_for_model(
            model=model,
            cache=cache,
            records=records,
            quality_frames=quality_frames,
            gallery_lookup=gallery_lookup,
            gallery_images=gallery_model_images,
            model_label=label,
            output_dir=output,
            device=device,
            batch_size=args.batch_size,
        )
        print(json.dumps({"quality_complete": label, "metrics": all_metrics[label]["quality"]}), flush=True)
        all_benchmarks[label] = _benchmark_model(
            model=model,
            device=device,
            full_height=args.full_height,
            full_width=args.full_width,
            iterations=args.benchmark_iterations,
            warmup=args.benchmark_warmup,
        )
        print(json.dumps({"benchmark_complete": label, "single_eye_512": all_benchmarks[label]["single_eye_512"]}), flush=True)
        del model
        if device.type == "cuda":
            torch.cuda.empty_cache()

    if any(image is None for image in gallery_inputs + gallery_teachers):
        raise RuntimeError("gallery input/teacher construction failed")
    if any(image is None for images in gallery_model_images.values() for image in images):
        raise RuntimeError("one or more models did not produce all gallery images")
    columns: list[tuple[str, list[Image.Image]]] = [
        ("Input", [image for image in gallery_inputs if image is not None]),
        ("DLSS5-NR teacher", [image for image in gallery_teachers if image is not None]),
    ]
    columns.extend(
        (label, [image for image in images if image is not None])
        for label, images in gallery_model_images.items()
    )
    gallery_path = output / "photorealism_gallery.png"
    _save_gallery(gallery_path, gallery_samples, columns, args.tile_size)

    manifest_hash = None
    try:
        import hashlib

        digest = hashlib.sha256()
        with args.manifest.resolve().open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
        manifest_hash = digest.hexdigest()
    except OSError:
        pass

    result = {
        "schema": "opennr-tiny-enhancement-photorealism-eval-v1",
        "manifest": str(args.manifest.resolve()),
        "manifest_sha256": manifest_hash,
        "source_root": str(source_root),
        "split": args.split,
        "test_used_for_tuning": False,
        "quality_scope": {
            "frame_ids": sorted(quality_frames),
            "rows": len([record for record in records if record["frame_id"] in quality_frames]),
            "sequences": len({record["sequence_id"] for record in records if record["frame_id"] in quality_frames}),
            "both_eyes": True,
        },
        "temporal_scope": {
            "frame_ids": temporal_frames,
            "rows": len(records),
            "sequences": len({record["sequence_id"] for record in records}),
            "reset_metadata_preserved": True,
            "model_state": "stateless inference; no reset token or temporal history consumed",
        },
        "device": torch.cuda.get_device_name(device) if device.type == "cuda" else str(device),
        "torch": torch.__version__,
        "models": metadata,
        "metrics": all_metrics,
        "benchmarks": all_benchmarks,
        "gallery": str(gallery_path),
        "notes": [
            "HyPER-GAN and REGEN checkpoints are official street-scene models evaluated OOD on unseen Skyrim frames.",
            "The DLSS5-NR teacher is used only for after-the-fact similarity metrics and visual context.",
            "The fixed frame-32 quality cohort is separate from the three-frame temporal/stereo sanity scope.",
            "A convincing independent photorealistic style remains a valid outcome even when teacher MAE is worse than the paired control models.",
        ],
    }
    (output / "photorealism_eval.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    (output / "model_metadata.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
