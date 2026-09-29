[CmdletBinding()]
param(
    [string]$GameRoot = 'E:\Games\Steam\steamapps\common\SkyrimVR',
    [string]$OutFile = 'D:\.CODEX_Projects\DLSS_5_SKYRIM\backups\game-root-baseline-20260829\manifest.csv'
)

$ErrorActionPreference = 'Stop'
$resolvedRoot = (Resolve-Path -LiteralPath $GameRoot).Path
$parent = Split-Path -Parent $OutFile
New-Item -ItemType Directory -Force -Path $parent | Out-Null

$rows = Get-ChildItem -LiteralPath $resolvedRoot -File | Sort-Object Name | ForEach-Object {
    [pscustomobject]@{
        RelativePath = $_.Name
        Length = $_.Length
        LastWriteTimeUtc = $_.LastWriteTimeUtc.ToString('o')
        SHA256 = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash
    }
}

$rows | Export-Csv -LiteralPath $OutFile -NoTypeInformation -Encoding UTF8
[pscustomobject]@{ GameRoot = $resolvedRoot; Manifest = $OutFile; Files = @($rows).Count } | Format-List
