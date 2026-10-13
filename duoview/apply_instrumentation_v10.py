#!/usr/bin/env python3
"""Apply *diagnostic-only* v10 DXGI/OpenXR/framework timing probes after v09.

All probes use relaxed atomics/steady_clock and preserve original return values,
wait semantics, hook order, and resource lifetimes. No hot-path file logging.
"""
from pathlib import Path
import argparse

def once(text, old, new, path):
    n = text.count(old)
    if n != 1:
        raise RuntimeError(f'{path}: expected one anchor; found {n}: {old[:110]!r}')
    return text.replace(old, new, 1)

def main():
    p = argparse.ArgumentParser()
    p.add_argument('root', type=Path)
    root = p.parse_args().root.resolve()
    diag = 'uevr::duoview::stability::counters()'

    # Time the callback + DXGI driver/native Present independently. This is
    # intentionally upstream of VR::on_present() so Native is measured, too.
    path = root/'src/hooks/D3D12Hook.cpp'
    text = path.read_text(encoding='utf-8')
    text = '#include "../mods/vr/DuoViewStabilityDiagnostics.hpp"\n' + text
    text = once(text,
        'HRESULT D3D12Hook::present_internal(IDXGISwapChain3* swap_chain, UINT sync_interval, UINT flags, DXGI_PRESENT_PARAMETERS* params, bool present1) {\n    auto d3d12 = g_d3d12_hook;',
        '''HRESULT D3D12Hook::present_internal(IDXGISwapChain3* swap_chain, UINT sync_interval, UINT flags, DXGI_PRESENT_PARAMETERS* params, bool present1) {
    const UINT v10_original_sync = sync_interval;
    const UINT v10_original_flags = flags;
    auto d3d12 = g_d3d12_hook;''', path)
    text = once(text,
        '''    if (d3d12->m_on_present) {
        d3d12->m_on_present(*d3d12);''',
        '''    if (d3d12->m_on_present) {
        uevr::duoview::stability::Duration v10_hook_scope{'%s'.max_hook_callback_us};
        d3d12->m_on_present(*d3d12);''' % diag, path)
    text = once(text,
        '''    if (!d3d12->m_ignore_next_present) {
        result = present_fn(swap_chain, sync_interval, flags, params);

        if (result != S_OK) {
            spdlog::error("Present failed: {:x}", result);
        }
    } else {''',
        '''    if (!d3d12->m_ignore_next_present) {
        auto& v10 = %s;
        v10.dxgi_present_calls.fetch_add(1, std::memory_order_relaxed);
        const auto v10_start = uevr::duoview::stability::microseconds();
        result = present_fn(swap_chain, sync_interval, flags, params);
        uevr::duoview::stability::maximum(v10.max_dxgi_present_us,
            uevr::duoview::stability::microseconds() - v10_start);

        if (result != S_OK) {
            v10.dxgi_present_failures.fetch_add(1, std::memory_order_relaxed);
            const HRESULT removed = d3d12->m_device == nullptr ? S_OK : d3d12->m_device->GetDeviceRemovedReason();
            spdlog::error("[DuoView v10] DXGI Present HRESULT=0x{:08x} removed=0x{:08x} "
                "original_sync={} original_flags=0x{:x} effective_sync={} effective_flags=0x{:x} "
                "swapchain={:p} queue={:p} framegen={} present1={}",
                static_cast<uint32_t>(result), static_cast<uint32_t>(removed),
                v10_original_sync, v10_original_flags, sync_interval, flags,
                static_cast<void*>(swap_chain), static_cast<void*>(d3d12->m_command_queue),
                d3d12->m_using_frame_generation_swapchain, present1);
        }
    } else {''' % diag, path)
    text = once(text,
        '''    if (d3d12->m_on_post_present) {
        d3d12->m_on_post_present(*d3d12);
    }''',
        '''    if (d3d12->m_on_post_present) {
        uevr::duoview::stability::Duration v10_post_scope{%s.max_post_callback_us};
        d3d12->m_on_post_present(*d3d12);
    }''' % diag, path)
    for which in ['present', 'present1']:
        signature = ('HRESULT WINAPI D3D12Hook::present(IDXGISwapChain3* swap_chain, UINT sync_interval, UINT flags) {'
                     if which == 'present' else
                     'HRESULT WINAPI D3D12Hook::present1(IDXGISwapChain3* swap_chain, UINT sync_interval, UINT flags, DXGI_PRESENT_PARAMETERS* params) {')
        text = once(text, signature + '''
    std::scoped_lock _{g_framework->get_hook_monitor_mutex()};''',
            signature + '''
    const auto v10_lock_start = uevr::duoview::stability::microseconds();
    std::scoped_lock _{g_framework->get_hook_monitor_mutex()};
    uevr::duoview::stability::maximum(%s.max_hook_lock_us,
        uevr::duoview::stability::microseconds() - v10_lock_start);''' % diag, path)
    path.write_text(text, encoding='utf-8')

    # Framework's shared overlay command-list fence can block the Present
    # callback even when DuoView is inactive.
    path = root/'src/Framework.cpp'
    text = '#include "mods/vr/DuoViewStabilityDiagnostics.hpp"\n' + path.read_text(encoding='utf-8')
    text = once(text, '''    cmd_ctx->wait(INFINITE);
    if (auto draw_data = ImGui::GetDrawData(); draw_data != nullptr) {''',
        '''    {
        const auto v10_wait_start = uevr::duoview::stability::microseconds();
        cmd_ctx->wait(INFINITE);
        const auto v10_wait_us = uevr::duoview::stability::microseconds() - v10_wait_start;
        auto& v10 = %s;
        uevr::duoview::stability::maximum(v10.max_framework_fence_us, v10_wait_us);
        if (v10_wait_us > 8000) v10.framework_fence_waits_over_8ms.fetch_add(1, std::memory_order_relaxed);
    }
    if (auto draw_data = ImGui::GetDrawData(); draw_data != nullptr) {''' % diag, path)
    path.write_text(text, encoding='utf-8')

    # OpenXR pacing: measure real runtime API boundaries (NOT the surrounding
    # synchronization mutex, which is reflected in the parent hook duration).
    path = root/'src/mods/vr/runtimes/OpenXR.cpp'
    text = '#include "../DuoViewStabilityDiagnostics.hpp"\n' + path.read_text(encoding='utf-8')
    for api, target, field, count, failure, extra in [
        ('xrWaitFrame', 'max_xr_wait_us', 'max_successful_xr_wait_us', 'xr_wait_calls', 'xr_wait_failures', True),
        ('xrBeginFrame', 'max_xr_begin_us', '', 'xr_begin_calls', 'xr_begin_failures', False),
        ('xrEndFrame', 'max_xr_end_us', '', 'xr_end_calls', 'xr_end_failures', False),
    ]:
        if api == 'xrWaitFrame':
            old='    auto result = xrWaitFrame(this->session, &frame_wait_info, &local_frame_state);'
        elif api == 'xrBeginFrame':
            old='    auto result = xrBeginFrame(this->session, &frame_begin_info);'
        else:
            old='    auto result = xrEndFrame(this->session, &frame_end_info);'
        new = '''    auto& v10_%s = %s;
    v10_%s.%s.fetch_add(1, std::memory_order_relaxed);
    const auto v10_%s_start = uevr::duoview::stability::microseconds();
%s
    const auto v10_%s_elapsed = uevr::duoview::stability::microseconds() - v10_%s_start;
    uevr::duoview::stability::maximum(v10_%s.%s, v10_%s_elapsed);
    if (result != XR_SUCCESS) v10_%s.%s.fetch_add(1, std::memory_order_relaxed);%s''' % (
        api,diag,api,count,api,old,api,api,api,target,api,api,failure,
        ('\n    else uevr::duoview::stability::maximum(v10_%s.%s, v10_%s_elapsed);' % (api,field,api)) if extra else '')
        text = once(text, old, new, path)
    path.write_text(text, encoding='utf-8')

    # One bounded summary every 10 sec, matching v09; no additional logging
    # in the hot path. v09 output intentionally remains for A/B comparisons.
    path = root/'src/mods/vr/D3D12Component.cpp'
    text = path.read_text(encoding='utf-8')
    anchor = '''            diagnostic.main_families_2.exchange(0), diagnostic.main_families_other.exchange(0));'''
    # Handle original v09 argument layout strictly.
    anchor = '''            diagnostic.main_families_2.exchange(0), diagnostic.main_families_other.exchange(0));'''
    new = anchor + '''
        spdlog::info("[DuoView shared frame v10] lock_us={} hook_us={} dxgi_us={} dxgi_calls={} dxgi_fail={} "
            "post_us={} fence_us={} fence_gt8={} "
            "xr_wait_us={} xr_wait_success_us={} xr_wait_calls={} xr_wait_fail={} "
            "xr_begin_us={} xr_begin_calls={} xr_begin_fail={} "
            "xr_end_us={} xr_end_calls={} xr_end_fail={}",
            diagnostic.max_hook_lock_us.exchange(0), diagnostic.max_hook_callback_us.exchange(0),
            diagnostic.max_dxgi_present_us.exchange(0), diagnostic.dxgi_present_calls.exchange(0),
            diagnostic.dxgi_present_failures.exchange(0), diagnostic.max_post_callback_us.exchange(0),
            diagnostic.max_framework_fence_us.exchange(0), diagnostic.framework_fence_waits_over_8ms.exchange(0),
            diagnostic.max_xr_wait_us.exchange(0), diagnostic.max_successful_xr_wait_us.exchange(0),
            diagnostic.xr_wait_calls.exchange(0), diagnostic.xr_wait_failures.exchange(0),
            diagnostic.max_xr_begin_us.exchange(0), diagnostic.xr_begin_calls.exchange(0),
            diagnostic.xr_begin_failures.exchange(0), diagnostic.max_xr_end_us.exchange(0),
            diagnostic.xr_end_calls.exchange(0), diagnostic.xr_end_failures.exchange(0));'''
    text = once(text, anchor, new, path)
    path.write_text(text, encoding='utf-8')
    print('v10: shared DXGI/Framework/OpenXR tracing added; renderer and wait policy unchanged')

if __name__ == '__main__':
    main()
