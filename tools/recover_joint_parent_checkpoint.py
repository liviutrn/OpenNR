"""Recover a self-contained parent initializer from a protected joint checkpoint.

The semantic joint checkpoint stores the complete parent model state, but the
original parent initializer may have been removed during storage triage.  This
tool creates a separately named, provenance-labeled parent checkpoint and a
working copy of the joint checkpoint whose parent reference points to it.  The
protected source checkpoint is never modified.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path

import torch

from capacity_student import CapacityConfig
from capacity_temporal_student import CapacityTemporalStyleContextStudent
from joint_parent_tone_model import load_joint_checkpoint
from student_v2 import ReconstructionConfig
from temporal_student import TemporalConfig
from train_capacity_temporal_student import _load_parent


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def atomic_torch_save(value, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    torch.save(value, temporary)
    temporary.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protected-joint", type=Path, required=True)
    parser.add_argument("--expected-protected-sha256", required=True)
    parser.add_argument("--recovered-parent", type=Path, required=True)
    parser.add_argument("--recovered-joint", type=Path, required=True)
    args = parser.parse_args()

    protected_joint = args.protected_joint.resolve()
    recovered_parent = args.recovered_parent.resolve()
    recovered_joint = args.recovered_joint.resolve()
    if not protected_joint.is_file():
        raise FileNotFoundError(protected_joint)
    if sha(protected_joint).lower() != args.expected_protected_sha256.lower():
        raise ValueError("Protected joint checkpoint SHA-256 does not match the recorded control")
    if recovered_parent.exists() or recovered_joint.exists():
        raise FileExistsError("Recovery output already exists; use a fresh output path")

    protected = torch.load(protected_joint, map_location="cpu", weights_only=False)
    if protected.get("architecture") != "semantic_joint_parent_v1":
        raise ValueError("Protected checkpoint is not semantic_joint_parent_v1")
    parent_state = protected.get("parent_model")
    if not isinstance(parent_state, dict) or not parent_state:
        raise ValueError("Protected joint checkpoint has no parent_model state")

    # These dimensions are independently confirmed from the serialized state:
    # 64-wide base, 64-wide temporal branch, 192-wide six-block capacity branch,
    # and a 96-wide three-block extra branch with both inherited gates enabled.
    base_config = {"width": 64, "blocks": 3, "scale": 4}
    temporal_config = {"hidden": 64, "downsample": 8, "delta_scale": 0.12}
    capacity_config = {
        "width": 192,
        "blocks": 6,
        "delta_scale": 0.12,
        "style_modulation": False,
        "extra_width": 96,
        "extra_blocks": 3,
        "residual_gate": True,
        "residual_gate_scale": 0.8,
        "final_gate": True,
        "final_gate_scale": 0.8,
    }
    model = CapacityTemporalStyleContextStudent(
        ReconstructionConfig(**base_config),
        TemporalConfig(**temporal_config),
        CapacityConfig(**capacity_config),
    )
    incompat = model.load_state_dict(parent_state, strict=False)
    if incompat.missing_keys or incompat.unexpected_keys:
        raise ValueError(
            f"Parent state does not match recovered architecture: missing={incompat.missing_keys}, "
            f"unexpected={incompat.unexpected_keys}"
        )
    parameter_count = sum(parameter.numel() for parameter in model.parameters())
    recorded_count = int(protected["run"].get("trainable_parent_parameters", parameter_count))
    if parameter_count != recorded_count:
        raise ValueError(f"Recovered parent parameter count {parameter_count} != recorded {recorded_count}")

    original_parent = protected["run"].get("parent")
    original_parent_sha = protected["run"].get("parent_sha256")
    parent_payload = {
        "architecture": "context_v7_capacity_temporal",
        "base_config": base_config,
        "temporal_config": temporal_config,
        "capacity_config": capacity_config,
        "model": parent_state,
        "step": int(protected.get("step", 0)),
        "run": {
            "recovery": "parent_model state extracted from protected semantic_joint_parent_v1 checkpoint",
            "source_joint_checkpoint": str(protected_joint),
            "source_joint_checkpoint_sha256": sha(protected_joint),
            "original_parent_path": original_parent,
            "original_parent_sha256": original_parent_sha,
            "parameter_count": parameter_count,
        },
    }
    atomic_torch_save(parent_payload, recovered_parent)
    recovered_parent_sha = sha(recovered_parent)

    # Confirm the recovered parent is loadable through the normal parent loader.
    _load_parent(recovered_parent, device="cpu")

    working = copy.copy(protected)
    working_run = dict(protected["run"])
    working_run["parent"] = str(recovered_parent)
    working_run["parent_sha256"] = recovered_parent_sha
    working_run["parent_recovery"] = {
        "source_joint_checkpoint": str(protected_joint),
        "source_joint_checkpoint_sha256": sha(protected_joint),
        "original_parent_path": original_parent,
        "original_parent_sha256": original_parent_sha,
        "recovered_parent_sha256": recovered_parent_sha,
        "reason": "original parent initializer was absent during preflight; exact parent state was embedded in the protected joint checkpoint",
    }
    working["run"] = working_run
    atomic_torch_save(working, recovered_joint)

    # Exercise the same integrity path used by training.  This also confirms
    # that the old cohort controls and source hashes remain untouched.
    load_joint_checkpoint(recovered_joint)
    summary = {
        "protected_joint": str(protected_joint),
        "protected_joint_sha256": sha(protected_joint),
        "recovered_parent": str(recovered_parent),
        "recovered_parent_sha256": recovered_parent_sha,
        "recovered_joint": str(recovered_joint),
        "recovered_joint_sha256": sha(recovered_joint),
        "parameter_count": parameter_count,
        "original_parent_path": original_parent,
        "original_parent_sha256": original_parent_sha,
        "source_immutable": True,
    }
    print(json.dumps(summary, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

