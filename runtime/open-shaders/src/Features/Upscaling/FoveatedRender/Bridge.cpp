#include "Bridge.h"

#include "../../../Globals.h"
#include "../../Upscaling.h"
#include "../FoveatedRender.h"

bool FoveatedRenderImpl::Bridge::IsRouteActive()
{
	// IsActive() already checks: enabledAtBoot && isVR
	//                            && GetUpscaleMethod() is kDLSS or kFSR (selected, not just available)
	return globals::features::upscaling.foveatedRender.IsActive();
}

void FoveatedRenderImpl::Bridge::BootSequence()
{
	auto& enhancer = globals::features::upscaling.foveatedRender;
	enhancer.LatchEnabled();
	enhancer.LatchQualityMode();
}

void FoveatedRenderImpl::Bridge::ComputeMvecScale(uint32_t eyeIndex, float& outX, float& outY)
{
	// Default: identity (caller's normal Streamline path).
	outX = 1.0f;
	outY = 1.0f;

	if (!IsRouteActive())
		return;
	const auto frame = globals::state ? globals::state->frameCount : UINT32_MAX;
	if (frame == mvecScaleFrame && eyeIndex < mvecScales.size()) {
		outX = mvecScales[eyeIndex][0];
		outY = mvecScales[eyeIndex][1];
		return;
	}

	auto& enhancer = globals::features::upscaling.foveatedRender;
	// Use the effective per-eye UV. Adaptive crop scales the selected region, and
	// eye tracking can recenter it around the live gaze before guides are resolved.
	const auto uv = (eyeIndex == 1) ? enhancer.GetEffectiveRightUV() : enhancer.GetEffectiveLeftUV();
	const bool isFullEye = uv.IsFullEye();

	if (isFullEye)
		return;

	// Default + Faster both use per-eye DLSS calls (not strip-merged), so
	// motion vectors scale by 1/UV.w on x.
	outX = (uv.w > 0.0f) ? (1.0f / uv.w) : 1.0f;
	outY = (uv.h > 0.0f) ? (1.0f / uv.h) : 1.0f;
}

void FoveatedRenderImpl::Bridge::SetMvecScaleForFrame(uint32_t frame,
	const std::array<std::array<float, 2>, 2>& scales)
{
	mvecScales = scales;
	mvecScaleFrame = frame;
}
