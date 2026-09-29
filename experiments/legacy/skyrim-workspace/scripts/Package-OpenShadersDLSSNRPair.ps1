[CmdletBinding()]
param(
    [ValidatePattern('^\d+\.\d+\.\d+$')]
    [string]$Version = '2.14.1',
    [Alias('PublicAioSource', 'LocalSource')]
    [string]$AioSource,
    [string]$NeuralRuntimePath,
    [string]$StreamlineRuntimeSource,
    [string]$OutputRoot,
    [string]$ImGuiVRHelperPath,
    [switch]$Force
)

$ErrorActionPreference = 'Stop'

$projectRoot = Split-Path -Parent $PSScriptRoot
$sourceWorktree = Join-Path $projectRoot 'work\open-shaders-2.12.0-open-nr'
$knownGoodRuntime = Join-Path $projectRoot 'vendor\streamline\streamline'
$imguiVRHelperVersion = '1.7.0'
$imguiVRHelperVendorRoot = Join-Path $projectRoot 'vendor\imgui-vr-helper\1.7.0'
$displayName = "OpenNR $Version"

if ([string]::IsNullOrWhiteSpace($AioSource)) {
    $AioSource = Join-Path $sourceWorktree "build\OpenNR-$Version\aio"
}
if ([string]::IsNullOrWhiteSpace($NeuralRuntimePath)) {
    $NeuralRuntimePath = Join-Path $knownGoodRuntime 'nvngx_dlssnr.dll'
}
if ([string]::IsNullOrWhiteSpace($StreamlineRuntimeSource)) {
    $StreamlineRuntimeSource = $knownGoodRuntime
}
if ([string]::IsNullOrWhiteSpace($OutputRoot)) {
    $OutputRoot = Join-Path $projectRoot "dist\OpenNR-$Version"
}
if ([string]::IsNullOrWhiteSpace($ImGuiVRHelperPath)) {
    $ImGuiVRHelperPath = Join-Path $imguiVRHelperVendorRoot 'SKSE\Plugins\imgui-vr-helper.dll'
}

$archivePath = Join-Path $OutputRoot "$displayName.7z"
$neuralRuntimeHashExpected = 'E16BCF15E16E13F527491CDF7845B2FE6521A738D8F7C9C721866A8496E1FC8E'
$imguiVRHelperHashExpected = 'BF2941D4513A37D526D37FD8BF657823E3DBF2C31A085ED28C6EE224C828EBA6'
$terrainHelperHashExpected = '937B23941750CD871CE8759C15A982CDE40EA354E0C3BC793516949604CA5171'

function Write-Utf8NoBom([string]$Path, [string]$Contents) {
    $encoding = [System.Text.UTF8Encoding]::new($false)
    [System.IO.File]::WriteAllText($Path, $Contents.Trim() + [Environment]::NewLine, $encoding)
}

function Assert-File([string]$Path, [string]$Description) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "$Description was not found: $Path"
    }
}

function Test-Win64Dll([string]$Path) {
    $bytes = [System.IO.File]::ReadAllBytes($Path)
    if ($bytes.Length -lt 0x40 -or $bytes[0] -ne 0x4d -or $bytes[1] -ne 0x5a) {
        return $false
    }
    $peOffset = [BitConverter]::ToInt32($bytes, 0x3c)
    if ($peOffset -lt 0 -or $peOffset + 6 -gt $bytes.Length) {
        return $false
    }
    if ($bytes[$peOffset] -ne 0x50 -or $bytes[$peOffset + 1] -ne 0x45 -or $bytes[$peOffset + 2] -ne 0 -or $bytes[$peOffset + 3] -ne 0) {
        return $false
    }
    return ([BitConverter]::ToUInt16($bytes, $peOffset + 4) -eq 0x8664)
}

function Test-ExcludedPayload([string]$RelativePath) {
    $path = $RelativePath.Replace('/', '\').ToLowerInvariant()
    if ($path -eq 'skse\plugins\communityshaders.pdb') { return $true }
    if ($path.StartsWith('renderdoc\')) { return $true }
    if ($path -eq 'shaders\features\renderdoc.ini') { return $true }
    if ($path.StartsWith('shaders\renderdoc\')) { return $true }
    if ($path.StartsWith('openxr\')) { return $true }
    if ($path.StartsWith('textures\')) { return $true }
    if ($path.StartsWith('meshes\')) { return $true }
    if ($path.StartsWith('particlelights\')) { return $true }
    if ($path.StartsWith('shaders\upscaling\streamlinedx12\')) { return $true }
    if ($path.StartsWith('shaders\upscaling\fidelityfx\')) { return $true }
    return $false
}

function Copy-Tree([string]$Source, [string]$Destination) {
    Assert-File (Join-Path $Source 'SKSE\Plugins\CommunityShaders.dll') 'OpenNR AIO CommunityShaders.dll'
    New-Item -ItemType Directory -Force -Path $Destination | Out-Null
    foreach ($file in (Get-ChildItem -LiteralPath $Source -Recurse -File)) {
        $relative = $file.FullName.Substring($Source.Length).TrimStart('\')
        if (Test-ExcludedPayload $relative) {
            continue
        }
        $targetPath = Join-Path $Destination $relative
        New-Item -ItemType Directory -Force -Path (Split-Path -Parent $targetPath) | Out-Null
        Copy-Item -LiteralPath $file.FullName -Destination $targetPath -Force
    }
}

function Copy-FileInto([string]$Source, [string]$DestinationRoot, [string]$RelativePath) {
    Assert-File $Source 'Required package file'
    $destination = Join-Path $DestinationRoot $RelativePath
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $destination) | Out-Null
    Copy-Item -LiteralPath $Source -Destination $destination -Force
}

function Write-ThirdPartyNotices([string]$PackageRoot) {
    $noticeRoot = Join-Path $PackageRoot 'ThirdParty\imgui-vr-helper'
    New-Item -ItemType Directory -Force -Path $noticeRoot | Out-Null
    foreach ($name in @('COPYING', 'EXCEPTIONS.md', 'NOTICE.txt')) {
        Copy-Item -LiteralPath (Join-Path $imguiVRHelperVendorRoot $name) -Destination (Join-Path $noticeRoot $name) -Force
    }
}

function Add-NativeRuntimeSet([string]$PayloadRoot) {
    $systemRoot = [Environment]::SystemDirectory
    $crtNames = @('MSVCP140.dll', 'MSVCP140_ATOMIC_WAIT.dll', 'VCOMP140.DLL', 'VCRUNTIME140.dll', 'VCRUNTIME140_1.dll')
    foreach ($name in $crtNames) {
        $source = Join-Path $systemRoot $name
        Assert-File $source "Microsoft x64 runtime $name"
        if (-not (Test-Win64Dll $source)) {
            throw "The Microsoft runtime is not a valid x64 DLL: $source"
        }
        $signature = Get-AuthenticodeSignature -LiteralPath $source
        if ($signature.Status -ne 'Valid' -or -not $signature.SignerCertificate -or $signature.SignerCertificate.Subject -notmatch 'Microsoft') {
            throw "Microsoft runtime signature validation failed: $source"
        }
        Copy-FileInto $source $PayloadRoot ("Shaders\Upscaling\Streamline\$name")
        Copy-FileInto $source $PayloadRoot ("SKSE\Plugins\$name")
    }

    Assert-File $NeuralRuntimePath 'Stock RTX 50 DLSSNR runtime'
    if ((Get-Item -LiteralPath $NeuralRuntimePath).Name -ne 'nvngx_dlssnr.dll') {
        throw "The neural runtime must be named nvngx_dlssnr.dll: $NeuralRuntimePath"
    }
    if (-not (Test-Win64Dll $NeuralRuntimePath)) {
        throw "The neural runtime is not a valid x64 DLL: $NeuralRuntimePath"
    }
    $neuralHash = (Get-FileHash -LiteralPath $NeuralRuntimePath -Algorithm SHA256).Hash
    if ($neuralHash -ne $neuralRuntimeHashExpected) {
        throw "Unexpected stock RTX 50 DLSSNR runtime hash: $neuralHash"
    }
    $neuralSignature = Get-AuthenticodeSignature -LiteralPath $NeuralRuntimePath
    if ($neuralSignature.Status -ne 'Valid' -or -not $neuralSignature.SignerCertificate -or $neuralSignature.SignerCertificate.Subject -notmatch 'NVIDIA') {
        throw "Stock DLSSNR runtime signature validation failed: $NeuralRuntimePath"
    }
    Copy-FileInto $NeuralRuntimePath $PayloadRoot 'Shaders\Upscaling\Streamline\nvngx_dlssnr.dll'
}

function Add-StreamlineRuntimeSet([string]$PayloadRoot) {
    $runtimeNames = @('nvngx_dlss.dll', 'sl.common.dll', 'sl.dlss.dll', 'sl.interposer.dll', 'sl.pcl.dll', 'sl.reflex.dll')
    foreach ($name in $runtimeNames) {
        $destinationRelative = "Shaders\Upscaling\Streamline\$name"
        $source = Join-Path $StreamlineRuntimeSource $name
        if (Test-Path -LiteralPath $source -PathType Leaf) {
            Copy-FileInto $source $PayloadRoot $destinationRelative
        }
        else {
            Assert-File (Join-Path $PayloadRoot $destinationRelative) "Native Streamline runtime $name"
        }
    }
}

function Assert-Payload([string]$PayloadRoot) {
    $required = @(
        'SKSE\Plugins\CommunityShaders.dll',
        'SKSE\Plugins\imgui-vr-helper.dll',
        'TerrainHelper.esp',
        'Shaders\Features\TerrainHelper.ini',
        'Shaders\Features\OpenNRCapture.ini',
        'Shaders\Upscaling\Streamline\nvngx_dlss.dll',
        'Shaders\Upscaling\Streamline\nvngx_dlssnr.dll',
        'Shaders\Upscaling\Streamline\sl.common.dll',
        'Shaders\Upscaling\Streamline\sl.dlss.dll',
        'Shaders\Upscaling\Streamline\sl.interposer.dll',
        'Shaders\Upscaling\Streamline\sl.pcl.dll',
        'Shaders\Upscaling\Streamline\sl.reflex.dll',
        'Shaders\Upscaling\Streamline\MSVCP140.dll',
        'Shaders\Upscaling\Streamline\MSVCP140_ATOMIC_WAIT.dll',
        'Shaders\Upscaling\Streamline\VCOMP140.DLL',
        'Shaders\Upscaling\Streamline\VCRUNTIME140.dll',
        'Shaders\Upscaling\Streamline\VCRUNTIME140_1.dll',
        'SKSE\Plugins\MSVCP140.dll',
        'SKSE\Plugins\MSVCP140_ATOMIC_WAIT.dll',
        'SKSE\Plugins\VCOMP140.DLL',
        'SKSE\Plugins\VCRUNTIME140.dll',
        'SKSE\Plugins\VCRUNTIME140_1.dll'
    )
    foreach ($relative in $required) {
        Assert-File (Join-Path $PayloadRoot $relative) "Required OpenNR payload $relative"
    }

    foreach ($dllName in @('SKSE\Plugins\CommunityShaders.dll', 'SKSE\Plugins\imgui-vr-helper.dll')) {
        $dll = Join-Path $PayloadRoot $dllName
        if (-not (Test-Win64Dll $dll)) {
            throw "Not a valid x64 DLL: $dll"
        }
    }
    $dll = Join-Path $PayloadRoot 'SKSE\Plugins\CommunityShaders.dll'
    $dllVersion = (Get-Item -LiteralPath $dll).VersionInfo.FileVersion
    if ($dllVersion -ne "$Version.0") {
        throw "Package version $Version does not match CommunityShaders.dll version $dllVersion"
    }
    $dllBytes = [System.IO.File]::ReadAllBytes($dll)
    $binaryText = [System.Text.Encoding]::ASCII.GetString($dllBytes)
    foreach ($marker in @('OpenNR Capture', 'frames.jsonl', 'Nasal Convergence 70%')) {
        if (-not $binaryText.Contains($marker)) {
            throw "CommunityShaders.dll is missing the required OpenNR marker: $marker"
        }
    }

    $captureIni = Get-Content -LiteralPath (Join-Path $PayloadRoot 'Shaders\Features\OpenNRCapture.ini') -Raw
    if (-not $captureIni.Contains('Beta = True')) {
        throw 'OpenNR Capture registration must remain visibly beta/opt-in.'
    }
    $captureHeader = Join-Path $sourceWorktree 'src\Features\OpenNRCapture.h'
    $captureImpl = Join-Path $sourceWorktree 'src\Features\OpenNRCapture.cpp'
    Assert-File $captureHeader 'OpenNR Capture source header'
    Assert-File $captureImpl 'OpenNR Capture source implementation'
    $headerText = Get-Content -LiteralPath $captureHeader -Raw
    $implText = Get-Content -LiteralPath $captureImpl -Raw
    if (-not $headerText.Contains('bool enableCapture = false;')) {
        throw 'OpenNR Capture no longer has a default-off master gate.'
    }
    if (-not $implText.Contains('settings = Settings{};')) {
        throw 'OpenNR Capture default restoration is not source-auditable.'
    }
    if (-not $implText.Contains('frames.jsonl')) {
        throw 'OpenNR Capture writer marker is missing from source.'
    }

    $helper = Join-Path $PayloadRoot 'SKSE\Plugins\imgui-vr-helper.dll'
    $helperVersion = (Get-Item -LiteralPath $helper).VersionInfo.FileVersion
    if ($helperVersion -ne "$imguiVRHelperVersion.0") {
        throw "Expected ImGuiVRHelper v$imguiVRHelperVersion, got $helperVersion"
    }
    $helperHash = (Get-FileHash -LiteralPath $helper -Algorithm SHA256).Hash
    if ($helperHash -ne $imguiVRHelperHashExpected) {
        throw "Unexpected ImGuiVRHelper SHA-256: $helperHash"
    }

    $terrain = Join-Path $PayloadRoot 'TerrainHelper.esp'
    $terrainFile = Get-Item -LiteralPath $terrain
    $terrainHash = (Get-FileHash -LiteralPath $terrain -Algorithm SHA256).Hash
    if ($terrainFile.Length -ne 194 -or $terrainHash -ne $terrainHelperHashExpected) {
        throw "Unexpected TerrainHelper.esp payload: $($terrainFile.Length) bytes / $terrainHash"
    }

    $unexpectedExcluded = @(
        foreach ($file in (Get-ChildItem -LiteralPath $PayloadRoot -Recurse -File)) {
            $relative = $file.FullName.Substring($PayloadRoot.Length).TrimStart('\')
            if (Test-ExcludedPayload $relative) { $relative }
        }
    )
    if ($unexpectedExcluded.Count -gt 0) {
        throw "Unified OpenNR package contains excluded optional payload: $($unexpectedExcluded -join ', ')"
    }
    if (@(Get-ChildItem -LiteralPath $PayloadRoot -Recurse -File -Filter 'SettingsUser.json').Count -gt 0) {
        throw 'Fresh-install packages must not include personal SettingsUser.json overrides.'
    }

    [pscustomobject]@{
        FileCount = @(Get-ChildItem -LiteralPath $PayloadRoot -Recurse -File).Count
        DllCount = @(Get-ChildItem -LiteralPath $PayloadRoot -Recurse -File -Filter '*.dll').Count
        PayloadBytes = ((Get-ChildItem -LiteralPath $PayloadRoot -Recurse -File | Measure-Object -Property Length -Sum).Sum)
        CommunityShadersSHA256 = (Get-FileHash -LiteralPath $dll -Algorithm SHA256).Hash
        ImGuiVRHelperSHA256 = $helperHash
        NeuralRuntimeSHA256 = (Get-FileHash -LiteralPath (Join-Path $PayloadRoot 'Shaders\Upscaling\Streamline\nvngx_dlssnr.dll') -Algorithm SHA256).Hash
    }
}

function Write-Metadata([string]$PackageRoot, [string]$PayloadFolderName) {
    $payloadRoot = Join-Path $PackageRoot $PayloadFolderName
    $meta = @"
[General]
gameName=SkyrimVR
modid=0
version=$Version
newestVersion=$Version
category=-1,
nexusFileStatus=0
installationFile=$displayName
repository=https://github.com/olekspa/OpenNR
comments=Unified OpenNR Neural Rendering package with the audited native Skyrim VR DLSS/DLSSNR/Reflex/PCL route, ImGuiVRHelper, TerrainHelper, and integrated OpenNR Capture.
notes=Install as one MO2 mod. OpenNR Capture is included but remains disabled by default until explicitly enabled in its menu/settings. The CommunityShaders.dll filename and SKSE compatibility layout are retained intentionally.
"@
    Write-Utf8NoBom (Join-Path $payloadRoot 'meta.ini') $meta

    $fomod = Join-Path $PackageRoot 'fomod'
    New-Item -ItemType Directory -Force -Path $fomod | Out-Null
    $info = @"
<?xml version="1.0" encoding="UTF-8"?>
<fomod>
  <Name>$displayName</Name>
  <Author>OpenNR</Author>
  <Version>$Version</Version>
  <Website>https://github.com/olekspa/OpenNR</Website>
  <Description><![CDATA[Unified OpenNR package with Neural Rendering, VR optimizations, and explicitly opt-in OpenNR Capture.]]></Description>
</fomod>
"@
    Write-Utf8NoBom (Join-Path $fomod 'info.xml') $info
}

function Write-PackageReadme([string]$PackageRoot) {
    $readme = @"
$displayName

This is the single unified OpenNR package. It contains the audited native Skyrim
VR DLSS/DLSSNR/Reflex/PCL runtime set, the OpenNR DLL and shader payload, the
ImGuiVRHelper v$imguiVRHelperVersion menu/input bridge, TerrainHelper, and the
integrated OpenNR Capture feature.

Install exactly this archive through MO2 as one mod. Do not combine it with an
older OpenNR DLSSNR VR archive or a separate OpenNR Capture archive. The package
retains CommunityShaders.dll and SKSE/Plugins/CommunityShaders/ for compatibility
with the upstream Community Shaders/Open Shaders runtime layout.

The in-game settings page formerly labelled DLSS 5 NR is now named Neural
Rendering. It contains the shared Neural Rendering, DLSS, foveation, VR, and
coverage controls. Foveated Rendering remains opt-in.

OpenNR Capture is present in the same package but is disabled by default. The
master Enable capture setting must be explicitly enabled before the
hotkeys ([ start/stop, ] single, \ burst), menu buttons, GPU readbacks, or
frames.jsonl writer can do anything.
It records aligned pre-NR inputs, native Feature 18 depth/motion guides, and
post-NR teacher output for dataset collection and route validation. It never
captures the desktop, headset compositor, or presented swap chain. Typed raw
data and JSONL metadata are authoritative; PNGs are optional previews.

Capture can be expensive and can consume substantial disk space. Use a dedicated
output directory, keep both eyes enabled for stereo validation, and audit every
sequence before training. Capture artifacts do not establish live VR quality,
temporal stability, or frame-budget acceptance.

The native Feature 18 route continues to require Skyrim VR/SKSE, Address Library,
a working SteamVR/OpenComposite runtime, a compatible NVIDIA driver/GPU, and the
normal surrounding mod stack. This package does not replace those prerequisites.

The package contains no personal SettingsUser.json. Existing settings are
preserved by the installation, so review the OpenNR Capture page after install
if an older profile had deliberately saved capture settings.
"@
    Write-Utf8NoBom (Join-Path $PackageRoot 'README.txt') $readme
}

function Write-PackageAudit([string]$PackageRoot, [string]$PayloadRoot, [string]$Source) {
    $includedFiles = @(Get-ChildItem -LiteralPath $PayloadRoot -Recurse -File)
    $includedBytes = ($includedFiles | Measure-Object -Property Length -Sum).Sum
    $sourceFiles = @(Get-ChildItem -LiteralPath $Source -Recurse -File)
    $excludedFiles = @($sourceFiles | Where-Object {
        $relative = $_.FullName.Substring($Source.Length).TrimStart('\')
        Test-ExcludedPayload $relative
    })
    $excludedBytes = ($excludedFiles | Measure-Object -Property Length -Sum).Sum
    $largest = $includedFiles | Sort-Object Length -Descending | Select-Object -First 20
    $lines = [System.Collections.Generic.List[string]]::new()
    $lines.Add("$displayName package audit")
    $lines.Add('========================')
    $lines.Add('Package contract: one unified OpenNR payload; OpenNR Capture included and default-off')
    $lines.Add("Source AIO: $Source")
    $lines.Add("Included payload files: $($includedFiles.Count)")
    $lines.Add("Included payload bytes: $includedBytes")
    $lines.Add("Excluded optional source files: $($excludedFiles.Count)")
    $lines.Add("Excluded optional source bytes: $excludedBytes")
    $lines.Add('')
    $lines.Add('Excluded by the lean native Skyrim VR contract:')
    $lines.Add('- RenderDoc payload and registration')
    $lines.Add('- OpenXR eye-tracking payload')
    $lines.Add('- textures, meshes, and particle-light trees')
    $lines.Add('- StreamlineDX12 runtime tree')
    $lines.Add('- FidelityFX runtime tree')
    $lines.Add('- CommunityShaders.pdb')
    $lines.Add('')
    $lines.Add('Largest included files:')
    foreach ($file in $largest) {
        $relative = $file.FullName.Substring($PayloadRoot.Length).TrimStart('\')
        $lines.Add(("{0,14} {1}" -f $file.Length, $relative))
    }
    $lines.Add('')
    $lines.Add('Runtime/provenance checks:')
    $lines.Add('- CommunityShaders.dll version matches the package version')
    $lines.Add('- stock signed RTX 50 nvngx_dlssnr.dll hash pinned by the packaging validator')
    $lines.Add('- Streamline 2.13 native Skyrim route retained; StreamlineDX12 omitted')
    $lines.Add('- OpenNR Capture source default gate is bool enableCapture = false')
    $lines.Add('- no SettingsUser.json shipped')
    Write-Utf8NoBom (Join-Path $PackageRoot 'OpenNR-PACKAGE-AUDIT.txt') ($lines -join [Environment]::NewLine)
}

$sevenZipCommand = Get-Command 7z.exe -ErrorAction SilentlyContinue
$sevenZip = if ($sevenZipCommand) { $sevenZipCommand.Source } else { 'C:\Program Files\7-Zip\7z.exe' }
Assert-File $sevenZip '7-Zip executable'
foreach ($path in @($AioSource, $NeuralRuntimePath, $ImGuiVRHelperPath)) {
    if (-not (Test-Path -LiteralPath $path)) {
        throw "Required packaging input was not found: $path"
    }
}
foreach ($name in @('COPYING', 'EXCEPTIONS.md', 'NOTICE.txt')) {
    Assert-File (Join-Path $imguiVRHelperVendorRoot $name) "ImGuiVRHelper license/notice $name"
}

if (Test-Path -LiteralPath $archivePath -PathType Leaf) {
    if (-not $Force) {
        throw "Canonical archive already exists; pass -Force to replace this exact file: $archivePath"
    }
    Remove-Item -LiteralPath $archivePath -Force
}
New-Item -ItemType Directory -Force -Path $OutputRoot | Out-Null
$stageRoot = Join-Path $OutputRoot ('.package-opennr-' + [guid]::NewGuid().ToString('N'))
$packageRoot = Join-Path $stageRoot 'OpenNR'
$payloadFolderName = "00 - $displayName"
$payloadRoot = Join-Path $packageRoot $payloadFolderName
New-Item -ItemType Directory -Force -Path $payloadRoot | Out-Null

try {
    Copy-Tree $AioSource $payloadRoot
    Copy-FileInto $ImGuiVRHelperPath $payloadRoot 'SKSE\Plugins\imgui-vr-helper.dll'
    Add-NativeRuntimeSet $payloadRoot
    Add-StreamlineRuntimeSet $payloadRoot
    $payloadSummary = Assert-Payload $payloadRoot
    Write-Metadata $packageRoot $payloadFolderName
    Write-PackageReadme $packageRoot
    Write-PackageAudit $packageRoot $payloadRoot $AioSource
    Write-ThirdPartyNotices $packageRoot

    Push-Location $packageRoot
    try {
        & $sevenZip a -t7z -mx=5 -mmt=on $archivePath '*' | Out-Null
        if ($LASTEXITCODE -ne 0) {
            throw "7-Zip failed for $displayName with exit code $LASTEXITCODE"
        }
    }
    finally {
        Pop-Location
    }

    [pscustomobject]@{
        Name = $displayName
        Archive = $archivePath
        ArchiveSHA256 = (Get-FileHash -LiteralPath $archivePath -Algorithm SHA256).Hash
        ArchiveBytes = (Get-Item -LiteralPath $archivePath).Length
        PayloadFiles = $payloadSummary.FileCount
        PayloadDlls = $payloadSummary.DllCount
        PayloadBytes = $payloadSummary.PayloadBytes
        CommunityShadersSHA256 = $payloadSummary.CommunityShadersSHA256
        ImGuiVRHelperSHA256 = $payloadSummary.ImGuiVRHelperSHA256
        NeuralRuntimeSHA256 = $payloadSummary.NeuralRuntimeSHA256
        OpenNRCapture = $true
        CaptureDefault = $false
    }
}
finally {
    if (Test-Path -LiteralPath $stageRoot) {
        $resolvedStage = [System.IO.Path]::GetFullPath($stageRoot)
        $resolvedOutput = [System.IO.Path]::GetFullPath($OutputRoot).TrimEnd('\') + '\'
        if (-not $resolvedStage.StartsWith($resolvedOutput, [StringComparison]::OrdinalIgnoreCase)) {
            throw "Package cleanup escaped the output directory: $resolvedStage"
        }
        Remove-Item -LiteralPath $stageRoot -Recurse -Force
    }
}
