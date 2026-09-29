#!/usr/bin/env python3
"""Verify the public Safetensors mirror against the local extracted records."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--safetensors", type=Path, required=True)
    parser.add_argument("--weights", type=Path, required=True)
    parser.add_argument("--backend", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    backend = args.backend.resolve()
    if str(backend) not in sys.path:
        sys.path.insert(0, str(backend))
    from nr_backend.weights import load_pinned_records
    from safetensors import safe_open

    safetensors_path = args.safetensors.resolve()
    local_records = load_pinned_records(args.weights.resolve())
    mismatches: list[dict[str, object]] = []
    checked = 0
    with safe_open(str(safetensors_path), framework="pt", device="cpu") as reader:
        keys = list(reader.keys())
        raw_keys = [key for key in keys if key.startswith("_raw.")]
        metadata = reader.metadata() or {}
        manifest_text = metadata.get("open_dlss5_manifest")
        if not manifest_text:
            raise ValueError("public file has no open_dlss_manifest metadata")
        manifest = json.loads(manifest_text)
        manifest_weights = {
            entry["name"]: entry for entry in manifest.get("weights", [])
        }
        for name, expected in local_records.items():
            checked += 1
            entry = manifest_weights.get(name)
            if entry is None:
                mismatches.append({"name": name, "reason": "missing from manifest"})
                continue
            actual_sha = sha256_bytes(expected)
            if entry.get("sha256") != actual_sha:
                mismatches.append({
                    "name": name,
                    "reason": "bytes differ",
                    "local_sha256": actual_sha,
                    "manifest_sha256": entry.get("sha256"),
                })

    result = {
        "schema": "opennr-public-safetensors-provenance-v1",
        "safetensors": str(safetensors_path),
        "safetensors_size": safetensors_path.stat().st_size,
        "safetensors_sha256": sha256_bytes(safetensors_path.read_bytes()),
        "safetensors_tensor_count": len(keys),
        "safetensors_raw_record_count": len(raw_keys),
        "public_manifest_raw_records": manifest.get("raw_records"),
        "public_manifest_weight_count": manifest.get("weight_count"),
        "local_record_count": len(local_records),
        "records_checked": checked,
        "mismatch_count": len(mismatches),
        "mismatches": mismatches,
        "metadata_source_sha256": metadata.get("source_sha256"),
        "metadata_resource_sha256": metadata.get("resource_sha256"),
        "metadata": metadata,
        "scope": (
            "read-only comparison of the public manifest's 153 per-record "
            "hashes with the locally hash-pinned extracted resource; the "
            "public file excludes raw records; no external executable was "
            "loaded or executed"
        ),
    }
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    return 0 if not mismatches else 1


if __name__ == "__main__":
    raise SystemExit(main())
