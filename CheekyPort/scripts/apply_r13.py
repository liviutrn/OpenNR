#!/usr/bin/env python3
"""Add explicit, opt-in source-eye filtering to the pinned Cheeky r12 patch stack.

0 = Both (identical to r12), 1 = role 0, 2 = role 1.
Unknown or shared-mono roles fail closed to passthrough; NEVER guess an eye.
The filter suppresses Cheeky modifications, not the game's native DLSS render.
"""
from pathlib import Path
import sys

root = Path(sys.argv[1]).resolve()
def patch(file, old, new, expected=1, nth=1):
    p = root / file
    s = p.read_text(encoding="utf-8")
    found = s.count(old)
    if found != expected:
        raise RuntimeError(f"R13 {file}: expected {expected} anchors, found {found}: {old[:110]!r}")
    pos = -1
    for _ in range(nth):
        pos = s.find(old, pos + 1)
    p.write_text(s[:pos] + new + s[pos + len(old):], encoding="utf-8", newline="\n")
    print(f"R13 {file}: replaced anchor {nth}/{expected}")

patch("src/settings.hpp",
      "    bool enabled{true};",
      "    bool enabled{true};\n    std::uint32_t eye_processing_mode{0U}; // 0 both; 1 source eye 0; 2 source eye 1")
patch("src/settings.hpp",
      "[[nodiscard]] Settings settings_for_view(",
      "[[nodiscard]] bool cheeky_processing_allowed_for_view(const Settings& settings,\n    std::uint64_t view_id) noexcept;\n[[nodiscard]] Settings settings_for_view(")
patch("src/settings.cpp",
      "std::atomic<bool> enabled{true};",
      "std::atomic<bool> enabled{true};\nstd::atomic<std::uint32_t> eye_processing_mode{0U};")
patch("src/settings.cpp",
      "    settings.enabled = enabled.load(std::memory_order_acquire);",
      "    settings.enabled = enabled.load(std::memory_order_acquire);\n    settings.eye_processing_mode = eye_processing_mode.load(std::memory_order_acquire);")
patch("src/settings.cpp",
      "    enabled.store(settings.enabled, std::memory_order_release);",
      "    enabled.store(settings.enabled, std::memory_order_release);\n    eye_processing_mode.store(settings.eye_processing_mode <= 2U ? settings.eye_processing_mode : 0U,\n        std::memory_order_release);")
patch("src/settings.cpp",
      "Settings settings_for_view(\n",
      """bool cheeky_processing_allowed_for_view(const Settings& settings,
    const std::uint64_t view_id) noexcept {
    if (settings.eye_processing_mode == 0U) return true; // Legacy path: zero overhead/behavior change.
    if (view_id == 0U || settings.eye_processing_mode > 2U) return false;
    // Reuse the existing view-role coordinator, not NGX handle ordering.
    // On uncalibrated startup it needs two observed views; until then passthrough.
    static_cast<void>(settings_for_view(settings, view_id));
    const auto role = stereo_eye_assignment(view_id);
    // A single shared-mono source cannot be filtered by submitted XR eye here.
    if (!role.assigned || role.shared_source) return false;
    return role.eye_index == settings.eye_processing_mode - 1U;
}

Settings settings_for_view(
""")
patch("uevr/settings_fields.inc",
      'CHEEKY_SETTING("Enabled", enabled)',
      'CHEEKY_SETTING("Enabled", enabled)\nCHEEKY_SETTING("EyeProcessingMode", eye_processing_mode)')
patch("uevr/settings_io.cpp",
      'for (const auto gaze : {"XOffset",',
      'for (const auto gaze : {"EyeProcessingMode", "XOffset",')
patch("uevr/settings_io.cpp",
      '    candidate.d3d12_lower_hook = true; // Older files use the new lower-hook default.',
      '    candidate.d3d12_lower_hook = true; // Older files use the new lower-hook default.\n    candidate.eye_processing_mode = 0U; // Missing key from r12 must not inherit a stale filter.')
patch("uevr/scripts/cheeky_foveated_dlss.lua",
      '        reset_group("Reset Stereo / gaze defaults", "gaze")',
      '''        if draft.EyeProcessingMode ~= nil then
            section("DuoView: select DLSS source eye")
            combo("Cheeky processing eye", "EyeProcessingMode",
                {[0]="Both (r12 default)", [1]="Eye 0 only (fovea)", [2]="Eye 1 only"})
            text("Other source uses game DLSS unchanged; this does not stop UEVR scene rendering.")
            text("Requires two identifiable DLSS views. Unknown/shared-mono mappings stay unmodified.")
        end
        reset_group("Reset Stereo / gaze defaults", "gaze")''')
patch("uevr/scripts/cheeky_foveated_dlss.lua",
      '"EyeCalibrationContinuous", "EyeCalibrationMethod"}) do',
      '"EyeCalibrationContinuous", "EyeCalibrationMethod", "EyeProcessingMode"}) do')
patch("src/addon.cpp",
      '    static_cast<void>(reshade::get_config_value(\n        nullptr, config_section, "AutoStereoAlignment", settings.auto_stereo_alignment));',
      '    static_cast<void>(reshade::get_config_value(\n        nullptr, config_section, "AutoStereoAlignment", settings.auto_stereo_alignment));\n    reshade::get_config_value(nullptr, config_section, "EyeProcessingMode", settings.eye_processing_mode);')
patch("src/addon.cpp",
      '    reshade::set_config_value(nullptr, config_section, "AutoStereoAlignment", settings.auto_stereo_alignment);',
      '    reshade::set_config_value(nullptr, config_section, "AutoStereoAlignment", settings.auto_stereo_alignment);\n    reshade::set_config_value(nullptr, config_section, "EyeProcessingMode", settings.eye_processing_mode);')
patch("src/addon.cpp",
      '    if (ImGui::CollapsingHeader("Stereo / Gaze")) {',
      '''    if (ImGui::CollapsingHeader("Stereo / Gaze")) {
        int eye_choice = static_cast<int>(settings.eye_processing_mode);
        if (ImGui::Combo("Cheeky processing eye", &eye_choice,
                "Both (r12 default)\\0Eye 0 only (fovea)\\0Eye 1 only\\0")) {
            settings.eye_processing_mode = static_cast<std::uint32_t>(eye_choice);
            changed = true;
        }
        ImGui::TextDisabled("Unselected DLSS source remains native; requires distinct, identified sources.");''')

# Native DX12 NGX high and low hook: stop BEFORE NR substitution, private
# allocations or peripheral DLAA. Preserve game's own evaluation unchanged.
native_find = "    auto settings = current_settings();\n    if (afw_coverage_enabled()) {"
patch("src/hooks.cpp", native_find,
      """    auto settings = current_settings();
    const auto active_id = static_cast<DlssViewId>(reinterpret_cast<std::uintptr_t>(call.handle));
    if (!cheeky_processing_allowed_for_view(settings, active_id)) {
        skip_d3d12_history(active_id);
        skip_d3d12_history(peripheral_dlaa_view_id(active_id));
        skip_dlss_nr_history(active_id);
        return original(call.command_list, call.handle, call.parameters, call.callback);
    }
    if (afw_coverage_enabled()) {""", expected=2, nth=1)
patch("src/hooks.cpp", native_find,
      """    auto settings = current_settings();
    const auto active_id = static_cast<DlssViewId>(reinterpret_cast<std::uintptr_t>(handle));
    if (!cheeky_processing_allowed_for_view(settings, active_id)) {
        skip_d3d12_history(active_id);
        skip_d3d12_history(peripheral_dlaa_view_id(active_id));
        skip_dlss_nr_history(active_id);
        return original(command_list, handle, parameters, callback);
    }
    if (afw_coverage_enabled()) {""", expected=1)

# D3D11 is retained, including the DX11->DX12 NR transport path.
dx11_find = "    const auto settings = current_settings();\n\n    if (!settings.enabled &&"
dx11_repl = """    const auto settings = current_settings();
    if (!cheeky_processing_allowed_for_view(settings,
            static_cast<DlssViewId>(reinterpret_cast<std::uintptr_t>(handle)))) {
        skip_dlss_nr_history(static_cast<DlssViewId>(reinterpret_cast<std::uintptr_t>(handle)));
        return original(context, handle, parameters, callback);
    }

    if (!settings.enabled &&"""
patch("src/hooks.cpp", dx11_find, dx11_repl, expected=2, nth=1)
patch("src/hooks.cpp", dx11_find, dx11_repl, expected=1)

# Streamline is not guaranteed to use the native NGX hook in STALKER 2.
# Filtering before NR and SR scope is critical: filtering only NGX is insufficient.
patch("src/hooks.cpp",
      "    const auto live_settings = current_settings();\n    NrPipelineTimingScope pipeline_timing",
      """    const auto live_settings = current_settings();
    const auto source_view_id = static_cast<DlssViewId>(cached_sl_options_viewport.value) + 1U;
    register_stereo_view(source_view_id);
    if (!cheeky_processing_allowed_for_view(live_settings, source_view_id)) {
        for (auto& history : streamline_crop_history) {
            if (history.viewport != cached_sl_options_viewport.value) continue;
            history.valid = false;
            history.afw_skipped = true;
        }
        skip_d3d12_history(source_view_id);
        skip_dlss_nr_history(source_view_id);
        StreamlineEvaluationScope native_scope;
        const auto native_result = original(feature, frame, inputs, input_count, command_buffer);
        stamp_streamline_output(static_cast<ID3D12GraphicsCommandList*>(command_buffer), native_result);
        return native_result;
    }
    NrPipelineTimingScope pipeline_timing""")

# Test default, validated persistence, unknown identity, both roles, reverse
# selection and out-of-range clamp. No simulator asserts headset correctness.
patch("tests/gaze_tests.cpp",
      'int main(int argc, char** argv) {',
      '''int main(int argc, char** argv) {
    if (argc == 2 && std::strcmp(argv[1], "--cheeky-r13") == 0) {
        using namespace cheeky::foveated_dlss;
        const auto saved = configured_settings();
        auto s = saved;
        expect(cheeky_processing_allowed_for_view(s, 99001),
            "Both/default leaves the legacy path untouched");
        s.eye_processing_mode = 1U;
        update_settings(s);
        expect(configured_settings().eye_processing_mode == 1U,
            "Eye 0 setting survives roundtrip");
        register_stereo_view(99001);
        expect(!cheeky_processing_allowed_for_view(s, 99001),
            "Unknown/one-view mapping never guesses source identity");
        register_stereo_view(99002);
        static_cast<void>(settings_for_view(s, 99001));
        static_cast<void>(settings_for_view(s, 99002));
        expect(cheeky_processing_allowed_for_view(s, 99001),
            "Role 0 gets Cheeky processing");
        expect(!cheeky_processing_allowed_for_view(s, 99002),
            "Role 1 bypasses Cheeky");
        s.eye_processing_mode = 2U;
        update_settings(s);
        expect(!cheeky_processing_allowed_for_view(s, 99001),
            "Role 0 bypasses on Eye 1 selection");
        expect(cheeky_processing_allowed_for_view(s, 99002),
            "Role 1 gets Cheeky processing");
        s.eye_processing_mode = 3U;
        update_settings(s);
        expect(configured_settings().eye_processing_mode == 0U,
            "Invalid eye selection is clamped to safe Both default");
        unregister_stereo_view(99001);
        unregister_stereo_view(99002);
        update_settings(saved);
        return failures ? 1 : 0;
    }''')

print("R13 source-eye filter installed: default Both, indexed source filtering and passthrough")
