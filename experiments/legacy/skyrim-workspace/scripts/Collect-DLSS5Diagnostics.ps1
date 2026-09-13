[CmdletBinding()]
param(
    [string]$ProjectRoot = 'D:\.CODEX_Projects\DLSS_5_SKYRIM',
    [string]$GameRoot = 'E:\Games\Steam\steamapps\common\SkyrimVR',
    [string]$MgoRoot = 'E:\MGO-RC3-clean'
)

$ErrorActionPreference = 'Continue'
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$outDir = Join-Path $ProjectRoot 'logs'
New-Item -ItemType Directory -Force -Path $outDir | Out-Null
$out = Join-Path $outDir "diagnostics-$stamp.txt"

"DLSS5 SkyrimVR diagnostics`nUTC=$([DateTime]::UtcNow.ToString('o'))`n" | Set-Content -LiteralPath $out -Encoding UTF8
"--- GPU ---" | Add-Content -LiteralPath $out
nvidia-smi --query-gpu=name,driver_version,memory.total,memory.used,utilization.gpu --format=csv,noheader 2>&1 | Add-Content -LiteralPath $out
"--- MO2 selection ---" | Add-Content -LiteralPath $out
Select-String -LiteralPath (Join-Path $MgoRoot 'ModOrganizer.ini') -Pattern '^selected_profile=|^gamePath=|^version=' | ForEach-Object Line | Add-Content -LiteralPath $out
"--- Processes ---" | Add-Content -LiteralPath $out
Get-Process -Name SkyrimVR,ModOrganizer,vrserver,OVRServer_x64,VirtualDesktop.Streamer -ErrorAction SilentlyContinue | Select-Object Id,ProcessName,Path,StartTime,CPU | Format-Table -AutoSize | Out-String | Add-Content -LiteralPath $out
"--- Prototype/root files ---" | Add-Content -LiteralPath $out
Get-ChildItem -LiteralPath $GameRoot -Force -File -ErrorAction SilentlyContinue | Where-Object { $_.Name -match '(?i)^(dxgi|reshade|renodx|dlss5|nvngx|sl\.)' -or $_.Extension -in '.addon64','.addon32' } | ForEach-Object { "{0}`t{1}`t{2}`t{3}" -f $_.Name,$_.Length,$_.VersionInfo.FileVersion,((Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash) } | Add-Content -LiteralPath $out
"--- Relevant logs ---" | Add-Content -LiteralPath $out
$logRoots = @($GameRoot,$MgoRoot,(Join-Path $MgoRoot 'logs'),(Join-Path $MgoRoot 'overwrite'))
foreach ($root in $logRoots) {
    if (Test-Path -LiteralPath $root) {
        Get-ChildItem -LiteralPath $root -Recurse -File -ErrorAction SilentlyContinue | Where-Object { $_.Name -match '(?i)(reshade|dlss5|bridge|streamline|communityshader|opencomposite|ocunleashed)' } | Sort-Object LastWriteTime -Descending | Select-Object -First 40 FullName,Length,LastWriteTime | Format-Table -AutoSize | Out-String | Add-Content -LiteralPath $out
    }
}
"Wrote $out" | Write-Output
