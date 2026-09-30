$ErrorActionPreference = 'Stop'

$source = 'scripts/v01/apply-sequential-renderer.ps1'
$resolved = Resolve-Path $source
$text = [IO.File]::ReadAllText($resolved).Replace("`r`n", "`n")
$pattern = '(?s)# Both normal entry points pass the configured relative coverage\..*?\[IO\.File\]::WriteAllText\(\(Resolve-Path \$renderer\), \$text, \[Text\.UTF8Encoding\]::new\(\$false\)\)\n'
$rx = [regex]::new($pattern)
$matches = $rx.Matches($text)
if ($matches.Count -ne 1) { throw "Expected one EnsureResources injection block, found $($matches.Count)" }
$replacement = @'
# Both normal entry points pass the configured relative coverage. Match either
# indentation depth: Apply() and ApplyStereo() do not align identically.
$text = [IO.File]::ReadAllText((Resolve-Path $renderer)).Replace("`r`n", "`n")
$callRx = [regex]::new('passCount, modelResolution,\n(?<indent>\s*)tuning\.adaptiveResolution,')
$callMatches = $callRx.Matches($text)
if ($callMatches.Count -ne 2) { throw "Expected two EnsureResources call anchors, found $($callMatches.Count)" }
$text = $callRx.Replace($text, { param($m)
    "passCount, modelResolution, passCount > 1 ? tuning.secondPass.coveragePercent : 100u,`n$($m.Groups['indent'].Value)tuning.adaptiveResolution,"
})
[IO.File]::WriteAllText((Resolve-Path $renderer), $text, [Text.UTF8Encoding]::new($false))
'@
$text = $rx.Replace($text, $replacement + "`n", 1)
[IO.File]::WriteAllText($resolved, $text, [Text.UTF8Encoding]::new($false))

& pwsh -NoProfile -File $source
if ($LASTEXITCODE -ne 0) { throw "Corrected sequential renderer transform failed with exit code $LASTEXITCODE" }
