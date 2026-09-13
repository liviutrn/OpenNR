[CmdletBinding()]
param([Parameter(Mandatory=$true)][string]$Path)

$ErrorActionPreference = 'Stop'
if (-not (Test-Path -LiteralPath $Path)) { throw "Bridge log not found: $Path" }
$lines = Get-Content -LiteralPath $Path
$timing = $lines | Where-Object { $_ -match 'frames:.*bridge CPU.*frame interval' }
if (-not $timing) {
    Write-Output 'No 600-frame timing lines found. The bridge may not have reached its reporting interval.'
    $lines | Select-Object -Last 30
    exit 2
}
$timing | ForEach-Object {
    if ($_ -match '([0-9]+) frames: bridge CPU ([0-9.]+) ms/frame \| frame interval ([0-9.]+) ms \(([0-9.]+) fps\).*spread ([0-9.]+)-([0-9.]+) ms.*bridge is ([0-9.]+)%.*d3d12 ([0-9]+)/([0-9]+)') {
        [pscustomobject]@{ Frames=[int]$Matches[1]; BridgeCpuMs=[double]$Matches[2]; FrameIntervalMs=[double]$Matches[3]; Fps=[double]$Matches[4]; SpreadMinMs=[double]$Matches[5]; SpreadMaxMs=[double]$Matches[6]; BridgePercent=[double]$Matches[7]; D3D12Completed=[int]$Matches[8]; D3D12Issued=[int]$Matches[9] }
    } else { [pscustomobject]@{ Raw=$_ } }
}
