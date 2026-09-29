"""Evaluate unchanged Skyrim input against the paired teacher."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import torch

from .dataset import TinyPairedCache, sha256_file
from .metrics import evaluate_model


class Identity(torch.nn.Module):
    def forward(self, value: torch.Tensor) -> torch.Tensor:
        return value


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--batch-size", type=int, default=2)
    parser.add_argument("--device", default="cuda")
    args = parser.parse_args()
    if args.device == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("CUDA was requested but is not available")
    device = torch.device(args.device)
    model = Identity().to(device).eval()
    validation = evaluate_model(model, TinyPairedCache(args.manifest.resolve(), "validation"), device, args.batch_size)
    test = evaluate_model(model, TinyPairedCache(args.manifest.resolve(), "test"), device, args.batch_size)
    result = {
        "schema": "opennr-tiny-enhancement-baseline-v1",
        "manifest": str(args.manifest.resolve()),
        "manifest_sha256": sha256_file(args.manifest.resolve()),
        "test_used_for_tuning": False,
        "validation": validation,
        "test": test,
    }
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "validation_mae": validation["overall"]["mae"],
        "validation_delta_mae": validation["overall"]["temporal_delta_mae"],
        "test_mae": test["overall"]["mae"],
        "test_delta_mae": test["overall"]["temporal_delta_mae"],
        "output": str(output),
    }, indent=2))


if __name__ == "__main__":
    main()

