#!/usr/bin/env python3
"""Apply bounded fixed-center two-view integration after verified Stage 1.
Original Joey modes 0/5 are protected. STALKER 2 DX12 OpenXR mode 6 only.
An incomplete pair quarantines the renderer inside mode 6; a single fault
frame may contain incomplete atlas pixels, then later frames use Joey Mono.
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
    header="src/mods/VR.hpp"
    edit(header,'#include "vr/RenderingMethodSetting.hpp"',
        '#include "vr/RenderingMethodSetting.hpp"\n#include "vr/DuoViewState.hpp"\n#include "vr/DuoViewPSVR2Gaze.hpp"')
    edit(header,'    bool is_using_duoview_mono() const { return m_rendering_method->value() == RenderingMethod::DUOVIEW_MONO; }',
        '''    bool is_using_duoview_mono() const { return m_rendering_method->value() == RenderingMethod::DUOVIEW_MONO; }
    bool is_duoview_renderer_active() const;
    uevr::duoview::State& duoview_state() { return m_duoview; }
    uevr::duoview::FrameKey duoview_key(uint32_t frame) const {
        return {mono_generation(), static_cast<uint64_t>(frame) + 1u};
    }
    uevr::duoview::FrameKey duoview_producer_key() const {
        // Draw prepares the NEXT UE engine frame; BeginRenderViewFamily
        // subsequently publishes that frame number as internal_frame_count.
        return duoview_key(get_runtime()->internal_frame_count + 1u);
    }
    bool duoview_gaze_active() const { return m_duoview_gaze.active(); }
    void configure_duoview();
    void note_duoview_gpu_ms(float ms) { m_duo_gpu_ms.store(ms, std::memory_order_relaxed); }
    std::optional<uevr::duoview::ViewFrame> duoview_begin_frame();
    void duoview_abort(const char* reason);''')
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
    uevr::duoview::psvr2::Reader m_duoview_gaze;
    std::atomic<bool> m_duoview_autostart_done{false};
    std::once_flag m_duoview_settings_once;
    std::atomic<const char*> m_mono_status{"Not selected"};''')
    edit(header,'    void on_device_reset() override {\n        get_runtime()->on_device_reset();',
        '    void on_device_reset() override {\n        m_duoview.retire();\n        get_runtime()->on_device_reset();')
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
    # Original Joey Mono is OpenXR-only; keep ID5 unchanged. Only validated
    # DuoView ID6 may use OpenVR's existing per-eye DX12 submission path.
    edit(cpp,
        '        .openxr = runtime != nullptr && runtime->is_openxr(),',
        '        .openxr = runtime != nullptr && (runtime->is_openxr() ||\n            (runtime->is_openvr() && (is_using_duoview_mono() ||\n             requested_rendering_method() == RenderingMethod::DUOVIEW_MONO))),')
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
                    ImGui::Text("View histories: %s; primary shading constructor: %s",
                        snap->scene_states[0] && snap->scene_states[1]
                            ? (snap->scene_states[0]!=snap->scene_states[1] ? "separate" : "shared") : "unobserved",
                        snap->shading_applied ? "applied" :
                            (snap->config.settings.independent_shading ? "requested / waiting for safe pair" : "OFF"));
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
    # Request fixed-center DuoView exactly once after OpenXR is loaded and
    # before the game's first eligible viewport transaction. Any subsequent
    # user mode selection is never overwritten during this injection.
    edit(cpp,
        'void VR::on_pre_engine_tick(sdk::UGameEngine* engine, float delta) {\n    service_mono_transition_game_thread();',
        '''void VR::on_pre_engine_tick(sdk::UGameEngine* engine, float delta) {
    if (!m_duoview_autostart_done.load(std::memory_order_acquire) && m_is_d3d12) {
        const auto runtime=get_runtime();
        if (runtime && (runtime->is_openxr() || runtime->is_openvr()) && runtime->loaded) {
            const auto path=utility::get_module_pathw(utility::get_executable());
            if (path && uevr::stalker2_native::is_executable(*path)) {
                m_duoview_autostart_done.store(true,std::memory_order_release);
                if (requested_rendering_method()!=RenderingMethod::DUOVIEW_MONO) {
                    m_rendering_method->request(RenderingMethod::DUOVIEW_MONO);
                    SPDLOG_INFO("[DuoView] Auto-requested mode 6 for STALKER 2; later manual selections honored");
                }
            }
        }
    }
    service_mono_transition_game_thread();''')
    edit(cpp,'    m_mono_main_view_token = 0;\n    m_mono_attachment_token = 0;',
        '    m_duoview.retire();\n    m_duo_shading->value()=false;\n    configure_duoview();\n    m_mono_main_view_token = 0;\n    m_mono_attachment_token = 0;')
    changed[cpp]+='''
// Update the immutable state from persisted controls only on changes.
void VR::configure_duoview() {
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

// Stage 5: sample native PSVR2 gaze ONCE per immutable source frame.
 // CAPI unavailable or invalid => fixed center. Never adjust mid-frame.
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
    if (!is_using_duoview_mono()) return;
    SPDLOG_WARNING_EVERY_N_SEC(2, "[DuoView] Two-view source unavailable; mode6 retained and no Mono fallback: {}", reason);
    set_mono_status("DuoView frame not ready: mode 6 retained; automatic Mono fallback prohibited");
}
'''
    hook="src/mods/vr/FFakeStereoRenderingHook.cpp"
    edit(hook,'#include "FFakeStereoRenderingHook.hpp"',
        '#include "FFakeStereoRenderingHook.hpp"\n#include "DuoViewGeometry.hpp"')
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
              (vr->is_duoview_renderer_active() ? (views_ptr->count == 1 || views_ptr->count == 2) : views_ptr->count == 1)));
        if (vr->is_duoview_renderer_active() && views_ptr) {
            vr->duoview_state().family(vr->duoview_key(frame_count), main_family, views_ptr->count);
        }''')
    edit(hook, '    std::optional<uint32_t> views_original_count{};',
    '''    std::optional<uint32_t> views_original_count{};
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
            // Both original values are restored by Joey's established guards.
            if (index==1 && views->count==1 &&
                is_readable_process_range(state,sizeof(uintptr_t)) &&
                vr->duoview_state().can_native_fix_secondary_source(key,state)) {
                set_effective_stereo_pass(EStereoscopicPass::eSSP_PRIMARY);
                applied=get_effective_stereo_pass()==EStereoscopicPass::eSSP_PRIMARY;
                if (applied) {
                    views_original_count=views->count;
                    views->count=0;
                    restore_init_options_after_constructor=true;
                    SPDLOG_INFO_ONCE("[DuoView] Native Fix source construction: temporary PRIMARY pass + hidden family singleton");
                }
            }
            vr->duoview_state().scene(key,index,state,applied);
        }
    }''')
    # Engine construction observes camera/rect/projection; a complete pair is
    # required before composition, not before we let the engine build its views.
    dxh="src/mods/vr/D3D12Component.hpp"
    edit(dxh,'#include "d3d12/TextureContext.hpp"',
        '#include "d3d12/TextureContext.hpp"\n#include "DuoViewD3D12.hpp"')
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
            if (duo_desc.Width==0 || duo_desc.Width>32768 ||
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
                backbuffer_desc.Height,false,frequency)) {
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
    '''                    if (vr->is_duoview_renderer_active()) {
                        bool recorded = false;
                        bool duo_recorded = false;
                        const auto frame = vr->duoview_state().consume(
                            vr->duoview_key(static_cast<uint32_t>(frame_count)));
                        vr->m_openxr->note_mono_copy(static_cast<uint32_t>(frame_count), false);
                        // No native Mono copy, stale source, or internal mode
                        // quarantine is permitted. Missing paired evidence
                        // suppresses the scene copy for this frame; next frame
                        // keeps trying DuoView ID6 with current camera/projection.
                        if (!frame) {
                            vr->duoview_abort("current-frame paired Unreal views unavailable");
                        } else {
                            const bool submitted = m_openxr.copy(
                                (uint32_t)runtimes::OpenXR::SwapchainIndex::DOUBLE_WIDE, nullptr,
                                [this, source=backbuffer, scene_source_state, device, frame,
                                 &recorded, &duo_recorded](
                                    d3d12::CommandContext& commands, ID3D12Resource* destination) {
                                    if (!commands.ready()) return;
                                    auto& item = m_openxr.duoview_compositors[&commands];
                                    if (!item) item = std::make_unique<uevr::duoview::dx12::Compositor>();
                                    duo_recorded = item->record(device, commands.cmd_list.Get(),
                                        source.Get(), destination, scene_source_state, frame->config,
                                        frame->config.settings.gpu_timing ? item->timing_frequency() : 0);
                                    if (frame->config.settings.gpu_timing)
                                        VR::get()->note_duoview_gpu_ms(item->gpu_milliseconds());
                                    if (item->recorded_commands()) commands.has_commands = true;
                                    recorded=duo_recorded;
                                }, std::nullopt, scene_source_state, nullptr,
                                std::nullopt, backbuffer.Get());
                            vr->m_openxr->note_mono_copy(static_cast<uint32_t>(frame_count), submitted && recorded);
                            if (!submitted || !recorded)
                                vr->duoview_abort("DX12 composite/copy unavailable; keeping DuoView active");
                        }
                    } else if (vr->is_using_mono()) {
                        bool recorded = false;''')
    # OpenVR source-pair composition: reuse the same validated compositor
    # and current-frame pair key, but submit through SteamVR's existing two
    # 6DoF pose-aware per-eye textures instead of OpenXR swapchains.
    edit(dx,'''            auto openvr = vr->get_runtime<runtimes::OpenVR>();
            const auto submit_pose = openvr->get_pose_for_submit();

            if (!is_afr) {
                m_openvr.copy_left(backbuffer.Get(), scene_source_state);''',
    '''            auto openvr = vr->get_runtime<runtimes::OpenVR>();
            const auto submit_pose = openvr->get_pose_for_submit();
            Microsoft::WRL::ComPtr<ID3D12Resource> duo_scene{};
            if (vr->is_duoview_renderer_active()) {
                auto frame=vr->duoview_state().consume(
                    vr->duoview_key(static_cast<uint32_t>(frame_count)));
                auto& context=m_openvr.duoview_commands;
                if (frame && m_openvr.duoview_output &&
                    m_openvr.duoview_compositor && context.ready()) {
                    context.wait(INFINITE);
                    if (m_openvr.duoview_compositor->record(device,
                        context.cmd_list.Get(),backbuffer.Get(),
                        m_openvr.duoview_output.Get(),scene_source_state,frame->config)) {
                        if (m_openvr.duoview_compositor->recorded_commands())
                            context.has_commands=true;
                        context.execute();
                        duo_scene=m_openvr.duoview_output;
                    }
                }
                if (!duo_scene) {
                    vr->duoview_abort("OpenVR paired-source composition unavailable");
                    // Do not substitute native stereo or original Mono.
                    runtime->frame_synced=false;
                    return vr::VRCompositorError_None;
                }
            }

            if (!is_afr) {
                m_openvr.copy_left(duo_scene ? duo_scene.Get() : backbuffer.Get(),
                    duo_scene ? D3D12_RESOURCE_STATE_RENDER_TARGET : scene_source_state);''')
    edit(dx,'''                if (native_stereo_packet == nullptr || m_scene_capture_tex.texture.Get() == nullptr) {
                    m_openvr.copy_right(backbuffer.Get(), scene_source_state);''',
    '''                if (duo_scene) {
                    m_openvr.copy_right(duo_scene.Get(),D3D12_RESOURCE_STATE_RENDER_TARGET);
                } else if (native_stereo_packet == nullptr || m_scene_capture_tex.texture.Get() == nullptr) {
                    m_openvr.copy_right(backbuffer.Get(), scene_source_state);''')
    # Copy reference modules into exact checked-out Joey tree. No private SDK
    # declarations or altered SDK files.
    for name in ("DuoViewGeometry.hpp","DuoViewGaze.hpp","DuoViewPSVR2Gaze.hpp","DuoViewCropStability.hpp","DuoViewFrame.hpp",
                 "DuoViewConfig.hpp","DuoViewState.hpp","DuoViewD3D12.hpp",
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
    subprocess.run([sys.executable, str(src/"embed_shader.py"),
        str(root/"src/mods/vr/DuoViewShaderSource.hpp")], check=True)
    for path,text in changed.items():
        (source_root(path)/path).write_text(text,encoding="utf-8",newline="")
    print("Applied fixed-center v22 source, guarded Native Fix constructor parity, strict no-Mono fallback (experimental).")

if __name__=="__main__":
    main()
