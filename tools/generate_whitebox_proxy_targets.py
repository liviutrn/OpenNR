#!/usr/bin/env python3
"""Generate quantized 512x512 white-box targets from complete eye frames.

This is an offline research target generator.  The recovered graph is run on
the entire captured eye, then the exact crop boxes already present in the
base OpenNR cache are applied to the recovered image.  The base cache's
``rgb.npy[..., 1]`` remains the native NVIDIA teacher; proxy targets are
stored in a separate ``proxy.npy`` array.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import sys
import time
from typing import Any

import numpy as np
from PIL import Image, ImageDraw


COLOR_FORMAT = "R8G8B8A8_UNORM"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def read_color_raw(path: Path, width: int, height: int, row_pitch: int) -> np.ndarray:
    raw = path.read_bytes()
    expected = row_pitch * height
    if len(raw) != expected:
        raise ValueError(f"{path}: {len(raw)} bytes, expected {expected}")
    if row_pitch < width * 4:
        raise ValueError(f"{path}: row pitch is too small for RGBA")
    rows = np.frombuffer(raw, dtype=np.uint8).reshape(height, row_pitch)
    return rows[:, : width * 4].reshape(height, width, 4)[..., :3].astype(np.float32) / 255.0


def rgb_image(array_chw: np.ndarray) -> Image.Image:
    return Image.fromarray(np.asarray(array_chw).transpose(1, 2, 0).clip(0, 255).astype(np.uint8), mode="RGB")


def preview_sheet(input_chw: np.ndarray, proxy_chw: np.ndarray, native_chw: np.ndarray, output: Path) -> None:
    panels = [
        ("Input", rgb_image(input_chw)),
        ("White-box proxy", rgb_image(proxy_chw)),
        ("Native NVIDIA", rgb_image(native_chw)),
    ]
    width = 384
    label_height = 28
    canvas = Image.new("RGB", (width * len(panels), width + label_height), (24, 24, 24))
    draw = ImageDraw.Draw(canvas)
    for index, (label, image) in enumerate(panels):
        left = index * width
        draw.text((left + 6, 6), label, fill=(240, 240, 240))
        canvas.paste(image.resize((width, width), Image.Resampling.BILINEAR), (left, label_height))
    output.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output, quality=94)


def add_module_path(path: Path) -> None:
    resolved = str(path.expanduser().resolve())
    if resolved not in sys.path:
        sys.path.insert(0, resolved)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--weights", type=Path, required=True)
    parser.add_argument("--dll", type=Path, required=True, help="provenance reference; never loaded")
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--mlx-python", type=Path, required=True, help="MLX-DLSS/python source directory")
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--precision", choices=("reference", "fast"), default="reference")
    parser.add_argument("--frame-index", type=int, default=0)
    parser.add_argument("--local-tone", type=float, default=1.0)
    parser.add_argument("--local-structure", type=float, default=1.0)
    parser.add_argument("--skin-structure", type=float, default=-1.0)
    parser.add_argument("--mask-structure", type=float, default=1.0)
    parser.add_argument("--intensity", type=float, default=1.0)
    parser.add_argument("--detail-strength", type=float, default=1.0)
    parser.add_argument("--colour-strength", type=float, default=1.0)
    parser.add_argument("--use-auto-mask", action="store_true")
    parser.add_argument("--preview-rows", type=int, default=12)
    args = parser.parse_args()

    cache = args.cache.expanduser().resolve()
    weights = args.weights.expanduser().resolve()
    dll = args.dll.expanduser().resolve()
    if not cache.is_dir() or not (cache / "complete.json").is_file():
        raise FileNotFoundError(f"base cache is not complete: {cache}")
    for path in (weights, dll, args.mlx_python.expanduser().resolve()):
        if not path.exists():
            raise FileNotFoundError(path)
    if args.frame_index < 0:
        raise ValueError("frame index must be non-negative")
    target_path = cache / "proxy.npy"
    metadata_path = cache / "proxy_complete.json"
    if target_path.exists() or metadata_path.exists():
        raise FileExistsError(f"proxy target already exists in {cache}; use a new research cache")

    rows = json.loads((cache / "rows.json").read_text(encoding="utf-8"))
    plan = json.loads((cache / "patches.json").read_text(encoding="utf-8"))
    if not isinstance(rows, list) or not rows or not isinstance(plan, list) or not plan:
        raise ValueError("cache rows/patch plan is empty or malformed")
    rgb = np.load(cache / "rgb.npy", mmap_mode="r")
    if tuple(rgb.shape[1:]) != (2, 3, 512, 512) or rgb.shape[0] != len(plan):
        raise ValueError(f"unexpected base rgb shape {rgb.shape} for {len(plan)} patches")
    by_row: dict[int, list[int]] = defaultdict(list)
    for index, item in enumerate(plan):
        row_index = int(item["row"])
        if row_index < 0 or row_index >= len(rows):
            raise ValueError(f"patch {index}: invalid row {row_index}")
        box = item.get("box")
        if not isinstance(box, list) or len(box) != 4 or tuple(map(int, box[2:])) != (512, 512):
            raise ValueError(f"patch {index}: expected a 512x512 crop box")
        by_row[row_index].append(index)

    add_module_path(args.mlx_python)
    import torch
    from mlxdlss import AutomaticMask, NeuralRenderingPipeline

    if str(args.device).startswith("cuda") and not torch.cuda.is_available():
        raise RuntimeError("CUDA was requested but torch.cuda.is_available() is false")
    torch.set_num_threads(4)
    pipeline = NeuralRenderingPipeline.from_safetensors(
        weights, device=args.device, precision=args.precision
    )
    pipeline.model.eval()
    options: dict[str, Any] = {
        "profile": "standard",
        "processing_scale": 1.0,
        "detail_strength": args.detail_strength,
        "colour_strength": args.colour_strength,
        "intensity": args.intensity,
        "frame_index": args.frame_index,
        "local_tone_strength": args.local_tone,
        "local_structure_strength": args.local_structure,
    }
    if args.use_auto_mask:
        options["automatic_mask"] = AutomaticMask(
            skin_structure_strength=args.skin_structure,
            automatic_mask_structure_strength=args.mask_structure,
        )

    partial_path = cache / "proxy.npy.partial"
    proxy = np.lib.format.open_memmap(partial_path, mode="w+", dtype="u1", shape=(len(plan), 3, 512, 512))
    preview_root = cache / "proxy_previews"
    preview_row_ids = sorted(rows, key=lambda item: (item.get("split", ""), item.get("sequence_id", ""), int(item.get("frame_id", 0)), int(item.get("eye", 0))))
    preview_row_ids = {rows.index(row) for row in preview_row_ids[: max(0, args.preview_rows)]}
    records: list[dict[str, Any]] = []
    started = time.perf_counter()
    for row_index, row in enumerate(rows):
        width, height = map(int, row["color_size"])
        raw_path = Path(row["raw_paths"]["input"])
        raw_artifact = raw_path
        # The manifest records the exact raw file; its dimensions/row pitch are
        # recoverable from the committed byte length and the RGBA contract.
        expected = width * height * 4
        raw_bytes = raw_artifact.stat().st_size
        if raw_bytes != expected:
            raise ValueError(f"{raw_artifact}: {raw_bytes} bytes, expected {expected}")
        source = read_color_raw(raw_artifact, width, height, width * 4)
        call_started = time.perf_counter()
        result = pipeline.enhance(source, **options)
        recovered = np.asarray(result.image, dtype=np.float32)
        if recovered.shape != source.shape:
            raise ValueError(f"row {row_index}: recovered shape {recovered.shape} != source {source.shape}")
        for patch_index in by_row[row_index]:
            x, y, patch_width, patch_height = map(int, plan[patch_index]["box"])
            if x < 0 or y < 0 or x + patch_width > width or y + patch_height > height:
                raise ValueError(f"row {row_index} patch {patch_index}: crop exceeds full eye")
            crop = np.rint(np.clip(recovered[y : y + patch_height, x : x + patch_width], 0.0, 1.0) * 255.0).astype(np.uint8)
            proxy[patch_index] = crop.transpose(2, 0, 1)
            if row_index in preview_row_ids and patch_index == by_row[row_index][0]:
                preview_sheet(rgb[patch_index, 0], proxy[patch_index], rgb[patch_index, 1], preview_root / f"row{row_index:05d}_{row['sequence_id']}_f{row['frame_id']}_e{row['eye']}.jpg")
        records.append(
            {
                "row": row_index,
                "sequence_id": row["sequence_id"],
                "frame_id": int(row["frame_id"]),
                "eye": int(row["eye"]),
                "split": row["split"],
                "patches": len(by_row[row_index]),
                "network_seconds": float(result.timings.get("network", 0.0)),
                "wall_seconds": float(time.perf_counter() - call_started),
                "recovered_min": float(recovered.min()),
                "recovered_max": float(recovered.max()),
            }
        )
        if (row_index + 1) % 4 == 0 or row_index + 1 == len(rows):
            print(json.dumps({"event": "proxy_progress", "rows": row_index + 1, "total": len(rows), "seconds": time.perf_counter() - started}), flush=True)
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    proxy.flush()
    del proxy
    partial_path.replace(target_path)
    metadata = {
        "schema": "opennr-whitebox-proxy-targets-v1",
        "scope": "offline full-eye recovered-look targets; not native-teacher labels or runtime acceptance",
        "cache": str(cache),
        "base_cache_sha256": sha256_file(cache / "complete.json"),
        "rows_sha256": sha256_file(cache / "rows.json"),
        "patches_sha256": sha256_file(cache / "patches.json"),
        "target_path": str(target_path),
        "target_sha256": sha256_file(target_path),
        "target_shape": [len(plan), 3, 512, 512],
        "target_dtype": "uint8",
        "target_quantization": "round(clamp(recovered_rgb,0,1)*255); target is generated after full-eye inference and then cropped",
        "weights": str(weights),
        "weights_sha256": sha256_file(weights),
        "dll": str(dll),
        "dll_sha256": sha256_file(dll),
        "source_commit": args.source_commit,
        "device": str(pipeline.device),
        "precision": args.precision,
        "frame_index": args.frame_index,
        "controls": {
            "profile": "standard",
            "local_tone_strength": args.local_tone,
            "local_structure_strength": args.local_structure,
            "skin_structure_strength": args.skin_structure,
            "automatic_mask_structure_strength": args.mask_structure,
            "automatic_mask_enabled": bool(args.use_auto_mask),
            "intensity": args.intensity,
            "detail_strength": args.detail_strength,
            "colour_strength": args.colour_strength,
        },
        "rows": len(rows),
        "patches": len(plan),
        "records": records,
        "elapsed_seconds": float(time.perf_counter() - started),
        "native_teacher_retained_in_rgb_npy": True,
        "training_started": False,
        "promotion": False,
    }
    metadata_path.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"event": "proxy_complete", "target": str(target_path), "rows": len(rows), "patches": len(plan), "elapsed_seconds": metadata["elapsed_seconds"]}, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
