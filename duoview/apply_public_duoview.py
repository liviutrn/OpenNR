#!/usr/bin/env python3
"""Integrate DuoView over the pinned public-backend calibrated Mono port."""
from pathlib import Path
import argparse
import shutil


def once(text, old, new, path):
    if text.count(old) != 1:
        raise RuntimeError(f'{path}: anchor count {text.count(old)}: {old[:100]!r}')
    return text.replace(old, new, 1)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('root', type=Path)
    root = parser.parse_args().root.resolve()
    source = Path(__file__).parent
    files = {}
    def change(path, old, new):
        text = files.get(path, (root/path).read_text(encoding='utf-8'))
        files[path] = once(text, old, new, path)
    policy='src/mods/vr/MonoRenderingPolicy.hpp'
    change(policy, 'inline constexpr int32_t method_id = 5;', '''inline constexpr int32_t method_id = 5;
inline constexpr int32_t duoview_method_id = 6;
constexpr bool is_mono_method(int32_t id) { return id == method_id || id == duoview_method_id; }''')
    change(policy, '    Choice{method_id, "Mono (Experimental)"},', '    Choice{method_id, "Mono (Experimental)"},\n    Choice{duoview_method_id, "DuoView Mono (Experimental)"},')
    change(policy,'inline constexpr std::array non_dibr_choices {choices[0], choices[1], choices[2], choices[5]};','inline constexpr std::array non_dibr_choices {choices[0], choices[1], choices[2], choices[5], choices[6]};')
    change(policy,'m_active = pack(value == method_id ? 0 : value, 0);','m_active = pack(is_mono_method(value) ? 0 : value, 0);')
    change(policy,'if (active() != method_id && value != method_id) {','if (!is_mono_method(active()) && !is_mono_method(value)) {')
    change(policy,'return method == method_id || generation != ready_generation;','return is_mono_method(method) || generation != ready_generation;')
    header='src/mods/VR.hpp'
    change(header,'#include "vr/RenderingMethodSetting.hpp"','#include "vr/RenderingMethodSetting.hpp"\n#include "vr/DuoViewState.hpp"')
    change(header,'        MONO = uevr::mono::method_id,','        MONO = uevr::mono::method_id,\n        DUOVIEW_MONO = uevr::mono::duoview_method_id,')
    change(header,'    bool is_using_mono() const { return m_rendering_method->value() == RenderingMethod::MONO; }','''    bool is_using_duoview_mono() const { return m_rendering_method->value() == DUOVIEW_MONO; }
    bool is_using_mono() const { return uevr::mono::is_mono_method(m_rendering_method->value()); }
    uevr::duoview::State& duoview_state() { return m_duoview; }
    uevr::duoview::FrameKey duoview_key(uint32_t frame) const { return {mono_generation(), static_cast<uint64_t>(frame) + 1}; }
    std::optional<uevr::duoview::ViewFrame> duoview_begin_frame();
    void configure_duoview();
    void note_duoview_gpu_ms(float ms) { m_duo_gpu_ms.store(ms, std::memory_order_relaxed); }''')
    change(header,'(requested_rendering_method() != RenderingMethod::MONO || mono_unavailable_reason() == nullptr);','(!uevr::mono::is_mono_method(requested_rendering_method()) || mono_unavailable_reason() == nullptr);')
    controls='''    uevr::duoview::State m_duoview;
    std::atomic<float> m_duo_gpu_ms{-1.f};
    const ModSlider::Ptr m_duo_width{ModSlider::create(generate_name("DuoViewCropWidth"), .1f, 1.f, .5f)};
    const ModSlider::Ptr m_duo_height{ModSlider::create(generate_name("DuoViewCropHeight"), .1f, 1.f, .5f)};
    const ModSlider::Ptr m_duo_periphery{ModSlider::create(generate_name("DuoViewPeripheralScale"), .05f, .5f, .2f)};
    const ModSlider::Ptr m_duo_density{ModSlider::create(generate_name("DuoViewFovealDensity"), .25f, 4.f, 1.f)};
    const ModSlider::Ptr m_duo_feather{ModSlider::create(generate_name("DuoViewFeather"), 0.f, .45f, .08f)};
    const ModToggle::Ptr m_duo_gaze{ModToggle::create(generate_name("DuoViewEyeTracking"), true)};
    const ModToggle::Ptr m_duo_border{ModToggle::create(generate_name("DuoViewDebugBorder"), false)};
    const ModInt32::Ptr m_duo_view{ModSliderInt32::create(generate_name("DuoViewFoveaSourceView"), 0, 1, 0)};
'''
    change(header,'    std::atomic<const char*> m_mono_status{"Not selected"};',controls+'    std::atomic<const char*> m_mono_status{"Not selected"};')
    change(header,'        m_options = {','''        m_options = {
            *m_duo_width, *m_duo_height, *m_duo_periphery, *m_duo_density,
            *m_duo_feather, *m_duo_gaze, *m_duo_border, *m_duo_view,''')
    cpp='src/mods/VR.cpp'
    change(cpp,'#include "VR.hpp"','#include "VR.hpp"\n#include "vr/PSVR2NativeGaze.hpp"\n#include <cstring>')
    change(cpp,'const bool entering = selection.requested() == RenderingMethod::MONO;','const bool entering = uevr::mono::is_mono_method(selection.requested());')
    change(cpp,'if (selection.requested() == RenderingMethod::MONO && mono_unavailable_reason() != nullptr) { return; }','if (uevr::mono::is_mono_method(selection.requested()) && mono_unavailable_reason() != nullptr) { return; }')
    change(cpp,'    m_mono_main_view_token = 0;','    m_duoview.retire();\n    m_mono_main_view_token = 0;')
    change(cpp,'    // Load camera offsets\n    load_cameras();','    configure_duoview();\n    // Load camera offsets\n    load_cameras();')
    change(cpp,'        m_rendering_method->draw("Rendering Method");','''        m_rendering_method->draw("Rendering Method");
        if (ImGui::TreeNode("DuoView Mono")) {
            m_duo_width->draw("Fovea width (fraction of full image)");
            m_duo_height->draw("Fovea height (fraction of full image)");
            m_duo_periphery->draw("Peripheral resolution scale");
            m_duo_density->draw("Foveal pixel density");
            m_duo_feather->draw("Feather fraction of crop");
            m_duo_gaze->draw("PSVR2 Toolkit gaze");
            m_duo_view->draw("Fovea source view (0 or 1)");
            m_duo_border->draw("Debug border");
            configure_duoview();
            if (const auto frame = m_duoview.snapshot(duoview_key(get_runtime()->internal_frame_count))) {
                const auto& l = frame->config.layout;
                ImGui::Text("UE fovea %ux%u; periphery %ux%u; output %ux%u", l.fovea.width, l.fovea.height,
                    l.periphery.width, l.periphery.height, l.atlas_width / 2, l.atlas_height);
                ImGui::Text("Gaze %s; UV %.3f, %.3f; %.2f million view pixels",
                    frame->gaze_valid ? "tracking" : "fixed center / unavailable", frame->config.gaze.u,
                    frame->config.gaze.v, uevr::duoview::rendered_pixels(l) / 1000000.0);
            }
            if (const float ms = m_duo_gpu_ms.load(std::memory_order_relaxed); ms >= 0)
                ImGui::Text("Composite + eye copies: %.3f ms GPU (last completed slot)", ms);
            const auto active_settings = m_duoview.settings();
            if (active_settings.crop_width != m_duo_width->value() || active_settings.crop_height != m_duo_height->value() ||
                active_settings.foveal_density != m_duo_density->value() || active_settings.peripheral_scale != m_duo_periphery->value())
                ImGui::TextWrapped("Selected sizes exceed the current atlas; previous valid settings are active.");
            ImGui::TextWrapped("Experimental: real game shading savings and temporal stability require headset testing.");
            ImGui::TreePop();
        }''')
    files[cpp] += '''
void VR::configure_duoview() {
    if (!m_duoview.configure({m_duo_width->value(), m_duo_height->value(), m_duo_periphery->value(),
        m_duo_density->value(), m_duo_feather->value(), m_duo_border->value(), m_duo_gaze->value(),
        static_cast<uint32_t>(m_duo_view->value())})) {
        SPDLOG_WARNING_EVERY_N_SEC(2, "[DuoView] Invalid layout settings; preserving last valid configuration");
    }
}

std::optional<uevr::duoview::ViewFrame> VR::duoview_begin_frame() {
    if (!is_using_duoview_mono() || !m_fake_stereo_hook->is_in_viewport_client_draw()) return {};
    auto runtime = get_runtime();
    const auto key = duoview_key(runtime->internal_frame_count);
    if (const auto existing = m_duoview.snapshot(key)) return existing;
    const float near_plane = sdk::globals::get_near_clipping_plane();
    if (!std::isfinite(near_plane) || near_plane <= 0.f) return {};
    runtime->update_matrices(near_plane, 10000.f);
    auto projection = get_projection_matrix(VRRuntime::Eye::LEFT);
    projection[3][2] = near_plane;
    std::array<float, 16> elements{};
    std::memcpy(elements.data(), &projection[0][0], sizeof(elements));
    return m_duoview.begin(key, get_hmd_width(), get_hmd_height(), elements, [&]() -> std::optional<uevr::duoview::UV> {
        XrQuaternionf orientation{};
        if (!cheeky_psvr2::read_orientation(orientation)) return {};
        const glm::quat gaze{orientation.w, orientation.x, orientation.y, orientation.z};
        const auto eye = get_eye_transform(0);
        const auto direction = glm::inverse(glm::quat_cast(glm::mat3(eye))) * (gaze * glm::vec3{0, 0, -1});
        if (projection[0][0] <= 0 || projection[1][1] <= 0) return {};
        const uevr::duoview::Tans tans{-1.f / projection[0][0], 1.f / projection[0][0],
            1.f / projection[1][1], -1.f / projection[1][1]};
        return uevr::duoview::ray_to_uv({direction.x, direction.y, -direction.z}, tans);
    });
}
'''
    hook='src/mods/vr/FFakeStereoRenderingHook.cpp'
    signature='void FFakeStereoRenderingHook::adjust_view_rect(FFakeStereoRendering* stereo, int32_t index, int* x, int* y, uint32_t* w, uint32_t* h) {'
    change(hook, signature, signature + """
    if (VR::get()->is_using_duoview_mono() &&
        uevr::duoview::renderer_view_index(index, g_hook->m_has_double_precision) < 0) return;""")
    projection_signature='__forceinline Matrix4x4f* FFakeStereoRenderingHook::calculate_stereo_projection_matrix(FFakeStereoRendering* stereo, Matrix4x4f* out, const int32_t view_index) {'
    change(hook, projection_signature, projection_signature + """
    if (out == nullptr) return nullptr;
    if (VR::get()->is_using_duoview_mono() &&
        uevr::duoview::renderer_view_index(view_index, g_hook->m_has_double_precision) < 0) {
        if (g_hook->m_calculate_stereo_projection_matrix_hook)
            return g_hook->m_calculate_stereo_projection_matrix_hook.call<Matrix4x4f*>(stereo, out, view_index);
        return out;
    }""")
    change(hook, '    const auto true_index = index_starts_from_one ? ((index + 1) % 2) : (index % 2);',
        '    const auto true_index = VR::get()->is_using_duoview_mono() ? uevr::duoview::renderer_view_index(index, g_hook->m_has_double_precision)\n        : (index_starts_from_one ? ((index + 1) % 2) : (index % 2));')
    change(hook, '    if (index_was_ever_two && view_index == 0) {\n        SPDLOG_INFO_ONCE("calculate stereo view offset called with view index 0 after 2, ignoring.");',
        '    if (!vr->is_using_duoview_mono() && index_was_ever_two && view_index == 0) {\n        SPDLOG_INFO_ONCE("calculate stereo view offset called with view index 0 after 2, ignoring.");')
    change(hook, '    auto true_index = index_starts_from_one ? ((view_index + 1) % 2) : (view_index % 2);\n    const auto has_double_precision = g_hook->m_has_double_precision;',
        '    auto true_index = vr->is_using_duoview_mono() ? uevr::duoview::renderer_view_index(view_index, g_hook->m_has_double_precision)\n        : (index_starts_from_one ? ((view_index + 1) % 2) : (view_index % 2));\n    const auto has_double_precision = g_hook->m_has_double_precision;')
    change(hook, '        auto true_index = index_starts_from_one ? ((view_index + 1) % 2) : (view_index % 2);',
        '        auto true_index = vr->is_using_duoview_mono() ? uevr::duoview::renderer_view_index(view_index, g_hook->m_has_double_precision)\n            : (index_starts_from_one ? ((view_index + 1) % 2) : (view_index % 2));')
    change(hook, 'bool FFakeStereoRenderingHook::hook_game_viewport_client() try {',
        'bool FFakeStereoRenderingHook::hook_game_viewport_client() try {\n    m_has_game_viewport_client_draw_hook = false;')
    change(hook, '    m_has_game_viewport_client_draw_hook = true;\n\n    if (!m_gameviewportclient_draw_hook) {',
        '    if (!m_gameviewportclient_draw_hook) {')
    change(hook, """    if (auto enable_result = m_gameviewportclient_draw_hook.enable(); !enable_result.has_value()) {
        SPDLOG_ERROR("Failed to enable UGameViewportClient::Draw hook!");
        return false;
    }

    return true;""", """    if (auto enable_result = m_gameviewportclient_draw_hook.enable(); !enable_result.has_value()) {
        SPDLOG_ERROR("Failed to enable UGameViewportClient::Draw hook!");
        return false;
    }
    m_has_game_viewport_client_draw_hook = true;
    return true;""")
    change(hook,'    if (vr->is_using_mono()) { return 1; }','    if (vr->is_using_duoview_mono()) { return 2; }\n    if (vr->is_using_mono()) { return 1; }')
    change(hook,'    if (VR::get()->is_using_mono()) { *x = 0; *y = 0; return; }','''    if (VR::get()->is_using_duoview_mono()) {
        auto vr = VR::get();
        if (const auto frozen = vr->duoview_begin_frame()) {
            const auto& rect = true_index == frozen->config.settings.fovea_view
                ? frozen->config.layout.fovea : frozen->config.layout.periphery;
            *x = rect.x; *y = rect.y; *w = rect.width; *h = rect.height;
            vr->duoview_state().rectangle(frozen->config.key, true_index);
        }
        return;
    }
    if (VR::get()->is_using_mono()) { *x = 0; *y = 0; return; }''')
    change(hook, '    if (view_index == -1) {\n        index_was_ever_negative = true;', """    if (vr->is_using_duoview_mono() &&
        uevr::duoview::renderer_view_index(view_index, g_hook->m_has_double_precision) < 0) return;
    if (view_index == -1) {
        index_was_ever_negative = true;""")
    for block in [
        """    if (index == 2) {
        index_starts_from_one = true;
    } else if (index == 0) {
        index_starts_from_one = false;
    }""",
        """    if (view_index == 2) {
        index_starts_from_one = true;
        index_was_ever_two = true;
    } else if (view_index == 0 && !index_was_ever_two) {
        index_starts_from_one = false;
    }""",
        """    if (view_index == 2) {
        index_starts_from_one = true;
        index_was_ever_two = true;
    } else if (view_index == 0) {
        index_starts_from_one = false;
    }"""]:
        change(hook, block, '    if (!VR::get()->is_using_duoview_mono()) {\n' + '\n'.join('    '+line for line in block.splitlines()) + '\n    }')
    change(hook, '    const auto is_full_pass = view_index == 0 && !index_was_ever_two && !index_was_ever_negative && !g_hook->m_has_double_precision;',
        '    const auto is_full_pass = !vr->is_using_duoview_mono() && view_index == 0 && !index_was_ever_two && !index_was_ever_negative && !g_hook->m_has_double_precision;')
    change(hook,'    const bool mono = vr->is_using_mono();\n    if (mono && !is_full_pass) { true_index = 0; }','''    const auto duo_view = true_index;
    const auto duo_key = vr->duoview_key(vr->get_runtime()->internal_frame_count);
    if (vr->is_using_duoview_mono() && !is_full_pass && g_hook->is_in_viewport_client_draw()) {
        vr->duoview_begin_frame();
        if (const auto camera = vr->duoview_state().camera(duo_key, duo_view)) {
            if (has_double_precision) {
                rot_d->pitch = camera->rotation[0]; rot_d->yaw = camera->rotation[1]; rot_d->roll = camera->rotation[2];
                auto* p = reinterpret_cast<Vector3d*>(view_location);
                *p = Vector3d{camera->position[0], camera->position[1], camera->position[2]};
            } else {
                view_rotation->pitch = static_cast<float>(camera->rotation[0]);
                view_rotation->yaw = static_cast<float>(camera->rotation[1]);
                view_rotation->roll = static_cast<float>(camera->rotation[2]);
                *view_location = Vector3f{camera->position[0], camera->position[1], camera->position[2]};
            }
            vr->duoview_state().camera(duo_key, duo_view, *camera);
            return;
        }
    }
    const bool mono = vr->is_using_mono();
    if (mono && !is_full_pass) { true_index = 0; }''')
    change(hook,'    SPDLOG_INFO_ONCE("Finished calculating stereo view offset!");','''    SPDLOG_INFO_ONCE("Finished calculating stereo view offset!");''')
    anchor='''#ifdef FFAKE_STEREO_RENDERING_LOG_ALL_CALLS
    SPDLOG_INFO("Finished calculating stereo view offset!");'''
    change(hook,anchor,'''    if (vr->is_using_duoview_mono() && !is_full_pass && g_hook->is_in_viewport_client_draw()) {
        const auto* p = reinterpret_cast<const Vector3d*>(view_location);
        const uevr::duoview::CameraPose camera = has_double_precision
            ? uevr::duoview::CameraPose{{rot_d->pitch, rot_d->yaw, rot_d->roll}, {p->x, p->y, p->z}}
            : uevr::duoview::CameraPose{{view_rotation->pitch, view_rotation->yaw, view_rotation->roll},
                {view_location->x, view_location->y, view_location->z}};
        vr->duoview_state().camera(duo_key, duo_view, camera);
    }
'''+anchor)
    change(hook,'        if (vr->is_using_mono()) { true_index = 0; }','        const auto duo_view = true_index;\n        if (vr->is_using_mono()) { true_index = 0; }')
    anchor='''        if (vr->mono_frame_gate_required() && vr->get_runtime()->is_openxr()) {
            vr->get_openxr_runtime()->note_mono_projection();
        }'''
    change(hook,anchor,'''        if (vr->is_using_duoview_mono()) {
            if (const auto frozen = vr->duoview_begin_frame()) {
                Matrix4x4f full{};
                std::memcpy(&full[0][0], frozen->projection.data(), sizeof(full));
                if (g_hook->m_has_double_precision) {
                    double_matrix = full;
                    if (duo_view == frozen->config.settings.fovea_view)
                        uevr::duoview::apply_foveal_crop(double_matrix, frozen->config.layout);
                } else {
                    *out = full;
                    if (duo_view == frozen->config.settings.fovea_view)
                        uevr::duoview::apply_foveal_crop(*out, frozen->config.layout);
                }
                vr->duoview_state().projection(frozen->config.key, duo_view);
            }
        }
'''+anchor)
    anchor='''        vr->get_openxr_runtime()->note_mono_main_family(frame_count, main_family && views_ptr != nullptr && views_ptr->count == 1);'''
    change(hook,anchor,'''        const auto desired = vr->is_using_duoview_mono() ? 2 : 1;
        vr->get_openxr_runtime()->note_mono_main_family(frame_count, main_family && views_ptr != nullptr && views_ptr->count == desired);
        if (vr->is_using_duoview_mono())
            vr->duoview_state().family(vr->duoview_key(frame_count), main_family, views_ptr ? views_ptr->count : 0);''')
    dxheader='src/mods/vr/D3D12Component.hpp'
    change(dxheader,'#include "d3d12/TextureContext.hpp"','#include "d3d12/TextureContext.hpp"\n#include "DuoViewD3D12.hpp"')
    change(dxheader,'        std::unordered_map<uint32_t, SwapchainContext> contexts{};','        std::unordered_map<uint32_t, SwapchainContext> contexts{};\n        std::unordered_map<d3d12::CommandContext*, std::unique_ptr<uevr::duoview::dx12::Compositor>> duoview_compositors;')
    dxcpp='src/mods/vr/D3D12Component.cpp'
    change(dxcpp,'    this->contexts.clear();\n    vr->m_openxr->swapchains.clear();','    this->duoview_compositors.clear();\n    this->contexts.clear();\n    vr->m_openxr->swapchains.clear();')
    anchor='''                if (vr->is_using_mono()) {
                    bool recorded = false;'''
    change(dxcpp,anchor,'''                if (vr->is_using_duoview_mono()) {
                    const auto frame = vr->duoview_state().consume(vr->duoview_key(static_cast<uint32_t>(frame_count)));
                    bool recorded = false;
                    vr->m_openxr->note_mono_copy(static_cast<uint32_t>(frame_count), false);
                    if (frame) {
                        const bool submitted = m_openxr.copy(static_cast<uint32_t>(runtimes::OpenXR::SwapchainIndex::DOUBLE_WIDE), nullptr,
                            [this, source = backbuffer, device, frame, &recorded](d3d12::CommandContext& commands, ID3D12Resource* destination) {
                                auto& compositor = m_openxr.duoview_compositors[&commands];
                                if (!compositor) compositor = std::make_unique<uevr::duoview::dx12::Compositor>();
                                UINT64 frequency{};
                                g_framework->get_d3d12_hook()->get_command_queue()->GetTimestampFrequency(&frequency);
                                recorded = compositor->record(device, commands.cmd_list.Get(), source.Get(), destination,
                                    D3D12_RESOURCE_STATE_RENDER_TARGET, frame->config, frequency);
                                if (compositor->recorded_commands()) commands.has_commands = true;
                                VR::get()->note_duoview_gpu_ms(compositor->gpu_milliseconds());
                            }, std::nullopt, D3D12_RESOURCE_STATE_RENDER_TARGET, nullptr, backbuffer.Get());
                        vr->m_openxr->note_mono_copy(static_cast<uint32_t>(frame_count), submitted && recorded);
                        if (submitted && recorded) {
                            vr->set_mono_status("DuoView composite queued; headset validation required");
                            SPDLOG_INFO_EVERY_N_SEC(5, "[DuoView] frame={} fovea={}x{} peripheral={}x{} output={}x{} gaze={}",
                                frame_count, frame->config.layout.fovea.width, frame->config.layout.fovea.height,
                                frame->config.layout.periphery.width, frame->config.layout.periphery.height,
                                frame->config.layout.atlas_width/2, frame->config.layout.atlas_height, frame->gaze_valid);
                        } else vr->set_mono_status("Waiting: DuoView resource/format or GPU submission failed");
                    } else vr->set_mono_status("Waiting: incomplete or mismatched DuoView frame");
                } else if (vr->is_using_mono()) {
                    bool recorded = false;''')
    sdkh='dependencies/submodules/UESDK/src/sdk/FSceneView.hpp'
    sdkcpp='dependencies/submodules/UESDK/src/sdk/FSceneView.cpp'
    change(sdkh, 'struct FSceneViewFamily;', 'class FSceneViewFamily;')
    change(sdkh, """    sdk::FSceneViewFamily* get_view_family() const {
        // FSceneView inherits FSceneViewFixLayout, which has a virtual destructor
        // in UE 5.6+, so the Family pointer follows the vtable.
        return *(sdk::FSceneViewFamily**)((uintptr_t)this + sizeof(void*));
    }""", '    sdk::FSceneViewFamily* get_view_family() const;')
    change(sdkcpp, 'void FSceneViewInitOptionsBase::update_offsets(FSceneViewInitOptionsBase* options) {', """sdk::FSceneViewFamily* FSceneView::get_view_family() const {
    const auto layout = get_scene_view_init_layout();
    if (layout == FSceneViewInitLayout::UnsupportedNewer) return nullptr;
    const auto offset = layout == FSceneViewInitLayout::UE4_UE55 ? 0u : sizeof(void*);
    return *reinterpret_cast<sdk::FSceneViewFamily* const*>(reinterpret_cast<uintptr_t>(this) + offset);
}

void FSceneViewInitOptionsBase::update_offsets(FSceneViewInitOptionsBase* options) {""")
    for path, text in files.items():
        (root/path).write_text(text, encoding='utf-8', newline='\n')
    for name in ['DuoViewGeometry.hpp','DuoViewGaze.hpp','DuoViewFrame.hpp','DuoViewConfig.hpp',
                 'DuoViewState.hpp','DuoViewD3D12.hpp','DuoViewMonoCopyD3D12.hpp','PSVR2NativeGaze.hpp']:
        shutil.copyfile(source/name,root/'src/mods/vr'/name)
    shader=(source/'DuoViewCompositeRaster.hlsl').read_text().replace('#include "DuoViewComposite.hlsl"',(source/'DuoViewComposite.hlsl').read_text())
    (root/'src/mods/vr/DuoViewShaderSource.hpp').write_text('#pragma once\nnamespace uevr::duoview::dx12 {\ninline constexpr char shader_source[] = R"DUOVIEW_SHADER('+shader+')DUOVIEW_SHADER";\n}\n')
    print('Public Mono and DuoView rendering, PSVR2 gaze, immutable-pair and DX12 composition integration applied.')

if __name__=='__main__': main()
