#!/usr/bin/env python3
"""Fail-fast regression check for exact source transformer startup ABI contract."""
from pathlib import Path

root=Path(__file__).resolve().parents[2]
patch=(root/"duoview/joey_stage1/apply_stage234.py").read_text(encoding="utf-8")
verify=(root/"duoview/joey_stage1/verify_stage234.py").read_text(encoding="utf-8")
correct="runtime && runtime->error.has_value()"
if patch.count(correct)!=2:
    raise AssertionError("Expected two runtime error optionals to be engaged-tested, not treated as strings")
if "runtime->error.empty()" in patch or "!runtime->error.has_value()" in patch:
    raise AssertionError("Disallowed invalid or inverted runtime-error test")
if f'vr_cpp.count("{correct}") != 2' not in verify or '"runtime->error.empty()" in vr_cpp' not in verify:
    raise AssertionError("Source verifier must check both optional runtime-error startup guards")
print("Pinned VRRuntime::error optional engagement and MSVC source guard passed")
