#!/usr/bin/env python3
"""Phase-0 parity gate for the isolated MLX-DLSS PyTorch rebuild.

This evaluator reads the immutable packed OpenNR crop cache. It never changes
native labels, the active runtime, or the student checkpoint. The cache stores
RGB as [row, input-or-teacher, channel, height, width].
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import time
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def metrics(actual: np.ndarray, target: np.ndarray) -> dict[str, float]:
    error = np.asarray(actual, dtype=np.float64) - np.asarray(target, dtype=np.float64)
    mae = float(np.abs(error).mean())
    rmse = float(np.sqrt(np.mean(error * error)))
    psnr = float("inf") if rmse == 0.0 else float(20.0 * math.log10(1.0 / rmse))
    return {
        "mae": mae,
        "rmse": rmse,
        "psnr_db": psnr,
        "max_abs": float(np.abs(error).max()),
    }


def to_image(value: np.ndarray, size: int = 256) -> Image.Image:
    value = np.clip(np.asarray(value, dtype=np.float32), 0.0, 1.0)
    image = Image.fromarray(np.rint(value * 255.0).astype(np.uint8), mode="RGB")
    return image.resize((size, size), Image.Resampling.BILINEAR)


def error_image(actual: np.ndarray, target: np.ndarray, size: int = 256) -> Image.Image:
    error = np.abs(np.asarray(actual, dtype=np.float32) - np.asarray(target, dtype=np.float32))
    error = np.clip(error * 8.0, 0.0, 1.0)
    return to_image(error, size)


def make_gallery(records: list[dict], destination: Path) -> None:
    cell = 256
    label_h = 24
    cols = 4
    rows = math.ceil(len(records) / cols)
    sheet = Image.new("RGB", (cols * cell, rows * (cell + label_h)), (24, 24, 24))
    draw = ImageDraw.Draw(sheet)
    for index, record in enumerate(records):
        x = (index % cols) * cell
        y = (index // cols) * (cell + label_h)
        tile = record["gallery_tiles"]
        sheet.paste(tile, (x, y))
        label = f"{record['sequence']} f{record['frame']:02d} e{record['eye']}"
        draw.text((x + 4, y + cell + 4), label, fill=(240, 240, 240))
    destination.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(destination)


def select_rows(rows: list[dict], split: str, sequence_limit: int, frame_ids: list[int]) -> list[tuple[int, dict]]:
    sequences = []
    seen: set[str] = set()
    for row in rows:
        if row.get("split") != split:
            continue
        sequence = str(row["sequence_id"])
        if sequence not in seen:
            sequences.append(sequence)
            seen.add(sequence)
    sequences = sequences[:sequence_limit]
    chosen: list[tuple[int, dict]] = []
    for index, row in enumerate(rows):
        if row.get("split") == split and row["sequence_id"] in sequences and int(row["frame_id"]) in frame_ids:
            chosen.append((index, row))
    return chosen


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--weights", type=Path, required=True)
    parser.add_argument("--dll", type=Path, required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--precision", choices=("reference", "fast"), default="fast")
    parser.add_argument("--split", default="validation")
    parser.add_argument("--sequence-limit", type=int, default=3)
    parser.add_argument("--frames", default="1,16,32,48,64")
    parser.add_argument("--local-tone", type=float, default=2.0)
    parser.add_argument("--local-structure", type=float, default=2.0)
    parser.add_argument("--skin-structure", type=float, default=-1.0)
    parser.add_argument("--mask-structure", type=float, default=2.0)
    parser.add_argument("--intensity", type=float, default=2.0)
    parser.add_argument("--detail-strength", type=float, default=2.0)
    parser.add_argument("--colour-strength", type=float, default=2.0)
    parser.add_argument("--no-auto-mask", action="store_true")
    args = parser.parse_args()

    if args.output.exists():
        raise FileExistsError(args.output)
    dataset = args.dataset.resolve()
    rows = json.loads((dataset / "rows.json").read_text(encoding="utf-8"))
    rgb = np.load(dataset / "rgb.npy", mmap_mode="r")
    frame_ids = [int(value) for value in args.frames.split(",") if value.strip()]
    selected = select_rows(rows, args.split, args.sequence_limit, frame_ids)
    if len(selected) < 20:
        raise ValueError(f"selected only {len(selected)} rows; require at least 20")

    # Import only after selecting/validating paths so a failed setup cannot
    # silently turn into an experiment on a different lineage.
    from mlxdlss import AutomaticMask, NeuralRenderingPipeline
    import torch

    if not torch.cuda.is_available() and str(args.device).startswith("cuda"):
        raise RuntimeError("CUDA was requested but torch.cuda.is_available() is false")
    pipeline = NeuralRenderingPipeline.from_safetensors(
        args.weights, device=args.device, precision=args.precision
    )
    pipeline.model.eval()
    if torch.cuda.is_available():
        torch.cuda.synchronize()
        torch.cuda.reset_peak_memory_stats()

    enhance_options = {
        "profile": "standard",
        "processing_scale": 1.0,
        "detail_strength": args.detail_strength,
        "colour_strength": args.colour_strength,
        "intensity": args.intensity,
        "local_tone_strength": args.local_tone,
        "local_structure_strength": args.local_structure,
    }
    if not args.no_auto_mask:
        enhance_options["automatic_mask"] = AutomaticMask(
            skin_structure_strength=args.skin_structure,
            automatic_mask_structure_strength=args.mask_structure,
        )

    records: list[dict] = []
    gallery_records: list[dict] = []
    determinism_max_abs: float | None = None
    started = time.perf_counter()
    with torch.no_grad():
        for row_index, row in selected:
            source = np.asarray(rgb[row_index, 0], dtype=np.float32).transpose(1, 2, 0) / 255.0
            target = np.asarray(rgb[row_index, 1], dtype=np.float32).transpose(1, 2, 0) / 255.0
            if torch.cuda.is_available():
                torch.cuda.synchronize()
            call_started = time.perf_counter()
            result = pipeline.enhance(
                source,
                frame_index=int(row["frame_id"]) - 1,
                **enhance_options,
            )
            if torch.cuda.is_available():
                torch.cuda.synchronize()
            recovered = np.asarray(result.image, dtype=np.float32)
            if recovered.shape != target.shape:
                raise ValueError(f"shape mismatch for {row['sequence_id']} {row['frame_id']} eye {row['eye']}")
            input_metrics = metrics(source, target)
            recovered_metrics = metrics(recovered, target)
            record = {
                "sequence": row["sequence_id"],
                "split": row["split"],
                "frame": int(row["frame_id"]),
                "eye": int(row["eye"]),
                "history_reset": row.get("history_reset"),
                "input_teacher": input_metrics,
                "recovered_teacher": recovered_metrics,
                "recovered_min": float(recovered.min()),
                "recovered_max": float(recovered.max()),
                "network_seconds": float(result.timings.get("network", 0.0)),
                "wall_seconds": float(time.perf_counter() - call_started),
            }
            records.append(record)
            if len(gallery_records) < 12:
                gallery_records.append(
                    {
                        **record,
                        "gallery_tiles": Image.fromarray(
                            np.concatenate(
                                [
                                    np.asarray(to_image(source)),
                                    np.asarray(to_image(target)),
                                    np.asarray(to_image(recovered)),
                                    np.asarray(error_image(recovered, target)),
                                ],
                                axis=1,
                            ),
                            mode="RGB",
                        ),
                    }
                )
            if determinism_max_abs is None:
                repeat = pipeline.enhance(
                    source,
                    frame_index=int(row["frame_id"]) - 1,
                    **enhance_options,
                )
                repeat_image = np.asarray(repeat.image, dtype=np.float32)
                determinism_max_abs = float(np.abs(recovered - repeat_image).max())

    if torch.cuda.is_available():
        peak_allocated = int(torch.cuda.max_memory_allocated())
        peak_reserved = int(torch.cuda.max_memory_reserved())
    else:
        peak_allocated = None
        peak_reserved = None

    def mean_metric(name: str, arm: str) -> float:
        return float(np.mean([item[arm][name] for item in records]))

    summary = {
        "schema": "opennr-mlx-dlss-phase0-cache-v1",
        "dataset": str(dataset),
        "dataset_rows_sha256": sha256(dataset / "rows.json"),
        "weights": str(args.weights.resolve()),
        "weights_sha256": sha256(args.weights),
        "dll": str(args.dll.resolve()),
        "dll_sha256": sha256(args.dll),
        "source_commit": args.source_commit,
        "device": str(pipeline.device),
        "precision": args.precision,
        "torch_version": torch.__version__,
        "cuda_version": torch.version.cuda,
        "gpu": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
        "controls": {
            "profile": "standard",
            "local_tone_strength": args.local_tone,
            "local_structure_strength": args.local_structure,
            "skin_structure_strength": args.skin_structure,
            "automatic_mask_structure_strength": args.mask_structure,
            "automatic_mask_enabled": not args.no_auto_mask,
            "intensity": args.intensity,
            "detail_strength": args.detail_strength,
            "colour_strength": args.colour_strength,
        },
        "split": args.split,
        "sequence_limit": args.sequence_limit,
        "frame_ids": frame_ids,
        "eye_rows": len(records),
        "elapsed_seconds": float(time.perf_counter() - started),
        "determinism_max_abs": determinism_max_abs,
        "peak_cuda_memory_allocated_bytes": peak_allocated,
        "peak_cuda_memory_reserved_bytes": peak_reserved,
        "mean_network_seconds": float(np.mean([item["network_seconds"] for item in records])),
        "mean_wall_seconds": float(np.mean([item["wall_seconds"] for item in records])),
        "input_teacher": {name: mean_metric(name, "input_teacher") for name in ("mae", "rmse", "psnr_db", "max_abs")},
        "recovered_teacher": {name: mean_metric(name, "recovered_teacher") for name in ("mae", "rmse", "psnr_db", "max_abs")},
        "records": records,
        "acceptance": {
            "cuda_load": str(pipeline.device).startswith("cuda"),
            "deterministic_repeat": bool(determinism_max_abs == 0.0),
            "native_labels_changed": False,
            "runtime_changed": False,
            "student_training_started": False,
            "promotion": False,
        },
    }
    args.output.mkdir(parents=True)
    (args.output / "phase0.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    make_gallery(gallery_records, args.output / "gallery" / "phase0_contact_sheet.png")
    print(json.dumps({
        "eye_rows": summary["eye_rows"],
        "input_teacher": summary["input_teacher"],
        "recovered_teacher": summary["recovered_teacher"],
        "determinism_max_abs": summary["determinism_max_abs"],
        "mean_network_seconds": summary["mean_network_seconds"],
        "peak_cuda_memory_allocated_bytes": summary["peak_cuda_memory_allocated_bytes"],
        "peak_cuda_memory_reserved_bytes": summary["peak_cuda_memory_reserved_bytes"],
        "weights_sha256": summary["weights_sha256"],
        "dll_sha256": summary["dll_sha256"],
    }, indent=2))


if __name__ == "__main__":
    main()
