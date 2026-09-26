cbuffer StereoResidualParams : register(b0)
{
	uint gColorWidth;
	uint gColorHeight;
	uint gGuideWidth;
	uint gGuideHeight;
	uint gEyeWidth;
	uint gEyeHeight;
	uint gSourceCropX;
	uint gSourceCropY;
	uint gTargetCropX;
	uint gTargetCropY;
	float gDepthTolerance;
	float gColorTolerance;
	float gResidualStrength;
	float gPadding0;
	float gPadding1;
	float gPadding2;
	row_major float4x4 gTargetInverseViewProjection;
	row_major float4x4 gSourceViewProjection;
};

Texture2D<float4> gSourceBase : register(t0);
Texture2D<float4> gSourceTeacher : register(t1);
Texture2D<float> gSourceDepth : register(t2);
Texture2D<float4> gTargetBase : register(t3);
Texture2D<float> gTargetDepth : register(t4);
RWTexture2D<float4> gOutput : register(u0);

static const float3 kLuma = float3(0.2126, 0.7152, 0.0722);

uint2 GuidePixel(uint2 colorPixel)
{
	const float2 guidePosition = (float2(colorPixel) + 0.5) *
		float2(gGuideWidth, gGuideHeight) / float2(gColorWidth, gColorHeight);
	return min(uint2(guidePosition), uint2(gGuideWidth - 1u, gGuideHeight - 1u));
}

float RelativeLumaError(float3 a, float3 b)
{
	const float lumaA = dot(a, kLuma);
	const float lumaB = dot(b, kLuma);
	return abs(lumaA - lumaB) / max(max(abs(lumaA), abs(lumaB)), 0.05);
}

[numthreads(8, 8, 1)]
void main(uint3 dispatchThreadID : SV_DispatchThreadID)
{
	if (dispatchThreadID.x >= gColorWidth || dispatchThreadID.y >= gColorHeight)
		return;

	const uint2 pixel = dispatchThreadID.xy;
	float4 outputColor = gTargetBase.Load(int3(pixel, 0));
	const float targetDepth = gTargetDepth.Load(int3(GuidePixel(pixel), 0));
	float3 residual = 0.0.xxx;
	float totalWeight = 0.0;
	float2 sourcePosition = -1.0.xx;
	float2 sourceLast = float2(gColorWidth, gColorHeight) - 1.0;

	if (targetDepth > 1e-6 && targetDepth < 1.0 - 1e-6)
	{
		const float2 targetEyeUV = (float2(gTargetCropX, gTargetCropY) + float2(pixel) + 0.5) /
			float2(gEyeWidth, gEyeHeight);
		const float2 targetNDC = targetEyeUV * float2(2.0, -2.0) + float2(-1.0, 1.0);
		float4 worldPosition = mul(gTargetInverseViewProjection, float4(targetNDC, targetDepth, 1.0));
		if (abs(worldPosition.w) > 1e-7)
		{
			worldPosition /= worldPosition.w;
			const float4 sourceClip = mul(gSourceViewProjection, worldPosition);
			if (sourceClip.w > 1e-7)
			{
				const float3 sourceNDC = sourceClip.xyz / sourceClip.w;
				const float2 sourceEyeUV = sourceNDC.xy * float2(0.5, -0.5) + 0.5;
				sourcePosition = sourceEyeUV * float2(gEyeWidth, gEyeHeight) -
					float2(gSourceCropX, gSourceCropY) - 0.5;
				if (sourceNDC.z >= 0.0 && sourceNDC.z <= 1.0 &&
					all(sourcePosition >= 0.0.xx) && all(sourcePosition <= sourceLast))
				{
					const int2 first = int2(floor(sourcePosition));
					const float2 fraction = frac(sourcePosition);
					const float3 targetLumaSource = outputColor.rgb;
					[unroll]
					for (uint tapY = 0; tapY < 2; ++tapY) {
						[unroll]
						for (uint tapX = 0; tapX < 2; ++tapX) {
							const int2 tap = first + int2(tapX, tapY);
							if (tap.x < 0 || tap.y < 0 || tap.x >= int(gColorWidth) || tap.y >= int(gColorHeight))
								continue;
							const float2 axisWeight = float2(tapX ? fraction.x : 1.0 - fraction.x,
								tapY ? fraction.y : 1.0 - fraction.y);
							float weight = axisWeight.x * axisWeight.y;
							if (weight <= 0.0)
								continue;
							const uint2 sourcePixel = uint2(tap);
							const float sourceDepth = gSourceDepth.Load(int3(GuidePixel(sourcePixel), 0));
							const float depthError = abs(sourceDepth - sourceNDC.z);
							if (sourceDepth <= 1e-6 || sourceDepth >= 1.0 - 1e-6 ||
								depthError >= gDepthTolerance)
								continue;

							const float4 sourceBase = gSourceBase.Load(int3(sourcePixel, 0));
							const float colorError = RelativeLumaError(sourceBase.rgb, targetLumaSource);
							if (colorError >= gColorTolerance)
								continue;
							const float4 sourceTeacher = gSourceTeacher.Load(int3(sourcePixel, 0));
							const float depthConfidence = 1.0 - smoothstep(gDepthTolerance * 0.35, gDepthTolerance, depthError);
							const float colorConfidence = 1.0 - smoothstep(gColorTolerance * 0.5, gColorTolerance, colorError);
							weight *= depthConfidence * colorConfidence;
							residual += (sourceTeacher.rgb - sourceBase.rgb) * weight;
							totalWeight += weight;
						}
					}
				}
			}
		}
	}

	if (totalWeight > 1e-5)
	{
		residual /= totalWeight;
		const float edgeDistance = min(min(sourcePosition.x, sourceLast.x - sourcePosition.x),
			min(sourcePosition.y, sourceLast.y - sourcePosition.y));
		const float cropConfidence = smoothstep(0.0, min(8.0, min(gColorWidth, gColorHeight) * 0.25), edgeDistance);
		outputColor.rgb += residual * (gResidualStrength * cropConfidence);
	}
	gOutput[pixel] = float4(max(outputColor.rgb, 0.0.xxx), outputColor.a);
}
