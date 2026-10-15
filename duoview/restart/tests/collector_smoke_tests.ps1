[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'

function Assert-Smoke {
    param([bool]$Condition, [string]$Message)
    if (-not $Condition) { throw $Message }
}

function Read-ZipText {
    param($Archive, [string]$EntryName)
    $entry = $Archive.GetEntry($EntryName)
    Assert-Smoke ($null -ne $entry) ("ZIP is missing $EntryName")
    $stream = $entry.Open()
    $reader = [System.IO.StreamReader]::new($stream)
    try { return $reader.ReadToEnd() }
    finally { $reader.Dispose(); $stream.Dispose() }
}

if ([System.Environment]::OSVersion.Platform -ne [System.PlatformID]::Win32NT) {
    throw 'Collector smoke tests require Windows PowerShell on Windows.'
}
if (($PSVersionTable.PSVersion.Major -lt 5) -or
    ($PSVersionTable.PSVersion.Major -eq 5 -and $PSVersionTable.PSVersion.Minor -lt 1)) {
    throw 'Collector smoke tests require Windows PowerShell 5.1 or later.'
}

$collector = Join-Path (Split-Path -Parent $PSScriptRoot) 'Collect-DuoViewRestartEvidence.ps1'
if (-not (Test-Path -LiteralPath $collector -PathType Leaf)) { throw 'Collector script was not found beside tests.' }

$tokens = $null
$parseErrors = $null
[void][System.Management.Automation.Language.Parser]::ParseFile($collector, [ref]$tokens, [ref]$parseErrors)
Assert-Smoke ($parseErrors.Count -eq 0) ("PowerShell parser found errors: $($parseErrors -join '; ')")

Add-Type -AssemblyName System.IO.Compression.FileSystem
$fixtureRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("DuoViewCollectorSmoke-$PID-" + [guid]::NewGuid().ToString('N'))
$oldAppData = $env:APPDATA
$oldLocalAppData = $env:LOCALAPPDATA
$zipPath = $null

try {
    $appDataRoot = Join-Path $fixtureRoot 'AppData'
    $localAppDataRoot = Join-Path $fixtureRoot 'LocalAppData'
    $savedRoot = Join-Path $localAppDataRoot 'Stalker2\Saved'
    $packageRoot = Join-Path $fixtureRoot 'Package'
    $evidenceRoot = Join-Path $fixtureRoot 'Evidence'
    $outputRoot = Join-Path $fixtureRoot 'Output'
    $executableStem = 'Stalker2-Win64-Shipping'
    $uevrRoot = Join-Path (Join-Path $appDataRoot 'UnrealVRMod') $executableStem
    $gameLogRoot = Join-Path $savedRoot 'Logs'
    $crashRoot = Join-Path (Join-Path $savedRoot 'Crashes') 'SmokeCrash'
    $configRoot = Join-Path (Join-Path $savedRoot 'Config') 'Windows'
    foreach ($directory in @($uevrRoot, $gameLogRoot, $crashRoot, $configRoot, $packageRoot, $evidenceRoot, $outputRoot,
            (Join-Path $savedRoot 'STEAM'))) {
        [void](New-Item -ItemType Directory -Path $directory -Force)
    }
    $env:APPDATA = $appDataRoot
    $env:LOCALAPPDATA = $localAppDataRoot

    [System.IO.File]::WriteAllText((Join-Path $uevrRoot 'settings.ini'), "api_key=smoke-secret-value`r`nmode=fixed`r`n")
    [System.IO.File]::WriteAllText((Join-Path $uevrRoot 'config.txt'), "render_method=stable_source_mask`r`n")
    [System.IO.File]::WriteAllText((Join-Path $uevrRoot 'notes.txt'), "private_note=must-not-be-collected`r`n")
    $telemetry = '[DuoViewRestart] copy_frame_counter=17 source_generation_observed=false projection_observed=false gaze_pose_observed=false mask_frame=17 requested_method=point effective_method=1 requested_control=stable_source_moving_mask_fixed observed_copy_path=stable_source_mask control_command_recorded=true mono_copy_command_recorded=false copy_api_returned_successfully=true copy_submission_accepted=true fallback_reason=none'
    $logText = ('old-record=bounded-tail-fixture' + "`r`n") * 180000 + $telemetry + "`r`n"
    [System.IO.File]::WriteAllText((Join-Path $uevrRoot 'log.txt'), $logText)
    [System.IO.File]::WriteAllText((Join-Path $gameLogRoot 'Stalker2.log'), "game log smoke fixture`r`n")
    [System.IO.File]::WriteAllText((Join-Path $crashRoot 'CrashContext.runtime-xml'), '<RuntimeCrashContext><Error>smoke</Error></RuntimeCrashContext>')
    [System.IO.File]::WriteAllText((Join-Path $configRoot 'GameUserSettings.ini'), "ResolutionSizeX=1920`r`n")
    [System.IO.File]::WriteAllText((Join-Path $savedRoot 'STEAM\do-not-collect.sav'), 'save fixture')
    [System.IO.File]::WriteAllText((Join-Path $packageRoot 'STATUS.md'), 'collector smoke fixture')
    [System.IO.File]::WriteAllText((Join-Path $packageRoot 'READ_FIRST.txt'), 'Build scope and package limitations')
    [System.IO.File]::WriteAllText((Join-Path $packageRoot 'source-snapshot-manifest.json'), '{"baseline_commit":"pinned"}')
    [System.IO.File]::WriteAllText((Join-Path $packageRoot 'Collect-DuoViewRestartEvidence.ps1'), '# collector fixture')
    [System.IO.File]::WriteAllText((Join-Path $packageRoot 'COLLECTOR_USAGE.md'), 'collector usage fixture')
    [System.IO.File]::WriteAllText((Join-Path $packageRoot 'unlisted-private.txt'), 'must not be collected')
    $hashManifestPath = Join-Path $packageRoot 'package-sha256.json'
    [System.IO.File]::WriteAllText($hashManifestPath, '[{"Path":"D3D12Core.dll","Hash":"0123456789abcdef"}]')

    $oversizedDump = Join-Path $crashRoot 'over-cap.dmp'
    $dumpStream = [System.IO.File]::Open($oversizedDump, [System.IO.FileMode]::CreateNew,
        [System.IO.FileAccess]::Write, [System.IO.FileShare]::None)
    try { $dumpStream.SetLength(21MB) } finally { $dumpStream.Dispose() }

    $zipPath = (& $collector -PackageRoot $packageRoot -OutputDirectory $outputRoot -IncludeDumps -RecentDays 30 |
        Select-Object -Last 1)
    Assert-Smoke (Test-Path -LiteralPath $zipPath -PathType Leaf) 'Collector did not produce a ZIP.'
    Assert-Smoke ((Get-Item -LiteralPath $zipPath).Length -lt 110MB) 'Collector ZIP exceeded the documented limit.'
    Assert-Smoke ($zipPath -match 'DuoViewRestart-evidence-\d{8}T\d{9}Z-p\d+-[a-f0-9]{8}\.zip$') 'ZIP name is missing timestamp/PID uniqueness.'

    $archive = [System.IO.Compression.ZipFile]::OpenRead($zipPath)
    try {
        $manifest = Read-ZipText $archive 'collection-manifest.json' | ConvertFrom-Json
        $summary = Read-ZipText $archive 'summary.txt'
        $entries = @($manifest.files)
        $uevrLog = $entries | Where-Object { $_.sourceLabel -eq 'source-verified UEVR Framework log.txt tail' } | Select-Object -First 1
        Assert-Smoke ($null -ne $uevrLog -and $uevrLog.status -eq 'truncated') 'Default UEVR logger tail was not found/truncated as expected.'
        Assert-Smoke ($manifest.roots.uevr.pathConventionSourceVerified -eq $true) 'Manifest did not mark the pinned UEVR logger convention source.'
        Assert-Smoke ($manifest.roots.gameSaved.candidateExists -eq $true) 'Manifest did not record the existing official Saved candidate.'
        Assert-Smoke ($manifest.diagnosticBoundary.passFailInferred -eq $false) 'Manifest inferred a control pass/fail result.'
        Assert-Smoke ($manifest.diagnosticBoundary.requestedMethodCounts.point -ge 1) 'Requested method log match was not counted.'
        Assert-Smoke ($manifest.diagnosticBoundary.fallbackReasonCounts.none -ge 1) 'Fallback reason log match was not counted.'
        Assert-Smoke ($manifest.caps.stagedEvidenceBytesUsed -le $manifest.caps.stagedEvidenceBytes) 'Staged evidence exceeded total byte cap.'
        Assert-Smoke ($manifest.caps.optionalDumpsBytesUsed -le $manifest.caps.optionalDumpsBytes) 'Optional dump evidence exceeded dump total cap.'
        $oversizedDumpRecord = $entries | Where-Object { $_.sourceLabel -eq 'opt-in crash dump; may contain sensitive process memory' } | Select-Object -First 1
        Assert-Smoke ($null -ne $oversizedDumpRecord -and
            $oversizedDumpRecord.status -eq 'excluded_size_limit' -and
            $oversizedDumpRecord.sourceBytes -eq (21MB) -and
            $oversizedDumpRecord.archivedBytes -eq 0) 'Oversized dump was not excluded at the 20 MiB per-file cap.'
        Assert-Smoke (($entries | Where-Object { $_.sourceLabel -eq 'package metadata: baseline.lock.json' -and $_.status -eq 'missing' }).Count -eq 1) 'Missing allowlisted package metadata was not recorded.'
        Assert-Smoke (($entries | Where-Object { $_.sourceLabel -eq 'package metadata: READ_FIRST.txt' -and $_.status -eq 'included' }).Count -eq 1) 'Workflow READ_FIRST package note was not included.'
        Assert-Smoke (($entries | Where-Object { $_.sourceLabel -eq 'package metadata: source-snapshot-manifest.json' -and $_.status -eq 'included' }).Count -eq 1) 'Source snapshot manifest was not included.'
        Assert-Smoke (($entries | Where-Object { $_.sourceLabel -eq 'package metadata: Collect-DuoViewRestartEvidence.ps1' -and $_.status -eq 'included' }).Count -eq 1) 'Collector script was not included.'
        Assert-Smoke (($entries | Where-Object { $_.sourceLabel -eq 'package metadata: COLLECTOR_USAGE.md' -and $_.status -eq 'included' }).Count -eq 1) 'Collector usage guide was not included.'
        Assert-Smoke (($entries | Where-Object { $_.sourceLabel -eq 'package provenance hash manifest: package-sha256.json' -and $_.status -eq 'included' }).Count -eq 1) 'Package hash payload was not discovered.'
        Assert-Smoke (($entries | Where-Object { $_.sourceLabel -eq 'recent STALKER 2 runtime XML or INI' -and $_.status -eq 'included' }).Count -ge 1) 'Runtime XML was not included.'
        Assert-Smoke ($summary.Contains('not a control pass/fail result')) 'Readable summary omitted the evidence boundary.'
        Assert-Smoke ($null -eq ($archive.Entries | Where-Object { $_.FullName -match 'do-not-collect\.sav$' })) 'Saved game content was collected.'
        Assert-Smoke ($null -eq ($archive.Entries | Where-Object { $_.FullName -match 'unlisted-private\.txt$' })) 'An unlisted package file was collected.'

        $settingsEntry = $archive.Entries | Where-Object { $_.FullName -match '^settings/.*settings\.ini$' } | Select-Object -First 1
        Assert-Smoke ($null -ne $settingsEntry) 'Allowlisted UEVR settings were not included.'
        $settingsStream = $settingsEntry.Open()
        $settingsReader = [System.IO.StreamReader]::new($settingsStream)
        try { $settingsText = $settingsReader.ReadToEnd() } finally { $settingsReader.Dispose(); $settingsStream.Dispose() }
        Assert-Smoke ($settingsText.Contains('[REDACTED]')) 'Settings secret pattern was not redacted.'
        Assert-Smoke (-not $settingsText.Contains('smoke-secret-value')) 'Sensitive fixture value leaked into the ZIP.'
        Assert-Smoke (($archive.Entries | Where-Object { $_.FullName -match '^settings/.*config\.txt$' }).Count -eq 1) 'Pinned exact config.txt was not included.'
        Assert-Smoke (($archive.Entries | Where-Object { $_.FullName -match 'notes\.txt$' }).Count -eq 0) 'An arbitrary profile .txt file was collected.'
    } finally {
        $archive.Dispose()
    }

    $explicitTextZip = (& $collector -PackageRoot $packageRoot -SettingsPath (Join-Path $uevrRoot 'notes.txt') -OutputDirectory $outputRoot -RecentDays 30 |
        Select-Object -Last 1)
    $explicitTextArchive = [System.IO.Compression.ZipFile]::OpenRead($explicitTextZip)
    try {
        $explicitTextManifest = Read-ZipText $explicitTextArchive 'collection-manifest.json' | ConvertFrom-Json
        Assert-Smoke (($explicitTextManifest.files | Where-Object { $_.sourceLabel -eq 'settings candidate' -and $_.status -eq 'excluded_type' }).Count -eq 1) 'An explicitly supplied arbitrary .txt file was not rejected by the exact-name rule.'
        Assert-Smoke (($explicitTextArchive.Entries | Where-Object { $_.FullName -match 'notes\.txt$' }).Count -eq 0) 'An explicitly supplied arbitrary .txt file was archived.'
    } finally {
        $explicitTextArchive.Dispose()
    }

    Write-Output "PASS collector parser and bounded fixture smoke ($($PSVersionTable.PSVersion))"
} finally {
    $env:APPDATA = $oldAppData
    $env:LOCALAPPDATA = $oldLocalAppData
    if (Test-Path -LiteralPath $fixtureRoot) {
        Remove-Item -LiteralPath $fixtureRoot -Recurse -Force -ErrorAction SilentlyContinue
    }
}
