$ErrorActionPreference = 'Stop'

# fixed3 already contains the intended final sharpening implementation. Its only
# remaining brittle point is an exact match for the pre-v02 ApplyDlssSharpening
# function body. Rewrite that one invocation to select the function by its
# signature and namespace boundary, leaving the replacement function unchanged.
$source = 'scripts/v02/apply-sharpening-fixed3.ps1'
$resolved = Resolve-Path $source
$text = [IO.File]::ReadAllText($resolved).Replace("`r`n", "`n")
$old = 'Replace-Exact $post $old $new'
$new = @'
$pattern = '(?s)\tbool Postprocess::ApplyDlssSharpening\(Upscaling& upscaling\)\s*\{.*?\n\t\}(?=\n\})'
Replace-RegexOnce $post $pattern $new
'@
$count = ([regex]::Matches($text, [regex]::Escape($old))).Count
if ($count -ne 1) { throw "Expected one Postprocess replacement invocation in fixed3, found $count" }
$text = $text.Replace($old, $new)
[IO.File]::WriteAllText($resolved, $text, [Text.UTF8Encoding]::new($false))

& pwsh -NoProfile -File $source
if ($LASTEXITCODE -ne 0) { throw "Sharpening fixed4 transform failed with exit code $LASTEXITCODE" }

# fixed3 removes the obsolete NR-specific sharpening members from the final
# FoveatedRender settings contract. The v01 gaze/sequential transform also emits
# six assignments to those members in Integration.cpp; remove only those exact
# generated writes so the original Upscaling-tab sharpening remains the sole path.
$integration = 'runtime/open-shaders/src/Features/Upscaling/NeuralRendering/Integration.cpp'
$integrationResolved = Resolve-Path $integration
$integrationText = [IO.File]::ReadAllText($integrationResolved).Replace("`r`n", "`n")
$staleAssignments = @(
    'tuning\.secondPass\.sharpeningEnabled\s*=\s*settings\.neuralRenderingPass2\.sharpeningEnabled;',
    'tuning\.secondPass\.sharpeningStrength\s*=\s*settings\.neuralRenderingPass2\.sharpeningStrength;',
    'tuning\.secondPass\.sharpeningPlacement\s*=\s*settings\.neuralRenderingPass2\.sharpeningPlacement;',
    'tuning\.sharpeningEnabled\s*=\s*settings\.neuralRenderingSharpeningEnabled;',
    'tuning\.sharpeningStrength\s*=\s*settings\.neuralRenderingSharpeningStrength;',
    'tuning\.sharpeningPlacement\s*=\s*settings\.neuralRenderingSharpeningPlacement;'
)
foreach ($assignment in $staleAssignments) {
    $pattern = "(?m)^[ `t]*$assignment[ `t]*`n"
    $rx = [regex]::new($pattern)
    $matches = $rx.Matches($integrationText)
    if ($matches.Count -ne 1) {
        throw "Expected exactly one stale NR sharpening integration assignment for pattern '$assignment', found $($matches.Count)"
    }
    $integrationText = $rx.Replace($integrationText, '', 1)
}
[IO.File]::WriteAllText($integrationResolved, $integrationText, [Text.UTF8Encoding]::new($false))

$verificationText = [IO.File]::ReadAllText($integrationResolved).Replace("`r`n", "`n")
foreach ($identifier in @(
    'tuning.secondPass.sharpeningEnabled',
    'tuning.secondPass.sharpeningStrength',
    'tuning.secondPass.sharpeningPlacement',
    'tuning.sharpeningEnabled',
    'tuning.sharpeningStrength',
    'tuning.sharpeningPlacement'
)) {
    if ($verificationText.Contains($identifier)) {
        throw "Stale NR sharpening integration write remains: $identifier"
    }
}

Write-Host 'v02 sharpening fixed4 function-boundary selector and stale integration cleanup applied successfully.'