# Removes only the Glamarye registration at the matching installation path.
$ErrorActionPreference = 'Stop'
$manifest = Join-Path $PSScriptRoot 'layer\glamayre_openxr.json'
$reg = 'HKCU:\SOFTWARE\Khronos\OpenXR\1\ApiLayers\Implicit'
if (Test-Path -LiteralPath $manifest) {
    $manifest = (Resolve-Path -LiteralPath $manifest).Path
}
if (Test-Path $reg) {
    $p = Get-ItemProperty -Path $reg -ErrorAction SilentlyContinue
    if ($p -and ($p.PSObject.Properties.Name -contains $manifest)) {
        Remove-ItemProperty -Path $reg -Name $manifest -ErrorAction Stop
        Write-Host "Glamarye OpenXR API layer disabled for current user."
    } else { Write-Host "No registration found for $manifest" }
} else { Write-Host "No OpenXR implicit-layer registration exists." }
Write-Host "Restart the game afterward."
