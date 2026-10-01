$ErrorActionPreference = 'Stop'

$source = 'scripts/v02/apply-gaze-stability.ps1'
$resolved = Resolve-Path $source
$text = [IO.File]::ReadAllText($resolved).Replace("`r`n", "`n")

# The first gaze checkpoint assumed smoothing + quantization remained adjacent in
# FoveatedRender::Settings. v01 transforms do not guarantee that layout. Rewrite
# only that insertion in the transform so it anchors on the unique quantization
# field and preserves whatever default value the inherited source carries.
$pattern = '(?s)Write-Host ''v02 gaze stability: persist dead-zone setting''\nReplace-Exact \$header @''.*?''@ @''.*?''@\n\nReplace-Exact \$foveated ''#include "FoveatedRender/Core\.h"'''
$rx = [regex]::new($pattern)
$matches = $rx.Matches($text)
if ($matches.Count -ne 1) { throw "Expected one gaze settings insertion block, found $($matches.Count)" }
$replacement = @'
Write-Host 'v02 gaze stability: persist dead-zone setting'
$headerPattern = '(?m)^(?<indent>\s*)(?<line>uint neuralRenderingEyeTrackedQuantizationPixels = [0-9]+;)$'
$headerReplacement = @'
${indent}${line}
${indent}float neuralRenderingEyeTrackedDeadZonePercent = 2.0f;
'@
Replace-RegexOnce $header $headerPattern $headerReplacement

Replace-Exact $foveated '#include "FoveatedRender/Core.h"'
'@
$text = $rx.Replace($text, $replacement, 1)
[IO.File]::WriteAllText($resolved, $text, [Text.UTF8Encoding]::new($false))

& pwsh -NoProfile -File $source
if ($LASTEXITCODE -ne 0) { throw "Corrected gaze stability transform failed with exit code $LASTEXITCODE" }
