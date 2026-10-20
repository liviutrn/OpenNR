#!/usr/bin/env python3
"""Apply the opt-in, stereo Quad Views overlay to pinned Build182 sources."""
from __future__ import annotations

import argparse
import shutil
from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one exact anchor, found {count}: {old[:100]!r}")
    return text.replace(old, new, 1)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("backend", type=Path)
    parser.add_argument("frontend", type=Path)
    parser.add_argument("overlay", type=Path, help="repository quadview/ directory")
    args = parser.parse_args()
    backend, frontend, overlay = args.backend, args.frontend, args.overlay

    changed: dict[Path, str] = {}

    def edit(root: Path, rel: str, before: str, after: str) -> None:
        path = root / rel
        current = changed.get(path, path.read_text(encoding="utf-8-sig"))
        changed[path] = replace_once(current, before, after, rel)

    # Keep ID 6 in the mono policy. ID 7 has a deferred renderer transition,
    # but retains two actual runtime eyes and never enters Mono pose overrides.
    edit(backend, "src/mods/vr/MonoRenderingPolicy.hpp",
        "inline constexpr int32_t duoview_method_id = 6;\nconstexpr bool is_mono_family(int32_t id) { return id == method_id || id == duoview_method_id; }",
        "inline constexpr int32_t duoview_method_id = 6;\ninline constexpr int32_t quadview_method_id = 7;\n"
        "constexpr bool is_mono_family(int32_t id) { return id == method_id || id == duoview_method_id; }\n"
        "constexpr bool is_deferred_family(int32_t id) { return is_mono_family(id) || id == quadview_method_id; }")
    edit(backend, "src/mods/vr/MonoRenderingPolicy.hpp",
        'Choice{duoview_method_id, "DuoView Mono (Eye Tracked - Experimental)"},\n};\ninline constexpr std::array non_dibr_choices {choices[0], choices[1], choices[2], choices[5], choices[6]};',
        'Choice{duoview_method_id, "DuoView Mono (Eye Tracked - Experimental)"},\n'
        '    Choice{quadview_method_id, "Quad Views Stereo (Experimental)"},\n};\n'
        'inline constexpr std::array non_dibr_choices {choices[0], choices[1], choices[2], choices[5], choices[6], choices[7]};')
    edit(backend, "src/mods/vr/MonoRenderingPolicy.hpp",
        "m_active = pack(is_mono_family(value) ? 0 : value, 0);",
        "m_active = pack(is_deferred_family(value) ? 0 : value, 0);")
    edit(backend, "src/mods/vr/MonoRenderingPolicy.hpp",
        "if (!is_mono_family(active()) && !is_mono_family(value)) {",
        "if (!is_deferred_family(active()) && !is_deferred_family(value)) {")
    edit(backend, "src/mods/vr/CompatibilityPolicy.hpp",
        "    DuoViewMono = 6,\n};", "    DuoViewMono = 6,\n    QuadViewsStereo = 7,\n};")

    # The two eye methods (Mono and DuoView) remain the only Mono policy.
    # Existing generic Native gates already keep ID 7 outside Mono.
    edit(backend, "src/mods/vr/CompatibilityPolicy.hpp",
        "if (method == RenderingMethod::Mono || method == RenderingMethod::DuoViewMono) { return false; }",
        "if (method == RenderingMethod::Mono || method == RenderingMethod::DuoViewMono ||\n"
        "        method == RenderingMethod::QuadViewsStereo) { return false; }")
    edit(backend, "tests/MonoRenderingTests.hpp",
        "for (int id = 0; id != 7; ++id) {\n        expect(m::available(id), \"DIBR build retains every serialized rendering ID\");\n"
        "        expect(m::available(id, m::non_dibr_choices) == (id < 3 || id == 5 || id == 6),\n"
        "            \"non-DIBR Mono remains ID 5; gaps are not exposed or renumbered\");\n    }",
        "for (int id = 0; id != 8; ++id) {\n        expect(m::available(id), \"DIBR build retains every serialized rendering ID\");\n"
        "        expect(m::available(id, m::non_dibr_choices) == (id < 3 || id == 5 || id == 6 || id == 7),\n"
        "            \"non-DIBR preserves Mono IDs and exposes stereo Quad Views as ID 7\");\n    }")
    edit(backend, "tests/MonoRenderingTests.hpp",
        'expect(!m::available(-1) && !m::available(7), "unsupported IDs are identified, never clamped into Mono");',
        'expect(!m::available(-1) && !m::available(8), "unsupported IDs are identified, never clamped into Mono");')
    edit(backend, "tests/MonoRenderingTests.hpp",
        'expect(m::is_mono_family(5) && m::is_mono_family(6) && !m::is_mono_family(0),\n'
        '        "original Mono and DuoView fallback share the safe Mono lifecycle, other modes do not");',
        'expect(m::is_mono_family(5) && m::is_mono_family(6) && !m::is_mono_family(0) &&\n'
        '        !m::is_mono_family(7) && m::is_deferred_family(7),\n'
        '        "Quad Views has deferred transitions but remains outside the Mono eye path");')
    edit(backend, "tests/MonoRenderingTests.hpp",
        'expect(!p::is_using_afr(p::RenderingMethod::DuoViewMono, true),\n'
        '        "DuoView fallback cannot accidentally activate AFR even if an old profile requests it");',
        'expect(!p::is_using_afr(p::RenderingMethod::DuoViewMono, true),\n'
        '        "DuoView fallback cannot accidentally activate AFR even if an old profile requests it");\n'
        '    expect(!p::is_using_afr(p::RenderingMethod::QuadViewsStereo, true),\n'
        '        "Quad Views cannot inherit AFR semantics from Extreme Compatibility");')
    edit(backend, "tests/MonoRenderingTests.hpp",
        '    {\n        m::Selection duo;',
        '    {\n        m::Selection quad;\n'
        '        quad.initialize(7);\n'
        '        expect(quad.active() == 0 && quad.pending(), "Quad Views startup defers renderer activation");\n'
        '        quad.consumers_retired(quad.request_token());\n'
        '        expect(quad.commit_at_game_frame_boundary() && quad.active() == 7 && quad.generation() == 1,\n'
        '            "Quad Views commits only after retired consumers at a game-frame boundary");\n'
        '        quad.request(0);\n'
        '        expect(quad.active() == 7 && quad.pending(), "Quad Views exit waits for old renderer retirement");\n'
        '    }\n'
        '    {\n        m::Selection duo;')
    edit(backend, "src/mods/VR.hpp",
        "        DUOVIEW_MONO = uevr::mono::duoview_method_id,\n    };",
        "        DUOVIEW_MONO = uevr::mono::duoview_method_id,\n"
        "        QUAD_VIEWS_STEREO = uevr::mono::quadview_method_id,\n    };")
    edit(backend, "src/mods/VR.hpp",
        '#include "vr/DuoViewState.hpp"',
        '#include "vr/DuoViewState.hpp"\n#include "vr/QuadViewProducer.hpp"\n#include "vr/QuadViewViewDemand.hpp"\n'
        '#include "vr/QuadViewSettings.hpp"\n#include "vr/QuadViewGaze.hpp"\n'
        '#include "vr/QuadViewPSVR2Gaze.hpp"\n#include "vr/DuoViewCropStability.hpp"')
    edit(backend, "src/mods/VR.hpp",
        "    bool is_using_mono() const { return uevr::mono::is_mono_family(m_rendering_method->value()); }\n"
        "    bool is_using_duoview_mono() const { return m_rendering_method->value() == RenderingMethod::DUOVIEW_MONO; }\n"
        "    bool is_duoview_renderer_active() const;",
        "    bool is_using_mono() const { return uevr::mono::is_mono_family(m_rendering_method->value()); }\n"
        "    bool is_using_duoview_mono() const { return m_rendering_method->value() == RenderingMethod::DUOVIEW_MONO; }\n"
        "    bool is_quadview_mode_selected() const { return m_rendering_method->value() == RenderingMethod::QUAD_VIEWS_STEREO; }\n"
        "    bool is_quadview_layout_active() const;\n"
        "    bool is_quadview_supported_title() const;\n"
        "    bool is_quadview_renderer_active() const;\n"
        "    const char* quadview_unavailable_reason() const;\n"
        "    bool is_duoview_renderer_active() const;")
    edit(backend, "src/mods/VR.hpp",
        "    void duoview_start_draw() {\n        m_duoview_draw_serial.fetch_add(1, std::memory_order_acq_rel);\n"
        "        m_duoview_candidate_key.store(nullptr, std::memory_order_release);\n"
        "        m_duoview_frozen_key.store(nullptr, std::memory_order_release);\n    }",
        "    void duoview_start_draw() {\n        m_duoview_draw_serial.fetch_add(1, std::memory_order_acq_rel);\n"
        "        m_duoview_candidate_key.store(nullptr, std::memory_order_release);\n"
        "        m_duoview_frozen_key.store(nullptr, std::memory_order_release);\n"
        "        m_quadview_draw_serial.fetch_add(1, std::memory_order_acq_rel);\n"
        "        m_quadview_candidate_key.store(nullptr, std::memory_order_release);\n"
        "        { std::scoped_lock lock{m_quadview_layout_mutex}; m_quadview_draw_config.reset(); m_quadview_draw_config_key={}; }\n"
        "        { std::scoped_lock lock{m_quadview_pose_mutex}; m_quadview_pose.reset(); m_quadview_pose_key={}; m_quadview_pose_eye_mask=0; }\n"
        "        const auto key=quadview_key();\n"
        "        m_quadview_draw_demand.begin(key.generation,key.draw_serial,is_quadview_mode_selected(),is_mono_transition_pending(),\n"
        "            m_rendering_method->selection().request_token());\n    }\n"
        "    uevr::quadview::Key quadview_key() const {\n"
        "        return {mono_generation(), m_quadview_draw_serial.load(std::memory_order_acquire)};\n    }\n"
        "    uevr::quadview::Key quadview_producer_key() const {\n"
        "        const auto candidate=m_quadview_candidate_key.load(std::memory_order_acquire);\n"
        "        return candidate && candidate->generation==mono_generation() ? *candidate : quadview_key();\n    }\n"
        "    uevr::quadview::Producer& quadview_producer() { return m_quadview; }\n"
        "    const uevr::quadview::Producer& quadview_producer() const { return m_quadview; }\n"
        "    std::optional<uevr::quadview::Layout> quadview_layout_for_hooks();\n"
        "    std::optional<uevr::quadview::Snapshot> quadview_begin_frame();\n"
        "    std::optional<uevr::quadview::gaze::Projection> quadview_base_projection(uevr::quadview::Key key,uint32_t eye) const {\n"
        "        std::scoped_lock lock{m_quadview_layout_mutex};\n"
        "        return eye<2 && m_quadview_draw_config_key==key && m_quadview_draw_config && m_quadview_draw_config->base_projection_valid\n"
        "            ? std::optional<uevr::quadview::gaze::Projection>{m_quadview_draw_config->projections[eye]} : std::nullopt;\n"
        "    }\n"
        "    unsigned quadview_desired_view_count() const {\n"
        "        const auto key=quadview_key();\n"
        "        const auto demand=m_quadview_draw_demand.get(key.generation,key.draw_serial);\n"
        "        return demand ? demand->view_count : 2u;\n    }\n"
        "    bool quadview_transition_draw_closed() const {\n"
        "        const auto& selection=m_rendering_method->selection();\n"
        "        const auto key=quadview_key();\n"
        "        return m_quadview_draw_demand.transition_closed(key.generation,key.draw_serial,\n"
        "            selection.request_token(),is_quadview_mode_selected(),selection.pending());\n    }\n"
        "    bool quadview_note_eye_pose(uint32_t eye) {\n"
        "        if (eye > 1 || !is_quadview_renderer_active() || m_openxr == nullptr) return false;\n"
        "        const auto key=quadview_key();\n"
        "        std::scoped_lock lock{m_quadview_pose_mutex};\n"
        "        if (m_quadview_pose_key != key || !m_quadview_pose || m_quadview_pose->stage_views.size()!=2 ||\n"
        "            m_quadview_pose->frame_state.predictedDisplayTime<=0 || m_quadview_pose->frame_state.shouldRender!=XR_TRUE) return false;\n"
        "        const auto current=m_openxr->capture_quadview_current_pose();\n"
        "        if (!current || current->frame_count!=m_quadview_pose->frame_count ||\n"
        "            current->frame_state.predictedDisplayTime!=m_quadview_pose->frame_state.predictedDisplayTime ||\n"
        "            current->frame_state.predictedDisplayPeriod!=m_quadview_pose->frame_state.predictedDisplayPeriod ||\n"
        "            current->frame_state.shouldRender!=m_quadview_pose->frame_state.shouldRender ||\n"
        "            current->coherent_sequence!=m_quadview_pose->coherent_sequence ||\n"
        "            current->coherent_source_frame_count!=m_quadview_pose->coherent_source_frame_count ||\n"
        "            current->coherent_display_time!=m_quadview_pose->coherent_display_time ||\n"
        "            current->view_space_location.locationFlags!=m_quadview_pose->view_space_location.locationFlags) return false;\n"
        "        const auto same_pose=[](const XrPosef& a,const XrPosef& b) {\n"
        "            return a.position.x==b.position.x && a.position.y==b.position.y && a.position.z==b.position.z &&\n"
        "                a.orientation.x==b.orientation.x && a.orientation.y==b.orientation.y &&\n"
        "                a.orientation.z==b.orientation.z && a.orientation.w==b.orientation.w;\n        };\n"
        "        const auto& frozen_head=m_quadview_pose->view_space_location.pose;\n"
        "        if (!same_pose(current->view_space_location.pose,frozen_head)) return false;\n"
        "        for (size_t i=0;i!=2;++i) {\n"
        "            const auto& a=current->stage_views[i]; const auto& b=m_quadview_pose->stage_views[i];\n"
        "            if (!same_pose(a.pose,b.pose) || a.fov.angleLeft!=b.fov.angleLeft ||\n"
        "                a.fov.angleRight!=b.fov.angleRight || a.fov.angleUp!=b.fov.angleUp ||\n"
        "                a.fov.angleDown!=b.fov.angleDown) return false;\n        }\n"
        "        m_quadview_pose_eye_mask |= static_cast<uint8_t>(1u << eye);\n"
        "        return true;\n"
        "    }\n"
        "    std::optional<runtimes::OpenXR::PipelineState> quadview_frozen_pose(uevr::quadview::Key key) const {\n"
        "        std::scoped_lock lock{m_quadview_pose_mutex};\n"
        "        return m_quadview_pose_key == key && m_quadview_pose_eye_mask == 0x03 ? m_quadview_pose : std::nullopt;\n"
        "    }\n"
        "    uint8_t quadview_pose_mask() const { std::scoped_lock lock{m_quadview_pose_mutex}; return m_quadview_pose_eye_mask; }\n"
        "    void set_quadview_status(const char* text) { m_quadview_status.store(text, std::memory_order_release); }\n"
        "    const char* quadview_status() const { return m_quadview_status.load(std::memory_order_acquire); }\n"
        "    void note_quadview_gpu_ms(float value) { if (std::isfinite(value)) m_quadview_gpu_ms.store(value,std::memory_order_release); }\n"
        "    float quadview_gpu_ms() const { return m_quadview_gpu_ms.load(std::memory_order_acquire); }")
    edit(backend, "src/mods/VR.hpp",
        "    bool is_using_afr() const {\n        if (is_using_mono()) { return false; }",
        "    bool is_using_afr() const {\n        if (is_using_mono() || is_quadview_mode_selected()) { return false; }")
    edit(backend, "src/mods/VR.hpp",
        "    bool is_depth_enabled() const {\n        return !is_using_mono() && m_enable_depth->value();\n    }",
        "    bool is_depth_enabled() const {\n        return !is_using_mono() && !is_quadview_mode_selected() && m_enable_depth->value();\n    }")
    edit(backend, "src/mods/VR.hpp",
        "    bool is_splitscreen_compatibility_enabled() const {\n        if (is_using_mono()) { return false; }",
        "    bool is_splitscreen_compatibility_enabled() const {\n        if (is_using_mono() || is_quadview_mode_selected()) { return false; }")
    edit(backend, "src/mods/VR.hpp",
        "    bool is_sceneview_compatibility_enabled() const {\n        if (is_using_mono()) { return false; }",
        "    bool is_sceneview_compatibility_enabled() const {\n        if (is_using_mono() || is_quadview_mode_selected()) { return false; }")
    edit(backend, "src/mods/VR.hpp",
        "    bool is_native_stereo_fix_enabled() const {\n        if (is_mono_transition_quiescing()) { return false; }",
        "    bool is_native_stereo_fix_enabled() const {\n        if (is_quadview_mode_selected() || is_mono_transition_quiescing()) { return false; }")
    edit(backend, "src/mods/VR.hpp",
        "    bool is_ghosting_fix_enabled() const {\n        if (is_using_mono() || is_mono_transition_quiescing()) { return false; }",
        "    bool is_ghosting_fix_enabled() const {\n        if (is_using_mono() || is_quadview_mode_selected() || is_mono_transition_quiescing()) { return false; }")
    edit(backend, "src/mods/VR.hpp",
        "    bool is_ghosting_fix_bootstrap_enabled() const {\n        return !is_using_mono() && !is_mono_transition_quiescing() && m_ghosting_fix_bootstrap_view_states->value();\n    }",
        "    bool is_ghosting_fix_bootstrap_enabled() const {\n        return !is_using_mono() && !is_quadview_mode_selected() && !is_mono_transition_quiescing() && m_ghosting_fix_bootstrap_view_states->value();\n    }")
    edit(backend, "src/mods/VR.hpp",
        "    bool is_using_2d_screen() const {\n        return m_2d_screen_mode->value();\n    }",
        "    bool is_using_2d_screen() const {\n        return !is_quadview_mode_selected() && m_2d_screen_mode->value();\n    }")
    edit(backend, "src/mods/VR.hpp",
        "    bool is_extreme_compatibility_mode_enabled() const {\n        return m_extreme_compat_mode->value();\n    }",
        "    bool is_extreme_compatibility_mode_enabled() const {\n        return !is_quadview_mode_selected() && m_extreme_compat_mode->value();\n    }")
    edit(backend, "src/mods/VR.hpp",
        '    const ModInt32::Ptr m_duo_relock{ModSliderInt32::create(generate_name("DuoViewGazeRelockSamples"), 1, 10, 3)};',
        '    const ModInt32::Ptr m_duo_relock{ModSliderInt32::create(generate_name("DuoViewGazeRelockSamples"), 1, 10, 3)};\n'
        '    const ModSlider::Ptr m_quadview_crop_width{ModSlider::create(generate_name("QuadViewFocusWidth"), .05f, 1.f, .50f)};\n'
        '    const ModSlider::Ptr m_quadview_crop_height{ModSlider::create(generate_name("QuadViewFocusHeight"), .05f, 1.f, .50f)};\n'
        '    const ModSlider::Ptr m_quadview_context_scale{ModSlider::create(generate_name("QuadViewContextScale"), .05f, .50f, .20f)};\n'
        '    const ModSlider::Ptr m_quadview_foveal_density{ModSlider::create(generate_name("QuadViewFovealDensity"), .25f, 4.f, 1.f)};\n'
        '    const ModSlider::Ptr m_quadview_feather{ModSlider::create(generate_name("QuadViewFeather"), 0.f, .45f, .08f)};\n'
        '    const ModSlider::Ptr m_quadview_sharpen{ModSlider::create(generate_name("QuadViewSharpen"), 0.f, 2.f, 1.f)};\n'
        '    const ModToggle::Ptr m_quadview_gpu_timing{ModToggle::create(generate_name("QuadViewGpuTiming"), false)};\n'
        '    const ModToggle::Ptr m_quadview_eye_tracking{ModToggle::create(generate_name("QuadViewEyeTracking"), true)};\n'
        '    const ModToggle::Ptr m_quadview_debug_border{ModToggle::create(generate_name("QuadViewDebugBorder"), false)};\n'
        '    const ModInt32::Ptr m_quadview_debug_mode{ModSliderInt32::create(generate_name("QuadViewDebugMode"), 0, 3, 0)};\n'
        '    const ModToggle::Ptr m_quadview_stabilize_crop{ModToggle::create(generate_name("QuadViewCropStabilization"), true)};\n'
        '    const ModSlider::Ptr m_quadview_guard{ModSlider::create(generate_name("QuadViewGazeGuard"), 0.f, .05f, .05f)};\n'
        '    const ModInt32::Ptr m_quadview_gaze_quant{ModSliderInt32::create(generate_name("QuadViewGazeQuantization"), 0, 16, 2)};\n'
        '    const ModInt32::Ptr m_quadview_gaze_hold{ModSliderInt32::create(generate_name("QuadViewGazeHoldMs"), 50, 2000, 350)};\n'
        '    const ModInt32::Ptr m_quadview_gaze_reacquire{ModSliderInt32::create(generate_name("QuadViewGazeReacquireSamples"), 1, 4, 2)};\n'
        '    const ModSlider::Ptr m_quadview_gaze_offset_u{ModSlider::create(generate_name("QuadViewGazeOffsetU"), -.25f, .25f, 0.f)};\n'
        '    const ModSlider::Ptr m_quadview_gaze_offset_v{ModSlider::create(generate_name("QuadViewGazeOffsetV"), -.25f, .25f, 0.f)};\n'
        '    const ModSlider::Ptr m_quadview_gaze_micro_gain{ModSlider::create(generate_name("QuadViewGazeMicroGain"), 0.f, 1.f, 0.f)};\n'
        '    const ModSlider::Ptr m_quadview_gaze_breakout{ModSlider::create(generate_name("QuadViewGazeBreakout"), .005f, .25f, .035f)};\n'
        '    const ModSlider::Ptr m_quadview_gaze_still{ModSlider::create(generate_name("QuadViewGazeStillRadius"), 0.f, .05f, .008f)};\n'
        '    const ModInt32::Ptr m_quadview_gaze_relock{ModSliderInt32::create(generate_name("QuadViewGazeRelockSamples"), 1, 10, 3)};')
    edit(backend, "src/mods/VR.hpp",
        "    std::once_flag m_duoview_settings_once;",
        "    std::once_flag m_duoview_settings_once;\n"
        "    uevr::quadview::Producer m_quadview;\n"
        "    struct QuadViewDrawConfig { uevr::quadview::Settings settings{}; uint64_t settings_revision{}; bool gaze_valid{},base_projection_valid{}; uevr::quadview::GazeEvidence gaze{};\n"
        "        std::array<uevr::quadview::gaze::Projection,2> projections{}; };\n"
        "    std::atomic<uint64_t> m_quadview_draw_serial{};\n"
        "    uevr::quadview::DrawDemandLatch m_quadview_draw_demand{};\n"
        "    std::atomic<std::shared_ptr<const uevr::quadview::Key>> m_quadview_candidate_key{};\n"
        "    mutable std::mutex m_quadview_layout_mutex{};\n"
        "    uevr::quadview::LayoutLatch m_quadview_layout_latch{};\n"
        "    uevr::quadview::Key m_quadview_draw_config_key{};\n"
        "    std::optional<QuadViewDrawConfig> m_quadview_draw_config{};\n"
        "    uevr::quadview::Settings m_quadview_applied_settings{};\n"
        "    uint64_t m_quadview_settings_revision{1};\n"
        "    std::atomic<uint32_t> m_quadview_rejected_settings{};\n"
        "    std::atomic<bool> m_quadview_dimension_fallback{};\n"
        "    std::atomic<float> m_quadview_gpu_ms{-1.f};\n"
        "    uevr::quadview::psvr2::Reader m_quadview_gaze{};\n"
        "    std::array<uevr::duoview::CropStability,2> m_quadview_crop_stability{};\n"
        "    mutable std::mutex m_quadview_pose_mutex{};\n"
        "    uevr::quadview::Key m_quadview_pose_key{};\n"
        "    std::optional<runtimes::OpenXR::PipelineState> m_quadview_pose{};\n"
        "    uint8_t m_quadview_pose_eye_mask{};\n"
        "    std::atomic<const char*> m_quadview_status{\"Waiting for four engine view histories\"};")
    edit(backend, "src/mods/VR.hpp",
        "    bool mono_frame_gate_required() const {\n        const auto state = m_rendering_method->selection().snapshot();\n"
        "        return uevr::mono::needs_frame_gate(state.method, state.generation, m_mono_ready_generation.load(std::memory_order_acquire));\n    }",
        "    bool mono_frame_gate_required() const {\n        if (is_quadview_mode_selected()) return false;\n"
        "        const auto state = m_rendering_method->selection().snapshot();\n"
        "        return uevr::mono::needs_frame_gate(state.method, state.generation, m_mono_ready_generation.load(std::memory_order_acquire));\n    }")
    edit(backend, "src/mods/VR.hpp",
        "    void on_device_reset() override {\n        m_duoview.retire();",
        "    void on_device_reset() override {\n        m_duoview.retire();\n        m_quadview.retire_all();")

    edit(backend, "src/mods/VR.cpp",
        "const char* VR::mono_unavailable_reason() const {",
        "bool VR::is_quadview_supported_title() const {\n"
        "    // Hook installation occurs at startup, before ID7 is selected.\n"
        "    // Cache title support independently of the active rendering mode.\n"
        "    static const bool stalker2_ue55 = [] {\n"
        "        const auto path=utility::get_module_pathw(utility::get_executable());\n"
        "        const auto detected_version=sdk::search_for_version(utility::get_executable()).value_or(L\"0.00\");\n"
        "        const auto file_version=sdk::get_file_version_info();\n"
        "        return path && uevr::games::is_stalker2_ue55_runtime(*path,detected_version,file_version.dwFileVersionMS);\n"
        "    }();\n"
        "    return stalker2_ue55;\n"
        "}\n\n"
        "const char* VR::quadview_unavailable_reason() const {\n"
        "    if (!is_quadview_mode_selected() && requested_rendering_method() != RenderingMethod::QUAD_VIEWS_STEREO) return nullptr;\n"
        "    if (!m_is_d3d12 || g_framework == nullptr || !g_framework->is_dx12()) return \"Quad Views requires DX12\";\n"
        "    const auto runtime = get_runtime();\n"
        "    if (runtime == nullptr || !runtime->is_openxr()) return \"Quad Views requires OpenXR\";\n"
        "    if (!is_quadview_supported_title()) return \"Quad Views currently supports STALKER 2 UE5.5 only\";\n"
        "    if (!m_fake_stereo_hook || !m_fake_stereo_hook->quadview_view_extensions_ready())\n"
        "        return \"Quad Views warming up: scene-view constructor hook is not ready\";\n"
        "    // Stay in the previous working rendering mode until the real renderer\n"
        "    // entry callback has executed. ID7 OpenXR requires a four-view image.\n"
        "    if (!m_fake_stereo_hook || !m_fake_stereo_hook->quadview_outer_renderer_observed())\n"
        "        return \"Quad Views warming up: outer renderer interception not observed\";\n"
        "    if (m_extreme_compat_mode->value() || m_splitscreen_compatibility_mode->value() || m_2d_screen_mode->value() ||\n"
        "        m_sceneview_compatibility_mode->value() || m_stereo_emulation_mode) return \"Quad Views requires Extreme Compatibility, split-screen, 2D Screen, SceneView compatibility and Stereo Emulation OFF\";\n"
        "    if (uevr::nascar::is_target()) return \"Quad Views is unavailable for this title's restricted rendering path\";\n"
        "    return nullptr;\n}\n\n"
        "const char* VR::mono_unavailable_reason() const {")

    edit(backend, "src/mods/VR.cpp",
        "bool VR::is_duoview_renderer_active() const {",
        "bool VR::is_quadview_renderer_active() const {\n"
        "    return is_quadview_layout_active() && quadview_unavailable_reason() == nullptr;\n}\n\n"
        "bool VR::is_quadview_layout_active() const {\n"
        "    const auto key=quadview_key();\n"
        "    const auto demand=m_quadview_draw_demand.get(key.generation,key.draw_serial);\n"
        "    return demand && demand->source_admission;\n}\n\n"
        "bool VR::is_duoview_renderer_active() const {")
    edit(backend, "src/mods/VR.cpp",
        "void VR::service_mono_transition_game_thread() {\n    auto& selection = m_rendering_method->selection();\n"
        "    if (!selection.pending()) { return; }\n"
        "    if (uevr::mono::is_mono_family(selection.requested()) && mono_unavailable_reason() != nullptr) { return; }",
        "void VR::service_mono_transition_game_thread() {\n    auto& selection = m_rendering_method->selection();\n"
        "    if (!selection.pending()) { return; }\n"
        "    if (uevr::mono::is_mono_family(selection.requested()) && mono_unavailable_reason() != nullptr) { return; }\n"
        "    if (selection.requested() == RenderingMethod::QUAD_VIEWS_STEREO && quadview_unavailable_reason() != nullptr) return;")
    edit(backend, "src/mods/VR.cpp",
        "    if (!selection.commit_at_game_frame_boundary()) { return; }\n    m_duoview.retire();\n    if (m_fake_stereo_hook) m_fake_stereo_hook->duoview_delivery.retire(mono_generation());",
        "    if (is_quadview_mode_selected() && (!quadview_transition_draw_closed() || !m_fake_stereo_hook ||\n"
        "        !m_fake_stereo_hook->quadview_delivery.engine_commands_retired(mono_generation()))) {\n"
        "        set_quadview_status(quadview_transition_draw_closed()\n"
        "            ? \"Waiting for tracked render-thread/RHI owners to execute at mode commit\"\n"
        "            : \"Waiting for the active viewport draw to latch a closed ID7 admission boundary\");\n"
        "        return;\n    }\n"
        "    if (!selection.commit_at_game_frame_boundary()) { return; }\n"
        "    const auto retired_generation = mono_generation() - 1;\n"
        "    m_duoview.retire();\n"
        "    if (m_fake_stereo_hook) {\n"
        "        m_fake_stereo_hook->duoview_delivery.retire(mono_generation());\n"
        "        m_fake_stereo_hook->quadview_delivery.retire_generation(retired_generation);\n    }\n"
        "    m_quadview.retire_generation(retired_generation);")
    edit(backend, "src/mods/VR.cpp",
        "    m_duoview_frozen_key.store(nullptr, std::memory_order_release);\n    m_duo_shading->value()=false;",
        "    m_duoview_frozen_key.store(nullptr, std::memory_order_release);\n"
        "    m_quadview_candidate_key.store(nullptr, std::memory_order_release);\n"
        "    m_duo_shading->value()=false;")
    edit(backend, "src/mods/VR.cpp",
        "void VR::duoview_abort(const char* reason) {",
        "std::optional<uevr::quadview::Snapshot> VR::quadview_begin_frame() {\n"
        "    const bool renderer_active=is_quadview_renderer_active();\n"
        "    const bool hook_available=m_fake_stereo_hook!=nullptr;\n"
        "    const bool viewport_draw=hook_available && m_fake_stereo_hook->is_in_viewport_client_draw();\n"
        "    if (!renderer_active || !viewport_draw) {\n"
        "        const char* reason=!is_quadview_mode_selected() ? \"mode_not_selected\" :\n"
        "            !hook_available ? \"fake_stereo_hook_unavailable\" :\n"
        "            !renderer_active ? \"renderer_not_active\" : \"not_viewport_draw\";\n"
        "        SPDLOG_WARNING_EVERY_N_SEC(2,\"[QuadViews][GTBegin][per-call-throttled] reason={} unavailable={} generation={} draw={} frame={}\",\n"
        "            reason,quadview_unavailable_reason() ? quadview_unavailable_reason() : \"none\",\n"
        "            mono_generation(),m_quadview_draw_serial.load(std::memory_order_acquire),m_render_frame_count);\n"
        "        return {};\n    }\n"
        "    const auto key = quadview_key();\n"
        "    if (key.generation == 0 || key.draw_serial == 0) {\n"
        "        SPDLOG_WARNING_EVERY_N_SEC(2,\"[QuadViews][GTBegin][per-call-throttled] reason=invalid_key generation={} draw={} frame={}\",\n"
        "            key.generation,key.draw_serial,m_render_frame_count);\n"
        "        return {};\n    }\n"
        "    if (const auto candidate = m_quadview_candidate_key.load(std::memory_order_acquire);\n"
        "        candidate && *candidate == key) {\n"
        "        if (const auto snapshot = m_quadview.snapshot(key)) return snapshot;\n"
        "        SPDLOG_WARNING_EVERY_N_SEC(2,\"[QuadViews][GTBegin][per-call-throttled] reason=duplicate_candidate_without_snapshot generation={} draw={} frame={}\",\n"
        "            key.generation,key.draw_serial,m_render_frame_count);\n"
        "        return {};\n"
        "    }\n"
        "    std::optional<uevr::quadview::Layout> layout;\n"
        "    QuadViewDrawConfig draw_config{};\n"
        "    {\n"
        "        std::scoped_lock lock{m_quadview_layout_mutex};\n"
        "        if (m_quadview_draw_config_key==key && m_quadview_draw_config) {\n"
        "            draw_config=*m_quadview_draw_config;\n"
        "            layout=m_quadview_layout_latch.get(key.generation,key.draw_serial);\n"
        "        } else {\n"
        "            const auto width=get_hmd_width(), height=get_hmd_height();\n"
        "            uevr::quadview::Settings requested{};\n"
        "            requested.crop_width=m_quadview_crop_width->value();\n"
        "            requested.crop_height=m_quadview_crop_height->value();\n"
        "            requested.context_scale=m_quadview_context_scale->value();\n"
        "            requested.foveal_density=m_quadview_foveal_density->value();\n"
        "            requested.feather_fraction=m_quadview_feather->value();\n"
        "            requested.sharpen_strength=m_quadview_sharpen->value();\n"
        "            requested.gpu_timing=m_quadview_gpu_timing->value();\n"
        "            requested.debug_border=m_quadview_debug_border->value();\n"
        "            requested.eye_tracked=m_quadview_eye_tracking->value();\n"
        "            requested.diagnostic_view=static_cast<uint32_t>(m_quadview_debug_mode->value());\n"
        "            requested.stabilize_crop=m_quadview_stabilize_crop->value();\n"
        "            requested.guard_fraction=m_quadview_guard->value();\n"
        "            requested.gaze_quant_pixels=static_cast<uint32_t>(m_quadview_gaze_quant->value());\n"
        "            requested.gaze_hold_ms=m_quadview_gaze_hold->value();\n"
        "            requested.gaze_reacquire_samples=m_quadview_gaze_reacquire->value();\n"
        "            requested.gaze_offset_u=m_quadview_gaze_offset_u->value();\n"
        "            requested.gaze_offset_v=m_quadview_gaze_offset_v->value();\n"
        "            requested.gaze_micro_gain=m_quadview_gaze_micro_gain->value();\n"
        "            requested.gaze_breakout_radius=m_quadview_gaze_breakout->value();\n"
        "            requested.gaze_still_radius=m_quadview_gaze_still->value();\n"
        "            requested.gaze_relock_samples=static_cast<uint32_t>(m_quadview_gaze_relock->value());\n"
        "            const auto reconciled=uevr::quadview::reconcile_settings(requested,m_quadview_applied_settings,width,height);\n"
        "            m_quadview_rejected_settings.store(reconciled.rejected,std::memory_order_release);\n"
        "            m_quadview_dimension_fallback.store(reconciled.dimension_fallback,std::memory_order_release);\n"
        "            if (reconciled.rejected) set_quadview_status(\"One or more saved Quad Views controls are rejected; see the per-field status below\");\n"
        "            if (!uevr::quadview::same_settings(reconciled.settings,m_quadview_applied_settings)) {\n"
        "                m_quadview_applied_settings=reconciled.settings; ++m_quadview_settings_revision;\n"
        "            }\n"
        "            draw_config.settings=m_quadview_applied_settings;\n"
        "            draw_config.settings_revision=m_quadview_settings_revision;\n"
        "            if (!width || !height || width>8192 || height>8192) {\n"
        "                set_quadview_status(\"Unsupported output dimensions; gaze sampling skipped for this draw\");\n"
        "                SPDLOG_WARNING_EVERY_N_SEC(2,\"[QuadViews][GTBegin][per-call-throttled] reason=unsupported_dimensions width={} height={} generation={} draw={}\",\n"
        "                    width,height,key.generation,key.draw_serial);\n"
        "                m_quadview_draw_config_key=key; m_quadview_draw_config=draw_config;\n"
        "                return {};\n"
        "            }\n"
        "            const auto frame=m_openxr ? m_openxr->internal_frame_count : 0u;\n"
        "            std::optional<runtimes::OpenXR::PipelineState> pose;\n"
        "            if (m_openxr && frame) pose=m_openxr->capture_quadview_pose(frame);\n"
        "            std::optional<uevr::duoview::Ray> head_ray;\n"
        "            draw_config.gaze={};\n"
        "            draw_config.gaze.sampled=draw_config.settings.eye_tracked;\n"
        "            draw_config.gaze.sample_tick=draw_config.gaze.sampled ? GetTickCount64() : 0;\n"
        "            if (draw_config.settings.eye_tracked) {\n"
        "                m_quadview_gaze.set_recovery_controls(static_cast<uint32_t>(draw_config.settings.gaze_hold_ms),\n"
        "                    static_cast<uint32_t>(draw_config.settings.gaze_reacquire_samples));\n"
        "                head_ray=m_quadview_gaze.read_ray();\n"
        "            }\n"
        "            const auto gaze_counts=m_quadview_gaze.counters();\n"
        "            draw_config.gaze.ray_valid=head_ray.has_value();\n"
        "            draw_config.gaze.reader_available=gaze_counts.available;\n"
        "            draw_config.gaze.reader_active=gaze_counts.active;\n"
        "            draw_config.gaze.age_ms=gaze_counts.age_ms;\n"
        "            draw_config.gaze.fresh=gaze_counts.fresh; draw_config.gaze.reused=gaze_counts.reused;\n"
        "            draw_config.gaze.invalid=gaze_counts.invalid; draw_config.gaze.expired=gaze_counts.expired;\n"
        "            draw_config.gaze.unavailable=gaze_counts.unavailable;\n"
        "            std::optional<std::array<uevr::duoview::UV,2>> eye_uv;\n"
        "            bool projection_valid=true;\n"
        "            for (size_t eye=0;eye!=2;++eye) {\n"
        "                const auto matrix=get_projection_matrix(static_cast<VRRuntime::Eye>(eye));\n"
        "                std::memcpy(draw_config.projections[eye].data(),&matrix[0][0],sizeof(draw_config.projections[eye]));\n"
        "                projection_valid=projection_valid && uevr::quadview::gaze::valid_perspective_projection(draw_config.projections[eye]);\n"
        "            }\n"
        "            draw_config.base_projection_valid=projection_valid;\n"
        "            if (pose && pose->stage_views.size()==2) {\n"
        "                const auto& h=pose->view_space_location.pose.orientation;\n"
        "                const uevr::quadview::gaze::Quaternion head{static_cast<float>(h.x),static_cast<float>(h.y),static_cast<float>(h.z),static_cast<float>(h.w)};\n"
        "                std::array<uevr::quadview::gaze::Quaternion,2> eyes{};\n"
        "                for (size_t eye=0; eye!=2; ++eye) {\n"
        "                    const auto& q=pose->stage_views[eye].pose.orientation;\n"
        "                    eyes[eye]={static_cast<float>(q.x),static_cast<float>(q.y),static_cast<float>(q.z),static_cast<float>(q.w)};\n"
        "                }\n"
        "                if (draw_config.base_projection_valid && head_ray) eye_uv=uevr::quadview::gaze::project_stereo_head_ray(*head_ray,head,eyes,draw_config.projections);\n"
        "            }\n"
        "            uevr::duoview::Settings stability{};\n"
        "            stability.crop_width=draw_config.settings.crop_width; stability.crop_height=draw_config.settings.crop_height;\n"
        "            stability.peripheral_scale=draw_config.settings.context_scale; stability.foveal_density=draw_config.settings.foveal_density;\n"
        "            stability.stabilize_crop=draw_config.settings.stabilize_crop; stability.guard_fraction=draw_config.settings.guard_fraction;\n"
        "            stability.gaze_quant_pixels=draw_config.settings.gaze_quant_pixels; stability.gaze_hold_ms=draw_config.settings.gaze_hold_ms;\n"
        "            stability.gaze_reacquire_samples=draw_config.settings.gaze_reacquire_samples;\n"
        "            stability.gaze_offset_u=draw_config.settings.gaze_offset_u; stability.gaze_offset_v=draw_config.settings.gaze_offset_v;\n"
        "            stability.gaze_micro_gain=draw_config.settings.gaze_micro_gain;\n"
        "            stability.gaze_breakout_radius=draw_config.settings.gaze_breakout_radius;\n"
        "            stability.gaze_still_radius=draw_config.settings.gaze_still_radius;\n"
        "            stability.gaze_relock_samples=draw_config.settings.gaze_relock_samples;\n"
        "            stability.eye_tracked=draw_config.settings.eye_tracked;\n"
        "            const uint64_t now=GetTickCount64();\n"
        "            std::array<uevr::quadview::FocusPoint,2> focus{};\n"
        "            for (uint32_t eye=0; eye!=2; ++eye) {\n"
        "                auto eye_settings=stability; eye_settings.fovea_view=eye;\n"
        "                const auto uv=m_quadview_crop_stability[eye].update({key.generation,key.draw_serial},width,height,eye_settings,\n"
        "                    eye_uv ? std::optional<uevr::duoview::UV>{(*eye_uv)[eye]} : std::nullopt,now);\n"
        "                focus[eye]={uv.u,uv.v};\n"
        "            }\n"
        "            draw_config.gaze_valid=eye_uv.has_value();\n"
        "            auto candidate=uevr::quadview::make_layout(width,height,draw_config.settings.crop_width,\n"
        "                draw_config.settings.crop_height,draw_config.settings.context_scale,draw_config.settings.foveal_density,focus);\n"
        "            if (!candidate) {\n"
        "                set_quadview_status(\"No valid four-view layout for this output extent; frame source rejected\");\n"
        "                SPDLOG_WARNING_EVERY_N_SEC(2,\"[QuadViews][GTBegin][per-call-throttled] reason=layout_rejected width={} height={} crop={}x{} context={} density={} generation={} draw={}\",\n"
        "                    width,height,draw_config.settings.crop_width,draw_config.settings.crop_height,draw_config.settings.context_scale,\n"
        "                    draw_config.settings.foveal_density,key.generation,key.draw_serial);\n"
        "                m_quadview_draw_config_key=key; m_quadview_draw_config=draw_config;\n"
        "                { std::scoped_lock pose_lock{m_quadview_pose_mutex}; m_quadview_pose_key=key; m_quadview_pose=std::move(pose); m_quadview_pose_eye_mask=0; }\n"
        "                return {};\n"
        "            }\n"
        "            layout=m_quadview_layout_latch.freeze(key.generation,key.draw_serial,*candidate);\n"
        "            m_quadview_draw_config_key=key; m_quadview_draw_config=draw_config;\n"
        "            {\n"
        "                std::scoped_lock pose_lock{m_quadview_pose_mutex};\n"
        "                m_quadview_pose_key=key; m_quadview_pose=std::move(pose); m_quadview_pose_eye_mask=0;\n"
        "            }\n"
        "        }\n"
        "    }\n"
        "    if (!layout) {\n"
        "        set_quadview_status(\"No frozen structural layout is available for this draw\");\n"
        "        SPDLOG_WARNING_EVERY_N_SEC(2,\"[QuadViews][GTBegin][per-call-throttled] reason=frozen_layout_unavailable generation={} draw={} frame={}\",\n"
        "            key.generation,key.draw_serial,m_render_frame_count);\n"
        "        return {};\n    }\n"
        "    const auto rtm = m_fake_stereo_hook->get_render_target_manager();\n"
        "    const auto target = rtm != nullptr ? rtm->get_view_family_render_target() : nullptr;\n"
        "    if (!m_quadview.begin(key, 0, reinterpret_cast<uintptr_t>(target), 0, *layout,draw_config.settings,draw_config.settings_revision,draw_config.gaze)) {\n"
        "        if (const auto snapshot = m_quadview.snapshot(key)) return snapshot;\n"
        "        set_quadview_status(\"Waiting for a fresh four-view producer transaction\");\n"
        "        SPDLOG_WARNING_EVERY_N_SEC(2,\"[QuadViews][GTBegin][per-call-throttled] reason=producer_begin_rejected generation={} draw={} frame={} target={:x} revision={}\",\n"
        "            key.generation,key.draw_serial,m_render_frame_count,reinterpret_cast<uintptr_t>(target),draw_config.settings_revision);\n"
        "        return {};\n"
        "    }\n"
        "    m_quadview_candidate_key.store(std::make_shared<const uevr::quadview::Key>(key), std::memory_order_release);\n"
        "    set_quadview_status(\"Waiting for four engine view histories and main-family raster\");\n"
        "    return m_quadview.snapshot(key);\n"
        "}\n\n"
        "std::optional<uevr::quadview::Layout> VR::quadview_layout_for_hooks() {\n"
        "    const auto key=quadview_key();\n"
        "    if (is_quadview_renderer_active() && m_fake_stereo_hook && m_fake_stereo_hook->is_in_viewport_client_draw())\n"
        "        (void)quadview_begin_frame();\n"
        "    {\n"
        "        std::scoped_lock lock{m_quadview_layout_mutex};\n"
        "        if (const auto layout=m_quadview_layout_latch.get(key.generation,key.draw_serial)) return layout;\n"
        "    }\n"
        "    const auto fallback=uevr::quadview::make_layout(get_hmd_width(),get_hmd_height(),.50f,.50f,.20f,1.0f,.50f,.50f);\n"
        "    if (!fallback) return {};\n"
        "    std::scoped_lock lock{m_quadview_layout_mutex};\n"
        "    return m_quadview_layout_latch.freeze(key.generation,key.draw_serial,*fallback);\n"
        "}\n\n"
        "void VR::duoview_abort(const char* reason) {")

    edit(backend, "src/mods/VR.cpp",
        "        if (is_using_mono() || uevr::mono::is_mono_family(requested_rendering_method()) || is_mono_transition_pending()) {",
        "        if (is_using_mono() || uevr::mono::is_mono_family(requested_rendering_method()) ||\n"
        "            (is_mono_transition_pending() && uevr::mono::is_mono_family(m_rendering_method->value()))) {")
    edit(backend, "src/mods/VR.cpp",
        "        if (rendering_method_changed && !is_mono_transition_pending() && get_runtime() != nullptr) {",
        "        if (is_quadview_mode_selected() || requested_rendering_method() == RenderingMethod::QUAD_VIEWS_STEREO) {\n"
        "            ImGui::TextWrapped(\"Quad Views Stereo (Experimental): four engine views use independent per-eye gaze crops while OpenXR receives two real stereo eyes.\");\n"
        "            if (const auto reason = quadview_unavailable_reason()) ImGui::TextWrapped(\"Unavailable: %s\", reason);\n"
        "            ImGui::TextWrapped(\"Quad Views status: %s\", quadview_status());\n"
        "            if (ImGui::TreeNode(\"Quad Views Stereo — focus controls and diagnostics\")) {\n"
        "                ImGui::TextWrapped(\"Each eye projects one calibrated head-space gaze ray through its own OpenXR eye rotation and full asymmetric frustum. Context and focus views keep independent histories; the existing full 2W×H target allocation remains.\");\n"
        "                m_quadview_crop_width->draw(\"Focus width / eye FOV\");\n"
        "                m_quadview_crop_height->draw(\"Focus height / eye FOV\");\n"
        "                m_quadview_context_scale->draw(\"Context resolution scale\");\n"
        "                m_quadview_foveal_density->draw(\"Focus pixel density\");\n"
        "                m_quadview_feather->draw(\"Context/focus blend feather\");\n"
        "                m_quadview_sharpen->draw(\"Fused focus sharpening strength\");\n"
                "                m_quadview_gpu_timing->draw(\"GPU timing: QuadView raster (completed slot; excludes UE and source gather)\");\n"
                "                if (m_quadview_gpu_timing->value()) {\n"
                "                    const float value=quadview_gpu_ms();\n"
                "                    if (value>=0.f) ImGui::Text(\"Last retired QuadView raster: %.3f ms\",value);\n"
                "                    else ImGui::TextUnformatted(\"QuadView GPU timing: waiting for a completed command slot\");\n"
                "                }\n"
        "                m_quadview_eye_tracking->draw(\"PSVR2 eye tracking\");\n"
        "                m_quadview_stabilize_crop->draw(\"Stabilize focus crop\");\n"
        "                m_quadview_guard->draw(\"Gaze guard fraction\");\n"
        "                m_quadview_gaze_quant->draw(\"Gaze crop quantization (pixels)\");\n"
        "                m_quadview_gaze_hold->draw(\"Gaze invalid hold (ms)\");\n"
        "                m_quadview_gaze_reacquire->draw(\"Gaze reacquire samples\");\n"
        "                m_quadview_gaze_offset_u->draw(\"Gaze horizontal offset\");\n"
        "                m_quadview_gaze_offset_v->draw(\"Gaze vertical offset\");\n"
        "                m_quadview_gaze_micro_gain->draw(\"Small-motion gain\");\n"
        "                m_quadview_gaze_breakout->draw(\"Saccade breakout radius\");\n"
        "                m_quadview_gaze_still->draw(\"Saccade stillness radius\");\n"
        "                m_quadview_gaze_relock->draw(\"Saccade relock samples\");\n"
        "                m_quadview_debug_border->draw(\"Show focus border\");\n"
        "                m_quadview_debug_mode->draw(\"Compositor diagnostic: 0 blend / 1 context / 2 focus / 3 source colors\");\n"
        "                const auto gaze=m_quadview_gaze.counters();\n"
                "                ImGui::Text(\"PSVR2 CAPI: %s; sample: %s\",gaze.available ? \"available\" : \"unavailable / not initialized\",gaze.active ? \"active\" : \"held or inactive\");\n"
                "                if (gaze.age_ms==UINT32_MAX) ImGui::TextUnformatted(\"PSVR2 sample age: unknown / expired\");\n"
                "                else ImGui::Text(\"PSVR2 sample age: %u ms\",gaze.age_ms);\n"
                "                ImGui::Text(\"Reader totals: fresh %llu, reused %llu, invalid %llu, expired %llu, unavailable %llu\",\n"
                "                    static_cast<unsigned long long>(gaze.fresh),static_cast<unsigned long long>(gaze.reused),\n"
                "                    static_cast<unsigned long long>(gaze.invalid),static_cast<unsigned long long>(gaze.expired),\n"
                "                    static_cast<unsigned long long>(gaze.unavailable));\n"
                "                const auto diagnostic_key=quadview_key();\n"
                "                if (const auto snapshot=quadview_producer().snapshot(diagnostic_key)) {\n"
                "                    ImGui::Text(\"Source generation %llu / draw %llu / engine frame %llu; revision %llu; histories 0x%02X; projections 0x%02X/0x%02X; context offsets 0x%02X\",\n"
                "                        static_cast<unsigned long long>(snapshot->key.generation),\n"
                "                        static_cast<unsigned long long>(snapshot->key.draw_serial),\n"
                "                        static_cast<unsigned long long>(snapshot->engine_frame),\n"
                "                        static_cast<unsigned long long>(snapshot->settings_revision),\n"
                "                        snapshot->constructor_mask,snapshot->expected_projection_mask,snapshot->projection_matrix_mask,quadview_pose_mask());\n"
                "                    const auto& frame_gaze=snapshot->gaze;\n"
                "                    ImGui::Text(\"Frozen frame gaze: sampled %s, ray %s, CAPI %s, state %s\",\n"
                "                        frame_gaze.sampled ? \"yes\" : \"no (fixed center)\",\n"
                "                        frame_gaze.ray_valid ? \"valid\" : \"held / unavailable\",\n"
                "                        frame_gaze.reader_available ? \"available\" : \"unavailable\",\n"
                "                        frame_gaze.reader_active ? \"active\" : \"inactive\");\n"
                "                    if (frame_gaze.age_ms==UINT32_MAX) ImGui::TextUnformatted(\"Frozen source sample age: unknown / expired\");\n"
                "                    else ImGui::Text(\"Frozen source sample age: %u ms at tick %llu\",frame_gaze.age_ms,static_cast<unsigned long long>(frame_gaze.sample_tick));\n"
                "                    ImGui::Text(\"Frozen source counters: fresh %llu, reused %llu, invalid %llu, expired %llu, unavailable %llu\",\n"
                "                        static_cast<unsigned long long>(frame_gaze.fresh),static_cast<unsigned long long>(frame_gaze.reused),\n"
                "                        static_cast<unsigned long long>(frame_gaze.invalid),static_cast<unsigned long long>(frame_gaze.expired),\n"
                "                        static_cast<unsigned long long>(frame_gaze.unavailable));\n"
                "                    ImGui::Text(\"Applied focus %.3f x %.3f, context %.3f, density %.3f; tracking %s; sharpen %.2f\",\n"
                "                        snapshot->settings.crop_width,snapshot->settings.crop_height,snapshot->settings.context_scale,\n"
                "                        snapshot->settings.foveal_density,snapshot->settings.eye_tracked ? \"on\" : \"fixed center\",\n"
                "                        snapshot->settings.sharpen_strength);\n"
                "                } else {\n"
                "                    ImGui::Text(\"Source generation %llu / draw %llu; waiting for a producer snapshot\",\n"
                "                        static_cast<unsigned long long>(diagnostic_key.generation),\n"
                "                        static_cast<unsigned long long>(diagnostic_key.draw_serial));\n"
                "                }\n"
                "                const uint32_t rejected=m_quadview_rejected_settings.load(std::memory_order_acquire);\n"
                "                if (rejected || m_quadview_dimension_fallback.load(std::memory_order_acquire)) {\n"
                "                    ImGui::TextWrapped(\"Rejected saved controls are listed until their values are accepted:\");\n"
                "                    if (rejected&uevr::quadview::reject_width) ImGui::TextUnformatted(\"Focus width rejected\");\n"
                "                    if (rejected&uevr::quadview::reject_height) ImGui::TextUnformatted(\"Focus height rejected\");\n"
                "                    if (rejected&uevr::quadview::reject_context) ImGui::TextUnformatted(\"Context scale rejected for current output dimensions\");\n"
                "                    if (rejected&uevr::quadview::reject_density) ImGui::TextUnformatted(\"Focus density rejected for current output dimensions\");\n"
                "                    if (rejected&uevr::quadview::reject_feather) ImGui::TextUnformatted(\"Blend feather rejected\");\n"
                "                    if (rejected&uevr::quadview::reject_sharpen) ImGui::TextUnformatted(\"Sharpen strength rejected\");\n"
                "                    if (rejected&uevr::quadview::reject_diagnostic) ImGui::TextUnformatted(\"Diagnostic view rejected\");\n"
                "                    if (rejected&uevr::quadview::reject_guard) ImGui::TextUnformatted(\"Gaze guard rejected\");\n"
                "                    if (rejected&uevr::quadview::reject_quant) ImGui::TextUnformatted(\"Gaze quantization rejected\");\n"
                "                    if (rejected&uevr::quadview::reject_hold) ImGui::TextUnformatted(\"Gaze hold duration rejected\");\n"
                "                    if (rejected&uevr::quadview::reject_reacquire) ImGui::TextUnformatted(\"Gaze reacquisition count rejected\");\n"
                "                    if (rejected&uevr::quadview::reject_offset_u) ImGui::TextUnformatted(\"Horizontal gaze offset rejected\");\n"
                "                    if (rejected&uevr::quadview::reject_offset_v) ImGui::TextUnformatted(\"Vertical gaze offset rejected\");\n"
                "                    if (rejected&uevr::quadview::reject_micro) ImGui::TextUnformatted(\"Small-motion gain rejected\");\n"
                "                    if (rejected&uevr::quadview::reject_breakout) ImGui::TextUnformatted(\"Saccade breakout rejected\");\n"
                "                    if (rejected&uevr::quadview::reject_still) ImGui::TextUnformatted(\"Saccade stillness rejected\");\n"
                "                    if (rejected&uevr::quadview::reject_relock) ImGui::TextUnformatted(\"Saccade relock count rejected\");\n"
                "                    if (m_quadview_dimension_fallback.load(std::memory_order_acquire)) ImGui::TextWrapped(\"Output dimensions changed; the applied fallback focus/context tuple matches this target.\");\n"
                "                }\n"
        "                ImGui::TreePop();\n"
        "            }\n"
        "        }\n"
        "        if (rendering_method_changed && !is_mono_transition_pending() && get_runtime() != nullptr) {")

    edit(backend, "src/mods/vr/FFakeStereoRenderingHook.hpp",
        '#include "DuoViewDelivery.hpp"',
        '#include "DuoViewDelivery.hpp"\n#include "runtimes/OpenXR.hpp"\n#include "QuadViewDelivery.hpp"\n#include "QuadViewFramePacket.hpp"\n#include "QuadViewViewDemand.hpp"')
    edit(backend, "src/mods/vr/FFakeStereoRenderingHook.hpp",
        "    using DuoDelivery = uevr::duoview::Delivery<NativeStereoFramePacket>;\n"
        "    mutable DuoDelivery duoview_delivery{};",
        "    struct QuadViewSourcePacket {\n"
        "        std::shared_ptr<const uevr::quadview::Snapshot> producer{};\n"
        "        Microsoft::WRL::ComPtr<ID3D12Resource> atlas{};\n"
        "        runtimes::OpenXR::PipelineState pose{};\n"
        "        D3D12_RESOURCE_STATES source_state{D3D12_RESOURCE_STATE_RENDER_TARGET};\n"
        "        uint64_t runtime_frame{}, serial{};\n"
        "    };\n"
        "    using DuoDelivery = uevr::duoview::Delivery<NativeStereoFramePacket>;\n"
        "    using QuadViewDelivery = uevr::quadview::Delivery<QuadViewSourcePacket>;\n"
        "    mutable DuoDelivery duoview_delivery{};\n"
        "    mutable QuadViewDelivery quadview_delivery{};")
    # This accessor must be public: VR's game-thread selection gate queries it.
    edit(backend, "src/mods/vr/FFakeStereoRenderingHook.hpp",
        "    const char* get_splitscreen_compatibility_status_text();",
        "    const char* get_splitscreen_compatibility_status_text();\n"
        "    bool quadview_outer_renderer_observed() const {\n"
        "        return m_render_module_begin_render_viewfamily_observed.load(std::memory_order_acquire);\n"
        "    }\n"
        "    bool quadview_view_extensions_ready() const {\n"
        "        return m_has_view_extensions_installed && !!m_sceneview_data.constructor_hook &&\n"
        "            m_has_double_precision && !!m_calculate_stereo_projection_matrix_hook;\n"
        "    }")
    edit(backend, "src/mods/vr/FFakeStereoRenderingHook.hpp",
        "        duoview_delivery.retire();",
        "        duoview_delivery.retire();\n        quadview_delivery.retire_all();")
    edit(backend, "src/mods/vr/FFakeStereoRenderingHook.cpp",
        "    if (!vr->is_ghosting_fix_enabled() && !vr->is_splitscreen_compatibility_enabled() && !vr->is_sceneview_compatibility_enabled() && !vr->is_native_stereo_fix_enabled()) {",
        "    if (!vr->is_ghosting_fix_enabled() && !vr->is_splitscreen_compatibility_enabled() && !vr->is_sceneview_compatibility_enabled() && !vr->is_native_stereo_fix_enabled() &&\n"
        "        !vr->is_quadview_supported_title() && !vr->is_quadview_mode_selected() &&\n"
        "        vr->requested_rendering_method() != VR::RenderingMethod::QUAD_VIEWS_STEREO) {")
    edit(backend, "src/mods/vr/FFakeStereoRenderingHook.cpp",
        "    const bool needs_begin_rendering_viewfamilies_hook = uevr::nascar::needs_generic_renderer_hook(\n"
        "        uevr::nascar::is_target(), vr->is_native_stereo_fix_enabled(),\n"
        "        vr->is_dibr_single_view_requested(), vr->is_splitscreen_compatibility_enabled());",
        "    const bool needs_begin_rendering_viewfamilies_hook = vr->is_quadview_supported_title() ||\n"
        "        vr->is_quadview_renderer_active() ||\n"
        "        (vr->is_quadview_mode_selected() && !vr->is_mono_transition_pending()) ||\n"
        "        uevr::nascar::needs_generic_renderer_hook(\n"
        "            uevr::nascar::is_target(), vr->is_native_stereo_fix_enabled(),\n"
        "            vr->is_dibr_single_view_requested(), vr->is_splitscreen_compatibility_enabled());")
    edit(backend, "src/mods/vr/FFakeStereoRenderingHook.cpp",
        "    if (g_hook->m_sceneview_data.inside_post_init_properties) {\n        return 2;\n    }",
        "    if (g_hook->m_sceneview_data.inside_post_init_properties) {\n        return 2;\n    }\n\n"
        "    if (vr->is_quadview_mode_selected()) {\n"
        "        const auto demanded=vr->quadview_desired_view_count();\n"
        "        if (demanded==4 && vr->is_quadview_renderer_active()) (void)vr->quadview_begin_frame();\n"
        "        return demanded;\n    }")
    edit(backend, "src/mods/vr/FFakeStereoRenderingHook.cpp",
        "    static bool index_starts_from_one = true;\n    const bool medium_one_based_eye_pass = medium_is_current_game();",
        "    const auto vr = VR::get();\n"
        "    if (vr->is_quadview_layout_active()) {\n"
        "        if (index < 0 || index >= 4) return;\n"
        "        const auto frame=vr->is_quadview_renderer_active() ? vr->quadview_begin_frame() : std::optional<uevr::quadview::Snapshot>{};\n"
        "        const auto layout=frame ? std::optional<uevr::quadview::Layout>{frame->layout} : vr->quadview_layout_for_hooks();\n"
        "        if (!layout) { vr->set_quadview_status(\"No valid frozen four-view layout is available\"); return; }\n"
        "        const auto& rect = layout->views[static_cast<size_t>(index)];\n"
        "        if (!rect.width || !rect.height || uint64_t(rect.x) + rect.width > layout->atlas_width ||\n"
        "            uint64_t(rect.y) + rect.height > layout->atlas_height) {\n"
        "            vr->set_quadview_status(\"Rejected an out-of-atlas engine view rectangle\"); return;\n"
        "        }\n"
        "        *x = static_cast<int>(rect.x); *y = static_cast<int>(rect.y);\n"
        "        *w = rect.width; *h = rect.height;\n"
        "        if (frame) vr->quadview_producer().rectangle_call(vr->quadview_producer_key(), index);\n"
        "        return;\n"
        "    }\n\n"
        "    static bool index_starts_from_one = true;\n    const bool medium_one_based_eye_pass = medium_is_current_game();")
    edit(backend, "src/mods/vr/FFakeStereoRenderingHook.cpp",
        "    auto vr = VR::get();\n    if (vr->is_duoview_renderer_active() && g_hook->m_has_double_precision && view_index == 1) {",
        "    auto vr = VR::get();\n"
        "    const bool quadview_active = vr->is_quadview_layout_active() && g_hook->m_has_double_precision;\n"
        "    if (quadview_active) {\n"
        "        if (view_index < 0 || view_index >= 4) return;\n"
        "        if (view_index >= 2) {\n"
        "            const auto pose = vr->quadview_producer().context_camera(vr->quadview_producer_key(), static_cast<uint32_t>(view_index & 1));\n"
        "            if (!pose) {\n"
        "                vr->set_quadview_status(\"Using the native eye offset while the matching context camera is unavailable\");\n"
        "            } else {\n"
        "                auto* rot = reinterpret_cast<Rotator<double>*>(view_rotation);\n"
        "                auto* pos = reinterpret_cast<Vector3d*>(view_location);\n"
        "                rot->pitch=pose->rotation[0]; rot->yaw=pose->rotation[1]; rot->roll=pose->rotation[2];\n"
        "                pos->x=pose->position[0]; pos->y=pose->position[1]; pos->z=pose->position[2];\n"
        "                return;\n"
        "            }\n"
        "        }\n"
        "    }\n"
        "    if (vr->is_duoview_renderer_active() && g_hook->m_has_double_precision && view_index == 1) {")
    edit(backend, "src/mods/vr/FFakeStereoRenderingHook.cpp",
        "    if (view_index == -1) {\n        index_was_ever_negative = true;",
        "    if (view_index == -1) {\n        if (!quadview_active) index_was_ever_negative = true;")
    edit(backend, "src/mods/vr/FFakeStereoRenderingHook.cpp",
        "    if (index_was_ever_two && view_index == 0 && !synced_ue56_zero_view_is_eye) {",
        "    if (!quadview_active && index_was_ever_two && view_index == 0 && !synced_ue56_zero_view_is_eye) {")
    edit(backend, "src/mods/vr/FFakeStereoRenderingHook.cpp",
        "    if (!medium_one_based_eye_pass) {\n        if (view_index == 2) {\n            index_starts_from_one = true;",
        "    if (!medium_one_based_eye_pass && !quadview_active) {\n        if (view_index == 2) {\n            index_starts_from_one = true;")
    edit(backend, "src/mods/vr/FFakeStereoRenderingHook.cpp",
        "    auto true_index = medium_one_based_eye_pass\n        ? view_index - 1\n        : (index_starts_from_one ? ((view_index + 1) % 2) : (view_index % 2));",
        "    auto true_index = quadview_active ? (view_index & 1) : (medium_one_based_eye_pass\n"
        "        ? view_index - 1\n        "
        "        : (index_starts_from_one ? ((view_index + 1) % 2) : (view_index % 2)));")
    edit(backend, "src/mods/vr/FFakeStereoRenderingHook.cpp",
        "        if (vr->is_duoview_renderer_active() && g_hook->m_has_double_precision && view_index == 0) {",
        "        if (vr->is_quadview_renderer_active() && g_hook->m_has_double_precision && view_index >= 0 && view_index <= 1) {\n"
        "            const auto* r = reinterpret_cast<const Rotator<double>*>(view_rotation);\n"
        "            const auto* p = reinterpret_cast<const Vector3d*>(view_location);\n"
        "            const uevr::quadview::CameraPose pose{{r->pitch,r->yaw,r->roll},{p->x,p->y,p->z},true};\n"
        "            if (!vr->quadview_producer().camera(vr->quadview_producer_key(), static_cast<uint32_t>(view_index), pose))\n"
        "                vr->set_quadview_status(\"Could not freeze the post-mod context camera\");\n"
        "            if (!vr->quadview_note_eye_pose(static_cast<uint32_t>(view_index)))\n"
        "                vr->set_quadview_status(\"Waiting for both context offsets to capture one exact OpenXR pose frame\");\n"
        "        }\n"
        "        if (vr->is_duoview_renderer_active() && g_hook->m_has_double_precision && view_index == 0) {")

    # Focus projections derive from the exact normal stereo eye matrix, so
    # asymmetric runtime frusta and all four clip rows survive the crop.
    edit(backend, "src/mods/vr/FFakeStereoRenderingHook.cpp",
        "    auto& vr = VR::get();\n\n    bool ghosting_bootstrap_ready = false;",
        "    auto& vr = VR::get();\n"
        "    if (vr->is_quadview_layout_active()) {\n"
        "        if (out == nullptr || view_index < 0 || view_index >= 4) {\n"
        "            vr->set_quadview_status(\"Quad Views projection output or eye index is unavailable\"); return out;\n        }\n"
        "        if (!g_hook->m_has_double_precision || !g_framework->is_game_data_intialized()) {\n"
        "            if (g_hook->m_calculate_stereo_projection_matrix_hook)\n"
        "                g_hook->m_calculate_stereo_projection_matrix_hook.call<Matrix4x4f*>(stereo,out,static_cast<int32_t>(view_index & 1));\n"
        "            vr->set_quadview_status(\"Using the native eye projection while the four-view projection capture is unavailable\"); return out;\n        }\n"
        "        const auto key = vr->quadview_producer_key();\n"
        "        const auto snapshot = vr->quadview_producer().snapshot(key);\n"
        "        const auto layout=snapshot ? std::optional<uevr::quadview::Layout>{snapshot->layout} : vr->quadview_layout_for_hooks();\n"
        "        if (!layout) { vr->set_quadview_status(\"No valid frozen four-view layout for projection\"); return out; }\n"
        "        Matrix4x4d matrix{};\n"
        "        if (view_index < 2) {\n"
        "            // Legacy engine storage is a two-eye pair; focus callbacks only use the captured context projection.\n"
        "            float near_z{};\n"
        "            if (g_hook->m_calculate_stereo_projection_matrix_hook) {\n"
        "                g_hook->m_calculate_stereo_projection_matrix_hook.call<Matrix4x4f*>(stereo, out, view_index);\n"
        "                near_z = static_cast<float>((*reinterpret_cast<Matrix4x4d*>(out))[3][2]);\n"
        "            } else {\n"
        "                near_z = sdk::globals::get_near_clipping_plane();\n"
        "            }\n"
        "            const auto runtime=vr->get_runtime();\n"
        "            if (runtime && std::isfinite(near_z) && near_z>0.f) {\n"
        "                vr->m_nearz = near_z; runtime->update_matrices(near_z, 10000.0f);\n"
        "                matrix = vr->get_projection_matrix(static_cast<VRRuntime::Eye>(view_index));\n"
        "            } else {\n"
        "                for (int col=0; col!=4; ++col) for (int row=0; row!=4; ++row) matrix[col][row]=(*reinterpret_cast<Matrix4x4d*>(out))[col][row];\n"
        "            }\n"
        "            if (const auto frozen=vr->quadview_base_projection(key,static_cast<uint32_t>(view_index))) {\n"
        "                for (int col=0; col!=4; ++col) {\n"
        "                    matrix[col][0]=(*frozen)[col*4+0]; matrix[col][1]=(*frozen)[col*4+1];\n"
        "                    matrix[col][3]=(*frozen)[col*4+3];\n"
        "                }\n"
        "            } else vr->set_quadview_status(\"Using the native context projection because its frozen OpenXR matrix was unavailable\");\n"
        "        } else {\n"
        "            const auto eye=static_cast<uint32_t>(view_index & 1);\n"
        "            const auto base = vr->quadview_producer().projection_matrix(key, eye);\n"
        "            if (base) {\n"
        "                for (int col=0; col!=4; ++col) for (int row=0; row!=4; ++row) matrix[col][row]=(*base)[col*4+row];\n"
        "            } else {\n"
        "                float near_z=sdk::globals::get_near_clipping_plane();\n"
        "                if (g_hook->m_calculate_stereo_projection_matrix_hook) {\n"
        "                    g_hook->m_calculate_stereo_projection_matrix_hook.call<Matrix4x4f*>(stereo,out,static_cast<int32_t>(eye));\n"
        "                    near_z=static_cast<float>((*reinterpret_cast<Matrix4x4d*>(out))[3][2]);\n"
        "                }\n"
        "                if (std::isfinite(near_z) && near_z>0.f && vr->get_runtime()) {\n"
        "                    vr->m_nearz=near_z; vr->get_runtime()->update_matrices(near_z,10000.0f);\n"
        "                }\n"
        "                if (vr->get_runtime()) matrix=vr->get_projection_matrix(static_cast<VRRuntime::Eye>(eye));\n"
        "                else for (int col=0; col!=4; ++col) for (int row=0; row!=4; ++row) matrix[col][row]=(*reinterpret_cast<Matrix4x4d*>(out))[col][row];\n"
        "                vr->set_quadview_status(\"Using a safe eye projection while the producer snapshot is unavailable\");\n"
        "            }\n"
        "            uevr::quadview::apply_focus_crop(matrix, layout->focus_crops[eye]);\n"
        "        }\n"
        "        *reinterpret_cast<Matrix4x4d*>(out) = matrix;\n"
        "        std::array<double,16> values{};\n"
        "        for (int col=0; col!=4; ++col) for (int row=0; row!=4; ++row) values[col*4+row]=matrix[col][row];\n"
        "        uint64_t hash=1469598103934665603ull;\n"
        "        const auto* bytes=reinterpret_cast<const uint8_t*>(values.data());\n"
        "        for (size_t i=0; i<sizeof(values); ++i) { hash ^= bytes[i]; hash *= 1099511628211ull; }\n"
        "        if (snapshot && !vr->quadview_producer().projection_call(key, view_index, hash, values))\n"
        "            vr->set_quadview_status(\"Could not freeze the expected Quad Views projection matrix\");\n"
        "        return out;\n    }\n\n    bool ghosting_bootstrap_ready = false;")

    # Capture real FSceneView, scene-state and exact options matrix after the
    # engine constructor. Four distinct histories are required before submit.
    edit(backend, "src/mods/vr/FFakeStereoRenderingHook.cpp",
        "    if (!inside_viewport_client_draw || !vr->is_hmd_active()) {\n        return g_hook->m_sceneview_data.constructor_hook.unsafe_call<sdk::FSceneView*>(view, init_options, a3, a4);\n    }",
        "    if (vr->is_quadview_renderer_active()) {\n"
        "        if (!inside_viewport_client_draw || !vr->is_hmd_active() || init_options == nullptr || !g_hook->m_has_double_precision)\n"
        "            return g_hook->m_sceneview_data.constructor_hook.unsafe_call<sdk::FSceneView*>(view, init_options, a3, a4);\n"
        "        update_init_offsets();\n"
        "        auto* family = init_options->get_view_family();\n"
        "        auto* state = init_options->get_scene_state();\n"
        "        auto* scene = family != nullptr ? family->get_scene_interface() : nullptr;\n"
        "        auto* target = family != nullptr ? family->get_render_target() : nullptr;\n"
        "        auto* result = g_hook->m_sceneview_data.constructor_hook.unsafe_call<sdk::FSceneView*>(view, init_options, a3, a4);\n"
        "        if (result == nullptr || family == nullptr || state == nullptr || scene == nullptr || target == nullptr ||\n"
        "            !result->has_view_family(family) || !is_readable_process_range(reinterpret_cast<uintptr_t>(state), sizeof(void*))) {\n"
        "            vr->set_quadview_status(\"Waiting for four valid engine scene histories\"); return result;\n        }\n"
        "        auto* options = reinterpret_cast<sdk::FSceneViewInitOptionsUE5*>(init_options);\n"
        "        Matrix4x4d projection{}; std::memcpy(&projection, &options->projection_matrix, sizeof(projection));\n"
        "        std::array<double,16> values{};\n"
        "        for (int col=0; col!=4; ++col) for (int row=0; row!=4; ++row) values[col*4+row]=projection[col][row];\n"
        "        uint64_t hash=1469598103934665603ull; const auto* bytes=reinterpret_cast<const uint8_t*>(values.data());\n"
        "        for (size_t i=0; i<sizeof(values); ++i) { hash ^= bytes[i]; hash *= 1099511628211ull; }\n"
        "        FIntRect actual_rect{}; std::memcpy(actual_rect.bounds, &options->view_rect, sizeof(actual_rect.bounds));\n"
        "        const uevr::quadview::Rect rect{static_cast<uint32_t>(actual_rect.bounds[0]), static_cast<uint32_t>(actual_rect.bounds[1]),\n"
        "            static_cast<uint32_t>(actual_rect.bounds[2]-actual_rect.bounds[0]), static_cast<uint32_t>(actual_rect.bounds[3]-actual_rect.bounds[1])};\n"
        "        const auto key=vr->quadview_producer_key();\n"
        "        if (!vr->quadview_producer().constructed(key, reinterpret_cast<uintptr_t>(family), reinterpret_cast<uintptr_t>(scene),\n"
        "            reinterpret_cast<uintptr_t>(target), reinterpret_cast<uintptr_t>(result), reinterpret_cast<uintptr_t>(state), rect, hash))\n"
        "            vr->set_quadview_status(\"Engine view/history did not match its frozen rectangle, projection, family or target\");\n"
        "        return result;\n    }\n\n"
        "    if (!inside_viewport_client_draw || !vr->is_hmd_active()) {\n        return g_hook->m_sceneview_data.constructor_hook.unsafe_call<sdk::FSceneView*>(view, init_options, a3, a4);\n    }")

    # QV must observe the normal main family even though Native Fix, DIBR and
    # scene/split compatibility are deliberately disabled. Keep that path
    # isolated from the legacy two-view metadata and zero/one-based heuristics.
    edit(backend, "src/mods/vr/FFakeStereoRenderingHook.cpp",
        "    const auto native_stereo_fix_enabled = vr->is_native_stereo_fix_enabled();\n    const bool split_screen_enabled = vr->is_splitscreen_compatibility_enabled();",
        "    const auto native_stereo_fix_enabled = vr->is_native_stereo_fix_enabled();\n"
        "    const bool split_screen_enabled = vr->is_splitscreen_compatibility_enabled();\n"
        "    const bool quadview_active = vr->is_quadview_renderer_active();")
    edit(backend, "src/mods/vr/FFakeStereoRenderingHook.cpp",
        "    if (!vr->is_hmd_active() ||\n        (!native_stereo_fix_enabled && !dibr_single_view_eligible && !split_screen_enabled)) {",
        "    if (!vr->is_hmd_active() ||\n"
        "        (!quadview_active && !native_stereo_fix_enabled && !dibr_single_view_eligible && !split_screen_enabled)) {")
    edit(backend, "src/mods/vr/FFakeStereoRenderingHook.cpp",
        "    auto& views = *views_ptr;\n    const auto prev_count = views.count;\n\n    // Observe Native Fix's original two-view main family before the fix",
        "    auto& views = *views_ptr;\n    const auto prev_count = views.count;\n\n"
                "    if (quadview_active) {\n"
        "        // The source is now registered by BeginRenderViewFamily on the game thread,\n"
        "        // before the render-thread family can execute. Never publish it from\n"
        "        // this later renderer entry; the old order raced against RHI delivery.\n"
        "        call_original();\n"
        "        return;\n"
        "    }\n"
        "\n"
        "    // Observe Native Fix's original two-view main family before the fix")

    # Publish the exact source at the engine game-thread BeginRenderViewFamily
    # callback, BEFORE any renderer-owned FViewInfo copy or RT family callback.
    # The outer renderer is no longer allowed to register it too late.
    edit(backend, "src/mods/vr/FFakeStereoRenderingHook.cpp",
        "    auto views_ptr = view_family.get_views();\n    if (const auto packet = duoview_build_packet; packet && packet->duoview_frame) {",
        "    auto views_ptr = view_family.get_views();\n"
        "    if (vr->is_quadview_layout_active()) {\n"
        "        auto* qv_rtm=g_hook->get_render_target_manager();\n"
        "        auto* qv_target=view_family.get_render_target();\n"
        "        auto* qv_scene=view_family.get_scene_interface();\n"
        "        auto* qv_expected_target=qv_rtm != nullptr ? qv_rtm->get_view_family_render_target() : nullptr;\n"
        "        const auto qv_key=vr->quadview_producer_key();\n"
        "        std::array<uintptr_t,4> qv_view_ids{};\n"
        "        const bool qv_family_readable=views_ptr && views_ptr->count==4 &&\n"
        "            views_ptr->capacity>=4 && views_ptr->data &&\n"
        "            is_readable_process_range(reinterpret_cast<uintptr_t>(views_ptr->data),sizeof(void*)*4);\n"
        "        if (qv_family_readable) {\n"
        "            for (size_t i=0; i!=4; ++i) qv_view_ids[i]=reinterpret_cast<uintptr_t>(views_ptr->data[i]);\n"
        "        }\n"
        "        std::optional<FFakeStereoRenderingHook::QuadViewDelivery::EngineTicket> qv_engine_ticket;\n"
        "        if (qv_family_readable && qv_target && qv_target==qv_expected_target && qv_scene) {\n"
        "            FFakeStereoRenderingHook::QuadViewDelivery::EngineTicket ticket{qv_key.generation,qv_key.draw_serial,\n"
        "                frame_count,reinterpret_cast<uintptr_t>(&view_family),reinterpret_cast<uintptr_t>(qv_target),\n"
        "                reinterpret_cast<uintptr_t>(qv_scene)};\n"
        "            if (g_hook->quadview_delivery.register_engine_family(ticket)) qv_engine_ticket=ticket;\n"
        "            else vr->set_quadview_status(\"Engine render-family ownership ledger is full; mode transition will remain blocked\");\n"
        "        }\n"
        "        const auto qv_snapshot=vr->quadview_producer().snapshot(qv_key);\n"
        "        const auto qv_pose=vr->quadview_frozen_pose(qv_key);\n"
        "        // The source must be published HERE, before a renderer-owned FViewInfo\n"
        "        // copy and before the RT callback has any opportunity to run.\n"
        "        const auto qv_valid=qv_family_readable && qv_engine_ticket && qv_snapshot &&\n"
        "            qv_target && qv_target==qv_expected_target && qv_scene && qv_pose &&\n"
        "            qv_pose->stage_views.size()==2 && qv_pose->frame_state.predictedDisplayTime>0 &&\n"
        "            qv_pose->frame_state.shouldRender==XR_TRUE;\n"
        "        if (qv_valid) {\n"
        "            auto* qv_source_rhi=qv_rtm->get_render_target();\n"
        "            auto* qv_native=qv_source_rhi ? static_cast<ID3D12Resource*>(qv_source_rhi->get_native_resource()) : nullptr;\n"
        "            if (qv_native) {\n"
        "                const auto desc=qv_native->GetDesc();\n"
        "                const bool atlas_valid=desc.Dimension==D3D12_RESOURCE_DIMENSION_TEXTURE2D &&\n"
        "                    desc.Width==qv_snapshot->layout.atlas_width && desc.Height==qv_snapshot->layout.atlas_height &&\n"
        "                    desc.DepthOrArraySize==1 && desc.SampleDesc.Count==1 &&\n"
        "                    (desc.Flags&D3D12_RESOURCE_FLAG_DENY_SHADER_RESOURCE)==0;\n"
        "                if (atlas_valid && vr->quadview_producer().main_family(qv_key,frame_count,\n"
        "                        reinterpret_cast<uintptr_t>(&view_family),reinterpret_cast<uintptr_t>(qv_scene),\n"
        "                        reinterpret_cast<uintptr_t>(qv_target),qv_view_ids)) {\n"
        "                    auto qv_packet=std::make_shared<FFakeStereoRenderingHook::QuadViewSourcePacket>();\n"
        "                    qv_packet->producer=vr->quadview_producer().frozen(qv_key);\n"
        "                    qv_packet->atlas=qv_native;\n"
        "                    qv_packet->pose=*qv_pose;\n"
        "                    qv_packet->source_state=is_ue_5_5_runtime()\n"
        "                        ? (D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE|D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE)\n"
        "                        : D3D12_RESOURCE_STATE_RENDER_TARGET;\n"
        "                    qv_packet->runtime_frame=static_cast<uint64_t>(qv_pose->frame_state.predictedDisplayTime);\n"
        "                    qv_packet->serial=qv_key.draw_serial;\n"
        "                    if (qv_packet->producer) {\n"
        "                        FFakeStereoRenderingHook::QuadViewDelivery::Source qv_source{\n"
        "                            qv_packet,qv_key.generation,qv_key.draw_serial,frame_count,qv_packet->runtime_frame,\n"
        "                            reinterpret_cast<uintptr_t>(&view_family),reinterpret_cast<uintptr_t>(qv_target),\n"
        "                            reinterpret_cast<uintptr_t>(qv_scene),qv_view_ids\n"
        "                        };\n"
        "                        // The published source is frame-bound atomically, not\n"
        "                        // registered first and bound after the RT thread may run.\n"
        "                        const bool registered=g_hook->quadview_delivery.register_bound(std::move(qv_source));\n"
        "                        if (registered) {\n"
        "                            vr->set_quadview_status(\"Four-view source registered before the renderer copies this family\");\n"
        "                            SPDLOG_INFO_EVERY_N_SEC(2,\"[QuadViews][GTProducer] BOUND serial={} frame={} family={:x} scene={:x} target={:x} views={:x},{:x},{:x},{:x} pose={}\",\n"
        "                                qv_key.draw_serial,frame_count,reinterpret_cast<uintptr_t>(&view_family),\n"
        "                                reinterpret_cast<uintptr_t>(qv_scene),reinterpret_cast<uintptr_t>(qv_target),\n"
        "                                qv_view_ids[0],qv_view_ids[1],qv_view_ids[2],qv_view_ids[3],qv_packet->runtime_frame);\n"
        "                        } else {\n"
        "                            vr->set_quadview_status(\"Failed to register a valid game-thread source before renderer handoff\");\n"
        "                            SPDLOG_WARNING_EVERY_N_SEC(2,\"[QuadViews][GTProducer] BIND_FAIL serial={} frame={}\",\n"
        "                                qv_key.draw_serial,frame_count);\n"
        "                        }\n"
        "                    }\n"
        "                } else {\n"
        "                    vr->set_quadview_status(\"Four-view engine scene roles or original source atlas are unvalidated\");\n"
        "                    SPDLOG_WARNING_EVERY_N_SEC(2,\"[QuadViews][GTProducer] main-family/atlas rejection serial={} frame={} atlas_valid={} views={:x},{:x},{:x},{:x}\",\n"
        "                        qv_key.draw_serial,frame_count,atlas_valid,qv_view_ids[0],qv_view_ids[1],qv_view_ids[2],qv_view_ids[3]);\n"
        "                }\n"
        "            } else {\n"
        "                vr->set_quadview_status(\"Original Unreal main scene has no native D3D12 atlas resource\");\n"
        "            }\n"
        "        } else {\n"
        "            vr->set_quadview_status(\"Waiting for complete four-view GT source and synchronized stereo pose\");\n"
        "            const char* qv_reason=!qv_family_readable ? \"view_family_unreadable\" : !qv_engine_ticket ? \"engine_ticket_rejected\" :\n"
        "                !qv_snapshot ? \"producer_snapshot_missing\" : !qv_target || qv_target!=qv_expected_target ? \"target_unavailable_or_mismatch\" :\n"
        "                !qv_scene ? \"scene_unavailable\" : !qv_pose ? \"coherent_pose_unavailable\" :\n"
        "                qv_pose->stage_views.size()!=2 ? \"pose_eye_count_invalid\" :\n"
        "                qv_pose->frame_state.predictedDisplayTime<=0 ? \"pose_display_time_invalid\" : \"pose_should_not_render\";\n"
        "            SPDLOG_WARNING_EVERY_N_SEC(2,\"[QuadViews][GTProducer][per-frame-throttled] NOT_READY reason={} serial={} frame={} readable={} ticket={} snap={} pose={} eyes={} target={:x} expected={:x} scene={:x}\",\n"
        "                qv_reason,qv_key.draw_serial,frame_count,qv_family_readable,static_cast<bool>(qv_engine_ticket),\n"
        "                static_cast<bool>(qv_snapshot),static_cast<bool>(qv_pose),\n"
        "                qv_pose ? qv_pose->stage_views.size() : 0,\n"
        "                reinterpret_cast<uintptr_t>(qv_target),reinterpret_cast<uintptr_t>(qv_expected_target),reinterpret_cast<uintptr_t>(qv_scene));\n"
        "        }\n"
        "    }\n"
                "    if (const auto packet = duoview_build_packet; packet && packet->duoview_frame) {")

    # Attach the QV source transaction to the exact RHI command tail created
    # by its main-family render callback. The family queue can run ahead; only
    # the executed tail below retires prior owners of a reused atlas.
    edit(backend, "src/mods/vr/FFakeStereoRenderingHook.cpp",
        "    static inline std::unordered_map<sdk::FRHICommandBase_New*, uint32_t> cmd_frame_counts{};\n"
        "    static inline std::unordered_map<sdk::FRHICommandBase_New*, FFakeStereoRenderingHook::DuoDelivery::Command> duo_command_sources{};",
        "    static inline std::unordered_map<sdk::FRHICommandBase_New*, uint32_t> cmd_frame_counts{};\n"
        "    static inline std::unordered_map<sdk::FRHICommandBase_New*, FFakeStereoRenderingHook::DuoDelivery::Command> duo_command_sources{};\n"
        "    static inline std::unordered_map<sdk::FRHICommandBase_New*, FFakeStereoRenderingHook::QuadViewDelivery::Source> quad_command_sources{};\n"
        "    static inline std::unordered_map<sdk::FRHICommandBase_New*, FFakeStereoRenderingHook::QuadViewDelivery::EngineTicket> quad_command_engines{};")
    edit(backend, "src/mods/vr/FFakeStereoRenderingHook.cpp",
        "        const auto duo_source = duo_command.owner();",
        "        const auto duo_source = duo_command.owner();\n"
        "        const auto quad_source_it=quad_command_sources.find(cmd);\n"
        "        const auto quad_source=quad_source_it != quad_command_sources.end()\n"
        "            ? quad_source_it->second : FFakeStereoRenderingHook::QuadViewDelivery::Source{};\n"
        "        const auto quad_engine_it=quad_command_engines.find(cmd);\n"
        "        const auto quad_engine=quad_engine_it != quad_command_engines.end()\n"
        "            ? quad_engine_it->second : FFakeStereoRenderingHook::QuadViewDelivery::EngineTicket{};")
    edit(backend, "src/mods/vr/FFakeStereoRenderingHook.cpp",
        "                if (duo_source && vr->is_duoview_renderer_active() && g_hook != nullptr) {\n"
        "                    for (const auto& source : duo_command.sources) {\n"
        "                        if (source) g_hook->duoview_delivery.executed(source, reinterpret_cast<uintptr_t>(cmd), GetCurrentThreadId());\n"
        "                    }\n"
        "                }",
        "                if (duo_source && vr->is_duoview_renderer_active() && g_hook != nullptr) {\n"
        "                    for (const auto& source : duo_command.sources) {\n"
        "                        if (source) g_hook->duoview_delivery.executed(source, reinterpret_cast<uintptr_t>(cmd), GetCurrentThreadId());\n"
        "                    }\n"
        "                }\n"
        "                if (quad_engine && g_hook != nullptr && quad_engine.generation==vr->mono_generation()) {\n"
        "                    if (!g_hook->quadview_delivery.executed_engine_family(quad_engine,quad_source,\n"
        "                            reinterpret_cast<uintptr_t>(cmd),GetCurrentThreadId()))\n"
        "                        vr->set_quadview_status(\"Tracked engine family command did not match its RHI owner\");\n"
        "                }")
    edit(backend, "src/mods/vr/FFakeStereoRenderingHook.cpp",
        "        duo_command_sources.erase(cmd);",
        "        duo_command_sources.erase(cmd);\n        quad_command_sources.erase(cmd);\n        quad_command_engines.erase(cmd);")
    edit(backend, "src/mods/vr/FFakeStereoRenderingHook.cpp",
        "    static void hook_new_rhi_command(sdk::FRHICommandBase_New* last_command, uint32_t frame_count,\n"
        "        const FFakeStereoRenderingHook::DuoDelivery::Source& duo_source = {}) {",
        "    static void hook_new_rhi_command(sdk::FRHICommandBase_New* last_command, uint32_t frame_count,\n"
        "        const FFakeStereoRenderingHook::DuoDelivery::Source& duo_source = {},\n"
        "        const FFakeStereoRenderingHook::QuadViewDelivery::Source& quad_source = {},\n"
        "        const FFakeStereoRenderingHook::QuadViewDelivery::EngineTicket& quad_engine = {}) {")
    edit(backend, "src/mods/vr/FFakeStereoRenderingHook.cpp",
        "        if (duo_source && (!vr->is_duoview_renderer_active() || duo_source.generation!=vr->mono_generation())) return;\n"
        "        if (!duo_source && vr->is_duoview_renderer_active() && original_vtables.contains(last_command)) return;",
        "        if (duo_source && (!vr->is_duoview_renderer_active() || duo_source.generation!=vr->mono_generation())) return;\n"
        "        if (quad_source && quad_source.generation!=vr->mono_generation()) return;\n"
        "        if (quad_engine && quad_engine.generation!=vr->mono_generation()) return;\n"
        "        if (!duo_source && vr->is_duoview_renderer_active() && original_vtables.contains(last_command)) return;\n"
        "        if (quad_engine) {\n"
        "            const char* root_rejection{};\n"
        "            if (!original_vtables.contains(last_command) && !is_probable_new_rhi_command(last_command, root_rejection)) {\n"
        "                vr->set_quadview_status(\"Rejected an unsafe main-family RHI command before tail ownership\"); return;\n            }\n"
        "            uintptr_t readable_begin{}, readable_end{};\n"
        "            const auto tail=uevr::duoview::command_tail(reinterpret_cast<uintptr_t>(last_command),\n"
        "                [&](uintptr_t at) -> std::optional<uintptr_t> {\n"
        "                    if (at < readable_begin || at >= readable_end || readable_end-at < sizeof(sdk::FRHICommandBase_New)) {\n"
        "                        MEMORY_BASIC_INFORMATION region{};\n"
        "                        if (!is_readable_process_range(at, sizeof(sdk::FRHICommandBase_New)) ||\n"
        "                            !VirtualQuery(reinterpret_cast<void*>(at), &region, sizeof(region))) return {};\n"
        "                        readable_begin=reinterpret_cast<uintptr_t>(region.BaseAddress); readable_end=readable_begin+region.RegionSize;\n"
        "                    }\n"
        "                    return reinterpret_cast<uintptr_t>(reinterpret_cast<sdk::FRHICommandBase_New*>(at)->next);\n"
        "                });\n"
        "            if (!tail) { vr->set_quadview_status(\"Could not identify the exact main-family RHI command tail\"); return; }\n"
        "            last_command=reinterpret_cast<sdk::FRHICommandBase_New*>(*tail);\n"
        "            if (original_vtables.contains(last_command)) {\n"
        "                const auto owner=quad_command_engines.find(last_command);\n"
        "                if (owner == quad_command_engines.end() || !owner->second.same_owner(quad_engine))\n"
        "                    vr->set_quadview_status(\"RHI command tail is already owned by a different family\");\n"
        "                return;\n            }\n"
        "        }")
    edit(backend, "src/mods/vr/FFakeStereoRenderingHook.cpp",
        "        const bool preserve_pending_identity = vr->is_duoview_renderer_active() || uevr::vr_compatibility::should_preserve_mafia_pending_rhi_identity(",
        "        const bool preserve_pending_identity = vr->is_duoview_renderer_active() || vr->is_quadview_mode_selected() ||\n"
        "            uevr::vr_compatibility::should_preserve_mafia_pending_rhi_identity(")
    edit(backend, "src/mods/vr/FFakeStereoRenderingHook.cpp",
        "            if (duo_source) g_hook->duoview_delivery.block(duo_source,\n                reinterpret_cast<uintptr_t>(last_command), GetCurrentThreadId());\n            if (preserve_pending_identity)",
        "            if (duo_source) g_hook->duoview_delivery.block(duo_source,\n                reinterpret_cast<uintptr_t>(last_command), GetCurrentThreadId());\n"
        "            if (quad_engine) vr->set_quadview_status(\"Tracked engine family command failed RHI tail validation; transition remains blocked\");\n"
        "            if (preserve_pending_identity)")
    edit(backend, "src/mods/vr/FFakeStereoRenderingHook.cpp",
        "        if (duo_source) {\n            FFakeStereoRenderingHook::DuoDelivery::Command command{};\n            command.attach(duo_source);\n            duo_command_sources.emplace(last_command, std::move(command));\n            g_hook->duoview_delivery.note(uevr::duoview::DeliveryEvent::hook, duo_source,\n                reinterpret_cast<uintptr_t>(last_command), GetCurrentThreadId());\n        }\n        *(void***)last_command = (void**)new_vtable.data();",
        "        if (duo_source) {\n            FFakeStereoRenderingHook::DuoDelivery::Command command{};\n            command.attach(duo_source);\n            duo_command_sources.emplace(last_command, std::move(command));\n            g_hook->duoview_delivery.note(uevr::duoview::DeliveryEvent::hook, duo_source,\n                reinterpret_cast<uintptr_t>(last_command), GetCurrentThreadId());\n        }\n"
        "        if (quad_engine) {\n"
        "            if (!g_hook->quadview_delivery.tail_hooked_engine_family(quad_engine,quad_source,\n"
        "                    reinterpret_cast<uintptr_t>(last_command))) {\n"
        "                vr->set_quadview_status(\"Could not latch the tracked engine-family RHI tail; transition remains blocked\");\n"
        "                original_vtables.erase(last_command); return;\n            }\n"
        "            quad_command_engines.emplace(last_command,quad_engine);\n"
        "        }\n"
        "        if (quad_source) {\n"
        "            quad_command_sources.emplace(last_command, quad_source);\n"
        "            SPDLOG_INFO_EVERY_N_SEC(2, \"[QuadViews][RHI] tail hooked serial={} frame={} command={:x}\",\n"
        "                quad_source.serial, quad_source.engine_frame, reinterpret_cast<uintptr_t>(last_command));\n"
        "        }\n        *(void***)last_command = (void**)new_vtable.data();")

    edit(backend, "src/mods/vr/FFakeStereoRenderingHook.cpp",
        "    const auto duo_source = vr->is_duoview_renderer_active()\n"
        "        ? g_hook->duoview_delivery.render(vr->mono_generation(), frame_count,\n"
        "            reinterpret_cast<uintptr_t>(view_family.get_render_target()),\n"
        "            reinterpret_cast<uintptr_t>(view_family.get_scene_interface()), GetCurrentThreadId())\n"
        "        : DuoDelivery::Source{};",
        "    const auto duo_source = vr->is_duoview_renderer_active()\n"
        "        ? g_hook->duoview_delivery.render(vr->mono_generation(), frame_count,\n"
        "            reinterpret_cast<uintptr_t>(view_family.get_render_target()),\n"
        "            reinterpret_cast<uintptr_t>(view_family.get_scene_interface()), GetCurrentThreadId())\n"
        "        : DuoDelivery::Source{};\n"
        "    std::optional<FFakeStereoRenderingHook::QuadViewDelivery::EngineTicket> quad_engine_opt;\n"
        "    std::optional<FFakeStereoRenderingHook::QuadViewDelivery::Source> quad_source_opt;\n"
        "    if (vr->is_quadview_mode_selected()) {\n"
        "        quad_engine_opt=g_hook->quadview_delivery.render_engine_family(vr->mono_generation(),frame_count,\n"
        "            reinterpret_cast<uintptr_t>(view_family.get_render_target()),\n"
        "            reinterpret_cast<uintptr_t>(view_family.get_scene_interface()));\n"
        "        auto* qv_views=view_family.get_views();\n"
        "        bool valid_qv_family=qv_views != nullptr && qv_views->count == 4 && qv_views->capacity >= 4 &&\n"
        "            qv_views->data != nullptr && is_readable_process_range(reinterpret_cast<uintptr_t>(qv_views->data), sizeof(void*)*4);\n"
        "        std::array<uintptr_t,4> qv_render_view_ids{};\n"
        "        if (valid_qv_family) {\n"
        "            for (size_t i=0; i!=4; ++i) {\n"
        "                qv_render_view_ids[i]=reinterpret_cast<uintptr_t>(qv_views->data[i]);\n"
        "                if (!qv_render_view_ids[i]) valid_qv_family=false;\n"
        "                for (size_t j=0; j<i; ++j) if (qv_render_view_ids[i]==qv_render_view_ids[j]) valid_qv_family=false;\n"
        "            }\n"
        "        }\n"
        "        if (!valid_qv_family) {\n"
        "            vr->set_quadview_status(\"Render-thread family did not contain four readable distinct views\");\n"
        "            SPDLOG_WARNING_EVERY_N_SEC(2, \"[QuadViews][RenderFamily] rejected: count={} capacity={} data={:x} frame={}\",\n"
        "                qv_views ? qv_views->count : 0, qv_views ? qv_views->capacity : 0,\n"
        "                qv_views ? reinterpret_cast<uintptr_t>(qv_views->data) : 0, frame_count);\n"
        "        } else if (quad_engine_opt) {\n"
        "            quad_source_opt=g_hook->quadview_delivery.render(vr->mono_generation(), frame_count,\n"
        "                reinterpret_cast<uintptr_t>(&view_family), reinterpret_cast<uintptr_t>(view_family.get_render_target()),\n"
        "                reinterpret_cast<uintptr_t>(view_family.get_scene_interface()));\n"
        "            if (quad_source_opt) {\n"
        "                SPDLOG_INFO_EVERY_N_SEC(2, \"[QuadViews][RenderFamily] matched serial={} source_frame={} render_frame={} family_copy={:x}\",\n"
        "                    quad_source_opt->serial, quad_source_opt->engine_frame, frame_count, reinterpret_cast<uintptr_t>(&view_family));\n"
        "            } else {\n"
        "                vr->set_quadview_status(\"Four-view render family has no unique bound engine-frame owner\");\n"
        "                SPDLOG_WARNING_EVERY_N_SEC(2, \"[QuadViews][RenderFamily] unmatched frame={} scene={:x} target={:x} family_copy={:x} views={:x},{:x},{:x},{:x}\",\n"
        "                    frame_count, reinterpret_cast<uintptr_t>(view_family.get_scene_interface()),\n"
        "                    reinterpret_cast<uintptr_t>(view_family.get_render_target()),\n"
        "                    reinterpret_cast<uintptr_t>(&view_family),\n"
        "                    qv_render_view_ids[0], qv_render_view_ids[1], qv_render_view_ids[2], qv_render_view_ids[3]);\n"
        "            }\n"
        "        } else if (vr->is_quadview_renderer_active()) {\n"
        "            vr->set_quadview_status(\"Four-view render family has no tracked GT engine owner\");\n"
        "        }\n"
        "    }\n"
        "    const auto quad_source=quad_source_opt.value_or(FFakeStereoRenderingHook::QuadViewDelivery::Source{});\n"
        "    const auto quad_engine=quad_engine_opt.value_or(FFakeStereoRenderingHook::QuadViewDelivery::EngineTicket{});")
    edit(backend, "src/mods/vr/FFakeStereoRenderingHook.cpp",
        "reinterpret_cast<sdk::FRHICommandBase_New*>(*root), frame_count + compensation, duo_source);",
        "reinterpret_cast<sdk::FRHICommandBase_New*>(*root), frame_count + compensation, duo_source, quad_source, quad_engine);")
    edit(backend, "src/mods/vr/FFakeStereoRenderingHook.cpp",
        "hook_new_rhi_command(root, frame_count + compensation, duo_source);",
        "hook_new_rhi_command(root, frame_count + compensation, duo_source, quad_source, quad_engine);")
    edit(backend, "src/mods/vr/FFakeStereoRenderingHook.cpp",
        "hook_new_rhi_command((sdk::FRHICommandBase_New*)l->root, frame_count + compensation, duo_source);",
        "hook_new_rhi_command((sdk::FRHICommandBase_New*)l->root, frame_count + compensation, duo_source, quad_source, quad_engine);")
    edit(backend, "src/mods/vr/FFakeStereoRenderingHook.cpp",
        "hook_new_rhi_command((sdk::FRHICommandBase_New*)cmd_list->root, frame_count + compensation, duo_source);",
        "hook_new_rhi_command((sdk::FRHICommandBase_New*)cmd_list->root, frame_count + compensation, duo_source, quad_source, quad_engine);")

    # Frontend ID choices are persisted values. Do not renumber existing rows.
    edit(frontend, "UEVR/RenderingModeOptions.cs",
        "        public const int DuoViewMono = 6;",
        "        public const int DuoViewMono = 6;\n        public const int QuadViewsStereo = 7;")
    edit(frontend, "UEVR/RenderingModeOptions.cs",
        '            result.Add(DuoViewMono.ToString(), "DuoView Mono (Eye Tracked - Experimental)");\n            return result;',
        '            result.Add(DuoViewMono.ToString(), "DuoView Mono (Eye Tracked - Experimental)");\n'
        '            result.Add(QuadViewsStereo.ToString(), "Quad Views Stereo (Experimental)");\n'
        '            return result;')
    edit(frontend, "tests/RenderingModes/Program.cs",
        "for (int id = 0; id <= 6; ++id) {\n        bool supported = id < 3 || id == 5 || id == 6 || dibr;",
        "for (int id = 0; id <= 7; ++id) {\n        bool supported = id < 3 || id == 5 || id == 6 || id == 7 || dibr;")
    edit(frontend, "tests/RenderingModes/Program.cs",
        'new[] { "0", "1", "2", "3", "4", "5", "6", "99", "-1" }',
        'new[] { "0", "1", "2", "3", "4", "5", "6", "7", "99", "-1" }')
    edit(frontend, "tests/RenderingModes/Program.cs",
        '    if (choices.ContainsKey("99")) { throw new Exception("Unknown ID leaked into other profiles"); }',
        '    if (choices["7"] != "Quad Views Stereo (Experimental)") { throw new Exception("ID 7 must be labeled as stereo Quad Views"); }\n'
        '    if (choices.ContainsKey("99")) { throw new Exception("Unknown ID leaked into other profiles"); }')

    for path, content in changed.items():
        path.write_text(content, encoding="utf-8")

    # Reuse the tested production-independent headers. The generated bytecode
    # is emitted in CI after applying this overlay.
    target = backend / "src/mods/vr"
    for name in ("QuadViewGeometry.hpp", "QuadViewProducer.hpp", "QuadViewDelivery.hpp",
                 "QuadViewFramePacket.hpp", "QuadViewD3D12.hpp", "QuadViewViewDemand.hpp",
                 "QuadViewSettings.hpp", "QuadViewGaze.hpp", "QuadViewPSVR2Gaze.hpp"):
        source = overlay / name
        if not source.is_file():
            raise RuntimeError(f"required Quad Views production header is missing: {source}")
        shutil.copy2(source, target / name)


if __name__ == "__main__":
    main()
