#!/usr/bin/env python3
"""Verify that a Windows build preserves its reviewed, patched source inputs."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess


PINS = {
    "backend": "5ac7edc207866569334175e4ed8a7517971547f6",
    "frontend": "60be4b0f9a646109fd9fdf448bacd41477234091",
    "sdk": "3cffbc82429b6165ceec2714f0f0d9ae48f55596",
}


def git(root: Path, *arguments: str) -> str:
    return subprocess.check_output(["git", "-C", str(root), *arguments], text=True).strip()


def inspect(backend: Path, frontend: Path) -> dict:
    roots = {"backend": backend, "frontend": frontend,
             "sdk": backend / "dependencies/submodules/UESDK"}
    for name, root in roots.items():
        if git(root, "rev-parse", "HEAD") != PINS[name]:
            raise RuntimeError(f"Unexpected {name} source revision")
    if git(roots["sdk"], "status", "--porcelain", "--untracked-files=all"):
        raise RuntimeError("The restricted SDK working tree changed")

    hashes = {}
    selections = (("backend", backend, ["src", "tests", "CMakeLists.txt", "cmake.toml"]),
                  ("frontend", frontend, ["UEVR", "tests"]))
    for name, root, selected in selections:
        root = root.resolve()
        for relative in selected:
            start = root / relative
            if not start.exists():
                raise RuntimeError(f"Missing source input: {name}/{relative}")
            files = [start] if start.is_file() else []
            if start.is_dir():
                for parent, directories, names in os.walk(start):
                    directories[:] = sorted(d for d in directories if d not in {"bin", "obj", ".git", "__pycache__"})
                    files.extend(Path(parent) / filename for filename in sorted(names))
            for path in files:
                if not path.resolve().is_relative_to(root):
                    raise RuntimeError("Source input resolves outside its checkout")
                key = f"{name}/{path.relative_to(root).as_posix()}"
                hashes[key] = hashlib.sha256(path.read_bytes()).hexdigest()
    return {"schema": 1, "pins": PINS, "sha256": hashes}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["capture", "verify"])
    parser.add_argument("backend", type=Path)
    parser.add_argument("frontend", type=Path)
    parser.add_argument("checkpoint", type=Path)
    args = parser.parse_args()
    actual = inspect(args.backend, args.frontend)
    if args.mode == "capture":
        args.checkpoint.parent.mkdir(parents=True, exist_ok=True)
        args.checkpoint.write_text(json.dumps(actual, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"Captured {len(actual['sha256'])} patched source inputs; exact SDK unchanged.")
        return
    expected = json.loads(args.checkpoint.read_text(encoding="utf-8"))
    if expected.get("pins") != actual["pins"] or expected.get("schema") != actual["schema"]:
        raise RuntimeError("Source checkpoint provenance does not match")
    before, after = expected["sha256"], actual["sha256"]
    changed = [name for name in sorted(before.keys() | after.keys()) if before.get(name) != after.get(name)]
    if changed:
        raise RuntimeError("Build changed its source inputs: " + ", ".join(changed[:30]))
    print(f"Verified {len(after)} patched source inputs; exact SDK unchanged.")


if __name__ == "__main__":
    main()
