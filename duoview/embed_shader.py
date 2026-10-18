#!/usr/bin/env python3
"""Generate deterministic precompiled DXBC bytecode. Never compile HLSL in the VR frame callback."""
from pathlib import Path
import argparse
import os
import shutil
import subprocess
import tempfile

def fxc_executable():
    in_path = shutil.which("fxc.exe") or shutil.which("fxc")
    if in_path:
        return Path(in_path)
    root = Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Windows Kits" / "10" / "bin"
    options = list(root.glob("*/x64/fxc.exe"))
    if not options:
        raise RuntimeError("Windows SDK fxc.exe missing: shader precompile is mandatory (no render-thread fallback)")
    return sorted(options, key=lambda p: [int(x) for x in p.parent.parent.name.split(".")])[-1]

def format_array(name, payload):
    if not payload.startswith(b"DXBC") or len(payload) < 64:
        raise RuntimeError(f"Invalid {name} DXBC shader output")
    groups = (payload[i:i + 12] for i in range(0, len(payload), 12))
    return "inline constexpr unsigned char " + name + "[] = {\n" + "".join(
        "    " + ", ".join(f"0x{b:02x}" for b in g) + ",\n" for g in groups) + "};\n"

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    source = Path(__file__).resolve().parent
    fxc = fxc_executable()
    sections = []
    with tempfile.TemporaryDirectory(prefix="duoview-shader-") as tmp:
        for entry, profile, name in (
            ("VSMain", "vs_5_0", "vertex_shader_bytecode"),
            ("PSMain", "ps_5_0", "pixel_shader_bytecode"),
            ("PSNativeMain", "ps_5_0", "native_pixel_shader_bytecode"),
        ):
            output = Path(tmp) / (name + ".cso")
            command = [str(fxc), "/nologo", "/O3", "/T", profile,
                       "/E", entry, "/I", str(source), "/Fo", str(output),
                       str(source / ("DuoViewNativeCompositeRaster.hlsl" if entry == "PSNativeMain" else "DuoViewCompositeRaster.hlsl"))]
            result = subprocess.run(command, capture_output=True, text=True)
            if result.returncode:
                raise RuntimeError(f"Shader {entry} failed compilation: {result.stdout}\n{result.stderr}")
            sections.append(format_array(name, output.read_bytes()))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        "#pragma once\n// HLSL precompiled by Windows SDK fxc.exe in CI; no runtime D3DCompile.\n"
        "namespace uevr::duoview::dx12 {\n" + "".join(sections) + "}\n",
        encoding="utf-8", newline="")
    print("DuoView DXBC shaders compiled offline: " + str(args.output))

if __name__ == "__main__":
    main()
