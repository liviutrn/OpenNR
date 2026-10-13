#pragma once
// Three independent, additive radius bands of Glamarye Intelligent Sharpen.
// Original equations: Robert Jessop, MIT; see LICENSE-GLAMARYE.txt.
// Small=original 0.5px; Big=original Bigger Sharpen 1.4px;
// Extra Big=experimental 2.5px radius (~1.79x Big, 5x Small).
// All enabled bands read the SAME source image in one shader pass,
// so no order-dependent re-sharpening / repeated texture copying.
static constexpr char kSharpenShader[] = R"HLSL(
cbuffer C : register(b0) {
    float2 imageSize;
    float smallStrength;
    float bigStrength;
    float extraStrength;
    float maxChange;
    float fxaaBias;
    float maximumColour;
    uint flags;     // bit0 edge protection; bit2 side-by-side; bit3 red test grid
    uint layer;
    uint colourMode; // 0=hardware sRGB/linear; 1=manual sRGB; 2=scRGB
};
Texture2DArray<float4> src : register(t0);
SamplerState linearClamp : register(s0);
static const float3 luma = float3(0.2126,0.7152,0.0722);
float3 DecodeColour(float3 c) {
    float3 low = c / 12.92;
    float3 high = pow(abs(c + 0.055) / 1.055, 2.4);
    float3 mask = float3(c.r > 0.04045 ? 1.0 : 0.0,
                         c.g > 0.04045 ? 1.0 : 0.0,
                         c.b > 0.04045 ? 1.0 : 0.0);
    float3 lin = lerp(low,high,mask);
    return (colourMode == 1u) ? lin :
           ((colourMode == 2u) ? c * (80.0 / 203.0) : c);
}
float3 EncodeColour(float3 c) {
    float3 low = c * 12.92;
    float3 high = 1.055 * pow(abs(c),1.0 / 2.4) - 0.055;
    float3 mask = float3(c.r > 0.0031308 ? 1.0 : 0.0,
                         c.g > 0.0031308 ? 1.0 : 0.0,
                         c.b > 0.0031308 ? 1.0 : 0.0);
    float3 encoded = lerp(low,high,mask);
    return (colourMode == 1u) ? encoded :
           ((colourMode == 2u) ? c * (203.0 / 80.0) : c);
}
struct VSOut { float4 pos : SV_Position; };
VSOut VSMain(uint id : SV_VertexID) {
    VSOut v;
    float2 uv = float2((id << 1) & 2,id & 2);
    v.pos = float4(uv * float2(2,-2) + float2(-1,1),0,1);
    return v;
}
float3 ReadAt(float2 uv, float2 offset) {
    float2 lo = 0.5 / imageSize;
    float2 hi = 1.0 - lo;
    if ((flags & 4u) != 0u) {
        float eyeBoundary = floor(imageSize.x*0.5);
        if (uv.x < eyeBoundary/imageSize.x)
            hi.x = (eyeBoundary-0.5)/imageSize.x;
        else
            lo.x = (eyeBoundary+0.5)/imageSize.x;
    }
    float2 p = clamp(uv + offset/imageSize,lo,hi);
    return DecodeColour(src.SampleLevel(linearClamp,float3(p,float(layer)),0).rgb);
}
// This function retains Glamarye's original diagonal detail extraction,
// luminance-based edge protection, and smoothly limited correction.
// radius 0.5 uses Glamarye's normal averaging; radius >=1.4 uses Bigger mode.
float3 SharpenScale(float2 uv, float3 c, float radius, float amount,
                    bool wide, float edgeDistance) {
    float3 ne = ReadAt(uv,float2( radius, radius));
    float3 sw = ReadAt(uv,float2(-radius,-radius));
    float3 se = ReadAt(uv,float2( radius,-radius));
    float3 nw = ReadAt(uv,float2(-radius, radius));
    float3 smoothed = (ne+nw)+(se+sw);
    if (wide)
        smoothed = clamp((smoothed+c)/5.0,c*0.5,c*2.0);
    else
        smoothed = clamp((smoothed-c)/3.0,c*0.5,c*2.0);
    smoothed = min(smoothed,maximumColour);
    float edgeRatio=0;
    if ((flags & 1u) != 0u) {
        float dy=dot(luma,abs((ne+nw)-(se+sw)));
        float dx=dot(luma,abs((ne+se)-(nw+sw)));
        bool horizontal=dy>dx;
        float3 n2=horizontal?ne+nw:ne+se;
        float3 s2=horizontal?se+sw:nw+sw;
        if (wide) {n2*=0.5;s2*=0.5;}
        else {n2-=c;s2-=c;}
        float2 west=horizontal?float2(-edgeDistance,0):float2(0,edgeDistance);
        float2 east=-west;
        float3 ww=ReadAt(uv,west);
        float3 ee=ReadAt(uv,east);
        float3 d1=abs((ww-n2)-(ee-s2));
        float3 d2=abs((ee-n2)-(ww-s2));
        float3 total=d1+d2+0.00004;
        float3 peak=max(d1,d2)+0.00001-fxaaBias*sqrt(max(smoothed,0.0));
        edgeRatio=max(2.0*dot(luma,peak/total)-1.0,0.0);
    }
    float3 diffRGB=2.0*c+(ne+nw+se+sw)
                  -3.0*(max(max(ne,nw),max(se,sw))
                         +min(min(ne,nw),min(se,sw)));
    float diff=dot(luma,diffRGB);
    float3 possible=min(smoothed,c*0.5);
    possible=min(possible,maximumColour-max(smoothed,c));
    possible=clamp(possible,0.00001,maxChange);
    float3 change=diff/(1.0/max(amount,0.00001)+abs(diff)/possible);
    if ((flags&1u)!=0u) change*=(1.0-edgeRatio);
    return change;
}
float4 PSMain(VSOut input) : SV_Target {
    float2 uv=input.pos.xy/imageSize;
    float4 original=src.SampleLevel(linearClamp,float3(uv,float(layer)),0);
    if ((flags&8u)!=0u &&
        (frac(uv.x*8.0)<0.12 || frac(uv.y*8.0)<0.12))
        return float4(1.0,0.01,0.05,original.a);
    if (smallStrength<=0.00001 && bigStrength<=0.00001 &&
        extraStrength<=0.00001)
        return original;
    float3 c=DecodeColour(original.rgb);
    float3 sum=0;
    if (smallStrength>0.00001)
        sum+=SharpenScale(uv,c,0.5,smallStrength,false,3.5);
    if (bigStrength>0.00001)
        sum+=SharpenScale(uv,c,1.4,bigStrength,true,3.5);
    if (extraStrength>0.00001)
        sum+=SharpenScale(uv,c,2.5,extraStrength,true,6.25);
    // Global safety limiter for three simultaneous sharpening bands.
    // For a single band this does not materially change the original formula.
    sum=clamp(sum,-maxChange,maxChange);
    return float4(EncodeColour(c+sum),original.a);
}
)HLSL";
