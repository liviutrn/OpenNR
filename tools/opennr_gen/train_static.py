"""Train one matched static OpenNR-GEN distillation arm.

Arms:

``control``
    raw/pre-NR RGB -> original DLSS5-NR RGB
``gen_a``
    raw/pre-NR RGB -> accepted offline enhanced target
``gen_b``
    raw/pre-NR RGB -> enhanced target plus a retention term toward DLSS5-NR

This trainer fails closed until the offline target gate is explicitly marked
accepted.  It never reads the source cache test split; the bounded GEN
manifest is made only from source-train rows and has its own sequence split.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import torch
from PIL import Image

from hybrid_student import HybridStudent, parameter_count


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            block = handle.read(chunk_size)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _verify_manifest(path: Path) -> dict[str, Any]:
    manifest = json.loads(path.read_text(encoding="utf-8"))
    body = dict(manifest)
    recorded = body.pop("manifest_sha256", None)
    if canonical_sha256(body) != recorded:
        raise ValueError("static manifest hash mismatch")
    if manifest.get("source_test_used_for_tuning") is not False:
        raise ValueError("GEN manifest does not protect source test data")
    if any(sample.get("source_split") != "train" for sample in manifest.get("samples", [])):
        raise ValueError("GEN manifest contains a non-train source row")
    return manifest


def _verify_target_gate(
    manifest: dict[str, Any], records_path: Path, review_path: Path
) -> tuple[dict[str, Any], dict[str, Any]]:
    records = json.loads(records_path.read_text(encoding="utf-8"))
    if records.get("schema") != "opennr-gen-static-target-records-v1":
        raise ValueError("unsupported target records")
    if records.get("manifest_sha256") != manifest["manifest_sha256"]:
        raise ValueError("target records and manifest differ")
    review = json.loads(review_path.read_text(encoding="utf-8"))
    if review.get("schema") != "opennr-gen-target-review-v1":
        raise ValueError("unsupported target review")
    expected = {sample["sample_id"] for sample in manifest["samples"]}
    actual = {sample["sample_id"] for sample in review.get("samples", [])}
    if expected != actual:
        raise ValueError("target review does not cover the manifest exactly")
    if review.get("status") != "accepted":
        raise ValueError("target review status is not accepted")
    for item in review["samples"]:
        if item.get("decision") != "accept":
            raise ValueError(f"target {item['sample_id']} is not accepted")
        for check in (
            "teacher_preference",
            "identity_and_face",
            "geometry_and_objects",
            "material_fidelity",
            "lighting_direction",
            "stereo_pair_consistency",
        ):
            if item.get(check) != "pass":
                raise ValueError(f"target {item['sample_id']} has non-passing {check}")
    expected_records = {sample["sample_id"] for sample in manifest["samples"]}
    if set(records.get("samples", {})) != expected_records:
        raise ValueError("target records are incomplete")
    for sample in manifest["samples"]:
        record = records["samples"][sample["sample_id"]]
        if record.get("status") not in {"generated", "skipped_existing"}:
            raise ValueError(f"target {sample['sample_id']} was not generated")
        target = Path(sample["enhanced_target_path"])
        if not target.exists() or sha256_file(target) != record.get("target_sha256"):
            raise ValueError(f"target hash mismatch for {sample['sample_id']}")
    return records, review


def _image_tensor(path: str | Path) -> torch.Tensor:
    with Image.open(path) as image:
        array = np.asarray(image.convert("RGB"), dtype=np.float32) / 255.0
    return torch.from_numpy(np.moveaxis(array, -1, 0).copy())


def _load_samples(manifest: dict[str, Any], split: str, overfit_count: int | None) -> list[dict[str, Any]]:
    samples = [sample for sample in manifest["samples"] if sample["student_split"] == split]
    if split == "train" and overfit_count is not None:
        if overfit_count < 1 or overfit_count > len(samples):
            raise ValueError(f"overfit_count {overfit_count} is outside train size {len(samples)}")
        samples = samples[:overfit_count]
    if not samples:
        raise ValueError(f"no samples for split {split}")
    return samples


def _make_schedule(
    samples: list[dict[str, Any]], steps: int, batch_size: int, seed: int
) -> list[list[str]]:
    rng = np.random.default_rng(seed)
    ids = [sample["sample_id"] for sample in samples]
    return [[ids[int(index)] for index in rng.integers(0, len(ids), size=batch_size)] for _ in range(steps)]


def _load_or_make_schedule(
    path: Path, samples: list[dict[str, Any]], steps: int, batch_size: int, seed: int, manifest_hash: str
) -> list[list[str]]:
    if path.exists():
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("schema") != "opennr-gen-static-schedule-v1":
            raise ValueError("unsupported schedule")
        for key, expected in {
            "manifest_sha256": manifest_hash,
            "steps": steps,
            "batch_size": batch_size,
            "seed": seed,
        }.items():
            if payload.get(key) != expected:
                raise ValueError(f"schedule {key} mismatch")
        schedule = payload.get("batches")
        if not isinstance(schedule, list) or len(schedule) != steps:
            raise ValueError("schedule length mismatch")
        allowed = {sample["sample_id"] for sample in samples}
        if any(any(sample_id not in allowed for sample_id in batch) for batch in schedule):
            raise ValueError("schedule references a sample outside the selected split")
        return schedule
    schedule = _make_schedule(samples, steps, batch_size, seed)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "schema": "opennr-gen-static-schedule-v1",
                "created_utc": datetime.now(timezone.utc).isoformat(),
                "manifest_sha256": manifest_hash,
                "sample_ids": [sample["sample_id"] for sample in samples],
                "steps": steps,
                "batch_size": batch_size,
                "seed": seed,
                "batches": schedule,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return schedule


def _batch(
    by_id: dict[str, dict[str, Any]], ids: list[str], device: torch.device
) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
    inputs = torch.stack([_image_tensor(by_id[sample_id]["raw_input_path"]) for sample_id in ids])
    teachers = torch.stack([_image_tensor(by_id[sample_id]["teacher_path"]) for sample_id in ids])
    targets = torch.stack([_image_tensor(by_id[sample_id]["enhanced_target_path"]) for sample_id in ids])
    return inputs.to(device), teachers.to(device), targets.to(device)


@torch.inference_mode()
def _evaluate(model: HybridStudent, samples: list[dict[str, Any]], device: torch.device) -> dict[str, float]:
    model.eval()
    target_sum = teacher_sum = input_sum = 0.0
    count = 0
    for sample in samples:
        inputs = _image_tensor(sample["raw_input_path"])[None].to(device)
        teachers = _image_tensor(sample["teacher_path"])[None].to(device)
        targets = _image_tensor(sample["enhanced_target_path"])[None].to(device)
        prediction = model(inputs).float()
        target_sum += float((prediction - targets).abs().mean().item())
        teacher_sum += float((prediction - teachers).abs().mean().item())
        input_sum += float((inputs - teachers).abs().mean().item())
        count += 1
    return {
        "target_mae": target_sum / count,
        "teacher_mae": teacher_sum / count,
        "input_teacher_mae": input_sum / count,
    }


def _seed_all(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--target-records", type=Path, required=True)
    parser.add_argument("--target-review", type=Path, required=True)
    parser.add_argument("--arm", choices=["control", "gen_a", "gen_b"], required=True)
    parser.add_argument("--capacity", choices=["0.25m", "1m", "4m"], required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--schedule", type=Path)
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--steps", type=int, default=1600)
    parser.add_argument("--eval-every", type=int, default=100)
    parser.add_argument("--batch-size", type=int, default=2)
    parser.add_argument("--overfit-count", type=int)
    parser.add_argument("--seed", type=int, default=91010)
    parser.add_argument("--learning-rate", type=float, default=1e-3)
    parser.add_argument("--retention-weight", type=float, default=0.25)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if args.steps < 1 or args.eval_every < 1 or args.batch_size < 1:
        raise ValueError("steps, eval-every, and batch-size must be positive")
    if args.retention_weight < 0.0:
        raise ValueError("retention weight must be nonnegative")
    manifest_path = args.manifest.resolve()
    manifest = _verify_manifest(manifest_path)
    records_path = args.target_records.resolve()
    review_path = args.target_review.resolve()
    records, review = _verify_target_gate(manifest, records_path, review_path)
    train_samples = _load_samples(manifest, "train", args.overfit_count)
    validation_samples = _load_samples(manifest, "validation", None)
    by_id = {sample["sample_id"]: sample for sample in manifest["samples"]}
    schedule_path = args.schedule.resolve() if args.schedule else args.output.resolve().parent / "matched_schedule.json"
    schedule = _load_or_make_schedule(
        schedule_path, train_samples, args.steps, args.batch_size, args.seed, manifest["manifest_sha256"]
    )
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    device = torch.device(args.device)
    if device.type == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("CUDA was requested but is not available")
    _seed_all(args.seed)
    model = HybridStudent(args.capacity).to(device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=args.learning_rate, weight_decay=1e-4)
    metadata: dict[str, Any] = {
        "schema": "opennr-gen-static-training-v1",
        "status": "dry_run" if args.dry_run else "running",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "manifest": str(manifest_path),
        "manifest_sha256": manifest["manifest_sha256"],
        "target_records": str(records_path),
        "target_records_sha256": sha256_file(records_path),
        "target_review": str(review_path),
        "target_review_sha256": sha256_file(review_path),
        "arm": args.arm,
        "capacity": args.capacity,
        "parameter_count": parameter_count(model),
        "device": str(device),
        "steps": args.steps,
        "eval_every": args.eval_every,
        "batch_size": args.batch_size,
        "overfit_count": args.overfit_count,
        "seed": args.seed,
        "learning_rate": args.learning_rate,
        "retention_weight": args.retention_weight,
        "schedule": str(schedule_path),
        "test_used": False,
        "target_gate_status": review.get("status"),
        "history": [],
    }
    (output / "run.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    if args.dry_run:
        print(json.dumps({key: metadata[key] for key in ("arm", "capacity", "parameter_count", "steps", "batch_size", "overfit_count", "test_used")}, indent=2))
        return

    best_target = float("inf")
    best_path: Path | None = None
    for step_index, ids in enumerate(schedule, start=1):
        model.train()
        inputs, teachers, targets = _batch(by_id, ids, device)
        prediction = model(inputs)
        if args.arm == "control":
            loss = (prediction - teachers).abs().mean()
            target_role = "dlss5_teacher"
        elif args.arm == "gen_a":
            loss = (prediction - targets).abs().mean()
            target_role = "enhanced_target"
        else:
            enhanced_loss = (prediction - targets).abs().mean()
            retention_loss = (prediction - teachers).abs().mean()
            loss = enhanced_loss + args.retention_weight * retention_loss
            target_role = "enhanced_target_plus_dlss5_retention"
        optimizer.zero_grad(set_to_none=True)
        loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
        optimizer.step()
        if step_index % args.eval_every == 0 or step_index == args.steps:
            metrics = _evaluate(model, validation_samples, device)
            metrics.update({"step": step_index, "train_loss": float(loss.detach().item())})
            metadata["history"].append(metrics)
            checkpoint = {
                "schema": "opennr-gen-static-checkpoint-v1",
                "step": step_index,
                "arm": args.arm,
                "capacity": args.capacity,
                "parameter_count": parameter_count(model),
                "manifest_sha256": manifest["manifest_sha256"],
                "target_records_sha256": metadata["target_records_sha256"],
                "target_review_sha256": metadata["target_review_sha256"],
                "test_used": False,
                "target_role": target_role,
                "model": model.state_dict(),
                "optimizer": optimizer.state_dict(),
                "metrics": metrics,
            }
            checkpoint_path = output / f"checkpoint_{step_index:06d}.pt"
            torch.save(checkpoint, checkpoint_path)
            if metrics["target_mae"] < best_target:
                best_target = metrics["target_mae"]
                best_path = output / "best.pt"
                torch.save(checkpoint, best_path)
            (output / "run.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
            print(json.dumps({"step": step_index, **metrics}))
    metadata["status"] = "complete"
    metadata["completed_utc"] = datetime.now(timezone.utc).isoformat()
    metadata["best_checkpoint"] = str(best_path) if best_path else None
    metadata["best_target_mae"] = best_target if best_path else None
    (output / "run.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": metadata["status"], "best_checkpoint": metadata["best_checkpoint"], "best_target_mae": metadata["best_target_mae"]}, indent=2))


if __name__ == "__main__":
    main()
