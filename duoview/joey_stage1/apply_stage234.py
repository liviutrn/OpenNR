#!/usr/bin/env python3
"""Apply isolated fixed-center two-view integration after verified Stage 1.
Joey original Mono ID5 and Native Stereo ID0 remain unmodified source modes.
STALKER2 DX12 supports OpenXR and native OpenVR with DuoView ID6; eye gaze OFF.
Reject incomplete/untreated pairs; after 60 initial or 4 subsequent failed
game ticks, safely request real Joey Mono ID5 (never automatic ID0).
All original-source anchors must match exactly or the build fails.
"""
from pathlib import Path
import argparse
import shutil
import subprocess
import sys

def replace(text,old,new,name):
    count=text.count(old)
    if count != 1:
        raise RuntimeError(f"{name} expected one anchor, found {count}: {old[:95]!r}")
    return text.replace(old,new,1)

def main():
    p=argparse.ArgumentParser()
    p.add_argument("backend",type=Path)
    p.add_argument("frontend",type=Path)
    p.add_argument("source",type=Path)
    p.add_argument("--source-only", action="store_true",
                   help="Apply source for review without compiling or generating the shader header")
    a=p.parse_args()
    root=a.backend
    src=a.source
    changed={}
    def source_root(path):
        return a.frontend if path.startswith("UEVR/") or path.startswith("tests/RenderingModes/") else root
    def edit(path,before,after):
        s=changed.get(path)
        if s is None: s=(source_root(path)/path).read_text(encoding="utf-8-sig")
        changed[path]=replace(s,before,after,path)
    edit("src/mods/vr/MonoRenderingPolicy.hpp",
        'DuoView Mono (Stage 1 - safe Mono fallback)',
        'DuoView Mono (Fixed Center - Experimental)')
    edit("UEVR/RenderingModeOptions.cs",
        'DuoView Mono (Stage 1 - safe Mono fallback)',
        'DuoView Mono (Fixed Center - Experimental)')
    edit("tests/RenderingModes/Program.cs",
        'DuoView Mono (Stage 1 - safe Mono fallback)',
        'DuoView Mono (Fixed Center - Experimental)')
    framework_header="src/Framework.hpp"
    edit(framework_header,'    bool is_ready() const { return m_initialized && m_game_data_initialized; }',
        '    bool is_ready() const { return m_initialized && m_game_data_initialized; }\n    bool is_mods_fully_initialized() const { return m_mods_fully_initialized.load(std::memory_order_acquire); }')
    framework_cpp="src/Framework.cpp"
    edit(framework_cpp,'        m_mods_fully_initialized = true;\n    }\n\n    return true;\n}',
        '        if (m_vr) m_vr->on_duoview_startup_config_finalized();\n        m_mods_fully_initialized = true;\n    }\n\n    return true;\n}')
    header="src/mods/VR.hpp"
    edit(header,'#include "vr/RenderingMethodSetting.hpp"',
        '#include "vr/RenderingMethodSetting.hpp"\n#include "vr/DuoViewState.hpp"\n#include "vr/DuoViewBootstrap.hpp"\n#include "vr/DuoViewPSVR2Gaze.hpp"')
    edit(header,'    bool is_using_duoview_mono() const { return m_rendering_method->value() == RenderingMethod::DUOVIEW_MONO; }',
        '''    bool is_using_duoview_mono() const { return m_rendering_method->value() == RenderingMethod::DUOVIEW_MONO; }
    bool defer_duoview_bootstrap_draw();
    void request_duoview_autostart_if_ready();
    void on_duoview_startup_config_finalized();
    bool is_duoview_renderer_active() const;
    uevr::duoview::State& duoview_state() { return m_duoview; }
    uevr::duoview::FrameKey duoview_key(uint32_t frame) const {
        return {mono_generation(), static_cast<uint64_t>(frame) + 1u};
    }
    uevr::duoview::FrameKey duoview_producer_key() const {
        return m_duoview_draw_frame ? duoview_key(*m_duoview_draw_frame) : uevr::duoview::FrameKey{};
    }
    std::optional<uint32_t> exchange_duoview_draw_frame(std::optional<uint32_t> frame) {
        const auto previous=m_duoview_draw_frame;
        m_duoview_draw_frame=frame;
        return previous;
    }
    bool duoview_gaze_active() const { return m_duoview_gaze.active(); }
    void configure_duoview();
    void note_duoview_gpu_ms(float ms) { m_duo_gpu_ms.store(ms, std::memory_order_relaxed); }
    std::optional<uevr::duoview::ViewFrame> duoview_begin_frame();
    void duoview_abort(const char* reason);
    void duoview_frame_success();
    void reset_duoview_faults();''')
    edit(header,'    std::atomic<const char*> m_mono_status{"Not selected"};',
        '''    // Legacy-style persistent options; never sampled by the XR compositor.
    const ModSlider::Ptr m_duo_width{ModSlider::create(generate_name("DuoViewCropWidth"), .10f, 1.f, .50f)};
    const ModSlider::Ptr m_duo_height{ModSlider::create(generate_name("DuoViewCropHeight"), .10f, 1.f, .50f)};
    const ModSlider::Ptr m_duo_periphery{ModSlider::create(generate_name("DuoViewPeripheralScale"), .05f, .50f, .20f)};
    const ModSlider::Ptr m_duo_density{ModSlider::create(generate_name("DuoViewFovealDensity"), .25f, 4.0f, 1.f)};
    const ModSlider::Ptr m_duo_feather{ModSlider::create(generate_name("DuoViewFeather"), 0.f, .45f, .08f)};
    const ModToggle::Ptr m_duo_gaze{ModToggle::create(generate_name("DuoViewEyeTracking"), false)};
    const ModSlider::Ptr m_duo_center_v{ModSlider::create(generate_name("DuoViewFixedCenterVertical"), 0.f, 1.f, .5f)};
    const ModToggle::Ptr m_duo_border{ModToggle::create(generate_name("DuoViewDebugBorder"), false)};
    const ModInt32::Ptr m_duo_debug_source{ModSliderInt32::create(generate_name("DuoViewDebugSource"), 0, 2, 0)};
    const ModInt32::Ptr m_duo_fovea_view{ModSliderInt32::create(generate_name("DuoViewFoveaSourceView"), 0, 1, 0)};
    const ModToggle::Ptr m_duo_stabilize{ModToggle::create(generate_name("DuoViewCropStability"), true)};
    const ModSlider::Ptr m_duo_guard{ModSlider::create(generate_name("DuoViewCropGuard"), 0.f, .25f, .08f)};
    const ModSlider::Ptr m_duo_smoothing{ModSlider::create(generate_name("DuoViewCropSmoothingMs"), 0.f, 250.f, 85.f)};
    const ModToggle::Ptr m_duo_shading{ModToggle::create(generate_name("DuoViewIndependentShading"), false)};
    const ModToggle::Ptr m_duo_timing{ModToggle::create(generate_name("DuoViewGpuTiming"), false)};
    std::atomic<float> m_duo_gpu_ms{-1.f};
    uevr::duoview::State m_duoview;
    inline static thread_local std::optional<uint32_t> m_duoview_draw_frame;
    uevr::duoview::psvr2::Reader m_duoview_gaze;
    std::atomic<bool> m_duoview_autostart_done{false};
    std::atomic<bool> m_duoview_launch_intent{false};
    std::atomic<bool> m_duoview_bootstrap_draw_gate{false};
    std::atomic<uint64_t> m_duoview_autostart_config_token{0};
    // Render-thread callbacks report failures; only the game thread changes
    // rendering modes at the normal Mono-family transaction boundary.
    std::atomic<uint32_t> m_duoview_consecutive_failures{0};
    // Count at most one render fault per game tick, even when multiple
    // setup/submit callbacks report the same missing pair.
    std::atomic<uint64_t> m_duoview_game_tick_serial{0};
    std::atomic<uint64_t> m_duoview_last_failure_tick{uevr::duoview::duoview_unseen_tick};
    std::atomic<uint64_t> m_duoview_last_success_tick{uevr::duoview::duoview_unseen_tick};
    std::atomic<bool> m_duoview_ever_presented{false};
    std::atomic<bool> m_duoview_fallback_requested{false};
    std::mutex m_duoview_fault_mutex;
    std::once_flag m_duoview_settings_once;
    std::atomic<const char*> m_mono_status{"Not selected"};''')
    edit(header,'    void on_device_reset() override {\n        get_runtime()->on_device_reset();',
        '    void on_device_reset() override {\n        m_duoview.retire();\n        reset_duoview_faults();\n        get_runtime()->on_device_reset();')
    edit(header,'        m_options = {',
        '''        m_options = {
            *m_duo_width, *m_duo_height, *m_duo_periphery, *m_duo_density,
            *m_duo_feather, *m_duo_center_v, *m_duo_border, *m_duo_debug_source,
            *m_duo_fovea_view, *m_duo_timing, *m_duo_stabilize, *m_duo_guard,
            *m_duo_smoothing,''')
    cpp="src/mods/VR.cpp"
    edit(cpp,
        'ImGui::TextWrapped("DuoView Stage 1: rendering uses original Joey Mono unchanged. Two-view foveation and gaze are NOT active.");',
        'ImGui::TextWrapped(is_duoview_renderer_active() ? "DuoView ID6: fixed-center two-view Mono" : "DuoView ID6: two-view renderer inactive (inspect diagnostics)");')
    edit(cpp, '#include "VR.hpp"', '#include "VR.hpp"\n#include <cstring>')
    # OpenVR only caches HMD projection matrices. A Mono -> DuoView or DuoView
    # -> Native mode transition must invalidate the per-eye cache, otherwise
    # it keeps the wrong source projection until an unrelated near-Z change.
    edit(cpp,'    m_openxr->reset_mono_projection_history();',
    '''    m_openxr->reset_mono_projection_history();
    if (auto rt=get_runtime(); rt && rt->is_openvr()) {
        std::unique_lock lock{rt->eyes_mtx};
        rt->should_recalculate_eye_projections=true;
        rt->should_update_eye_matrices=true;
    }''')
    # Keep original Joey Mono OpenXR-only for every OTHER game.
    # Only verified STALKER2 DX12 may use Mono ID5 / DuoView ID6 on SteamVR
    # OpenVR. Otherwise a global runtime capability change would silently
    # expose an unvalidated Mono submission path for other titles.
    edit(cpp,
        '    return uevr::mono::unavailable_reason({',
        '''    static const bool duoview_stalker2_title=[] {
        const auto p=utility::get_module_pathw(utility::get_executable());
        return p && uevr::stalker2_native::is_executable(*p);
    }();
    return uevr::mono::unavailable_reason({''')
    edit(cpp,
        '        .openxr = runtime != nullptr && runtime->is_openxr(),',
        '        .openxr = runtime != nullptr && (runtime->is_openxr() || (runtime->is_openvr() &&\n            g_framework != nullptr && g_framework->is_dx12() && duoview_stalker2_title)),')
    edit(cpp,'        if (rendering_method_changed && !is_mono_transition_pending() && get_runtime() != nullptr) {',
    '''        if (is_using_duoview_mono() || requested_rendering_method() == RenderingMethod::DUOVIEW_MONO) {
            if (ImGui::TreeNode("DuoView Mono — quality and diagnostics")) {
                ImGui::TextWrapped("Settings are frozen once per new UE frame. The original Joey Mono ID5 is untouched.");
                if (ImGui::Button("Restore old DuoView settings")) {
                    m_duo_width->value()=.50f; m_duo_height->value()=.50f;
                    m_duo_periphery->value()=.20f; m_duo_density->value()=1.f;
                    m_duo_feather->value()=.08f; m_duo_center_v->value()=.5f; m_duo_gaze->value()=false;
                    m_duo_border->value()=false; m_duo_fovea_view->value()=0;
                    m_duo_debug_source->value()=0;
                }
                m_duo_width->draw("Fovea width / full FOV");
                m_duo_height->draw("Fovea height / full FOV");
                m_duo_periphery->draw("Peripheral resolution scale");
                m_duo_density->draw("Foveal pixel density");
                m_duo_feather->draw("Blend feather width");
                m_duo_center_v->draw("Fixed fovea vertical position (0=top, 1=bottom)");
                m_duo_border->draw("Blend border highlight");
                m_duo_debug_source->draw("Source diagnostic: 0 Blend / 1 Periphery / 2 Fovea");
                m_duo_fovea_view->draw("Fovea UE source view (0 or 1)");
                m_duo_timing->draw("GPU timing: composite + both eye copies");
                if (m_duo_timing->value()) {
                    const float ms=m_duo_gpu_ms.load(std::memory_order_relaxed);
                    if (ms >= 0.f) ImGui::Text("Composite + eye copies: %.3f ms GPU (last retired slot)", ms);
                    else ImGui::TextUnformatted("GPU timing: waiting for a completed command slot");
                }
                configure_duoview();
                if (const auto snap=m_duoview.snapshot(duoview_key(get_runtime()->internal_frame_count))) {
                    const auto& layout=snap->config.layout;
                    ImGui::Text("Fovea %ux%u; peripheral %ux%u; output %ux%u",
                        layout.fovea.width,layout.fovea.height,
                        layout.periphery.width,layout.periphery.height,
                        layout.atlas_width/2,layout.atlas_height);
                    ImGui::Text("Fovea UE%u; periphery UE%u; fixed center vertical %.3f",
                        snap->config.settings.fovea_view,1u-snap->config.settings.fovea_view,
                        snap->config.settings.fixed_center_v);
                    ImGui::Text("View histories: %s; secondary source constructor: %s",
                        snap->scene_states[0] && snap->scene_states[1]
                            ? (snap->scene_states[0]!=snap->scene_states[1] ? "separate" : "shared") : "unobserved",
                        snap->shading_applied ? "validated" : "waiting for valid secondary source");
                    ImGui::Text("Applied crop centre (%.3f, %.3f), scene pixels: %.2f million",
                        snap->config.gaze.u,snap->config.gaze.v,
                        uevr::duoview::rendered_pixels(layout)/1000000.);
                }
                const auto active=m_duoview.settings();
                if (active.crop_width!=m_duo_width->value() || active.crop_height!=m_duo_height->value() ||
                    active.foveal_density!=m_duo_density->value() || active.peripheral_scale!=m_duo_periphery->value())
                    ImGui::TextWrapped("Selected view sizes exceed existing atlas; previous valid settings remain in effect.");
                ImGui::TextWrapped("Diagnostic 1 isolates the full-FOV peripheral pass. Diagnostic 2 isolates the foveal pass (dark outside crop). Compare shadows/lighting in the same scene.");
                ImGui::TextWrapped("View 0 = FIRST Unreal pass (old prototype default), view 1 = SECOND pass (Build19 default). Identical frozen Mono camera. Switching may reset temporal history.");
                ImGui::TreePop();
            }
        }
        if (rendering_method_changed && !is_mono_transition_pending() && get_runtime() != nullptr) {''')
    edit(cpp,'    // Load camera offsets\n    load_cameras();',
        '    // Load camera offsets\n    load_cameras();\n    configure_duoview();')
    # Latch launch intent at the first tick, but only request after Framework
    # confirms startup config initialization and a ready D3D12 VR runtime.
    # The Draw hook services this request before creating another native scene.
    edit(cpp,
        'void VR::on_pre_engine_tick(sdk::UGameEngine* engine, float delta) {\n    service_mono_transition_game_thread();',
        '''void VR::on_pre_engine_tick(sdk::UGameEngine* engine, float delta) {
    m_duoview_game_tick_serial.fetch_add(1, std::memory_order_acq_rel);
    const auto duoview_path=utility::get_module_pathw(utility::get_executable());
    if (duoview_path && uevr::stalker2_native::is_executable(*duoview_path))
        m_duoview_launch_intent.store(true,std::memory_order_release);
    request_duoview_autostart_if_ready();
    {
        std::scoped_lock fault_lock{m_duoview_fault_mutex};
        if (m_duoview_fallback_requested.exchange(false,std::memory_order_acq_rel) &&
            is_using_duoview_mono() &&
            requested_rendering_method()==RenderingMethod::DUOVIEW_MONO &&
            uevr::duoview::should_fallback_to_mono(
                m_duoview_consecutive_failures.load(std::memory_order_acquire),
                m_duoview_ever_presented.load(std::memory_order_acquire))) {
            m_rendering_method->request(RenderingMethod::MONO);
            set_mono_status("DuoView failed: switching to Joey Mono ID5 (not Native Stereo)");
            SPDLOG_WARN("[DuoView] Consecutive paired-view errors; requested safe Joey Mono ID5");
        }
    }
    service_mono_transition_game_thread();''')
    edit(cpp,'    m_mono_main_view_token = 0;\n    m_mono_attachment_token = 0;',
        '    m_duoview.retire();\n    reset_duoview_faults();\n    m_duo_shading->value()=false;\n    configure_duoview();\n    m_mono_main_view_token = 0;\n    m_mono_attachment_token = 0;')
    changed[cpp]+='''
// Update the immutable state from persisted controls only on changes.
void VR::configure_duoview() {
    const float vertical=m_duo_center_v->value();
    m_duo_center_v->value()=std::isfinite(vertical) ? std::clamp(vertical,0.f,1.f) : .5f;
    const uevr::duoview::Settings candidate{
        .crop_width=m_duo_width->value(), .crop_height=m_duo_height->value(),
        .peripheral_scale=m_duo_periphery->value(), .foveal_density=m_duo_density->value(),
        .feather_fraction=m_duo_feather->value(), .debug_border=m_duo_border->value(),
        .eye_tracked=false, .fixed_center_v=m_duo_center_v->value(),
        .fovea_view=static_cast<uint32_t>(m_duo_fovea_view->value()),
        .diagnostic_view=static_cast<uint32_t>(m_duo_debug_source->value()),
        .gpu_timing=m_duo_timing->value(), .stabilize_crop=m_duo_stabilize->value(),
        .guard_fraction=m_duo_guard->value(), .smoothing_ms=m_duo_smoothing->value(),
        .independent_shading=false};
    const auto current=m_duoview.settings();
    if (current.crop_width==candidate.crop_width && current.crop_height==candidate.crop_height &&
        current.peripheral_scale==candidate.peripheral_scale && current.foveal_density==candidate.foveal_density &&
        current.feather_fraction==candidate.feather_fraction && current.debug_border==candidate.debug_border &&
        current.eye_tracked==candidate.eye_tracked && current.fixed_center_v==candidate.fixed_center_v &&
        current.fovea_view==candidate.fovea_view &&
        current.diagnostic_view==candidate.diagnostic_view && current.gpu_timing==candidate.gpu_timing &&
        current.stabilize_crop==candidate.stabilize_crop && current.guard_fraction==candidate.guard_fraction &&
        current.smoothing_ms==candidate.smoothing_ms &&
        current.independent_shading==candidate.independent_shading) return;
    if (!m_duoview.configure(candidate))
        SPDLOG_WARNING_EVERY_N_SEC(2, "[DuoView] Requested quality settings exceed atlas geometry; preserving previous valid settings");
}

void VR::on_duoview_startup_config_finalized() {
    if (!m_duoview_autostart_done.load(std::memory_order_acquire)) {
        m_duoview_autostart_config_token.store(
            m_rendering_method->selection().request_token(), std::memory_order_release);
    }
}

void VR::request_duoview_autostart_if_ready() {
    if (m_duoview_autostart_done.load(std::memory_order_acquire) ||
        !m_duoview_launch_intent.load(std::memory_order_acquire) || g_framework == nullptr) return;
    if (g_framework->is_dx11() && !g_framework->is_dx12()) {
        m_duoview_autostart_done.store(true, std::memory_order_release);
        return;
    }
    if (!g_framework->is_dx12() && !m_is_d3d12) return;
    if (!g_framework->is_mods_fully_initialized()) return;

    const auto baseline_token=m_duoview_autostart_config_token.load(std::memory_order_acquire);
    if (baseline_token==0) return;
    auto& selection=m_rendering_method->selection();
    if (selection.request_token()!=baseline_token) {
        // A config or manual choice made after startup config finalization wins.
        m_duoview_autostart_done.store(true, std::memory_order_release);
        return;
    }

    const auto runtime=get_runtime();
    if (runtime && !runtime->error.empty()) {
        m_duoview_autostart_done.store(true, std::memory_order_release);
        return;
    }
    if (g_framework->is_mods_fully_initialized() &&
        (!runtime || (runtime->loaded && !runtime->is_openxr() && !runtime->is_openvr()))) {
        m_duoview_autostart_done.store(true, std::memory_order_release);
        return;
    }
    if (!runtime || !runtime->loaded || (!runtime->is_openxr() && !runtime->is_openvr())) return;

    m_duoview_autostart_done.store(true, std::memory_order_release);
    m_duoview_bootstrap_draw_gate.store(true, std::memory_order_release);
    if (selection.requested()!=RenderingMethod::DUOVIEW_MONO) {
        // A saved fallback ID5 must not prevent ID6 auto-start on a new launch.
        m_rendering_method->request(RenderingMethod::DUOVIEW_MONO);
    }
    SPDLOG_INFO("[DuoView] Auto-requested mode 6 for STALKER 2 after startup config and VR readiness");
}

bool VR::defer_duoview_bootstrap_draw() {
    if (!m_duoview_launch_intent.load(std::memory_order_acquire)) {
        const auto path=utility::get_module_pathw(utility::get_executable());
        if (!path || !uevr::stalker2_native::is_executable(*path)) return false;
        m_duoview_launch_intent.store(true, std::memory_order_release);
    }
    if (m_duoview_autostart_done.load(std::memory_order_acquire) &&
        !m_duoview_bootstrap_draw_gate.load(std::memory_order_acquire)) return false;
    if (g_framework == nullptr) return false;

    const bool dx12=g_framework->is_dx12() || m_is_d3d12;
    const bool dx11=g_framework->is_dx11();
    const bool backend_known=dx12 || dx11;
    if (backend_known && !dx12) {
        m_duoview_bootstrap_draw_gate.store(false, std::memory_order_release);
        m_duoview_autostart_done.store(true, std::memory_order_release);
        return false;
    }

    request_duoview_autostart_if_ready();
    const auto runtime=get_runtime();
    if (runtime && !runtime->error.empty()) {
        m_duoview_bootstrap_draw_gate.store(false, std::memory_order_release);
        m_duoview_autostart_done.store(true, std::memory_order_release);
        return false;
    }
    if (g_framework->is_mods_fully_initialized() &&
        (!runtime || (runtime->loaded && !runtime->is_openxr() && !runtime->is_openvr()))) {
        m_duoview_bootstrap_draw_gate.store(false, std::memory_order_release);
        m_duoview_autostart_done.store(true, std::memory_order_release);
        return false;
    }
    const bool ready=g_framework->is_mods_fully_initialized() && runtime && runtime->loaded &&
        (runtime->is_openxr() || runtime->is_openvr());
    auto& selection=m_rendering_method->selection();
    const bool mono_pending=selection.pending() && uevr::mono::is_mono_family(selection.requested());
    const bool mono_supported=ready && mono_unavailable_reason()==nullptr;
    const auto decision=uevr::duoview::bootstrap_draw_decision(
        m_duoview_launch_intent.load(std::memory_order_acquire), backend_known, dx12,
        ready, mono_supported, mono_pending, selection.active()==0);
    if (!uevr::duoview::should_defer_bootstrap_draw(decision)) {
        m_duoview_bootstrap_draw_gate.store(false, std::memory_order_release);
        return false;
    }

    m_duoview_bootstrap_draw_gate.store(true, std::memory_order_release);
    if (decision==uevr::duoview::BootstrapDrawDecision::wait_for_manual_selection) {
        if (const auto reason=mono_unavailable_reason()) set_mono_status(reason);
        return true;
    }
    if (decision==uevr::duoview::BootstrapDrawDecision::wait_for_retirement &&
        !m_native_openxr_async_wait_inflight.load(std::memory_order_acquire)) {
        const auto token=selection.request_token();
        if (g_framework->is_dx12() && m_d3d12.mono_consumers_retired())
            selection.consumers_retired(token);
        service_mono_transition_game_thread();
    }
    if (selection.active()!=0) {
        m_duoview_bootstrap_draw_gate.store(false, std::memory_order_release);
        return false;
    }
    return true;
}

// Fixed-center mode 6 always uses its frozen optical projection and does not read eye gaze.
bool VR::is_duoview_renderer_active() const {
    if (!is_using_duoview_mono() || !m_is_d3d12) return false;
    const auto runtime = get_runtime();
    if (!runtime || (!runtime->is_openxr() && !runtime->is_openvr())) return false;
    static const bool stalker2 = [] {
        const auto path = utility::get_module_pathw(utility::get_executable());
        return path && uevr::stalker2_native::is_executable(*path);
    }();
    return stalker2;
}

std::optional<uevr::duoview::ViewFrame> VR::duoview_begin_frame() {
    if (!is_duoview_renderer_active() || !m_fake_stereo_hook ||
        !m_fake_stereo_hook->is_in_viewport_client_draw()) return {};
    std::call_once(m_duoview_settings_once, [this] { configure_duoview(); });
    const auto key = duoview_producer_key();
    if (auto found = m_duoview.snapshot(key)) return found;
    auto projection = get_projection_matrix(VRRuntime::Eye::LEFT);
    const float near_plane=sdk::globals::get_near_clipping_plane();
    if (!std::isfinite(near_plane) || near_plane<=0.f) return {};
    projection[3][2]=near_plane;
    std::array<float, 16> frozen{};
    std::memcpy(frozen.data(), &projection[0][0], sizeof(frozen));
    const auto eye=get_eye_transform(0);
    const std::array<float,9> optical{
        eye[0][0],eye[0][1],eye[0][2],
        eye[1][0],eye[1][1],eye[1][2],
        eye[2][0],eye[2][1],eye[2][2]};
    return m_duoview.begin(key, get_hmd_width(), get_hmd_height(), frozen,
        [this, frozen, optical]() -> std::optional<uevr::duoview::UV> {
            return m_duoview_gaze.read_uv(frozen,optical);
        }, GetTickCount64());
}

void VR::duoview_abort(const char* reason) {
    std::scoped_lock fault_lock{m_duoview_fault_mutex};
    if (!is_using_duoview_mono()) return;
    const auto tick=m_duoview_game_tick_serial.load(std::memory_order_acquire);
    auto previous=m_duoview_last_failure_tick.load(std::memory_order_acquire);
    while (uevr::duoview::is_distinct_failed_tick(
            tick, previous, m_duoview_last_success_tick.load(std::memory_order_acquire))) {
        if (m_duoview_last_failure_tick.compare_exchange_weak(
                previous, tick, std::memory_order_acq_rel, std::memory_order_acquire)) {
            // A successful compositor callback takes priority over an error
            // reported for the same game tick.
            if (m_duoview_last_success_tick.load(std::memory_order_acquire)==tick) return;
            const auto failures=m_duoview_consecutive_failures.fetch_add(1,std::memory_order_acq_rel)+1;
            const bool ever_presented=m_duoview_ever_presented.load(std::memory_order_acquire);
            if (uevr::duoview::should_fallback_to_mono(failures,ever_presented))
                m_duoview_fallback_requested.store(true,std::memory_order_release);
            SPDLOG_WARNING_EVERY_N_SEC(2,"[DuoView] Faulted game tick {}: failure streak {} (startup_warmup={}): {}. Fallback: Joey Mono ID5",
                tick, failures, !ever_presented, reason);
            set_mono_status("DuoView fault; waiting for valid pair or Joey Mono ID5");
            return;
        }
    }
}
void VR::duoview_frame_success() {
    std::scoped_lock fault_lock{m_duoview_fault_mutex};
    if (!is_using_duoview_mono()) return;
    m_duoview_last_success_tick.store(m_duoview_game_tick_serial.load(std::memory_order_acquire),
        std::memory_order_release);
    m_duoview_ever_presented.store(true,std::memory_order_release);
    m_duoview_consecutive_failures.store(0,std::memory_order_release);
    m_duoview_fallback_requested.store(false,std::memory_order_release);
}
void VR::reset_duoview_faults() {
    std::scoped_lock fault_lock{m_duoview_fault_mutex};
    m_duoview_ever_presented.store(false,std::memory_order_release);
    m_duoview_consecutive_failures.store(0,std::memory_order_release);
    m_duoview_last_failure_tick.store(uevr::duoview::duoview_unseen_tick,std::memory_order_release);
    m_duoview_last_success_tick.store(uevr::duoview::duoview_unseen_tick,std::memory_order_release);
    m_duoview_fallback_requested.store(false,std::memory_order_release);
}
'''
    hook="src/mods/vr/FFakeStereoRenderingHook.cpp"
    edit(hook,'#include "FFakeStereoRenderingHook.hpp"',
        '#include "FFakeStereoRenderingHook.hpp"\n#include "DuoViewGeometry.hpp"')
    edit(hook,'    SPDLOG_INFO_ONCE("UGameViewportClient::Draw called for the first time.");\n\n    if (!g_framework->is_game_data_intialized()) {\n        call_orig();\n        return;\n    }',
        '''    SPDLOG_INFO_ONCE("UGameViewportClient::Draw called for the first time.");

    if (!g_framework->is_game_data_intialized()) {
        if (auto& startup_vr=VR::get(); startup_vr && startup_vr->defer_duoview_bootstrap_draw()) return;
        call_orig();
        return;
    }''')
    draw_scope = "\n".join((
        "    utility::ScopeGuard _{ ",
        "        []() { ",
        "            g_hook->m_in_viewport_client_draw = false;",
        "            g_hook->m_was_in_viewport_client_draw = false;",
        "        } ",
        "    };",
        "",
        "    auto vr = VR::get();",
        "",
        "    if (!vr->is_hmd_active()) {",
    ))
    edit(hook, draw_scope, draw_scope[:-len("    if (!vr->is_hmd_active()) {")] + """    // This is the last game-thread boundary before UE builds another scene.
    // Keep native Draw quiescent until startup configuration, mode request,
    // and actual Mono-consumer retirement are ready.
    if (vr->defer_duoview_bootstrap_draw()) return;

    if (!vr->is_hmd_active()) {""")
    edit(hook, '    const auto in_engine_tick = g_hook->m_in_engine_tick;',
    '''    const auto in_engine_tick = g_hook->m_in_engine_tick;
    // update_hmd_state advances the runtime counter before either view is built.
    const auto prior_duoview_frame=vr->exchange_duoview_draw_frame(
        vr->get_runtime()->internal_frame_count+1u);
    utility::ScopeGuard restore_duoview_draw_frame{[&]() {
        vr->exchange_duoview_draw_frame(prior_duoview_frame);
    }};''')
    edit(hook,'    if (vr->is_using_mono()) { return 1; }',
        '    if (vr->is_duoview_renderer_active()) { return 2; }\n    if (vr->is_using_mono()) { return 1; }')
    edit(hook,'''    if (VR::get()->is_using_mono()) {
        *x = 0;
        *y = 0;
    } else if (!VR::get()->is_native_stereo_fix_enabled() || swgr_ue574_dx12_runtime()) {''',
    '''    if (VR::get()->is_duoview_renderer_active() && g_hook->m_has_double_precision &&
        (index == 0 || index == 1)) {
        const auto vr = VR::get();
        if (const auto frame = vr->duoview_begin_frame()) {
            const auto& rect = static_cast<uint32_t>(index) == frame->config.settings.fovea_view
                ? frame->config.layout.fovea : frame->config.layout.periphery;
            if (rect.width && rect.height &&
                uint64_t(rect.x) + rect.width <= frame->config.layout.atlas_width &&
                uint64_t(rect.y) + rect.height <= frame->config.layout.atlas_height) {
                *x = static_cast<int>(rect.x);
                *y = static_cast<int>(rect.y);
                *w = rect.width;
                *h = rect.height;
                vr->duoview_state().rectangle(frame->config.key, static_cast<unsigned>(index));
                return;
            }
        }
        // Pair cannot pass frame validation. Original Mono fallback is guarded at submission.
    }
    if (VR::get()->is_using_mono()) {
        *x = 0;
        *y = 0;
    } else if (!VR::get()->is_native_stereo_fix_enabled() || swgr_ue574_dx12_runtime()) {''')
    # A second view must receive the SAME fully processed Mono camera, not
    # a physical right-eye offset or a second head-pose sample.
    edit(hook,'''    auto vr = VR::get();
    //std::scoped_lock _{vr->get_vr_mutex()};''',
    '''    auto vr = VR::get();
    if (vr->is_duoview_renderer_active() && g_hook->m_has_double_precision && view_index == 1) {
        const auto key = vr->duoview_producer_key();
        if (const auto pose = vr->duoview_state().camera(key, 1)) {
            auto* rot = reinterpret_cast<Rotator<double>*>(view_rotation);
            auto* pos = reinterpret_cast<Vector3d*>(view_location);
            rot->pitch = pose->rotation[0]; rot->yaw = pose->rotation[1]; rot->roll = pose->rotation[2];
            pos->x = pose->position[0]; pos->y = pose->position[1]; pos->z = pose->position[2];
            if (vr->duoview_state().camera(key, 1, *pose)) return;
        }
        // A missing pose remains incomplete; the render submission gate will fall back.
    }
    //std::scoped_lock _{vr->get_vr_mutex()};''')
    edit(hook,'''        // Modify Player Control Rotation
        const auto controller_camera_guard_active = vr->is_controller_camera_conflict_guard_active();''',
    '''        if (vr->is_duoview_renderer_active() && g_hook->m_has_double_precision && view_index == 0) {
            const auto key = vr->duoview_producer_key();
            const auto* r = reinterpret_cast<const Rotator<double>*>(view_rotation);
            const auto* p = reinterpret_cast<const Vector3d*>(view_location);
            const uevr::duoview::CameraPose pose{{r->pitch,r->yaw,r->roll},{p->x,p->y,p->z}};
            vr->duoview_begin_frame();
            if (!vr->duoview_state().camera(key, 0, pose))
                SPDLOG_WARNING_EVERY_N_SEC(2, "[DuoView] First scene pose not captured");
        }

        // Modify Player Control Rotation
        const auto controller_camera_guard_active = vr->is_controller_camera_conflict_guard_active();''')
    edit(hook,'''        if (vr->is_using_mono()) { true_index = 0; }

        auto& double_matrix = *(Matrix4x4d*)out;''',
    '''        const bool duo_index=vr->is_duoview_renderer_active() && g_hook->m_has_double_precision &&
            (view_index == 0 || view_index == 1);
        const auto duo_frame=duo_index ? vr->duoview_begin_frame() :
            std::optional<uevr::duoview::ViewFrame>{};
        const bool duo_fovea=duo_frame && static_cast<uint32_t>(view_index) == duo_frame->config.settings.fovea_view;
        const bool duo_full=duo_frame && !duo_fovea;
        if (vr->is_using_mono()) { true_index = 0; }

        auto& double_matrix = *(Matrix4x4d*)out;''')
    edit(hook,'''        if (vr->mono_frame_gate_required() && vr->get_runtime()->is_openxr()) {
            vr->get_openxr_runtime()->note_mono_projection();
        }''',
    '''        if (duo_fovea || duo_full) {
            if (const auto frame = vr->duoview_begin_frame()) {
                uevr::duoview::apply_frame_projection(double_matrix,*frame,static_cast<unsigned>(view_index));
                vr->duoview_state().projection(frame->config.key, static_cast<unsigned>(view_index));
            } else {
                SPDLOG_WARNING_EVERY_N_SEC(2, "[DuoView] Missing projection snapshot");
            }
        }
        if (vr->mono_frame_gate_required() && vr->get_runtime()->is_openxr()) {
            vr->get_openxr_runtime()->note_mono_projection();
        }''')
    edit(hook,'''            (!vr->is_using_mono() || views_ptr->count == 1));''',
    '''            (!vr->is_using_mono() ||
              (vr->is_duoview_renderer_active() ? views_ptr->count == 2 : views_ptr->count == 1)));''')
    edit(hook, '    runtime->on_pre_render_game_thread(frame_count);',
    '''    runtime->on_pre_render_game_thread(frame_count);
    if (vr->is_duoview_renderer_active() && views_ptr) {
        const auto rtm=g_hook->get_render_target_manager();
        const bool main_family=rtm && view_family.get_render_target()!=nullptr &&
            view_family.get_render_target()==rtm->get_view_family_render_target();
        vr->duoview_state().family(vr->duoview_key(frame_count), main_family, views_ptr->count);
    }''')
    edit(hook, '    std::optional<uint32_t> views_original_count{};',
    '''    std::optional<uint32_t> views_original_count{};
    sdk::TArray<sdk::FSceneView*>* duo_hidden_views{};
    int32_t duo_original_count{};
    utility::ScopeGuard restore_duoview_family{[&]() {
        if (duo_hidden_views) duo_hidden_views->count=duo_original_count;
    }};
    struct DuoViewSceneObservation {
        uevr::duoview::FrameKey key;
        unsigned index;
        uintptr_t state;
        bool shading;
    };
    std::optional<DuoViewSceneObservation> duo_scene_observation;
    if (vr->is_duoview_renderer_active() && g_hook->is_in_viewport_client_draw()) {
        const auto family=init_options_view_family;
        const auto rtm=g_hook->get_render_target_manager();
        const auto views=family ? family->get_views() : nullptr;
        const bool main=family && rtm && family->get_render_target()==rtm->get_view_family_render_target();
        const bool source_pass=init_options_original_stereo_pass==EStereoscopicPass::eSSP_PRIMARY ||
                               init_options_original_stereo_pass==EStereoscopicPass::eSSP_SECONDARY;
        if (main && views && source_pass) {
            const unsigned index=init_options_original_stereo_pass==EStereoscopicPass::eSSP_PRIMARY ? 0u : 1u;
            const auto key=vr->duoview_producer_key();
            const auto state=reinterpret_cast<uintptr_t>(init_options_scene_state);
            bool applied=false;
            // Same source-construction pair treatment as Native Stereo Fix:
            // SECONDARY impersonates PRIMARY only during the constructor,
            // temporarily hiding the already-constructed view-family list.
            // Restore the exact mutated array on normal return and C++ unwind.
            if (index==1 && views->count==1 &&
                sdk::FSceneViewFamily::validate_views(family,views,2) &&
                is_readable_process_range(state,sizeof(uintptr_t)) &&
                vr->duoview_state().can_native_fix_secondary_source(key,state)) {
                restore_init_options_after_constructor=true;
                set_effective_stereo_pass(EStereoscopicPass::eSSP_PRIMARY);
                applied=get_effective_stereo_pass()==EStereoscopicPass::eSSP_PRIMARY;
                if (applied) {
                    duo_hidden_views=views;
                    duo_original_count=views->count;
                    views->count=0;
                    SPDLOG_INFO_ONCE("[DuoView] Native Fix source construction: temporary PRIMARY pass + hidden family singleton");
                }
            }
            duo_scene_observation=DuoViewSceneObservation{key,index,state,applied};
        }
    }''')
    edit(hook,
        '    auto result = g_hook->m_sceneview_data.constructor_hook.unsafe_call<sdk::FSceneView*>(view, init_options, a3, a4);',
    '''    auto result = g_hook->m_sceneview_data.constructor_hook.unsafe_call<sdk::FSceneView*>(view, init_options, a3, a4);
    if (duo_hidden_views) {
        duo_hidden_views->count=duo_original_count;
        duo_hidden_views=nullptr;
    }
    if (result && duo_scene_observation) {
        const auto& observation=*duo_scene_observation;
        vr->duoview_state().scene(observation.key,observation.index,observation.state,observation.shading);
    }''')
    # Engine construction observes camera/rect/projection; a complete pair is
    # required before composition, not before we let the engine build its views.
    dxh="src/mods/vr/D3D12Component.hpp"
    edit(dxh,'#include "d3d12/TextureContext.hpp"',
        '#include "d3d12/TextureContext.hpp"\n#include "DuoViewD3D12.hpp"')
    edit(dxh,'            std::shared_ptr<uevr::stalker2_native::PairFrame> retained_stalker_pair = nullptr);',
        '            std::shared_ptr<uevr::stalker2_native::PairFrame> retained_stalker_pair = nullptr,\n            bool duoview_recovery = false, bool* deferred_for_gpu = nullptr);')
    cc_h="src/mods/vr/d3d12/CommandContext.hpp"
    edit(cc_h,"#include <mutex>\n#include <d3d12.h>",
        "#include <mutex>\n#include <vector>\n#include <d3d12.h>")
    edit(cc_h,"    void execute();",'''    void execute();
    /// Enables recovery and retained-resource quarantine for DuoView submissions.
    void enable_duoview_poison_recovery();
    /// Keeps a D3D object alive through retirement of DuoView work.
    void retain_duoview_reference(IUnknown* object);
    /// Reports a known in-flight fence as ordinary GPU backpressure.
    bool is_duoview_backpressured();
    /// Proves retirement using the captured queue and fence evidence.
    bool duoview_retirement_proven();
    /// Resets the command slot after retirement is proven.
    bool duoview_reset_after_retirement();
    /// Waits for retirement without releasing uncertain resources.
    bool duoview_wait(uint32_t ms);
    /// Clears completed DuoView queue, fence and resource evidence.
    void duoview_clear_tracking();
    /// Quarantines retained resources when teardown cannot prove retirement.
    void quarantine_duoview_resources();''')
    edit(cc_h,"    bool poisoned{false};",'''    bool poisoned{false};
    bool duoview_recovery_enabled{false};
    bool duoview_execute_submitted{false};
    bool duoview_preexecute_failure_proven{false};
    bool duoview_submitted_fence_signaled{false};
    UINT64 duoview_submitted_fence_value{};
    bool duoview_recovery_fence_signaled{false};
    UINT64 duoview_recovery_fence_value{};
    ComPtr<ID3D12CommandQueue> duoview_queue{};
    ComPtr<ID3D12Device> duoview_device{};
    std::vector<ComPtr<IUnknown>> duoview_retained_references{};''')
    cc_cpp="src/mods/vr/d3d12/CommandContext.cpp"
    dx="src/mods/vr/D3D12Component.cpp"
    edit(cc_cpp,'#include <chrono>\n#include <string_view>',
        '#include <chrono>\n#include <string_view>\n#include <thread>\n#include <limits>\n#include <algorithm>\n#include <utility>\n#include "../DuoViewCommandRecovery.hpp"')
    edit(cc_cpp,'''namespace d3d12 {
void set_fence_profiler_enabled(bool enabled) {''',
    '''namespace {
struct DuoViewQuarantineEntry {
    d3d12::ComPtr<ID3D12CommandAllocator> allocator{};
    d3d12::ComPtr<ID3D12GraphicsCommandList> command_list{};
    d3d12::ComPtr<ID3D12Fence> fence{};
    d3d12::ComPtr<ID3D12CommandQueue> queue{};
    d3d12::ComPtr<ID3D12Device> device{};
    std::vector<d3d12::ComPtr<IUnknown>> references{};
    HANDLE event{};
};
auto& duoview_quarantine() {
    static auto* entries = new std::vector<DuoViewQuarantineEntry>();
    return *entries;
}
auto& duoview_quarantine_mutex() {
    static auto* mutex = new std::mutex();
    return *mutex;
}
}

namespace d3d12 {
void CommandContext::enable_duoview_poison_recovery() {
    std::scoped_lock _{this->mtx};
    this->duoview_recovery_enabled = true;
}

void CommandContext::retain_duoview_reference(IUnknown* object) {
    std::scoped_lock _{this->mtx};
    if (!this->duoview_recovery_enabled || object == nullptr) return;
    for (const auto& retained : this->duoview_retained_references)
        if (retained.Get() == object) return;
    ComPtr<IUnknown> retained = object;
    this->duoview_retained_references.push_back(std::move(retained));
}

void CommandContext::duoview_clear_tracking() {
    std::scoped_lock _{this->mtx};
    this->duoview_execute_submitted = false;
    this->duoview_preexecute_failure_proven = false;
    this->duoview_submitted_fence_signaled = false;
    this->duoview_submitted_fence_value = 0;
    this->duoview_recovery_fence_signaled = false;
    this->duoview_recovery_fence_value = 0;
    this->duoview_queue.Reset();
    this->duoview_device.Reset();
    this->duoview_retained_references.clear();
}

bool CommandContext::duoview_retirement_proven() {
    std::scoped_lock _{this->mtx};
    if (!this->duoview_execute_submitted) {
        if (this->waiting_for_fence) {
            if (!this->fence) return false;
            const auto completed = this->fence->GetCompletedValue();
            return completed != UINT64_MAX && completed >= this->fence_value;
        }
        const auto completed = this->fence ? this->fence->GetCompletedValue() : 0;
        const bool device_removed = completed == UINT64_MAX && this->duoview_device &&
            FAILED(this->duoview_device->GetDeviceRemovedReason());
        return uevr::duoview::fence_retirement_proven({false, this->has_commands,
            this->poisoned, this->duoview_preexecute_failure_proven,
            false, 0, false, 0, completed, device_removed});
    }
    const bool captured_device_removed = this->duoview_device &&
        FAILED(this->duoview_device->GetDeviceRemovedReason());
    if (captured_device_removed) return true;
    if (!this->fence || !this->duoview_queue) return false;
    const auto prior_completed = this->fence->GetCompletedValue();
    const bool prior_device_removed = prior_completed == UINT64_MAX && this->duoview_device &&
        FAILED(this->duoview_device->GetDeviceRemovedReason());
    if (prior_device_removed) return true;
    if (!this->duoview_submitted_fence_signaled && !this->duoview_recovery_fence_signaled) {
        const auto next = this->fence_value + 1;
        if (next != 0) {
            const auto signal_result = this->duoview_queue->Signal(this->fence.Get(), next);
            if (SUCCEEDED(signal_result)) {
                this->duoview_recovery_fence_signaled = true;
                this->duoview_recovery_fence_value = next;
                this->fence_value = next;
                if (this->fence_event != nullptr)
                    this->fence->SetEventOnCompletion(next, this->fence_event);
            } else if (this->duoview_device &&
                       FAILED(this->duoview_device->GetDeviceRemovedReason())) {
                return true;
            }
        }
    }
    const auto completed = this->fence->GetCompletedValue();
    const bool device_removed = completed == UINT64_MAX && this->duoview_device &&
        FAILED(this->duoview_device->GetDeviceRemovedReason());
    return uevr::duoview::fence_retirement_proven({
        this->duoview_execute_submitted,
        this->has_commands,
        this->poisoned,
        this->duoview_preexecute_failure_proven,
        this->duoview_submitted_fence_signaled,
        this->duoview_submitted_fence_value,
        this->duoview_recovery_fence_signaled,
        this->duoview_recovery_fence_value,
        completed,
        device_removed});
}

bool CommandContext::is_duoview_backpressured() {
    std::scoped_lock _{this->mtx};
    if (!this->duoview_recovery_enabled) return false;
    if (this->duoview_execute_submitted)
        return !this->duoview_retirement_proven() &&
            (this->duoview_submitted_fence_signaled || this->duoview_recovery_fence_signaled);
    return this->waiting_for_fence && !this->poisoned && this->fence &&
        this->fence->GetCompletedValue() != UINT64_MAX &&
        this->fence->GetCompletedValue() < this->fence_value;
}

bool CommandContext::duoview_reset_after_retirement() {
    std::scoped_lock _{this->mtx};
    if (!this->duoview_retirement_proven()) return false;
    if (this->fence_event != nullptr) ResetEvent(this->fence_event);
    this->waiting_for_fence = false;
    if (this->cmd_allocator && FAILED(this->cmd_allocator->Reset())) {
        const auto failed_reset = uevr::duoview::reset_failed_after_retirement(true,
            {this->duoview_execute_submitted, this->has_commands, this->poisoned,
             this->duoview_preexecute_failure_proven});
        this->has_commands = failed_reset.commands_recorded;
        this->poisoned = failed_reset.poisoned;
        this->duoview_clear_tracking();
        this->duoview_preexecute_failure_proven = failed_reset.preexecute_failure_proven;
        return false;
    }
    if (this->cmd_list && this->cmd_allocator && FAILED(this->cmd_list->Reset(this->cmd_allocator.Get(), nullptr))) {
        const auto failed_reset = uevr::duoview::reset_failed_after_retirement(true,
            {this->duoview_execute_submitted, this->has_commands, this->poisoned,
             this->duoview_preexecute_failure_proven});
        this->has_commands = failed_reset.commands_recorded;
        this->poisoned = failed_reset.poisoned;
        this->duoview_clear_tracking();
        this->duoview_preexecute_failure_proven = failed_reset.preexecute_failure_proven;
        return false;
    }
    this->has_commands = false;
    this->poisoned = false;
    this->duoview_clear_tracking();
    return this->ready();
}

bool CommandContext::duoview_wait(uint32_t ms) {
    std::scoped_lock _{this->mtx};
    if (!this->duoview_execute_submitted && !this->waiting_for_fence) {
        if (this->has_commands) return false;
        if (this->poisoned) {
            const auto name = this->internal_name;
            return this->setup(name.c_str());
        }
        return this->ready();
    }
    const auto start = std::chrono::steady_clock::now();
    const bool infinite = ms == INFINITE;
    while (!this->duoview_retirement_proven()) {
        if (!infinite && std::chrono::steady_clock::now() - start >= std::chrono::milliseconds(ms)) return false;
        bool event_armed = false;
        const auto target = this->duoview_recovery_fence_signaled ? this->duoview_recovery_fence_value :
            (this->duoview_submitted_fence_signaled ? this->duoview_submitted_fence_value : 0);
        if (target && this->fence && this->fence_event &&
            SUCCEEDED(this->fence->SetEventOnCompletion(target, this->fence_event))) {
            event_armed = true;
        }
        if (event_armed) {
            DWORD timeout = INFINITE;
            if (!infinite) {
                const auto elapsed = std::chrono::duration_cast<std::chrono::milliseconds>(
                    std::chrono::steady_clock::now() - start).count();
                timeout = static_cast<DWORD>(std::max<int64_t>(0, static_cast<int64_t>(ms) - elapsed));
            }
            WaitForSingleObject(this->fence_event, timeout);
        } else {
            std::this_thread::sleep_for(std::chrono::milliseconds(1));
        }
    }
    return this->duoview_reset_after_retirement();
}

void CommandContext::quarantine_duoview_resources() {
    std::scoped_lock _{this->mtx};
    if (!this->duoview_execute_submitted) return;
    DuoViewQuarantineEntry entry{};
    entry.allocator = this->cmd_allocator;
    entry.command_list = this->cmd_list;
    entry.fence = this->fence;
    entry.queue = this->duoview_queue;
    entry.device = this->duoview_device;
    entry.references = this->duoview_retained_references;
    entry.event = std::exchange(this->fence_event, nullptr);
    std::scoped_lock quarantine_lock{duoview_quarantine_mutex()};
    duoview_quarantine().push_back(std::move(entry));
    spdlog::error("[DuoView] GPU retirement unproven; command and resource graph retained until process exit");
}

void set_fence_profiler_enabled(bool enabled) {''')
    edit(cc_cpp,'    if (this->waiting_for_fence && !this->wait(2000)) {',
    '''    if (this->duoview_recovery_enabled && this->duoview_execute_submitted) {
        if (!this->duoview_retirement_proven()) return false;
        this->duoview_clear_tracking();
    }
    if (this->waiting_for_fence && !this->wait(2000)) {''')
    edit(cc_cpp,'    if (this->duoview_recovery_enabled && this->duoview_execute_submitted) {\n        if (!this->duoview_retirement_proven()) return false;\n        this->duoview_clear_tracking();\n    }',
    '''    if (this->duoview_recovery_enabled && this->duoview_execute_submitted) {
        if (!this->duoview_retirement_proven()) return false;
        this->duoview_clear_tracking();
    }
    if (this->duoview_recovery_enabled && !this->duoview_execute_submitted &&
        (this->has_commands || (this->poisoned && !this->duoview_preexecute_failure_proven)))
        return false;''')
    edit(cc_cpp,'    this->internal_name = name;',
    '''    if (this->duoview_recovery_enabled) this->duoview_clear_tracking();
    this->internal_name = name;''')
    edit(cc_cpp,'    this->waiting_for_fence = false;\n    this->has_commands = false;\n    this->poisoned = false;\n    this->close_failure_count = 0;\n}\n\nbool CommandContext::wait',
    '''    this->waiting_for_fence = false;
    this->has_commands = false;
    this->poisoned = false;
    this->close_failure_count = 0;
    this->duoview_recovery_enabled = false;
    this->duoview_clear_tracking();
}

bool CommandContext::wait''')
    edit(cc_cpp,'''void CommandContext::reset() {
    std::scoped_lock _{this->mtx};
    this->wait(2000);
    //this->on_post_present(VR::get().get());''',
    '''void CommandContext::reset() {
    std::scoped_lock _{this->mtx};
    const bool waited = this->wait(2000);
    if (this->duoview_recovery_enabled && this->duoview_execute_submitted) {
        if (!waited && !this->duoview_retirement_proven())
            this->quarantine_duoview_resources();
        else
            this->duoview_clear_tracking();
    }
    //this->on_post_present(VR::get().get());''')
    edit(cc_cpp,'''    this->poisoned = false;
    this->close_failure_count = 0;

    if (FAILED(device->CreateCommandAllocator''',
    '''    this->poisoned = false;
    this->duoview_preexecute_failure_proven = false;
    this->close_failure_count = 0;

    if (FAILED(device->CreateCommandAllocator''')
    edit(cc_cpp,'bool CommandContext::wait(uint32_t ms) {\n    std::scoped_lock _{this->mtx};',
    '''bool CommandContext::wait(uint32_t ms) {
    std::scoped_lock _{this->mtx};
    if (this->duoview_recovery_enabled) return this->duoview_wait(ms);''')
    edit(cc_cpp,'bool CommandContext::try_wait() {\n    std::scoped_lock _{this->mtx};',
    '''bool CommandContext::try_wait() {
    std::scoped_lock _{this->mtx};
    if (this->duoview_recovery_enabled) {
        if (!this->duoview_execute_submitted && !this->waiting_for_fence) {
            if (this->has_commands) return false;
            if (this->poisoned) {
                const auto name = this->internal_name;
                return this->setup(name.c_str());
            }
            return this->ready();
        }
        return this->duoview_reset_after_retirement();
    }''')
    edit(cc_cpp,'''bool CommandContext::references_retired() {
    std::scoped_lock _{this->mtx};
    return utility::gpu::references_retired(this->has_commands, this->waiting_for_fence,
        this->poisoned, this->fence != nullptr, this->fence_value,
        [&] { return this->fence->GetCompletedValue(); });
}''',
    '''bool CommandContext::references_retired() {
    std::scoped_lock _{this->mtx};
    if (this->duoview_recovery_enabled) return this->duoview_retirement_proven();
    return utility::gpu::references_retired(this->has_commands, this->waiting_for_fence,
        this->poisoned, this->fence != nullptr, this->fence_value,
        [&] { return this->fence->GetCompletedValue(); });
}''')
    edit(cc_cpp,'''        ID3D12CommandList* const cmd_lists[] = {this->cmd_list.Get()};''',
    '''        if (this->duoview_recovery_enabled) {
            this->duoview_queue = command_queue;
            this->duoview_device.Reset();
            command_queue->GetDevice(IID_PPV_ARGS(&this->duoview_device));
            this->duoview_execute_submitted = false;
            this->duoview_preexecute_failure_proven = false;
            this->duoview_submitted_fence_signaled = false;
            this->duoview_submitted_fence_value = 0;
            this->duoview_recovery_fence_signaled = false;
            this->duoview_recovery_fence_value = 0;
        }
        ID3D12CommandList* const cmd_lists[] = {this->cmd_list.Get()};''')
    edit(cc_cpp,'        command_queue->ExecuteCommandLists(1, cmd_lists);\n        const auto next_fence_value',
    '''        command_queue->ExecuteCommandLists(1, cmd_lists);
        if (this->duoview_recovery_enabled) this->duoview_execute_submitted = true;
        const auto next_fence_value''')
    edit(cc_cpp,'        this->fence_value = next_fence_value;\n        const auto event_result',
    '''        this->fence_value = next_fence_value;
        if (this->duoview_recovery_enabled) {
            this->duoview_submitted_fence_signaled = true;
            this->duoview_submitted_fence_value = next_fence_value;
        }
        const auto event_result''')
    edit(cc_cpp,'''        if (FAILED(close_result)) {
            this->has_commands = false;
            this->poisoned = true;''',
    '''        if (FAILED(close_result)) {
            this->has_commands = false;
            if (this->duoview_recovery_enabled) this->duoview_preexecute_failure_proven = true;
            this->poisoned = true;''')
    edit(cc_cpp,'''        if (command_queue == nullptr) {
            this->poisoned = true;''',
    '''        if (command_queue == nullptr) {
            if (this->duoview_recovery_enabled) {
                const auto failed_before_execute = uevr::duoview::queue_unavailable_after_close(
                    {this->duoview_execute_submitted, this->has_commands, this->poisoned,
                     this->duoview_preexecute_failure_proven});
                this->has_commands = failed_before_execute.commands_recorded;
                this->poisoned = failed_before_execute.poisoned;
                this->duoview_preexecute_failure_proven = failed_before_execute.preexecute_failure_proven;
            } else {
                this->poisoned = true;
            }''')
    edit(cc_cpp,'''    if (src == nullptr || dst == nullptr) {
        spdlog::error("[VR] nullptr passed to copy_region_to_subresource");
        return;
    }''',
    '''    if (src == nullptr || dst == nullptr) {
        spdlog::error("[VR] nullptr passed to copy_region_to_subresource");
        return;
    }
    this->retain_duoview_reference(src);
    this->retain_duoview_reference(dst);''')
    edit(dx,'''    std::shared_ptr<uevr::stalker2_native::PairFrame> retained_stalker_pair)
{''',
    '''    std::shared_ptr<uevr::stalker2_native::PairFrame> retained_stalker_pair,
    bool duoview_recovery,
    bool* deferred_for_gpu)
{''')
    edit(dx,'''    bool* deferred_for_gpu)
{
    std::scoped_lock _{this->mtx};''',
    '''    bool* deferred_for_gpu)
{
    std::scoped_lock _{this->mtx};
    if (deferred_for_gpu) *deferred_for_gpu = false;''')
    edit(dx,'''    auto& texture_ctx = ctx.texture_contexts[texture_index];
    const bool retired = retained_mono_source != nullptr''',
    '''    auto& texture_ctx = ctx.texture_contexts[texture_index];
    if (duoview_recovery) texture_ctx->commands.enable_duoview_poison_recovery();
    const bool retired = retained_mono_source != nullptr''')
    edit(dx,'''        if (!retired || !texture_ctx->commands.ready()) {
            // No new commands reference this acquired image. Keep the old''',
    '''        if (!retired || !texture_ctx->commands.ready()) {
            if (deferred_for_gpu && duoview_recovery && texture_ctx->commands.is_duoview_backpressured())
                *deferred_for_gpu = true;
            // No new commands reference this acquired image. Keep the old''')
    edit(dxh, '        std::array<d3d12::TextureContext, 3> left_eye_tex{};',
        '''        bool copy_duoview_pair(ID3D12Resource* source, bool& deferred_for_gpu) {
            deferred_for_gpu = false;
            if (!source) return false;
            const auto desc=source->GetDesc();
            const UINT width=parent->m_backbuffer_size[0]/2;
            const UINT height=parent->m_backbuffer_size[1];
            if (!width || !height || desc.Width!=uint64_t(width)*2 || desc.Height!=height)
                return false;
            for (unsigned eye=0;eye<2;++eye) {
                auto& ctx=eye==0 ? get_left() : get_right();
                if (!ctx.texture) return false;
                ctx.commands.enable_duoview_poison_recovery();
                if (!ctx.commands.try_wait()) {
                    deferred_for_gpu = ctx.commands.is_duoview_backpressured();
                    return false;
                }
                if (!ctx.commands.ready()) return false;
                const auto target=ctx.texture->GetDesc();
                if (target.Width!=width || target.Height!=height) return false;
                const auto fence_before=ctx.commands.fence_value;
                D3D12_BOX box{eye*width,0,0,(eye+1)*width,height,1};
                ctx.commands.copy_region(source,ctx.texture.Get(),&box,
                    D3D12_RESOURCE_STATE_RENDER_TARGET,D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE);
                ctx.commands.execute();
                if (!ctx.commands.ready() || !ctx.commands.waiting_for_fence ||
                    ctx.commands.fence_value<=fence_before) return false;
            }
            return true;
        }

        std::array<d3d12::TextureContext, 3> left_eye_tex{};''')
    edit(dxh,'''        std::array<d3d12::TextureContext, 3> right_eye_tex{};
        d3d12::TextureContext ui_tex{};''',
        '''        std::array<d3d12::TextureContext, 3> right_eye_tex{};
        // OpenVR's source pair is composed to the same full-width Mono texture
        // as OpenXR, then both eye textures receive the two identical halves.
        Microsoft::WRL::ComPtr<ID3D12Resource> duoview_output{};
        d3d12::CommandContext duoview_commands{};
        std::unique_ptr<uevr::duoview::dx12::Compositor> duoview_compositor{};
        d3d12::TextureContext ui_tex{};''')
    edit(dxh,'        std::unordered_map<uint32_t, SwapchainContext> contexts{};',
        '''        std::unordered_map<uint32_t, SwapchainContext> contexts{};
        std::unordered_map<d3d12::CommandContext*, std::unique_ptr<uevr::duoview::dx12::Compositor>> duoview_compositors;''')
    dx="src/mods/vr/D3D12Component.cpp"
    edit(dx,'''    for (auto& ctx : m_openvr.left_eye_tex) {
        ctx.reset();
    }''',
        '''    m_openvr.duoview_commands.reset();
    m_openvr.duoview_compositor.reset();
    m_openvr.duoview_output.Reset();
    for (auto& ctx : m_openvr.left_eye_tex) {
        ctx.reset();
    }''')
    # Allocate/prewarm the OpenVR DuoView output in normal setup, never in
    # SteamVR Submit or a live compositor hot path.
    edit(dx,'        // Set up the UI texture to match the engine-provided UI extent when available.',
    '''        if (vr->is_duoview_renderer_active()) {
            auto duo_desc=backbuffer_desc;
            duo_desc.Width=backbuffer_desc.Width*2;
            if (duo_desc.Width==0 || duo_desc.Width>16384 || duo_desc.Height>16384 ||
                FAILED(device->CreateCommittedResource(&heap_props,D3D12_HEAP_FLAG_NONE,
                    &duo_desc,D3D12_RESOURCE_STATE_RENDER_TARGET,nullptr,
                    IID_PPV_ARGS(&m_openvr.duoview_output)))) {
                SPDLOG_ERROR("[DuoView][OpenVR] Full-size compositor target allocation failed");
                return false;
            }
            if (!m_openvr.duoview_commands.setup(L"DuoView OpenVR compositor"))
                return false;
            m_openvr.duoview_compositor=std::make_unique<uevr::duoview::dx12::Compositor>();
            UINT64 frequency{};
            if (auto queue=hook->get_command_queue();queue)
                queue->GetTimestampFrequency(&frequency);
            if (!m_openvr.duoview_compositor->prewarm(device,
                static_cast<UINT>(backbuffer_desc.Width),
                backbuffer_desc.Height,
                backbuffer->GetDesc().Format==DXGI_FORMAT_B8G8R8A8_UNORM_SRGB ||
                    backbuffer->GetDesc().Format==DXGI_FORMAT_R8G8B8A8_UNORM_SRGB,frequency)) {
                SPDLOG_ERROR("[DuoView][OpenVR] Compositor prewarm failed");
                return false;
            }
        }

        // Set up the UI texture to match the engine-provided UI extent when available.''')
    edit(dx,'    this->contexts.clear();\n    vr->m_openxr->swapchains.clear();',
        '    this->duoview_compositors.clear();\n    this->contexts.clear();\n    vr->m_openxr->swapchains.clear();')
    edit(dx,'    this->contexts.clear();\n\n    auto create_swapchain',
        '    this->duoview_compositors.clear();\n    this->contexts.clear();\n\n    auto create_swapchain')
    # Prime each existing XR image's command slot at swapchain setup time.
    # Startup/mode-transition prewarming occurs outside xrAcquire/copy/submit.
    # No change is made to original Joey modes 0/5.
    edit(dx,'''        if (vr->is_native_stereo_fix_texture_array_submit_enabled()) {
            auto native_array_create_info = standard_swapchain_create_info;''',
    '''        if (vr->is_duoview_renderer_active()) {
            auto& duo_ctx = this->contexts[(uint32_t)runtimes::OpenXR::SwapchainIndex::DOUBLE_WIDE];
            const bool duo_srgb = backbuffer_desc.Format == DXGI_FORMAT_B8G8R8A8_UNORM_SRGB ||
                                  backbuffer_desc.Format == DXGI_FORMAT_R8G8B8A8_UNORM_SRGB;
            UINT64 duo_frequency{};
            if (const auto queue=g_framework->get_d3d12_hook()->get_command_queue(); queue)
                queue->GetTimestampFrequency(&duo_frequency);
            for (auto& tc : duo_ctx.texture_contexts) {
                if (!tc) continue;
                auto& comp = this->duoview_compositors[&tc->commands];
                if (!comp) comp = std::make_unique<uevr::duoview::dx12::Compositor>();
                if (!comp->prewarm(device, vr->get_hmd_width(), vr->get_hmd_height(), duo_srgb, duo_frequency)) {
                    SPDLOG_WARNING_EVERY_N_SEC(2,
                        "[DuoView] DX12 prewarm failed: retaining DuoView for next frame");
                }
            }
        }

        if (vr->is_native_stereo_fix_texture_array_submit_enabled()) {
            auto native_array_create_info = standard_swapchain_create_info;''')
    edit(dx,'                    if (vr->is_using_mono()) {\n                        bool recorded = false;',
    '''                    if (vr->is_using_duoview_mono() && !vr->is_duoview_renderer_active()) {
                        vr->duoview_abort("mode6 selected but validated DX12/VR producer unavailable");
                        vr->m_openxr->note_mono_copy(static_cast<uint32_t>(frame_count), false);
                    } else if (vr->is_duoview_renderer_active()) {
                        bool recorded = false;
                        bool deferred_for_gpu = false;
                        bool duo_recorded = false;
                        const auto frame = vr->duoview_state().consume(
                            vr->duoview_key(static_cast<uint32_t>(frame_count)));
                        vr->m_openxr->note_mono_copy(static_cast<uint32_t>(frame_count), false);
                        // Never present the partial DuoView atlas as a whole Mono image.
                        // Request real Joey Mono mode5 after repeated failures via
                        // normal main-thread, GPU-retired mode transition.
                        if (!frame) {
                            vr->duoview_abort("current-frame paired Unreal views unavailable");
                        } else {
                            const bool submitted = m_openxr.copy(
                                (uint32_t)runtimes::OpenXR::SwapchainIndex::DOUBLE_WIDE, nullptr,
                                [this, source=backbuffer, scene_source_state, device, frame,
                                 &recorded, &duo_recorded](
                                    d3d12::CommandContext& commands, ID3D12Resource* destination) {
                                    commands.enable_duoview_poison_recovery();
                                    if (!commands.ready()) return;
                                    auto& item = m_openxr.duoview_compositors[&commands];
                                    if (!item) item = std::make_unique<uevr::duoview::dx12::Compositor>();
                                    duo_recorded = item->record(device, commands.cmd_list.Get(),
                                        source.Get(), destination, scene_source_state, frame->config,
                                        frame->config.settings.gpu_timing ? item->timing_frequency() : 0);
                                    if (frame->config.settings.gpu_timing)
                                        VR::get()->note_duoview_gpu_ms(item->gpu_milliseconds());
                                    if (item->recorded_commands()) {
                                        commands.has_commands = true;
                                        item->retain_gpu_references(commands);
                                        commands.retain_duoview_reference(source.Get());
                                        commands.retain_duoview_reference(destination);
                                    }
                                    recorded=duo_recorded;
                                }, std::nullopt, scene_source_state, nullptr,
                                std::nullopt, backbuffer.Get(), nullptr, true, &deferred_for_gpu);
                            vr->m_openxr->note_mono_copy(static_cast<uint32_t>(frame_count), submitted && recorded);
                            if ((!submitted || !recorded) && !deferred_for_gpu)
                                vr->duoview_abort("OpenXR DX12 composite/copy unavailable");
                        }
                    } else if (vr->is_using_mono()) {
                        bool recorded = false;''')
    # Protect DuoView's OpenVR compositor and output against GPU-use-after-free
    # during transition, device reset and render-target recreation. The original
    # modes have no allocated DuoView output and retain their existing behavior.
    # Full renderer setup failures (swapchain, RT, GPU prewarm) must count
    # towards the fallback rather than silently retrying forever.
    edit(dx,'''        if (!setup()) {
            SPDLOG_ERROR_EVERY_N_SEC(1, "[D3D12 VR] Could not set up, trying again next frame");''',
        '''        if (!setup()) {
            if (vr->is_using_duoview_mono())
                vr->duoview_abort("D3D12 setup/device/swapchain preparation failed");
            SPDLOG_ERROR_EVERY_N_SEC(1, "[D3D12 VR] Could not set up, trying again next frame");''')
    edit(dx,'    return shf_scene_consumers_retired(true) &&',
    '''    if (m_openvr.duoview_output) {
        if (!m_openvr.duoview_commands.references_retired()) return false;
        for (auto& ctx : m_openvr.left_eye_tex)
            if (!ctx.commands.references_retired()) return false;
        for (auto& ctx : m_openvr.right_eye_tex)
            if (!ctx.commands.references_retired()) return false;
    }
    return shf_scene_consumers_retired(true) &&''')
    # OpenVR uses a SteamVR pose/texture presentation path, not OpenXR's
    # mono-frame projection bookkeeping. Require a coherent current producer
    # snapshot instead of probing an XR frame that never exists on OpenVR.
    edit(dx,'''    if (vr->mono_frame_gate_required()) {
        if (!vr->m_openxr->has_mono_frame(static_cast<uint32_t>(vr->m_frame_count))) {
            vr->set_mono_status("Waiting for a current main-view pose and validated common projection");
            vr->m_openxr->end_mono_transition_frame();
            return vr::VRCompositorError_None;
        }
        vr->note_mono_frame_ready(m_mono_generation);
    }''',
    '''    if (vr->mono_frame_gate_required()) {
        if (vr->is_using_mono() && vr->get_runtime()->is_openvr()) {
            // Native OpenVR has no OpenXR mono_frame history. Mode 6's
            // pair is independently checked by consume() at composition.
            // Mode 5 safely submits the one full engine view twice.
            if (!vr->get_runtime<runtimes::OpenVR>()->got_first_valid_poses) {
                vr->set_mono_status("OpenVR: waiting for a valid headset pose");
                return vr::VRCompositorError_None;
            }
        } else if (!vr->m_openxr->has_mono_frame(static_cast<uint32_t>(vr->m_frame_count))) {
            if (vr->is_using_duoview_mono())
                vr->duoview_abort("OpenXR frame/projection gate not ready");
            vr->set_mono_status("Waiting for a current main-view pose and validated common projection");
            vr->m_openxr->end_mono_transition_frame();
            return vr::VRCompositorError_None;
        }
        vr->note_mono_frame_ready(m_mono_generation);
    }''')
    # OpenVR uses the SAME calibrated binocular single-scene union for both
    # Joey Mono ID5 and DuoView ID6; other modes keep regular stereo.
    openvr="src/mods/vr/runtimes/OpenVR.cpp"
    edit("src/mods/vr/runtimes/OpenXR.cpp",
        '    if (mono && result == XR_SUCCESS && !projection_layer_views.empty()) {',
    '''    if (mono && vr->is_duoview_renderer_active() && !projection_layer_views.empty()) {
        if (result == XR_SUCCESS) vr->duoview_frame_success();
        else vr->duoview_abort("OpenXR projection submission failed");
    }
    if (mono && result == XR_SUCCESS && !projection_layer_views.empty()) {''')
    edit(openvr,'#include "../SteamFrameInput.hpp"',
        '#include "../SteamFrameInput.hpp"\n#include "../MonoRenderingPolicy.hpp"\n#include <glm/gtc/quaternion.hpp>')
    edit(openvr,'''        this->projections[vr::Eye_Right] = get_mat(vr::Eye_Right);
        this->should_recalculate_eye_projections = false;''',
    '''        this->projections[vr::Eye_Right] = get_mat(vr::Eye_Right);
        if (auto owner=VR::get(); owner && owner->is_using_mono()) {
            std::array<uevr::mono::Eye,2> optical{};
            for (size_t eye=0; eye<2; ++eye) {
                const auto q=glm::quat_cast(glm::mat3(this->eyes[eye]));
                const auto& position=this->eyes[eye][3];
                const auto& f=this->raw_projections[eye];
                optical[eye]={{q.x,q.y,q.z,q.w},
                    {position.x,position.y,position.z},
                    {f[0],f[1],-f[2],-f[3]}};
            }
            if (const auto common=uevr::mono::geometry(optical)) {
                const auto mono_projection=Matrix4x4f{
                    1.f/common->horizontal,0.f,0.f,0.f,
                    0.f,1.f/common->vertical,0.f,0.f,
                    0.f,0.f,0.f,1.f,
                    0.f,0.f,nearz,0.f};
                for (size_t eye=0;eye<2;++eye) {
                    this->projections[eye]=mono_projection;
                    for (size_t edge=0;edge<4;++edge)
                        this->view_bounds[eye][edge]=common->bounds[eye][edge];
                }
                spdlog::info("[Mono/DuoView][OpenVR] Calibrated shared optical frustum for two per-eye display bounds");
            } else {
                spdlog::error("[Mono/DuoView][OpenVR] Invalid common Mono optical geometry");
                this->should_recalculate_eye_projections=true;
                return VRRuntime::Error::SUCCESS;
            }
        }
        this->should_recalculate_eye_projections = false;''')
    # OpenVR source-pair composition: reuse the same validated compositor
    # and current-frame pair key, but submit through SteamVR's existing two
    # 6DoF pose-aware per-eye textures instead of OpenXR swapchains.
    edit(dx,'''            auto openvr = vr->get_runtime<runtimes::OpenVR>();
            const auto submit_pose = openvr->get_pose_for_submit();

            if (!is_afr) {
                m_openvr.copy_left(backbuffer.Get(), scene_source_state);''',
    '''            auto openvr = vr->get_runtime<runtimes::OpenVR>();
            const auto submit_pose = openvr->get_pose_for_submit();
            if (vr->is_using_duoview_mono() && !vr->is_duoview_renderer_active()) {
                vr->duoview_abort("OpenVR mode6 selected but scene-source prerequisites missing");
                runtime->frame_synced=false;
                return vr::VRCompositorError_None;
            }
            Microsoft::WRL::ComPtr<ID3D12Resource> duo_scene{};
            bool duo_backpressure=false;
            if (vr->is_duoview_renderer_active()) {
                auto frame=vr->duoview_state().consume(
                    vr->duoview_key(static_cast<uint32_t>(frame_count)));
                auto& context=m_openvr.duoview_commands;
                if (frame && m_openvr.duoview_output &&
                    m_openvr.duoview_compositor) {
                    // A failed/poisoned GPU fence must never permit recording
                    // into an in-flight or reset DX12 command allocator.
                    context.enable_duoview_poison_recovery();
                    if (context.try_wait()) {
                      if (context.ready()) {
                        const auto fence_before=context.fence_value;
                        const bool recorded=m_openvr.duoview_compositor->record(device,
                            context.cmd_list.Get(),backbuffer.Get(),m_openvr.duoview_output.Get(),
                            scene_source_state,frame->config,
                            frame->config.settings.gpu_timing ? m_openvr.duoview_compositor->timing_frequency() : 0);
                        if (frame->config.settings.gpu_timing)
                            vr->note_duoview_gpu_ms(m_openvr.duoview_compositor->gpu_milliseconds());
                        if (m_openvr.duoview_compositor->recorded_commands()) {
                            context.has_commands=true;
                            m_openvr.duoview_compositor->retain_gpu_references(context);
                            context.retain_duoview_reference(backbuffer.Get());
                            context.retain_duoview_reference(m_openvr.duoview_output.Get());
                        }
                        context.execute();
                        if (recorded && context.ready() && context.waiting_for_fence &&
                            context.fence_value>fence_before)
                            duo_scene=m_openvr.duoview_output;
                      }
                    } else if (context.is_duoview_backpressured()) {
                        duo_backpressure=true;
                    }
                }
                if (!duo_scene) {
                    if (!duo_backpressure)
                        vr->duoview_abort("OpenVR paired-source composition unavailable");
                    // Do not misinterpret the partial atlas as Mono in this
                    // current frame; transition to true ID5 at frame boundary.
                    runtime->frame_synced=false;
                    return vr::VRCompositorError_None;
                }
            }
            bool eye_copy_deferred=false;
            if (duo_scene && !m_openvr.copy_duoview_pair(duo_scene.Get(), eye_copy_deferred)) {
                duo_backpressure = duo_backpressure || eye_copy_deferred;
                if (!duo_backpressure)
                    vr->duoview_abort("OpenVR per-eye GPU copies failed");
                runtime->frame_synced=false;
                return vr::VRCompositorError_None;
            }
            bool duo_left_submit_ok=false;

            if (!is_afr) {
                if (!duo_scene) m_openvr.copy_left(backbuffer.Get(),scene_source_state);''')
    edit(dx,'''                if (native_stereo_packet == nullptr || m_scene_capture_tex.texture.Get() == nullptr) {
                    m_openvr.copy_right(backbuffer.Get(), scene_source_state);''',
    '''                if (duo_scene) {
                    // Both current-frame copies were enqueued before either Submit.
                } else if (vr->is_using_mono() && !vr->is_using_duoview_mono()) {
                    // True single-view Joey Mono has one engine view in the
                    // first half; duplicate that half, not the empty right.
                    m_openvr.copy_left_to_right(backbuffer.Get(),scene_source_state);
                } else if (native_stereo_packet == nullptr || m_scene_capture_tex.texture.Get() == nullptr) {
                    m_openvr.copy_right(backbuffer.Get(), scene_source_state);''')
    # Mark a DuoView frame as successfully presented only after BOTH SteamVR
    # Submit calls succeeded. A successful GPU record is insufficient and
    # must not zero the fault streak before the headset submission.
    edit(dx,'''                auto e = vr::VRCompositor()->Submit(vr::Eye_Left, &left_eye, &left_bounds, vr::EVRSubmitFlags::Submit_TextureWithPose);
                record_native_submit(frame_diag::Runtime::openvr, frame_diag::Stage::submit_result, static_cast<int32_t>(e), 0);''',
    '''                auto e = vr::VRCompositor()->Submit(vr::Eye_Left, &left_eye, &left_bounds, vr::EVRSubmitFlags::Submit_TextureWithPose);
                duo_left_submit_ok=(e==vr::VRCompositorError_None);
                record_native_submit(frame_diag::Runtime::openvr, frame_diag::Stage::submit_result, static_cast<int32_t>(e), 0);''')
    edit(dx,'''            if (e != vr::VRCompositorError_None) {
                spdlog::error("[VR] VRCompositor failed to submit right eye: {}", (int)e);
                return e;
            } else {
                vr->m_submitted = true;
            }''',
    '''            if (e != vr::VRCompositorError_None) {
                if (duo_scene) vr->duoview_abort("OpenVR right-eye Submit failed");
                spdlog::error("[VR] VRCompositor failed to submit right eye: {}", (int)e);
                return e;
            } else {
                if (duo_scene) {
                    if (duo_left_submit_ok) vr->duoview_frame_success();
                    else vr->duoview_abort("OpenVR left-eye Submit failed");
                }
                vr->m_submitted = true;
            }''')
    # Copy reference modules into exact checked-out Joey tree. No private SDK
    # declarations or altered SDK files.
    for name in ("DuoViewGeometry.hpp","DuoViewGaze.hpp","DuoViewPSVR2Gaze.hpp","DuoViewCropStability.hpp","DuoViewFrame.hpp",
                 "DuoViewBootstrap.hpp",
                 "DuoViewConfig.hpp","DuoViewState.hpp","DuoViewCommandRecovery.hpp","DuoViewD3D12.hpp",
                 "DuoViewMonoCopyD3D12.hpp"):
        target=root/"src/mods/vr"/name
        if target.exists(): raise RuntimeError("Refusing to overwrite prior source: "+str(target))
        text=(src/name).read_text(encoding="utf-8")
        if name=="DuoViewConfig.hpp":
            text=replace(text,
                '        cached_.reset();\n    }',
                '        cached_.reset();\n        last_key_ = {};\n    }',name)
        if name=="DuoViewD3D12.hpp":
            # No timestamp work by default; note that initial PSO creation still
            # needs prewarming before a production release.
            pass
        target.write_text(text,encoding="utf-8",newline="")
    # A reproducible Windows CI build compiles HLSL to DXBC, preventing D3DCompile
    # and its potentially long shader-compiler stall during live XR submission.
    if not a.source_only:
        subprocess.run([sys.executable, str(src/"embed_shader.py"),
            str(root/"src/mods/vr/DuoViewShaderSource.hpp")], check=True)
    for path,text in changed.items():
        (source_root(path)/path).write_text(text,encoding="utf-8",newline="")
    print("Applied fixed-center DuoView ID6 for STALKER2 DX12 OpenXR/OpenVR; 60-startup/4-steady failed ticks -> Joey Mono ID5 only (experimental).")
    if a.source_only:
        print("SOURCE REVIEW ONLY: shader header absent; no compilation or full source verification performed.")

if __name__=="__main__":
    main()
