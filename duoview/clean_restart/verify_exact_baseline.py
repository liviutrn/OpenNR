"""Require the original pinned SDK and unchanged Joey sources before packaging."""

import argparse
import hashlib
import json
from pathlib import Path

from audit_sources import audit, git


def verify(lock_path, backend, frontend, output):
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    sdk = backend / "dependencies/submodules/UESDK"
    expected_sdk = lock["backend"]["sdk_commit"]
    if git(sdk, "rev-parse", "HEAD") != expected_sdk:
        raise ValueError("Only the exact original Joey SDK is accepted")
    if git(sdk, "rev-parse", "HEAD^{tree}") != "c958569565e435c8670caec726eece63ac7c317b":
        raise ValueError("Original SDK tree differs")
    report = audit(lock, backend, sdk, output)
    if report["missing_direct_sdk_headers"] or report["missing_sdk_test_sources"]:
        raise ValueError("Original SDK source is incomplete")
    actual_frontend = git(frontend, "rev-parse", "HEAD")
    if actual_frontend != lock["frontend"]["commit"]:
        raise ValueError("Unexpected matching frontend source")
    generated = "UEVR/FilteredExecutables.json"
    changed = git(frontend, "diff", "--name-only", "HEAD").splitlines()
    if set(changed) - {generated}:
        raise ValueError("Original frontend source was modified")
    git(frontend, "diff", "--exit-code", "HEAD", "--", ".", f":(exclude){generated}")
    if generated in changed:
        inputs = json.loads((frontend / "UEVR/PlainTextFilteredExecutables.json").read_text(encoding="utf-8"))
        expected = json.dumps([hashlib.sha256(name.encode()).hexdigest().upper() for name in inputs], indent=4)
        if (frontend / generated).read_text(encoding="utf-8") != expected:
            raise ValueError("Frontend generated resource differs from its original build script")
    for source in (backend, sdk, frontend):
        untracked = git(source, "ls-files", "--others", "--exclude-standard")
        if untracked:
            raise ValueError(f"Untracked files could affect source identity: {source.name}: {untracked}")
    report.update(frontend_commit=actual_frontend, exact_original_sdk=True,
                  sdk_tree="c958569565e435c8670caec726eece63ac7c317b",
                  duoview_integrated=False, reconstructed_sdk_integrated=False,
                  frontend_generated_resource_verified=generated in changed)
    (output / "exact-baseline-source.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print("Exact original Joey backend, SDK, frontend and source completeness verified")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("lock", type=Path)
    parser.add_argument("backend", type=Path)
    parser.add_argument("frontend", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    verify(args.lock, args.backend, args.frontend, args.output)
