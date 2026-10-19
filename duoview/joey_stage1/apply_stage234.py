#!/usr/bin/env python3
"""Apply DuoView through the original Native Stereo Fix producer pipeline.
Original Joey modes 0/5 are protected. STALKER 2 DX12 OpenXR mode 6 only.
Native Stereo Fix is forced on for ID6. Validated primary and secondary sources
are sampled directly when compatible; the per-slot atlas remains a format fallback.
An opt-in A/B control enables one direct raster draw on matching double-wide XR
targets; the default retains intermediate composition and copy.
Missing warmup packets leave the OpenXR transition loop live; actual compositor
faults return to original Joey Mono on the next frame. All source anchors match.
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
        'DuoView Mono (Eye Tracked - Experimental)')
    edit("UEVR/RenderingModeOptions.cs",
        'DuoView Mono (Stage 1 - safe Mono fallback)',
        'DuoView Mono (Eye Tracked - Experimental)')
    edit("tests/RenderingModes/Program.cs",
        'DuoView Mono (Stage 1 - safe Mono fallback)',
        'DuoView Mono (Eye Tracked - Experimental)')
    header="src/mods/VR.hpp"
    edit(header,'#include "vr/RenderingMethodSetting.hpp"',
        '#include "vr/RenderingMethodSetting.hpp"\n#include "vr/DuoViewState.hpp"\n#include "vr/DuoViewPSVR2Gaze.hpp"')
    edit(header,'''        if (should_ignore_native_stereo_fix_for_avowed_sync()) {
            return false;
        }

        return m_native_stereo_fix->value() &&''',
    '''        if (should_ignore_native_stereo_fix_for_avowed_sync()) {
            return false;
        }
        if (is_duoview_renderer_active()) { return true; }

        return m_native_stereo_fix->value() &&''')
    # Always retain the validated Native two-source capture. OFF changes only
    # Unreal's secondary constructor label (stock lighting) for comparison.
    edit(header,'''    bool is_native_stereo_fix_same_pass_enabled() const {
        if (should_force_native_stereo_fix_same_pass()) {''',
    '''    bool is_native_stereo_fix_same_pass_enabled() const {
        if (is_duoview_renderer_active()) return m_duoview.settings().native_fix_same_pass;
        if (should_force_native_stereo_fix_same_pass()) {''')
    edit(header,'''    bool is_native_stereo_fix_preserve_secondary_pass_enabled() const {
        return m_native_stereo_fix_preserve_secondary_pass->value();''',
    '''    bool is_native_stereo_fix_preserve_secondary_pass_enabled() const {
        if (is_duoview_renderer_active() && !m_duoview.settings().native_fix_same_pass) return true;
        return m_native_stereo_fix_preserve_secondary_pass->value();''')
    edit(header,'    bool is_using_duoview_mono() const { return m_rendering_method->value() == RenderingMethod::DUOVIEW_MONO; }',
        '''    bool is_using_duoview_mono() const { return m_rendering_method->value() == RenderingMethod::DUOVIEW_MONO; }
    bool is_duoview_renderer_active() const;
    uevr::duoview::State& duoview_state() { return m_duoview; }
    void duoview_start_draw() {
        m_duoview_draw_serial.fetch_add(1, std::memory_order_acq_rel);
        m_duoview_candidate_key.store(nullptr, std::memory_order_release);
        m_duoview_frozen_key.store(nullptr, std::memory_order_release);
    }
    uevr::duoview::FrameKey duoview_key() const {
        return {mono_generation(), m_duoview_draw_serial.load(std::memory_order_acquire)};
    }
    uevr::duoview::FrameKey duoview_producer_key() const {
        if (m_fake_stereo_hook && m_fake_stereo_hook->is_in_viewport_client_draw()) {
            const auto candidate = m_duoview_candidate_key.load(std::memory_order_acquire);
            if (candidate && candidate->generation == mono_generation()) return *candidate;
        }
        const auto frozen = m_duoview_frozen_key.load(std::memory_order_acquire);
        if (frozen && frozen->generation == mono_generation()) return *frozen;
        const auto candidate = m_duoview_candidate_key.load(std::memory_order_acquire);
        if (candidate && candidate->generation == mono_generation()) return *candidate;
        return duoview_key();
    }
    bool duoview_note_main_family(uint32_t, bool main, uint32_t count) {
        const auto candidate = m_duoview_candidate_key.load(std::memory_order_acquire);
        if (!candidate || candidate->generation != mono_generation() ||
            !m_duoview.family(*candidate, main, count)) return false;
        const auto frame = m_duoview.snapshot(*candidate);
        if (!frame || !frame->mono_source_frame || !get_openxr_runtime() ||
            !get_openxr_runtime()->has_mono_pose(*frame->mono_source_frame)) return false;
        m_duoview_frozen_key.store(candidate, std::memory_order_release);
        return true;
    }
    std::optional<uint32_t> duoview_mono_source_frame() const {
        const auto frame = m_duoview.snapshot(duoview_producer_key());
        return frame ? frame->mono_source_frame : std::optional<uint32_t>{};
    }
    bool duoview_gaze_active() const { return m_duoview.settings().eye_tracked && m_duoview_gaze.active(); }
    void configure_duoview();
    void note_duoview_gpu_ms(float ms) { m_duo_gpu_ms.store(ms, std::memory_order_relaxed); }
    void note_duoview_output_path(bool direct_xr) {
        m_duoview_output_path.store(direct_xr ? 1 : 0, std::memory_order_relaxed);
    }
    void note_duoview_source_extents(uint64_t packed) {
        m_duoview_source_extents.store(packed,std::memory_order_relaxed);
    }
    std::optional<uevr::duoview::ViewFrame> duoview_begin_frame();
    void duoview_abort(const char* reason);''')
    edit(header,'    std::atomic<const char*> m_mono_status{"Not selected"};',
        '''    // Legacy-style persistent options; never sampled by the XR compositor.
    std::atomic<uint32_t> m_duo_ui_rejected_mask{0};
    const ModSlider::Ptr m_duo_width{ModSlider::create(generate_name("DuoViewCropWidth"), .10f, 1.f, .50f)};
    const ModSlider::Ptr m_duo_height{ModSlider::create(generate_name("DuoViewCropHeight"), .10f, 1.f, .50f)};
    const ModSlider::Ptr m_duo_periphery{ModSlider::create(generate_name("DuoViewPeripheralScale"), .05f, .50f, .20f)};
    const ModSlider::Ptr m_duo_density{ModSlider::create(generate_name("DuoViewFovealDensity"), .25f, 4.0f, 1.f)};
    const ModSlider::Ptr m_duo_feather{ModSlider::create(generate_name("DuoViewFeather"), 0.f, .45f, .08f)};
    const ModToggle::Ptr m_duo_gaze{ModToggle::create(generate_name("DuoViewEyeTracking"), true)};
    const ModToggle::Ptr m_duo_border{ModToggle::create(generate_name("DuoViewDebugBorder"), false)};
    const ModInt32::Ptr m_duo_debug_source{ModSliderInt32::create(generate_name("DuoViewDebugSource"), 0, 2, 0)};
    const ModInt32::Ptr m_duo_fovea_view{ModSliderInt32::create(generate_name("DuoViewFoveaSourceView"), 0, 1, 0)};
    const ModToggle::Ptr m_duo_stabilize{ModToggle::create(generate_name("DuoViewCropStability"), true)};
    const ModSlider::Ptr m_duo_guard{ModSlider::create(generate_name("DuoViewCropGuard"), 0.f, .05f, .05f)};
    const ModToggle::Ptr m_duo_shading{ModToggle::create(generate_name("DuoViewIndependentShading"), false)};
    const ModToggle::Ptr m_duo_native_fix{ModToggle::create(generate_name("DuoViewNativeFixSamePass"), true)};
    const ModInt32::Ptr m_duo_quant{ModSliderInt32::create(generate_name("DuoViewQuantizationPixels"), 0, 16, 2)};
    const ModInt32::Ptr m_duo_hold{ModSliderInt32::create(generate_name("DuoViewGazeHoldMs"), 50, 2000, 350)};
    const ModInt32::Ptr m_duo_reacquire{ModSliderInt32::create(generate_name("DuoViewGazeReacquireSamples"), 1, 4, 2)};
    const ModSlider::Ptr m_duo_offset_x{ModSlider::create(generate_name("DuoViewGazeOffsetX"), -.25f, .25f, 0.f)};
    const ModSlider::Ptr m_duo_offset_y{ModSlider::create(generate_name("DuoViewGazeOffsetY"), -.25f, .25f, 0.f)};
    // Nonlinear response: stillness lock / instantaneous full-speed saccade.
    const ModSlider::Ptr m_duo_micro_gain{ModSlider::create(generate_name("DuoViewGazeMicroGain"), 0.f, 1.f, 0.f)};
    const ModSlider::Ptr m_duo_breakout{ModSlider::create(generate_name("DuoViewGazeBreakout"), .005f, .25f, .035f)};
    const ModSlider::Ptr m_duo_stillness{ModSlider::create(generate_name("DuoViewGazeStillness"), 0.f, .05f, .008f)};
    const ModInt32::Ptr m_duo_relock{ModSliderInt32::create(generate_name("DuoViewGazeRelockSamples"), 1, 10, 3)};
    const ModToggle::Ptr m_duo_direct_xr{ModToggle::create(generate_name("DuoViewDirectXROutput"), false)};
    const ModToggle::Ptr m_duo_timing{ModToggle::create(generate_name("DuoViewGpuTiming"), false)};
    std::atomic<float> m_duo_gpu_ms{-1.f};
    std::atomic<int32_t> m_duoview_output_path{-1};
    std::atomic<uint64_t> m_duoview_source_extents{0};
    uevr::duoview::State m_duoview;
    std::atomic<uint64_t> m_duoview_draw_serial{};
    std::atomic<std::shared_ptr<const uevr::duoview::FrameKey>> m_duoview_candidate_key{};
    std::atomic<std::shared_ptr<const uevr::duoview::FrameKey>> m_duoview_frozen_key{};
    uevr::duoview::psvr2::Reader m_duoview_gaze;
    std::atomic<bool> m_duoview_quarantined{false};
    std::once_flag m_duoview_settings_once;
    std::atomic<const char*> m_mono_status{"Not selected"};''')
    edit(header,'    void on_device_reset() override {\n        get_runtime()->on_device_reset();',
        '    void on_device_reset() override {\n        m_duoview.retire();\n        get_runtime()->on_device_reset();')
    edit(header,'        m_options = {',
        '''        m_options = {
            *m_duo_width, *m_duo_height, *m_duo_periphery, *m_duo_density,
            *m_duo_feather, *m_duo_gaze, *m_duo_border, *m_duo_debug_source,
            *m_duo_fovea_view, *m_duo_timing, *m_duo_direct_xr, *m_duo_stabilize, *m_duo_guard,
            *m_duo_native_fix, *m_duo_quant, *m_duo_hold, *m_duo_reacquire,
            *m_duo_offset_x, *m_duo_offset_y,
            *m_duo_micro_gain, *m_duo_breakout, *m_duo_stillness, *m_duo_relock,''')
    cpp="src/mods/VR.cpp"
    edit(cpp,'''bool VR::should_force_native_stereo_fix_same_pass() const {
    if (is_using_mono()) { return false; }
    if (!m_native_stereo_fix->value() || is_using_afr() || !stalker2_native_fix_requires_same_pass_cached()) {''',
    '''bool VR::should_force_native_stereo_fix_same_pass() const {
    if (is_duoview_renderer_active()) {
        if (!m_duoview.settings().native_fix_same_pass ||
            is_using_afr() || !stalker2_native_fix_requires_same_pass_cached()) { return false; }
        SPDLOG_INFO_ONCE("[DuoView][NativeStereoFix] Preserving the validated same-pass STALKER 2 layout");
        return true;
    }
    if (is_using_mono()) { return false; }
    if (!m_native_stereo_fix->value() || is_using_afr() || !stalker2_native_fix_requires_same_pass_cached()) {''')
    edit(cpp,'''bool VR::is_stalker2_native_fix_experiment_enabled() const {
    if (!m_stalker2_native_pair_experiment->value() || !is_native_stereo_fix_enabled() ||''',
    '''bool VR::is_stalker2_native_fix_experiment_enabled() const {
    if (is_duoview_renderer_active()) { return false; }
    if (!m_stalker2_native_pair_experiment->value() || !is_native_stereo_fix_enabled() ||''')
    edit(cpp,
        'ImGui::TextWrapped("DuoView Stage 1: rendering uses original Joey Mono unchanged. Two-view foveation and gaze are NOT active.");',
        'ImGui::TextWrapped(is_duoview_renderer_active() ? (duoview_gaze_active() ? "DuoView ID6: eye-tracked two-view Mono (PSVR2 Toolkit active)" : "DuoView ID6: held crop / center fallback (gaze unavailable)") : "DuoView ID6: original Joey Mono fallback / DuoView inactive");')
    edit(cpp, '#include "VR.hpp"', '#include "VR.hpp"\n#include <cstring>')
    edit(cpp,'            ImGui::TextWrapped("Mono (Experimental): one centered, head-tracked scene for both eyes; no binocular scene depth. DX11/DX12 with OpenXR. Native Fix, Ghost Fix/bootstrap and depth submission are inactive in Mono; saved preferences are retained.");',
        '            if (!is_using_duoview_mono()) ImGui::TextWrapped("Mono (Experimental): one centered, head-tracked scene for both eyes; no binocular scene depth. DX11/DX12 with OpenXR. Native Fix, Ghost Fix/bootstrap and depth submission are inactive in Mono; saved preferences are retained.");')
    edit(cpp,'        if (rendering_method_changed && !is_mono_transition_pending() && get_runtime() != nullptr) {',
    '''        if (is_using_duoview_mono() || requested_rendering_method() == RenderingMethod::DUOVIEW_MONO) {
            if (ImGui::TreeNode("DuoView Mono — quality and diagnostics")) {
                ImGui::TextWrapped("Settings are frozen once per new UE frame. The original Joey Mono ID5 is untouched.");
                if (ImGui::Button("Restore old DuoView settings")) {
                    m_duo_width->value()=.50f; m_duo_height->value()=.50f;
                    m_duo_periphery->value()=.20f; m_duo_density->value()=1.f;
                    m_duo_feather->value()=.08f; m_duo_gaze->value()=true;
                    m_duo_border->value()=false; m_duo_fovea_view->value()=0;
                    m_duo_debug_source->value()=0;
                    m_duo_direct_xr->value()=false;
                    m_duo_native_fix->value()=true; m_duo_quant->value()=2;
                    m_duo_hold->value()=350; m_duo_reacquire->value()=2;
                    m_duo_offset_x->value()=0.f; m_duo_offset_y->value()=0.f;
                    m_duo_micro_gain->value()=0.f; m_duo_breakout->value()=.035f;
                    m_duo_stillness->value()=.008f; m_duo_relock->value()=3;
                }
                m_duo_width->draw("Fovea width / full FOV");
                m_duo_height->draw("Fovea height / full FOV");
                m_duo_periphery->draw("Peripheral resolution scale");
                m_duo_density->draw("Foveal pixel density");
                m_duo_feather->draw("Blend feather width");
                m_duo_gaze->draw("Eye tracking");
                m_duo_border->draw("Blend border highlight");
                m_duo_debug_source->draw("Source diagnostic: 0 Blend / 1 Periphery / 2 Fovea");
                m_duo_fovea_view->draw("Fovea UE source view (0 or 1)");
                m_duo_stabilize->draw("Stable gaze crop (OpenNR r10 policy)");
                if (m_duo_stabilize->value()) m_duo_guard->draw("Crop centre guard (fraction of crop)");
                m_duo_native_fix->draw("Native Stereo Fix shading (OFF = stock secondary-pass)");
                ImGui::TextWrapped("Both choices keep Joey's proven two-texture DuoView capture. ON relabels the UE secondary pass as PRIMARY (Build 149). OFF preserves its stock SECONDARY label for a hybrid native-fix capture + stock-style lighting. Compare Lumen visually; this does not disable the underlying two-target capture.");
                m_duo_quant->draw("Gaze quantization (0=off, 1-16 fovea pixels)");
                m_duo_hold->draw("Blink / tracking-loss ray hold (milliseconds)");
                m_duo_reacquire->draw("Consistent samples after large post-blink jump (1=instant)");
                m_duo_offset_x->draw("Fovea horizontal offset (also in fixed mode)");
                m_duo_offset_y->draw("Fovea vertical / height offset (also in fixed mode)");
                ImGui::TextWrapped("Adaptive response: small gaze movement holds or follows slowly; large movement jumps 1:1 and follows at full speed; then automatically locks when steady. No heavy temporal smoothing.");
                m_duo_micro_gain->draw("Small gaze movement gain (0=locked; 1=full)");
                m_duo_breakout->draw("Fast 1:1 breakout (fraction of full view)");
                m_duo_stillness->draw("Stillness threshold per gaze sample (fraction of view)");
                m_duo_relock->draw("Quiet samples before fovea relocks");
                if (m_duo_stillness->value() >= m_duo_breakout->value())
                    ImGui::TextWrapped("Stillness must be below breakout; the conflicting setting is rejected, all other controls keep working.");
                ImGui::Text("DuoView delivery: %llu copied / %llu held / %llu empty or failed",
                    static_cast<unsigned long long>(m_openxr->duoview_copy_submits.load()),
                    static_cast<unsigned long long>(m_openxr->duoview_hold_submits.load()),
                    static_cast<unsigned long long>(m_openxr->duoview_empty_submits.load()));
                if (ImGui::Button("Reset DuoView delivery counters")) {
                    m_openxr->duoview_copy_submits=0; m_openxr->duoview_hold_submits=0;
                    m_openxr->duoview_empty_submits=0;
                }
                m_duo_direct_xr->draw("Direct XR output (experimental A/B)");
                ImGui::TextWrapped("OFF composes once and copies to both eyes. ON blends both eye halves directly when formats match. Compare GPU timing in the same scene; either route may be faster.");
                m_duo_timing->draw("GPU timing: DuoView raster/output (excludes UE and source gather)");
                if (m_duo_timing->value()) {
                    const float ms=m_duo_gpu_ms.load(std::memory_order_relaxed);
                    if (ms >= 0.f) ImGui::Text("DuoView raster/output: %.3f ms GPU (last retired slot; excludes UE and source gather)", ms);
                    else ImGui::TextUnformatted("GPU timing: waiting for a completed command slot");
                }
                const auto output_path=m_duoview_output_path.load(std::memory_order_relaxed);
                if (output_path < 0) ImGui::TextUnformatted("XR output path: waiting for a submitted DuoView frame");
                else ImGui::Text("Last submitted XR output path: %s",
                    output_path ? "direct double-wide raster" : "composite and copy compatibility route");
                const auto source_extents=m_duoview_source_extents.load(std::memory_order_relaxed);
                const auto primary_width=static_cast<uint32_t>((source_extents>>48)&0xffffu);
                const auto primary_height=static_cast<uint32_t>((source_extents>>32)&0xffffu);
                const auto secondary_width=static_cast<uint32_t>((source_extents>>16)&0xffffu);
                const auto secondary_height=static_cast<uint32_t>(source_extents&0xffffu);
                if (primary_width && primary_height && secondary_width && secondary_height)
                    ImGui::Text("Native source allocations: primary %ux%u, secondary %ux%u",
                        primary_width,primary_height,secondary_width,secondary_height);
                ImGui::TextWrapped("These are Native color-resource allocations. They do not prove the depth, G-buffer, Lumen, or other UE pass extents; measure those with a GPU capture.");
                const auto counts=m_duoview_gaze.counters();
                ImGui::Text("PSVR2 gaze: fresh=%llu held=%llu invalid=%llu expired=%llu unavailable=%llu",
                    static_cast<unsigned long long>(counts.fresh),
                    static_cast<unsigned long long>(counts.reused),
                    static_cast<unsigned long long>(counts.invalid),
                    static_cast<unsigned long long>(counts.expired),
                    static_cast<unsigned long long>(counts.unavailable));
                if (counts.age_ms == UINT32_MAX) ImGui::TextUnformatted("Last gaze sample: unavailable");
                else ImGui::Text("Last gaze sample: %u ms", counts.age_ms);
                configure_duoview();
                const auto rejected=m_duo_ui_rejected_mask.load(std::memory_order_acquire);
                if (rejected) {
                    ImGui::TextWrapped("Control warning: one or more requested sliders are invalid; "
                        "only those individual settings are rejected. All valid changes remain active.");
                    const struct { uint32_t mask; const char* label; } conflicts[]={
                        {uevr::duoview::reject_width,"Fovea width"},
                        {uevr::duoview::reject_height,"Fovea height"},
                        {uevr::duoview::reject_periphery,"Peripheral scale"},
                        {uevr::duoview::reject_density,"Foveal density"},
                        {uevr::duoview::reject_feather,"Feather"},
                        {uevr::duoview::reject_fovea_view,"Fovea source view"},
                        {uevr::duoview::reject_diagnostic,"Source diagnostic"},
                        {uevr::duoview::reject_guard,"Crop guard"},
                        {uevr::duoview::reject_quant,"Quantization"},
                        {uevr::duoview::reject_hold,"Blink hold"},
                        {uevr::duoview::reject_reacquire,"Reacquisition"},
                        {uevr::duoview::reject_offset_u,"Horizontal offset"},
                        {uevr::duoview::reject_offset_v,"Vertical offset"},
                        {uevr::duoview::reject_micro,"Small movement gain"},
                        {uevr::duoview::reject_breakout,"Fast breakout"},
                        {uevr::duoview::reject_still,"Stillness threshold"},
                        {uevr::duoview::reject_relock,"Relock samples"}};
                    for (const auto& bad:conflicts) {
                        if (rejected & bad.mask) ImGui::BulletText("Not applied: %s",bad.label);
                    }
                } else ImGui::TextUnformatted("DuoView controls: validated and accepted for next render frame");
                const auto applied=m_duoview.settings();
                ImGui::Text("Active Fovea W/H: %.3f / %.3f, density %.3f, periphery %.3f",
                    applied.crop_width,applied.crop_height,applied.foveal_density,applied.peripheral_scale);
                ImGui::Text("Active Eye Tracking: %s, Native shading: %s, fixed offsets X/Y: %.3f / %.3f",
                    applied.eye_tracked ? "ON" : "OFF",
                    applied.native_fix_same_pass ? "ON" : "OFF",
                    applied.gaze_offset_u,applied.gaze_offset_v);
                if (const auto snap=m_duoview.snapshot(duoview_producer_key())) {
                    const auto& layout=snap->config.layout;
                    ImGui::Text("Fovea %ux%u; peripheral %ux%u; output %ux%u",
                        layout.fovea.width,layout.fovea.height,
                        layout.periphery.width,layout.periphery.height,
                        layout.atlas_width/2,layout.atlas_height);
                    ImGui::Text("Fovea UE%u; periphery UE%u; gaze %s",
                        snap->config.settings.fovea_view,1u-snap->config.settings.fovea_view,
                        snap->gaze_valid ? "tracking" : "held crop / center fallback");
                    ImGui::Text("View histories: %s; primary shading constructor: %s",
                        snap->scene_states[0] && snap->scene_states[1]
                            ? (snap->scene_states[0]!=snap->scene_states[1] ? "separate" : "shared") : "unobserved",
                        snap->shading_applied ? "applied" :
                            (snap->config.settings.independent_shading ? "requested / waiting for safe pair" : "OFF"));
                    ImGui::Text("Applied crop centre (%.3f, %.3f), scene pixels: %.2f million",
                        snap->config.gaze.u,snap->config.gaze.v,
                        uevr::duoview::rendered_pixels(layout)/1000000.);
                }
                // Active/applied values and precise per-field rejections appear
                // directly above; never claim the entire settings set is frozen.
                ImGui::TextWrapped("Diagnostic 1 isolates the full-FOV peripheral pass. Diagnostic 2 isolates the foveal pass (dark outside crop). Compare shadows/lighting in the same scene.");
                ImGui::TextWrapped("View 0 = FIRST Unreal pass (old prototype default), view 1 = SECOND pass (Build19 default). Identical frozen Mono camera. Switching may reset temporal history.");
                ImGui::TreePop();
            }
        }
        if (rendering_method_changed && !is_mono_transition_pending() && get_runtime() != nullptr) {''')
    edit(cpp,'    // Load camera offsets\n    load_cameras();',
        '    // Load camera offsets\n    load_cameras();\n    configure_duoview();')
    edit(cpp,'    m_mono_main_view_token = 0;\n    m_mono_attachment_token = 0;',
        '    m_duoview.retire();\n    m_duoview_candidate_key.store(nullptr, std::memory_order_release);\n    m_duoview_frozen_key.store(nullptr, std::memory_order_release);\n    m_duo_shading->value()=false;\n    configure_duoview();\n    if (selection.active() == RenderingMethod::DUOVIEW_MONO) m_duoview_quarantined.store(false, std::memory_order_release);\n    m_mono_main_view_token = 0;\n    m_mono_attachment_token = 0;')
    changed[cpp]+='''
// Update the immutable state from persisted controls only on changes.
void VR::configure_duoview() {
    // Validate ALL independent settings separately. Do not let one invalid
    // option veto any other valid controls. Latch the reconciled immutable
    // Settings atomically on the next UE frame; never alter native source size.
    const auto current = m_duoview.settings();
    uevr::duoview::Settings candidate{
        .crop_width=m_duo_width->value(), .crop_height=m_duo_height->value(),
        .peripheral_scale=m_duo_periphery->value(), .foveal_density=m_duo_density->value(),
        .feather_fraction=m_duo_feather->value(), .debug_border=m_duo_border->value(),
        .eye_tracked=m_duo_gaze->value(), .fovea_view=static_cast<uint32_t>(m_duo_fovea_view->value()),
        .diagnostic_view=static_cast<uint32_t>(m_duo_debug_source->value()),
        .gpu_timing=m_duo_timing->value(), .direct_xr_output=m_duo_direct_xr->value(), .stabilize_crop=m_duo_stabilize->value(),
        .guard_fraction=m_duo_guard->value(), .independent_shading=false,
        .native_fix_same_pass=m_duo_native_fix->value(),
        .gaze_quant_pixels=static_cast<uint32_t>(m_duo_quant->value()),
        .gaze_hold_ms=m_duo_hold->value(), .gaze_reacquire_samples=m_duo_reacquire->value(),
        .gaze_offset_u=m_duo_offset_x->value(), .gaze_offset_v=m_duo_offset_y->value(),
        .gaze_micro_gain=m_duo_micro_gain->value(),
        .gaze_breakout_radius=m_duo_breakout->value(),
        .gaze_still_radius=m_duo_stillness->value(),
        .gaze_relock_samples=static_cast<uint32_t>(m_duo_relock->value())};
    const auto checked=uevr::duoview::reconcile_ui_settings(candidate,current);
    candidate=checked.settings;
    m_duo_ui_rejected_mask.store(checked.rejected,std::memory_order_release);
    if (checked.rejected) {
        SPDLOG_WARNING_EVERY_N_SEC(5,
            "[DuoView][Controls] Rejected invalid UI fields mask=0x{:X}; "
            "other valid controls continue; active quality width={:.3f} height={:.3f} periphery={:.3f} density={:.3f}",
            checked.rejected,candidate.crop_width,candidate.crop_height,
            candidate.peripheral_scale,candidate.foveal_density);
    }
    if (current.crop_width==candidate.crop_width && current.crop_height==candidate.crop_height &&
        current.peripheral_scale==candidate.peripheral_scale && current.foveal_density==candidate.foveal_density &&
        current.feather_fraction==candidate.feather_fraction && current.debug_border==candidate.debug_border &&
        current.eye_tracked==candidate.eye_tracked && current.fovea_view==candidate.fovea_view &&
        current.diagnostic_view==candidate.diagnostic_view && current.gpu_timing==candidate.gpu_timing &&
        current.direct_xr_output==candidate.direct_xr_output &&
        current.stabilize_crop==candidate.stabilize_crop && current.guard_fraction==candidate.guard_fraction &&
        current.independent_shading==candidate.independent_shading &&
        current.native_fix_same_pass==candidate.native_fix_same_pass &&
        current.gaze_quant_pixels==candidate.gaze_quant_pixels &&
        current.gaze_hold_ms==candidate.gaze_hold_ms &&
        current.gaze_reacquire_samples==candidate.gaze_reacquire_samples &&
        current.gaze_offset_u==candidate.gaze_offset_u &&
        current.gaze_offset_v==candidate.gaze_offset_v &&
        current.gaze_micro_gain==candidate.gaze_micro_gain &&
        current.gaze_breakout_radius==candidate.gaze_breakout_radius &&
        current.gaze_still_radius==candidate.gaze_still_radius &&
        current.gaze_relock_samples==candidate.gaze_relock_samples) return;
    if (!m_duoview.configure(candidate))
        SPDLOG_WARNING_EVERY_N_SEC(2, "[DuoView][Controls] Internal validated settings rejected; retaining prior frame and reporting for diagnosis");
}

// Stage 5: sample native PSVR2 gaze ONCE per immutable source frame.
 // CAPI unavailable or invalid => fixed center. Never adjust mid-frame.
bool VR::is_duoview_renderer_active() const {
    if (!is_using_duoview_mono() || !m_is_d3d12 || m_duoview_quarantined.load(std::memory_order_acquire)) return false;
    const auto runtime = get_runtime();
    if (!runtime || !runtime->is_openxr()) return false;
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
    const auto runtime = get_runtime();
    if (const auto candidate=m_duoview_candidate_key.load(std::memory_order_acquire)) {
        if (candidate->generation==mono_generation()) {
            if (const auto found=m_duoview.snapshot(*candidate)) return found;
        }
    }
    const auto source_frame = runtime->internal_frame_count;
    if (!get_openxr_runtime() || !get_openxr_runtime()->has_mono_pose(source_frame)) {
        set_mono_status("Waiting: DuoView has no exact OpenXR Mono pose token yet");
        return {};
    }
    const auto key = duoview_key();
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
    const auto settings=m_duoview.settings();
    m_duoview_gaze.set_recovery_controls(static_cast<uint32_t>(settings.gaze_hold_ms),
        static_cast<uint32_t>(settings.gaze_reacquire_samples));
    auto frame=m_duoview.begin(key, get_hmd_width(), get_hmd_height(), frozen,
        [this, frozen, optical]() -> std::optional<uevr::duoview::UV> {
            return m_duoview_gaze.read_uv(frozen,optical);
        }, GetTickCount64(), source_frame);
    if (frame) m_duoview_candidate_key.store(
        std::make_shared<const uevr::duoview::FrameKey>(key), std::memory_order_release);
    return frame;
}

void VR::duoview_abort(const char* reason) {
    if (!is_using_duoview_mono()) return;
    SPDLOG_WARNING_EVERY_N_SEC(2, "[DuoView] Quarantining two-view path; continuing original Mono inside ID6: {}", reason);
    m_duoview_quarantined.store(true, std::memory_order_release);
    m_duoview.retire();
    m_duoview_candidate_key.store(nullptr, std::memory_order_release);
    m_duoview_frozen_key.store(nullptr, std::memory_order_release);
    set_mono_status("DuoView fault: rendering original Mono inside ID6; reselect ID6 to retry");
}
'''
    hook="src/mods/vr/FFakeStereoRenderingHook.cpp"
    edit(hook,'#include "FFakeStereoRenderingHook.hpp"',
        '#include "FFakeStereoRenderingHook.hpp"\n#include "DuoViewGeometry.hpp"')
    edit(hook,'''        packet->render_frame = vr->m_render_frame_count;
        packet->player_index = native_left_metadata.player_index;''',
    '''        packet->render_frame = vr->m_render_frame_count;
        if (duo_packet_frame && duo_packet_pose) {
            packet->duoview_frame=std::make_shared<const uevr::duoview::ViewFrame>(*duo_packet_frame);
            packet->duoview_mono_source_frame=*duo_packet_frame->mono_source_frame;
            packet->duoview_mono_source_valid=true;
            std::copy_n(duo_packet_pose->stage_views.begin(),2,packet->duoview_views.begin());
            packet->duoview_frame_state=duo_packet_pose->frame_state;
            packet->duoview_view_location=duo_packet_pose->view_space_location;
            packet->duoview_pose_valid=true;
        }
        packet->player_index = native_left_metadata.player_index;''')
    edit("src/mods/vr/runtimes/OpenXR.hpp", "    void note_mono_projection();",
        "    void note_mono_projection();\n    void note_mono_projection(uint32_t source_frame);")
    edit("src/mods/vr/runtimes/OpenXR.cpp", '''    frame.generation = vr->mono_generation();
}

void OpenXR::note_mono_main_family(uint32_t frame, bool main_family) {''',
    '''    frame.generation = vr->mono_generation();
}

// DuoView passes the immutable source pose token observed before Joey's
// Native Fix split invokes its second renderer callback.
void OpenXR::note_mono_projection(uint32_t source_frame) {
    std::scoped_lock lock{this->sync_assignment_mtx, this->pose_mtx};
    const auto vr = VR::get();
    auto& frame = mono_frames[source_frame % QUEUE_SIZE];
    if (frame.pose_frame != source_frame || !frame.pose_valid) { return; }
    frame.projection_frame = source_frame;
    frame.generation = vr->mono_generation();
}

void OpenXR::note_mono_main_family(uint32_t frame, bool main_family) {''')
    edit("src/mods/vr/FFakeStereoRenderingHook.hpp", '#include "Stalker2NativePolicy.hpp"',
        '#include "Stalker2NativePolicy.hpp"\n#include "DuoViewState.hpp"')
    edit("src/mods/vr/FFakeStereoRenderingHook.hpp", '''    struct NativeStereoFramePacket {
        std::shared_ptr<const VRRenderTargetManager_Base::SceneCaptureTargetSnapshot> capture{};''',
    '''    struct NativeStereoFramePacket {
        std::shared_ptr<const VRRenderTargetManager_Base::SceneCaptureTargetSnapshot> capture{};
        std::shared_ptr<const uevr::duoview::ViewFrame> duoview_frame{};
        uint32_t duoview_mono_source_frame{};
        bool duoview_mono_source_valid{};
        std::array<XrView,2> duoview_views{};
        XrFrameState duoview_frame_state{XR_TYPE_FRAME_STATE};
        XrSpaceLocation duoview_view_location{XR_TYPE_SPACE_LOCATION};
        bool duoview_pose_valid{};''')
    edit(hook,'''    g_hook->m_in_viewport_client_draw = true;
    g_hook->m_was_in_viewport_client_draw = false;''',
    '''    g_hook->m_in_viewport_client_draw = true;
    g_hook->m_was_in_viewport_client_draw = false;
    VR::get()->duoview_start_draw();''')
    edit(hook,'''    const bool wants_localplayer_bootstrap = !vr->is_using_mono() && (''',
        '''    const bool wants_localplayer_bootstrap = (!vr->is_using_mono() || vr->is_duoview_renderer_active()) && (''')
    edit(hook,'    if (vr->is_using_mono()) { return 1; }',
        '    if (vr->is_duoview_renderer_active()) { return 2; }\n    if (vr->is_using_mono()) { return 1; }')
    edit(hook,'''    auto& views = *views_ptr;
    const auto prev_count = views.count;

    if (auto view_family_target = view_family->get_render_target(); view_family_target != nullptr) {''',
    '''    auto& views = *views_ptr;
    const auto prev_count = views.count;

    // Observe Native Fix's original two-view main family before the fix
    // splits it into one-view primary and secondary render callbacks.
    const auto duo_target = view_family->get_render_target();
    const auto duo_main_target = rtm ? rtm->get_view_family_render_target() : nullptr;
    const bool duo_views_readable = vr->is_duoview_renderer_active() && prev_count == 2 &&
        views.capacity >= 2 && views.data != nullptr &&
        is_readable_process_range(reinterpret_cast<uintptr_t>(views.data), sizeof(void*) * 2);
    const bool duo_original_main_pair = duo_views_readable &&
        duo_target != nullptr && duo_target == duo_main_target &&
        view_family->get_scene_interface() != nullptr && views.data[0] != nullptr &&
        views.data[1] != nullptr && views.data[0] != views.data[1];
    if (duo_original_main_pair && vr->duoview_note_main_family(0, true, prev_count)) {
        const auto source_frame = vr->duoview_mono_source_frame();
        if (source_frame && vr->get_openxr_runtime())
            vr->get_openxr_runtime()->note_mono_main_family(*source_frame, true);
    }

    if (auto view_family_target = view_family->get_render_target(); view_family_target != nullptr) {''')
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
                // Native Fix renders each source into a separate single-eye target.
                // Atlas placement is applied only after both sources are validated.
                *x = 0;
                *y = 0;
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
        if (duo_frame && duo_frame->mono_source_frame && vr->mono_frame_gate_required() &&
            vr->get_runtime()->is_openxr()) {
            vr->get_openxr_runtime()->note_mono_projection(*duo_frame->mono_source_frame);
        } else if (!duo_frame && vr->mono_frame_gate_required() && vr->get_runtime()->is_openxr()) {
            vr->get_openxr_runtime()->note_mono_projection();
        }''')
    edit(hook,'''    if (vr->mono_frame_gate_required() && runtime->is_openxr()) {
        const bool main_family = view_family.get_render_target() != nullptr && view_family.get_render_target() ==
            reinterpret_cast<sdk::FRenderTarget*>(g_hook->get_render_target_manager()->get_viewport());
        vr->get_openxr_runtime()->note_mono_main_family(frame_count,
            main_family && views_ptr != nullptr && views_ptr->count > 0 &&
            (!vr->is_using_mono() || views_ptr->count == 1));
    }''',
    '''    if (!vr->is_duoview_renderer_active() && vr->mono_frame_gate_required() && runtime->is_openxr()) {
        const bool main_family = view_family.get_render_target() != nullptr && view_family.get_render_target() ==
            reinterpret_cast<sdk::FRenderTarget*>(g_hook->get_render_target_manager()->get_viewport());
        vr->get_openxr_runtime()->note_mono_main_family(frame_count,
            main_family && views_ptr != nullptr && views_ptr->count > 0 &&
            (!vr->is_using_mono() || views_ptr->count == 1));
    }''')
    edit(hook, '    std::optional<uint32_t> views_original_count{};',
    '''    if (vr->is_duoview_renderer_active() && g_hook->is_in_viewport_client_draw()) {
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
            if (index==1 && views->count==1 &&
                is_readable_process_range(state,sizeof(uintptr_t)) &&
                vr->duoview_state().can_independent_shading(key,state)) {
                set_effective_stereo_pass(EStereoscopicPass::eSSP_PRIMARY);
                restore_init_options_after_constructor=true;
                applied=get_effective_stereo_pass()==EStereoscopicPass::eSSP_PRIMARY;
            }
            vr->duoview_state().scene(key,index,state,applied);
        }
    }
    std::optional<uint32_t> views_original_count{};''')
    # Engine construction observes camera/rect/projection; a complete pair is
    # required before composition, not before we let the engine build its views.
    dxh="src/mods/vr/D3D12Component.hpp"
    edit(dxh,'#include "d3d12/TextureContext.hpp"',
        '#include "d3d12/TextureContext.hpp"\n#include "DuoViewD3D12.hpp"')
    edit(dxh,'        std::unordered_map<uint32_t, SwapchainContext> contexts{};',
        '''        std::unordered_map<d3d12::CommandContext*, std::unique_ptr<uevr::duoview::dx12::Compositor>> duoview_compositors;
        std::unordered_map<uint32_t, SwapchainContext> contexts{};''')
    dx="src/mods/vr/D3D12Component.cpp"

    # Session XR swapchains are created before the user selects ID6. Warm on
    # mode setup, not only during the XR swapchain creation (and never in copy).
    edit(dx,'''    spdlog::info("[VR] d3d12 textures have been setup");
    m_force_reset = false;''',
    '''    // DuoView may be activated long after OpenXR swapchains were created.
    // Build GPU objects for the EXISTING XR command slots on the mode transition.
    if (vr->is_duoview_renderer_active() && vr->get_runtime()->is_openxr()) {
        auto it = m_openxr.contexts.find(
            (uint32_t)runtimes::OpenXR::SwapchainIndex::DOUBLE_WIDE);
        if (it == m_openxr.contexts.end() || it->second.texture_contexts.empty()) {
            spdlog::warn("[DuoView][Activation] Double-wide OpenXR command contexts not ready");
        } else {
            UINT64 frequency{};
            if (auto queue = g_framework->get_d3d12_hook()->get_command_queue(); queue)
                queue->GetTimestampFrequency(&frequency);
            const bool srgb = false; // Existing Joey BGRA8 UNORM render source.
            uint32_t prepared = 0;
            for (auto& tc : it->second.texture_contexts) {
                if (!tc) continue;
                auto& comp = m_openxr.duoview_compositors[&tc->commands];
                if (!comp) comp = std::make_unique<uevr::duoview::dx12::Compositor>();
                if (comp->prewarm(device, vr->get_hmd_width(), vr->get_hmd_height(), srgb, frequency))
                    ++prepared;
                else
                    spdlog::warn("[DuoView][Activation] DX12 command-slot prewarm failed: {}", comp->error());
            }
            SPDLOG_INFO("[DuoView][Activation] Prepared {}/{} OpenXR command slots on ID6 entry",
                prepared, it->second.texture_contexts.size());
        }
    }
    spdlog::info("[VR] d3d12 textures have been setup");
    m_force_reset = false;''')

    edit(dx,'''    if (vr->mono_frame_gate_required()) {
        if (!vr->m_openxr->has_mono_frame(static_cast<uint32_t>(vr->m_frame_count))) {
            vr->set_mono_status("Waiting for a current main-view pose and validated common projection");
            vr->m_openxr->end_mono_transition_frame();
            return vr::VRCompositorError_None;
        }
        vr->note_mono_frame_ready(m_mono_generation);
    }''',
    '''    if (vr->mono_frame_gate_required() && !vr->is_duoview_renderer_active()) {
        if (!vr->m_openxr->has_mono_frame(static_cast<uint32_t>(vr->m_frame_count))) {
            vr->set_mono_status("Waiting for a current main-view pose and validated common projection");
            vr->m_openxr->end_mono_transition_frame();
            return vr::VRCompositorError_None;
        }
        vr->note_mono_frame_ready(m_mono_generation);
    }''')
    edit(dx,'    const auto frame_count = vr->is_using_mono() ? vr->m_frame_count : vr->m_render_frame_count;',
        '''    const auto frame_count = vr->is_using_mono() ? vr->m_frame_count : vr->m_render_frame_count;
    const bool duo_native_active = vr->is_duoview_renderer_active();
    const auto native_packet_frame_count = duo_native_active ? vr->m_render_frame_count : frame_count;''')
    edit(dx,'    const bool stalker_requested = vr->is_stalker2_native_fix_experiment_enabled();',
        '    const bool stalker_requested = vr->is_stalker2_native_fix_experiment_enabled();')
    edit(dx,'''    auto native_stereo_packet = ffsr != nullptr && !vr->is_using_mono()
        ? stalker_exact ? ffsr->get_stalker2_native_packet(stalker_frame, &native_frame_ticket)
            : ffsr->get_native_stereo_frame_packet_for_submit(frame_count, frame_diag::Backend::d3d12, &native_frame_ticket)
        : nullptr;''',
    '''    auto native_stereo_packet = ffsr != nullptr && (!vr->is_using_mono() || duo_native_active)
        ? stalker_exact && !duo_native_active ? ffsr->get_stalker2_native_packet(stalker_frame, &native_frame_ticket)
            : ffsr->get_native_stereo_frame_packet_for_submit(native_packet_frame_count, frame_diag::Backend::d3d12, &native_frame_ticket)
        : nullptr;''')
    edit(dx,'''        native_stereo_packet = ffsr->get_native_stereo_frame_packet_for_submit(
            frame_count, frame_diag::Backend::d3d12, &native_frame_ticket);''',
    '''        native_stereo_packet = ffsr->get_native_stereo_frame_packet_for_submit(
            native_packet_frame_count, frame_diag::Backend::d3d12, &native_frame_ticket);''')
    edit(dx,'''    this->wait_for_all_copies();

    for (auto& it : this->contexts) {''',
    '''    for (const auto& [commands, compositor] : this->duoview_compositors) {
        if (compositor && (!commands || commands->poisoned)) {
            spdlog::error("[DuoView] Retaining swapchains: command-slot retirement is unproven");
            return;
        }
    }
    this->wait_for_all_copies();
    for (const auto& [commands, compositor] : this->duoview_compositors) {
        if (compositor && !commands->references_retired()) {
            spdlog::error("[DuoView] Retaining swapchains: GPU references have not retired");
            return;
        }
    }
    vr->get_openxr_runtime()->invalidate_duoview_scene();
    this->duoview_compositors.clear();

    for (auto& it : this->contexts) {''')
    edit(dx,'''std::optional<std::string> D3D12Component::OpenXR::create_swapchains() {
    std::scoped_lock _{this->mtx};

    spdlog::info("[VR] Creating OpenXR swapchains for D3D12");

    this->destroy_swapchains();''',
    '''std::optional<std::string> D3D12Component::OpenXR::create_swapchains() {
    std::scoped_lock _{this->mtx};

    spdlog::info("[VR] Creating OpenXR swapchains for D3D12");

    this->destroy_swapchains();
    if (!this->duoview_compositors.empty())
        return "DuoView command-slot retirement pending; swapchains retained";''')
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
                        "[DuoView] DX12 prewarm failed; guarded compositing/fallback remains available");
                }
            }
        }

        if (vr->is_native_stereo_fix_texture_array_submit_enabled()) {
            auto native_array_create_info = standard_swapchain_create_info;''')
    edit(dx,'''                    if (vr->is_using_mono()) {
                        bool recorded = false;''',
    '''                    if (vr->is_duoview_renderer_active()) {
                        const auto packet = native_stereo_packet;
                        const auto packet_source = packet && packet->duoview_mono_source_valid
                            ? std::optional<uint32_t>{packet->duoview_mono_source_frame}
                            : std::optional<uint32_t>{};
                        const auto packet_frame = packet ? packet->duoview_frame : nullptr;
                        const auto packet_binding = packet_frame
                            ? uevr::duoview::native_frame_binding(*packet_frame)
                            : std::optional<uevr::duoview::NativeFrameBinding>{};
                        const bool packet_pair_valid = packet && packet_frame && packet_source &&
                            packet_frame->mono_source_frame &&
                            *packet_frame->mono_source_frame == *packet_source && packet_binding &&
                            packet_binding->key == packet_frame->config.key &&
                            packet_frame->config.key.generation == vr->mono_generation() &&
                            packet_binding->mono_source_frame == *packet_source &&
                            scene_capture_packet_ready && m_game_tex.texture.Get() != nullptr &&
                            m_scene_capture_tex.texture.Get() != nullptr &&
                            packet->duoview_pose_valid;
                        if (!packet_pair_valid) {
                            SPDLOG_WARNING_EVERY_N_SEC(2,
                                "[DuoView][Pair] Waiting serial={} pose_valid={} binding={} capture_ready={} source={}",
                                packet ? packet->serial : 0,packet && packet->duoview_pose_valid,
                                packet_binding.has_value(),scene_capture_packet_ready,packet_source.value_or(0));
                            vr->set_mono_status("Waiting for a complete Native Stereo Fix DuoView source pair");
                        } else {
                            bool recorded = false;
                            bool callback_attempted = false;
                            bool compositor_fault = false;
                            bool output_direct = false;
                            uint64_t source_extents = 0;
                            ID3D12Resource* recorded_secondary=nullptr;
                            ID3D12Resource* recorded_target=nullptr;
                            const bool submitted = m_openxr.copy(
                                (uint32_t)runtimes::OpenXR::SwapchainIndex::DOUBLE_WIDE, nullptr,
                                [this, packet, packet_frame, source=m_game_tex.texture,
                                 secondary=m_scene_capture_tex.texture, device,
                                 &recorded, &callback_attempted, &compositor_fault,
                                 &output_direct, &source_extents, &recorded_secondary, &recorded_target](
                                    d3d12::CommandContext& commands, ID3D12Resource* destination) {
                                    if (!commands.ready()) return;
                                    callback_attempted = true;
                                    const auto vr = VR::get();
                                    if (packet_frame->config.key.generation != vr->mono_generation() ||
                                        packet_frame->mono_source_frame !=
                                            std::optional<uint32_t>{packet->duoview_mono_source_frame} ||
                                        !uevr::duoview::native_frame_binding(*packet_frame)) {
                                        compositor_fault = true;
                                        return;
                                    }
                                    const auto found = m_openxr.duoview_compositors.find(&commands);
                                    if (found == m_openxr.duoview_compositors.end() || !found->second) {
                                        SPDLOG_WARNING_EVERY_N_SEC(2,
                                            "[DuoView][Activation] Missing prewarmed compositor for XR command slot");
                                        compositor_fault = true;
                                        return;
                                    }
                                    auto& compositor = *found->second;
                                    recorded = compositor.record_native(device, commands.cmd_list.Get(),
                                        source.Get(), secondary.Get(), destination,
                                        D3D12_RESOURCE_STATE_RENDER_TARGET,
                                        D3D12_RESOURCE_STATE_RENDER_TARGET, *packet_frame,
                                        std::static_pointer_cast<const void>(packet),
                                        packet_frame->config.settings.gpu_timing ? compositor.timing_frequency() : 0);
                                    if (recorded) {
                                        recorded_secondary=secondary.Get(); recorded_target=destination;
                                        output_direct=compositor.last_native_direct_xr();
                                        source_extents=compositor.last_native_source_extents();
                                    }
                                    if (compositor.recorded_commands()) commands.has_commands = true;
                                    if (packet_frame->config.settings.gpu_timing)
                                        vr->note_duoview_gpu_ms(compositor.gpu_milliseconds());
                                    if (!recorded) {
                                        SPDLOG_WARNING_EVERY_N_SEC(2,
                                            "[DuoView][Activation] Native compositing rejected: {}", compositor.error());
                                        compositor_fault = true;
                                    }
                                }, std::nullopt, D3D12_RESOURCE_STATE_RENDER_TARGET, nullptr,
                                std::nullopt, m_game_tex.texture.Get());
                            if (submitted && recorded) {
                                runtimes::OpenXR::PipelineState pose{};
                                pose.frame_count=*packet_source;
                                pose.stage_views.assign(packet->duoview_views.begin(),packet->duoview_views.end());
                                pose.frame_state=packet->duoview_frame_state;
                                pose.view_space_location=packet->duoview_view_location;
                                vr->m_openxr->note_duoview_copy(std::move(pose),packet_frame->config.key.generation);
                            }
                            if (submitted && recorded && callback_attempted) {
                                if (native_frame_ticket) {
                                    native_stereo_hook->record_native_frame_stage(*native_stereo_packet, native_frame_ticket,
                                        frame_diag::Backend::d3d12, frame_diag::Runtime::openxr, frame_diag::Stage::copy_recorded,
                                        0, 2, 0, recorded_secondary, recorded_target);
                                }
                                native_stereo_hook->note_native_stereo_frame_packet_consumed(packet->serial);
                                vr->note_duoview_output_path(output_direct);
                                vr->note_duoview_source_extents(source_extents);
                                vr->note_mono_frame_ready(m_mono_generation);
                            }
                            if (compositor_fault) {
                                vr->duoview_abort("Validated Native Stereo Fix pair failed DuoView composition");
                            } else if (!submitted || !recorded || !callback_attempted) {
                                vr->set_mono_status("Waiting for a retired OpenXR command slot for DuoView composition");
                            }
                        }
                    } else if (vr->is_using_mono()) {
                        bool recorded = false;''')
    edit(dx,'''    if (native_stereo_packet != nullptr && !scene_capture_packet_ready && native_stereo_hook != nullptr) {''',
        '''    if (!vr->is_duoview_renderer_active() && native_stereo_packet != nullptr &&
        !scene_capture_packet_ready && native_stereo_hook != nullptr) {''')
    edit(hook,'''    const auto publish_native_packet = [&]() {''',
    '''    const auto duo_packet_frame = vr->is_duoview_renderer_active()
        ? vr->duoview_state().snapshot(vr->duoview_producer_key())
        : std::optional<uevr::duoview::ViewFrame>{};
    const auto duo_packet_pose = duo_packet_frame && duo_packet_frame->mono_source_frame &&
        uevr::duoview::native_frame_binding(*duo_packet_frame) && vr->get_openxr_runtime()
        ? vr->get_openxr_runtime()->capture_duoview_pose(*duo_packet_frame->mono_source_frame)
        : std::optional<runtimes::OpenXR::PipelineState>{};
    const auto publish_native_packet = [&]() {''')
    xr="src/mods/vr/runtimes/OpenXR.cpp"
    xrh="src/mods/vr/runtimes/OpenXR.hpp"
    edit(xrh,'#include "../MonoRenderingPolicy.hpp"',
        '#include "../MonoRenderingPolicy.hpp"\n#include "../DuoViewFrame.hpp"')
    edit(xrh,'    PipelineState get_submit_state();',
    '''    PipelineState get_submit_state();
    std::optional<PipelineState> capture_duoview_pose(uint32_t frame);
    void note_duoview_copy(PipelineState pose, uint64_t generation);
    void invalidate_duoview_scene();
    std::optional<PipelineState> duoview_pending_pose, duoview_submitted_pose;
    uevr::duoview::SubmitContinuity duoview_continuity;
    bool duoview_holding{};
    std::atomic<uint64_t> duoview_copy_submits{}, duoview_hold_submits{}, duoview_empty_submits{};''')
    edit(xr,'    mono_copied_frame.reset();\n    this->should_recalculate_eye_projections = true;',
    '''    mono_copied_frame.reset();
    duoview_pending_pose.reset(); duoview_submitted_pose.reset();
    duoview_continuity.reset(); duoview_holding=false;
    this->should_recalculate_eye_projections = true;''')
    edit(xr,'OpenXR::PipelineState OpenXR::get_submit_state() {',
    '''std::optional<OpenXR::PipelineState> OpenXR::capture_duoview_pose(uint32_t frame) {
    std::scoped_lock lock{this->sync_assignment_mtx};
    const auto& pose=this->pipeline_states[frame%QUEUE_SIZE];
    if (!has_mono_frame(frame) || pose.frame_count!=frame || pose.stage_views.size()!=2) {
        SPDLOG_WARNING_EVERY_N_SEC(2,
            "[DuoView][Pose] Producer snapshot rejected source={} slot_token={} views={} mono_valid={}",
            frame,pose.frame_count,pose.stage_views.size(),has_mono_frame(frame));
        return {};
    }
    return pose;
}

void OpenXR::invalidate_duoview_scene() {
    std::scoped_lock lock{this->sync_assignment_mtx};
    duoview_pending_pose.reset(); duoview_submitted_pose.reset();
    duoview_continuity.reset(); duoview_holding=false;
}

void OpenXR::note_duoview_copy(PipelineState pose, uint64_t generation) {
    std::scoped_lock lock{this->sync_assignment_mtx};
    const auto vr=VR::get();
    if (!vr->is_duoview_renderer_active() || generation!=vr->mono_generation()) return;
    duoview_pending_pose=std::move(pose);
}

OpenXR::PipelineState OpenXR::get_submit_state() {
    if (const auto vr=VR::get(); vr->is_duoview_renderer_active()) {
        std::scoped_lock lock{this->sync_assignment_mtx};
        PipelineState selected{};
        const auto scene=this->swapchains.find((uint32_t)SwapchainIndex::DOUBLE_WIDE);
        const uint64_t handle=scene==this->swapchains.end() ? 0 : reinterpret_cast<uint64_t>(scene->second.handle);
        duoview_holding=false;
        if (duoview_pending_pose) {
            selected=std::move(*duoview_pending_pose);
            duoview_pending_pose.reset();
        } else if (duoview_submitted_pose &&
            duoview_continuity.can_hold(vr->mono_generation(),handle,GetTickCount64())) {
            selected=*duoview_submitted_pose;
            duoview_holding=true;
        }
        selected.frame_state=this->frame_state;
        this->has_render_frame_count=false;
        this->last_submit_state=selected;
        return selected;
    }''')
    edit(xr,'''    if (mono && result == XR_SUCCESS && !projection_layer_views.empty()) {
        vr->set_mono_status("Active: one current centered scene submitted to both eyes");
    }''',
    '''    if (vr->is_duoview_renderer_active()) {
        std::scoped_lock lock{this->sync_assignment_mtx};
        if (result==XR_SUCCESS && !projection_layer_views.empty()) {
            if (duoview_holding) ++duoview_hold_submits;
            else ++duoview_copy_submits;
            if (!duoview_holding) {
                const auto scene=this->swapchains.find((uint32_t)SwapchainIndex::DOUBLE_WIDE);
                if (scene!=this->swapchains.end()) {
                    duoview_submitted_pose=submit_state;
                    duoview_continuity.submitted(vr->mono_generation(),
                        reinterpret_cast<uint64_t>(scene->second.handle),GetTickCount64());
                }
            }
            vr->set_mono_status(duoview_holding
                ? "DuoView: holding the last submitted scene through a short source interruption"
                : "DuoView: active two-source scene submitted to both eyes");
        } else {
            if (this->frame_state.shouldRender==XR_TRUE) ++duoview_empty_submits;
            duoview_continuity.reset();
        }
    } else if (mono && result == XR_SUCCESS && !projection_layer_views.empty()) {
        vr->set_mono_status("Active: one current centered scene submitted to both eyes");
    }''')
    edit(dx,'''    bool used_pre_acquired_image = false;''',
    '''    if (swapchain_idx==(uint32_t)runtimes::OpenXR::SwapchainIndex::DOUBLE_WIDE &&
        vr->is_using_duoview_mono()) vr->get_openxr_runtime()->invalidate_duoview_scene();
    bool used_pre_acquired_image = false;''')

    edit(dx,'''    const auto& swapchain = vr->m_openxr->swapchains[swapchain_idx];
    XrSwapchainImageAcquireInfo acquire_info{XR_TYPE_SWAPCHAIN_IMAGE_ACQUIRE_INFO};''',
    '''    const auto& swapchain = vr->m_openxr->swapchains[swapchain_idx];
    if (swapchain_idx==(uint32_t)runtimes::OpenXR::SwapchainIndex::DOUBLE_WIDE &&
        vr->is_using_duoview_mono()) vr->get_openxr_runtime()->invalidate_duoview_scene();
    XrSwapchainImageAcquireInfo acquire_info{XR_TYPE_SWAPCHAIN_IMAGE_ACQUIRE_INFO};''')
    edit(dx,'''    // OpenXR copy contexts can still reference the borrowed Native Fix source.
    // Drain them before releasing any source or descriptor wrappers below.
    if (runtime->is_openxr() && runtime->loaded) {
        m_openxr.wait_for_all_copies();''',
    '''    // OpenXR copy contexts can still reference the borrowed Native Fix source.
    // Drain them before releasing any source or descriptor wrappers below.
    if (runtime->is_openxr() && runtime->loaded) {
        vr->get_openxr_runtime()->invalidate_duoview_scene();
        m_openxr.wait_for_all_copies();''')

    edit(hook,'''    if (native_stereo_fix_enabled) {
        if (g_hook->m_native_stereo_localplayer_bootstrap_failed.load(std::memory_order_acquire)) {''',
    '''    if (native_stereo_fix_enabled) {
        if (vr->is_duoview_renderer_active()) {
            bool duo_main_target_present=false;
            const auto expected=rtm->get_view_family_render_target();
            for (const auto family:view_families) {
                if (expected && family && family->get_render_target()==expected) {
                    duo_main_target_present=true;
                    break;
                }
            }
            if (!duo_main_target_present) {
                call_original();
                return;
            }
        }
        if (g_hook->m_native_stereo_localplayer_bootstrap_failed.load(std::memory_order_acquire)) {''')

    edit(hook,'''    const auto rtm = const_cast<FFakeStereoRenderingHook*>(this)->get_render_target_manager();
    const auto current_capture = rtm != nullptr ? rtm->get_scene_capture_target_snapshot() : nullptr;''',
    '''    const auto rtm = const_cast<FFakeStereoRenderingHook*>(this)->get_render_target_manager();
    if (vr->is_duoview_renderer_active() &&
        (!rtm || packet->main_target!=rtm->get_view_family_render_target())) {
        record_outcome(frame_diag::Reason::changed_resource);
        return nullptr;
    }
    const auto current_capture = rtm != nullptr ? rtm->get_scene_capture_target_snapshot() : nullptr;''')

    edit(xr,'''    if (vr->mono_frame_gate_required()) {
        auto& mono = mono_frames[frame_count % QUEUE_SIZE];
        mono.generation = vr->mono_generation();''',
    '''    if (vr->mono_frame_gate_required()) {
        if (vr->is_duoview_renderer_active()) pipeline_state.frame_count=frame_count;
        auto& mono = mono_frames[frame_count % QUEUE_SIZE];
        mono.generation = vr->mono_generation();''')

    edit("tests/CadenceReplayTests.cpp",
        'copies == (std::string(backend) == "D3D11" ? 2 : 3)',
        'copies == (std::string(backend) == "D3D11" ? 2 : 4)')

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
    print("Applied Stage 5 PSVR2 gaze with cached per-frame projection, same-pose two-view and DX12 compositor (experimental).")

if __name__=="__main__":
    main()

