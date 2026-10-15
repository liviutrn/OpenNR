"""Verify only the intended pinned backend patch remains after a build."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path

from apply_backend_patch import BACKEND_COMMIT, PatchError


def git(backend: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(backend), *args],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise PatchError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout.rstrip("\r\n")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify(backend: Path, manifest_path: Path) -> None:
    backend = backend.resolve()
    report = json.loads(manifest_path.read_text(encoding="utf-8"))
    if git(backend, "rev-parse", "HEAD") != BACKEND_COMMIT or report.get("backend_commit") != BACKEND_COMMIT:
        raise PatchError("backend revision differs from the pinned Build3 commit")

    expected_files = set(report["files"])
    actual_files = {
        Path(line[3:].strip()).as_posix()
        for line in git(backend, "status", "--porcelain=v1", "--untracked-files=all").splitlines()
    }
    if actual_files != expected_files:
        raise PatchError(f"backend changed-file set differs: expected={sorted(expected_files)} actual={sorted(actual_files)}")

    for relative, expected_hash in report["files"].items():
        actual_hash = sha256(backend / relative)
        if actual_hash != expected_hash:
            raise PatchError(f"generated backend source changed after patching: {relative}")
    print("Pinned backend patch file set and generated-source hashes verified")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--backend", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    arguments = parser.parse_args()
    verify(arguments.backend, arguments.manifest)
