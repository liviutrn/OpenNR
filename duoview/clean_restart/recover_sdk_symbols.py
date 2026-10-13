"""Extract evidence from the PDB paired with the pinned official Joey DLL.

This reads CodeView records; it does not reconstruct or modify SDK source.
Unknown field records are retained as hex rather than interpreted guesses.
"""

import argparse
from array import array
import hashlib
import json
from pathlib import Path
import struct
import uuid


def integer(data, offset, fmt="I"):
    return struct.unpack_from("<" + fmt, data, offset)[0]


def string(data, offset):
    end = data.index(0, offset)
    return data[offset:end].decode("utf-8", errors="replace"), end + 1


def numeric(data, offset):
    leaf = integer(data, offset, "H")
    if leaf < 0x8000:
        return leaf, offset + 2
    formats = {0x8000: "b", 0x8001: "h", 0x8002: "H", 0x8003: "i",
               0x8004: "I", 0x8009: "q", 0x800A: "Q"}
    if leaf not in formats:
        raise ValueError(f"Unsupported numeric leaf {leaf:#x}")
    fmt = formats[leaf]
    return integer(data, offset + 2, fmt), offset + 2 + struct.calcsize(fmt)


class Pdb:
    def __init__(self, path):
        self.file = path.open("rb")
        self.size = path.stat().st_size
        header = self.file.read(56)
        if not header.startswith(b"Microsoft C/C++ MSF 7.00\r\n\x1aDS\x00\x00\x00"):
            raise ValueError("Expected MSF 7.00 PDB")
        self.block_size = integer(header, 32)
        if self.block_size not in {512, 1024, 2048, 4096, 8192}:
            raise ValueError("Unsupported PDB block size")
        directory_size = integer(header, 44)
        block_map = integer(header, 52)
        count = (directory_size + self.block_size - 1) // self.block_size
        if count * 4 > self.block_size:
            raise ValueError("Multi-block directory map is not supported")
        blocks = struct.unpack("<" + "I" * count,
                               self.read_at(block_map * self.block_size, count * 4))
        directory = self.read_blocks(blocks)[:directory_size]
        count = integer(directory, 0)
        sizes = struct.unpack_from("<" + "I" * count, directory, 4)
        offset = 4 + count * 4
        self.streams = []
        for size in sizes:
            n = 0 if size == 0xFFFFFFFF else (size + self.block_size - 1) // self.block_size
            blocks = struct.unpack_from("<" + "I" * n, directory, offset)
            offset += n * 4
            self.streams.append((size, blocks))

    def read_at(self, offset, size):
        if offset < 0 or size < 0 or offset > self.size or size > self.size - offset:
            raise ValueError("PDB range outside file")
        self.file.seek(offset)
        result = self.file.read(size)
        if len(result) != size:
            raise ValueError("Truncated PDB")
        return result

    def read_blocks(self, blocks):
        return b"".join(self.read_at(b * self.block_size, self.block_size) for b in blocks)

    def stream(self, index):
        size, blocks = self.streams[index]
        if size == 0xFFFFFFFF:
            raise ValueError("Absent PDB stream")
        return self.read_blocks(blocks)[:size]


class Types:
    def __init__(self, data):
        self.data = data
        self.begin = integer(data, 8)
        self.end = integer(data, 12)
        offset = integer(data, 4)
        limit = offset + integer(data, 16)
        if limit > len(data):
            raise ValueError("Truncated type stream")
        self.offsets = array("I")
        self.lengths = array("H")
        while offset < limit:
            length = integer(data, offset, "H")
            if length < 2 or offset + 2 + length > limit:
                raise ValueError("Invalid type record")
            self.offsets.append(offset + 2)
            self.lengths.append(length)
            offset += 2 + length
        if len(self.offsets) != self.end - self.begin or offset != limit:
            raise ValueError("Type-index count mismatch")

    def record(self, index):
        if not self.begin <= index < self.end:
            return None
        slot = index - self.begin
        offset = self.offsets[slot]
        return self.data[offset:offset + self.lengths[slot]]

    def named(self, index):
        record = self.record(index)
        if record is None:
            return {"index": hex(index), "primitive": True}
        leaf = integer(record, 0, "H")
        result = {"index": hex(index), "leaf": hex(leaf)}
        if leaf in {0x1504, 0x1505}:
            size, offset = numeric(record, 18)
            result.update(name=string(record, offset)[0], size=size,
                          forward=bool(integer(record, 4, "H") & 0x80),
                          field_list=hex(integer(record, 6)))
        elif leaf == 0x1506:
            size, offset = numeric(record, 10)
            result.update(name=string(record, offset)[0], size=size,
                          forward=bool(integer(record, 4, "H") & 0x80),
                          field_list=hex(integer(record, 6)))
        elif leaf == 0x1507:
            result.update(name=string(record, 14)[0],
                          forward=bool(integer(record, 4, "H") & 0x80),
                          field_list=hex(integer(record, 10)))
        return result

    def fields(self, index, visited=None):
        visited = set() if visited is None else visited
        if index in visited:
            raise ValueError("Cyclic field-list continuation")
        visited.add(index)
        record = self.record(index)
        if record is None or integer(record, 0, "H") != 0x1203:
            return []
        offset, fields = 2, []
        while offset < len(record):
            if record[offset] >= 0xF0:
                padding = record[offset] & 0xF
                if padding == 0:
                    raise ValueError("Zero-length CodeView padding")
                offset += padding
                continue
            start = offset
            leaf = integer(record, offset, "H")
            field = {"leaf": hex(leaf)}
            if leaf == 0x150D:
                field["type"] = self.named(integer(record, offset + 4))
                value, offset = numeric(record, offset + 8)
                name, offset = string(record, offset)
                field.update(name=name, offset=value, kind="member")
            elif leaf == 0x150E:
                field["type"] = self.named(integer(record, offset + 4))
                name, offset = string(record, offset + 8)
                field.update(name=name, kind="static_member")
            elif leaf == 0x1502:
                value, offset = numeric(record, offset + 4)
                name, offset = string(record, offset)
                field.update(name=name, value=value, kind="enumerator")
            elif leaf in {0x150F, 0x1510}:
                field["type"] = self.named(integer(record, offset + 4))
                name, offset = string(record, offset + 8)
                field.update(name=name, kind="method_group" if leaf == 0x150F else "nested_type")
            elif leaf == 0x1511:
                attributes = integer(record, offset + 2, "H")
                field["type"] = self.named(integer(record, offset + 4))
                offset += 8
                if (attributes >> 2) & 7 in {4, 6}:
                    field["vtable_offset"] = integer(record, offset, "i")
                    offset += 4
                name, offset = string(record, offset)
                field.update(name=name, kind="method")
            elif leaf == 0x1400:
                field["type"] = self.named(integer(record, offset + 4))
                value, offset = numeric(record, offset + 8)
                field.update(offset=value, kind="base_class")
            elif leaf == 0x1404:
                fields.extend(self.fields(integer(record, offset + 4), visited))
                offset += 8
                continue
            elif leaf == 0x1409:
                field.update(type=self.named(integer(record, offset + 4)), kind="vtable")
                offset += 8
            else:
                fields.append({"leaf": hex(leaf), "unparsed_remainder_hex": record[start:].hex()})
                break
            fields.append(field)
        return fields

    def sdk_types(self):
        result = []
        for index in range(self.begin, self.end):
            slot = index - self.begin
            leaf = integer(self.data, self.offsets[slot], "H")
            if leaf not in {0x1504, 0x1505, 0x1506, 0x1507}:
                continue
            item = self.named(index)
            if item.get("name", "").startswith("sdk::") and not item.get("forward"):
                item["fields"] = self.fields(int(item["field_list"], 16))
                result.append(item)
        return result


def symbols(data, start=0, limit=None):
    limit = len(data) if limit is None else limit
    offset = start
    while offset < limit:
        length = integer(data, offset, "H")
        if length < 2 or offset + 2 + length > limit:
            raise ValueError("Invalid symbol-record length")
        record = data[offset + 2:offset + 2 + length]
        kind = integer(record, 0, "H")
        if kind in {0x110F, 0x1110, 0x1146, 0x1147}:
            name = string(record, 37)[0]
            if "sdk::" in name:
                yield {"name": name, "type_index": hex(integer(record, 26)),
                       "offset": integer(record, 30), "section": integer(record, 34, "H"),
                       "size": integer(record, 14), "record_kind": hex(kind)}
        offset += 2 + length


def modules(pdb):
    dbi = pdb.stream(3)
    end = 64 + integer(dbi, 24)
    offset = 64
    result = []
    while offset < end:
        module_stream = integer(dbi, offset + 34, "H")
        sym_size = integer(dbi, offset + 36)
        module_name, following = string(dbi, offset + 64)
        object_name, following = string(dbi, following)
        item = {"module": module_name, "object": object_name, "stream": module_stream}
        if module_stream != 0xFFFF and sym_size > 4:
            data = pdb.stream(module_stream)
            if sym_size > len(data):
                raise ValueError("Module symbols exceed stream")
            item["sdk_functions"] = list(symbols(data, 4, sym_size))
        else:
            item["sdk_functions"] = []
        if item["sdk_functions"] or "uesdk" in object_name.lower():
            result.append(item)
        offset = (following + 3) & ~3
    if offset != end:
        raise ValueError("Module-info size mismatch")
    return result


def dll_identity(path):
    data = path.read_bytes()
    if data[:2] != b"MZ":
        raise ValueError("Expected PE DLL")
    pe = integer(data, 0x3C)
    if data[pe:pe + 4] != b"PE\x00\x00":
        raise ValueError("Invalid PE signature")
    count = integer(data, pe + 6, "H")
    optional_size = integer(data, pe + 20, "H")
    optional = pe + 24
    if integer(data, optional, "H") != 0x20B:
        raise ValueError("Expected 64-bit PE")
    sections = []
    for index in range(count):
        offset = optional + optional_size + index * 40
        sections.append({"rva": integer(data, offset + 12),
                         "raw_size": integer(data, offset + 16),
                         "raw_offset": integer(data, offset + 20)})
    debug_rva, debug_size = struct.unpack_from("<II", data, optional + 112 + 6 * 8)
    directory = None
    for section in sections:
        delta = debug_rva - section["rva"]
        if 0 <= delta <= section["raw_size"] and debug_size <= section["raw_size"] - delta:
            directory = section["raw_offset"] + delta
            break
    if directory is None or debug_size % 28:
        raise ValueError("Invalid PE debug directory")
    identities = []
    for offset in range(directory, directory + debug_size, 28):
        if integer(data, offset + 12) != 2:
            continue
        size = integer(data, offset + 16)
        raw = integer(data, offset + 24)
        if size < 24 or raw > len(data) or size > len(data) - raw:
            raise ValueError("Invalid CodeView range")
        if data[raw:raw + 4] == b"RSDS":
            identities.append({"guid": str(uuid.UUID(bytes_le=data[raw + 4:raw + 20])),
                               "age": integer(data, raw + 20)})
    if len(identities) != 1:
        raise ValueError("Expected exactly one RSDS identity")
    return {"sha256": hashlib.sha256(data).hexdigest(), **identities[0],
            "image_base": integer(data, optional + 24, "Q"), "sections": sections}


def digest(path):
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def recover(lock_path, dll_path, pdb_path, output):
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    expected = next(x["sha256"] for x in lock["official_assets"] if x["name"] == "DIBRUEVRBackend.dll")
    dll = dll_identity(dll_path)
    if dll["sha256"] != expected:
        raise ValueError("DLL differs from pinned official Mono baseline")
    pdb = Pdb(pdb_path)
    info = pdb.stream(1)
    identity = {"guid": str(uuid.UUID(bytes_le=info[12:28])), "age": integer(info, 8)}
    if any(identity[key] != dll[key] for key in identity):
        raise ValueError("PDB GUID/age does not match the official DLL")
    types = Types(pdb.stream(2))
    sdk_types = types.sdk_types()
    sdk_modules = modules(pdb)
    output.mkdir(parents=True, exist_ok=True)
    report = {"backend_commit": lock["backend"]["commit"],
              "required_sdk_commit": lock["backend"]["sdk_commit"],
              "dll": dll, "pdb": {"sha256": digest(pdb_path), **identity},
              "sdk_types": sdk_types, "modules": sdk_modules,
              "sdk_source_recovered": False, "sdk_equivalence_verified": False,
              "full_backend_build_verified": False}
    (output / "sdk-symbol-evidence.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    summary = {"dll_sha256": dll["sha256"], "pdb": report["pdb"],
               "sdk_type_count": len(sdk_types), "module_count": len(sdk_modules),
               "sdk_function_count": sum(len(x["sdk_functions"]) for x in sdk_modules)}
    print(json.dumps(summary, indent=2))
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("lock", type=Path)
    parser.add_argument("dll", type=Path)
    parser.add_argument("pdb", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    recover(args.lock, args.dll, args.pdb, args.output)
