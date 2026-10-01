$ErrorActionPreference = 'Stop'

function Read-Normalized([string]$Path) {
    return [IO.File]::ReadAllText((Resolve-Path $Path)).Replace("`r`n", "`n")
}
function Write-Normalized([string]$Path, [string]$Text) {
    [IO.File]::WriteAllText((Resolve-Path $Path), $Text, [Text.UTF8Encoding]::new($false))
}

$integration = 'runtime/open-shaders/src/Features/Upscaling/NeuralRendering/Integration.cpp'
$text = Read-Normalized $integration

$old = @'
				tuning.modelResolutionPercent = settings.neuralRenderingModelResolution;
				tuning.adaptiveResolution = false;
				tuning.adaptiveHandoff = !adaptiveCrop;
'@
$new = @'
				tuning.modelResolutionPercent = settings.neuralRenderingModelResolution;
				tuning.adaptiveResolution = false;
				// Stereo atlas requires temporal reuse and staggered-eye reuse to be
				// inactive. Do not let stale experimental settings force an otherwise
				// valid adaptive-atlas frame onto the independent-eye fallback path.
				tuning.temporalReuseCadence = 0;
				tuning.temporalReuseStaggerEyes = false;
				tuning.adaptiveHandoff = !adaptiveCrop;
'@
$count = ([regex]::Matches($text, [regex]::Escape($old))).Count
if ($count -ne 1) { throw "Expected one v04 adaptive tuning block, found $count" }
$text = $text.Replace($old, $new)
Write-Normalized $integration $text

$text = Read-Normalized $integration
if ($text -notmatch 'tuning\.temporalReuseCadence = 0;\s*\n\s*tuning\.temporalReuseStaggerEyes = false;') {
    throw 'Atlas adaptive temporal-safety override missing'
}
Write-Host 'v04 atlas/adaptive compatibility hardened.'
