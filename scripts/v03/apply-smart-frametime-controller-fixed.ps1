$ErrorActionPreference = 'Stop'

# The original controller transform assumed two inherited fields were adjacent.
# Insert the new pass state directly after the unique adaptiveNextDownshiftIsCrop
# declaration, then disable only the brittle insertion call in the source
# transform before executing the rest unchanged.
$header = 'runtime/open-shaders/src/Features/Upscaling/FoveatedRender.h'
$headerResolved = Resolve-Path $header
$headerText = [IO.File]::ReadAllText($headerResolved).Replace("`r`n", "`n")
$statePattern = '(?m)^(?<indent>\s*)bool adaptiveNextDownshiftIsCrop = true;$'
$stateRx = [regex]::new($statePattern)
$stateMatches = $stateRx.Matches($headerText)
if ($stateMatches.Count -ne 1) {
    throw "Expected one adaptiveNextDownshiftIsCrop declaration, found $($stateMatches.Count)"
}
$stateReplacement = @'
${indent}bool adaptiveNextDownshiftIsCrop = true;
${indent}// v03 pass controller. Adaptive mode intentionally caps automatic sequential
${indent}// operation at two passes; 3x remains available when the controller is off.
${indent}std::uint32_t adaptiveActivePasses = 1;
${indent}std::uint32_t adaptiveConfiguredPasses = 1;
${indent}std::uint32_t adaptivePassDwellFrames = 0;
${indent}std::uint32_t adaptivePassPressureFrames = 0;
${indent}std::uint32_t adaptivePassHeadroomFrames = 0;
${indent}bool adaptivePassInitialized = false;
${indent}float adaptiveFastWorkloadMs = 0.0f;
${indent}float adaptiveSlowWorkloadMs = 0.0f;
'@
$headerText = $stateRx.Replace($headerText, $stateReplacement, 1)
[IO.File]::WriteAllText($headerResolved, $headerText, [Text.UTF8Encoding]::new($false))

$source = 'scripts/v03/apply-smart-frametime-controller.ps1'
$sourceResolved = Resolve-Path $source
$sourceText = [IO.File]::ReadAllText($sourceResolved).Replace("`r`n", "`n")
$oldCall = 'Replace-ExactOnce $header $stateOld $stateNew'
$count = ([regex]::Matches($sourceText, [regex]::Escape($oldCall))).Count
if ($count -ne 1) {
    throw "Expected one brittle state insertion call in source transform, found $count"
}
$sourceText = $sourceText.Replace($oldCall, "Write-Host 'v03 adaptive pass state already inserted by fixed wrapper'")
[IO.File]::WriteAllText($sourceResolved, $sourceText, [Text.UTF8Encoding]::new($false))

& pwsh -NoProfile -File $source
if ($LASTEXITCODE -ne 0) {
    throw "Corrected smart frametime controller transform failed with exit code $LASTEXITCODE"
}
