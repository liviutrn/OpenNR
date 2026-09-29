[CmdletBinding()]
param(
    [ValidateSet('Begin', 'Capture', 'Status')]
    [string]$Action = 'Status',
    [ValidateSet('A', 'B')]
    [string]$Side,
    [string]$Session,
    [string]$Name = 'skyrimvr',
    [string]$SourcePath,
    [int]$WaitSeconds = 45,
    [string]$ProjectRoot = 'D:\.CODEX_Projects\DLSS_5_SKYRIM',
    [string]$GameRoot = 'E:\Games\Steam\steamapps\common\SkyrimVR',
    [string]$SettingsPath = 'E:\MGO-RC3-clean\overwrite\SKSE\Plugins\CommunityShaders\SettingsUser.json',
    [string]$ScreenshotRoot
)

$ErrorActionPreference = 'Stop'
$comparisonRoot = Join-Path $ProjectRoot 'captures\ab'
New-Item -ItemType Directory -Force -Path $comparisonRoot | Out-Null

function Get-SessionDirectory {
    if ($Session) {
        if (Test-Path -LiteralPath $Session -PathType Container) { return (Resolve-Path -LiteralPath $Session).Path }
        $candidate = Join-Path $comparisonRoot $Session
        if (Test-Path -LiteralPath $candidate -PathType Container) { return (Resolve-Path -LiteralPath $candidate).Path }
        throw "Comparison session was not found: $Session"
    }
    $latest = Get-ChildItem -LiteralPath $comparisonRoot -Directory | Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if (-not $latest) { throw "No comparison session exists under $comparisonRoot" }
    return $latest.FullName
}

function Read-SettingsSnapshot {
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

if ($Action -eq 'Status') {
    $sessions = Get-ChildItem -LiteralPath $comparisonRoot -Directory | Sort-Object LastWriteTime -Descending
    if (-not $sessions) { 'No A/B sessions yet.'; exit 0 }
    $statusRows = foreach ($dir in $sessions) {
        $meta = Join-Path $dir.FullName 'session.json'
        [pscustomobject]@{ Session = $dir.Name; LastWriteTime = $dir.LastWriteTime; A = (Test-Path -LiteralPath (Join-Path $dir.FullName 'A.json')); B = (Test-Path -LiteralPath (Join-Path $dir.FullName 'B.json')); Metadata = $meta }
    }
    $statusRows | Format-Table -AutoSize
    exit 0
}

if ($Action -eq 'Begin') {
    $stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
    $dir = Join-Path $comparisonRoot "$Name-$stamp"
    New-Item -ItemType Directory -Force -Path $dir | Out-Null
    $settings = Read-SettingsSnapshot
    if ($settings) { $settings | ConvertTo-Json -Depth 100 | Set-Content -LiteralPath (Join-Path $dir 'session-settings.json') -Encoding UTF8 }
    $game = Get-Process -Name SkyrimVR -ErrorAction SilentlyContinue | Select-Object -First 1 ProcessName,Id,StartTime,CPU
    [pscustomobject]@{
        Session = $dir
        Name = $Name
        StartedUtc = [DateTime]::UtcNow.ToString('o')
        ScreenshotRoot = if ($ScreenshotRoot) { $ScreenshotRoot } else { Join-Path $GameRoot 'Screenshots' }
        Game = $game
        Instructions = 'Hold the same viewpoint. Press the Open Shaders screenshot hotkey, then run Capture for side A. Toggle only NR, keep the viewpoint fixed, press the same hotkey, then run Capture for side B.'
    } | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath (Join-Path $dir 'session.json') -Encoding UTF8
    [pscustomobject]@{ Session = $dir; StartedUtc = [DateTime]::UtcNow.ToString('o'); Next = "Capture with -Side A -Session '$($dir)' after pressing the native screenshot hotkey." } | Format-List
    exit 0
}

if (-not $Side) { throw 'Capture requires -Side A or -Side B.' }
$dir = Get-SessionDirectory
$sessionMetaPath = Join-Path $dir 'session.json'
$sessionMeta = if (Test-Path -LiteralPath $sessionMetaPath) { Get-Content -LiteralPath $sessionMetaPath -Raw | ConvertFrom-Json } else { $null }
$sinceUtc = if ($sessionMeta.StartedUtc) { [DateTime]::Parse($sessionMeta.StartedUtc).ToUniversalTime() } else { (Get-Date).ToUniversalTime().AddMinutes(-5) }

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
if (-not $source) {
    throw "No new native screenshot found. Press the configured Open Shaders screenshot key first, or pass -SourcePath. Searched the game Screenshots folder and project captures."
}

$destination = Join-Path $dir ("{0}{1}" -f $Side, $source.Extension.ToLowerInvariant())
$resolvedSource = (Resolve-Path -LiteralPath $source.FullName).Path
$resolvedDestination = if (Test-Path -LiteralPath $destination) { (Resolve-Path -LiteralPath $destination).Path } else { $destination }
if ($resolvedSource -ne $resolvedDestination) {
    Copy-Item -LiteralPath $source.FullName -Destination $destination -Force
}
$settings = Read-SettingsSnapshot
if ($settings) { $settings | ConvertTo-Json -Depth 100 | Set-Content -LiteralPath (Join-Path $dir "$Side-settings.json") -Encoding UTF8 }
$hash = (Get-FileHash -LiteralPath $destination -Algorithm SHA256).Hash
[pscustomobject]@{
    Side = $Side
    Session = $dir
    Source = $source.FullName
    Output = $destination
    SHA256 = $hash
    CapturedUtc = [DateTime]::UtcNow.ToString('o')
    SettingsSnapshot = Join-Path $dir "$Side-settings.json"
} | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath (Join-Path $dir "$Side.json") -Encoding UTF8

[pscustomobject]@{ Side = $Side; Output = $destination; SHA256 = $hash; SettingsSnapshot = Join-Path $dir "$Side-settings.json" } | Format-List
