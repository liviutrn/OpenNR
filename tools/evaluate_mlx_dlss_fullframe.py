#!/usr/bin/env python3
"""Replay the recovered white-box graph on one exact Skyrim full-frame capture.

This is an evaluation-only tool.  It reads a validated OpenNR master sequence,
uses the raw R8G8B8A8 input and native teacher bytes for both eyes, and never
changes the capture, weights, DLL, Skyrim profile, or runtime.  The recovered
graph is RGB/controls-only, so the captured depth and motion resources are
verified and fingerprinted as part of the contract but are not fabricated as
inputs to the graph.

The intended use is a first-frame rescue test: frame 1 must be complete and
history-reset for both eyes.  ``frame_index=0`` then matches the recovered
graph's first deterministic-noise frame.  This is not a temporal or live-VR
acceptance test.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import hashlib
import json
import math
from pathlib import Path
import platform
import time
from typing import Any

import numpy as np
from PIL import Image, ImageDraw


EXPECTED_COLOR_FORMAT = "R8G8B8A8_UNORM"
EXPECTED_GUIDE_FORMATS = {"R32_FLOAT", "R16G16_FLOAT"}
EXPECTED_CONTROLS = {
    "intensity": 2.0,
    "local_structure_strength": 2.0,
    "local_tone_strength": 2.0,
    "skin_structure_strength": -1.0,
    "style": 0,
    "ui_correction": False,
    "use_auto_mask": True,
}


@dataclass
class ArtifactEvidence:
    stage: str
    eye: int
    width: int
    height: int
    format_name: str
    row_pitch: int
    raw_path: str
    raw_sha256: str
    raw_bytes: int
    nonzero_fraction: float


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_path(sequence: Path, relative: str) -> Path:
    path = (sequence / relative).resolve()
    path.relative_to(sequence.resolve())
    if not path.is_file():
        raise FileNotFoundError(path)
    return path


def find_full_artifact(row: dict[str, Any], stage: str, eye: int) -> dict[str, Any]:
    matches = [
        item
        for item in row.get("artifacts", [])
        if item.get("stage") == stage
        and int(item.get("eye", -1)) == eye
        and bool(item.get("full_frame"))
    ]
    if len(matches) != 1:
        raise ValueError(
            f"expected one full-frame {stage!r} artifact for eye {eye}, found {len(matches)}"
        )
    artifact = matches[0]
    if not artifact.get("raw_written") or not artifact.get("raw_path"):
        raise ValueError(f"full-frame {stage!r} eye {eye} is not a written raw artifact")
    return artifact


def artifact_evidence(sequence: Path, artifact: dict[str, Any]) -> ArtifactEvidence:
    path = safe_path(sequence, str(artifact["raw_path"]))
    raw = path.read_bytes()
    expected = int(artifact["row_pitch"]) * int(artifact["height"])
    if len(raw) != expected:
        raise ValueError(f"{path}: {len(raw)} bytes, expected {expected}")
    return ArtifactEvidence(
        stage=str(artifact["stage"]),
        eye=int(artifact["eye"]),
        width=int(artifact["width"]),
        height=int(artifact["height"]),
        format_name=str(artifact["format_name"]),
        row_pitch=int(artifact["row_pitch"]),
        raw_path=str(artifact["raw_path"]),
        raw_sha256=hashlib.sha256(raw).hexdigest(),
        raw_bytes=len(raw),
        nonzero_fraction=float(np.count_nonzero(np.frombuffer(raw, dtype=np.uint8)) / max(1, len(raw))),
    )


def read_rgba_rgb(sequence: Path, artifact: dict[str, Any]) -> np.ndarray:
    if artifact.get("format_name") != EXPECTED_COLOR_FORMAT:
        raise ValueError(
            f"{artifact.get('stage')} eye {artifact.get('eye')}: expected "
            f"{EXPECTED_COLOR_FORMAT}, got {artifact.get('format_name')!r}"
        )
    width = int(artifact["width"])
    height = int(artifact["height"])
    row_pitch = int(artifact["row_pitch"])
    path = safe_path(sequence, str(artifact["raw_path"]))
    raw = path.read_bytes()
    expected = row_pitch * height
    if len(raw) != expected:
        raise ValueError(f"{path}: {len(raw)} bytes, expected {expected}")
    if row_pitch < width * 4:
        raise ValueError(f"{path}: row pitch {row_pitch} is smaller than RGBA row {width * 4}")
    rows = np.frombuffer(raw, dtype=np.uint8).reshape(height, row_pitch)
    rgba = rows[:, : width * 4].reshape(height, width, 4)
    return rgba[..., :3].astype(np.float32) / 255.0


def metrics(actual: np.ndarray, target: np.ndarray) -> dict[str, Any]:
    error = np.asarray(actual, dtype=np.float64) - np.asarray(target, dtype=np.float64)
    rmse = float(np.sqrt(np.mean(error * error)))
    channel_mae = np.abs(error).mean(axis=(0, 1)).tolist()
    return {
        "mae": float(np.abs(error).mean()),
        "rmse": rmse,
        "psnr_db": float("inf") if rmse == 0.0 else float(20.0 * math.log10(1.0 / rmse)),
        "max_abs": float(np.abs(error).max()),
        "channel_mae_rgb": [float(value) for value in channel_mae],
    }


def pil_rgb(image: np.ndarray) -> Image.Image:
    return Image.fromarray(
        np.rint(np.clip(np.asarray(image), 0.0, 1.0) * 255.0).astype(np.uint8),
        mode="RGB",
    )


def make_contact_sheet(
    panels: list[tuple[str, np.ndarray]], output: Path, panel_width: int = 640
) -> None:
    if not panels:
        raise ValueError("no panels")
    original_height, original_width = panels[0][1].shape[:2]
    panel_height = max(1, round(original_height * panel_width / original_width))
    label_height = 28
    canvas = Image.new("RGB", (panel_width * len(panels), panel_height + label_height), (24, 24, 24))
    draw = ImageDraw.Draw(canvas)
    for index, (label, array) in enumerate(panels):
        left = index * panel_width
        draw.text((left + 6, 6), label, fill=(240, 240, 240))
        image = pil_rgb(array).resize((panel_width, panel_height), Image.Resampling.BILINEAR)
        canvas.paste(image, (left, label_height))
    output.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output)


def read_row(sequence: Path, frame_id: int) -> dict[str, Any]:
    manifest = sequence / "frames.jsonl"
    if not manifest.is_file():
        raise FileNotFoundError(manifest)
    for line in manifest.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if int(row.get("frame_id", -1)) == frame_id:
            return row
    raise ValueError(f"frame_id={frame_id} not found in {manifest}")


def check_contract(sequence: Path, row: dict[str, Any]) -> dict[str, Any]:
    if row.get("status") != "complete":
        raise ValueError(f"frame {row.get('frame_id')} is not complete: {row.get('status')!r}")
    if row.get("route") != "feature18_stereo":
        raise ValueError(f"unexpected route: {row.get('route')!r}")
    if int(row.get("pass_count", -1)) != 1:
        raise ValueError(f"expected one Feature 18 pass, got {row.get('pass_count')!r}")
    if int(row.get("model_resolution_percent", -1)) != 100:
        raise ValueError(f"expected 100% model resolution, got {row.get('model_resolution_percent')!r}")
    if row.get("motion_vector_contract") != "exact_feature18_bound_resource":
        raise ValueError(f"unexpected motion contract: {row.get('motion_vector_contract')!r}")
    reset = row.get("history_reset")
    if reset != [True, True]:
        raise ValueError(f"first-frame rescue test requires [true,true] reset, got {reset!r}")

    settings = row.get("teacher_settings") or {}
    mismatches = {}
    for key, expected in EXPECTED_CONTROLS.items():
        actual = settings.get(key)
        if actual != expected:
            mismatches[key] = {"expected": expected, "actual": actual}
    if mismatches:
        raise ValueError(f"native teacher controls are not the expected exact contract: {mismatches}")

    evidence: dict[str, Any] = {}
    for eye in (0, 1):
        for stage in ("input", "teacher", "depth", "motion_vectors"):
            artifact = find_full_artifact(row, stage, eye)
            if stage in ("input", "teacher") and artifact.get("format_name") != EXPECTED_COLOR_FORMAT:
                raise ValueError(f"unexpected {stage} format: {artifact.get('format_name')!r}")
            if stage in ("depth", "motion_vectors") and artifact.get("format_name") not in EXPECTED_GUIDE_FORMATS:
                raise ValueError(f"unexpected {stage} format: {artifact.get('format_name')!r}")
            evidence[f"eye{eye}_{stage}"] = asdict(artifact_evidence(sequence, artifact))
    return {
        "sequence_json_sha256": sha256(sequence / "sequence.json"),
        "frames_jsonl_sha256": sha256(sequence / "frames.jsonl"),
        "frame_id": int(row["frame_id"]),
        "sample_index": int(row["sample_index"]),
        "host_frame": int(row["host_frame"]),
        "history_reset": reset,
        "route": row["route"],
        "pass_count": int(row["pass_count"]),
        "model_resolution_percent": int(row["model_resolution_percent"]),
        "color_resolution": [int(row["color_width"]), int(row["color_height"])],
        "guide_resolution": [int(row["guide_width"]), int(row["guide_height"])],
        "motion_vector_scale_x": row.get("motion_vector_scale_x"),
        "motion_vector_scale_y": row.get("motion_vector_scale_y"),
        "teacher_settings": settings,
        "artifacts": evidence,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sequence", type=Path, required=True, help="one OpenNR master-sequence directory")
    parser.add_argument("--frame-id", type=int, default=1)
    parser.add_argument("--weights", type=Path, required=True)
    parser.add_argument("--dll", type=Path, required=True, help="native DLL used for provenance only")
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--precision", choices=("reference", "fast"), default="reference")
    parser.add_argument("--local-tone", type=float, default=2.0)
    parser.add_argument("--local-structure", type=float, default=2.0)
    parser.add_argument("--skin-structure", type=float, default=-1.0)
    parser.add_argument("--mask-structure", type=float, default=2.0)
    parser.add_argument("--intensity", type=float, default=2.0)
    parser.add_argument("--detail-strength", type=float, default=2.0)
    parser.add_argument("--colour-strength", type=float, default=2.0)
    parser.add_argument("--frame-index", type=int, default=None)
    parser.add_argument(
        "--no-auto-mask",
        action="store_true",
        help="diagnostic only: do not synthesize the recovered graph's scalar automatic-mask controls",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    sequence = args.sequence.expanduser().resolve()
    weights = args.weights.expanduser().resolve()
    dll = args.dll.expanduser().resolve()
    output = args.output.expanduser().resolve()
    if not sequence.is_dir():
        raise FileNotFoundError(sequence)
    if not weights.is_file() or not dll.is_file():
        raise FileNotFoundError("weights and DLL must both be files")
    if output.exists():
        raise FileExistsError(f"refusing to overwrite existing output: {output}")

    row = read_row(sequence, args.frame_id)
    contract = check_contract(sequence, row)
    frame_index = args.frame_index if args.frame_index is not None else args.frame_id - 1
    if frame_index < 0:
        raise ValueError("frame index must be non-negative")

    # Import the external implementation only after all capture and path gates
    # have passed.  The caller supplies its isolated PYTHONPATH.
    from mlxdlss import AutomaticMask, NeuralRenderingPipeline
    import torch

    if str(args.device).startswith("cuda") and not torch.cuda.is_available():
        raise RuntimeError("CUDA was requested but torch.cuda.is_available() is false")

    output.mkdir(parents=True)
    pipeline = NeuralRenderingPipeline.from_safetensors(
        weights, device=args.device, precision=args.precision
    )
    pipeline.model.eval()

    if torch.cuda.is_available():
        torch.cuda.reset_peak_memory_stats()

    enhance_options: dict[str, Any] = {
        "profile": "standard",
        "processing_scale": 1.0,
        "detail_strength": args.detail_strength,
        "colour_strength": args.colour_strength,
        "intensity": args.intensity,
        "frame_index": frame_index,
        "local_tone_strength": args.local_tone,
        "local_structure_strength": args.local_structure,
    }
    if not args.no_auto_mask:
        enhance_options["automatic_mask"] = AutomaticMask(
            skin_structure_strength=args.skin_structure,
            automatic_mask_structure_strength=args.mask_structure,
        )

    records: list[dict[str, Any]] = []
    started = time.perf_counter()
    for eye in (0, 1):
        input_artifact = find_full_artifact(row, "input", eye)
        teacher_artifact = find_full_artifact(row, "teacher", eye)
        source = read_rgba_rgb(sequence, input_artifact)
        target = read_rgba_rgb(sequence, teacher_artifact)
        if source.shape != target.shape:
            raise ValueError(f"eye {eye}: input shape {source.shape} != teacher shape {target.shape}")

        call_started = time.perf_counter()
        result = pipeline.enhance(source, **enhance_options)
        recovered = np.asarray(result.image, dtype=np.float32)
        if recovered.shape != target.shape:
            raise ValueError(f"eye {eye}: recovered shape {recovered.shape} != target {target.shape}")
        eye_metrics = {
            "source_vs_native_teacher": metrics(source, target),
            "recovered_vs_native_teacher": metrics(recovered, target),
            "recovered_vs_source": metrics(recovered, source),
        }
        pil_rgb(source).save(output / f"eye{eye}_source.png")
        pil_rgb(target).save(output / f"eye{eye}_native_teacher.png")
        pil_rgb(recovered).save(output / f"eye{eye}_recovered_whitebox.png")
        make_contact_sheet(
            [
                ("Skyrim pre-NR input", source),
                ("native NVIDIA teacher", target),
                ("recovered white-box", recovered),
                ("absolute difference ×8", np.clip(np.abs(recovered - target) * 8.0, 0.0, 1.0)),
            ],
            output / f"eye{eye}_contact_sheet.png",
        )
        records.append(
            {
                "eye": eye,
                "shape_hwc": list(source.shape),
                "history_reset": row["history_reset"],
                "frame_index": frame_index,
                "metrics": eye_metrics,
                "network_seconds": float(result.timings.get("network", 0.0)),
                "wall_seconds": float(time.perf_counter() - call_started),
                "recovered_min": float(recovered.min()),
                "recovered_max": float(recovered.max()),
            }
        )
        if torch.cuda.is_available():
            torch.cuda.empty_cache()

    recovered_errors = [item["metrics"]["recovered_vs_native_teacher"]["mae"] for item in records]
    source_errors = [item["metrics"]["source_vs_native_teacher"]["mae"] for item in records]
    mean_recovered = float(np.mean(recovered_errors))
    mean_source = float(np.mean(source_errors))
    peak_allocated = int(torch.cuda.max_memory_allocated()) if torch.cuda.is_available() else None
    peak_reserved = int(torch.cuda.max_memory_reserved()) if torch.cuda.is_available() else None
    summary = {
        "schema": "opennr-mlx-dlss-fullframe-reproduction-v1",
        "scope": "one complete first-frame full-resolution stereo replay; not temporal, live-headset, runtime, or VR-budget acceptance",
        "sequence": str(sequence),
        "contract": contract,
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
        "platform": platform.platform(),
        "recovered_options": {
            "profile": "standard",
            "processing_scale": 1.0,
            "frame_index": frame_index,
            "local_tone_strength": args.local_tone,
            "local_structure_strength": args.local_structure,
            "skin_structure_strength": args.skin_structure,
            "automatic_mask_structure_strength": args.mask_structure,
            "automatic_mask_enabled": not args.no_auto_mask,
            "intensity": args.intensity,
            "detail_strength": args.detail_strength,
            "colour_strength": args.colour_strength,
        },
        "eye_records": records,
        "mean_source_vs_native_teacher_mae": mean_source,
        "mean_recovered_vs_native_teacher_mae": mean_recovered,
        "mean_recovered_minus_source_mae": mean_recovered - mean_source,
        "improvement_vs_source_mae": mean_source - mean_recovered,
        "peak_cuda_memory_allocated_bytes": peak_allocated,
        "peak_cuda_memory_reserved_bytes": peak_reserved,
        "elapsed_seconds": float(time.perf_counter() - started),
        "interpretation_helpers": {
            "upstream_style_mae_reference": 0.007,
            "upstream_reference_note": "The repository's 0.004-0.005 claim was measured on a private five-crop Metal benchmark; this one-frame Skyrim CUDA result is evidence, not a replacement for that benchmark.",
            "direct_reference_range_pass": bool(mean_recovered <= 0.007),
            "source_improved": bool(mean_recovered < mean_source),
            "native_labels_changed": False,
            "capture_changed": False,
            "runtime_changed": False,
            "weights_changed": False,
            "training_started": False,
            "promotion": False,
        },
    }
    (output / "fullframe_reproduction.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "sequence": sequence.name,
        "frame_id": args.frame_id,
        "history_reset": row["history_reset"],
        "color_resolution": contract["color_resolution"],
        "mean_source_vs_native_teacher_mae": mean_source,
        "mean_recovered_vs_native_teacher_mae": mean_recovered,
        "improvement_vs_source_mae": mean_source - mean_recovered,
        "direct_reference_range_pass": mean_recovered <= 0.007,
        "output": str(output),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
