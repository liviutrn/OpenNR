#include "Upscaling/NeuralRendering/CenterSharedCommon.hlsli"

Texture2D<float4> OriginalStereo : register(t0);
Texture2D<float4> CenterResidual : register(t5);
Texture2D<float> CenterDepthColor : register(t6);
Texture2D<float> CenterConfidence : register(t7);
Texture2D<float4> CenterBase : register(t8);
RWTexture2D<float4> FinalStereo : register(u0);

float CenterDepthEdge(float2 uv)
{
	float2 stepUV = FrameSize.zw;
	float center = LinearDepth(CenterDepthColor.SampleLevel(PointSampler, uv, 0));
	float gradient = 0.0;
	gradient = max(gradient, abs(center - LinearDepth(CenterDepthColor.SampleLevel(PointSampler, uv + float2(stepUV.x, 0), 0))));
	gradient = max(gradient, abs(center - LinearDepth(CenterDepthColor.SampleLevel(PointSampler, uv - float2(stepUV.x, 0), 0))));
	gradient = max(gradient, abs(center - LinearDepth(CenterDepthColor.SampleLevel(PointSampler, uv + float2(0, stepUV.y), 0))));
	gradient = max(gradient, abs(center - LinearDepth(CenterDepthColor.SampleLevel(PointSampler, uv - float2(0, stepUV.y), 0))));
	return saturate(gradient / max(center * 0.025, 0.01));
}

[numthreads(8, 8, 1)]
void main(uint3 id : SV_DispatchThreadID)
{
	uint eye = id.z;
	if (eye > 1 || id.x >= SourceRect[eye].z || id.y >= SourceRect[eye].w)
		return;
	uint2 pixel = uint2(SourceRect[eye].xy) + id.xy;
	float4 original = OriginalStereo.Load(int3(pixel, 0));
	float2 eyeUV = (float2(id.xy) + 0.5) / SourceRect[eye].zw;
	float rawDepth = EyeDepthAt(eyeUV, eye);
	if (rawDepth <= 0.00001 || rawDepth >= 0.99999) {
		FinalStereo[pixel] = original;
		return;
	}
	float centerZ;
	float2 centerUV = EyeToCenter(eyeUV, rawDepth, eye, centerZ);
	if (!Inside(centerUV) || centerZ <= DepthRange.x * 1.001 || centerZ >= DepthRange.y) {
		FinalStereo[pixel] = original;
		return;
	}

	float centerRaw = CenterDepthColor.SampleLevel(PointSampler, centerUV, 0);
	float centerSampleZ = LinearDepth(centerRaw);
	float relativeDepthError = abs(centerSampleZ - centerZ) / max(centerZ, 0.01);
	float depthConfidence = 1.0 - smoothstep(0.01, 0.035, relativeDepthError);
	float edgeConfidence = (1.0 - 0.85 * DepthEdge(eyeUV, eye)) *
		(1.0 - 0.85 * CenterDepthEdge(centerUV));
	float4 centerBase = CenterBase.SampleLevel(LinearSampler, centerUV, 0);
	float colorDifference = length(centerBase.rgb - original.rgb);
	float colorConfidence = 1.0 - smoothstep(0.12, 0.4, colorDifference);
	float nearConfidence = lerp(0.35, 1.0,
		saturate((centerZ - DepthRange.x * 2.0) / max(DepthRange.x * 10.0, 0.01)));
	float cropConfidence = saturate(min(min(eyeUV.x, eyeUV.y),
		min(1.0 - eyeUV.x, 1.0 - eyeUV.y)) * 40.0);
	float confidence = CenterConfidence.SampleLevel(LinearSampler, centerUV, 0) *
		depthConfidence * edgeConfidence * colorConfidence * nearConfidence * cropConfidence;
	float4 residual = CenterResidual.SampleLevel(LinearSampler, centerUV, 0);
	float4 result = original + float4(residual.rgb * confidence, 0.0);
	if (DebugMode == 1)
		result = centerBase;
	else if (DebugMode == 2)
		result = float4(centerRaw.xxx, 1.0);
	else if (DebugMode == 3) {
		float centerConfidence = CenterConfidence.SampleLevel(LinearSampler, centerUV, 0);
		result = float4(centerConfidence, centerConfidence, centerConfidence, 1.0);
	}
	else if (DebugMode == 4)
		result = float4(residual.rgb * 0.5 + 0.5, 1.0);
	else if ((DebugMode == 5 && eye == 0) || (DebugMode == 6 && eye == 1))
		result = float4(confidence, confidence, confidence, 1.0);
	FinalStereo[pixel] = result;
}
