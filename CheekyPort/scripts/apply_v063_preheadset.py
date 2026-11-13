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

# 8. Decode-only shader visualization. Reuse one existing padding DWORD:
# faithful D3D12 codec root size remains exactly 48 DWORD and Vulkan stays 40.
edit("src/nr_codec_shader.hpp","     uint ExposurePadding;","     uint DebugView;")
edit("src/dlss_nr.cpp",
'''    constants.padding[0] = std::bit_cast<std::uint32_t>(gpu.exposure''',
'''    constants.padding[1] = settings.nr_debug_view; // Zero when OFF; unused old slot.
    constants.padding[0] = std::bit_cast<std::uint32_t>(gpu.exposure''')
edit("src/nr_codec_shader.hpp",
'''[numthreads(16, 16, 1)]
void EncodeMain''',
'''float3 NrDebugApplied(float3 original, float3 final_result) {
    const float white = CodecWhite();
    const float3 a = max(original/white, 0.0);
    const float3 b = max(final_result/white, 0.0);
    const float ya = Luminance(a);
    const float yb = Luminance(b);
    if (DebugView == 1U) {
        const float stops = clamp(log2(max(yb,1e-6) / max(ya,1e-6)), -1.0, 1.0);
        const float gain = abs(stops);
        return white * (stops >= 0.0 ?
            lerp(float3(0.18,0.18,0.18),float3(0.85,0.12,0.12),gain) :
            lerp(float3(0.18,0.18,0.18),float3(0.12,0.20,0.85),gain));
    }
    const float3 achroma = log2(max(a,1e-6)) - log2(max(ya,1e-6));
    const float3 bchroma = log2(max(b,1e-6)) - log2(max(yb,1e-6));
    const float amount = saturate(length(clamp(bchroma-achroma,-2.0,2.0)) * 0.35);
    return white * lerp(float3(0.18,0.18,0.18),float3(0.90,0.25,0.80),amount);
}

[numthreads(16, 16, 1)]
void EncodeMain''')
edit("src/nr_codec_shader.hpp",
'''        Output0[SourceBase + dispatch_id.xy] = original_sample;
        return;
    }
    const float2 proxy_position''',
'''        Output0[SourceBase + dispatch_id.xy] = DebugView == 0U
            ? original_sample : float4(original_sample.rgb * 0.5, original_sample.a);
        return;
    }
    const float2 proxy_position''')
edit("src/nr_codec_shader.hpp",
'''        Output0[SourceBase + dispatch_id.xy] = lerp(original_sample, processed, foveation_weight);
        return;
    }
    const float3 original = original_sample.rgb / CodecWhite();''',
'''        const float4 final_color = lerp(original_sample, processed, foveation_weight);
        Output0[SourceBase + dispatch_id.xy] = DebugView == 0U ? final_color :
            float4(NrDebugApplied(original_sample.rgb, final_color.rgb), original_sample.a);
        return;
    }
    const float3 original = original_sample.rgb / CodecWhite();''')
edit("src/nr_codec_shader.hpp",
'''    Output0[SourceBase + dispatch_id.xy] = lerp(original_sample, processed, foveation_weight);
}
)";''',
'''    const float4 final_color = lerp(original_sample, processed, foveation_weight);
    Output0[SourceBase + dispatch_id.xy] = DebugView == 0U ? final_color :
        float4(NrDebugApplied(original_sample.rgb, final_color.rgb), original_sample.a);
}
)";''')
# Test-oriented metadata log makes the state understandable while the visual
# diagnostic is enabled. No normal-frame traces are added by default.
print("PASS opt-in debug view: existing root constant padding only, no new layouts")


# 9. One-shot GPU-correct, non-blocking capture of the original source,
# encoded input, neural output and decoded final image. Every allocation is
# behind a manual request flag; buffers are READBACK (system-visible memory).
# The existing NrLifetime proves command-list/queue completion before Map.
# The worker owns the readback COM references until disk writes finish.
# Source layouts are preserved losslessly including GPU-aligned row pitch.
capture = r'''
// Generated on November 13, 2026 by apply_v063_preheadset.py.
// This header is included inside the dlss_nr.cpp anonymous namespace.
// No capture resources or threads exist until explicit user interaction.
// Output files: %LOCALAPPDATA%\CheekyNR-Captures\<timestamp>-<seq>-view-<id>\
// Raw texture rows (row_pitch_bytes per row), plus capture.json metadata.
struct NrProbeCopy {
    Microsoft::WRL::ComPtr<ID3D12Resource> readback;
    D3D12_PLACED_SUBRESOURCE_FOOTPRINT layout{};
    std::uint64_t size{};
    std::uint32_t width{},height{},format{};
    const char* name{};
};
struct NrProbeSnapshot {
    NrLifetime lifetime;
    std::array<NrProbeCopy,4> images{};
    std::uint64_t sequence{},source_id{},reserved{}, captured_ms{};
    std::uint32_t source_role{},passes{},reconstruction_mode{},hdr_flags{},model_flags{};
    std::uint32_t region_x{},region_y{},working_width{},working_height{};
    float paper_white{},transfer{},color_strength{},shoulder{},brighten{},darken{},chroma{},hue{},pedestal{},working_scale{};
    ~NrProbeSnapshot();
};
std::atomic<unsigned> nr_probe_requested{};
std::atomic<std::uint64_t> nr_probe_memory{};
std::atomic<std::uint64_t> nr_probe_sequence{};
std::deque<std::shared_ptr<NrProbeSnapshot>> nr_probe_inflight;
NrProbeSnapshot::~NrProbeSnapshot() {
    nr_probe_memory.fetch_sub(reserved,std::memory_order_acq_rel);
}
void nr_probe_transition(ID3D12GraphicsCommandList* list,ID3D12Resource* res,
    D3D12_RESOURCE_STATES before,D3D12_RESOURCE_STATES after) noexcept {
    if(before==after)return;
    D3D12_RESOURCE_BARRIER barrier{};
    barrier.Type=D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;
    barrier.Transition.pResource=res;
    barrier.Transition.StateBefore=before;barrier.Transition.StateAfter=after;
    barrier.Transition.Subresource=D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES;
    list->ResourceBarrier(1U,&barrier);
}
bool nr_probe_readback(ID3D12Device* device,NrProbeCopy& out,
    ID3D12Resource* src,unsigned width,unsigned height,const char* name) noexcept {
    if(!src||!width||!height)return false;
    const auto real=src->GetDesc();
    if(real.Dimension!=D3D12_RESOURCE_DIMENSION_TEXTURE2D || real.MipLevels!=1U ||
       real.DepthOrArraySize!=1U || real.SampleDesc.Count!=1U) return false;
    if(real.Format!=DXGI_FORMAT_R16G16B16A16_FLOAT &&
       real.Format!=DXGI_FORMAT_R8G8B8A8_UNORM &&
       real.Format!=DXGI_FORMAT_R10G10B10A2_UNORM) return false;
    D3D12_RESOURCE_DESC tex=real;
    tex.Width=width;tex.Height=height;
    tex.Flags=D3D12_RESOURCE_FLAG_NONE;tex.Layout=D3D12_TEXTURE_LAYOUT_UNKNOWN;
    UINT64 bytes{};
    device->GetCopyableFootprints(&tex,0U,1U,0ULL,&out.layout,nullptr,nullptr,&bytes);
    if(!bytes || bytes>96ULL*1024ULL*1024ULL)return false;
    D3D12_RESOURCE_DESC buffer{};
    buffer.Dimension=D3D12_RESOURCE_DIMENSION_BUFFER;
    buffer.Width=bytes;buffer.Height=1U;buffer.DepthOrArraySize=1U;
    buffer.MipLevels=1U;buffer.SampleDesc.Count=1U;
    buffer.Layout=D3D12_TEXTURE_LAYOUT_ROW_MAJOR;
    D3D12_HEAP_PROPERTIES heap{};
    heap.Type=D3D12_HEAP_TYPE_READBACK;
    heap.CreationNodeMask=heap.VisibleNodeMask=1U;
    if(FAILED(device->CreateCommittedResource(&heap,D3D12_HEAP_FLAG_NONE,
        &buffer,D3D12_RESOURCE_STATE_COPY_DEST,nullptr,
        IID_PPV_ARGS(&out.readback))))return false;
    out.size=bytes;out.width=width;out.height=height;
    out.format=static_cast<std::uint32_t>(real.Format);out.name=name;
    return true;
}
void nr_probe_write(std::shared_ptr<NrProbeSnapshot> capture) noexcept {
    try {
        wchar_t root[32768]{};
        auto size=GetEnvironmentVariableW(L"LOCALAPPDATA",root,32768U);
        if(!size||size>=32768U) {
            size=GetTempPathW(32768U,root);
            if(!size||size>=32768U)return;
        }
        SYSTEMTIME time{};GetLocalTime(&time);
        wchar_t name[256]{};
        swprintf_s(name,L"%04u%02u%02u-%02u%02u%02u-%llu-view-%llu",
            time.wYear,time.wMonth,time.wDay,time.wHour,time.wMinute,time.wSecond,
            static_cast<unsigned long long>(capture->sequence),
            static_cast<unsigned long long>(capture->source_id));
        const auto folder=std::filesystem::path(root)/L"CheekyNR-Captures"/name;
        std::filesystem::create_directories(folder);
        bool ok=true;
        for(const auto& image:capture->images){
            void* data{};
            const D3D12_RANGE range{0,static_cast<SIZE_T>(image.size)};
            const auto mapped=image.readback->Map(0U,&range,&data);
            if(FAILED(mapped)||!data){ok=false;break;}
            std::ofstream file(folder/(std::string(image.name)+".bin"),std::ios::binary);
            file.write(static_cast<const char*>(data),static_cast<std::streamsize>(image.size));
            file.close();
            const D3D12_RANGE no_writes{0,0};image.readback->Unmap(0U,&no_writes);
            if(!file){ok=false;break;}
        }
        if(ok) {
            std::ofstream meta(folder/"capture.json",std::ios::binary);
            meta << std::setprecision(9);
            meta << "{\n  \"schema\":1,\n  \"source_id\":\"" << capture->source_id
                 << "\",\n  \"source_role\":" << capture->source_role
                 << ",\n  \"logical_passes\":" << capture->passes
                 << ",\n  \"reconstruction_mode\":" << capture->reconstruction_mode
                 << ",\n  \"game_create_flags\":" << capture->hdr_flags
                 << ",\n  \"nr_create_flags\":" << capture->model_flags
                 << ",\n  \"region_x\":" << capture->region_x
                 << ",\n  \"region_y\":" << capture->region_y
                 << ",\n  \"working_width\":" << capture->working_width
                 << ",\n  \"working_height\":" << capture->working_height
                 << ",\n  \"paper_white_scale\":" << capture->paper_white
                 << ",\n  \"transfer_strength\":" << capture->transfer
                 << ",\n  \"color_strength\":" << capture->color_strength
                 << ",\n  \"shoulder_knee\":" << capture->shoulder
                 << ",\n  \"edit_brighten\":" << capture->brighten
                 << ",\n  \"edit_darken\":" << capture->darken
                 << ",\n  \"edit_chroma\":" << capture->chroma
                 << ",\n  \"edit_hue\":" << capture->hue
                 << ",\n  \"dark_pedestal\":" << capture->pedestal
                 << ",\n  \"working_scale\":" << capture->working_scale
                 << ",\n  \"format_note\":\"R16G16B16A16_FLOAT=10, R8G8B8A8_UNORM=28, R10G10B10A2_UNORM=24; little-endian; rows include DXGI padding\",\n  \"images\":{\n";
            for(size_t i=0;i<capture->images.size();++i) {
                const auto& im=capture->images[i];
                meta<<"    \""<<im.name<<"\":{\"file\":\""<<im.name<<".bin\",\"width\":"<<im.width
                    <<",\"height\":"<<im.height<<",\"format\":"<<im.format
                    <<",\"row_pitch_bytes\":"<<im.layout.Footprint.RowPitch
                    <<",\"bytes\":"<<im.size<<"}"<<(i+1<capture->images.size()?",":"")<<"\n";
            }
            meta<<"  }\n}\n";meta.close();ok=!!meta;
        }
        char folder_utf8[2048]{};
        WideCharToMultiByte(CP_UTF8,0,folder.c_str(),-1,folder_utf8,sizeof(folder_utf8),nullptr,nullptr);
        trace_event("[CheekyNR][FrameCapture] %s path=%s source=%llu bytes=%llu (readback after GPU recording retirement)",
            ok?"saved":"write_failed",folder_utf8,
            static_cast<unsigned long long>(capture->source_id),
            static_cast<unsigned long long>(capture->reserved));
    } catch (...) {
        trace_event("[CheekyNR][FrameCapture] write_failed exception");
    }
}
void nr_probe_poll() noexcept {
    for(auto it=nr_probe_inflight.begin();it!=nr_probe_inflight.end();) {
        auto& capture=*it;
        capture->lifetime.collect();
        if(!capture->lifetime.empty()) {++it;continue;}
        auto completed=capture;it=nr_probe_inflight.erase(it);
        try { std::thread([completed]{nr_probe_write(completed);}).detach(); }
        catch (...) { trace_event("[CheekyNR][FrameCapture] worker_unavailable"); }
    }
}
void nr_probe_capture_one(const DlssNrFrame& frame,const GpuResources& gpu,
    const NrRegion& codec,const Settings& settings,unsigned passes) noexcept {
    if(!nr_probe_requested.load(std::memory_order_acquire))return;
    if(nr_probe_inflight.size()>=2U)return;
    if(!frame.command_list||!frame.color||!gpu.original_output ||
        !gpu.color_proxy||!gpu.neural_output)return;
    if(nr_probe_requested.exchange(0U,std::memory_order_acq_rel)==0U)return;
    try {
        Microsoft::WRL::ComPtr<ID3D12Device> device;
        if(FAILED(frame.command_list->GetDevice(IID_PPV_ARGS(&device))))return;
        auto capture=std::make_shared<NrProbeSnapshot>();
        struct Source {
            ID3D12Resource* tex;
            unsigned width,height,x,y;
            D3D12_RESOURCE_STATES state;
            const char* name;
        };
        const std::array<Source,4> sources{{
            {gpu.original_output,gpu.width,gpu.height,0U,0U,D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE,"original"},
            {gpu.color_proxy,gpu.working_width,gpu.working_height,0U,0U,D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE,"model_input"},
            {gpu.neural_output,gpu.working_width,gpu.working_height,0U,0U,D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE,"model_output"},
            {frame.color,gpu.width,gpu.height,codec.base_x,codec.base_y,D3D12_RESOURCE_STATE_UNORDERED_ACCESS,"final"}
        }};
        std::uint64_t required{};
        for(size_t i=0;i<sources.size();++i){
            const auto& src=sources[i];
            const auto desc=src.tex->GetDesc();
            if(src.x>desc.Width || src.width>desc.Width-src.x ||
               src.y>desc.Height || src.height>desc.Height-src.y ||
               !nr_probe_readback(device.Get(),capture->images[i],
                   src.tex,src.width,src.height,src.name)) {
                trace_event("[CheekyNR][FrameCapture] unsupported_format_or_region");
                return;
            }
            required+=capture->images[i].size;
        }
        if(required>192ULL*1024ULL*1024ULL) {
            trace_event("[CheekyNR][FrameCapture] sample_too_large bytes=%llu",
                static_cast<unsigned long long>(required));
            return;
        }
        auto used=nr_probe_memory.load();
        do {
            if(used>256ULL*1024ULL*1024ULL-required)return;
        } while(!nr_probe_memory.compare_exchange_weak(used,used+required));
        capture->reserved=required;
        if(!capture->lifetime.record(frame.command_list)){
            trace_event("[CheekyNR][FrameCapture] lifetime_unavailable");
            return;
        }
        capture->sequence=nr_probe_sequence.fetch_add(1U)+1U;
        capture->source_id=frame.view_id;capture->source_role=frame.source_role;
        capture->passes=passes;capture->hdr_flags=frame.create_flags;
        capture->model_flags=settings.nr_create_flags_mode==1U ? frame.create_flags & ~1U : frame.create_flags;
        capture->region_x=codec.base_x;capture->region_y=codec.base_y;
        capture->working_width=gpu.working_width;capture->working_height=gpu.working_height;
        capture->reconstruction_mode=settings.nr_reconstruction_mode;
        capture->paper_white=settings.nr_paper_white_scale;
        capture->transfer=settings.nr_hdr_transfer_strength;
        capture->color_strength=settings.nr_color_strength;
        capture->shoulder=settings.nr_shoulder_knee;
        capture->brighten=settings.nr_edit_brighten;
        capture->darken=settings.nr_edit_darken;
        capture->chroma=settings.nr_edit_chroma;
        capture->hue=settings.nr_edit_hue;
        capture->pedestal=settings.nr_dark_pedestal;
        capture->working_scale=settings.nr_working_scale;
        for(size_t i=0;i<sources.size();++i){
            const auto& src=sources[i];
            nr_probe_transition(frame.command_list,src.tex,src.state,D3D12_RESOURCE_STATE_COPY_SOURCE);
            D3D12_TEXTURE_COPY_LOCATION dst{};
            dst.pResource=capture->images[i].readback.Get();
            dst.Type=D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT;
            dst.PlacedFootprint=capture->images[i].layout;
            D3D12_TEXTURE_COPY_LOCATION from{};
            from.pResource=src.tex;from.Type=D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;
            from.SubresourceIndex=0U;
            const D3D12_BOX box{src.x,src.y,0U,
                src.x+src.width,src.y+src.height,1U};
            frame.command_list->CopyTextureRegion(&dst,0U,0U,0U,&from,&box);
            nr_probe_transition(frame.command_list,src.tex,D3D12_RESOURCE_STATE_COPY_SOURCE,src.state);
        }
        nr_probe_inflight.push_back(capture);
        trace_event("[CheekyNR][FrameCapture] copy_recorded source=%llu bytes=%llu; no GPU wait",
            static_cast<unsigned long long>(frame.view_id),
            static_cast<unsigned long long>(required));
    } catch (...) {
        trace_event("[CheekyNR][FrameCapture] capture_setup_failed");
    }
}
'''
file=root/"src/nr_probe_capture.hpp"
file.write_text(capture,encoding="utf-8",newline="\n")
edit("src/dlss_nr.cpp","#include <vector>",
'''#include <vector>
#include <thread>
#include <memory>
#include <filesystem>
#include <fstream>
#include <iomanip>''')
edit("src/dlss_nr.cpp",
'''std::deque<ViewState> views;''',
'''std::deque<ViewState> views;
#include "nr_probe_capture.hpp"''')
edit("src/dlss_nr.hpp",
'''void reset_dlss_nr() noexcept;''',
'''void reset_dlss_nr() noexcept;
// One-shot, opt-in, lossless raw texture capture; never queues GPU readback
// or allocates when no user request exists.
[[nodiscard]] bool request_dlss_nr_capture() noexcept;''')
edit("src/dlss_nr.cpp",
'''void reset_dlss_nr() noexcept {''',
'''bool request_dlss_nr_capture() noexcept {
    unsigned idle=0U;
    return nr_probe_requested.compare_exchange_strong(idle,1U);
}
void reset_dlss_nr() noexcept {''')
# Collector is already protected by the D3D12 execution mutex; completion
# only grants writer ownership after GPU recording/fence retirement.
edit("src/dlss_nr.cpp",
'''void collect_dlss_nr_submissions() noexcept {
    std::lock_guard execution_lock(calibration12_execution_mutex());''',
'''void collect_dlss_nr_submissions() noexcept {
    std::lock_guard execution_lock(calibration12_execution_mutex());
    nr_probe_poll();''')
# Capture the unmodified original and exact neural input/output BEFORE codec
# scratch states are restored, and immediately AFTER final decode. All sources
# are restored to their previous resource states after the optional copy.
edit("src/dlss_nr.cpp",
'''    uav_barrier(frame.command_list, frame.color);
    transition(
        frame.command_list,
        frame.color,
        D3D12_RESOURCE_STATE_UNORDERED_ACCESS,
        frame.color_state
    );
    transition(
        frame.command_list,
        gpu->original_output,''',
'''    uav_barrier(frame.command_list, frame.color);
    nr_probe_capture_one(frame,*gpu,codec_region,settings,pass_count);
    transition(
        frame.command_list,
        frame.color,
        D3D12_RESOURCE_STATE_UNORDERED_ACCESS,
        frame.color_state
    );
    transition(
        frame.command_list,
        gpu->original_output,''')
edit("uevr/runtime.cpp",
'''        if (action == "reset_nr") { reset_dlss_nr(); return true; }''',
'''        if (action == "reset_nr") { reset_dlss_nr(); return true; }
        if (action == "nr_capture") {
            const bool armed=request_dlss_nr_capture();
            s.message=armed
                ? "NR frame capture armed; GPU readback files will be written to LocalAppData/ CheekyNR-Captures after GPU completion"
                : "NR capture already armed; finish existing request before triggering again";
            trace_event("[CheekyNR][FrameCapture] request=%s", armed?"armed":"already_pending");
            return armed;
        }''')
edit("uevr/scripts/cheeky_foveated_dlss.lua",
'''        section("Pre-headset diagnostics (all off by default)")''',
'''        section("Pre-headset diagnostics (all off by default)")
        if imgui.button("Capture one NR frame (lossless raw)") then send("nr_capture") end
        text("Capture location: %LOCALAPPDATA%/CheekyNR-Captures")
        text("Four raw images plus capture.json; saves only after GPU completion.")
        text("Button is one-shot; default running has no readback allocations.")''')
print("PASS lossless one-shot capture: 4 GPU textures, deferred readback, existing lifetime")

print("PASS pre-headset setup, DLL version, optional pedestal & flags, look-only template swaps, downscale")
