"""Strip training-only state from the verified semantic joint checkpoint."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import torch

from semantic_joint_runtime import sha256_file, tensor_digest


TRAINING_ONLY_KEYS = (
    "optimizer",
    "raw_model",
    "numpy_rng_state",
    "torch_rng_state",
    "cuda_rng_state",
)


def cpu_state(state):
    return {name: value.detach().cpu().contiguous() for name, value in state.items()}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True, help="New directory for bundle.pt and manifest.json")
    args = parser.parse_args()
    source = args.checkpoint.resolve()
    output = args.output.resolve()
    if not source.is_file():
        raise FileNotFoundError(source)
    if output.exists() and any(output.iterdir()):
        raise FileExistsError(f"Output is not empty: {output}")
    output.mkdir(parents=True, exist_ok=True)

    payload = torch.load(source, map_location="cpu", weights_only=False)
    if payload.get("architecture") != "semantic_joint_parent_v1":
        raise ValueError("The source is not a semantic joint-parent checkpoint")
    missing = [name for name in ("head", "parent_model", "run", "step") if name not in payload]
    if missing:
        raise ValueError(f"Checkpoint is missing required fields: {missing}")
    present_training_only = [name for name in TRAINING_ONLY_KEYS if name in payload]

    run = payload["run"]
    parent_source = Path(run["parent"]).resolve()
    parent_payload = torch.load(parent_source, map_location="cpu", weights_only=False)
    parent_config = {
        "base_config": parent_payload.get("base_config", run.get("base_config")),
        "temporal_config": parent_payload.get("temporal_config", run.get("temporal_config")),
        "capacity_config": parent_payload.get("capacity_config", run.get("capacity_config")),
    }
    if any(value is None for value in parent_config.values()):
        raise ValueError("Could not recover the parent architecture configuration")
    if "model" not in parent_payload:
        raise ValueError("Parent checkpoint has no EMA model state")

    parent_state = cpu_state(payload["parent_model"])
    head_state = cpu_state(payload["head"])
    bundle = {
        "format": "opennr-semantic-joint-inference-v1",
        "source_checkpoint": str(source),
        "source_checkpoint_sha256": sha256_file(source),
        "source_architecture": payload["architecture"],
        "source_step": int(payload["step"]),
        "source_run": {
            "seed": run.get("seed"),
            "cohort_labels": run.get("cohort_labels"),
            "test_used": run.get("test_used"),
            "pretrained_encoder": run.get("pretrained_encoder"),
            "joint_parent": run.get("joint_parent"),
        },
        "parent_source": str(parent_source),
        "parent_source_sha256": run.get("parent_sha256", sha256_file(parent_source)),
        "parent_architecture": parent_payload.get("architecture"),
        "parent_config": parent_config,
        "encoder_source": run["encoder_provenance"]["source"],
        "encoder_weights_sha256": run["encoder_provenance"].get("weights_sha256"),
        "parent_state_dict": parent_state,
        "head_state_dict": head_state,
        "parent_state_digest": tensor_digest(parent_state),
        "head_state_digest": tensor_digest(head_state),
        "input_contract": {
            "rgb": "float32 [1,3,H,W] in [0,1], color/model surface",
            "guides": "float32 [1,5,ceil(H/4),ceil(W/4)] in training-normalized Feature-18 depth/MV/validity order",
            "context": "float32 [1,8,96,96], input RGB plus guide context",
            "output": "float32 [1,3,H,W] in [0,1]",
            "hidden_state": "float32 [1,64,ceil(H/8),ceil(W/8)]",
            "previous_state": "float32 [1,3,H,W]",
            "reset": "hidden=zeros and previous=current RGB, equivalent to state=None",
            "causal": True,
            "stereo": "run one independent state chain per eye",
        },
        "training_only_fields_removed": present_training_only,
        "bundle_contains_optimizer": False,
        "bundle_contains_rng": False,
    }
    bundle_path = output / "bundle.pt"
    torch.save(bundle, bundle_path, pickle_protocol=4)
    reloaded = torch.load(bundle_path, map_location="cpu", weights_only=False)
    if tensor_digest(reloaded["parent_state_dict"]) != bundle["parent_state_digest"]:
        raise ValueError("Parent digest changed after bundle serialization")
    if tensor_digest(reloaded["head_state_dict"]) != bundle["head_state_digest"]:
        raise ValueError("Head digest changed after bundle serialization")

    manifest = {
        "format": bundle["format"],
        "bundle": str(bundle_path),
        "bundle_sha256": sha256_file(bundle_path),
        "bundle_bytes": bundle_path.stat().st_size,
        "source_checkpoint": bundle["source_checkpoint"],
        "source_checkpoint_sha256": bundle["source_checkpoint_sha256"],
        "source_step": bundle["source_step"],
        "parent_source": bundle["parent_source"],
        "parent_source_sha256": bundle["parent_source_sha256"],
        "parent_architecture": bundle["parent_architecture"],
        "parent_tensor_count": len(parent_state),
        "head_tensor_count": len(head_state),
        "parent_parameter_count": sum(value.numel() for value in parent_state.values()),
        "head_parameter_count": sum(value.numel() for value in head_state.values()),
        "parent_state_digest": bundle["parent_state_digest"],
        "head_state_digest": bundle["head_state_digest"],
        "training_only_fields_removed": present_training_only,
        "test_used": run.get("test_used"),
        "input_contract": bundle["input_contract"],
    }
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, indent=2), flush=True)


if __name__ == "__main__":
    main()

