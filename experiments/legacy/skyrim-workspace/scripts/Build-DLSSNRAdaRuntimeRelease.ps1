[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$AdaNeuralDllPath,
    [string]$SourceModPath = 'E:\MGO-RC3-clean\mods\DLSS5 SkyrimVR Open Shaders DLSSNR',
    [string]$OutputRoot = 'D:\.CODEX_Projects\DLSS_5_SKYRIM\dist',
    [string]$Version = '0.2.0-mgo-vr.1',
    [switch]$AllowPrivateAdaRuntime,
    [switch]$Force
)

$ErrorActionPreference = 'Stop'

if (-not $AllowPrivateAdaRuntime) {
    throw 'This builder packages an unofficial Ada-patched binary. Re-run with -AllowPrivateAdaRuntime only for a private developer handoff.'
}
if (-not (Test-Path -LiteralPath $AdaNeuralDllPath -PathType Leaf)) {
    throw "Ada neural runtime was not found: $AdaNeuralDllPath"
}
if (-not (Test-Path -LiteralPath $SourceModPath -PathType Container)) {
    throw "Source mod folder was not found: $SourceModPath"
}

function Test-Win64Dll([string]$path) {
    $bytes = [System.IO.File]::ReadAllBytes($path)
    if ($bytes.Length -lt 0x40 -or $bytes[0] -ne 0x4d -or $bytes[1] -ne 0x5a) { return $false }
    $peOffset = [BitConverter]::ToInt32($bytes, 0x3c)
    if ($peOffset -lt 0 -or $peOffset + 6 -gt $bytes.Length) { return $false }
    if ($bytes[$peOffset] -ne 0x50 -or $bytes[$peOffset + 1] -ne 0x45 -or $bytes[$peOffset + 2] -ne 0 -or $bytes[$peOffset + 3] -ne 0) { return $false }
    return ([BitConverter]::ToUInt16($bytes, $peOffset + 4) -eq 0x8664)
}

$adaFile = Get-Item -LiteralPath $AdaNeuralDllPath
if ($adaFile.Name -notmatch '(?i)^nvngx_dlssnr(?:\.dll|[._-].+\.dll)$') { throw "Select the nvngx_dlssnr.dll family file, not $($adaFile.Name)" }
if (-not (Test-Win64Dll $AdaNeuralDllPath)) { throw 'The Ada neural runtime is not a valid x64 Windows DLL.' }
$adaHash = (Get-FileHash -LiteralPath $AdaNeuralDllPath -Algorithm SHA256).Hash
$stockHash = 'E16BCF15E16E13F527491CDF7845B2FE6521A738D8F7C9C721866A8496E1FC8E'
if ($adaHash -eq $stockHash) { throw 'The selected file is the stock RTX 50 runtime, not an Ada-patched runtime.' }
$adaSignature = Get-AuthenticodeSignature -LiteralPath $AdaNeuralDllPath

$streamlineRoot = Join-Path $SourceModPath 'Shaders\Upscaling\Streamline'
if (-not (Test-Path -LiteralPath $streamlineRoot -PathType Container)) {
    throw "The source mod does not contain Shaders\Upscaling\Streamline: $SourceModPath"
}
$runtimeNames = @('nvngx_dlss.dll', 'sl.interposer.dll', 'sl.common.dll', 'sl.dlss.dll', 'sl.reflex.dll', 'sl.pcl.dll')
$runtimeFiles = foreach ($name in $runtimeNames) {
    $source = Join-Path $streamlineRoot $name
    if (-not (Test-Path -LiteralPath $source -PathType Leaf)) { throw "The source mod is missing $name" }
    $signature = Get-AuthenticodeSignature -LiteralPath $source
    if ($signature.Status -ne 'Valid' -or $signature.SignerCertificate.Subject -notmatch 'NVIDIA Corporation') {
        throw "$name is not a valid NVIDIA-signed runtime. Status=$($signature.Status) Signer=$($signature.SignerCertificate.Subject)"
    }
    [pscustomobject]@{
        Name = $name
        Source = $source
        SHA256 = (Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash
        Version = (Get-Item -LiteralPath $source).VersionInfo.FileVersion
    }
}

New-Item -ItemType Directory -Force -Path $OutputRoot | Out-Null
$safeVersion = $Version -replace '[^A-Za-z0-9._-]', '-'
$archive = Join-Path $OutputRoot "DLSSNR-MGO-VR-$safeVersion-PRIVATE-RTX40-ADA.zip"
if (Test-Path -LiteralPath $archive) {
    if (-not $Force) { throw "Output already exists. Use -Force to replace this exact archive: $archive" }
    Remove-Item -LiteralPath $archive -Force
}

$stage = Join-Path $OutputRoot ('.staging-DLSSNRAda-' + [guid]::NewGuid().ToString('N'))
$payload = Join-Path $stage 'Shaders\Upscaling\Streamline'
New-Item -ItemType Directory -Force -Path $payload | Out-Null
Copy-Item -LiteralPath $AdaNeuralDllPath -Destination (Join-Path $payload 'nvngx_dlssnr.dll')
foreach ($runtime in $runtimeFiles) { Copy-Item -LiteralPath $runtime.Source -Destination (Join-Path $payload $runtime.Name) }

$files = foreach ($file in (Get-ChildItem -LiteralPath $stage -Recurse -File | Sort-Object FullName)) {
    $relative = $file.FullName.Substring($stage.Length + 1).Replace('\', '/')
    [pscustomobject]@{
        Path = $relative
        Bytes = $file.Length
        SHA256 = (Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash
    }
}
$manifest = [ordered]@{
    Name = 'DLSSNR-MGO-VR-PRIVATE-RTX40-ADA'
    Version = $Version
    Variant = 'private-developer-ada-runtime'
    GeneratedUtc = [DateTime]::UtcNow.ToString('o')
    DeclaredArchitectures = @('sm_75', 'sm_86', 'sm_89', 'sm_120')
    ArchitectureNote = 'Declared by the supplied universal runtime package; individual GPU acceptance still requires a real Skyrim VR test.'
    NeuralRuntime = [ordered]@{
        Path = 'Shaders/Upscaling/Streamline/nvngx_dlssnr.dll'
        Version = $adaFile.VersionInfo.FileVersion
        SHA256 = $adaHash
        AuthenticodeStatus = $adaSignature.Status.ToString()
        Signer = if ($adaSignature.SignerCertificate) { $adaSignature.SignerCertificate.Subject } else { $null }
        Note = 'Unofficial Ada patch supplied by the developer; do not redistribute publicly.'
    }
    SignedRuntimeFiles = @($runtimeFiles | ForEach-Object {
        [pscustomobject]@{ Path = "Shaders/Upscaling/Streamline/$($_.Name)"; Version = $_.Version; SHA256 = $_.SHA256; Signer = 'NVIDIA Corporation' }
    })
    IncludedFiles = @($files)
}
[System.IO.File]::WriteAllText((Join-Path $stage 'DLSSNR-private-ada-manifest.json'), ($manifest | ConvertTo-Json -Depth 10) + [Environment]::NewLine, [System.Text.UTF8Encoding]::new($false))

$readme = @"
DLSSNR for MGO Skyrim VR - PRIVATE RTX 40 ADA RUNTIME $Version

This ZIP is a private developer companion for the VR-only DLSSNR preview.
It contains the six normal signed Streamline dependencies and the external
Ada-patched nvngx_dlssnr.dll supplied by the developer. The neural DLL is not
an NVIDIA stock file and must not be uploaded or redistributed without the
patch author's permission.

Install this ZIP as a second MO2 mod, below/after the DLSSNR core payload, in
the isolated test profile. Do not enable the old CSX/DLSS wrapper at the same
time. Keep Frame Generation disabled for the first test.

Declared targets are sm_75 (RTX 20), sm_86 (RTX 30), sm_89 (RTX 40), and sm_120
(RTX 50). These targets still need per-GPU Skyrim VR acceptance testing.

The exact neural DLL hash and signature state are recorded in
DLSSNR-private-ada-manifest.json. Build this only from an authorized file from
the RenoDX Discord #dlss5 pinned source, and keep the resulting archive private.
"@
[System.IO.File]::WriteAllText((Join-Path $stage 'README-PRIVATE-RTX40-ADA.txt'), $readme.Trim() + [Environment]::NewLine, [System.Text.UTF8Encoding]::new($false))

Compress-Archive -Path (Join-Path $stage '*') -DestinationPath $archive -CompressionLevel Optimal
$archiveHash = (Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash
$sizeMiB = [math]::Round((Get-Item -LiteralPath $archive).Length / 1MB, 2)
Remove-Item -LiteralPath $stage -Recurse -Force

[pscustomobject]@{
    Archive = $archive
    ArchiveSHA256 = $archiveHash
    ArchiveMiB = $sizeMiB
    NeuralSHA256 = $adaHash
    NeuralAuthenticode = $adaSignature.Status.ToString()
    SignedRuntimeFiles = $runtimeFiles.Count
    Variant = 'private-developer-ada-runtime'
} | Format-List
