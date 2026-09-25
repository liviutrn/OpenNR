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
// route/crop changes. Crop-motion compensation is applied before these passes.

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

bool DepthMatches(float currentDepth, float previousDepth)
{
	if (currentDepth != currentDepth || previousDepth != previousDepth ||
		abs(currentDepth) <= 1e-6 || abs(previousDepth) <= 1e-6)
		return false;
	const float depthScale = max(max(abs(currentDepth), abs(previousDepth)), 1e-5);
	return abs(currentDepth - previousDepth) <= max(gDepthThreshold, 0.0) * depthScale;
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
	// Invalid vectors use a sentinel. A point load prevents filtering the
	// sentinel into a plausible displacement at a surface or crop boundary.
	const uint2 previousPixel = min(uint2(floor(previousPosition)),
		uint2(gColorWidth - 1u, gColorHeight - 1u));
	const float2 previousAccumulated = gPreviousAccumulatedMotion.Load(int3(previousPixel, 0));
	if (!IsBoundedMotion(previousAccumulated, colorLimit))
	{
		gAccumulatedMotionTarget[pixel] = colorLimit * 2.0;
		return;
	}
	const float2 accumulated = currentMotion + previousAccumulated;
	gAccumulatedMotionTarget[pixel] = IsBoundedMotion(accumulated, colorLimit) ? accumulated : colorLimit * 2.0;
}

// Feature 18 consumes a guide-sized motion resource. Pack the accumulated
// color-pixel displacement into its active guide region before the next anchor.
[numthreads(8, 8, 1)]
void PackNativeMotion(uint3 dispatchThreadID : SV_DispatchThreadID)
{
	if (dispatchThreadID.x >= gGuideWidth || dispatchThreadID.y >= gGuideHeight)
		return;

	const uint2 guidePixel = dispatchThreadID.xy;
	const uint2 colorSize = uint2(max(gColorWidth, 1u), max(gColorHeight, 1u));
	const uint2 guideSize = uint2(max(gGuideWidth, 1u), max(gGuideHeight, 1u));
	const uint2 colorPixel = min(uint2((float2(guidePixel) + 0.5) * float2(colorSize) / float2(guideSize)), colorSize - 1u);
	const float2 motion = gPreviousAccumulatedMotion.Load(int3(colorPixel, 0));
	gAccumulatedMotionTarget[guidePixel] = IsBoundedMotion(motion, float2(colorSize)) ? motion : 0.0.xx;
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
	float3 result = currentColor.rgb;
	if (accepted)
	{
		const uint2 first = uint2(floor(previousPosition));
		const uint2 last = uint2(gColorWidth - 1u, gColorHeight - 1u);
		const float2 fraction = frac(previousPosition);
		const float currentDepth = gUseDepth != 0u ?
			gDepth0.Load(int3(GuidePixel(currentPosition), 0)) : 0.0;
		const float currentLuma = dot(currentColor.rgb, kLuma);
		const float tolerance = max(gColorTolerance, 0.0);
		float3 residual = 0.0;
		float totalWeight = 0.0;
		[unroll]
		for (uint tapY = 0; tapY < 2; ++tapY) {
			[unroll]
			for (uint tapX = 0; tapX < 2; ++tapX) {
				const uint2 tap = min(first + uint2(tapX, tapY), last);
				const float2 axisWeight = float2(tapX ? fraction.x : 1.0 - fraction.x,
					tapY ? fraction.y : 1.0 - fraction.y);
				float weight = axisWeight.x * axisWeight.y;
				if (weight <= 0.0)
					continue;
				if (gUseDepth != 0u) {
					const float previousDepth = gPreviousDepth.Load(int3(GuidePixel(float2(tap)), 0));
					if (!DepthMatches(currentDepth, previousDepth))
						continue;
				}
				const float4 previousBase = gPreviousBase.Load(int3(tap, 0));
				if (gUseColor != 0u) {
					const float previousLuma = dot(previousBase.rgb, kLuma);
					const float lumaScale = max(max(abs(currentLuma), abs(previousLuma)), 0.05);
					const float relativeLumaError = abs(currentLuma - previousLuma) / lumaScale;
					weight *= tolerance > 1e-5 ?
						1.0 - smoothstep(tolerance * 0.65, tolerance, relativeLumaError) :
						(relativeLumaError <= tolerance ? 1.0 : 0.0);
				}
				residual += gPreviousResidual.Load(int3(tap, 0)).rgb * weight;
				totalWeight += weight;
			}
		}
		if (totalWeight > 1e-5) {
			residual /= totalWeight;
			const float residualLuma = dot(residual, kLuma);
			const float maxLumaDelta = max(abs(currentLuma) * 0.35, 0.015);
			if (abs(residualLuma) > maxLumaDelta)
				residual *= maxLumaDelta / abs(residualLuma);
			const float maxChannelDelta = max(abs(currentLuma) * 0.75, 0.04);
			const float maxChannel = max(abs(residual.x), max(abs(residual.y), abs(residual.z)));
			if (maxChannel > maxChannelDelta)
				residual *= maxChannelDelta / maxChannel;
			result += residual;
		}
	}
	gOutput[pixel] = float4(max(result, 0.0.xxx), currentColor.a);
}
