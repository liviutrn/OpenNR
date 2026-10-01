$ErrorActionPreference = 'Stop'

function Read-Normalized([string]$Path) {
    return [IO.File]::ReadAllText((Resolve-Path $Path)).Replace("`r`n", "`n")
}

function Write-Normalized([string]$Path, [string]$Text) {
    [IO.File]::WriteAllText((Resolve-Path $Path), $Text, [Text.UTF8Encoding]::new($false))
}

function Replace-RegexCount([string]$Path, [string]$Pattern, [string]$Replacement, [int]$ExpectedCount) {
    $text = Read-Normalized $Path
    $rx = [regex]::new($Pattern, [Text.RegularExpressions.RegexOptions]::Multiline)
    $matches = $rx.Matches($text)
    if ($matches.Count -ne $ExpectedCount) {
        throw "Expected $ExpectedCount matches in $Path for '$Pattern', found $($matches.Count)"
    }
    Write-Normalized $Path ($rx.Replace($text, $Replacement))
}

$upscaling = 'runtime/open-shaders/src/Features/Upscaling.cpp'
$foveated = 'runtime/open-shaders/src/Features/Upscaling/FoveatedRender.cpp'
$post = 'runtime/open-shaders/src/Features/Upscaling/FoveatedRender/Postprocess.cpp'
$shader = 'runtime/open-shaders/features/Upscaling/Shaders/Upscaling/RCAS/RCAS.hlsl'

Write-Host 'v03 sharpness: extend shared DLSS UI to 0..3'
Replace-RegexCount $upscaling '(&settings\.sharpnessDLSS,\s*0\.0f,\s*)1\.0f(,\s*"%\.1f"\))' '${1}3.0f${2}' 2

Write-Host 'v03 sharpness: preserve old 0..1 curve and encode >1 as safe delta boost'
$oldCurve = 'float currentSharpness = \(-2\.0f \* settings\.sharpnessDLSS\) \+ 2\.0f;\s*\n\s*currentSharpness = exp2\(-currentSharpness\);'
$newCurve = @'
float currentSharpness = settings.sharpnessDLSS <= 1.0f ?
			exp2(-((-2.0f * settings.sharpnessDLSS) + 2.0f)) :
			std::clamp(settings.sharpnessDLSS, 1.0f, 3.0f);
'@
Replace-RegexCount $upscaling $oldCurve $newCurve 2

$postCurve = 'float currentSharpness = \(-2\.0f \* upscaling\.settings\.sharpnessDLSS\) \+ 2\.0f;\s*\n\s*currentSharpness = exp2\(-currentSharpness\);'
$postReplacement = @'
float currentSharpness = upscaling.settings.sharpnessDLSS <= 1.0f ?
			exp2(-((-2.0f * upscaling.settings.sharpnessDLSS) + 2.0f)) :
			std::clamp(upscaling.settings.sharpnessDLSS, 1.0f, 3.0f);
'@
Replace-RegexCount $post $postCurve $postReplacement 1

Write-Host 'v03 sharpness: expose 3.0 through foveated shared accessor'
Replace-RegexCount $foveated '(return std::clamp\(globals::features::upscaling\.settings\.sharpnessDLSS, 0\.0f, )1\.0f(\);)' '${1}3.0f${2}' 1

Write-Host 'v03 sharpness: keep RCAS kernel stable and amplify only the sharpening delta above 1.0'
$shaderText = Read-Normalized $shader
$oldLobe = 'float lobe = max(-FSR_RCAS_LIMIT, min(max(lobeR, max(lobeG, lobeB)), 0.0)) * sharpness;'
$newLobe = @'
// 0..1 keeps the historical RCAS behavior exactly. Values above 1 never
	// overdrive the RCAS lobe itself (which can cross its stable denominator);
	// instead they extrapolate the already-bounded sharpened delta below.
	float kernelSharpness = min(sharpness, 1.0);
	float deltaBoost = max(sharpness, 1.0);
	float lobe = max(-FSR_RCAS_LIMIT, min(max(lobeR, max(lobeG, lobeB)), 0.0)) * kernelSharpness;
'@
if (([regex]::Matches($shaderText, [regex]::Escape($oldLobe))).Count -ne 1) {
    throw 'Expected exactly one RCAS lobe assignment'
}
$shaderText = $shaderText.Replace($oldLobe, $newLobe)
$oldOut = @'
	Dest[DTid.xy] = float4(pixR, pixG, pixB, 1.0);
'@
$newOut = @'
	float3 sharpened = float3(pixR, pixG, pixB);
	float3 boosted = e + (sharpened - e) * deltaBoost;
	Dest[DTid.xy] = float4(boosted, 1.0);
'@
if (([regex]::Matches($shaderText, [regex]::Escape($oldOut))).Count -ne 1) {
    throw 'Expected exactly one RCAS output assignment'
}
$shaderText = $shaderText.Replace($oldOut, $newOut)
Write-Normalized $shader $shaderText

Write-Host 'v03 sharpness: verify contract'
$u = Read-Normalized $upscaling
$f = Read-Normalized $foveated
$p = Read-Normalized $post
$s = Read-Normalized $shader
if (([regex]::Matches($u, '&settings\.sharpnessDLSS,\s*0\.0f,\s*3\.0f')).Count -ne 2) { throw 'DLSS sharpness UI range verification failed' }
if ($f -notmatch 'sharpnessDLSS, 0\.0f, 3\.0f') { throw 'Foveated sharpness accessor still clips at old maximum' }
if ($p -notmatch 'std::clamp\(upscaling\.settings\.sharpnessDLSS, 1\.0f, 3\.0f\)') { throw 'Foveated RCAS path lacks extended mapping' }
if ($s -notmatch 'kernelSharpness = min\(sharpness, 1\.0\)' -or $s -notmatch 'deltaBoost = max\(sharpness, 1\.0\)') { throw 'RCAS safe boost mapping missing' }
if ($s -match '\* sharpness;') { throw 'Unsafe direct >1 RCAS lobe multiplication remains' }

Write-Host 'v03 sharpness range applied: legacy 0..1 preserved, max 3.0 boosts bounded RCAS delta 3x.'
