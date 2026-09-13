"""Independent validation replay for a semantic-joint checkpoint.

The replay reloads a saved checkpoint through the normal provenance-checked
loader and evaluates only its recorded validation cohorts. It deliberately
does not construct a test cache or read frozen-test streams.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import torch

from joint_parent_tone_model import load_joint_checkpoint
from prepare_conditioning_pilot import save, sha
from train_semantic_ablation import cohort
from train_temporal_student import evaluate_streaming


SCALAR_KEYS = (
    "mae",
    "psnr",
    "temporal_delta_mae",
    "first_frame_mae",
    "steady_frame_mae",
    "identity_mae",
    "improvement_pct",
)


def _read_json(path: Path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _write_json(path: Path, value) -> None:
    save(Path(path), value)


def _replay(checkpoint: Path, output: Path, batch: int) -> dict:
    payload = torch.load(checkpoint, map_location="cpu", weights_only=False)
    if payload.get("architecture") != "semantic_joint_parent_v1":
        raise ValueError(f"Unsupported checkpoint architecture: {checkpoint}")
    run = payload["run"]
    roots = [Path(value).resolve() for value in run["cohorts"]]
    labels = list(run["cohort_labels"])
    if len(roots) != len(labels):
        raise ValueError("Checkpoint cohort labels do not match roots")
    validation = [cohort(root, "validation") for root in roots]
    model, reloaded_payload = load_joint_checkpoint(checkpoint)
    if int(reloaded_payload["step"]) != int(payload["step"]):
        raise ValueError("Reloaded checkpoint step changed")
    metrics = {}
    started = time.time()
    artifact_prefix = f"{checkpoint.parent.name}_{checkpoint.stem}"
    for label, cache in zip(labels, validation):
        _write_json(
            output / f"{artifact_prefix}_status.json",
            {"state": "evaluating", "checkpoint": str(checkpoint), "cohort": label, "test_used": False},
        )
        metrics[label] = evaluate_streaming(model, cache, batch=batch)
    recorded = payload["validation"]
    differences = {}
    max_abs = 0.0
    for label in labels:
        differences[label] = {}
        for key in SCALAR_KEYS:
            difference = abs(float(metrics[label][key]) - float(recorded[label][key]))
            differences[label][key] = difference
            max_abs = max(max_abs, difference)
        differences[label]["eye_mae"] = {
            eye: abs(float(metrics[label]["eye_mae"][eye]) - float(recorded[label]["eye_mae"][eye]))
            for eye in recorded[label]["eye_mae"]
        }
        max_abs = max(max_abs, *(differences[label]["eye_mae"].values()))
    result = {
        "checkpoint": str(checkpoint.resolve()),
        "checkpoint_sha256": sha(checkpoint),
        "step": int(payload["step"]),
        "batch": int(batch),
        "recorded_validation": recorded,
        "replayed_validation": metrics,
        "absolute_differences": differences,
        "max_abs_difference": max_abs,
        "replay_match": bool(max_abs <= 1e-7),
        "test_used": False,
        "seconds": time.time() - started,
        "source_sha256": sha(Path(__file__)),
    }
    _write_json(output / f"{artifact_prefix}_replay.json", result)
    _write_json(
        output / f"{artifact_prefix}_status.json",
        {"state": "complete", "checkpoint": str(checkpoint), "replay_match": result["replay_match"], "test_used": False},
    )
    del model
    torch.cuda.empty_cache()
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint", action="append", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--batch", type=int, default=1)
    args = parser.parse_args()
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is required")
    if args.batch < 1:
        raise ValueError("Batch must be positive")
    checkpoints = [path.resolve() for path in args.checkpoint]
    if any(not path.is_file() for path in checkpoints):
        raise FileNotFoundError("A replay checkpoint is missing")
    args.output = args.output.resolve()
    if args.output.exists():
        raise FileExistsError(args.output)
    args.output.mkdir(parents=True)
    torch.set_num_threads(4)
    torch.backends.cudnn.benchmark = False
    results = [_replay(path, args.output, args.batch) for path in checkpoints]
    _write_json(args.output / "summary.json", {"results": results, "test_used": False})


if __name__ == "__main__":
    main()
