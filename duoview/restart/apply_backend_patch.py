"""Apply the reviewed Build3 stable-source/moving-mask backend adapter."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path


BACKEND_COMMIT = "5ac7edc207866569334175e4ed8a7517971547f6"
COMPONENT_BLOB = "d117973845198e23aa56f1f40ddd6ba8f3450a26"
COMPONENT = Path("src/mods/vr/D3D12Component.cpp")
VR_DIR = Path("src/mods/vr")
BLOCK_START = "                    if (vr->is_using_mono()) {\n"
BLOCK_END = "                    } else if (use_native_array_submit) {"
MONO_INCLUDE = '#include "MonoD3D12.hpp"\n'
CONTROL_INCLUDE = '#include "StableSourceMaskD3D12.hpp"\n'


class PatchError(RuntimeError):
    pass


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


def transform_source(source: str, control_block: str) -> str:
    if source.count(MONO_INCLUDE) != 1:
        raise PatchError("pinned MonoD3D12 include anchor is missing or ambiguous")
    if source.count(CONTROL_INCLUDE):
        raise PatchError("control include already exists; refusing a second patch")
    if source.count(BLOCK_START) != 1:
        raise PatchError("pinned Mono callback start anchor is missing or ambiguous")
    start = source.index(BLOCK_START)
    if source.count(BLOCK_END, start) != 1:
        raise PatchError("pinned native-array callback boundary is missing or ambiguous")
    end = source.index(BLOCK_END, start) + len(BLOCK_END)

    # The first line of the template starts at column zero; the remaining lines
    # retain the indentation of the original Mono callback block.
    control_block = "                    " + control_block
    source = source[:start] + control_block.rstrip("\n") + source[end:]
    include_at = source.index(MONO_INCLUDE) + len(MONO_INCLUDE)
    return source[:include_at] + CONTROL_INCLUDE + source[include_at:]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def apply(backend: Path, workspace: Path, manifest_path: Path) -> dict:
    backend = backend.resolve()
    workspace = workspace.resolve()
    manifest_path = manifest_path.resolve()
    try:
        manifest_path.relative_to(backend)
    except ValueError:
        pass
    else:
        raise PatchError("write the generated patch manifest outside the backend checkout")

    head = git(backend, "rev-parse", "HEAD")
    if head != BACKEND_COMMIT:
        raise PatchError(f"backend HEAD {head} does not match pinned commit {BACKEND_COMMIT}")
    status = git(backend, "status", "--porcelain=v1", "--untracked-files=all")
    if status:
        raise PatchError("backend checkout is not clean before patching")

    component = backend / COMPONENT
    original_blob = git(backend, "hash-object", f"--path={COMPONENT.as_posix()}", str(component))
    if original_blob != COMPONENT_BLOB:
        raise PatchError(f"D3D12Component.cpp blob {original_blob} does not match pinned source {COMPONENT_BLOB}")

    template_path = workspace / "duoview/restart/backend/MonoControlBlock.inl"
    template = template_path.read_text(encoding="utf-8")
    source = component.read_text(encoding="utf-8")
    transformed = transform_source(source, template)
    component.write_text(transformed, encoding="utf-8", newline="\n")

    generated = {
        VR_DIR / "DuoViewRestartDiagnostics.hpp": workspace / "duoview/restart/DuoViewRestartDiagnostics.hpp",
        VR_DIR / "StableSourceMaskD3D12.hpp": workspace / "duoview/restart/backend/StableSourceMaskD3D12.hpp",
    }
    for target, origin in generated.items():
        destination = backend / target
        if destination.exists():
            raise PatchError(f"refusing to overwrite existing backend file: {target}")
        destination.write_bytes(origin.read_bytes())

    report = {
        "backend_commit": BACKEND_COMMIT,
        "component_original_blob": COMPONENT_BLOB,
        "component": COMPONENT.as_posix(),
        "files": {
            path.as_posix(): sha256(backend / path)
            for path in (COMPONENT, *generated.keys())
        },
        "patch_template_sha256": sha256(template_path),
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"Applied pinned stable-source/moving-mask patch to {backend}")
    print(f"Generated-source manifest: {manifest_path}")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--backend", type=Path, required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    arguments = parser.parse_args()
    apply(arguments.backend, arguments.workspace, arguments.manifest)
