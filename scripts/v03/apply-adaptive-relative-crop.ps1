$ErrorActionPreference = 'Stop'

function Read-Normalized([string]$Path) {
    return [IO.File]::ReadAllText((Resolve-Path $Path)).Replace("`r`n", "`n")
}
function Write-Normalized([string]$Path, [string]$Text) {
    [IO.File]::WriteAllText((Resolve-Path $Path), $Text, [Text.UTF8Encoding]::new($false))
}
function Replace-ExactOnce([string]$Path, [string]$Old, [string]$New) {
    $text = Read-Normalized $Path
    $count = ([regex]::Matches($text, [regex]::Escape($Old))).Count
    if ($count -ne 1) { throw "Expected one exact block in $Path, found $count" }
    Write-Normalized $Path ($text.Replace($Old, $New))
}
function Replace-RegexOnce([string]$Path, [string]$Pattern, [string]$Replacement) {
    $text = Read-Normalized $Path
    $rx = [regex]::new($Pattern, [Text.RegularExpressions.RegexOptions]::Singleline)
    $matches = $rx.Matches($text)
    if ($matches.Count -ne 1) { throw "Expected one regex block in $Path for '$Pattern', found $($matches.Count)" }
    Write-Normalized $Path ($rx.Replace($text, $Replacement, 1))
}

$policy = 'runtime/open-shaders/src/Features/Upscaling/NeuralRendering/RuntimePolicy.h'
$cropHeader = 'runtime/open-shaders/src/Features/Upscaling/NeuralRendering/AdaptiveCropController.h'
$cropCpp = 'runtime/open-shaders/src/Features/Upscaling/NeuralRendering/AdaptiveCropController.cpp'
$foveatedHeader = 'runtime/open-shaders/src/Features/Upscaling/FoveatedRender.h'
$foveated = 'runtime/open-shaders/src/Features/Upscaling/FoveatedRender.cpp'
$integration = 'runtime/open-shaders/src/Features/Upscaling/NeuralRendering/Integration.cpp'

Write-Host 'v03 adaptive: unlock validated adaptive model-resolution machinery'
Replace-ExactOnce $policy 'inline constexpr bool kFullResolutionNeuralRenderingOnly = true;' 'inline constexpr bool kFullResolutionNeuralRenderingOnly = false;'

Write-Host 'v03 adaptive crop: convert controller buckets to relative scale of user-selected crop'
Replace-ExactOnce $cropHeader 'std::uint32_t maximumCoverage = 85;' 'std::uint32_t maximumCoverage = 100;'
$bucketReplacement = @'
static constexpr std::array<std::uint32_t, 6> kCoverageBuckets{
			100, 90, 80, 70, 60, 50 };
'@
Replace-RegexOnce $cropHeader 'static constexpr std::array<std::uint32_t, 6> kCoverageBuckets\{\s*85, 80, 75, 70, 65, 60 \};' $bucketReplacement
Replace-ExactOnce $cropHeader 'std::uint32_t previousCoverage_ = 85;' 'std::uint32_t previousCoverage_ = 100;'

$normalizePattern = 'normalized\.maximumCoverage = FindBucketAtOrBelow\(std::clamp\(normalized\.maximumCoverage, 60u, 85u\)\);\s*\n\s*normalized\.minimumCoverage = FindBucketAtOrBelow\(std::max\(normalized\.minimumCoverage, 60u\)\);'
$normalizeReplacement = @'
normalized.maximumCoverage = FindBucketAtOrBelow(std::clamp(normalized.maximumCoverage, 50u, 100u));
		normalized.minimumCoverage = FindBucketAtOrBelow(std::clamp(normalized.minimumCoverage, 50u, 100u));
'@
Replace-RegexOnce $cropCpp $normalizePattern $normalizeReplacement

Write-Host 'v03 adaptive crop: selected crop is always the 100% ceiling'
Replace-ExactOnce $foveatedHeader 'uint neuralRenderingAdaptiveCropMaximumCoverage = 85;' 'uint neuralRenderingAdaptiveCropMaximumCoverage = 100;'

$maxSwitchPattern = '(?s)\tswitch \(settings\.neuralRenderingAdaptiveCropMaximumCoverage\) \{.*?\n\t\}\n\t// Keep the configured ladder ordered\.'
$maxSwitchReplacement = @'
	// v03 semantics: 100% means exactly the user-selected crop. Adaptive logic
	// may only shrink from that baseline; it never expands beyond the user's choice.
	settings.neuralRenderingAdaptiveCropMaximumCoverage = 100;
	// Keep the configured ladder ordered.
'@
Replace-RegexOnce $foveated $maxSwitchPattern $maxSwitchReplacement

$fovText = Read-Normalized $foveated
$minRx = [regex]::new('(?s)\tswitch \(settings\.neuralRenderingAdaptiveCropMinimumCoverage\) \{.*?\n\t\}\n\t// v03 semantics:')
$minMatches = $minRx.Matches($fovText)
if ($minMatches.Count -ne 1) { throw "Expected one adaptive minimum switch after maximum rewrite, found $($minMatches.Count)" }
$minReplacement = @'
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
	// v03 semantics:
'@
Write-Normalized $foveated ($minRx.Replace($fovText, $minReplacement, 1))

Write-Host 'v03 adaptive crop: scale both fixed and gaze crops around their existing center'
$effectivePattern = '(?s)Util::Subrect::UVRegion FoveatedRender::GetEffectiveLeftUV\(\) const\n\{.*?\n\}\n\nUtil::Subrect::UVRegion FoveatedRender::GetEffectiveRightUV\(\) const\n\{.*?\n\}\n(?=\nFoveatedRender::DlssMode)'
$effectiveReplacement = @'
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
'@
Replace-RegexOnce $foveated $effectivePattern $effectiveReplacement

Write-Host 'v03 adaptive crop: allow fixed-envelope resource stability while gaze owns origin'
Replace-ExactOnce $integration "`t`t`tif (!fullEye && !gaze.dynamic &&`n`t`t`t`tfoveated.IsAdaptiveCropRuntimeActive() &&" "`t`t`tif (!fullEye && foveated.IsAdaptiveCropRuntimeActive() &&"

Write-Host 'v03 adaptive UI: remove independent absolute maximum and expose relative floor'
$maxUiPattern = '(?s)\t\t\t\t\tstatic const char\* adaptiveCropMaximums\[\].*?drawWrapped\("Maximum is the controller reference tier\. With eye tracking it represents 100% of your configured gaze crop; lower adaptive tiers scale that live crop around the gaze center\."\);'
$maxUiReplacement = @'
					settings.neuralRenderingAdaptiveCropMaximumCoverage = 100;
					ImGui::TextDisabled("Adaptive crop ceiling: 100%% of your selected crop (never larger).");
'@
Replace-RegexOnce $foveated $maxUiPattern $maxUiReplacement

$minUiPattern = '(?s)\t\t\t\t\tstatic const char\* adaptiveCropMinimums\[\] = \{.*?\n\t\t\t\t\t\tsettings\.neuralRenderingAdaptiveCropMinimumCoverage = adaptiveCropMinimumValues\[cropMinimumIndex\];'
$minUiReplacement = @'
					static const char* adaptiveCropMinimums[] = { "90% of selected crop", "80%", "70%", "60%", "50%" };
					static constexpr uint adaptiveCropMinimumValues[] = { 90u, 80u, 70u, 60u, 50u };
					int cropMinimumIndex = 3;
					for (int index = 0; index < IM_ARRAYSIZE(adaptiveCropMinimumValues); ++index)
						if (settings.neuralRenderingAdaptiveCropMinimumCoverage == adaptiveCropMinimumValues[index]) {
							cropMinimumIndex = index;
							break;
						}
					if (ImGui::Combo("Adaptive minimum crop size", &cropMinimumIndex,
						adaptiveCropMinimums, IM_ARRAYSIZE(adaptiveCropMinimums)))
						settings.neuralRenderingAdaptiveCropMinimumCoverage = adaptiveCropMinimumValues[cropMinimumIndex];
'@
Replace-RegexOnce $foveated $minUiPattern $minUiReplacement

$fovText = Read-Normalized $foveated
$fovText = $fovText.Replace('ImGui::TextDisabled("Crop: %u%% -> %u%% | max %u%% | handoff %.2f",', 'ImGui::TextDisabled("Crop scale: %u%% -> %u%% of selected crop | ceiling %u%% | handoff %.2f",')
Write-Normalized $foveated $fovText

Write-Host 'v03 adaptive relative-crop verification'
$p = Read-Normalized $policy
$ch = Read-Normalized $cropHeader
$fh = Read-Normalized $foveatedHeader
$f = Read-Normalized $foveated
$i = Read-Normalized $integration
if ($p -notmatch 'kFullResolutionNeuralRenderingOnly = false') { throw 'Full-resolution-only lock still enabled' }
if ($ch -notmatch '100, 90, 80, 70, 60, 50') { throw 'Relative crop buckets missing' }
if ($fh -notmatch 'neuralRenderingAdaptiveCropMaximumCoverage = 100') { throw 'Relative crop ceiling default missing' }
if ($f -notmatch 'RenderCoverage\(\)\) / 100\.0f') { throw 'Effective crop is not relative to user baseline' }
if ($i -match '!fullEye && !gaze\.dynamic &&\s*\n\s*foveated\.IsAdaptiveCropRuntimeActive') { throw 'Gaze still blocks fixed-envelope adaptive crop' }
if ($f -match 'Maximum is independent of the static crop preset') { throw 'Old absolute crop semantics remain in UI' }

Write-Host 'v03 adaptive model tiers unlocked; adaptive crop is relative to the user-selected crop and gaze-compatible.'
