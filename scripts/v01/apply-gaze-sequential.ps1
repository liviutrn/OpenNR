$ErrorActionPreference = 'Stop'

function Replace-Exact {
    param([string]$Path,[string]$Old,[string]$New)
    $resolved = Resolve-Path $Path
    $text = [IO.File]::ReadAllText($resolved).Replace("`r`n", "`n")
    $count = ([regex]::Matches($text, [regex]::Escape($Old))).Count
    if ($count -ne 1) { throw "Expected exactly one source block in $Path, found $count" }
    [IO.File]::WriteAllText($resolved, $text.Replace($Old,$New), [Text.UTF8Encoding]::new($false))
}

function Replace-RegexOnce {
    param([string]$Path,[string]$Pattern,[string]$Replacement)
    $resolved = Resolve-Path $Path
    $text = [IO.File]::ReadAllText($resolved).Replace("`r`n", "`n")
    $rx = [regex]::new($Pattern, [Text.RegularExpressions.RegexOptions]::Singleline)
    $matches = $rx.Matches($text)
    if ($matches.Count -ne 1) { throw "Expected exactly one regex source block in $Path, found $($matches.Count)" }
    [IO.File]::WriteAllText($resolved, $rx.Replace($text,$Replacement,1), [Text.UTF8Encoding]::new($false))
}

$gaze = 'runtime/open-shaders/src/Features/Upscaling/GazeCropPolicy.h'
$foveated = 'runtime/open-shaders/src/Features/Upscaling/FoveatedRender.cpp'
$integration = 'runtime/open-shaders/src/Features/Upscaling/NeuralRendering/Integration.cpp'
$runtime = 'runtime/open-shaders/src/Features/Upscaling/NeuralRendering/Runtime.h'

# 1. Continuous gaze response: remove the 2-pixel binary bypass and replace the
# hard hold/snap crop origin with a soft hysteresis response. Quantization remains
# available but is blended instead of becoming a hard dead-zone.
$old = @'
	/** Smooth fixation noise only; deliberate eye movement bypasses the filter. */
	inline std::array<float, 2> Filter(const std::array<float, 2>& previous,
		const std::array<float, 2>& sample, float deltaMs, float smoothingMs,
		std::uint32_t width, std::uint32_t height)
	{
		if (!width || !height ||
			std::abs(sample[0] - previous[0]) * static_cast<float>(width) > 2.0f ||
			std::abs(sample[1] - previous[1]) * static_cast<float>(height) > 2.0f)
			return sample;
		const float duration = std::clamp(std::isfinite(smoothingMs) ? smoothingMs : 0.0f, 0.0f, 250.0f);
		const float elapsed = std::clamp(std::isfinite(deltaMs) ? deltaMs : 16.67f, 0.1f, 250.0f);
		const float alpha = duration > 0.0f ? elapsed / (duration + elapsed) : 1.0f;
		return { previous[0] + (sample[0] - previous[0]) * alpha,
			previous[1] + (sample[1] - previous[1]) * alpha };
	}

	/** Retain a stable crop inside a small central guard; recenter without slew outside it. */
	inline float ResolveOrigin(float previous, float sample, float extent,
		std::uint32_t pixels, std::uint32_t quantizationPixels, bool havePrevious)
	{
		const float maxOrigin = std::max(0.0f, 1.0f - extent);
		const float desired = std::clamp(sample - extent * 0.5f, 0.0f, maxOrigin);
		const float guard = std::min(0.02f, extent * 0.05f);
		if (havePrevious && std::abs(desired - previous) <= guard)
			return previous;
		// Quantization must not place the tracked point outside the central guard.
		const float step = pixels ? std::min(static_cast<float>(quantizationPixels) / static_cast<float>(pixels), guard) : 0.0f;
		return step > 0.0f ? std::clamp(std::round(desired / step) * step, 0.0f, maxOrigin) : desired;
	}
'@
$new = @'
	/** Continuous exponential gaze tracking: smoothing is never disabled by a binary pixel threshold. */
	inline std::array<float, 2> Filter(const std::array<float, 2>& previous,
		const std::array<float, 2>& sample, float deltaMs, float smoothingMs,
		std::uint32_t width, std::uint32_t height)
	{
		if (!width || !height)
			return sample;
		const float duration = std::clamp(std::isfinite(smoothingMs) ? smoothingMs : 0.0f, 0.0f, 250.0f);
		const float elapsed = std::clamp(std::isfinite(deltaMs) ? deltaMs : 16.67f, 0.1f, 250.0f);
		if (duration <= 0.0f)
			return sample;
		// Exponential response is frame-rate independent. A distance boost keeps a
		// deliberate saccade responsive without the old >2 px instant snap.
		const float baseAlpha = 1.0f - std::exp(-elapsed / std::max(duration, 0.1f));
		const float dx = std::abs(sample[0] - previous[0]) * static_cast<float>(width);
		const float dy = std::abs(sample[1] - previous[1]) * static_cast<float>(height);
		const float distancePixels = std::sqrt(dx * dx + dy * dy);
		const float distanceBoost = std::clamp((distancePixels - 6.0f) / 96.0f, 0.0f, 1.0f);
		const float alpha = std::clamp(baseAlpha + (1.0f - baseAlpha) * distanceBoost * 0.85f, 0.0f, 1.0f);
		return { previous[0] + (sample[0] - previous[0]) * alpha,
			previous[1] + (sample[1] - previous[1]) * alpha };
	}

	/** Soft hysteresis around the current crop origin; no hard 2%-of-eye hold/snap. */
	inline float ResolveOrigin(float previous, float sample, float extent,
		std::uint32_t pixels, std::uint32_t quantizationPixels, bool havePrevious)
	{
		const float maxOrigin = std::max(0.0f, 1.0f - extent);
		const float desired = std::clamp(sample - extent * 0.5f, 0.0f, maxOrigin);
		if (!havePrevious)
			return desired;
		const float pixel = pixels ? 1.0f / static_cast<float>(pixels) : 0.0f;
		const float requestedStep = pixel * static_cast<float>(std::max(quantizationPixels, 1u));
		// The soft zone is deliberately bounded to a few pixels; unlike the old
		// min(2% eye, 5% crop) rule it cannot become a ~48 px dead-zone at 2400 px.
		const float softZone = pixels ? std::clamp(requestedStep, 1.0f * pixel, 6.0f * pixel) : 0.0f;
		const float delta = desired - previous;
		const float distance = std::abs(delta);
		float follow = 1.0f;
		if (softZone > 0.0f && distance < softZone) {
			const float t = std::clamp(distance / softZone, 0.0f, 1.0f);
			const float smooth = t * t * (3.0f - 2.0f * t);
			// Even at fixation retain 8% response, avoiding a frozen crop followed by a jump.
			follow = 0.08f + 0.92f * smooth;
		}
		float resolved = previous + delta * follow;
		if (requestedStep > pixel && pixels) {
			const float snapped = std::clamp(std::round(resolved / requestedStep) * requestedStep, 0.0f, maxOrigin);
			const float quantizeMix = std::clamp(distance / std::max(softZone * 4.0f, pixel), 0.0f, 0.35f);
			resolved += (snapped - resolved) * quantizeMix;
		}
		return std::clamp(resolved, 0.0f, maxOrigin);
	}
'@
Replace-Exact $gaze $old $new

# 2. Keep legacy aggregate initializers valid. Checkpoint 2 deliberately introduced
# v01 fields after multiPass; move those fields to the tail of Tuning before any
# C++ translation unit sees the transformed source.
$old = @'
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
$new = @'
		std::uint32_t multiPass = 0;
		// Experimental temporal reuse: 0 = disabled, otherwise run a full
'@
Replace-Exact $runtime $old $new

$old = @'
		bool temporalReuseStaggerEyes = false;
	};
'@
$new = @'
		bool temporalReuseStaggerEyes = false;

		// v01-only fields are trailing so all pre-v01 aggregate initializers retain
		// their exact field mapping. Integration assigns them explicitly.
		SequentialPassTuning secondPass{};
		bool stereoAtlas = false;
		std::uint32_t stereoAtlasGuardPixels = 50;
		float adaptiveSecondPassCostMs = 6.0f;
		bool sharpeningEnabled = false;
		float sharpeningStrength = 0.0f;
		std::uint32_t sharpeningPlacement = 1;
	};
'@
Replace-Exact $runtime $old $new

# 3. Adaptive crop may coexist with gaze. The controller owns only size; the
# gaze resolver remains the sole owner of crop center/origin.
$old = @'
	const bool cropPolicyAvailable = nrEligible && settings.neuralRenderingAdaptiveEnabled &&
		settings.neuralRenderingAdaptiveCropEnabled && geometryCompatible && !eyeTrackingOwnsCrop &&
		configuredCoverage >= 60;
	const bool cropCanDownshift = cropPolicyAvailable &&
		!FoveatedRenderImpl::Core::vrSubrectFixedEnvelopeRejected &&
		!FoveatedRenderImpl::Core::vrSubrectNeuralFixedEnvelopeRejected &&
		(adaptiveCropController.IsRuntimeActive() ?
			adaptiveCropController.ActiveCoverage() > adaptiveCropController.MinimumCoverage() :
			configuredCoverage > settings.neuralRenderingAdaptiveCropMinimumCoverage);
'@
$new = @'
	const std::uint32_t adaptiveConfiguredCoverage = eyeTrackingOwnsCrop ?
		settings.neuralRenderingAdaptiveCropMaximumCoverage : configuredCoverage;
	const bool cropPolicyAvailable = nrEligible && settings.neuralRenderingAdaptiveEnabled &&
		settings.neuralRenderingAdaptiveCropEnabled && geometryCompatible &&
		(eyeTrackingOwnsCrop || configuredCoverage >= 60);
	const bool cropCanDownshift = cropPolicyAvailable &&
		!FoveatedRenderImpl::Core::vrSubrectFixedEnvelopeRejected &&
		!FoveatedRenderImpl::Core::vrSubrectNeuralFixedEnvelopeRejected &&
		(adaptiveCropController.IsRuntimeActive() ?
			adaptiveCropController.ActiveCoverage() > adaptiveCropController.MinimumCoverage() :
			adaptiveConfiguredCoverage > settings.neuralRenderingAdaptiveCropMinimumCoverage);
'@
Replace-Exact $foveated $old $new

$old = @'
	adaptiveCropController.Update(frame, cropConfig, adaptiveNRActive && geometryCompatible,
		configuredCoverage, geometryCompatible, eyeTrackingOwnsCrop, cropShouldDownshiftFirst,
		adaptiveController.IsTransitioning(), nrAtStableMaximum,
		adaptiveController.LastSampleOverBudget(), adaptiveController.LastSampleHadHeadroom());
'@
$new = @'
	adaptiveCropController.Update(frame, cropConfig, adaptiveNRActive && geometryCompatible,
		adaptiveConfiguredCoverage, geometryCompatible, false, cropShouldDownshiftFirst,
		adaptiveController.IsTransitioning(), nrAtStableMaximum,
		adaptiveController.LastSampleOverBudget(), adaptiveController.LastSampleHadHeadroom());
'@
Replace-Exact $foveated $old $new

$old = @'
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
'@
$new = @'
Util::Subrect::UVRegion FoveatedRender::GetEffectiveLeftUV() const
{
	const auto base = subrectController.GetUV();
	if (!adaptiveCropController.IsRuntimeActive())
		return base;
	if (IsEyeTrackedFoveationEnabled()) {
		const float maximum = static_cast<float>(std::max(adaptiveCropController.MaximumCoverage(), 1u));
		const float scale = std::clamp(static_cast<float>(adaptiveCropController.RenderCoverage()) / maximum, 0.01f, 1.0f);
		Util::Subrect::UVRegion out = base;
		const float centerX = base.x + base.w * 0.5f;
		const float centerY = base.y + base.h * 0.5f;
		out.w = std::clamp(base.w * scale, 0.01f, 1.0f);
		out.h = std::clamp(base.h * scale, 0.01f, 1.0f);
		out.x = std::clamp(centerX - out.w * 0.5f, 0.0f, 1.0f - out.w);
		out.y = std::clamp(centerY - out.h * 0.5f, 0.0f, 1.0f - out.h);
		return out;
	}
	const float coverage = std::clamp(
		static_cast<float>(adaptiveCropController.RenderCoverage()) / 100.0f, 0.01f, 1.0f);
	const bool nasalConvergence = IsNasalConvergenceGeometry(
		base, subrectController.GetRightEyeUV());
	return MakeAdaptiveCropUV(coverage, true, nasalConvergence);
}

Util::Subrect::UVRegion FoveatedRender::GetEffectiveRightUV() const
{
	const auto base = subrectController.GetRightEyeUV();
	if (!adaptiveCropController.IsRuntimeActive())
		return base;
	if (IsEyeTrackedFoveationEnabled()) {
		const float maximum = static_cast<float>(std::max(adaptiveCropController.MaximumCoverage(), 1u));
		const float scale = std::clamp(static_cast<float>(adaptiveCropController.RenderCoverage()) / maximum, 0.01f, 1.0f);
		Util::Subrect::UVRegion out = base;
		const float centerX = base.x + base.w * 0.5f;
		const float centerY = base.y + base.h * 0.5f;
		out.w = std::clamp(base.w * scale, 0.01f, 1.0f);
		out.h = std::clamp(base.h * scale, 0.01f, 1.0f);
		out.x = std::clamp(centerX - out.w * 0.5f, 0.0f, 1.0f - out.w);
		out.y = std::clamp(centerY - out.h * 0.5f, 0.0f, 1.0f - out.h);
		return out;
	}
	const float coverage = std::clamp(
		static_cast<float>(adaptiveCropController.RenderCoverage()) / 100.0f, 0.01f, 1.0f);
	const bool nasalConvergence = IsNasalConvergenceGeometry(
		subrectController.GetUV(), base);
	return MakeAdaptiveCropUV(coverage, false, nasalConvergence);
}
'@
Replace-Exact $foveated $old $new

# 4. Populate trailing v01 tuning fields explicitly. This keeps the legacy
# aggregate untouched while giving the renderer independent pass-2 settings.
$pattern = '(			Tuning tuning\{.*?\n			\};\n)(			if constexpr \(kFullResolutionNeuralRenderingOnly\))'
$replacement = @'
$1			tuning.secondPass.coveragePercent = settings.neuralRenderingPass2.coveragePercent;
			tuning.secondPass.modelResolutionPercent = settings.neuralRenderingPass2.modelResolution;
			tuning.secondPass.modelResolveMode = settings.neuralRenderingPass2.resolveMode;
			tuning.secondPass.intensity = settings.neuralRenderingPass2.intensity;
			tuning.secondPass.localToneStrength = settings.neuralRenderingPass2.localTone;
			tuning.secondPass.localStructureStrength = settings.neuralRenderingPass2.localStructure;
			tuning.secondPass.skinStructureStrength = settings.neuralRenderingPass2.skinStructure;
			tuning.secondPass.style = settings.neuralRenderingPass2.style;
			tuning.secondPass.useAutoMask = settings.neuralRenderingPass2.autoMask;
			tuning.secondPass.uiCorrection = settings.neuralRenderingPass2.uiCorrection;
			tuning.secondPass.resultShapingEnabled = settings.neuralRenderingPass2.resultShapingEnabled;
			tuning.secondPass.resultEditStrength = settings.neuralRenderingPass2.resultEditStrength;
			tuning.secondPass.resultBrightening = settings.neuralRenderingPass2.resultBrightening;
			tuning.secondPass.resultDarkening = settings.neuralRenderingPass2.resultDarkening;
			tuning.secondPass.resultColor = settings.neuralRenderingPass2.resultColor;
			tuning.secondPass.resultHueShiftStrength = settings.neuralRenderingPass2.resultHueShiftStrength;
			tuning.secondPass.resultShadows = settings.neuralRenderingPass2.resultShadows;
			tuning.secondPass.resultMidtones = settings.neuralRenderingPass2.resultMidtones;
			tuning.secondPass.resultHighlights = settings.neuralRenderingPass2.resultHighlights;
			tuning.secondPass.resultMaxBrighteningStops = settings.neuralRenderingPass2.resultMaxBrighteningStops;
			tuning.secondPass.resultMaxDarkeningStops = settings.neuralRenderingPass2.resultMaxDarkeningStops;
			tuning.secondPass.resultMaxColorChangeStops = settings.neuralRenderingPass2.resultMaxColorChangeStops;
			tuning.secondPass.resultLargeScaleTone = settings.neuralRenderingPass2.resultLargeScaleTone;
			tuning.secondPass.resultFineDetail = settings.neuralRenderingPass2.resultFineDetail;
			tuning.secondPass.resultDetailRadius = settings.neuralRenderingPass2.resultDetailRadius;
			tuning.secondPass.resultHaloSuppression = settings.neuralRenderingPass2.resultHaloSuppression;
			tuning.secondPass.stabilizeMode = settings.neuralRenderingPass2.stabilizeMode;
			tuning.secondPass.stabilizeTimeMs = settings.neuralRenderingPass2.stabilizeTimeMs;
			tuning.secondPass.stabilizeDetail = settings.neuralRenderingPass2.stabilizeDetail;
			tuning.secondPass.stabilizeDepthThreshold = settings.neuralRenderingPass2.stabilizeDepthThreshold;
			tuning.secondPass.stabilizeColorTolerance = settings.neuralRenderingPass2.stabilizeColorTolerance;
			tuning.secondPass.blendMode = settings.neuralRenderingPass2.blendMode;
			tuning.secondPass.maskMode = settings.neuralRenderingPass2.maskMode;
			tuning.secondPass.featherWidth = settings.neuralRenderingPass2.featherWidth;
			tuning.secondPass.falloffCurve = settings.neuralRenderingPass2.falloffCurve;
			tuning.secondPass.ditherStrength = settings.neuralRenderingPass2.ditherStrength;
			tuning.secondPass.sharpeningEnabled = settings.neuralRenderingPass2.sharpeningEnabled;
			tuning.secondPass.sharpeningStrength = settings.neuralRenderingPass2.sharpeningStrength;
			tuning.secondPass.sharpeningPlacement = settings.neuralRenderingPass2.sharpeningPlacement;
			tuning.stereoAtlas = settings.neuralRenderingStereoAtlas;
			tuning.stereoAtlasGuardPixels = settings.neuralRenderingStereoAtlasGuardPixels;
			tuning.adaptiveSecondPassCostMs = settings.neuralRenderingAdaptiveSecondPassCostMs;
			tuning.sharpeningEnabled = settings.neuralRenderingSharpeningEnabled;
			tuning.sharpeningStrength = settings.neuralRenderingSharpeningStrength;
			tuning.sharpeningPlacement = settings.neuralRenderingSharpeningPlacement;
$2
'@
Replace-RegexOnce $integration $pattern $replacement

# 5. Cropped/gaze routes may now use sequential NR. Temporal cadence reuse remains
# disabled for moving/adaptive crop origins; v00 crop-motion compensation handles
# ordinary native-history crop motion instead of forcing a whole Feature reset.
$old = @'
		if (!fullEye || coverageCrop)
			// The cascade relies on full-eye dimensions and isolated stage history;
			// keep cropped/foveated regions on the established single-pass route.
		{
			tuning.multiPass = 0;
			// A fixed crop now owns crop-local temporal history in the renderer. Do
			// not attempt reuse while an eye-tracked crop is moving: its local origin
			// changes every frame and must first be handled by an explicit crop-origin
			// transform. Adaptive crop already supplies cadence zero through GetTuning.
			if (gaze.dynamic)
				tuning.temporalReuseCadence = 0;
		}
'@
$new = @'
		// v01: sequential Feature 18 is valid on cropped/gaze routes. Cadence-based
		// whole-frame residual reuse remains disabled while crop geometry can move;
		// each sequential stage keeps its own native Feature history.
		if (gaze.dynamic || foveated.IsAdaptiveCropRuntimeActive())
			tuning.temporalReuseCadence = 0;
'@
Replace-Exact $integration $old $new

Write-Host 'v01 gaze/adaptive/sequential route transformations applied successfully.'
