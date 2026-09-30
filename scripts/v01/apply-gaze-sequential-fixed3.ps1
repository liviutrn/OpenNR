$ErrorActionPreference = 'Stop'

$source = 'scripts/v01/apply-gaze-sequential.ps1'
$resolved = Resolve-Path $source
$text = [IO.File]::ReadAllText($resolved).Replace("`r`n", "`n")
$rx = [regex]::new('(?m)^\$pattern = .*kFullResolutionNeuralRenderingOnly.*$')
$matches = $rx.Matches($text)
if ($matches.Count -ne 1) { throw "Expected exactly one GetTuning pattern declaration, found $($matches.Count)" }
$newLine = @'
$pattern = '((?:\t\t\t)?Tuning tuning\{.*?\n\t\t\t\};\n)(\t\t\tif constexpr \(kFullResolutionNeuralRenderingOnly\))'
'@
$text = $rx.Replace($text, $newLine, 1)
[IO.File]::WriteAllText($resolved, $text, [Text.UTF8Encoding]::new($false))

& pwsh -NoProfile -File $source
if ($LASTEXITCODE -ne 0) { throw "Corrected gaze/sequential transform failed with exit code $LASTEXITCODE" }
