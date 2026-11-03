#!/usr/bin/env python3
"""Port only verified r13 source-view gating onto upstream Cheeky v0.6.3."""
from pathlib import Path
import sys
root=Path(sys.argv[1]).resolve()
def patch(path,old,new,count=1):
    f=root/path; s=f.read_text(encoding="utf-8"); n=s.count(old)
    if n!=count: raise RuntimeError(f"{path}: expected {count}, found {n}: {old[:100]!r}")
    f.write_text(s.replace(old,new),encoding="utf-8",newline="\n")
    print("PATCH",path,count)

patch("src/settings.hpp","    bool enabled{true};",
      "    bool enabled{true};\n    std::uint32_t eye_processing_mode{0U}; // Both=0, view0=1, view1=2")
patch("src/settings.hpp","[[nodiscard]] Settings settings_for_view(",
      "[[nodiscard]] bool cheeky_processing_allowed_for_view(const Settings&, std::uint64_t) noexcept;\n[[nodiscard]] Settings settings_for_view(")
patch("src/settings.cpp","std::atomic<bool> enabled{true};",
      "std::atomic<bool> enabled{true};\nstd::atomic<std::uint32_t> eye_processing_mode{0U};")
patch("src/settings.cpp","    settings.enabled = enabled.load(std::memory_order_acquire);",
      "    settings.enabled = enabled.load(std::memory_order_acquire);\n    settings.eye_processing_mode = eye_processing_mode.load(std::memory_order_acquire);")
patch("src/settings.cpp","    enabled.store(settings.enabled, std::memory_order_release);",
      "    enabled.store(settings.enabled, std::memory_order_release);\n    eye_processing_mode.store(settings.eye_processing_mode <= 2U ? settings.eye_processing_mode : 0U, std::memory_order_release);")
patch("src/settings.cpp","Settings settings_for_view(\n",
"""bool cheeky_processing_allowed_for_view(const Settings& settings,
    const std::uint64_t view_id) noexcept {
    if (settings.eye_processing_mode == 0U) return true;
    if (view_id == 0U || settings.eye_processing_mode > 2U) return false;
    // Identical to proven r13: use existing role coordinator, not handle order.
    static_cast<void>(settings_for_view(settings, view_id));
    const auto role = stereo_eye_assignment(view_id);
    if (!role.assigned || role.shared_source) return false;
    return role.eye_index == settings.eye_processing_mode - 1U;
}

Settings settings_for_view(
""")
patch("uevr/settings_fields.inc",'CHEEKY_SETTING("Enabled", enabled)',
      'CHEEKY_SETTING("Enabled", enabled)\nCHEEKY_SETTING("EyeProcessingMode", eye_processing_mode)')
patch("uevr/settings_io.cpp",'for (const auto gaze : {"XOffset",',
      'for (const auto gaze : {"EyeProcessingMode", "XOffset",')
patch("uevr/settings_io.cpp",'    candidate.d3d12_lower_hook = true; // Older files use the new lower-hook default.',
      '    candidate.d3d12_lower_hook = true; // Older files use the new lower-hook default.\n    candidate.eye_processing_mode = 0U;')
patch("uevr/scripts/cheeky_foveated_dlss.lua",
      '"EyeCalibrationContinuous", "EyeCalibrationMethod"}) do',
      '"EyeCalibrationContinuous", "EyeCalibrationMethod", "EyeProcessingMode"}) do')
patch("uevr/scripts/cheeky_foveated_dlss.lua",
      '        reset_group("Reset Stereo / gaze defaults", "gaze")',
'''        if draft.EyeProcessingMode ~= nil then
            section("DuoView: NR source view")
            combo("NR processing view", "EyeProcessingMode",
                {[0]="Both", [1]="View 0 only", [2]="View 1 only"}, {0,1,2})
            text("Deselected view uses native game DLSS; UEVR still renders both.")
            text("Unknown/shared-mono mapping stays native until identified.")
        end
        reset_group("Reset Stereo / gaze defaults", "gaze")''')

patch("src/hooks.cpp",
      "    auto settings = current_settings();\n    if(quad_view_snapshot().active)settings=settings_for_view(settings,reinterpret_cast<std::uintptr_t>(call.handle));",
"""    auto settings = current_settings();
    const auto id = static_cast<DlssViewId>(reinterpret_cast<std::uintptr_t>(call.handle));
    if (!cheeky_processing_allowed_for_view(settings, id)) {
        skip_d3d12_history(id);
        skip_d3d12_history(peripheral_dlaa_view_id(id));
        skip_dlss_nr_history(id);
        return original(call.command_list, call.handle, call.parameters, call.callback);
    }
    if(quad_view_snapshot().active)settings=settings_for_view(settings,reinterpret_cast<std::uintptr_t>(call.handle));""")
patch("src/hooks.cpp",
      "    auto settings = current_settings();\n    if(quad_view_snapshot().active)settings=settings_for_view(settings,reinterpret_cast<std::uintptr_t>(handle));",
"""    auto settings = current_settings();
    const auto id = static_cast<DlssViewId>(reinterpret_cast<std::uintptr_t>(handle));
    if (!cheeky_processing_allowed_for_view(settings, id)) {
        skip_d3d12_history(id);
        skip_d3d12_history(peripheral_dlaa_view_id(id));
        skip_dlss_nr_history(id);
        return original(command_list, handle, parameters, callback);
    }
    if(quad_view_snapshot().active)settings=settings_for_view(settings,reinterpret_cast<std::uintptr_t>(handle));""")
patch("src/hooks.cpp",
      "    const auto settings = settings_for_view(current_settings(),reinterpret_cast<uintptr_t>(handle));",
"""    const auto settings = settings_for_view(current_settings(),reinterpret_cast<uintptr_t>(handle));
    if (!cheeky_processing_allowed_for_view(settings,
            static_cast<DlssViewId>(reinterpret_cast<std::uintptr_t>(handle)))) {
        skip_dlss_nr_history(static_cast<DlssViewId>(reinterpret_cast<std::uintptr_t>(handle)));
        return original(context, handle, parameters, callback);
    }""",count=2)
patch("src/hooks.cpp",
      "    const auto live_settings = current_settings();\n    NrPipelineTimingScope pipeline_timing{",
"""    const auto live_settings = current_settings();
    if (live_settings.eye_processing_mode != 0U) {
        const auto id = static_cast<DlssViewId>(cached_sl_options_viewport.value) + 1U;
        register_stereo_view(id);
        if (!cheeky_processing_allowed_for_view(live_settings, id)) {
            for (auto& history : streamline_crop_history) {
                if (history.viewport != cached_sl_options_viewport.value) continue;
                history.valid = false;
                history.afw_skipped = true;
            }
            skip_d3d12_history(id);
            skip_dlss_nr_history(id);
            StreamlineEvaluationScope native_scope;
            const auto result = original(feature, frame, inputs, input_count, command_buffer);
            stamp_streamline_output(static_cast<ID3D12GraphicsCommandList*>(command_buffer), result);
            return result;
        }
    }
    NrPipelineTimingScope pipeline_timing{""")
patch("tests/gaze_tests.cpp", '#include "foveation.hpp"', '#include "foveation.hpp"\n#include "settings_io.hpp"')
patch("tests/gaze_tests.cpp","int main(int argc, char** argv) {",
'''int main(int argc, char** argv) {
    if (argc == 2 && std::strcmp(argv[1], "--opennr-v063") == 0) {
        using namespace cheeky::foveated_dlss;
        const auto old = configured_settings();
        auto s = old;
        s.eye_processing_mode = 0U;
        expect(cheeky_processing_allowed_for_view(s, 99001), "Both is upstream");
        s.eye_processing_mode = 1U;
        update_settings(s);
        expect(configured_settings().eye_processing_mode == 1U, "Setting persists");
        register_stereo_view(99001);
        expect(!cheeky_processing_allowed_for_view(s,99001), "Unknown view passthrough");
        register_stereo_view(99002);
        static_cast<void>(settings_for_view(s,99001));
        static_cast<void>(settings_for_view(s,99002));
        expect(cheeky_processing_allowed_for_view(s,99001), "View 0 selected");
        expect(!cheeky_processing_allowed_for_view(s,99002), "View 1 deselected");
        s.eye_processing_mode = 2U;
        expect(!cheeky_processing_allowed_for_view(s,99001), "View 0 deselected");
        expect(cheeky_processing_allowed_for_view(s,99002), "View 1 selected");
        s.eye_processing_mode = 3U;
        update_settings(s);
        expect(configured_settings().eye_processing_mode == 0U, "Invalid mode to Both");
        // Fresh-review additions: configuration roundtrip and safe reset.
        Settings saved_file{};
        expect(set_named_setting(saved_file, "EyeProcessingMode", "2") &&
            saved_file.eye_processing_mode == 2U, "UEVR settings parser accepts view 1");
        expect(serialize_settings(saved_file).find("EyeProcessingMode=2") != std::string::npos,
            "UEVR settings file persists view selection");
        expect(settings_json(saved_file).find("\\\"EyeProcessingMode\\\":2") != std::string::npos,
            "UEVR live UI snapshot reports active selector");
        expect(reset_settings_group(saved_file, "gaze") && saved_file.eye_processing_mode == 0U,
            "Stereo/gaze Reset returns selection to Both");

        // Assigned source identity must not silently depend on the initial
        // NGX registration order once a calibrated stereo mapping is learned.
        const auto generation0 = stereo_view_generation(99001);
        const auto generation1 = stereo_view_generation(99002);
        expect(publish_stereo_calibration(99002, 99001, generation1, generation0,
            100U, GetTickCount64(), nullptr, 1U),
            "Calibrated reversed-eye source mapping published");
        s.eye_processing_mode = 1U;
        expect(cheeky_processing_allowed_for_view(s, 99002) &&
            !cheeky_processing_allowed_for_view(s, 99001),
            "A legitimate calibration reversal follows the mapped role");
        s.eye_processing_mode = 2U;
        expect(cheeky_processing_allowed_for_view(s, 99001) &&
            !cheeky_processing_allowed_for_view(s, 99002),
            "Opposite calibrated role selects the other source");

        // An OpenXR mono submission may map both physical eyes to one DLSS
        // source. Never invent an extra render pass or process the wrong one.
        unregister_stereo_view(99001);
        unregister_stereo_view(99002);
        register_stereo_view(99003);
        const auto shared_generation = stereo_view_generation(99003);
        expect(publish_stereo_calibration(99003, 99003, shared_generation, shared_generation,
            101U, GetTickCount64(), nullptr, 1U, false, true),
            "Shared-mono calibration published");
        s.eye_processing_mode = 1U;
        expect(!cheeky_processing_allowed_for_view(s, 99003),
            "Shared-mono source bypasses view 0 selection");
        s.eye_processing_mode = 2U;
        expect(!cheeky_processing_allowed_for_view(s, 99003),
            "Shared-mono source bypasses view 1 selection");
        s.eye_processing_mode = 0U;
        expect(cheeky_processing_allowed_for_view(s, 99003),
            "Both remains upstream-compatible even for shared-mono");
        unregister_stereo_view(99003);
        update_settings(old);
        return failures ? 1 : 0;
    }''')
print("Cheeky v0.6.3 r13 minimal source selector applied")
