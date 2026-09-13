#!/usr/bin/env python3
"""Reconstruct the DLSSNR serialized resource map from extracted packed tensors.

The packed Safetensors file intentionally keeps each WEIGHTS_HT payload and
its original record metadata separately.  This utility rebuilds the resource
container for offline compatibility tests; it does not extract anything from
or modify a DLL.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import struct

import numpy as np
from safetensors import safe_open


def _record(name: str, payload: bytes, metadata: dict[str, object]) -> bytes:
    dimensions = tuple(int(value) for value in metadata["dimensions"])
    if not dimensions or any(value <= 0 for value in dimensions):
        raise ValueError(f"invalid dimensions for {name}")
    byte_count = int(metadata["byteCount"])
    if byte_count != len(payload):
        raise ValueError(f"byte count mismatch for {name}: {byte_count} != {len(payload)}")
    # The serialized map stores ``outer_size`` before the body.  The size
    # counts the body beginning with inner_size; it does not count the
    # outer_size field itself.
    body_size = 8 + 8 + 4 + byte_count + 4 + 4 + 8 + 4 * len(dimensions)
    body = b"".join(
        (
            struct.pack("<Q", body_size),
            struct.pack("<Q", byte_count),
            struct.pack("<I", int(metadata["dtypeCode"])),
            payload,
            struct.pack(
                "<IIQ",
                int(metadata["metadata0"]),
                int(metadata["metadata1"]),
                len(dimensions),
            ),
            struct.pack("<" + "I" * len(dimensions), *dimensions),
        )
    )
    if len(body) != body_size:
        raise AssertionError(f"internal record size mismatch for {name}")
    return (
        struct.pack("<Q", len(name.encode("utf-8")))
        + name.encode("utf-8")
        + struct.pack("<Q", body_size)
        + body
    )


def rebuild(source: Path, destination: Path) -> dict[str, object]:
    if destination.exists():
        raise FileExistsError(destination)
    with safe_open(str(source), framework="numpy", device="cpu") as handle:
        metadata = handle.metadata() or {}
        if metadata.get("format") != "dlssnr-WEIGHTS_HT-packed-u8-v2":
            raise ValueError("source is not the expected packed DLSSNR Safetensors format")
        records = json.loads(metadata["source_tensor_records"])
        names = sorted(handle.keys())
        if names != sorted(records):
            raise ValueError("Safetensors keys and source record metadata differ")
        encoded_records = []
        for name in names:
            payload = np.asarray(handle.get_tensor(name), dtype=np.uint8).reshape(-1).tobytes()
            encoded_records.append(_record(name, payload, records[name]))

    blob = struct.pack("<Q", 0) + b"".join(encoded_records)
    blob = struct.pack("<Q", len(blob)) + blob[8:]
    digest = hashlib.sha256(blob).hexdigest()
    expected = str(metadata.get("resource_sha256", "")).lower()
    if expected and digest != expected:
        raise ValueError(
            f"reconstructed resource hash mismatch: expected {expected}, got {digest}"
        )
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(blob)
    manifest = {
        "schema": "opennr-dlssnr-resource-map-reconstruction-v1",
        "source": str(source.resolve()),
        "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "resource_sha256": digest,
        "expected_resource_sha256": expected or None,
        "tensor_count": len(names),
        "bytes": len(blob),
        "destination": str(destination.resolve()),
        "status": "hash_verified" if expected and digest == expected else "reconstructed",
        "scope": "offline serialized weight-envelope reconstruction; no DLL or game mutation",
    }
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--packed", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--manifest", type=Path)
    args = parser.parse_args()
    manifest = rebuild(args.packed.resolve(), args.output.resolve())
    manifest_path = (args.manifest or args.output.with_suffix(args.output.suffix + ".json")).resolve()
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
