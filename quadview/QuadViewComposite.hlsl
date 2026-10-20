Texture2D<float4> SourceAtlas : register(t0);
SamplerState LinearClamp : register(s0);

cbuffer QuadViewConstants : register(b0) {
    uint4 EyeAndAtlas;
    uint4 ContextLeft;
    uint4 ContextRight;
    uint4 FocusLeft;
    uint4 FocusRight;
    float4 CropUvLeft;
    float4 CropUvRight;
    float4 Options;
    float4 Sharpen; // strength, flags, maximum filter-space change, FXAA bias
};

struct VertexOut {
    float4 position : SV_POSITION;
};

VertexOut VSMain(uint vertexId : SV_VertexID) {
    const float2 uv = float2((vertexId << 1) & 2, vertexId & 2);
    VertexOut result;
    result.position = float4(uv * float2(2.0, -2.0) + float2(-1.0, 1.0), 0.0, 1.0);
    return result;
}

float2 AtlasUv(uint4 rectangle, float2 uv) {
    const float2 atlasSize = float2(EyeAndAtlas.zw);
    const float2 origin = float2(rectangle.xy);
    const float2 extent = float2(rectangle.zw);
    const float2 texel = clamp(origin + saturate(uv) * extent,
                              origin + 0.5, origin + extent - 0.5);
    return texel / atlasSize;
}

float FocusWeight(float2 uv, float4 crop) {
    if (any(uv < crop.xy) || any(uv > crop.zw)) return 0.0;
    const float2 cropExtent = crop.zw - crop.xy;
    const float2 distanceToEdge = min(uv - crop.xy, crop.zw - uv) / cropExtent;
    const float feather = clamp(Options.x, 0.0, 0.49);
    if (feather == 0.0) return 1.0;
    const float edge = saturate(min(distanceToEdge.x, distanceToEdge.y) / feather);
    return edge * edge * (3.0 - 2.0 * edge);
}

static const float3 GlamLuma = float3(0.2126, 0.7152, 0.0722);

float3 GlamDecode(float3 color) {
    if (((uint)Sharpen.y & 4u) == 0u) return color;
    const float3 low = color / 12.92;
    const float3 high = pow(abs(color + 0.055) / 1.055, 2.4);
    return lerp(low, high, float3(color.r > 0.04045, color.g > 0.04045, color.b > 0.04045));
}

float3 GlamEncode(float3 color) {
    if (((uint)Sharpen.y & 4u) == 0u) return color;
    const float3 low = color * 12.92;
    const float3 high = 1.055 * pow(abs(color), 1.0 / 2.4) - 0.055;
    return lerp(low, high, float3(color.r > 0.0031308, color.g > 0.0031308, color.b > 0.0031308));
}

float3 ReadFocus(uint4 rect, float4 crop, float2 fullUv, float2 pixelOffset) {
    // Offsets are in final output pixels after the game's upscaler. AtlasUv
    // clamps each tap to this eye's focus rectangle, so eyes never bleed.
    const float2 shifted = fullUv + pixelOffset / float2(EyeAndAtlas.xy);
    const float2 local = (shifted - crop.xy) / (crop.zw - crop.xy);
    return GlamDecode(SourceAtlas.SampleLevel(LinearClamp, AtlasUv(rect, local), 0.0).rgb);
}

float3 GlamSharpenFocus(uint4 rect, float4 crop, float2 fullUv, float3 center) {
    // Fused v186.1 Glamarye Bigger-radius four-diagonal filter with its
    // FXAA-style edge guard and maximum-change limiter. No separate pass.
    const float3 c = GlamDecode(center);
    const float radius = 1.4;
    const float3 ne = ReadFocus(rect, crop, fullUv, float2( radius,  radius));
    const float3 sw = ReadFocus(rect, crop, fullUv, float2(-radius, -radius));
    const float3 se = ReadFocus(rect, crop, fullUv, float2( radius, -radius));
    const float3 nw = ReadFocus(rect, crop, fullUv, float2(-radius,  radius));
    float3 smoothed = (ne + nw) + (se + sw);
    smoothed = clamp((smoothed + c) / 5.0, c * 0.5, c * 2.0);
    smoothed = min(smoothed, 1.0);

    const float dy = dot(GlamLuma, abs((ne + nw) - (se + sw)));
    const float dx = dot(GlamLuma, abs((ne + se) - (nw + sw)));
    const bool horizontal = dy > dx;
    float3 n2 = horizontal ? ne + nw : ne + se;
    float3 s2 = horizontal ? se + sw : nw + sw;
    n2 *= 0.5; s2 *= 0.5;
    const float2 west = horizontal ? float2(-3.5, 0.0) : float2(0.0, 3.5);
    const float2 east = horizontal ? float2( 3.5, 0.0) : float2(0.0,-3.5);
    const float3 ww = ReadFocus(rect, crop, fullUv, west);
    const float3 ee = ReadFocus(rect, crop, fullUv, east);
    const float3 d1 = abs((ww - n2) - (ee - s2));
    const float3 d2 = abs((ee - n2) - (ww - s2));
    const float3 totalDiff = d1 + d2 + 0.00004;
    const float3 maxDiff = max(d1, d2) + 0.00001 - Sharpen.w * sqrt(max(smoothed, 0.0));
    const float edgeRatio = max(2.0 * dot(GlamLuma, maxDiff / totalDiff) - 1.0, 0.0);

    const float3 diffRGB = 2.0 * c + (ne + nw + se + sw)
        - 3.0 * (max(max(ne,nw),max(se,sw)) + min(min(ne,nw),min(se,sw)));
    const float diff = dot(GlamLuma, diffRGB);
    float3 possible = min(smoothed, c * 0.5);
    possible = min(possible, 1.0 - max(smoothed, c));
    possible = clamp(possible, 0.00001, Sharpen.z);
    float3 change = diff / (1.0 / max(Sharpen.x, 0.00001) + abs(diff) / possible);
    change *= (1.0 - edgeRatio);
    return GlamEncode(c + change);
}

float4 CompositePixel(VertexOut input) {
    const uint eye = min((uint)input.position.x / EyeAndAtlas.x, 1u);
    const float2 eyeUv = float2(input.position.x - eye * EyeAndAtlas.x,
                               input.position.y) / float2(EyeAndAtlas.xy);
    const uint4 contextRect = eye == 0 ? ContextLeft : ContextRight;
    const uint4 focusRect = eye == 0 ? FocusLeft : FocusRight;
    const float4 crop = eye == 0 ? CropUvLeft : CropUvRight;
    const uint debugMode = (uint)Options.y;
    const float weight = FocusWeight(eyeUv, crop);

    if (debugMode == 3) {
        const float3 contextColor = eye == 0 ? float3(0.8, 0.1, 0.1) : float3(0.1, 0.8, 0.1);
        const float3 focusColor = eye == 0 ? float3(0.1, 0.2, 1.0) : float3(1.0, 0.8, 0.1);
        return float4(lerp(contextColor, focusColor, weight), 1.0);
    }

    const float4 context = SourceAtlas.SampleLevel(LinearClamp, AtlasUv(contextRect, eyeUv), 0.0);
    if (debugMode == 1) return context;
    const float4 background = debugMode == 2 ? float4(0.04, 0.04, 0.04, 1.0) : context;
    if (weight <= 0.0) return background;

    const float2 focusUv = (eyeUv - crop.xy) / (crop.zw - crop.xy);
    float4 focus = SourceAtlas.SampleLevel(LinearClamp, AtlasUv(focusRect, focusUv), 0.0);
    [branch] if (Sharpen.x > 0.0)
        focus.rgb = GlamSharpenFocus(focusRect, crop, eyeUv, focus.rgb);
    float4 output = debugMode == 2 ? focus : lerp(context, focus, weight);
    if (Options.w > 0.5) {
        const float2 edgePx = min(eyeUv - crop.xy, crop.zw - eyeUv) * float2(EyeAndAtlas.xy);
        if (min(edgePx.x, edgePx.y) < 1.0) output.rgb = float3(1.0, 0.75, 0.0);
    }
    return output;
}

// Preserve the baseline copy's color encoding when a typed UNORM atlas is
// drawn into an sRGB runtime texture. The RTV performs the inverse encoding.
float4 PSMain(VertexOut input) : SV_TARGET0 {
    float4 color = CompositePixel(input);
    if (Options.z > 0.5) {
        const float3 low = color.rgb / 12.92;
        const float3 high = pow(max((color.rgb + 0.055) / 1.055, 0.0), 2.4);
        color.rgb = float3(color.r <= 0.04045 ? low.r : high.r,
                           color.g <= 0.04045 ? low.g : high.g,
                           color.b <= 0.04045 ? low.b : high.b);
    }
    return color;
}
