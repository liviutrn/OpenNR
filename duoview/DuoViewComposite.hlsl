// DuoView Mono — Stage 3 atlas compositor (experimental)
// Input is the packed UE render target: a high-density cropped view plus a
// low-density full-frustum view. Output is ONE full-frustum monoscopic frame.
// Run after UE scene rendering and before the existing Mono OpenXR copies.
// Do not apply to UI texture, depth buffer, or existing mono swapchain images.
// This shader's integration into UEVR D3D12 is not yet implemented.

Texture2D<float4> SourceAtlas : register(t0);
RWTexture2D<float4> CompositeTarget : register(u0);
SamplerState LinearClamp : register(s0);

cbuffer DuoViewCompositeConfig : register(b0)
{
    uint2 OutputSize;          // 3000x3000 typical
    uint2 AtlasSize;           // 6000x3000 in the initial double-wide layout
    uint4 FoveaRect;          // x, y, width, height (texels)
    uint4 PeripheralRect;      // x, y, width, height (texels)
    float4 CropUv;             // u0, v0, u1, v1 in full-frustum normalized UVs
    float FeatherFraction;     // feather as fraction of fovea width/height
    uint DebugBorder;
    uint DebugViewMode;
    float _reserved;
    uint2 NativeFoveaDimensions;
    uint2 NativePeripheryDimensions;
    uint2 OutputOffset; // offset of current OpenXR eye within doublewide RTV
};

float2 AtlasSampleUV(uint4 rect, float2 localUv)
{
    // Explicit half-texel clamp prevents filtering one view into the other.
    const float2 origin = float2(rect.xy);
    const float2 dimensions = float2(rect.zw);
    const float2 atlasDimensions = float2(AtlasSize);
    const float2 uv = (origin + saturate(localUv) * dimensions) / atlasDimensions;
    const float2 lo = (origin + 0.5) / atlasDimensions;
    const float2 hi = (origin + dimensions - 0.5) / atlasDimensions;
    return clamp(uv, lo, hi);
}

float BlendWeight(float2 fullUv)
{
    const float2 cropSize = CropUv.zw - CropUv.xy;
    if (any(fullUv < CropUv.xy) || any(fullUv > CropUv.zw))
        return 0.0;

    if (FeatherFraction <= 0.0)
        return 1.0;

    const float2 local = (fullUv - CropUv.xy) / cropSize;
    const float2 toBorder = min(local, 1.0 - local);
    const float relativeDistance = min(toBorder.x, toBorder.y);
    const float t = saturate(relativeDistance / FeatherFraction);
    return t * t * (3.0 - 2.0 * t);
}

[numthreads(8, 8, 1)]
void CSMain(uint3 threadId : SV_DispatchThreadID)
{
    if (threadId.x >= OutputSize.x || threadId.y >= OutputSize.y)
        return;

    const float2 fullUv = (float2(threadId.xy) + 0.5) / float2(OutputSize);
    const float2 peripheralSample = AtlasSampleUV(PeripheralRect, fullUv);
    const float4 peripheralColor = SourceAtlas.SampleLevel(LinearClamp, peripheralSample, 0.0);

    const float weight = BlendWeight(fullUv);
    float4 result = DebugViewMode == 2 ? float4(.04,.04,.04,1) : peripheralColor;
    if (weight > 0.0 && DebugViewMode != 1)
    {
        const float2 roiLocal = (fullUv - CropUv.xy) / (CropUv.zw - CropUv.xy);
        const float2 fovealSample = AtlasSampleUV(FoveaRect, roiLocal);
        const float4 fovealColor = SourceAtlas.SampleLevel(LinearClamp, fovealSample, 0.0);
        // Intended for identical color encoding in both views. Seam reduction
        // requires both UE views to use compatible exposure and temporal history.
        result = DebugViewMode == 2 ? fovealColor : lerp(peripheralColor, fovealColor, weight);
    }

    if (DebugBorder != 0 && weight > 0.01 && weight < 0.1)
        result.rgb = float3(1.0, 0.3, 0.0);

    CompositeTarget[threadId.xy] = result;
}
