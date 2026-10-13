# Run this from the extracted Glamarye plugin folder before launching STALKER 2.
# Registers the layer for the current Windows user only. No admin required.
$ErrorActionPreference = 'Stop'
$layer = Join-Path $PSScriptRoot 'layer'
$manifest = Join-Path $layer 'glamayre_openxr.json'
$dll = Join-Path $layer 'GlamaryeOpenXRLayer.dll'
if (-not (Test-Path -LiteralPath $manifest -PathType Leaf)) { throw "Missing manifest: $manifest" }
if (-not (Test-Path -LiteralPath $dll -PathType Leaf)) { throw "Missing DLL: $dll" }
$manifest = (Resolve-Path -LiteralPath $manifest).Path
$reg = 'HKCU:\SOFTWARE\Khronos\OpenXR\1\ApiLayers\Implicit'
New-Item -Path $reg -Force | Out-Null
New-ItemProperty -Path $reg -Name $manifest -PropertyType DWord -Value 0 -Force | Out-Null
Write-Host "Glamarye OpenXR layer enabled for CURRENT USER."
Write-Host "Manifest: $manifest"
Write-Host "Restart the game and UEVR after installation."
Write-Host "To disable it, run uninstall-layer.ps1."
