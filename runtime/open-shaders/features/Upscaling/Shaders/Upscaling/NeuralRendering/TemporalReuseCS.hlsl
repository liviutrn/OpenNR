// Experimental OpenNR temporal residual reuse.
//
// This pass deliberately consumes the same game motion-vector texture and
// Feature 18 scale that the native path receives. It does not estimate motion
// from color, use optical flow, or update the native Feature 18 history while a
// frame is skipped. A full Feature 18 frame stores:
//   residual = teacher - input
// and an intervening frame evaluates:
//   output = current_input + reproject(previous_residual, accumulated_MV)
//
// The accumulated vector follows the current-to-previous convention used by
// the OpenNR guide contract: current pixel p maps to the previous frame at
// p + MV. The C++ caller gates this shader to single-pass, stable-layout
// full-eye or crop-local resources and invalidates its history on reset or
// route/crop changes. A moving crop is not transformed here yet.

cbuffer TemporalReuseParams : register(b0)
{
	uint gColorWidth;
	uint gColorHeight;
	uint gGuideWidth;
	uint gGuideHeight;
	float gMotionScaleX;
	float gMotionScaleY;
	float gDepthThreshold;
	float gColorTolerance;
	uint gUseDepth;
	uint gUseColor;
	uint gPadding0;
	uint gPadding1;
};

Texture2D<float4> gColor0 : register(t0);
Texture2D<float4> gColor1 : register(t1);
Texture2D<float> gDepth0 : register(t2);
Texture2D<float4> gPreviousBase : register(t3);
Texture2D<float> gPreviousDepth : register(t4);
Texture2D<float4> gPreviousResidual : register(t5);
Texture2D<float2> gCurrentMotion : register(t6);
Texture2D<float2> gPreviousAccumulatedMotion : register(t7);

RWTexture2D<float4> gBaseTarget : register(u0);
RWTexture2D<float4> gResidualTarget : register(u1);
RWTexture2D<float2> gAccumulatedMotionTarget : register(u2);
RWTexture2D<float4> gOutput : register(u3);

SamplerState gLinear : register(s0);

static const float3 kLuma = float3(0.2126, 0.7152, 0.0722);

bool IsBoundedMotion(float2 motion, float2 limit)
{
	// The equality check rejects NaNs without depending on an optional shader
	// model intrinsic. A camera cut, invalid guide, or out-of-range chain must
	// fail closed instead of being clamped to a valid-looking edge sample.
	return all(motion == motion) && all(abs(motion) <= limit);
}

uint2 GuidePixel(float2 colorPosition)
{
	const float2 colorSize = float2(max(gColorWidth, 1u), max(gColorHeight, 1u));
	const uint2 guideLast = uint2(max(gGuideWidth, 1u) - 1u, max(gGuideHeight, 1u) - 1u);
	return min(uint2(max(colorPosition + 0.5, 0.0.xx) * float2(gGuideWidth, gGuideHeight) / colorSize), guideLast);
}

float2 ColorUV(float2 colorPosition)
{
	return (colorPosition + 0.5) / float2(max(gColorWidth, 1u), max(gColorHeight, 1u));
}

[numthreads(8, 8, 1)]
void Snapshot(uint3 dispatchThreadID : SV_DispatchThreadID)
{
	if (dispatchThreadID.x >= gColorWidth || dispatchThreadID.y >= gColorHeight)
		return;

	const uint2 pixel = dispatchThreadID.xy;
	const float4 inputColor = gColor0.Load(int3(pixel, 0));
	const float4 teacherColor = gColor1.Load(int3(pixel, 0));
	gBaseTarget[pixel] = inputColor;
	gResidualTarget[pixel] = float4(teacherColor.rgb - inputColor.rgb, 0.0);
}

[numthreads(8, 8, 1)]
void Accumulate(uint3 dispatchThreadID : SV_DispatchThreadID)
{
	if (dispatchThreadID.x >= gColorWidth || dispatchThreadID.y >= gColorHeight)
		return;

	const uint2 pixel = dispatchThreadID.xy;
	// Use a nearest guide lookup for the current vector. Interpolating the
	// source MV field here would no longer be an exact resource-bound sample.
	const uint2 motionPixel = GuidePixel(float2(pixel));
	const float2 currentMotion = gCurrentMotion.Load(int3(motionPixel, 0)) * float2(gMotionScaleX, gMotionScaleY);
	const float2 colorLimit = float2(gColorWidth, gColorHeight);
	const float2 previousPosition = float2(pixel) + 0.5 + currentMotion;
	const bool currentStepInBounds = IsBoundedMotion(currentMotion, colorLimit) &&
		all(previousPosition >= 0.5.xx) && all(previousPosition <= colorLimit - 0.5);
	if (!currentStepInBounds)
	{
		gAccumulatedMotionTarget[pixel] = colorLimit * 2.0;
		return;
	}
	const float2 previousUV = previousPosition / float2(max(gColorWidth, 1u), max(gColorHeight, 1u));
	const float2 previousAccumulated = gPreviousAccumulatedMotion.SampleLevel(gLinear, previousUV, 0);
	if (!IsBoundedMotion(previousAccumulated, colorLimit))
	{
		gAccumulatedMotionTarget[pixel] = colorLimit * 2.0;
		return;
	}
	const float2 accumulated = currentMotion + previousAccumulated;
	gAccumulatedMotionTarget[pixel] = IsBoundedMotion(accumulated, colorLimit) ? accumulated : colorLimit * 2.0;
}

[numthreads(8, 8, 1)]
void Reproject(uint3 dispatchThreadID : SV_DispatchThreadID)
{
	if (dispatchThreadID.x >= gColorWidth || dispatchThreadID.y >= gColorHeight)
		return;

	const uint2 pixel = dispatchThreadID.xy;
	const float2 currentPosition = float2(pixel);
	const float2 accumulatedMotion = gPreviousAccumulatedMotion.Load(int3(pixel, 0));
	const float2 previousPosition = currentPosition + accumulatedMotion;
	const float2 colorLast = float2(gColorWidth, gColorHeight) - 1.0;
	const float2 colorLimit = float2(gColorWidth, gColorHeight);
	const bool inBounds = IsBoundedMotion(accumulatedMotion, colorLimit) &&
		all(previousPosition >= 0.0.xx) && all(previousPosition <= colorLast);

	const float4 currentColor = gColor0.Load(int3(pixel, 0));
	bool accepted = inBounds;
	if (accepted && gUseDepth != 0u)
	{
		const float currentDepth = gDepth0.Load(int3(GuidePixel(currentPosition), 0));
		const float previousDepth = gPreviousDepth.Load(int3(GuidePixel(previousPosition), 0));
		const bool validDepth = abs(currentDepth) > 1e-6 && abs(previousDepth) > 1e-6;
		const float depthScale = max(max(abs(currentDepth), abs(previousDepth)), 1.0);
		accepted = validDepth && abs(currentDepth - previousDepth) <= max(gDepthThreshold, 0.0) * depthScale;
	}
	if (accepted && gUseColor != 0u)
	{
		const float3 previousBase = gPreviousBase.SampleLevel(gLinear, ColorUV(previousPosition), 0).rgb;
		const float currentLuma = dot(currentColor.rgb, kLuma);
		const float previousLuma = dot(previousBase, kLuma);
		const float lumaScale = max(max(abs(currentLuma), abs(previousLuma)), 0.05);
		accepted = abs(currentLuma - previousLuma) / lumaScale <= max(gColorTolerance, 0.0);
	}

	float3 result = currentColor.rgb;
	if (accepted)
		result += gPreviousResidual.SampleLevel(gLinear, ColorUV(previousPosition), 0).rgb;
	gOutput[pixel] = float4(max(result, 0.0.xxx), currentColor.a);
}
