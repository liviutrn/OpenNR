#!/usr/bin/env python3
"""Run NVIDIA's disassembler on temporary embedded cubins and summarize it.

The embedded ELF bytes are materialized only under a temporary directory for
the duration of each invocation.  The output contains metadata and aggregate
instruction counts, not disassembly or cubin payloads.
"""

from __future__ import annotations

import argparse
import collections
import hashlib
import json
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any


ELF_MAGIC = b"\x7fELF"


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


def collect_json_values(value: Any, keys: set[str], result: list[str]) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if key.lower() in keys and isinstance(child, str):
                result.append(child)
            collect_json_values(child, keys, result)
    elif isinstance(value, list):
        for child in value:
            collect_json_values(child, keys, result)


def collect_json_key_statistics(value: Any, key_counts: collections.Counter[str], samples: dict[str, list[str]]) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = str(key).lower()
            key_counts[normalized] += 1
            if normalized in {"function", "function_name", "opcode", "instruction", "sass_instruction", "name", "code"}:
                if len(samples.setdefault(normalized, [])) < 8:
                    preview = repr(child)
                    samples[normalized].append(preview[:500])
            collect_json_key_statistics(child, key_counts, samples)
    elif isinstance(value, list):
        for child in value:
            collect_json_key_statistics(child, key_counts, samples)


def collect_function_summaries(value: Any, result: list[dict[str, Any]]) -> None:
    if isinstance(value, dict):
        if "function-name" in value and "sass-instructions" in value:
            instructions = value.get("sass-instructions")
            if isinstance(instructions, list):
                opcodes = collections.Counter(
                    item.get("opcode")
                    for item in instructions
                    if isinstance(item, dict) and isinstance(item.get("opcode"), str)
                )
                result.append({
                    "name": value.get("function-name"),
                    "start": value.get("start"),
                    "length": value.get("length"),
                    "instruction_count": len(instructions),
                    "inter_warp_barrier": value.get("inter-warp-barrier"),
                    "top_opcodes": dict(opcodes.most_common(16)),
                })
        for child in value.values():
            collect_function_summaries(child, result)
    elif isinstance(value, list):
        for child in value:
            collect_function_summaries(child, result)


def likely_opcode_counts(text: str) -> collections.Counter[str]:
    """Count SASS mnemonic-looking tokens from nvdisasm's text/JSON output."""
    counts: collections.Counter[str] = collections.Counter()
    # JSON string values and text output both contain tokens such as HMMA.1688
    # or LDG.E.32.  Restrict the alphabet to avoid counting symbol names.
    known_prefixes = (
        "HMMA", "IMMA", "MMA", "FFMA", "FADD", "FMUL", "FMA", "DADD", "DMUL",
        "IADD", "IMAD", "IMUL", "LOP", "SHF", "ISCADD", "LEA", "MOV", "SEL",
        "LD", "ST", "ATOM", "LDS", "STS", "RED", "BRA", "BRX", "CALL", "RET",
        "EXIT", "BAR", "MEMBAR", "DEPBAR", "TEX", "TLD", "SULD", "SUST", "PLOP3",
        "F2F", "F2I", "I2F", "I2I", "R2UR", "S2R", "CS2R", "BMSK", "BFE", "BFI",
        "SHFL", "VOTE", "MATCH", "PSET", "PLOP", "NOP", "YIELD", "ULDC", "CCTL",
        "ERRBAR", "PLOP3", "BSYNC", "WARPSYNC", "NANOSLEEP",
    )
    token_re = re.compile(r"\b[A-Z][A-Z0-9_.]*\b")
    for token in token_re.findall(text):
        if token.startswith(known_prefixes):
            counts[token] += 1
    return counts


def summarize_one(
    data: bytes,
    start: int,
    end: int,
    index: int,
    nvdisasm: Path,
    cuobjdump: Path | None,
    timeout_seconds: int,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "index": index,
        "offset": start,
        "span": end - start,
        "nvdisasm": str(nvdisasm),
        "returncode": None,
        "stdout_bytes": 0,
        "stderr": "",
        "json_parsed": False,
        "top_level_keys": [],
        "function_names": [],
        "instruction_count_from_json": 0,
        "opcode_counts": {},
        "cuobjdump_resource_usage": "",
        "cuobjdump_returncode": None,
    }
    with tempfile.TemporaryDirectory(prefix="open nr nvdisasm ") as temp_dir:
        cubin_path = Path(temp_dir) / f"embedded_{index:02d}.cubin"
        cubin_path.write_bytes(data[start:end])
        command = [
            str(nvdisasm),
            "--print-code",
            "--emit-json",
            "--no-dataflow",
            "--separate-functions",
            str(cubin_path),
        ]
        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                timeout=timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            result["error"] = f"timeout after {timeout_seconds}s"
            result["stdout_bytes"] = len(exc.stdout or b"")
            result["stderr"] = (exc.stderr or b"").decode("utf-8", errors="replace")[-2000:]
            return result
        result["returncode"] = completed.returncode
        stdout = completed.stdout or b""
        stderr = completed.stderr or b""
        result["stdout_bytes"] = len(stdout)
        result["stderr"] = stderr.decode("utf-8", errors="replace")[-4000:]
        text_output = stdout.decode("utf-8", errors="replace")
        counts = likely_opcode_counts(text_output)
        result["opcode_counts"] = dict(counts.most_common())
        try:
            parsed = json.loads(text_output)
        except json.JSONDecodeError as exc:
            result["json_error"] = str(exc)
            return result
        result["json_parsed"] = True
        if isinstance(parsed, dict):
            result["top_level_keys"] = sorted(str(key) for key in parsed)
        key_counts: collections.Counter[str] = collections.Counter()
        key_samples: dict[str, list[str]] = {}
        collect_json_key_statistics(parsed, key_counts, key_samples)
        result["json_key_counts"] = dict(key_counts.most_common())
        result["json_key_samples"] = key_samples
        function_summaries: list[dict[str, Any]] = []
        collect_function_summaries(parsed, function_summaries)
        result["function_summaries"] = function_summaries
        result["function_names"] = [item["name"] for item in function_summaries if item.get("name")]
        instruction_values: list[str] = []
        collect_json_values(parsed, {"opcode", "instruction", "sass_instruction"}, instruction_values)
        result["instruction_count_from_json"] = len(instruction_values)
        json_opcodes = collections.Counter(
            value for value in instruction_values if value in counts or isinstance(value, str)
        )
        result["json_opcode_counts"] = dict(json_opcodes.most_common())
        if cuobjdump is not None:
            resource_command = [str(cuobjdump), "--dump-resource-usage", str(cubin_path)]
            try:
                resource = subprocess.run(
                    resource_command,
                    capture_output=True,
                    timeout=timeout_seconds,
                    check=False,
                )
                result["cuobjdump_returncode"] = resource.returncode
                result["cuobjdump_resource_usage"] = (resource.stdout or b"").decode(
                    "utf-8", errors="replace"
                )[-12000:]
                resource_stderr = (resource.stderr or b"").decode("utf-8", errors="replace")
                if resource_stderr:
                    result["cuobjdump_stderr"] = resource_stderr[-2000:]
            except subprocess.TimeoutExpired:
                result["cuobjdump_error"] = f"timeout after {timeout_seconds}s"
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dll", required=True, type=Path)
    parser.add_argument("--nvdisasm", required=True, type=Path)
    parser.add_argument("--cuobjdump", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--indices", default="0,1,2,3,4,5")
    parser.add_argument("--timeout-seconds", type=int, default=120)
    args = parser.parse_args()
    dll = args.dll.resolve()
    nvdisasm = args.nvdisasm.resolve()
    data = dll.read_bytes()
    offsets = find_offsets(data, ELF_MAGIC)
    requested = [int(value) for value in args.indices.split(",") if value.strip()]
    summaries: list[dict[str, Any]] = []
    for index in requested:
        if index < 0 or index >= len(offsets):
            summaries.append({"index": index, "error": "ELF index out of range"})
            continue
        end = offsets[index + 1] if index + 1 < len(offsets) else len(data)
        summaries.append(
            summarize_one(data, offsets[index], end, index, nvdisasm, args.cuobjdump, args.timeout_seconds)
        )
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    report = {
        "analysis": {
            "tool": "summarize_embedded_cuda_disassembly.py",
            "mode": "aggregate disassembly metadata; temporary cubin materialization only",
            "temporary_payloads_retained": False,
        },
        "file": {"path": str(dll), "size": len(data), "sha256": sha256_file(dll)},
        "nvdisasm": str(nvdisasm),
        "requested_indices": requested,
        "summaries": summaries,
    }
    output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({
        "output": str(output),
        "sha256": report["file"]["sha256"],
        "summaries": [
            {
                "index": item.get("index"),
                "returncode": item.get("returncode"),
                "json_parsed": item.get("json_parsed"),
                "stdout_bytes": item.get("stdout_bytes"),
                "instruction_count_from_json": item.get("instruction_count_from_json"),
                "top_opcodes": list(item.get("opcode_counts", {}).items())[:12],
                "cuobjdump_returncode": item.get("cuobjdump_returncode"),
                "cuobjdump_resource_usage": item.get("cuobjdump_resource_usage", "")[:1200],
                "stderr": item.get("stderr", "")[:300],
            }
            for item in summaries
        ],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
