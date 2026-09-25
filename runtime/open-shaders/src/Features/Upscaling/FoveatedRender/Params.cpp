#include "Params.h"

#include "../../../State.h"
#include "../../../Utils/Game.h"
#include "../../Upscaling.h"
#include "../FoveatedRender.h"
#include "../NativeOpenVRGaze.h"
#include "../PerfMode.h"

namespace FoveatedRenderImpl
{
	VRDlssParams VRDlssParams::Resolve(
		ID3D11Resource* upscalingTexture,
		ID3D11Resource* depth,
		ID3D11Resource* reactive,
		ID3D11Resource* transparency,
		ID3D11Resource* mvec)
	{
		VRDlssParams p{};

		// Dimensions. With DLSSperf (PerfMode) active, the engine RTs (kMAIN,
		// depth, mvec) are allocated at RenderRes and state->screenSize is
		// spoofed to RenderRes too. PerfMode owns a private DisplayRes
		// testTexture that DLSS must target. Mirror Streamline::Upscale's
		// plumbing (Streamline.cpp:617-626) so the foveated route works in
		// both stacks: input extents read from kMAIN at RenderRes, output
		// extents and colorDst point at DisplayRes / testTexture.
		auto& perfMode = globals::features::upscaling.perfMode;
		const bool dlssperfActive = perfMode.IsHookActive() && perfMode.GetTestTexture();

		const auto screenSize = globals::state->screenSize;
		const auto renderSize = Util::ConvertToDynamic(screenSize);
		const auto displaySize = dlssperfActive ? perfMode.GetDisplayScreenSize() : screenSize;

		p.renderW = (uint32_t)renderSize.x;
		p.renderH = (uint32_t)renderSize.y;
		p.eyeWidthIn = (uint32_t)(renderSize.x / 2);
		p.eyeHeightIn = (uint32_t)renderSize.y;
		p.eyeWidthOut = (uint32_t)(displaySize.x / 2);
		p.eyeHeightOut = (uint32_t)displaySize.y;

		// Textures. With DLSSperf, DLSS output lands in PerfMode's testTexture
		// (DisplayRes); the stretched periphery also targets the testTexture's
		// UAV. Without DLSSperf, both alias kMAIN at full size.
		p.colorSrc = upscalingTexture;
		p.colorDst = dlssperfActive ? static_cast<ID3D11Resource*>(perfMode.GetTestTexture()) : upscalingTexture;
		p.colorDstUAV = dlssperfActive ? perfMode.GetTestTextureUAV() :
		                                 globals::game::renderer->GetRuntimeData().renderTargets[RE::RENDER_TARGETS::kMAIN].UAV;

		p.depthTexture = depth;
		p.reactiveMask = reactive;
		p.transparencyMask = transparency;
		p.motionVectors = mvec;

		// Mode & subrect. Effective UVs include the optional regular centered
		// adaptive-crop owner; gaze resolution below may still take ownership when
		// eye-tracked foveation is explicitly enabled.
		auto& enhancer = globals::features::upscaling.foveatedRender;
		auto& upscaling = globals::features::upscaling;
		p.mode = enhancer.GetDlssMode();
		p.leftUV = enhancer.GetEffectiveLeftUV();
		p.rightUV = enhancer.GetEffectiveRightUV();
		const NativeOpenVRGaze::Config gazeConfig{
			.enabled = enhancer.settings.neuralRenderingEyeTrackedFoveation,
			.smoothingMs = enhancer.settings.neuralRenderingEyeTrackedSmoothingMs,
			.policy = enhancer.settings.neuralRenderingEyeTrackedPolicy,
			.catchupMs = enhancer.settings.neuralRenderingEyeTrackedCatchupMs,
			.deadbandPixels = enhancer.settings.neuralRenderingEyeTrackedDeadbandPixels,
			.holdMs = enhancer.settings.neuralRenderingEyeTrackedHoldMs,
			.predictionMs = enhancer.settings.neuralRenderingEyeTrackedPredictionMs,
			.quantizationPixels = enhancer.settings.neuralRenderingEyeTrackedQuantizationPixels,
			.cropPaddingPixels = enhancer.settings.neuralRenderingEyeTrackedCropPaddingPixels,
		};
		const bool gazeRequested = gazeConfig.enabled && enhancer.settings.neuralRenderingEnabled &&
			p.mode == FoveatedRender::DlssMode::kDefault &&
			upscaling.GetUpscaleMethod() == Upscaling::UpscaleMethod::kDLSS;
		const std::uint32_t frame = globals::state ? globals::state->frameCount : 0;
		const auto gaze = NativeOpenVRGaze::ResolveForFrame(
			gazeConfig, p.leftUV, p.rightUV, p.eyeWidthIn, p.eyeHeightIn, frame,
			gazeRequested && NativeOpenVRGaze::IsDynamicGazeAllowed());
		p.leftUV = gaze.leftUV;
		p.rightUV = gaze.rightUV;
		p.eyeTrackedGazeActive = gaze.dynamic;
		p.eyeTrackedGazeConfigured = gazeRequested;
		p.eyeTrackedGazeReset = gaze.historyReset;
		p.isFullEye = p.leftUV.IsFullEye() && p.rightUV.IsFullEye();

		// Jitter — ConfigureUpscaling already computed correct DLSS jitter.
		p.jitterX = upscaling.jitter.x;
		p.jitterY = upscaling.jitter.y;

		return p;
	}
}
