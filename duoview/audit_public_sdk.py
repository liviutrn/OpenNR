#!/usr/bin/env python3
"""Offline dependency audit: Joey Sept-2026 UEVR vs July-2026 public UESDK.

Only reports facts: missing headers under sdk/, and the top three references.
This cannot establish SDK ABI or behavior compatibility.
"""
from __future__ import annotations

import collections
import pathlib
import re
import sys

if len(sys.argv) != 3:
    raise SystemExit("usage: audit_public_sdk.py <uevr_root> <public_sdk_root>")

uevr = pathlib.Path(sys.argv[1])
sdk = pathlib.Path(sys.argv[2]) / "src" / "sdk"
if not sdk.is_dir():
    raise SystemExit("public SDK tree not found: " + str(sdk))

include = re.compile(r'^\s*#\s*include\s*[<"]sdk/([^">]+)[">]')
uses: dict[str, list[str]] = collections.defaultdict(list)
scan_roots = ["src", "tests", "shared", "include"]
for root in scan_roots:
    src_root = uevr / root
    if not src_root.is_dir():
        continue
    for path in src_root.rglob("*"):
        if path.suffix not in (".h", ".hpp", ".cpp", ".inl", ".cc"):
            continue
        try:
            content = path.read_text(encoding="utf-8-sig", errors="replace")
        except OSError:
            continue
        for n, line in enumerate(content.splitlines(), 1):
            m = include.match(line)
            if m:
                uses[m.group(1)].append(f"{path.relative_to(uevr)}:{n}")

all_refs = sorted(uses)
missing = [item for item in all_refs if not (sdk / item).is_file()]
print("Joey UEVR: pinned db6729dd9f5745705b1cdec2ec6f51bdc9570983")
print("Public SDK: elliotttate/UESDK-RenderDoc 418729025bad57b094bf6b2e2b55734454c97de6")
print(f"Distinct direct SDK headers referenced: {len(all_refs)}")
print(f"Present in candidate: {len(all_refs)-len(missing)}")
print(f"MISSING: {len(missing)}")
for name in missing:
    refs = uses[name]
    print(f"  MISSING src/sdk/{name} ({len(refs)} uses)")
    for where in refs[:4]:
        print("    " + where)
print("Existing SDK header inventory:", len(list(sdk.rglob("*.hpp"))))
print("This is a header-availability report, NOT proof of compile/ABI compatibility.")
