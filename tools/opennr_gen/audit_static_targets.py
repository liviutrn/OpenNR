"""Audit OpenNR-GEN target completeness, hashes, and the first visual gate."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REQUIRED_CHECKS = (
    "teacher_preference",
    "identity_and_face",
    "geometry_and_objects",
    "material_fidelity",
    "lighting_direction",
    "stereo_pair_consistency",
)


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


def _load_manifest(path: Path) -> dict[str, Any]:
    manifest = json.loads(path.read_text(encoding="utf-8"))
    recorded = manifest.get("manifest_sha256")
    body = dict(manifest)
    body.pop("manifest_sha256", None)
    if canonical_sha256(body) != recorded:
        raise ValueError("manifest hash mismatch")
    if manifest.get("source_test_used_for_tuning") is not False:
        raise ValueError("source test split is not protected")
    return manifest


def _review_template(manifest: dict[str, Any], records_path: Path) -> dict[str, Any]:
    return {
        "schema": "opennr-gen-target-review-v1",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "status": "pending",
        "target_records": str(records_path.resolve()),
        "instructions": [
            "Compare every raw/teacher/target triplet and both eyes.",
            "Use accept only when the target is preferable to the DLSS5 teacher and all checks pass.",
            "Use reject for hallucinated geometry/identity/material/lighting/stereo artifacts.",
            "Use rerun_lower_strength when the target is promising but diffusion strength is too aggressive.",
        ],
        "allowed_decisions": ["accept", "reject", "rerun_lower_strength"],
        "allowed_check_values": ["pass", "fail", "pending"],
        "required_checks": list(REQUIRED_CHECKS),
        "samples": [
            {
                "sample_id": sample["sample_id"],
                "pair_id": sample["pair_id"],
                "eye": sample["eye"],
                "decision": "pending",
                **{check: "pending" for check in REQUIRED_CHECKS},
                "note": "",
            }
            for sample in manifest["samples"]
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--target-records", type=Path, required=True)
    parser.add_argument("--review", type=Path)
    parser.add_argument("--write-review-template", type=Path)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--require-accepted", action="store_true")
    args = parser.parse_args()

    manifest_path = args.manifest.resolve()
    records_path = args.target_records.resolve()
    manifest = _load_manifest(manifest_path)
    if not records_path.exists():
        raise FileNotFoundError(records_path)
    records = json.loads(records_path.read_text(encoding="utf-8"))
    if records.get("schema") != "opennr-gen-static-target-records-v1":
        raise ValueError("unsupported target-records schema")
    if records.get("manifest_sha256") != manifest["manifest_sha256"]:
        raise ValueError("target records reference a different static manifest")

    expected = {sample["sample_id"]: sample for sample in manifest["samples"]}
    actual = records.get("samples", {})
    missing_records = sorted(set(expected) - set(actual))
    mismatched: list[str] = []
    complete_target_ids: list[str] = []
    for sample_id, sample in expected.items():
        record = actual.get(sample_id)
        if record is None:
            continue
        if record.get("status") in {"generated", "skipped_existing"}:
            complete_target_ids.append(sample_id)
            target = Path(sample["enhanced_target_path"])
            if not target.exists() or record.get("target_sha256") != sha256_file(target):
                mismatched.append(sample_id + ":target")
            for key, path_key in (("raw_input_sha256", "raw_input_path"), ("teacher_sha256", "teacher_path")):
                source = Path(sample[path_key])
                if not source.exists() or record.get(key) != sha256_file(source):
                    mismatched.append(sample_id + ":" + path_key)
        elif record.get("status") not in {"skipped_existing", "running"}:
            mismatched.append(sample_id + ":status")

    pairs: dict[str, list[str]] = defaultdict(list)
    for sample in manifest["samples"]:
        pairs[sample["pair_id"]].append(sample["sample_id"])
    incomplete_pairs = sorted(
        pair_id
        for pair_id, sample_ids in pairs.items()
        if not all(item in complete_target_ids for item in sample_ids)
    )

    review_payload = None
    review_status = "not_provided"
    accepted = rejected = rerun = pending = 0
    if args.review and args.review.exists():
        review_payload = json.loads(args.review.resolve().read_text(encoding="utf-8"))
        if review_payload.get("schema") != "opennr-gen-target-review-v1":
            raise ValueError("unsupported target review schema")
        by_id = {item["sample_id"]: item for item in review_payload.get("samples", [])}
        if set(by_id) != set(expected):
            raise ValueError("target review does not cover exactly the manifest samples")
        for sample_id, item in by_id.items():
            decision = item.get("decision")
            if decision == "accept":
                accepted += 1
            elif decision == "reject":
                rejected += 1
            elif decision == "rerun_lower_strength":
                rerun += 1
            elif decision == "pending":
                pending += 1
            else:
                raise ValueError(f"invalid decision for {sample_id}: {decision!r}")
            for check in REQUIRED_CHECKS:
                if item.get(check) not in {"pass", "fail", "pending"}:
                    raise ValueError(f"invalid {check} for {sample_id}")
        review_status = review_payload.get("status", "unknown")

    all_accepted = (
        len(complete_target_ids) == len(expected)
        and not mismatched
        and not incomplete_pairs
        and review_payload is not None
        and accepted == len(expected)
        and rejected == 0
        and rerun == 0
        and pending == 0
        and all(
            item.get(check) == "pass"
            for item in review_payload["samples"]
            for check in REQUIRED_CHECKS
        )
    )
    result = {
        "schema": "opennr-gen-static-target-audit-v1",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "manifest": str(manifest_path),
        "manifest_sha256": manifest["manifest_sha256"],
        "target_records": str(records_path),
        "target_records_sha256": sha256_file(records_path),
        "expected_count": len(expected),
        "generated_count": len(complete_target_ids),
        "missing_record_count": len(missing_records),
        "missing_records": missing_records,
        "hash_mismatch_count": len(mismatched),
        "hash_mismatches": mismatched,
        "incomplete_pair_count": len(incomplete_pairs),
        "incomplete_pairs": incomplete_pairs,
        "review_status": review_status,
        "accepted_count": accepted,
        "rejected_count": rejected,
        "rerun_count": rerun,
        "pending_count": pending,
        "target_gate": "accepted" if all_accepted else "pending_or_failed",
        "student_training_allowed": all_accepted,
    }
    if args.write_review_template:
        template_path = args.write_review_template.resolve()
        template_path.parent.mkdir(parents=True, exist_ok=True)
        template_path.write_text(json.dumps(_review_template(manifest, records_path), indent=2) + "\n", encoding="utf-8")
        result["review_template"] = str(template_path)
    report_path = args.report.resolve() if args.report else records_path.parent / "target_audit.json"
    report_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    if args.require_accepted and not all_accepted:
        raise SystemExit(2)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"GEN target audit failed: {exc}", file=sys.stderr)
        raise
