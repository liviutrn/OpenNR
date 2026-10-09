cbuffer ResultShapingParams : register(b0)
{
	uint gColorWidth;
	uint gColorHeight;
	uint gGuideWidth;
	uint gGuideHeight;
	float gMotionScaleX;
	float gMotionScaleY;
	float gFrameDeltaSeconds;
	float gStabilizeTimeMs;
	float gEditStrength;
	float gBrightening;
	float gDarkening;
	float gColorStrength;
	float gHueShiftStrength;
	float gShadows;
	float gMidtones;
	float gHighlights;
	float gLargeScaleTone;
	float gFineDetail;
	float gDetailRadius;
	float gHaloSuppression;
	float gMaxBrighteningStops;
	float gMaxDarkeningStops;
	float gMaxColorChangeStops;
	float gDepthThreshold;
	float gColorTolerance;
	uint gShapeEnabled;
	uint gStabilizeMode;
	uint gStabilizeDetail;
	float gHistoryEdgeFadePixels;
	float gTransitionWeightScale;
	float gNearBlackProtection;
	float gNearBlackThreshold;
	uint4 gPreviousLayout;
	float2 gOriginDelta;
	float gNearBlackLiftSoftness;
	float gResumeBlendAlpha;
};

Texture2D<float4> gInput : register(t0);
Texture2D<float4> gNRResult : register(t1);
Texture2D<float> gDepth : register(t2);
Texture2D<float2> gMotionVectors : register(t3);
Texture2D<float4> gPreviousResult : register(t4);
Texture2D<float4> gPreviousInput : register(t5);
Texture2D<float> gPreviousDepth : register(t6);

RWTexture2D<float4> gOutput : register(u0);
// Stabilized but unshaped result (input + stabilized NR delta). It is the next
// frame's gPreviousResult, so stabilization always runs in the raw NR domain and
// result shaping is applied afterwards; the two filters never mix domains.
RWTexture2D<float4> gHistoryOutput : register(u1);
SamplerState gLinearClamp : register(s0);

static const float3 kLuma = float3(0.2126, 0.7152, 0.0722);
static const float3 kChromaAxisA = float3(0.8760923, -0.2169604, -0.4305700);
static const float3 kChromaAxisB = float3(-0.3899056, 0.2064967, -0.8974033);

float2 ChromaCoordinates(float3 color)
{
	const float3 chroma = color - dot(color, kLuma).xxx;
	return float2(dot(chroma, kChromaAxisA), dot(chroma, kChromaAxisB));
}

float2 ColorUV(float2 pixel)
{
	uint width, height;
	gInput.GetDimensions(width, height);
	return clamp(pixel + 0.5, 0.5, float2(gColorWidth, gColorHeight) - 0.5) / float2(width, height);
}


float2 PreviousUV(float2 position)
{
	uint width, height;
	gPreviousInput.GetDimensions(width, height);
	return position / float2(width, height);
}
uint2 PreviousGuidePixel(float2 position)
{
	return min(uint2(max(position, 0.0) * float2(gPreviousLayout.zw) / max(float2(gPreviousLayout.xy), 1.0)),
		max(gPreviousLayout.zw, 1u) - 1u);
}

uint2 GuidePixel(float2 colorPosition)
{
	const float2 colorSize = float2(max(gColorWidth, 1u), max(gColorHeight, 1u));
	const uint2 guideLast = uint2(max(gGuideWidth, 1u) - 1u, max(gGuideHeight, 1u) - 1u);
	return min(uint2(max(colorPosition + 0.5, 0.0.xx) * float2(gGuideWidth, gGuideHeight) / colorSize), guideLast);
}

float3 CurrentDeltaAt(float2 pixel)
{
	const float2 uv = ColorUV(pixel);
	return gNRResult.SampleLevel(gLinearClamp, uv, 0).rgb - gInput.SampleLevel(gLinearClamp, uv, 0).rgb;
}

float3 PreviousDeltaAt(float2 uv)
{
	uint width, height;
	gPreviousInput.GetDimensions(width, height);
	uv = clamp(uv * float2(width, height), 0.5, float2(gPreviousLayout.xy) - 0.5) / float2(width, height);
	return gPreviousResult.SampleLevel(gLinearClamp, uv, 0).rgb -
		gPreviousInput.SampleLevel(gLinearClamp, uv, 0).rgb;
}

float3 CurrentLowFrequencyDelta(float2 pixel)
{
	const float radiusPixels = max(gDetailRadius, 0.1) * 0.01 * max(gColorHeight, 1u);
	return (CurrentDeltaAt(pixel) * 4.0 + CurrentDeltaAt(pixel + float2(radiusPixels,0)) +
		CurrentDeltaAt(pixel - float2(radiusPixels,0)) + CurrentDeltaAt(pixel + float2(0,radiusPixels)) +
		CurrentDeltaAt(pixel - float2(0,radiusPixels))) / 8.0;
}

float SoftCeiling(float value, float ceiling)
{
	if (value <= ceiling)
		return value;
	const float softness = max(abs(ceiling) * 0.1, 1e-6);
	return ceiling + softness * (1.0 - exp(-(value - ceiling) / softness));
}

float SoftFloor(float value, float floorValue)
{
	if (value >= floorValue)
		return value;
	const float softness = max(abs(floorValue) * 0.1, 1e-6);
	return floorValue - softness * (1.0 - exp(-(floorValue - value) / softness));
}

float3 PreviousLowFrequencyDelta(float2 uv)
{
	const float radiusPixels = max(gDetailRadius, 0.1) * 0.01 * max(gColorHeight, 1u);
	uint resourceWidth, resourceHeight;
	gInput.GetDimensions(resourceWidth, resourceHeight);
	const float2 offset = radiusPixels / float2(resourceWidth, resourceHeight);
	const float3 center = PreviousDeltaAt(uv);
	return (center * 4.0 +
		PreviousDeltaAt(uv + float2(offset.x, 0.0)) +
		PreviousDeltaAt(uv - float2(offset.x, 0.0)) +
		PreviousDeltaAt(uv + float2(0.0, offset.y)) +
		PreviousDeltaAt(uv - float2(0.0, offset.y))) / 8.0;
}

// lowFrequencyDelta must describe the same (possibly stabilized) delta that is passed in.
float3 ShapeDelta(float2 pixel, float3 baseColor, float3 delta, float3 lowFrequencyDelta)
{
	delta *= gEditStrength;
	if (gLargeScaleTone != 1.0 || gFineDetail != 1.0)
	{
		const float3 lowFrequency = lowFrequencyDelta * gEditStrength;
		delta = lowFrequency * gLargeScaleTone + (delta - lowFrequency) * gFineDetail;
	}

	const float baseLuma = max(dot(baseColor, kLuma), 0.0);
	const float normalizedLuma = saturate(baseLuma);
	const float shadowWeight = 1.0 - smoothstep(0.10, 0.42, normalizedLuma);
	const float highlightWeight = smoothstep(0.58, 0.90, normalizedLuma);
	const float midtoneWeight = saturate(1.0 - shadowWeight - highlightWeight);
	const float tonalWeight = shadowWeight * gShadows + midtoneWeight * gMidtones + highlightWeight * gHighlights;

	float lumaDelta = dot(delta, kLuma) * tonalWeight;
	lumaDelta *= lumaDelta >= 0.0 ? gBrightening : gDarkening;
	if (gMaxBrighteningStops > 0.0)
		lumaDelta = SoftCeiling(lumaDelta, max(baseLuma, 1e-4) * (exp2(gMaxBrighteningStops) - 1.0));
	if (gMaxDarkeningStops > 0.0)
		lumaDelta = SoftFloor(lumaDelta, -baseLuma * (1.0 - exp2(-gMaxDarkeningStops)));

	const float2 baseChroma = ChromaCoordinates(baseColor);
	const float2 modelChroma = ChromaCoordinates(baseColor + delta);
	const float2 scaledChroma = baseChroma + (modelChroma - baseChroma) * gColorStrength;
	float2 shapedChroma = scaledChroma;
	if (length(baseChroma) > 1e-5 && length(scaledChroma) > 1e-5 && gHueShiftStrength != 1.0)
	{
		const float baseHue = atan2(baseChroma.y, baseChroma.x);
		const float scaledHue = atan2(scaledChroma.y, scaledChroma.x);
		const float hueDelta = atan2(sin(scaledHue - baseHue), cos(scaledHue - baseHue));
		const float shapedHue = baseHue + hueDelta * gHueShiftStrength;
		shapedChroma = length(scaledChroma) * float2(cos(shapedHue), sin(shapedHue));
	}
	float2 chromaChange = shapedChroma - baseChroma;
	if (gMaxColorChangeStops > 0.0)
	{
		const float chromaLength = length(chromaChange);
		const float maxChroma = max(baseLuma, 1e-4) * (exp2(gMaxColorChangeStops) - 1.0);
		if (chromaLength > maxChroma) {
			const float softness = max(maxChroma * 0.1, 1e-6);
			const float limitedLength = maxChroma + softness *
				(1.0 - exp(-(chromaLength - maxChroma) / softness));
			chromaChange *= limitedLength / max(chromaLength, 1e-6);
		}
	}

	if (gHaloSuppression > 0.0)
	{
		const int2 center = int2(pixel);
		const int2 last = int2(gColorWidth, gColorHeight) - 1;
		float localMin = baseLuma;
		float localMax = baseLuma;
		[unroll]
		for (int y = -1; y <= 1; ++y)
		{
			[unroll]
			for (int x = -1; x <= 1; ++x)
			{
				const int2 samplePixel = clamp(center + int2(x, y), int2(0, 0), last);
				const float sampleLuma = dot(gInput.Load(int3(samplePixel, 0)).rgb, kLuma);
				localMin = min(localMin, sampleLuma);
				localMax = max(localMax, sampleLuma);
			}
		}
		const float margin = max((localMax - localMin) * 0.10, 0.005);
		const float proposedLuma = baseLuma + lumaDelta;
		const float limitedLuma = clamp(proposedLuma, localMin - margin, localMax + margin);
		lumaDelta = lerp(lumaDelta, limitedLuma - baseLuma, saturate(gHaloSuppression));
	}

	const float3 chromaDelta = kChromaAxisA * chromaChange.x + kChromaAxisB * chromaChange.y;
	return lumaDelta.xxx + chromaDelta;
}

bool IsFiniteMotion(float2 motion)
{
	return all(isfinite(motion)) && !any(asuint(motion) == 0x00800000u);
}

float HistoryEdgeWeight(float2 previousPosition)
{
	if (gHistoryEdgeFadePixels <= 0.0)
		return 1.0;
	const float2 edgeDistance = min(previousPosition - 0.5,
		float2(gPreviousLayout.xy) - 0.5 - previousPosition);
	return saturate(min(edgeDistance.x, edgeDistance.y) / gHistoryEdgeFadePixels);
}

bool IsHistoryValid(float2 pixel, float2 previousPosition, float3 baseColor)
{
	const float2 colorLimit = float2(gPreviousLayout.xy);
	if (!all(previousPosition >= 0.5.xx) || !all(previousPosition <= colorLimit - 0.5))
		return false;

	const float currentDepth = gDepth.Load(int3(GuidePixel(pixel), 0));
	const float previousDepth = gPreviousDepth.Load(int3(PreviousGuidePixel(previousPosition), 0));
	if (!(abs(currentDepth) > 1e-6) || !(abs(previousDepth) > 1e-6) ||
		!(abs(currentDepth) < 1e20) || !(abs(previousDepth) < 1e20))
		return false;
	const float depthScale = max(max(abs(currentDepth), abs(previousDepth)), 1.0);
	if (abs(currentDepth - previousDepth) > gDepthThreshold * depthScale)
		return false;

	const float previousLuma = dot(gPreviousInput.SampleLevel(gLinearClamp, PreviousUV(previousPosition), 0).rgb, kLuma);
	const float currentLuma = dot(baseColor, kLuma);
	const float colorScale = max(max(abs(currentLuma), abs(previousLuma)), 0.05);
	return abs(currentLuma - previousLuma) / colorScale <= gColorTolerance;
}

[numthreads(8, 8, 1)]
void main(uint3 dispatchThreadID : SV_DispatchThreadID)
{
	if (dispatchThreadID.x >= gColorWidth || dispatchThreadID.y >= gColorHeight)
		return;

	const uint2 pixel = dispatchThreadID.xy;
	const float2 pixelPosition = float2(pixel);
	const float4 baseColor = gInput.Load(int3(pixel, 0));
	const float4 nrColor = gNRResult.Load(int3(pixel, 0));
	const float3 rawDelta = nrColor.rgb - baseColor.rgb;
	float3 delta = rawDelta;
	const bool shapeNeedsLowFrequency = gShapeEnabled != 0u && (gLargeScaleTone != 1.0 || gFineDetail != 1.0);
	const bool stabilizeNeedsLowFrequency = gStabilizeMode != 0u && gStabilizeDetail == 0u;
	float3 lowFrequency = (shapeNeedsLowFrequency || stabilizeNeedsLowFrequency) ?
		CurrentLowFrequencyDelta(pixelPosition) : float3(0.0, 0.0, 0.0);

	if (gStabilizeMode != 0u)
	{
		float2 previousPosition = pixelPosition + 0.5;
		bool motionValid = true;
		if (gStabilizeMode == 2u)
		{
			const float2 rawMotion = gMotionVectors.Load(int3(GuidePixel(pixelPosition), 0));
			const float2 motion = rawMotion * float2(gMotionScaleX, gMotionScaleY);
			motionValid = IsFiniteMotion(rawMotion) && all(isfinite(motion));
			previousPosition += motion + gOriginDelta;
		}

		if (motionValid && IsHistoryValid(pixelPosition, previousPosition, baseColor.rgb))
		{
			const float2 previousUV = PreviousUV(previousPosition);
			const float3 previousDelta = PreviousDeltaAt(previousUV);
			const float historyWeight = gTransitionWeightScale * HistoryEdgeWeight(previousPosition) * exp(-max(gFrameDeltaSeconds, 1.0 / 240.0) /
				max(gStabilizeTimeMs * 0.001, 0.001));
			if (gStabilizeDetail != 0u)
			{
				delta = lerp(rawDelta, previousDelta, historyWeight);
				if (shapeNeedsLowFrequency)
					lowFrequency = lerp(lowFrequency, PreviousLowFrequencyDelta(previousUV), historyWeight);
			}
			else
			{
				const float3 stabilizedLowFrequency = lerp(lowFrequency,
					PreviousLowFrequencyDelta(previousUV), historyWeight);
				delta = stabilizedLowFrequency + (rawDelta - lowFrequency);
				lowFrequency = stabilizedLowFrequency;
			}
		}
	}

	float3 stabilized = baseColor.rgb + delta;
	if (!all(stabilized == stabilized) || !all(abs(stabilized) < float3(1e20, 1e20, 1e20)))
		stabilized = nrColor.rgb;
	gHistoryOutput[pixel] = float4(max(stabilized, 0.0.xxx), nrColor.a);

	if (gShapeEnabled != 0u)
		delta = ShapeDelta(pixelPosition, baseColor.rgb, delta, lowFrequency);

	if (gNearBlackProtection > 0.0 && dot(delta, kLuma) > 0.0) {
		const float peak = max(max(baseColor.r, baseColor.g), max(baseColor.b, 0.0));
		const float positiveWeight = smoothstep(0.0, gNearBlackLiftSoftness, dot(delta, kLuma));
		const float attenuation = saturate(gNearBlackProtection * (1.0 - smoothstep(0.0, gNearBlackThreshold, peak)) * positiveWeight);
		delta *= 1.0 - attenuation;
	}

	float3 result = baseColor.rgb + delta * saturate(gResumeBlendAlpha);
	if (!all(result == result) || !all(abs(result) < float3(1e20, 1e20, 1e20)))
		result = nrColor.rgb;
	gOutput[pixel] = float4(max(result, 0.0.xxx), nrColor.a);
}
