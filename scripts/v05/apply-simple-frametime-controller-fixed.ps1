$ErrorActionPreference = 'Stop'

# v04 already owns adaptiveCropTargetCoverage and several diagnostic members.
# Keep those declarations for source compatibility, but add only the new v05
# authoritative timing/action state. The v05 policy replacement below makes the
# inherited fast/slow/predictive members non-decision-making.
$header = 'runtime/open-shaders/src/Features/Upscaling/FoveatedRender.h'
$headerResolved = Resolve-Path $header
$headerText = [IO.File]::ReadAllText($headerResolved).Replace("`r`n", "`n")
$stateRx = [regex]::new('(?m)^(?<indent>\s*)bool adaptiveGpuLimited = true;$')
$stateMatches = $stateRx.Matches($headerText)
if ($stateMatches.Count -ne 1) {
    throw "Expected one adaptiveGpuLimited declaration, found $($stateMatches.Count)"
}
$stateReplacement = @'
${indent}bool adaptiveGpuLimited = true;
${indent}// v05 authoritative controller state. Inherited v03/v04 diagnostic members
${indent}// remain for source compatibility but do not participate in v05 decisions.
${indent}float adaptiveFilteredFrameTimeMs = 0.0f;
${indent}float adaptiveLastFrameTimeMs = 0.0f;
${indent}float adaptiveDecreaseHoldMs = 0.0f;
${indent}float adaptiveIncreaseHoldMs = 0.0f;
${indent}float adaptiveCooldownRemainingMs = 0.0f;
${indent}std::uint32_t adaptivePendingAction = 0;
${indent}std::uint32_t adaptiveLastAction = 0;
${indent}std::uint32_t adaptiveLastActionFrom = 0;
${indent}std::uint32_t adaptiveLastActionTo = 0;
${indent}float adaptiveLastActionFrameTimeMs = 0.0f;
'@
$headerText = $stateRx.Replace($headerText, $stateReplacement, 1)
[IO.File]::WriteAllText($headerResolved, $headerText, [Text.UTF8Encoding]::new($false))

# Patch only the checked-in transform script used in this CI workspace. This is
# the same fixed-wrapper pattern used by v03/v04: keep the readable base transform
# and correct assumptions that only become visible after the inherited transforms.
$source = 'scripts/v05/apply-simple-frametime-controller.ps1'
$sourceResolved = Resolve-Path $source
$sourceText = [IO.File]::ReadAllText($sourceResolved).Replace("`r`n", "`n")

$stateBlockRx = [regex]::new("(?s)Write-Host 'v05: simplify runtime state'.*?(?=Write-Host 'v05: constrain adaptive crop to the approved relative tiers 100/80/60')")
$stateBlockMatches = $stateBlockRx.Matches($sourceText)
if ($stateBlockMatches.Count -ne 1) {
    throw "Expected one v05 brittle state-replacement block, found $($stateBlockMatches.Count)"
}
$sourceText = $stateBlockRx.Replace($sourceText, "Write-Host 'v05 simple state already inserted by fixed wrapper'`n`n", 1)

$oldVerification = "if (`$f -match 'passCostMs' -or `$f -match 'adaptiveFastWorkloadMs' -or `$f -match 'adaptiveSlowWorkloadMs') { throw 'Predictive/dual-filter controller state survived v05' }"
$newVerification = "if (`$f -match 'adaptiveController\.Update\(') { throw 'Old model-resolution controller still drives adaptive decisions' }"
$verificationCount = ([regex]::Matches($sourceText, [regex]::Escape($oldVerification))).Count
if ($verificationCount -ne 1) {
    throw "Expected one over-broad v05 legacy-state verification, found $verificationCount"
}
$sourceText = $sourceText.Replace($oldVerification, $newVerification)

# The readable v05 UI replacement intentionally starts at the old adaptive block
# and ends at the first Resolve/Pipeline separator. That range also consumes the
# opening Experimental Pipeline CollapsingHeader from the inherited source. Put
# that opening scope back so the later closing brace cannot escape the Neural
# Rendering panel and move supportedRoute out of scope.
$missingPipelineOpen = "`t`t`t}`n`n`t`t`t`tImGui::SeparatorText(`"Resolve and Pipeline`");"
$restoredPipelineOpen = "`t`t`t}`n`n`t`t`tif (ImGui::CollapsingHeader(`"Experimental Pipeline`")) {`n`t`t`t`tImGui::SeparatorText(`"Resolve and Pipeline`");"
$pipelineOpenCount = ([regex]::Matches($sourceText, [regex]::Escape($missingPipelineOpen))).Count
if ($pipelineOpenCount -ne 1) {
    throw "Expected one v05 UI replacement missing Experimental Pipeline scope, found $pipelineOpenCount"
}
$sourceText = $sourceText.Replace($missingPipelineOpen, $restoredPipelineOpen)

[IO.File]::WriteAllText($sourceResolved, $sourceText, [Text.UTF8Encoding]::new($false))

& pwsh -NoProfile -File $source
if ($LASTEXITCODE -ne 0) {
    throw "Corrected v05 simple controller transform failed with exit code $LASTEXITCODE"
}
