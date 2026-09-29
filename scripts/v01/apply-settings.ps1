$ErrorActionPreference = 'Stop'

function Replace-Exact {
    param(
        [Parameter(Mandatory=$true)][string]$Path,
        [Parameter(Mandatory=$true)][string]$Old,
        [Parameter(Mandatory=$true)][string]$New
    )
    $resolved = Resolve-Path $Path
    $text = [IO.File]::ReadAllText($resolved).Replace("`r`n", "`n")
    $count = ([regex]::Matches($text, [regex]::Escape($Old))).Count
    if ($count -ne 1) { throw "Expected exactly one source block in $Path, found $count" }
    $text = $text.Replace($Old, $New)
    [IO.File]::WriteAllText($resolved, $text, [Text.UTF8Encoding]::new($false))
}

$header = 'runtime/open-shaders/src/Features/Upscaling/FoveatedRender.h'
$cpp = 'runtime/open-shaders/src/Features/Upscaling/FoveatedRender.cpp'
$runtime = 'runtime/open-shaders/src/Features/Upscaling/NeuralRendering/Runtime.h'

$old = @'
	static const char* SubrectBlendModeName(SubrectBlendMode mode);
	static const char* SubrectMaskModeName(SubrectMaskMode mode);

	// FoveatedRender-specific settings. Quality mode / sharpness / DLSS preset /
'@
$new = @'
	static const char* SubrectBlendModeName(SubrectBlendMode mode);
	static const char* SubrectMaskModeName(SubrectMaskMode mode);

	// Independent controls for sequential Feature 18 pass 2. Route ownership
	// (gaze/adaptive controller) remains shared: pass 2 derives its region from
	// the live pass-1 region every frame instead of maintaining a competing crop.
	struct SequentialPassSettings
	{
		uint coveragePercent = 100;  // relative linear coverage of the live pass-1 crop
		uint modelResolution = 100;
		uint preset = 0;
		float intensity = 1.70f;
		float localTone = 1.00f;
		float localStructure = 1.70f;
		float skinStructure = -1.0f;
		uint style = 0;
		bool autoMask = true;
		bool uiCorrection = false;
		uint resolveMode = 0;
		bool resultShapingEnabled = false;
		float resultEditStrength = 1.0f;
		float resultBrightening = 1.0f;
		float resultDarkening = 1.0f;
		float resultColor = 1.0f;
		float resultHueShiftStrength = 1.0f;
		float resultShadows = 1.0f;
		float resultMidtones = 1.0f;
		float resultHighlights = 1.0f;
		float resultMaxBrighteningStops = 0.0f;
		float resultMaxDarkeningStops = 0.0f;
		float resultMaxColorChangeStops = 0.0f;
		float resultLargeScaleTone = 1.0f;
		float resultFineDetail = 1.0f;
		float resultDetailRadius = 1.0f;
		float resultHaloSuppression = 0.0f;
		uint stabilizeMode = 0;
		float stabilizeTimeMs = 60.0f;
		bool stabilizeDetail = false;
		float stabilizeDepthThreshold = 0.05f;
		float stabilizeColorTolerance = 0.08f;
		uint blendMode = static_cast<uint>(SubrectBlendMode::kFeather);
		uint maskMode = static_cast<uint>(SubrectMaskMode::kOval);
		float featherWidth = 64.0f;
		float falloffCurve = 1.0f;
		float ditherStrength = 1.0f;
		bool sharpeningEnabled = false;
		float sharpeningStrength = 0.0f;  // 0..5
		uint sharpeningPlacement = 1;     // 0=before NR, 1=after NR
	};

	// FoveatedRender-specific settings. Quality mode / sharpness / DLSS preset /
'@
Replace-Exact $header $old $new

$old = @'
		float neuralRenderingResultHaloSuppression = 0.0f;
		// 0 = off, 1 = static-pixel, 2 = game-motion-vector reprojection.
'@
$new = @'
		float neuralRenderingResultHaloSuppression = 0.0f;
		bool neuralRenderingSharpeningEnabled = false;
		float neuralRenderingSharpeningStrength = 0.0f;  // 0..5
		uint neuralRenderingSharpeningPlacement = 1;     // 0=before NR, 1=after NR
		// 0 = off, 1 = static-pixel, 2 = game-motion-vector reprojection.
'@
Replace-Exact $header $old $new

$old = @'
		uint neuralRenderingMultiPass = 0;
		// Experimental Feature 18 temporal reuse. 0 = off; 2/3/4 means a full
'@
$new = @'
		uint neuralRenderingMultiPass = 0;
		// Pass 2 is independently tunable but inherits route ownership (gaze/adaptive
		// crop center) from pass 1. coveragePercent is relative to the live pass-1
		// crop, not the persisted static preset.
		SequentialPassSettings neuralRenderingPass2{};
		// Experimental stereo atlas: pack both eyes into one Feature 18 evaluation
		// per sequential stage. Off by default; incompatible geometry fails closed
		// to the normal independent-eye path.
		bool neuralRenderingStereoAtlas = false;
		uint neuralRenderingStereoAtlasGuardPixels = 50;
		// Adaptive controller estimate used when deciding whether a two-pass route
		// can fit the frame budget without oscillating simply because pass 2 toggles.
		float neuralRenderingAdaptiveSecondPassCostMs = 6.0f;
		// Experimental Feature 18 temporal reuse. 0 = off; 2/3/4 means a full
'@
Replace-Exact $header $old $new

$old = @'
#define OPENNR_FOVEATED_SETTINGS_FIELDS(X) \
	X(enabled) \
'@
$new = @'
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
	X(ditherStrength) \
	X(sharpeningEnabled) \
	X(sharpeningStrength) \
	X(sharpeningPlacement)

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
'@
Replace-Exact $cpp $old $new

$old = @'
	X(neuralRenderingResultHaloSuppression) \
	X(neuralRenderingStabilizeMode) \
'@
$new = @'
	X(neuralRenderingResultHaloSuppression) \
	X(neuralRenderingSharpeningEnabled) \
	X(neuralRenderingSharpeningStrength) \
	X(neuralRenderingSharpeningPlacement) \
	X(neuralRenderingStabilizeMode) \
'@
Replace-Exact $cpp $old $new

$old = @'
	X(neuralRenderingResolveMode) \
	X(neuralRenderingMultiPass) \
	X(neuralRenderingTemporalReuseCadence) \
'@
$new = @'
	X(neuralRenderingResolveMode) \
	X(neuralRenderingMultiPass) \
	X(neuralRenderingPass2) \
	X(neuralRenderingStereoAtlas) \
	X(neuralRenderingStereoAtlasGuardPixels) \
	X(neuralRenderingAdaptiveSecondPassCostMs) \
	X(neuralRenderingTemporalReuseCadence) \
'@
Replace-Exact $cpp $old $new

$old = @'
#undef OPENNR_FOVEATED_SETTINGS_FIELDS

// ============================================================================
'@
$new = @'
#undef OPENNR_FOVEATED_SETTINGS_FIELDS
#undef OPENNR_SEQUENTIAL_PASS_FIELDS

// ============================================================================
'@
Replace-Exact $cpp $old $new

$old = @'
	settings.neuralRenderingResultHaloSuppression = clampFinite(settings.neuralRenderingResultHaloSuppression, 0.0f, 0.0f, 1.0f);
	settings.neuralRenderingStabilizeMode = std::min(settings.neuralRenderingStabilizeMode, 2u);
'@
$new = @'
	settings.neuralRenderingResultHaloSuppression = clampFinite(settings.neuralRenderingResultHaloSuppression, 0.0f, 0.0f, 1.0f);
	settings.neuralRenderingSharpeningStrength = clampFinite(settings.neuralRenderingSharpeningStrength, 0.0f, 0.0f, 5.0f);
	settings.neuralRenderingSharpeningPlacement = std::min(settings.neuralRenderingSharpeningPlacement, 1u);
	settings.neuralRenderingStabilizeMode = std::min(settings.neuralRenderingStabilizeMode, 2u);
'@
Replace-Exact $cpp $old $new

$old = @'
	settings.neuralRenderingPreUpscale = std::min(settings.neuralRenderingPreUpscale, 1u);
	settings.neuralRenderingResolveMode = std::min(settings.neuralRenderingResolveMode, 1u);
	settings.neuralRenderingMultiPass = std::min(settings.neuralRenderingMultiPass, 2u);
	if (settings.neuralRenderingTemporalReuseCadence != 0 &&
'@
$new = @'
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
	pass2.sharpeningStrength = clampFinite(pass2.sharpeningStrength, 0.0f, 0.0f, 5.0f);
	pass2.sharpeningPlacement = std::min(pass2.sharpeningPlacement, 1u);
	if (settings.neuralRenderingTemporalReuseCadence != 0 &&
'@
Replace-Exact $cpp $old $new

$old = @'
namespace NeuralRendering
{
	struct Tuning
	{
'@
$new = @'
namespace NeuralRendering
{
	struct SequentialPassTuning
	{
		std::uint32_t coveragePercent = 100;
		std::uint32_t modelResolutionPercent = 100;
		std::uint32_t modelResolveMode = 0;
		float intensity = 1.70f;
		float localToneStrength = 1.00f;
		float localStructureStrength = 1.70f;
		float skinStructureStrength = -1.0f;
		std::uint32_t style = 0;
		bool useAutoMask = true;
		bool uiCorrection = false;
		bool resultShapingEnabled = false;
		float resultEditStrength = 1.0f;
		float resultBrightening = 1.0f;
		float resultDarkening = 1.0f;
		float resultColor = 1.0f;
		float resultHueShiftStrength = 1.0f;
		float resultShadows = 1.0f;
		float resultMidtones = 1.0f;
		float resultHighlights = 1.0f;
		float resultMaxBrighteningStops = 0.0f;
		float resultMaxDarkeningStops = 0.0f;
		float resultMaxColorChangeStops = 0.0f;
		float resultLargeScaleTone = 1.0f;
		float resultFineDetail = 1.0f;
		float resultDetailRadius = 1.0f;
		float resultHaloSuppression = 0.0f;
		std::uint32_t stabilizeMode = 0;
		float stabilizeTimeMs = 60.0f;
		bool stabilizeDetail = false;
		float stabilizeDepthThreshold = 0.05f;
		float stabilizeColorTolerance = 0.08f;
		std::uint32_t blendMode = 1;
		std::uint32_t maskMode = 1;
		float featherWidth = 64.0f;
		float falloffCurve = 1.0f;
		float ditherStrength = 1.0f;
		bool sharpeningEnabled = false;
		float sharpeningStrength = 0.0f;
		std::uint32_t sharpeningPlacement = 1;
	};

	struct Tuning
	{
'@
Replace-Exact $runtime $old $new

$old = @'
		std::uint32_t multiPass = 0;
		// Experimental temporal reuse: 0 = disabled, otherwise run a full
'@
$new = @'
		std::uint32_t multiPass = 0;
		SequentialPassTuning secondPass{};
		bool stereoAtlas = false;
		std::uint32_t stereoAtlasGuardPixels = 50;
		float adaptiveSecondPassCostMs = 6.0f;
		bool sharpeningEnabled = false;
		float sharpeningStrength = 0.0f;
		std::uint32_t sharpeningPlacement = 1;
		// Experimental temporal reuse: 0 = disabled, otherwise run a full
'@
Replace-Exact $runtime $old $new

Write-Host 'v01 settings/runtime contracts applied successfully.'
