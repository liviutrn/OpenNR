"""Dedicated DuoView startup, compact scene allocation and gaze camera."""
from pathlib import Path
from apply_stage234 import replace

def apply(root, frontend, changed):
    def edit(path, old, new):
        base=frontend if path.startswith(('UEVR/','tests/RenderingModes/')) else root
        text=changed.get(path)
        if text is None: text=(base/path).read_text(encoding='utf-8-sig')
        changed[path]=replace(text,old,new,path)
    policy='src/mods/vr/MonoRenderingPolicy.hpp'
    edit(policy,'    void initialize(int32_t value) {', '''    void initialize_duoview() {
        std::scoped_lock lock{m_mutex};
        if (m_initialized) { return; }
        m_initialized=true;
        m_requested=pack(duoview_method_id,1);
        m_active=pack(duoview_method_id,1);
    }
    void initialize(int32_t value) {''')
    setting='src/mods/vr/RenderingMethodSetting.hpp'
    edit(setting,': m_name{std::move(name)}, m_options{options} {}',
         ': m_name{std::move(name)}, m_options{options} { m_selection.initialize_duoview(); }')
    edit(setting,'void request(int32_t value) { m_selection.request(value); }',
         'void request(int32_t) { m_selection.request(uevr::mono::duoview_method_id); }')
    edit(setting,'m_selection.initialize(defaults ? 0 : cfg.get<int32_t>(m_name).value_or(requested_value()));',
         'm_selection.initialize_duoview();')
    header='src/mods/VR.hpp'
    edit(header,'#include "vr/DuoViewState.hpp"',
         '#include "vr/DuoViewState.hpp"\n#include "vr/DuoViewSceneLayout.hpp"')
    edit(header,'generate_name("RenderingMethod"), uevr::mono::choices)',
         'generate_name("RenderingMethod"), std::span<const uevr::mono::Choice>{&uevr::mono::choices[6],1})')
    edit(header,'return {mono_generation(), static_cast<uint64_t>(frame) + 1u};',
         'return {m_duoview_epoch.load(std::memory_order_acquire), static_cast<uint64_t>(frame) + 1u};')
    edit(header,'    void configure_duoview();', '''    void configure_duoview();
    std::array<uint32_t,2> duoview_scene_extent() const {
        const auto s=m_duoview.settings();
        const auto layout=uevr::duoview::scene_layout(get_hmd_width(),get_hmd_height(),s);
        return {layout.atlas_width,layout.atlas_height};
    }
    uevr::duoview::Rect duoview_scene_rectangle(int index,bool double_precision) const {
        const auto s=m_duoview.settings();
        return uevr::duoview::scene_rectangle(
            uevr::duoview::scene_layout(get_hmd_width(),get_hmd_height(),s),s.fovea_view,index,double_precision);
    }
    void reset_duoview() {
        m_duoview_epoch.fetch_add(1,std::memory_order_acq_rel);
        m_duoview.retire();
        m_duoview_quarantined.store(false,std::memory_order_release);
        m_mono_ready_generation.store(0,std::memory_order_release);
    }''')
    edit(header,'    std::once_flag m_duoview_settings_once;',
         '    std::once_flag m_duoview_settings_once;\n    std::atomic<uint64_t> m_duoview_epoch{1};')
    edit(header,'    void on_device_reset() override {\n        m_duoview.retire();',
         '    void on_device_reset() override {\n        reset_duoview();')
    edit(header,'        spdlog::info("Reinitializing OpenXR");',
         '        spdlog::info("Reinitializing OpenXR");\n        reset_duoview();')
    cpp='src/mods/VR.cpp'
    edit(header,'    const ModSlider::Ptr m_duo_smoothing{ModSlider::create(generate_name("DuoViewCropSmoothingMs"), 0.f, 250.f, 85.f)};',
         '''    const ModSlider::Ptr m_duo_smoothing{ModSlider::create(generate_name("DuoViewCropSmoothingMs"), 0.f, 250.f, 0.f)};
    const ModInt32::Ptr m_duo_quantization{ModSliderInt32::create(generate_name("DuoViewCropQuantizationPixels"),0,64,8)};''')
    edit(header,'            *m_duo_smoothing, *m_duo_history_audit,',
         '            *m_duo_smoothing, *m_duo_history_audit, *m_duo_quantization,')
    edit(cpp,'        .guard_fraction=0.f, .smoothing_ms=0.f,',
         '        .guard_fraction=.05f, .smoothing_ms=m_duo_smoothing->value(),')
    edit(cpp,'        // Compatibility with saved Build32 profiles: force latency settings off.\n','')
    edit(cpp,'.temporal_audit=m_duo_history_audit->value()};',
         '''.temporal_audit=m_duo_history_audit->value(),
        .gaze_camera=true, .compact_atlas=true, .hold_tracking_loss=true,
        .r10_crop_policy=true,
        .quantization_pixels=static_cast<uint32_t>(m_duo_quantization->value())};''')
    edit(cpp,'current.temporal_audit==candidate.temporal_audit) return;',
         '''current.temporal_audit==candidate.temporal_audit && current.gaze_camera &&
        current.compact_atlas && current.hold_tracking_loss && current.r10_crop_policy &&
        current.quantization_pixels==candidate.quantization_pixels) return;''')
    edit(cpp,'ImGui::TextWrapped("v24: Eye tracking is INSTANT. Old crop guard/smoothing settings are ignored, including values stored in older profiles. No velocity cap or quantization.");',
         '''m_duo_stabilize->draw("OpenNR r10 crop stabilization");
                m_duo_smoothing->draw("Fixation smoothing (ms; larger eye moves bypass)");
                m_duo_quantization->draw("Crop movement quantization (foveal pixels; 0 off)");
                if (ImGui::Button("Restore OpenNR r10 tracking defaults")) {
                    m_duo_stabilize->value()=true;m_duo_smoothing->value()=0.f;m_duo_quantization->value()=8;
                }
                ImGui::TextWrapped("Fixation guard holds small crop changes. Deliberate eye movement recenters immediately. No speed cap or delayed crop following.");''')
    edit(cpp,'                        layout.atlas_width/2,layout.atlas_height);',
         '                        layout.output_width,layout.output_height);')
    edit(cpp,'ImGui::TextWrapped("View 0 = FIRST Unreal pass (old prototype default), view 1 = SECOND pass (Build19 default). Identical frozen Mono camera. Switching may reset temporal history.");',
         'ImGui::TextWrapped("View 0 is the first UE pass; view 1 is the second. Same Mono position. Tracked fovea uses a gaze-directed camera and matching ray mapping.");')
    edit(cpp,'if (!is_using_duoview_mono() || !m_is_d3d12 || m_duoview_quarantined.load(std::memory_order_acquire)) return false;',
         'if (!is_using_duoview_mono() || !m_is_d3d12) return false;')
    edit(cpp,'    m_duoview.retire();\n    set_mono_status("DuoView fault: rendering original Mono inside ID6; reselect ID6 to retry");',
         '    set_mono_status("DuoView frame rejected; waiting for a complete current two-view frame");')
    edit(cpp,'"[DuoView] Quarantining two-view path; continuing original Mono inside ID6: {}"',
         '"[DuoView] Rejecting incomplete frame without changing rendering mode: {}"')
    edit(cpp,'    m_prospi_camera_trace_requested.store(is_prospi_executable() && m_prospi_camera_trace_enabled->value(), std::memory_order_release);',
         '''    m_extreme_compat_mode->value()=false;
    m_splitscreen_compatibility_mode->value()=false;
    m_sceneview_compatibility_mode->value()=false;
    m_2d_screen_mode->value()=false;
    m_stereo_emulation_mode=false;
    configure_duoview();
    m_prospi_camera_trace_requested.store(is_prospi_executable() && m_prospi_camera_trace_enabled->value(), std::memory_order_release);''')
    hook='src/mods/vr/FFakeStereoRenderingHook.cpp'
    edit(hook,'if (!vr->is_ghosting_fix_enabled() && !vr->is_splitscreen_compatibility_enabled() && !vr->is_sceneview_compatibility_enabled() && !vr->is_native_stereo_fix_enabled()) {',
         'if (!vr->is_using_duoview_mono() && !vr->is_ghosting_fix_enabled() && !vr->is_splitscreen_compatibility_enabled() && !vr->is_sceneview_compatibility_enabled() && !vr->is_native_stereo_fix_enabled()) {')
    edit(hook,'    FIntRect native_view_rect{};', '''    std::optional<Matrix4x4d> duoview_original_rotation{};
    utility::ScopeGuard duoview_restore_rotation{[&]() {
        if (!duoview_original_rotation) return;
        if (is_ue50_to_53) init_options_ue50_to_53->view_rotation_matrix=*duoview_original_rotation;
        else init_options_ue5->view_rotation_matrix=*duoview_original_rotation;
    }};
    if (vr->is_duoview_renderer_active() && is_ue5 &&
        init_options_view_family && (init_options_stereo_pass==EStereoscopicPass::eSSP_PRIMARY ||
        init_options_stereo_pass==EStereoscopicPass::eSSP_SECONDARY)) {
        const auto rtm=g_hook->get_render_target_manager();
        if (rtm && init_options_view_family->get_render_target()==rtm->get_view_family_render_target()) {
            const unsigned index=init_options_stereo_pass==EStereoscopicPass::eSSP_PRIMARY ? 0u : 1u;
            if (const auto frame=vr->duoview_begin_frame(); frame &&
                index==frame->config.settings.fovea_view && frame->config.foveal_camera.enabled) {
                auto& rotation=is_ue50_to_53 ? init_options_ue50_to_53->view_rotation_matrix :
                    init_options_ue5->view_rotation_matrix;
                duoview_original_rotation=rotation;
                uevr::duoview::rotate_foveal_view(rotation,frame->config.foveal_camera);
                vr->duoview_state().foveal_rotation(frame->config.key);
            }
        }
    }
    FIntRect native_view_rect{};''')
    edit(hook,'    x = VR::get()->get_hmd_width() * 2;\n    y = VR::get()->get_hmd_height();',
         '    const auto duo_extent=VR::get()->duoview_scene_extent();\n    x = duo_extent[0];\n    y = duo_extent[1];')
    edit(hook,'    const auto w = VR::get()->get_hmd_width();\n    const auto h = VR::get()->get_hmd_height();',
         '    const auto duo_extent=VR::get()->duoview_scene_extent();\n    const auto w = duo_extent[0];\n    const auto h = duo_extent[1];')
    # All generic texture-allocation discovery paths must match the compact scene.
    text=changed[hook]
    import re
    text,count=re.subn(r'const auto scan_x = VR::get\(\)->get_hmd_width\(\) \* 2;\n(\s*)const auto scan_y = VR::get\(\)->get_hmd_height\(\);',
        r'const auto scan_x = VR::get()->duoview_scene_extent()[0];\n\1const auto scan_y = VR::get()->duoview_scene_extent()[1];',text)
    if count!=4: raise RuntimeError(f'Expected four texture allocation discovery extents, got {count}')
    changed[hook]=text
    # Never let temporary setup/failed snapshots request full eye rectangles.
    edit(hook,'    if (g_hook->m_skip_next_adjust_view_rect) {',
         '    if (!VR::get()->is_using_duoview_mono() && g_hook->m_skip_next_adjust_view_rect) {')
    edit(hook,'    if (g_hook->m_skip_next_adjust_view_rect_count > 0) {',
         '    if (!VR::get()->is_using_duoview_mono() && g_hook->m_skip_next_adjust_view_rect_count > 0) {')
    edit(hook,'        // Pair cannot pass frame validation. Original Mono fallback is guarded at submission.',
         '''        const auto rect=vr->duoview_scene_rectangle(index,g_hook->m_has_double_precision);
        *x=static_cast<int>(rect.x); *y=static_cast<int>(rect.y); *w=rect.width; *h=rect.height;
        return;''')
    edit(hook,'    if (VR::get()->is_stereo_emulation_enabled()) {\n        *w *= 2;',
         '''    if (VR::get()->is_using_duoview_mono() &&
        (!VR::get()->is_duoview_renderer_active() || !g_hook->m_has_double_precision)) {
        const auto rect=VR::get()->duoview_scene_rectangle(index,g_hook->m_has_double_precision);
        *x=static_cast<int>(rect.x); *y=static_cast<int>(rect.y); *w=rect.width; *h=rect.height;
        return;
    }
    if (VR::get()->is_stereo_emulation_enabled()) {
        *w *= 2;''')
    dx='src/mods/vr/D3D12Component.cpp'
    text=changed[dx]
    start=text.index('                                if (!duo_recorded) {')
    end=text.index('                            }, std::nullopt, scene_source_state, nullptr,',start)
    text=text[:start]+'''                                if (!duo_recorded) {
                                    duo_failed=true;
                                } else recorded=true;
'''+text[end:]
    changed[dx]=text
    edit(dx,'"XR copy/composite fault; safe original Mono requested"',
         '"XR copy/composite fault; frame rejected, DuoView remains selected"')
    edit(dx,'''                        // Do not skip the OpenXR copy if pair evidence fails.
                        // Emergency copy may be an incomplete atlas; quarantine ID6
                        // after this callback, then original Joey Mono on the next frame.
''','')
    edit(dx,'''    if (!vr->is_extreme_compatibility_mode_enabled()) {
        m_backbuffer_size[0] = backbuffer_desc.Width * 2;''',
         '''    if (vr->is_using_duoview_mono()) {
        m_backbuffer_size[0] = backbuffer_desc.Width;
    } else if (!vr->is_extreme_compatibility_mode_enabled()) {
        m_backbuffer_size[0] = backbuffer_desc.Width * 2;''')
    # Scene textures and compositor output have separate extents.
    edit(dx,'        backbuffer_desc.Width /= 2; // The texture we get from UE is both eyes combined. we will copy the regions later.',
         '        if (!vr->is_using_duoview_mono()) backbuffer_desc.Width /= 2;')
    # The ordinary staging textures must match source copies; mono output is owned by the compositor.
    frontend_modes='UEVR/RenderingModeOptions.cs'
    text=changed[frontend_modes]
    start=text.index('            var result = new Dictionary<string, string> {')
    end=text.index('            return result;',start)
    text=text[:start]+'''            var result = new Dictionary<string, string> {
                { DuoViewMono.ToString(), "DuoView Mono (Always On)" }
            };
'''+text[end:]
    start=text.index('            var result = new Dictionary<string, string>(choices);')
    end=text.index('            return result;',start)
    text=text[:start]+'''            var result = new Dictionary<string, string>(choices);
'''+text[end:]
    changed[frontend_modes]=text
    edit('UEVR/MainWindow.xaml.cs','((int)RenderingMethod.NativeStereo).ToString()',
         'RenderingModeOptions.DuoViewMono.ToString()')
    edit('UEVR/MainWindow.xaml.cs','new GameSettingEntry { Key = kv.Key, Value = kv.Value, ComboValues = comboValues, Tooltip = tooltip }',
         'new GameSettingEntry { Key = kv.Key, Value = kv.Key == "VR_RenderingMethod" ? RenderingModeOptions.DuoViewMono.ToString() : kv.Value, ComboValues = comboValues, Tooltip = tooltip }')
    changed['tests/RenderingModes/Program.cs']='''using System;
using UEVR;
foreach (bool dibr in new[] { false,true }) {
    var choices=RenderingModeOptions.Create(dibr);
    if (choices.Count!=1 || !choices.ContainsKey("6")) throw new Exception("DuoView must be the only selectable mode");
    foreach (string old in new[] {"0","1","2","3","4","5","6","99","-1"}) {
        var mapped=RenderingModeOptions.PreserveValue(choices,old);
        if (mapped.Count!=1 || !mapped.ContainsKey("6")) throw new Exception("Legacy profile exposed a different mode");
    }
}
Console.WriteLine("Dedicated DuoView mode and legacy-profile migration passed.");
'''
