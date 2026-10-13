param([ValidateRange(0,3)][int]$Mode=0)
$ErrorActionPreference='Stop'
if (Get-Process 'Stalker2-Win64-Shipping' -ErrorAction SilentlyContinue) { throw 'Close STALKER 2 before installing or changing the test mode.' }
$profilePath=Join-Path $env:APPDATA 'UnrealVRMod\Stalker2-Win64-Shipping'
$plugins=Join-Path $profilePath 'plugins'
New-Item $plugins -ItemType Directory -Force | Out-Null
$backup=Join-Path $profilePath ('DuoViewBackup-'+(Get-Date -Format 'yyyyMMdd-HHmmss'))
$items=@('CheekyFoveatedDLSS.dll','CheekyFoveatedDLSSRuntime.dll','CheekyFoveatedDLSS','DuoViewJoey.dll')
foreach ($item in $items) {
  $from=Join-Path $plugins $item
  if (Test-Path $from) {
    New-Item $backup -ItemType Directory -Force | Out-Null
    Move-Item $from $backup
  }
}
$config=Join-Path $profilePath 'DuoViewJoey.ini'
if (Test-Path $config) {
  New-Item $backup -ItemType Directory -Force | Out-Null
  Copy-Item $config $backup
}
Copy-Item (Join-Path $PSScriptRoot 'Plugin\DuoViewJoey.dll') $plugins
$text=Get-Content (Join-Path $PSScriptRoot 'Plugin\DuoViewJoey.ini') -Raw
$text=$text -replace '(?m)^Mode=\d+$',"Mode=$Mode"
Set-Content $config $text -Encoding ASCII
Write-Host "Installed test mode $Mode. Use JoeyOriginal\UEVRInjector.exe from this extracted package."
Write-Host 'Disable Cheeky and ReShade OpenXR API layers for this test.'
if ($Mode -eq 0) { Write-Host 'Select ordinary Mono. This stage records diagnostics and does not hook rendering.' }
else { Write-Host 'Select Native Stereo, with Native Fix, Extreme Compatibility, 2D Screen, and Stereo Emulation OFF.' }
Write-Host 'Remove plugins\DuoViewJoey.dll to restore ordinary Joey behavior. Any moved plugins are in the timestamped backup folder.'
