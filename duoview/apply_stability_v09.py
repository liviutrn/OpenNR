#!/usr/bin/env python3
"""v09 original-backend stability overlay; apply after Mono and DuoView integrations.

This does NOT modify the working crop, gaze, camera, or compositing algorithms.
"""
from pathlib import Path
import argparse
import shutil

def change_once(text, old, new, name):
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f'{name}: expected one anchor, found {count}: {old[:80]!r}')
    return text.replace(old, new, 1)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('root', type=Path)
    root = parser.parse_args().root.resolve()
    source = Path(__file__).with_name('DuoViewStabilityDiagnostics.hpp')
    if not source.exists():
        raise RuntimeError('Missing diagnostics header')
    destination = root / 'src/mods/vr/DuoViewStabilityDiagnostics.hpp'
    if destination.exists():
        raise RuntimeError('v09 overlay already applied')
    shutil.copy2(source, destination)

    vr = root / 'src/mods/VR.cpp'
    s = '#include "vr/DuoViewStabilityDiagnostics.hpp"\n' + vr.read_text(encoding='utf-8')
    s = change_once(s,
        '    m_openxr->reset_mono_projection_history();\n    set_mono_status("Waiting for a current main-view projection and scene");',
        '''    m_openxr->reset_mono_projection_history();
    // Leaving Mono invalidates old Mono gates. Native frames must not be
    // rejected for lacking Mono-only projection/family metadata.
    if (!is_using_mono()) {
        m_mono_ready_generation.store(selection.generation(), std::memory_order_release);
        set_mono_status("Native rendering restored");
    } else {
        set_mono_status("Waiting for a current main-view projection and scene");
    }''', vr)
    s = change_once(s, 'void VR::on_present() {\n    ZoneScopedN(__FUNCTION__);',
        'void VR::on_present() {\n    uevr::duoview::stability::present_entry();\n    ZoneScopedN(__FUNCTION__);', vr)
    vr.write_text(s, encoding='utf-8')

    dx = root / 'src/mods/vr/D3D12Component.cpp'
    s = '#include "DuoViewStabilityDiagnostics.hpp"\n' + dx.read_text(encoding='utf-8')
    s = change_once(s, 'vr::EVRCompositorError D3D12Component::on_frame(VR* vr) {\n    m_mono_block_post_present',
        '''vr::EVRCompositorError D3D12Component::on_frame(VR* vr) {
    auto& diagnostic = uevr::duoview::stability::counters();
    diagnostic.frame_calls.fetch_add(1, std::memory_order_relaxed);
    uevr::duoview::stability::Duration frame_scope{diagnostic.max_frame_us};
    m_mono_block_post_present''', dx)
    s = change_once(s,
        '''        if (!vr->m_openxr->has_mono_frame(static_cast<uint32_t>(vr->m_frame_count))) {
            vr->m_openxr->end_mono_transition_frame();''',
        '''        if (!vr->m_openxr->has_mono_frame(static_cast<uint32_t>(vr->m_frame_count))) {
            diagnostic.rejected_mono_frames.fetch_add(1, std::memory_order_relaxed);
            vr->m_openxr->end_mono_transition_frame();''', dx)
    start = s.index('void D3D12Component::on_post_present(VR* vr) {')
    end = s.index('\nvoid D3D12Component::on_reset(', start)
    part = s[start:end]
    part = change_once(part,
        '    if (vr->is_mono_transition_quiescing() || vr->is_mono_transition_waiting() || m_mono_block_post_present) { return; }',
        '''    // Always retire graphics-memory allocations; only backbuffer clearing
    // is unsafe while a Mono producer/transition owns its source.
    const bool block_clear = vr->is_mono_transition_quiescing() ||
        vr->is_mono_transition_waiting() || m_mono_block_post_present;
    auto& diagnostic = uevr::duoview::stability::counters();
    diagnostic.post_presents.fetch_add(1, std::memory_order_relaxed);
    if (block_clear) diagnostic.clears_blocked.fetch_add(1, std::memory_order_relaxed);''', dx)
    part = change_once(part, '        m_graphics_memory->Commit(command_queue);',
        '''        {
            uevr::duoview::stability::Duration commit_scope{diagnostic.max_commit_us};
            m_graphics_memory->Commit(command_queue);
        }
        diagnostic.graphics_commits.fetch_add(1, std::memory_order_relaxed);''', dx)
    part = change_once(part, '    if (vr->is_hmd_active()) {\n        clear_backbuffer();\n    }',
        '''    if (!block_clear && vr->is_hmd_active()) {
        uevr::duoview::stability::Duration clear_scope{diagnostic.max_clear_us};
        clear_backbuffer();
    }''', dx)
    trailer = '    }\n}'
    if not part.endswith(trailer):
        raise RuntimeError('Unexpected post-present function ending')
    report = '''    // Ten-second snapshots: relaxed atomics only in the per-frame path.
    // Diagnostic output itself never waits for or synchronizes the GPU.
    static std::atomic<std::int64_t> last_report_us{0};
    const auto now_us = uevr::duoview::stability::microseconds();
    auto previous = last_report_us.load(std::memory_order_relaxed);
    if (now_us - previous >= 10000000 &&
        last_report_us.compare_exchange_strong(previous, now_us, std::memory_order_relaxed)) {
        spdlog::info("[DuoView stability v09] mode={} requested={} generation={} pending={} "
            "presents={} gaps17={} gaps33={} max_gap_us={} frames={} rejected={} "
            "post={} blocked_clears={} commits={} max_frame_us={} max_commit_us={} max_clear_us={} "
            "raw_view_bits=0x{:x} families_1={} families_2={} families_other={}",
            vr->is_using_duoview_mono() ? 6 : vr->is_using_mono() ? 5 : 0,
            vr->requested_rendering_method(), vr->mono_generation(), vr->is_mono_transition_pending(),
            diagnostic.present_entries.exchange(0), diagnostic.present_gaps_17ms.exchange(0),
            diagnostic.present_gaps_33ms.exchange(0), diagnostic.max_present_gap_us.exchange(0),
            diagnostic.frame_calls.exchange(0), diagnostic.rejected_mono_frames.exchange(0),
            diagnostic.post_presents.exchange(0), diagnostic.clears_blocked.exchange(0),
            diagnostic.graphics_commits.exchange(0), diagnostic.max_frame_us.exchange(0),
            diagnostic.max_commit_us.exchange(0), diagnostic.max_clear_us.exchange(0),
            diagnostic.raw_view_bits.exchange(0), diagnostic.main_families_1.exchange(0),
            diagnostic.main_families_2.exchange(0), diagnostic.main_families_other.exchange(0));
    }
'''
    part = part[:-len(trailer)] + '    }\n' + report + '}'
    s = s[:start] + part + s[end:]
    dx.write_text(s, encoding='utf-8')

    stereo = root / 'src/mods/vr/FFakeStereoRenderingHook.cpp'
    s = '#include "DuoViewStabilityDiagnostics.hpp"\n' + stereo.read_text(encoding='utf-8')
    s = change_once(s, '    static bool index_was_ever_negative = false;',
        '''    static bool index_was_ever_negative = false;
    if (vr->is_using_mono()) uevr::duoview::stability::raw_view(view_index);''', stereo)
    s = change_once(s,
        '        vr->get_openxr_runtime()->note_mono_main_family(frame_count, main_family && views_ptr != nullptr && views_ptr->count == desired);',
        '''        vr->get_openxr_runtime()->note_mono_main_family(frame_count, main_family && views_ptr != nullptr && views_ptr->count == desired);
        if (main_family) uevr::duoview::stability::main_family(views_ptr ? views_ptr->count : 0);''', stereo)
    stereo.write_text(s, encoding='utf-8')
    print('v09: native-exit frame gate, graphics memory retirement, bounded diagnostics applied')

if __name__ == '__main__':
    main()
