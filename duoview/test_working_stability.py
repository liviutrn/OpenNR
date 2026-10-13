#!/usr/bin/env python3
"""Regression: a transition must never suppress DX12 allocation retirement."""
import importlib.util
from pathlib import Path

script=Path(__file__).with_name("apply_working_stability.py")
spec=importlib.util.spec_from_file_location("stability",script)
module=importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
before="""void D3D12Component::on_post_present(VR* vr) {
    if (vr->is_mono_transition_quiescing() || vr->is_mono_transition_waiting() || m_mono_block_post_present) { return; }
    if (m_graphics_memory != nullptr) {
        auto& hook = g_framework->get_d3d12_hook();
        auto device = hook->get_device();
        auto command_queue = hook->get_command_queue();
        m_graphics_memory->Commit(command_queue);
    }
    if (vr->is_hmd_active()) {
        clear_backbuffer();
    }
}
void D3D12Component::on_reset(VR* vr, bool mono_retired) {
}
"""
after=module.repair(before)
assert after.count("m_graphics_memory->Commit(command_queue);")==1
block=after.split("void D3D12Component::on_post_present(VR* vr) {")[1].split("void D3D12Component::on_reset(")[0]
assert "return;" not in block
assert "m_mono_block_post_present;" in block
assert "vr->is_hmd_active() && !defer_backbuffer_clear" in block
assert block.index("m_graphics_memory->Commit(command_queue);") < block.index("clear_backbuffer();")
assert before!=after
for bad in [
    before.replace("m_graphics_memory->Commit(command_queue);","m_graphics_memory->Reset();"),
    before.replace("if (vr->is_hmd_active())","if (vr->is_hmd_active() && 1)"),
    before.replace("m_mono_block_post_present) { return; }","m_mono_block_post_present) { /*skip*/ }"),
]:
    try: module.repair(bad)
    except RuntimeError: pass
    else: raise AssertionError("Must reject unexpected renderer source")
print("Production Present-path repair + fail-closed source patch tests PASS")
