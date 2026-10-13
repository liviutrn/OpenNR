#!/usr/bin/env python3
"""Fail closed if a Stage 1 build mutates any tracked renderer source unexpectedly."""
import argparse
import hashlib
import json
import subprocess
from pathlib import Path

EXPECTED_BACKEND = {
    "src/mods/vr/MonoRenderingPolicy.hpp",
    "src/mods/vr/CompatibilityPolicy.hpp",
    "src/mods/VR.hpp",
    "src/mods/VR.cpp",
    "tests/MonoRenderingTests.hpp",
}
EXPECTED_FRONTEND = {
    "UEVR/RenderingModeOptions.cs",
    "tests/RenderingModes/Program.cs",
}
GENERATED_FRONTEND = {"UEVR/FilteredExecutables.json"}

def git(root, *args):
    return subprocess.check_output(["git", "-C", str(root), *args], text=True).strip()

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def verify(root, expected, allowed_generated, previous=None):
    diff = set(git(root, "diff", "--name-only", "HEAD").splitlines())
    if not expected.issubset(diff) or diff - (expected | allowed_generated):
        raise RuntimeError(f"{root}: unexpected tracked changes: {sorted(diff)}")
    untracked = git(root, "ls-files", "--others", "--exclude-standard")
    if untracked:
        raise RuntimeError(f"{root}: unexpected untracked files: {untracked}")
    hashes = {x: digest(root / x) for x in sorted(expected)}
    if previous is not None and hashes != previous:
        raise RuntimeError(f"{root}: source changed after patched build")
    return hashes

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("backend", type=Path)
    p.add_argument("frontend", type=Path)
    p.add_argument("evidence", type=Path)
    p.add_argument("--final", action="store_true")
    a = p.parse_args()
    f = a.evidence / "duoview-stage1-source-hashes.json"
    previous = json.loads(f.read_text()) if a.final else None
    if git(a.backend, "rev-parse", "HEAD") != "5ac7edc207866569334175e4ed8a7517971547f6":
        raise RuntimeError("Unexpected Joey backend revision")
    if git(a.frontend, "rev-parse", "HEAD") != "60be4b0f9a646109fd9fdf448bacd41477234091":
        raise RuntimeError("Unexpected Joey frontend revision")
    sdk = a.backend / "dependencies/submodules/UESDK"
    if git(sdk, "rev-parse", "HEAD") != "3cffbc82429b6165ceec2714f0f0d9ae48f55596":
        raise RuntimeError("Unexpected SDK revision")
    if git(sdk, "status", "--porcelain"):
        raise RuntimeError("Original restricted SDK must remain unchanged")
    result = {
        "backend": verify(a.backend, EXPECTED_BACKEND, set(), previous["backend"] if previous else None),
        "frontend": verify(a.frontend, EXPECTED_FRONTEND, GENERATED_FRONTEND,
                           previous["frontend"] if previous else None),
    }
    if not a.final:
        f.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print("DuoView Stage 1 source verified", "after build" if a.final else "after patch")
