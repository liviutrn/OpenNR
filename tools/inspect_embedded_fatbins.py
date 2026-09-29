#!/usr/bin/env python3
"""Inspect DLSS-NR fatbin containers through cuobjdump using temp files only."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any


FATBIN_MAGIC = b"\x50\xed\x55\xba"


def find_offsets(data: bytes, needle: bytes) -> list[int]:
    offsets: list[int] = []
    start = 0
    while True:
        offset = data.find(needle, start)
        if offset < 0:
            return offsets
        offsets.append(offset)
        start = offset + 1


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def run_tool(executable: Path, options: list[str], image: Path, timeout: int) -> dict[str, Any]:
    completed = subprocess.run(
        [str(executable), *options, str(image)],
        capture_output=True,
        timeout=timeout,
        check=False,
    )
    stdout = (completed.stdout or b"").decode("utf-8", errors="replace")
    stderr = (completed.stderr or b"").decode("utf-8", errors="replace")
    return {
        "returncode": completed.returncode,
        "stdout_chars": len(stdout),
        "stderr": stderr[-2000:],
        "lines": stdout.splitlines(),
    }


def compact_lines(lines: list[str], limit: int = 80) -> list[str]:
    return [line[:500] for line in lines if line.strip()][:limit]


def symbol_lines(lines: list[str]) -> list[str]:
    values: list[str] = []
    for line in lines:
        text = line.strip()
        if not text or text.startswith("//") or text.startswith("Fatbin"):
            continue
        if "Function" in text or text.startswith("_Z") or text.startswith("cc_") or "kernel" in text.lower():
            values.append(text[:500])
    return values[:4096]


def ptx_summary(lines: list[str]) -> dict[str, Any]:
    text = "\n".join(lines)
    entries = []
    for line in lines:
        match = re.search(r"\.visible\s+\.entry\s+([^\s(]+)", line)
        if match:
            entries.append(match.group(1))
    markers = {
        "ptx_version_directives": r"\.version\s+[0-9.]+",
        "ptx_targets": r"\.target\s+[^\s]+",
        "mma_sync": r"\bmma\.sync",
        "wgmma": r"\bwgmma",
        "cp_async": r"\bcp\.async",
        "cp_async_bulk": r"\bcp\.async\.bulk",
        "mbarrier": r"\bmbarrier",
        "elect_sync": r"\belect\.sync",
        "bar_sync": r"\bbar\.sync",
        "red_global": r"\bred\.global",
        "fence_release": r"\bfence\.release",
        "fence_acq_rel": r"\bfence\.acq_rel",
        "atom_global": r"\batom\.global",
    }
    counts: dict[str, int] = {}
    for name, pattern in markers.items():
        counts[name] = len(re.findall(pattern, text, flags=re.IGNORECASE))
    return {
        "line_count": len(lines),
        "text_chars": len(text),
        "entries": entries[:4096],
        "entry_count": len(entries),
        "counts": counts,
        "directive_sample": [
            line.strip()[:500]
            for line in lines
            if line.strip().startswith((".version", ".target", ".address_size"))
        ][:64],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dll", required=True, type=Path)
    parser.add_argument("--cuobjdump", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--indices", default="0,1,2,3,4,5")
    parser.add_argument("--timeout-seconds", type=int, default=60)
    args = parser.parse_args()

    dll = args.dll.resolve()
    data = dll.read_bytes()
    offsets = find_offsets(data, FATBIN_MAGIC)
    requested = [int(value) for value in args.indices.split(",") if value.strip()]
    records: list[dict[str, Any]] = []
    for index in requested:
        record: dict[str, Any] = {"index": index, "offset": None}
        if index < 0 or index >= len(offsets):
            record["error"] = "fatbin index out of range"
            records.append(record)
            continue
        start = offsets[index]
        end = offsets[index + 1] if index + 1 < len(offsets) else len(data)
        record.update({"offset": start, "span": end - start})
        with tempfile.TemporaryDirectory(prefix="open nr fatbin ") as temp_dir:
            image = Path(temp_dir) / f"embedded_{index:02d}.fatbin"
            image.write_bytes(data[start:end])
            list_elf = run_tool(args.cuobjdump, ["--list-elf"], image, args.timeout_seconds)
            list_ptx = run_tool(args.cuobjdump, ["--list-ptx"], image, args.timeout_seconds)
            dump_ptx = run_tool(args.cuobjdump, ["--dump-ptx"], image, args.timeout_seconds)
            symbols = run_tool(args.cuobjdump, ["--dump-elf-symbols"], image, args.timeout_seconds)
            resources = run_tool(args.cuobjdump, ["--dump-resource-usage"], image, args.timeout_seconds)
            record["list_elf"] = {
                "returncode": list_elf["returncode"],
                "lines": compact_lines(list_elf["lines"]),
            }
            record["list_ptx"] = {
                "returncode": list_ptx["returncode"],
                "lines": compact_lines(list_ptx["lines"]),
            }
            record["ptx"] = {
                "returncode": dump_ptx["returncode"],
                "summary": ptx_summary(dump_ptx["lines"]),
                "stderr": dump_ptx["stderr"],
            }
            record["symbols"] = {
                "returncode": symbols["returncode"],
                "candidate_lines": symbol_lines(symbols["lines"]),
                "all_nonempty_line_count": sum(1 for line in symbols["lines"] if line.strip()),
                "stderr": symbols["stderr"],
            }
            record["resources"] = {
                "returncode": resources["returncode"],
                "lines": compact_lines(resources["lines"], limit=256),
                "function_count": sum(1 for line in resources["lines"] if line.strip().startswith("Function ")),
                "stderr": resources["stderr"],
            }
        records.append(record)

    report = {
        "analysis": {
            "tool": "inspect_embedded_fatbins.py",
            "mode": "cuobjdump metadata on temporary fatbin slices",
            "temporary_payloads_retained": False,
        },
        "file": {"path": str(dll), "size": len(data), "sha256": sha256_file(dll)},
        "fatbin_count": len(offsets),
        "fatbin_offsets": offsets,
        "requested_indices": requested,
        "records": records,
    }
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({
        "output": str(output),
        "sha256": report["file"]["sha256"],
        "fatbin_count": len(offsets),
        "records": [
            {
                "index": record.get("index"),
                "offset": record.get("offset"),
                "span": record.get("span"),
                "list_elf_rc": record.get("list_elf", {}).get("returncode"),
                "list_ptx_rc": record.get("list_ptx", {}).get("returncode"),
                "symbol_rc": record.get("symbols", {}).get("returncode"),
                "resource_rc": record.get("resources", {}).get("returncode"),
                "resource_function_count": record.get("resources", {}).get("function_count"),
            }
            for record in records
        ],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
