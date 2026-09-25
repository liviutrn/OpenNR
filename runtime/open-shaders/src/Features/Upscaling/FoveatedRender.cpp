#include "FoveatedRender.h"

#include "../../Globals.h"
#include "../../I18n/I18n.h"
#include "../../Utils/Subrect.h"
#include "../../Utils/UI.h"
#include "../FoveatedCommon.h"
#include "../OpenNRCapture.h"
#include "../Upscaling.h"
#include "../VR.h"
#include "FoveatedRender/Core.h"
#include "FoveatedRender/Bridge.h"
#include "FoveatedRender/Postprocess.h"
#include "NativeOpenVRGaze.h"
#include "NeuralRendering/AdaptiveQualityOrder.h"
#include "NeuralRendering/Integration.h"
#include "NeuralRendering/StageSplitPolicy.h"
#include "NeuralRendering/FuturePipeline.h"
#include "NeuralRendering/Renderer.h"

#include <algorithm>
#include <cmath>

#define I18N_KEY_PREFIX "feature.upscaling."

static_assert(!NeuralRendering::Future::AsyncOwnershipContract::kRuntimeEnabled);
static_assert(!NeuralRendering::Future::DepthMatchedResidualFillContract::kRuntimeEnabled);
static_assert(!NeuralRendering::Future::PeripheralCompressionContract::kRuntimeEnabled);

namespace
{
	constexpr float kStereoGeometryEpsilon = 0.0025f;

	bool IsNasalConvergenceGeometry(const Util::Subrect::UVRegion& left,
		const Util::Subrect::UVRegion& right)
	{
		// The known-good SkyrimVR arrangement places the left-eye crop toward the
		// nasal/right side and the right-eye crop toward the nasal/left side. The
		// extents must still match because the shared Feature 18 resource contract
		// is size-symmetric; only the per-eye x origins differ.
		const bool sameExtent = std::abs(left.w - right.w) <= kStereoGeometryEpsilon &&
			std::abs(left.h - right.h) <= kStereoGeometryEpsilon;
		const bool mirrored = std::abs(right.x - (1.0f - left.x - left.w)) <= kStereoGeometryEpsilon;
		return sameExtent && mirrored && left.x > right.x + kStereoGeometryEpsilon;
	}

	Util::Subrect::UVRegion MakeAdaptiveCropUV(float coverage, bool leftEye, bool nasalConvergence)
	{
		const float offset = (1.0f - coverage) * 0.5f;
		if (!nasalConvergence)
			return { offset, offset, coverage, coverage };

		// Keep the two eye crops on their original HMD convergence sides while
		// changing only their shared coverage. At 60% this exactly reproduces the
		// persisted Nasal Convergence 60% preset: left=(.4,.2,.6,.6),
		// right=(0,.2,.6,.6).
		return leftEye ?
			Util::Subrect::UVRegion{ 1.0f - coverage, offset, coverage, coverage } :
			Util::Subrect::UVRegion{ 0.0f, offset, coverage, coverage };
	}

	std::uint32_t AdjacentAdaptiveResolution(std::uint32_t resolution, bool higher)
	{
		const auto& buckets = NeuralRendering::AdaptiveController::ResolutionBuckets();
		for (std::size_t index = 0; index < buckets.size(); ++index) {
			if (buckets[index] != resolution)
				continue;
			if (higher && index > 0)
				return buckets[index - 1];
			if (!higher && index + 1 < buckets.size())
				return buckets[index + 1];
			return resolution;
		}
		return resolution;
	}
}

NLOHMANN_DEFINE_TYPE_NON_INTRUSIVE_WITH_DEFAULT(
	FoveatedRender::Settings,
	enabled,
	dlssMode,
	stretchMode,
	peripheryBlurRadius,
	debugVisualize,
	peripheryAAMode,
	peripheryTemporalAlpha,
	subrectBlendMode,
	subrectMaskMode,
	subrectFeatherWidth,
	subrectFalloffCurve,
	subrectDitherStrength,
	neuralRenderingEnabled,
	neuralRenderingModelResolution,
	neuralRenderingPreset,
	neuralRenderingIntensity,
	neuralRenderingLocalTone,
	neuralRenderingLocalStructure,
	neuralRenderingSkinStructure,
	neuralRenderingStyle,
	neuralRenderingAutoMask,
	neuralRenderingUICorrection,
	neuralRenderingResolveMode,
	neuralRenderingMultiPass,
	neuralRenderingSecondPassContribution,
	neuralRenderingSecondPassCropReduction,
	neuralRenderingSecondPassCropReductionX,
	neuralRenderingSecondPassCropReductionY,
	neuralRenderingSecondPassBlendMode,
	neuralRenderingSecondPassMaskMode,
	neuralRenderingSecondPassFeatherWidth,
	neuralRenderingSecondPassFalloffCurve,
	neuralRenderingSecondPassDitherStrength,
	neuralRenderingAdaptiveEnabled,
	neuralRenderingAdaptiveRefreshHz,
	neuralRenderingAdaptiveBudgetMode,
	neuralRenderingAdaptiveTargetFps,
	neuralRenderingAdaptiveTargetFrameTimeMs,
	neuralRenderingAdaptiveMinimumResolution,
	neuralRenderingAdaptiveDownshiftFrames,
	neuralRenderingAdaptiveUpshiftFrames,
	neuralRenderingAdaptiveMinimumDwellFrames,
	neuralRenderingAdaptiveGuardTimeMs,
	neuralRenderingAdaptiveDiagnostics,
	neuralRenderingAdaptiveQualityOrder,
	neuralRenderingAdaptiveCropEnabled,
	neuralRenderingAdaptiveCropMaximumCoverage,
	neuralRenderingAdaptiveCropMinimumCoverage,
	neuralRenderingAdaptiveCropDownshiftFrames,
	neuralRenderingAdaptiveCropUpshiftFrames,
	neuralRenderingAdaptiveCropMinimumDwellFrames,
	neuralRenderingAdaptiveCropTransitionFrames,
	neuralRenderingEyeTrackedFoveation,
	neuralRenderingEyeTrackedSmoothingMs,
	neuralRenderingEyeTrackedPolicy,
	neuralRenderingEyeTrackedCatchupMs,
	neuralRenderingEyeTrackedDeadbandPixels,
	neuralRenderingEyeTrackedHoldMs,
	neuralRenderingEyeTrackedPredictionMs,
	neuralRenderingEyeTrackedQuantizationPixels,
	neuralRenderingEyeTrackedCropPaddingPixels,
	neuralRenderingNRContribution,
	neuralRenderingDetailBoost);

// ============================================================================
// Lifecycle
// ============================================================================

void FoveatedRender::PostPostLoad()
{
	bootSnapshot.LatchIfNeeded(settings);
	adaptiveController.Reset();
	adaptiveCropController.Reset();
	adaptivePassController.Reset();

	// Opt into the stereo extension so the controller tracks a separate
	// right-eye UV (HMD nose-side overlap symmetry).
	subrectController.SetStereoEnabled(true);

	// Seed sensible foveal presets. Empty-case only — user edits persist.
	// The regular centered sequence is the recommended starting point for the
	// adaptive-crop experiment. Centered presets are symmetric per eye (no rightUV
	// means auto-mirror, which produces an identical right-eye UV). Keep the older
	// asymmetric Nasal Convergence presets available for existing users, but do not
	// select one by default: changing crop ownership during a handoff is easier to
	// reason about when both eyes use the same centered geometry.
	subrectController.SeedDefaultPresets({
		{ .name = kPresetFullEye, .uv = { 0.0f, 0.0f, 1.0f, 1.0f } },
		{ .name = kPresetCenter90, .uv = { 0.05f, 0.05f, 0.90f, 0.90f } },
		{ .name = kPresetCenter80, .uv = { 0.10f, 0.10f, 0.80f, 0.80f } },
		{ .name = kPresetCenter75, .uv = { 0.125f, 0.125f, 0.75f, 0.75f } },
		{ .name = kPresetCenter70, .uv = { 0.15f, 0.15f, 0.70f, 0.70f } },
		{ .name = kPresetCenter60, .uv = { 0.20f, 0.20f, 0.60f, 0.60f } },
		{ .name = kPresetCenter50, .uv = { 0.25f, 0.25f, 0.5f, 0.5f } },
		{ .name = kPresetCenter40, .uv = { 0.30f, 0.30f, 0.4f, 0.4f } },
		{ .name = kPresetCenter30, .uv = { 0.35f, 0.35f, 0.3f, 0.3f } },
		{ .name = kPresetNasalConvergence50,
			.uv = { 0.5f, 0.25f, 0.5f, 0.5f },
			.rightUV = Util::Subrect::UVRegion{ 0.0f, 0.25f, 0.5f, 0.5f } },
		{ .name = kPresetNasalConvergence60,
			.uv = { 0.4f, 0.2f, 0.6f, 0.6f },
			.rightUV = Util::Subrect::UVRegion{ 0.0f, 0.2f, 0.6f, 0.6f } },
		{ .name = kPresetNasalConvergence70,
			.uv = { 0.3f, 0.15f, 0.7f, 0.7f },
			.rightUV = Util::Subrect::UVRegion{ 0.0f, 0.15f, 0.7f, 0.7f } },
	}, kPresetCenter75);
	// PostPostLoad runs after settings load, so a user with an older, shorter
	// persisted preset list (from before these names existed) still sees every
	// current preset in the DrawEditor dropdown, not just whichever ones they
	// happened to click as buttons.
	subrectController.MaterializeNewDefaults();
	stl::write_vfunc<0x1, UICompositeRenderHook>(RE::VTABLE_BSImagespaceShaderCopyDynamicFetchDisabled[3]);
}

void FoveatedRender::UICompositeRenderHook::thunk(void* imageSpaceShader, RE::BSTriShape* shape, RE::ImageSpaceEffectParam* param)
{
	auto& upscaling = globals::features::upscaling;
	const bool sharpen = FoveatedRenderImpl::Bridge::IsRouteActive() &&
		upscaling.GetUpscaleMethod() == Upscaling::UpscaleMethod::kDLSS;
	if (sharpen && !upscaling.settings.sharpnessAfterNR)
		FoveatedRenderImpl::Postprocess::ApplyDlssSharpening(upscaling);
	NeuralRendering::ApplyFoveatedLdr();
	if (sharpen && upscaling.settings.sharpnessAfterNR)
		FoveatedRenderImpl::Postprocess::ApplyDlssSharpening(upscaling);
	func(imageSpaceShader, shape, param);
}

void FoveatedRender::ClearShaderCache()
{
	FoveatedRenderImpl::Postprocess::Reset();
	FoveatedRenderImpl::Core::ClearShaderCache();
	NeuralRendering::Renderer::Instance().ClearShaderCache();
	FoveatedRenderImpl::Core::ClearResources();
}

// ============================================================================
// Settings I/O — driven from Upscaling::Save/LoadSettings under a nested key
// ============================================================================

void FoveatedRender::SaveSettings(json& o_json)
{
	o_json = settings;
	subrectController.SaveSettings(o_json);
}

void FoveatedRender::LoadSettings(const json& o_json)
{
	settings = o_json;
	// Util::Subrect::Controller::LoadSettings takes `const json&` (Subrect.h:68)
	// so no const_cast is needed — keeping it would imply mutation that never
	// happens.
	subrectController.LoadSettings(o_json);
	ClampSettings();
}

void FoveatedRender::RestoreDefaultSettings()
{
	settings = {};
	ResetAdaptiveState();
	ClampSettings();
}

bool FoveatedRender::ApplyNeuralRenderingPreset(std::string_view presetName)
{
	uint preset = 0;
	if (presetName == "Default")
		preset = 0;
	else if (presetName == "Balanced")
		preset = 1;
	else if (presetName == "Fabric Detail")
		preset = 2;
	else if (presetName == "Natural")
		preset = 3;
	else if (presetName == "Strong")
		preset = 4;
	else if (presetName == "Custom")
		preset = 5;
	else
		return false;

	settings.neuralRenderingPreset = preset;
	switch (preset) {
	case 0:
		settings.neuralRenderingIntensity = Settings{}.neuralRenderingIntensity;
		settings.neuralRenderingLocalTone = Settings{}.neuralRenderingLocalTone;
		settings.neuralRenderingLocalStructure = Settings{}.neuralRenderingLocalStructure;
		settings.neuralRenderingSkinStructure = -1.0f;
		settings.neuralRenderingStyle = 0;
		settings.neuralRenderingAutoMask = true;
		break;
	case 1:
		settings.neuralRenderingIntensity = 1.0f;
		settings.neuralRenderingLocalTone = 1.0f;
		settings.neuralRenderingLocalStructure = 1.0f;
		settings.neuralRenderingSkinStructure = 1.0f;
		break;
	case 2:
		settings.neuralRenderingIntensity = 1.35f;
		settings.neuralRenderingLocalTone = 0.9f;
		settings.neuralRenderingLocalStructure = 1.6f;
		settings.neuralRenderingSkinStructure = 1.15f;
		break;
	case 3:
		settings.neuralRenderingIntensity = 0.8f;
		settings.neuralRenderingLocalTone = 0.75f;
		settings.neuralRenderingLocalStructure = 0.9f;
		settings.neuralRenderingSkinStructure = 0.9f;
		break;
	case 4:
		settings.neuralRenderingIntensity = 1.75f;
		settings.neuralRenderingLocalTone = 1.25f;
		settings.neuralRenderingLocalStructure = 1.5f;
		settings.neuralRenderingSkinStructure = 1.3f;
		break;
	case 5:
		break;
	default:
		return false;
	}
	return true;
}

void FoveatedRender::ClampSettings()
{
	settings.enabled = std::min(settings.enabled, 1u);
	settings.dlssMode = std::min(settings.dlssMode, 1u);
	settings.stretchMode = std::min(settings.stretchMode, 2u);
	settings.debugVisualize = std::min(settings.debugVisualize, 1u);
	settings.peripheryAAMode = std::min(settings.peripheryAAMode, 1u);
	settings.subrectBlendMode = std::min(settings.subrectBlendMode, 2u);
	settings.subrectMaskMode = std::min(settings.subrectMaskMode, 1u);
	settings.peripheryBlurRadius = std::clamp(settings.peripheryBlurRadius, 0.5f, 4.0f);
	settings.peripheryTemporalAlpha = std::clamp(settings.peripheryTemporalAlpha, 0.05f, 0.5f);
	settings.subrectFeatherWidth = std::clamp(settings.subrectFeatherWidth, 2.0f, 128.0f);
	settings.subrectFalloffCurve = std::clamp(settings.subrectFalloffCurve, 0.5f, 2.0f);
	settings.subrectDitherStrength = std::clamp(settings.subrectDitherStrength, 0.0f, 2.0f);
	if (settings.neuralRenderingModelResolution != 33 &&
		settings.neuralRenderingModelResolution != 50 &&
		settings.neuralRenderingModelResolution != 70 &&
		settings.neuralRenderingModelResolution != 75 &&
		settings.neuralRenderingModelResolution != 80 &&
		settings.neuralRenderingModelResolution != 85 &&
		settings.neuralRenderingModelResolution != 90 &&
		settings.neuralRenderingModelResolution != 95 &&
		settings.neuralRenderingModelResolution != 100)
		settings.neuralRenderingModelResolution = settings.neuralRenderingModelResolution < 33 ? 33 :
			(settings.neuralRenderingModelResolution < 70 ? 70 :
				100);
	settings.neuralRenderingPreset = std::min(settings.neuralRenderingPreset, 5u);
	settings.neuralRenderingIntensity = std::clamp(settings.neuralRenderingIntensity, 0.0f, 2.0f);
	settings.neuralRenderingLocalTone = std::clamp(settings.neuralRenderingLocalTone, 0.0f, 2.0f);
	settings.neuralRenderingLocalStructure = std::clamp(settings.neuralRenderingLocalStructure, 0.0f, 2.0f);
	settings.neuralRenderingSkinStructure = std::clamp(settings.neuralRenderingSkinStructure, -1.0f, 2.0f);
	settings.neuralRenderingStyle = std::min(settings.neuralRenderingStyle, 3u);
	settings.neuralRenderingPreUpscale = 0;
	settings.neuralRenderingPreUpscaleCropCoverage = 0;
	settings.neuralRenderingTemporalReuseCadence = 0;
	settings.neuralRenderingTemporalDepthThreshold = 0.05f;
	settings.neuralRenderingTemporalColorTolerance = 0.08f;
	settings.neuralRenderingTemporalReuseResetAfterSkip = false;
	settings.neuralRenderingResolveMode = std::min(settings.neuralRenderingResolveMode, 1u);
	settings.neuralRenderingMultiPass = std::min(settings.neuralRenderingMultiPass, 2u);
	settings.neuralRenderingSecondPassContribution = std::isfinite(settings.neuralRenderingSecondPassContribution) ?
		std::clamp(settings.neuralRenderingSecondPassContribution, 0.0f, 1.0f) : 1.0f;
	settings.neuralRenderingSecondPassCropReduction = std::min(settings.neuralRenderingSecondPassCropReduction, 50u);
	if (settings.neuralRenderingSecondPassCropReductionX == 0 && settings.neuralRenderingSecondPassCropReductionY == 0 &&
		settings.neuralRenderingSecondPassCropReduction != 0) {
		settings.neuralRenderingSecondPassCropReductionX = settings.neuralRenderingSecondPassCropReduction;
		settings.neuralRenderingSecondPassCropReductionY = settings.neuralRenderingSecondPassCropReduction;
	}
	settings.neuralRenderingSecondPassCropReduction = 0;
	settings.neuralRenderingSecondPassCropReductionX = std::min(settings.neuralRenderingSecondPassCropReductionX, 50u);
	settings.neuralRenderingSecondPassCropReductionY = std::min(settings.neuralRenderingSecondPassCropReductionY, 50u);
	settings.neuralRenderingSecondPassBlendMode = std::min(settings.neuralRenderingSecondPassBlendMode, 2u);
	settings.neuralRenderingSecondPassMaskMode = std::min(settings.neuralRenderingSecondPassMaskMode, 1u);
	settings.neuralRenderingSecondPassFeatherWidth = std::clamp(settings.neuralRenderingSecondPassFeatherWidth, 2.0f, 128.0f);
	settings.neuralRenderingSecondPassFalloffCurve = std::clamp(settings.neuralRenderingSecondPassFalloffCurve, 0.5f, 2.0f);
	settings.neuralRenderingSecondPassDitherStrength = std::clamp(settings.neuralRenderingSecondPassDitherStrength, 0.0f, 2.0f);
	switch (settings.neuralRenderingAdaptiveRefreshHz) {
	case 70:
	case 72:
	case 80:
	case 90:
		break;
	default:
		settings.neuralRenderingAdaptiveRefreshHz = 80;
		break;
	}
	if (settings.neuralRenderingAdaptiveBudgetMode > 2)
		settings.neuralRenderingAdaptiveBudgetMode = 0;
	// Migrate prior custom-FPS settings to the new explicit budget selector.
	if (settings.neuralRenderingAdaptiveBudgetMode == 0 && settings.neuralRenderingAdaptiveTargetFps != 0)
		settings.neuralRenderingAdaptiveBudgetMode = 1;
	if (settings.neuralRenderingAdaptiveTargetFps != 0)
		settings.neuralRenderingAdaptiveTargetFps = std::clamp(settings.neuralRenderingAdaptiveTargetFps, 15u, 60u);
	settings.neuralRenderingAdaptiveTargetFrameTimeMs = std::isfinite(settings.neuralRenderingAdaptiveTargetFrameTimeMs) ?
		std::clamp(settings.neuralRenderingAdaptiveTargetFrameTimeMs, 5.0f, 50.0f) : 20.0f;
	switch (settings.neuralRenderingAdaptiveMinimumResolution) {
	case 70:
	case 75:
	case 80:
	case 85:
	case 90:
	case 95:
	case 100:
		break;
	default:
		settings.neuralRenderingAdaptiveMinimumResolution = 70;
		break;
	}
	settings.neuralRenderingAdaptiveDownshiftFrames = std::clamp(settings.neuralRenderingAdaptiveDownshiftFrames, 1u, 16u);
	settings.neuralRenderingAdaptiveUpshiftFrames = std::clamp(settings.neuralRenderingAdaptiveUpshiftFrames, 4u, 64u);
	settings.neuralRenderingAdaptiveMinimumDwellFrames = std::clamp(settings.neuralRenderingAdaptiveMinimumDwellFrames, 4u, 240u);
	settings.neuralRenderingAdaptiveGuardTimeMs = std::clamp(settings.neuralRenderingAdaptiveGuardTimeMs, 0.0f, 5.0f);
	switch (settings.neuralRenderingAdaptiveCropMinimumCoverage) {
	case 30:
	case 35:
	case 40:
	case 45:
	case 50:
	case 55:
	case 60:
	case 65:
	case 70:
	case 75:
	case 80:
		break;
	default:
		settings.neuralRenderingAdaptiveCropMinimumCoverage = 30;
		break;
	}
	switch (settings.neuralRenderingAdaptiveCropMaximumCoverage) {
	case 30:
	case 35:
	case 40:
	case 45:
	case 50:
	case 55:
	case 60:
	case 65:
	case 70:
	case 75:
	case 80:
	case 85:
		break;
	default:
		settings.neuralRenderingAdaptiveCropMaximumCoverage = 85;
		break;
	}
	// Keep the configured ladder ordered. If a user raises the minimum above
	// the saved maximum, preserving the requested floor is the least surprising
	// repair and avoids a controller with an empty legal range.
	if (settings.neuralRenderingAdaptiveCropMaximumCoverage < settings.neuralRenderingAdaptiveCropMinimumCoverage)
		settings.neuralRenderingAdaptiveCropMaximumCoverage = settings.neuralRenderingAdaptiveCropMinimumCoverage;
	settings.neuralRenderingAdaptiveCropDownshiftFrames = std::clamp(settings.neuralRenderingAdaptiveCropDownshiftFrames, 1u, 16u);
	settings.neuralRenderingAdaptiveCropUpshiftFrames = std::clamp(settings.neuralRenderingAdaptiveCropUpshiftFrames, 8u, 240u);
	settings.neuralRenderingAdaptiveCropMinimumDwellFrames = std::clamp(settings.neuralRenderingAdaptiveCropMinimumDwellFrames, 8u, 600u);
	settings.neuralRenderingAdaptiveCropTransitionFrames = std::clamp(settings.neuralRenderingAdaptiveCropTransitionFrames, 2u, 24u);
	settings.neuralRenderingAdaptiveQualityOrder = std::min(settings.neuralRenderingAdaptiveQualityOrder, 5u);
	settings.neuralRenderingEyeTrackedPolicy = std::min(settings.neuralRenderingEyeTrackedPolicy, 1u);
	settings.neuralRenderingEyeTrackedSmoothingMs = std::isfinite(settings.neuralRenderingEyeTrackedSmoothingMs) ?
		std::clamp(settings.neuralRenderingEyeTrackedSmoothingMs, 0.0f,
			settings.neuralRenderingEyeTrackedPolicy == 1 ? 100.0f : 250.0f) : 0.0f;
	settings.neuralRenderingEyeTrackedCatchupMs = std::isfinite(settings.neuralRenderingEyeTrackedCatchupMs) ?
		std::clamp(settings.neuralRenderingEyeTrackedCatchupMs, 0.0f, 30.0f) : 8.0f;
	settings.neuralRenderingEyeTrackedDeadbandPixels = std::min(settings.neuralRenderingEyeTrackedDeadbandPixels, 32u);
	settings.neuralRenderingEyeTrackedHoldMs = std::min(settings.neuralRenderingEyeTrackedHoldMs, 200u);
	settings.neuralRenderingEyeTrackedPredictionMs = std::isfinite(settings.neuralRenderingEyeTrackedPredictionMs) ?
		std::clamp(settings.neuralRenderingEyeTrackedPredictionMs, 0.0f, 15.0f) : 0.0f;
	settings.neuralRenderingEyeTrackedQuantizationPixels = std::clamp(settings.neuralRenderingEyeTrackedQuantizationPixels, 0u, 64u);
	settings.neuralRenderingEyeTrackedCropPaddingPixels = std::clamp(settings.neuralRenderingEyeTrackedCropPaddingPixels, 0u, 128u);
	settings.neuralRenderingNRContribution = std::isfinite(settings.neuralRenderingNRContribution) ?
		std::clamp(settings.neuralRenderingNRContribution, 0.0f, 1.0f) : 1.0f;
	settings.neuralRenderingDetailBoost = std::isfinite(settings.neuralRenderingDetailBoost) ?
		std::clamp(settings.neuralRenderingDetailBoost, 1.0f, 2.0f) : 1.0f;
	// Preset clamping reads from Upscaling::Settings now.
	auto& sharedPreset = globals::features::upscaling.settings.presetDLSS;
	sharedPreset = std::min(sharedPreset, 5u);
	if (!IsPresetCompatibleWithMode(sharedPreset)) {
		sharedPreset = 3;  // Fall back to L
	}
}

// ============================================================================
// Activation + accessors
// ============================================================================

bool FoveatedRender::IsActive() const
{
	// Gate on DLSS/FSR being the *selected* method, not just available
	// (IsRuntimeSupported): otherwise foveation and its SSR consumer run under
	// TAA/None and the route derefs unallocated upscaler resources — the crash
	// seen under RenderDoc, whose DX12 swapchain disables DLSS.
	if (!enabledAtBoot || !IsRuntimeSupported())
		return false;
	const auto method = globals::features::upscaling.GetUpscaleMethod();
	if (method != Upscaling::UpscaleMethod::kDLSS && method != Upscaling::UpscaleMethod::kFSR)
		return false;

	// Full Eye is a supported no-crop mode.  It still uses the per-eye route so
	// DLSSNR receives isolated left/right guides; the route simply skips the
	// background stretch and subrect copy-back work in ExecuteDefaultMode.
	return true;
}

bool FoveatedRender::ShouldForceVisualize() const
{
	using namespace std::chrono_literals;
	return std::chrono::steady_clock::now() - lastDragTime < 3s;
}

bool FoveatedRender::IsRuntimeSupported() const
{
	// FSR's host path has no adapter/runtime prerequisite, so VR alone is
	// sufficient to enable the option -- IsActive() is what actually gates
	// on the *selected* method (kDLSS/kFSR) being one the route supports.
	return globals::game::isVR;
}

void FoveatedRender::ResetAdaptiveState()
{
	const bool cropWasActive = adaptiveCropController.IsRuntimeActive();
	adaptiveController.Reset();
	adaptiveCropController.Reset();
	adaptivePassController.Reset();
	adaptiveCropDiagnosticGeneration = UINT64_MAX;
	if (cropWasActive)
		FoveatedRenderImpl::Core::ResetAdaptiveCropHandoff();
}

bool FoveatedRender::IsEyeTrackedFoveationEnabled() const
{
	// Report crop-center ownership for the UI/diagnostics. Adaptive crop changes
	// only the extent, then the gaze provider recenters that extent per eye.
	return settings.neuralRenderingEyeTrackedFoveation ||
		(globals::game::isVR && globals::features::vr.stereoOpt.settings.useEyeTracking);
}

void FoveatedRender::UpdateAdaptiveState(std::uint32_t frame, bool routeEligible)
{
	const auto& nrRenderer = NeuralRendering::Renderer::Instance();
	const auto& streamline = globals::features::upscaling.streamline;
	const bool recentDLSSFailure = streamline.lastDLSSFailureFrame != UINT32_MAX &&
		frame >= streamline.lastDLSSFailureFrame &&
		frame - streamline.lastDLSSFailureFrame <= 1;
	const bool runtimeHealthy = !nrRenderer.IsFailureLatched() && !recentDLSSFailure;
	const auto method = globals::features::upscaling.GetUpscaleMethod();
	const bool nrEligible = routeEligible && IsActive() &&
		method == Upscaling::UpscaleMethod::kDLSS &&
		GetDlssMode() == DlssMode::kDefault && settings.neuralRenderingEnabled &&
		!globals::features::upscaling.IsFrameGenerationActive() &&
		!globals::features::openNRCapture.settings.enableCapture &&
		runtimeHealthy;
	const auto leftUV = subrectController.GetUV();
	const auto rightUV = subrectController.GetRightEyeUV();
	const bool geometryCompatible = std::abs(leftUV.w - rightUV.w) <= 0.0005f &&
		std::abs(leftUV.h - rightUV.h) <= 0.0005f;
	const std::uint32_t configuredCoverage = static_cast<std::uint32_t>(std::lround(std::clamp(
		std::min({ leftUV.w, leftUV.h, rightUV.w, rightUV.h }) * 100.0f, 0.0f, 100.0f)));
	const bool eyeTrackingOwnsCrop = IsEyeTrackedFoveationEnabled();
	const bool adaptiveRouteEnabled = nrEligible && settings.neuralRenderingAdaptiveEnabled;
	const auto requestedPassMode = std::min(settings.neuralRenderingMultiPass, 2u);
	const bool cropPolicyAvailable = adaptiveRouteEnabled && settings.neuralRenderingAdaptiveCropEnabled &&
		geometryCompatible && configuredCoverage >= 30;
	const auto effectiveCropMaximum = std::min(settings.neuralRenderingAdaptiveCropMaximumCoverage, configuredCoverage);
	const auto effectiveCropMinimum = std::min(settings.neuralRenderingAdaptiveCropMinimumCoverage, effectiveCropMaximum);
	const bool cropCanDownshift = cropPolicyAvailable &&
		!FoveatedRenderImpl::Core::vrSubrectFixedEnvelopeRejected &&
		!FoveatedRenderImpl::Core::vrSubrectNeuralFixedEnvelopeRejected &&
		(adaptiveCropController.IsRuntimeActive() ?
			adaptiveCropController.ActiveCoverage() > adaptiveCropController.MinimumCoverage() :
		effectiveCropMaximum > effectiveCropMinimum);
	const auto selectedPassMode = adaptivePassController.ActiveMode(requestedPassMode);
	const bool passesCanDownshift = adaptiveRouteEnabled && selectedPassMode > 0;
	const bool nrCanDownshift = adaptiveRouteEnabled && !adaptiveController.IsAtMinimum();
	const auto downshiftAxis = NeuralRendering::SelectAdaptiveDownshift(
		settings.neuralRenderingAdaptiveQualityOrder, passesCanDownshift, cropCanDownshift, nrCanDownshift);
	const bool passesCanUpshift = adaptiveRouteEnabled && adaptivePassController.CanIncrease(requestedPassMode);
	const bool cropCanUpshift = cropPolicyAvailable && adaptiveCropController.IsRuntimeActive() &&
		adaptiveCropController.ActiveCoverage() < adaptiveCropController.MaximumCoverage();
	const bool nrCanUpshift = adaptiveRouteEnabled && !adaptiveController.IsAtMaximum();
	const auto upshiftAxis = NeuralRendering::SelectAdaptiveUpshift(
		settings.neuralRenderingAdaptiveQualityOrder, passesCanUpshift, cropCanUpshift, nrCanUpshift);
	const auto stageReadiness = NeuralRendering::ResolveAdaptiveStageReadiness(
		false, false, selectedPassMode, requestedPassMode);
	const auto activeNRForReadiness = adaptiveController.ActiveResolution();
	const auto higherNR = AdjacentAdaptiveResolution(activeNRForReadiness, true);
	const auto lowerNR = AdjacentAdaptiveResolution(activeNRForReadiness, false);
	const auto& preNRRenderer = NeuralRendering::Renderer::PreUpscaleInstance();
	auto isAdaptiveTierReady = [&](std::uint32_t resolution) {
		const bool preReady = !stageReadiness.preStageRequired || preNRRenderer.IsAdaptiveTierReady(resolution, 1);
		const bool postReady = !stageReadiness.postStageRequired ||
			nrRenderer.IsAdaptiveTierReady(resolution, stageReadiness.postPassCapacity);
		return preReady && postReady;
	};
	// Feature 18 creation is not a frame-safe operation on this route. The
	// renderer prewarms the adjacent tier while the current tier is running;
	// do not let the controller expose a tier until both eyes and its native
	// handle are resident. This turns an on-demand multi-hundred-ms create into
	// a quiet wait on the current image instead of a stale/reprojected frame.
	const bool nrUpshiftReady = adaptiveController.IsAtMaximum() || isAdaptiveTierReady(higherNR);
	const bool nrDownshiftReady = adaptiveController.IsAtMinimum() || isAdaptiveTierReady(lowerNR);

	NeuralRendering::AdaptiveController::Config nrConfig;
	nrConfig.enabled = settings.neuralRenderingAdaptiveEnabled;
	nrConfig.memoryPressure = streamline.IsVRAMPressure();
	nrConfig.allowDownshift = downshiftAxis == NeuralRendering::AdaptiveQualityAxis::Resolution &&
		!adaptiveCropController.IsTransitioning() && nrDownshiftReady;
	nrConfig.allowUpshift = upshiftAxis == NeuralRendering::AdaptiveQualityAxis::Resolution &&
		!adaptiveCropController.IsTransitioning() && !nrRenderer.IsRecoveryLimited() &&
		!streamline.IsVRAMPressure() && nrUpshiftReady;
	nrConfig.refreshHz = settings.neuralRenderingAdaptiveRefreshHz;
	nrConfig.targetFps = settings.neuralRenderingAdaptiveBudgetMode == 1 ? settings.neuralRenderingAdaptiveTargetFps : 0u;
	nrConfig.targetFrameTimeMs = settings.neuralRenderingAdaptiveBudgetMode == 2 ?
		settings.neuralRenderingAdaptiveTargetFrameTimeMs : 0.0f;
	nrConfig.minimumResolution = settings.neuralRenderingAdaptiveMinimumResolution;
	nrConfig.maximumResolution = settings.neuralRenderingModelResolution;
	nrConfig.downshiftFrames = settings.neuralRenderingAdaptiveDownshiftFrames;
	nrConfig.upshiftFrames = settings.neuralRenderingAdaptiveUpshiftFrames;
	nrConfig.minimumDwellFrames = settings.neuralRenderingAdaptiveMinimumDwellFrames;
	nrConfig.guardTimeMs = settings.neuralRenderingAdaptiveGuardTimeMs;

	const auto previousNR = adaptiveController.ActiveResolution();
	const auto previousNRTarget = adaptiveController.TargetResolution();
	float workloadMs = -1.0f;
	float gpuWorkMs = -1.0f;
	float activeSubmitMs = -1.0f;
	static std::uint32_t timingFrame = UINT32_MAX;
	static std::uint32_t sampledEngineFrame = UINT32_MAX;
	if (globals::game::isVR && nrEligible && frame != sampledEngineFrame) {
		sampledEngineFrame = frame;
		if (auto* compositor = RE::BSOpenVR::GetIVRCompositor()) {
			vr::Compositor_FrameTiming timing{};
			timing.m_nSize = sizeof(timing);
			if (compositor->GetFrameTiming(&timing) && timing.m_nFrameIndex != timingFrame) {
				timingFrame = timing.m_nFrameIndex;
				const float gpuMs = timing.m_flPreSubmitGpuMs + timing.m_flPostSubmitGpuMs;
				const float cpuMs = timing.m_flNewFrameReadyMs - timing.m_flNewPosesReadyMs;
				gpuWorkMs = gpuMs;
				activeSubmitMs = cpuMs;
				if (std::isfinite(gpuMs) && gpuMs > 0.0f && std::isfinite(cpuMs) && cpuMs >= 0.0f)
					workloadMs = std::max(gpuMs, cpuMs);
			}
		}
	}
	if (streamline.IsVRAMPressure())
		workloadMs = std::max(workloadMs, 1.3f * adaptiveController.ApplicationDeadlineMs());
	const auto previousMemoryCeiling = adaptiveController.MemoryCeiling();
	adaptiveController.Update(frame, nrConfig, nrEligible, workloadMs);
	if (previousMemoryCeiling != adaptiveController.MemoryCeiling())
		logger::info("[DLSSNR][MEMORY] ceiling {}% -> {}% active={}%; higher tiers held until Neural Rendering Reset or restart",
			previousMemoryCeiling, adaptiveController.MemoryCeiling(), adaptiveController.ActiveResolution());
	const bool adaptiveNRActive = nrEligible && adaptiveController.IsEnabled();
	adaptivePassController.Update(frame, requestedPassMode, adaptiveNRActive,
		downshiftAxis == NeuralRendering::AdaptiveQualityAxis::Passes,
		upshiftAxis == NeuralRendering::AdaptiveQualityAxis::Passes,
		adaptiveController.LastSampleOverBudget(), adaptiveController.LastSampleHadHeadroom(),
		settings.neuralRenderingAdaptiveDownshiftFrames, settings.neuralRenderingAdaptiveUpshiftFrames,
		settings.neuralRenderingAdaptiveMinimumDwellFrames);
	if (nrEligible && previousNR != adaptiveController.ActiveResolution()) {
		logger::info("[DLSSNR] adaptive NR handoff {}% -> {}% alpha={:.2f} work={:.2f}/{:.2f}ms reason={}",
			previousNR, adaptiveController.ActiveResolution(), adaptiveController.HandoffAlpha(),
			adaptiveController.SmoothedFrameTimeMs(), adaptiveController.ApplicationDeadlineMs(), adaptiveController.DecisionReason());
	}

	NeuralRendering::AdaptiveCropController::Config cropConfig;
	cropConfig.enabled = settings.neuralRenderingAdaptiveCropEnabled;
	cropConfig.hold = FoveatedRenderImpl::Core::vrSubrectFixedEnvelopeRejected ||
		FoveatedRenderImpl::Core::vrSubrectNeuralFixedEnvelopeRejected;
	cropConfig.maximumCoverage = settings.neuralRenderingAdaptiveCropMaximumCoverage;
	cropConfig.minimumCoverage = settings.neuralRenderingAdaptiveCropMinimumCoverage;
	cropConfig.downshiftFrames = settings.neuralRenderingAdaptiveCropDownshiftFrames;
	cropConfig.upshiftFrames = settings.neuralRenderingAdaptiveCropUpshiftFrames;
	cropConfig.minimumDwellFrames = settings.neuralRenderingAdaptiveCropMinimumDwellFrames;
	cropConfig.transitionFrames = settings.neuralRenderingAdaptiveCropTransitionFrames;

	const bool cropWasActive = adaptiveCropController.IsRuntimeActive();
	const auto previousCrop = adaptiveCropController.ActiveCoverage();
	const auto previousCropTarget = adaptiveCropController.TargetCoverage();
	const auto previousRenderCrop = adaptiveCropController.RenderCoverage();
	adaptiveCropController.Update(frame, cropConfig, adaptiveNRActive && geometryCompatible,
		configuredCoverage, geometryCompatible,
		downshiftAxis == NeuralRendering::AdaptiveQualityAxis::Crop,
		upshiftAxis == NeuralRendering::AdaptiveQualityAxis::Crop,
		adaptiveController.IsTransitioning(), adaptiveController.LastSampleOverBudget(),
		adaptiveController.LastSampleHadHeadroom());
	if (cropWasActive && !adaptiveCropController.IsRuntimeActive())
		FoveatedRenderImpl::Core::ResetAdaptiveCropHandoff();
	const auto currentCrop = adaptiveCropController.ActiveCoverage();
	const auto currentRenderCrop = adaptiveCropController.RenderCoverage();
	const auto currentNR = adaptiveController.ActiveResolution();
	static std::uint32_t lastBudgetLog = UINT32_MAX;
	if (settings.neuralRenderingAdaptiveEnabled && frame % 300 == 0 && frame != lastBudgetLog) {
		lastBudgetLog = frame;
		logger::info("[DLSSNR][BUDGET] frame={} source=steamvr-workload fresh={} workMs={:.2f} averageMs={:.2f} deadlineMs={:.2f} pressure={} headroom={} nr={} crop={} cropHeld={} nrTransition={} cropTransition={} nrUpReady={} nrDownReady={} gpuMs={:.2f} activeSubmitMs={:.2f}",
			frame, workloadMs > 0.0f, workloadMs, adaptiveController.SmoothedFrameTimeMs(),
			adaptiveController.ApplicationDeadlineMs(), adaptiveController.LastSampleOverBudget(),
			adaptiveController.LastSampleHadHeadroom(), currentNR, currentCrop, cropConfig.hold,
			adaptiveController.IsTransitioning(), adaptiveCropController.IsTransitioning(), nrUpshiftReady,
			nrDownshiftReady, gpuWorkMs, activeSubmitMs);
	}
	const auto effectiveLeftUV = GetEffectiveLeftUV();
	const auto effectiveRightUV = GetEffectiveRightUV();
	if (adaptiveCropController.LastResetReason() != NeuralRendering::AdaptiveCropController::ResetReason::None &&
		adaptiveCropDiagnosticGeneration != adaptiveCropController.Generation()) {
		adaptiveCropDiagnosticGeneration = adaptiveCropController.Generation();
		const char* resourceMode = FoveatedRenderImpl::Core::vrSubrectResourceMode ==
			FoveatedRenderImpl::Core::SubrectResourceMode::FixedEnvelope ? "fixed-envelope" : "exact-cache";
		logger::info("[DLSSNR][ADAPTIVE] frame={} generation={} reset={} eligible={} nrEligible={} cropEligible={} eyeTracking={} geometry={} configuredCrop={} adaptiveCropMax={} prevNR={} prevNRTarget={} activeNR={} targetNR={} prevCrop={} prevCropTarget={} activeCrop={} targetCrop={} effectiveLUV=({:.3f},{:.3f},{:.3f},{:.3f}) effectiveRUV=({:.3f},{:.3f},{:.3f},{:.3f}) validOut={}x{} validIn={}x{} envelopeOut={}x{} envelopeIn={}x{} resourceMode={} creates={} reuses={} frees={} envelopeChecks={} fallbackEntries={} fallbackEvictions={} neuralFallbackEntries={}",
			frame, adaptiveCropController.Generation(),
			NeuralRendering::AdaptiveCropController::ResetReasonName(adaptiveCropController.LastResetReason()),
			adaptiveNRActive && geometryCompatible, nrEligible, cropPolicyAvailable, eyeTrackingOwnsCrop,
			geometryCompatible, configuredCoverage, cropConfig.maximumCoverage, previousNR, previousNRTarget, currentNR, adaptiveController.TargetResolution(),
			previousCrop, previousCropTarget, currentCrop, adaptiveCropController.TargetCoverage(),
			effectiveLeftUV.x, effectiveLeftUV.y, effectiveLeftUV.w, effectiveLeftUV.h,
			effectiveRightUV.x, effectiveRightUV.y, effectiveRightUV.w, effectiveRightUV.h,
			FoveatedRenderImpl::Core::vrSubrectValidOutW, FoveatedRenderImpl::Core::vrSubrectValidOutH,
			FoveatedRenderImpl::Core::vrSubrectValidInW, FoveatedRenderImpl::Core::vrSubrectValidInH,
			FoveatedRenderImpl::Core::vrSubrectOutW, FoveatedRenderImpl::Core::vrSubrectOutH,
			FoveatedRenderImpl::Core::vrSubrectInW, FoveatedRenderImpl::Core::vrSubrectInH,
			resourceMode, FoveatedRenderImpl::Core::vrSubrectResourceCreates,
			FoveatedRenderImpl::Core::vrSubrectResourceReuses, FoveatedRenderImpl::Core::vrSubrectResourceFrees,
			FoveatedRenderImpl::Core::vrSubrectEnvelopeValidations, FoveatedRenderImpl::Core::vrSubrectFallbackEntries,
			FoveatedRenderImpl::Core::vrSubrectFallbackEvictions,
			FoveatedRenderImpl::Core::vrSubrectNeuralFallbackEntries);
	}
	if (adaptiveCropController.IsRuntimeActive() && previousCrop != currentCrop) {
		// ActiveCoverage changes when the controller makes a new decision, while
		// RenderCoverage remains on the old UV geometry until the handoff is
		// complete. Do not invalidate temporal history here: the renderer is still
		// sampling the old crop geometry during this part of the transition.
		logger::info("[DLSSNR] adaptive crop decision {}% -> {}% render={} -> {}% alpha={:.2f} frame={} generation={} valid={}x{} envelope={}x{}",
			previousCrop, currentCrop, previousRenderCrop, currentRenderCrop,
			adaptiveCropController.HandoffAlpha(), frame,
			adaptiveCropController.Generation(), FoveatedRenderImpl::Core::vrSubrectValidOutW,
			FoveatedRenderImpl::Core::vrSubrectValidOutH, FoveatedRenderImpl::Core::vrSubrectOutW,
			FoveatedRenderImpl::Core::vrSubrectOutH);
	}
	if (adaptiveCropController.IsRuntimeActive() && previousRenderCrop != currentRenderCrop) {
		// The fixed envelope keeps the native resource identity stable, but the
		// crop origin/extent changes the meaning of every temporal sample. Reset
		// only when RenderCoverage commits the new UV geometry, so Feature 18 and
		// both eyes cannot blend history produced for the previous crop tier.
		FoveatedRenderImpl::Core::InvalidateTemporalState();
		logger::info("[DLSSNR] adaptive crop geometry commit {}% -> {}% decision={} -> {}% frame={} generation={} valid={}x{} envelope={}x{}",
			previousRenderCrop, currentRenderCrop, previousCrop, currentCrop, frame,
			adaptiveCropController.Generation(), FoveatedRenderImpl::Core::vrSubrectValidOutW,
			FoveatedRenderImpl::Core::vrSubrectValidOutH, FoveatedRenderImpl::Core::vrSubrectOutW,
			FoveatedRenderImpl::Core::vrSubrectOutH);
	}
}

Util::Subrect::UVRegion FoveatedRender::GetEffectiveLeftUV() const
{
	if (!adaptiveCropController.IsRuntimeActive())
		return subrectController.GetUV();
	const float coverage = std::clamp(
		static_cast<float>(adaptiveCropController.RenderCoverage()) / 100.0f, 0.01f, 1.0f);
	const bool nasalConvergence = IsNasalConvergenceGeometry(
		subrectController.GetUV(), subrectController.GetRightEyeUV());
	return MakeAdaptiveCropUV(coverage, true, nasalConvergence);
}

Util::Subrect::UVRegion FoveatedRender::GetEffectiveRightUV() const
{
	if (!adaptiveCropController.IsRuntimeActive())
		return subrectController.GetRightEyeUV();
	const float coverage = std::clamp(
		static_cast<float>(adaptiveCropController.RenderCoverage()) / 100.0f, 0.01f, 1.0f);
	const bool nasalConvergence = IsNasalConvergenceGeometry(
		subrectController.GetUV(), subrectController.GetRightEyeUV());
	return MakeAdaptiveCropUV(coverage, false, nasalConvergence);
}

FoveatedRender::DlssMode FoveatedRender::GetDlssMode() const
{
	if (globals::features::upscaling.GetUpscaleMethod() == Upscaling::UpscaleMethod::kFSR)
		return DlssMode::kDefault;
	return (DlssMode)std::min(settings.dlssMode, 1u);
}

FoveatedRender::FoveationProfile FoveatedRender::GetFoveationProfile() const
{
	FoveationProfile profile;
	if (!IsActive())
		return profile;

	const auto leftUV = GetEffectiveLeftUV();
	const auto rightUV = GetEffectiveRightUV();

	// Map the rectangular subrect onto the centered superellipse the mask helper expects: vertical
	// extent drives coverageScale (radiusY = coverageScale/2), the rect aspect drives the horizontal
	// stretch (radiusX = coverageScale * hScale/2). The mask carries one scale for both eyes (only
	// the center offset is per-eye), so size comes from the less-foveated (larger) extent of the two:
	// the center is the superset enclosing both eyes' full-quality regions, so neither eye's sharp
	// zone is ever foveated (min would shrink it below an eye's sharp region and foveate it). A
	// full eye therefore yields full coverage and disables foveation (the gate below).
	const float coverageH = std::max(leftUV.h, rightUV.h);
	const float coverageW = std::max(leftUV.w, rightUV.w);
	const float coverageScale = FoveatedCommon::ClampCenterScale(coverageH);

	// Availability keys off the clamped scale: if the larger eye rounds up to full coverage there is
	// nothing to foveate, leave the default (available == false).
	if (!FoveatedCommon::IsActiveCoverage(coverageScale))
		return profile;

	profile.available = true;
	profile.coverageScale = coverageScale;
	profile.centerHorizontalScale = FoveatedCommon::ClampCenterHorizontalScale(
		coverageH > 1e-4f ? coverageW / coverageH : 1.0f);
	profile.centerOffsets[0] = float2{ (leftUV.x + leftUV.w * 0.5f) - 0.5f, (leftUV.y + leftUV.h * 0.5f) - 0.5f };
	profile.centerOffsets[1] = float2{ (rightUV.x + rightUV.w * 0.5f) - 0.5f, (rightUV.y + rightUV.h * 0.5f) - 0.5f };
	return profile;
}

void FoveatedRender::LatchQualityMode()
{
	qualityModeAtBoot = std::clamp(globals::features::upscaling.settings.qualityMode, 1u, 4u);
}

uint FoveatedRender::GetActiveQualityMode() const
{
	return std::clamp(globals::features::upscaling.settings.qualityMode, 1u, 4u);
}

uint FoveatedRender::GetActivePresetDLSS() const
{
	return std::min(globals::features::upscaling.settings.presetDLSS, 5u);
}

float FoveatedRender::GetActiveSharpnessDLSS() const
{
	return Sharpening::Sanitize(globals::features::upscaling.settings.sharpnessDLSS);
}

float FoveatedRender::GetRenderScaleForQuality(uint qualityMode)
{
	return Upscaling::GetQualityModeRatio(qualityMode);
}

bool FoveatedRender::IsPresetCompatibleWithMode(uint presetIndex) const
{
	// Preset indices: 0=Default, 1=J, 2=K, 3=L, 4=M, 5=F
	// Faster mode: J(1) and K(2) are incompatible.
	if (GetDlssMode() == DlssMode::kFaster) {
		return presetIndex != 1 && presetIndex != 2;
	}
	return true;
}

void FoveatedRender::ClampPresetToMode()
{
	auto& sharedPreset = globals::features::upscaling.settings.presetDLSS;
	if (!IsPresetCompatibleWithMode(sharedPreset)) {
		sharedPreset = 3;  // Fall back to L
	}
}

// ============================================================================
// UI — FoveatedRender-specific knobs only. Quality / sharpness / preset /
// Streamline log level live on Upscaling's panel and apply to both DLSS paths.
// Called from Upscaling::DrawSettings inside a TreeNode.
// ============================================================================

void FoveatedRender::DrawEnable()
{
	ClampSettings();

	ImGui::TextWrapped(T(TKEY("foveated_overview"),
		"Full DLSS/FSR runs in the selected eye region; the periphery is stretched to reduce VR cost."));

	const bool runtimeSupported = IsRuntimeSupported();
	if (!runtimeSupported) {
		settings.enabled = 0;
	}

	if (!runtimeSupported)
		ImGui::BeginDisabled();
	bool enabledBool = settings.enabled != 0;
	if (ImGui::Checkbox(T(TKEY("foveated_enable"), "Enable Foveated Upscaling (region source)"), &enabledBool)) {
		settings.enabled = enabledBool ? 1u : 0u;
	}
	if (!runtimeSupported)
		ImGui::EndDisabled();

	Util::UI::DrawSettingDiff(bootSnapshot, settings, &Settings::enabled);

	if (enabledAtBoot) {
		const auto method = globals::features::upscaling.GetUpscaleMethod();
		const bool methodOk = method == Upscaling::UpscaleMethod::kDLSS || method == Upscaling::UpscaleMethod::kFSR;
		const bool fullEye = subrectController.GetUV().IsFullEye() && subrectController.GetRightEyeUV().IsFullEye();
		if (IsActive() && fullEye)
			ImGui::TextWrapped("%s", T(TKEY("foveated_full_eye_active"), "Active: Full Eye mode. No peripheral stretch or crop seam."));
		else if (IsActive())
			ImGui::TextWrapped("%s", T(TKEY("foveated_active"), "Active: foveated upscaling. Skipped in menus or after preflight failure."));
		else if (!methodOk)
			Util::Text::Warning(T(TKEY("foveated_standing_by"), "Standing by: requires DLSS or FSR."));
		else
			Util::Text::Warning(T(TKEY("foveated_standing_by"), "Standing by: the VR upscaling route is inactive."));
	}

	if (!globals::game::isVR) {
		Util::Text::Warning(T(TKEY("foveated_vr_only"), "VR only."));
	}
}

const char* FoveatedRender::DlssModeName(DlssMode mode)
{
	return mode == DlssMode::kFaster ?
	           T(TKEY("foveated_dlss_mode_faster"), "Faster") :
	           T(TKEY("foveated_dlss_mode_default"), "Default");
}

const char* FoveatedRender::StretchModeName(StretchMode mode)
{
	switch (mode) {
	case StretchMode::kPoint:
		return T(TKEY("foveated_stretch_point"), "Point");
	case StretchMode::kGaussianBlur:
		return T(TKEY("foveated_stretch_gaussian"), "Gaussian Blur");
	default:
		return T(TKEY("foveated_stretch_bilinear"), "Bilinear");
	}
}

const char* FoveatedRender::PeripheryAAModeName(PeripheryAAMode mode)
{
	return mode == PeripheryAAMode::kTemporalSmooth ?
	           T(TKEY("foveated_periphery_aa_temporal"), "Temporal Smooth") :
	           T(TKEY("foveated_periphery_aa_none"), "None");
}

const char* FoveatedRender::SubrectBlendModeName(SubrectBlendMode mode)
{
	switch (mode) {
	case SubrectBlendMode::kFeather:
		return T(TKEY("foveated_blend_feather"), "Feather");
	case SubrectBlendMode::kDither:
		return T(TKEY("foveated_blend_dither"), "Dither");
	default:
		return T(TKEY("foveated_blend_hard_copy"), "Hard Copy");
	}
}

const char* FoveatedRender::SubrectMaskModeName(SubrectMaskMode mode)
{
	return mode == SubrectMaskMode::kOval ?
	           T(TKEY("foveated_mask_oval"), "Oval") :
	           T(TKEY("foveated_mask_rectangle"), "Rectangle");
}

	void FoveatedRender::DrawSettings(bool showSharedPanelNote, bool vrControlsFirst)
	{
		ClampSettings();
		// Keep all Neural Rendering prose inside the shared, width-aware helper so
		// the desktop and VR panel use the same wrapping rules.
		const auto drawWrapped = [](const char* text) { Util::UI::DrawWrappedText(text); };
		const auto drawDisabledWrapped = [](const char* text) { Util::UI::DrawWrappedDisabledText(text); };
		const auto drawWarningWrapped = [](const char* text) { Util::UI::DrawWrappedWarningText(text); };
	const auto drawVrControls = [&]() {
	// ── VR-only knobs ──
	if (globals::game::isVR) {
			ImGui::Separator();
			ImGui::Text("%s", T(TKEY("foveated_dlss_mode_header"), "VR DLSS Mode"));
			if (auto _tt = Util::HoverTooltipWrapper()) {
				drawWrapped(T(TKEY("foveated_dlss_mode_tooltip"),
									  "Default — highest quality. Each eye gets its own isolated copy of color/depth/motion\n"
									  "vectors so DLSS can't sample across the stereo midline. 5 copies per eye per frame.\n"
									  "All DLSS presets supported. Best for screenshots or when Faster shows edge artifacts.\n"
								  "\n"
								  "Faster — lower overhead. DLSS reads directly from the frame buffer using a viewport\n"
								  "offset instead of isolating each eye. 1 snapshot + 2 mask clears per frame.\n"
								  "DLSS may sample 1-2 pixels from the neighboring eye near the stereo center — usually\n"
								  "invisible in motion. Presets J and K are incompatible and auto-clamp to L."));
		}

		const bool isFSR = globals::features::upscaling.GetUpscaleMethod() == Upscaling::UpscaleMethod::kFSR;
		if (isFSR)
			ImGui::BeginDisabled();
		uint prevMode = settings.dlssMode;
		ImGui::SliderInt(T(TKEY("foveated_dlss_mode_label"), "DLSS Mode"), reinterpret_cast<int*>(&settings.dlssMode), 0, 1, DlssModeName((DlssMode)std::min(settings.dlssMode, 1u)));
		if (settings.dlssMode != prevMode) {
			const uint prevPreset = globals::features::upscaling.settings.presetDLSS;
			ClampPresetToMode();
			if (globals::features::upscaling.settings.presetDLSS != prevPreset) {
				logger::info("[FOVEATED] DLSS preset clamped from {} to {} after mode switch (J/K incompatible with Faster)",
					prevPreset, globals::features::upscaling.settings.presetDLSS);
			}
		}
		if (isFSR) {
			ImGui::EndDisabled();
			ImGui::TextWrapped(T(TKEY("foveated_dlss_mode_fsr_desc"), "Not used by FSR -- applies only when DLSS is the selected upscaler."));
		} else {
			switch (GetDlssMode()) {
			case DlssMode::kDefault:
				ImGui::TextWrapped(T(TKEY("foveated_dlss_mode_default_desc"), "Per-eye isolation: 5 copies per frame, 2 DLSS evaluates. All presets."));
				break;
			case DlssMode::kFaster:
				ImGui::TextWrapped(T(TKEY("foveated_dlss_mode_faster_desc"), "Viewport offset: 1 snapshot, 2 mask clears, 2 DLSS evaluates. Presets J/K unavailable."));
				break;
			default:
				break;
			}
		}

			ImGui::Separator();
			ImGui::Text("%s", T(TKEY("foveated_periphery_header"), "Periphery Rendering"));
			if (auto _tt = Util::HoverTooltipWrapper()) {
				drawWrapped(T(TKEY("foveated_periphery_tooltip"),
									  "The area outside your selected subrect is filled cheaply rather than running\n"
								  "the selected upscaler. These settings control how that cheap fill looks and\n"
								  "whether it flickers.\n"
								  "\n"
								  "Stretch method: how pixels outside the subrect are reconstructed from the lower-res\n"
								  "render buffer. Does not affect the upscaled subrect region at all.\n"
								  "\n"
								  "Periphery AA: reduces temporal flicker in the stretched area using motion-compensated\n"
								  "history blending. Independent of the upscaled subrect.\n"
								  "\n"
								  "Edge Blend: controls how the upscaled subrect edge meets the stretched periphery.\n"
								  "Hard Copy leaves a sharp seam; Feather/Dither soften it. Edge Shape selects a\n"
								  "rectangle or oval composite. The Feature 18 subrect remains rectangular internally."));
		}

		ImGui::SliderInt(T(TKEY("foveated_stretch_label"), "Stretch"), reinterpret_cast<int*>(&settings.stretchMode), 0, 2, StretchModeName((StretchMode)settings.stretchMode));
		switch (GetStretchMode()) {
		case StretchMode::kBilinear:
			ImGui::TextWrapped(T(TKEY("foveated_stretch_bilinear_desc"), "Bilinear: smooth upscale of the render buffer. Looks soft but clean."));
			break;
		case StretchMode::kPoint:
			ImGui::TextWrapped(T(TKEY("foveated_stretch_point_desc"), "Point: cheapest, visibly pixelated. Good for benchmarking foveated savings."));
			break;
		case StretchMode::kGaussianBlur:
			ImGui::TextWrapped(T(TKEY("foveated_stretch_gaussian_desc"), "Gaussian: blurs the periphery further into soft focus. Good default for foveated use."));
			ImGui::SliderFloat(T(TKEY("foveated_blur_radius"), "Blur Radius"), &settings.peripheryBlurRadius, 0.5f, 4.0f, "%.1f px");
			break;
		}

		ImGui::SliderInt(T(TKEY("foveated_periphery_aa_label"), "Periphery AA"), reinterpret_cast<int*>(&settings.peripheryAAMode), 0, 1, PeripheryAAModeName((PeripheryAAMode)settings.peripheryAAMode));
		if (GetPeripheryAAMode() == PeripheryAAMode::kTemporalSmooth) {
			ImGui::TextWrapped(T(TKEY("foveated_periphery_aa_temporal_desc"), "Blends the stretched periphery with motion-reprojected history to reduce flicker."));
				ImGui::SliderFloat(T(TKEY("foveated_smoothing"), "Smoothing"), &settings.peripheryTemporalAlpha, 0.05f, 0.5f, "%.2f");
				if (auto _tt = Util::HoverTooltipWrapper()) {
					drawWrapped(T(TKEY("foveated_smoothing_tooltip"), "Lower = more temporal history (smoother but may ghost). Higher = more responsive."));
				}
		}

		ImGui::SliderInt(T(TKEY("foveated_edge_blend_label"), "Edge Blend"), reinterpret_cast<int*>(&settings.subrectBlendMode), 0, 2, SubrectBlendModeName((SubrectBlendMode)std::min(settings.subrectBlendMode, 2u)));
		switch (GetSubrectBlendMode()) {
		case SubrectBlendMode::kHardCopy:
			ImGui::TextWrapped(T(TKEY("foveated_blend_hard_copy_desc"), "Sharp seam at the subrect boundary. Lowest cost."));
			break;
	case SubrectBlendMode::kFeather:
			ImGui::TextWrapped(T(TKEY("foveated_blend_feather_desc"), "Smoothstep fade over N pixels at the boundary. Hides the seam."));
				ImGui::SliderFloat(T(TKEY("foveated_feather_width"), "Feather Width"), &settings.subrectFeatherWidth, 2.0f, 128.0f, "%.0f px");
				ImGui::SliderFloat(T(TKEY("foveated_falloff_curve"), "Falloff Curve"), &settings.subrectFalloffCurve, 0.5f, 2.0f, "%.2f");
				if (auto _tt = Util::HoverTooltipWrapper())
					drawWrapped(T(TKEY("foveated_falloff_curve_tooltip"), "Controls how the oval transition distributes the fade. 1.00 is balanced; lower values carry the neural result farther into the band, higher values hold the periphery longer."));
			break;
	case SubrectBlendMode::kDither:
			ImGui::TextWrapped(T(TKEY("foveated_blend_dither_desc"), "Noise-dithered fade — more natural-looking than feather at large subrects."));
			ImGui::SliderFloat(T(TKEY("foveated_band_width"), "Band Width"), &settings.subrectFeatherWidth, 2.0f, 128.0f, "%.0f px");
			ImGui::SliderFloat(T(TKEY("foveated_falloff_curve"), "Falloff Curve"), &settings.subrectFalloffCurve, 0.5f, 2.0f, "%.2f");
			ImGui::SliderFloat(T(TKEY("foveated_noise_amount"), "Noise Amount"), &settings.subrectDitherStrength, 0.0f, 2.0f, "%.2f");
			break;
		}

		ImGui::SliderInt(T(TKEY("foveated_mask_shape_label"), "Edge Shape"), reinterpret_cast<int*>(&settings.subrectMaskMode), 0, 1,
			SubrectMaskModeName(GetSubrectMaskMode()));
		if (GetSubrectMaskMode() == SubrectMaskMode::kOval)
			ImGui::TextWrapped(T(TKEY("foveated_mask_oval_desc"),
				"Oval: a distance-corrected elliptical feather/dither mask that removes the box corners. The DLSS/Feature 18 work is still evaluated over the rectangular bounding region; this changes only the composite edge."));
		else
			ImGui::TextWrapped(T(TKEY("foveated_mask_rectangle_desc"),
				"Rectangle: keep the original rectangular feather/dither mask. Use this fallback if the oval edge is not preferred."));

		ImGui::Separator();
		ImGui::Text("%s", T(TKEY("foveated_subrect_region_header"), "Subrect Region"));
		ImGui::TextWrapped(T(TKEY("foveated_subrect_region_desc"),
			"Drag the preview to choose the full-quality region; the rest is stretched."));
		drawDisabledWrapped(T(TKEY("foveated_screenshot_subrect_note"), "Screenshot has its own subrect; align only for pixel-matched captures."));

			bool debugBool = settings.debugVisualize != 0;
			if (ImGui::Checkbox(T(TKEY("foveated_visualize_regions"), "Visualize regions"), &debugBool))
				settings.debugVisualize = debugBool ? 1u : 0u;
			if (auto _tt = Util::HoverTooltipWrapper()) {
				drawWrapped(T(TKEY("foveated_visualize_regions_tooltip"),
									  "Diagnostic: tint the cheap-stretched periphery red so the upscaled\n"
								  "subrect (un-tinted) pops visually in-game. Lets you confirm at a glance where\n"
								  "the selected upscaler is actually running vs where the cheap stretch is filling.\n"
								  "No perf impact; runtime toggle, no restart needed. Also shows briefly whenever\n"
								  "you drag-resize the region below, even with this off."));
		}

		// Preview off kVR_FRAMEBUFFER (the final composed SBS image the headset
		// sees) rather than kMAIN. kMAIN is mid-pipeline and carries non-1
		// alpha where Skyrim composited UI plates, so even with the opaque
		// blend callback you see the menu mask outline instead of the rendered
		// world. ScreenshotFeature picks the same RT for the same reason
		// (ScreenshotFeature.cpp:243). Foveated is VR-only so kVR_FRAMEBUFFER
		// is always populated when we get here.
		auto renderer = globals::game::renderer;
		if (renderer) {
			auto& fb = renderer->GetRuntimeData().renderTargets[RE::RENDER_TARGETS::kVR_FRAMEBUFFER];
			auto* tex = static_cast<ID3D11Texture2D*>(fb.texture);
			subrectController.DrawEditor(fb.SRV, tex, 0.5f, 0.0f, Util::Subrect::OpaquePreviewBlendCallback);
		} else {
			subrectController.DrawEditor(nullptr, nullptr, 0.5f);
		}

		if (subrectController.IsDragging())
			lastDragTime = std::chrono::steady_clock::now();
	}
	};

	if (globals::game::isVR && showSharedPanelNote)
		drawDisabledWrapped(T(TKEY("foveated_shared_panel_note"), "Quality, sharpness, and DLSS preset are on the Upscaling page."));

	if (vrControlsFirst)
		drawVrControls();
	if (ImGui::CollapsingHeader(T(TKEY("neural_rendering_header"), "DLSS Neural Rendering"), ImGuiTreeNodeFlags_DefaultOpen)) {
		const bool supportedRoute = globals::features::upscaling.GetUpscaleMethod() == Upscaling::UpscaleMethod::kDLSS &&
			!globals::features::upscaling.IsFrameGenerationConfiguredForSession() &&
			(!globals::game::isVR || (GetDlssMode() == DlssMode::kDefault &&
				globals::features::upscaling.perfMode.IsHookActive()));
		if (!supportedRoute) {
			if (globals::features::upscaling.IsFrameGenerationConfiguredForSession())
				drawWarningWrapped("Disable Frame Generation and restart before enabling Neural Rendering.");
			else
				drawWarningWrapped(T(TKEY("neural_rendering_unavailable"), "Requires DLSS. VR also requires Default mode and active PerfMode."));
			ImGui::BeginDisabled();
		}
		ImGui::Checkbox(T(TKEY("neural_rendering_enable"), "Enable DLSS Neural Rendering"), &settings.neuralRenderingEnabled);

		if (settings.neuralRenderingEnabled) {
			ImGui::SeparatorText("NR Overview");
			drawWrapped("Adaptive NR changes model resolution to meet the selected frame-time target. Display refresh and output size stay unchanged.");
			drawWrapped("Adaptive crop can reduce coverage to its configured floor. Eye-tracked foveation disables it.");
			drawDisabledWrapped("Target: headset half-refresh, custom 15–60 FPS, or a custom 5–50 ms frame-time budget. NR floor: 70%.");

			// The runtime still receives the stable numeric Style value (0-3), but
			// expose the four choices as named cards so users do not have to guess
			// what "Style 1" or "Style 2" means.  Keep the lower-level tuning
			// preset and sliders below this row; selecting a style is intentionally
			// independent of those numeric strength controls.
			const char* styleLabels[] = {
				T(TKEY("neural_rendering_style_natural"), "Natural"),
				T(TKEY("neural_rendering_style_fabric_detail"), "Fabric Detail"),
				T(TKEY("neural_rendering_style_cinematic"), "Cinematic"),
				T(TKEY("neural_rendering_style_strong"), "Strong")
			};
			const char* styleDescriptions[] = {
				T(TKEY("neural_rendering_style_natural_desc"), "Neutral detail with restrained contrast."),
				T(TKEY("neural_rendering_style_fabric_detail_desc"), "Emphasizes fine materials and surface texture."),
				T(TKEY("neural_rendering_style_cinematic_desc"), "More character and local contrast."),
				T(TKEY("neural_rendering_style_strong_desc"), "Most aggressive reconstruction and detail.")
			};
			const int activeStyle = static_cast<int>(std::min(settings.neuralRenderingStyle, 3u));
			bool custom = false;

			ImGui::SeparatorText(T(TKEY("neural_rendering_visual_style"), "Visual Style"));
			if (auto _tt = Util::HoverTooltipWrapper())
				drawWrapped(T(TKEY("neural_rendering_visual_style_tooltip"), "Select a style. Fine intensity and structure controls remain below."));

			const float minimumStyleCardWidth = 150.0f * Util::GetUIScale();
			const int styleColumnCount = std::clamp(
				static_cast<int>(ImGui::GetContentRegionAvail().x / minimumStyleCardWidth),
				1,
				IM_ARRAYSIZE(styleLabels));
			if (ImGui::BeginTable("##neural_rendering_visual_styles", styleColumnCount,
				ImGuiTableFlags_SizingStretchSame | ImGuiTableFlags_PadOuterX | ImGuiTableFlags_NoSavedSettings)) {
				for (int styleIndex = 0; styleIndex < IM_ARRAYSIZE(styleLabels); ++styleIndex) {
					ImGui::TableNextColumn();
					ImGui::PushID(styleIndex);
					const bool selected = styleIndex == activeStyle;
					if (selected) {
						ImGui::PushStyleColor(ImGuiCol_Button, ImGui::GetStyleColorVec4(ImGuiCol_ButtonActive));
						ImGui::PushStyleColor(ImGuiCol_ButtonHovered, ImGui::GetStyleColorVec4(ImGuiCol_ButtonActive));
					}
					if (ImGui::Button(styleLabels[styleIndex], ImVec2(-1.0f, 0.0f))) {
						settings.neuralRenderingStyle = static_cast<uint>(styleIndex);
						custom = true;
					}
					if (selected)
						ImGui::PopStyleColor(2);
					drawDisabledWrapped(styleDescriptions[styleIndex]);
					if (auto _tt = Util::HoverTooltipWrapper()) {
						drawWrapped(styleDescriptions[styleIndex]);
						drawDisabledWrapped(std::format("DLSSNR style {}", styleIndex).c_str());
					}
					ImGui::PopID();
				}
				ImGui::EndTable();
			}
			ImGui::TextDisabled("%s %s", T(TKEY("neural_rendering_active_style"), "Active style:"), styleLabels[activeStyle]);

			ImGui::SeparatorText("NR Cost / Model Resolution");
			static const char* modelResolutions[] = {
				"Full (100%)", "95%", "90%", "85%", "80%", "75%", "70%", "50% (experimental)", "33% (experimental)",
			};
			static constexpr uint modelResolutionValues[] = { 100u, 95u, 90u, 85u, 80u, 75u, 70u, 50u, 33u };
			int modelResolution = 0;
			for (int index = 0; index < IM_ARRAYSIZE(modelResolutionValues); ++index) {
				if (settings.neuralRenderingModelResolution == modelResolutionValues[index]) {
					modelResolution = index;
					break;
				}
			}
			if (ImGui::Combo(T(TKEY("neural_rendering_model_resolution"), "Model Resolution / Adaptive Ceiling"),
				&modelResolution, modelResolutions, IM_ARRAYSIZE(modelResolutions))) {
				settings.neuralRenderingModelResolution = modelResolutionValues[modelResolution];
			}
			if (auto _tt = Util::HoverTooltipWrapper())
				drawWrapped(T(TKEY("neural_rendering_model_resolution_tooltip"),
					"The display stays full resolution. Below 100%, NR works on a smaller grid; 50% and 33% remain experimental. With Adaptive NR enabled, this selection sets the adaptive quality ceiling."));

			ImGui::SeparatorText("Adaptive Neural Rendering");
			ImGui::Checkbox("Enable adaptive NR resolution", &settings.neuralRenderingAdaptiveEnabled);
			if (auto _tt = Util::HoverTooltipWrapper())
				drawWrapped("Adjusts one NR tier after sustained pressure, from the selected NR resolution down to the configured minimum. Handoffs are blended.");
			if (settings.neuralRenderingAdaptiveEnabled) {
				static constexpr uint adaptiveRefreshValues[] = { 70u, 72u, 80u, 90u };
				static const char* adaptiveRefreshRates[] = {
					"70 Hz | 35 FPS budget", "72 Hz | 36 FPS budget", "80 Hz | 40 FPS budget", "90 Hz | 45 FPS budget" };
				int refreshIndex = 2;
				for (int index = 0; index < IM_ARRAYSIZE(adaptiveRefreshValues); ++index)
					if (settings.neuralRenderingAdaptiveRefreshHz == adaptiveRefreshValues[index]) {
						refreshIndex = index;
						break;
					}

				static const char* adaptiveBudgetModes[] = {
					"Headset refresh", "Custom FPS target", "Custom frame-time target" };
				int budgetMode = static_cast<int>(std::min(settings.neuralRenderingAdaptiveBudgetMode, 2u));
				if (ImGui::Combo("Adaptive budget mode", &budgetMode,
					adaptiveBudgetModes, IM_ARRAYSIZE(adaptiveBudgetModes))) {
					settings.neuralRenderingAdaptiveBudgetMode = static_cast<uint>(budgetMode);
					if (budgetMode == 1)
						settings.neuralRenderingAdaptiveTargetFps = settings.neuralRenderingAdaptiveTargetFps == 0 ? 40u : settings.neuralRenderingAdaptiveTargetFps;
					else
						settings.neuralRenderingAdaptiveTargetFps = 0;
				}
				if (settings.neuralRenderingAdaptiveBudgetMode == 1) {
					int targetFps = static_cast<int>(std::clamp(settings.neuralRenderingAdaptiveTargetFps, 15u, 60u));
					if (ImGui::SliderInt("FPS target", &targetFps, 15, 60, "%d FPS"))
						settings.neuralRenderingAdaptiveTargetFps = static_cast<uint>(targetFps);
				} else if (settings.neuralRenderingAdaptiveBudgetMode == 2) {
					ImGui::SliderFloat("Frame-time budget", &settings.neuralRenderingAdaptiveTargetFrameTimeMs,
						5.0f, 50.0f, "%.1f ms");
					if (auto _tt = Util::HoverTooltipWrapper())
						drawWrapped("Caps measured application GPU/CPU work at this frame time. The reserve below compares it with the headset's half-refresh application slot.");
				}
				if (settings.neuralRenderingAdaptiveBudgetMode != 0) {
					const float targetFrameTimeMs = settings.neuralRenderingAdaptiveBudgetMode == 1 ?
						1000.0f / static_cast<float>(std::max(settings.neuralRenderingAdaptiveTargetFps, 1u)) :
						settings.neuralRenderingAdaptiveTargetFrameTimeMs;
					const float headsetSlotMs = 2000.0f / static_cast<float>(settings.neuralRenderingAdaptiveRefreshHz);
					const float compositorReserveMs = headsetSlotMs - targetFrameTimeMs;
					if (compositorReserveMs >= 0.0f)
						ImGui::TextDisabled("Half-refresh slot %.2f ms | target leaves %.2f ms for compositor work",
							headsetSlotMs, compositorReserveMs);
					else
						drawWarningWrapped(std::format("Target exceeds the selected headset's half-refresh slot by {:.2f} ms.",
							-compositorReserveMs).c_str());
				}

				ImGui::TextDisabled("Headset refresh target");
				ImGui::BeginDisabled(settings.neuralRenderingAdaptiveBudgetMode != 0);
				if (ImGui::BeginTable("##neural_rendering_adaptive_refresh", IM_ARRAYSIZE(adaptiveRefreshValues),
						ImGuiTableFlags_SizingStretchSame | ImGuiTableFlags_PadOuterX | ImGuiTableFlags_NoSavedSettings)) {
					for (int index = 0; index < IM_ARRAYSIZE(adaptiveRefreshValues); ++index) {
						ImGui::TableNextColumn();
						const bool selected = index == refreshIndex;
						if (selected)
							ImGui::PushStyleColor(ImGuiCol_Button, ImGui::GetStyleColorVec4(ImGuiCol_ButtonActive));
						if (ImGui::Button(adaptiveRefreshRates[index], ImVec2(-1.0f, 32.0f * Util::GetUIScale())))
							settings.neuralRenderingAdaptiveRefreshHz = adaptiveRefreshValues[index];
						if (selected)
							ImGui::PopStyleColor();
					}
					ImGui::EndTable();
				}
				ImGui::EndDisabled();
				drawDisabledWrapped(settings.neuralRenderingAdaptiveBudgetMode == 0 ?
					"Headset mode uses half the selected refresh." : "The headset refresh buttons are inactive for a custom target.");

				static const char* adaptiveMinimums[] = {
					"100% | 100% model area", "95% | 90% model area", "90% | 81% model area", "85% | 72% model area",
					"80% | 64% model area", "75% | 56% model area", "70% | 49% model area" };
				static constexpr uint adaptiveMinimumValues[] = { 100u, 95u, 90u, 85u, 80u, 75u, 70u };
				int minimumIndex = 6;
				for (int index = 0; index < IM_ARRAYSIZE(adaptiveMinimumValues); ++index)
					if (settings.neuralRenderingAdaptiveMinimumResolution == adaptiveMinimumValues[index]) {
						minimumIndex = index;
						break;
					}
				if (ImGui::Combo("Adaptive minimum NR cost", &minimumIndex, adaptiveMinimums, IM_ARRAYSIZE(adaptiveMinimums)))
					settings.neuralRenderingAdaptiveMinimumResolution = adaptiveMinimumValues[minimumIndex];

				static const char* adaptiveQualityOrders[] = {
					"Passes → crop → NR resolution",
					"Passes → NR resolution → crop",
					"Crop → passes → NR resolution",
					"Crop → NR resolution → passes",
					"NR resolution → passes → crop",
					"NR resolution → crop → passes",
				};
				int qualityOrder = static_cast<int>(std::min(settings.neuralRenderingAdaptiveQualityOrder, 5u));
				if (ImGui::Combo("Adaptive quality order", &qualityOrder,
					adaptiveQualityOrders, IM_ARRAYSIZE(adaptiveQualityOrders)))
					settings.neuralRenderingAdaptiveQualityOrder = static_cast<uint>(qualityOrder);
				if (auto _tt = Util::HoverTooltipWrapper())
					drawWrapped("Pressure moves down one available tier in this order. Recovery restores tiers in reverse order. Pass-count control applies when sequential NR is selected.");

				int downshiftFrames = static_cast<int>(settings.neuralRenderingAdaptiveDownshiftFrames);
				if (ImGui::SliderInt("NR downshift fade", &downshiftFrames, 1, 16, "%d budget frames"))
					settings.neuralRenderingAdaptiveDownshiftFrames = static_cast<uint>(downshiftFrames);
				int upshiftFrames = static_cast<int>(settings.neuralRenderingAdaptiveUpshiftFrames);
				if (ImGui::SliderInt("NR restore response", &upshiftFrames, 4, 64, "%d frames"))
					settings.neuralRenderingAdaptiveUpshiftFrames = static_cast<uint>(upshiftFrames);
				int minimumDwellFrames = static_cast<int>(settings.neuralRenderingAdaptiveMinimumDwellFrames);
				if (ImGui::SliderInt("NR tier minimum dwell", &minimumDwellFrames, 4, 240, "%d frames"))
					settings.neuralRenderingAdaptiveMinimumDwellFrames = static_cast<uint>(minimumDwellFrames);
				ImGui::SliderFloat("Adaptive reserved headroom", &settings.neuralRenderingAdaptiveGuardTimeMs,
					0.0f, 5.0f, "%.1f ms");
				ImGui::TextDisabled("Target %.2f ms (%.1f FPS) | NR tier %u%% -> %u%% | measured %.2f ms | target headroom %.2f ms",
					adaptiveController.ApplicationTargetFrameTimeMs(), adaptiveController.ApplicationTargetFps(),
					adaptiveController.ActiveResolution(), adaptiveController.TargetResolution(),
					adaptiveController.SmoothedFrameTimeMs(),
					std::max(0.0f, adaptiveController.ApplicationDeadlineMs() - adaptiveController.SmoothedFrameTimeMs()));
				drawDisabledWrapped("The selected order chooses which quality tier gives way first under sustained pressure.");
				drawWarningWrapped("Resource setup may hitch once.");
				ImGui::Checkbox("Show handoff diagnostics", &settings.neuralRenderingAdaptiveDiagnostics);
			}

			ImGui::SeparatorText("Adaptive Foveated Crop");
			const bool adaptiveCropParentEnabled = settings.neuralRenderingAdaptiveEnabled;
			if (!adaptiveCropParentEnabled)
				ImGui::BeginDisabled();
			ImGui::Checkbox("Enable adaptive crop", &settings.neuralRenderingAdaptiveCropEnabled);
			if (!adaptiveCropParentEnabled)
				ImGui::EndDisabled();
			if (auto _tt = Util::HoverTooltipWrapper())
				drawWrapped("Order: crop → NR → crop. NR restores before crop expands. With eye tracking, the crop extent changes around the live gaze center.");
			if (!adaptiveCropParentEnabled)
				ImGui::TextDisabled("Enable Adaptive Neural Rendering before enabling its crop companion.");
			if (settings.neuralRenderingAdaptiveCropEnabled && adaptiveCropParentEnabled) {
				static const char* adaptiveCropMaximums[] = {
					"85%", "80%", "75%", "70%", "65%", "60%", "55%", "50%", "45%", "40%", "35%", "30%" };
				static constexpr uint adaptiveCropMaximumValues[] = { 85u, 80u, 75u, 70u, 65u, 60u, 55u, 50u, 45u, 40u, 35u, 30u };
				int cropMaximumIndex = 0;
				for (int index = 0; index < IM_ARRAYSIZE(adaptiveCropMaximumValues); ++index)
					if (settings.neuralRenderingAdaptiveCropMaximumCoverage == adaptiveCropMaximumValues[index]) {
						cropMaximumIndex = index;
						break;
					}
				if (ImGui::Combo("Adaptive maximum crop coverage", &cropMaximumIndex,
					adaptiveCropMaximums, IM_ARRAYSIZE(adaptiveCropMaximums)))
					settings.neuralRenderingAdaptiveCropMaximumCoverage = adaptiveCropMaximumValues[cropMaximumIndex];
				if (auto _tt = Util::HoverTooltipWrapper())
					drawWrapped("The maximum is capped by the selected crop size. Under pressure the region shrinks around its current center, including the live gaze center.");

				static const char* adaptiveCropMinimums[] = {
					"80%", "75%", "70%", "65%", "60%", "55%", "50%", "45%", "40%", "35%", "30%" };
				static constexpr uint adaptiveCropMinimumValues[] = { 80u, 75u, 70u, 65u, 60u, 55u, 50u, 45u, 40u, 35u, 30u };
				int cropMinimumIndex = IM_ARRAYSIZE(adaptiveCropMinimumValues) - 1;
				for (int index = 0; index < IM_ARRAYSIZE(adaptiveCropMinimumValues); ++index)
					if (settings.neuralRenderingAdaptiveCropMinimumCoverage == adaptiveCropMinimumValues[index]) {
						cropMinimumIndex = index;
						break;
					}
				if (ImGui::Combo("Adaptive minimum crop coverage", &cropMinimumIndex,
					adaptiveCropMinimums, IM_ARRAYSIZE(adaptiveCropMinimums)))
					settings.neuralRenderingAdaptiveCropMinimumCoverage = adaptiveCropMinimumValues[cropMinimumIndex];

				int cropDownshiftFrames = static_cast<int>(settings.neuralRenderingAdaptiveCropDownshiftFrames);
				if (ImGui::SliderInt("Crop downshift response", &cropDownshiftFrames, 1, 16, "%d frames"))
					settings.neuralRenderingAdaptiveCropDownshiftFrames = static_cast<uint>(cropDownshiftFrames);
				int cropUpshiftFrames = static_cast<int>(settings.neuralRenderingAdaptiveCropUpshiftFrames);
				if (ImGui::SliderInt("Crop restore response", &cropUpshiftFrames, 8, 240, "%d frames"))
					settings.neuralRenderingAdaptiveCropUpshiftFrames = static_cast<uint>(cropUpshiftFrames);
				int cropMinimumDwellFrames = static_cast<int>(settings.neuralRenderingAdaptiveCropMinimumDwellFrames);
				if (ImGui::SliderInt("Crop tier minimum dwell", &cropMinimumDwellFrames, 8, 600, "%d frames"))
					settings.neuralRenderingAdaptiveCropMinimumDwellFrames = static_cast<uint>(cropMinimumDwellFrames);
				int cropTransitionFrames = static_cast<int>(settings.neuralRenderingAdaptiveCropTransitionFrames);
				if (ImGui::SliderInt("Crop handoff duration", &cropTransitionFrames, 2, 24, "%d frames"))
					settings.neuralRenderingAdaptiveCropTransitionFrames = static_cast<uint>(cropTransitionFrames);
				ImGui::TextDisabled("Crop: %u%% -> %u%% | max %u%% | handoff %.2f",
					adaptiveCropController.ActiveCoverage(), adaptiveCropController.TargetCoverage(),
					settings.neuralRenderingAdaptiveCropMaximumCoverage,
					adaptiveCropController.HandoffAlpha());
			}
			if (IsEyeTrackedFoveationEnabled())
				drawWrapped("Adaptive crop changes the gaze region's size; eye tracking continues to control its center.");
			if (FoveatedRenderImpl::Core::vrSubrectFixedEnvelopeRejected ||
				FoveatedRenderImpl::Core::vrSubrectNeuralFixedEnvelopeRejected)
				drawWarningWrapped("Crop held: resource contract failed. Restart required to retry.");

			if (settings.neuralRenderingAdaptiveDiagnostics) {
				ImGui::SeparatorText("Handoff Diagnostics");
				const char* resourceMode = FoveatedRenderImpl::Core::vrSubrectResourceMode ==
					FoveatedRenderImpl::Core::SubrectResourceMode::FixedEnvelope ? "fixed envelope" : "exact cache";
				ImGui::TextDisabled("Resources: %s | valid %ux%u | envelope %ux%u",
					resourceMode, FoveatedRenderImpl::Core::vrSubrectValidOutW,
					FoveatedRenderImpl::Core::vrSubrectValidOutH, FoveatedRenderImpl::Core::vrSubrectOutW,
					FoveatedRenderImpl::Core::vrSubrectOutH);
				ImGui::TextDisabled("Creates %llu | reuses %llu | frees %llu",
					static_cast<unsigned long long>(FoveatedRenderImpl::Core::vrSubrectResourceCreates),
					static_cast<unsigned long long>(FoveatedRenderImpl::Core::vrSubrectResourceReuses),
					static_cast<unsigned long long>(FoveatedRenderImpl::Core::vrSubrectResourceFrees));
				ImGui::TextDisabled("Fallback entries %llu | evictions %llu | envelope checks %llu",
					static_cast<unsigned long long>(FoveatedRenderImpl::Core::vrSubrectFallbackEntries),
					static_cast<unsigned long long>(FoveatedRenderImpl::Core::vrSubrectFallbackEvictions),
					static_cast<unsigned long long>(FoveatedRenderImpl::Core::vrSubrectEnvelopeValidations));
				ImGui::TextDisabled("Crop reset: %s | generation %llu",
					NeuralRendering::AdaptiveCropController::ResetReasonName(adaptiveCropController.LastResetReason()),
					static_cast<unsigned long long>(adaptiveCropController.Generation()));
			}

			ImGui::SeparatorText("Resolve and Pipeline");
			static const char* resolveModes[] = { "Classic (bounded source)", "Matched Residual (experimental)" };
			int resolveMode = static_cast<int>(std::min(settings.neuralRenderingResolveMode, 1u));
			if (ImGui::Combo(T(TKEY("neural_rendering_resolve_mode"), "Reduced NR Resolve"), &resolveMode,
				resolveModes, IM_ARRAYSIZE(resolveModes))) {
				settings.neuralRenderingResolveMode = static_cast<uint>(resolveMode);
			}
			if (auto _tt = Util::HoverTooltipWrapper())
				drawWrapped(T(TKEY("neural_rendering_resolve_mode_tooltip"), "Matched Residual uses an area-matched input and adds only the matching residual. Compare it at the same model resolution."));

			static const char* multiPassModes[] = { "Off", "2x sequential NR", "3x sequential NR" };
			int multiPass = static_cast<int>(std::min(settings.neuralRenderingMultiPass, 2u));
			if (ImGui::Combo(T(TKEY("neural_rendering_multi_pass"), "Experimental sequential NR"),
				&multiPass, multiPassModes, IM_ARRAYSIZE(multiPassModes)))
				settings.neuralRenderingMultiPass = static_cast<uint>(multiPass);
			if (auto _tt = Util::HoverTooltipWrapper())
				drawWrapped(T(TKEY("neural_rendering_multi_pass_tooltip"), "Runs NR two or three times on each eye's current region, including eye-tracked crops. With adaptive NR enabled, the pass count can be reduced under pressure according to the selected quality order. Resources are retained at the configured maximum pass count."));
			if (settings.neuralRenderingMultiPass) {
				if (settings.neuralRenderingMultiPass == 1) {
					ImGui::SliderFloat("Second-pass contribution", &settings.neuralRenderingSecondPassContribution,
						0.0f, 1.0f, "%.2f");
					if (auto _tt = Util::HoverTooltipWrapper())
						drawWrapped("Blends pass two against pass one before the final NR composition. Zero skips pass two. This blend does not feed back into Feature 18 history.");
				}
				if (settings.neuralRenderingMultiPass >= 2)
					drawWarningWrapped(T(TKEY("neural_rendering_multi_pass_warning"), "Experimental 3x: very large frame-time and VRAM increase."));
				else
					drawWarningWrapped(T(TKEY("neural_rendering_multi_pass_warning"), "Experimental 2x: major frame-time increase and possible smearing."));
				if (settings.neuralRenderingAdaptiveEnabled)
					ImGui::TextDisabled("Adaptive pass count: %u x", GetEffectiveMultiPassMode() + 1);
				if (settings.neuralRenderingAdaptiveEnabled)
					drawWrapped("Adaptive pass reduction keeps resources for your selected maximum resident, so changing pass count does not recreate the cascade mid-game.");
				if (settings.neuralRenderingMultiPass == 1) {
					ImGui::TextDisabled("Pass 1 uses the selected/gaze crop and the outer Edge Blend, Feather Width, Falloff Curve, and Edge Shape settings above.");
					int cropReductionX = static_cast<int>(settings.neuralRenderingSecondPassCropReductionX);
					if (ImGui::SliderInt("Pass 2 width reduction", &cropReductionX, 0, 50, "%d%% smaller"))
						settings.neuralRenderingSecondPassCropReductionX = static_cast<uint>(cropReductionX);
					int cropReductionY = static_cast<int>(settings.neuralRenderingSecondPassCropReductionY);
					if (ImGui::SliderInt("Pass 2 height reduction", &cropReductionY, 0, 50, "%d%% smaller"))
						settings.neuralRenderingSecondPassCropReductionY = static_cast<uint>(cropReductionY);
					if (auto _tt = Util::HoverTooltipWrapper())
						drawWrapped("Shrinks pass two around the current gaze or selected crop. The width and height can be reduced independently; zero on both axes keeps pass two the same size as pass one. The edge settings below blend a smaller pass two over pass one.");
					if (settings.neuralRenderingSecondPassCropReductionX != 0 || settings.neuralRenderingSecondPassCropReductionY != 0) {
						static const char* passTwoBlendModes[] = { "Feather", "Dither", "Hard Copy" };
						int blendMode = static_cast<int>(std::min(settings.neuralRenderingSecondPassBlendMode, 2u));
						if (ImGui::Combo("Pass 2 edge blend", &blendMode, passTwoBlendModes, IM_ARRAYSIZE(passTwoBlendModes)))
							settings.neuralRenderingSecondPassBlendMode = static_cast<uint>(blendMode);
						static const char* passTwoMaskModes[] = { "Rectangle", "Oval" };
						int maskMode = static_cast<int>(std::min(settings.neuralRenderingSecondPassMaskMode, 1u));
						if (ImGui::Combo("Pass 2 edge shape", &maskMode, passTwoMaskModes, IM_ARRAYSIZE(passTwoMaskModes)))
							settings.neuralRenderingSecondPassMaskMode = static_cast<uint>(maskMode);
						if (settings.neuralRenderingSecondPassBlendMode != static_cast<uint>(SubrectBlendMode::kHardCopy)) {
							const char* featherLabel = settings.neuralRenderingSecondPassBlendMode == static_cast<uint>(SubrectBlendMode::kDither) ?
								"Pass 2 band width" : "Pass 2 feather width";
						ImGui::SliderFloat(featherLabel, &settings.neuralRenderingSecondPassFeatherWidth, 2.0f, 128.0f, "%.0f px");
						ImGui::SliderFloat("Pass 2 falloff curve", &settings.neuralRenderingSecondPassFalloffCurve, 0.5f, 2.0f, "%.2f");
						if (settings.neuralRenderingSecondPassBlendMode == static_cast<uint>(SubrectBlendMode::kDither))
							ImGui::SliderFloat("Pass 2 noise amount", &settings.neuralRenderingSecondPassDitherStrength, 0.0f, 2.0f, "%.2f");
					}
				} else if (settings.neuralRenderingMultiPass >= 2) {
					ImGui::TextDisabled("Pass 2 crop and feather controls apply to 2x only; 3x uses full selected crops for each pass.");
				}
			}
			}

			ImGui::SeparatorText("Eye-tracked Foveation");
			bool eyeTrackedFoveation = settings.neuralRenderingEyeTrackedFoveation;
			if (ImGui::Checkbox("Native OpenVR gaze provider", &eyeTrackedFoveation))
				settings.neuralRenderingEyeTrackedFoveation = eyeTrackedFoveation;
			if (auto _tt = Util::HoverTooltipWrapper())
				drawWrapped("Optional moving crop for native OpenVR eye tracking. Requires VR, Default mode, and a cropped region; stale gaze falls back to the static crop.");
			if (settings.neuralRenderingEyeTrackedFoveation) {
				static const char* gazePolicies[] = { "Legacy", "Adaptive" };
				int gazePolicy = static_cast<int>(std::min(settings.neuralRenderingEyeTrackedPolicy, 1u));
				if (ImGui::Combo("Gaze response", &gazePolicy, gazePolicies, IM_ARRAYSIZE(gazePolicies)))
					settings.neuralRenderingEyeTrackedPolicy = static_cast<uint>(gazePolicy);
				if (auto _tt = Util::HoverTooltipWrapper())
					drawWrapped("Legacy keeps the existing immediate pursuit behavior. Adaptive adds a small fixation deadband and timed catch-up while keeping left and right eye samples independent.");
				ImGui::SliderFloat("Fixation smoothing", &settings.neuralRenderingEyeTrackedSmoothingMs,
					0.0f, settings.neuralRenderingEyeTrackedPolicy == 1 ? 100.0f : 250.0f, "%.0f ms");
				if (settings.neuralRenderingEyeTrackedPolicy == 1) {
					ImGui::SliderFloat("Gaze catch-up", &settings.neuralRenderingEyeTrackedCatchupMs, 0.0f, 30.0f, "%.0f ms");
					int deadband = static_cast<int>(settings.neuralRenderingEyeTrackedDeadbandPixels);
					if (ImGui::SliderInt("Gaze deadband", &deadband, 0, 8, "%d input px"))
						settings.neuralRenderingEyeTrackedDeadbandPixels = static_cast<uint>(deadband);
					int hold = static_cast<int>(settings.neuralRenderingEyeTrackedHoldMs);
					if (ImGui::SliderInt("Invalid gaze hold", &hold, 0, 200, "%d ms"))
						settings.neuralRenderingEyeTrackedHoldMs = static_cast<uint>(hold);
					ImGui::SliderFloat("Gaze prediction", &settings.neuralRenderingEyeTrackedPredictionMs, 0.0f, 15.0f, "%.0f ms");
				}
				drawWrapped("Gaze filtering changes only crop placement, not head pose. History is re-anchored after tracking loss or a large crop jump.");
				int quantizationPixels = static_cast<int>(std::min(settings.neuralRenderingEyeTrackedQuantizationPixels, 64u));
				if (ImGui::SliderInt("Crop movement quantization", &quantizationPixels, 0, 64, quantizationPixels == 0 ? "Off" : "%d input px"))
					settings.neuralRenderingEyeTrackedQuantizationPixels = static_cast<uint>(std::clamp(quantizationPixels, 0, 64));
				int cropPadding = static_cast<int>(std::min(settings.neuralRenderingEyeTrackedCropPaddingPixels, 128u));
				if (ImGui::SliderInt("Gaze crop edge margin", &cropPadding, 0, 128, cropPadding == 0 ? "Off" : "%d input px"))
					settings.neuralRenderingEyeTrackedCropPaddingPixels = static_cast<uint>(std::clamp(cropPadding, 0, 128));
				if (auto _tt = Util::HoverTooltipWrapper())
					drawWrapped("Expands the moving NR crop by this many input pixels on each edge. It can hide crop-boundary artifacts, at the cost of processing a larger area. Zero preserves the current crop size.");
				if (!globals::game::isVR)
					drawWarningWrapped("Native OpenVR gaze is available only in VR.");
				else if (GetDlssMode() != DlssMode::kDefault)
					drawWarningWrapped("Native OpenVR gaze requires Foveated Default mode.");
				else if (subrectController.GetUV().IsFullEye() && subrectController.GetRightEyeUV().IsFullEye())
					drawWarningWrapped("Select a cropped eye region before enabling moving gaze.");
				const auto gaze = FoveatedRenderImpl::NativeOpenVRGaze::GetDiagnostics();
				ImGui::TextDisabled("Provider: %s | API: %s | Focus: %s | Native sample: %s",
					FoveatedRenderImpl::NativeOpenVRGaze::StatusName(gaze.status), gaze.interfaceVersion.c_str(),
					gaze.focused ? "yes" : "no", gaze.nativeQueryValid ? "valid" : "invalid");
				ImGui::TextDisabled("Crop: %s | Fallback: %s | History reset: %s | Last valid query: %.1f ms",
					gaze.dynamic ? "dynamic" : "static", gaze.usingFallback ? "yes" : "no",
					gaze.historyReset ? "yes" : "no", gaze.sampleAgeMs);
				ImGui::TextDisabled("Query: %.3f ms | Crop changes: %llu | Resets: %llu",
					gaze.providerQueryMs, static_cast<unsigned long long>(gaze.cropChangeCount),
					static_cast<unsigned long long>(gaze.historyResetCount));
				ImGui::TextDisabled("Filtered gaze L=(%.3f, %.3f) R=(%.3f, %.3f) | sequence=%llu",
					gaze.filteredLeftUV[0], gaze.filteredLeftUV[1], gaze.filteredRightUV[0], gaze.filteredRightUV[1],
					static_cast<unsigned long long>(gaze.sampleSequence));
			}

			ImGui::SeparatorText("Advanced NR Tuning");
			static const char* presets[] = { "Default", "Balanced", "Fabric Detail", "Natural", "Strong", "Custom" };
			int preset = static_cast<int>(settings.neuralRenderingPreset);
			if (ImGui::Combo(T(TKEY("neural_rendering_preset"), "Model Preset"), &preset, presets, IM_ARRAYSIZE(presets))) {
				static constexpr std::string_view presetNames[] = { "Default", "Balanced", "Fabric Detail", "Natural", "Strong", "Custom" };
				ApplyNeuralRenderingPreset(presetNames[std::clamp(preset, 0, IM_ARRAYSIZE(presetNames) - 1)]);
			}
			custom |= ImGui::SliderFloat(T(TKEY("neural_rendering_intensity"), "Intensity"), &settings.neuralRenderingIntensity, 0.0f, 2.0f, "%.2f");
			custom |= ImGui::SliderFloat(T(TKEY("neural_rendering_local_tone"), "Local Tone"), &settings.neuralRenderingLocalTone, 0.0f, 2.0f, "%.2f");
			custom |= ImGui::SliderFloat(T(TKEY("neural_rendering_local_structure"), "Local Structure"), &settings.neuralRenderingLocalStructure, 0.0f, 2.0f, "%.2f");
			ImGui::SliderFloat("NR contribution", &settings.neuralRenderingNRContribution, 0.0f, 1.0f, "%.2f");
			if (auto _tt = Util::HoverTooltipWrapper())
				drawWrapped("Blends the native NR image over its current input. Zero skips NR and marks native histories for reset before the next evaluation.");
			ImGui::SliderFloat("Detail boost", &settings.neuralRenderingDetailBoost, 1.0f, 2.0f, "%.2f");
			if (auto _tt = Util::HoverTooltipWrapper())
				drawWrapped("Raises local NR detail with a guarded luminance ratio. 1.0 preserves the existing image exactly; higher values are clamped to limit dark-scene excursions.");
			custom |= ImGui::SliderFloat(T(TKEY("neural_rendering_skin_structure"), "Skin Structure"), &settings.neuralRenderingSkinStructure, -1.0f, 2.0f, "%.2f");
			custom |= ImGui::Checkbox(T(TKEY("neural_rendering_auto_mask"), "Automatic Mask"), &settings.neuralRenderingAutoMask);
			custom |= ImGui::Checkbox(T(TKEY("neural_rendering_ui_correction"), "UI Correction"), &settings.neuralRenderingUICorrection);
			if (custom)
				settings.neuralRenderingPreset = 5;

				auto& neuralRenderer = NeuralRendering::Renderer::Instance();
				if (adaptiveController.MemoryCeiling() < settings.neuralRenderingModelResolution)
					ImGui::TextDisabled("VRAM-limited NR ceiling: %u%%. Reset retries higher tiers.", adaptiveController.MemoryCeiling());
				if (neuralRenderer.IsFailureLatched() || neuralRenderer.IsRecoveryLimited() ||
					adaptiveController.MemoryCeiling() < settings.neuralRenderingModelResolution ||
					FoveatedRenderImpl::Core::vrSubrectFixedEnvelopeRejected ||
					FoveatedRenderImpl::Core::vrSubrectNeuralFixedEnvelopeRejected) {
					drawWarningWrapped("Neural rendering recovery or adaptive crop is limited after a failure. Reset to retry.");
				if (ImGui::Button("Reset Neural Rendering Failure"))
					NeuralRendering::RequestReset();
			}
			if (globals::state && globals::state->IsDeveloperMode()) {
				ImGui::TextDisabled("Status: %s | NGX: 0x%08X | Evaluations: %llu",
					neuralRenderer.StatusText(), neuralRenderer.NgxResult(),
					static_cast<unsigned long long>(neuralRenderer.SuccessfulFrames()));
			}
		}
		if (!supportedRoute)
			ImGui::EndDisabled();
	}


	if (!vrControlsFirst)
		drawVrControls();
}

#undef I18N_KEY_PREFIX
