$ErrorActionPreference = 'Stop'

# fixed3 already contains the intended final sharpening implementation. Its only
# remaining brittle point is an exact match for the pre-v02 ApplyDlssSharpening
# function body. Rewrite that one invocation to select the function by its
# signature and namespace boundary, leaving the replacement function unchanged.
$source = 'scripts/v02/apply-sharpening-fixed3.ps1'
$resolved = Resolve-Path $source
$text = [IO.File]::ReadAllText($resolved).Replace("`r`n", "`n")
$old = 'Replace-Exact $post $old $new'
$new = @'
$pattern = '(?s)\tbool Postprocess::ApplyDlssSharpening\(Upscaling& upscaling\)\s*\{.*?\n\t\}(?=\n\})'
Replace-RegexOnce $post $pattern $new
'@
$count = ([regex]::Matches($text, [regex]::Escape($old))).Count
if ($count -ne 1) { throw "Expected one Postprocess replacement invocation in fixed3, found $count" }
$text = $text.Replace($old, $new)
[IO.File]::WriteAllText($resolved, $text, [Text.UTF8Encoding]::new($false))

& pwsh -NoProfile -File $source
if ($LASTEXITCODE -ne 0) { throw "Sharpening fixed4 transform failed with exit code $LASTEXITCODE" }

Write-Host 'v02 sharpening fixed4 function-boundary selector applied successfully.'