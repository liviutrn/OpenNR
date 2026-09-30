$ErrorActionPreference = 'Stop'

$source = 'scripts/v01/apply-sequential-renderer.ps1'
$resolved = Resolve-Path $source
$text = [IO.File]::ReadAllText($resolved).Replace("`r`n", "`n")

# Replace brittle EnsureResources call-site injection.
$blockRx = [regex]::new('(?s)# Both normal entry points pass the configured relative coverage\..*?\[IO\.File\]::WriteAllText\(\(Resolve-Path \$renderer\), \$text, \[Text\.UTF8Encoding\]::new\(\$false\)\)\n')
if ($blockRx.Matches($text).Count -ne 1) { throw 'Expected one EnsureResources injection block' }
$blockReplacement = @'
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
$text = $blockRx.Replace($text, $blockReplacement + "`n", 1)

# Replace brittle ExecuteCascade call-site injection. Apply(), ApplyStereo(), and
# staggered stereo have different indentation but the same resource pair.
$cascadeBlockRx = [regex]::new('(?s)# Every cascade call now provides the optional compact pass-2 target\..*?\[IO\.File\]::WriteAllText\(\(Resolve-Path \$renderer\), \$text, \[Text\.UTF8Encoding\]::new\(\$false\)\)\n')
if ($cascadeBlockRx.Matches($text).Count -ne 1) { throw 'Expected one cascade call injection block' }
$cascadeReplacement = @'
# Every cascade call now provides the optional compact pass-2 target. Preserve
# each call site's indentation rather than assuming one nesting depth.
$text = [IO.File]::ReadAllText((Resolve-Path $renderer)).Replace("`r`n", "`n")
$cascadeRx = [regex]::new('tier\.cascadeIntermediates\[0\]\.resource12\.Get\(\), tier\.cascadeIntermediates\[1\]\.resource12\.Get\(\) \},\n(?<indent>\s*)tier\.output\.resource12\.Get\(\),')
$cascadeMatches = $cascadeRx.Matches($text)
if ($cascadeMatches.Count -lt 2) { throw "Expected at least two cascade call anchors, found $($cascadeMatches.Count)" }
$text = $cascadeRx.Replace($text, { param($m)
    "tier.cascadeIntermediates[0].resource12.Get(), tier.cascadeIntermediates[1].resource12.Get() },`n$($m.Groups['indent'].Value)tier.secondPassOutput.resource12.Get(), tier.output.resource12.Get(),"
})
[IO.File]::WriteAllText((Resolve-Path $renderer), $text, [Text.UTF8Encoding]::new($false))
'@
$text = $cascadeBlockRx.Replace($text, $cascadeReplacement + "`n", 1)

[IO.File]::WriteAllText($resolved, $text, [Text.UTF8Encoding]::new($false))
& pwsh -NoProfile -File $source
if ($LASTEXITCODE -ne 0) { throw "Corrected sequential renderer transform failed with exit code $LASTEXITCODE" }
