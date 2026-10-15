"""Create/verify a Git-blob manifest for every restart source file in a snapshot."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


MANIFEST_RELATIVE = Path("duoview/restart/source-snapshot-manifest.json")
WORKFLOW_RELATIVE = Path(".github/workflows/duoview-restart-build3-control.yml")
ATTRIBUTES_RELATIVE = Path(".gitattributes")
RESTART_ROOT = Path("duoview/restart")
GENERATED_DIRECTORIES = {"build", "warp-build", "__pycache__"}


def git_blob_sha(data: bytes) -> str:
    header = f"blob {len(data)}\0".encode("ascii")
    return hashlib.sha1(header + data).hexdigest()


def source_paths(root: Path) -> list[Path]:
    paths = [path for path in (root / RESTART_ROOT).rglob("*")
        if path.is_file() and path.relative_to(root) != MANIFEST_RELATIVE
        and not GENERATED_DIRECTORIES.intersection(path.relative_to(root).parts)]
    workflow = root / WORKFLOW_RELATIVE
    if workflow.is_file():
        paths.append(workflow)
    attributes = root / ATTRIBUTES_RELATIVE
    if attributes.is_file():
        paths.append(attributes)
    return sorted(path.relative_to(root) for path in paths)


def make_manifest(root: Path) -> dict:
    files = {
        path.as_posix(): git_blob_sha((root / path).read_bytes())
        for path in source_paths(root)
    }
    return {
        "schema_version": 1,
        "baseline_commit": "64432d0442066715fa442660a0848cf4963640b0",
        "files": files,
    }


def write(root: Path) -> None:
    manifest_path = root / MANIFEST_RELATIVE
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest = make_manifest(root)
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote snapshot manifest for {len(manifest['files'])} files: {manifest_path}")


def verify(root: Path) -> None:
    manifest_path = root / MANIFEST_RELATIVE
    expected = json.loads(manifest_path.read_text(encoding="utf-8"))
    if expected.get("schema_version") != 1 or expected.get("baseline_commit") != "64432d0442066715fa442660a0848cf4963640b0":
        raise ValueError("restart source snapshot manifest has an unsupported schema or baseline")

    actual_paths = {path.as_posix() for path in source_paths(root)}
    expected_paths = set(expected.get("files", {}))
    if actual_paths != expected_paths:
        raise ValueError(
            f"restart source file set differs: missing={sorted(expected_paths - actual_paths)} "
            f"unexpected={sorted(actual_paths - expected_paths)}"
        )
    for relative, expected_hash in expected["files"].items():
        actual_hash = git_blob_sha((root / relative).read_bytes())
        if actual_hash != expected_hash:
            raise ValueError(f"restart source snapshot hash differs: {relative}")
    print(f"Verified pushed source snapshot manifest for {len(actual_paths)} files")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("workspace", type=Path)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--write", action="store_true")
    modes.add_argument("--verify", action="store_true")
    arguments = parser.parse_args()
    if arguments.write:
        write(arguments.workspace.resolve())
    else:
        verify(arguments.workspace.resolve())
