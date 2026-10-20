// Fused fovea-only Glamarye Intelligent Sharpen for DuoView Mono v182.
// Adapted from Robert Jessop's Glamarye Fast Effects (MIT license), retaining
// the original four-diagonal detail, larger radius, FXAA-style edge guard
// and maximum-change limiter. This is used ONLY within the native compositor.
// No OpenXR hook, full-frame copy, extra command list, or extra shader pass.
//
// Every offset is in FINAL output pixels, AFTER game DLSS upscaling.
// NativeSampleUV clamps to the view's own extent; never sample its neighbor.
static const float3 kGlamLuma = float3(0.2126, 0.7152, 0.0722);

float3 GlamDecode(float3 c) {
    if ((SharpenFlags & 4u) == 0u) return c;
    float3 low = c / 12.92;
    float3 high = pow(abs(c + 0.055) / 1.055, 2.4);
    return lerp(low, high, float3(c.r > 0.04045, c.g > 0.04045, c.b > 0.04045));
}
float3 GlamEncode(float3 c) {
    if ((SharpenFlags & 4u) == 0u) return c;
    float3 low = c * 12.92;
    float3 high = 1.055 * pow(abs(c), 1.0 / 2.4) - 0.055;
    return lerp(low, high, float3(c.r > 0.0031308, c.g > 0.0031308, c.b > 0.0031308));
}
float3 GlamReadFovea(float2 fullUv, float2 pixelOffset) {
    float2 shifted = fullUv + pixelOffset / float2(OutputSize);
    float2 local = (shifted - CropUv.xy) / (CropUv.zw - CropUv.xy);
    float2 coords = NativeSampleUV(local, FoveaRect.zw, NativeFoveaDimensions);
    return GlamDecode(SourceAtlas.SampleLevel(LinearClamp, coords, 0.0).rgb);
}
float3 GlamSharpenNativeFovea(float2 fullUv, float3 center) {
    // Called only when SharpenStrength > 0 and the foveal view contributes.
    float3 c = GlamDecode(center);
    const bool bigger = (SharpenFlags & 2u) != 0u;
    float radius = bigger ? 1.4 : 0.5;
    float3 ne = GlamReadFovea(fullUv, float2( radius,  radius));
    float3 sw = GlamReadFovea(fullUv, float2(-radius, -radius));
    float3 se = GlamReadFovea(fullUv, float2( radius, -radius));
    float3 nw = GlamReadFovea(fullUv, float2(-radius,  radius));
    float3 smoothed = (ne + nw) + (se + sw);
    if (bigger) smoothed = clamp((smoothed + c) / 5.0, c * 0.5, c * 2.0);
    else smoothed = clamp((smoothed - c) / 3.0, c * 0.5, c * 2.0);
    smoothed = min(smoothed, 1.0);

    float edgeRatio = 0.0;
    if ((SharpenFlags & 1u) != 0u) {
        float dy = dot(kGlamLuma, abs((ne + nw) - (se + sw)));
        float dx = dot(kGlamLuma, abs((ne + se) - (nw + sw)));
        bool horizontal = dy > dx;
        float3 n2 = horizontal ? ne + nw : ne + se;
        float3 s2 = horizontal ? se + sw : nw + sw;
        if (bigger) { n2 *= 0.5; s2 *= 0.5; }
        else { n2 -= c; s2 -= c; }
        float2 west = horizontal ? float2(-3.5, 0.0) : float2(0.0, 3.5);
        float2 east = horizontal ? float2( 3.5, 0.0) : float2(0.0,-3.5);
        float3 ww = GlamReadFovea(fullUv, west);
        float3 ee = GlamReadFovea(fullUv, east);
        float3 d1 = abs((ww - n2) - (ee - s2));
        float3 d2 = abs((ee - n2) - (ww - s2));
        float3 totalDiff = d1 + d2 + 0.00004;
        float3 maxDiff = max(d1, d2) + 0.00001 - SharpenFXAABias * sqrt(max(smoothed, 0.0));
        edgeRatio = max(2.0 * dot(kGlamLuma, maxDiff / totalDiff) - 1.0, 0.0);
    }

    float3 diffRGB = 2.0 * c + (ne + nw + se + sw)
                   - 3.0 * (max(max(ne,nw),max(se,sw)) + min(min(ne,nw),min(se,sw)));
    float diff = dot(kGlamLuma, diffRGB);
    float3 possible = min(smoothed, c * 0.5);
    possible = min(possible, 1.0 - max(smoothed, c));
    possible = clamp(possible, 0.00001, SharpenMaxChange);
    float3 change = diff / (1.0 / max(SharpenStrength, 0.00001) + abs(diff) / possible);
    if ((SharpenFlags & 1u) != 0u) change *= (1.0 - edgeRatio);
    return GlamEncode(c + change);
}
