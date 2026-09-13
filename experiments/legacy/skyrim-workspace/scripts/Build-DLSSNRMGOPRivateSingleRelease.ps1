[CmdletBinding()]
param(
    [string]$ModSource = 'E:\MGO-RC3-clean\mods\DLSS5 SkyrimVR Open Shaders DLSSNR',
    [string]$NeuralRuntimePath = 'D:\.CODEX_Projects\DLSS_5_SKYRIM\nvngx_dlssnr.approx-fp16-sm_75-sm_86-sm_89-sm_120.dll',
    [string]$OutputRoot = 'D:\.CODEX_Projects\DLSS_5_SKYRIM\dist',
    [string]$Version = '0.2.1-mgo-vr.1',
    [switch]$Force
)

$ErrorActionPreference = 'Stop'

if (-not (Test-Path -LiteralPath $ModSource -PathType Container)) {
    throw "Source mod folder was not found: $ModSource"
}
if (-not (Test-Path -LiteralPath $NeuralRuntimePath -PathType Leaf)) {
    throw "Universal neural runtime was not found: $NeuralRuntimePath"
}

function Get-RelativePath([string]$base, [string]$path) {
    return $path.Substring($base.Length + 1).Replace('\', '/')
}

function Test-Win64Dll([string]$path) {
    $bytes = [System.IO.File]::ReadAllBytes($path)
    if ($bytes.Length -lt 0x40 -or $bytes[0] -ne 0x4d -or $bytes[1] -ne 0x5a) { return $false }
    $peOffset = [BitConverter]::ToInt32($bytes, 0x3c)
    if ($peOffset -lt 0 -or $peOffset + 6 -gt $bytes.Length) { return $false }
    if ($bytes[$peOffset] -ne 0x50 -or $bytes[$peOffset + 1] -ne 0x45 -or $bytes[$peOffset + 2] -ne 0 -or $bytes[$peOffset + 3] -ne 0) { return $false }
    return ([BitConverter]::ToUInt16($bytes, $peOffset + 4) -eq 0x8664)
}

function Test-Excluded([string]$relativePath) {
    $path = $relativePath.ToLowerInvariant()
    if ($path -eq 'skse/plugins/communityshaders.pdb') { return $true }
    if ($path.StartsWith('renderdoc/')) { return $true }
    if ($path.StartsWith('textures/')) { return $true }
    if ($path.StartsWith('meshes/')) { return $true }
    if ($path.StartsWith('particlelights/')) { return $true }
    if ($path -eq 'shaders/features/renderdoc.ini') { return $true }
    if ($path.StartsWith('shaders/upscaling/') -and $path.EndsWith('.dll')) { return $true }
    return $false
}

$universalNeuralHash = 'DCC0DC2414AEDEC4A8E084647070383BE068554042587180C20C784D4772D36F'
$neuralFile = Get-Item -LiteralPath $NeuralRuntimePath
if ($neuralFile.Name -notmatch '(?i)^nvngx_dlssnr(?:\.dll|[._-].+\.dll)$') { throw "Select the nvngx_dlssnr.dll family file, not $($neuralFile.Name)" }
if (-not (Test-Win64Dll $NeuralRuntimePath)) { throw 'The universal neural runtime is not a valid x64 Windows DLL.' }
$neuralHash = (Get-FileHash -LiteralPath $NeuralRuntimePath -Algorithm SHA256).Hash
if ($neuralHash -ne $universalNeuralHash) { throw "Unexpected universal neural runtime hash: $neuralHash" }
$neuralSignature = Get-AuthenticodeSignature -LiteralPath $NeuralRuntimePath

$streamlineSource = Join-Path $ModSource 'Shaders\Upscaling\Streamline'
if (-not (Test-Path -LiteralPath $streamlineSource -PathType Container)) { throw "Streamline runtime folder was not found: $streamlineSource" }
$runtimeExpected = @(
    [pscustomobject]@{ Name = 'nvngx_dlss.dll'; Version = '310.8.0.0'; SHA256 = 'C85F971CE023C9F3492FC7455F0B01A24BA18EA39636407A846902C4360B0B7E' },
    [pscustomobject]@{ Name = 'sl.interposer.dll'; Version = '2.13.0.0'; SHA256 = '27B2190057994C0B287C2C5716953BF1586F6499AC12FBBB2092B9AAF8396570' },
    [pscustomobject]@{ Name = 'sl.common.dll'; Version = '2.13.0.0'; SHA256 = 'A4B2B5ACBE49FBC6D44DD432CAC19CD53218F698B2539DC7ED0FB268C72CFC8D' },
    [pscustomobject]@{ Name = 'sl.dlss.dll'; Version = '2.13.0.0'; SHA256 = '1EB5FB3D6F01D340FE086D981CC2DE4F18AA6D05EE276E5CF28ECD54818DCC8B' },
    [pscustomobject]@{ Name = 'sl.reflex.dll'; Version = '2.13.0.0'; SHA256 = 'ECF12973CDCEC2FFCED2EA77B1C7E45F4D387E7C864DDB5531B66A6F947EFFB3' },
    [pscustomobject]@{ Name = 'sl.pcl.dll'; Version = '2.13.0.0'; SHA256 = '12AA4E76C28A27C735E4ECB3072F44D09428ACB107B70AC38E4BD48DDB05F88D' }
)

New-Item -ItemType Directory -Force -Path $OutputRoot | Out-Null
$safeVersion = $Version -replace '[^A-Za-z0-9._-]', '-'
$archive = Join-Path $OutputRoot "DLSSNR-MGO-VR-Private-Single-$safeVersion-MO2.zip"
if (Test-Path -LiteralPath $archive) {
    if (-not $Force) { throw "Output already exists. Use -Force to replace this exact archive: $archive" }
    Remove-Item -LiteralPath $archive -Force
}

$stage = Join-Path $OutputRoot ('.staging-DLSSNR-private-single-' + [guid]::NewGuid().ToString('N'))
$core = Join-Path $stage '00 - DLSSNR Core'
$runtime = Join-Path $stage '01 - DLSSNR Universal Runtime\Shaders\Upscaling\Streamline'
New-Item -ItemType Directory -Force -Path $core,$runtime | Out-Null

$sourceFiles = Get-ChildItem -LiteralPath $ModSource -Recurse -File
foreach ($file in $sourceFiles) {
    $relative = Get-RelativePath $ModSource $file.FullName
    if (Test-Excluded $relative) { continue }
    $destination = Join-Path $core ($relative -replace '/', '\')
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $destination) | Out-Null
    Copy-Item -LiteralPath $file.FullName -Destination $destination
}

$meta = @"
[General]
gameName=SkyrimSE
modid=0
version=$Version
newestVersion=$Version
category=-1,
nexusFileStatus=0
installationFile=DLSSNR MGO VR Private Single $Version
repository=https://github.com/YtzyFvra/skyrim-community-shaders
comments=Private local Open Shaders DLSS Neural Rendering VR build for MGO Skyrim VR with the universal SM75/SM86/SM89/SM120 runtime.
notes=Install as one MO2 mod in an isolated test profile. Do not enable with Community Shaders Expanded, the CSX VR shader cache, the DX11 bridge, RenoDX Feeder, or ReShade wrappers.
"@
[System.IO.File]::WriteAllText((Join-Path $core 'meta.ini'), $meta.Trim() + [Environment]::NewLine, [System.Text.UTF8Encoding]::new($false))

$runtimeRecords = @()
Copy-Item -LiteralPath $NeuralRuntimePath -Destination (Join-Path $runtime 'nvngx_dlssnr.dll')
$runtimeRecords += [pscustomobject]@{
    Path = 'Shaders/Upscaling/Streamline/nvngx_dlssnr.dll'
    Version = $neuralFile.VersionInfo.FileVersion
    Bytes = $neuralFile.Length
    SHA256 = $neuralHash
    Signature = $neuralSignature.Status.ToString()
    Signer = if ($neuralSignature.SignerCertificate) { $neuralSignature.SignerCertificate.Subject } else { $null }
    Flavor = 'universal-sm75-sm86-sm89-sm120'
}
foreach ($entry in $runtimeExpected) {
    $source = Join-Path $streamlineSource $entry.Name
    if (-not (Test-Path -LiteralPath $source -PathType Leaf)) { throw "Required runtime file is missing: $source" }
    $hash = (Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash
    if ($hash -ne $entry.SHA256) { throw "Hash mismatch for $($entry.Name): expected $($entry.SHA256), got $hash" }
    $signature = Get-AuthenticodeSignature -LiteralPath $source
    if ($signature.Status -ne 'Valid' -or $signature.SignerCertificate.Subject -notmatch 'NVIDIA Corporation') {
        throw "Signature validation failed for $($entry.Name): status=$($signature.Status), subject=$($signature.SignerCertificate.Subject)"
    }
    Copy-Item -LiteralPath $source -Destination (Join-Path $runtime $entry.Name)
    $runtimeRecords += [pscustomobject]@{
        Path = "Shaders/Upscaling/Streamline/$($entry.Name)"
        Version = $entry.Version
        Bytes = (Get-Item -LiteralPath $source).Length
        SHA256 = $hash
        Signature = $signature.Status.ToString()
        Signer = $signature.SignerCertificate.Subject
        Flavor = 'signed-streamline'
    }
}

$sourceCommit = (& git -C (Join-Path $PSScriptRoot '..\vendor\open-shaders-dlssnr-vr-091bfb4d') rev-parse HEAD 2>$null).Trim()
if (-not $sourceCommit) { $sourceCommit = 'unknown-local-build' }
$includedCore = foreach ($file in (Get-ChildItem -LiteralPath $core -Recurse -File | Sort-Object FullName)) {
    $relative = Get-RelativePath $core $file.FullName
    [pscustomobject]@{ Path = $relative; Bytes = $file.Length; SHA256 = (Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash }
}
$manifest = [ordered]@{
    Name = 'DLSSNR-MGO-VR-Private-Single'
    Version = $Version
    Variant = 'private-single-mo2-fomod-vr-only'
    GeneratedUtc = [DateTime]::UtcNow.ToString('o')
    SourceCommit = $sourceCommit
    DeclaredArchitectures = @('sm_75', 'sm_86', 'sm_89', 'sm_120')
    ArchitectureNote = 'Declared by the supplied universal runtime; individual GPU acceptance still requires a real Skyrim VR test.'
    RuntimeFiles = @($runtimeRecords)
    IncludedCoreFiles = @($includedCore)
    Excluded = @('CommunityShaders.pdb', 'RenderDoc', 'textures', 'meshes', 'ParticleLights', 'shader RenderDoc.ini', 'duplicate Streamline DLL payloads')
}
[System.IO.File]::WriteAllText((Join-Path $stage 'DLSSNR-private-single-manifest.json'), ($manifest | ConvertTo-Json -Depth 12) + [Environment]::NewLine, [System.Text.UTF8Encoding]::new($false))

$readme = @"
DLSSNR for MGO Skyrim VR - PRIVATE SINGLE MO2 PACKAGE $Version

This local developer ZIP contains the VR-only DLSSNR core and the universal
SM75/SM86/SM89/SM120 runtime in one MO2/FOMOD install. It is intended for this
machine or a private developer test only.

PATCH NOTES (0.2.1)
- Routes map/stats and static pause/menu backdrops through the VR menu bridge.
- Supplies camera-derived motion vectors for those backdrops so head movement
  does not leave a frozen head-locked image.
- Keeps a live rendered world behind a pause menu on the normal gameplay path.

INSTALL
1. Back up MGO or use the copied test profile.
2. Install this one ZIP through MO2's install-mod/archive button.
3. Enable the single installed mod. Do not install the separate public core or
   private runtime companion alongside this package.
4. Disable CSX, the CSX VR shader cache, the older DX11 bridge, RenoDX Feeder,
   ReShade DLSS wrappers, and Frame Generation for the first test.
5. Launch Skyrim VR through MO2, press End, open Upscaling / Foveated DLSS,
   enable DLSS Neural Rendering, and confirm the Developer Mode evaluations.

The archive places the runtime at:
Shaders/Upscaling/Streamline/

Declared targets: sm_75 (RTX 20), sm_86 (RTX 30), sm_89 (RTX 40), and sm_120
(RTX 50). The patched neural DLL may report Authenticode HashMismatch; its
hash and signature state are recorded in DLSSNR-private-single-manifest.json.
The archive does not edit saves, profiles, or the physical game folder.
"@
[System.IO.File]::WriteAllText((Join-Path $stage 'README-PRIVATE-SINGLE.txt'), $readme.Trim() + [Environment]::NewLine, [System.Text.UTF8Encoding]::new($false))

$licenses = Join-Path $stage 'LICENSES'
New-Item -ItemType Directory -Force -Path $licenses | Out-Null
Copy-Item -LiteralPath (Join-Path $PSScriptRoot '..\vendor\open-shaders-dlssnr-vr-091bfb4d\COPYING') -Destination (Join-Path $licenses 'Open-Shaders-GPL-3.0.txt')

$fomod = Join-Path $stage 'fomod'
New-Item -ItemType Directory -Force -Path $fomod | Out-Null
$info = @"
<?xml version="1.0" encoding="UTF-8"?>
<fomod>
  <Name>DLSSNR for MGO Skyrim VR - Private Single Package</Name>
  <Author>DLSS5 SkyrimVR prototype contributors</Author>
  <Version>$Version</Version>
  <Website>https://github.com/YtzyFvra/skyrim-community-shaders</Website>
  <Description><![CDATA[Private VR-only Open Shaders DLSS Neural Rendering package with the universal SM75/SM86/SM89/SM120 runtime included.]]></Description>
</fomod>
"@
[System.IO.File]::WriteAllText((Join-Path $fomod 'info.xml'), $info.Trim() + [Environment]::NewLine, [System.Text.UTF8Encoding]::new($false))
$config = @"
<?xml version="1.0" encoding="UTF-8"?>
<config xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:noNamespaceSchemaLocation="http://qconsulting.ca/fo3/ModConfig5.0.xsd">
  <moduleName>DLSSNR for MGO Skyrim VR - Private Single Package</moduleName>
  <installSteps order="Explicit">
    <installStep name="Install complete private VR package">
      <optionalFileGroups order="Explicit">
        <group name="Core and universal runtime" type="SelectExactlyOne">
          <plugins order="Explicit">
            <plugin name="Install complete package">
              <description>Installs the VR-only DLSSNR core and the included universal SM75/SM86/SM89/SM120 runtime as one MO2 mod.</description>
              <files>
                <file source="00 - DLSSNR Core" destination="" />
                <file source="01 - DLSSNR Universal Runtime" destination="" />
              </files>
            </plugin>
          </plugins>
        </group>
      </optionalFileGroups>
    </installStep>
  </installSteps>
</config>
"@
[System.IO.File]::WriteAllText((Join-Path $fomod 'ModuleConfig.xml'), $config.Trim() + [Environment]::NewLine, [System.Text.UTF8Encoding]::new($false))

Compress-Archive -Path (Join-Path $stage '*') -DestinationPath $archive -CompressionLevel Optimal
$archiveHash = (Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash
$sizeMiB = [math]::Round((Get-Item -LiteralPath $archive).Length / 1MB, 2)
Remove-Item -LiteralPath $stage -Recurse -Force

[pscustomobject]@{
    Archive = $archive
    ArchiveSHA256 = $archiveHash
    ArchiveMiB = $sizeMiB
    RuntimeFiles = $runtimeRecords.Count
    CoreFiles = $includedCore.Count
    Variant = 'private-single-mo2-fomod-vr-only'
} | Format-List
