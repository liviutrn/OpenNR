#!/usr/bin/env python3
"""Post-Fable source-level safety contract for generated Cheeky 0.6.3.

Pure inspection complements the C++ source observer and Windows GPU tests.
"""
from pathlib import Path
import sys
root=Path(sys.argv[1])
load=lambda p:(root/p).read_text(encoding="utf-8")
settings=load("src/settings.cpp")
header=load("src/settings.hpp")
hooks=load("src/hooks.cpp")
ui=load("uevr/scripts/cheeky_foveated_dlss.lua")
tests=load("tests/gaze_tests.cpp")
nr=load("src/dlss_nr.cpp")
runtime=load("uevr/runtime.cpp")
checks={
  "all four requested user modes persist":
    all(x in ui for x in ("DuoView Mono: fovea only","DuoView Mono: fovea + periphery",
                         "TriView Stereo: both foveas","TriView Stereo: all three")),
  "periphery only opt-in":
    "settings.nr_target_mode == 3U" in header and
    "case 0U: return 1U;" in header and "case 2U: return 3U;" in header,
  "Quad-compatible periphery only on 3-source explicit Tri ALL":
    "physical_source_count==3U" in settings and
    "cheeky_nr_tri_periphery_requested(settings)" in settings,
  "manual Duo ambiguity fail closed":
    "if (!identified) return 0U" in settings,
  "no source ID guess from NGX output alone":
    "identified = (input && output && input != output) ? 0 : input;" in settings and
    "Duo output-only area difference cannot infer the fovea" in tests,
  "Duo both allowed ONLY explicitly and all passes opted in":
    "settings.nr_target_mode == 1U" in settings and
    "full_or_none(settings.nr_pass1_views)" in settings and
    "full_or_none(settings.nr_pass2_views)" in settings,
  "source menu scoped by four modes":
    all(x in ui for x in ("mode == 0 and {1,0}","mode == 1 and {5,1,4,0}",
                         "mode == 2 and {3,1,2,0}","source_combo(\"Pass 2 source views\"")),
  "route change diagnostic includes mode, source sizes, role and pass masks":
    "[CheekyNR][RouteChange]" in hooks and
    "last_observation.exchange(hash" in hooks and "cheeky_nr_observed_sources()" in settings,
  "native SR and both-model lifetime preserved":
    "NR-LITE: game-native DLSS SR is always authoritative" in hooks and
    "collect_retired_views()" in nr and
    "release_dlss_nr_resources(); // GPU-fence-aware full mode switch" in runtime,
}
for name,passed in checks.items():
    print(("PASS " if passed else "FAIL ")+name)
if not all(checks.values()):
    raise SystemExit("Fable review post-patch source contract FAILED")
print("PASS Fable review generated-source contract")
