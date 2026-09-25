cbuffer CropMotion : register(b0)
{
	uint2 Extent;
	float2 OriginOffset;
};
Texture2D<float2> Source : register(t0);
RWTexture2D<float2> Output : register(u0);

[numthreads(8, 8, 1)]
void main(uint3 id : SV_DispatchThreadID)
{
	if (any(id.xy >= Extent))
		return;
	float2 motion = Source.Load(int3(id.xy, 0));
	bool invalid = any(!isfinite(motion)) || any(asuint(motion) == 0x00800000u);
	Output[id.xy] = invalid ? motion : motion + OriginOffset;
}
