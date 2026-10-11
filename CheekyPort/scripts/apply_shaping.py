#!/usr/bin/env python3
"""After-neural display-only result shaping and near-black protection for Cheeky DX12."""
from pathlib import Path
import argparse
ap=argparse.ArgumentParser()
ap.add_argument("root",type=Path)
root=ap.parse_args().root.resolve()
def patch(path, old, new):
    p=root/path
    src=p.read_text(encoding="utf-8")
    if src.count(old)!=1: raise RuntimeError(f"{path}: anchor count {src.count(old)}, {old[:100]!r}")
    p.write_text(src.replace(old,new),encoding="utf-8",newline="\n")
    print("RESULT_SHAPING",path)

patch("src/settings.hpp",
    "    float nr_paper_white_scale{1.0F};",
    """    // Result shaping is composited AFTER the model evaluation; do not feed
    // display color changes into the next DLSS NR history.
    bool nr_result_shaping{false};
    float nr_result_edit_strength{1.0F};
    float nr_result_brighten{1.0F};
    float nr_result_darken{1.0F};
    float nr_result_color{1.0F};
    float nr_result_highlights{1.0F};
    float nr_result_shadows{1.0F};
    float nr_result_lift_limit{2.0F};
    float nr_result_dark_limit{2.0F};
    float nr_result_color_limit{2.0F};
    float nr_result_highlight_threshold{0.7F};
    float nr_result_shadow_threshold{0.2F};
    float nr_result_broad_tone{1.0F};
    float nr_result_fine_detail{1.0F};
    float nr_nearblack_strength{0.0F};
    float nr_nearblack_threshold{0.03F};
    float nr_nearblack_onset{0.08F};
    float nr_paper_white_scale{1.0F};""")
patch("uevr/settings_fields.inc",
    'CHEEKY_SETTING("NrAdaptiveCooldownMs", nr_adaptive_cooldown_ms)',
    """CHEEKY_SETTING("NrAdaptiveCooldownMs", nr_adaptive_cooldown_ms)
CHEEKY_SETTING("NrResultShaping", nr_result_shaping)
CHEEKY_SETTING("NrResultEditStrength", nr_result_edit_strength)
CHEEKY_SETTING("NrResultBrighten", nr_result_brighten)
CHEEKY_SETTING("NrResultDarken", nr_result_darken)
CHEEKY_SETTING("NrResultColor", nr_result_color)
CHEEKY_SETTING("NrResultHighlights", nr_result_highlights)
CHEEKY_SETTING("NrResultShadows", nr_result_shadows)
CHEEKY_SETTING("NrResultLiftLimit", nr_result_lift_limit)
CHEEKY_SETTING("NrResultDarkLimit", nr_result_dark_limit)
CHEEKY_SETTING("NrResultColorLimit", nr_result_color_limit)
CHEEKY_SETTING("NrResultHighlightThreshold", nr_result_highlight_threshold)
CHEEKY_SETTING("NrResultShadowThreshold", nr_result_shadow_threshold)
CHEEKY_SETTING("NrResultBroadTone", nr_result_broad_tone)
CHEEKY_SETTING("NrResultFineDetail", nr_result_fine_detail)
CHEEKY_SETTING("NrNearBlackStrength", nr_nearblack_strength)
CHEEKY_SETTING("NrNearBlackThreshold", nr_nearblack_threshold)
CHEEKY_SETTING("NrNearBlackOnset", nr_nearblack_onset)""")

fields=[
("nr_result_shaping","bool",False),
("nr_result_edit_strength","float",2.0),
("nr_result_brighten","float",2.0),
("nr_result_darken","float",2.0),
("nr_result_color","float",2.0),
("nr_result_highlights","float",2.0),
("nr_result_shadows","float",2.0),
("nr_result_lift_limit","float",2.0),
("nr_result_dark_limit","float",2.0),
("nr_result_color_limit","float",2.0),
("nr_result_highlight_threshold","float",1.0),
("nr_result_shadow_threshold","float",1.0),
("nr_result_broad_tone","float",2.0),
("nr_result_fine_detail","float",2.0),
("nr_nearblack_strength","float",2.0),
("nr_nearblack_threshold","float",0.25),
("nr_nearblack_onset","float",0.25),
]
get_lines="\n".join(f"    settings.{f} = adaptive_configuration.{f};" for f,_,__ in fields)
patch("src/settings.cpp",
    "    settings.nr_adaptive_cooldown_ms = adaptive_configuration.nr_adaptive_cooldown_ms;",
    "    settings.nr_adaptive_cooldown_ms = adaptive_configuration.nr_adaptive_cooldown_ms;\n"+get_lines)
set_lines="\n".join(
    f"    adaptive_configuration.{f} = settings.{f};" if typ=="bool" else
    f"    adaptive_configuration.{f}=finite(settings.{f},0.0F,{float(high)}F,{0.03 if f=='nr_nearblack_threshold' else 0.08 if f=='nr_nearblack_onset' else 0.7 if f=='nr_result_highlight_threshold' else 0.2 if f=='nr_result_shadow_threshold' else 0 if f=='nr_nearblack_strength' else 1}.0F);"
    for f,typ,high in fields
)
# Use unambiguous 1.0F default expressions for numerical fields.
set_lines=set_lines.replace("0.03.0F","0.03F").replace("0.08.0F","0.08F").replace("0.7.0F","0.7F").replace("0.2.0F","0.2F")
patch("src/settings.cpp",
    "    adaptive_configuration.nr_adaptive_cooldown_ms=finite(settings.nr_adaptive_cooldown_ms,0,5000,1000);",
    "    adaptive_configuration.nr_adaptive_cooldown_ms=finite(settings.nr_adaptive_cooldown_ms,0,5000,1000);\n"+set_lines)

patch("src/nr_codec_shader.hpp",
    "        float mask_bounds[4][4];\n    };\n    static_assert(sizeof(CodecConstants) == 40U * sizeof(std::uint32_t));",
    """        float mask_bounds[4][4];
        float shape_enabled, shape_edit, shape_brighten, shape_darken;
        float shape_color, shape_highlights, shape_shadows, shape_lift_limit;
        float shape_dark_limit, shape_color_limit, shape_highlight_threshold, shape_shadow_threshold;
        float shape_broad_tone, shape_fine_detail, nearblack_strength, nearblack_threshold;
        float nearblack_onset, reserved[3];
    };
    static_assert(sizeof(CodecConstants) == 60U * sizeof(std::uint32_t));""")
patch("src/nr_codec_shader.hpp",
    "    float4 MaskBounds[4];\n};",
    """    float4 MaskBounds[4];
    float ShapeEnabled, ShapeEdit, ShapeBrighten, ShapeDarken;
    float ShapeColor, ShapeHighlights, ShapeShadows, ShapeLiftLimit;
    float ShapeDarkLimit, ShapeColorLimit, ShapeHighlightThreshold, ShapeShadowThreshold;
    float ShapeBroadTone, ShapeFineDetail, NearBlackStrength, NearBlackThreshold;
    float NearBlackOnset;
    float3 ShapePadding;
};""")
patch("src/nr_codec_shader.hpp",
    "[numthreads(16, 16, 1)]\nvoid EncodeMain",
    """// Applied only in the decode/display pass, never to the model's temporal output.
float3 ShapeNeuralResult(float3 original, float3 edited) {
    original = max(original, 0.0);
    float y = max(0.0, Luminance(original));
    float3 delta = edited - original;
    if (ShapeEnabled > 0.5) {
        float luminance_delta = Luminance(delta);
        float3 chroma_delta = delta - luminance_delta.xxx;
        float hi = smoothstep(max(0.0, ShapeHighlightThreshold * 0.6),
                              max(0.001, ShapeHighlightThreshold), y);
        float lo = 1.0 - smoothstep(max(0.0, ShapeShadowThreshold * 0.5),
                                    max(0.001, ShapeShadowThreshold), y);
        float tonal_gain = lerp(1.0, ShapeHighlights, hi) * lerp(1.0, ShapeShadows, lo);
        float directional = luminance_delta >= 0.0 ? ShapeBrighten : ShapeDarken;
        float tone = luminance_delta * ShapeEdit * tonal_gain * directional * ShapeBroadTone;
        tone = clamp(tone, -ShapeDarkLimit, ShapeLiftLimit);
        float3 color = clamp(chroma_delta * ShapeEdit * ShapeColor * ShapeFineDetail,
                             -float3(ShapeColorLimit,ShapeColorLimit,ShapeColorLimit), float3(ShapeColorLimit,ShapeColorLimit,ShapeColorLimit));
        edited = max(original + float3(tone,tone,tone) + color, 0.0);
    }
    if (NearBlackStrength > 0.0) {
        // Original pixel luminance controls protection, NOT the neural edit.
        // Positive neural lifting is suppressed; legitimate darkening survives.
        float allow = smoothstep(NearBlackThreshold,
                                 NearBlackThreshold + max(NearBlackOnset, 0.0001), y);
        float positive_gain = lerp(1.0, allow, saturate(NearBlackStrength));
        float3 corrected = edited-original;
        edited = max(original + max(corrected, 0.0)*positive_gain +
                     min(corrected, 0.0), 0.0);
    }
    return edited;
}

[numthreads(16, 16, 1)]
void EncodeMain""")
patch("src/nr_codec_shader.hpp",
    """        const float4 processed = float4(lerp(original_sample.rgb, neural_sample.rgb,
            TransferStrength * ColorStrength), original_sample.a);""",
    """        const float3 initial = lerp(original_sample.rgb, neural_sample.rgb,
            TransferStrength * ColorStrength);
        const float4 processed = float4(
            ShapeNeuralResult(original_sample.rgb, initial), original_sample.a);""")
patch("src/nr_codec_shader.hpp",
    """    const float3 decoded = lerp(original, upgraded, ColorStrength) * PaperWhiteScale;
    const float4 processed = float4(max(decoded, 0.0), original_sample.a);""",
    """    const float3 decoded = lerp(original, upgraded, ColorStrength);
    const float3 shaped = ShapeNeuralResult(original, decoded) * PaperWhiteScale;
    const float4 processed = float4(max(shaped, 0.0), original_sample.a);""")
patch("src/dlss_nr.cpp",
    "root_parameters[2].Constants.Num32BitValues = 40U;",
    "root_parameters[2].Constants.Num32BitValues = 60U;")
patch("src/dlss_nr.cpp",
    "frame.command_list->SetComputeRoot32BitConstants(2U, 40U, &constants, 0U);",
    "frame.command_list->SetComputeRoot32BitConstants(2U, 60U, &constants, 0U);")
patch("src/dlss_nr.cpp",
    """        region.mask.count, {}, {},
    };
    std::memcpy(constants.mask_bounds""",
    """        region.mask.count, {}, {},
        settings.nr_result_shaping ? 1.0F : 0.0F,
        settings.nr_result_edit_strength,
        settings.nr_result_brighten,
        settings.nr_result_darken,
        settings.nr_result_color,
        settings.nr_result_highlights,
        settings.nr_result_shadows,
        settings.nr_result_lift_limit,
        settings.nr_result_dark_limit,
        settings.nr_result_color_limit,
        settings.nr_result_highlight_threshold,
        settings.nr_result_shadow_threshold,
        settings.nr_result_broad_tone,
        settings.nr_result_fine_detail,
        settings.nr_nearblack_strength,
        settings.nr_nearblack_threshold,
        settings.nr_nearblack_onset,
        {},
    };
    std::memcpy(constants.mask_bounds""")
patch("uevr/scripts/cheeky_foveated_dlss.lua",
    '                    slider("Color strength", "NrColorStrength", 0, 2)',
    """                    slider("Color strength", "NrColorStrength", 0, 2)
                    if imgui.tree_node("OpenNR result shaping (display-only)") then
                        check("Enable result shaping", "NrResultShaping")
                        if draft.NrResultShaping then
                            slider("Neural edit strength", "NrResultEditStrength", 0, 2)
                            slider("Brightening", "NrResultBrighten", 0, 2)
                            slider("Darkening", "NrResultDarken", 0, 2)
                            slider("Color change", "NrResultColor", 0, 2)
                            slider("Highlights", "NrResultHighlights", 0, 2)
                            slider("Shadows", "NrResultShadows", 0, 2)
                            slider("Lift limit", "NrResultLiftLimit", 0, 2)
                            slider("Darkening limit", "NrResultDarkLimit", 0, 2)
                            slider("Color-change limit", "NrResultColorLimit", 0, 2)
                            slider("Highlight threshold", "NrResultHighlightThreshold", 0, 1)
                            slider("Shadow threshold", "NrResultShadowThreshold", 0, 1)
                            slider("Broad tone", "NrResultBroadTone", 0, 2)
                            slider("Fine detail / chroma", "NrResultFineDetail", 0, 2)
                        end
                        slider("Protect near-black", "NrNearBlackStrength", 0, 2)
                        slider("Near-black threshold", "NrNearBlackThreshold", 0, 0.25)
                        slider("Near-black lift onset", "NrNearBlackOnset", 0, 0.25)
                        text("Changes are applied AFTER NR; raw neural history is preserved.")
                        imgui.tree_pop()
                    end""")
patch("tests/gaze_tests.cpp",
    '    if (argc == 2 && std::strcmp(argv[1], "--opennr-r10-gaze") == 0) {',
    """    // Verify adaptive stages and extra shaping controls against the actual
    // configured/current-settings plumbing, not independent duplicated math.
    if (argc == 2 && std::strcmp(argv[1], "--cheeky-r11-adaptive") == 0) {
        using namespace cheeky::foveated_dlss;
        set_processing_allowed(true);
        Settings test{};
        test.enabled = true;
        test.nr_enabled = true;
        test.nr_foveated = true;
        test.nr_width = test.nr_height = .5F;
        test.nr_working_scale = .4F;
        test.nr_adaptive_enabled = true;
        test.nr_adaptive_mode = 3U;
        test.nr_adaptive_stage2 = 90U;
        test.nr_adaptive_stage3 = 80U;
        test.nr_result_shaping = true;
        test.nr_nearblack_strength = 1.5F;
        update_settings(test);
        auto value = current_settings();
        expect(std::abs(value.nr_width-.4F) < 0.0001F &&
               std::abs(value.nr_height-.4F) < 0.0001F,
               "Stage 3 scales relative to selected NR crop");
        expect(value.nr_working_scale == 1.F, "Active adaptive stages use full-resolution NR");
        expect(value.nr_result_shaping && value.nr_nearblack_strength == 1.5F,
               "Result shaping settings round-trip without changing NR model history");
        test.nr_adaptive_mode = 6U;
        update_settings(test);
        value = current_settings();
        expect(!value.nr_enabled && value.nr_width == .5F,
               "Stage 6 switches off NR without destroying selected crop");
        test.nr_adaptive_mode = 5U;
        test.nr_adaptive_stage5 = 100U; // clamp to preceding stage, never reorder
        update_settings(test);
        value = current_settings();
        expect(std::abs(value.nr_width-.35F) < 0.0001F,
               "Out-of-order stage ladder clamps safely");
        update_settings(Settings{});
        return failures ? 1 : 0;
    }
    if (argc == 2 && std::strcmp(argv[1], "--opennr-r10-gaze") == 0) {""")

# SPIR-V assets are intentionally retained from pinned Cheeky 0.5.5.
# They use the original 40-dword codec push constant layout. Our DX12-only
# decode-shader extensions increase C++ CodecConstants to 60 dwords; Vulkan
# must continue using just the first 40 for pipeline ranges and push commands.
# Otherwise 240-byte pushes can exceed a device's minimum push-constant limit.
patch("src/vulkan_nr.cpp",
    """        !slot.encode_dispatch.create(a,pipelines.encode[index],sizeof(CodecConstants)) ||
        !slot.decode_dispatch.create(a,pipelines.decode[index],sizeof(CodecConstants)) ||
        !slot.border_dispatch.create(a,pipelines.border[index],sizeof(CodecConstants)) ||""",
    """        !slot.encode_dispatch.create(a,pipelines.encode[index],40U*sizeof(std::uint32_t)) ||
        !slot.decode_dispatch.create(a,pipelines.decode[index],40U*sizeof(std::uint32_t)) ||
        !slot.border_dispatch.create(a,pipelines.border[index],40U*sizeof(std::uint32_t)) ||""")
patch("src/vulkan_nr.cpp",
    "slot.encode_dispatch.record(a,cmd,pipelines.encode[index],encode_inputs,encode_outputs,&codec,sizeof(codec),",
    "slot.encode_dispatch.record(a,cmd,pipelines.encode[index],encode_inputs,encode_outputs,&codec,40U*sizeof(std::uint32_t),")
patch("src/vulkan_nr.cpp",
    "slot.decode_dispatch.record(a,cmd,pipelines.decode[index],inputs,outputs,&codec,sizeof(codec),",
    "slot.decode_dispatch.record(a,cmd,pipelines.decode[index],inputs,outputs,&codec,40U*sizeof(std::uint32_t),")
patch("src/vulkan_nr.cpp",
    "slot.border_dispatch.record(a,cmd,pipelines.border[index],inputs,outputs,&codec,sizeof(codec),",
    "slot.border_dispatch.record(a,cmd,pipelines.border[index],inputs,outputs,&codec,40U*sizeof(std::uint32_t),")
print("NR result shaping and independent near-black protection applied")
