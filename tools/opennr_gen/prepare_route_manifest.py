"""Clone a prepared static GEN manifest for an isolated enhancer route."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while block := handle.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def canonical_sha256(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _load_manifest(path: Path) -> dict[str, Any]:
    manifest = json.loads(path.read_text(encoding="utf-8"))
    recorded = manifest.get("manifest_sha256")
    body = dict(manifest)
    body.pop("manifest_sha256", None)
    if not recorded or canonical_sha256(body) != recorded:
        raise ValueError("source manifest hash does not match its contents")
    if manifest.get("source_test_used_for_tuning") is not False:
        raise ValueError("source manifest does not explicitly protect its test split")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-manifest", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--route-name", required=True)
    parser.add_argument("--coverage-review", type=Path)
    args = parser.parse_args()

    source_manifest_path = args.source_manifest.resolve()
    source = _load_manifest(source_manifest_path)
    output_root = args.output_root.resolve()
    output_root.mkdir(parents=True, exist_ok=True)

    samples: list[dict[str, Any]] = []
    for source_sample in source["samples"]:
        sample = dict(source_sample)
        sample_id = str(sample["sample_id"])
        sample_dir = output_root / "samples" / sample_id
        sample_dir.mkdir(parents=True, exist_ok=True)

        raw_source = Path(sample["raw_input_path"]).resolve()
        teacher_source = Path(sample["teacher_path"]).resolve()
        if not raw_source.is_file() or not teacher_source.is_file():
            raise FileNotFoundError(f"missing source image for {sample_id}")

        raw_target = sample_dir / "raw_input.png"
        teacher_target = sample_dir / "dlss5_teacher.png"
        shutil.copy2(raw_source, raw_target)
        shutil.copy2(teacher_source, teacher_target)

        if sha256_file(raw_source) != sha256_file(raw_target):
            raise ValueError(f"raw copy hash mismatch for {sample_id}")
        if sha256_file(teacher_source) != sha256_file(teacher_target):
            raise ValueError(f"teacher copy hash mismatch for {sample_id}")

        sample["raw_input_path"] = str(raw_target)
        sample["teacher_path"] = str(teacher_target)
        sample["enhanced_target_path"] = str(sample_dir / "enhanced_target.png")
        samples.append(sample)

    body = dict(source)
    parent_hash = body.pop("manifest_sha256")
    body["created_utc"] = datetime.now(timezone.utc).isoformat()
    body["parent_manifest"] = str(source_manifest_path)
    body["parent_manifest_sha256"] = parent_hash
    body["target_route"] = args.route_name
    body["samples"] = samples
    body["eye_image_count"] = len(samples)
    body["manifest_sha256"] = canonical_sha256(body)

    manifest_path = output_root / "manifest.json"
    manifest_path.write_text(json.dumps(body, indent=2) + "\n", encoding="utf-8")
    (output_root / "manifest.sha256").write_text(
        f"{body['manifest_sha256']}  manifest.json\n", encoding="utf-8"
    )

    if args.coverage_review:
        coverage_path = args.coverage_review.resolve()
        coverage = json.loads(coverage_path.read_text(encoding="utf-8"))
        coverage["manifest"] = str(manifest_path)
        coverage["parent_manifest"] = str(source_manifest_path)
        coverage["parent_manifest_sha256"] = parent_hash
        (output_root / "coverage_review.json").write_text(
            json.dumps(coverage, indent=2) + "\n", encoding="utf-8"
        )

    print(
        json.dumps(
            {
                "manifest": str(manifest_path),
                "manifest_sha256": body["manifest_sha256"],
                "parent_manifest_sha256": parent_hash,
                "route_name": args.route_name,
                "scene_count": body["scene_count"],
                "eye_image_count": len(samples),
                "source_test_used_for_tuning": body["source_test_used_for_tuning"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
