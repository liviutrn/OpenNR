$ErrorActionPreference = "Stop"
$roots = @((Join-Path $env:LOCALAPPDATA 'DuoViewDiagnostics'),
           (Join-Path $env:TEMP 'DuoViewDiagnostics_fallback'))
$dir = $roots | ForEach-Object {
    if (Test-Path $_) { Get-ChildItem -Path $_ -Directory -Filter 'v49_pid*' }
} | Sort-Object LastWriteTime -Descending | Select-Object -First 1
if (-not $dir) { Write-Host "No DuoView v49 diagnostic session found. Run STALKER 2 and enable DuoView ID6, then try again."; exit 2 }
Start-Sleep -Milliseconds 200
$out = Join-Path ([Environment]::GetFolderPath('Desktop')) ("DuoView-v49-Diagnostic-" + $dir.Name + ".zip")
if (Test-Path $out) { Remove-Item $out -Force }
Compress-Archive -Path (Join-Path $dir.FullName '*') -DestinationPath $out -CompressionLevel Optimal -Force
$csv=Join-Path $dir.FullName 'frame_trace.csv'
$gpu=Join-Path $dir.FullName 'image_manifest.csv'
if (-not (Test-Path $csv)) { Write-Host "WARNING: no frame trace was produced. Preserve the UEVR log." }
if (-not (Test-Path $gpu) -or (Get-Item $gpu).Length -lt 100) { Write-Host "WARNING: GPU snapshots absent. The CPU trace and the normal UEVR log may still be useful." }
Write-Host "Diagnostic archive: $out"
Write-Host "Upload this ZIP to the ChatGPT conversation for analysis. No gameplay screenshot from the headset is required."
