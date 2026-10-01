$ErrorActionPreference = 'Stop'

& pwsh -NoProfile -File scripts/v02/apply-sharpening-fixed.ps1
if ($LASTEXITCODE -ne 0) { throw "Sharpening transform failed with exit code $LASTEXITCODE" }

$foveated = Resolve-Path 'runtime/open-shaders/src/Features/Upscaling/FoveatedRender.cpp'
$text = [IO.File]::ReadAllText($foveated).Replace("`r`n", "`n")

# The final status/recovery panel has its own Renderer reference. After the v02
# sharpening UI insertion MSVC sees that declaration in the same lambda scope as
# an earlier renderer reference. Rename only this bounded status-panel handle;
# no behavior or lifetime changes.
$pattern = '(?s)(\n\s*)auto& neuralRenderer = NeuralRendering::Renderer::Instance\(\);(?<body>.*?)(?=\n\s*if \(!supportedRoute\))'
$rx = [regex]::new($pattern)
$matches = $rx.Matches($text)
if ($matches.Count -ne 1) {
    throw "Expected exactly one final neural-renderer status block, found $($matches.Count)"
}
$match = $matches[0]
$replacement = $match.Value.Replace('auto& neuralRenderer = NeuralRendering::Renderer::Instance();',
    'auto& statusRenderer = NeuralRendering::Renderer::Instance();').Replace('neuralRenderer.', 'statusRenderer.')
$text = $text.Substring(0, $match.Index) + $replacement + $text.Substring($match.Index + $match.Length)
[IO.File]::WriteAllText($foveated, $text, [Text.UTF8Encoding]::new($false))

$statusCount = ([regex]::Matches($text, [regex]::Escape('auto& statusRenderer = NeuralRendering::Renderer::Instance();'))).Count
if ($statusCount -ne 1) { throw "Expected one statusRenderer declaration after repair, found $statusCount" }

Write-Host 'v02 sharpening status-renderer scope repair applied successfully.'
