#!/usr/bin/env python3
"""Inventory embedded ELF/CUDA binary metadata inside a PE file.

The script records ELF headers, section metadata, and symbol names/counts.  It
does not write embedded ELF/PTX/cubin bytes to disk and does not execute them.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import struct
from pathlib import Path
from typing import Any


ELF_MAGIC = b"\x7fELF"


def find_offsets(data: bytes, needle: bytes) -> list[int]:
    result: list[int] = []
    start = 0
    while True:
        offset = data.find(needle, start)
        if offset < 0:
            return result
        result.append(offset)
        start = offset + 1


def bounded_elf_offsets(data: bytes) -> list[int]:
    """Find embedded ELF headers without scanning one Python offset at a time."""
    return find_offsets(data, ELF_MAGIC)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def c_string(blob: bytes, offset: int) -> str:
    if offset < 0 or offset >= len(blob):
        return ""
    end = blob.find(b"\x00", offset)
    if end < 0:
        end = len(blob)
    return blob[offset:end].decode("utf-8", errors="replace")


def safe_region(data: bytes, base: int, offset: int, size: int) -> bytes:
    start = base + offset
    end = start + size
    if start < 0 or end < start or end > len(data):
        return b""
    return data[start:end]


def printable_strings(blob: bytes, min_length: int = 4) -> list[str]:
    values: list[str] = []
    current = bytearray()
    for byte in blob:
        if 32 <= byte < 127:
            current.append(byte)
            continue
        if len(current) >= min_length:
            values.append(current.decode("ascii", errors="replace"))
        current.clear()
    if len(current) >= min_length:
        values.append(current.decode("ascii", errors="replace"))
    return values


def parse_elf(data: bytes, base: int, next_base: int | None) -> dict[str, Any]:
    result: dict[str, Any] = {
        "offset": base,
        "next_elf_offset": next_base,
        "parse_ok": False,
    }
    if base + 64 > len(data) or data[base : base + 4] != ELF_MAGIC:
        result["error"] = "not an ELF64 header"
        return result
    ident = data[base : base + 16]
    elf_class = ident[4]
    data_encoding = ident[5]
    result["ident"] = {
        "class": elf_class,
        "data": data_encoding,
        "version": ident[6],
        "osabi": ident[7],
    }
    if elf_class != 2 or data_encoding != 1:
        result["error"] = "unsupported ELF class or byte order"
        return result

    try:
        header_values = struct.unpack_from("<HHIQQQIHHHHHH", data, base + 16)
    except struct.error as exc:
        result["error"] = f"header unpack failed: {exc}"
        return result
    (
        e_type,
        e_machine,
        e_version,
        e_entry,
        e_phoff,
        e_shoff,
        e_flags,
        e_ehsize,
        e_phentsize,
        e_phnum,
        e_shentsize,
        e_shnum,
        e_shstrndx,
    ) = header_values
    result["header"] = {
        "type": e_type,
        "machine": e_machine,
        "version": e_version,
        "entry": e_entry,
        "program_header_offset": e_phoff,
        "section_header_offset": e_shoff,
        "flags": e_flags,
        "header_size": e_ehsize,
        "program_header_size": e_phentsize,
        "program_header_count": e_phnum,
        "section_header_size": e_shentsize,
        "section_count": e_shnum,
        "section_name_index": e_shstrndx,
    }

    # Do not infer an embedded file size from arbitrary padding.  The next ELF
    # marker is a useful upper bound for metadata parsing; section bounds are
    # checked against the complete PE file independently.
    upper_bound = next_base if next_base is not None else len(data)
    section_records: list[dict[str, Any]] = []
    section_headers: list[tuple[int, int, int, int, int, int, int, int, int, int]] = []
    for index in range(e_shnum):
        header_offset = base + e_shoff + index * e_shentsize
        if e_shentsize < 64 or header_offset + 64 > len(data):
            break
        values = struct.unpack_from("<IIQQQQIIQQ", data, header_offset)
        section_headers.append(values)
    if len(section_headers) != e_shnum:
        result["section_header_parse_count"] = len(section_headers)

    shstr = b""
    if 0 <= e_shstrndx < len(section_headers):
        shstr_header = section_headers[e_shstrndx]
        shstr = safe_region(data, base, shstr_header[4], shstr_header[5])
    section_names: list[str] = []
    for index, values in enumerate(section_headers):
        (
            sh_name,
            sh_type,
            sh_flags,
            sh_addr,
            sh_offset,
            sh_size,
            sh_link,
            sh_info,
            sh_addralign,
            sh_entsize,
        ) = values
        name = c_string(shstr, sh_name)
        section_names.append(name)
        record: dict[str, Any] = {
            "index": index,
            "name": name,
            "type": sh_type,
            "flags": sh_flags,
            "address": sh_addr,
            "offset": sh_offset,
            "size": sh_size,
            "link": sh_link,
            "info": sh_info,
            "alignment": sh_addralign,
            "entry_size": sh_entsize,
            "within_next_elf_bound": base + sh_offset + sh_size <= upper_bound,
        }
        section_records.append(record)
    result["sections"] = section_records
    result["section_names"] = section_names

    string_tables: dict[int, bytes] = {}
    for index, values in enumerate(section_headers):
        if values[1] == 3:  # SHT_STRTAB
            string_tables[index] = safe_region(data, base, values[4], values[5])

    symbols: list[dict[str, Any]] = []
    symbol_sections = {2, 11}  # SHT_SYMTAB and SHT_DYNSYM
    for section_index, values in enumerate(section_headers):
        if values[1] not in symbol_sections:
            continue
        section_offset, section_size, string_index, entry_size = values[4], values[5], values[6], values[9]
        if entry_size < 24:
            entry_size = 24
        string_table = string_tables.get(string_index, b"")
        available = safe_region(data, base, section_offset, section_size)
        count = len(available) // entry_size
        for symbol_index in range(count):
            symbol_offset = symbol_index * entry_size
            try:
                st_name, st_info, st_other, st_shndx, st_value, st_size = struct.unpack_from(
                    "<IBBHQQ", available, symbol_offset
                )
            except struct.error:
                break
            name = c_string(string_table, st_name)
            if not name:
                continue
            symbols.append({
                "table_section": section_names[section_index] if section_index < len(section_names) else section_index,
                "index": symbol_index,
                "name": name,
                "binding": st_info >> 4,
                "type": st_info & 0x0F,
                "section_index": st_shndx,
                "value": st_value,
                "size": st_size,
            })
    result["symbol_count"] = len(symbols)
    # Names are metadata useful for mapping launch entry points; cap the full
    # list and separately retain likely kernel symbols.
    result["kernel_like_symbols"] = [
        item for item in symbols
        if any(token in item["name"].lower() for token in ("kernel", "k_", "cubin", "swin", "attn", "ffwd", "conv", "reproject"))
    ][:2048]
    result["symbol_name_sample"] = [item["name"] for item in symbols[:256]]

    # Collect only short, recognizable architecture markers from the ELF's
    # bounded region.  This avoids dumping arbitrary proprietary strings.
    bounded_start = base
    bounded_end = min(len(data), upper_bound)
    bounded = data[bounded_start:bounded_end]
    strings = printable_strings(bounded)
    selected = sorted({
        value for value in strings
        if any(token in value.lower() for token in ("sm_", "compute_", "ptx", "cubin", "fatbin", "kernel", "k_"))
    })
    result["architecture_string_sample"] = selected[:512]
    result["parse_ok"] = True
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dll", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    path = args.dll.resolve()
    output = args.output.resolve()
    data = path.read_bytes()
    offsets = bounded_elf_offsets(data)
    elfs = [parse_elf(data, offset, offsets[index + 1] if index + 1 < len(offsets) else None) for index, offset in enumerate(offsets)]
    inventory = {
        "analysis": {
            "tool": "inventory_embedded_cuda_elf.py",
            "mode": "read-only ELF metadata and symbol inventory",
            "embedded_payloads_extracted": False,
            "embedded_payloads_executed": False,
        },
        "file": {
            "path": str(path),
            "size": len(data),
            "sha256": sha256_file(path),
        },
        "elf_count": len(elfs),
        "elf_offsets": offsets,
        "elfs": elfs,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(inventory, indent=2), encoding="utf-8")
    print(json.dumps({
        "output": str(output),
        "sha256": inventory["file"]["sha256"],
        "elf_count": len(elfs),
        "elf_offsets": [f"0x{offset:X}" for offset in offsets],
        "parsed": sum(1 for item in elfs if item.get("parse_ok")),
        "section_counts": [len(item.get("sections", [])) for item in elfs],
        "symbol_counts": [item.get("symbol_count", 0) for item in elfs],
        "kernel_like_symbol_counts": [len(item.get("kernel_like_symbols", [])) for item in elfs],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
