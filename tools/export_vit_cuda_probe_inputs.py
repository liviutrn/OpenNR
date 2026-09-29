#!/usr/bin/env python3
"""Export one real recovered ViT block for a standalone CUDA speed probe.

The files are derived research artifacts.  This script does not modify the
source captures, the OpenNR runtime, or any training cache.  It runs the
reconstructed public reset graph up to the first ViT block, then exports the
two large dense boundaries and their reference inputs/outputs.
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
    values = np.ascontiguousarray(
        tensor.detach().to("cpu").numpy(), dtype=np.float16
    )
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
    parser.add_argument("--height", type=int, default=1080)
    parser.add_argument("--width", type=int, default=1920)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()

    if (args.height, args.width) not in {
        (256, 256), (512, 512), (480, 864), (1080, 1920), (1439, 2559)
    }:
        raise ValueError("use one of the observed public RGB contracts")

    backend = args.backend.resolve()
    if str(backend) not in sys.path:
        sys.path.insert(0, str(backend))

    from PIL import Image

    from nr_backend.executor import ResetNR
    from nr_backend.front import reset_front_features
    from nr_backend.vit_block import split_k_projection
    from nr_backend.weights import load_pinned_records

    image = Image.open(args.rgb_png.resolve()).convert("RGB").resize(
        (args.width, args.height), Image.Resampling.BOX
    )
    rgb = torch.from_numpy(
        np.asarray(image, dtype=np.float32) / 255.0
    ).to("cuda", dtype=torch.float16).contiguous()
    records = load_pinned_records(args.weights.resolve())
    model = ResetNR(records, None).eval().to("cuda")
    padded_size = model.PADDED_SIZES[(args.height, args.width)]

    with torch.inference_mode():
        front = reset_front_features(
            rgb, padded_size=padded_size, seed=args.seed, noise_source=None
        )
        x = model.pre.forward_features_outputs(front)[1]
        for group in model.encoder:
            for block in group:
                skip, down = block.forward_outputs(x)
                x = down if down is not None else skip
        for block_index, block in enumerate(model.encoder512):
            values = block.forward_boundaries(x)
            x = values[-1]

        features = x.reshape(-1, 1024).contiguous()
        if features.shape[0] <= 0:
            raise ValueError("the recovered graph produced no ViT tokens")

        block = model.vit[0]
        hidden, mlp, query, key, value, attended, block_output = block.forward_boundaries(features)

        # The CUDA probe measures the two large projection boundaries rather
        # than claiming to reproduce the full attention block.  Keep the
        # exact reference inputs/outputs so the standalone result can be
        # checked for finite values and numerical drift.
        expand_input = features
        expand_expected = hidden
        contract_input = hidden
        contract_initial = (features * block.ffn_skip).half()
        contract_expected = split_k_projection(
            contract_input, block.contract, contract_initial
        )

        projection_input = attended
        projection_initial = (mlp * block.attn_skip).half()
        projection_expected = split_k_projection(
            projection_input, block.projection, projection_initial
        )

    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    entries: dict[str, object] = {
        "schema": "opennr-vit-cuda-probe-inputs-v1",
        "source_rgb": str(args.rgb_png.resolve()),
        "source_weights": str(args.weights.resolve()),
        "source_weights_sha256": hashlib.sha256(
            args.weights.resolve().read_bytes()
        ).hexdigest(),
        "seed": args.seed,
        "rgb_contract": [args.height, args.width, 3],
        "padded_contract": list(padded_size),
        "tokens": int(features.shape[0]),
        "block": 0,
        "expand_input": write_tensor(output / "expand_input.bin", expand_input),
        "expand_weight": write_tensor(output / "expand_weight.bin", block.expand),
        "expand_expected": write_tensor(
            output / "expand_expected.bin", expand_expected
        ),
        "contract_input": write_tensor(output / "contract_input.bin", contract_input),
        "contract_weight": write_tensor(output / "contract_weight.bin", block.contract),
        "contract_initial": write_tensor(
            output / "contract_initial.bin", contract_initial
        ),
        "contract_expected": write_tensor(
            output / "contract_expected.bin", contract_expected
        ),
        "ffn_skip": write_tensor(output / "ffn_skip.bin", block.ffn_skip),
        "query": write_tensor(output / "query.bin", query),
        "key": write_tensor(output / "key.bin", key),
        "value": write_tensor(output / "value.bin", value),
        "qkv_weight": write_tensor(output / "qkv_weight.bin", block.qkv_weight),
        "projection_input": write_tensor(
            output / "projection_input.bin", projection_input
        ),
        "projection_weight": write_tensor(
            output / "projection_weight.bin", block.projection
        ),
        "projection_initial": write_tensor(
            output / "projection_initial.bin", projection_initial
        ),
        "projection_expected": write_tensor(
            output / "projection_expected.bin", projection_expected
        ),
        "attn_skip": write_tensor(output / "attn_skip.bin", block.attn_skip),
        "query_scale": write_tensor(output / "query_scale.bin", block.query_scale),
        "block_output": write_tensor(output / "block_output.bin", block_output),
        "scope": (
            "real recovered ViT block projection inputs and weights; "
            "CUDA probe is a speed/finiteness experiment, not native parity"
        ),
    }
    (output / "manifest.json").write_text(
        json.dumps(entries, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(entries, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
