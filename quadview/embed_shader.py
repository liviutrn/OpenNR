#!/usr/bin/env python3
"""Compile the QuadView raster shader with the Windows SDK and embed DXBC."""

from pathlib import Path
import os
import shutil
import subprocess
import sys
import tempfile


def find_fxc() -> Path:
    found = shutil.which("fxc.exe") or shutil.which("fxc")
    if found:
        return Path(found)
    candidates = []
    for name in ("WindowsSdkVerBinPath", "WindowsSdkDir"):
        if os.environ.get(name):
            root = Path(os.environ[name])
            candidates.extend(root.glob("**/x64/fxc.exe"))
    kits = Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Windows Kits" / "10" / "bin"
    candidates.extend(kits.glob("*/x64/fxc.exe"))
    if not candidates:
        raise RuntimeError("Windows SDK fxc.exe is required; shader compilation cannot be skipped")
    return max(candidates, key=lambda p: tuple(int(x) for x in p.parent.parent.name.split(".") if x.isdigit()))


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("Usage: embed_shader.py OUTPUT_HEADER")
    output = Path(sys.argv[1]).resolve()
    source = Path(__file__).resolve().with_name("QuadViewComposite.hlsl")
    compiler = find_fxc()
    arrays = []
    with tempfile.TemporaryDirectory(prefix="quadview-shader-") as temporary:
        for name, entry, profile in (("vertex", "VSMain", "vs_5_0"), ("pixel", "PSMain", "ps_5_0")):
            bytecode = Path(temporary) / f"{name}.cso"
            subprocess.run([str(compiler), "/nologo", "/Ges", "/WX", "/O3", "/T", profile,
                            "/E", entry, "/Fo", str(bytecode), str(source)], check=True)
            data = bytecode.read_bytes()
            if not data.startswith(b"DXBC"):
                raise RuntimeError(f"{entry} did not produce a DXBC shader")
            lines = [", ".join(f"0x{b:02x}" for b in data[start:start + 16]) for start in range(0, len(data), 16)]
            arrays.append(f"alignas(4) inline constexpr unsigned char {name}[] = {{\n    " + ",\n    ".join(lines) + "\n};")
    contents = "#pragma once\nnamespace uevr::quadview::shaders {\n" + "\n".join(arrays) + "\n}\n"
    output.parent.mkdir(parents=True, exist_ok=True)
    if not output.exists() or output.read_text(encoding="utf-8") != contents:
        output.write_text(contents, encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
