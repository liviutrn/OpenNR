#pragma once
// Glamarye Intelligent Sharpen DX12 adaptation.
// Original sharpening and anti-aliasing mathematics:
// Copyright (c) 2021 Robert Jessop, MIT License.
// See LICENSE-GLAMARYE.txt. This adaptation is not affiliated with the author.
static constexpr char kSharpenShader[] = R"HLSL(
cbuffer C : register(b0) {
    float2 imageSize;
    float strength;
    float maxChange;
    float fxaaBias;
    float maximumColour;
    uint flags;    // bit0: edge protection; bit1: bigger; bit2: side-by-side; bit3: debug grid
    uint layer;
    uint colourMode; // 0=hardware sRGB/linear; 1=manual SDR sRGB; 2=scRGB (203 nit reference)
};
Texture2DArray<float4> src : register(t0);
SamplerState linearClamp : register(s0);
static const float3 luma = float3(0.2126, 0.7152, 0.0722);
// Glamarye's explicit color-space transformation, where required.
// When the SRV and RTV use DXGI_FORMAT_*_SRGB, hardware handles the two
// conversions automatically and mode 0 avoids processing the transfer twice.
float3 DecodeColour(float3 c) {
    // Branchless vector decode avoids FXC's conditional-function return warnings.
    float3 srgbLow = c / 12.92;
    float3 srgbHigh = pow(abs(c + 0.055) / 1.055, 2.4);
    float3 mask = float3(c.r > 0.04045 ? 1.0 : 0.0,
                         c.g > 0.04045 ? 1.0 : 0.0,
                         c.b > 0.04045 ? 1.0 : 0.0);
    float3 srgbLinear = lerp(srgbLow, srgbHigh, mask);
    return (colourMode == 1u) ? srgbLinear :
           ((colourMode == 2u) ? c * (80.0 / 203.0) : c);
}
float3 EncodeColour(float3 c) {
    float3 srgbLow = c * 12.92;
    float3 srgbHigh = 1.055 * pow(abs(c), 1.0 / 2.4) - 0.055;
    float3 mask = float3(c.r > 0.0031308 ? 1.0 : 0.0,
                         c.g > 0.0031308 ? 1.0 : 0.0,
                         c.b > 0.0031308 ? 1.0 : 0.0);
    float3 srgbOut = lerp(srgbLow, srgbHigh, mask);
    return (colourMode == 1u) ? srgbOut :
           ((colourMode == 2u) ? c * (203.0 / 80.0) : c);
}
struct VSOut { float4 pos : SV_Position; };
VSOut VSMain(uint id : SV_VertexID) {
    VSOut v;
    float2 uv = float2((id << 1) & 2, id & 2);
    v.pos = float4(uv * float2(2, -2) + float2(-1, 1), 0, 1);
    return v;
}
float3 ReadAt(float2 uv, float2 offset, float2 centerUV) {
    float2 p = uv + offset / imageSize;
    float2 lo = 0.5 / imageSize;
    float2 hi = 1.0 - lo;
    // A side-by-side eye buffer must never sample from the other eye.
    if ((flags & 4u) != 0u) {
        float halfWidth = floor(imageSize.x * 0.5);
        if (centerUV.x < halfWidth / imageSize.x) hi.x = (halfWidth - 0.5) / imageSize.x;
        else lo.x = (halfWidth + 0.5) / imageSize.x;
    }
    return DecodeColour(src.SampleLevel(linearClamp, float3(clamp(p, lo, hi), float(layer)), 0).rgb);
}
float4 PSMain(VSOut input) : SV_Target {
    float2 uv = input.pos.xy / imageSize;
    float4 original = src.SampleLevel(linearClamp, float3(uv, float(layer)), 0);
    // Red test grid is OFF by default and only proves the GPU pass touches
    // the actual submitted eye texture; it is not part of Glamarye sharpening.
    if ((flags & 8u) != 0u &&
        (frac(uv.x*8.0) < 0.12 || frac(uv.y*8.0) < 0.12))
        return float4(1.0, 0.01, 0.05, original.a);
    if (strength <= 0.00001) return original;

    float3 c = DecodeColour(original.rgb);
    float radius = (flags & 2u) != 0u ? 1.4 : 0.5;
    float3 ne = ReadAt(uv, float2( radius,  radius), uv);
    float3 sw = ReadAt(uv, float2(-radius, -radius), uv);
    float3 se = ReadAt(uv, float2( radius, -radius), uv);
    float3 nw = ReadAt(uv, float2(-radius,  radius), uv);
    float3 smoothed = (ne + nw) + (se + sw);
    if ((flags & 2u) != 0u)
        smoothed = clamp((smoothed + c) / 5.0, c / 2.0, c * 2.0);
    else
        smoothed = clamp((smoothed - c) / 3.0, c / 2.0, c * 2.0);
    smoothed = min(smoothed, maximumColour);

    float edgeRatio = 0;
    if ((flags & 1u) != 0u) {
        float dy = dot(luma, abs((ne + nw) - (se + sw)));
        float dx = dot(luma, abs((ne + se) - (nw + sw)));
        bool horizontal = dy > dx;
        float3 n2 = horizontal ? ne + nw : ne + se;
        float3 s2 = horizontal ? se + sw : nw + sw;
        if ((flags & 2u) != 0u) { n2 *= 0.5; s2 *= 0.5; }
        else { n2 -= c; s2 -= c; }
        float2 farWest = horizontal ? float2(-3.5, 0.0) : float2(0.0, 3.5);
        float2 farEast = horizontal ? float2(3.5, 0.0) : float2(0.0, -3.5);
        float3 ww = ReadAt(uv, farWest, uv);
        float3 ee = ReadAt(uv, farEast, uv);
        float3 d1 = abs((ww - n2) - (ee - s2));
        float3 d2 = abs((ee - n2) - (ww - s2));
        float3 totalDiff = d1 + d2 + 0.00004;
        float3 maxDiff = max(d1, d2) + 0.00001 - fxaaBias * sqrt(max(smoothed, 0.0));
        float score = dot(luma, maxDiff / totalDiff);
        edgeRatio = max(2.0 * score - 1.0, 0.0);
    }

    // Retains the original median/outlier detail term from Glamarye.
    float3 diffRGB = 2.0*c + (ne+nw+se+sw)
                   - 3.0*(max(max(ne,nw),max(se,sw)) + min(min(ne,nw),min(se,sw)));
    float diff = dot(luma, diffRGB);
    float3 possible = min(smoothed, c * 0.5);
    possible = min(possible, maximumColour - max(smoothed, c));
    possible = clamp(possible, 0.00001, maxChange);
    float3 change = diff / (1.0 / max(strength, 0.00001) + abs(diff) / possible);
    if ((flags & 1u) != 0u) change *= (1.0 - edgeRatio);
    return float4(EncodeColour(c + change), original.a);
}
)HLSL";
