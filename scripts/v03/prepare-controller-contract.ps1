$ErrorActionPreference = 'Stop'

$path = 'runtime/open-shaders/src/Features/Upscaling/NeuralRendering/Integration.cpp'
$resolved = Resolve-Path $path
$text = [IO.File]::ReadAllText($resolved).Replace("`r`n", "`n")
$old = 'LogPreUpscaleBlocked("VR pre-NR is currently limited to Full Eye");'
$new = 'LogPreUpscaleBlocked("VR pre-NR crop route is unavailable");'
$count = ([regex]::Matches($text, [regex]::Escape($old))).Count
if ($count -ne 1) { throw "Expected one retired pre-NR Full Eye diagnostic, found $count" }
$text = $text.Replace($old, $new)
[IO.File]::WriteAllText($resolved, $text, [Text.UTF8Encoding]::new($false))
Write-Host 'v03 controller contract prepared: retired pre-NR diagnostic no longer implies an active Full Eye controller restriction.'
