$ErrorActionPreference = 'Stop'

# Insert the v04-only state by anchoring to the unique slow-workload member.
# This deliberately avoids assuming tabs/spaces or adjacency produced by the
# inherited v03 wrapper. Then disable only the brittle insertion call in the
# main v04 transform and execute every other rewrite unchanged.
$header = 'runtime/open-shaders/src/Features/Upscaling/FoveatedRender.h'
$resolved = Resolve-Path $header
$text = [IO.File]::ReadAllText($resolved).Replace("`r`n", "`n")
$rx = [regex]::new('(?m)^(?<indent>\s*)float adaptiveSlowWorkloadMs = 0\.0f;$')
$matches = $rx.Matches($text)
if ($matches.Count -ne 1) {
    throw "Expected one adaptiveSlowWorkloadMs declaration, found $($matches.Count)"
}
$replacement = @'
${indent}float adaptiveSlowWorkloadMs = 0.0f;
${indent}// v04: one controller owns pass count and relative crop target. The old
${indent}// model-resolution controller remains present for ABI/source compatibility
${indent}// but is deliberately not a decision maker while adaptive v04 is active.
${indent}std::uint32_t adaptiveCropTargetCoverage = 100;
${indent}float adaptiveOverBudgetMs = 0.0f;
${indent}float adaptiveHeadroomMs = 0.0f;
${indent}float adaptiveCooldownMs = 0.0f;
${indent}float adaptiveLastGpuMs = 0.0f;
${indent}float adaptiveLastCpuMs = 0.0f;
${indent}std::uint32_t adaptiveOutlierStreak = 0;
${indent}bool adaptiveGpuLimited = true;
'@
$text = $rx.Replace($text, $replacement, 1)
[IO.File]::WriteAllText($resolved, $text, [Text.UTF8Encoding]::new($false))

$source = 'scripts/v04/apply-unified-frametime-controller.ps1'
$sourceResolved = Resolve-Path $source
$sourceText = [IO.File]::ReadAllText($sourceResolved).Replace("`r`n", "`n")
$oldCall = 'Replace-ExactOnce $header $stateOld $stateNew'
$count = ([regex]::Matches($sourceText, [regex]::Escape($oldCall))).Count
if ($count -ne 1) {
    throw "Expected one brittle v04 state insertion call, found $count"
}
$sourceText = $sourceText.Replace($oldCall, "Write-Host 'v04 unified state already inserted by fixed wrapper'")
[IO.File]::WriteAllText($sourceResolved, $sourceText, [Text.UTF8Encoding]::new($false))

& pwsh -NoProfile -File $source
if ($LASTEXITCODE -ne 0) {
    throw "Corrected v04 unified controller transform failed with exit code $LASTEXITCODE"
}
