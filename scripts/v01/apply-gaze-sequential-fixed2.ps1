$ErrorActionPreference = 'Stop'

$source = 'scripts/v01/apply-gaze-sequential.ps1'
$resolved = Resolve-Path $source
$text = [IO.File]::ReadAllText($resolved).Replace("`r`n", "`n")
$oldLine = '$pattern = ''(\t\t\tTuning tuning\\{.*?\\n\t\t\t\\};\\n)(\t\t\tif constexpr \\(kFullResolutionNeuralRenderingOnly\\))'''
$newLine = '$pattern = ''((?:\t\t\t)?Tuning tuning\\{.*?\\n\t\t\t\\};\\n)(\t\t\tif constexpr \\(kFullResolutionNeuralRenderingOnly\\))'''
$count = ([regex]::Matches($text, [regex]::Escape($oldLine))).Count
if ($count -ne 1) { throw "Expected exactly one GetTuning pattern declaration, found $count" }
[IO.File]::WriteAllText($resolved, $text.Replace($oldLine, $newLine), [Text.UTF8Encoding]::new($false))

& pwsh -NoProfile -File $source
if ($LASTEXITCODE -ne 0) { throw "Corrected gaze/sequential transform failed with exit code $LASTEXITCODE" }
