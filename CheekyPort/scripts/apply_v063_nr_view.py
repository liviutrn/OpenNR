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
        // Regression: an SR crop may provide gaze positioning even when NR
        // has a separately configured size. It must not disable NR pass crops.
        Settings independent_settings{};
        independent_settings.nr_foveated = true;
        independent_settings.nr_use_sr_foveation = false;
        independent_settings.nr_width = 0.7F;
        independent_settings.nr_height = 0.6F;
        independent_settings.nr_extra_passes[0].independent_crop = true;
        independent_settings.nr_extra_passes[0].crop_width = 0.3F;
        independent_settings.nr_extra_passes[0].crop_height = 0.4F;
        const FoveationGeometry sr_gaze_crop{256U,192U,512U,384U,
            256U,192U,512U,384U};
        const auto outer_nr = calculate_region(independent_settings,1024U,768U,
            &sr_gaze_crop,1024U,768U,nullptr);
        const auto inner_nr = calculate_region(
            nr_pass_settings(independent_settings,1U),1024U,768U,
            &sr_gaze_crop,1024U,768U,nullptr);
        const auto mapped = dlss_nr_pass_subrect(outer_nr,inner_nr,512U,384U);
        expect(mapped.valid && mapped.width < 512U && mapped.height < 384U,
            "SR gaze metadata keeps independent NR pass crop active");
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
        command("1\\n212\\nset\\nNrPreset=2\\nNrPasses=2\\nNrWidth=0.7\\nNrIntensity=0.35\\nNrPass2IndependentCrop=true\\nNrPass2CropWidth=0.3\\nNrPass2CropHeight=0.45");
        command("1\\n213\\nnr_template_save_2");
        require(field(received, "NrTemplateActive")==2, "Template 2 save acknowledged");
        command("1\\n214\\nnr_template_load_1");
        require(field(received, "NrPreset")==1 && field(received, "NrPasses")==1 &&
            std::abs(field(received, "NrWidth")-0.4)<0.0001,
            "Template 1 model, pass count and crop restored");
        command("1\\n215\\nnr_template_load_2");
        require(field(received, "NrPreset")==2 && field(received, "NrPasses")==2 &&
            std::abs(field(received, "NrWidth")-0.7)<0.0001 &&
            field(received, "NrPass2IndependentCrop")==1 &&
            std::abs(field(received, "NrPass2CropWidth")-0.3)<0.0001 &&
            std::abs(field(received, "NrPass2CropHeight")-0.45)<0.0001 &&
            field(received, "EyeProcessingMode")==2,
            "Template 2 restores independent second crop without changing DuoView source selector");
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


# Independent *actual* evaluation subrects for chained NR passes.
# Keep the full shared HDR proxy and its depth/motion guides in a common coordinate
# space. Each pass has a centered, independently sized NGX evaluation rectangle.
# A partial pass copies its input to the output before neural evaluation so
# pixels outside that rectangle keep the preceding pass (no uninitialized GPU
# output, and no extra game render or composition pass).
patch("src/settings.hpp",
      "    float local_tone_strength{1.0F};\n    bool operator==(const NrExtraPass&) const = default;",
      """    float local_tone_strength{1.0F};
    bool independent_crop{false}; // When false inherit the first NR crop size.
    float crop_width{0.56F};      // Fractions of this DLSS source view.
    float crop_height{0.56F};
    bool operator==(const NrExtraPass&) const = default;""")
patch("src/settings.cpp",
      "        tuning(pass.local_tone_strength, 2.0F, 1.0F),\n    };",
      """        tuning(pass.local_tone_strength, 2.0F, 1.0F),
        pass.independent_crop,
        std::isfinite(pass.crop_width) ? std::clamp(pass.crop_width, 0.2F, 1.0F) : 0.56F,
        std::isfinite(pass.crop_height) ? std::clamp(pass.crop_height, 0.2F, 1.0F) : 0.56F,
    };""")
patch("src/settings.hpp",
      "    if (extra.same_as_pass1) return result;\n    result.nr_style = extra.style;",
      """    if (extra.independent_crop && result.nr_foveated && !result.nr_use_sr_foveation) {
        result.nr_width = std::clamp(extra.crop_width, 0.2F, 1.0F);
        result.nr_height = std::clamp(extra.crop_height, 0.2F, 1.0F);
    }
    if (extra.same_as_pass1) return result;
    result.nr_style = extra.style;""")
# This helper is pure integer geometry and unit-testable without an NVIDIA GPU.
patch("src/dlss_nr_contract.hpp",
      "#include <cstdint>",
      "#include <cstdint>\n#include <algorithm>")
patch("src/dlss_nr_contract.hpp",
      "struct ScaledSubrect {",
      """struct NrPassSubrect {
    std::uint32_t x{}, y{}, width{}, height{};
    bool valid{};
    [[nodiscard]] bool full(std::uint32_t w, std::uint32_t h) const noexcept {
        return valid && !x && !y && width == w && height == h;
    }
};

// Transfer a pass's absolute input region to the working-resolution allocation.
// Nested region checks prevent a mapping error from silently cropping wrong pixels.
[[nodiscard]] inline NrPassSubrect dlss_nr_pass_subrect(
    const NrRegion& allocation, const NrRegion& pass,
    std::uint32_t working_width, std::uint32_t working_height
) noexcept {
    NrPassSubrect out{};
    if (!working_width || !working_height || !allocation.width || !allocation.height ||
        !pass.width || !pass.height || pass.base_x < allocation.base_x ||
        pass.base_y < allocation.base_y ||
        std::uint64_t(pass.base_x) + pass.width > std::uint64_t(allocation.base_x) + allocation.width ||
        std::uint64_t(pass.base_y) + pass.height > std::uint64_t(allocation.base_y) + allocation.height)
        return out;
    const auto convert = [](std::uint32_t delta, std::uint32_t length,
        std::uint32_t full, std::uint32_t capacity, std::uint32_t& first,
        std::uint32_t& extent) noexcept {
        const auto begin = (std::uint64_t(delta) * capacity + full / 2U) / full;
        const auto end = (std::uint64_t(delta + length) * capacity + full / 2U) / full;
        first = std::uint32_t(std::min<std::uint64_t>(begin, capacity - 1U));
        extent = std::uint32_t(std::min<std::uint64_t>(capacity - first,
            std::max<std::uint64_t>(end > first ? end - first : 1U, 1U)));
    };
    convert(pass.base_x - allocation.base_x, pass.width, allocation.width,
            working_width, out.x, out.width);
    convert(pass.base_y - allocation.base_y, pass.height, allocation.height,
            working_height, out.y, out.height);
    out.valid = out.width != 0U && out.height != 0U;
    return out;
}

struct ScaledSubrect {""")
patch("uevr/settings_fields.inc",
      'CHEEKY_SETTING("NrPass2SameAsPass1", nr_extra_passes[0].same_as_pass1)',
      '''CHEEKY_SETTING("NrPass2SameAsPass1", nr_extra_passes[0].same_as_pass1)
CHEEKY_SETTING("NrPass2IndependentCrop", nr_extra_passes[0].independent_crop)
CHEEKY_SETTING("NrPass2CropWidth", nr_extra_passes[0].crop_width)
CHEEKY_SETTING("NrPass2CropHeight", nr_extra_passes[0].crop_height)''')
patch("uevr/settings_fields.inc",
      'CHEEKY_SETTING("NrPass3SameAsPass1", nr_extra_passes[1].same_as_pass1)',
      '''CHEEKY_SETTING("NrPass3SameAsPass1", nr_extra_passes[1].same_as_pass1)
CHEEKY_SETTING("NrPass3IndependentCrop", nr_extra_passes[1].independent_crop)
CHEEKY_SETTING("NrPass3CropWidth", nr_extra_passes[1].crop_width)
CHEEKY_SETTING("NrPass3CropHeight", nr_extra_passes[1].crop_height)''')
# Keep crop independent of model-tuning "Same as pass 1" switch.
patch("uevr/scripts/cheeky_foveated_dlss.lua",
      '    if not imgui.tree_node("Pass " .. number .. " settings") then return end',
      '''    if not imgui.tree_node("Pass " .. number .. " settings") then return end
    check("Independent crop size##" .. p, p .. "IndependentCrop")
    if draft[p .. "IndependentCrop"] == true then
        slider("Crop width (of source)##" .. p, p .. "CropWidth", 0.2, 1)
        slider("Crop height (of source)##" .. p, p .. "CropHeight", 0.2, 1)
        text("Centered on the same gaze point as Pass 1.")
        if draft.NrUseSrFoveation then
            text("Disable Use SR size and shape for independent crops.")
        end
    end''')
patch("uevr/scripts/cheeky_foveated_dlss.lua",
      '                    text("Each extra pass refines the previous one and costs about one more NR evaluation.")',
      '''                    text("Each pass may use its own crop width and height.")
                    text("Different crops use NVIDIA NGX subrects; GPU savings depend on runtime support.")
                    text("Each extra pass refines the previous output and costs one more NR evaluation.")''')
# The codec allocates the encompassing pass region and produces the shared
# normalized color/guide textures only once.
patch("src/dlss_nr.cpp",
      """    const auto region = calculate_region(
        settings,
        processing_width,""",
      """    Settings allocation_settings = settings;
    const bool independent_crops_allowed = settings.nr_foveated &&
        !settings.nr_use_sr_foveation && !frame.color_is_region;
    if (independent_crops_allowed) {
        for (std::uint32_t index = 1U;
             index < std::clamp(settings.nr_passes, 1U, max_nr_passes); ++index) {
            const auto pass = nr_pass_settings(settings, index);
            allocation_settings.nr_width = std::max(allocation_settings.nr_width, pass.nr_width);
            allocation_settings.nr_height = std::max(allocation_settings.nr_height, pass.nr_height);
        }
    }
    const auto region = calculate_region(
        allocation_settings,
        processing_width,""")
# NR histories must invalidate if the individual first crop changes while the
# union/allocation region stays constant because another pass is larger.
patch("src/dlss_nr.cpp",
      """    const auto signature = dlss_nr_history_signature(nr_settings_signature(settings, region), {""",
      """    const auto first_region = independent_crops_allowed
        ? calculate_region(settings, processing_width, processing_height,
            frame.has_shared_sr_crop ? &frame.shared_sr_crop : nullptr,
            frame.input_width, frame.input_height, frame.has_center ? &frame.center : nullptr)
        : region;
    const auto signature = dlss_nr_history_signature(
        nr_settings_signature(settings, region) ^
            (nr_settings_signature(settings, first_region) * 0x9e3779b97f4a7c15ULL), {""")
patch("src/dlss_nr.cpp",
      """        bool reset{};
    };
    std::array<ModelPass, max_nr_passes> passes{};
    passes[0] = {&view, settings, signature, reset};""",
      """        bool reset{};
        NrPassSubrect crop{};
    };
    std::array<ModelPass, max_nr_passes> passes{};
    const auto first_crop = dlss_nr_pass_subrect(region, first_region,
        working_width, working_height);
    if (!first_crop.valid) {
        diagnostics.state = DlssNrState::input_preparation_failed;
        diagnostics.skip_reason = "NR pass 1 crop outside shared allocation";
        ++diagnostics.failed_calls;
        return false;
    }
    passes[0] = {&view, settings, signature, reset, first_crop};""")
patch("src/dlss_nr.cpp",
      """        // Chain the signature so a change to an earlier pass resets later ones.
        const auto pass_signature = (passes[pass - 1U].signature * 1099511628211ULL) ^
            nr_settings_signature(pass_settings, region);
        const bool pass_reset = reset || !pass_view.was_enabled ||
            pass_view.settings_signature != pass_signature;
        passes[pass] = {&pass_view, std::move(pass_settings), pass_signature, pass_reset};""",
      """        const auto pass_region = independent_crops_allowed
            ? calculate_region(pass_settings, processing_width, processing_height,
                frame.has_shared_sr_crop ? &frame.shared_sr_crop : nullptr,
                frame.input_width, frame.input_height, frame.has_center ? &frame.center : nullptr)
            : region;
        const auto crop = dlss_nr_pass_subrect(region, pass_region, working_width, working_height);
        if (!crop.valid) {
            diagnostics.state = DlssNrState::input_preparation_failed;
            diagnostics.skip_reason = "Later NR pass crop outside shared allocation";
            ++diagnostics.failed_calls;
            return false;
        }
        // Chain signatures so changes in any earlier pass invalidate descendants.
        const auto pass_signature = (passes[pass - 1U].signature * 1099511628211ULL) ^
            nr_settings_signature(pass_settings, pass_region);
        const bool pass_reset = reset || !pass_view.was_enabled ||
            pass_view.settings_signature != pass_signature;
        passes[pass] = {&pass_view, std::move(pass_settings), pass_signature, pass_reset, crop};""")
patch("src/dlss_nr.cpp",
      """        move_model_output(output, D3D12_RESOURCE_STATE_UNORDERED_ACCESS);
        auto* const parameters = model.view->parameters;
        parameters->Set("DLSSNR.Color", pass_input);""",
      """        // When the pass covers only part of the common HDR proxy, preserve the
        // rest of its preceding pass by copying first. This is recorded on the
        // same command list, with explicit source/destination state transitions.
        if (!model.crop.full(working_width, working_height)) {
            if (pass_input == gpu->color_proxy) {
                transition(frame.command_list, pass_input,
                    D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE,
                    D3D12_RESOURCE_STATE_COPY_SOURCE);
            } else move_model_output(pass_input, D3D12_RESOURCE_STATE_COPY_SOURCE);
            move_model_output(output, D3D12_RESOURCE_STATE_COPY_DEST);
            frame.command_list->CopyResource(output, pass_input);
            if (pass_input == gpu->color_proxy) {
                transition(frame.command_list, pass_input,
                    D3D12_RESOURCE_STATE_COPY_SOURCE,
                    D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE);
            } else move_model_output(pass_input, D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE);
        }
        move_model_output(output, D3D12_RESOURCE_STATE_UNORDERED_ACCESS);
        auto* const parameters = model.view->parameters;
        parameters->Set("DLSSNR.Color", pass_input);""")
# Set matching color/depth/motion/output NGX subrects; guides are a single
# coherent common-resolution texture, so all four share exactly the same crop.
for key in ("Color", "Output", "Depth", "MVec"):
    patch("src/dlss_nr.cpp",
          f'        parameters->Set("DLSSNR.{key}SubrectBaseX", 0U);',
          f'        parameters->Set("DLSSNR.{key}SubrectBaseX", model.crop.x);')
    patch("src/dlss_nr.cpp",
          f'        parameters->Set("DLSSNR.{key}SubrectBaseY", 0U);',
          f'        parameters->Set("DLSSNR.{key}SubrectBaseY", model.crop.y);')
    patch("src/dlss_nr.cpp",
          f'        parameters->Set("DLSSNR.{key}SubrectWidth", working_width);',
          f'        parameters->Set("DLSSNR.{key}SubrectWidth", model.crop.width);')
    patch("src/dlss_nr.cpp",
          f'        parameters->Set("DLSSNR.{key}SubrectHeight", working_height);',
          f'        parameters->Set("DLSSNR.{key}SubrectHeight", model.crop.height);')
# Geometry unit tests prove nested, asymmetric, full-sized and invalid crops.
patch("tests/gaze_tests.cpp",
      '        // Independent source mapping regressions; UEVR serialization is',
      '''        const NrRegion outer{100U, 50U, 800U, 600U};
        const NrRegion middle{300U, 200U, 400U, 300U};
        const NrRegion invalid{0U, 0U, 400U, 300U};
        const auto inner = dlss_nr_pass_subrect(outer, middle, 400U, 300U);
        expect(inner.valid && inner.x == 100U && inner.y == 75U &&
            inner.width == 200U && inner.height == 150U,
            "Later pass independent centered crop has correct pixel subrect");
        expect(dlss_nr_pass_subrect(outer, outer, 400U, 300U).full(400U, 300U),
            "Matching pass crops preserve the old full-frame model path");
        expect(!dlss_nr_pass_subrect(outer, invalid, 400U, 300U).valid,
            "Out-of-allocation NR crop is rejected without GPU access");
        // Independent source mapping regressions; UEVR serialization is''')


# Keep per-pass temporal history coherent when a smaller crop shifts relative
# to the shared source allocation near screen boundaries.
patch("src/settings.hpp", '#include <cstdint>', '#include <algorithm>\n#include <cstdint>')
patch("src/dlss_nr.cpp",
      "    NrRegion last_region{};",
      "    NrRegion last_region{};\n    NrPassSubrect last_crop{};")
patch("src/dlss_nr.cpp",
      "    passes[0] = {&view, settings, signature, reset, first_crop};",
      """    const bool first_crop_changed = view.was_enabled &&
        (view.last_crop.x != first_crop.x || view.last_crop.y != first_crop.y ||
         view.last_crop.width != first_crop.width || view.last_crop.height != first_crop.height);
    passes[0] = {&view, settings, signature, reset || first_crop_changed, first_crop};""")
patch("src/dlss_nr.cpp",
      """        const bool pass_reset = reset || !pass_view.was_enabled ||
            pass_view.settings_signature != pass_signature;
        passes[pass] = {&pass_view, std::move(pass_settings), pass_signature, pass_reset, crop};""",
      """        const bool crop_changed = pass_view.was_enabled &&
            (pass_view.last_crop.x != crop.x || pass_view.last_crop.y != crop.y ||
             pass_view.last_crop.width != crop.width || pass_view.last_crop.height != crop.height);
        const bool pass_reset = reset || !pass_view.was_enabled || crop_changed ||
            pass_view.settings_signature != pass_signature;
        passes[pass] = {&pass_view, std::move(pass_settings), pass_signature, pass_reset, crop};""")
patch("src/dlss_nr.cpp",
      """    view.last_region = region; view.last_order = settings.nr_processing_order;""",
      """    view.last_region = region; view.last_crop = passes[0].crop;
    view.last_order = settings.nr_processing_order;""")
patch("src/dlss_nr.cpp",
      """        passes[pass].view->settings_signature = passes[pass].signature;
        passes[pass].view->was_enabled = true;""",
      """        passes[pass].view->settings_signature = passes[pass].signature;
        passes[pass].view->last_crop = passes[pass].crop;
        passes[pass].view->was_enabled = true;""")

print("Cheeky v0.6.3 r13 minimal source selector applied")
