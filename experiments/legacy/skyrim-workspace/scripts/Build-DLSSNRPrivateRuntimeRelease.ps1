[CmdletBinding()]
param(
    [string]$RuntimeSource = 'E:\MGO-RC3-clean\mods\DLSS5 SkyrimVR Open Shaders DLSSNR\Shaders\Upscaling\Streamline',
    [string]$NeuralRuntimePath = 'D:\.CODEX_Projects\DLSS_5_SKYRIM\nvngx_dlssnr.approx-fp16-sm_75-sm_86-sm_89-sm_120.dll',
    [string]$OutputRoot = 'D:\.CODEX_Projects\DLSS_5_SKYRIM\dist',
    [string]$Version = '0.2.0-mgo-vr.1',
    [switch]$Force
)

$ErrorActionPreference = 'Stop'

function Test-Win64Dll([string]$path) {
    $bytes = [System.IO.File]::ReadAllBytes($path)
    if ($bytes.Length -lt 0x40 -or $bytes[0] -ne 0x4d -or $bytes[1] -ne 0x5a) { return $false }
    $peOffset = [BitConverter]::ToInt32($bytes, 0x3c)
    if ($peOffset -lt 0 -or $peOffset + 6 -gt $bytes.Length) { return $false }
    if ($bytes[$peOffset] -ne 0x50 -or $bytes[$peOffset + 1] -ne 0x45 -or $bytes[$peOffset + 2] -ne 0 -or $bytes[$peOffset + 3] -ne 0) { return $false }
    return ([BitConverter]::ToUInt16($bytes, $peOffset + 4) -eq 0x8664)
}

if (-not (Test-Path -LiteralPath $RuntimeSource -PathType Container)) {
    throw "Runtime source folder was not found: $RuntimeSource"
}

$required = @(
    [pscustomobject]@{ Name = 'nvngx_dlss.dll'; Version = '310.8.0.0'; SHA256 = 'C85F971CE023C9F3492FC7455F0B01A24BA18EA39636407A846902C4360B0B7E'; Required = $true },
    [pscustomobject]@{ Name = 'sl.interposer.dll'; Version = '2.13.0.0'; SHA256 = '27B2190057994C0B287C2C5716953BF1586F6499AC12FBBB2092B9AAF8396570'; Required = $true },
    [pscustomobject]@{ Name = 'sl.common.dll'; Version = '2.13.0.0'; SHA256 = 'A4B2B5ACBE49FBC6D44DD432CAC19CD53218F698B2539DC7ED0FB268C72CFC8D'; Required = $true },
    [pscustomobject]@{ Name = 'sl.dlss.dll'; Version = '2.13.0.0'; SHA256 = '1EB5FB3D6F01D340FE086D981CC2DE4F18AA6D05EE276E5CF28ECD54818DCC8B'; Required = $true },
    [pscustomobject]@{ Name = 'sl.reflex.dll'; Version = '2.13.0.0'; SHA256 = 'ECF12973CDCEC2FFCED2EA77B1C7E45F4D387E7C864DDB5531B66A6F947EFFB3'; Required = $true },
    [pscustomobject]@{ Name = 'sl.pcl.dll'; Version = '2.13.0.0'; SHA256 = '12AA4E76C28A27C735E4ECB3072F44D09428ACB107B70AC38E4BD48DDB05F88D'; Required = $true }
)

New-Item -ItemType Directory -Force -Path $OutputRoot | Out-Null
$safeVersion = $Version -replace '[^A-Za-z0-9._-]', '-'
$archive = Join-Path $OutputRoot "DLSSNR-MGO-VR-Preview-$safeVersion-PRIVATE-RUNTIME.zip"
if (Test-Path -LiteralPath $archive) {
    if (-not $Force) {
        throw "Output already exists. Use -Force to replace this exact archive: $archive"
    }
    Remove-Item -LiteralPath $archive -Force
}

$stage = Join-Path $OutputRoot ('.staging-DLSSNR-private-' + [guid]::NewGuid().ToString('N'))
$runtime = Join-Path $stage 'Shaders\Upscaling\Streamline'
New-Item -ItemType Directory -Force -Path $runtime | Out-Null

$neuralFile = Get-Item -LiteralPath $NeuralRuntimePath
if ($neuralFile.Name -notmatch '(?i)^nvngx_dlssnr(?:\.dll|[._-].+\.dll)$') { throw "Select the nvngx_dlssnr.dll family file, not $($neuralFile.Name)" }
if (-not (Test-Win64Dll $NeuralRuntimePath)) { throw 'The neural runtime is not a valid x64 Windows DLL.' }
$neuralHash = (Get-FileHash -LiteralPath $NeuralRuntimePath -Algorithm SHA256).Hash
$stockNeuralHash = 'E16BCF15E16E13F527491CDF7845B2FE6521A738D8F7C9C721866A8496E1FC8E'
$universalNeuralHash = 'DCC0DC2414AEDEC4A8E084647070383BE068554042587180C20C784D4772D36F'
$neuralSignature = Get-AuthenticodeSignature -LiteralPath $NeuralRuntimePath
$neuralFlavor = if ($neuralHash -eq $stockNeuralHash) { 'stock-rtx50' } elseif ($neuralHash -eq $universalNeuralHash) { 'universal-sm75-sm86-sm89-sm120' } else { throw "Unrecognized neural runtime hash: $neuralHash" }
if ($neuralFlavor -eq 'stock-rtx50' -and ($neuralSignature.Status -ne 'Valid' -or $neuralSignature.SignerCertificate.Subject -notmatch 'NVIDIA Corporation')) {
    throw "Signature validation failed for the stock neural runtime: status=$($neuralSignature.Status), subject=$($neuralSignature.SignerCertificate.Subject)"
}
Copy-Item -LiteralPath $NeuralRuntimePath -Destination (Join-Path $runtime 'nvngx_dlssnr.dll')
$neuralRecord = [pscustomobject]@{
    Path = 'Shaders/Upscaling/Streamline/nvngx_dlssnr.dll'
    Version = $neuralFile.VersionInfo.FileVersion
    Bytes = $neuralFile.Length
    SHA256 = $neuralHash
    Signature = $neuralSignature.Status.ToString()
    Signer = if ($neuralSignature.SignerCertificate) { $neuralSignature.SignerCertificate.Subject } else { $null }
    Flavor = $neuralFlavor
}

$files = @($neuralRecord) + @(foreach ($entry in $required) {
    $source = Join-Path $RuntimeSource $entry.Name
    if (-not (Test-Path -LiteralPath $source -PathType Leaf)) {
        throw "Required runtime file is missing: $source"
    }
    $hash = (Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash
    if ($hash -ne $entry.SHA256) {
        throw "Hash mismatch for $($entry.Name). Expected $($entry.SHA256), got $hash"
    }
    $signature = Get-AuthenticodeSignature -LiteralPath $source
    if ($signature.Status -ne 'Valid' -or $signature.SignerCertificate.Subject -notmatch 'NVIDIA Corporation') {
        throw "Signature validation failed for $($entry.Name): status=$($signature.Status), subject=$($signature.SignerCertificate.Subject)"
    }
    Copy-Item -LiteralPath $source -Destination (Join-Path $runtime $entry.Name)
    [pscustomobject]@{
        Path = "Shaders/Upscaling/Streamline/$($entry.Name)"
        Version = $entry.Version
        Bytes = (Get-Item -LiteralPath $source).Length
        SHA256 = $hash
        Signature = $signature.Status
        Signer = 'NVIDIA Corporation'
    }
})

$manifest = [ordered]@{
    Name = 'DLSSNR-MGO-VR-Preview-PRIVATE-RUNTIME'
    Version = $Version
    RuntimeFlavor = $neuralFlavor
    NeuralRuntimeSHA256 = $neuralHash
    DeclaredArchitectures = @('sm_75', 'sm_86', 'sm_89', 'sm_120')
    ArchitectureNote = 'Declared by the supplied universal runtime package; individual GPU acceptance still requires a real Skyrim VR test.'
    Purpose = 'Private developer companion archive for the public MO2 package.'
    Redistribution = 'PRIVATE ONLY - NVIDIA/Streamline binaries are not included in the public archive. Do not re-upload or redistribute without authorization.'
    GeneratedUtc = [DateTime]::UtcNow.ToString('o')
    Files = @($files)
}
[System.IO.File]::WriteAllText((Join-Path $stage 'DLSSNR-private-runtime-manifest.json'), ($manifest | ConvertTo-Json -Depth 10) + [Environment]::NewLine, [System.Text.UTF8Encoding]::new($false))

$readme = @"
DLSSNR for MGO Skyrim VR - PRIVATE RUNTIME COMPANION

This archive contains only the seven runtime DLLs omitted from the public MO2
package: six signed NVIDIA/Streamline files plus the selected DLSSNR neural
runtime. The default is the new universal SM75/SM86/SM89/SM120 file, which is
intended for private developer handoff.
Declared targets: sm_75 (RTX 20), sm_86 (RTX 30), sm_89 (RTX 40), and sm_120
(RTX 50). These targets still need per-GPU Skyrim VR acceptance testing.
Do not publish or redistribute these files without confirming the applicable
license and distribution rights.

INSTALL
1. Install the public DLSSNR-MGO-VR-Preview MO2 ZIP first.
2. Install this ZIP as a second MO2 mod.
3. Enable both mods in the isolated test profile. Put this private runtime
   mod below/after the public package if MO2 reports an order choice.
4. Keep CSX, the CSX VR shader cache, the old DX11 bridge, RenoDX Feeder,
   ReShade DLSS wrappers, and Frame Generation disabled for this preview.

The files are placed at:
Shaders/Upscaling/Streamline/

The accompanying manifest records the SHA-256 hashes and signature state. The
universal neural file is an external patched binary and may report
Authenticode HashMismatch; do not redistribute it without permission.
"@
[System.IO.File]::WriteAllText((Join-Path $stage 'README-PRIVATE-DEVELOPER.txt'), $readme.Trim() + [Environment]::NewLine, [System.Text.UTF8Encoding]::new($false))

Compress-Archive -Path (Join-Path $stage '*') -DestinationPath $archive -CompressionLevel Optimal
$archiveHash = (Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash
$sizeMiB = [math]::Round((Get-Item -LiteralPath $archive).Length / 1MB, 2)
Remove-Item -LiteralPath $stage -Recurse -Force

[pscustomobject]@{
    Archive = $archive
    ArchiveSHA256 = $archiveHash
    ArchiveMiB = $sizeMiB
    IncludedFiles = $files.Count
    Variant = "private-runtime-companion ($neuralFlavor)"
} | Format-List
