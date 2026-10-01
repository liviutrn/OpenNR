$ErrorActionPreference = 'Stop'

$source = 'scripts/v02/apply-sharpening.ps1'
$resolved = Resolve-Path $source
$text = [IO.File]::ReadAllText($resolved).Replace("`r`n", "`n")
$old = 'found $count: $Needle'
$new = 'found ${count}: $Needle'
$count = ([regex]::Matches($text, [regex]::Escape($old))).Count
if ($count -ne 1) { throw "Expected one sharpening parser repair anchor, found $count" }
$text = $text.Replace($old, $new)
[IO.File]::WriteAllText($resolved, $text, [Text.UTF8Encoding]::new($false))

& pwsh -NoProfile -File $source
if ($LASTEXITCODE -ne 0) { throw "Corrected sharpening transform failed with exit code $LASTEXITCODE" }
