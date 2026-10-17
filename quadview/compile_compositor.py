#!/usr/bin/env python3
"""Fail CI if the independent QuadView same-eye DX12 pixel shader is invalid.
This is compile evidence ONLY: no UEVR binding or headset functionality.
"""
import argparse
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

def locate_fxc() -> Path:
    binary=shutil.which("fxc.exe") or shutil.which("fxc")
    if binary: return Path(binary)
    sdk=Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Windows Kits" / "10" / "bin"
    found=list(sdk.glob("*/x64/fxc.exe"))
    if not found: raise RuntimeError("Windows SDK FXC is required; no runtime shader compilation")
    return sorted(found,key=lambda p: tuple(int(x) for x in p.parent.parent.name.split(".")))[-1]

def main() -> int:
    parser=argparse.ArgumentParser()
    parser.add_argument("output",type=Path)
    args=parser.parse_args()
    source=Path(__file__).resolve().parent / "QuadStereoComposite.hlsl"
    if not source.is_file(): raise RuntimeError("Missing QuadStereoComposite.hlsl")
    args.output.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="quad-stereo-ps-") as tmp:
        result=Path(tmp)/"quad.cso"
        cmd=[str(locate_fxc()),"/nologo","/O3","/T","ps_5_0","/E","main",
             "/Fo",str(result),str(source)]
        ran=subprocess.run(cmd,capture_output=True,text=True)
        if ran.returncode:
            raise RuntimeError(f"QuadView DXBC compile error: {ran.stdout}\n{ran.stderr}")
        data=result.read_bytes()
        if not data.startswith(b"DXBC") or len(data)<64:
            raise RuntimeError("FXC returned invalid DXBC bytecode")
        args.output.write_bytes(data)
        print(f"QuadView stereo pixel shader compiled: {len(data)} bytes SHA256:{hashlib.sha256(data).hexdigest()}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
