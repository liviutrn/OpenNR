// DuoView Stage 7: production-oriented DX12 raster compositor.
// Writes directly to a BGRA8 render target; does not require typed BGRA8 UAV.
// Reuses the *same* layout, sampling bounds, feathering and constants as the
// independently validated compute shader. Caller must bind atlas t0,
// constant buffer b0, linear clamp sampler s0 and a dedicated RTV.
// Never render onto the atlas SRV itself: source and destination must differ.
#include "DuoViewComposite.hlsl"

struct VertexOut {
    float4 pos : SV_POSITION;
    float2 uv : TEXCOORD0;
};

// Full-screen triangle, with no scene vertex buffer.
VertexOut VSMain(uint vertexId : SV_VertexID) {
    VertexOut v;
    v.uv = float2((vertexId << 1) & 2, vertexId & 2);
    v.pos = float4(v.uv * float2(2.0, -2.0) + float2(-1.0, 1.0), 0.0, 1.0);
    return v;
}

float4 PSMain(VertexOut i) : SV_TARGET0 {
    const float2 fullUv = i.pos.xy / float2(OutputSize);
    const float2 peripheralSample = AtlasSampleUV(PeripheralRect, fullUv);
    const float4 peripheralColor = SourceAtlas.SampleLevel(LinearClamp, peripheralSample, 0.0);
    const float weight = BlendWeight(fullUv);
    float4 result = DebugViewMode == 2 ? float4(.04,.04,.04,1) : peripheralColor;
    if (weight > 0.0 && DebugViewMode != 1) {
        const float2 foveaUV = (fullUv - CropUv.xy) / (CropUv.zw - CropUv.xy);
        const float2 foveaSample = AtlasSampleUV(FoveaRect, foveaUV);
        const float4 foveaColor = SourceAtlas.SampleLevel(LinearClamp, foveaSample, 0.0);
        result = DebugViewMode == 2 ? foveaColor : lerp(peripheralColor, foveaColor, weight);
    }
    if (DebugBorder && weight > 0.01 && weight < 0.1) {
        result.rgb = float3(1.0, 0.3, 0.0);
    }
    return result;
}
