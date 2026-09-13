[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$Source,
    [Parameter(Mandatory = $true)]
    [string]$Destination,
    [Parameter(Mandatory = $true)]
    [int64]$ExpectedFiles,
    [Parameter(Mandatory = $true)]
    [int64]$ExpectedBytes
)

$ErrorActionPreference = 'Stop'
$sourceItem = Get-Item -LiteralPath $Source -Force
$destinationItem = Get-Item -LiteralPath $Destination -Force
if (-not $sourceItem.PSIsContainer) { throw "Source is not a directory: $Source" }
if (-not $destinationItem.PSIsContainer) { throw "Destination is not a directory: $Destination" }
if ($sourceItem.Attributes -band [IO.FileAttributes]::ReparsePoint) {
    throw "Refusing to finalize a source that is already a reparse point: $Source"
}
$sourceResolved = (Resolve-Path -LiteralPath $Source).Path
$destinationResolved = (Resolve-Path -LiteralPath $Destination).Path
if ($sourceResolved -ne $Source) { throw "Source resolved unexpectedly: $sourceResolved" }
if ($destinationResolved -ne $Destination) { throw "Destination resolved unexpectedly: $destinationResolved" }
$sourceFiles = @(Get-ChildItem -LiteralPath $Source -File -Recurse -Force)
$destinationFiles = @(Get-ChildItem -LiteralPath $Destination -File -Recurse -Force)
$sourceBytes = [int64](($sourceFiles | Measure-Object Length -Sum).Sum)
$destinationBytes = [int64](($destinationFiles | Measure-Object Length -Sum).Sum)
if ($sourceFiles.Count -ne $ExpectedFiles -or $destinationFiles.Count -ne $ExpectedFiles) {
    throw "File-count verification failed: source=$($sourceFiles.Count), destination=$($destinationFiles.Count), expected=$ExpectedFiles"
}
if ($sourceBytes -ne $ExpectedBytes -or $destinationBytes -ne $ExpectedBytes) {
    throw "Byte-count verification failed: source=$sourceBytes, destination=$destinationBytes, expected=$ExpectedBytes"
}
$sourceChildren = @(Get-ChildItem -LiteralPath $Source -Force)
if (@($sourceChildren | Where-Object { -not $_.PSIsContainer }).Count -ne 0) {
    throw "Source enumeration changed during verification"
}
Remove-Item -LiteralPath $Source -Recurse -Force
if (Test-Path -LiteralPath $Source) { throw "Source remained after verified cleanup: $Source" }
New-Item -ItemType Junction -Path $Source -Target $Destination | Out-Null
$junction = Get-Item -LiteralPath $Source -Force
if ($junction.LinkType -ne 'Junction') { throw "Expected a junction at $Source" }
[pscustomobject]@{
    source = $Source
    destination = $Destination
    source_removed = $true
    link_type = $junction.LinkType
    target = $junction.Target
} | ConvertTo-Json -Compress
