#!/usr/bin/env python3
"""Build33 recovery: low-resolution native stereo warmup -> guarded DuoView -> restore.

Apply after the exact pinned Stage1 and Stage2-4 patches. Do NOT combine with
v25-v27 compact atlas, direct NGX interception or forced ID6-at-injection.
All replace anchors must match once; no private SDK modifications.
"""
from pathlib import Path
import argparse

BOOT_SCALE = "0.30f"

def replace_once(text, old, new, name):
    found=text.count(old)
    if found != 1:
        raise RuntimeError(f"{name}: expected one anchor, got {found}: {old[:110]!r}")
    return text.replace(old, new, 1)

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("backend",type=Path)
    args=ap.parse_args()
    root=args.backend
    changed={}
    def edit(path,old,new):
        content=changed.get(path)
        if content is None:
            content=(root/path).read_text(encoding="utf-8-sig")
        changed[path]=replace_once(content,old,new,path)

    setting="src/mods/vr/RenderingMethodSetting.hpp"
    edit(setting, 'm_selection.initialize(defaults ? 0 : cfg.get<int32_t>(m_name).value_or(requested_value()));',
         '''// Preserve active ID6 through profile reloads, but on first load always
        // initialize real Native0 rather than allowing saved ID6 at injection.
        if (!m_bootstrap_released.load(std::memory_order_acquire)) m_selection.initialize(0);''')
    # Suppress premature profile/front-end requests until the prepared native
    # initialization has completed, without bypassing Joey's retirement gate.
    edit(setting,'void request(int32_t value) { m_selection.request(value); }',
         '''void request(int32_t value) {
        if (!m_bootstrap_released.load(std::memory_order_acquire)) return;
        m_selection.request(value);
    }
    void complete_duoview_bootstrap() {
        m_selection.request(uevr::mono::duoview_method_id);
        m_bootstrap_released.store(true,std::memory_order_release);
    }''')
    edit(setting,'    uevr::mono::Selection m_selection;',
         '''    uevr::mono::Selection m_selection;
    std::atomic<bool> m_bootstrap_released{false};''')
    edit(setting,'void config_save(utility::Config& cfg) override { cfg.set<int32_t>(m_name, requested_value()); }',
         '''void config_save(utility::Config& cfg) override {
        cfg.set<int32_t>(m_name, m_bootstrap_released.load(std::memory_order_acquire)
            ? requested_value() : uevr::mono::duoview_method_id);
    }''')

    header="src/mods/VR.hpp"
    edit(header, '    void configure_duoview();',
         '''    void configure_duoview();
    void service_duoview_bootstrap();
    void note_duoview_bootstrap_composite() {
        m_duoview_bootstrap_composed_frames.fetch_add(1, std::memory_order_release);
    }''')
    edit(header,'    std::atomic<const char*> m_mono_status{"Not selected"};',
         '''    std::chrono::steady_clock::time_point m_duoview_native_ready_since{};
    std::chrono::steady_clock::time_point m_duoview_composite_ready_since{};
    float m_duoview_saved_resolution_scale{1.0f};
    bool m_duoview_saved_resolution_captured{};
    bool m_duoview_low_resolution_applied{};
    bool m_duoview_mode_requested{};
    bool m_duoview_restore_attempted{};
    std::atomic<uint32_t> m_duoview_bootstrap_composed_frames{0};
    std::atomic<const char*> m_mono_status{"Not selected"};''')
    cpp="src/mods/VR.cpp"
    edit(cpp,'''void VR::on_pre_engine_tick(sdk::UGameEngine* engine, float delta) {
    service_mono_transition_game_thread();''',
         '''void VR::on_pre_engine_tick(sdk::UGameEngine* engine, float delta) {
    service_duoview_bootstrap();
    service_mono_transition_game_thread();''')
    edit(cpp,'    m_openxr = std::make_shared<runtimes::OpenXR>();\n\n    spdlog::info("[VR] Initializing OpenXR");',
         '''    m_openxr = std::make_shared<runtimes::OpenXR>();
    if (!m_duoview_restore_attempted) {
        m_openxr->resolution_scale->value() = ''' + BOOT_SCALE + ''';
    }

    spdlog::info("[VR] Initializing OpenXR");''')
    edit(cpp,
         '        get_runtime()->on_config_load(cfg, set_defaults);\n\n        // Run the rest of OpenXR initialization code here that depends on config values',
         '''        get_runtime()->on_config_load(cfg, set_defaults);
        // Set the boot scale AFTER persisted options load, but BEFORE initial
        // swapchains are created by initialize_openxr_swapchains below.
        if (!m_duoview_restore_attempted && get_runtime()->is_openxr() && m_openxr) {
            if (!m_duoview_saved_resolution_captured) {
                m_duoview_saved_resolution_scale=m_openxr->resolution_scale->value();
                m_duoview_saved_resolution_captured=true;
            }
            m_openxr->resolution_scale->value() = ''' + BOOT_SCALE + ''';
            m_duoview_low_resolution_applied=true;
            SPDLOG_INFO_ONCE("[DuoView][Bootstrap] Native 0 boot scale 0.30, restore target {:.3f}",
                            m_duoview_saved_resolution_scale);
        }

        // Run the rest of OpenXR initialization code here that depends on config values''')
    edit(cpp,'void VR::configure_duoview() {',
         '''void VR::service_duoview_bootstrap() {
    auto runtime=get_runtime();
    if (runtime == nullptr || !runtime->is_openxr() || !runtime->ready() ||
        !is_hmd_active() || !m_is_d3d12) {
        m_duoview_native_ready_since={};
        m_duoview_composite_ready_since={};
        return;
    }
    const auto now=std::chrono::steady_clock::now();
    if (!m_duoview_mode_requested) {
        if (!m_duoview_low_resolution_applied || !m_duoview_saved_resolution_captured ||
            m_rendering_method->value()!=RenderingMethod::NATIVE_STEREO ||
            requested_rendering_method()!=RenderingMethod::NATIVE_STEREO ||
            is_mono_transition_pending() || m_render_frame_count < 8) {
            m_duoview_native_ready_since={};
            return;
        }
        if (m_duoview_native_ready_since.time_since_epoch().count()==0) {
            m_duoview_native_ready_since=now;
            SPDLOG_INFO("[DuoView][Bootstrap] Low-resolution Native Stereo ready; begin warmup");
            return;
        }
        if (now-m_duoview_native_ready_since < std::chrono::seconds(3)) return;
        m_duoview_mode_requested=true;
        m_rendering_method->complete_duoview_bootstrap();
        SPDLOG_INFO("[DuoView][Bootstrap] Request guarded Native0 -> DuoView6 transition");
        return;
    }
    if (m_duoview_restore_attempted) return;
    if (m_rendering_method->value()!=RenderingMethod::DUOVIEW_MONO ||
        is_mono_transition_pending() || !is_duoview_renderer_active() ||
        m_duoview_bootstrap_composed_frames.load(std::memory_order_acquire) < 3) {
        m_duoview_composite_ready_since={};
        return;
    }
    if (m_duoview_composite_ready_since.time_since_epoch().count()==0) {
        m_duoview_composite_ready_since=now;
        return;
    }
    if (now-m_duoview_composite_ready_since < std::chrono::seconds(2)) return;
    // This uses EXACTLY Joey's live resolution-change callback, which waits
    // for copies before subsequent D3D12 setup. Never attempt a second resize
    // if the engine's safety policy rejects it.
    m_duoview_restore_attempted=true;
    if (!m_openxr->restore_duoview_bootstrap_scale(m_duoview_saved_resolution_scale)) {
        SPDLOG_ERROR("[DuoView][Bootstrap] OpenXR scale restore rejected; remaining at safe boot scale");
        return;
    }
    m_duoview.retire();
    SPDLOG_INFO("[DuoView][Bootstrap] Restored OpenXR scale {:.3f}; deferred texture recreation requested",
                m_duoview_saved_resolution_scale);
}

void VR::configure_duoview() {''')

    # The Build33 UE scene-view constructor hook was only armed for Native Fix
    # or other compatibility toggles; entering ID6 after vanilla Native0
    # otherwise risks missing the required projection/view-state hook.
    # Activate this ONE existing hook for ID6 itself (no ID0-dependent state).
    hook="src/mods/vr/FFakeStereoRenderingHook.cpp"
    edit(hook,
         'if (!vr->is_ghosting_fix_enabled() && !vr->is_splitscreen_compatibility_enabled() && !vr->is_sceneview_compatibility_enabled() && !vr->is_native_stereo_fix_enabled()) {',
         'if (!vr->is_using_duoview_mono() && !vr->is_ghosting_fix_enabled() && !vr->is_splitscreen_compatibility_enabled() && !vr->is_sceneview_compatibility_enabled() && !vr->is_native_stereo_fix_enabled()) {')

    dx="src/mods/vr/D3D12Component.cpp"
    edit(dx,
         '''                        vr->m_openxr->note_mono_copy(static_cast<uint32_t>(frame_count), submitted && recorded);
                        // Only a successfully accepted two-view XR copy may seed
                        // the NEXT compositor sample shift. Quarantine on failure.
                        if (frame && submitted && recorded && duo_recorded)
                            vr->duoview_state().accept_composite(frame->config.key);
                        if (duo_failed || !submitted || !recorded)''',
         '''                        vr->m_openxr->note_mono_copy(static_cast<uint32_t>(frame_count), submitted && recorded);
                        // Only a successfully accepted two-view XR copy may seed
                        // the NEXT compositor sample shift. Quarantine on failure.
                        if (frame && submitted && recorded && duo_recorded)
                            vr->duoview_state().accept_composite(frame->config.key);
                        if (submitted && recorded && duo_recorded) vr->note_duoview_bootstrap_composite();
                        if (duo_failed || !submitted || !recorded)''')

    xr_h="src/mods/vr/runtimes/OpenXR.hpp"
    edit(xr_h, "    void on_draw_ui() override;",
         '''    void on_draw_ui() override;
    bool restore_duoview_bootstrap_scale(float scale);''')
    xr_cpp="src/mods/vr/runtimes/OpenXR.cpp"
    edit(xr_cpp,"void OpenXR::on_draw_ui() {",
         '''// Reuse the same validated reconfigure path as the in-game scale control.
bool OpenXR::restore_duoview_bootstrap_scale(float target) {
    const auto vr=VR::get();
    if (!vr || !vr->is_duoview_renderer_active() ||
        vr->is_mono_transition_pending() || !std::isfinite(target) ||
        target < 0.1f || target > 3.0f) return false;
    const float prior=resolution_scale->value();
    if (std::abs(prior-target)<0.0001f) return true;
    const uint32_t old_width=get_width_for_scale(prior);
    const uint32_t old_height=get_height_for_scale(prior);
    const uint32_t new_width=get_width_for_scale(target);
    const uint32_t new_height=get_height_for_scale(target);
    if (!old_width || !old_height || !new_width || !new_height) return false;
    // The original UI changes the slider value BEFORE running the callback.
    resolution_scale->value()=target;
    if (!vr->on_openxr_resolution_scale_changed(old_width,old_height,new_width,new_height)) {
        resolution_scale->value()=prior;
        resolution_scale_live_apply_deferred=false;
        return false;
    }
    resolution_scale_live_apply_deferred=false;
    resolution_scale_reconfigure_pending=false;
    last_applied_resolution_scale=target;
    last_applied_resolution_width=new_width;
    last_applied_resolution_height=new_height;
    return true;
}

void OpenXR::on_draw_ui() {''')

    for path,text in changed.items():
        (root/path).write_text(text,encoding="utf-8",newline="")
    print("Build37 native0 lowres boot -> safe ID6 -> confirmed composition -> UEVR renderer-scale restore.")
if __name__=="__main__":
    main()
