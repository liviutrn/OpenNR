[CmdletBinding()]
param(
    [ValidateSet('baseline','neural','custom')][string]$Label = 'custom',
    [int]$DurationSeconds = 30,
    [int]$IntervalMilliseconds = 500,
    [string]$ProjectRoot = 'D:\.CODEX_Projects\DLSS_5_SKYRIM'
)

$ErrorActionPreference = 'Stop'
if ($DurationSeconds -lt 1) { throw 'DurationSeconds must be at least 1.' }
if ($IntervalMilliseconds -lt 100) { throw 'IntervalMilliseconds must be at least 100.' }
if (-not (Get-Process -Name SkyrimVR -ErrorAction SilentlyContinue)) {
    throw 'SkyrimVR.exe is not running; start the intended test scene before sampling.'
}

$outDir = Join-Path $ProjectRoot 'logs'
New-Item -ItemType Directory -Force -Path $outDir | Out-Null
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$out = Join-Path $outDir "perf-$Label-$stamp.csv"
$end = [DateTime]::UtcNow.AddSeconds($DurationSeconds)
$rows = [System.Collections.Generic.List[object]]::new()

while ([DateTime]::UtcNow -lt $end) {
    $now = [DateTime]::UtcNow
    $gpu = @(nvidia-smi --query-gpu=name,utilization.gpu,memory.used,memory.total,temperature.gpu,clocks.gr --format=csv,noheader,nounits 2>$null)
    $gpuFields = if ($gpu.Count -gt 0) { $gpu[0] -split '\s*,\s*' } else { @() }
    $game = Get-Process -Name SkyrimVR -ErrorAction SilentlyContinue | Select-Object -First 1
    $rows.Add([pscustomobject]@{
        Utc = $now.ToString('o')
        Label = $Label
        GameCpuSeconds = if ($game) { [double]$game.CPU } else { $null }
        GameWorkingSetMB = if ($game) { [math]::Round($game.WorkingSet64 / 1MB, 1) } else { $null }
        GPU = if ($gpuFields.Count -gt 0) { $gpuFields[0] } else { $null }
        GPUUtilPercent = if ($gpuFields.Count -gt 1) { [double]$gpuFields[1] } else { $null }
        GPUMemoryUsedMB = if ($gpuFields.Count -gt 2) { [double]$gpuFields[2] } else { $null }
        GPUMemoryTotalMB = if ($gpuFields.Count -gt 3) { [double]$gpuFields[3] } else { $null }
        GPUTemperatureC = if ($gpuFields.Count -gt 4) { [double]$gpuFields[4] } else { $null }
        GPUClockMHz = if ($gpuFields.Count -gt 5) { [double]$gpuFields[5] } else { $null }
    })
    Start-Sleep -Milliseconds $IntervalMilliseconds
}

$rows | Export-Csv -LiteralPath $out -NoTypeInformation -Encoding UTF8
[pscustomobject]@{ Label = $Label; Samples = $rows.Count; DurationSeconds = $DurationSeconds; Output = $out } | Format-List
