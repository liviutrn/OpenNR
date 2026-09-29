[CmdletBinding()]
param(
    [ValidateSet('Begin', 'Capture', 'Status')]
    [string]$Action = 'Status',
    [ValidateSet('Off', 'I0.0', 'I0.5', 'I1.0', 'I1.5', 'I2.0', 'Cinematic')]
    [string]$Profile,
    [string]$Session,
    [string]$Name = 'nr-intensity',
    [string]$SourcePath,
    [int]$WaitSeconds = 45,
    [string]$ProjectRoot = 'D:\.CODEX_Projects\DLSS_5_SKYRIM',
    [string]$GameRoot = 'E:\Games\Steam\steamapps\common\SkyrimVR',
    [string]$SettingsPath = 'E:\MGO-RC3-clean\overwrite\SKSE\Plugins\CommunityShaders\SettingsUser.json',
    [string]$ScreenshotRoot
)

$ErrorActionPreference = 'Stop'
$matrixRoot = Join-Path $ProjectRoot 'captures\intensity-matrix'
New-Item -ItemType Directory -Force -Path $matrixRoot | Out-Null

$profiles = @(
    [ordered]@{ Label = 'Off'; Neural = $false; Intensity = $null; PresetCode = $null; Preset = 'Neural off' },
    [ordered]@{ Label = 'I0.0'; Neural = $true; Intensity = 0.0; PresetCode = 0; Preset = 'Custom' },
    [ordered]@{ Label = 'I0.5'; Neural = $true; Intensity = 0.5; PresetCode = 0; Preset = 'Custom' },
    [ordered]@{ Label = 'I1.0'; Neural = $true; Intensity = 1.0; PresetCode = 0; Preset = 'Custom' },
    [ordered]@{ Label = 'I1.5'; Neural = $true; Intensity = 1.5; PresetCode = 0; Preset = 'Custom' },
    [ordered]@{ Label = 'I2.0'; Neural = $true; Intensity = 2.0; PresetCode = 0; Preset = 'Custom' },
    [ordered]@{ Label = 'Cinematic'; Neural = $true; Intensity = 1.25; PresetCode = 0; LocalTone = 0.65; LocalStructure = 1.25; SkinStructure = 1.0; Style = 3; Preset = 'Project-defined Cinematic' }
)

function Get-SessionDirectory {
    if ($Session) {
        if (Test-Path -LiteralPath $Session -PathType Container) { return (Resolve-Path -LiteralPath $Session).Path }
        $candidate = Join-Path $matrixRoot $Session
        if (Test-Path -LiteralPath $candidate -PathType Container) { return (Resolve-Path -LiteralPath $candidate).Path }
        throw "Intensity matrix session was not found: $Session"
    }
    $latest = Get-ChildItem -LiteralPath $matrixRoot -Directory | Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if (-not $latest) { throw "No intensity matrix session exists under $matrixRoot" }
    return $latest.FullName
}

function Get-ExpectedProfile([string]$label) {
    $item = $profiles | Where-Object { $_.Label -eq $label }
    if (-not $item) { throw "Unknown matrix profile: $label" }
    return $item
}

function Read-Settings {
    if (-not (Test-Path -LiteralPath $SettingsPath)) { return $null }
    return (Get-Content -LiteralPath $SettingsPath -Raw | ConvertFrom-Json)
}

function Get-ImageCandidates([datetime]$sinceUtc, [string]$excludeDirectory) {
    $roots = @()
    if ($ScreenshotRoot) { $roots += $ScreenshotRoot }
    $roots += (Join-Path $GameRoot 'Screenshots')
    $roots += (Join-Path $GameRoot 'screenshots')
    foreach ($root in ($roots | Select-Object -Unique)) {
        if (-not (Test-Path -LiteralPath $root -PathType Container)) { continue }
        Get-ChildItem -LiteralPath $root -File -Recurse -ErrorAction SilentlyContinue |
            Where-Object {
                $_.Extension -match '^\.(png|bmp|jpg|jpeg)$' -and
                $_.LastWriteTimeUtc -gt $sinceUtc -and
                $_.FullName -notmatch '(?i)\\omnisight\\' -and
                (-not $excludeDirectory -or -not $_.FullName.StartsWith($excludeDirectory, [System.StringComparison]::OrdinalIgnoreCase))
            }
    }
}

function Test-SettingsMatch($expected, $settings) {
    if (-not $settings -or -not $settings.Upscaling -or -not $settings.Upscaling.foveatedRender) { return $false }
    $u = $settings.Upscaling.foveatedRender
    if ([bool]$u.neuralRenderingEnabled -ne [bool]$expected.Neural) { return $false }
    if ($null -ne $expected.PresetCode -and [int]$u.neuralRenderingPreset -ne [int]$expected.PresetCode) { return $false }
    if ($null -ne $expected.Intensity -and [math]::Abs([double]$u.neuralRenderingIntensity - [double]$expected.Intensity) -gt 0.01) { return $false }
    foreach ($field in @('LocalTone', 'LocalStructure', 'SkinStructure', 'Style')) {
        if ($null -ne $expected.$field -and [math]::Abs([double]$u.("neuralRendering$field") - [double]$expected.$field) -gt 0.01) { return $false }
    }
    return $true
}

if ($Action -eq 'Status') {
    $sessions = Get-ChildItem -LiteralPath $matrixRoot -Directory | Sort-Object LastWriteTime -Descending
    if (-not $sessions) { 'No intensity matrix sessions yet.'; exit 0 }
    $statusRows = foreach ($dir in $sessions) {
        $present = @($profiles | Where-Object { Test-Path -LiteralPath (Join-Path $dir.FullName "$($_.Label).json") }).Count
        [pscustomobject]@{ Session = $dir.Name; Captured = "$present/$($profiles.Count)"; LastWriteTime = $dir.LastWriteTime; Directory = $dir.FullName }
    }
    $statusRows | Format-Table -AutoSize
    exit 0
}

if ($Action -eq 'Begin') {
    $stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
    $dir = Join-Path $matrixRoot "$Name-$stamp"
    New-Item -ItemType Directory -Force -Path $dir | Out-Null
    $settings = Read-Settings
    if ($settings) { $settings | ConvertTo-Json -Depth 100 | Set-Content -LiteralPath (Join-Path $dir 'baseline-settings.json') -Encoding UTF8 }
    [pscustomobject]@{
        Session = $dir
        StartedUtc = [DateTime]::UtcNow.ToString('o')
        Profiles = $profiles
        ControlScript = (Join-Path $ProjectRoot 'scripts\Invoke-DLSSNRControl.ps1')
        Instructions = 'For each profile, apply the matching settings, keep the same scene/head pose, press the native screenshot hotkey, and run Capture with that profile label.'
    } | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath (Join-Path $dir 'matrix.json') -Encoding UTF8
    [pscustomobject]@{ Session = $dir; Profiles = ($profiles.Label -join ', '); Next = "Capture with -Profile Off -Session '$dir' after setting Neural off and taking a screenshot." } | Format-List
    exit 0
}

if (-not $Profile) { throw 'Capture requires -Profile Off, I0.0, I0.5, I1.0, I1.5, I2.0, or Cinematic.' }
$expected = Get-ExpectedProfile $Profile
$dir = Get-SessionDirectory
$metaPath = Join-Path $dir 'matrix.json'
$matrixMeta = if (Test-Path -LiteralPath $metaPath) { Get-Content -LiteralPath $metaPath -Raw | ConvertFrom-Json } else { $null }
$sinceUtc = if ($matrixMeta.StartedUtc) { [DateTime]::Parse($matrixMeta.StartedUtc).ToUniversalTime() } else { (Get-Date).ToUniversalTime().AddMinutes(-5) }

$source = $null
if ($SourcePath) {
    if (-not (Test-Path -LiteralPath $SourcePath -PathType Leaf)) { throw "Source screenshot was not found: $SourcePath" }
    $source = Get-Item -LiteralPath $SourcePath
} else {
    $deadline = [DateTime]::UtcNow.AddSeconds([math]::Max(1, $WaitSeconds))
    do {
        $source = Get-ImageCandidates $sinceUtc $dir | Sort-Object LastWriteTimeUtc -Descending | Select-Object -First 1
        if ($source) { break }
        Start-Sleep -Milliseconds 500
    } while ([DateTime]::UtcNow -lt $deadline)
}
if (-not $source) { throw 'No new screenshot found. Press the configured Open Shaders screenshot key or pass -SourcePath.' }

$settings = Read-Settings
$settingsMatch = Test-SettingsMatch $expected $settings
if (-not $settingsMatch) {
    throw "Active settings do not match $Profile. Expected Neural=$($expected.Neural), Intensity=$($expected.Intensity), PresetCode=$($expected.PresetCode); use Invoke-DLSSNRControl.ps1 first."
}

$destination = Join-Path $dir ("{0}{1}" -f $Profile, $source.Extension.ToLowerInvariant())
$resolvedSource = (Resolve-Path -LiteralPath $source.FullName).Path
$resolvedDestination = if (Test-Path -LiteralPath $destination) { (Resolve-Path -LiteralPath $destination).Path } else { $destination }
if ($resolvedSource -ne $resolvedDestination) { Copy-Item -LiteralPath $source.FullName -Destination $destination -Force }
$hash = (Get-FileHash -LiteralPath $destination -Algorithm SHA256).Hash
if ($settings) { $settings | ConvertTo-Json -Depth 100 | Set-Content -LiteralPath (Join-Path $dir "$Profile-settings.json") -Encoding UTF8 }
[pscustomobject]@{
    Profile = $Profile
    Session = $dir
    Source = $source.FullName
    Output = $destination
    SHA256 = $hash
    SettingsMatch = $settingsMatch
    CapturedUtc = [DateTime]::UtcNow.ToString('o')
} | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath (Join-Path $dir "$Profile.json") -Encoding UTF8

[pscustomobject]@{ Profile = $Profile; Output = $destination; SHA256 = $hash; SettingsMatch = $settingsMatch } | Format-List
