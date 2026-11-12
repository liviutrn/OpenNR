#!/usr/bin/env python3
"""Release contract AFTER the DuoView/TriView compatibility patch.

Static contract; the Windows CheekyTests.exe covers behavioral cases.
A Windows build is still not an STALKER 2 / PSVR2 hardware validation.
"""
from pathlib import Path
import sys
r = Path(sys.argv[1])
get = lambda path: (r / path).read_text(encoding="utf-8")
state = get("src/settings.cpp")
hooks = get("src/hooks.cpp")
nr = get("src/dlss_nr.cpp")
settings = get("src/settings.hpp")
ui = get("uevr/scripts/cheeky_foveated_dlss.lua")
gaze = get("tests/gaze_tests.cpp")
tests = {
    "DuoView positive subrect identity required": "ngx_output_base_valid" in state and
        "if (n == 2U)" in state and "fovea->view_id ? 1U" in state,
    "TriView original 3/4 classifier retained": "if (n != 3U && n != 4U) return 0U;" in state
        and "if (pairs != 1U) return 0U;" in state,
    "NGX source subrect checked for actual presence": 'parameters->Get("DLSS.Output.Subrect.Base.X", &ngx_base_x)' in hooks,
    "source subrect tracked by live view id": "note_stereo_view_output_subrect(physical_id" in hooks
        and "void note_stereo_view_output_subrect(" in settings,
    "unverified and ambiguous DuoView fail closed": "if (!fovea || !periphery ||" in state
        and "if (!different_input && !different_output) return 0U;" in state,
    "periphery forbidden pass 1": "const auto first = settings.nr_pass1_views & 3U;" in state,
    "periphery forbidden pass 2": "settings.nr_pass2_views & 3U" in state,
    "persisted old periphery masks sanitized": "nr_pass1_views = settings.nr_pass1_views & 3U;" in state
        and "nr_pass2_views = settings.nr_pass2_views & 3U;" in state,
    "periphery GPU resources retired": "view.source_role == 4U ||" in nr,
    "old pass selector still independent": "nr_pass1_views" in state and "nr_pass2_views" in state,
    "periphery removed from live UI": "Periphery only" not in ui
        and 'combo("Pass 1 source views"' in ui and 'combo("Pass 2 source views"' in ui,
    "four runtime regression cases": all(s in gaze for s in [
        "DuoView positive subrect routes both passes only to mono fovea",
        "DuoView output subrect, not NGX handle order, chooses fovea",
        "Ordinary two-eye stereo is not guessed as DuoView",
        "Missing NGX subrect evidence fails closed",
        "Periphery-only legacy settings cannot enable any NR"]),
    "native DLSS SR remains game-owned": "NR-LITE: game-native DLSS SR is always authoritative" in hooks,
    "Faithful HDR still present": "NrReconstructionMode" in ui,
}
for k,v in tests.items(): print(("PASS " if v else "FAIL ") + k)
if not all(tests.values()): raise SystemExit("Failed DuoView/TriView safety gate")
print("PASS DuoView + TriView fovea-only compatibility source contract")
