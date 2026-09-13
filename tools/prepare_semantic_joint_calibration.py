"""Prepare representative reset/steady inputs for a fixed semantic ONNX graph.

This is an isolated, read-only calibration-data builder. It reads preserved
full-resolution capture files, recreates the native guide/context tensors, runs
the frozen inference bundle to obtain causal state distributions, and writes a
CPU-side NPZ for a later quantization experiment. It never writes to training,
Skyrim, SteamVR, or Community Shaders paths.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import torch

from benchmark_semantic_joint_fullres_inputs import _artifact, _load_eye
from native_preprocess import NativePreprocessor
from semantic_joint_runtime import load_bundle, sha256_file


def _records(sequence: Path) -> list[dict]:
    path = sequence / "frames.jsonl"
    rows: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        try:
            for eye in (0, 1):
                _artifact(row, "input", eye)
                _artifact(row, "depth", eye)
                _artifact(row, "motion_vectors", eye)
        except ValueError:
            continue
        rows.append(row)
    return rows


def _select_records(sequence: Path, count: int) -> list[dict]:
    rows = _records(sequence)
    if not rows:
        return []
    if count <= 1 or len(rows) == 1:
        return [rows[0]]
    positions = np.linspace(0, len(rows) - 1, count, dtype=int).tolist()
    selected: list[dict] = []
    seen: set[int] = set()
    for position in positions:
        row = rows[position]
        frame_id = int(row.get("frame_id", position))
        if frame_id not in seen:
            selected.append(row)
            seen.add(frame_id)
    return selected


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--capture-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-sequences", type=int, default=6)
    parser.add_argument("--frames-per-sequence", type=int, default=2)
    args = parser.parse_args()
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is required for native preprocessing and state generation")
    if args.max_sequences < 1 or args.frames_per_sequence < 1:
        raise ValueError("sequence and frame limits must be positive")

    bundle_path = args.bundle.resolve()
    capture_root = args.capture_root.resolve()
    output_path = args.output.resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    preprocessor = NativePreprocessor(w=2496, h=2688, gw=1664, gh=1792)
    model, bundle = load_bundle(bundle_path, "cuda")
    model.eval()

    samples: dict[str, list[np.ndarray]] = {
        "rgb": [],
        "guides": [],
        "context": [],
        "hidden": [],
        "previous": [],
    }
    selected_manifest: list[dict] = []
    sequence_count = 0
    frame_count = 0

    sequence_paths = sorted(capture_root.glob("seq-*/"))
    with torch.inference_mode():
        for sequence in sequence_paths:
            if sequence_count >= args.max_sequences:
                break
            selected = _select_records(sequence, args.frames_per_sequence)
            if not selected:
                continue
            states: list[tuple[torch.Tensor, torch.Tensor] | None] = [None, None]
            sequence_manifest = {"sequence": str(sequence), "frames": []}
            for record in selected:
                frame_id = int(record.get("frame_id", -1))
                frame_manifest = {"frame": frame_id, "eyes": []}
                for eye in (0, 1):
                    rgb, guides, context, metadata = _load_eye(
                        sequence,
                        record,
                        eye,
                        preprocessor,
                        model_height=887,
                        model_width=824,
                    )
                    if states[eye] is None:
                        hidden, previous = model.parent.initial_state(rgb)
                    else:
                        hidden, previous = states[eye]

                    samples["rgb"].append(rgb.detach().float().cpu().numpy())
                    samples["guides"].append(guides.detach().float().cpu().numpy())
                    samples["context"].append(context.detach().float().cpu().numpy())
                    samples["hidden"].append(hidden.detach().float().cpu().numpy())
                    samples["previous"].append(previous.detach().float().cpu().numpy())

                    _, states[eye] = model.forward_temporal(
                        rgb,
                        guides,
                        context,
                        (hidden, previous),
                    )
                    frame_manifest["eyes"].append(
                        {
                            "eye": eye,
                            "rgb": metadata["input"],
                            "depth": metadata["depth"],
                            "motion_vectors": metadata["motion_vectors"],
                            "model_shape": metadata["model_shape"],
                        }
                    )
                sequence_manifest["frames"].append(frame_manifest)
                frame_count += 1
            selected_manifest.append(sequence_manifest)
            sequence_count += 1

    if not samples["rgb"]:
        raise RuntimeError("No complete full-frame capture records were found")

    arrays = {name: np.concatenate(values, axis=0).astype(np.float32, copy=False) for name, values in samples.items()}
    np.savez_compressed(output_path, **arrays)
    manifest = {
        "format": "opennr-semantic-joint-calibration-v1",
        "bundle": str(bundle_path),
        "bundle_sha256": sha256_file(bundle_path),
        "capture_root": str(capture_root),
        "output": str(output_path),
        "output_sha256": sha256_file(output_path),
        "samples": int(arrays["rgb"].shape[0]),
        "sequence_count": sequence_count,
        "frame_count": frame_count,
        "eye_samples": int(arrays["rgb"].shape[0]),
        "input_shapes": {name: list(value.shape) for name, value in arrays.items()},
        "state_policy": "first selected frame uses reset hidden/previous; later selected frames use the frozen eager model causal state per eye",
        "sequences": selected_manifest,
        "source_step": bundle["source_step"],
    }
    manifest_path = output_path.with_suffix(".json")
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, indent=2), flush=True)


if __name__ == "__main__":
    main()
