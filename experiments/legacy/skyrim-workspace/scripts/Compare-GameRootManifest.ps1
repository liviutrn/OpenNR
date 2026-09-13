[CmdletBinding()]
param(
    [string]$GameRoot = 'E:\Games\Steam\steamapps\common\SkyrimVR',
    [string]$Manifest = 'D:\.CODEX_Projects\DLSS_5_SKYRIM\backups\game-root-baseline-20260829\manifest.csv'
)

$ErrorActionPreference = 'Stop'
$resolvedRoot = (Resolve-Path -LiteralPath $GameRoot).Path
$baseline = @(Import-Csv -LiteralPath $Manifest | ForEach-Object {
    [pscustomobject]@{ RelativePath = $_.RelativePath; Length = [int64]$_.Length; SHA256 = $_.SHA256 }
})
$current = @(Get-ChildItem -LiteralPath $resolvedRoot -File | Sort-Object Name | ForEach-Object {
    [pscustomobject]@{
        RelativePath = $_.Name
        Length = $_.Length
        SHA256 = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash
    }
})

$baseMap = @{}
$currentMap = @{}
foreach ($row in $baseline) { $baseMap[$row.RelativePath.ToLowerInvariant()] = $row }
foreach ($row in $current) { $currentMap[$row.RelativePath.ToLowerInvariant()] = $row }
$keys = @($baseMap.Keys + $currentMap.Keys | Sort-Object -Unique)
$diff = foreach ($key in $keys) {
    $b = $baseMap[$key]
    $c = $currentMap[$key]
    if ($null -eq $b) { [pscustomobject]@{ Change = 'ADDED'; RelativePath = $c.RelativePath; Baseline = ''; Current = $c.SHA256 } }
    elseif ($null -eq $c) { [pscustomobject]@{ Change = 'REMOVED'; RelativePath = $b.RelativePath; Baseline = $b.SHA256; Current = '' } }
    elseif ($b.Length -ne $c.Length -or $b.SHA256 -ne $c.SHA256) {
        [pscustomobject]@{ Change = 'MODIFIED'; RelativePath = $c.RelativePath; Baseline = $b.SHA256; Current = $c.SHA256 }
    }
}

if (@($diff).Count -eq 0) {
    [pscustomobject]@{ GameRoot = $resolvedRoot; Result = 'PASS'; Files = $current.Count; Differences = 0 } | Format-List
    exit 0
}

$diff | Sort-Object RelativePath | Format-Table -AutoSize
[pscustomobject]@{ GameRoot = $resolvedRoot; Result = 'FAIL'; Files = $current.Count; Differences = @($diff).Count } | Format-List
exit 1
