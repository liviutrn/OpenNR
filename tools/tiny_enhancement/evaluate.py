"""Evaluate a frozen tiny enhancement checkpoint on validation and test splits."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import torch

from .dataset import TinyPairedCache, sha256_file
from .metrics import evaluate_model
from .models import build_model, parameter_count


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--batch-size", type=int, default=2)
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--include-validation", action="store_true")
    args = parser.parse_args()
    if args.device == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("CUDA was requested but is not available")
    device = torch.device(args.device)
    manifest_path = args.manifest.resolve()
    checkpoint_path = args.checkpoint.resolve()
    checkpoint = torch.load(checkpoint_path, map_location=device, weights_only=False)
    model = build_model(checkpoint["architecture"], checkpoint.get("config")).to(device)
    model.load_state_dict(checkpoint["model"])
    model.eval()
    if parameter_count(model) != checkpoint["parameters"]:
        raise ValueError("checkpoint parameter count mismatch")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if checkpoint.get("manifest_sha256") != sha256_file(manifest_path):
        raise ValueError("checkpoint manifest identity does not match evaluation manifest")
    validation = None
    if args.include_validation:
        validation = evaluate_model(model, TinyPairedCache(manifest_path, "validation"), device, args.batch_size)
    test = evaluate_model(model, TinyPairedCache(manifest_path, "test"), device, args.batch_size)
    result = {
        "schema": "opennr-tiny-enhancement-evaluation-v1",
        "architecture": checkpoint["architecture"],
        "checkpoint": str(checkpoint_path),
        "checkpoint_sha256": hashlib.sha256(checkpoint_path.read_bytes()).hexdigest(),
        "checkpoint_step": checkpoint.get("step"),
        "parameters": parameter_count(model),
        "manifest": str(manifest_path),
        "manifest_sha256": sha256_file(manifest_path),
        "source_cache": manifest["source_cache"],
        "test_used_for_tuning": False,
        "validation": validation,
        "test": test,
    }
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "architecture": result["architecture"],
        "step": result["checkpoint_step"],
        "parameters": result["parameters"],
        "test_mae": test["overall"]["mae"],
        "test_input_mae": test["overall"]["input_mae"],
        "test_delta_mae": test["overall"]["temporal_delta_mae"],
        "output": str(output),
    }, indent=2))


if __name__ == "__main__":
    main()

