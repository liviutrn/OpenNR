// OpenNR 2.20.1-v01 — sequential Feature 18 pass-2 composite.
//
// Pass 1 is a full image of the live NR crop. Pass 2 may cover only a centered
// fraction of that image. This pass copies pass 1 everywhere and composites the
// compact pass-2 result into its centered region with independent edge controls.
//
// BlendMode: 0=hard copy, 1=feather, 2=dither.
// MaskMode:  0=rectangle, 1=oval.

cbuffer SequentialCompositeCB : register(b0)
{
    uint FullWidth;
    uint FullHeight;
    uint Pass2OffsetX;
    uint Pass2OffsetY;

    uint Pass2Width;
    uint Pass2Height;
    uint BlendMode;
    uint MaskMode;

    uint FrameIndex;
    float FeatherWidth;
    float DitherStrength;
    float FalloffCurve;

    float _pad0;
    float _pad1;
    float _pad2;
    float _pad3;
};

Texture2D<float4> Pass1Tex : register(t0);
Texture2D<float4> Pass2Tex : register(t1);
RWTexture2D<float4> OutputTex : register(u0);

float BlueNoise(uint2 pos, uint frame)
{
    float x = float(pos.x) + 5.588238 * float(frame);
    float y = float(pos.y) + 5.588238 * float(frame);
    return frac(52.9829189 * frac(0.06711056 * x + 0.00583715 * y));
}

float EllipseEdgeDistance(float2 offset, float2 radii)
{
    float2 safeRadii = max(radii, float2(0.5, 0.5));
    float2 inverseRadiiSquared = 1.0 / (safeRadii * safeRadii);
    float ellipseValue = 1.0 - dot(offset * offset, inverseRadiiSquared);
    float2 gradient = 2.0 * offset * inverseRadiiSquared;
    float gradientLength = length(gradient);
    if (gradientLength < 1e-5)
        return min(safeRadii.x, safeRadii.y);
    return clamp(ellipseValue / gradientLength,
        -max(safeRadii.x, safeRadii.y), max(safeRadii.x, safeRadii.y));
}

float FalloffAlpha(float normalizedDistance, float curve)
{
    float t = saturate(normalizedDistance);
    t = pow(t, clamp(curve, 0.5, 2.0));
    return t * t * (3.0 - 2.0 * t);
}

[numthreads(8, 8, 1)]
void main(uint3 tid : SV_DispatchThreadID)
{
    if (tid.x >= FullWidth || tid.y >= FullHeight)
        return;

    const uint2 dstPos = tid.xy;
    const float4 pass1 = Pass1Tex.Load(int3(dstPos, 0));

    if (tid.x < Pass2OffsetX || tid.y < Pass2OffsetY ||
        tid.x >= Pass2OffsetX + Pass2Width || tid.y >= Pass2OffsetY + Pass2Height) {
        OutputTex[dstPos] = pass1;
        return;
    }

    const uint2 local = uint2(tid.x - Pass2OffsetX, tid.y - Pass2OffsetY);
    const float4 pass2 = Pass2Tex.Load(int3(local, 0));
    if (BlendMode == 0) {
        OutputTex[dstPos] = pass2;
        return;
    }

    float edgeDistance;
    if (MaskMode == 1) {
        const float2 center = float2(Pass2Width, Pass2Height) * 0.5;
        const float2 radii = max(center, float2(0.5, 0.5));
        const float2 localPos = float2(local) + 0.5;
        edgeDistance = EllipseEdgeDistance(localPos - center, radii);
    } else {
        const float distL = float(local.x);
        const float distR = float(Pass2Width - 1 - local.x);
        const float distT = float(local.y);
        const float distB = float(Pass2Height - 1 - local.y);
        edgeDistance = min(min(distL, distR), min(distT, distB));
    }

    // Outside an oval, pass 1 owns the pixel entirely.
    if (edgeDistance <= 0.0) {
        OutputTex[dstPos] = pass1;
        return;
    }

    const float feather = max(FeatherWidth, 1.0);
    if (edgeDistance >= feather) {
        OutputTex[dstPos] = pass2;
        return;
    }

    float alpha = FalloffAlpha(edgeDistance / feather, FalloffCurve);
    if (BlendMode == 2) {
        const float noise = BlueNoise(local, FrameIndex);
        alpha = saturate(alpha + (noise - 0.5) * DitherStrength);
    }
    OutputTex[dstPos] = lerp(pass1, pass2, alpha);
}
