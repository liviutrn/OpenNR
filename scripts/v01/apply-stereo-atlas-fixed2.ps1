$ErrorActionPreference = 'Stop'

$source = 'scripts/v01/apply-stereo-atlas.ps1'
$resolved = Resolve-Path $source
$text = [IO.File]::ReadAllText($resolved).Replace("`r`n", "`n")

$marker = '# Try atlas after all per-eye inputs are prepared and capture has consumed them,'
$markerIndex = $text.IndexOf($marker)
if ($markerIndex -lt 0) { throw 'Atlas insertion marker not found' }
$callText = 'Replace-Exact $renderer $old $new'
$callIndex = $text.IndexOf($callText, $markerIndex)
if ($callIndex -lt 0) { throw 'Atlas insertion Replace-Exact call not found' }

# Replace only this invocation with an exact-match selector. $old and $new are
# still defined by the original script immediately above this point.
$replacementLines = @(
    '$rendererPath = Resolve-Path $renderer',
    '$rendererText = [IO.File]::ReadAllText($rendererPath).Replace("`r`n", "`n")',
    '$matches = [regex]::Matches($rendererText, [regex]::Escape($old))',
    '$selected = @()',
    'foreach ($match in $matches) {',
    '    $tailLength = [Math]::Min(1400, $rendererText.Length - ($match.Index + $match.Length))',
    '    $tail = $rendererText.Substring($match.Index + $match.Length, $tailLength)',
    '    if ($tail.Contains("ExecuteAdaptivePrewarm(commandList, adaptivePrewarm")) { $selected += $match }',
    '}',
    'if ($selected.Count -ne 1) { throw "Expected one stereo BeginD3D12 anchor followed by adaptive prewarm, found $($selected.Count)" }',
    '$match = $selected[0]',
    '$rendererText = $rendererText.Substring(0, $match.Index) + $new + $rendererText.Substring($match.Index + $match.Length)',
    '[IO.File]::WriteAllText($rendererPath, $rendererText, [Text.UTF8Encoding]::new($false))'
)
$replacement = $replacementLines -join "`n"
$text = $text.Substring(0, $callIndex) + $replacement + $text.Substring($callIndex + $callText.Length)
[IO.File]::WriteAllText($resolved, $text, [Text.UTF8Encoding]::new($false))

& pwsh -NoProfile -File $source
if ($LASTEXITCODE -ne 0) { throw "Corrected stereo atlas transform failed with exit code $LASTEXITCODE" }
