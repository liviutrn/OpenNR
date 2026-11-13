#!/usr/bin/env python3
"""Post-generation source contracts for NR VRAM guard, not a replacement for C++ tests."""
from pathlib import Path
import sys
root=Path(sys.argv[1]).resolve()
read=lambda p:(root/p).read_text(encoding="utf-8")
hpp=read("src/settings.hpp")
settings=read("src/settings.cpp")
io=read("uevr/settings_io.cpp")
fields=read("uevr/settings_fields.inc")
policy=read("uevr/nr_lite_budget_policy.hpp")
runtime=read("uevr/runtime.cpp")
ui=read("uevr/scripts/cheeky_foveated_dlss.lua")
tests=read("tests/nr_processing_tests.cpp")
hooks=read("src/hooks.cpp")
checks={
 "fresh settings use 1536 MiB":
    "nr_vram_guard_mib{1536U}" in hpp and
    "nr_vram_guard_mib{1536U}" in settings,
 "live settings atomic round trip":
    "settings.nr_vram_guard_mib = nr_vram_guard_mib.load" in settings and
    "nr_vram_guard_mib.store((std::clamp)(settings.nr_vram_guard_mib" in settings,
 "persistence and runtime setting key":
    'CHEEKY_SETTING("NrVramGuardMiB", nr_vram_guard_mib)' in fields and
    'key == "NrVramGuardMiB"' in io,
 "range validated and clamped":
    "limit < 512U || limit > 4096U" in io and
    "(std::clamp)(requested.nr_vram_guard_mib, 512U, 4096U)" in policy,
 "runtime uses actual effective guard":
    "nr_lite_effective_headroom(previous, next)" in runtime and
    "nr_lite_has_headroom(required, valid, usage, budget)" in runtime,
 "no allocation bypass or new model feature on cap-only change":
    "if (!policy) return 0ULL;" in policy and
    "return (std::min)(policy, cap);" in policy,
 "log shows original policy and user cap":
    "policyMiB=%llu capMiB=%u" in runtime and
    "reserveMiB=%llu" in runtime,
 "template load does not silently edit guard":
    'std::string_view(name) != "NrVramGuardMiB"' in runtime,
 "in-game slider with live headroom":
    'slider("Max VRAM admission reserve (MiB)", "NrVramGuardMiB", 512, 4096, true)' in ui and
    'DXGI free:' in ui,
 "actual C++ regression coverage":
    "Guard caps the policy requirement at default 1536 MiB" in tests and
    "Unknown DXGI headroom must still fail closed" in tests and
    "Small model rekey preserves old 768 MiB" in tests,
 "previous native SR and Fable source retirement preserved":
    "NR-LITE: game-native DLSS SR is always authoritative" in hooks and
    "selected.role != view.source_role" in read("src/dlss_nr.cpp"),
}
for name,ok in checks.items():print(("PASS " if ok else "FAIL ")+name)
if not all(checks.values()):raise SystemExit("NR VRAM adjustable guard source gate FAILED")
print("PASS adjustable NR VRAM guard generated-source contract")
