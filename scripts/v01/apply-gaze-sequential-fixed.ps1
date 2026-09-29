$ErrorActionPreference = 'Stop'

$source = 'scripts/v01/apply-gaze-sequential.ps1'
$text = [IO.File]::ReadAllText((Resolve-Path $source)).Replace("`r`n", "`n")
$old = '$pattern = ''(\t\t\tTuning tuning\\{.*?\\n\t\t\t\\};\\n)(\t\t\tif constexpr \\(kFullResolutionNeuralRenderingOnly\\))'''
$new = '$pattern = ''(?:\t\t\t)?Tuning tuning\\{.*?\\n\t\t\t\\};\\n(?=\t\t\tif constexpr \\(kFullResolutionNeuralRenderingOnly\\))'''
if (-not $text.Contains($old)) { throw 'Expected GetTuning regex declaration not found in gaze script' }
$text = $text.Replace($old, $new)
[IO.File]::WriteAllText((Resolve-Path $source), $text, [Text.UTF8Encoding]::new($false))

# The corrected regex no longer exposes capture groups, so its replacement must
# simply inject the v01 assignments immediately before the existing if constexpr.
$text = [IO.File]::ReadAllText((Resolve-Path $source)).Replace("`r`n", "`n")
$oldReplacementStart = '$replacement = @''`n$1'
if ($text.Contains($oldReplacementStart)) {
    throw 'Unexpected literal newline encoding in gaze script replacement block'
}
# Rewrite $1/$2 placeholders used by the original grouped regex into an explicit
# whole-match preservation plus look-ahead. $0 preserves the aggregate itself.
$text = $text.Replace("`$1`t`t`t", "`$0`t`t`t")
$text = $text.Replace("`n`$2`n'@", "`n'@")
[IO.File]::WriteAllText((Resolve-Path $source), $text, [Text.UTF8Encoding]::new($false))

& pwsh -NoProfile -File $source
if ($LASTEXITCODE -ne 0) { throw "Corrected gaze/sequential transform failed with exit code $LASTEXITCODE" }
