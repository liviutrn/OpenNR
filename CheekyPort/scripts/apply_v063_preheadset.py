#!/usr/bin/env python3
"""2026-11-13 pre-headset probes on top of verified Cheeky v0.6.3 DuoTri.
Run once AFTER ALL previous patches (including adjustable guard), before shaders/tests.
All behavior changes opt-in; stock defaults stay byte-for-byte on decode/encode.
No routing, FG, native SR, lifetime, or VRAM cap changes.
"""
from pathlib import Path
import sys
root=Path(sys.argv[1]).resolve()
def edit(path,old,new):
    file=root/path; src=file.read_text(encoding="utf-8")
    n=src.count(old)
    if n!=1:raise RuntimeError(f"{path}: strict anchor expected 1, found {n}: {old[:120]!r}")
    file.write_text(src.replace(old,new,1),encoding="utf-8",newline="\n")
    print("PREHEADSET",path,old[:52].replace("\n"," "))
def splice(path,begin,end,replacement):
    file=root/path; src=file.read_text(encoding="utf-8")
    if src.count(begin)!=1 or src.count(end)!=1:raise RuntimeError("Bad splice anchors "+str(path))
    a=src.index(begin);b=src.index(end,a)
    file.write_text(src[:a]+replacement+src[b:],encoding="utf-8",newline="\n")
    print("PREHEADSET SPLICE",path)
# 1. Source-side defaults and atomic settings. Debug view is session-only.
edit("src/settings.hpp","    std::uint32_t nr_reconstruction_mode{1U};",
"""    std::uint32_t nr_reconstruction_mode{1U};
    std::uint32_t nr_debug_view{0U}; // transient 0=off,1=exposure edit,2=chroma edit
    float nr_dark_pedestal{0.0F}; // decode-only; 0 is unchanged
    std::uint32_t nr_create_flags_mode{0U}; // 0=game flag,1=NR-only clear IsHDR
""".rstrip())
edit("src/settings.cpp","std::atomic<std::uint32_t> nr_reconstruction_mode{1U};",
"""std::atomic<std::uint32_t> nr_reconstruction_mode{1U};
std::atomic<std::uint32_t> nr_debug_view{0U};
std::atomic<std::uint32_t> nr_dark_pedestal_bits{};
std::atomic<std::uint32_t> nr_create_flags_mode{};""")
edit("src/settings.cpp","    settings.nr_reconstruction_mode = nr_reconstruction_mode.load(std::memory_order_acquire);",
"""    settings.nr_reconstruction_mode = nr_reconstruction_mode.load(std::memory_order_acquire);
    settings.nr_debug_view = nr_debug_view.load(std::memory_order_acquire);
    settings.nr_dark_pedestal = load_float(nr_dark_pedestal_bits);
    settings.nr_create_flags_mode = nr_create_flags_mode.load(std::memory_order_acquire);""")
edit("src/settings.cpp","    nr_reconstruction_mode.store((std::min)(settings.nr_reconstruction_mode, 1U), std::memory_order_release);",
"""    nr_reconstruction_mode.store((std::min)(settings.nr_reconstruction_mode, 1U), std::memory_order_release);
    nr_debug_view.store((std::min)(settings.nr_debug_view, 2U), std::memory_order_release);
    store_float(nr_dark_pedestal_bits, std::isfinite(settings.nr_dark_pedestal)
        ? (std::clamp)(settings.nr_dark_pedestal, 0.0F, 0.05F) : 0.0F);
    nr_create_flags_mode.store((std::min)(settings.nr_create_flags_mode, 1U), std::memory_order_release);""")
edit("uevr/settings_fields.inc",'CHEEKY_SETTING("NrReconstructionMode", nr_reconstruction_mode)',
'''CHEEKY_SETTING("NrReconstructionMode", nr_reconstruction_mode)
CHEEKY_SETTING("NrDebugView", nr_debug_view)
CHEEKY_SETTING("NrDarkPedestal", nr_dark_pedestal)
CHEEKY_SETTING("NrCreateFlagsMode", nr_create_flags_mode)''')
edit("uevr/settings_io.cpp",'    if(key=="NrReconstructionMode") {',
'''    if(key=="NrDebugView" || key=="NrCreateFlagsMode") {
        std::uint32_t mode{};
        if (!parse(value,mode) || mode > (key=="NrDebugView" ? 2U : 1U))return false;
        (key=="NrDebugView" ? s.nr_debug_view : s.nr_create_flags_mode)=mode;
        return true;
    }
    if(key=="NrDarkPedestal") {
        float pedestal{};
        if (!parse(value,pedestal) || pedestal < 0.0F || pedestal > 0.05F)return false;
        s.nr_dark_pedestal=pedestal;
        return true;
    }
    if(key=="NrReconstructionMode") {''')
# Do not persist debug view. On restart it is zero, even if INI has old key.
edit("uevr/settings_io.cpp",
 '#define CHEEKY_SETTING(name, field) out << name << \'=\' << number(s.field) << \'\\n\';',
 '#define CHEEKY_SETTING(name, field) if (std::string_view(name) != "NrDebugView") out << name << \'=\' << number(s.field) << \'\\n\';')
edit("uevr/settings_io.cpp",'    candidate.nr_style = 0U; // Older files used the hardcoded Standard style.',
 '''    candidate.nr_style = 0U; // Older files used the hardcoded Standard style.
    candidate.nr_debug_view = 0U; // Session-only; never load saved debug mode.''')
edit("uevr/settings_io.cpp",'            bool known = key == "FgWaitForCompletion";',
 '''            if (key == "NrDebugView") continue; // Deliberately transient.
            bool known = key == "FgWaitForCompletion";''')
edit("uevr/runtime.cpp",
 'std::string_view(name) != "NrVramGuardMiB") settings.field = stored.field;',
 'std::string_view(name) != "NrVramGuardMiB" && std::string_view(name) != "NrDebugView") settings.field = stored.field;')
# 2. DLL version log once, during runtime loading, not sampled each frame.
edit("src/dlss_nr.cpp",'#include <Windows.h>',
 '''#include <Windows.h>
#include <winver.h>
#pragma comment(lib,"version.lib")''')
edit("src/dlss_nr.cpp",'''    const auto& directory=module.directory;
    if(!runtime.module)''',
'''    const auto& directory=module.directory;
    if(runtime.module) {
        wchar_t runtime_path[32768]{};
        const auto length=GetModuleFileNameW(runtime.module,runtime_path,32768U);
        unsigned version_parts[4]{};
        if(length && length<32768U) {
            DWORD ignored{};
            const auto bytes=GetFileVersionInfoSizeW(runtime_path,&ignored);
            if(bytes && bytes < 4U*1024U*1024U) {
                std::vector<std::byte> buffer(bytes);
                if(GetFileVersionInfoW(runtime_path,0U,bytes,buffer.data())) {
                    VS_FIXEDFILEINFO* info{};UINT extent{};
                    if(VerQueryValueW(buffer.data(),L"\\\\",
                        reinterpret_cast<void**>(&info),&extent) &&
                        info && extent >= sizeof(VS_FIXEDFILEINFO) && info->dwSignature==0xFEEF04BDU) {
                        version_parts[0]=HIWORD(info->dwFileVersionMS);
                        version_parts[1]=LOWORD(info->dwFileVersionMS);
                        version_parts[2]=HIWORD(info->dwFileVersionLS);
                        version_parts[3]=LOWORD(info->dwFileVersionLS);
                    }
                }
            }
        }
        char utf8[32768]{};
        if(length && length<32768U)WideCharToMultiByte(CP_UTF8,0,runtime_path,-1,
            utf8,sizeof(utf8),nullptr,nullptr);
        trace_event("[CheekyNR][Runtime] path=%s version=%u.%u.%u.%u (file version; zero means unavailable)",
            utf8,version_parts[0],version_parts[1],version_parts[2],version_parts[3]);
    }
    if(!runtime.module)''')
edit("src/dlss_nr.cpp","#include <utility>","#include <utility>\n#include <vector>")
# 3. Optional NR-only HDR flag toggle. Never modify the game's SR flags.
edit("src/dlss_nr.cpp",'''    const FeatureKey key{
        working_width,''',
'''    const auto nr_flags = settings.nr_create_flags_mode == 1U
        ? frame.create_flags & ~1U : frame.create_flags;
    const FeatureKey key{
        working_width,''')
edit("src/dlss_nr.cpp",'''        frame.create_flags,
        settings.nr_processing_order,''',
'''        nr_flags,
        settings.nr_processing_order,''')
edit("src/dlss_nr.cpp",'''    parameters->Set("DLSS.Feature.Create.Flags", frame.create_flags);''',
'''    parameters->Set("DLSS.Feature.Create.Flags", nr_flags); // NR only. Game SR unchanged.''')
edit("src/dlss_nr.cpp",'''        frame.create_flags,
        preset''',
'''        nr_flags,
        preset''')
edit("uevr/nr_lite_budget_policy.hpp",'''    const bool rekey = requested.nr_preset != current.nr_preset ||''',
'''    const bool rekey = requested.nr_create_flags_mode != current.nr_create_flags_mode ||
        requested.nr_preset != current.nr_preset ||''')
# 4. Decoded faithful pedestal, no cost or mathematical change at zero.
edit("src/nr_codec_shader.hpp",'     float ReservedFaithful;',
 '     float DarkPedestal;')
edit("src/dlss_nr.cpp",'    constants.reserved_faithful = 0.0F;',
 '    constants.reserved_faithful = settings.nr_dark_pedestal;')
# Existing FaithfulUpgrade code is preserved for DarkPedestal == 0; the positive
# branch ONLY replaces its final luminance multiplier.
edit("src/nr_codec_shader.hpp",
'''    result *= exp2(stops);
    // Preserve signed out-of-gamut HDR channels when the NR edit is neutral.''',
'''    if (DarkPedestal > 0.0) {
        const float c = DarkPedestal;
        // Log edit of a pedestal-offset luminance ratio. This avoids the
        // near-black py gate without inventing unbounded black amplification.
        const float yt = max((oy + c) * (ny + c) / max(py + c, 1e-6) - c, 0.0);
        float ss = log2(max(yt + c, 1e-6) / max(oy + c, 1e-6));
        const float light_weight = ss >= 0.0 ? EditBrighten :
            EditDarken * lerp(1.0, 0.5, hi);
        ss = clamp(ss * light_weight * TransferStrength * ColorStrength, -2.0, 2.0);
        const float pedestal_y = max((oy + c) * exp2(ss) - c, 0.0);
        // Above the shadow region retain precisely the existing luminance
        // expression to avoid a visible daylight colour shift.
        const float original_y = oy * exp2(stops);
        const float daylight = smoothstep(0.02, 0.10, oy);
        const float final_y = lerp(pedestal_y, original_y, daylight);
        if (oy > 1e-6) {
            result *= final_y / max(oy, 1e-6);
        } else if (final_y > 0.0) {
            const float3 n = max(neural,0.0);
            const float yn = Luminance(n);
            result = (yn > 1e-6 ? n / yn : float3(1,1,1)) * final_y;
        }
    } else {
        result *= exp2(stops); // DEFAULT: unmodified faithful shader operation.
    }
    // Preserve signed out-of-gamut HDR channels when the NR edit is neutral.''')
# 5. Encode tap filter only for reduced working scale; at 1.0 the original
# bilinear code executes exactly as before.
edit("src/nr_codec_shader.hpp",
'''        const float4 proxy_source = LoadSource0Bilinear(
            source_position,
            SourceBase,
            SourceSize
        );
        const float3 linear_color''',
'''        float4 proxy_source = LoadSource0Bilinear(
            source_position,
            SourceBase,
            SourceSize
        );
        if (any(ProxySize < SourceSize)) {
            const float2 footprint = float2(SourceSize) / float2(ProxySize);
            const float2 step = 0.25 * footprint;
            proxy_source = 0.25 * (
                LoadSource0Bilinear(source_position+float2(-step.x,-step.y),SourceBase,SourceSize) +
                LoadSource0Bilinear(source_position+float2( step.x,-step.y),SourceBase,SourceSize) +
                LoadSource0Bilinear(source_position+float2(-step.x, step.y),SourceBase,SourceSize) +
                LoadSource0Bilinear(source_position+float2( step.x, step.y),SourceBase,SourceSize));
        }
        const float3 linear_color''')
# 6. History: roundness, transition are shape/feather after model input. Keep
# region sizes and neural model keys/history reset.
edit("src/nr_parameters.hpp",'''            region.shape_height,
            region.roundness,
            region.transition,''',
'''            region.shape_height,''')
# Provide a conservative comparison for template load: decode controls are not
# sampled into NVIDIA inference, so an A/B look-only swap skips explicit reset.
# Any doubt -> reset. Model keys, crop and guide geometry included.
patch_text = root/"uevr/runtime.cpp"
runtime=patch_text.read_text(encoding="utf-8")
anchor='''                update_settings(settings);
                reset_dlss_nr(); // Do not reuse another model's temporal history.'''
if runtime.count(anchor)!=1:raise RuntimeError("Template reset anchor changed")
replacement='''                const auto old = configured_settings();
                const bool needs_model_reset =
                    old.nr_enabled != settings.nr_enabled ||
                    old.nr_target_mode != settings.nr_target_mode ||
                    old.nr_duo_fovea_source != settings.nr_duo_fovea_source ||
                    old.nr_pass1_views != settings.nr_pass1_views ||
                    old.nr_pass2_views != settings.nr_pass2_views ||
                    old.nr_passes != settings.nr_passes ||
                    old.nr_preset != settings.nr_preset ||
                    old.nr_style != settings.nr_style ||
                    old.nr_intensity != settings.nr_intensity ||
                    old.nr_local_tone_strength != settings.nr_local_tone_strength ||
                    old.nr_local_structure_strength != settings.nr_local_structure_strength ||
                    old.nr_skin_structure_strength != settings.nr_skin_structure_strength ||
                    old.nr_automatic_mask != settings.nr_automatic_mask ||
                    old.nr_ui_correction != settings.nr_ui_correction ||
                    old.nr_processing_order != settings.nr_processing_order ||
                    old.nr_foveated != settings.nr_foveated ||
                    old.nr_use_sr_foveation != settings.nr_use_sr_foveation ||
                    old.nr_width != settings.nr_width || old.nr_height != settings.nr_height ||
                    old.nr_working_scale != settings.nr_working_scale ||
                    old.nr_pass2_foveated != settings.nr_pass2_foveated ||
                    old.nr_pass2_width != settings.nr_pass2_width ||
                    old.nr_pass2_height != settings.nr_pass2_height ||
                    old.nr_depth_convention != settings.nr_depth_convention ||
                    old.nr_motion_scale_x_multiplier != settings.nr_motion_scale_x_multiplier ||
                    old.nr_motion_scale_y_multiplier != settings.nr_motion_scale_y_multiplier ||
                    old.nr_paper_white_scale != settings.nr_paper_white_scale ||
                    old.nr_reconstruction_mode != settings.nr_reconstruction_mode ||
                    old.nr_shoulder_knee != settings.nr_shoulder_knee ||
                    old.nr_create_flags_mode != settings.nr_create_flags_mode ||
                    old.nr_extra_passes != settings.nr_extra_passes;
                update_settings(settings);
                if (needs_model_reset) reset_dlss_nr();
                trace_event("[CheekyNR][Template] slot=%u modelReset=%u",
                    slot, needs_model_reset ? 1U : 0U);'''
runtime=runtime.replace(anchor,replacement,1)
patch_text.write_text(runtime,encoding="utf-8",newline="\n")
# Operators: std::array<NrExtraPass> currently not comparable. Use memcmp? No
# (padding instability). Provide explicit, per-field comparison across 2 passes.
edit("uevr/runtime.cpp",
'''                    old.nr_extra_passes != settings.nr_extra_passes;''',
'''                    old.nr_extra_passes[0].same_as_pass1 != settings.nr_extra_passes[0].same_as_pass1 ||
                    old.nr_extra_passes[0].style != settings.nr_extra_passes[0].style ||
                    old.nr_extra_passes[0].intensity != settings.nr_extra_passes[0].intensity ||
                    old.nr_extra_passes[0].local_tone_strength != settings.nr_extra_passes[0].local_tone_strength ||
                    old.nr_extra_passes[0].local_structure_strength != settings.nr_extra_passes[0].local_structure_strength;''')
# 7. Menu: explicit opt-in controls. Capture button added in separate patch stage.
edit("uevr/scripts/cheeky_foveated_dlss.lua",
'''            slider("Neural hue change", "NrEditHue", 0, 2)''',
'''            slider("Neural hue change", "NrEditHue", 0, 2)
            slider("Dark shadow pedestal (experimental)", "NrDarkPedestal", 0, 0.05)''')
edit("uevr/scripts/cheeky_foveated_dlss.lua",
'''        slider("Color strength", "NrColorStrength", 0, 2)''',
'''        slider("Color strength", "NrColorStrength", 0, 2)
        section("Pre-headset diagnostics (all off by default)")
        combo("NR edit debug", "NrDebugView",
            {[0]="Off",[1]="Brightness: blue/darker, red/brighter",
             [2]="Chroma / hue magnitude"}, {0,1,2})
        combo("Experimental NR input HDR flag", "NrCreateFlagsMode",
            {[0]="Original game flags (default)",
             [1]="NR-only: clear IsHDR bit"}, {0,1})
        text("Model create-flags experiment resets the NR model, not game DLSS SR.")''')
print("PASS pre-headset setup, DLL version, optional pedestal & flags, look-only template swaps, downscale")
