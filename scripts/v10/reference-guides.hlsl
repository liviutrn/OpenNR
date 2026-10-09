cbuffer LadderAtlas : register(b0)
{
	uint4 gCurrent; // model width/height, guide width/height
	uint4 gPrevious; // model width/height, color width/height
	uint4 gLayout; // color width/height, color guard, previous color guard
	float4 gLeftOrigin;
	float4 gRightOrigin;
	float4 gMotionScale; // scene color pixels, native model pixels
	uint4 gFlags; // previous valid, guide guard, resident model height, padding
	float4 gModelPitch;
	float4 gLeftPhase;
	float4 gRightPhase;
};
Texture2D<float2> gLeftMotion : register(t0);
Texture2D<float2> gRightMotion : register(t1);
Texture2D<float> gLeftDepth : register(t2);
Texture2D<float> gRightDepth : register(t3);
RWTexture2D<float2> gMotion : register(u0);
RWTexture2D<float> gDepth : register(u1);

[numthreads(8,8,1)]
void main(uint3 id : SV_DispatchThreadID)
{
	const uint rightStart = gCurrent.z + gFlags.y;
	if (id.x >= rightStart + gCurrent.z || id.y >= gCurrent.w) return;
	const bool right = id.x >= rightStart;
	const uint x = right ? id.x - rightStart : min(id.x, gCurrent.z - 1);
	const float4 origin = right ? gRightOrigin : gLeftOrigin;
	const float4 phase = right ? gRightPhase : gLeftPhase;
	const float2 currentModel = (float2(x, id.y) + 0.5) * float2(gCurrent.xy) / float2(gCurrent.zw);
	const float2 currentColor = currentModel * gModelPitch.xy + phase.xy;
	const uint2 pixel = uint2(clamp(currentColor * float2(gCurrent.zw) / float2(gLayout.xy),
		0.0.xx, float2(gCurrent.zw) - 1.0));
	const float2 raw = right ? gRightMotion.Load(int3(pixel,0)) : gLeftMotion.Load(int3(pixel,0));
	gDepth[id.xy] = right ? gRightDepth.Load(int3(pixel,0)) : gLeftDepth.Load(int3(pixel,0));
	const float2 previousColor = currentColor + origin.xy - origin.zw + raw * gMotionScale.xy;
	const float2 previousModel = (previousColor - phase.zw) / max(gModelPitch.zw, 1e-6);

	const bool sourceValid = all(isfinite(raw)) && !any(asuint(raw) == 0x00800000u);
	const bool valid = gFlags.x != 0 && sourceValid &&
		all(previousModel >= 0.5 - 0.001) && all(previousModel <= float2(gPrevious.xy) - 0.5 + 0.001);
	const bool sameLayout = all(gCurrent.xy == gPrevious.xy) && all(gLayout.xy == gPrevious.zw) && all(gModelPitch.xy == gModelPitch.zw);
	float2 delta = sameLayout ? (origin.xy - origin.zw + phase.xy - phase.zw +
		raw * gMotionScale.xy) / gModelPitch.xy : previousModel - currentModel;
	if (right) delta.x += float(gPrevious.x + gLayout.w) - float(gCurrent.x + gLayout.z);
	const float2 rejection = float2(0.0, 2.0 * gFlags.z / gMotionScale.w);
	const bool unchanged = sameLayout && all(origin.xy == origin.zw) && all(phase.xy == phase.zw) &&
		all(abs(gMotionScale.xy / gModelPitch.xy - gMotionScale.zw) <= 1e-5 * abs(gMotionScale.zw)) &&
		(!right || gLayout.z == gLayout.w);
	gMotion[id.xy] = !sourceValid ? raw : valid ? (unchanged ? raw : delta / gMotionScale.zw) : rejection;
}

