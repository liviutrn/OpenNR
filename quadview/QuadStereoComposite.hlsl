// Joey QuadView same-eye native pairs: isolated full-eye composite pixel shader.
// Engine MUST first render LF/LP at identical left physical eye pose, and RF/RP
// at identical right physical eye pose. Do not warp an opposite-eye source.
// This shader does NOT create Unreal views, history owners or GPU transitions.
Texture2D<float4> LeftFovea    : register(t0);
Texture2D<float4> LeftPeriphery: register(t1);
Texture2D<float4> RightFovea   : register(t2);
Texture2D<float4> RightPeriphery:register(t3);
SamplerState LinearClamp       : register(s0);
cbuffer QuadStereoCompose : register(b0) {
    // Full physical-eye UV rectangle covered by the narrowed projection.
    float4 FoveaCrop; // u0,v0,u1,v1, top-down UV
    float FeatherUV; // 0 = exact crop step, otherwise UV edge softness
    uint PhysicalEye; // 0 left / 1 right, never inferred from draw phase
    float2 Reserved;
};
struct PSInput {
    float4 position : SV_POSITION;
    float2 uv : TEXCOORD0;
};
float4 main(PSInput input) : SV_Target0 {
    float2 uv = saturate(input.uv);
    float4 peripheral = PhysicalEye == 0
        ? LeftPeriphery.Sample(LinearClamp, uv)
        : RightPeriphery.Sample(LinearClamp, uv);

    // Guard invalid crop configuration at runtime: leave the full peripheral
    // source visible, never sample undefined fovea UV or stale opposite eye.
    float2 extent = FoveaCrop.zw - FoveaCrop.xy;
    if (any(extent <= float2(0.00001,0.00001)) ||
        any(FoveaCrop.xy < 0.0) || any(FoveaCrop.zw > 1.0) ||
        PhysicalEye > 1) return peripheral;

    float2 edgeLo = uv - FoveaCrop.xy;
    float2 edgeHi = FoveaCrop.zw - uv;
    float edge = min(min(edgeLo.x,edgeLo.y),min(edgeHi.x,edgeHi.y));
    if (edge <= 0.0) return peripheral;

    float weight = FeatherUV <= 0.0 ? 1.0 : saturate(edge / FeatherUV);
    float2 foveaUV = saturate((uv - FoveaCrop.xy) / extent);
    float4 fovea = PhysicalEye == 0
        ? LeftFovea.Sample(LinearClamp, foveaUV)
        : RightFovea.Sample(LinearClamp, foveaUV);
    return lerp(peripheral, fovea, weight);
}
