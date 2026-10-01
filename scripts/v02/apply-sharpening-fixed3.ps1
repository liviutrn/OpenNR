$ErrorActionPreference = 'Stop'

# Repair the v02 sharpening transform itself before executing it. PowerShell does
# not use backslash to escape quotes inside double-quoted strings; the previous
# source line could therefore generate a malformed/empty C++ include.
$source = 'scripts/v02/apply-sharpening.ps1'
$resolved = Resolve-Path $source
$text = [IO.File]::ReadAllText($resolved).Replace("`r`n", "`n")
$old = 'Insert-After-Unique $foveated ''#include "FoveatedRender/Core.h"'' "`n#include \"FoveatedRender/Postprocess.h\""'
$new = 'Insert-After-Unique $foveated ''#include "FoveatedRender/Core.h"'' ("`n" + ''#include "FoveatedRender/Postprocess.h"'')'
$count = ([regex]::Matches($text, [regex]::Escape($old))).Count
if ($count -ne 1) { throw "Expected one malformed sharpening include anchor, found $count" }
$text = $text.Replace($old, $new)
[IO.File]::WriteAllText($resolved, $text, [Text.UTF8Encoding]::new($false))

& pwsh -NoProfile -File scripts/v02/apply-sharpening-fixed2.ps1
if ($LASTEXITCODE -ne 0) { throw "Sharpening transform failed with exit code $LASTEXITCODE" }

$foveated = Resolve-Path 'runtime/open-shaders/src/Features/Upscaling/FoveatedRender.cpp'
$fovText = [IO.File]::ReadAllText($foveated).Replace("`r`n", "`n")
$include = '#include "FoveatedRender/Postprocess.h"'
$includeCount = ([regex]::Matches($fovText, [regex]::Escape($include))).Count
if ($includeCount -ne 1) { throw "Expected exactly one valid Postprocess include after sharpening transform, found $includeCount" }
if ($fovText -match '#include\s+""') { throw 'Sharpening transform still produced an empty include' }

Write-Host 'v02 sharpening include generation repaired and verified.'
