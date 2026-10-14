#!/usr/bin/env python3
"""Safe Mono bootstrap for DuoView Build33 recovery (no atlas or NGX changes).

Run after apply_stage1.py and apply_stage234.py on the exact pinned Joey source.
No SDK edits. All text anchors are single-occurrence, fail-closed.
"""
from pathlib import Path
import argparse

def replace_once(text, before, after, path):
    count=text.count(before)
    if count != 1:
        raise RuntimeError(f"{path}: expected exactly one anchor, found {count}: {before[:96]!r}")
    return text.replace(before,after,1)

def main():
    p=argparse.ArgumentParser()
    p.add_argument("backend",type=Path)
    a=p.parse_args()
    root=a.backend
    changes={}
    def edit(rel,before,after):
        text=changes.get(rel)
        if text is None:
            text=(root/rel).read_text(encoding="utf-8-sig")
        changes[rel]=replace_once(text,before,after,rel)

    policy="src/mods/vr/MonoRenderingPolicy.hpp"
    edit(policy, '    void initialize(int32_t value) {',
        '''    // Dedicated DuoView recovery: start with ONE proven Joey Mono scene
    // rather than allocating native stereo or constructing DuoView views at injection.
    // The ordinary initialize()/request() policy remains unchanged.
    void initialize_duoview_safe_bootstrap() {
        std::scoped_lock lock{m_mutex};
        if (m_initialized) { return; }
        m_initialized=true;
        m_requested=pack(method_id,1);
        m_active=pack(method_id,1);
        m_retired_request=0;
    }
    void initialize(int32_t value) {''')

    setting="src/mods/vr/RenderingMethodSetting.hpp"
    edit(setting, ': m_name{std::move(name)}, m_options{options} {}',
        ': m_name{std::move(name)}, m_options{options} { m_selection.initialize_duoview_safe_bootstrap(); }')
    edit(setting, 'void request(int32_t value) { m_selection.request(value); }',
        '''// No profile, frontend, or UI request may activate Native Stereo or ID6
    // before the three-second Mono5 bootstrap has reached a safe frame boundary.
    void request(int32_t value) {
        if (!m_bootstrap_released.load(std::memory_order_acquire)) return;
        m_selection.request(value);
    }
    void complete_duoview_bootstrap() {
        m_selection.request(uevr::mono::duoview_method_id);
        m_bootstrap_released.store(true,std::memory_order_release);
    }''')
    edit(setting, '    uevr::mono::Selection m_selection;',
        '''    uevr::mono::Selection m_selection;
    std::atomic<bool> m_bootstrap_released{false};''')
    edit(setting,
        '        m_selection.initialize(defaults ? 0 : cfg.get<int32_t>(m_name).value_or(requested_value()));',
        '''        // Dedicated recovery build always warms up Joey Mono (5), regardless
        // of stale saved Native Stereo (0) or DuoView (6) startup profiles.
        // VR::service_duoview_bootstrap() requests 6 only after readiness + 3s.
        (void)cfg; (void)defaults;
        m_selection.initialize_duoview_safe_bootstrap();''')
    edit(setting,
        'void config_save(utility::Config& cfg) override { cfg.set<int32_t>(m_name, requested_value()); }',
        '''void config_save(utility::Config& cfg) override {
        // Retain ID6 as the intended mode even when a profile is saved during warmup.
        cfg.set<int32_t>(m_name, uevr::mono::duoview_method_id);
    }''')

    header="src/mods/VR.hpp"
    edit(header,'    void configure_duoview();',
        '    void configure_duoview();\n    void service_duoview_bootstrap();')
    edit(header,'    std::atomic<const char*> m_mono_status{"Not selected"};',
        '''    // Game-thread-only boot sequence. Never change the OpenXR resolution at runtime.
    std::chrono::steady_clock::time_point m_duoview_bootstrap_since{};
    bool m_duoview_bootstrap_completed{};
    std::atomic<const char*> m_mono_status{"Not selected"};''')
    cpp="src/mods/VR.cpp"
    edit(cpp,
        '''void VR::on_pre_engine_tick(sdk::UGameEngine* engine, float delta) {
    service_mono_transition_game_thread();''',
        '''void VR::on_pre_engine_tick(sdk::UGameEngine* engine, float delta) {
    service_duoview_bootstrap();
    service_mono_transition_game_thread();''')
    edit(cpp,'void VR::configure_duoview() {',
        '''// A time delay is only a secondary safeguard: all readiness predicates must
// remain true continuously before requesting the ORIGINAL guarded 5 -> 6 switch.
// No runtime swapchain or SteamVR render-resolution changes are attempted.
void VR::service_duoview_bootstrap() {
    if (m_duoview_bootstrap_completed) return;
    const auto runtime=get_runtime();
    const bool ready = runtime != nullptr && runtime->is_openxr() && runtime->ready()
        && is_hmd_active() && m_is_d3d12 && m_render_frame_count >= 8
        && m_rendering_method->value() == RenderingMethod::MONO
        && requested_rendering_method() == RenderingMethod::MONO
        && !is_mono_transition_pending()
        && mono_unavailable_reason() == nullptr;
    if (!ready) {
        m_duoview_bootstrap_since={};
        return;
    }
    const auto now=std::chrono::steady_clock::now();
    if (m_duoview_bootstrap_since.time_since_epoch().count()==0) {
        m_duoview_bootstrap_since=now;
        SPDLOG_INFO("[DuoView][Bootstrap] Safe Joey Mono ready, beginning three-second warmup");
        return;
    }
    if (now-m_duoview_bootstrap_since < std::chrono::seconds(3)) return;
    // request(6) is deferred while active 5 and only commits after consumer
    // retirement at the existing game frame boundary.
    m_duoview_bootstrap_completed=true;
    m_rendering_method->complete_duoview_bootstrap();
    SPDLOG_INFO("[DuoView][Bootstrap] Requesting guarded Mono 5 -> DuoView 6 transition");
}

void VR::configure_duoview() {''')

    hook="src/mods/vr/FFakeStereoRenderingHook.cpp"
    edit(hook,
        'if (!vr->is_ghosting_fix_enabled() && !vr->is_splitscreen_compatibility_enabled() && !vr->is_sceneview_compatibility_enabled() && !vr->is_native_stereo_fix_enabled()) {',
        'if (!vr->is_using_duoview_mono() && !vr->is_ghosting_fix_enabled() && !vr->is_splitscreen_compatibility_enabled() && !vr->is_sceneview_compatibility_enabled() && !vr->is_native_stereo_fix_enabled()) {')

    for rel,content in changes.items():
        (root/rel).write_text(content,encoding="utf-8",newline="")
    print("Recovery patch: Mono5 first, 3s guarded transition to ID6; old full atlas kept; no NGX hooks.")

if __name__=="__main__":
    main()
