"""Generate isolated test references from verified official DLL/PDB evidence."""

import argparse
import hashlib
import json
from pathlib import Path
import sys

import capstone
import pefile

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from recover_sdk_symbols import dll_identity, digest


def generate(evidence, dll_path, output):
    identity = dll_identity(dll_path)
    if identity["sha256"] != evidence["dll"]["sha256"] or any(
            identity[key] != evidence["pdb"][key] for key in ("guid", "age")):
        raise ValueError("Reference DLL differs from verified symbol evidence")
    image = pefile.PE(str(dll_path))
    decoder = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
    decoder.detail = True
    imports = {entry.address: entry.name.decode("ascii")
               for module in image.DIRECTORY_ENTRY_IMPORT for entry in module.imports if entry.name}
    wanted = {"sdk::discovery::read_process", "sdk::discovery::executable_image"}
    functions = {}
    for module in evidence["modules"]:
        for function in module["sdk_functions"]:
            if function["name"] in wanted:
                prior = functions.get(function["name"])
                if prior and (prior["section"], prior["offset"], prior["size"]) != (
                        function["section"], function["offset"], function["size"]):
                    raise ValueError("Ambiguous reference function")
                functions[function["name"]] = function
    if set(functions) != wanted:
        raise ValueError("Missing original memory functions")
    lines = ["#pragma once", "#include <array>", "#include <cstddef>", "#include <cstdint>",
             "namespace original_sdk_memory {",
             "struct Patch { size_t displacement; const char* import; };"]
    references = []
    for name in sorted(functions):
        function = functions[name]
        section = image.sections[function["section"] - 1]
        rva = section.VirtualAddress + function["offset"]
        code = image.get_data(rva, function["size"])
        base = image.OPTIONAL_HEADER.ImageBase + rva
        patches, assembly, decoded_size = [], [], 0
        for instruction in decoder.disasm(code, base):
            decoded_size += instruction.size
            assembly.append(f"{instruction.address - base:04x}: {instruction.mnemonic} {instruction.op_str}")
            for operand in instruction.operands:
                if operand.type == capstone.x86.X86_OP_MEM and operand.mem.base == capstone.x86.X86_REG_RIP:
                    if instruction.mnemonic != "call" or instruction.bytes[:2] != b"\xff\x15":
                        raise ValueError("Reference slice has a non-import RIP-relative dependency")
                    target = instruction.address + instruction.size + operand.mem.disp
                    imported = imports.get(target)
                    if imported not in {"GetCurrentProcess", "ReadProcessMemory", "VirtualQuery"}:
                        raise ValueError("Unexpected original reference import")
                    patches.append((instruction.address - base + 2, imported))
            if instruction.mnemonic.startswith("j") or instruction.mnemonic == "call":
                for operand in instruction.operands:
                    if operand.type == capstone.x86.X86_OP_IMM and not base <= operand.imm < base + len(code):
                        raise ValueError("Reference slice calls or jumps outside its verified bounds")
        if decoded_size != len(code):
            raise ValueError("Reference slice was not completely decoded")
        identifier = name.split("::")[-1]
        lines.append(f"inline constexpr std::array<uint8_t, {len(code)}> {identifier}_code{{")
        for offset in range(0, len(code), 16):
            lines.append("    " + ",".join(f"0x{byte:02x}" for byte in code[offset:offset + 16]) + ",")
        lines.append("};")
        lines.append(f"inline constexpr std::array<Patch, {len(patches)}> {identifier}_patches{{{{")
        lines.extend(f'    {{{offset}, "{imported}"}},' for offset, imported in patches)
        lines.append("}};")
        references.append({"name": name, "rva": hex(rva), "size": len(code),
                           "sha256": hashlib.sha256(code).hexdigest(),
                           "imports": [{"displacement": offset, "name": imported} for offset, imported in patches],
                           "disassembly": assembly})
    lines.append("}")
    output.mkdir(parents=True, exist_ok=True)
    (output / "OriginalMemoryReference.hpp").write_text("\n".join(lines) + "\n", encoding="utf-8")
    report = {"dll_sha256": digest(dll_path), "pdb": evidence["pdb"], "functions": references,
              "scope": "Offline test reference only; not a runtime binary hook or SDK source recovery"}
    (output / "OriginalMemoryReference.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"references": [{"name": x["name"], "rva": x["rva"], "sha256": x["sha256"]}
                                     for x in references]}, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("evidence", type=Path)
    parser.add_argument("dll", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    generate(json.loads(args.evidence.read_text(encoding="utf-8")), args.dll, args.output)
