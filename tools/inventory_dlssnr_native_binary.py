#!/usr/bin/env python3
"""Read-only inventory of a DLSS-NR PE binary.

This deliberately records metadata, offsets, and marker counts only.  It does
not extract, execute, or copy embedded proprietary payloads.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import struct
from pathlib import Path
from typing import Any


MARKERS: dict[str, bytes] = {
    "nv_relfatbin": b"__nv_relfatbin",
    "nv_fatbin": b"__nv_fatbin",
    "cuda_fat_cubin": b"__cudaFatCubin",
    "clang_offload_bundle": b"__CLANG_OFFLOAD_BUNDLE__",
    "nv_fatbin_section": b".nv_fatbin",
    "nv_fat_bin_segment": b".nvFatBinSegment",
    "ptx": b"PTX",
    "ptxas": b"ptxas",
    "cubin_lower": b"cubin",
    "cubin_upper": b"CUBIN",
    "sm_120": b"sm_120",
    "compute_120": b"compute_120",
    "sm_100": b"sm_100",
    "compute_100": b"compute_100",
    "version_directive": b".version ",
    "target_directive": b".target ",
    "address_size_directive": b".address_size ",
    "weight_resource_name": b"WEIGHTS_HT",
    "dlssnr": b"DLSSNR",
}

MAGIC_MARKERS: dict[str, bytes] = {
    "mz": b"MZ",
    "pe": b"PE\x00\x00",
    "elf": b"\x7fELF",
    "gzip": b"\x1f\x8b",
    "zlib_78_01": b"\x78\x01",
    "zlib_78_5e": b"\x78\x5e",
    "zlib_78_9c": b"\x78\x9c",
    "zlib_78_da": b"\x78\xda",
}


def find_offsets(data: bytes, needle: bytes, limit: int = 128) -> list[int]:
    offsets: list[int] = []
    start = 0
    while len(offsets) < limit:
        pos = data.find(needle, start)
        if pos < 0:
            break
        offsets.append(pos)
        start = pos + 1
    return offsets


def count_occurrences(data: bytes, needle: bytes) -> int:
    count = 0
    start = 0
    while True:
        pos = data.find(needle, start)
        if pos < 0:
            return count
        count += 1
        start = pos + 1


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def entropy(blob: bytes) -> float | None:
    if not blob:
        return None
    counts = [0] * 256
    for value in blob:
        counts[value] += 1
    total = len(blob)
    return -sum((count / total) * math.log2(count / total) for count in counts if count)


def safe_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def safe_text(value: Any) -> str | None:
    if value is None:
        return None
    try:
        return str(value)
    except Exception:
        return None


def lief_inventory(path: Path, data: bytes) -> dict[str, Any]:
    result: dict[str, Any] = {"available": False}
    try:
        import lief  # type: ignore
    except Exception as exc:
        result["error"] = f"lief import failed: {type(exc).__name__}: {exc}"
        return result

    result["available"] = True
    try:
        binary = lief.parse(str(path))
        if binary is None:
            result["error"] = "lief.parse returned None"
            return result
        result["format"] = safe_text(getattr(binary, "format", None))
        result["header"] = {
            "entrypoint": safe_int(getattr(binary, "entrypoint", None)),
            "imagebase": safe_int(getattr(binary, "imagebase", None)),
            "virtual_size": safe_int(getattr(binary, "virtual_size", None)),
        }
        sections: list[dict[str, Any]] = []
        for section in getattr(binary, "sections", []):
            item: dict[str, Any] = {
                "name": safe_text(getattr(section, "name", None)),
                "offset": safe_int(getattr(section, "offset", None)),
                "size": safe_int(getattr(section, "size", None)),
                "virtual_address": safe_int(getattr(section, "virtual_address", None)),
                "virtual_size": safe_int(getattr(section, "virtual_size", None)),
                "entropy": None,
            }
            offset = item["offset"]
            size = item["size"]
            if isinstance(offset, int) and isinstance(size, int) and offset >= 0 and size >= 0:
                item["entropy"] = entropy(data[offset : offset + size])
            characteristics = getattr(section, "characteristics", None)
            if characteristics is not None:
                item["characteristics"] = safe_text(characteristics)
            sections.append(item)
        result["sections"] = sections

        imports: list[dict[str, Any]] = []
        for imported in getattr(binary, "imports", []):
            functions: list[str] = []
            for function in getattr(imported, "entries", []):
                name = safe_text(getattr(function, "name", None))
                if name:
                    functions.append(name)
            imports.append({
                "name": safe_text(getattr(imported, "name", None)),
                "functions": functions[:512],
                "function_count": len(functions),
            })
        result["imports"] = imports

        exported: list[str] = []
        for function in getattr(binary, "exported_functions", []):
            name = safe_text(function)
            if name:
                exported.append(name)
        result["exported_functions"] = exported[:4096]
        result["export_count"] = len(exported)

        # Resource traversal is intentionally shallow and metadata-only.  LIEF
        # has changed its resource API across releases, so capture what is
        # exposed without depending on one exact version.
        resources = getattr(binary, "resources", None)
        result["resource_api"] = {
            "present": resources is not None,
            "type": safe_text(type(resources).__name__) if resources is not None else None,
        }
        try:
            manager = getattr(binary, "resources_manager", None)
            result["resource_manager_api"] = {
                "present": manager is not None,
                "type": safe_text(type(manager).__name__) if manager is not None else None,
                "dir": sorted(name for name in dir(manager) if not name.startswith("_"))[:128]
                if manager is not None
                else [],
            }
        except Exception as exc:
            result["resource_manager_api_error"] = f"{type(exc).__name__}: {exc}"
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dll", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    path = args.dll.resolve()
    output = args.output.resolve()
    if not path.is_file():
        raise SystemExit(f"DLL not found: {path}")

    data = path.read_bytes()
    inventory: dict[str, Any] = {
        "analysis": {
            "tool": "inventory_dlssnr_native_binary.py",
            "mode": "read-only metadata and marker scan",
            "proprietary_bytes_extracted": False,
        },
        "file": {
            "path": str(path),
            "size": len(data),
            "sha256": sha256_file(path),
        },
        "markers": {},
        "magic_markers": {},
        "lief": lief_inventory(path, data),
    }

    for name, marker in MARKERS.items():
        offsets = find_offsets(data, marker)
        inventory["markers"][name] = {
            "needle_hex": marker.hex(),
            "count": count_occurrences(data, marker),
            "first_offsets": offsets,
        }
    for name, marker in MAGIC_MARKERS.items():
        offsets = find_offsets(data, marker)
        inventory["magic_markers"][name] = {
            "needle_hex": marker.hex(),
            "count": count_occurrences(data, marker),
            "first_offsets": offsets,
        }

    # Look for CUDA/PTX-like byte sequences independent of ASCII symbol names.
    # These values are reported as offsets only; no payload is written out.
    binary_patterns: dict[str, bytes] = {
        "dlss_fatbin_header_ba55ed50_little_endian": struct.pack("<I", 0xBA55ED50),
        "zstd_frame_magic_little_endian": struct.pack("<I", 0x28B52FFD),
        "cuda_fatbin_magic_little_endian": struct.pack("<I", 0x466243B1),
        "cuda_fatbin_magic_big_endian": struct.pack(">I", 0x466243B1),
        "fatbin_wrapper_magic_little_endian": struct.pack("<I", 0x1EE55A7A),
        "fatbin_wrapper_magic_big_endian": struct.pack(">I", 0x1EE55A7A),
    }
    inventory["binary_patterns"] = {}
    for name, marker in binary_patterns.items():
        offsets = find_offsets(data, marker)
        inventory["binary_patterns"][name] = {
            "needle_hex": marker.hex(),
            "count": count_occurrences(data, marker),
            "first_offsets": offsets,
        }

    fatbin_magic = binary_patterns["dlss_fatbin_header_ba55ed50_little_endian"]
    fatbin_offsets = find_offsets(data, fatbin_magic)
    fatbin_headers: list[dict[str, Any]] = []
    for index, offset in enumerate(fatbin_offsets):
        header = data[offset : offset + 64]
        record: dict[str, Any] = {
            "index": index,
            "offset": offset,
            "next_header_offset": fatbin_offsets[index + 1] if index + 1 < len(fatbin_offsets) else None,
            "header_bytes_available": len(header),
        }
        if len(header) >= 32:
            words = struct.unpack_from("<8I", header, 0)
            record["u32_words_0_7_hex"] = [f"0x{word:08X}" for word in words]
            record["payload_size_u64_at_8"] = struct.unpack_from("<Q", header, 8)[0]
            record["compressed_size_u64_at_16"] = struct.unpack_from("<Q", header, 16)[0]
            record["arch_u32_at_28"] = struct.unpack_from("<I", header, 28)[0]
        fatbin_headers.append(record)
    inventory["fatbin_headers"] = fatbin_headers

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(inventory, indent=2), encoding="utf-8")
    print(json.dumps({
        "output": str(output),
        "size": len(data),
        "sha256": inventory["file"]["sha256"],
        "lief_error": inventory["lief"].get("error"),
        "section_count": len(inventory["lief"].get("sections", [])),
        "markers": {
            name: item["count"]
            for name, item in inventory["markers"].items()
            if item["count"]
        },
        "magic_markers": {
            name: item["count"]
            for name, item in inventory["magic_markers"].items()
            if item["count"]
        },
        "binary_patterns": {
            name: item["count"]
            for name, item in inventory["binary_patterns"].items()
            if item["count"]
        },
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
