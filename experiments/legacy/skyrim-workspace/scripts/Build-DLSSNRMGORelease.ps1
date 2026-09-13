[CmdletBinding()]
param(
    [string]$ModSource = 'E:\MGO-RC3-clean\mods\DLSS5 SkyrimVR Open Shaders DLSSNR',
    [string]$OutputRoot = 'D:\.CODEX_Projects\DLSS_5_SKYRIM\dist',
    [string]$Version = '0.2.2-mgo-vr.1',
    [switch]$Force
)

$ErrorActionPreference = 'Stop'

if (-not (Test-Path -LiteralPath $ModSource -PathType Container)) {
    throw "Source mod folder was not found: $ModSource"
}
$sourceDll = Join-Path $ModSource 'SKSE\Plugins\CommunityShaders.dll'
if (-not (Test-Path -LiteralPath $sourceDll -PathType Leaf)) {
    throw "The source mod does not contain the expected custom CommunityShaders.dll: $sourceDll"
}

New-Item -ItemType Directory -Force -Path $OutputRoot | Out-Null
$safeVersion = $Version -replace '[^A-Za-z0-9._-]', '-'
$archive = Join-Path $OutputRoot "DLSSNR-MGO-VR-Preview-$safeVersion-MO2.zip"
if (Test-Path -LiteralPath $archive) {
    if (-not $Force) {
        throw "Output already exists. Use -Force to replace this exact archive: $archive"
    }
    Remove-Item -LiteralPath $archive -Force
}

$stage = Join-Path $OutputRoot (".staging-DLSSNR-" + [guid]::NewGuid().ToString('N'))
$core = Join-Path $stage '00 - DLSSNR Core'
New-Item -ItemType Directory -Force -Path $core | Out-Null

function Get-RelativePath([string]$base, [string]$path) {
    return $path.Substring($base.Length + 1).Replace('\', '/')
}

function Copy-SourceFile([string]$relativePath) {
    $source = Join-Path $ModSource ($relativePath -replace '/', '\')
    if (-not (Test-Path -LiteralPath $source -PathType Leaf)) {
        throw "Required source file is missing: $source"
    }
    $destination = Join-Path $core ($relativePath -replace '/', '\')
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $destination) | Out-Null
    Copy-Item -LiteralPath $source -Destination $destination
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
installationFile=DLSSNR MGO VR Preview $Version
repository=https://github.com/YtzyFvra/skyrim-community-shaders
comments=Experimental Open Shaders DLSS Neural Rendering VR build for MGO Skyrim VR; VR-only packaging.
notes=Install in an isolated MO2 profile. Do not enable with Community Shaders Expanded, the CSX VR shader cache, the DX11 bridge, RenoDX Feeder, or ReShade wrappers. NVIDIA runtime DLLs are external dependencies and are not bundled.
"@
[System.IO.File]::WriteAllText((Join-Path $core 'meta.ini'), $meta.Trim() + [Environment]::NewLine, [System.Text.UTF8Encoding]::new($false))

$sourceHash = (Get-FileHash -LiteralPath $sourceDll -Algorithm SHA256).Hash
$sourceRepo = Join-Path $PSScriptRoot '..\vendor\open-shaders-dlssnr-vr-091bfb4d'
$sourceCommit = (& git -C $sourceRepo rev-parse HEAD 2>$null).Trim()
if (-not $sourceCommit) { $sourceCommit = 'unknown-local-build' }
$sourceStatus = @(& git -C $sourceRepo status --porcelain 2>$null)
$sourceWorktreeDirty = ($sourceStatus.Count -gt 0)

$external = @(
    [pscustomobject]@{ Path = 'Shaders/Upscaling/Streamline/nvngx_dlssnr.dll'; Version = '310.8.0.0 stock RTX 50'; SHA256 = 'E16BCF15E16E13F527491CDF7845B2FE6521A738D8F7C9C721866A8496E1FC8E'; Signer = 'NVIDIA Corporation'; Source = 'DLSS5 add-on author / authorized RHI distribution'; URL = 'https://github.com/RankFTW/RHI/releases'; Required = $true },
    [pscustomobject]@{ Path = 'Shaders/Upscaling/Streamline/nvngx_dlssnr.dll'; Version = 'developer-supplied Ada patch'; SHA256 = 'record after obtaining'; Signer = 'may be unsigned or patch-invalidated'; Source = 'RenoDX Discord #dlss5 pinned Ada-patch source'; URL = 'https://discord.com/channels/1408098019194310818/1542647972695904317'; Required = $false; GPU = 'RTX 40 Ada' },
    [pscustomobject]@{ Path = 'Shaders/Upscaling/Streamline/nvngx_dlss.dll'; Version = '310.8.0.0'; SHA256 = 'C85F971CE023C9F3492FC7455F0B01A24BA18EA39636407A846902C4360B0B7E'; Signer = 'NVIDIA Corporation'; Source = 'Supplied Streamline runtime package'; URL = 'https://github.com/NVIDIA-RTX/Streamline/releases'; Required = $true },
    [pscustomobject]@{ Path = 'Shaders/Upscaling/Streamline/sl.interposer.dll'; Version = '2.13.0.0'; SHA256 = '27B2190057994C0B287C2C5716953BF1586F6499AC12FBBB2092B9AAF8396570'; Signer = 'NVIDIA Corporation'; Source = 'Supplied Streamline runtime package'; URL = 'https://github.com/NVIDIA-RTX/Streamline/releases'; Required = $true },
    [pscustomobject]@{ Path = 'Shaders/Upscaling/Streamline/sl.common.dll'; Version = '2.13.0.0'; SHA256 = 'A4B2B5ACBE49FBC6D44DD432CAC19CD53218F698B2539DC7ED0FB268C72CFC8D'; Signer = 'NVIDIA Corporation'; Source = 'Supplied Streamline runtime package'; URL = 'https://github.com/NVIDIA-RTX/Streamline/releases'; Required = $true },
    [pscustomobject]@{ Path = 'Shaders/Upscaling/Streamline/sl.dlss.dll'; Version = '2.13.0.0'; SHA256 = '1EB5FB3D6F01D340FE086D981CC2DE4F18AA6D05EE276E5CF28ECD54818DCC8B'; Signer = 'NVIDIA Corporation'; Source = 'Supplied Streamline runtime package'; URL = 'https://github.com/NVIDIA-RTX/Streamline/releases'; Required = $true },
    [pscustomobject]@{ Path = 'Shaders/Upscaling/Streamline/sl.reflex.dll'; Version = '2.13.0.0'; SHA256 = 'ECF12973CDCEC2FFCED2EA77B1C7E45F4D387E7C864DDB5531B66A6F947EFFB3'; Signer = 'NVIDIA Corporation'; Source = 'Supplied Streamline runtime package'; URL = 'https://github.com/NVIDIA-RTX/Streamline/releases'; Required = $false },
    [pscustomobject]@{ Path = 'Shaders/Upscaling/Streamline/sl.pcl.dll'; Version = '2.13.0.0'; SHA256 = '12AA4E76C28A27C735E4ECB3072F44D09428ACB107B70AC38E4BD48DDB05F88D'; Signer = 'NVIDIA Corporation'; Source = 'Supplied Streamline runtime package'; URL = 'https://github.com/NVIDIA-RTX/Streamline/releases'; Required = $false }
)

$included = foreach ($file in (Get-ChildItem -LiteralPath $core -Recurse -File | Sort-Object FullName)) {
    $relative = Get-RelativePath $core $file.FullName
    [pscustomobject]@{
        Path = $relative
        Bytes = $file.Length
        SHA256 = (Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash
    }
}

$manifest = [ordered]@{
    Name = 'DLSSNR-MGO-VR-Preview'
    Version = $Version
    Variant = 'public-mo2-fomod-vr-only'
    GeneratedUtc = [DateTime]::UtcNow.ToString('o')
    SourceCommit = $sourceCommit
    SourceWorktreeDirty = $sourceWorktreeDirty
    CommunityShadersSha256 = $sourceHash
    Excluded = @(
        'NVIDIA/Streamline/DLSS/NR binaries: obtain from an authorized source and verify the manifest hashes.'
        'CommunityShaders.pdb: debug symbols.'
        'Renderdoc: developer-only tooling.'
        'textures, meshes, ParticleLights: unrelated AIO/game-content payload for this DLSSNR preview.'
        'DX12 Streamline and FidelityFX binary runtimes: frame generation is disabled for this preview.'
    )
    ExternalDependencies = @($external)
    IncludedFiles = @($included)
}
$manifestJson = $manifest | ConvertTo-Json -Depth 10
[System.IO.File]::WriteAllText((Join-Path $stage 'DLSSNR-manifest.json'), $manifestJson + [Environment]::NewLine, [System.Text.UTF8Encoding]::new($false))

$readme = @"
DLSSNR for MGO Skyrim VR - Experimental Preview $Version

This is an MO2/FOMOD package for testing the Open Shaders DLSS Neural Rendering
VR path only. It is not a replacement for MGO and it does not include saves or a
profile. Install it only in a copied MO2 profile.

INSTALL
1. Back up the MGO instance or create a copy of the MGO profile.
2. In MO2, install this ZIP from the archive/install-mod button.
3. In the test profile, enable this mod and disable:
   - Community Shaders Expanded (CSX)
   - Community Shaders VR Shader Cache - csx3.18
   - DLSS5/DX11 bridge, RenoDX Feeder, and ReShade wrappers
4. Open the archive, run TOOLS/Install-DLSSNRRuntime.cmd, and select the
   authorized nvngx_dlssnr.dll. For RTX 50, use the normal helper and its
   exact stock hash/signature checks. For RTX 40 Ada, use
   TOOLS/Install-DLSSNRAdaRuntime.cmd with the developer-supplied Ada-patched
   DLL. For the multi-GPU SM75/SM86/SM89/SM120 runtime, use
   TOOLS/Install-DLSSNRUniversalRuntime.cmd; both paths perform a separate
   explicit confirmation and record the DLL hash.
   Both paths copy only the required runtime files into the DLSSNR mod.
   For a private developer handoff, the separate PRIVATE-RUNTIME ZIP can be
   installed as a second MO2 mod instead of using this helper.
5. Keep Frame Generation disabled for this preview, launch Skyrim VR through
   MO2, and press End to open Open Shaders.
6. Open Upscaling / Foveated DLSS, enable DLSS Neural Rendering, and use the
   Developer Mode status line to confirm successful Evaluations.

ROLLBACK
Disable or remove this single mod and switch back to the original MGO profile.
The package does not edit saves, the primary profile, or the physical game
folder.

LIMITATIONS
This build is experimental and VR-only; it does not package or claim Flat
support. It is currently targeted at the tested MGO/Skyrim VR
configuration. Do not report a headset FPS result without recording the
headset refresh, real application frame time, and the Open Shaders evaluation
count. The desktop mirror alone is not acceptance evidence.
"@
[System.IO.File]::WriteAllText((Join-Path $stage 'README-INSTALL.txt'), $readme.Trim() + [Environment]::NewLine, [System.Text.UTF8Encoding]::new($false))

$changelog = @"
DLSSNR-MGO-VR $Version

This package is built from the Open Shaders Skyrim VR branch at:
$sourceCommit
The manifest records whether preserved local MGO/VR worktree changes were
present when this package was built.

Included implementation update:
- Upstream 05e037c runs the flat SDR neural pass against kFRAMEBUFFER before
  UI composition. The change is guarded out of the VR path, so it does not
  alter the stereo route being tested here.
- The existing VR branch batching/fence and motion/depth handoff work remains
  included in the rebuilt CommunityShaders.dll.
- The DLL is an optimized Release build compiled with the local VS2022 toolset.

This is still an experimental VR preview. It does not claim a performance gain
until a headset A/B run records real application frame time, GPU frame time,
refresh rate, and neural evaluation/frame-delivery evidence.

No Feeder, RenoDX, ReShade wrapper, DLSS5 bridge executable, or proprietary
NVIDIA/Streamline runtime DLL is included. Those are intentionally separate so
this package can be disabled as one MO2 mod without changing the base MGO
profile or the physical Skyrim VR folder.
"@
[System.IO.File]::WriteAllText((Join-Path $stage 'CHANGELOG.md'), $changelog.Trim() + [Environment]::NewLine, [System.Text.UTF8Encoding]::new($false))

$thirdParty = @"
THIRD-PARTY DEPENDENCIES

The public package deliberately does not redistribute NVIDIA-signed runtime
binaries or the unofficial Ada patch. Obtain them only from an authorized
source, verify the signature and SHA-256 where applicable, and never use random
DLL mirrors.

Required neural runtime:
- Path: Shaders/Upscaling/Streamline/nvngx_dlssnr.dll
- Version: 310.8.0.0
- SHA-256: E16BCF15E16E13F527491CDF7845B2FE6521A738D8F7C9C721866A8496E1FC8E
- Authorized distribution starting point: https://github.com/RankFTW/RHI/releases

The normal DLSS/Streamline files can normally be obtained from the user's
existing MGO/CSX installation. Exact tested versions and hashes are recorded
in DLSSNR-manifest.json. NVIDIA Streamline releases are here:
https://github.com/NVIDIA-RTX/Streamline/releases

Verify a DLL in PowerShell before using it:
Get-AuthenticodeSignature .\nvngx_dlssnr.dll
Get-FileHash .\nvngx_dlssnr.dll -Algorithm SHA256

The signature should report Valid and NVIDIA Corporation. Do not enable this
preview alongside CSX, the CSX VR shader cache, the older DX11 bridge, RenoDX
Feeder, or a ReShade DLSS5 wrapper.

RTX 40 Ada path:
- Obtain the authorized Ada-patched nvngx_dlssnr.dll from the RenoDX Discord
  #dlss5 pinned source: https://discord.com/channels/1408098019194310818/1542647972695904317
- Keep the file named nvngx_dlssnr.dll and run TOOLS/Install-DLSSNRAdaRuntime.cmd.
- For the universal SM75/SM86/SM89/SM120 file, run
  TOOLS/Install-DLSSNRUniversalRuntime.cmd instead.
- The patch may invalidate Authenticode; the helper records that state and
  requires typing ADA (Ada launcher) or UNIVERSAL (four-architecture launcher)
  before installation. The normal Streamline DLLs still must be signed NVIDIA
  files.
"@
[System.IO.File]::WriteAllText((Join-Path $stage 'THIRD-PARTY-DOWNLOADS.md'), $thirdParty.Trim() + [Environment]::NewLine, [System.Text.UTF8Encoding]::new($false))

$licenses = Join-Path $stage 'LICENSES'
New-Item -ItemType Directory -Force -Path $licenses | Out-Null
Copy-Item -LiteralPath (Join-Path $PSScriptRoot '..\vendor\open-shaders-dlssnr-vr-091bfb4d\COPYING') -Destination (Join-Path $licenses 'Open-Shaders-GPL-3.0.txt')

$tools = Join-Path $stage 'TOOLS'
New-Item -ItemType Directory -Force -Path $tools | Out-Null
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'Install-DLSSNRRuntime.ps1') -Destination (Join-Path $tools 'Install-DLSSNRRuntime.ps1')
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'Install-DLSSNRRuntime.cmd') -Destination (Join-Path $tools 'Install-DLSSNRRuntime.cmd')
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'Install-DLSSNRAdaRuntime.cmd') -Destination (Join-Path $tools 'Install-DLSSNRAdaRuntime.cmd')
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'Install-DLSSNRUniversalRuntime.cmd') -Destination (Join-Path $tools 'Install-DLSSNRUniversalRuntime.cmd')

$fomod = Join-Path $stage 'fomod'
New-Item -ItemType Directory -Force -Path $fomod | Out-Null
$info = @"
<?xml version="1.0" encoding="UTF-8"?>
<fomod>
  <Name>DLSSNR for MGO Skyrim VR - Experimental Preview</Name>
  <Author>DLSS5 SkyrimVR prototype contributors</Author>
  <Version>$Version</Version>
  <Website>https://github.com/YtzyFvra/skyrim-community-shaders</Website>
  <Description><![CDATA[Experimental Open Shaders DLSS Neural Rendering VR payload for a separate MGO MO2 profile. External NVIDIA runtime dependencies are not bundled.]]></Description>
</fomod>
"@
[System.IO.File]::WriteAllText((Join-Path $fomod 'info.xml'), $info.Trim() + [Environment]::NewLine, [System.Text.UTF8Encoding]::new($false))
$config = @"
<?xml version="1.0" encoding="UTF-8"?>
<config xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:noNamespaceSchemaLocation="http://qconsulting.ca/fo3/ModConfig5.0.xsd">
  <moduleName>DLSSNR for MGO Skyrim VR - Experimental Preview</moduleName>
  <installSteps order="Explicit">
    <installStep name="Core payload">
      <optionalFileGroups order="Explicit">
        <group name="Install the DLSSNR preview payload" type="SelectExactlyOne">
          <plugins order="Explicit">
            <plugin name="Install core payload">
              <description>Installs the isolated Open Shaders DLSSNR VR build. Disable conflicting CSX/DLSS wrappers in the test profile.</description>
              <files>
                <file source="00 - DLSSNR Core" destination="" />
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
    IncludedFiles = $included.Count
    ExternalDependencies = $external.Count
    CommunityShadersSHA256 = $sourceHash
    Variant = 'public-mo2-fomod-vr-only (NVIDIA/Streamline DLLs intentionally omitted)'
} | Format-List
