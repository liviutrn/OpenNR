#!/usr/bin/env python3
"""Compare standalone CUDA ViT projection outputs with their exact exports."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np


def metrics(output: np.ndarray, expected: np.ndarray) -> dict[str, object]:
    diff = output.astype(np.float32) - expected.astype(np.float32)
    return {
        "shape": list(output.shape),
        "output_finite": bool(np.isfinite(output).all()),
        "expected_finite": bool(np.isfinite(expected).all()),
        "mae_vs_reference": float(np.abs(diff).mean()),
        "rmse_vs_reference": float(np.sqrt(np.mean(diff * diff))),
        "max_abs_vs_reference": float(np.abs(diff).max()),
        "output_min": float(output.min()),
        "output_max": float(output.max()),
    }


def read_half(path: Path, shape: tuple[int, ...]) -> np.ndarray:
    values = np.fromfile(path, dtype=np.float16)
    expected_count = int(np.prod(shape))
    if values.size != expected_count:
        raise ValueError(f"{path} has {values.size} values; expected {expected_count}")
    return values.reshape(shape)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inputs", type=Path, required=True)
    parser.add_argument("--outputs", type=Path, required=True)
    parser.add_argument("--result", type=Path, required=True)
    args = parser.parse_args()

    inputs = args.inputs.resolve()
    outputs = args.outputs.resolve()
    manifest = json.loads((inputs / "manifest.json").read_text(encoding="utf-8"))
    rows = int(manifest["tokens"])
    cases = {
        "expand": (4096, "expand_expected.bin"),
        "contract": (1024, "contract_expected.bin"),
        "projection": (1024, "projection_expected.bin"),
    }
    report: dict[str, object] = {
        "schema": "opennr-vit-cuda-probe-validation-v1",
        "inputs": str(inputs),
        "outputs": str(outputs),
        "tokens": rows,
        "cases": {},
        "scope": (
            "real recovered ViT projection outputs compared with the "
            "public native-reference math exports; this is not native NVIDIA parity"
        ),
    }
    for label, (columns, expected_name) in cases.items():
        output = read_half(outputs / f"{label}_fused.bin", (rows, columns))
        expected = read_half(inputs / expected_name, (rows, columns))
        report["cases"][label] = metrics(output, expected)

    args.result.resolve().parent.mkdir(parents=True, exist_ok=True)
    args.result.resolve().write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
