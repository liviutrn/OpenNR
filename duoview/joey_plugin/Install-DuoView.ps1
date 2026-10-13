param([ValidateRange(0,3)][int]$Mode=0)
$ErrorActionPreference='Stop'
if (Get-Process 'Stalker2-Win64-Shipping' -ErrorAction SilentlyContinue) { throw 'Close STALKER 2 before installing or changing the test mode.' }
$profilePath=Join-Path $env:APPDATA 'UnrealVRMod\Stalker2-Win64-Shipping'
$plugins=Join-Path $profilePath 'plugins'
New-Item $plugins -ItemType Directory -Force | Out-Null
$backup=Join-Path $profilePath ('DuoViewBackup-'+(Get-Date -Format 'yyyyMMdd-HHmmss'))
$items=@('DuoViewJoey.dll')
foreach ($item in $items) {
  $from=Join-Path $plugins $item
  if (Test-Path $from) {
    New-Item $backup -ItemType Directory -Force | Out-Null
    Move-Item $from $backup
  }
}
$data=Join-Path $profilePath 'data'
New-Item $data -ItemType Directory -Force | Out-Null
$config=Join-Path $data 'DuoViewJoey.ini'
if (Test-Path $config) {
  New-Item $backup -ItemType Directory -Force | Out-Null
  Copy-Item $config $backup
}
Copy-Item (Join-Path $PSScriptRoot 'Plugin\DuoViewJoey.dll') $plugins
$scripts=Join-Path $profilePath 'scripts'
New-Item $scripts -ItemType Directory -Force | Out-Null
$oldUi=Join-Path $scripts 'DuoViewJoeyUI.lua'
if (Test-Path $oldUi) {
  New-Item $backup -ItemType Directory -Force | Out-Null
  Copy-Item $oldUi $backup
}
Copy-Item (Join-Path $PSScriptRoot 'Plugin\DuoViewJoeyUI.lua') $scripts
$oldStatus=Join-Path $data 'DuoViewJoey.status'
if (Test-Path $oldStatus) { Remove-Item $oldStatus -Force }
$text=Get-Content (Join-Path $PSScriptRoot 'Plugin\DuoViewJoey.ini') -Raw
$text=$text -replace '(?m)^Mode=\d+$',"Mode=$Mode"
Set-Content $config $text -Encoding ASCII
Write-Host "Installed configuration mode $Mode (requested, not necessarily active)." 
Write-Host 'Owned-copy DuoView candidate: active views wait for an accepted native baseline copy. Headset validation is pending.'
Write-Host 'Use JoeyOriginal\UEVRInjector.exe from the extracted package.'
Write-Host 'UEVR Scripts menu: DuoView Mono - Joey original backend. The Lua UI uses UEVR game/data for settings and status.'
Write-Host 'Conflicting Cheeky/ReShade modules must be disabled for active DuoView modes; this installer DOES NOT change them.'
if ($Mode -eq 0) { Write-Host 'Select ordinary Mono. This stage records diagnostics and does not hook rendering.' }
else { Write-Host 'Select Native Stereo, with Native Fix, Extreme Compatibility, 2D Screen, and Stereo Emulation OFF.' }
Write-Host 'Remove plugins\DuoViewJoey.dll to restore ordinary Joey behavior. The installer leaves other plugins untouched; previous DuoView files are backed up.'
