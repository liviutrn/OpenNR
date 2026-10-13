"""Require the original pinned SDK and unchanged Joey sources before packaging."""

import argparse
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
    git(frontend, "diff", "--exit-code", "HEAD")
    for source in (backend, sdk, frontend):
        if git(source, "ls-files", "--others", "--exclude-standard"):
            raise ValueError(f"Untracked files could affect source identity: {source.name}")
    report.update(frontend_commit=actual_frontend, exact_original_sdk=True,
                  sdk_tree="c958569565e435c8670caec726eece63ac7c317b",
                  duoview_integrated=False, reconstructed_sdk_integrated=False)
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
