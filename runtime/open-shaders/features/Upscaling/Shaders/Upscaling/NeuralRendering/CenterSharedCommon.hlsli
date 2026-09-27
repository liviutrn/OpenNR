cbuffer CenterSharedConstants : register(b0)
{
	float4 EyeFrustum[2];
	float4 EyeOffset[2];
	float4 EyeCrop[2];
	float4 EyeMotionScale[2];
	float4 CenterFrustum;
	float4 CenterCrop;
	float4 SourceRect[2];
	float4 FrameSize;
	float4 GuideSize;
	float4 DepthRange;
	uint DebugMode;
	float3 CenterPadding;
};

Texture2D<float> LeftDepth : register(t1);
Texture2D<float> RightDepth : register(t2);
Texture2D<float2> LeftMotion : register(t3);
Texture2D<float2> RightMotion : register(t4);
SamplerState PointSampler : register(s0);
SamplerState LinearSampler : register(s1);

bool Inside(float2 uv)
{
	return all(uv >= 0.0) && all(uv < 1.0);
}

float LinearDepth(float raw)
{
	return DepthRange.x * DepthRange.y /
		max(DepthRange.y - raw * (DepthRange.y - DepthRange.x), 1e-5);
}

float RawDepth(float linearDepth)
{
	return (DepthRange.y - DepthRange.x * DepthRange.y / max(linearDepth, 1e-5)) /
		(DepthRange.y - DepthRange.x);
}

float2 FullToTan(float2 fullUV, float4 frustum)
{
	return lerp(float2(frustum.x, frustum.z), float2(frustum.y, frustum.w), fullUV);
}

float2 TanToFull(float2 tangent, float4 frustum)
{
	return (tangent - float2(frustum.x, frustum.z)) /
		float2(frustum.y - frustum.x, frustum.w - frustum.z);
}

float2 EyeToCenter(float2 eyeLocalUV, float rawDepth, uint eye, out float centerZ)
{
	float2 fullUV = EyeCrop[eye].xy + eyeLocalUV * EyeCrop[eye].zw;
	float z = LinearDepth(rawDepth);
	float2 tangent = FullToTan(fullUV, EyeFrustum[eye]);
	float3 centerPosition = float3(tangent * z, z) + EyeOffset[eye].xyz;
	centerZ = centerPosition.z;
	float2 centerFullUV = TanToFull(centerPosition.xy / centerZ, CenterFrustum);
	return (centerFullUV - CenterCrop.xy) / CenterCrop.zw;
}

float2 CenterToEye(float2 centerLocalUV, float z, uint eye)
{
	float2 fullUV = CenterCrop.xy + centerLocalUV * CenterCrop.zw;
	float2 tangent = FullToTan(fullUV, CenterFrustum);
	float3 eyePosition = float3(tangent * z, z) - EyeOffset[eye].xyz;
	float2 eyeFullUV = TanToFull(eyePosition.xy / eyePosition.z, EyeFrustum[eye]);
	return (eyeFullUV - EyeCrop[eye].xy) / EyeCrop[eye].zw;
}

float EyeDepthAt(float2 uv, uint eye)
{
	return eye == 0 ? LeftDepth.SampleLevel(PointSampler, uv, 0) :
		RightDepth.SampleLevel(PointSampler, uv, 0);
}

float2 EyeMotionAt(float2 uv, uint eye)
{
	return eye == 0 ? LeftMotion.SampleLevel(PointSampler, uv, 0) :
		RightMotion.SampleLevel(PointSampler, uv, 0);
}

float DepthEdge(float2 uv, uint eye)
{
	float2 stepUV = GuideSize.zw;
	float center = LinearDepth(EyeDepthAt(uv, eye));
	float gradient = 0.0;
	gradient = max(gradient, abs(center - LinearDepth(EyeDepthAt(uv + float2(stepUV.x, 0), eye))));
	gradient = max(gradient, abs(center - LinearDepth(EyeDepthAt(uv - float2(stepUV.x, 0), eye))));
	gradient = max(gradient, abs(center - LinearDepth(EyeDepthAt(uv + float2(0, stepUV.y), eye))));
	gradient = max(gradient, abs(center - LinearDepth(EyeDepthAt(uv - float2(0, stepUV.y), eye))));
	return saturate(gradient / max(center * 0.025, 0.01));
}

struct Candidate
{
	float2 uv;
	float2 centerUV;
	float centerZ;
	float rawDepth;
	float confidence;
};

Candidate FindCandidate(float2 centerUV, uint eye, float2 centerPixelSize)
{
	Candidate candidate;
	candidate.uv = 0.0;
	candidate.centerUV = 0.0;
	candidate.centerZ = 0.0;
	candidate.rawDepth = 0.0;
	candidate.confidence = 0.0;
	float2 centerFullUV = CenterCrop.xy + centerUV * CenterCrop.zw;
	float2 centerTangent = FullToTan(centerFullUV, CenterFrustum);
	float2 eyeFullUV = TanToFull(centerTangent, EyeFrustum[eye]);
	float2 eyeUV = (eyeFullUV - EyeCrop[eye].xy) / EyeCrop[eye].zw;
	if (!Inside(eyeUV))
		return candidate;

	float rawDepth = EyeDepthAt(eyeUV, eye);
	if (rawDepth <= 0.00001 || rawDepth >= 0.99999)
		return candidate;
	float z = LinearDepth(rawDepth) + EyeOffset[eye].z;
	eyeUV = CenterToEye(centerUV, z, eye);
	if (!Inside(eyeUV))
		return candidate;
	rawDepth = EyeDepthAt(eyeUV, eye);
	if (rawDepth <= 0.00001 || rawDepth >= 0.99999)
		return candidate;
	z = LinearDepth(rawDepth) + EyeOffset[eye].z;
	eyeUV = CenterToEye(centerUV, z, eye);
	if (!Inside(eyeUV))
		return candidate;
	rawDepth = EyeDepthAt(eyeUV, eye);
	if (rawDepth <= 0.00001 || rawDepth >= 0.99999)
		return candidate;

	float centerZ;
	float2 projectedCenterUV = EyeToCenter(eyeUV, rawDepth, eye, centerZ);
	if (centerZ <= DepthRange.x * 1.001 || centerZ >= DepthRange.y)
		return candidate;
	float2 errorPixels = (projectedCenterUV - centerUV) / centerPixelSize;
	float error = length(errorPixels);
	float confidence = 1.0 - smoothstep(0.75, 2.5, error);
	confidence *= 1.0 - 0.75 * DepthEdge(eyeUV, eye);
	confidence *= saturate(min(min(eyeUV.x, eyeUV.y), min(1.0 - eyeUV.x, 1.0 - eyeUV.y)) * 50.0);
	candidate.uv = eyeUV;
	candidate.centerUV = projectedCenterUV;
	candidate.centerZ = centerZ;
	candidate.rawDepth = rawDepth;
	candidate.confidence = confidence;
	return candidate;
}

float2 CenterMotion(Candidate candidate, uint eye)
{
	float2 eyeMotion = EyeMotionAt(candidate.uv, eye);
	eyeMotion *= EyeMotionScale[eye].xy;
	float2 previousEyeUV = candidate.uv + eyeMotion;
	if (!Inside(previousEyeUV))
		return 0.0;
	float previousZ;
	float2 previousCenterUV = EyeToCenter(previousEyeUV, candidate.rawDepth, eye, previousZ);
	return clamp(previousCenterUV - candidate.centerUV, -0.1, 0.1);
}
