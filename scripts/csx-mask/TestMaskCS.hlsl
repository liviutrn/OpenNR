#include "Common/ShaderDetailFoveation.hlsli"
cbuffer Samples : register(b0) { float4 samples[16]; };
RWTexture2D<float4> Results : register(u0);
[numthreads(16,1,1)]
void main(uint3 tid : SV_DispatchThreadID)
{
 float4 maskSample = samples[tid.x];
 Results[tid.xy] = GetShaderDetailFoveationWeight(SharedData::VRDetailFoveationModes.x, maskSample.xy, (uint)maskSample.z);
}
