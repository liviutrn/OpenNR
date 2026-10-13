#!/usr/bin/env python3
"""Verify exact Stage 2-4 added/edited source and unchanged original SDK."""
import argparse, hashlib, json, subprocess
from pathlib import Path

EDITED_BACKEND = {
 "src/mods/vr/MonoRenderingPolicy.hpp", "src/mods/vr/CompatibilityPolicy.hpp",
 "src/mods/VR.hpp", "src/mods/VR.cpp",
 "src/mods/vr/FFakeStereoRenderingHook.cpp", "src/mods/vr/D3D12Component.hpp",
 "src/mods/vr/D3D12Component.cpp", "tests/MonoRenderingTests.hpp",
}
ADDED_BACKEND = {
 "src/mods/vr/DuoViewGeometry.hpp", "src/mods/vr/DuoViewGaze.hpp",
 "src/mods/vr/DuoViewFrame.hpp", "src/mods/vr/DuoViewConfig.hpp",
 "src/mods/vr/DuoViewState.hpp", "src/mods/vr/DuoViewD3D12.hpp",
 "src/mods/vr/DuoViewMonoCopyD3D12.hpp", "src/mods/vr/DuoViewShaderSource.hpp",
}
EDITED_FRONTEND = {"UEVR/RenderingModeOptions.cs", "tests/RenderingModes/Program.cs"}
GENERATED_FRONTEND = {"UEVR/FilteredExecutables.json"}

def git(root,*args):
 return subprocess.check_output(["git","-C",str(root),*args],text=True).strip()
def sha(p):
 return hashlib.sha256(p.read_bytes()).hexdigest()
def tracked(root):
 return set(git(root,"diff","--name-only","HEAD").splitlines())
def untracked(root):
 return set(git(root,"ls-files","--others","--exclude-standard").splitlines())

def main():
 p=argparse.ArgumentParser()
 p.add_argument("backend",type=Path)
 p.add_argument("frontend",type=Path)
 p.add_argument("evidence",type=Path)
 p.add_argument("--final",action="store_true")
 a=p.parse_args()
 assert git(a.backend,"rev-parse","HEAD")=="5ac7edc207866569334175e4ed8a7517971547f6"
 assert git(a.frontend,"rev-parse","HEAD")=="60be4b0f9a646109fd9fdf448bacd41477234091"
 sdk=a.backend/"dependencies/submodules/UESDK"
 assert git(sdk,"rev-parse","HEAD")=="3cffbc82429b6165ceec2714f0f0d9ae48f55596"
 if git(sdk,"status","--porcelain"): raise RuntimeError("SDK source not clean")
 bdiff=tracked(a.backend)
 if bdiff!=EDITED_BACKEND: raise RuntimeError(f"Wrong backend edited paths: {bdiff ^ EDITED_BACKEND}")
 buntracked=untracked(a.backend)
 if buntracked!=ADDED_BACKEND: raise RuntimeError(f"Unexpected added backend paths: {buntracked ^ ADDED_BACKEND}")
 fdiff=tracked(a.frontend)
 if fdiff - (EDITED_FRONTEND|GENERATED_FRONTEND) or not EDITED_FRONTEND.issubset(fdiff):
  raise RuntimeError(f"Unexpected frontend tracked changes: {fdiff}")
 if untracked(a.frontend): raise RuntimeError("Unexpected untracked frontend source")
 inputs = sorted(EDITED_BACKEND | ADDED_BACKEND)
 hashes = {"backend":{k:sha(a.backend/k) for k in inputs},
           "frontend":{k:sha(a.frontend/k) for k in sorted(EDITED_FRONTEND)}}
 lock=a.evidence/"duoview-stage234-hashes.json"
 if a.final:
  if json.loads(lock.read_text())!=hashes: raise RuntimeError("Stage 2-4 source mutated during compile")
 else:
  lock.write_text(json.dumps(hashes,indent=2)+"\n")
 print("Stage 2-4 exact source, proprietary SDK isolation and source hashes verified.")

if __name__=="__main__":
 main()
