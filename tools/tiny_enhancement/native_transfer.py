"""Evaluate released pretrained enhancement models on unseen OpenNR crops.

This is intentionally separate from the paired teacher-distillation harness.
The models in this file receive only the frozen test input RGB.  Teacher RGB is
loaded only by the cache contract (and is not passed to a model or used for
selection).  The official LUT implementations are run through small
PyTorch-only interpolation fallbacks so that the source snapshots do not need
to be compiled or modified on this Windows host.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import math
import re
import sys
import types
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable

import torch
import torch.nn as nn
import torch.nn.functional as F
from PIL import Image, ImageDraw

from .dataset import TinyPairedCache
from .models import ZeroDCEConfig, ZeroDCEPlusPlus


def _load_module(module_name: str, path: Path):
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"could not load module from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _sample_lut3d(lut: torch.Tensor, image: torch.Tensor) -> torch.Tensor:
    """Official 3D-LUT layout: [channel, B, G, R]."""

    # grid_sample's 5D coordinate order is (x=W, y=H, z=D), matching the
    # official LUT's R/G/B axis order when the LUT tensor is [B,G,R].
    coordinates = image.permute(0, 2, 3, 1).clamp(0.0, 1.0).mul(2.0).sub(1.0)
    sampled = F.grid_sample(
        lut,
        coordinates.unsqueeze(1),
        mode="bilinear",
        padding_mode="border",
        align_corners=True,
    )
    return sampled.squeeze(2)


def _sample_plane(plane: torch.Tensor, x: torch.Tensor, y: torch.Tensor) -> torch.Tensor:
    """Batched bilinear sampling of [B,H,W] planes at normalized coordinates."""

    coordinates = torch.stack((x.clamp(0.0, 1.0), y.clamp(0.0, 1.0)), dim=-1)
    return F.grid_sample(
        plane.unsqueeze(1),
        coordinates.mul(2.0).sub(1.0),
        mode="bilinear",
        padding_mode="border",
        align_corners=True,
    ).squeeze(1)


def _svdlut_fallback(
    grid: torch.Tensor,
    image: torch.Tensor,
    grid_weights: torch.Tensor,
    grid_bias: torch.Tensor,
    lut: torch.Tensor,
    lut_weights: torch.Tensor,
    lut_bias: torch.Tensor,
) -> torch.Tensor:
    """Pure PyTorch equivalent of SVDLUT's released CUDA slicing kernel.

    The coordinate pairs and channel layout mirror
    ``trilinear2D_slice_LUTTransform_cuda.cu`` in the official snapshot.
    """

    _, _, height, width = image.shape
    y_coord = torch.linspace(0.0, 1.0, height, device=image.device, dtype=image.dtype)
    x_coord = torch.linspace(0.0, 1.0, width, device=image.device, dtype=image.dtype)
    y_coord = y_coord.view(1, height, 1).expand(image.shape[0], height, width)
    x_coord = x_coord.view(1, 1, width).expand(image.shape[0], height, width)
    red, green, blue = image[:, 0], image[:, 1], image[:, 2]

    grid_per_channel = grid.shape[1] // image.shape[1]
    intermediate = torch.zeros_like(image)
    coordinate_sets = (
        ((x_coord, y_coord), (x_coord, red), (y_coord, red)),
        ((x_coord, y_coord), (x_coord, green), (y_coord, green)),
        ((x_coord, y_coord), (x_coord, blue), (y_coord, blue)),
    )
    for channel, pairs in enumerate(coordinate_sets):
        value = torch.zeros_like(red)
        for branch in range(grid_per_channel):
            grid_channel = channel * grid_per_channel + branch
            for subchannel, (coord_x, coord_y) in enumerate(pairs):
                value = value + grid_weights[:, branch, 3 * channel + subchannel].view(-1, 1, 1) * _sample_plane(
                    grid[:, grid_channel, subchannel], coord_x, coord_y
                )
            value = value + grid_bias[:, branch, channel].view(-1, 1, 1)
        intermediate[:, channel] = value

    lut_pairs = ((red, green), (red, blue), (green, blue))
    output = intermediate.clone()
    for channel in range(3):
        pair_values = (
            _sample_plane(lut[:, channel, 0], *lut_pairs[0]),
            _sample_plane(lut[:, channel, 1], *lut_pairs[1]),
            _sample_plane(lut[:, channel, 2], *lut_pairs[2]),
        )
        output[:, channel] = (
            intermediate[:, channel]
            + sum(
                lut_weights[:, channel, branch].view(-1, 1, 1) * pair_values[branch]
                for branch in range(3)
            )
            + lut_bias[:, channel].view(-1, 1, 1)
        )
    return output


def _install_svd_fallback() -> None:
    extension_interface = types.ModuleType("cpp_ext_interface")
    extension_interface.bilinear_2Dslicing_lut_transform = _svdlut_fallback
    sys.modules["cpp_ext_interface"] = extension_interface


def _install_adaptive_extension_stub() -> None:
    package = types.ModuleType("trilinear_c")
    package.__path__ = []  # type: ignore[attr-defined]
    extension = types.ModuleType("trilinear_c._ext")
    extension.trilinear = types.SimpleNamespace()
    sys.modules["trilinear_c"] = package
    sys.modules["trilinear_c._ext"] = extension


class OfficialAdaptive(nn.Module):
    def __init__(self, source_dir: Path, classifier_path: Path, luts_path: Path, unpaired: bool):
        super().__init__()
        _install_adaptive_extension_stub()
        official = _load_module(
            f"official_adaptive_{'unpaired' if unpaired else 'paired'}",
            source_dir / "models.py",
        )
        classifier_class = official.Classifier_unpaired if unpaired else official.Classifier
        self.classifier = classifier_class()
        classifier_state = torch.load(classifier_path, map_location="cpu", weights_only=False)
        self.classifier.load_state_dict(classifier_state, strict=True)

        lut_state = torch.load(luts_path, map_location="cpu", weights_only=False)
        self.lut_bank = nn.Parameter(
            torch.stack([lut_state[str(index)]["LUT"] for index in range(3)], dim=0),
            requires_grad=False,
        )

    def forward(self, image: torch.Tensor) -> torch.Tensor:
        coefficients = self.classifier(image).flatten(1)
        lut = torch.einsum("bk,kcxyz->bcxyz", coefficients, self.lut_bank)
        return _sample_lut3d(lut, image).clamp(0.0, 1.0)


class OfficialSVDLUT(nn.Module):
    def __init__(self, source_dir: Path, checkpoint_path: Path, configuration: dict):
        super().__init__()
        _install_svd_fallback()
        official = _load_module("official_svdlut", source_dir / "models.py")
        # The released PPR10K experts use the official ResNet-18 backbone.
        # That constructor still asks torchvision for ImageNet weights even
        # though the checkpoint contains the complete ResNet state.  Build
        # the same architecture without a network/cache lookup, then load the
        # released state dict below.
        if configuration.get("backbone_type", "cnn").lower() == "resnet":
            import torchvision.models as torchvision_models

            original_resnet18 = official.models.resnet18

            def resnet18_without_download(*args, **kwargs):
                kwargs.pop("pretrained", None)
                kwargs["weights"] = None
                return original_resnet18(*args, **kwargs)

            official.models.resnet18 = resnet18_without_download
            try:
                self.model = official.SVDLUT(**configuration)
            finally:
                official.models.resnet18 = original_resnet18
        else:
            self.model = official.SVDLUT(**configuration)
        checkpoint = torch.load(checkpoint_path, map_location="cpu", weights_only=False)
        self.model.load_state_dict(checkpoint, strict=True)

    def forward(self, image: torch.Tensor) -> torch.Tensor:
        return self.model(image)[0].clamp(0.0, 1.0)


class OfficialZeroDCE(nn.Module):
    def __init__(self, checkpoint_path: Path):
        super().__init__()
        self.model = ZeroDCEPlusPlus(ZeroDCEConfig(scale_factor=12))
        checkpoint = torch.load(checkpoint_path, map_location="cpu", weights_only=False)
        self.model.load_state_dict(checkpoint, strict=True)

    def forward(self, image: torch.Tensor) -> torch.Tensor:
        height, width = image.shape[-2:]
        factor = 12
        padded_height = math.ceil(height / factor) * factor
        padded_width = math.ceil(width / factor) * factor
        padded = F.pad(image, (0, padded_width - width, 0, padded_height - height), mode="reflect")
        result = self.model(padded)
        return result[..., :height, :width]


class OfficialSRVGG(nn.Module):
    def __init__(self, checkpoint_path: Path):
        super().__init__()
        num_feat = 64
        upscale = 4
        body: list[nn.Module] = [nn.Conv2d(3, num_feat, 3, 1, 1), nn.PReLU(num_parameters=num_feat)]
        for _ in range(32):
            body.extend((nn.Conv2d(num_feat, num_feat, 3, 1, 1), nn.PReLU(num_parameters=num_feat)))
        body.append(nn.Conv2d(num_feat, 3 * upscale * upscale, 3, 1, 1))
        self.body = nn.Sequential(*body)
        self.upsampler = nn.PixelShuffle(upscale)
        checkpoint = torch.load(checkpoint_path, map_location="cpu", weights_only=False)
        self.load_state_dict(checkpoint["params"], strict=True)

    def forward(self, image: torch.Tensor) -> torch.Tensor:
        residual = self.upsampler(self.body(image))
        base = F.interpolate(image, scale_factor=4, mode="nearest")
        return (residual + base).clamp(0.0, 1.0)


@dataclass(frozen=True)
class NativeSpec:
    label: str
    family: str
    checkpoint: str
    resolution_behavior: str


def _select_samples(cache: TinyPairedCache, per_cohort_sequences: int, frame: int) -> list[dict]:
    selected_groups: list[dict] = []
    seen_sequences: dict[str, int] = {}
    for group in cache.groups:
        cohort = str(group["cache_source"])
        if seen_sequences.get(cohort, 0) >= per_cohort_sequences:
            continue
        if group["eye"] == 0:
            selected_groups.append(group)
            seen_sequences[cohort] = seen_sequences.get(cohort, 0) + 1
            sibling = next(
                (
                    candidate
                    for candidate in cache.groups
                    if candidate["sequence_id"] == group["sequence_id"] and candidate["eye"] == 1
                ),
                None,
            )
            if sibling is not None:
                selected_groups.append(sibling)

    samples: list[dict] = []
    for group in selected_groups:
        frame_ids = group["frame_ids"]
        chosen_frame = frame if frame in frame_ids else frame_ids[len(frame_ids) // 2]
        absolute_index = group["indices"][frame_ids.index(chosen_frame)]
        samples.append(
            {
                "sequence_id": group["sequence_id"],
                "eye": group["eye"],
                "frame_id": chosen_frame,
                "cache_source": group["cache_source"],
                "absolute_index": absolute_index,
            }
        )
    return samples


def _to_image(tensor: torch.Tensor, size: int) -> Image.Image:
    value = tensor.detach().float().clamp(0.0, 1.0).mul(255.0).round().byte().permute(1, 2, 0).cpu().numpy()
    return Image.fromarray(value, mode="RGB").resize((size, size), Image.Resampling.LANCZOS)


def _safe_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value)


def _label_tile(image: Image.Image, label: str, sample: dict, tile_size: int) -> Image.Image:
    tile = Image.new("RGB", (tile_size, tile_size + 24), "#151515")
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
    output_path: Path,
    input_images: list[Image.Image],
    model_images: dict[str, list[Image.Image]],
    samples: list[dict],
    tile_size: int,
) -> None:
    columns = [("Input", input_images)] + list(model_images.items())
    tile_height = tile_size + 24
    sheet = Image.new("RGB", (len(columns) * tile_size, len(samples) * tile_height), "#151515")
    for column_index, (label, images) in enumerate(columns):
        for row_index, image in enumerate(images):
            sheet.paste(
                _label_tile(image, label, samples[row_index], tile_size),
                (column_index * tile_size, row_index * tile_height),
            )
    sheet.save(output_path)


def _svdlut_configuration(label: str) -> dict:
    if label == "svdlut_fivek":
        return {
            "backbone_type": "cnn",
            "backbone_coef": 8,
            "lut_n_vertices": 33,
            "lut_n_ranks": 8,
            "grid_n_vertices": 17,
            "grid_n_ranks": 8,
            "ch_per_grid": 2,
            "lut_weight_ranks": 8,
            "grid_weight_ranks": 8,
            "lut_n_singular": 8,
            "grid_n_singular": 8,
        }
    return {
        # The PPR10K experts are the ResNet-18 variant.  Their tensor shapes
        # are authoritative: the feature width is 512, the 3D LUT has ten
        # ranks, and the bilateral-grid path has eight ranks.
        "backbone_type": "resnet",
        "backbone_coef": 8,
        "lut_n_vertices": 33,
        "lut_n_ranks": 10,
        "grid_n_vertices": 17,
        "grid_n_ranks": 8,
        "ch_per_grid": 2,
        "lut_weight_ranks": 10,
        "grid_weight_ranks": 8,
        "lut_n_singular": 8,
        "grid_n_singular": 8,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--split", choices=["validation", "test"], default="test")
    parser.add_argument("--per-cohort-sequences", type=int, default=3)
    parser.add_argument("--frame", type=int, default=32)
    parser.add_argument("--tile-size", type=int, default=224)
    parser.add_argument("--device", default="cuda")
    args = parser.parse_args()

    if args.device == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("CUDA is required for this native transfer pass")
    device = torch.device(args.device)
    source_root = args.source_root.resolve()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    cache = TinyPairedCache(args.manifest.resolve(), args.split)
    samples = _select_samples(cache, args.per_cohort_sequences, args.frame)
    (output / "samples.json").write_text(json.dumps(samples, indent=2) + "\n", encoding="utf-8")

    adaptive_root = source_root / "adaptive_3dlut"
    svdlut_root = source_root / "svdlut"
    zero_root = source_root / "zero_dce" / "Zero-DCE++"
    real_root = source_root / "real_esrgan"

    specs: list[tuple[NativeSpec, Callable[[], nn.Module]]] = [
        (
            NativeSpec("adaptive_fivek", "Image-Adaptive-3DLUT", "sRGB/paired", "same_resolution"),
            lambda: OfficialAdaptive(
                adaptive_root,
                adaptive_root / "pretrained_models" / "sRGB" / "classifier.pth",
                adaptive_root / "pretrained_models" / "sRGB" / "LUTs.pth",
                False,
            ),
        ),
        (
            NativeSpec("adaptive_unpaired", "Image-Adaptive-3DLUT", "sRGB/unpaired", "same_resolution"),
            lambda: OfficialAdaptive(
                adaptive_root,
                adaptive_root / "pretrained_models" / "sRGB" / "classifier_unpaired.pth",
                adaptive_root / "pretrained_models" / "sRGB" / "LUTs_unpaired.pth",
                True,
            ),
        ),
        (
            NativeSpec("svdlut_fivek", "SVDLUT", "fiveK_sRGB.pth", "same_resolution"),
            lambda: OfficialSVDLUT(
                svdlut_root,
                svdlut_root / "pretrained" / "fiveK_sRGB.pth",
                _svdlut_configuration("svdlut_fivek"),
            ),
        ),
        *[
            (
                NativeSpec(f"svdlut_ppr_{expert}", "SVDLUT", f"ppr10K_{expert}.pth", "same_resolution"),
                lambda expert=expert: OfficialSVDLUT(
                    svdlut_root,
                    svdlut_root / "pretrained" / f"ppr10K_{expert}.pth",
                    _svdlut_configuration(f"svdlut_ppr_{expert}"),
                ),
            )
            for expert in ("a", "b", "c")
        ],
        (
            NativeSpec("zero_dce_official", "Zero-DCE++", "Epoch99.pth", "same_resolution_after_padding"),
            lambda: OfficialZeroDCE(zero_root / "snapshots_Zero_DCE++" / "Epoch99.pth"),
        ),
        (
            NativeSpec("realesr_general_x4v3", "Real-ESRGAN SRVGG", "realesr-general-x4v3.pth", "x4_super_resolution"),
            lambda: OfficialSRVGG(real_root / "weights" / "realesr-general-x4v3.pth"),
        ),
    ]

    input_images: list[Image.Image] = []
    input_tensors: list[torch.Tensor] = []
    teacher_tensors: list[torch.Tensor] = []
    for sample in samples:
        inputs, teachers = cache.load_batch([sample["absolute_index"]], device)
        input_tensors.append(inputs[0].detach().float().cpu())
        teacher_tensors.append(teachers[0].detach().float().cpu())
        input_images.append(_to_image(inputs[0], args.tile_size))

    model_images: dict[str, list[Image.Image]] = {}
    model_stats: list[dict] = []
    lut_labels = ["adaptive_fivek", "adaptive_unpaired", "svdlut_fivek", "svdlut_ppr_a", "svdlut_ppr_b", "svdlut_ppr_c"]
    other_labels = ["zero_dce_official", "realesr_general_x4v3"]
    for spec, factory in specs:
        print(json.dumps({"loading": asdict(spec)}), flush=True)
        model = factory().to(device).eval()
        images: list[Image.Image] = []
        changes: list[float] = []
        clip_fractions: list[float] = []
        teacher_abs_sum = 0.0
        teacher_sq_sum = 0.0
        input_abs_sum = 0.0
        comparison_pixels = 0.0
        native_dir = output / "outputs" / spec.label
        native_dir.mkdir(parents=True, exist_ok=True)
        with torch.inference_mode():
            for index, sample in enumerate(samples):
                inputs, _ = cache.load_batch([sample["absolute_index"]], device)
                prediction = model(inputs)[0].clamp(0.0, 1.0)
                prediction_cpu = prediction.detach().float().cpu()
                images.append(_to_image(prediction, args.tile_size))
                source = input_tensors[index]
                teacher = teacher_tensors[index]
                comparison = prediction_cpu
                if comparison.shape[-2:] != source.shape[-2:]:
                    comparison = F.interpolate(
                        comparison.unsqueeze(0), size=source.shape[-2:], mode="bilinear", align_corners=False
                    )[0]
                teacher_error = comparison - teacher
                input_error = source - teacher
                teacher_abs_sum += float(teacher_error.abs().sum().item())
                teacher_sq_sum += float(teacher_error.square().sum().item())
                input_abs_sum += float(input_error.abs().sum().item())
                comparison_pixels += float(teacher_error.numel())
                changes.append(float((comparison - source).abs().mean()))
                clip_fractions.append(float(((prediction_cpu <= 1e-6) | (prediction_cpu >= 1.0 - 1e-6)).float().mean()))
                sample_name = _safe_name(
                    f"{index:02d}_{sample['cache_source']}_{sample['sequence_id']}_e{sample['eye']}_f{sample['frame_id']}"
                )
                Image.fromarray(
                    prediction_cpu.mul(255.0).round().byte().permute(1, 2, 0).numpy(), mode="RGB"
                ).save(native_dir / f"{sample_name}.png")
        model_images[spec.label] = images
        model_stats.append(
            {
                **asdict(spec),
                "parameters": sum(parameter.numel() for parameter in model.parameters()),
                "mean_abs_change_vs_input": sum(changes) / len(changes),
                "teacher_mae": teacher_abs_sum / max(comparison_pixels, 1.0),
                "teacher_mse": teacher_sq_sum / max(comparison_pixels, 1.0),
                "teacher_psnr": 10.0 * math.log10(1.0 / max(teacher_sq_sum / max(comparison_pixels, 1.0), 1e-12)),
                "input_mae_same_comparison_resolution": input_abs_sum / max(comparison_pixels, 1.0),
                "mean_clip_fraction": sum(clip_fractions) / len(clip_fractions),
                "samples": len(samples),
                "teacher_comparison": "prediction bilinearly resized to input/teacher resolution when the model changes resolution",
            }
        )
        del model
        if device.type == "cuda":
            torch.cuda.empty_cache()
        print(json.dumps({"completed": spec.label, "mean_abs_change_vs_input": model_stats[-1]["mean_abs_change_vs_input"]}), flush=True)

    _save_gallery(output / "native_lut_gallery.png", input_images, {label: model_images[label] for label in lut_labels}, samples, args.tile_size)
    _save_gallery(output / "native_other_gallery.png", input_images, {label: model_images[label] for label in other_labels}, samples, args.tile_size)
    result = {
        "schema": "opennr-tiny-enhancement-native-transfer-v2",
        "manifest": str(args.manifest.resolve()),
        "split": args.split,
        "teacher_used_for_inference": False,
        "teacher_used_for_selection": False,
        "sample_count": len(samples),
        "device": torch.cuda.get_device_name(0) if device.type == "cuda" else str(device),
        "torch": torch.__version__,
        "models": model_stats,
        "galleries": {
            "lut": str(output / "native_lut_gallery.png"),
            "other": str(output / "native_other_gallery.png"),
        },
        "notes": [
            "Inputs are frozen test rows unseen by the paired training arm.",
            "Official SVDLUT CUDA slicing was reproduced with F.grid_sample; no source snapshot was modified.",
            "Real-ESRGAN output is x4 and is not a same-resolution NR candidate.",
            "Teacher images remain in the paired galleries and were not provided to native models.",
        ],
    }
    (output / "native_transfer.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
