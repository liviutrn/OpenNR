#!/usr/bin/env python3
"""Validate exact production-source transformation and its ordering contract."""
from pathlib import Path
import importlib.util
script=Path(__file__).with_name("apply_frame_pacing_v14.py")
spec=importlib.util.spec_from_file_location("fovea_gate",script)
module=importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
original="""void OpenXR::sample(uint32_t frame_count) {
    auto vr = VR::get();
    auto& pipeline_state = this->pipeline_states[frame_count % OpenXR::QUEUE_SIZE];
    if (vr->mono_frame_gate_required()) { mono_frames[frame_count % QUEUE_SIZE] = {}; }
}
void OpenXR::note_mono_main_family(uint32_t frame, bool main_family) {
    auto& entry = mono_frames[frame % QUEUE_SIZE];
    entry.main_family = entry.pose_frame == frame && entry.projection_frame == frame &&
        entry.generation == VR::get()->mono_generation();
}
bool OpenXR::has_mono_frame(uint32_t frame) {
    const auto& entry = mono_frames[frame % QUEUE_SIZE];
    return entry.pose_valid && uevr::mono::frame_matches(VR::get()->mono_generation(), entry.generation,
        frame, entry.pose_frame, entry.projection_frame, entry.main_family) &&
        (!VR::get()->is_using_mono() || entry.geometry.has_value());
}
"""
modified=module.repair(original)
assert modified!=original
assert "evidence.generation != vr->mono_generation() || evidence.pose_frame != frame_count" in modified
assert "entry.pose_frame == frame &&\n        entry.generation" in modified
assert "entry.projection_frame == frame &&" not in modified.split("void OpenXR::note_mono_main_family")[1].split("bool OpenXR::has_mono_frame")[0]
assert "frame_matches(" in modified
assert "geometry.has_value()" in modified
assert "SPDLOG_WARNING_EVERY_N_SEC(2," in modified
for bad in [original.replace("mono_frames[frame_count % QUEUE_SIZE] = {};","mono_frames[frame_count % QUEUE_SIZE].reset();"),
            original.replace("entry.projection_frame == frame &&","true &&"),
            original.replace("entry.pose_valid &&","true &&")]:
    try:module.repair(bad)
    except RuntimeError:pass
    else:raise AssertionError("Unexpected upstream code must fail closed")

# Simulate the bug on real callback ordering with immutable frame keys.
def observed_sequence(repeated_pose_update, projection_before_family):
    frame=42
    st={"generation":0, "pose_frame":0, "pose_valid":False, "projection_frame":0, "main_family":False}
    def pose():
        nonlocal st
        # v14 only resets on a *different* (generation,frame) key.
        if st["generation"]!=1 or st["pose_frame"]!=frame:
            st={"generation":0, "pose_frame":0, "pose_valid":False, "projection_frame":0, "main_family":False}
        st["generation"]=1;st["pose_frame"]=frame;st["pose_valid"]=True
    def family():
        st["main_family"]=st["pose_frame"]==frame and st["generation"]==1
    def projection():
        st["projection_frame"]=frame
    pose()
    if projection_before_family:projection();family()
    else:family();projection()
    if repeated_pose_update:pose()
    return st["pose_valid"] and st["main_family"] and st["generation"]==1 and st["pose_frame"]==frame and st["projection_frame"]==frame

for repeated in (False,True):
    for ordering in (False,True):
        assert observed_sequence(repeated,ordering), (repeated,ordering)
print("v14 true production XR code patch, repeated same-frame pose refresh, and callback order regressions PASS")
