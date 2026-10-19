#!/usr/bin/env python3
"""Verify the copied DuoView source files against the Build182 baseline."""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "BASELINE_SOURCE_SHA256SUMS"


def main() -> int:
    failures: list[str] = []
    for line in MANIFEST.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        expected, relative_path = line.split("  ", 1)
        path = ROOT / relative_path
        if not path.is_file():
            failures.append(f"missing: {relative_path}")
            continue
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != expected:
            failures.append(f"changed: {relative_path}")

    expected_paths = {
        line.split("  ", 1)[1]
        for line in MANIFEST.read_text(encoding="utf-8").splitlines()
        if line.strip()
    }
    actual_paths = {
        path.relative_to(ROOT).as_posix()
        for path in (ROOT / "duoview").rglob("*")
        if path.is_file()
    }
    failures.extend(f"unmanifested: {path}" for path in sorted(actual_paths - expected_paths))
    if failures:
        print("Build182 source verification failed:", file=sys.stderr)
        print("\n".join(f"- {failure}" for failure in failures), file=sys.stderr)
        return 1

    print(f"Verified {len(expected_paths)} Build182 source files.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
