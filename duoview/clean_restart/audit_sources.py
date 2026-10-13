import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path


def git(root, *args):
    return subprocess.check_output(
        ["git", "-C", str(root), *args], text=True, encoding="utf-8"
    ).strip()


def audit(lock, backend, sdk, output):
    expected = lock["backend"]
    actual_backend = git(backend, "rev-parse", "HEAD")
    actual_sdk = git(sdk, "rev-parse", "HEAD")
    if actual_backend != expected["commit"]:
        raise RuntimeError(f"Unexpected Joey source: {actual_backend}")
    sdk_allowed = {expected["sdk_commit"], lock["public_sdk_diagnostic"]["commit"]}
    if actual_sdk not in sdk_allowed:
        raise RuntimeError(f"Unreviewed SDK source: {actual_sdk}")
    git(backend, "diff", "--exit-code", "--ignore-submodules=all", "HEAD")
    git(sdk, "diff", "--exit-code", "HEAD")
    sdk_gitlink = git(backend, "ls-tree", "HEAD", "dependencies/submodules/UESDK").split()[2]
    if sdk_gitlink != expected["sdk_commit"]:
        raise RuntimeError(f"Unexpected Joey SDK gitlink: {sdk_gitlink}")
    hashes = {}
    missing = {}
    sdk_includes = {}
    missing_sdk_test_sources = []
    for name in re.findall(r'"(dependencies/submodules/UESDK/[^"\n]+)"', (backend / "CMakeLists.txt").read_text(encoding="utf-8")):
        relative = Path(name).relative_to("dependencies/submodules/UESDK")
        if relative.parts[0] == "tests" and not (sdk / relative).is_file():
            missing_sdk_test_sources.append(str(relative).replace("\\", "/"))
    policy = (backend / "src/mods/vr/MonoRenderingPolicy.hpp").read_text(encoding="utf-8")
    if not re.search(r"method_id\s*=\s*5\s*;", policy):
        raise RuntimeError("Expected original Joey Mono ID 5 is absent")
    for name in git(backend, "ls-files").splitlines():
        path = backend / name
        if not path.is_file():
            continue
        hashes[name] = hashlib.sha256(path.read_bytes()).hexdigest()
        if path.suffix not in {".cpp", ".hpp", ".h"}:
            continue
        for header in re.findall(r'#\s*include\s*[<"](sdk/[^>"\n]+)', path.read_text(encoding="utf-8", errors="replace")):
            sdk_includes.setdefault(header, []).append(name)
            if not (sdk / "src" / header).is_file():
                missing.setdefault(header, []).append(name)
    report = {
        "backend_commit": actual_backend,
        "required_sdk_commit": sdk_gitlink,
        "actual_sdk_commit": actual_sdk,
        "sdk_matches_original": actual_sdk == sdk_gitlink,
        "backend_tracked_source_unmodified": True,
        "sdk_tracked_source_unmodified": True,
        "missing_direct_sdk_headers": dict(sorted(missing.items())),
        "missing_sdk_test_sources": sorted(set(missing_sdk_test_sources)),
        "original_mono_method_id": 5,
        "direct_sdk_header_count": len(sdk_includes),
        "full_backend_compatibility_verified": False,
        "headset_stability_verified": False,
    }
    output.mkdir(parents=True, exist_ok=True)
    (output / "source-audit.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    (output / "backend-source-sha256.json").write_text(json.dumps(hashes, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("lock", type=Path)
    parser.add_argument("backend", type=Path)
    parser.add_argument("sdk", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    audit(json.loads(args.lock.read_text(encoding="utf-8")), args.backend, args.sdk, args.output)
