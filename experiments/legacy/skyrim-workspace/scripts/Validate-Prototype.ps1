[CmdletBinding()]
param(
    [string]$ProjectRoot = 'D:\.CODEX_Projects\DLSS_5_SKYRIM',
    [string]$MgoRoot = 'E:\MGO-RC3-clean',
    [string]$ActiveProfile = 'Mad God Overhaul - NSFW',
    [string]$PrototypeProfile = 'DLSS5 SkyrimVR Prototype',
    [string]$PrototypeMod = 'DLSS5 SkyrimVR Experimental'
)

$ErrorActionPreference = 'Stop'
$checks = [System.Collections.Generic.List[object]]::new()
function Check([string]$Name, [bool]$Passed, [string]$Detail) {
    $checks.Add([pscustomobject]@{ Check = $Name; Result = $(if ($Passed) { 'PASS' } else { 'FAIL' }); Detail = $Detail })
}
function Hash([string]$Path) { (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash }

$active = Join-Path $MgoRoot "profiles\$ActiveProfile"
$prototype = Join-Path $MgoRoot "profiles\$PrototypeProfile"
$mod = Join-Path $MgoRoot "mods\$PrototypeMod"
$baseline = Join-Path $ProjectRoot 'backups\active-profile-baseline-20260829\profile'

Check 'Active profile exists' (Test-Path -LiteralPath $active) $active
Check 'Prototype profile exists' (Test-Path -LiteralPath $prototype) $prototype
Check 'Prototype mod exists' (Test-Path -LiteralPath $mod) $mod
Check 'MO2 still selects the original profile' ((Get-Content -LiteralPath (Join-Path $MgoRoot 'ModOrganizer.ini') -Raw) -match [regex]::Escape("selected_profile=@ByteArray($ActiveProfile)")) $ActiveProfile
$prototypeEnabled = @(Get-Content -LiteralPath (Join-Path $prototype 'modlist.txt') |
    Where-Object { $_ -eq "+$PrototypeMod" }).Count -gt 0
$activeEnabled = @(Get-Content -LiteralPath (Join-Path $active 'modlist.txt') |
    Where-Object { $_ -eq "+$PrototypeMod" }).Count -gt 0
Check 'Prototype mod enabled in prototype profile' $prototypeEnabled 'prototype modlist'
Check 'Prototype mod absent from active profile' (-not $activeEnabled) 'active modlist'

$sourceProfileFiles = Get-ChildItem -LiteralPath $active -Recurse -File | Sort-Object FullName
$baselineFiles = Get-ChildItem -LiteralPath $baseline -Recurse -File | Sort-Object FullName
$profilePathMatch = @((Compare-Object ($sourceProfileFiles | ForEach-Object { $_.FullName.Substring($active.Length).ToLowerInvariant() }) ($baselineFiles | ForEach-Object { $_.FullName.Substring($baseline.Length).ToLowerInvariant() }))).Count -eq 0
$profileHashDiff = 0
foreach ($file in $sourceProfileFiles) {
    $relative = $file.FullName.Substring($active.Length)
    $baseFile = Join-Path $baseline $relative
    if ((Test-Path -LiteralPath $baseFile) -and (Hash $file.FullName) -ne (Hash $baseFile)) { $profileHashDiff++ }
}
Check 'Active profile paths match baseline' $profilePathMatch "$($sourceProfileFiles.Count) files"
Check 'Active profile hashes match baseline' ($profileHashDiff -eq 0) "differences=$profileHashDiff"

$required = @(
    'root\dxgi.dll',
    'root\renodx-dlss5.addon64',
    'root\dlss5-dx11-bridge.addon64',
    'root\nvngx_dlssnr.dll',
    'root\ReShade.ini',
    'root\dlss5-dx11-bridge.cfg',
    'Shaders\Upscaling\Streamline\sl.interposer.dll',
    'Shaders\Upscaling\Streamline\sl.dlss.dll'
)
foreach ($relative in $required) {
    $path = Join-Path $mod $relative
    Check "Prototype file $relative" (Test-Path -LiteralPath $path) $path
}

$skyrim = Join-Path $MgoRoot '..\..\Games\Steam\steamapps\common\SkyrimVR\SkyrimVR.exe'
if (-not (Test-Path -LiteralPath $skyrim)) { $skyrim = 'E:\Games\Steam\steamapps\common\SkyrimVR\SkyrimVR.exe' }
Check 'SkyrimVR executable exists' (Test-Path -LiteralPath $skyrim) $skyrim
if (Test-Path -LiteralPath $skyrim) { Check 'SkyrimVR version is 1.4.15.0' ($((Get-Item -LiteralPath $skyrim).VersionInfo.FileVersion) -eq '1.4.15.0') ((Get-Item -LiteralPath $skyrim).VersionInfo.FileVersion) }

$checks | Format-Table -AutoSize
if ($checks.Result -contains 'FAIL') { exit 1 }
