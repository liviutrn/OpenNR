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
        '#include "vr/DuoViewState.hpp"\n#include "vr/QuadViewProducer.hpp"')
    edit(backend, "src/mods/VR.hpp",
        "    bool is_using_mono() const { return uevr::mono::is_mono_family(m_rendering_method->value()); }\n"
        "    bool is_using_duoview_mono() const { return m_rendering_method->value() == RenderingMethod::DUOVIEW_MONO; }\n"
        "    bool is_duoview_renderer_active() const;",
        "    bool is_using_mono() const { return uevr::mono::is_mono_family(m_rendering_method->value()); }\n"
        "    bool is_using_duoview_mono() const { return m_rendering_method->value() == RenderingMethod::DUOVIEW_MONO; }\n"
        "    bool is_quadview_mode_selected() const { return m_rendering_method->value() == RenderingMethod::QUAD_VIEWS_STEREO; }\n"
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
        "        { std::scoped_lock lock{m_quadview_pose_mutex}; m_quadview_pose.reset(); m_quadview_pose_key={}; m_quadview_pose_eye_mask=0; }\n    }\n"
        "    uevr::quadview::Key quadview_key() const {\n"
        "        return {mono_generation(), m_quadview_draw_serial.load(std::memory_order_acquire)};\n    }\n"
        "    uevr::quadview::Key quadview_producer_key() const {\n"
        "        const auto candidate=m_quadview_candidate_key.load(std::memory_order_acquire);\n"
        "        return candidate && candidate->generation==mono_generation() ? *candidate : quadview_key();\n    }\n"
        "    uevr::quadview::Producer& quadview_producer() { return m_quadview; }\n"
        "    const uevr::quadview::Producer& quadview_producer() const { return m_quadview; }\n"
        "    std::optional<uevr::quadview::Snapshot> quadview_begin_frame();\n"
        "    bool quadview_note_eye_pose(uint32_t eye) {\n"
        "        if (eye > 1 || !is_quadview_renderer_active() || m_openxr == nullptr) return false;\n"
        "        const auto frame=m_openxr->internal_frame_count;\n"
        "        const auto pose=m_openxr->capture_quadview_pose(frame);\n"
        "        if (!pose || pose->frame_count != frame || pose->stage_views.size() != 2 ||\n"
        "            pose->frame_state.predictedDisplayTime <= 0 || pose->frame_state.shouldRender != XR_TRUE) return false;\n"
        "        const auto key=quadview_key();\n"
        "        std::scoped_lock lock{m_quadview_pose_mutex};\n"
        "        if (m_quadview_pose_key != key || !m_quadview_pose) {\n"
        "            m_quadview_pose_key=key; m_quadview_pose=*pose; m_quadview_pose_eye_mask=0;\n"
        "        } else if (m_quadview_pose->frame_count != pose->frame_count ||\n"
        "            m_quadview_pose->frame_state.predictedDisplayTime != pose->frame_state.predictedDisplayTime) {\n"
        "            m_quadview_pose.reset(); m_quadview_pose_eye_mask=0; return false;\n"
        "        }\n"
        "        m_quadview_pose_eye_mask |= static_cast<uint8_t>(1u << eye);\n"
        "        return true;\n"
        "    }\n"
        "    std::optional<runtimes::OpenXR::PipelineState> quadview_frozen_pose(uevr::quadview::Key key) const {\n"
        "        std::scoped_lock lock{m_quadview_pose_mutex};\n"
        "        return m_quadview_pose_key == key && m_quadview_pose_eye_mask == 0x03 ? m_quadview_pose : std::nullopt;\n"
        "    }\n"
        "    float quadview_feather() const { return m_quadview_feather->value(); }\n"
        "    unsigned quadview_debug_mode() const { return static_cast<unsigned>(m_quadview_debug_mode->value()); }\n"
        "    void set_quadview_status(const char* text) { m_quadview_status.store(text, std::memory_order_release); }\n"
        "    const char* quadview_status() const { return m_quadview_status.load(std::memory_order_acquire); }")
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
        '    const ModSlider::Ptr m_quadview_crop_width{ModSlider::create(generate_name("QuadViewFocusWidth"), .1f, 1.f, .5f)};\n'
        '    const ModSlider::Ptr m_quadview_crop_height{ModSlider::create(generate_name("QuadViewFocusHeight"), .1f, 1.f, .5f)};\n'
        '    const ModSlider::Ptr m_quadview_context_scale{ModSlider::create(generate_name("QuadViewContextScale"), .05f, .5f, .2f)};\n'
        '    const ModSlider::Ptr m_quadview_feather{ModSlider::create(generate_name("QuadViewFeather"), 0.f, .49f, .08f)};\n'
        '    const ModInt32::Ptr m_quadview_debug_mode{ModSliderInt32::create(generate_name("QuadViewDebugMode"), 0, 3, 0)};')
    edit(backend, "src/mods/VR.hpp",
        "    std::once_flag m_duoview_settings_once;",
        "    std::once_flag m_duoview_settings_once;\n"
        "    uevr::quadview::Producer m_quadview;\n"
        "    std::atomic<uint64_t> m_quadview_draw_serial{};\n"
        "    std::atomic<std::shared_ptr<const uevr::quadview::Key>> m_quadview_candidate_key{};\n"
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
        "    return is_quadview_mode_selected() && !is_mono_transition_pending() && quadview_unavailable_reason() == nullptr;\n}\n\n"
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
        "    if (!is_quadview_renderer_active() || !m_fake_stereo_hook ||\n"
        "        !m_fake_stereo_hook->is_in_viewport_client_draw()) return {};\n"
        "    const auto key = quadview_key();\n"
        "    if (key.generation == 0 || key.draw_serial == 0) return {};\n"
        "    if (const auto candidate = m_quadview_candidate_key.load(std::memory_order_acquire);\n"
        "        candidate && *candidate == key) {\n"
        "        if (const auto snapshot = m_quadview.snapshot(key)) return snapshot;\n"
        "    }\n"
        "    const auto width = get_hmd_width();\n"
        "    const auto height = get_hmd_height();\n"
        "    const auto layout = uevr::quadview::make_layout(width, height,\n"
        "        m_quadview_crop_width->value(), m_quadview_crop_height->value(),\n"
        "        m_quadview_context_scale->value(), 1.0f, 0.5f, 0.5f);\n"
        "    if (!layout) { set_quadview_status(\"Invalid atlas dimensions or focus/context controls\"); return {}; }\n"
        "    const auto rtm = m_fake_stereo_hook->get_render_target_manager();\n"
        "    const auto target = rtm != nullptr ? rtm->get_view_family_render_target() : nullptr;\n"
        "    if (!m_quadview.begin(key, 0, reinterpret_cast<uintptr_t>(target), 0, *layout)) {\n"
        "        if (const auto snapshot = m_quadview.snapshot(key)) return snapshot;\n"
        "        set_quadview_status(\"Waiting for a fresh four-view producer transaction\");\n"
        "        return {};\n"
        "    }\n"
        "    m_quadview_candidate_key.store(std::make_shared<const uevr::quadview::Key>(key), std::memory_order_release);\n"
        "    set_quadview_status(\"Waiting for four engine view histories and main-family raster\");\n"
        "    return m_quadview.snapshot(key);\n"
        "}\n\n"
        "void VR::duoview_abort(const char* reason) {")

    edit(backend, "src/mods/VR.cpp",
        "        if (is_using_mono() || uevr::mono::is_mono_family(requested_rendering_method()) || is_mono_transition_pending()) {",
        "        if (is_using_mono() || uevr::mono::is_mono_family(requested_rendering_method()) ||\n"
        "            (is_mono_transition_pending() && uevr::mono::is_mono_family(m_rendering_method->value()))) {")
    edit(backend, "src/mods/VR.cpp",
        "        if (rendering_method_changed && !is_mono_transition_pending() && get_runtime() != nullptr) {",
        "        if (is_quadview_mode_selected() || requested_rendering_method() == RenderingMethod::QUAD_VIEWS_STEREO) {\n"
        "            ImGui::TextWrapped(\"Quad Views Stereo (Experimental): four engine views share a fixed-center focus crop while OpenXR still receives two real stereo eyes.\");\n"
        "            if (const auto reason = quadview_unavailable_reason()) ImGui::TextWrapped(\"Unavailable: %s\", reason);\n"
        "            ImGui::TextWrapped(\"Quad Views status: %s\", quadview_status());\n"
        "            if (ImGui::TreeNode(\"Quad Views Stereo — focus controls and diagnostics\")) {\n"
        "                ImGui::TextWrapped(\"The focus crop stays at screen center. Engine context and focus views use independent lazily created histories. The full 2W×H render target allocation is retained; this control does not promise a GPU speedup.\");\n"
        "                m_quadview_crop_width->draw(\"Focus width / eye FOV\");\n"
        "                m_quadview_crop_height->draw(\"Focus height / eye FOV\");\n"
        "                m_quadview_context_scale->draw(\"Context resolution scale\");\n"
        "                m_quadview_feather->draw(\"Context/focus blend feather\");\n"
        "                m_quadview_debug_mode->draw(\"Compositor diagnostic: 0 blend / 1 context / 2 focus / 3 source colors\");\n"
        "                ImGui::TextWrapped(\"Producer history and compositor-record counters are reported separately; they do not prove scene raster or display completion.\");\n"
        "                ImGui::TreePop();\n"
        "            }\n"
        "        }\n"
        "        if (rendering_method_changed && !is_mono_transition_pending() && get_runtime() != nullptr) {")

    edit(backend, "src/mods/vr/FFakeStereoRenderingHook.hpp",
        '#include "DuoViewDelivery.hpp"',
        '#include "DuoViewDelivery.hpp"\n#include "runtimes/OpenXR.hpp"\n#include "QuadViewDelivery.hpp"\n#include "QuadViewFramePacket.hpp"')
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
        "    if (vr->is_quadview_renderer_active()) {\n"
        "        // Never request four renderer views until the real outer renderer\n"
        "        // hook has been observed. Constructor-only evidence cannot\n"
        "        // authorize an extra pair of GPU scene views.\n"
        "        const bool producer_ready = g_hook->m_has_view_extensions_installed &&\n"
        "            !!g_hook->m_sceneview_data.constructor_hook;\n"
        "        const bool renderer_ready = !!g_hook->m_render_module_begin_render_viewfamily_hook &&\n"
        "            g_hook->m_render_module_begin_render_viewfamily_observed.load(std::memory_order_acquire);\n"
        "        if (!producer_ready || !renderer_ready) {\n"
        "            vr->set_quadview_status(\"Waiting for validated scene-view and outer-renderer hooks before requesting four GPU views\");\n"
        "            SPDLOG_WARNING_EVERY_N_SEC(2, \"[QuadViews][ActivationGate] producer={} outer_renderer={}\", producer_ready, renderer_ready);\n"
        "            return 2u;\n"
        "        }\n"
        "        return vr->quadview_begin_frame().has_value() ? 4u : 2u;\n    }")
    edit(backend, "src/mods/vr/FFakeStereoRenderingHook.cpp",
        "    static bool index_starts_from_one = true;\n    const bool medium_one_based_eye_pass = medium_is_current_game();",
        "    const auto vr = VR::get();\n"
        "    if (vr->is_quadview_renderer_active()) {\n"
        "        if (index < 0 || index >= 4) return;\n"
        "        if (const auto frame = vr->quadview_begin_frame()) {\n"
        "            const auto& rect = frame->layout.views[static_cast<size_t>(index)];\n"
        "            if (!rect.width || !rect.height || uint64_t(rect.x) + rect.width > frame->layout.atlas_width ||\n"
        "                uint64_t(rect.y) + rect.height > frame->layout.atlas_height) {\n"
        "                vr->set_quadview_status(\"Rejected an out-of-atlas engine view rectangle\"); return;\n"
        "            }\n"
        "            *x = static_cast<int>(rect.x); *y = static_cast<int>(rect.y);\n"
        "            *w = rect.width; *h = rect.height;\n"
        "            vr->quadview_producer().rectangle_call(vr->quadview_producer_key(), index);\n"
        "            return;\n"
        "        }\n"
        "        return;\n"
        "    }\n\n"
        "    static bool index_starts_from_one = true;\n    const bool medium_one_based_eye_pass = medium_is_current_game();")
    edit(backend, "src/mods/vr/FFakeStereoRenderingHook.cpp",
        "    auto vr = VR::get();\n    if (vr->is_duoview_renderer_active() && g_hook->m_has_double_precision && view_index == 1) {",
        "    auto vr = VR::get();\n"
        "    const bool quadview_active = vr->is_quadview_renderer_active() && g_hook->m_has_double_precision;\n"
        "    if (quadview_active) {\n"
        "        if (view_index < 0 || view_index >= 4) return;\n"
        "        if (view_index >= 2) {\n"
        "            const auto pose = vr->quadview_producer().context_camera(vr->quadview_producer_key(), static_cast<uint32_t>(view_index & 1));\n"
        "            if (!pose) { vr->set_quadview_status(\"Waiting for the matching context camera before its focus view\"); return; }\n"
        "            auto* rot = reinterpret_cast<Rotator<double>*>(view_rotation);\n"
        "            auto* pos = reinterpret_cast<Vector3d*>(view_location);\n"
        "            rot->pitch=pose->rotation[0]; rot->yaw=pose->rotation[1]; rot->roll=pose->rotation[2];\n"
        "            pos->x=pose->position[0]; pos->y=pose->position[1]; pos->z=pose->position[2];\n"
        "            return;\n"
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
        "    auto true_index = quadview_active ? view_index : (medium_one_based_eye_pass\n"
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
        "    if (vr->is_quadview_renderer_active()) {\n"
        "        if (!g_hook->m_has_double_precision || out == nullptr ||\n"
        "            !g_framework->is_game_data_intialized() || view_index < 0 || view_index >= 4) {\n"
        "            vr->set_quadview_status(\"Quad Views projection hook or double-precision matrix is unavailable\"); return out;\n        }\n"
        "        const auto key = vr->quadview_producer_key();\n"
        "        const auto snapshot = vr->quadview_producer().snapshot(key);\n"
        "        if (!snapshot) { vr->set_quadview_status(\"Waiting for a Quad Views draw transaction\"); return out; }\n"
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
        "            vr->m_nearz = near_z;\n"
        "            vr->get_runtime()->update_matrices(near_z, 10000.0f);\n"
        "            matrix = vr->get_projection_matrix(static_cast<VRRuntime::Eye>(view_index));\n"
        "        } else {\n"
        "            const auto base = vr->quadview_producer().projection_matrix(key, static_cast<uint32_t>(view_index & 1));\n"
        "            if (!base) { vr->set_quadview_status(\"Waiting for the matching context projection before its focus view\"); return out; }\n"
        "            for (int col=0; col!=4; ++col) for (int row=0; row!=4; ++row) matrix[col][row]=(*base)[col*4+row];\n"
        "            uevr::quadview::apply_focus_crop(matrix, snapshot->layout.focus_crop);\n"
        "        }\n"
        "        *reinterpret_cast<Matrix4x4d*>(out) = matrix;\n"
        "        std::array<double,16> values{};\n"
        "        for (int col=0; col!=4; ++col) for (int row=0; row!=4; ++row) values[col*4+row]=matrix[col][row];\n"
        "        uint64_t hash=1469598103934665603ull;\n"
        "        const auto* bytes=reinterpret_cast<const uint8_t*>(values.data());\n"
        "        for (size_t i=0; i<sizeof(values); ++i) { hash ^= bytes[i]; hash *= 1099511628211ull; }\n"
        "        if (!vr->quadview_producer().projection_call(key, view_index, hash, values))\n"
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
        "    if (vr->is_quadview_renderer_active()) {\n"
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
        "        const auto qv_snapshot=vr->quadview_producer().snapshot(qv_key);\n"
        "        const auto qv_pose=vr->quadview_frozen_pose(qv_key);\n"
        "        // The source must be published HERE, before a renderer-owned FViewInfo\n"
        "        // copy and before the RT callback has any opportunity to run.\n"
        "        const auto qv_valid=qv_family_readable && qv_snapshot &&\n"
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
        "            SPDLOG_WARNING_EVERY_N_SEC(2,\"[QuadViews][GTProducer] NOT_READY serial={} frame={} readable={} snap={} pose={} eyes={} target={:x} expected={:x} scene={:x}\",\n"
        "                qv_key.draw_serial,frame_count,qv_family_readable,static_cast<bool>(qv_snapshot),static_cast<bool>(qv_pose),\n"
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
        "    static inline std::unordered_map<sdk::FRHICommandBase_New*, FFakeStereoRenderingHook::QuadViewDelivery::Source> quad_command_sources{};")
    edit(backend, "src/mods/vr/FFakeStereoRenderingHook.cpp",
        "        const auto duo_source = duo_command.owner();",
        "        const auto duo_source = duo_command.owner();\n"
        "        const auto quad_source_it=quad_command_sources.find(cmd);\n"
        "        const auto quad_source=quad_source_it != quad_command_sources.end()\n"
        "            ? quad_source_it->second : FFakeStereoRenderingHook::QuadViewDelivery::Source{};")
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
        "                if (quad_source && g_hook != nullptr && vr->is_quadview_renderer_active()) {\n"
        "                    if (g_hook->quadview_delivery.executed(quad_source, reinterpret_cast<uintptr_t>(cmd), GetCurrentThreadId())) {\n"
        "                        vr->set_quadview_status(\"Four-view source command executed on the submission thread\");\n"
        "                        SPDLOG_INFO_EVERY_N_SEC(2, \"[QuadViews][RHI] source executed serial={} frame={} command={:x} thread={}\",\n"
        "                            quad_source.serial, quad_source.engine_frame, reinterpret_cast<uintptr_t>(cmd), GetCurrentThreadId());\n"
        "                    } else {\n"
        "                        vr->set_quadview_status(\"The four-view source command could not be proven executed on this thread\");\n"
        "                    }\n"
        "                }")
    edit(backend, "src/mods/vr/FFakeStereoRenderingHook.cpp",
        "        duo_command_sources.erase(cmd);",
        "        duo_command_sources.erase(cmd);\n        quad_command_sources.erase(cmd);")
    edit(backend, "src/mods/vr/FFakeStereoRenderingHook.cpp",
        "    static void hook_new_rhi_command(sdk::FRHICommandBase_New* last_command, uint32_t frame_count,\n"
        "        const FFakeStereoRenderingHook::DuoDelivery::Source& duo_source = {}) {",
        "    static void hook_new_rhi_command(sdk::FRHICommandBase_New* last_command, uint32_t frame_count,\n"
        "        const FFakeStereoRenderingHook::DuoDelivery::Source& duo_source = {},\n"
        "        const FFakeStereoRenderingHook::QuadViewDelivery::Source& quad_source = {}) {")
    edit(backend, "src/mods/vr/FFakeStereoRenderingHook.cpp",
        "        if (duo_source && (!vr->is_duoview_renderer_active() || duo_source.generation!=vr->mono_generation())) return;\n"
        "        if (!duo_source && vr->is_duoview_renderer_active() && original_vtables.contains(last_command)) return;",
        "        if (duo_source && (!vr->is_duoview_renderer_active() || duo_source.generation!=vr->mono_generation())) return;\n"
        "        if (quad_source && (!vr->is_quadview_renderer_active() || quad_source.generation!=vr->mono_generation())) return;\n"
        "        if (!duo_source && vr->is_duoview_renderer_active() && original_vtables.contains(last_command)) return;\n"
        "        if (quad_source) {\n"
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
        "                const auto owner=quad_command_sources.find(last_command);\n"
        "                if (owner == quad_command_sources.end() || !owner->second.same_owner(quad_source))\n"
        "                    vr->set_quadview_status(\"RHI command tail is already owned by a different family\");\n"
        "                return;\n            }\n"
        "        }")
    edit(backend, "src/mods/vr/FFakeStereoRenderingHook.cpp",
        "        const bool preserve_pending_identity = vr->is_duoview_renderer_active() || uevr::vr_compatibility::should_preserve_mafia_pending_rhi_identity(",
        "        const bool preserve_pending_identity = vr->is_duoview_renderer_active() || vr->is_quadview_renderer_active() ||\n"
        "            uevr::vr_compatibility::should_preserve_mafia_pending_rhi_identity(")
    edit(backend, "src/mods/vr/FFakeStereoRenderingHook.cpp",
        "            if (duo_source) g_hook->duoview_delivery.block(duo_source,\n                reinterpret_cast<uintptr_t>(last_command), GetCurrentThreadId());\n            if (preserve_pending_identity)",
        "            if (duo_source) g_hook->duoview_delivery.block(duo_source,\n                reinterpret_cast<uintptr_t>(last_command), GetCurrentThreadId());\n"
        "            if (quad_source) vr->set_quadview_status(\"RHI source command failed safety validation\");\n"
        "            if (preserve_pending_identity)")
    edit(backend, "src/mods/vr/FFakeStereoRenderingHook.cpp",
        "        if (duo_source) {\n            FFakeStereoRenderingHook::DuoDelivery::Command command{};\n            command.attach(duo_source);\n            duo_command_sources.emplace(last_command, std::move(command));\n            g_hook->duoview_delivery.note(uevr::duoview::DeliveryEvent::hook, duo_source,\n                reinterpret_cast<uintptr_t>(last_command), GetCurrentThreadId());\n        }\n        *(void***)last_command = (void**)new_vtable.data();",
        "        if (duo_source) {\n            FFakeStereoRenderingHook::DuoDelivery::Command command{};\n            command.attach(duo_source);\n            duo_command_sources.emplace(last_command, std::move(command));\n            g_hook->duoview_delivery.note(uevr::duoview::DeliveryEvent::hook, duo_source,\n                reinterpret_cast<uintptr_t>(last_command), GetCurrentThreadId());\n        }\n"
        "        if (quad_source) {\n"
        "            if (!g_hook->quadview_delivery.tail_hooked(quad_source, reinterpret_cast<uintptr_t>(last_command))) {\n"
        "                vr->set_quadview_status(\"Could not latch the exact four-view RHI command tail\");\n"
        "                original_vtables.erase(last_command); return;\n            }\n"
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
        "    std::optional<FFakeStereoRenderingHook::QuadViewDelivery::Source> quad_source_opt;\n"
        "    if (vr->is_quadview_renderer_active()) {\n"
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
        "        } else {\n"
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
        "        }\n"
        "    }\n"
        "    const auto quad_source=quad_source_opt.value_or(FFakeStereoRenderingHook::QuadViewDelivery::Source{});")
    edit(backend, "src/mods/vr/FFakeStereoRenderingHook.cpp",
        "reinterpret_cast<sdk::FRHICommandBase_New*>(*root), frame_count + compensation, duo_source);",
        "reinterpret_cast<sdk::FRHICommandBase_New*>(*root), frame_count + compensation, duo_source, quad_source);")
    edit(backend, "src/mods/vr/FFakeStereoRenderingHook.cpp",
        "hook_new_rhi_command(root, frame_count + compensation, duo_source);",
        "hook_new_rhi_command(root, frame_count + compensation, duo_source, quad_source);")
    edit(backend, "src/mods/vr/FFakeStereoRenderingHook.cpp",
        "hook_new_rhi_command((sdk::FRHICommandBase_New*)l->root, frame_count + compensation, duo_source);",
        "hook_new_rhi_command((sdk::FRHICommandBase_New*)l->root, frame_count + compensation, duo_source, quad_source);")
    edit(backend, "src/mods/vr/FFakeStereoRenderingHook.cpp",
        "hook_new_rhi_command((sdk::FRHICommandBase_New*)cmd_list->root, frame_count + compensation, duo_source);",
        "hook_new_rhi_command((sdk::FRHICommandBase_New*)cmd_list->root, frame_count + compensation, duo_source, quad_source);")

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
                 "QuadViewFramePacket.hpp", "QuadViewD3D12.hpp"):
        source = overlay / name
        if not source.is_file():
            raise RuntimeError(f"required Quad Views production header is missing: {source}")
        shutil.copy2(source, target / name)


if __name__ == "__main__":
    main()
