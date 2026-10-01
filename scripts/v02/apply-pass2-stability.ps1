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

$renderer = 'runtime/open-shaders/src/Features/Upscaling/NeuralRendering/Renderer.cpp'

Write-Host 'v02 compact P2: make native handle recreation checks pass-aware'
$pattern = '\t\t\tconst bool lowResolutionMotion = [^\n]+;\n\t\t\tfor \(std::uint32_t pass = 0; pass < passCount; \+\+pass\) \{.*?\n\t\t\t\}'
$replacement = @'
			const std::uint32_t pass2Coverage = passCount > 1 ? std::clamp(secondPassCoverage, 50u, 100u) : 100u;
			for (std::uint32_t pass = 0; pass < passCount; ++pass) {
				const bool compactPass2 = pass == 1 && pass2Coverage < 100;
				const std::uint32_t expectedInputWidth = compactPass2 ? ScaleDimension(resourceModelWidth, pass2Coverage) : featureInputWidth;
				const std::uint32_t expectedInputHeight = compactPass2 ? ScaleDimension(resourceModelHeight, pass2Coverage) : featureInputHeight;
				const std::uint32_t expectedOutputWidth = compactPass2 ? ScaleDimension(resourceModelWidth, pass2Coverage) : resourceModelWidth;
				const std::uint32_t expectedOutputHeight = compactPass2 ? ScaleDimension(resourceModelHeight, pass2Coverage) : resourceModelHeight;
				const std::uint32_t expectedGuideWidth = compactPass2 ? ScaleDimension(sharedGuideWidth, pass2Coverage) : sharedGuideWidth;
				const std::uint32_t expectedGuideHeight = compactPass2 ? ScaleDimension(sharedGuideHeight, pass2Coverage) : sharedGuideHeight;
				const bool lowResolutionMotion = expectedGuideWidth <= expectedInputWidth && expectedGuideHeight <= expectedInputHeight;
				const auto slot = FeatureSlot(eyeIndex, tierIndex, pass);
				if (!Runtime::Instance().NeedsRecreation(slot, expectedInputWidth, expectedInputHeight,
					expectedOutputWidth, expectedOutputHeight, lowResolutionMotion))
					continue;
				if (!waited && !interop.WaitForIdle())
					return false;
				waited = true;
				Runtime::Instance().ResetFeature(slot);
				resetPending[eyeIndex][tierIndex] = true;
			}
'@
Replace-RegexOnce $renderer $pattern $replacement

Write-Host 'v02 compact P2: keep atlas on the validated full-P2 contract'
$atlasCompatible = 'const bool compatible = passCount >= 1 && passCount <= 2 && !tuning.adaptiveResolution &&'
$atlasReplacement = @'
// v01 atlas pass 2 has no independent GPU-safe recreation contract for
			// changing compact dimensions. Reduced P2 therefore falls back to the
			// corrected independent-eye path instead of reusing a stale atlas handle.
			const bool compactPass2 = passCount == 2 && tuning.secondPass.coveragePercent < 100;
			const bool compatible = passCount >= 1 && passCount <= 2 && !compactPass2 && !tuning.adaptiveResolution &&
'@
Replace-Exact $renderer $atlasCompatible $atlasReplacement

$text = [IO.File]::ReadAllText((Resolve-Path $renderer)).Replace("`r`n", "`n")
if ($text -notmatch 'expectedInputWidth = compactPass2 \? ScaleDimension\(resourceModelWidth, pass2Coverage\)') {
    throw 'Compact P2 native-handle dimensions are not used by recreation checks'
}
if ($text -notmatch 'expectedGuideWidth = compactPass2 \? ScaleDimension\(sharedGuideWidth, pass2Coverage\)') {
    throw 'Compact P2 motion-vector low-resolution contract is not pass-aware'
}
if ($text -notmatch 'const bool compactPass2 = passCount == 2 && tuning\.secondPass\.coveragePercent < 100;') {
    throw 'Atlas reduced-P2 safety fallback was not installed'
}
if ($text -notmatch 'passCount <= 2 && !compactPass2 && !tuning\.adaptiveResolution') {
    throw 'Atlas compatibility does not fail closed for reduced pass 2'
}

Write-Host 'v02 compact reduced pass-2 stability repair applied successfully.'
