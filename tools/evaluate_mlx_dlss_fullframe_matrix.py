#!/usr/bin/env python3
"""Run a bounded style/control matrix on one fixed Skyrim full-frame target.

The input and native teacher never change between arms.  This is a diagnostic
for control/style mapping around the recovered MLX-DLSS graph, not a training
run and not evidence that a non-native setting is the correct Skyrim setting.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import time
from typing import Any

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from evaluate_mlx_dlss_fullframe import (  # noqa: E402
    check_contract,
    find_full_artifact,
    make_contact_sheet,
    metrics,
    pil_rgb,
    read_rgba_rgb,
    read_row,
    sha256,
)


def arms() -> list[dict[str, Any]]:
    """Return a small predeclared matrix with one changed factor at a time where possible."""

    common = {
        "local_tone_strength": 1.0,
        "local_structure_strength": 1.0,
        "skin_structure_strength": -1.0,
        "automatic_mask_structure_strength": 1.0,
        "intensity": 1.0,
        "detail_strength": 1.0,
        "colour_strength": 1.0,
        "automatic_mask": False,
    }

    def arm(name: str, **updates: Any) -> dict[str, Any]:
        result = {"name": name, "style_index": 0, **common}
        result.update(updates)
        return result

    return [
        arm("default_1x_auto_off"),
        arm("natural_1x_auto_off", style_index=1),
        arm("cinematic_1x_auto_off", style_index=2),
        arm("default_intensity_050", intensity=0.5),
        arm("default_intensity_075", intensity=0.75),
        arm("default_1x_auto_on", automatic_mask=True),
        arm(
            "default_local_tone2_structure2",
            local_tone_strength=2.0,
            local_structure_strength=2.0,
        ),
        arm("default_detail2_colour2", detail_strength=2.0, colour_strength=2.0),
        arm(
            "default_detail050_colour050",
            detail_strength=0.5,
            colour_strength=0.5,
        ),
    ]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sequence", type=Path, required=True)
    parser.add_argument("--frame-id", type=int, default=1)
    parser.add_argument("--weights", type=Path, required=True)
    parser.add_argument("--dll", type=Path, required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--precision", choices=("reference", "fast"), default="reference")
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
    sources: dict[int, np.ndarray] = {}
    targets: dict[int, np.ndarray] = {}
    for eye in (0, 1):
        sources[eye] = read_rgba_rgb(sequence, find_full_artifact(row, "input", eye))
        targets[eye] = read_rgba_rgb(sequence, find_full_artifact(row, "teacher", eye))
        if sources[eye].shape != targets[eye].shape:
            raise ValueError(f"eye {eye}: source and target shapes differ")

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

    results: list[dict[str, Any]] = []
    started = time.perf_counter()
    for arm in arms():
        arm_dir = output / str(arm["name"])
        arm_dir.mkdir()
        style = float(arm["style_index"]) / 128.0
        options: dict[str, Any] = {
            "profile": "standard",
            "processing_scale": 1.0,
            "normalized_style": style,
            "frame_index": args.frame_id - 1,
            "local_tone_strength": float(arm["local_tone_strength"]),
            "local_structure_strength": float(arm["local_structure_strength"]),
            "intensity": float(arm["intensity"]),
            "detail_strength": float(arm["detail_strength"]),
            "colour_strength": float(arm["colour_strength"]),
        }
        if arm["automatic_mask"]:
            options["automatic_mask"] = AutomaticMask(
                skin_structure_strength=float(arm["skin_structure_strength"]),
                automatic_mask_structure_strength=float(
                    arm["automatic_mask_structure_strength"]
                ),
            )

        eye_records: list[dict[str, Any]] = []
        arm_started = time.perf_counter()
        for eye in (0, 1):
            call_started = time.perf_counter()
            result = pipeline.enhance(sources[eye], **options)
            recovered = np.asarray(result.image, dtype=np.float32)
            if recovered.shape != targets[eye].shape:
                raise ValueError(f"{arm['name']} eye {eye}: output shape mismatch")
            source_metrics = metrics(sources[eye], targets[eye])
            recovered_metrics = metrics(recovered, targets[eye])
            pil_rgb(recovered).save(arm_dir / f"eye{eye}_recovered.png")
            make_contact_sheet(
                [
                    ("Skyrim pre-NR input", sources[eye]),
                    ("native NVIDIA teacher", targets[eye]),
                    ("recovered white-box", recovered),
                    (
                        "absolute difference ×8",
                        np.clip(np.abs(recovered - targets[eye]) * 8.0, 0.0, 1.0),
                    ),
                ],
                arm_dir / f"eye{eye}_contact_sheet.png",
            )
            eye_records.append(
                {
                    "eye": eye,
                    "source_vs_teacher": source_metrics,
                    "recovered_vs_teacher": recovered_metrics,
                    "recovered_vs_source": metrics(recovered, sources[eye]),
                    "recovered_min": float(recovered.min()),
                    "recovered_max": float(recovered.max()),
                    "network_seconds": float(result.timings.get("network", 0.0)),
                    "wall_seconds": float(time.perf_counter() - call_started),
                }
            )
            if torch.cuda.is_available():
                torch.cuda.empty_cache()

        recovered_mae = float(
            np.mean([item["recovered_vs_teacher"]["mae"] for item in eye_records])
        )
        source_mae = float(
            np.mean([item["source_vs_teacher"]["mae"] for item in eye_records])
        )
        results.append(
            {
                "name": arm["name"],
                "settings": {
                    **arm,
                    "normalized_style": style,
                    "frame_index": args.frame_id - 1,
                },
                "eye_records": eye_records,
                "mean_source_vs_teacher_mae": source_mae,
                "mean_recovered_vs_teacher_mae": recovered_mae,
                "improvement_vs_source_mae": source_mae - recovered_mae,
                "elapsed_seconds": float(time.perf_counter() - arm_started),
            }
        )

    results.sort(key=lambda item: item["mean_recovered_vs_teacher_mae"])
    peak_allocated = int(torch.cuda.max_memory_allocated()) if torch.cuda.is_available() else None
    peak_reserved = int(torch.cuda.max_memory_reserved()) if torch.cuda.is_available() else None
    summary = {
        "schema": "opennr-mlx-dlss-fullframe-control-matrix-v1",
        "scope": "fixed one-frame full-resolution stereo diagnostic; styles/settings varied, input and native teacher fixed; not training, temporal, runtime, headset, or VR-budget acceptance",
        "sequence": str(sequence),
        "contract": contract,
        "weights": str(weights),
        "weights_sha256": sha256(weights),
        "dll": str(dll),
        "dll_sha256": sha256(dll),
        "source_commit": args.source_commit,
        "device": str(pipeline.device),
        "precision": args.precision,
        "gpu": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
        "arm_count": len(results),
        "eye_rows_per_arm": 2,
        "results_ranked_by_recovered_teacher_mae": results,
        "peak_cuda_memory_allocated_bytes": peak_allocated,
        "peak_cuda_memory_reserved_bytes": peak_reserved,
        "elapsed_seconds": float(time.perf_counter() - started),
        "interpretation": {
            "native_teacher_style_is_fixed": 0,
            "native_teacher_controls_are_fixed": row["teacher_settings"],
            "upstream_style_mae_reference": 0.007,
            "warning": "A nonzero style or alternate setting ranking best against the style-0 native target indicates a mapping/calibration clue, not permission to relabel the native target or call that style native-equivalent.",
            "training_started": False,
            "runtime_changed": False,
            "native_labels_changed": False,
            "capture_changed": False,
            "promotion": False,
        },
    }
    (output / "fullframe_control_matrix.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "sequence": sequence.name,
                "frame_id": args.frame_id,
                "arm_count": len(results),
                "best_arm": results[0]["name"],
                "best_mean_recovered_vs_teacher_mae": results[0][
                    "mean_recovered_vs_teacher_mae"
                ],
                "best_improvement_vs_source_mae": results[0][
                    "improvement_vs_source_mae"
                ],
                "ranked": [
                    {
                        "name": item["name"],
                        "mae": item["mean_recovered_vs_teacher_mae"],
                        "improvement_vs_source": item["improvement_vs_source_mae"],
                    }
                    for item in results
                ],
                "output": str(output),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
