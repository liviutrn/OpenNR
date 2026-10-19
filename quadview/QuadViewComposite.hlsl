Texture2D<float4> SourceAtlas : register(t0);
SamplerState LinearClamp : register(s0);

cbuffer QuadViewConstants : register(b0) {
    uint4 EyeAndAtlas;
    uint4 ContextLeft;
    uint4 ContextRight;
    uint4 FocusLeft;
    uint4 FocusRight;
    float4 CropUv;
    float4 Options;
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

float FocusWeight(float2 uv) {
    if (any(uv < CropUv.xy) || any(uv > CropUv.zw)) return 0.0;
    const float2 cropExtent = CropUv.zw - CropUv.xy;
    const float2 distanceToEdge = min(uv - CropUv.xy, CropUv.zw - uv) / cropExtent;
    const float feather = clamp(Options.x, 0.0, 0.49);
    if (feather == 0.0) return 1.0;
    const float edge = saturate(min(distanceToEdge.x, distanceToEdge.y) / feather);
    return edge * edge * (3.0 - 2.0 * edge);
}

float4 CompositePixel(VertexOut input) {
    const uint eye = min((uint)input.position.x / EyeAndAtlas.x, 1u);
    const float2 eyeUv = float2(input.position.x - eye * EyeAndAtlas.x,
                               input.position.y) / float2(EyeAndAtlas.xy);
    const uint4 contextRect = eye == 0 ? ContextLeft : ContextRight;
    const uint4 focusRect = eye == 0 ? FocusLeft : FocusRight;
    const uint debugMode = (uint)Options.y;
    const float weight = FocusWeight(eyeUv);

    if (debugMode == 3) {
        const float3 contextColor = eye == 0 ? float3(0.8, 0.1, 0.1) : float3(0.1, 0.8, 0.1);
        const float3 focusColor = eye == 0 ? float3(0.1, 0.2, 1.0) : float3(1.0, 0.8, 0.1);
        return float4(lerp(contextColor, focusColor, weight), 1.0);
    }

    const float4 context = SourceAtlas.SampleLevel(LinearClamp, AtlasUv(contextRect, eyeUv), 0.0);
    if (debugMode == 1) return context;
    const float4 background = debugMode == 2 ? float4(0.04, 0.04, 0.04, 1.0) : context;
    if (weight <= 0.0) return background;

    const float2 focusUv = (eyeUv - CropUv.xy) / (CropUv.zw - CropUv.xy);
    const float4 focus = SourceAtlas.SampleLevel(LinearClamp, AtlasUv(focusRect, focusUv), 0.0);
    return debugMode == 2 ? focus : lerp(context, focus, weight);
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
