#include "Upscaling/NeuralRendering/CenterSharedCommon.hlsli"

Texture2D<float4> StereoColor : register(t0);
RWTexture2D<float4> CenterColor : register(u0);
RWTexture2D<float> CenterDepthColor : register(u1);
RWTexture2D<float> CenterConfidence : register(u2);

float4 ReadEyeColor(Candidate candidate, uint eye)
{
	float2 sourcePixel = SourceRect[eye].xy + candidate.uv * SourceRect[eye].zw;
	return StereoColor.SampleLevel(LinearSampler, sourcePixel / FrameSize.xy, 0);
}

[numthreads(8, 8, 1)]
void main(uint3 id : SV_DispatchThreadID)
{
	uint width, height;
	CenterColor.GetDimensions(width, height);
	if (id.x >= width || id.y >= height)
		return;
	float2 uv = (float2(id.xy) + 0.5) / float2(width, height);
	float2 pixelSize = 1.0 / float2(width, height);
	Candidate left = FindCandidate(uv, 0, pixelSize);
	Candidate right = FindCandidate(uv, 1, pixelSize);

	float4 result = 0.0;
	float confidence = 0.0;
	float centerZ = DepthRange.y;
	if (left.confidence > 0.0 && right.confidence > 0.0) {
		float relativeDepthDifference = abs(left.centerZ - right.centerZ) /
			max(min(left.centerZ, right.centerZ), 0.01);
		if (relativeDepthDifference < 0.02) {
			float4 leftColor = ReadEyeColor(left, 0);
			float4 rightColor = ReadEyeColor(right, 1);
			float colorDifference = length(leftColor.rgb - rightColor.rgb);
			float leftWeight = left.confidence;
			float rightWeight = right.confidence;
			if (colorDifference > 0.15) {
				if (leftWeight >= rightWeight)
					rightWeight *= 0.25;
				else
					leftWeight *= 0.25;
			}
			float weight = max(leftWeight + rightWeight, 1e-5);
			result = (leftColor * leftWeight + rightColor * rightWeight) / weight;
			centerZ = (left.centerZ * leftWeight + right.centerZ * rightWeight) / weight;
			confidence = min(1.0, (left.confidence + right.confidence) * 0.5);
			confidence *= 1.0 - 0.6 * smoothstep(0.12, 0.35, colorDifference);
		} else {
			bool selectLeft = left.centerZ < right.centerZ;
			Candidate selected = left;
			if (!selectLeft)
				selected = right;
			result = ReadEyeColor(selected, selectLeft ? 0 : 1);
			centerZ = selected.centerZ;
			confidence = selected.confidence * 0.45;
		}
	} else if (left.confidence > 0.0 || right.confidence > 0.0) {
		bool selectLeft = left.confidence > 0.0;
		Candidate selected = left;
		if (!selectLeft)
			selected = right;
		result = ReadEyeColor(selected, selectLeft ? 0 : 1);
		centerZ = selected.centerZ;
		confidence = selected.confidence * 0.55;
	} else {
		float2 sourcePixel = SourceRect[0].xy + uv * SourceRect[0].zw;
		result = StereoColor.SampleLevel(LinearSampler, sourcePixel / FrameSize.xy, 0);
	}

	CenterColor[id.xy] = result;
	CenterDepthColor[id.xy] = RawDepth(centerZ);
	CenterConfidence[id.xy] = confidence;
}
