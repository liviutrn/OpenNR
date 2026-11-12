#!/usr/bin/env python3
"""Generated-source contract for reviewed, explicitly selected Duo/Tri NR targeting.

Static tests complement, but do not replace, Windows behavioral tests and headset verification.
"""
from pathlib import Path
import sys

r = Path(sys.argv[1])
read = lambda path: (r / path).read_text(encoding="utf-8")
state = read("src/settings.cpp")
settings = read("src/settings.hpp")
nr = read("src/dlss_nr.cpp")
inputs = read("src/dlss_nr_input.cpp")
runtime = read("uevr/runtime.cpp")
budget = read("uevr/nr_lite_budget_policy.hpp")
ui = read("uevr/scripts/cheeky_foveated_dlss.lua")
io = read("uevr/settings_io.cpp")
tests = read("tests/gaze_tests.cpp")
hooks = read("src/hooks.cpp")
checks = {
    "four explicit persisted layouts": all(
        x in settings for x in ["nr_target_mode{2U}", "nr_duo_fovea_source{0U}",
                              "case 0U: return 1U", "case 1U: return 5U",
                              "case 2U: return 3U", "case 3U: return 7U"]),
    "independent pass masks preserved incl periphery opt-in":
        "const auto first = settings.nr_pass1_views & allowed" in state
        and "settings.nr_pass2_views & allowed" in state,
    "Duo uses observed input geometry, not assumed atlas offset":
        "v[0]->evaluation_input_width" in state and "compare_area(" in state
        and "ngx_output_base_x" not in state[state.index("std::uint32_t cheeky_nr_source_role_for("):
                                               state.index("std::uint32_t cheeky_nr_selected_passes(")],
    "Duo has explicit manual fallback":
        "settings.nr_duo_fovea_source == 1U" in state,
    "Duo no-guess when partial masks / equal source dimensions":
        "full_or_none(settings.nr_pass1_views)" in state
        and "if (!identified) return 0U" in state,
    "TriView original three/four-source classifier kept":
        "if (pairs != 1U) return 0U;" in state and
        "if (settings.nr_target_mode < 2U || (n != 3U && n != 4U))" in state,
    "unselected sources avoid Before-SR input allocation":
        "cheeky_nr_selected_passes(settings, frame.view_id) == 0U" in inputs and
        inputs.index("cheeky_nr_selected_passes(settings, frame.view_id) == 0U") <
        inputs.index("std::lock_guard execution_lock(calibration12_execution_mutex());", 
                     inputs.index("ID3D12Resource* prepare_dlss_nr_input(")),
    "actual NR feature retirement stays fence-aware":
        "release_dlss_nr_resources(); // GPU-fence-aware full mode switch" in runtime
        and "collect_retired_views()" in nr,
    "budget uses eligible sources and considers Duo/Tri switching":
        "cheeky_nr_target_mask(requested)" in budget
        and "current.nr_target_mode / 2U != requested.nr_target_mode / 2U" in budget,
    "separate pass UI and four modes":
        all(x in ui for x in ["DuoView Mono: fovea only", "DuoView Mono: fovea + periphery",
                            "TriView Stereo: both foveas", "TriView Stereo: all three",
                            "Pass 1 source views", "Pass 2 source views",
                            "Duo mono fovea source"]),
    "NR template loads preserve current Duo/Tri target mode":
        'std::string_view(name) != "NrTargetMode"' in runtime and
        'std::string_view(name) != "NrDuoFoveaSource"' in runtime,
    "existing saved settings consumed with bounds":
        'key=="NrTargetMode"' in io and 'parsed > (key=="NrTargetMode" ? 3U : 2U)' in io
        and "(mask & 7U)" in io,
    "focused real source observer tests":
        all(x in tests for x in [
          "Duo fovea-only routes by actual region resolution",
          "Duo fovea plus periphery enables both sources intentionally",
          "TriView all-three opt-in runs both passes on peripheral source",
          "Duo all-sources mode works even when both input areas are equal",
          "Identical source dimensions fail closed in fovea-only mode",
          "Explicit Duo source A can identify equal-size resources",
          "Explicit Duo source B can identify equal-size resources",
          "Duo physical source order and role can reverse",
          "Ambiguous Duo source identity never guesses a partial pass mask"]),
    "existing native SR unchanged":
        "NR-LITE: game-native DLSS SR is always authoritative" in hooks,
    "existing HDR reconstruction retained": "NrReconstructionMode" in ui,
}
for k, v in checks.items():
    print(("PASS " if v else "FAIL ") + k)
if not all(checks.values()):
    raise SystemExit("Explicit-source-mode contract failed")
print("PASS reviewed four-mode DuoView/TriView generated-source contract")
