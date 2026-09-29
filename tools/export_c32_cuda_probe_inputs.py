#!/usr/bin/env python3
"""Export one recovered C32 MLP contract for the standalone CUDA probe.

This produces only derived research artifacts: a projected public-contract
input and the decoded first C32 MLP weights. It does not alter the source
captures, the OpenNR runtime, or any training cache.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

import numpy as np
import torch


def write_tensor(path: Path, tensor: torch.Tensor) -> dict[str, object]:
    values = np.ascontiguousarray(tensor.detach().to("cpu").numpy(), dtype=np.float16)
    values.tofile(path)
    return {
        "path": str(path),
        "shape": list(values.shape),
        "dtype": "float16",
        "bytes": int(values.nbytes),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend", type=Path, required=True)
    parser.add_argument("--weights", type=Path, required=True)
    parser.add_argument("--rgb-png", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()

    backend = args.backend.resolve()
    if str(backend) not in sys.path:
        sys.path.insert(0, str(backend))
    from nr_backend.executor import ResetNR
    from nr_backend.front import project_front_features, reset_front_features
    from nr_backend.weights import load_pinned_records

    from PIL import Image

    image = Image.open(args.rgb_png.resolve()).convert("RGB").resize((1920, 1080), Image.Resampling.BOX)
    rgb = torch.from_numpy(np.asarray(image, dtype=np.float32) / 255.0).to("cuda", dtype=torch.float16).contiguous()
    records = load_pinned_records(args.weights.resolve())
    model = ResetNR(records, None).eval().to("cuda")
    with torch.inference_mode():
        front = reset_front_features(rgb, padded_size=(1152, 1920), seed=args.seed, noise_source=None)
        # The C++ probe is a runtime/layout test. Ordinary FP16 projection keeps
        # this export bounded; the public reference-math front is tested in the
        # existing Python probes and is not silently claimed here.
        projected = project_front_features(front, model.pre.front_weight, reference_math=False)
        projected = projected.reshape(-1, 32).contiguous()

    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    entries = {
        "schema": "opennr-c32-cuda-probe-inputs-v1",
        "source_rgb": str(args.rgb_png.resolve()),
        "source_weights": str(args.weights.resolve()),
        "source_weights_sha256": hashlib.sha256(args.weights.resolve().read_bytes()).hexdigest(),
        "seed": args.seed,
        "tokens": int(projected.shape[0]),
        "channels": 32,
        "expansion": write_tensor(output / "expansion.bin", model.pre.mlp.expansion),
        "contraction": write_tensor(output / "contraction.bin", model.pre.mlp.contraction),
        "skip": write_tensor(output / "skip.bin", model.pre.mlp.skip_scale),
        "input": write_tensor(output / "input.bin", projected),
    }
    (output / "manifest.json").write_text(json.dumps(entries, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(entries, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
