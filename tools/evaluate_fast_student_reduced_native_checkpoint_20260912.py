"""Evaluate a saved reduced-native FastStudent checkpoint on full-eye replays."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import torch

from fast_student_v1 import load_fast_student
from train_fast_student_reduced_native_multiseq_20260912 import (
    _evaluate_sequence,
    _load_sequence,
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--replay-root", type=Path, action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--context-size", type=int, default=96)
    parser.add_argument("--device", default="cuda")
    args = parser.parse_args()

    if args.output.exists() and any(args.output.iterdir()):
        raise FileExistsError(f"refusing to use non-empty output directory: {args.output}")
    if args.device.startswith("cuda") and not torch.cuda.is_available():
        raise RuntimeError("CUDA is required for this evaluation")
    args.output.mkdir(parents=True, exist_ok=True)
    device = torch.device(args.device)
    checkpoint = args.checkpoint.resolve()
    model, saved = load_fast_student(checkpoint, device)
    results: list[dict[str, object]] = []
    for root in args.replay_root:
        data = _load_sequence(root, args.context_size, device, 0.75)
        evaluation = _evaluate_sequence(model, data, data["frames"], device)
        results.append(
            {
                "replay_root": str(data["replay_root"]),
                "manifest_sha256": data["manifest_sha256"],
                "sequence": str(data["sequence"]),
                "frames": data["frames"],
                "evaluation": evaluation,
            }
        )
        for item in data["items"].values():
            item.clear()
        data["items"].clear()
        if device.type == "cuda":
            torch.cuda.empty_cache()

    result = {
        "schema": "opennr-fast-student-reduced-native-checkpoint-evaluation-v1",
        "checkpoint": str(checkpoint),
        "checkpoint_sha256": _sha256(checkpoint),
        "architecture": saved.get("architecture"),
        "config": saved.get("config"),
        "parameters": sum(value.numel() for value in saved["model"].values()),
        "context_size": args.context_size,
        "device": str(device),
        "gpu": torch.cuda.get_device_name(device) if device.type == "cuda" else None,
        "replays": results,
        "promotion": False,
        "live_runtime_tested": False,
        "scope": "full-eye offline checkpoint evaluation; no live Skyrim or VR acceptance",
    }
    (args.output / "result.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
