// DuoView Native Stereo Fix compositor: sample both validated UE source
// textures in place, rather than gathering two rectangles into a doublewide
// intermediate atlas. Matches the legacy blend and half-texel bounds exactly.
// SourceAtlas (t0) is repurposed for the fovea, t1 for the periphery.
// Original Native Fix render targets, scene histories and shading are untouched.
#include "DuoViewCompositeRaster.hlsl"
Texture2D<float4> PeripheralNativeSource : register(t1);

float2 NativeSampleUV(float2 local, uint2 active, uint2 resourceSize) {
    const float2 texels = clamp(saturate(local) * float2(active),
                                float2(.5,.5), float2(active)-.5);
    return texels / float2(resourceSize);
}

float4 PSNativeMain(VertexOut i) : SV_TARGET0 {
    // A compatible double-wide XR target can be filled in one raster draw.
    // Reuse the same Mono image coordinates in each half without changing
    // either source rectangle or the eye-local blend math.
    float2 outputPixel = i.pos.xy;
    if (outputPixel.x >= OutputSize.x) outputPixel.x -= OutputSize.x;
    const float2 fullUv = outputPixel / float2(OutputSize);
    const float2 peripherySample = NativeSampleUV(
        fullUv, PeripheralRect.zw, NativePeripheryDimensions);
    const float4 periphery = PeripheralNativeSource.SampleLevel(
        LinearClamp, peripherySample, 0.0);
    const float weight = BlendWeight(fullUv);
    float4 result = DebugViewMode == 2 ? float4(.04,.04,.04,1) : periphery;
    if (weight > 0.0 && DebugViewMode != 1) {
        const float2 localFovea = (fullUv - CropUv.xy) / (CropUv.zw - CropUv.xy);
        const float2 foveaSample = NativeSampleUV(
            localFovea, FoveaRect.zw, NativeFoveaDimensions);
        const float4 fovea = SourceAtlas.SampleLevel(LinearClamp, foveaSample, 0.0);
        result = DebugViewMode == 2 ? fovea : lerp(periphery,fovea,weight);
    }
    if (DebugBorder && weight > 0.01 && weight < 0.1)
        result.rgb = float3(1.0,0.3,0.0);
    return result;
}
