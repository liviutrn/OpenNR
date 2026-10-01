$ErrorActionPreference = 'Stop'

function Read-Normalized([string]$Path) {
    return [IO.File]::ReadAllText((Resolve-Path $Path)).Replace("`r`n", "`n")
}
function Write-Normalized([string]$Path, [string]$Text) {
    [IO.File]::WriteAllText((Resolve-Path $Path), $Text, [Text.UTF8Encoding]::new($false))
}

$integration = 'runtime/open-shaders/src/Features/Upscaling/NeuralRendering/Integration.cpp'
$text = Read-Normalized $integration

# Anchor to the unique v04 explanatory comment rather than the exact surrounding
# indentation/body produced by earlier transforms. Insert the atlas-safety flags
# immediately after v04 disables adaptive model-resolution switching.
$pattern = '(?s)(// Pass/crop adaptation must not set adaptiveResolution: the stereo-atlas.*?\n(?<indent>\s*)tuning\.adaptiveResolution = false;\n)'
$rx = [regex]::new($pattern)
$matches = $rx.Matches($text)
if ($matches.Count -ne 1) {
    throw "Expected one v04 adaptive tuning marker, found $($matches.Count)"
}
$match = $matches[0]
$indent = $match.Groups['indent'].Value
$insert = $match.Groups[1].Value +
    $indent + "// Stereo atlas requires temporal reuse and staggered-eye reuse to be inactive.`n" +
    $indent + "// Keep stale experimental settings from forcing independent-eye fallback.`n" +
    $indent + "tuning.temporalReuseCadence = 0;`n" +
    $indent + "tuning.temporalReuseStaggerEyes = false;`n"
$text = $text.Substring(0, $match.Index) + $insert + $text.Substring($match.Index + $match.Length)
Write-Normalized $integration $text

$text = Read-Normalized $integration
if ($text -notmatch 'tuning\.adaptiveResolution = false;\s*\n\s*// Stereo atlas requires temporal reuse.*?\n\s*// Keep stale experimental settings.*?\n\s*tuning\.temporalReuseCadence = 0;\s*\n\s*tuning\.temporalReuseStaggerEyes = false;') {
    throw 'Atlas adaptive temporal-safety override missing'
}
Write-Host 'v04 atlas/adaptive compatibility hardened.'
