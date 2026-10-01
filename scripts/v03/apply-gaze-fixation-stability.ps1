$ErrorActionPreference = 'Stop'

function Read-Normalized([string]$Path) {
    return [IO.File]::ReadAllText((Resolve-Path $Path)).Replace("`r`n", "`n")
}
function Write-Normalized([string]$Path, [string]$Text) {
    [IO.File]::WriteAllText((Resolve-Path $Path), $Text, [Text.UTF8Encoding]::new($false))
}
function Replace-RegexOnce([string]$Path, [string]$Pattern, [string]$Replacement) {
    $text = Read-Normalized $Path
    $rx = [regex]::new($Pattern, [Text.RegularExpressions.RegexOptions]::Singleline)
    $matches = $rx.Matches($text)
    if ($matches.Count -ne 1) { throw "Expected one match in $Path for '$Pattern', found $($matches.Count)" }
    Write-Normalized $Path ($rx.Replace($text, $Replacement, 1))
}
function Replace-ExactOnce([string]$Path, [string]$Old, [string]$New) {
    $text = Read-Normalized $Path
    $count = ([regex]::Matches($text, [regex]::Escape($Old))).Count
    if ($count -ne 1) { throw "Expected one exact block in $Path, found $count" }
    Write-Normalized $Path ($text.Replace($Old, $New))
}

$gaze = 'runtime/open-shaders/src/Features/Upscaling/GazeCropPolicy.h'
$header = 'runtime/open-shaders/src/Features/Upscaling/FoveatedRender.h'
$foveated = 'runtime/open-shaders/src/Features/Upscaling/FoveatedRender.cpp'
$provider = 'runtime/open-shaders/src/Features/Upscaling/NativeOpenVRGaze.cpp'

Write-Host 'v03 gaze: replace binary >2px bypass with continuous fixation filtering'
$policyPattern = '(?s)\t// v02 restores the v00/original hard-hold crop policy\..*?\n\tinline float gDeadZonePercent = 2\.0f;.*?\n\t}\n}'
$policyReplacement = @'
	// v03 keeps the validated crop-motion history compensation, but fixes the
	// fixation policy. v02 bypassed filtering whenever a gaze sample moved more
	// than two pixels, so ordinary tracker noise could become raw crop motion.
	// The optional large dead zone remains available, including 0 = disabled.
	inline float gDeadZonePercent = 0.0f;

	inline void SetDeadZonePercent(float percent)
	{
		gDeadZonePercent = std::clamp(std::isfinite(percent) ? percent : 0.0f, 0.0f, 10.0f);
	}

	/** Continuous, frame-rate-independent fixation filtering with fast saccade response. */
	inline std::array<float, 2> Filter(const std::array<float, 2>& previous,
		const std::array<float, 2>& sample, float deltaMs, float smoothingMs,
		std::uint32_t width, std::uint32_t height)
	{
		if (!width || !height)
			return sample;
		const float elapsed = std::clamp(std::isfinite(deltaMs) ? deltaMs : 16.67f, 0.1f, 50.0f);
		const float requested = std::clamp(std::isfinite(smoothingMs) ? smoothingMs : 0.0f, 0.0f, 250.0f);
		const float dx = (sample[0] - previous[0]) * static_cast<float>(width);
		const float dy = (sample[1] - previous[1]) * static_cast<float>(height);
		const float distancePixels = std::sqrt(dx * dx + dy * dy);

		// Even with user smoothing at zero, damp only fixation-scale noise. Once
		// movement is clearly intentional the response becomes effectively direct.
		const float effectiveMs = requested > 0.0f ? requested : 8.0f;
		const float baseAlpha = 1.0f - std::exp(-elapsed / std::max(effectiveMs, 0.1f));
		const float motionBoost = std::clamp((distancePixels - 2.0f) / 24.0f, 0.0f, 1.0f);
		const float alpha = std::clamp(baseAlpha + (1.0f - baseAlpha) * motionBoost, 0.0f, 1.0f);
		return { previous[0] + (sample[0] - previous[0]) * alpha,
			previous[1] + (sample[1] - previous[1]) * alpha };
	}

	/**
	 * Stable fixation without a large mandatory lag zone.
	 * A 1.5-3 pixel micro guard is always present to keep a fixed gaze genuinely
	 * fixed. The user percentage dead zone is optional and only enlarges it.
	 */
	inline float ResolveOrigin(float previous, float sample, float extent,
		std::uint32_t pixels, std::uint32_t quantizationPixels, bool havePrevious)
	{
		const float maxOrigin = std::max(0.0f, 1.0f - extent);
		const float desired = std::clamp(sample - extent * 0.5f, 0.0f, maxOrigin);
		if (!havePrevious)
			return desired;

		const float pixel = pixels ? 1.0f / static_cast<float>(pixels) : 0.0f;
		const float microPixels = std::clamp(static_cast<float>(std::max(quantizationPixels, 1u)) * 0.25f, 1.5f, 3.0f);
		const float microGuard = pixel * microPixels;
		const float userGuard = std::clamp(gDeadZonePercent * 0.01f, 0.0f, 0.10f);
		const float guard = std::max(microGuard, userGuard);
		if (std::abs(desired - previous) <= guard)
			return previous;

		const float step = pixels && quantizationPixels ?
			static_cast<float>(quantizationPixels) / static_cast<float>(pixels) : 0.0f;
		return step > 0.0f ? std::clamp(std::round(desired / step) * step, 0.0f, maxOrigin) : desired;
	}
}
'@
Replace-RegexOnce $gaze $policyPattern $policyReplacement

Write-Host 'v03 gaze: allow zero percent large dead zone and make it the new default'
Replace-ExactOnce $header 'float neuralRenderingEyeTrackedDeadZonePercent = 2.0f;' 'float neuralRenderingEyeTrackedDeadZonePercent = 0.0f;'
Replace-ExactOnce $foveated 'settings.neuralRenderingEyeTrackedDeadZonePercent = clampFinite(settings.neuralRenderingEyeTrackedDeadZonePercent, 2.0f, 1.0f, 10.0f);' 'settings.neuralRenderingEyeTrackedDeadZonePercent = clampFinite(settings.neuralRenderingEyeTrackedDeadZonePercent, 0.0f, 0.0f, 10.0f);'
$sliderPattern = 'ImGui::SliderFloat\("Gaze crop dead zone", &settings\.neuralRenderingEyeTrackedDeadZonePercent,\s*\n\s*1\.0f, 10\.0f, "%.1f%% of eye"\)'
$sliderReplacement = @'
ImGui::SliderFloat("Gaze crop dead zone", &settings.neuralRenderingEyeTrackedDeadZonePercent,
						0.0f, 10.0f, "%.1f%% of eye")
'@
Replace-RegexOnce $foveated $sliderPattern $sliderReplacement
Replace-ExactOnce $foveated 'settings.neuralRenderingEyeTrackedDeadZonePercent = std::clamp(settings.neuralRenderingEyeTrackedDeadZonePercent, 1.0f, 10.0f);' 'settings.neuralRenderingEyeTrackedDeadZonePercent = std::clamp(settings.neuralRenderingEyeTrackedDeadZonePercent, 0.0f, 10.0f);'
Replace-ExactOnce $foveated 'drawWrapped("v00-style hard hold: inside this gaze-origin dead zone the crop remains exactly stationary. Default 2%. Larger values prioritize fixation stability over immediate recentering.");' 'drawWrapped("Optional large gaze-origin hold zone. 0% is recommended for low-lag tracking; v03 still applies a tiny 1.5-3 px fixation lock to suppress tracker tremble. Larger values intentionally trade recenter latency for extra stability.");'

Write-Host 'v03 gaze: assert validated crop-motion history behavior remains active'
$providerText = Read-Normalized $provider
if ($providerText -match 'historyReset\s*=\s*result\.historyReset\s*\|\|\s*cropChanged') {
    throw 'Regression: ordinary gaze crop motion again forces a full Feature18 history reset'
}
if ($providerText -notmatch 'cropChangeCount') { throw 'Native gaze provider contract unexpectedly changed' }

$g = Read-Normalized $gaze
$h = Read-Normalized $header
$f = Read-Normalized $foveated
if ($g -match '> 2\.0f\)\s*\n\s*return sample') { throw 'Old >2px raw-sample bypass still present' }
if ($g -notmatch 'microPixels' -or $g -notmatch 'motionBoost') { throw 'v03 fixation filter not present' }
if ($h -notmatch 'neuralRenderingEyeTrackedDeadZonePercent = 0\.0f') { throw 'new dead-zone default missing' }
if ($f -notmatch '0\.0f, 10\.0f, "%.1f%% of eye"') { throw 'dead-zone UI still excludes zero' }

Write-Host 'v03 gaze fixation stability applied; ordinary crop motion keeps compensated history.'
