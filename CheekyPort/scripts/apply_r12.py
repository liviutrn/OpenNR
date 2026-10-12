#!/usr/bin/env python3
"""Cheeky r12 isolated changes on pinned v0.5.5 + successful r11 patches."""
from pathlib import Path
import sys
root=Path(sys.argv[1]).resolve()
def patch(file,old,new,count=1):
    p=root/file; s=p.read_text(encoding="utf-8")
    if s.count(old)!=count: raise RuntimeError(f"R12 {file}: anchor matched {s.count(old)}, expected {count}: {old[:100]}")
    p.write_text(s.replace(old,new),encoding="utf-8",newline="\n")
    print("R12",file,"anchors",count)

patch("src/settings.hpp","    float aligned_height_offset{0.0F};",
      "    float aligned_height_offset{0.0F};\n    float gaze_vertical_offset{0.0F}; // valid gaze UV shift, never fallback")
patch("src/settings.cpp","std::atomic<std::uint32_t> aligned_height_offset_bits{};",
      "std::atomic<std::uint32_t> aligned_height_offset_bits{};\nstd::atomic<std::uint32_t> gaze_vertical_offset_bits{};")
patch("src/settings.cpp","    settings.aligned_height_offset = load_float(aligned_height_offset_bits);",
      "    settings.aligned_height_offset = load_float(aligned_height_offset_bits);\n    settings.gaze_vertical_offset = load_float(gaze_vertical_offset_bits);")
patch("src/settings.cpp","    store_float(aligned_height_offset_bits, std::clamp(settings.aligned_height_offset, -1.0F, 1.0F));",
      "    store_float(aligned_height_offset_bits, std::clamp(settings.aligned_height_offset, -1.0F, 1.0F));\n    store_float(gaze_vertical_offset_bits, std::isfinite(settings.gaze_vertical_offset)\n        ? std::clamp(settings.gaze_vertical_offset, -0.5F, 0.5F) : 0.0F);")
patch("uevr/settings_fields.inc",'CHEEKY_SETTING("AlignedHeightOffset", aligned_height_offset)',
      'CHEEKY_SETTING("AlignedHeightOffset", aligned_height_offset)\nCHEEKY_SETTING("GazeVerticalOffset", gaze_vertical_offset)')
patch("uevr/scripts/cheeky_foveated_dlss.lua",
      '        if imgui.tree_node("Advanced eye tracking") then\n            slider("Gaze smoothing (ms)", "GazeSmoothingMs", 0, 100)',
      '        if imgui.tree_node("Advanced eye tracking") then\n            if draft.CenterMode ~= 0 then\n                slider("Live gaze vertical offset", "GazeVerticalOffset", -0.5, 0.5)\n                text("Shift the real tracked gaze center vertically; zero preserves r11 position.")\n            end\n            slider("Gaze smoothing (ms)", "GazeSmoothingMs", 0, 100)')
# Shift the final filtered location, not the tracked sample or cached gaze history.
patch("src/gaze_foveation.cpp",
      "    if (resolved_center) *resolved_center = {temporal_result.center_u, temporal_result.center_v,\n        settings.gaze_quantization_pixels};",
      "    const float live_center_v = std::clamp(temporal_result.center_v +\n        (temporal_result.using_gaze ? settings.gaze_vertical_offset : 0.0F), 0.0F, 1.0F);\n    if (resolved_center) *resolved_center = {temporal_result.center_u, live_center_v,\n        settings.gaze_quantization_pixels};")
patch("src/gaze_foveation.cpp",
      "                temporal_result.center_u,\n                temporal_result.center_v,\n                settings.gaze_quantization_pixels\n            },",
      "                temporal_result.center_u,\n                live_center_v,\n                settings.gaze_quantization_pixels\n            },")
# UEVR AFW bilateral: shift filtered and fresh gaze together so coverage still contains gaze.
patch("src/gaze_foveation.cpp",
      "        reacquired |= filtered.reacquired; tracking |= filtered.using_gaze;\n        bounds.include({filtered.center_u, filtered.center_v, 1}, settings.afw_gaze_width, settings.afw_gaze_height);",
      "        reacquired |= filtered.reacquired; tracking |= filtered.using_gaze;\n        const float live_bias = filtered.using_gaze ? settings.gaze_vertical_offset : 0.0F;\n        const float displayed_v = std::clamp(filtered.center_v + live_bias, 0.0F, 1.0F);\n        bounds.include({filtered.center_u, displayed_v, 1}, settings.afw_gaze_width, settings.afw_gaze_height);")
patch("src/gaze_foveation.cpp",
      "        afw_mask_include(mask, {filtered.center_u, filtered.center_v, 1}, settings.afw_gaze_width, settings.afw_gaze_height,",
      "        afw_mask_include(mask, {filtered.center_u, displayed_v, 1}, settings.afw_gaze_width, settings.afw_gaze_height,")
patch("src/gaze_foveation.cpp",
      "            bounds.include(raw[eye], settings.afw_gaze_width, settings.afw_gaze_height);\n            afw_mask_include(mask, raw[eye], settings.afw_gaze_width, settings.afw_gaze_height, settings.afw_warp_margin,",
      "            const auto shifted_raw = FoveationCenter{raw[eye].u,\n                std::clamp(raw[eye].v + settings.gaze_vertical_offset, 0.0F, 1.0F), 1U};\n            bounds.include(shifted_raw, settings.afw_gaze_width, settings.afw_gaze_height);\n            afw_mask_include(mask, shifted_raw, settings.afw_gaze_width, settings.afw_gaze_height, settings.afw_warp_margin,")
patch("src/gaze_foveation.cpp",
      "        diagnostics.views[eye].center_u = filtered.center_u; diagnostics.views[eye].center_v = filtered.center_v;",
      "        diagnostics.views[eye].center_u = filtered.center_u; diagnostics.views[eye].center_v = displayed_v;")
patch("src/gaze_foveation.cpp",
      "            afw_mask_include(fresh_mask, raw[eye], settings.afw_gaze_width, settings.afw_gaze_height,",
      "            afw_mask_include(fresh_mask, {raw[eye].u,\n                std::clamp(raw[eye].v + settings.gaze_vertical_offset, 0.0F, 1.0F), 1U}, settings.afw_gaze_width, settings.afw_gaze_height,")
# Genuine NR stability fix: tiny guide rounding differences no longer invalidate
# all model history. Larger scale changes, geometry changes and lost overlap still reset.
patch("src/dlss_nr_contract.cpp",
      "        previous.scale_x != current.scale_x || previous.scale_y != current.scale_y ||\n        current.width == 0U || current.height == 0U) return false;",
      "        current.width == 0U || current.height == 0U) return false;\n    if (!std::isfinite(previous.scale_x) || !std::isfinite(previous.scale_y) ||\n        !std::isfinite(current.scale_x) || !std::isfinite(current.scale_y)) return false;\n    const auto scale_close=[](float a,float b) {\n        return std::abs(a-b) <= 0.005F * (std::max)(0.0001F,(std::max)(std::abs(a),std::abs(b)));\n    };\n    if (!scale_close(previous.scale_x,current.scale_x) ||\n        !scale_close(previous.scale_y,current.scale_y)) return false;")
patch("tests/nr_processing_tests.cpp",
      "        current.x += 8U;\n        float dx{}, dy{};",
      "        current.x += 8U;\n        float dx{}, dy{};\n        auto rounding=current; rounding.scale_x *= 1.002F;\n        require(dlss_nr_motion_offset(previous,rounding,dx,dy),\n            \"Subpixel guide scale rounding must preserve NR history\");\n        auto changed=current; changed.scale_x *= 1.05F;\n        require(!dlss_nr_motion_offset(previous,changed,dx,dy),\n            \"A significant motion guide scale change must reset NR history\");")
# Expose NR reset/movement counters and the last reason; all reads under NR mutex.
patch("src/dlss_nr.hpp",
      "    std::uint64_t codec_creations{}, border_creations{}, resource_rebinds{};",
      "    std::uint64_t codec_creations{}, border_creations{}, resource_rebinds{};\n    std::uint64_t history_calls{}, history_moves{}, history_resets{}, history_corrections{};\n    const char* history_reset_reason{};")
patch("src/dlss_nr.cpp",
      "    if (corrected) ++view.history_corrections;\n    const bool compensation_failed",
      "    if (corrected) ++view.history_corrections;\n    diagnostics.history_calls=view.history_calls;\n    diagnostics.history_moves=view.history_moves;\n    diagnostics.history_resets=view.history_resets;\n    diagnostics.history_corrections=view.history_corrections;\n    diagnostics.history_reset_reason=reset_reason ? reset_reason : \"none\";\n    const bool compensation_failed")
# Report actual private SR reconstruction and NGX success, not only a saved setting.
patch("src/backend.hpp",
      "struct D3D12Evaluation;",
      """struct D3D12Evaluation;
struct SrReconstructionStatus {
    std::uint32_t input_width{}, input_height{}, display_width{}, display_height{};
    std::uint32_t reconstruction_width{}, reconstruction_height{};
    bool attempted{}, succeeded{};
};
[[nodiscard]] SrReconstructionStatus sr_reconstruction_status() noexcept;""")
patch("src/d3d12_backend.cpp",
      "std::atomic<std::uint64_t> canonical_failure_sequence{};",
      """std::atomic<std::uint64_t> canonical_failure_sequence{};
std::atomic<std::uint32_t> sr_input_w{},sr_input_h{},sr_display_w{},sr_display_h{},sr_recon_w{},sr_recon_h{};
std::atomic<bool> sr_attempt{},sr_success{};
void record_sr_plan(const CropGeometry& display,const CropGeometry& reconstruction) noexcept {
    sr_success.store(false,std::memory_order_relaxed);
    sr_input_w.store(display.input_width); sr_input_h.store(display.input_height);
    sr_display_w.store(display.output_width); sr_display_h.store(display.output_height);
    sr_recon_w.store(reconstruction.output_width); sr_recon_h.store(reconstruction.output_height);
    sr_attempt.store(true,std::memory_order_release);
}""")
patch("src/d3d12_backend.cpp",
      "    const auto reconstruction = supersampled_crop(crop, settings.center_supersampling);\n    auto* const resources = find_or_create_resources(",
      "    const auto reconstruction = supersampled_crop(crop, settings.center_supersampling);\n    record_sr_plan(crop, reconstruction);\n    auto* const resources = find_or_create_resources(",2)
patch("src/d3d12_backend.cpp",
      "    if (evaluation == nullptr) {\n        return;\n    }\n\n    if (parameters != nullptr) {",
      "    if (evaluation == nullptr) {\n        return;\n    }\n    sr_success.store(ngx_succeeded(result),std::memory_order_release);\n\n    if (parameters != nullptr) {")
patch("src/d3d12_backend.cpp",
      "CropGeometry d3d12_reconstruction_crop(const D3D12Evaluation* evaluation) noexcept {",
      """SrReconstructionStatus sr_reconstruction_status() noexcept {
    SrReconstructionStatus s{};
    s.attempted=sr_attempt.load(std::memory_order_acquire);
    s.succeeded=sr_success.load(std::memory_order_acquire);
    s.input_width=sr_input_w.load(); s.input_height=sr_input_h.load();
    s.display_width=sr_display_w.load(); s.display_height=sr_display_h.load();
    s.reconstruction_width=sr_recon_w.load(); s.reconstruction_height=sr_recon_h.load();
    return s;
}
CropGeometry d3d12_reconstruction_crop(const D3D12Evaluation* evaluation) noexcept {""")
patch("uevr/runtime.cpp",
      '#include "diagnostics.hpp"',
      '#include "diagnostics.hpp"\n#include "backend.hpp"')
patch("uevr/runtime.cpp",
      "    const auto gpu = gpu_timing_status();\n    out <<",
      "    const auto gpu = gpu_timing_status();\n    const auto sr=sr_reconstruction_status();\n    out <<")
patch("uevr/runtime.cpp",
      '        << ",\\\"nr_details\\\":{"',
      '        << ",\\\"sr_reconstruction\\\":{\\\"attempted\\\":" << sr.attempted\n        << ",\\\"succeeded\\\":" << sr.succeeded\n        << ",\\\"requested_scale\\\":" << configured_settings().center_supersampling\n        << ",\\\"input_width\\\":" << sr.input_width << ",\\\"input_height\\\":" << sr.input_height\n        << ",\\\"display_width\\\":" << sr.display_width << ",\\\"display_height\\\":" << sr.display_height\n        << ",\\\"output_width\\\":" << sr.reconstruction_width << ",\\\"output_height\\\":" << sr.reconstruction_height << "}"\n        << ",\\\"nr_details\\\":{"')
patch("uevr/runtime.cpp",
      '        << ",\\\"codec_creations\\\":" << nr.codec_creations',
      '        << ",\\\"history_calls\\\":" << nr.history_calls\n        << ",\\\"history_moves\\\":" << nr.history_moves\n        << ",\\\"history_resets\\\":" << nr.history_resets\n        << ",\\\"history_corrections\\\":" << nr.history_corrections\n        << ",\\\"history_reset_reason\\\":\\\"" << json_escape(nr.history_reset_reason ? nr.history_reset_reason : "none") << "\\\""\n        << ",\\\"codec_creations\\\":" << nr.codec_creations')
patch("uevr/scripts/cheeky_foveated_dlss.lua",
      '    if imgui.tree_node("Performance") then performance(d, f); imgui.tree_pop() end',
      '''    if imgui.tree_node("Performance") then
        performance(d, f)
        local sr = status.sr_reconstruction or {}
        section("Center SR reconstruction (DX12)")
        rows("sr_reconstruction_r12", {
            {"Requested", string.format("%.2fx", sr.requested_scale or 1)},
            {"Private NGX result", sr.attempted and (sr.succeeded and "Successful" or "Not successful / pending") or "No private SR attempt"},
            {"Center input", size(sr.input_width, sr.input_height)},
            {"Center display", size(sr.display_width, sr.display_height)},
            {"Center reconstructed", size(sr.output_width, sr.output_height)}
        })
        local nr = status.nr_details or {}
        section("NR gaze history (latest eye)")
        rows("nr_gaze_history_r12", {
            {"NR evaluations", nr.history_calls or 0},
            {"Gaze crop moves", nr.history_moves or 0},
            {"NR history resets", nr.history_resets or 0},
            {"Motion corrections", nr.history_corrections or 0},
            {"Last reset cause", nr.history_reset_reason or "none"}
        })
        text("Private SR output must exceed center display size at >1.0x. Rechecks after slider release.")
        imgui.tree_pop()
    end''')
patch("tests/gaze_tests.cpp",
      '    if (argc == 2 && std::strcmp(argv[1], "--d3d12-history") == 0) return run_d3d12_history_tests();',
      '''    if (argc == 2 && std::strcmp(argv[1], "--cheeky-r12") == 0) {
        test_center_supersampling();
        test_dlss_nr_stable_crop_and_history();
        test_mono_gaze_coordinator();
        auto original=cheeky::foveated_dlss::configured_settings();
        auto edited=original; edited.gaze_vertical_offset=0.125F;
        cheeky::foveated_dlss::update_settings(edited);
        expect_near(cheeky::foveated_dlss::configured_settings().gaze_vertical_offset,0.125F,0.00001F,
                    "Live gaze calibration setting roundtrip");
        cheeky::foveated_dlss::update_settings(original);
        return failures ? 1 : 0;
    }
    if (argc == 2 && std::strcmp(argv[1], "--d3d12-history") == 0) return run_d3d12_history_tests();''')
print("Cheeky PSVR2 r12 patches applied")
