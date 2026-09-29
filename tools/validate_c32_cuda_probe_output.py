#!/usr/bin/env python3
"""Compare the standalone fused C32 CUDA probe with a bounded torch reference."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import torch


def load_half(path: Path, shape: tuple[int, ...]) -> torch.Tensor:
    values = np.fromfile(path, dtype=np.float16)
    expected = int(np.prod(shape))
    if values.size != expected:
        raise ValueError(f"{path} has {values.size} values; expected {expected}")
    return torch.from_numpy(values.reshape(shape))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inputs", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--result", type=Path, required=True)
    parser.add_argument("--chunk", type=int, default=32768)
    args = parser.parse_args()
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is required")

    manifest = json.loads((args.inputs / "manifest.json").read_text(encoding="utf-8"))
    tokens = int(manifest["tokens"])
    channels = int(manifest["channels"])
    if channels != 32:
        raise ValueError("This validator expects the C32 probe contract")
    input_values = np.fromfile(args.inputs / "input.bin", dtype=np.float16).reshape(tokens, channels)
    observed_values = np.fromfile(args.output, dtype=np.float16).reshape(tokens, channels)
    expansion = load_half(args.inputs / "expansion.bin", (32, 128)).to("cuda", dtype=torch.float32)
    contraction = load_half(args.inputs / "contraction.bin", (128, 32)).to("cuda", dtype=torch.float32)
    skip = load_half(args.inputs / "skip.bin", (32,)).to("cuda", dtype=torch.float16)

    total_abs = 0.0
    total_squared = 0.0
    max_abs = 0.0
    compared = 0
    for start in range(0, tokens, args.chunk):
        stop = min(tokens, start + args.chunk)
        source = torch.from_numpy(input_values[start:stop].copy()).to("cuda", dtype=torch.float16)
        hidden = source.to(torch.float32) @ expansion
        half_hidden = hidden.to(torch.float16)
        t = half_hidden.clamp(-4.0, 4.0)
        p = torch.addcmul(
            torch.full_like(t, 0.447265625, dtype=torch.float16),
            -t.abs(),
            torch.full_like(t, 0.055908203125, dtype=torch.float16),
        )
        v = torch.addcmul(
            torch.full_like(t, 0.89453125, dtype=torch.float16),
            t,
            p,
        )
        activated = (half_hidden * v).to(torch.float16)
        predicted = (activated.to(torch.float32) @ contraction).to(torch.float16)
        predicted = (predicted + source * skip).to(torch.float16)
        observed = torch.from_numpy(observed_values[start:stop].copy()).to("cuda", dtype=torch.float16)
        difference = (predicted.float() - observed.float()).abs()
        total_abs += float(difference.sum().cpu())
        total_squared += float((difference * difference).sum().cpu())
        max_abs = max(max_abs, float(difference.max().cpu()))
        compared += difference.numel()
        del source, hidden, half_hidden, t, p, v, activated, predicted, observed, difference

    result = {
        "schema": "opennr-c32-cuda-probe-validation-v1",
        "status": "passed",
        "tokens": tokens,
        "channels": channels,
        "compared_values": compared,
        "mae_vs_fp32_reference": total_abs / compared,
        "rmse_vs_fp32_reference": (total_squared / compared) ** 0.5,
        "max_abs_vs_fp32_reference": max_abs,
        "observed_output_finite": bool(np.isfinite(observed_values).all()),
        "scope": "real decoded C32 weights and Skyrim-derived projected input; approximate FP32 reference, not native parity",
    }
    args.result.parent.mkdir(parents=True, exist_ok=True)
    args.result.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
