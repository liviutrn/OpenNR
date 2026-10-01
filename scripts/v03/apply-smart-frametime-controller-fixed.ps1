$ErrorActionPreference = 'Stop'

# The first v03 controller checkpoint assumed the two inherited adaptive state
# fields remained adjacent after the full v00/v01/v02 reconstruction. They do
# not. Rewrite only that insertion inside the source transform so it anchors on
# the unique adaptiveNextDownshiftIsCrop declaration and preserves all generated
# fields around it.
$source = 'scripts/v03/apply-smart-frametime-controller.ps1'
$resolved = Resolve-Path $source
$text = [IO.File]::ReadAllText($resolved).Replace("`r`n", "`n")

$pattern = '(?s)Write-Host ''v03 controller: add explicit adaptive pass state''\n\$stateOld = @''\n.*?\n''@\n\$stateNew = @''\n.*?\n''@\nReplace-ExactOnce \$header \$stateOld \$stateNew'
$rx = [regex]::new($pattern)
$matches = $rx.Matches($text)
if ($matches.Count -ne 1) {
    throw "Expected one original adaptive-state insertion in smart controller transform, found $($matches.Count)"
}

$replacement = @'
Write-Host 'v03 controller: add explicit adaptive pass state'
$statePattern = '(?m)^(?<indent>\s*)bool adaptiveNextDownshiftIsCrop = true;$'
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
Replace-RegexOnce $header $statePattern $stateReplacement
'@

$text = $rx.Replace($text, $replacement, 1)
[IO.File]::WriteAllText($resolved, $text, [Text.UTF8Encoding]::new($false))

& pwsh -NoProfile -File $source
if ($LASTEXITCODE -ne 0) {
    throw "Corrected smart frametime controller transform failed with exit code $LASTEXITCODE"
}
