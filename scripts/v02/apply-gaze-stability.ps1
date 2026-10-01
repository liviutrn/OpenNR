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

function Insert-Before-Unique {
    param([string]$Path,[string]$Needle,[string]$Insertion)
    $resolved = Resolve-Path $Path
    $text = [IO.File]::ReadAllText($resolved).Replace("`r`n", "`n")
    $count = ([regex]::Matches($text, [regex]::Escape($Needle))).Count
    if ($count -ne 1) { throw "Expected exactly one insertion anchor in $Path, found ${count}: $Needle" }
    [IO.File]::WriteAllText($resolved, $text.Replace($Needle, $Insertion + $Needle), [Text.UTF8Encoding]::new($false))
}

$gaze = 'runtime/open-shaders/src/Features/Upscaling/GazeCropPolicy.h'
$header = 'runtime/open-shaders/src/Features/Upscaling/FoveatedRender.h'
$foveated = 'runtime/open-shaders/src/Features/Upscaling/FoveatedRender.cpp'

Write-Host 'v02 gaze stability: restore v00 hard-hold policy with configurable dead zone'
$pattern = '\t/\*\* Continuous exponential gaze tracking:.*?\n\t}\n}'
$replacement = @'
	// v02 restores the v00/original hard-hold crop policy. The percentage is a
	// fraction of the full eye axis, not of the crop extent, so the whole 1..10%
	// user range remains meaningful even with smaller gaze crops.
	inline float gDeadZonePercent = 2.0f;

	inline void SetDeadZonePercent(float percent)
	{
		gDeadZonePercent = std::clamp(std::isfinite(percent) ? percent : 2.0f, 1.0f, 10.0f);
	}

	/** v00 behavior: smooth fixation noise only; deliberate eye movement bypasses the filter. */
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

	/** Hard dead zone: the crop origin does not move at all until gaze exits the guard. */
	inline float ResolveOrigin(float previous, float sample, float extent,
		std::uint32_t pixels, std::uint32_t quantizationPixels, bool havePrevious)
	{
		const float maxOrigin = std::max(0.0f, 1.0f - extent);
		const float desired = std::clamp(sample - extent * 0.5f, 0.0f, maxOrigin);
		const float guard = std::clamp(gDeadZonePercent * 0.01f, 0.01f, 0.10f);
		if (havePrevious && std::abs(desired - previous) <= guard)
			return previous;
		const float step = pixels ? std::min(static_cast<float>(quantizationPixels) / static_cast<float>(pixels), guard) : 0.0f;
		return step > 0.0f ? std::clamp(std::round(desired / step) * step, 0.0f, maxOrigin) : desired;
	}
}
'@
Replace-RegexOnce $gaze $pattern $replacement

Write-Host 'v02 gaze stability: persist dead-zone setting'
Replace-Exact $header @'
		float neuralRenderingEyeTrackedSmoothingMs = 0.0f;
		uint neuralRenderingEyeTrackedQuantizationPixels = 8;
'@ @'
		float neuralRenderingEyeTrackedSmoothingMs = 0.0f;
		uint neuralRenderingEyeTrackedQuantizationPixels = 8;
		float neuralRenderingEyeTrackedDeadZonePercent = 2.0f;
'@

Replace-Exact $foveated '#include "FoveatedRender/Core.h"' @'
#include "FoveatedRender/Core.h"
#include "GazeCropPolicy.h"
'@

Replace-Exact $foveated @'
	X(neuralRenderingEyeTrackedFoveation) \
	X(neuralRenderingEyeTrackedSmoothingMs) \
	X(neuralRenderingEyeTrackedQuantizationPixels)
'@ @'
	X(neuralRenderingEyeTrackedFoveation) \
	X(neuralRenderingEyeTrackedSmoothingMs) \
	X(neuralRenderingEyeTrackedQuantizationPixels) \
	X(neuralRenderingEyeTrackedDeadZonePercent)
'@

Replace-Exact $foveated @'
	settings.neuralRenderingEyeTrackedSmoothingMs = std::clamp(settings.neuralRenderingEyeTrackedSmoothingMs, 0.0f, 250.0f);
	settings.neuralRenderingEyeTrackedQuantizationPixels = std::clamp(settings.neuralRenderingEyeTrackedQuantizationPixels, 0u, 64u);
'@ @'
	settings.neuralRenderingEyeTrackedSmoothingMs = std::clamp(settings.neuralRenderingEyeTrackedSmoothingMs, 0.0f, 250.0f);
	settings.neuralRenderingEyeTrackedQuantizationPixels = std::clamp(settings.neuralRenderingEyeTrackedQuantizationPixels, 0u, 64u);
	settings.neuralRenderingEyeTrackedDeadZonePercent = clampFinite(settings.neuralRenderingEyeTrackedDeadZonePercent, 2.0f, 1.0f, 10.0f);
	FoveatedRenderImpl::GazeCropPolicy::SetDeadZonePercent(settings.neuralRenderingEyeTrackedDeadZonePercent);
'@

$quantizationAnchor = 'int quantizationPixels = static_cast<int>(std::min(settings.neuralRenderingEyeTrackedQuantizationPixels, 64u));'
$deadZoneUi = @'
					if (ImGui::SliderFloat("Gaze crop dead zone", &settings.neuralRenderingEyeTrackedDeadZonePercent,
						1.0f, 10.0f, "%.1f%% of eye")) {
						settings.neuralRenderingEyeTrackedDeadZonePercent = std::clamp(settings.neuralRenderingEyeTrackedDeadZonePercent, 1.0f, 10.0f);
						FoveatedRenderImpl::GazeCropPolicy::SetDeadZonePercent(settings.neuralRenderingEyeTrackedDeadZonePercent);
					}
					if (auto _tt = Util::HoverTooltipWrapper())
						drawWrapped("v00-style hard hold: inside this gaze-origin dead zone the crop remains exactly stationary. Default 2%. Larger values prioritize fixation stability over immediate recentering.");
					
'@
Insert-Before-Unique $foveated $quantizationAnchor $deadZoneUi

Write-Host 'v02 gaze stability: verify rollback and configuration wiring'
$gazeText = [IO.File]::ReadAllText((Resolve-Path $gaze)).Replace("`r`n", "`n")
$headerText = [IO.File]::ReadAllText((Resolve-Path $header)).Replace("`r`n", "`n")
$fovText = [IO.File]::ReadAllText((Resolve-Path $foveated)).Replace("`r`n", "`n")
if ($gazeText -match 'retain 8% response' -or $gazeText -match 'Soft hysteresis') { throw 'v01 soft gaze-origin policy still present' }
if ($gazeText -notmatch 'return previous;' -or $gazeText -notmatch 'gDeadZonePercent \* 0\.01f') { throw 'v00 hard dead-zone behavior is not active' }
if ($headerText -notmatch 'neuralRenderingEyeTrackedDeadZonePercent = 2\.0f') { throw 'Dead-zone setting missing from FoveatedRender settings' }
if ($fovText -notmatch 'SliderFloat\("Gaze crop dead zone"' -or $fovText -notmatch 'SetDeadZonePercent') { throw 'Dead-zone UI/runtime wiring missing' }

Write-Host 'v02 v00-style gaze stability rollback applied successfully.'
