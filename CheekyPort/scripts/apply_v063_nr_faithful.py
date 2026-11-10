#!/usr/bin/env python3
"""Add backwards-compatible Faithful HDR result reconstruction to Cheeky NR-Lite.

Legacy shader remains bit-for-bit available in mode 0. Model inference,
frame cadence and game's native DLSS SR remain untouched. No temporal cache.
"""
from pathlib import Path
import sys

root = Path(sys.argv[1]).resolve()

def patch(path, before, after, occurrences=1):
    file = root / path
    data = file.read_text(encoding="utf-8")
    n = data.count(before)
    if n != occurrences:
        raise RuntimeError(f"{path}: expected {occurrences} anchors, found {n}: {before[:120]!r}")
    file.write_text(data.replace(before, after), encoding="utf-8", newline="\n")
    print("NR-FAITHFUL patched", path)

# Persist reconstructed look independently of NVIDIA's feature key and history.
# Mode 0: exact legacy. Mode 1: faithful HDR / game-color preservation.
patch("src/settings.hpp",
    "    float nr_color_strength{1.0F};",
    """    float nr_color_strength{1.0F};
    std::uint32_t nr_reconstruction_mode{1U};
    float nr_shoulder_knee{0.75F};
    float nr_edit_brighten{0.40F};
    float nr_edit_darken{0.40F};
    float nr_edit_chroma{0.15F};
    float nr_edit_hue{0.0F};
    float nr_detail_preservation{0.0F}; // experimental, off until profiled""")
patch("src/settings.cpp",
    "std::atomic<std::uint32_t> nr_color_strength_bits{0x3F800000U};",
    """std::atomic<std::uint32_t> nr_color_strength_bits{0x3F800000U};
std::atomic<std::uint32_t> nr_reconstruction_mode{1U};
std::atomic<std::uint32_t> nr_shoulder_knee_bits{0x3F400000U};
std::atomic<std::uint32_t> nr_edit_brighten_bits{0x3ECCCCCDU};
std::atomic<std::uint32_t> nr_edit_darken_bits{0x3ECCCCCDU};
std::atomic<std::uint32_t> nr_edit_chroma_bits{0x3E19999AU};
std::atomic<std::uint32_t> nr_edit_hue_bits{};
std::atomic<std::uint32_t> nr_detail_preservation_bits{};""")
patch("src/settings.cpp",
    "    settings.nr_color_strength = load_float(nr_color_strength_bits);",
    """    settings.nr_color_strength = load_float(nr_color_strength_bits);
    settings.nr_reconstruction_mode = nr_reconstruction_mode.load(std::memory_order_acquire);
    settings.nr_shoulder_knee = load_float(nr_shoulder_knee_bits);
    settings.nr_edit_brighten = load_float(nr_edit_brighten_bits);
    settings.nr_edit_darken = load_float(nr_edit_darken_bits);
    settings.nr_edit_chroma = load_float(nr_edit_chroma_bits);
    settings.nr_edit_hue = load_float(nr_edit_hue_bits);
    settings.nr_detail_preservation = load_float(nr_detail_preservation_bits);""")
patch("src/settings.cpp",
    """    nr_depth_convention.store(
        (std::min)(settings.nr_depth_convention, 2U),""",
    """    nr_reconstruction_mode.store((std::min)(settings.nr_reconstruction_mode, 1U), std::memory_order_release);
    store_float(nr_shoulder_knee_bits, std::clamp(settings.nr_shoulder_knee, 0.5F, 0.95F));
    store_float(nr_edit_brighten_bits, std::clamp(settings.nr_edit_brighten, 0.0F, 2.0F));
    store_float(nr_edit_darken_bits, std::clamp(settings.nr_edit_darken, 0.0F, 2.0F));
    store_float(nr_edit_chroma_bits, std::clamp(settings.nr_edit_chroma, 0.0F, 2.0F));
    store_float(nr_edit_hue_bits, std::clamp(settings.nr_edit_hue, 0.0F, 2.0F));
    store_float(nr_detail_preservation_bits, std::clamp(settings.nr_detail_preservation, 0.0F, 1.0F));
    nr_depth_convention.store(
        (std::min)(settings.nr_depth_convention, 2U),""")
patch("uevr/settings_fields.inc",
    'CHEEKY_SETTING("NrColorStrength", nr_color_strength)',
    '''CHEEKY_SETTING("NrColorStrength", nr_color_strength)
CHEEKY_SETTING("NrReconstructionMode", nr_reconstruction_mode)
CHEEKY_SETTING("NrShoulderKnee", nr_shoulder_knee)
CHEEKY_SETTING("NrEditBrighten", nr_edit_brighten)
CHEEKY_SETTING("NrEditDarken", nr_edit_darken)
CHEEKY_SETTING("NrEditChroma", nr_edit_chroma)
CHEEKY_SETTING("NrEditHue", nr_edit_hue)
CHEEKY_SETTING("NrDetailPreservation", nr_detail_preservation)''')
patch("uevr/settings_io.cpp",
    '    if(key=="NrPass1Views" || key=="NrPass2Views"){',
    '''    if(key=="NrReconstructionMode") {
        unsigned mode{};
        if (!parse(value, mode) || mode > 1U) return false;
        s.nr_reconstruction_mode = mode;
        return true;
    }
    if(key=="NrPass1Views" || key=="NrPass2Views"){''')

# Existing UEVR layout retains paper white, HDR transfer, and color strength.
# New faithful controls are shown only when the new mode is active.
patch("uevr/scripts/cheeky_foveated_dlss.lua",
    '        slider("Color strength", "NrColorStrength", 0, 2)',
    '''        slider("Color strength", "NrColorStrength", 0, 2)
        section("HDR reconstruction — game colour preservation")
        combo("NR HDR reconstruction", "NrReconstructionMode",
            {[0]="Legacy (original Cheeky)", [1]="Faithful HDR (recommended)"}, {1,0})
        if (draft.NrReconstructionMode or 0) == 1 then
            text("Keeps original game color; new controls edit only the NR result.")
            slider("Highlight shoulder knee", "NrShoulderKnee", 0.5, 0.95)
            slider("Neural brighten", "NrEditBrighten", 0, 2)
            slider("Neural darken", "NrEditDarken", 0, 2)
            slider("Neural saturation change", "NrEditChroma", 0, 2)
            slider("Neural hue change", "NrEditHue", 0, 2)
            text("Detail-preservation filter is experimental and OFF until GPU/visual validation.")
            text("Experimental 4-neighbour spatial detail. OFF until cost/halos are verified.")
            slider("Spatial detail preservation", "NrDetailPreservation", 0, 1)
        end''')

# Embed eight more shader constants in the SAME root-constants block.
# No extra resource descriptors, command lists or GPU texture allocations.
patch("src/nr_codec_shader.hpp",
    "        float mask_bounds[4][4];",
    """        float mask_bounds[4][4];
        std::uint32_t reconstruction_mode;
        float shoulder_knee, edit_brighten, edit_darken;
        float edit_chroma, edit_hue, detail_preservation;
        float reserved_faithful;""")
patch("src/nr_codec_shader.hpp",
    "static_assert(sizeof(CodecConstants) == 40U * sizeof(std::uint32_t));",
    "static_assert(sizeof(CodecConstants) == 48U * sizeof(std::uint32_t));")
patch("src/nr_codec_shader.hpp",
    "    float4 MaskBounds[4];",
    """    float4 MaskBounds[4];
    uint ReconstructionMode;
    float ShoulderKnee;
    float EditBrighten;
    float EditDarken;
    float EditChroma;
    float EditHue;
    float DetailPreservation;
    float ReservedFaithful;""")

faithful_code = r"""
// The network sees a bounded, hue-preserving proxy rather than hard-clipped
// scene-linear RGB channels. The original HDR source remains unmodified.
float3 FaithfulShoulder(float3 linear_color) {
    const float3 c = max(linear_color, 0.0);
    const float y = Luminance(c);
    const float k = clamp(ShoulderKnee, 0.5, 0.95);
    const float roll = y <= k ? y :
        k + (1.0 - k) * (1.0 - exp(-(y - k) / max(1.0 - k, 1e-4)));
    float3 mapped = c * (roll / max(y, 1e-6));
    // Preserve RGB ratios, including very saturated HDR primaries.
    const float peak = max(mapped.r, max(mapped.g, mapped.b));
    return peak > 1.0 ? mapped / peak : mapped;
}

// Decode-space result editor. Every edit is measured against the ORIGINAL
// proxy fed to NGX, not against the game frame, making no-edit exact identity.
// A luminance-only result preserves the game's hue and saturation.

// Same-frame, edge-gated four-neighbour high-frequency NR edit. No history,
// no persistent GPU surface and no second NR evaluation. Costs extra texture
// reads ONLY when DetailPreservation > 0; do not enable as default until timed.
float FaithfulSpatialDetail(float2 position) {
    const int2 size = int2(ProxySize);
    const int2 texel = clamp(int2(round(position)), int2(0, 0), size - 1);
    const float3 cp = Source1.Load(int3(texel, 0)).rgb;
    const float3 cn = Source2.Load(int3(texel, 0)).rgb;
    const float base = max(Luminance(cp), 1e-4);
    const float center = clamp(log2(max(Luminance(cn), 1e-4) / base), -2.0, 2.0);
    float sum = center;
    float weight_sum = 1.0;
    [unroll] for (int i = 0; i < 4; ++i) {
        const int2 offset = i == 0 ? int2(-2, 0) :
                            i == 1 ? int2(2, 0) :
                            i == 2 ? int2(0, -2) : int2(0, 2);
        const int2 q = clamp(texel + offset, int2(0, 0), size - 1);
        const float yp = max(Luminance(Source1.Load(int3(q, 0)).rgb), 1e-4);
        const float yn = max(Luminance(Source2.Load(int3(q, 0)).rgb), 1e-4);
        // Similar original materials only. Reject sky/grass boundaries to
        // avoid leaking the brightness edit across an actual scene edge.
        const float same = saturate(1.0 - 2.5 * abs(log2(yp / base)));
        sum += same * clamp(log2(yn / yp), -2.0, 2.0);
        weight_sum += same;
    }
    const float broad = sum / max(weight_sum, 1.0);
    // Convert encoded-domain log contrast to approximate linear detail.
    return clamp(1.5 * (center - broad), -1.0, 1.0);
}

float3 FaithfulUpgrade(float3 original, float3 proxy, float3 neural,
                       float2 proxy_position) {
    const float eps = 1e-5;
    if (!all(isfinite(original)) || !all(isfinite(proxy)) || !all(isfinite(neural)))
        return original;
    const float py = Luminance(max(proxy, 0.0));
    const float ny = Luminance(max(neural, 0.0));
    const float oy = Luminance(max(original, 0.0));
    const float trust = smoothstep(0.002, 0.035, py);
    float stops = clamp(log2(max(ny, eps) / max(py, eps)), -2.0, 2.0);
    // Guard against the heavy NR darkening of highlights on Natural/Cinematic.
    const float hi = smoothstep(0.65, 0.98, py);
    const float lighten = stops >= 0.0 ? EditBrighten :
        EditDarken * lerp(1.0, 0.5, hi);
    stops *= lighten * trust * TransferStrength * ColorStrength;
    if (DetailPreservation > 0.0001 && trust > 0.01) {
        const float fine = FaithfulSpatialDetail(proxy_position);
        stops += fine * DetailPreservation * trust * TransferStrength * ColorStrength;
    }

    const float3 ln_p = log2(max(proxy, eps));
    const float3 ln_n = log2(max(neural, eps));
    const float3 w = float3(0.2126, 0.7152, 0.0722);
    float3 color_edit = clamp(ln_n - ln_p, -1.0, 1.0);
    color_edit -= dot(color_edit, w);
    float3 direction = ln_p - dot(ln_p, w);
    const float norm = dot(direction * direction, w);
    float3 radial = norm > 1e-5 ?
        direction * (dot(color_edit * direction, w) / norm) : 0.0;
    float3 tangent = color_edit - radial;
    const float3 limited = clamp(EditChroma * radial + EditHue * tangent,
                                 -0.6, 0.6);
    const float3 directionally_edited =
        max(original, 0.0) * exp2(limited * trust * TransferStrength * ColorStrength);
    const float lum = Luminance(directionally_edited);
    // Renormalize the chroma edit so it cannot secretly shift brightness.
    float3 result = directionally_edited * (oy / max(lum, eps));
    result *= exp2(stops);
    // Preserve signed out-of-gamut HDR channels when the NR edit is neutral.
    return result + min(original, 0.0);
}
"""

patch("src/nr_codec_shader.hpp",
    "[numthreads(16, 16, 1)]\nvoid EncodeMain",
    faithful_code + "\n[numthreads(16, 16, 1)]\nvoid EncodeMain")
patch("src/nr_codec_shader.hpp",
    "        const float3 encoded = HdrMode != 0 ? SrgbEncode(linear_color) : proxy_source.rgb;",
    """        const float3 encoded = HdrMode != 0
            ? SrgbEncode(ReconstructionMode == 1U
                ? FaithfulShoulder(linear_color) : linear_color)
            : proxy_source.rgb;""")
patch("src/nr_codec_shader.hpp",
    """    const float3 upgraded = UpgradeToneMap(original, proxy, neural);
    const float3 decoded = lerp(original, upgraded, ColorStrength) * CodecWhite();""",
    """    const float3 upgraded = ReconstructionMode == 1U
        ? FaithfulUpgrade(original, proxy, neural, proxy_position)
        : UpgradeToneMap(original, proxy, neural);
    const float3 decoded = (ReconstructionMode == 1U
        ? upgraded : lerp(original, upgraded, ColorStrength)) * CodecWhite();""")

# Note: The optional spatial pass is deliberately not activated yet. A real
# detail/halo/frametime comparison is required before enabling it. Its setting
# remains 0 and this initial build does not allocate any extra textures.

# SDR/uncertain-HDR NGX paths need the same faithful controls, otherwise a
# misreported HDR flag silently falls back to the uncorrected legacy transfer.
# Preserve the exact old behavior when ReconstructionMode is 0.
patch("src/nr_codec_shader.hpp",
    """    if (HdrMode == 0) {
        const float4 processed = float4(lerp(original_sample.rgb, neural_sample.rgb,
            TransferStrength * ColorStrength), original_sample.a);
        Output0[SourceBase + dispatch_id.xy] = lerp(original_sample, processed, foveation_weight);
        return;
    }""",
    """    if (HdrMode == 0) {
        const float3 faithful = FaithfulUpgrade(original_sample.rgb,
            proxy_sample.rgb, neural_sample.rgb, proxy_position);
        const float3 color = ReconstructionMode == 1U
            ? saturate(faithful)
            : lerp(original_sample.rgb, neural_sample.rgb, TransferStrength * ColorStrength);
        const float4 processed = float4(color, original_sample.a);
        Output0[SourceBase + dispatch_id.xy] = lerp(original_sample, processed, foveation_weight);
        return;
    }""")

patch("src/dlss_nr.cpp",
    "    root_parameters[2].Constants.Num32BitValues = 40U;",
    "    root_parameters[2].Constants.Num32BitValues = 48U;")
patch("src/dlss_nr.cpp",
    "    frame.command_list->SetComputeRoot32BitConstants(2U, 40U, &constants, 0U);",
    """    constants.reconstruction_mode = settings.nr_reconstruction_mode;
    constants.shoulder_knee = settings.nr_shoulder_knee;
    constants.edit_brighten = settings.nr_edit_brighten;
    constants.edit_darken = settings.nr_edit_darken;
    constants.edit_chroma = settings.nr_edit_chroma;
    constants.edit_hue = settings.nr_edit_hue;
    constants.detail_preservation = settings.nr_detail_preservation;
    constants.reserved_faithful = 0.0F;
    frame.command_list->SetComputeRoot32BitConstants(2U, 48U, &constants, 0U);""")

# Exposure: log verifiable CPU metadata and actual shader path, without a GPU
# readback stall. Texture contents remain GPU-only, so DO NOT claim that the
# final scalar CodecWhite was measured on CPU.
patch("src/dlss_nr.cpp",
    "    const auto exposure_state = debug_exposure.state;",
    """    if (pipeline == gpu.encode_pipeline) {
        static std::array<std::atomic<std::uint64_t>, 5> exposure_log_counter{};
        const auto idx = (std::min)(frame.source_role, 4U);
        const auto sequence = exposure_log_counter[idx].fetch_add(1U, std::memory_order_relaxed);
        if ((sequence & 127ULL) == 0ULL) {
            const bool valid = gpu.exposure &&
                debug_exposure_supported(debug_exposure);
            const float basis = valid ? debug_exposure.pre / debug_exposure.scale : 0.0F;
            trace_event("[CheekyNR][Exposure] source=%llu role=%u pass=%u hdr=%u route=%u sourceValid=%u exposureTexture=%p pre=%.7g scale=%.7g ratio=%.7g paperWhite=%.7g GPUwhiteFormula=%s",
                static_cast<unsigned long long>(frame.view_id), frame.source_role,
                frame.logical_pass, unsigned((frame.create_flags & 1U) != 0U),
                unsigned(frame.route), unsigned(valid), gpu.exposure.Get(),
                debug_exposure.pre, debug_exposure.scale, basis,
                settings.nr_paper_white_scale,
                valid ? "paperWhite*ratio/texture.r" : "paperWhite(fallback)");
        }
    }
    const auto exposure_state = debug_exposure.state;""")

# Switching the input shoulder changes NVIDIA inference input, so reset the
# neural history ONLY when the HDR input encoding/mode changes. Shader-only
# result sliders must preserve histories and feature keys.
patch("src/nr_parameters.hpp",
    "    append(static_cast<std::uint32_t>(settings.nr_processing_order));",
    """    append(static_cast<std::uint32_t>(settings.nr_processing_order));
    append(settings.nr_reconstruction_mode);
    std::uint32_t shoulder_bits{};
    std::memcpy(&shoulder_bits, &settings.nr_shoulder_knee, sizeof(shoulder_bits));
    append(shoulder_bits);""")

# The checked-in Vulkan SPIR-V remains the pinned upstream 40-DWORD codec.
# The extended 48-DWORD root block is for regenerated D3D12 HLSL ONLY.
# Preserve Vulkan's original push-constant interface and legacy behavior.
vulkan = root / "src/vulkan_nr.cpp"
source = vulkan.read_text(encoding="utf-8")
if source.count("sizeof(CodecConstants)") != 6:
    raise RuntimeError("Vulkan codec ABI uses unexpected number of push-constant sites")
source = source.replace("sizeof(CodecConstants)", "(40U * sizeof(std::uint32_t))")
vulkan.write_text(source, encoding="utf-8", newline="\n")
print("PASS Vulkan retained original 40-DWORD codec ABI")

print("PASS Faithful HDR shader result editor, persisted controls, exposure metadata")
