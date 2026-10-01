$ErrorActionPreference = 'Stop'

function Replace-Exact {
    param([string]$Path,[string]$Old,[string]$New)
    $resolved = Resolve-Path $Path
    $text = [IO.File]::ReadAllText($resolved).Replace("`r`n", "`n")
    $count = ([regex]::Matches($text, [regex]::Escape($Old))).Count
    if ($count -ne 1) { throw "Expected exactly one source block in $Path, found $count" }
    [IO.File]::WriteAllText($resolved, $text.Replace($Old,$New), [Text.UTF8Encoding]::new($false))
}

$renderer = 'runtime/open-shaders/src/Features/Upscaling/NeuralRendering/Renderer.cpp'

# v01 atlas safety intentionally keeps the dormant per-eye Feature18 reset flags
# armed while the atlas owns native history. The v00 crop-motion code previously
# reused those per-eye flags as the reset seed, which disabled crop-origin motion
# compensation on every continuing atlas frame. Keep the reset domains separate:
# while atlas was active last frame, crop motion follows the atlas reset state.
Replace-Exact $renderer `
    'bool reset = resetPending[eyeIndex][tierIndex];' `
    'bool reset = stereoAtlasActiveLastFrame ? stereoAtlasResetPending : resetPending[eyeIndex][tierIndex];'

Replace-Exact $renderer `
    'resetPending[eyeIndex][tierIndex] = reset;' `
@'
if (stereoAtlasActiveLastFrame) {
						// A true crop-history discontinuity must reset atlas Feature18, but the
						// deliberately armed dormant per-eye reset flag must not suppress
						// ordinary atlas crop-motion compensation.
						if (reset)
							stereoAtlasResetPending = true;
					} else {
						resetPending[eyeIndex][tierIndex] = reset;
					}
'@

$text = [IO.File]::ReadAllText((Resolve-Path $renderer)).Replace("`r`n", "`n")
if ($text -notmatch 'stereoAtlasActiveLastFrame \? stereoAtlasResetPending : resetPending\[eyeIndex\]\[tierIndex\]') {
    throw 'Atlas crop-motion reset-domain selection was not installed'
}
if ($text -notmatch 'if \(reset\)\s*\n\s*stereoAtlasResetPending = true;') {
    throw 'Atlas crop-history discontinuities are not propagated to atlas history reset'
}
if ($text -notmatch 'resetPending\[eyeIndex\]\[tierIndex\] = nativeEvaluationDone;') {
    throw 'Expected v01 atlas fallback-safety contract is missing'
}

Write-Host 'v02 atlas crop-motion/history reset domains separated successfully.'
