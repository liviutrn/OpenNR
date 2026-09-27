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
	return (pixel + 0.5) / float2(max(gColorWidth, 1u), max(gColorHeight, 1u));
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
	return gPreviousResult.SampleLevel(gLinearClamp, uv, 0).rgb -
		gPreviousInput.SampleLevel(gLinearClamp, uv, 0).rgb;
}

float3 CurrentLowFrequencyDelta(float2 pixel)
{
	const float radiusPixels = max(gDetailRadius, 0.1) * 0.01 * max(gColorHeight, 1u);
	const float2 offset = radiusPixels / float2(max(gColorWidth, 1u), max(gColorHeight, 1u));
	const float3 center = CurrentDeltaAt(pixel);
	const float2 uv = ColorUV(pixel);
	const float3 horizontal =
		gNRResult.SampleLevel(gLinearClamp, uv + float2(offset.x, 0.0), 0).rgb -
		gInput.SampleLevel(gLinearClamp, uv + float2(offset.x, 0.0), 0).rgb +
		gNRResult.SampleLevel(gLinearClamp, uv - float2(offset.x, 0.0), 0).rgb -
		gInput.SampleLevel(gLinearClamp, uv - float2(offset.x, 0.0), 0).rgb;
	const float3 vertical =
		gNRResult.SampleLevel(gLinearClamp, uv + float2(0.0, offset.y), 0).rgb -
		gInput.SampleLevel(gLinearClamp, uv + float2(0.0, offset.y), 0).rgb +
		gNRResult.SampleLevel(gLinearClamp, uv - float2(0.0, offset.y), 0).rgb -
		gInput.SampleLevel(gLinearClamp, uv - float2(0.0, offset.y), 0).rgb;
	return (center * 4.0 + horizontal + vertical) / 8.0;
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
	const float2 offset = radiusPixels / float2(max(gColorWidth, 1u), max(gColorHeight, 1u));
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

bool IsBoundedMotion(float2 motion, float2 limit)
{
	return all(motion == motion) && all(abs(motion) <= limit);
}

bool IsHistoryValid(float2 pixel, float2 previousPosition, float3 baseColor)
{
	const float2 colorLimit = float2(gColorWidth, gColorHeight);
	if (!all(previousPosition >= 0.5.xx) || !all(previousPosition <= colorLimit - 0.5))
		return false;

	const float currentDepth = gDepth.Load(int3(GuidePixel(pixel), 0));
	const float previousDepth = gPreviousDepth.Load(int3(GuidePixel(previousPosition - 0.5), 0));
	if (!(abs(currentDepth) > 1e-6) || !(abs(previousDepth) > 1e-6) ||
		!(abs(currentDepth) < 1e20) || !(abs(previousDepth) < 1e20))
		return false;
	const float depthScale = max(max(abs(currentDepth), abs(previousDepth)), 1.0);
	if (abs(currentDepth - previousDepth) > gDepthThreshold * depthScale)
		return false;

	const float previousLuma = dot(gPreviousInput.SampleLevel(gLinearClamp, ColorUV(previousPosition - 0.5), 0).rgb, kLuma);
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
			const float2 motion = gMotionVectors.Load(int3(GuidePixel(pixelPosition), 0)) *
				float2(gMotionScaleX, gMotionScaleY);
			motionValid = IsBoundedMotion(motion, float2(gColorWidth, gColorHeight) * 0.5);
			previousPosition += motion;
		}

		if (motionValid && IsHistoryValid(pixelPosition, previousPosition, baseColor.rgb))
		{
			const float2 previousUV = ColorUV(previousPosition - 0.5);
			const float3 previousDelta = PreviousDeltaAt(previousUV);
			const float historyWeight = exp(-max(gFrameDeltaSeconds, 1.0 / 240.0) /
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

	float3 result = baseColor.rgb + delta;
	if (!all(result == result) || !all(abs(result) < float3(1e20, 1e20, 1e20)))
		result = nrColor.rgb;
	gOutput[pixel] = float4(max(result, 0.0.xxx), nrColor.a);
}
