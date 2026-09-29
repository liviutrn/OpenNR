"""Fit a multi-sequence affine residual resolve and test it sequence-disjoint."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np

from fit_affine_scale_resolve_20260912 import flat_arrays


FULL_WIDTH = 2496
FULL_HEIGHT = 2688


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _spec(replay_root: Path, train_fraction: float) -> dict[str, Any]:
    replay_root = replay_root.resolve()
    manifest_path = replay_root / "input_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    frames = [int(value) for value in manifest["frames"]]
    train_count = max(1, min(len(frames) - 1, int(len(frames) * train_fraction)))
    return {
        "replay_root": replay_root,
        "manifest_path": manifest_path,
        "manifest_sha256": _sha256(manifest_path),
        "sequence": Path(manifest["sequence"]).resolve(),
        "frames": frames,
        "train_frames": frames[:train_count],
        "heldout_frames": frames[train_count:],
        "work_dimensions": [int(value) for value in manifest["network_dimensions"]],
        "scale_percent": int(manifest["scale_percent"]),
    }


def _accumulate(
    normal: np.ndarray,
    cross: np.ndarray,
    source: np.ndarray,
    teacher: np.ndarray,
    edit: np.ndarray,
    chunk_pixels: int,
) -> None:
    for start in range(0, source.shape[0], chunk_pixels):
        stop = min(start + chunk_pixels, source.shape[0])
        rgb = source[start:stop]
        features = np.empty((stop - start, 7), dtype=np.float64)
        features[:, 0] = 1.0
        features[:, 1:4] = rgb
        features[:, 4:7] = edit[start:stop]
        normal += features.T @ features
        cross += features.T @ (teacher[start:stop] - rgb)


def fit_coefficients(specs: list[dict[str, Any]], chunk_rows: int) -> np.ndarray:
    normal = np.zeros((7, 7), dtype=np.float64)
    cross = np.zeros((7, 3), dtype=np.float64)
    chunk_pixels = chunk_rows * FULL_WIDTH
    for spec in specs:
        small_width, small_height = spec["work_dimensions"]
        for frame_id in spec["train_frames"]:
            for eye in (0, 1):
                source, teacher, edit = flat_arrays(
                    spec["replay_root"],
                    spec["sequence"],
                    frame_id,
                    eye,
                    small_width,
                    small_height,
                )
                _accumulate(normal, cross, source, teacher, edit, chunk_pixels)
    return np.linalg.solve(normal + 1e-8 * np.eye(7), cross)


def _metrics(
    prediction: np.ndarray,
    teacher: np.ndarray,
    source: np.ndarray,
) -> dict[str, float]:
    error = prediction - teacher
    identity_error = source - teacher
    mae = float(np.abs(error).mean())
    rmse = float(np.sqrt(np.mean(error * error)))
    identity_mae = float(np.abs(identity_error).mean())
    return {
        "mae": mae,
        "rmse": rmse,
        "identity_mae": identity_mae,
        "improvement_vs_identity_mae": identity_mae - mae,
        "psnr_db": float(20.0 * np.log10(1.0 / max(rmse, 1e-12))),
        "better_fraction_pixels": float(
            np.mean(np.abs(error) < np.abs(identity_error))
        ),
    }


def evaluate_spec(
    spec: dict[str, Any],
    frames: list[int],
    beta: np.ndarray,
) -> dict[str, Any]:
    small_width, small_height = spec["work_dimensions"]
    records: list[dict[str, Any]] = []
    for frame_id in frames:
        for eye in (0, 1):
            source, teacher, edit = flat_arrays(
                spec["replay_root"],
                spec["sequence"],
                frame_id,
                eye,
                small_width,
                small_height,
            )
            features = np.empty((source.shape[0], 7), dtype=np.float64)
            features[:, 0] = 1.0
            features[:, 1:4] = source
            features[:, 4:7] = edit
            affine = np.clip(source + features @ beta, 0.0, 1.0)
            naive = np.clip(source + edit, 0.0, 1.0)
            records.append(
                {
                    "frame_id": frame_id,
                    "eye": eye,
                    "naive": _metrics(naive, teacher, source),
                    "affine": _metrics(affine, teacher, source),
                }
            )
    naive_mae = np.asarray([record["naive"]["mae"] for record in records])
    affine_mae = np.asarray([record["affine"]["mae"] for record in records])
    return {
        "sequence": str(spec["sequence"]),
        "replay_root": str(spec["replay_root"]),
        "frames": frames,
        "sample_count": len(records),
        "records": records,
        "naive_mae_mean": float(naive_mae.mean()),
        "affine_mae_mean": float(affine_mae.mean()),
        "affine_improvement_vs_naive_mae": float(naive_mae.mean() - affine_mae.mean()),
        "affine_better_than_naive_samples": int(np.sum(affine_mae < naive_mae)),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--train-replay-root", type=Path, action="append", required=True)
    parser.add_argument("--test-replay-root", type=Path, action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--train-fraction", type=float, default=0.75)
    parser.add_argument("--chunk-rows", type=int, default=256)
    args = parser.parse_args()

    if len(args.train_replay_root) < 2:
        raise ValueError("pass at least two training replays")
    if not 0.0 < args.train_fraction < 1.0 or args.chunk_rows < 1:
        raise ValueError("invalid train fraction or chunk size")
    if args.output.exists():
        raise FileExistsError(f"refusing to overwrite {args.output}")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    train_specs = [_spec(root, args.train_fraction) for root in args.train_replay_root]
    test_specs = [_spec(root, args.train_fraction) for root in args.test_replay_root]
    dimensions = {tuple(spec["work_dimensions"]) for spec in [*train_specs, *test_specs]}
    if len(dimensions) != 1:
        raise ValueError(f"all replays must have one work shape: {dimensions}")

    beta = fit_coefficients(train_specs, args.chunk_rows)
    training = [
        evaluate_spec(spec, spec["train_frames"], beta) for spec in train_specs
    ]
    heldout = [
        evaluate_spec(spec, spec["heldout_frames"], beta) for spec in train_specs
    ]
    test = [evaluate_spec(spec, spec["frames"], beta) for spec in test_specs]

    def aggregate(rows: list[dict[str, Any]]) -> dict[str, Any]:
        sample_count = sum(int(row["sample_count"]) for row in rows)
        return {
            "sequence_count": len(rows),
            "sample_count": sample_count,
            "naive_mae_mean": float(
                np.average([row["naive_mae_mean"] for row in rows], weights=[row["sample_count"] for row in rows])
            ),
            "affine_mae_mean": float(
                np.average([row["affine_mae_mean"] for row in rows], weights=[row["sample_count"] for row in rows])
            ),
            "affine_better_than_naive_samples": int(
                sum(row["affine_better_than_naive_samples"] for row in rows)
            ),
        }

    result = {
        "schema": "opennr-affine-scale-resolve-multiseq-v1",
        "train_replays": [
            {
                "replay_root": str(spec["replay_root"]),
                "manifest_sha256": spec["manifest_sha256"],
                "sequence": str(spec["sequence"]),
                "train_frames": spec["train_frames"],
                "heldout_frames": spec["heldout_frames"],
            }
            for spec in train_specs
        ],
        "test_replays": [
            {
                "replay_root": str(spec["replay_root"]),
                "manifest_sha256": spec["manifest_sha256"],
                "sequence": str(spec["sequence"]),
                "frames": spec["frames"],
            }
            for spec in test_specs
        ],
        "feature_order": ["bias", "rgb_r", "rgb_g", "rgb_b", "edit_r", "edit_g", "edit_b"],
        "coefficients": beta.tolist(),
        "training": training,
        "training_aggregate": aggregate(training),
        "heldout": heldout,
        "heldout_aggregate": aggregate(heldout),
        "test": test,
        "test_aggregate": aggregate(test),
        "promotion": False,
        "live_runtime_tested": False,
        "scope": "multi-sequence affine fit; no temporal-state model or live VR acceptance",
    }
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "training": result["training_aggregate"],
        "heldout": result["heldout_aggregate"],
        "test": result["test_aggregate"],
        "output": str(args.output.resolve()),
    }, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
