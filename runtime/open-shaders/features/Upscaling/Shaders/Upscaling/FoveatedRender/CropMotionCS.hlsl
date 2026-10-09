cbuffer CropMotion : register(b0)
{
	uint2 Extent;
	float2 OriginOffset;
	float2 MotionUVScale;
	float2 Padding;
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
	if (invalid) {
		Output[id.xy] = motion;
		return;
	}
	const float2 compensated = motion + OriginOffset;
	const float2 previousPosition = float2(id.xy) + 0.5 + compensated * MotionUVScale * float2(Extent);
	const float precisionPixels = 0.001;
	const bool insideHistory = all(isfinite(previousPosition)) &&
		all(previousPosition >= 0.5 - precisionPixels) &&
		all(previousPosition <= float2(Extent) - 0.5 + precisionPixels);
	// Reject outside the eye/atlas vertically without depending on an invalid-value convention.
	const float2 rejected = float2(0.0, 2.0 / MotionUVScale.y);
	Output[id.xy] = insideHistory ? compensated : rejected;
}
