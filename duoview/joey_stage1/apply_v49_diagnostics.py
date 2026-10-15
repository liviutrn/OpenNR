#!/usr/bin/env python3
"""Apply v49 diagnostic-only hooks after the pinned v48+Joey source patch.
Fail closed on any changed anchor. No UESDK edits, no NGX hook.
"""
from pathlib import Path
import sys

def replace(s,old,new,label):
    count=s.count(old)
    if count!=1: raise RuntimeError(f"v49 anchor {label}: expected once, found {count}")
    return s.replace(old,new,1)

def main():
    if len(sys.argv)!=3: raise RuntimeError("usage: apply_v49_diagnostics.py BACKEND DUOVIEW_SOURCE")
    backend,source=map(Path,sys.argv[1:])
    root=backend/"src/mods/vr"
    for name in ("DuoViewDiagnostic.hpp","DuoViewImageProbe.hpp"):
        destination=root/name
        if destination.exists(): raise RuntimeError("Diagnostic collision: "+str(destination))
        destination.write_bytes((source/name).read_bytes())
    def edit(path,fn):
        f=backend/path
        s=f.read_text(encoding="utf-8-sig")
        patched=fn(s)
        f.write_text(patched,encoding="utf-8",newline="")

    def vrh(s):
        s=replace(s,'#include "vr/DuoViewPSVR2Gaze.hpp"',
                  '#include "vr/DuoViewPSVR2Gaze.hpp"\n#include "vr/DuoViewDiagnostic.hpp"', "VR.hpp include")
        s=replace(s,'m_duo_smoothing{ModSlider::create(generate_name("DuoViewCropSmoothingMs"), 0.f, 250.f, 85.f)}',
                  'm_duo_smoothing{ModSlider::create(generate_name("DuoViewCropSmoothingMs"), 0.f, 250.f, 0.f)}',
                  "diag smoothing zero, no sensor lag")
        return s
    edit("src/mods/VR.hpp",vrh)
    def vrc(s):
        s=replace(s,'return m_duoview.begin(key, get_hmd_width(), get_hmd_height(), frozen,',
          'const auto result=m_duoview.begin(key, get_hmd_width(), get_hmd_height(), frozen,',"begin captured")
        s=replace(s,'[this, frozen, optical]() -> uevr::duoview::GazeSample {',
          '[this, frozen, optical, key]() -> uevr::duoview::GazeSample {',"frozen source key")
        s=replace(s,'return m_duoview_gaze.read_sample(frozen,optical);',
          'return uevr::duoview::diag::Recorder::get().source_gaze(key, m_duoview_gaze.read_sample(frozen,optical));',
          "synth gaze before projection")
        s=replace(s,'        }, GetTickCount64());',
          '''        }, GetTickCount64());
    if(result) {
        const auto sensor=m_duoview_gaze.observation();
        auto& recorder=uevr::duoview::diag::Recorder::get();
        recorder.cpu(0,0,*result,0,0,0,0,0,0,
            sensor.device_timestamp_raw,sensor.device_frame_counter,sensor.host_arrival_ms);
        SPDLOG_INFO_EVERY_N_SEC(1,
            "[DuoView][V49] frame={} phase={} gaze=({:.5f},{:.5f}) sensor_frame={} noHistory={} diagnostic_dir={}",
            key.frame,uevr::duoview::diag::phase_name(uevr::duoview::diag::phase_of(recorder.sequence(key.frame))),
            result->config.gaze.u,result->config.gaze.v,sensor.device_frame_counter,
            result->fovea_history_disabled,recorder.directory().string());
    }
    return result;''',"CPU frame + independent UEVR logger")
        return s
    edit("src/mods/VR.cpp",vrc)

    def constructor(s):
        anchor='    auto result = g_hook->m_sceneview_data.constructor_hook.unsafe_call<sdk::FSceneView*>(view, init_options, a3, a4);'
        pre='''    if (vr->is_duoview_renderer_active() && is_ue5 && init_options_ue5 && init_options_view_family) {
        const auto key=vr->duoview_producer_key();
        if (const auto snap=vr->duoview_state().snapshot(key)) {
            const unsigned idx=init_options_original_stereo_pass==EStereoscopicPass::eSSP_PRIMARY ? 0u : 1u;
            if (init_options_original_stereo_pass==EStereoscopicPass::eSSP_PRIMARY ||
                init_options_original_stereo_pass==EStereoscopicPass::eSSP_SECONDARY) {
                const auto& p=init_options_ue5->projection_matrix;
                uevr::duoview::diag::Recorder::get().cpu(1,idx,*snap,duo_fresh_fovea_applied?1u:0u,
                    reinterpret_cast<uintptr_t>(init_options_scene_state),
                    p[0][0],p[1][1],p[2][0],p[2][1]);
            }
        }
    }
'''
        s=replace(s,anchor,pre+anchor,"SceneView constructor input")
        anchor='''    if (duo_fresh_fovea_applied)
        init_options_ue5->scene_view_state=duo_saved_fovea_state;'''
        post='''    if (vr->is_duoview_renderer_active() && init_options_view_family) {
        const auto key=vr->duoview_producer_key();
        if (const auto snap=vr->duoview_state().snapshot(key)) {
            const unsigned idx=init_options_original_stereo_pass==EStereoscopicPass::eSSP_PRIMARY ? 0u : 1u;
            if (init_options_original_stereo_pass==EStereoscopicPass::eSSP_PRIMARY ||
                init_options_original_stereo_pass==EStereoscopicPass::eSSP_SECONDARY)
                uevr::duoview::diag::Recorder::get().cpu(2,idx,*snap,
                    (result!=nullptr?2u:0u)|(duo_fresh_fovea_applied?1u:0u),
                    reinterpret_cast<uintptr_t>(init_options_scene_state));
        }
    }'''
        return replace(s,anchor,anchor+"\n"+post,"SceneView post-construction")
    edit("src/mods/vr/FFakeStereoRenderingHook.cpp",constructor)

    def dx(s):
        anchor='                                    if (item->recorded_commands()) commands.has_commands = true;'
        s=replace(s,anchor,anchor+'''
                                    uevr::duoview::diag::Recorder::get().cpu(3,0,*frame,duo_recorded?1u:0u);''',
                  "GPU command trace")
        anchor='''                        if (duo_failed || !submitted || !recorded)
                            vr->duoview_abort("XR copy/composite fault; safe original Mono requested");'''
        s=replace(s,anchor,'''                        if (frame) uevr::duoview::diag::Recorder::get().cpu(
                            (submitted && recorded && duo_recorded) ? 4u : 7u,0,*frame,
                            (submitted && recorded && duo_recorded) ? 2u : 1u);
'''+anchor,"XR acceptance/fault trace")
        return s
    edit("src/mods/vr/D3D12Component.cpp",dx)

    def compositor(s):
        s=replace(s,'#include "DuoViewShaderSource.hpp"',
                  '#include "DuoViewShaderSource.hpp"\n#include "DuoViewImageProbe.hpp"',
                  "diagnostic image helper")
        s=replace(s,'        recorded_commands_ = false;',
                  '        probe_.harvest();\n        recorded_commands_ = false;',
                  "retired fence-safe readback")
        s=replace(s,'        transition(cmd, atlas, D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE, atlas_state);',
                  '        probe_.schedule(device, cmd, atlas, output_.Get(), frame);\n'
                  '        transition(cmd, atlas, D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE, atlas_state);',
                  "GPU capture before final composite copy")
        s=replace(s,'    std::string error_;',
                  '    uevr::duoview::diag::ImageProbe probe_;\n    std::string error_;',
                  "per-slot capture lifetime")
        return s
    edit("src/mods/vr/DuoViewD3D12.hpp",compositor)
    print("v49 diagnosis integration applied (CPU frame, UE inputs, async DX12 3-tile GPU and log redundancy).")

if __name__=="__main__": main()
