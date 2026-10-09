#include "FoveatedRender.h"

#include "../../Globals.h"
#include "../../I18n/I18n.h"
#include "../../Utils/Subrect.h"
#include "../../Utils/UI.h"
#include "../HDRDisplay.h"
#include "../FoveatedCommon.h"
#include "../OpenNRCapture.h"
#include "../Upscaling.h"
#include "../VR.h"
#include "FoveatedRender/Core.h"
#include "GazeCropPolicy.h"
#include "NativeOpenVRGaze.h"
#include "NeuralRendering/Integration.h"
#include "NeuralRendering/FuturePipeline.h"
#include "NeuralRendering/Renderer.h"
#include "../../Profiler.h"
#include "../../State.h"
#include "NeuralRendering/RuntimePolicy.h"

#include <algorithm>
#include <cmath>
#include <format>
#include <string>

#define I18N_KEY_PREFIX "feature.upscaling."

static_assert(!NeuralRendering::Future::AsyncOwnershipContract::kRuntimeEnabled);
static_assert(!NeuralRendering::Future::DepthMatchedResidualFillContract::kRuntimeEnabled);
static_assert(!NeuralRendering::Future::PeripheralCompressionContract::kRuntimeEnabled);

#define OPENNR_SEQUENTIAL_PASS_FIELDS(X) \
	X(coveragePercent) \
	X(modelResolution) \
	X(preset) \
	X(intensity) \
	X(localTone) \
	X(localStructure) \
	X(skinStructure) \
	X(style) \
	X(autoMask) \
	X(uiCorrection) \
	X(resolveMode) \
	X(resultShapingEnabled) \
	X(resultEditStrength) \
	X(resultBrightening) \
	X(resultDarkening) \
	X(resultColor) \
	X(resultHueShiftStrength) \
	X(resultShadows) \
	X(resultMidtones) \
	X(resultHighlights) \
	X(resultMaxBrighteningStops) \
	X(resultMaxDarkeningStops) \
	X(resultMaxColorChangeStops) \
	X(resultLargeScaleTone) \
	X(resultFineDetail) \
	X(resultDetailRadius) \
	X(resultHaloSuppression) \
	X(stabilizeMode) \
	X(stabilizeTimeMs) \
	X(stabilizeDetail) \
	X(stabilizeDepthThreshold) \
	X(stabilizeColorTolerance) \
	X(blendMode) \
	X(maskMode) \
	X(featherWidth) \
	X(falloffCurve) \
	X(ditherStrength)

template <typename BasicJsonType>
void to_json(BasicJsonType& json, const FoveatedRender::SequentialPassSettings& settings)
{
	json = BasicJsonType::object();
#define OPENNR_WRITE_SEQUENTIAL_PASS_SETTING(field) json[#field] = settings.field;
	OPENNR_SEQUENTIAL_PASS_FIELDS(OPENNR_WRITE_SEQUENTIAL_PASS_SETTING)
#undef OPENNR_WRITE_SEQUENTIAL_PASS_SETTING
}

template <typename BasicJsonType>
void from_json(const BasicJsonType& json, FoveatedRender::SequentialPassSettings& settings)
{
	const FoveatedRender::SequentialPassSettings defaults{};
	if (json.is_null()) {
		settings = defaults;
		return;
	}
#define OPENNR_READ_SEQUENTIAL_PASS_SETTING(field) settings.field = json.value(#field, defaults.field);
	OPENNR_SEQUENTIAL_PASS_FIELDS(OPENNR_READ_SEQUENTIAL_PASS_SETTING)
#undef OPENNR_READ_SEQUENTIAL_PASS_SETTING
}

#define OPENNR_FOVEATED_SETTINGS_FIELDS(X) \
	X(enabled) \
	X(debugVisualize) \
	X(peripheryAAMode) \
	X(peripheryTemporalAlpha) \
	X(subrectMaskMode) \
	X(neuralRenderingEnabled) \
	X(neuralRenderingIntensity) \
	X(neuralRenderingLocalTone) \
	X(neuralRenderingLocalStructure) \
	X(neuralRenderingSkinStructure) \
	X(neuralRenderingAutoMask) \
	X(neuralRenderingUICorrection) \
	X(neuralRenderingResultShapingEnabled) \
	X(neuralRenderingResultEditStrength) \
	X(neuralRenderingResultBrightening) \
	X(neuralRenderingResultColor) \
	X(neuralRenderingResultHighlights) \
	X(neuralRenderingResultMaxBrighteningStops) \
	X(neuralRenderingResultMaxDarkeningStops) \
	X(neuralRenderingResultMaxColorChangeStops) \
	X(neuralRenderingResultLargeScaleTone) \
	X(neuralRenderingResultFineDetail) \
	X(neuralRenderingResultDetailRadius) \
	X(neuralRenderingNearBlackProtection) \
	X(neuralRenderingNearBlackThreshold) \
	X(neuralRenderingNearBlackLiftSoftness) \
	X(neuralRenderingStereoAtlasGuardPixels) \
	X(neuralRenderingAdaptiveEnabled) \
	X(neuralRenderingAdaptiveSmoothingMs) \
	X(neuralRenderingAdaptiveDecreaseHoldMs) \
	X(neuralRenderingAdaptiveIncreaseHoldMs) \
	X(neuralRenderingAdaptiveCooldownMs) \
	X(neuralRenderingAdaptiveDiagnostics) \
	X(neuralRenderingAdaptiveCropTransitionFrames) \
	X(neuralRenderingEyeTrackedSmoothingMs) \
	X(neuralRenderingEyeTrackedFreezeCrop) \
	X(neuralRenderingLadderBudgetMs) \
	X(neuralRenderingLadderReserveMs) \
	X(neuralRenderingLadderHandoffMs) \
	X(neuralRenderingDisableAboveMs) \
	X(neuralRenderingEnableBelowMs) \
	X(neuralRenderingCropDrop) \
	X(neuralRenderingForcedStage) \
	X(neuralRenderingEyeTrackedQuantizationPixels)

template <typename BasicJsonType>
void to_json(BasicJsonType& json, const FoveatedRender::Settings& settings)
{
	json = BasicJsonType::object();
#define OPENNR_WRITE_FOVEATED_SETTING(field) json[#field] = settings.field;
	OPENNR_FOVEATED_SETTINGS_FIELDS(OPENNR_WRITE_FOVEATED_SETTING)
#undef OPENNR_WRITE_FOVEATED_SETTING
}

template <typename BasicJsonType>
void from_json(const BasicJsonType& json, FoveatedRender::Settings& settings)
{
	const FoveatedRender::Settings defaults{};
	if (json.is_null()) {
		settings = defaults;
		return;
	}
#define OPENNR_READ_FOVEATED_SETTING(field) settings.field = json.value(#field, defaults.field);
	OPENNR_FOVEATED_SETTINGS_FIELDS(OPENNR_READ_FOVEATED_SETTING)
#undef OPENNR_READ_FOVEATED_SETTING
}

#undef OPENNR_FOVEATED_SETTINGS_FIELDS
#undef OPENNR_SEQUENTIAL_PASS_FIELDS

// ============================================================================
// Lifecycle
// ============================================================================

void FoveatedRender::PostPostLoad()
{
	bootSnapshot.LatchIfNeeded(settings);
	adaptiveCropController.Reset();

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
	NeuralRendering::ApplyFoveatedLdr();
	func(imageSpaceShader, shape, param);
}

void FoveatedRender::ClearShaderCache()
{
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
	case 5:
		break;
	default:
		return false;
	}
	return true;
}

void FoveatedRender::ClampSettings()
{
	const auto clampFinite = [](float value, float fallback, float minimum, float maximum) {
		return std::clamp(std::isfinite(value) ? value : fallback, minimum, maximum);
	};
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
			(settings.neuralRenderingModelResolution < 70 ? 70 : 100);
	settings.neuralRenderingCoverage = NeuralRendering::NormalizeNeuralCoverage(settings.neuralRenderingCoverage);
	if constexpr (NeuralRendering::kFullResolutionNeuralRenderingOnly) {
		// Reduced NR model area weakens the neural effect: this build evaluates every
		// NR pixel at the full display-eye resolution. Saved reduced tiers, adaptive
		// tiering and render-resolution pre-upscale NR are normalized off here.
		settings.neuralRenderingModelResolution = 100;
		settings.neuralRenderingAdaptiveEnabled = false;
		settings.neuralRenderingAdaptiveCropEnabled = false;
		settings.neuralRenderingPreUpscale = 0;
	}
	if (settings.neuralRenderingPreset == 4 || settings.neuralRenderingPreset > 5)
		settings.neuralRenderingPreset = 5;
	settings.neuralRenderingIntensity = std::clamp(settings.neuralRenderingIntensity, 0.0f, 2.0f);
	settings.neuralRenderingLocalTone = std::clamp(settings.neuralRenderingLocalTone, 0.0f, 2.0f);
	settings.neuralRenderingLocalStructure = std::clamp(settings.neuralRenderingLocalStructure, 0.0f, 2.0f);
	settings.neuralRenderingSkinStructure = std::clamp(settings.neuralRenderingSkinStructure, -1.0f, 2.0f);
	settings.neuralRenderingStyle = std::min(settings.neuralRenderingStyle, 2u);
	settings.neuralRenderingResultEditStrength = clampFinite(settings.neuralRenderingResultEditStrength, 1.0f, 0.0f, 2.0f);
	settings.neuralRenderingResultBrightening = clampFinite(settings.neuralRenderingResultBrightening, 1.0f, 0.0f, 2.0f);
	settings.neuralRenderingResultDarkening = clampFinite(settings.neuralRenderingResultDarkening, 1.0f, 0.0f, 2.0f);
	settings.neuralRenderingResultColor = clampFinite(settings.neuralRenderingResultColor, 1.0f, 0.0f, 2.0f);
	settings.neuralRenderingResultHueShiftStrength = clampFinite(settings.neuralRenderingResultHueShiftStrength, 1.0f, 0.0f, 2.0f);
	settings.neuralRenderingResultShadows = clampFinite(settings.neuralRenderingResultShadows, 1.0f, 0.0f, 2.0f);
	settings.neuralRenderingResultMidtones = clampFinite(settings.neuralRenderingResultMidtones, 1.0f, 0.0f, 2.0f);
	settings.neuralRenderingResultHighlights = clampFinite(settings.neuralRenderingResultHighlights, 1.0f, 0.0f, 2.0f);
	settings.neuralRenderingResultMaxBrighteningStops = clampFinite(settings.neuralRenderingResultMaxBrighteningStops, 0.0f, 0.0f, 4.0f);
	settings.neuralRenderingResultMaxDarkeningStops = clampFinite(settings.neuralRenderingResultMaxDarkeningStops, 0.0f, 0.0f, 4.0f);
	settings.neuralRenderingResultMaxColorChangeStops = clampFinite(settings.neuralRenderingResultMaxColorChangeStops, 0.0f, 0.0f, 4.0f);
	settings.neuralRenderingResultLargeScaleTone = clampFinite(settings.neuralRenderingResultLargeScaleTone, 1.0f, 0.0f, 2.0f);
	settings.neuralRenderingResultFineDetail = clampFinite(settings.neuralRenderingResultFineDetail, 1.0f, 0.0f, 2.0f);
	settings.neuralRenderingResultDetailRadius = clampFinite(settings.neuralRenderingResultDetailRadius, 1.0f, 0.1f, 8.0f);
	settings.neuralRenderingResultHaloSuppression = clampFinite(settings.neuralRenderingResultHaloSuppression, 0.0f, 0.0f, 1.0f);
	settings.neuralRenderingNearBlackProtection = clampFinite(settings.neuralRenderingNearBlackProtection, 0.0f, 0.0f, 2.0f);
	settings.neuralRenderingNearBlackThreshold = clampFinite(settings.neuralRenderingNearBlackThreshold, 0.035f, 0.001f, 0.25f);
	settings.neuralRenderingNearBlackLiftSoftness = clampFinite(settings.neuralRenderingNearBlackLiftSoftness, 0.001f, 0.00001f, 0.05f);
	settings.neuralRenderingStabilizeMode = std::min(settings.neuralRenderingStabilizeMode, 2u);
	settings.neuralRenderingStabilizeTimeMs = clampFinite(settings.neuralRenderingStabilizeTimeMs, 60.0f, 10.0f, 250.0f);
	settings.neuralRenderingStabilizeDepthThreshold = clampFinite(settings.neuralRenderingStabilizeDepthThreshold, 0.05f, 0.0f, 0.25f);
	settings.neuralRenderingStabilizeColorTolerance = clampFinite(settings.neuralRenderingStabilizeColorTolerance, 0.08f, 0.0f, 0.50f);
	// v01 retires the pre-upscale experiment; sequential NR is post-upscale only.
	settings.neuralRenderingPreUpscale = 0;
	settings.neuralRenderingResolveMode = std::min(settings.neuralRenderingResolveMode, 1u);
	settings.neuralRenderingMultiPass = std::min(settings.neuralRenderingMultiPass, 2u);
	settings.neuralRenderingStereoAtlasGuardPixels = std::clamp(settings.neuralRenderingStereoAtlasGuardPixels, 8u, 256u);
	settings.neuralRenderingAdaptiveSecondPassCostMs = clampFinite(settings.neuralRenderingAdaptiveSecondPassCostMs, 6.0f, 0.0f, 20.0f);
	auto& pass2 = settings.neuralRenderingPass2;
	switch (pass2.coveragePercent) {
	case 50: case 60: case 70: case 80: case 90: case 100:
		break;
	default:
		pass2.coveragePercent = 100;
		break;
	}
	if (pass2.modelResolution != 33 && pass2.modelResolution != 50 && pass2.modelResolution != 70 &&
		pass2.modelResolution != 75 && pass2.modelResolution != 80 && pass2.modelResolution != 85 &&
		pass2.modelResolution != 90 && pass2.modelResolution != 95 && pass2.modelResolution != 100)
		pass2.modelResolution = pass2.modelResolution < 33 ? 33 : (pass2.modelResolution < 70 ? 70 : 100);
	if constexpr (NeuralRendering::kFullResolutionNeuralRenderingOnly)
		pass2.modelResolution = 100;
	if (pass2.preset == 4 || pass2.preset > 5)
		pass2.preset = 5;
	pass2.intensity = clampFinite(pass2.intensity, 1.70f, 0.0f, 2.0f);
	pass2.localTone = clampFinite(pass2.localTone, 1.00f, 0.0f, 2.0f);
	pass2.localStructure = clampFinite(pass2.localStructure, 1.70f, 0.0f, 2.0f);
	pass2.skinStructure = clampFinite(pass2.skinStructure, -1.0f, -1.0f, 2.0f);
	pass2.style = std::min(pass2.style, 2u);
	pass2.resolveMode = std::min(pass2.resolveMode, 1u);
	pass2.resultEditStrength = clampFinite(pass2.resultEditStrength, 1.0f, 0.0f, 2.0f);
	pass2.resultBrightening = clampFinite(pass2.resultBrightening, 1.0f, 0.0f, 2.0f);
	pass2.resultDarkening = clampFinite(pass2.resultDarkening, 1.0f, 0.0f, 2.0f);
	pass2.resultColor = clampFinite(pass2.resultColor, 1.0f, 0.0f, 2.0f);
	pass2.resultHueShiftStrength = clampFinite(pass2.resultHueShiftStrength, 1.0f, 0.0f, 2.0f);
	pass2.resultShadows = clampFinite(pass2.resultShadows, 1.0f, 0.0f, 2.0f);
	pass2.resultMidtones = clampFinite(pass2.resultMidtones, 1.0f, 0.0f, 2.0f);
	pass2.resultHighlights = clampFinite(pass2.resultHighlights, 1.0f, 0.0f, 2.0f);
	pass2.resultMaxBrighteningStops = clampFinite(pass2.resultMaxBrighteningStops, 0.0f, 0.0f, 4.0f);
	pass2.resultMaxDarkeningStops = clampFinite(pass2.resultMaxDarkeningStops, 0.0f, 0.0f, 4.0f);
	pass2.resultMaxColorChangeStops = clampFinite(pass2.resultMaxColorChangeStops, 0.0f, 0.0f, 4.0f);
	pass2.resultLargeScaleTone = clampFinite(pass2.resultLargeScaleTone, 1.0f, 0.0f, 2.0f);
	pass2.resultFineDetail = clampFinite(pass2.resultFineDetail, 1.0f, 0.0f, 2.0f);
	pass2.resultDetailRadius = clampFinite(pass2.resultDetailRadius, 1.0f, 0.1f, 8.0f);
	pass2.resultHaloSuppression = clampFinite(pass2.resultHaloSuppression, 0.0f, 0.0f, 1.0f);
	pass2.stabilizeMode = std::min(pass2.stabilizeMode, 2u);
	pass2.stabilizeTimeMs = clampFinite(pass2.stabilizeTimeMs, 60.0f, 10.0f, 250.0f);
	pass2.stabilizeDepthThreshold = clampFinite(pass2.stabilizeDepthThreshold, 0.05f, 0.0f, 0.25f);
	pass2.stabilizeColorTolerance = clampFinite(pass2.stabilizeColorTolerance, 0.08f, 0.0f, 0.50f);
	pass2.blendMode = std::min(pass2.blendMode, 2u);
	pass2.maskMode = std::min(pass2.maskMode, 1u);
	pass2.featherWidth = clampFinite(pass2.featherWidth, 64.0f, 2.0f, 128.0f);
	pass2.falloffCurve = clampFinite(pass2.falloffCurve, 1.0f, 0.5f, 2.0f);
	pass2.ditherStrength = clampFinite(pass2.ditherStrength, 1.0f, 0.0f, 2.0f);
	if (settings.neuralRenderingTemporalReuseCadence != 0 &&
		settings.neuralRenderingTemporalReuseCadence != 2 &&
		settings.neuralRenderingTemporalReuseCadence != 3 &&
		settings.neuralRenderingTemporalReuseCadence != 4)
		settings.neuralRenderingTemporalReuseCadence = 0;
	settings.neuralRenderingTemporalDepthThreshold = std::clamp(settings.neuralRenderingTemporalDepthThreshold, 0.0f, 0.25f);
	settings.neuralRenderingTemporalColorTolerance = std::clamp(settings.neuralRenderingTemporalColorTolerance, 0.0f, 0.50f);
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
	if (settings.neuralRenderingAdaptiveTargetFps != 0)
		settings.neuralRenderingAdaptiveTargetFps = std::clamp(settings.neuralRenderingAdaptiveTargetFps, 15u, 60u);
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
	settings.neuralRenderingAdaptivePassIncreaseBelowMs = clampFinite(settings.neuralRenderingAdaptivePassIncreaseBelowMs, 14.0f, 10.0f, 30.0f);
	settings.neuralRenderingAdaptiveCropIncreaseBelowMs = clampFinite(settings.neuralRenderingAdaptiveCropIncreaseBelowMs, 16.0f, 10.0f, 30.0f);
	settings.neuralRenderingAdaptiveCropDecreaseAboveMs = clampFinite(settings.neuralRenderingAdaptiveCropDecreaseAboveMs, 18.0f, 10.0f, 30.0f);
	settings.neuralRenderingAdaptivePassDecreaseAboveMs = clampFinite(settings.neuralRenderingAdaptivePassDecreaseAboveMs, 20.0f, 10.0f, 30.0f);
	settings.neuralRenderingAdaptiveSmoothingMs = clampFinite(settings.neuralRenderingAdaptiveSmoothingMs, 250.0f, 0.0f, 1000.0f);
	settings.neuralRenderingAdaptiveDecreaseHoldMs = clampFinite(settings.neuralRenderingAdaptiveDecreaseHoldMs, 350.0f, 0.0f, 2500.0f);
	settings.neuralRenderingAdaptiveIncreaseHoldMs = clampFinite(settings.neuralRenderingAdaptiveIncreaseHoldMs, 1200.0f, 0.0f, 5000.0f);
	settings.neuralRenderingAdaptiveCooldownMs = clampFinite(settings.neuralRenderingAdaptiveCooldownMs, 1000.0f, 0.0f, 5000.0f);
	switch (settings.neuralRenderingAdaptiveCropMinimumCoverage) {
	case 50:
	case 60:
	case 70:
	case 80:
	case 90:
		break;
	default:
		settings.neuralRenderingAdaptiveCropMinimumCoverage = 60;
		break;
	}
	// v03 semantics: 100% means exactly the user-selected crop. Adaptive logic
	// may only shrink from that baseline; it never expands beyond the user's choice.
	settings.neuralRenderingAdaptiveCropMaximumCoverage = 100;
	// Keep the configured ladder ordered. If a user raises the minimum above
	// the saved maximum, preserving the requested floor is the least surprising
	// repair and avoids a controller with an empty legal range.
	if (settings.neuralRenderingAdaptiveCropMaximumCoverage < settings.neuralRenderingAdaptiveCropMinimumCoverage)
		settings.neuralRenderingAdaptiveCropMaximumCoverage = settings.neuralRenderingAdaptiveCropMinimumCoverage;
	settings.neuralRenderingAdaptiveCropDownshiftFrames = std::clamp(settings.neuralRenderingAdaptiveCropDownshiftFrames, 1u, 16u);
	settings.neuralRenderingAdaptiveCropUpshiftFrames = std::clamp(settings.neuralRenderingAdaptiveCropUpshiftFrames, 8u, 240u);
	settings.neuralRenderingAdaptiveCropMinimumDwellFrames = std::clamp(settings.neuralRenderingAdaptiveCropMinimumDwellFrames, 8u, 600u);
	settings.neuralRenderingAdaptiveCropTransitionFrames = std::clamp(settings.neuralRenderingAdaptiveCropTransitionFrames, 2u, 24u);
	settings.neuralRenderingEyeTrackedSmoothingMs = clampFinite(settings.neuralRenderingEyeTrackedSmoothingMs, 60.0f, 0.0f, 250.0f);
	settings.neuralRenderingEyeTrackedResponsiveness = clampFinite(settings.neuralRenderingEyeTrackedResponsiveness, 8.0f, 0.0f, 50.0f);
	settings.neuralRenderingEyeTrackedSlowPercent = clampFinite(settings.neuralRenderingEyeTrackedSlowPercent, 10.0f, 0.0f, 50.0f);
	settings.neuralRenderingEyeTrackedFastPercent = clampFinite(settings.neuralRenderingEyeTrackedFastPercent, 100.0f, 5.0f, 200.0f);
	settings.neuralRenderingEyeTrackedJumpPercent = clampFinite(settings.neuralRenderingEyeTrackedJumpPercent, 100.0f, 5.0f, 200.0f);
	settings.neuralRenderingEyeTrackedJumpSpeed = clampFinite(settings.neuralRenderingEyeTrackedJumpSpeed, 20.0f, 1.0f, 100.0f);
	settings.neuralRenderingEyeTrackedMaxLagPercent = clampFinite(settings.neuralRenderingEyeTrackedMaxLagPercent, 25.0f, 0.0f, 50.0f);
	settings.neuralRenderingLadderBudgetMs = clampFinite(settings.neuralRenderingLadderBudgetMs, 20.0f, 10.0f, 30.0f);
	settings.neuralRenderingLadderReserveMs = clampFinite(settings.neuralRenderingLadderReserveMs, 1.0f, 0.5f, 5.0f);
	settings.neuralRenderingLadderHandoffMs = clampFinite(settings.neuralRenderingLadderHandoffMs, 150.0f, 0.0f, 500.0f);
	settings.neuralRenderingAdaptiveFirstPassIncreaseBelowMs = clampFinite(settings.neuralRenderingAdaptiveFirstPassIncreaseBelowMs, 14.0f, 10.0f, 30.0f);
	settings.neuralRenderingAdaptiveFirstPassHoldMs = clampFinite(settings.neuralRenderingAdaptiveFirstPassHoldMs, 1200.0f, 0.0f, 5000.0f);
	settings.neuralRenderingAdaptiveFirstPassCostMs = clampFinite(settings.neuralRenderingAdaptiveFirstPassCostMs, 6.0f, 0.0f, 20.0f);
	settings.neuralRenderingAdaptiveFirstPassMarginMs = clampFinite(settings.neuralRenderingAdaptiveFirstPassMarginMs, 1.0f, 0.0f, 5.0f);
	settings.neuralRenderingAdaptiveFirstPassRetryMs = clampFinite(settings.neuralRenderingAdaptiveFirstPassRetryMs, 3000.0f, 0.0f, 10000.0f);
	settings.neuralRenderingAdaptiveRelativeCropFloor = std::clamp(settings.neuralRenderingAdaptiveRelativeCropFloor, 60u, 100u) / 5u * 5u;
	settings.neuralRenderingAdaptiveRelativeCropStep = std::clamp(settings.neuralRenderingAdaptiveRelativeCropStep, 5u, 20u) / 5u * 5u;
	settings.neuralRenderingEyeTrackedQuantizationPixels = std::clamp(settings.neuralRenderingEyeTrackedQuantizationPixels, 0u, 64u);
	settings.neuralRenderingEyeTrackedDeadZonePercent = clampFinite(settings.neuralRenderingEyeTrackedDeadZonePercent, 0.0f, 0.0f, 10.0f);
	// Preset clamping reads from Upscaling::Settings now.
	auto& sharedPreset = globals::features::upscaling.settings.presetDLSS;
	sharedPreset = std::min(sharedPreset, 6u);
	if (!IsPresetCompatibleWithMode(sharedPreset)) {
		sharedPreset = 3;  // Fall back to L
	}
	// Retired saved values cannot reactivate unsupported render modes.
	settings.dlssMode = 0;
	settings.stretchMode = 1;
	settings.peripheryBlurRadius = 1.0f;
	settings.subrectBlendMode = 2;
	settings.subrectFeatherWidth = 128.0f;
	settings.subrectFalloffCurve = 0.5f;
	settings.subrectDitherStrength = 1.0f;
	settings.neuralRenderingSinglePassLadder = true;
	settings.neuralRenderingStyle = 0;
	settings.neuralRenderingPreset = 5;
	settings.neuralRenderingCoverage = 100;
	settings.neuralRenderingModelResolution = 100;
	settings.neuralRenderingResolveMode = 1;
	settings.neuralRenderingMultiPass = 0;
	settings.neuralRenderingPreUpscale = 0;
	settings.neuralRenderingStereoAtlas = true;
	settings.neuralRenderingTemporalReuseCadence = 0;
	settings.neuralRenderingTemporalReuseStaggerEyes = false;
	settings.neuralRenderingStabilizeMode = 0;
	settings.neuralRenderingStabilizeDetail = false;
	settings.neuralRenderingResultDarkening = 1.0f;
	settings.neuralRenderingResultHueShiftStrength = 1.0f;
	settings.neuralRenderingResultShadows = 1.0f;
	settings.neuralRenderingResultMidtones = 1.0f;
	settings.neuralRenderingResultHaloSuppression = 0.0f;
	settings.neuralRenderingEyeTrackedFoveation = true;
	settings.neuralRenderingEyeTrackedAdaptiveSmoothing = false;
	settings.neuralRenderingEyeTrackedDeadZonePercent = 0.0f;
	settings.neuralRenderingForcedStage = std::min(settings.neuralRenderingForcedStage, 6u);
	if (settings.neuralRenderingForcedStage != 0) settings.neuralRenderingAdaptiveEnabled = true;
	settings.neuralRenderingCropDrop = NeuralRendering::SinglePassLadder::NormalizeCropStep(settings.neuralRenderingCropDrop);
	settings.neuralRenderingDisableAboveMs = clampFinite(settings.neuralRenderingDisableAboveMs, 24.0f, 10.0f, 50.0f);
	settings.neuralRenderingEnableBelowMs = clampFinite(settings.neuralRenderingEnableBelowMs, 14.0f, 1.0f, 50.0f);

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
	const std::uint32_t manualPasses = 1;
	const bool restoringPasses = adaptivePassInitialized && adaptiveActivePasses < manualPasses;
	const bool cropWasActive = adaptiveCropController.IsRuntimeActive();
	adaptiveCropController.Reset();
	adaptiveConfiguredPasses = manualPasses;
	adaptiveActivePasses = manualPasses;
	adaptivePassInitialized = false;
	adaptiveCropTargetCoverage = 100;
	adaptiveFilteredFrameTimeMs = 0.0f;
	adaptiveLastFrameTimeMs = 0.0f;
	adaptiveDecreaseHoldMs = 0.0f;
	adaptiveIncreaseHoldMs = 0.0f;
	adaptiveCooldownRemainingMs = 0.0f;
	adaptivePendingAction = 0;
	adaptiveLastAction = 0;
	adaptiveLastActionFrom = 0;
	adaptiveLastActionTo = 0;
	adaptiveLastActionFrameTimeMs = 0.0f;
	adaptivePolicyObserved = false;
	adaptiveWorkloadObserved = false;
	adaptiveLadderStage = 0;
	adaptiveModelResolution = 100;
	adaptiveBlockedGrowthStage = UINT32_MAX;
	adaptiveGrowthBaselineMs = adaptiveBlockedGrowthBaselineMs = 0.0f;
	adaptiveResumeRemainingMs = 0.0f;
	if (cropWasActive)
		FoveatedRenderImpl::Core::ResetAdaptiveCropHandoff();
	if (restoringPasses)
		NeuralRendering::ResetHistory();
}
bool FoveatedRender::IsEyeTrackedFoveationEnabled() const
{
	// The performance crop must not become a second owner of UV geometry. Keep
	// both the explicit native-gaze setting and the existing stereo eye-tracking
	// setting as hard lockouts.
	return settings.neuralRenderingEyeTrackedFoveation ||
		(globals::game::isVR && globals::features::vr.stereoOpt.settings.useEyeTracking);
}

void FoveatedRender::UpdateAdaptiveState(std::uint32_t frame, bool routeEligible)
{
	if (adaptiveUpdateFrame == frame) return;
	adaptiveUpdateFrame = frame;
	const auto& nrRenderer = NeuralRendering::Renderer::Instance();
	const auto& streamline = globals::features::upscaling.streamline;
	const bool recentDLSSFailure = streamline.lastDLSSFailureFrame != UINT32_MAX &&
		frame >= streamline.lastDLSSFailureFrame && frame - streamline.lastDLSSFailureFrame <= 1;
	const bool runtimeHealthy = !nrRenderer.IsFailureLatched() && !recentDLSSFailure;
	const auto method = globals::features::upscaling.GetUpscaleMethod();
	const bool nrEligible = routeEligible && IsActive() &&
		method == Upscaling::UpscaleMethod::kDLSS && GetDlssMode() == DlssMode::kDefault &&
		settings.neuralRenderingEnabled && !globals::features::upscaling.IsFrameGenerationActive() &&
		!globals::features::openNRCapture.settings.enableCapture &&
		settings.neuralRenderingPreUpscale == 0 && runtimeHealthy;

	const std::uint32_t requestedPasses = 1;

	if (!settings.neuralRenderingAdaptiveEnabled || !nrEligible) {
		if (adaptivePassInitialized || adaptiveCropController.IsRuntimeActive())
			ResetAdaptiveState();
		adaptiveConfiguredPasses = 1;
		adaptiveActivePasses = adaptiveConfiguredPasses;
		return;
	}

	const auto leftUV = subrectController.GetUV();
	const auto rightUV = subrectController.GetRightEyeUV();
	const bool geometryCompatible = leftUV.w > 0.01f && leftUV.h > 0.01f &&
		rightUV.w > 0.01f && rightUV.h > 0.01f &&
		leftUV.w == rightUV.w && leftUV.h == rightUV.h;
	const bool eyeTrackingOwnsOrigin = IsEyeTrackedFoveationEnabled();
	const bool cropPolicyAvailable = geometryCompatible;
	const bool decisionsSuspended = globals::state->isLoadingMenuOpen ||
		globals::state->IsPausedOrMenuOpen(globals::game::ui);
	const bool envelopeRejected = FoveatedRenderImpl::Core::vrSubrectFixedEnvelopeRejected ||
		FoveatedRenderImpl::Core::vrSubrectNeuralFixedEnvelopeRejected;
	const auto& upscaling = globals::features::upscaling;
	const auto displaySize = upscaling.perfMode.IsHookActive() ? upscaling.perfMode.GetDisplayScreenSize() : globals::state->screenSize;
	const float renderWidth = upscaling.perfMode.IsHookActive() ? static_cast<float>(upscaling.perfMode.GetRenderEyeWidth() * 2u) : displaySize.x * upscaling.resolutionScale.x;
	const float renderHeight = upscaling.perfMode.IsHookActive() ? static_cast<float>(upscaling.perfMode.GetRenderEyeHeight()) : displaySize.y * upscaling.resolutionScale.y;
	const std::array<float, 10> workloadKey{ leftUV.w, leftUV.h, rightUV.w, rightUV.h,
		displaySize.x, displaySize.y, renderWidth, renderHeight,
		static_cast<float>(upscaling.settings.qualityMode), static_cast<float>(upscaling.settings.presetDLSS) };
	if (adaptiveWorkloadObserved && adaptiveWorkloadKey != workloadKey) {
		adaptiveFilteredFrameTimeMs = 0.0f;
		adaptiveDecreaseHoldMs = adaptiveIncreaseHoldMs = 0.0f;
		adaptivePendingAction = 0;
		adaptiveBlockedGrowthStage = UINT32_MAX;
		adaptiveGrowthBaselineMs = adaptiveBlockedGrowthBaselineMs = 0.0f;
		adaptiveCooldownRemainingMs = settings.neuralRenderingAdaptiveCooldownMs;
	}
	adaptiveWorkloadKey = workloadKey;
	adaptiveWorkloadObserved = true;

	if (!adaptivePassInitialized) {
		adaptivePassInitialized = true;
		adaptiveConfiguredPasses = requestedPasses;
		adaptiveActivePasses = requestedPasses;
		adaptiveCropTargetCoverage = 100;
		adaptiveFilteredFrameTimeMs = 0.0f;
		adaptiveLastFrameTimeMs = 0.0f;
		adaptiveDecreaseHoldMs = 0.0f;
		adaptiveIncreaseHoldMs = 0.0f;
		adaptiveCooldownRemainingMs = 0.0f;
		adaptivePendingAction = 0;
	}
	if (requestedPasses != adaptiveConfiguredPasses) {
		const auto oldConfigured = adaptiveConfiguredPasses;
		adaptiveConfiguredPasses = requestedPasses;
		adaptiveActivePasses = std::min(adaptiveActivePasses, adaptiveConfiguredPasses);
		adaptiveDecreaseHoldMs = 0.0f;
		adaptiveIncreaseHoldMs = 0.0f;
		adaptiveCooldownRemainingMs = 0.0f;
		logger::info("[DLSSNR][ADAPTIVE-v05] configured pass ceiling {} -> {} active={}",
			oldConfigured, adaptiveConfiguredPasses, adaptiveActivePasses);
	}

	const NeuralRendering::SinglePassLadder::Config policyConfig{
		.budget = settings.neuralRenderingLadderBudgetMs,
		.reserve = settings.neuralRenderingLadderReserveMs,
		.disableAbove = settings.neuralRenderingDisableAboveMs,
		.enableBelow = settings.neuralRenderingEnableBelowMs,
		.decreaseHold = settings.neuralRenderingAdaptiveDecreaseHoldMs,
		.increaseHold = settings.neuralRenderingAdaptiveIncreaseHoldMs,
		.cooldown = settings.neuralRenderingAdaptiveCooldownMs,
		.smoothing = settings.neuralRenderingAdaptiveSmoothingMs,
		.cropFloor = 100u - 2u * NeuralRendering::SinglePassLadder::NormalizeCropStep(settings.neuralRenderingCropDrop),
		.cropStep = NeuralRendering::SinglePassLadder::NormalizeCropStep(settings.neuralRenderingCropDrop),
		.transitionFrames = settings.neuralRenderingAdaptiveCropTransitionFrames,
		.forcedStage = std::min(settings.neuralRenderingForcedStage, 6u),
	};
	if (!adaptivePolicyObserved || !(adaptivePolicyConfig == policyConfig)) {
		adaptivePolicyConfig = policyConfig;
		adaptivePolicyObserved = true;
		adaptiveBlockedGrowthStage = UINT32_MAX;
		adaptiveDecreaseHoldMs = adaptiveIncreaseHoldMs = 0.0f;
		adaptivePendingAction = 0;
		const auto quality = NeuralRendering::SinglePassLadder::Level(adaptiveLadderStage, policyConfig.cropStep);
		adaptiveCropTargetCoverage = quality.crop;
		adaptiveModelResolution = quality.model;
	}
	if (policyConfig.forcedStage != 0 && adaptiveLadderStage != policyConfig.forcedStage - 1) {
		const auto previousStage = adaptiveLadderStage;
		adaptiveLadderStage = policyConfig.forcedStage - 1;
		const auto quality = NeuralRendering::SinglePassLadder::Level(adaptiveLadderStage, policyConfig.cropStep);
		adaptiveCropTargetCoverage = quality.crop;
		adaptiveModelResolution = quality.model;
		if (!quality.nrEnabled || previousStage == NeuralRendering::SinglePassLadder::suspendedStage) adaptiveActivePasses = 0;
		adaptiveDecreaseHoldMs = adaptiveIncreaseHoldMs = 0.0f;
		adaptivePendingAction = 0;
		adaptiveCooldownRemainingMs = settings.neuralRenderingAdaptiveCooldownMs;
	}
	const auto selectedQuality = NeuralRendering::SinglePassLadder::Level(adaptiveLadderStage, policyConfig.cropStep);
	adaptiveCropTargetCoverage = cropPolicyAvailable ? selectedQuality.crop : 100u;
	adaptiveModelResolution = cropPolicyAvailable ? selectedQuality.model : 100u;

	float gpuFrameTimeMs = -1.0f;
	float sampleDeltaMs = 11.1f;
	bool freshTiming = false;
	bool timingAttempted = false;
	static std::uint32_t timingFrame = UINT32_MAX;
	if (globals::game::isVR) {
		timingAttempted = true;
		if (auto* compositor = RE::BSOpenVR::GetIVRCompositor()) {
			vr::Compositor_FrameTiming timing{};
			timing.m_nSize = sizeof(timing);
			if (compositor->GetFrameTiming(&timing) && timing.m_nFrameIndex != timingFrame) {
				timingFrame = timing.m_nFrameIndex;
				const float gpuMs = timing.m_flPreSubmitGpuMs + timing.m_flPostSubmitGpuMs;
				if (std::isfinite(gpuMs) && gpuMs > 0.0f) {
					gpuFrameTimeMs = gpuMs;
					freshTiming = true;
				}
				if (std::isfinite(timing.m_flClientFrameIntervalMs) && timing.m_flClientFrameIntervalMs > 0.0f)
					sampleDeltaMs = std::clamp(timing.m_flClientFrameIntervalMs, 1.0f, 100.0f);
			}
		}
	}

	bool qualityChanged = false;
	if (freshTiming) {
		adaptiveResumeRemainingMs = std::max(0.0f, adaptiveResumeRemainingMs - sampleDeltaMs);
		adaptiveLastFrameTimeMs = gpuFrameTimeMs;
		// A single loading hitch must not dominate the EMA for seconds. The 60 ms
		// filter cap is still above the highest configurable 50 ms threshold,
		// so sustained severe load continues to downshift normally.
		const float filterSampleMs = std::min(gpuFrameTimeMs, 60.0f);
		const float smoothingMs = std::clamp(settings.neuralRenderingAdaptiveSmoothingMs, 0.0f, 1000.0f);
		if (adaptiveFilteredFrameTimeMs <= 0.0f || smoothingMs <= 1.0f) {
			adaptiveFilteredFrameTimeMs = filterSampleMs;
		} else {
			const float alpha = std::clamp(1.0f - std::exp(-sampleDeltaMs / smoothingMs), 0.001f, 1.0f);
			adaptiveFilteredFrameTimeMs += (filterSampleMs - adaptiveFilteredFrameTimeMs) * alpha;
		}

		if (adaptiveCooldownRemainingMs > 0.0f) {
			adaptiveCooldownRemainingMs = std::max(0.0f, adaptiveCooldownRemainingMs - sampleDeltaMs);
			adaptiveDecreaseHoldMs = 0.0f;
			adaptiveIncreaseHoldMs = 0.0f;
			adaptivePendingAction = 0;
		} else {
			const bool cropTransitioning = adaptiveCropController.IsTransitioning();
			const auto previousAction = adaptivePendingAction;
			const bool blocked = adaptiveBlockedGrowthStage == adaptiveLadderStage &&
				adaptiveFilteredFrameTimeMs > adaptiveBlockedGrowthBaselineMs - policyConfig.reserve;
			const bool resumePending = adaptiveLadderStage != NeuralRendering::SinglePassLadder::suspendedStage && adaptiveActivePasses == 0;
			adaptivePendingAction = NeuralRendering::SinglePassLadder::Select(adaptiveLadderStage,
				adaptiveFilteredFrameTimeMs, policyConfig,
				(adaptiveActivePasses > 0 && nrRenderer.IsOutputTransitioning()) || cropTransitioning || adaptiveCropController.RenderCoverage() != adaptiveCropTargetCoverage || resumePending || adaptiveResumeRemainingMs > 0.0f || !cropPolicyAvailable || envelopeRejected || decisionsSuspended, blocked);

			if (previousAction != adaptivePendingAction)
				adaptiveDecreaseHoldMs = adaptiveIncreaseHoldMs = 0.0f;

			const bool decreasing = adaptivePendingAction == 1;
			const bool increasing = adaptivePendingAction == 2;
			if (decreasing) {
				adaptiveDecreaseHoldMs += sampleDeltaMs;
				adaptiveIncreaseHoldMs = 0.0f;
			} else if (increasing) {
				adaptiveIncreaseHoldMs += sampleDeltaMs;
				adaptiveDecreaseHoldMs = 0.0f;
			} else {
				adaptiveDecreaseHoldMs = 0.0f;
				adaptiveIncreaseHoldMs = 0.0f;
			}

			const bool actionReady = decreasing ?
				adaptiveDecreaseHoldMs >= settings.neuralRenderingAdaptiveDecreaseHoldMs :
				(increasing && adaptiveIncreaseHoldMs >=
					policyConfig.increaseHold);
			if (adaptivePendingAction != 0 && actionReady) {
				adaptiveLastAction = adaptivePendingAction;
				adaptiveLastActionFrameTimeMs = adaptiveFilteredFrameTimeMs;
				const auto oldStage = adaptiveLadderStage;
				if (adaptivePendingAction == 1) {
					adaptiveLadderStage = std::min(NeuralRendering::SinglePassLadder::suspendedStage, oldStage + 1);
					if (adaptiveLastActionFrom == adaptiveLadderStage && adaptiveGrowthBaselineMs > 0.0f) {
						adaptiveBlockedGrowthStage = adaptiveLadderStage;
						adaptiveBlockedGrowthBaselineMs = adaptiveGrowthBaselineMs;
					}
				} else {
					adaptiveLadderStage = oldStage - 1;
					adaptiveGrowthBaselineMs = adaptiveFilteredFrameTimeMs;
				}
				adaptiveLastActionFrom = oldStage;
				adaptiveLastActionTo = adaptiveLadderStage;
				const auto quality = NeuralRendering::SinglePassLadder::Level(adaptiveLadderStage, policyConfig.cropStep);
				adaptiveCropTargetCoverage = quality.crop;
				adaptiveModelResolution = quality.model;
				if (!quality.nrEnabled || oldStage == NeuralRendering::SinglePassLadder::suspendedStage) adaptiveActivePasses = 0;
				qualityChanged = true;

				if (qualityChanged) {
					adaptiveCooldownRemainingMs = settings.neuralRenderingAdaptiveCooldownMs;
					adaptiveDecreaseHoldMs = 0.0f;
					adaptiveIncreaseHoldMs = 0.0f;
					adaptivePendingAction = 0;
				}
			}
		}
	}

	if (timingAttempted && !freshTiming) {
		adaptiveDecreaseHoldMs = adaptiveIncreaseHoldMs = 0.0f;
		adaptivePendingAction = 0;
	}

	NeuralRendering::AdaptiveCropController::Config cropConfig;
	cropConfig.enabled = cropPolicyAvailable;
	cropConfig.hold = envelopeRejected || decisionsSuspended;
	cropConfig.maximumCoverage = 100;
	cropConfig.minimumCoverage = policyConfig.cropFloor;
	cropConfig.stepCoverage = policyConfig.cropStep;
	// v05 owns smoothing, hysteresis, holds and cooldown. The crop controller is
	// only a stereo-safe actuator/handoff mechanism, so its own decision delays
	// are one frame and cannot create a hidden second policy.
	cropConfig.downshiftFrames = 1;
	cropConfig.upshiftFrames = 1;
	cropConfig.minimumDwellFrames = 1;
	cropConfig.transitionFrames = settings.neuralRenderingAdaptiveCropTransitionFrames;
	const bool cropWasActive = adaptiveCropController.IsRuntimeActive();
	const std::uint32_t previousRenderCrop = cropWasActive ? adaptiveCropController.RenderCoverage() : 100u;
	const std::uint32_t currentCrop = cropWasActive ? adaptiveCropController.ActiveCoverage() : 100u;
	const bool driveCropDown = cropPolicyAvailable && !envelopeRejected && !decisionsSuspended && currentCrop > adaptiveCropTargetCoverage;
	const bool driveCropUp = cropPolicyAvailable && !envelopeRejected && !decisionsSuspended && currentCrop < adaptiveCropTargetCoverage;
	// Eye/gaze tracking keeps ownership of crop origin. Adaptive v05 changes only
	// scale relative to that live user-selected crop, exactly as v03 established.
	adaptiveCropController.Update(frame, cropConfig, cropPolicyAvailable,
		100, geometryCompatible, false, driveCropDown, false, true,
		driveCropDown, driveCropUp);
	if (cropWasActive && !adaptiveCropController.IsRuntimeActive())
		FoveatedRenderImpl::Core::ResetAdaptiveCropHandoff();
	const std::uint32_t committedRenderCrop = adaptiveCropController.IsRuntimeActive() ?
		adaptiveCropController.RenderCoverage() : 100u;
	if (adaptiveCropController.IsRuntimeActive() && previousRenderCrop != committedRenderCrop) {
		// The resident atlas and residual handoff preserve NR history on geometry
		// commits. Gaze motion retains the validated guide alignment.
		logger::info("[DLSSNR][ADAPTIVE-v05] crop geometry commit {}% -> {}% of selected crop frame={}",
			previousRenderCrop, committedRenderCrop, frame);
	}

	if (adaptiveLadderStage != NeuralRendering::SinglePassLadder::suspendedStage && adaptiveActivePasses == 0 &&
		!adaptiveCropController.IsTransitioning() && committedRenderCrop == adaptiveCropTargetCoverage &&
		cropPolicyAvailable && !envelopeRejected && !decisionsSuspended) {
		NeuralRendering::ResetHistory();
		adaptiveActivePasses = 1;
		adaptiveResumeRemainingMs = settings.neuralRenderingLadderHandoffMs;
		adaptiveCooldownRemainingMs = settings.neuralRenderingAdaptiveCooldownMs;
		adaptiveDecreaseHoldMs = adaptiveIncreaseHoldMs = 0.0f;
		adaptivePendingAction = 0;
	}

	if (qualityChanged) {
		const char* action = adaptiveLastAction == 1 ? "quality-down" : "quality-up";
		logger::info("[DLSSNR][ADAPTIVE-v05] action={} {} -> {} raw={:.2f}ms filtered={:.2f}ms passes={}/{} cropTarget={} atlas={} gaze={}",
			action, adaptiveLastActionFrom, adaptiveLastActionTo,
			adaptiveLastFrameTimeMs, adaptiveFilteredFrameTimeMs,
			adaptiveActivePasses, adaptiveConfiguredPasses, adaptiveCropTargetCoverage,
			nrRenderer.IsStereoAtlasActive(), eyeTrackingOwnsOrigin);
	}

	if (frame % 300 == 0) {
		logger::info("[DLSSNR][BUDGET-v05] frame={} fresh={} raw={:.2f} filtered={:.2f} passes={}/{} cropRender={} cropTarget={} decHold={:.0f} incHold={:.0f} cooldown={:.0f} atlas={} gaze={}",
			frame, freshTiming, adaptiveLastFrameTimeMs, adaptiveFilteredFrameTimeMs,
			adaptiveActivePasses, adaptiveConfiguredPasses,
			adaptiveCropController.IsRuntimeActive() ? adaptiveCropController.RenderCoverage() : 100u,
			adaptiveCropTargetCoverage, adaptiveDecreaseHoldMs, adaptiveIncreaseHoldMs,
			adaptiveCooldownRemainingMs, nrRenderer.IsStereoAtlasActive(), eyeTrackingOwnsOrigin);
	}
}
Util::Subrect::UVRegion FoveatedRender::GetEffectiveLeftUV() const
{
	const auto base = subrectController.GetUV();
	if (!adaptiveCropController.IsRuntimeActive())
		return base;
	const float scale = std::clamp(static_cast<float>(adaptiveCropController.RenderCoverage()) / 100.0f, 0.01f, 1.0f);
	Util::Subrect::UVRegion out = base;
	const float centerX = base.x + base.w * 0.5f;
	const float centerY = base.y + base.h * 0.5f;
	out.w = std::clamp(base.w * scale, 0.01f, 1.0f);
	out.h = std::clamp(base.h * scale, 0.01f, 1.0f);
	out.x = std::clamp(centerX - out.w * 0.5f, 0.0f, 1.0f - out.w);
	out.y = std::clamp(centerY - out.h * 0.5f, 0.0f, 1.0f - out.h);
	return out;
}

Util::Subrect::UVRegion FoveatedRender::GetEffectiveRightUV() const
{
	const auto base = subrectController.GetRightEyeUV();
	if (!adaptiveCropController.IsRuntimeActive())
		return base;
	const float scale = std::clamp(static_cast<float>(adaptiveCropController.RenderCoverage()) / 100.0f, 0.01f, 1.0f);
	Util::Subrect::UVRegion out = base;
	const float centerX = base.x + base.w * 0.5f;
	const float centerY = base.y + base.h * 0.5f;
	out.w = std::clamp(base.w * scale, 0.01f, 1.0f);
	out.h = std::clamp(base.h * scale, 0.01f, 1.0f);
	out.x = std::clamp(centerX - out.w * 0.5f, 0.0f, 1.0f - out.w);
	out.y = std::clamp(centerY - out.h * 0.5f, 0.0f, 1.0f - out.h);
	return out;
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
	return std::min(globals::features::upscaling.settings.presetDLSS, 6u);
}

float FoveatedRender::GetActiveSharpnessDLSS() const
{
	return std::clamp(globals::features::upscaling.settings.sharpnessDLSS, 0.0f, 3.0f);
}

float FoveatedRender::GetRenderScaleForQuality(uint qualityMode)
{
	return Upscaling::GetQualityModeRatio(qualityMode);
}

bool FoveatedRender::IsPresetCompatibleWithMode(uint presetIndex) const
{
	// Preset indices: 0=Default, 1=J, 2=K, 3=L, 4=M, 5=E, 6=F
	// Faster mode: J(1) and K(2) are incompatible; E(5) is unverified there.
	if (GetDlssMode() == DlssMode::kFaster) {
		return presetIndex != 1 && presetIndex != 2 && presetIndex != 5;
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

	void FoveatedRender::DrawNeuralRenderingStatusButton()
	{
		const bool enabled = settings.neuralRenderingEnabled;
		const auto method = globals::features::upscaling.GetUpscaleMethod();
		auto& upscaling = globals::features::upscaling;
		const bool frameGenerationConfigured = upscaling.IsFrameGenerationConfiguredForSession();
		const bool frameGenerationActive = upscaling.IsFrameGenerationActive();
		const bool hdrConfigured = globals::features::hdrDisplay.loaded &&
			globals::features::hdrDisplay.settings.enableHDR;
		const bool routeSupported = method == Upscaling::UpscaleMethod::kDLSS &&
			!frameGenerationConfigured && !frameGenerationActive &&
			(globals::game::isVR ? (IsActive() && GetDlssMode() == DlssMode::kDefault &&
				upscaling.perfMode.IsHookActive()) : !hdrConfigured);
		auto& renderer = NeuralRendering::Renderer::Instance();
		const bool failed = renderer.IsFailureLatched();
		const bool waitingForFirstFrame = renderer.SuccessfulFrames() == 0;
		const bool automaticallySuspended = settings.neuralRenderingAdaptiveEnabled && adaptivePassInitialized && adaptiveActivePasses == 0;
		const char* state = !enabled ? "OFF" : !routeSupported ? "UNAVAILABLE" : failed ? "ERROR" : automaticallySuspended ? (adaptiveLadderStage == 5 ? "SUSPENDED" : "RESUMING") :
			waitingForFirstFrame ? "STARTING" : "ON";
		const std::string label = std::format("NEURAL RENDERING  |  {}", state);

		ImVec4 color = ImGui::GetStyleColorVec4(ImGuiCol_Button);
		if (enabled && routeSupported && !failed && !waitingForFirstFrame && !automaticallySuspended)
			color = ImVec4(0.20f, 0.58f, 0.50f, 1.0f);
		else if (failed)
			color = ImVec4(0.58f, 0.20f, 0.22f, 1.0f);
		else if (enabled)
			color = ImVec4(0.66f, 0.37f, 0.20f, 1.0f);
		ImGui::PushStyleColor(ImGuiCol_Button, color);
		ImGui::PushStyleColor(ImGuiCol_ButtonHovered, ImVec4(color.x + 0.08f, color.y + 0.08f, color.z + 0.08f, color.w));
		ImGui::PushStyleColor(ImGuiCol_ButtonActive, ImVec4(color.x - 0.05f, color.y - 0.05f, color.z - 0.05f, color.w));
		ImGui::PushStyleVar(ImGuiStyleVar_FramePadding, ImVec2(12.0f * Util::GetUIScale(), 10.0f * Util::GetUIScale()));
		if (ImGui::Button(label.c_str(), ImVec2(-1.0f, 46.0f * Util::GetUIScale()))) {
			settings.neuralRenderingEnabled = !settings.neuralRenderingEnabled;
			NeuralRendering::RequestHistoryReset();
		}
		ImGui::PopStyleVar();
		ImGui::PopStyleColor(3);

		std::string detail;
		if (!enabled) {
			detail = "Click to enable Neural Rendering.";
		} else if (frameGenerationConfigured || frameGenerationActive) {
			detail = "Unavailable: Frame Generation is configured for this session.";
		} else if (method != Upscaling::UpscaleMethod::kDLSS) {
			detail = "Unavailable: select NVIDIA DLSS as the upscaler.";
		} else if (!globals::game::isVR && hdrConfigured) {
			detail = "Unavailable: the flat Neural Rendering route does not support HDR Display.";
		} else if (globals::game::isVR && !IsActive()) {
			detail = "Unavailable: enable Foveated DLSS and restart.";
		} else if (globals::game::isVR && GetDlssMode() != DlssMode::kDefault) {
			detail = "Unavailable: VR Neural Rendering requires Default DLSS mode.";
		} else if (globals::game::isVR && !globals::features::upscaling.perfMode.IsHookActive()) {
			detail = "Unavailable: VR Neural Rendering requires active PerfMode.";
		} else if (failed) {
			detail = std::format("Runtime error: {}. Use Reset Neural Rendering to retry.", renderer.StatusText());
		} else if (automaticallySuspended) {
			detail = "Adaptive controller has suspended NR. SR remains active; NR restores after sustained headroom and crop commit.";
		} else if (waitingForFirstFrame) {
			detail = std::format("Starting: waiting for the first NR frame. Runtime: {}.", renderer.StatusText());
		} else {
			detail = std::format("Ready. {} successful evaluations this session.", renderer.SuccessfulFrames());
		}
		ImGui::TextDisabled("%s", detail.c_str());
	}

	void FoveatedRender::DrawSettings(bool showSharedPanelNote, bool vrControlsFirst,
		bool showNeuralRenderingStatusButton)
	{
		ClampSettings();
		if (showNeuralRenderingStatusButton)
			DrawNeuralRenderingStatusButton();
		// Keep all Neural Rendering prose inside the shared, width-aware helper so
		// the desktop and VR panel use the same wrapping rules.
		const auto drawWrapped = [](const char* text) { Util::UI::DrawWrappedText(text); };
		const auto drawDisabledWrapped = [](const char* text) { Util::UI::DrawWrappedDisabledText(text); };
		const auto drawWarningWrapped = [](const char* text) { Util::UI::DrawWrappedWarningText(text); };
	const auto drawVrControls = [&]() {
	// ── VR-only knobs ──
	if (globals::game::isVR) {
		ImGui::TextDisabled("VR DLSS: Default | Periphery: Point");
		ImGui::SliderInt(T(TKEY("foveated_periphery_aa_label"), "Periphery AA"), reinterpret_cast<int*>(&settings.peripheryAAMode), 0, 1, PeripheryAAModeName((PeripheryAAMode)settings.peripheryAAMode));
		if (GetPeripheryAAMode() == PeripheryAAMode::kTemporalSmooth) {
			ImGui::TextWrapped(T(TKEY("foveated_periphery_aa_temporal_desc"), "Blends the stretched periphery with motion-reprojected history to reduce flicker."));
				ImGui::SliderFloat(T(TKEY("foveated_smoothing"), "Smoothing"), &settings.peripheryTemporalAlpha, 0.05f, 0.5f, "%.2f");
				if (auto _tt = Util::HoverTooltipWrapper()) {
					drawWrapped(T(TKEY("foveated_smoothing_tooltip"), "Lower = more temporal history (smoother but may ghost). Higher = more responsive."));
				}
		}

		ImGui::TextDisabled("Inner edge: Dither | width 128 px | falloff 0.5 | noise 1.0");
		ImGui::SliderInt(T(TKEY("foveated_mask_shape_label"), "Edge Shape"), reinterpret_cast<int*>(&settings.subrectMaskMode), 0, 1,
			SubrectMaskModeName(GetSubrectMaskMode()));
		if (GetSubrectMaskMode() == SubrectMaskMode::kOval)
			ImGui::TextWrapped(T(TKEY("foveated_mask_oval_desc"),
				"Oval: a distance-corrected elliptical feather/dither mask that removes the box corners. The DLSS/Feature 18 work is still evaluated over the rectangular bounding region; this changes only the composite edge."));
		else
			ImGui::TextWrapped(T(TKEY("foveated_mask_rectangle_desc"),
				"Rectangle: keep the original rectangular feather/dither mask. Use this fallback if the oval edge is not preferred."));

		ImGui::Separator();

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
			auto* tex = Util::AsReal(fb.texture);
			subrectController.DrawEditor(Util::AsReal(fb.SRV), tex, 0.5f, 0.0f, Util::Subrect::OpaquePreviewBlendCallback);
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
		auto& neuralRenderer = NeuralRendering::Renderer::Instance();
		if (!supportedRoute) {
			if (globals::features::upscaling.IsFrameGenerationConfiguredForSession())
				drawWarningWrapped("Disable Frame Generation and restart before enabling Neural Rendering.");
			else
				drawWarningWrapped(T(TKEY("neural_rendering_unavailable"), "Requires DLSS. VR also requires Default mode and active PerfMode."));
			ImGui::BeginDisabled();
		}
		if (settings.neuralRenderingEnabled) {
			drawDisabledWrapped("Tune NR quality, output shaping, and optional frame-time controls.");

			ImGui::TextDisabled("Visual style: Natural | NR resolution and coverage: controller managed");
			bool custom = false;
			custom |= ImGui::SliderFloat(T(TKEY("neural_rendering_intensity"), "Intensity"), &settings.neuralRenderingIntensity, 0.0f, 2.0f, "%.2f");
			custom |= ImGui::SliderFloat(T(TKEY("neural_rendering_local_tone"), "Local Tone"), &settings.neuralRenderingLocalTone, 0.0f, 2.0f, "%.2f");
			custom |= ImGui::SliderFloat(T(TKEY("neural_rendering_local_structure"), "Local Structure"), &settings.neuralRenderingLocalStructure, 0.0f, 2.0f, "%.2f");
			custom |= ImGui::SliderFloat(T(TKEY("neural_rendering_skin_structure"), "Skin Structure"), &settings.neuralRenderingSkinStructure, -1.0f, 2.0f, "%.2f");
			custom |= ImGui::Checkbox(T(TKEY("neural_rendering_auto_mask"), "Automatic Mask"), &settings.neuralRenderingAutoMask);
			custom |= ImGui::Checkbox(T(TKEY("neural_rendering_ui_correction"), "UI Correction"), &settings.neuralRenderingUICorrection);
			if (custom)
				settings.neuralRenderingPreset = 5;

			if (ImGui::CollapsingHeader("Adaptive Performance")) {
				if (ImGui::Checkbox("Enable adaptive performance controller", &settings.neuralRenderingAdaptiveEnabled) && !settings.neuralRenderingAdaptiveEnabled) settings.neuralRenderingForcedStage = 0;
				ImGui::TextWrapped("Two crop reductions, then NR resolution 85% and 70%, then NR off at 100% of your selected crop. Recovery reverses the order. Stereo atlas is permanent.");
				const char* stageModes[] = { "Auto", "Force stage 1", "Force stage 2", "Force stage 3", "Force stage 4", "Force stage 5", "Force stage 6 (NR off)" };
				int forcedStage = static_cast<int>(settings.neuralRenderingForcedStage);
				if (ImGui::Combo("Controller mode", &forcedStage, stageModes, 7)) {
					settings.neuralRenderingForcedStage = static_cast<uint>(forcedStage);
					if (forcedStage != 0) settings.neuralRenderingAdaptiveEnabled = true;
				}
				const char* cropDrops[] = { "20 points: 100 / 80 / 60", "15 points: 100 / 85 / 70", "10 points: 100 / 90 / 80" };
				int cropDrop = settings.neuralRenderingCropDrop == 10 ? 2 : settings.neuralRenderingCropDrop == 15 ? 1 : 0;
				if (ImGui::Combo("Crop reduction per step", &cropDrop, cropDrops, 3))
					settings.neuralRenderingCropDrop = cropDrop == 2 ? 10u : cropDrop == 1 ? 15u : 20u;
				ImGui::SliderFloat("GPU budget", &settings.neuralRenderingLadderBudgetMs, 10.0f, 30.0f, "%.1f ms");
				ImGui::SliderFloat("Recovery headroom", &settings.neuralRenderingLadderReserveMs, 0.5f, 5.0f, "%.1f ms");
				ImGui::SliderFloat("Disable NR above (stage 5 only)", &settings.neuralRenderingDisableAboveMs, 10.0f, 50.0f, "%.1f ms");
				ImGui::SliderFloat("Re-enable NR below (stage 6 only)", &settings.neuralRenderingEnableBelowMs, 1.0f, 50.0f, "%.1f ms");
				if (settings.neuralRenderingEnableBelowMs >= settings.neuralRenderingDisableAboveMs)
					drawWarningWrapped("Re-enable must be below Disable. NR on/off changes are held until the thresholds are ordered.");
				ImGui::SliderFloat("Frametime smoothing", &settings.neuralRenderingAdaptiveSmoothingMs, 0.0f, 1000.0f, "%.0f ms");
				ImGui::SliderFloat("Decrease hold", &settings.neuralRenderingAdaptiveDecreaseHoldMs, 0.0f, 2500.0f, "%.0f ms");
				ImGui::SliderFloat("Increase hold", &settings.neuralRenderingAdaptiveIncreaseHoldMs, 0.0f, 5000.0f, "%.0f ms");
				ImGui::SliderFloat("Cooldown after change", &settings.neuralRenderingAdaptiveCooldownMs, 0.0f, 5000.0f, "%.0f ms");
				ImGui::SliderFloat("NR transition smoothing", &settings.neuralRenderingLadderHandoffMs, 0.0f, 500.0f, "%.0f ms");
				ImGui::TextDisabled("Stage %u/6 | crop %u%% | NR %u%% | %s | GPU %.2f ms", adaptiveLadderStage + 1,
					adaptiveCropTargetCoverage, adaptiveModelResolution,
					adaptiveActivePasses == 0 ? "NR suspended / waiting for crop" : "NR active", adaptiveFilteredFrameTimeMs);
				if (adaptiveCropController.IsTransitioning() || adaptiveCropController.RenderCoverage() != adaptiveCropTargetCoverage || adaptiveResumeRemainingMs > 0.0f || (adaptiveActivePasses > 0 && neuralRenderer.IsOutputTransitioning())) ImGui::TextUnformatted("Settling: wait before measuring this stage");
				ImGui::TextDisabled("Hold down %.0f ms | hold up %.0f ms | cooldown %.0f ms", adaptiveDecreaseHoldMs, adaptiveIncreaseHoldMs, adaptiveCooldownRemainingMs);
			}


			ImGui::TextDisabled("Pipeline: SR → one stereo-atlas NR pass | Matched Residual");

			if (ImGui::CollapsingHeader("NR near-black protection")) {
				ImGui::SliderFloat("Protection strength", &settings.neuralRenderingNearBlackProtection, 0.0f, 2.0f, "%.2f");
				ImGui::SliderFloat("Dark threshold", &settings.neuralRenderingNearBlackThreshold, 0.001f, 0.25f, "%.3f");
				ImGui::SliderFloat("Positive lift onset", &settings.neuralRenderingNearBlackLiftSoftness, 0.00001f, 0.05f, "%.5f");
				if (auto _tt = Util::HoverTooltipWrapper()) drawWrapped("Smoothly enables protection as NR brightening grows, preventing a hard switch when small color edits cross zero brightness. Larger values preserve more tiny brightening edits.");
				drawWrapped("Inside the NR region only. Reduces positive NR edits on originally near-black pixels after result shaping; darker edits and bright source pixels are preserved. 0 disables it, 1 is normal, 2 protects more of the threshold range. Higher values also reduce intentional shadow lifting. Original RGB peak controls eligibility so saturated highlights are preserved.");
				drawWrapped("Uses the ResultShaping GPU pass; no new NR evaluation or temporal filter. If that pass was inactive, enabling protection adds one postprocess dispatch per eye. Measures the shared output shaping/protection/transition pass.");
				ImGui::Checkbox("Measure NR postprocess GPU cost", &measureNRProtection);
				auto* profiler = globals::profiler;
				if (measureNRProtection && profiler && profiler->IsUserEnabled()) {
					profiler->RequestCapture(Profiler::CaptureMode::GPU, "NeuralRendering::ResultShaping");
					bool fresh = false;
					for (const auto& timer : profiler->GetResults())
						if (timer.name == "NeuralRendering::ResultShaping" && timer.hasGpu && timer.activeGpu && globals::state->frameCount - profiler->GetCapturedGpuFrameCount() <= 10) {
							ImGui::Text("NR postprocess GPU: %.3f ms latest, %.3f ms rolling average", timer.gpuTimeMs, timer.avgMs);
							fresh = true;
						}
					if (!fresh) ImGui::TextUnformatted("GPU timing: waiting for active NR postprocess");
				} else if (measureNRProtection) drawWrapped("Enable runtime profiling in the Profiling menu to measure GPU cost.");
				drawWrapped("Timing includes output shaping, near-black protection and controller transitions, combined across the eyes that ran. Compare protection 0 versus your chosen strength with the same scene and settings. Turn measurement off after tuning.");

			}

			if (ImGui::CollapsingHeader("NR Result Shaping")) {
				ImGui::Checkbox("Shape the NR result", &settings.neuralRenderingResultShapingEnabled);
				if (auto _tt = Util::HoverTooltipWrapper())
					drawWrapped("Applies optional image-space tone, color, and detail edits after Feature 18. The native NR model settings stay unchanged.");
				if (settings.neuralRenderingResultShapingEnabled) {
					ImGui::SliderFloat("Edit strength", &settings.neuralRenderingResultEditStrength, 0.0f, 2.0f, "%.2f");
					if (auto _tt = Util::HoverTooltipWrapper())
						drawWrapped("Scales the whole NR correction: 0 removes it, 1 preserves it, and 2 doubles it.");
					ImGui::SliderFloat("Brightening", &settings.neuralRenderingResultBrightening, 0.0f, 2.0f, "%.2f");
					ImGui::SliderFloat("Color", &settings.neuralRenderingResultColor, 0.0f, 2.0f, "%.2f");
					if (auto _tt = Util::HoverTooltipWrapper())
						drawWrapped("Scales how far NR moves colors toward or away from gray.");
					ImGui::SliderFloat("Highlights", &settings.neuralRenderingResultHighlights, 0.0f, 2.0f, "%.2f");
					ImGui::SliderFloat("Max brightening", &settings.neuralRenderingResultMaxBrighteningStops, 0.0f, 4.0f, "%.2f stops");
					ImGui::SliderFloat("Max darkening", &settings.neuralRenderingResultMaxDarkeningStops, 0.0f, 4.0f, "%.2f stops");
					ImGui::SliderFloat("Max color change", &settings.neuralRenderingResultMaxColorChangeStops, 0.0f, 4.0f, "%.2f stops");
					ImGui::TextDisabled("A zero limit leaves that change uncapped.");
					ImGui::SliderFloat("Large-scale tone", &settings.neuralRenderingResultLargeScaleTone, 0.0f, 2.0f, "%.2f");
					ImGui::SliderFloat("Fine detail", &settings.neuralRenderingResultFineDetail, 0.0f, 2.0f, "%.2f");
					ImGui::SliderFloat("Detail radius", &settings.neuralRenderingResultDetailRadius, 0.1f, 8.0f, "%.2f%%");
					if (auto _tt = Util::HoverTooltipWrapper())
						drawWrapped("Sets where the broad lighting change ends and fine detail begins, as a share of image height.");
				}

			}

			if (ImGui::CollapsingHeader("Eye-tracked Foveation")) {
				ImGui::TextWrapped("Native OpenVR gaze is used when available. Freeze crop selects the fixed centre for comparison.");
				ImGui::SliderFloat("Gaze smoothing", &settings.neuralRenderingEyeTrackedSmoothingMs, 0.0f, 250.0f, "%.0f ms");
				ImGui::Checkbox("Freeze crop at selected centre (comparison)", &settings.neuralRenderingEyeTrackedFreezeCrop);
				int quantizationPixels = static_cast<int>(settings.neuralRenderingEyeTrackedQuantizationPixels);
				if (ImGui::SliderInt("Crop movement quantization", &quantizationPixels, 0, 64, quantizationPixels == 0 ? "Off" : "%d input px"))
					settings.neuralRenderingEyeTrackedQuantizationPixels = static_cast<uint>(quantizationPixels);
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

				if (neuralRenderer.IsFailureLatched() || neuralRenderer.IsRecoveryLimited() ||
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
