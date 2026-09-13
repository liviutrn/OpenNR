// Experimental adaptive-NR handoff.
//
// Feature 18 itself remains on a native, pre-created resolution tier. This
// pass only makes the visible handoff between the old displayed result and the
// new tier less abrupt. It is deliberately short-lived, motion-aware, and
// depth-gated; it is not a replacement for a proper per-frame temporal NR
// history.

cbuffer AdaptiveHandoffParams : register(b0)
{
	uint gColorWidth;
	uint gColorHeight;
	uint gGuideWidth;
	uint gGuideHeight;
	float gMotionScaleX;
	float gMotionScaleY;
	float gBlendAlpha;
	float gDepthThreshold;
	uint gHistoryValid;
	uint gUseDepth;
	uint gPadding0;
	uint gPadding1;
};

Texture2D<float4> gCurrent : register(t0);
Texture2D<float4> gPrevious : register(t1);
Texture2D<float> gCurrentDepth : register(t2);
Texture2D<float> gPreviousDepth : register(t3);
Texture2D<float2> gMotion : register(t4);
RWTexture2D<float4> gTarget : register(u0);
SamplerState gLinear : register(s0);

uint2 GuidePixel(float2 colorPixel)
{
	float2 guideSize = float2(max(gGuideWidth, 1u), max(gGuideHeight, 1u));
	float2 uv = (colorPixel + 0.5) / float2(max(gColorWidth, 1u), max(gColorHeight, 1u));
	return min(uint2(max(uv * guideSize, 0.0)), uint2(max(gGuideWidth, 1u) - 1u, max(gGuideHeight, 1u) - 1u));
}

float2 MotionPixels(uint2 colorPixel)
{
	const uint2 guidePixel = GuidePixel(float2(colorPixel));
	const float2 motion = gMotion.Load(int3(guidePixel, 0));
	const float2 guideToColor = float2(
		(float)gColorWidth / max((float)gGuideWidth, 1.0),
		(float)gColorHeight / max((float)gGuideHeight, 1.0));
	return motion * float2(gMotionScaleX, gMotionScaleY) * guideToColor;
}

bool InBounds(float2 pixel)
{
	return all(pixel >= 0.5) && pixel.x < (float)gColorWidth - 0.5 && pixel.y < (float)gColorHeight - 0.5;
}

[numthreads(8, 8, 1)]
void main(uint3 id : SV_DispatchThreadID)
{
	if (id.x >= gColorWidth || id.y >= gColorHeight)
		return;

	const uint2 pixel = id.xy;
	const float4 current = gCurrent.Load(int3(pixel, 0));
	const float2 motionPixels = MotionPixels(pixel);
	const float2 previousPosition = float2(pixel) + 0.5 + motionPixels;
	bool historyAccepted = gHistoryValid != 0 && gUseDepth != 0 &&
		all(isfinite(motionPixels)) && InBounds(previousPosition);

	if (historyAccepted && gUseDepth != 0)
	{
		const uint2 currentGuidePixel = GuidePixel(float2(pixel));
		const uint2 previousGuidePixel = GuidePixel(previousPosition - 0.5);
		const float currentDepth = gCurrentDepth.Load(int3(currentGuidePixel, 0));
		const float previousDepth = gPreviousDepth.Load(int3(previousGuidePixel, 0));
		const bool currentDepthValid = currentDepth > 0.00001;
		const bool previousDepthValid = previousDepth > 0.00001;
		historyAccepted = currentDepthValid && previousDepthValid &&
			isfinite(currentDepth) && isfinite(previousDepth);
		if (currentDepthValid && previousDepthValid)
		{
			const float depthScale = max(max(abs(currentDepth), abs(previousDepth)), 1.0);
			historyAccepted = abs(currentDepth - previousDepth) <= gDepthThreshold * depthScale;
		}
	}

	const float2 outputSize = float2(max(gColorWidth, 1u), max(gColorHeight, 1u));
	uint allocationWidth, allocationHeight;
	gPrevious.GetDimensions(allocationWidth, allocationHeight);
	const float2 safePosition = all(isfinite(previousPosition)) ? previousPosition : float2(pixel) + 0.5;
	float4 previous = gPrevious.SampleLevel(gLinear, safePosition / float2(allocationWidth, allocationHeight), 0);
	float3 lo = current.rgb;
	float3 hi = current.rgb;
	[unroll] for (int y = -1; y <= 1; ++y)
		[unroll] for (int x = -1; x <= 1; ++x) {
			int2 p = clamp(int2(pixel) + int2(x, y), int2(0, 0), int2(gColorWidth, gColorHeight) - 1);
			float3 sampleColor = gCurrent.Load(int3(p, 0)).rgb;
			lo = min(lo, sampleColor);
			hi = max(hi, sampleColor);
		}
	historyAccepted = historyAccepted && all(isfinite(previous));
	previous.rgb = clamp(previous.rgb, lo, hi);
	const float normalizedMotion = length(motionPixels / max(outputSize, 1.0));
	const float motionAlpha = saturate(normalizedMotion * 10.0);
	const float alpha = historyAccepted ? max(saturate(gBlendAlpha), saturate(length(motionPixels) / 8.0)) : 1.0;
	gTarget[pixel] = historyAccepted ? lerp(previous, current, alpha) : current;
}
