cbuffer GuideAlignment : register(b0)
{
	uint2 gExtent;
	uint2 gSourceOffset;
	float2 gScale;
	float2 gOffset;
};
Texture2D<float> gSourceDepth : register(t0);
Texture2D<float2> gSourceMotion : register(t1);
RWTexture2D<float> gDepth : register(u0);
RWTexture2D<float2> gMotion : register(u1);

[numthreads(8, 8, 1)]
void main(uint3 id : SV_DispatchThreadID)
{
	if (any(id.xy >= gExtent)) return;
	const float2 position = clamp((float2(id.xy) + 0.5) * gScale + gOffset,
		0.5.xx, float2(gExtent) - 0.5);
	const uint2 source = uint2(position) + gSourceOffset;
	gDepth[id.xy] = gSourceDepth.Load(int3(source, 0));
	gMotion[id.xy] = gSourceMotion.Load(int3(source, 0));
}
