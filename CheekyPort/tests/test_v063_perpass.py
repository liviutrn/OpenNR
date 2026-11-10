#!/usr/bin/env python3
"""Static contracts supplement (not replace) real Windows/UEVR test suites."""
from pathlib import Path
import sys
root=Path(sys.argv[1])
def has(path, fragments):
    data=(root/path).read_text(encoding="utf-8")
    for fragment in fragments:
        assert fragment in data, f"{path}: missing {fragment}"
has("src/settings.hpp",["nr_pass1_views{3U}","nr_pass2_views{3U}","nr_pass2_foveated{false}"])
has("src/settings.cpp",["cheeky_nr_source_role","cheeky_nr_selected_passes",
                        "role==0U","return 4U"])
has("src/dlss_nr.cpp",["evaluate_nr_selected_passes","frame.view_id ^ (1ULL << 63U)",
                       "pass_frame.view_id ^= (1ULL << 63U)",
                       "second.nr_foveated = settings.nr_pass2_foveated",
                       "second.nr_passes = 1U",
                       "evaluate_dlss_nr(pass_frame, second)",
                       "nr_gpu_stage_begin","nr_gpu_stage_end"])
has("src/dlss_nr_input.cpp",["evaluate_nr_selected_passes","before_input_copy"])
has("src/hooks.cpp",["nr_stage_measurement","nr_stage_model1","nr_stage_model2",
                     "nr_gpu_stage_begin","nr_gpu_stage_end",
                     "[CheekyNR][GPUStage]"])
has("uevr/runtime.cpp",["nr_lite_check_budget"])
has("uevr/nr_lite_budget_policy.hpp",["first_new","second_new","pass2_grows"])
has("uevr/scripts/cheeky_foveated_dlss.lua",["Pass 1 source views",
    "Pass 2 source views","NrPass2Foveated","last_apply_error",
    "ACTIVE TARGETS pass 1="])
has("tests/gaze_tests.cpp",["Pass1 all, pass2 foveas excludes peripheral pass2",
    "Independent pass mask routing","Pass2-only peripheral routing"])
# No shared NVIDIA feature: synthetic pass-2 view ID preserves history isolation.
# No forced NR on periphery; masks select every source independently.
print("NR independent-mask and GPU trace static contracts: OK")
