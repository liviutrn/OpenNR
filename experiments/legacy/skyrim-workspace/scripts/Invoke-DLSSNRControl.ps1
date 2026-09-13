[CmdletBinding()]
param(
    [ValidateSet('Status', 'Apply')]
    [string]$Action = 'Status',
    [ValidateSet('leave', 'on', 'off')]
    [string]$Neural = 'leave',
    [ValidateSet('leave', 'Custom', 'Balanced', 'Fabric Detail', 'Natural', 'Strong', 'Cinematic')]
    [string]$Preset = 'leave',
    [double]$Intensity = -1,
    [double]$LocalTone = -1,
    [double]$LocalStructure = -1,
    [double]$SkinStructure = -1,
    [int]$Style = -1,
    [ValidateSet('leave', 'on', 'off')]
    [string]$AutoMask = 'leave',
    [ValidateSet('leave', 'on', 'off')]
    [string]$UICorrection = 'leave',
    [ValidateSet('leave', 'on', 'off')]
    [string]$DeveloperMode = 'leave',
    [string]$SettingsPath = 'E:\MGO-RC3-clean\overwrite\SKSE\Plugins\CommunityShaders\SettingsUser.json',
    [string]$ProjectRoot = 'D:\.CODEX_Projects\DLSS_5_SKYRIM',
    [switch]$AllowRunningGame
)

$ErrorActionPreference = 'Stop'

function Get-SettingObject {
    if (-not (Test-Path -LiteralPath $SettingsPath)) {
        throw "Settings file was not found: $SettingsPath"
    }

    $root = Get-Content -LiteralPath $SettingsPath -Raw | ConvertFrom-Json
    if ($null -eq $root.Upscaling -or $null -eq $root.Upscaling.foveatedRender) {
        throw "The settings file does not contain Upscaling.foveatedRender: $SettingsPath"
    }
    return $root
}

function Convert-SwitchValue([string]$value) {
    if ($value -eq 'leave') { return $null }
    return $value -eq 'on'
}

function Assert-Range([string]$name, [double]$value) {
    if ($value -ge 0 -and $value -le 2) { return }
    throw "$name must be between 0.0 and 2.0, or omitted. Received: $value"
}

function Get-PresetValues([string]$name) {
    switch ($name) {
        'Balanced'    { return @{ Code = 1; Intensity = 1.0;  LocalTone = 1.0;  LocalStructure = 1.0; SkinStructure = 1.0 } }
        'Fabric Detail' { return @{ Code = 2; Intensity = 1.35; LocalTone = 0.9; LocalStructure = 1.6; SkinStructure = 1.15 } }
        'Natural'     { return @{ Code = 3; Intensity = 0.8;  LocalTone = 0.75; LocalStructure = 0.9; SkinStructure = 0.9 } }
        'Strong'      { return @{ Code = 4; Intensity = 1.75; LocalTone = 1.25; LocalStructure = 1.5; SkinStructure = 1.3 } }
        # Project-defined profile; Open Shaders itself currently exposes Custom,
        # Balanced, Fabric Detail, Natural, and Strong. Cinematic is stored as
        # Custom with restrained tone and moderate detail.
        'Cinematic'  { return @{ Code = 0; Intensity = 1.25; LocalTone = 0.65; LocalStructure = 1.25; SkinStructure = 1.0; Style = 3 } }
        'Custom'      { return @{ Code = 0 } }
        default       { return $null }
    }
}

$root = Get-SettingObject
$u = $root.Upscaling.foveatedRender

if ($Action -eq 'Status') {
    [pscustomobject]@{
        SettingsPath = $SettingsPath
        GameRunning = [bool](Get-Process -Name SkyrimVR -ErrorAction SilentlyContinue)
        DeveloperMode = if ($null -ne $root.Advanced) { [bool]$root.Advanced.'Developer Mode' } else { $false }
        NeuralRenderingEnabled = [bool]$u.neuralRenderingEnabled
        TuningPreset = @('Custom', 'Balanced', 'Fabric Detail', 'Natural', 'Strong')[[int]$u.neuralRenderingPreset]
        TuningPresetCode = [int]$u.neuralRenderingPreset
        Intensity = [double]$u.neuralRenderingIntensity
        LocalTone = [double]$u.neuralRenderingLocalTone
        LocalStructure = [double]$u.neuralRenderingLocalStructure
        SkinStructure = [double]$u.neuralRenderingSkinStructure
        Style = [int]$u.neuralRenderingStyle
        AutomaticMask = [bool]$u.neuralRenderingAutoMask
        UICorrection = [bool]$u.neuralRenderingUICorrection
        UpscaleMethod = [int]$root.Upscaling.upscaleMethod
        QualityMode = [int]$root.Upscaling.qualityMode
        FoveatedEnabled = [bool]$u.enabled
        Crop = "{0}x{1} at {2},{3}" -f $u.CropW, $u.CropH, $u.CropX, $u.CropY
    } | Format-List
    exit 0
}

$hasNumericChange = $Intensity -ge 0 -or $LocalTone -ge 0 -or $LocalStructure -ge 0 -or $SkinStructure -ge 0
$hasChange = $Neural -ne 'leave' -or $Preset -ne 'leave' -or $hasNumericChange -or $Style -ge 0 -or $AutoMask -ne 'leave' -or $UICorrection -ne 'leave' -or $DeveloperMode -ne 'leave'
if (-not $hasChange) {
    throw 'Apply requires at least one control: -Neural, -Preset, -Intensity, -LocalTone, -LocalStructure, -SkinStructure, -Style, -AutoMask, -UICorrection, or -DeveloperMode.'
}

if ($Intensity -ge 0) { Assert-Range 'Intensity' $Intensity }
if ($LocalTone -ge 0) { Assert-Range 'LocalTone' $LocalTone }
if ($LocalStructure -ge 0) { Assert-Range 'LocalStructure' $LocalStructure }
if ($SkinStructure -ge 0) { Assert-Range 'SkinStructure' $SkinStructure }
if ($Style -lt -1 -or $Style -gt 3) { throw 'Style must be 0, 1, 2, or 3.' }

$game = Get-Process -Name SkyrimVR -ErrorAction SilentlyContinue
if ($game -and -not $AllowRunningGame) {
    throw 'SkyrimVR is running. Use the in-game Open Shaders panel for live changes, or close the game before applying JSON changes. Pass -AllowRunningGame only for an intentional live-file experiment.'
}

$presetValues = if ($Preset -ne 'leave') { Get-PresetValues $Preset } else { $null }
if ($null -ne $presetValues) {
    $u.neuralRenderingPreset = $presetValues.Code
    if ($presetValues.ContainsKey('Intensity')) {
        $u.neuralRenderingIntensity = $presetValues.Intensity
        $u.neuralRenderingLocalTone = $presetValues.LocalTone
        $u.neuralRenderingLocalStructure = $presetValues.LocalStructure
        $u.neuralRenderingSkinStructure = $presetValues.SkinStructure
    }
    if ($presetValues.ContainsKey('Style')) { $u.neuralRenderingStyle = $presetValues.Style }
}

if ($Neural -ne 'leave') { $u.neuralRenderingEnabled = ($Neural -eq 'on') }
if ($Intensity -ge 0) { $u.neuralRenderingIntensity = $Intensity; $u.neuralRenderingPreset = 0 }
if ($LocalTone -ge 0) { $u.neuralRenderingLocalTone = $LocalTone; $u.neuralRenderingPreset = 0 }
if ($LocalStructure -ge 0) { $u.neuralRenderingLocalStructure = $LocalStructure; $u.neuralRenderingPreset = 0 }
if ($SkinStructure -ge 0) { $u.neuralRenderingSkinStructure = $SkinStructure; $u.neuralRenderingPreset = 0 }
if ($Style -ge 0) { $u.neuralRenderingStyle = $Style; $u.neuralRenderingPreset = 0 }

$autoMaskValue = Convert-SwitchValue $AutoMask
if ($null -ne $autoMaskValue) { $u.neuralRenderingAutoMask = $autoMaskValue }
$uiCorrectionValue = Convert-SwitchValue $UICorrection
if ($null -ne $uiCorrectionValue) { $u.neuralRenderingUICorrection = $uiCorrectionValue }
$developerModeValue = Convert-SwitchValue $DeveloperMode
if ($null -ne $developerModeValue) {
    if ($null -eq $root.Advanced) { $root | Add-Member -MemberType NoteProperty -Name Advanced -Value ([pscustomobject]@{}) }
    $root.Advanced.'Developer Mode' = $developerModeValue
}

$backupDir = Join-Path $ProjectRoot 'backups'
New-Item -ItemType Directory -Force -Path $backupDir | Out-Null
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$backup = Join-Path $backupDir "dlssnr-control-before-$stamp.json"
Copy-Item -LiteralPath $SettingsPath -Destination $backup

$serialized = $root | ConvertTo-Json -Depth 100
$temporary = "$SettingsPath.codex-$stamp.tmp"
$utf8NoBom = [System.Text.UTF8Encoding]::new($false)
[System.IO.File]::WriteAllText($temporary, $serialized, $utf8NoBom)
Move-Item -LiteralPath $temporary -Destination $SettingsPath -Force

[pscustomobject]@{
    Applied = $true
    SettingsPath = $SettingsPath
    Backup = $backup
    DeveloperMode = if ($null -ne $root.Advanced) { [bool]$root.Advanced.'Developer Mode' } else { $false }
    NeuralRenderingEnabled = [bool]$u.neuralRenderingEnabled
    TuningPresetCode = [int]$u.neuralRenderingPreset
    Intensity = [double]$u.neuralRenderingIntensity
    LocalTone = [double]$u.neuralRenderingLocalTone
    LocalStructure = [double]$u.neuralRenderingLocalStructure
    SkinStructure = [double]$u.neuralRenderingSkinStructure
    Style = [int]$u.neuralRenderingStyle
    AutomaticMask = [bool]$u.neuralRenderingAutoMask
    UICorrection = [bool]$u.neuralRenderingUICorrection
    Note = 'Restart SkyrimVR for deterministic application; use the Open Shaders panel for live changes.'
} | Format-List
