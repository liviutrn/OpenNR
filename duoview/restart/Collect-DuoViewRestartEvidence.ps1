<#
.SYNOPSIS
Collects a bounded, local-only DuoView restart evidence ZIP.

.DESCRIPTION
Run separately from the game/injector, or use -WatchPid to wait for a process
to exit before collecting. Paths are inspected only in the documented,
allowlisted locations; this script does not scan a user profile recursively,
read process environment variables, or upload data.
#>
[CmdletBinding()]
param(
    [string]$UevrRoot,
    [string]$GameSavedRoot,
    [string]$PackageRoot,
    [string]$UevrLogPath,
    [string[]]$SettingsPath = @(),
    [string]$DiagnosticPath,
    [switch]$IncludeDumps,
    [int]$WatchPid = 0,
    [ValidateRange(1, 21600)] [int]$WatchTimeoutSeconds = 3600,
    [string]$OutputDirectory,
    [ValidateRange(1, 365)] [int]$RecentDays = 30
)

$ErrorActionPreference = 'Stop'
$script:MaxTotalBytes = 100MB
$script:MaxDumpTotalBytes = 32MB
$script:DumpBytes = 0L
$script:TotalBytes = 0L
$script:ArchiveCounter = 0
$script:Records = New-Object System.Collections.ArrayList
$script:ParsedLogText = New-Object System.Text.StringBuilder
$script:StageRoot = $null
$script:Utf8NoBom = [System.Text.UTF8Encoding]::new($false)

function Add-Record {
    param([hashtable]$Value)
    [void]$script:Records.Add([pscustomobject]$Value)
}

function Get-HashHex {
    param([byte[]]$Bytes)
    $sha = [System.Security.Cryptography.SHA256]::Create()
    try {
        return ([BitConverter]::ToString($sha.ComputeHash($Bytes))).Replace('-', '').ToLowerInvariant()
    } finally {
        $sha.Dispose()
    }
}

function Test-LocalPath {
    param([string]$Path)
    if ([string]::IsNullOrWhiteSpace($Path)) { return $false }
    try {
        $full = [System.IO.Path]::GetFullPath($Path)
        if ($full.StartsWith('\\', [System.StringComparison]::OrdinalIgnoreCase)) { return $false }
        $root = [System.IO.Path]::GetPathRoot($full)
        if ([string]::IsNullOrWhiteSpace($root)) { return $false }
        $drive = [System.IO.DriveInfo]::new($root)
        return ($drive.DriveType -ne [System.IO.DriveType]::Network)
    } catch {
        return $false
    }
}

function Test-PlainDirectory {
    param([string]$Path)
    if (-not (Test-LocalPath $Path) -or -not (Test-Path -LiteralPath $Path -PathType Container)) { return $false }
    try {
        $directory = Get-Item -LiteralPath $Path -Force
        return (($directory.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -eq 0)
    } catch {
        return $false
    }
}

function Get-SafeName {
    param([string]$Name)
    $safe = [regex]::Replace($Name, '[<>:"/\\|?*\x00-\x1f]', '_').Trim(' ', '.')
    if ([string]::IsNullOrWhiteSpace($safe)) { return 'unnamed.bin' }
    return $safe
}

function Protect-Text {
    param([string]$Text)
    $count = 0
    $patterns = @(
        '(?im)(\b(?:password|passwd|token|api[_-]?key|client[_-]?secret|authorization|cookie)\b\s*[:=]\s*)("[^"\r\n]*"|''[^''\r\n]*''|[^\s,;]+)',
        '(?im)(\bBearer\s+)[A-Za-z0-9._~+/-]+=*',
        '(?i)(https?://)[^/@\s:]+:[^/@\s]+@',
        '(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b'
    )
    $replacements = @('$1[REDACTED]', '$1[REDACTED]', '$1[REDACTED]@', '[EMAIL]')
    for ($i = 0; $i -lt $patterns.Count; $i++) {
        $count += [regex]::Matches($Text, $patterns[$i]).Count
        $Text = [regex]::Replace($Text, $patterns[$i], $replacements[$i])
    }
    if (-not [string]::IsNullOrWhiteSpace($env:USERPROFILE)) {
        $profilePattern = [regex]::Escape($env:USERPROFILE)
        $count += [regex]::Matches($Text, $profilePattern, [System.Text.RegularExpressions.RegexOptions]::IgnoreCase).Count
        $Text = [regex]::Replace($Text, $profilePattern, '[USERPROFILE]', [System.Text.RegularExpressions.RegexOptions]::IgnoreCase)
    }
    return [pscustomobject]@{ Text = $Text; Redactions = $count }
}

function New-ArchiveFilePath {
    param([string]$Category, [string]$Leaf)
    $script:ArchiveCounter++
    $safe = Get-SafeName $Leaf
    $relative = Join-Path $Category ('{0:D3}-{1}' -f $script:ArchiveCounter, $safe)
    $parent = Join-Path $script:StageRoot $Category
    if (-not (Test-Path -LiteralPath $parent -PathType Container)) {
        [void](New-Item -ItemType Directory -Path $parent -Force)
    }
    return [pscustomobject]@{
        Relative = $relative.Replace('\', '/')
        Full = Join-Path $script:StageRoot $relative
    }
}

function Save-EvidenceFile {
    param(
        [string]$SourcePath,
        [string]$Label,
        [string]$Category,
        [ValidateSet('Tail', 'Text', 'Binary')] [string]$Mode,
        [long]$PerFileLimit,
        [switch]$Redact,
        [switch]$ParseTelemetry,
        [switch]$IsDump
    )

    $recordBase = @{
        sourceLabel = $Label
        archivePath = $null
        status = 'failed'
        reason = $null
        sourceBytes = $null
        archivedBytes = 0
        archivedSha256 = $null
        sourceSha256 = $null
        redactions = 0
        truncated = $false
        modifiedUtc = $null
        capturedRange = $null
    }
    try {
        if (-not (Test-LocalPath $SourcePath)) {
            $recordBase.status = 'excluded_path'
            $recordBase.reason = 'non-local or invalid path'
            Add-Record $recordBase
            return
        }
        $full = [System.IO.Path]::GetFullPath($SourcePath)
        if (-not (Test-Path -LiteralPath $full -PathType Leaf)) {
            $recordBase.status = 'missing'
            $recordBase.reason = 'file not found'
            Add-Record $recordBase
            return
        }
        $info = Get-Item -LiteralPath $full -Force
        if (($info.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
            $recordBase.status = 'excluded_reparse_point'
            $recordBase.reason = 'link target is not followed'
            Add-Record $recordBase
            return
        }
        $length = [long]$info.Length
        $recordBase.sourceBytes = $length
        $recordBase.modifiedUtc = $info.LastWriteTimeUtc.ToString('o')

        $remaining = [long]($script:MaxTotalBytes - $script:TotalBytes)
        if ($IsDump) {
            $remaining = [long][Math]::Min($remaining, ($script:MaxDumpTotalBytes - $script:DumpBytes))
        }
        if ($remaining -le 0) {
            $recordBase.status = 'excluded_total_cap'
            $recordBase.reason = 'collection byte cap reached'
            Add-Record $recordBase
            return
        }

        [byte[]]$outputBytes = @()
        $sourceHash = $null
        $redactionCount = 0
        $tailRange = $null
        $truncated = $false
        $telemetryText = $null

        if ($Mode -eq 'Binary') {
            if ($length -gt $PerFileLimit -or $length -gt $remaining) {
                $recordBase.status = 'excluded_size_limit'
                $recordBase.reason = 'dump exceeds per-file or remaining total cap; dumps are not partially copied'
                Add-Record $recordBase
                return
            }
            $outputBytes = [System.IO.File]::ReadAllBytes($full)
            $sourceHash = Get-HashHex $outputBytes
        } elseif ($Mode -eq 'Text') {
            if ($length -gt $PerFileLimit) {
                $recordBase.status = 'excluded_size_limit'
                $recordBase.reason = 'full text file exceeds per-file cap'
                Add-Record $recordBase
                return
            }
            $rawBytes = [System.IO.File]::ReadAllBytes($full)
            $sourceHash = Get-HashHex $rawBytes
            $text = [System.IO.File]::ReadAllText($full)
            if ($Redact) {
                $protected = Protect-Text $text
                $text = $protected.Text
                $redactionCount = $protected.Redactions
            }
            $outputBytes = $script:Utf8NoBom.GetBytes($text)
            if ($outputBytes.LongLength -gt $remaining) {
                $recordBase.status = 'excluded_total_cap'
                $recordBase.reason = 'file does not fit remaining total cap'
                Add-Record $recordBase
                return
            }
        } else {
            $captureLimit = [long][Math]::Min($PerFileLimit, $remaining)
            if ($captureLimit -le 0) {
                $recordBase.status = 'excluded_total_cap'
                $recordBase.reason = 'no remaining bytes for tail'
                Add-Record $recordBase
                return
            }
            $take = [long][Math]::Min($length, $captureLimit)
            $stream = $null
            try {
                $share = [System.IO.FileShare]::ReadWrite -bor [System.IO.FileShare]::Delete
                $stream = [System.IO.File]::Open($full, [System.IO.FileMode]::Open, [System.IO.FileAccess]::Read, $share)
                [void]$stream.Seek(($length - $take), [System.IO.SeekOrigin]::Begin)
                $buffer = [byte[]]::new([int]$take)
                $read = 0
                while ($read -lt $buffer.Length) {
                    $n = $stream.Read($buffer, $read, ($buffer.Length - $read))
                    if ($n -le 0) { break }
                    $read += $n
                }
                if ($read -ne $buffer.Length) {
                    [byte[]]$shortBuffer = [byte[]]::new($read)
                    [Array]::Copy($buffer, $shortBuffer, $read)
                    $buffer = $shortBuffer
                }
            } finally {
                if ($null -ne $stream) { $stream.Dispose() }
            }
            $text = [System.Text.Encoding]::UTF8.GetString($buffer)
            $startByte = $length - $buffer.Length
            if ($startByte -gt 0) {
                $newline = $text.IndexOf("`n")
                if ($newline -ge 0) {
                    $droppedPrefix = $text.Substring(0, $newline + 1)
                    $startByte += [System.Text.Encoding]::UTF8.GetByteCount($droppedPrefix)
                    $text = $text.Substring($newline + 1)
                } else {
                    $text = "[collector: no complete line boundary in captured tail]`r`n" + $text
                }
                $truncated = $true
                $text = "[collector: earlier file bytes omitted; tail starts near byte $startByte of $length]`r`n" + $text
            }
            if ($Redact) {
                $protected = Protect-Text $text
                $text = $protected.Text
                $redactionCount = $protected.Redactions
            }
            $outputBytes = $script:Utf8NoBom.GetBytes($text)
            $tailRange = "byte $startByte through $length (UTF-8 tail; line boundary adjusted)"
            $telemetryText = $text
        }

        if ($outputBytes.LongLength -gt $remaining) {
            $recordBase.status = 'excluded_total_cap'
            $recordBase.reason = 'redacted output does not fit remaining total cap'
            Add-Record $recordBase
            return
        }
        $archive = New-ArchiveFilePath $Category ([System.IO.Path]::GetFileName($full))
        [System.IO.File]::WriteAllBytes($archive.Full, $outputBytes)
        $script:TotalBytes += $outputBytes.LongLength
        if ($IsDump) { $script:DumpBytes += $outputBytes.LongLength }
        $recordBase.archivePath = $archive.Relative
        $recordBase.status = 'included'
        if ($truncated) { $recordBase.status = 'truncated' }
        $recordBase.reason = $(if ($truncated) { 'bounded recent tail captured' } else { 'allowlisted file copied' })
        $recordBase.archivedBytes = $outputBytes.LongLength
        $recordBase.archivedSha256 = Get-HashHex $outputBytes
        $recordBase.sourceSha256 = $sourceHash
        $recordBase.redactions = $redactionCount
        $recordBase.truncated = $truncated
        $recordBase.capturedRange = $tailRange
        Add-Record $recordBase
        if ($ParseTelemetry -and $null -ne $telemetryText) {
            [void]$script:ParsedLogText.AppendLine($telemetryText)
        }
    } catch {
        $recordBase.status = 'error'
        $recordBase.reason = 'I/O error: ' + $_.Exception.GetType().Name
        Add-Record $recordBase
    }
}

function Get-BoundedRecentFiles {
    param(
        [string[]]$Directories,
        [string[]]$Extensions,
        [int]$Maximum,
        [datetime]$CutoffUtc,
        [switch]$IncludeOneChildLevel,
        [switch]$IgnoreAge
    )
    $found = New-Object System.Collections.ArrayList
    $staleCount = 0
    foreach ($directory in $Directories) {
        if (-not (Test-PlainDirectory $directory)) { continue }
        $scanDirectories = New-Object System.Collections.ArrayList
        [void]$scanDirectories.Add($directory)
        if ($IncludeOneChildLevel) {
            try {
                $children = @(Get-ChildItem -LiteralPath $directory -Directory -Force -ErrorAction Stop | Select-Object -First 21)
                foreach ($child in $children | Select-Object -First 20) {
                    if (($child.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -eq 0) { [void]$scanDirectories.Add($child.FullName) }
                }
                if ($children.Count -gt 20) {
                    Add-Record @{ sourceLabel = 'candidate-directories'; archivePath = $null; status = 'truncated'; reason = 'immediate child directory scan capped at 20'; sourceBytes = $null; archivedBytes = 0; archivedSha256 = $null; sourceSha256 = $null; redactions = 0; truncated = $true; modifiedUtc = $null; capturedRange = $null }
                }
            } catch {
                Add-Record @{ sourceLabel = 'candidate-directories'; archivePath = $null; status = 'error'; reason = 'allowlisted immediate child listing failed: ' + $_.Exception.GetType().Name; sourceBytes = $null; archivedBytes = 0; archivedSha256 = $null; sourceSha256 = $null; redactions = 0; truncated = $false; modifiedUtc = $null; capturedRange = $null }
            }
        }
        foreach ($scanDirectory in $scanDirectories) {
            try {
                $files = @(Get-ChildItem -LiteralPath $scanDirectory -File -Force -ErrorAction Stop | Select-Object -First 251)
                if ($files.Count -gt 250) {
                    Add-Record @{ sourceLabel = 'candidate-files'; archivePath = $null; status = 'truncated'; reason = 'file enumeration capped at 250 in an allowlisted directory'; sourceBytes = $null; archivedBytes = 0; archivedSha256 = $null; sourceSha256 = $null; redactions = 0; truncated = $true; modifiedUtc = $null; capturedRange = $null }
                }
                foreach ($file in $files | Select-Object -First 250) {
                    if (($file.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) { continue }
                    if ($Extensions -notcontains $file.Extension.ToLowerInvariant()) { continue }
                    if (-not $IgnoreAge -and $file.LastWriteTimeUtc -lt $CutoffUtc) { $staleCount++; continue }
                    [void]$found.Add($file)
                }
            } catch {
                Add-Record @{ sourceLabel = 'candidate-files'; archivePath = $null; status = 'error'; reason = 'allowlisted directory listing failed: ' + $_.Exception.GetType().Name; sourceBytes = $null; archivedBytes = 0; archivedSha256 = $null; sourceSha256 = $null; redactions = 0; truncated = $false; modifiedUtc = $null; capturedRange = $null }
            }
        }
    }
    if ($staleCount -gt 0) {
        Add-Record @{ sourceLabel = 'stale candidates'; archivePath = $null; status = 'excluded_stale'; reason = "$staleCount allowlisted file(s) were older than the requested recent-file window"; sourceBytes = $null; archivedBytes = 0; archivedSha256 = $null; sourceSha256 = $null; redactions = 0; truncated = $false; modifiedUtc = $null; capturedRange = $null }
    }
    $ordered = @($found | Sort-Object -Property LastWriteTimeUtc -Descending)
    if ($ordered.Count -gt $Maximum) {
        Add-Record @{ sourceLabel = 'candidate-files'; archivePath = $null; status = 'excluded_candidate_limit'; reason = "only the $Maximum most recent matching files are collected"; sourceBytes = $null; archivedBytes = 0; archivedSha256 = $null; sourceSha256 = $null; redactions = 0; truncated = $false; modifiedUtc = $null; capturedRange = $null }
    }
    if ($ordered.Count -gt $Maximum) { return @($ordered | Select-Object -First $Maximum) }
    return $ordered
}

function Get-ValueCounts {
    param([string]$Field)
    $pattern = '\b' + [regex]::Escape($Field) + '=([A-Za-z0-9_.-]+)'
    $matches = [regex]::Matches($script:ParsedLogText.ToString(), $pattern)
    $counts = @{}
    foreach ($match in $matches) {
        $value = $match.Groups[1].Value
        if (-not $counts.ContainsKey($value)) { $counts[$value] = 0 }
        $counts[$value]++
    }
    return $counts
}

function Format-ValueCounts {
    param([hashtable]$Counts)
    if ($Counts.Count -eq 0) { return 'none observed' }
    $parts = New-Object System.Collections.ArrayList
    foreach ($key in ($Counts.Keys | Sort-Object)) { [void]$parts.Add("$key=$($Counts[$key])") }
    return ($parts -join ', ')
}

# Optional watch is a read-only wait; the target process is never stopped.
$watchStatus = 'not_requested'
if ($WatchPid -gt 0) {
    $watchStatus = 'waiting'
    $watchStarted = [datetime]::UtcNow
    while (([datetime]::UtcNow - $watchStarted).TotalSeconds -lt $WatchTimeoutSeconds) {
        try {
            $null = Get-Process -Id $WatchPid -ErrorAction Stop
        } catch {
            $watchStatus = 'process_exited_or_unavailable'
            break
        }
        Start-Sleep -Milliseconds 900
    }
    if ($watchStatus -eq 'waiting') { $watchStatus = 'timeout_process_may_still_run' }
}

if ([System.Environment]::OSVersion.Platform -ne [System.PlatformID]::Win32NT) {
    throw 'This collector is intended for Windows PowerShell 5.1 on Windows.'
}

$uevrRootMode = 'explicit'
if ([string]::IsNullOrWhiteSpace($UevrRoot)) {
    $uevrRootMode = 'default_candidate_unverified'
    if (-not [string]::IsNullOrWhiteSpace($env:LOCALAPPDATA)) { $UevrRoot = Join-Path $env:LOCALAPPDATA 'UEVR' }
}
$packageRootMode = 'explicit'
if ([string]::IsNullOrWhiteSpace($PackageRoot)) {
    $packageRootMode = 'script_directory_default'
    $PackageRoot = $PSScriptRoot
}
$gameRootMode = $(if ([string]::IsNullOrWhiteSpace($GameSavedRoot)) { 'not_supplied_no_verified_default' } else { 'explicit' })
if ([string]::IsNullOrWhiteSpace($OutputDirectory)) { $OutputDirectory = (Get-Location).Path }
if (-not (Test-LocalPath $OutputDirectory)) { throw 'OutputDirectory must be a local filesystem path.' }
if (-not (Test-Path -LiteralPath $OutputDirectory -PathType Container)) { [void](New-Item -ItemType Directory -Path $OutputDirectory -Force) }
$OutputDirectory = [System.IO.Path]::GetFullPath($OutputDirectory)
if (-not (Test-PlainDirectory $OutputDirectory)) { throw 'OutputDirectory must be a local non-reparse directory.' }

$stamp = [datetime]::UtcNow.ToString('yyyyMMddTHHmmssfffZ')
$suffix = [guid]::NewGuid().ToString('N').Substring(0, 8)
$zipLeaf = "DuoViewRestart-evidence-$stamp-p$PID-$suffix.zip"
$zipPath = Join-Path $OutputDirectory $zipLeaf
$tempZipPath = Join-Path $OutputDirectory (".$zipLeaf.tmp.zip")
$script:StageRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("DVR-$stamp-$suffix")
[void](New-Item -ItemType Directory -Path $script:StageRoot -Force)

try {
    $cutoffUtc = [datetime]::UtcNow.AddDays(-$RecentDays)

    # UEVR log discovery is intentionally shallow and limited to this candidate root and one named child.
    if (-not [string]::IsNullOrWhiteSpace($UevrLogPath)) {
        Save-EvidenceFile -SourcePath $UevrLogPath -Label 'explicit UEVR log' -Category 'uevr-logs' -Mode Tail -PerFileLimit 4MB -Redact -ParseTelemetry
    } elseif (-not [string]::IsNullOrWhiteSpace($UevrRoot) -and (Test-PlainDirectory $UevrRoot)) {
        $uevrLogDirs = @($UevrRoot, (Join-Path $UevrRoot 'logs'))
        $uevrLogs = @(Get-BoundedRecentFiles -Directories $uevrLogDirs -Extensions @('.log', '.txt') -Maximum 5 -CutoffUtc $cutoffUtc)
        if ($uevrLogs.Count -eq 0) {
            Add-Record @{ sourceLabel = 'UEVR logs'; archivePath = $null; status = 'missing'; reason = 'no recent top-level log found in candidate root or its immediate logs child'; sourceBytes = $null; archivedBytes = 0; archivedSha256 = $null; sourceSha256 = $null; redactions = 0; truncated = $false; modifiedUtc = $null; capturedRange = $null }
        }
        foreach ($file in $uevrLogs) {
            Save-EvidenceFile -SourcePath $file.FullName -Label 'recent UEVR log tail' -Category 'uevr-logs' -Mode Tail -PerFileLimit 4MB -Redact -ParseTelemetry
        }
    } else {
        Add-Record @{ sourceLabel = 'UEVR logs'; archivePath = $null; status = 'missing_root'; reason = 'default candidate is %LOCALAPPDATA%\UEVR; no verified runtime log location is established'; sourceBytes = $null; archivedBytes = 0; archivedSha256 = $null; sourceSha256 = $null; redactions = 0; truncated = $false; modifiedUtc = $null; capturedRange = $null }
    }

    if (-not [string]::IsNullOrWhiteSpace($DiagnosticPath)) {
        Save-EvidenceFile -SourcePath $DiagnosticPath -Label 'explicit diagnostic file; output type not assumed' -Category 'diagnostic' -Mode Tail -PerFileLimit 4MB -Redact -ParseTelemetry
    }

    # Exact settings names only; explicit paths are still restricted to text-like formats and local files.
    $settings = New-Object System.Collections.ArrayList
    if ($SettingsPath.Count -gt 0) {
        foreach ($path in $SettingsPath) { [void]$settings.Add($path) }
    } elseif (-not [string]::IsNullOrWhiteSpace($UevrRoot) -and (Test-PlainDirectory $UevrRoot)) {
        foreach ($name in @('settings.ini', 'settings.json', 'config.ini', 'config.json')) {
            $candidate = Join-Path $UevrRoot $name
            if (Test-Path -LiteralPath $candidate -PathType Leaf) { [void]$settings.Add($candidate) }
        }
    }
    if ($settings.Count -eq 0) {
        Add-Record @{ sourceLabel = 'UEVR settings'; archivePath = $null; status = 'missing'; reason = 'no explicit settings path or exact-name settings candidate found'; sourceBytes = $null; archivedBytes = 0; archivedSha256 = $null; sourceSha256 = $null; redactions = 0; truncated = $false; modifiedUtc = $null; capturedRange = $null }
    }
    foreach ($path in $settings | Select-Object -First 8) {
        $extension = [System.IO.Path]::GetExtension($path).ToLowerInvariant()
        if (@('.ini', '.json', '.cfg', '.xml', '.toml') -notcontains $extension) {
            Add-Record @{ sourceLabel = 'settings candidate'; archivePath = $null; status = 'excluded_type'; reason = 'settings allowlist accepts only ini/json/cfg/xml/toml text files'; sourceBytes = $null; archivedBytes = 0; archivedSha256 = $null; sourceSha256 = $null; redactions = 0; truncated = $false; modifiedUtc = $null; capturedRange = $null }
            continue
        }
        Save-EvidenceFile -SourcePath $path -Label 'allowlisted UEVR settings file' -Category 'settings' -Mode Text -PerFileLimit 512KB -Redact
    }
    if ($settings.Count -gt 8) {
        Add-Record @{ sourceLabel = 'settings candidates'; archivePath = $null; status = 'excluded_candidate_limit'; reason = 'settings collection is capped at 8 files'; sourceBytes = $null; archivedBytes = 0; archivedSha256 = $null; sourceSha256 = $null; redactions = 0; truncated = $false; modifiedUtc = $null; capturedRange = $null }
    }

    # The caller supplies the game's Saved directory. No install/profile search is attempted.
    if ([string]::IsNullOrWhiteSpace($GameSavedRoot) -or -not (Test-PlainDirectory $GameSavedRoot)) {
        Add-Record @{ sourceLabel = 'STALKER 2 Saved root'; archivePath = $null; status = 'missing_root'; reason = 'pass -GameSavedRoot with the game Saved directory; no verified default is established'; sourceBytes = $null; archivedBytes = 0; archivedSha256 = $null; sourceSha256 = $null; redactions = 0; truncated = $false; modifiedUtc = $null; capturedRange = $null }
    } else {
        $gameLogDirs = @((Join-Path $GameSavedRoot 'Logs'), (Join-Path $GameSavedRoot 'Crashes'))
        $gameLogs = @(Get-BoundedRecentFiles -Directories $gameLogDirs -Extensions @('.log', '.xml', '.runtime-xml', '.ini') -Maximum 12 -CutoffUtc $cutoffUtc -IncludeOneChildLevel)
        if ($gameLogs.Count -eq 0) {
            Add-Record @{ sourceLabel = 'STALKER 2 logs/crash metadata'; archivePath = $null; status = 'missing'; reason = 'no recent log/runtime-xml/xml/ini in Saved\Logs, Saved\Crashes, or one immediate crash subdirectory'; sourceBytes = $null; archivedBytes = 0; archivedSha256 = $null; sourceSha256 = $null; redactions = 0; truncated = $false; modifiedUtc = $null; capturedRange = $null }
        }
        foreach ($file in $gameLogs) {
            if ($file.Extension -eq '.log') {
                Save-EvidenceFile -SourcePath $file.FullName -Label 'recent STALKER 2 log tail' -Category 'game-logs' -Mode Tail -PerFileLimit 2MB -Redact
            } else {
                Save-EvidenceFile -SourcePath $file.FullName -Label 'recent STALKER 2 runtime XML or INI' -Category 'game-metadata' -Mode Text -PerFileLimit 1MB -Redact
            }
        }
        $configDirs = @((Join-Path $GameSavedRoot 'Config\Windows'), (Join-Path $GameSavedRoot 'Config\WindowsNoEditor'), (Join-Path $GameSavedRoot 'Config\Win64'))
        $gameConfig = @(Get-BoundedRecentFiles -Directories $configDirs -Extensions @('.ini', '.xml') -Maximum 8 -CutoffUtc $cutoffUtc)
        foreach ($file in $gameConfig) {
            Save-EvidenceFile -SourcePath $file.FullName -Label 'recent STALKER 2 config allowlist' -Category 'game-metadata' -Mode Text -PerFileLimit 1MB -Redact
        }
        if ($gameConfig.Count -eq 0) {
            Add-Record @{ sourceLabel = 'STALKER 2 config'; archivePath = $null; status = 'missing'; reason = 'no recent ini/xml in the three allowlisted Saved\Config directories'; sourceBytes = $null; archivedBytes = 0; archivedSha256 = $null; sourceSha256 = $null; redactions = 0; truncated = $false; modifiedUtc = $null; capturedRange = $null }
        }
        if ($IncludeDumps) {
            $dumps = @(Get-BoundedRecentFiles -Directories @((Join-Path $GameSavedRoot 'Crashes')) -Extensions @('.dmp', '.mdmp', '.dump') -Maximum 3 -CutoffUtc $cutoffUtc -IncludeOneChildLevel)
            if ($dumps.Count -eq 0) {
                Add-Record @{ sourceLabel = 'optional crash dumps'; archivePath = $null; status = 'missing'; reason = 'no recent dump in Saved\Crashes or one immediate child directory'; sourceBytes = $null; archivedBytes = 0; archivedSha256 = $null; sourceSha256 = $null; redactions = 0; truncated = $false; modifiedUtc = $null; capturedRange = $null }
            }
            foreach ($dump in $dumps) {
                Save-EvidenceFile -SourcePath $dump.FullName -Label 'opt-in crash dump; may contain sensitive process memory' -Category 'optional-dumps' -Mode Binary -PerFileLimit 20MB -IsDump
            }
        } else {
            Add-Record @{ sourceLabel = 'optional crash dumps'; archivePath = $null; status = 'excluded_by_default'; reason = 'use -IncludeDumps to opt in; dump files can contain sensitive process memory'; sourceBytes = $null; archivedBytes = 0; archivedSha256 = $null; sourceSha256 = $null; redactions = 0; truncated = $false; modifiedUtc = $null; capturedRange = $null }
        }
    }

    # Exact package file allowlist; absent files are recorded rather than treated as an error.
    $packageFiles = @('baseline.lock.json', 'exact-baseline-source.json', 'backend-patch-manifest.json', 'STATUS.md', 'EXPERIMENTS.md', 'README.md', 'source-snapshot-manifest.json')
    if (-not [string]::IsNullOrWhiteSpace($PackageRoot) -and (Test-PlainDirectory $PackageRoot)) {
        foreach ($name in $packageFiles) {
            $path = Join-Path $PackageRoot $name
            if (Test-Path -LiteralPath $path -PathType Leaf) {
                Save-EvidenceFile -SourcePath $path -Label ("package metadata: $name") -Category 'package-metadata' -Mode Text -PerFileLimit 2MB -Redact
            } else {
                Add-Record @{ sourceLabel = ("package metadata: $name"); archivePath = $null; status = 'missing'; reason = 'allowlisted package file not present at PackageRoot'; sourceBytes = $null; archivedBytes = 0; archivedSha256 = $null; sourceSha256 = $null; redactions = 0; truncated = $false; modifiedUtc = $null; capturedRange = $null }
            }
        }
    } else {
        Add-Record @{ sourceLabel = 'package metadata'; archivePath = $null; status = 'missing_root'; reason = 'PackageRoot is missing or non-local'; sourceBytes = $null; archivedBytes = 0; archivedSha256 = $null; sourceSha256 = $null; redactions = 0; truncated = $false; modifiedUtc = $null; capturedRange = $null }
    }

    $parsed = $script:ParsedLogText.ToString()
    $recordCount = [regex]::Matches($parsed, '\[DuoViewRestart\]').Count
    $requestedMethod = Get-ValueCounts 'requested_method'
    $requestedControl = Get-ValueCounts 'requested_control'
    $effectiveMethod = Get-ValueCounts 'effective_method'
    $observedPath = Get-ValueCounts 'observed_copy_path'
    $fallbackReason = Get-ValueCounts 'fallback_reason'
    $submissionAccepted = Get-ValueCounts 'copy_submission_accepted'
    $projectionObserved = Get-ValueCounts 'projection_observed'
    $gazeObserved = Get-ValueCounts 'gaze_pose_observed'
    $sourceGenerationObserved = Get-ValueCounts 'source_generation_observed'
    $summaryLines = @(
        'DuoView restart evidence collection',
        "Collected UTC: $([datetime]::UtcNow.ToString('o'))",
        "Watch status: $watchStatus (timeout is bounded; the target process is never terminated)",
        "UEVR root selection: $uevrRootMode; the default candidate is %LOCALAPPDATA%\UEVR and is not a verified runtime log location.",
        "Game Saved root selection: $gameRootMode; no game path was searched when this was not supplied.",
        "Recent-file window: $RecentDays days. Staged evidence cap: 100 MiB; optional dump cap: 20 MiB per file and 32 MiB total.",
        '',
        "[DuoViewRestart] producer-copy summary matches: $recordCount",
        "requested_method: $(Format-ValueCounts $requestedMethod)",
        "requested_control: $(Format-ValueCounts $requestedControl)",
        "effective_method: $(Format-ValueCounts $effectiveMethod)",
        "observed_copy_path: $(Format-ValueCounts $observedPath)",
        "fallback_reason: $(Format-ValueCounts $fallbackReason)",
        "copy_submission_accepted: $(Format-ValueCounts $submissionAccepted)",
        "projection_observed: $(Format-ValueCounts $projectionObserved)",
        "gaze_pose_observed: $(Format-ValueCounts $gazeObserved)",
        "source_generation_observed: $(Format-ValueCounts $sourceGenerationObserved)",
        '',
        'Boundary: these are bounded log-field matches at the producer copy boundary, not a control pass/fail result.',
        'Engine source-generation relation: unavailable/unproven. xrEndFrame acceptance: unavailable.',
        'Headset presentation and PSVR2 connection/tracking: unavailable from these files.',
        'Redactions are pattern-based and do not guarantee that every sensitive value is removed.'
    )
    $summary = $summaryLines -join "`r`n"
    [System.IO.File]::WriteAllText((Join-Path $script:StageRoot 'summary.txt'), $summary, $script:Utf8NoBom)

    $rootSummary = [ordered]@{
        uevr = [ordered]@{ selection = $uevrRootMode; candidateLeaf = $(if ($UevrRoot) { [System.IO.Path]::GetFileName($UevrRoot.TrimEnd('\')) } else { $null }); verifiedRuntimeLocation = $false }
        gameSaved = [ordered]@{ selection = $gameRootMode; candidateLeaf = $(if ($GameSavedRoot) { [System.IO.Path]::GetFileName($GameSavedRoot.TrimEnd('\')) } else { $null }); verifiedDefault = $false }
        package = [ordered]@{ selection = $packageRootMode; candidateLeaf = $(if ($PackageRoot) { [System.IO.Path]::GetFileName($PackageRoot.TrimEnd('\')) } else { $null }) }
    }
    $manifest = [ordered]@{
        schemaVersion = 1
        collector = 'Collect-DuoViewRestartEvidence.ps1'
        collectedAtUtc = [datetime]::UtcNow.ToString('o')
        platform = [System.Environment]::OSVersion.VersionString
        powershellVersion = $PSVersionTable.PSVersion.ToString()
        processId = $PID
        watchPid = $(if ($WatchPid -gt 0) { $WatchPid } else { $null })
        watchStatus = $watchStatus
        roots = $rootSummary
        caps = [ordered]@{ stagedEvidenceBytes = $script:MaxTotalBytes; stagedEvidenceBytesUsed = $script:TotalBytes; optionalDumpsBytes = $script:MaxDumpTotalBytes; optionalDumpsBytesUsed = $script:DumpBytes; recentDays = $RecentDays }
        diagnosticBoundary = [ordered]@{
            producerCopySummaryMatches = $recordCount
            requestedMethodCounts = $requestedMethod
            requestedControlCounts = $requestedControl
            effectiveMethodCounts = $effectiveMethod
            observedCopyPathCounts = $observedPath
            fallbackReasonCounts = $fallbackReason
            copySubmissionAcceptedCounts = $submissionAccepted
            projectionObservedCounts = $projectionObserved
            gazePoseObservedCounts = $gazeObserved
            sourceGenerationObservedCounts = $sourceGenerationObserved
            engineSourceGenerationRelation = 'unavailable_or_unproven'
            xrEndFrameAcceptance = 'unavailable'
            headsetPresentation = 'unavailable'
            psVr2ConnectionOrTracking = 'unavailable'
            passFailInferred = $false
        }
        redactionPolicy = 'Pattern-based key/value, bearer, URL user-info, email, and current-user-profile substitutions; not a guarantee of complete sanitization.'
        files = @($script:Records.ToArray())
    }
    $manifestJson = ConvertTo-Json -InputObject $manifest -Depth 8
    [System.IO.File]::WriteAllText((Join-Path $script:StageRoot 'collection-manifest.json'), $manifestJson, $script:Utf8NoBom)

    $stagedBytes = [long]0
    Get-ChildItem -LiteralPath $script:StageRoot -File -Recurse -Force | ForEach-Object { $stagedBytes += $_.Length }
    if ($stagedBytes -gt ($script:MaxTotalBytes + 1MB)) { throw 'Staged evidence exceeded the archive safety cap.' }
    if (Test-Path -LiteralPath $tempZipPath) { Remove-Item -LiteralPath $tempZipPath -Force }
    Compress-Archive -Path (Join-Path $script:StageRoot '*') -DestinationPath $tempZipPath -CompressionLevel Optimal -Force
    $zipInfo = Get-Item -LiteralPath $tempZipPath
    if ($zipInfo.Length -gt 110MB) { throw 'Compressed ZIP exceeded 110 MiB safety limit.' }
    Move-Item -LiteralPath $tempZipPath -Destination $zipPath
    Write-Output $zipPath
} finally {
    if (Test-Path -LiteralPath $tempZipPath) { Remove-Item -LiteralPath $tempZipPath -Force -ErrorAction SilentlyContinue }
    if ($script:StageRoot -and (Test-Path -LiteralPath $script:StageRoot)) {
        Remove-Item -LiteralPath $script:StageRoot -Recurse -Force -ErrorAction SilentlyContinue
    }
}
