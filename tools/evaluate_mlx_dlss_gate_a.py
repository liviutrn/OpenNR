#!/usr/bin/env python3
"""Evaluate the recovered MLX-DLSS graph against immutable OpenNR labels.

This is an isolated Phase-2/Gate-A evaluator.  It deliberately does not load
or alter the OpenNR student, native DLL, capture labels, or active runtime.
The cache stores RGB as [row, input-or-teacher, channel, height, width].

Unlike the earlier smoke evaluator, this tool reports the direct recovered
versus native-teacher error (B-A), a training-only SqueezeNet feature distance,
and small stereo/sparse-frame diagnostics.  The latter are diagnostic only;
they are not claims of live temporal or headset acceptance.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
import hashlib
import json
import math
from pathlib import Path
import time

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
    return {
        "mae": mae,
        "rmse": rmse,
        "psnr_db": float("inf") if rmse == 0.0 else float(20.0 * math.log10(1.0 / rmse)),
        "max_abs": float(np.abs(error).max()),
    }


def to_image(value: np.ndarray, size: int = 256) -> Image.Image:
    value = np.clip(np.asarray(value, dtype=np.float32), 0.0, 1.0)
    image = Image.fromarray(np.rint(value * 255.0).astype(np.uint8), mode="RGB")
    return image.resize((size, size), Image.Resampling.BILINEAR)


def error_image(actual: np.ndarray, target: np.ndarray, size: int = 256) -> Image.Image:
    return to_image(
        np.clip(np.abs(np.asarray(actual) - np.asarray(target)) * 8.0, 0.0, 1.0),
        size,
    )


def gallery_tile(
    source: np.ndarray, target: np.ndarray, recovered: np.ndarray, size: int = 256
) -> Image.Image:
    labels = ("source", "native NVIDIA", "recovered white-box", "abs diff ×8")
    images = (
        to_image(source, size),
        to_image(target, size),
        to_image(recovered, size),
        error_image(recovered, target, size),
    )
    header_h = 24
    tile = Image.new("RGB", (len(images) * size, header_h + size), (24, 24, 24))
    draw = ImageDraw.Draw(tile)
    for index, (label, image) in enumerate(zip(labels, images)):
        x = index * size
        draw.text((x + 4, 4), label, fill=(240, 240, 240))
        tile.paste(image, (x, header_h))
    return tile


def make_gallery(records: list[dict], destination: Path) -> None:
    label_h = 24
    tile_w = records[0]["gallery_tile"].width
    tile_h = records[0]["gallery_tile"].height
    cols = 2
    rows = math.ceil(len(records) / cols)
    sheet = Image.new(
        "RGB", (cols * tile_w, rows * (tile_h + label_h)), (24, 24, 24)
    )
    draw = ImageDraw.Draw(sheet)
    for index, record in enumerate(records):
        x = (index % cols) * tile_w
        y = (index // cols) * (tile_h + label_h)
        sheet.paste(record["gallery_tile"], (x, y))
        draw.text(
            (x + 4, y + tile_h + 4),
            f"{record['sequence']} f{record['frame']:02d} e{record['eye']}",
            fill=(240, 240, 240),
        )
    destination.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(destination)


def select_rows(
    rows: list[dict], split: str, sequence_limit: int, frame_ids: list[int]
) -> list[tuple[int, dict]]:
    sequences: list[str] = []
    seen: set[str] = set()
    for row in rows:
        if row.get("split") != split:
            continue
        sequence = str(row["sequence_id"])
        if sequence not in seen:
            sequences.append(sequence)
            seen.add(sequence)
    sequences = sequences[:sequence_limit]
    return [
        (index, row)
        for index, row in enumerate(rows)
        if row.get("split") == split
        and row["sequence_id"] in sequences
        and int(row["frame_id"]) in frame_ids
    ]


def mean_metric(records: list[dict], field: str, name: str) -> float:
    return float(np.mean([record[field][name] for record in records]))


def paired_diagnostics(records: list[dict]) -> dict[str, object]:
    """Return stereo and sparse frame diagnostics without implying temporal parity."""

    by_pair: dict[tuple[str, int], dict[int, dict]] = defaultdict(dict)
    for record in records:
        by_pair[(record["sequence"], record["frame"])][record["eye"]] = record
    stereo = []
    for (sequence, frame), eyes in sorted(by_pair.items()):
        if 0 not in eyes or 1 not in eyes:
            continue
        left, right = eyes[0], eyes[1]
        stereo.append(
            {
                "sequence": sequence,
                "frame": frame,
                "source_left_right_mae": metrics(left["source"], right["source"])["mae"],
                "teacher_left_right_mae": metrics(left["target"], right["target"])["mae"],
                "recovered_left_right_mae": metrics(
                    left["recovered"], right["recovered"]
                )["mae"],
            }
        )

    by_eye: dict[tuple[str, int], list[dict]] = defaultdict(list)
    for record in records:
        by_eye[(record["sequence"], record["eye"])].append(record)
    sparse_temporal = []
    for (sequence, eye), values in sorted(by_eye.items()):
        values.sort(key=lambda value: value["frame"])
        for previous, current in zip(values, values[1:]):
            sparse_temporal.append(
                {
                    "sequence": sequence,
                    "eye": eye,
                    "from_frame": previous["frame"],
                    "to_frame": current["frame"],
                    "source_delta_mae": metrics(
                        current["source"], previous["source"]
                    )["mae"],
                    "teacher_delta_mae": metrics(
                        current["target"], previous["target"]
                    )["mae"],
                    "recovered_delta_mae": metrics(
                        current["recovered"], previous["recovered"]
                    )["mae"],
                }
            )

    def mean(values: list[dict], key: str) -> float | None:
        return float(np.mean([item[key] for item in values])) if values else None

    return {
        "stereo_pairs": len(stereo),
        "stereo_mean": {
            key: mean(stereo, key)
            for key in (
                "source_left_right_mae",
                "teacher_left_right_mae",
                "recovered_left_right_mae",
            )
        },
        "stereo_records": stereo,
        "sparse_frame_transitions": len(sparse_temporal),
        "sparse_frame_transition_mean": {
            key: mean(sparse_temporal, key)
            for key in (
                "source_delta_mae",
                "teacher_delta_mae",
                "recovered_delta_mae",
            )
        },
        "sparse_frame_transition_records": sparse_temporal,
        "scope": (
            "Static crop diagnostics over selected frame IDs. These are not a "
            "strict contiguous temporal run, recurrent-state result, live stereo "
            "result, headset result, or VR-budget result."
        ),
    }


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
    parser.add_argument("--sequence-limit", type=int, default=6)
    parser.add_argument("--frames", default="1,16,32,48,64")
    parser.add_argument("--local-tone", type=float, default=2.0)
    parser.add_argument("--local-structure", type=float, default=2.0)
    parser.add_argument("--skin-structure", type=float, default=-1.0)
    parser.add_argument("--mask-structure", type=float, default=2.0)
    parser.add_argument("--intensity", type=float, default=2.0)
    parser.add_argument("--detail-strength", type=float, default=2.0)
    parser.add_argument("--colour-strength", type=float, default=2.0)
    parser.add_argument("--no-auto-mask", action="store_true")
    parser.add_argument(
        "--feature-distance",
        action="store_true",
        help="also run the cached training-only SqueezeNet feature distance",
    )
    args = parser.parse_args()

    if args.output.exists():
        raise FileExistsError(args.output)
    dataset = args.dataset.resolve()
    weights = args.weights.resolve()
    dll = args.dll.resolve()
    rows = json.loads((dataset / "rows.json").read_text(encoding="utf-8"))
    rgb = np.load(dataset / "rgb.npy", mmap_mode="r")
    frame_ids = [int(value) for value in args.frames.split(",") if value.strip()]
    selected = select_rows(rows, args.split, args.sequence_limit, frame_ids)
    if len(selected) < 20:
        raise ValueError(f"selected only {len(selected)} rows; require at least 20")

    # Import only after paths and row selection are validated.
    from mlxdlss import AutomaticMask, NeuralRenderingPipeline
    import torch

    if not torch.cuda.is_available() and str(args.device).startswith("cuda"):
        raise RuntimeError("CUDA was requested but torch.cuda.is_available() is false")
    pipeline = NeuralRenderingPipeline.from_safetensors(
        weights, device=args.device, precision=args.precision
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
                source, frame_index=int(row["frame_id"]) - 1, **enhance_options
            )
            if torch.cuda.is_available():
                torch.cuda.synchronize()
            recovered = np.asarray(result.image, dtype=np.float32)
            if recovered.shape != target.shape:
                raise ValueError(
                    f"shape mismatch for {row['sequence_id']} {row['frame_id']} eye {row['eye']}"
                )
            record = {
                "sequence": row["sequence_id"],
                "split": row["split"],
                "frame": int(row["frame_id"]),
                "eye": int(row["eye"]),
                "history_reset": row.get("history_reset"),
                "source": source,
                "target": target,
                "recovered": recovered,
                "source_vs_teacher": metrics(source, target),
                "recovered_vs_teacher": metrics(recovered, target),
                "recovered_vs_source": metrics(recovered, source),
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
                        "gallery_tile": gallery_tile(source, target, recovered),
                    }
                )
            if determinism_max_abs is None:
                repeat = pipeline.enhance(
                    source, frame_index=int(row["frame_id"]) - 1, **enhance_options
                )
                repeat_image = np.asarray(repeat.image, dtype=np.float32)
                determinism_max_abs = float(np.abs(recovered - repeat_image).max())

    feature_summary = None
    if args.feature_distance:
        feature_distance = __import__("perceptual_features").FeatureDistance().to(args.device).eval()
        values = []
        with torch.no_grad():
            # FeatureDistance reduces over its batch.  Use one crop per call so
            # the saved record remains a true per-crop diagnostic rather than a
            # repeated batch mean.
            for start in range(len(records)):
                batch = records[start : start + 1]
                predicted = torch.from_numpy(
                    np.stack([item["recovered"].transpose(2, 0, 1) for item in batch])
                ).to(args.device)
                expected = torch.from_numpy(
                    np.stack([item["target"].transpose(2, 0, 1) for item in batch])
                ).to(args.device)
                values.append(float(feature_distance(predicted, expected).detach().cpu().item()))
        for record, value in zip(records, values):
            record["squeezenet_feature_distance"] = float(value)
        feature_summary = {
            "name": "SqueezeNet1_1 ImageNet normalized feature distance",
            "scope": "training-only diagnostic; not LPIPS and not a VR acceptance metric",
            "mean": float(np.mean(values)),
            "median": float(np.median(values)),
            "max": float(np.max(values)),
        }

    peak_allocated = int(torch.cuda.max_memory_allocated()) if torch.cuda.is_available() else None
    peak_reserved = int(torch.cuda.max_memory_reserved()) if torch.cuda.is_available() else None
    input_mean = {name: mean_metric(records, "source_vs_teacher", name) for name in ("mae", "rmse", "psnr_db", "max_abs")}
    recovered_mean = {
        name: mean_metric(records, "recovered_vs_teacher", name)
        for name in ("mae", "rmse", "psnr_db", "max_abs")
    }
    summary = {
        "schema": "opennr-mlx-dlss-gate-a-v1",
        "dataset": str(dataset),
        "dataset_rows_sha256": sha256(dataset / "rows.json"),
        "weights": str(weights),
        "weights_sha256": sha256(weights),
        "dll": str(dll),
        "dll_sha256": sha256(dll),
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
        "selected_sequences": sorted({record["sequence"] for record in records}),
        "frame_ids": frame_ids,
        "eye_rows": len(records),
        "elapsed_seconds": float(time.perf_counter() - started),
        "determinism_max_abs": determinism_max_abs,
        "peak_cuda_memory_allocated_bytes": peak_allocated,
        "peak_cuda_memory_reserved_bytes": peak_reserved,
        "mean_network_seconds": float(np.mean([item["network_seconds"] for item in records])),
        "mean_wall_seconds": float(np.mean([item["wall_seconds"] for item in records])),
        "source_vs_teacher": input_mean,
        "recovered_vs_teacher": recovered_mean,
        "recovered_minus_source_mae": recovered_mean["mae"] - input_mean["mae"],
        "squeezenet_feature_distance": feature_summary,
        "paired_diagnostics": paired_diagnostics(records),
        "records": [
            {
                key: value
                for key, value in record.items()
                if key not in {"source", "target", "recovered"}
            }
            for record in records
        ],
        "acceptance": {
            "cuda_load": str(pipeline.device).startswith("cuda"),
            "deterministic_repeat": bool(determinism_max_abs == 0.0),
            "direct_gate_a_target_mae_max": 0.007,
            "direct_gate_a_pass": bool(recovered_mean["mae"] <= 0.007),
            "native_labels_changed": False,
            "runtime_changed": False,
            "student_training_started": False,
            "promotion": False,
        },
    }
    args.output.mkdir(parents=True)
    (args.output / "gate_a.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    make_gallery(gallery_records, args.output / "gallery" / "gate_a_contact_sheet.png")
    print(
        json.dumps(
            {
                "eye_rows": summary["eye_rows"],
                "source_vs_teacher": summary["source_vs_teacher"],
                "recovered_vs_teacher": summary["recovered_vs_teacher"],
                "recovered_minus_source_mae": summary["recovered_minus_source_mae"],
                "squeezenet_feature_distance": summary["squeezenet_feature_distance"],
                "determinism_max_abs": summary["determinism_max_abs"],
                "mean_network_seconds": summary["mean_network_seconds"],
                "peak_cuda_memory_allocated_bytes": summary["peak_cuda_memory_allocated_bytes"],
                "gate_a_pass": summary["acceptance"]["direct_gate_a_pass"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
