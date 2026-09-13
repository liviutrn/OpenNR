#!/usr/bin/env python3
"""Run the public NR-B580 fused backend on CUDA as an offline probe.

The public backend was published with XPU guards.  The selected research copy
has those guards widened to CUDA without changing kernel bodies; this tool
loads the hash-verified serialized resource reconstructed from our preserved
packed Safetensors payload and measures the backend at its observed 256x256
contract.  This is an independent-backend experiment, not a native runtime.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
import time

import numpy as np
import torch


def _image(path: Path, device: str) -> torch.Tensor:
    from PIL import Image

    image = Image.open(path).convert("RGB").resize((256, 256), Image.Resampling.BOX)
    values = np.asarray(image, dtype=np.float32) / 255.0
    return torch.from_numpy(values).to(device=device, dtype=torch.float16).contiguous()


def _event_ms(callback) -> float:
    start = torch.cuda.Event(enable_timing=True)
    end = torch.cuda.Event(enable_timing=True)
    start.record()
    output = callback()
    end.record()
    end.synchronize()
    return float(start.elapsed_time(end)), output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--weights", type=Path, required=True)
    parser.add_argument("--backend", type=Path, required=True)
    parser.add_argument("--rgb-png", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--mode", choices=("triton", "reference"), default="triton")
    parser.add_argument("--warmup", type=int, default=1)
    parser.add_argument("--iterations", type=int, default=3)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is required")
    if args.warmup < 0 or args.iterations < 1:
        raise ValueError("warmup must be non-negative and iterations must be positive")

    backend_root = args.backend.resolve()
    if str(backend_root) not in sys.path:
        sys.path.insert(0, str(backend_root))
    from nr_backend.execution import use_arithmetic_backend
    from nr_backend.executor import ResetNR
    from nr_backend.front import reset_front_features
    from nr_backend.weights import load_pinned_records

    weights_path = args.weights.resolve()
    records = load_pinned_records(weights_path)
    rgb = _image(args.rgb_png.resolve(), "cuda")
    with torch.inference_mode():
        front_ms, front = _event_ms(
            lambda: reset_front_features(
                rgb, padded_size=(320, 320), seed=args.seed, noise_source=None
            )
        )
    model = ResetNR(records, None).eval().to("cuda")
    torch.cuda.synchronize()

    counters = []
    times = []
    output = None
    with torch.inference_mode(), use_arithmetic_backend(args.mode) as dispatches:
        for _ in range(args.warmup):
            output = model._forward_front(rgb, front)
        torch.cuda.synchronize()
        for _ in range(args.iterations):
            elapsed, output = _event_ms(lambda: model._forward_front(rgb, front))
            times.append(elapsed)
        counters.append(dict(dispatches))
    if output is None:
        raise AssertionError("model produced no output")
    values = output.detach().float()
    result = {
        "schema": "opennr-public-b580-cuda-probe-v1",
        "status": "passed",
        "mode": args.mode,
        "contract": {"rgb": [256, 256, 3], "padded_front": [320, 320, 16]},
        "weights": str(weights_path),
        "weights_sha256": hashlib.sha256(weights_path.read_bytes()).hexdigest(),
        "backend": str(backend_root),
        "rgb": str(args.rgb_png.resolve()),
        "gpu": torch.cuda.get_device_name(0),
        "torch": torch.__version__,
        "cuda": torch.version.cuda,
        "warmup": args.warmup,
        "iterations": args.iterations,
        "front_prepare_ms": front_ms,
        "network_ms": times,
        "network_median_ms": float(np.median(times)),
        "network_p95_ms": float(np.percentile(times, 95)),
        "dispatches": counters,
        "output_shape": list(output.shape),
        "output_finite": bool(torch.isfinite(values).all().item()),
        "output_min": float(values.min().item()),
        "output_max": float(values.max().item()),
        "scope": "offline CUDA execution of the public independent backend at its 256x256 reference contract; not full-resolution, temporal, stereo, Feature 18, or VR acceptance",
    }
    args.output.resolve().mkdir(parents=True, exist_ok=True)
    (args.output.resolve() / "result.json").write_text(
        json.dumps(result, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(result, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
