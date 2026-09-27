#include "Upscaling/NeuralRendering/CenterSharedCommon.hlsli"

RWTexture2D<float> CenterDepthGuide : register(u0);
RWTexture2D<float2> CenterMotionGuide : register(u1);

[numthreads(8, 8, 1)]
void main(uint3 id : SV_DispatchThreadID)
{
	uint width, height;
	CenterDepthGuide.GetDimensions(width, height);
	if (id.x >= width || id.y >= height)
		return;
	float2 uv = (float2(id.xy) + 0.5) / float2(width, height);
	float2 pixelSize = 1.0 / float2(width, height);
	Candidate left = FindCandidate(uv, 0, pixelSize);
	Candidate right = FindCandidate(uv, 1, pixelSize);
	float centerZ = DepthRange.y;
	float2 motion = 0.0;
	if (left.confidence > 0.0 && right.confidence > 0.0) {
		float relativeDepthDifference = abs(left.centerZ - right.centerZ) /
			max(min(left.centerZ, right.centerZ), 0.01);
		if (relativeDepthDifference < 0.02) {
			float weight = left.confidence + right.confidence;
			centerZ = (left.centerZ * left.confidence + right.centerZ * right.confidence) / weight;
			motion = (CenterMotion(left, 0) * left.confidence +
				CenterMotion(right, 1) * right.confidence) / weight;
		} else {
			bool selectLeft = left.centerZ < right.centerZ;
			Candidate selected = selectLeft ? left : right;
			centerZ = selected.centerZ;
			motion = CenterMotion(selected, selectLeft ? 0 : 1);
		}
	} else if (left.confidence > 0.0 || right.confidence > 0.0) {
		bool selectLeft = left.confidence > 0.0;
		Candidate selected = selectLeft ? left : right;
		centerZ = selected.centerZ;
		motion = CenterMotion(selected, selectLeft ? 0 : 1);
	}
	CenterDepthGuide[id.xy] = RawDepth(centerZ);
	CenterMotionGuide[id.xy] = motion;
}
