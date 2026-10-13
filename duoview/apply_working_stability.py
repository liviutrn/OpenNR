#!/usr/bin/env python3
"""Repair a specific shared Present-path error in the user-tested Injector-5.

Run AFTER apply_public_mono.py and apply_public_duoview.py on the pinned
public UEVR revision. Do not alter foveal geometry, gaze, frame keys, shader,
projection or OpenXR copy code.
"""
import argparse
from pathlib import Path

def repair(source: str) -> str:
    old = """void D3D12Component::on_post_present(VR* vr) {
    if (vr->is_mono_transition_quiescing() || vr->is_mono_transition_waiting() || m_mono_block_post_present) { return; }
    if (m_graphics_memory != nullptr) {"""
    new = """void D3D12Component::on_post_present(VR* vr) {
    // The old early-return skipped DX12 graphics-memory Commit() on every
    // quiesced/blocked frame, including Native frames after a Mono transition.
    // ALWAYS retire graphics-memory allocations; suppress only the backbuffer
    // clear while the Mono source or a transition owns its content.
    const bool defer_backbuffer_clear =
        vr->is_mono_transition_quiescing() ||
        vr->is_mono_transition_waiting() ||
        m_mono_block_post_present;
    if (m_graphics_memory != nullptr) {"""
    if source.count(old) != 1:
        raise RuntimeError("Unexpected on_post_present layout; refuse unsafe rewrite")
    source=source.replace(old,new,1)
    start=source.index("void D3D12Component::on_post_present(VR* vr) {")
    end=source.index("\nvoid D3D12Component::on_reset(",start)
    block=source[start:end]
    old_clear="""if (vr->is_hmd_active()) {
        clear_backbuffer();
    }"""
    new_clear="""if (vr->is_hmd_active() && !defer_backbuffer_clear) {
        clear_backbuffer();
    }"""
    if block.count(old_clear) != 1 or block.count("m_graphics_memory->Commit(command_queue);") != 1:
        raise RuntimeError("Graphics memory and backbuffer clear not uniquely identified")
    source=source[:start]+block.replace(old_clear,new_clear,1)+source[end:]
    result=source[start:source.index("\nvoid D3D12Component::on_reset(",start)]
    if result.index("m_graphics_memory->Commit(command_queue);") > result.index("if (vr->is_hmd_active() && !defer_backbuffer_clear)"):
        raise RuntimeError("Unexpected Present ordering")
    if " { return; }" in result:
        raise RuntimeError("Legacy premature return still present in on_post_present")
    return source

def main():
    p=argparse.ArgumentParser()
    p.add_argument("backend_root",type=Path)
    args=p.parse_args()
    file=args.backend_root/"src/mods/vr/D3D12Component.cpp"
    original=file.read_text(encoding="utf-8")
    updated=repair(original)
    file.write_text(updated,encoding="utf-8")
    print("Restored unconditional DX12 graphics-memory Commit; restricted transition guard to backbuffer clear.")
    print("DuoView foveation, camera, gaze, projection and compositor paths unchanged.")

if __name__=="__main__":
    main()
