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
    std::optional<uevr::duoview::ViewFrame> duoview_begin_frame();
    void duoview_abort(const char* reason);''')
    edit(header,'    std::atomic<const char*> m_mono_status{"Not selected"};',
        '''    uevr::duoview::State m_duoview;
    uevr::duoview::psvr2::Reader m_duoview_gaze;
    std::atomic<bool> m_duoview_quarantined{false};
    std::once_flag m_duoview_settings_once;
    std::atomic<const char*> m_mono_status{"Not selected"};''')
    edit(header,'    void on_device_reset() override {\n        get_runtime()->on_device_reset();',
        '    void on_device_reset() override {\n        m_duoview.retire();\n        get_runtime()->on_device_reset();')
    cpp="src/mods/VR.cpp"
    edit(cpp,
        'ImGui::TextWrapped("DuoView Stage 1: rendering uses original Joey Mono unchanged. Two-view foveation and gaze are NOT active.");',
        'ImGui::TextWrapped(is_duoview_renderer_active() ? (duoview_gaze_active() ? "DuoView ID6: eye-tracked two-view Mono (PSVR2 Toolkit active)" : "DuoView ID6: two-view CENTER fallback (no fresh PSVR2 gaze)") : "DuoView ID6: original Joey Mono fallback / DuoView inactive");')
    edit(cpp, '#include "VR.hpp"', '#include "VR.hpp"\n#include <cstring>')
    edit(cpp,'    m_mono_main_view_token = 0;\n    m_mono_attachment_token = 0;',
        '    m_duoview.retire();\n    if (selection.active() == RenderingMethod::DUOVIEW_MONO) m_duoview_quarantined.store(false, std::memory_order_release);\n    m_mono_main_view_token = 0;\n    m_mono_attachment_token = 0;')
    changed[cpp]+='''
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
    std::call_once(m_duoview_settings_once, [this] {
        // 0.30x0.30 full-FOV crop at 2.5x output density.
        // Periphery is full field at 0.25x output resolution.
        if (!m_duoview.configure({.crop_width=.30f, .crop_height=.30f,
            .peripheral_scale=.25f, .foveal_density=2.5f,
            .feather_fraction=.08f, .debug_border=false,
            .eye_tracked=true, .fovea_view=1u})) {
            spdlog::error("[DuoView] Fixed-center settings rejected");
        }
    });
    const auto key = duoview_producer_key();
    if (auto found = m_duoview.snapshot(key)) return found;
    const auto projection = get_projection_matrix(VRRuntime::Eye::LEFT);
    std::array<float, 16> frozen{};
    std::memcpy(frozen.data(), &projection[0][0], sizeof(frozen));
    return m_duoview.begin(key, get_hmd_width(), get_hmd_height(), frozen,
        [this, frozen]() -> std::optional<uevr::duoview::UV> { return m_duoview_gaze.read_uv(frozen); });
}

void VR::duoview_abort(const char* reason) {
    if (!is_using_duoview_mono()) return;
    SPDLOG_WARNING_EVERY_N_SEC(2, "[DuoView] Quarantining two-view path; continuing original Mono inside ID6: {}", reason);
    m_duoview_quarantined.store(true, std::memory_order_release);
    m_duoview.retire();
    set_mono_status("DuoView fault: rendering original Mono inside ID6; reselect ID6 to retry");
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
            const auto& rect = index == 0 ? frame->config.layout.periphery : frame->config.layout.fovea;
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
    '''        const bool duo_fovea = vr->is_duoview_renderer_active() && g_hook->m_has_double_precision && view_index == 1;
        const bool duo_full = vr->is_duoview_renderer_active() && g_hook->m_has_double_precision && view_index == 0;
        if (vr->is_using_mono()) { true_index = 0; }

        auto& double_matrix = *(Matrix4x4d*)out;''')
    edit(hook,'''        if (vr->mono_frame_gate_required() && vr->get_runtime()->is_openxr()) {
            vr->get_openxr_runtime()->note_mono_projection();
        }''',
    '''        if (duo_fovea || duo_full) {
            if (const auto frame = vr->duoview_begin_frame()) {
                if (duo_fovea) uevr::duoview::apply_foveal_crop(double_matrix, frame->config.layout);
                vr->duoview_state().projection(frame->config.key, duo_fovea ? 1u : 0u);
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
    # Engine construction observes camera/rect/projection; a complete pair is
    # required before composition, not before we let the engine build its views.
    dxh="src/mods/vr/D3D12Component.hpp"
    edit(dxh,'#include "d3d12/TextureContext.hpp"',
        '#include "d3d12/TextureContext.hpp"\n#include "DuoViewD3D12.hpp"')
    edit(dxh,'        std::unordered_map<uint32_t, SwapchainContext> contexts{};',
        '''        std::unordered_map<uint32_t, SwapchainContext> contexts{};
        std::unordered_map<d3d12::CommandContext*, std::unique_ptr<uevr::duoview::dx12::Compositor>> duoview_compositors;''')
    dx="src/mods/vr/D3D12Component.cpp"
    edit(dx,'    this->contexts.clear();\n    vr->m_openxr->swapchains.clear();',
        '    this->duoview_compositors.clear();\n    this->contexts.clear();\n    vr->m_openxr->swapchains.clear();')
    edit(dx,'    this->contexts.clear();\n\n    auto create_swapchain',
        '    this->duoview_compositors.clear();\n    this->contexts.clear();\n\n    auto create_swapchain')
    edit(dx,'                    if (vr->is_using_mono()) {\n                        bool recorded = false;',
    '''                    if (vr->is_duoview_renderer_active()) {
                        bool recorded = false;
                        bool duo_recorded = false;
                        bool duo_failed = false;
                        const auto frame = vr->duoview_state().consume(
                            vr->duoview_key(static_cast<uint32_t>(frame_count)));
                        vr->m_openxr->note_mono_copy(static_cast<uint32_t>(frame_count), false);
                        // Do not skip the OpenXR copy if pair evidence fails.
                        // Emergency copy may be an incomplete atlas; quarantine ID6
                        // after this callback, then original Joey Mono on the next frame.
                        const bool submitted = m_openxr.copy(
                            (uint32_t)runtimes::OpenXR::SwapchainIndex::DOUBLE_WIDE, nullptr,
                            [this, source=backbuffer, scene_source_state, device, frame,
                             &recorded, &duo_recorded, &duo_failed](
                                d3d12::CommandContext& commands, ID3D12Resource* destination) {
                                if (!commands.ready()) return;
                                if (frame) {
                                    auto& item = m_openxr.duoview_compositors[&commands];
                                    if (!item) item = std::make_unique<uevr::duoview::dx12::Compositor>();
                                    duo_recorded = item->record(device, commands.cmd_list.Get(),
                                        source.Get(), destination, scene_source_state, frame->config);
                                    if (item->recorded_commands()) commands.has_commands = true;
                                }
                                if (!duo_recorded) {
                                    recorded = uevr::mono::dx12::copy_scene(
                                        commands.cmd_list.Get(), device, source.Get(), destination,
                                        scene_source_state, D3D12_RESOURCE_STATE_RENDER_TARGET);
                                    if (recorded) commands.has_commands = true;
                                    duo_failed = true; // handle after OpenXR copy returns
                                } else {
                                    recorded = true;
                                }
                            }, std::nullopt, scene_source_state, nullptr,
                            std::nullopt, backbuffer.Get());
                        vr->m_openxr->note_mono_copy(static_cast<uint32_t>(frame_count), submitted && recorded);
                        if (duo_failed || !submitted || !recorded)
                            vr->duoview_abort("XR copy/composite fault; safe original Mono requested");
                    } else if (vr->is_using_mono()) {
                        bool recorded = false;''')
    # Copy reference modules into exact checked-out Joey tree. No private SDK
    # declarations or altered SDK files.
    for name in ("DuoViewGeometry.hpp","DuoViewGaze.hpp","DuoViewPSVR2Gaze.hpp","DuoViewFrame.hpp",
                 "DuoViewConfig.hpp","DuoViewState.hpp","DuoViewD3D12.hpp",
                 "DuoViewMonoCopyD3D12.hpp"):
        target=root/"src/mods/vr"/name
        if target.exists(): raise RuntimeError("Refusing to overwrite prior source: "+str(target))
        text=(src/name).read_text(encoding="utf-8")
        if name=="DuoViewGeometry.hpp":
            # Put the full-FOV peripheral view first in atlas/camera order.
            text=replace(text,'.fovea = {0, 0, fw, fh},','.fovea = {pw, 0, fw, fh},',name)
            text=replace(text,'.periphery = {fw, 0, pw, ph},','.periphery = {0, 0, pw, ph},',name)
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
