[CmdletBinding()]
param(
    [string]$ProjectRoot = 'D:\.CODEX_Projects\DLSS_5_SKYRIM'
)

$ErrorActionPreference = 'Stop'
$shaderRoot = Join-Path $ProjectRoot 'tests\shaders'
$outputRoot = Join-Path $ProjectRoot 'build\shader-tests'

$fxc = Get-ChildItem -LiteralPath 'C:\Program Files (x86)\Windows Kits\10\bin' -Filter 'fxc.exe' -Recurse -ErrorAction SilentlyContinue |
    Where-Object { $_.FullName -match '\\x64\\fxc\.exe$' } |
    Sort-Object FullName -Descending |
    Select-Object -First 1
if ($null -eq $fxc) { throw 'The x64 Windows shader compiler (fxc.exe) was not found.' }
if (-not (Test-Path -LiteralPath $shaderRoot)) { throw "Shader test directory not found: $shaderRoot" }
New-Item -ItemType Directory -Force -Path $outputRoot | Out-Null

$results = foreach ($source in Get-ChildItem -LiteralPath $shaderRoot -Filter '*.hlsl' -File | Sort-Object Name) {
    $output = Join-Path $outputRoot ($source.BaseName + '.cso')
    $null = & $fxc.FullName /nologo /T cs_5_0 /E main /Fo $output $source.FullName 2>&1
    if ($LASTEXITCODE -ne 0) { throw "fxc failed for $($source.Name) with exit code $LASTEXITCODE." }
    [pscustomobject]@{
        Shader = $source.Name
        Compiler = $fxc.FullName
        Output = $output
        Size = (Get-Item -LiteralPath $output).Length
    }
}

$results | Format-Table -AutoSize
