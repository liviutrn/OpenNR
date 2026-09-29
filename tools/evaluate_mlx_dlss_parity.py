"""Compare an isolated MLX-DLSS recovered graph with native Feature 18 captures.

This tool is deliberately an evaluation-only bridge. It never rewrites capture
files, never relabels native teacher targets, and records the source DLL/model
hashes plus the exact control settings. A recovered graph from an unknown DLL
build is reported as a separate lineage and cannot satisfy OpenNR promotion.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import time

import numpy as np


FORMAT_CHANNELS = {
    "R8G8B8A8_UNORM": 4,
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _artifact(row: dict, stage: str, eye: int) -> dict:
    matches = [
        item
        for item in row["artifacts"]
        if item.get("stage") == stage and int(item.get("eye", -1)) == eye
    ]
    if len(matches) != 1:
        raise ValueError(
            f"expected one {stage!r} eye {eye} artifact, found {len(matches)}"
        )
    return matches[0]


def _read_rgba_rgb(sequence: Path, artifact: dict) -> np.ndarray:
    if artifact.get("format_name") != "R8G8B8A8_UNORM":
        raise ValueError(
            f"expected R8G8B8A8_UNORM, got {artifact.get('format_name')!r}"
        )
    width = int(artifact["width"])
    height = int(artifact["height"])
    row_pitch = int(artifact["row_pitch"])
    channels = FORMAT_CHANNELS[artifact["format_name"]]
    expected = row_pitch * height
    path = sequence / artifact["raw_path"]
    raw = path.read_bytes()
    if len(raw) != expected:
        raise ValueError(f"raw byte size mismatch for {path}: {len(raw)} != {expected}")
    values = np.frombuffer(raw, dtype=np.uint8).reshape(height, row_pitch)
    values = values[:, : width * channels].reshape(height, width, channels)
    return values[..., :3].astype(np.float32) / 255.0


def _load_rows(sequence: Path, frame_limit: int) -> list[tuple[int, dict]]:
    rows = []
    with (sequence / "frames.jsonl").open(encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            if row.get("status") != "complete":
                raise ValueError(f"incomplete row in {sequence}: {row.get('frame_id')}")
            rows.append((int(row["frame_id"]), row))
    rows.sort(key=lambda item: item[0])
    if len(rows) != 64 or [frame for frame, _ in rows] != list(range(1, 65)):
        raise ValueError(f"sequence is not a strict 64-frame stream: {sequence}")
    return rows[:frame_limit]


def _sequence_dirs(root: Path, requested: list[str] | None) -> list[Path]:
    if requested:
        result = [root / name for name in requested]
    else:
        result = sorted(root.glob("seq-*"))
    result = [path for path in result if path.is_dir()]
    if not result:
        raise ValueError("no sequence directories selected")
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--weights", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--dll", type=Path, required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--sequence", action="append", dest="sequences")
    parser.add_argument("--frames", type=int, default=8)
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--precision", choices=("reference", "fast"), default="fast")
    parser.add_argument("--local-tone", type=float, default=2.0)
    parser.add_argument("--local-structure", type=float, default=2.0)
    parser.add_argument("--skin-structure", type=float, default=-1.0)
    parser.add_argument("--mask-structure", type=float, default=2.0)
    parser.add_argument(
        "--no-auto-mask",
        action="store_true",
        help="Do not synthesize the recovered graph's scalar automatic-mask controls.",
    )
    parser.add_argument("--detail-strength", type=float, default=2.0)
    parser.add_argument("--colour-strength", type=float, default=2.0)
    parser.add_argument("--intensity", type=float, default=1.0)
    args = parser.parse_args()

    if not 1 <= args.frames <= 64:
        parser.error("--frames must be between 1 and 64")
    if args.output.exists():
        raise FileExistsError(args.output)
    if not args.root.is_dir():
        raise FileNotFoundError(args.root)
    if not args.weights.is_file() or not args.dll.is_file():
        raise FileNotFoundError("weights and DLL must both be files")

    # Import the external package only after argument/path validation. The
    # caller supplies its isolated PYTHONPATH; this repo does not vendor it.
    from mlxdlss import AutomaticMask, NeuralRenderingPipeline

    args.output.mkdir(parents=True)
    pipeline = NeuralRenderingPipeline.from_safetensors(
        args.weights, device=args.device, precision=args.precision
    )
    sequences = _sequence_dirs(args.root, args.sequences)
    records: list[dict] = []
    started = time.perf_counter()
    for sequence in sequences:
        rows = _load_rows(sequence, args.frames)
        for frame_id, row in rows:
            for eye in (0, 1):
                source = _read_rgba_rgb(sequence, _artifact(row, "input", eye))
                target = _read_rgba_rgb(sequence, _artifact(row, "teacher", eye))
                enhance_args = {
                    "profile": "standard",
                    "processing_scale": 1.0,
                    "detail_strength": args.detail_strength,
                    "colour_strength": args.colour_strength,
                    "intensity": args.intensity,
                    "frame_index": frame_id - 1,
                    "local_tone_strength": args.local_tone,
                    "local_structure_strength": args.local_structure,
                }
                if not args.no_auto_mask:
                    enhance_args["automatic_mask"] = AutomaticMask(
                        skin_structure_strength=args.skin_structure,
                        automatic_mask_structure_strength=args.mask_structure,
                    )
                result = pipeline.enhance(source, **enhance_args)
                recovered = np.asarray(result.image, dtype=np.float32)
                if recovered.shape != target.shape:
                    raise ValueError(
                        f"shape mismatch for {sequence.name} frame {frame_id} eye {eye}: "
                        f"{recovered.shape} != {target.shape}"
                    )
                records.append(
                    {
                        "sequence": sequence.name,
                        "frame": frame_id,
                        "eye": eye,
                        "history_reset": row["history_reset"],
                        "input_teacher_mae": float(np.abs(source - target).mean()),
                        "recovered_teacher_mae": float(np.abs(recovered - target).mean()),
                        "recovered_min": float(recovered.min()),
                        "recovered_max": float(recovered.max()),
                        "network_seconds": float(result.timings.get("network", 0.0)),
                    }
                )

    input_errors = np.asarray([item["input_teacher_mae"] for item in records])
    recovered_errors = np.asarray(
        [item["recovered_teacher_mae"] for item in records]
    )
    summary = {
        "schema": "opennr-mlx-dlss-parity-v1",
        "root": str(args.root.resolve()),
        "weights": str(args.weights.resolve()),
        "weights_sha256": sha256(args.weights),
        "dll": str(args.dll.resolve()),
        "dll_sha256": sha256(args.dll),
        "source_commit": args.source_commit,
        "device": str(pipeline.device),
        "precision": args.precision,
        "controls": {
            "profile": "standard",
            "local_tone_strength": args.local_tone,
            "local_structure_strength": args.local_structure,
            "skin_structure_strength": args.skin_structure,
            "automatic_mask_structure_strength": args.mask_structure,
            "automatic_mask_enabled": not args.no_auto_mask,
            "detail_strength": args.detail_strength,
            "colour_strength": args.colour_strength,
            "intensity": args.intensity,
        },
        "sequence_count": len(sequences),
        "frames_per_sequence": args.frames,
        "eye_rows": len(records),
        "elapsed_seconds": time.perf_counter() - started,
        "input_teacher_mae": float(input_errors.mean()),
        "recovered_teacher_mae": float(recovered_errors.mean()),
        "improvement_vs_input": float(input_errors.mean() - recovered_errors.mean()),
        "records": records,
        "acceptance": {
            "native_teacher_replaced": False,
            "student_training_labels_changed": False,
            "runtime_changed": False,
            "unknown_dll_build": True,
            "promotion": False,
        },
    }
    (args.output / "parity.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({key: summary[key] for key in (
        "sequence_count", "frames_per_sequence", "eye_rows", "input_teacher_mae",
        "recovered_teacher_mae", "improvement_vs_input", "weights_sha256", "dll_sha256",
    )}, indent=2))


if __name__ == "__main__":
    main()
