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
        // Independent source mapping regressions; UEVR serialization is
        // tested separately by the native UEVR runtime integration harness.
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

# Independent integration tests use the *real* UEVR runtime command bridge,
# rather than just calling the selector directly in the coordinator fixture.
patch("tests/uevr_tests.cpp",
      '        for (unsigned i = 0; i < 35; ++i) { Sleep(10); present(); }',
      r'''        command("1\n201\nset\nEyeProcessingMode=0");
        require(field(received, "EyeProcessingMode")==0, "Both mode acknowledged by live UEVR runtime");
        command("1\n202\nset\nEyeProcessingMode=1");
        require(field(received, "EyeProcessingMode")==1, "View 0 mode acknowledged by live UEVR runtime");
        command("1\n203\nset\nEyeProcessingMode=2");
        require(field(received, "EyeProcessingMode")==2, "View 1 mode acknowledged by live UEVR runtime");
        for (unsigned i = 0; i < 35; ++i) { Sleep(10); present(); }''')
patch("tests/uevr_tests.cpp",
      '        require(!saved.eye_calibration_continuous, "Calibration policy must be saved per game");',
      '''        require(saved.eye_processing_mode == 2U, "View selection was not persisted to disk");
        require(!saved.eye_calibration_continuous, "Calibration policy must be saved per game");''')
patch("tests/uevr_tests.cpp",
      '        require(field(received,"NrProcessingOrder")==1 && std::abs(field(received,"NrWorkingScale")-0.37)<0.0001,',
      '''        require(field(received,"EyeProcessingMode")==2, "UEVR plugin reload lost selected view");
        require(field(received,"NrProcessingOrder")==1 && std::abs(field(received,"NrWorkingScale")-0.37)<0.0001,''')


# Per-game dual NR templates. Templates live beside the usual Cheeky INI, but
# only Nr* fields are restored. SR, FG and DuoView source selection remain live.
patch("src/settings.hpp",
      "    std::uint32_t nr_preset{};",
      "    std::uint32_t nr_preset{};\n    std::uint32_t nr_template_active{}; // 0 custom; 1/2 last loaded or saved slot")
patch("src/settings.cpp",
      "std::atomic<std::uint32_t> nr_preset{};",
      "std::atomic<std::uint32_t> nr_preset{};\nstd::atomic<std::uint32_t> nr_template_active{};")
patch("src/settings.cpp",
      "    settings.nr_preset = nr_preset.load(std::memory_order_acquire);",
      "    settings.nr_preset = nr_preset.load(std::memory_order_acquire);\n    settings.nr_template_active = nr_template_active.load(std::memory_order_acquire);")
patch("src/settings.cpp",
      "    nr_preset.store((std::min)(settings.nr_preset, 7U), std::memory_order_release);",
      "    nr_preset.store((std::min)(settings.nr_preset, 7U), std::memory_order_release);\n    nr_template_active.store((std::min)(settings.nr_template_active, 2U), std::memory_order_release);")
patch("uevr/settings_fields.inc",
      'CHEEKY_SETTING("NrPreset", nr_preset)',
      'CHEEKY_SETTING("NrPreset", nr_preset)\nCHEEKY_SETTING("NrTemplateActive", nr_template_active)')
# 310.9.16 NR packs original and faster models. Values are independently
# verified: 1=original 310.8, 2=new 310.9, 0=runtime default (new on 310.9).
patch("uevr/scripts/cheeky_foveated_dlss.lua",
      '                slider("NR working scale", "NrWorkingScale", 0.1, 1)',
      '''                slider("NR working scale", "NrWorkingScale", 0.1, 1)
                if draft.NrPreset ~= nil then
                    combo("NR model", "NrPreset",
                        {[0]="Default (DLL choice)",[1]="Original (310.8 / A)",
                         [2]="Faster (310.9 / B)"}, {0,1,2})
                    text("Model change recreates NR features and resets temporal history.")
                end''')
patch("uevr/scripts/cheeky_foveated_dlss.lua",
      '    if imgui.tree_node("DLSS-NR (experimental)") then',
      '''    if imgui.tree_node("DLSS-NR (experimental)") then
        section("Saved NR templates")
        text("Save or load all NR settings, including model and pass settings.")
        if draft.NrTemplateActive ~= nil then
            local active = draft.NrTemplateActive
            text("Last loaded/saved template: " .. (active == 1 and "1" or active == 2 and "2" or "Custom"))
        end
        local blocked = pending_apply ~= nil or next(dirty) ~= nil
        if blocked then text("Apply pending edits before saving or switching templates.") end
        imgui.begin_disabled(blocked)
        if imgui.button("Save current as Template 1") then send("nr_template_save_1") end
        imgui.same_line()
        if imgui.button("Load Template 1") then send("nr_template_load_1") end
        if imgui.button("Save current as Template 2") then send("nr_template_save_2") end
        imgui.same_line()
        if imgui.button("Load Template 2") then send("nr_template_load_2") end
        if imgui.button("Toggle Template 1 / 2") then send("nr_template_toggle") end
        imgui.end_disabled()
        text("Loading changes NR only; source-view selection, SR and FG are untouched.")''')
# The game config directory is established by UEVR; no user-supplied path.
# On error leave current settings completely untouched, including active slot.
patch("uevr/runtime.cpp",
      '        if (action == "reset_nr") { reset_dlss_nr(); return true; }',
      '''        if (action == "reset_nr") { reset_dlss_nr(); return true; }
        if (action.starts_with("nr_template_save_") ||
            action.starts_with("nr_template_load_") ||
            action == "nr_template_toggle") {
            const bool saving = action.starts_with("nr_template_save_");
            const bool toggling = action == "nr_template_toggle";
            const auto suffix = toggling ? "" : action.substr(17U);
            if (!toggling && suffix != "1" && suffix != "2") {
                s.message = "Invalid NR template slot"; return false;
            }
            const auto slot = toggling
                ? (configured_settings().nr_template_active == 1U ? 2U : 1U)
                : static_cast<std::uint32_t>(suffix[0] - '0');
            const auto filepath = s.directory /
                (slot == 1U ? L"CheekyFoveatedDLSS-NR-Template-1.ini"
                            : L"CheekyFoveatedDLSS-NR-Template-2.ini");
            auto settings = configured_settings();
            std::string error;
            if (saving) {
                // Preserve all Nr* fields as a transaction; template loading
                // deliberately ignores every other saved setting.
                if (!write_settings_file(filepath, settings, error)) {
                    s.message = "NR template save failed: " + error; return false;
                }
            } else {
                Settings stored{};
                if (!read_settings_file(filepath, stored, error)) {
                    s.message = "NR template load failed: " + error; return false;
                }
#define CHEEKY_SETTING(name, field) if (std::string_view(name).starts_with("Nr") && std::string_view(name) != "NrTemplateActive") settings.field = stored.field;
#include "settings_fields.inc"
#undef CHEEKY_SETTING
                update_settings(settings);
                reset_dlss_nr(); // Do not reuse another model's temporal history.
            }
            settings.nr_template_active = slot;
            update_settings(settings);
            ++s.revision;
            s.applied_request = id;
            s.message = saving ? "NR Template saved" : "NR Template loaded";
            request_save(s);
            return true;
        }''')
# Tests exercise the real UEVR API, persistence and two profiles.
patch("tests/uevr_tests.cpp",
      '        for (unsigned i = 0; i < 35; ++i) { Sleep(10); present(); }',
      '''        command("1\\n210\\nset\\nNrPreset=1\\nNrPasses=1\\nNrWidth=0.4\\nNrIntensity=0.7");
        command("1\\n211\\nnr_template_save_1");
        require(field(received, "NrTemplateActive")==1, "Template 1 save acknowledged");
        command("1\\n212\\nset\\nNrPreset=2\\nNrPasses=2\\nNrWidth=0.7\\nNrIntensity=0.35");
        command("1\\n213\\nnr_template_save_2");
        require(field(received, "NrTemplateActive")==2, "Template 2 save acknowledged");
        command("1\\n214\\nnr_template_load_1");
        require(field(received, "NrPreset")==1 && field(received, "NrPasses")==1 &&
            std::abs(field(received, "NrWidth")-0.4)<0.0001,
            "Template 1 model, pass count and crop restored");
        command("1\\n215\\nnr_template_load_2");
        require(field(received, "NrPreset")==2 && field(received, "NrPasses")==2 &&
            std::abs(field(received, "NrWidth")-0.7)<0.0001,
            "Template 2 model, pass count and crop restored");
        command("1\\n216\\nnr_template_toggle");
        require(field(received, "NrPreset")==1 && field(received,"NrTemplateActive")==1,
            "One-click toggle switched from template 2 to template 1");
        command("1\\n217\\nnr_template_toggle");
        require(field(received, "NrPreset")==2 && field(received,"NrTemplateActive")==2,
            "One-click toggle switched from template 1 to template 2");
        require(std::filesystem::exists(root/"CheekyFoveatedDLSS-NR-Template-1.ini") &&
            std::filesystem::exists(root/"CheekyFoveatedDLSS-NR-Template-2.ini"),
            "Both template files persisted");
        for (unsigned i = 0; i < 35; ++i) { Sleep(10); present(); }''')

print("Cheeky v0.6.3 r13 minimal source selector applied")
