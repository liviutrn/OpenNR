[CmdletBinding()]
param(
    [string]$TargetModPath,
    [string]$SourceModPath,
    [string]$NeuralDllPath,
    [ValidateSet('Auto', 'RTX50-Stock', 'RTX40-Ada', 'Universal-SM75-SM86-SM89-SM120')]
    [string]$RuntimeMode = 'Auto',
    [switch]$AllowAdaPatchedRuntime
)

$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms

function Select-Folder([string]$description) {
    $dialog = New-Object System.Windows.Forms.FolderBrowserDialog
    $dialog.Description = $description
    $dialog.UseDescriptionForTitle = $true
    if ($dialog.ShowDialog() -ne [System.Windows.Forms.DialogResult]::OK) {
        throw 'Folder selection was cancelled.'
    }
    return $dialog.SelectedPath
}

function Select-File([string]$title) {
    $dialog = New-Object System.Windows.Forms.OpenFileDialog
    $dialog.Title = $title
    $dialog.Filter = 'DLL files (*.dll)|*.dll|All files (*.*)|*.*'
    if ($dialog.ShowDialog() -ne [System.Windows.Forms.DialogResult]::OK) {
        throw 'File selection was cancelled.'
    }
    return $dialog.FileName
}

function Get-StreamlineRoot([string]$modPath) {
    $root = Join-Path $modPath 'Shaders\Upscaling\Streamline'
    if (-not (Test-Path -LiteralPath $root -PathType Container)) {
        throw "The selected folder does not contain Shaders\Upscaling\Streamline: $modPath"
    }
    return $root
}

function Test-Win64Dll([string]$path) {
    $bytes = [System.IO.File]::ReadAllBytes($path)
    if ($bytes.Length -lt 0x40 -or $bytes[0] -ne 0x4d -or $bytes[1] -ne 0x5a) { return $false }
    $peOffset = [BitConverter]::ToInt32($bytes, 0x3c)
    if ($peOffset -lt 0 -or $peOffset + 6 -gt $bytes.Length) { return $false }
    if ($bytes[$peOffset] -ne 0x50 -or $bytes[$peOffset + 1] -ne 0x45 -or $bytes[$peOffset + 2] -ne 0 -or $bytes[$peOffset + 3] -ne 0) { return $false }
    return ([BitConverter]::ToUInt16($bytes, $peOffset + 4) -eq 0x8664)
}

if (-not $TargetModPath) { $TargetModPath = Select-Folder 'Select the installed DLSSNR MGO preview mod folder' }
if (-not (Test-Path -LiteralPath $TargetModPath -PathType Container)) { throw "Target mod folder was not found: $TargetModPath" }
if (-not (Test-Path -LiteralPath (Join-Path $TargetModPath 'SKSE\Plugins\CommunityShaders.dll') -PathType Leaf)) {
    throw 'The target folder does not contain the DLSSNR CommunityShaders.dll. Install the MO2 package first.'
}

if (-not $SourceModPath) { $SourceModPath = Select-Folder 'Select an existing MGO mod folder containing the working Streamline runtime (normally Community Shaders Expanded)' }
$sourceRoot = Get-StreamlineRoot $SourceModPath
$targetRoot = Join-Path $TargetModPath 'Shaders\Upscaling\Streamline'
New-Item -ItemType Directory -Force -Path $targetRoot | Out-Null

if (-not $NeuralDllPath) { $NeuralDllPath = Select-File 'Select the authorized NVIDIA-signed nvngx_dlssnr.dll' }
if (-not (Test-Path -LiteralPath $NeuralDllPath -PathType Leaf)) { throw "Neural runtime was not found: $NeuralDllPath" }
$neuralFile = Get-Item -LiteralPath $NeuralDllPath
if ($neuralFile.Name -notmatch '(?i)^nvngx_dlssnr(?:\.dll|[._-].+\.dll)$') { throw "Select the nvngx_dlssnr.dll family file, not $($neuralFile.Name)" }
$neuralHash = (Get-FileHash -LiteralPath $NeuralDllPath -Algorithm SHA256).Hash
$neuralSignature = Get-AuthenticodeSignature -LiteralPath $NeuralDllPath
$neuralVersion = $neuralFile.VersionInfo.FileVersion
$stockNeuralHash = 'E16BCF15E16E13F527491CDF7845B2FE6521A738D8F7C9C721866A8496E1FC8E'
if ($RuntimeMode -eq 'Auto') {
    $RuntimeMode = if ($neuralHash -eq $stockNeuralHash) { 'RTX50-Stock' } else { 'Universal-SM75-SM86-SM89-SM120' }
}
if ($RuntimeMode -eq 'RTX50-Stock') {
    if ($neuralHash -ne $stockNeuralHash) {
        throw "nvngx_dlssnr.dll hash does not match the tested RTX 50 stock runtime. Received: $neuralHash"
    }
    if ($neuralSignature.Status -ne 'Valid' -or $neuralSignature.SignerCertificate.Subject -notmatch 'NVIDIA Corporation') {
        throw "nvngx_dlssnr.dll is not signed by NVIDIA Corporation. Status=$($neuralSignature.Status) Signer=$($neuralSignature.SignerCertificate.Subject)"
    }
} else {
    if (-not $AllowAdaPatchedRuntime) {
        throw "The selected nvngx_dlssnr.dll is not the tested stock RTX 50 file. For an authorized universal patched DLL, rerun with -RuntimeMode Universal-SM75-SM86-SM89-SM120 -AllowAdaPatchedRuntime or use Install-DLSSNRUniversalRuntime.cmd."
    }
    if ($neuralHash -eq $stockNeuralHash) {
        throw 'RTX40-Ada mode received the stock RTX 50 neural runtime. Select the authorized Ada-patched DLL.'
    }
    if (-not (Test-Win64Dll $NeuralDllPath)) {
        throw 'The selected Ada neural runtime is not a valid x64 Windows DLL.'
    }
    Write-Warning "External patched neural runtime mode selected. The supplied file may not retain NVIDIA Authenticode validation."
    $confirmationToken = if ($RuntimeMode -eq 'RTX40-Ada') { 'ADA' } else { 'UNIVERSAL' }
    $confirmation = Read-Host "Type $confirmationToken to confirm this is the authorized patched nvngx_dlssnr.dll"
    if ($confirmation -cne $confirmationToken) { throw "Patched runtime installation cancelled because confirmation was not $confirmationToken." }
}

$runtimeNames = @('nvngx_dlss.dll', 'sl.interposer.dll', 'sl.common.dll', 'sl.dlss.dll', 'sl.reflex.dll', 'sl.pcl.dll')
$runtimeFiles = foreach ($name in $runtimeNames) {
    $source = Join-Path $sourceRoot $name
    if (-not (Test-Path -LiteralPath $source -PathType Leaf)) {
        throw "The selected source mod is missing $name. Choose the MGO/CSX mod that contains the active Streamline runtime."
    }
    $signature = Get-AuthenticodeSignature -LiteralPath $source
    if ($signature.Status -ne 'Valid' -or $signature.SignerCertificate.Subject -notmatch 'NVIDIA Corporation') {
        throw "$name is not a valid NVIDIA-signed runtime. Status=$($signature.Status) Signer=$($signature.SignerCertificate.Subject)"
    }
    [pscustomobject]@{ Name = $name; Source = $source; Hash = (Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash; Version = (Get-Item -LiteralPath $source).VersionInfo.FileVersion }
}

$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$backupRoot = Join-Path $TargetModPath "TOOLS\runtime-backup-$stamp"
$copied = @()
foreach ($runtime in $runtimeFiles) {
    $destination = Join-Path $targetRoot $runtime.Name
    if (Test-Path -LiteralPath $destination -PathType Leaf) {
        New-Item -ItemType Directory -Force -Path $backupRoot | Out-Null
        Copy-Item -LiteralPath $destination -Destination (Join-Path $backupRoot $runtime.Name)
    }
    Copy-Item -LiteralPath $runtime.Source -Destination $destination -Force
    $copied += [pscustomobject]@{ Name = $runtime.Name; Destination = $destination; Version = $runtime.Version; SHA256 = $runtime.Hash }
}
$neuralDestination = Join-Path $targetRoot 'nvngx_dlssnr.dll'
if (Test-Path -LiteralPath $neuralDestination -PathType Leaf) {
    New-Item -ItemType Directory -Force -Path $backupRoot | Out-Null
    Copy-Item -LiteralPath $neuralDestination -Destination (Join-Path $backupRoot 'nvngx_dlssnr.dll')
}
Copy-Item -LiteralPath $NeuralDllPath -Destination $neuralDestination -Force
$copied += [pscustomobject]@{ Name = 'nvngx_dlssnr.dll'; Destination = $neuralDestination; Version = $neuralVersion; SHA256 = $neuralHash }

$report = [ordered]@{
    InstalledUtc = [DateTime]::UtcNow.ToString('o')
    TargetModPath = $TargetModPath
    SourceModPath = $SourceModPath
    RuntimeMode = $RuntimeMode
    BackupPath = if (Test-Path -LiteralPath $backupRoot) { $backupRoot } else { $null }
    Files = @($copied)
    NeuralSignature = $neuralSignature.Status.ToString()
    NeuralSigner = if ($neuralSignature.SignerCertificate) { $neuralSignature.SignerCertificate.Subject } else { $null }
    NeuralPatchedRuntime = ($RuntimeMode -eq 'RTX40-Ada')
}
$reportPath = Join-Path $TargetModPath 'TOOLS\runtime-install-report.json'
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $reportPath) | Out-Null
$report | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $reportPath -Encoding UTF8

Write-Host ''
Write-Host 'DLSSNR runtime installation completed.' -ForegroundColor Green
Write-Host "Target: $TargetModPath"
Write-Host "Runtime mode: $RuntimeMode"
Write-Host "Neural runtime: $neuralVersion / $neuralHash"
Write-Host "Report: $reportPath"
Write-Host 'Enable this mod in the isolated MO2 profile and keep Frame Generation disabled for the first test.'
