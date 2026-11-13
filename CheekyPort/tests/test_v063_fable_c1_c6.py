#!/usr/bin/env python3
"""Independent source checks after Fable C1-C6 patch and compiled C++ tests."""
from pathlib import Path
import sys
r=Path(sys.argv[1]); load=lambda p:(r/p).read_text(encoding="utf-8")
settings=load("src/settings.cpp")
hpp=load("src/settings.hpp")
nr=load("src/dlss_nr.cpp")
hooks=load("src/hooks.cpp")
runtime=load("uevr/runtime.cpp")
budget=load("uevr/nr_lite_budget_policy.hpp")
fields=load("uevr/settings_fields.inc")
io=load("uevr/settings_io.cpp")
ui=load("uevr/scripts/cheeky_foveated_dlss.lua")
tests=load("tests/gaze_tests.cpp")
ntests=load("tests/nr_processing_tests.cpp")
checks={
  "same family mode switch no full release":
    "previous_nr_layout.nr_target_mode / 2U != settings.nr_target_mode / 2U" in runtime
    and "if (nr_family_changed) release_dlss_nr_resources();" in runtime,
  "source collector reclassifies outside nr mutex":
    "std::array<CheekyNrSelection,64> expected{};" in nr
    and "expected[i]=cheeky_nr_selection(live,physical_ids[i]);" in nr
    and "selected.role != view.source_role" in nr
    and "release_dlss_nr_inputs(changed_inputs[i]);" in nr,
  "Duo old saved handle key retired":
    'CHEEKY_SETTING("NrDuoFoveaSizeHint", nr_duo_fovea_source)' in fields
    and 'CHEEKY_SETTING("NrDuoFoveaSource", nr_duo_fovea_source)' not in fields
    and "candidate.nr_duo_fovea_source = 0U;" in io,
  "Duo forced sizes require separation":
    "identified = -input;" in settings and "identified = input;" in settings
    and "if (!identified) return 0U;" in settings,
  "selection single classification":
    "CheekyNrSelection cheeky_nr_selection(" in settings
    and "return cheeky_nr_selection(settings,view_id).passes;" in settings
    and "const auto selection = cheeky_nr_selection(settings, frame.view_id);" in nr
    and "const auto role = selection.role;" in nr,
  "native excluded-view skip not duplicated":
    "if (selected_passes && !processed && settings.eye_independent_coverage)" in hooks,
  "family switch budget uses target from scratch":
    "fresh.nr_enabled=false;" in budget
    and "return nr_lite_required_headroom(fresh,requested);" in budget,
  "simultaneous masks and hint use maximum reserve":
    "(std::max)(mask_reserve,hint_reserve)" in budget,
  "source liveness aligned":
    "view.evaluation_input_width || !view.evaluation_input_height" not in settings[
      settings.index("CheekyNrObservedSources cheeky_nr_observed_sources()"):
      settings.index("void note_stereo_view_output_subrect(")],
  "runtime effective masks and source-role status":
    'nr_routing' in runtime and "cheeky_nr_selection(nr_layout,source.view_id)" in runtime
    and "layout_mismatch" in runtime,
  "UI explicit family and mismatch warning":
    "NrDuoFoveaSizeHint" in ui and "LAYOUT MISMATCH" in ui
    and "EFFECTIVE running masks:" in ui and "VRAM GUARD:" in ui,
  "C++ classifier fixtures":
    "Forced smaller-input fovea" in tests and "Forced larger image never guesses" in tests,
  "C++ budget scenarios":
    "Tri->Duo reserves the REQUESTED" in ntests and
    "Duo both->fovea-only" in ntests,
  "native SR and Faithful HDR retained":
    "NR-LITE: game-native DLSS SR is always authoritative" in hooks
    and "NrReconstructionMode" in ui,
}
for k,v in checks.items():print(("PASS " if v else "FAIL ")+k)
if not all(checks.values()):raise SystemExit("Post-Fable source regression FAILED")
print("PASS C1-C6 post-generated source contract")
