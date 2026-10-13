#!/usr/bin/env python3
"""Fix DuoView's known false-negative OpenXR frame validation.

Run after apply_public_mono.py, apply_public_duoview.py and
apply_working_stability.py. Do not change visual rendering, camera, gaze,
projection math, DX12 copy/barriers, or any runtime frame timestamp.
"""
import argparse
from pathlib import Path

def replace_once(text, old, new, what):
    n=text.count(old)
    if n!=1: raise RuntimeError(f"{what}: expected one exact anchor; found {n}")
    return text.replace(old,new,1)

def repair(source):
    # The callback can be invoked more than once with the same frame_count.
    # The old unconditional reset then erases projection+main-family evidence
    # from a frame which may already have passed its UE view callbacks.
    source=replace_once(source,
        """    auto& pipeline_state = this->pipeline_states[frame_count % OpenXR::QUEUE_SIZE];
    if (vr->mono_frame_gate_required()) { mono_frames[frame_count % QUEUE_SIZE] = {}; }""",
        """    auto& pipeline_state = this->pipeline_states[frame_count % OpenXR::QUEUE_SIZE];
    if (vr->mono_frame_gate_required()) {
        auto& evidence = mono_frames[frame_count % QUEUE_SIZE];
        // Preserve already-observed projection and main UE view-family
        // callbacks during repeated pose refreshes for the SAME frame.
        // A new (generation, frame) still clears all old evidence.
        if (evidence.generation != vr->mono_generation() || evidence.pose_frame != frame_count) {
            evidence = {};
        }
    }""",
        "same-frame pose evidence retention")
    # Main-family callback is its own proof. Requiring a projection callback
    # to have happened BEFORE the family callback unnecessarily imposes a
    # callback order not promised by UEVR's public SDK.
    source=replace_once(source,
        """    entry.main_family = entry.pose_frame == frame && entry.projection_frame == frame &&
        entry.generation == VR::get()->mono_generation();""",
        """    // Family and projection callbacks can arrive in either order.
    // Both remain mandatory at has_mono_frame(), where each frame identity
    // is checked independently. Do not discard family evidence only because
    // the projection callback has not fired yet.
    entry.main_family = entry.pose_frame == frame &&
        entry.generation == VR::get()->mono_generation();""",
        "independent view family admission")
    old="""    return entry.pose_valid && uevr::mono::frame_matches(VR::get()->mono_generation(), entry.generation,
        frame, entry.pose_frame, entry.projection_frame, entry.main_family) &&
        (!VR::get()->is_using_mono() || entry.geometry.has_value());"""
    new="""    const bool valid = entry.pose_valid &&
        uevr::mono::frame_matches(VR::get()->mono_generation(), entry.generation,
            frame, entry.pose_frame, entry.projection_frame, entry.main_family) &&
        (!VR::get()->is_using_mono() || entry.geometry.has_value());
    if (!valid) {
        // Rate-limited; exact reasons let us distinguish true invalid scene
        // evidence from false negatives without logging every VR frame.
        SPDLOG_WARNING_EVERY_N_SEC(2,
            "[DuoView] Mono frame rejected: frame={} generation={} stored_generation={} pose_frame={} projection_frame={} valid_pose={} main_family={} geometry={}",
            frame, VR::get()->mono_generation(), entry.generation, entry.pose_frame,
            entry.projection_frame, entry.pose_valid, entry.main_family, entry.geometry.has_value());
    }
    return valid;"""
    source=replace_once(source,old,new,"frame gate diagnostics")
    return source

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("backend_root",type=Path)
    opts=parser.parse_args()
    file=opts.backend_root/"src/mods/vr/runtimes/OpenXR.cpp"
    original=file.read_text(encoding="utf-8")
    modified=repair(original)
    file.write_text(modified,encoding="utf-8")
    print("DuoView pose evidence preserved on repeated same-frame updates; family callback no longer depends on prior projection; rate-limited frame rejection reasons enabled.")

if __name__ == "__main__": main()
