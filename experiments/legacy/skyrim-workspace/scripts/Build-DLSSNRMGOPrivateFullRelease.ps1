[CmdletBinding()]
param(
    [string]$AioSource,
    [string]$NeuralRuntimePath,
    [string]$OutputRoot,
	[string]$Version = '0.5.2-mgo-vr.1-private-dev',
    [switch]$DlssNrOnly,
    [switch]$LeanFullVr,
    [switch]$AllowDirtySource,
    [switch]$OmitVCRuntime,
    [switch]$Force
)

$ErrorActionPreference = 'Stop'
if ($DlssNrOnly -and $LeanFullVr) {
    throw 'Choose either -DlssNrOnly or -LeanFullVr; the packaging profiles are mutually exclusive.'
}
$projectRoot = Split-Path -Parent $PSScriptRoot
$sourceRepo = Join-Path $projectRoot 'vendor\open-shaders-dlssnr-vr-091bfb4d'
$usingDefaultAioSource = [string]::IsNullOrWhiteSpace($AioSource)
if ($usingDefaultAioSource) {
    # Dev-Fast is the release-capable DLSSNR/VR configuration in this checkout;
    # ALL-VS2022 may contain a stale AIO tree when unrelated FidelityFX targets
    # prevent the full solution from linking. Pass -AioSource explicitly to use
    # another verified build tree.
    $AioSource = Join-Path $sourceRepo 'build\Dev-Fast\aio'
}
if ([string]::IsNullOrWhiteSpace($NeuralRuntimePath)) {
    $NeuralRuntimePath = Join-Path $projectRoot 'vendor\streamline\streamline\nvngx_dlssnr.dll'
}
if ([string]::IsNullOrWhiteSpace($OutputRoot)) {
    $OutputRoot = Join-Path $projectRoot 'dist'
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

function Test-BinaryContainsAscii([string]$path, [string]$text) {
    $bytes = [System.IO.File]::ReadAllBytes($path)
    $needle = [System.Text.Encoding]::ASCII.GetBytes($text)
    if ($needle.Length -eq 0 -or $needle.Length -gt $bytes.Length) { return $false }
    for ($offset = 0; $offset -le $bytes.Length - $needle.Length; $offset++) {
        $match = $true
        for ($index = 0; $index -lt $needle.Length; $index++) {
            if ($bytes[$offset + $index] -ne $needle[$index]) {
                $match = $false
                break
            }
        }
        if ($match) { return $true }
    }
    return $false
}

$vcRuntimeNames = @(
    'MSVCP140.dll'
    'MSVCP140_ATOMIC_WAIT.dll'
    'VCRUNTIME140.dll'
    'VCRUNTIME140_1.dll'
    'VCOMP140.DLL'
)
$vcRuntimeFiles = @()
if (-not $OmitVCRuntime) {
    $systemDirectory = [Environment]::SystemDirectory
    foreach ($name in $vcRuntimeNames) {
        $path = Join-Path $systemDirectory $name
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
            throw "Required x64 MSVC runtime was not found: $path"
        }
        if (-not (Test-Win64Dll $path)) {
            throw "The MSVC runtime is not a valid x64 Windows DLL: $path"
        }
        $signature = Get-AuthenticodeSignature -LiteralPath $path
        if ($signature.Status -ne 'Valid' -or $signature.SignerCertificate.Subject -notmatch 'Microsoft') {
            throw "MSVC runtime signature validation failed: $path status=$($signature.Status), signer=$($signature.SignerCertificate.Subject)"
        }
        $vcRuntimeFiles += [pscustomobject]@{ Name = $name; Path = $path }
    }
}

function Test-Excluded([string]$relativePath) {
    $path = $relativePath.ToLowerInvariant()
    if ($path.StartsWith('renderdoc/')) { return $true }
    if ($path.StartsWith('textures/')) { return $true }
    if ($path.StartsWith('meshes/')) { return $true }
    if ($path.StartsWith('particlelights/')) { return $true }
    if ($path -eq 'terrainhelper.esp') { return $true }
    if (($DlssNrOnly -or $LeanFullVr) -and $path -eq 'skse/plugins/communityshaders.pdb') { return $true }
    if ($DlssNrOnly -and $path -match '^shaders/upscaling/(fidelityfx|streamlinedx12)/.*\.dll$') { return $true }
    if ($LeanFullVr -and $path.StartsWith('shaders/upscaling/streamlinedx12/')) { return $true }
    if ($LeanFullVr -and $path -eq 'shaders/upscaling/fidelityfx/amd_fidelityfx_framegeneration_dx12.dll') { return $true }
    return $false
}

function Get-DllRecord([string]$path, [string]$relativePath, [string]$role) {
    $file = Get-Item -LiteralPath $path
    $signature = Get-AuthenticodeSignature -LiteralPath $path
    [ordered]@{
        Path = $relativePath
        Role = $role
        Version = $file.VersionInfo.FileVersion
        Bytes = $file.Length
        SHA256 = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash
        Signature = $signature.Status.ToString()
        Signer = if ($signature.SignerCertificate) { $signature.SignerCertificate.Subject } else { $null }
    }
}

foreach ($required in @($sourceRepo, $AioSource, $NeuralRuntimePath)) {
    if (-not (Test-Path -LiteralPath $required)) {
        throw "Required path was not found: $required"
    }
}

$sourceStatus = @(& git -C $sourceRepo status --porcelain 2>$null)
if ($sourceStatus.Count -gt 0 -and -not $AllowDirtySource) {
    throw "The source checkout is dirty; commit it before making a provenance-clean package:`n$($sourceStatus -join [Environment]::NewLine)"
}
$sourceDirty = $sourceStatus.Count -gt 0
$sourceCommit = (& git -C $sourceRepo rev-parse HEAD 2>$null).Trim()
$sourceBranch = (& git -C $sourceRepo branch --show-current 2>$null).Trim()
$ffxCommit = (& git -C (Join-Path $sourceRepo 'extern\FidelityFX-SDK') rev-parse HEAD 2>$null).Trim()
if (-not $sourceCommit) { throw 'Could not resolve the source commit.' }
if (-not $ffxCommit) { throw 'Could not resolve the FidelityFX SDK submodule commit.' }

$neuralFile = Get-Item -LiteralPath $NeuralRuntimePath
$neuralHashExpected = 'E16BCF15E16E13F527491CDF7845B2FE6521A738D8F7C9C721866A8496E1FC8E'
$neuralHash = (Get-FileHash -LiteralPath $NeuralRuntimePath -Algorithm SHA256).Hash
if ($neuralFile.Name -ne 'nvngx_dlssnr.dll') {
    throw "The stock RTX 50 runtime must be named nvngx_dlssnr.dll; got $($neuralFile.Name)"
}
if (-not (Test-Win64Dll $NeuralRuntimePath)) {
    throw 'The neural runtime is not a valid x64 Windows DLL.'
}
if ($neuralHash -ne $neuralHashExpected) {
    throw "Unexpected stock neural runtime hash: $neuralHash"
}
$neuralSignature = Get-AuthenticodeSignature -LiteralPath $NeuralRuntimePath
if ($neuralSignature.Status -ne 'Valid' -or $neuralSignature.SignerCertificate.Subject -notmatch 'NVIDIA Corporation') {
    throw "Stock neural runtime signature validation failed: status=$($neuralSignature.Status), signer=$($neuralSignature.SignerCertificate.Subject)"
}

$sourceDll = Join-Path $AioSource 'SKSE\Plugins\CommunityShaders.dll'
$sourcePdb = Join-Path $AioSource 'SKSE\Plugins\CommunityShaders.pdb'

# CMake's install tree can lag behind the just-linked target when the AIO
# partition was generated before the final incremental link. For the default
# Dev-Fast tree, refresh the AIO copy from the sibling target when it is newer
# or when only the target contains the current multi-pass UI marker. This keeps
# package metadata and the binary actually shipped in sync.
if ($usingDefaultAioSource) {
    $buildRoot = Split-Path -Parent $AioSource
    $linkedDll = Join-Path $buildRoot 'CommunityShaders.dll'
    $linkedPdb = Join-Path $buildRoot 'CommunityShaders.pdb'
    if (Test-Path -LiteralPath $linkedDll -PathType Leaf) {
        $refreshAio = $false
        if (-not (Test-Path -LiteralPath $sourceDll -PathType Leaf)) {
            $refreshAio = $true
        }
        else {
            $linkedHasMultiPass = Test-BinaryContainsAscii $linkedDll 'Experimental 2x sequential NR'
            $aioHasMultiPass = Test-BinaryContainsAscii $sourceDll 'Experimental 2x sequential NR'
            $refreshAio = $linkedHasMultiPass -and (-not $aioHasMultiPass)
            if (-not $refreshAio) {
                $refreshAio = (Get-Item -LiteralPath $linkedDll).LastWriteTimeUtc -gt (Get-Item -LiteralPath $sourceDll).LastWriteTimeUtc
            }
        }
        if ($refreshAio) {
            New-Item -ItemType Directory -Force -Path (Split-Path -Parent $sourceDll) | Out-Null
            Copy-Item -LiteralPath $linkedDll -Destination $sourceDll -Force
            if (Test-Path -LiteralPath $linkedPdb -PathType Leaf) {
                Copy-Item -LiteralPath $linkedPdb -Destination $sourcePdb -Force
            }
        }
    }
}

if (-not (Test-Path -LiteralPath $sourceDll -PathType Leaf)) { throw "AIO DLL missing: $sourceDll" }
if (-not $DlssNrOnly -and -not $LeanFullVr -and -not (Test-Path -LiteralPath $sourcePdb -PathType Leaf)) { throw "AIO PDB missing: $sourcePdb" }
if (-not (Test-Win64Dll $sourceDll)) { throw 'The rebuilt CommunityShaders.dll is not a valid x64 Windows DLL.' }
if (-not (Test-BinaryContainsAscii $sourceDll 'Experimental sequential NR (screenshot/benchmark)')) {
    throw 'The CommunityShaders.dll does not contain the current sequential NR UI marker; refusing to package a stale binary.'
}
if (-not (Test-BinaryContainsAscii $sourceDll 'Temporal state invalidated after subrect/mode change')) {
    throw 'The CommunityShaders.dll does not contain the crop-transition temporal reset marker; refusing to package a stale binary.'
}
if (-not (Test-BinaryContainsAscii $sourceDll 'modelPercent=')) {
    throw 'The CommunityShaders.dll does not contain the resolution-aware model logging marker; refusing to package a stale binary.'
}
if (-not (Test-BinaryContainsAscii $sourceDll 'resolve=transfer')) {
    throw 'The CommunityShaders.dll does not contain the resolution-aware resolve logging marker; refusing to package a stale binary.'
}
if (-not (Test-BinaryContainsAscii $sourceDll 'Automatically pauses while paused')) {
    throw 'The CommunityShaders.dll does not contain the 0.4.7 map/menu stereo safety gate marker; refusing to package a stale binary.'
}

$resolvedAioSource = (Resolve-Path -LiteralPath $AioSource).Path
$buildDirectory = Split-Path -Parent $resolvedAioSource
$cmakeCachePath = Join-Path $buildDirectory 'CMakeCache.txt'
$buildGenerator = 'Unspecified'
$buildConfiguration = 'Release'
if (Test-Path -LiteralPath $cmakeCachePath -PathType Leaf) {
    foreach ($line in (Get-Content -LiteralPath $cmakeCachePath)) {
        if ($line -match '^CMAKE_GENERATOR(?::[^=]+)?=(.*)$' -and $matches[1]) {
            $buildGenerator = $matches[1]
        }
        elseif ($line -match '^CMAKE_BUILD_TYPE(?::[^=]+)?=(.*)$' -and $matches[1]) {
            $buildConfiguration = $matches[1]
        }
    }
}

$safeVersion = $Version -replace '[^A-Za-z0-9._-]', '-'
$displayVersion = $Version.Split('-')[0]
$mo2ModName = "Open Shaders DLSSNR VR $displayVersion OpenNR"
$runtimeProfile = if ($DlssNrOnly) { 'dlssnr-only-vr' } elseif ($LeanFullVr) { 'lean-full-vr' } else { 'full-aio-vr' }
$archiveProfile = if ($DlssNrOnly) { 'PRIVATE-DLSSNR-ONLY-MO2' } elseif ($LeanFullVr) { 'PRIVATE-LEAN-FULL-VR-MO2' } else { 'PRIVATE-FULL-MO2' }
$manifestName = if ($DlssNrOnly) { 'DLSSNR-MGO-VR-Private-DLSSNR-Only' } elseif ($LeanFullVr) { 'DLSSNR-MGO-VR-Private-Lean-Full-VR' } else { 'DLSSNR-MGO-VR-Private-Full' }
$packageLabel = if ($DlssNrOnly) { 'Private DLSSNR-Only' } elseif ($LeanFullVr) { 'Private Lean Full VR' } else { 'Private Full' }
$manifestFileName = if ($DlssNrOnly) { 'DLSSNR-private-dlssnr-only-manifest.json' } elseif ($LeanFullVr) { 'DLSSNR-private-lean-full-vr-manifest.json' } else { 'DLSSNR-private-full-manifest.json' }
New-Item -ItemType Directory -Force -Path $OutputRoot | Out-Null
$archive = Join-Path $OutputRoot "$mo2ModName.7z"
if (Test-Path -LiteralPath $archive) {
    if (-not $Force) { throw "Output already exists; use -Force to replace this exact archive: $archive" }
    Remove-Item -LiteralPath $archive -Force
}

$stage = Join-Path $OutputRoot ('.staging-DLSSNR-private-full-' + [guid]::NewGuid().ToString('N'))
$core = Join-Path $stage '00 - DLSSNR Core'
New-Item -ItemType Directory -Force -Path $core | Out-Null

try {
    foreach ($file in (Get-ChildItem -LiteralPath $AioSource -Recurse -File)) {
        $relative = Get-RelativePath $AioSource $file.FullName
        if (Test-Excluded $relative) { continue }
        $destination = Join-Path $core ($relative -replace '/', '\')
        New-Item -ItemType Directory -Force -Path (Split-Path -Parent $destination) | Out-Null
        Copy-Item -LiteralPath $file.FullName -Destination $destination
    }

    $runtimeDestination = Join-Path $core 'Shaders\Upscaling\Streamline\nvngx_dlssnr.dll'
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $runtimeDestination) | Out-Null
    Copy-Item -LiteralPath $NeuralRuntimePath -Destination $runtimeDestination

    if ($vcRuntimeFiles.Count -gt 0) {
        $pluginRuntimeDirectory = Join-Path $core 'SKSE\Plugins'
        $streamlineRuntimeDirectory = Join-Path $core 'Shaders\Upscaling\Streamline'
        foreach ($runtime in $vcRuntimeFiles) {
            Copy-Item -LiteralPath $runtime.Path -Destination (Join-Path $pluginRuntimeDirectory $runtime.Name)
            # Streamline DLLs are loaded from their own directory; keep the
            # same runtime set beside them rather than relying on global VC++.
            Copy-Item -LiteralPath $runtime.Path -Destination (Join-Path $streamlineRuntimeDirectory $runtime.Name)
        }
    }

    $meta = @"
[General]
gameName=SkyrimSE
modid=0
version=$Version
newestVersion=$Version
category=-1,
nexusFileStatus=0
installationFile=$mo2ModName
repository=https://github.com/YtzyFvra/skyrim-community-shaders
comments=Private Open Shaders DLSS Neural Rendering VR developer build for MGO Skyrim VR; $runtimeProfile payload included.
    notes=Install as one MO2 mod in an isolated test profile. This $displayVersion build retains the DLSS/DLSSNR route, optional matched-residual resolve, resolution-aware reduced-resolution resolve, experimental pre-upscale NR, 2x sequential NR benchmark mode, and optional NVAPI VRS. Fresh NR tuning is enabled in the stored defaults; the restart-gated Foveated master switch remains opt-in, with Nasal Convergence 60% and Feather/oval edge masking as the first-run crop/blend defaults. OpenNR Capture is fully opt-in: it defaults off, does not poll the bracket hotkeys, and does not enter renderer capture setup until Enable capture is explicitly checked. DLSSNR-only builds omit FSR, StreamlineDX12, Frame Generation, and debug symbols; lean-full VR builds retain FSR upscaling while omitting StreamlineDX12, Frame Generation, and debug symbols. Do not enable with Community Shaders Expanded, the CSX VR shader cache, RenoDX Feeder, ReShade wrappers, or Frame Generation during the first test.
"@
    [IO.File]::WriteAllText((Join-Path $core 'meta.ini'), $meta.Trim() + [Environment]::NewLine, [Text.UTF8Encoding]::new($false))

    $runtimeRecords = @()
    $runtimeRecords += Get-DllRecord $runtimeDestination 'Shaders/Upscaling/Streamline/nvngx_dlssnr.dll' 'DLSS5 Neural Rendering stock RTX 50 runtime'
    foreach ($file in (Get-ChildItem -LiteralPath (Join-Path $core 'Shaders\Upscaling') -Recurse -File | Where-Object Extension -ieq '.dll' | Sort-Object FullName)) {
        $relative = Get-RelativePath $core $file.FullName
        if ($relative -eq 'Shaders/Upscaling/Streamline/nvngx_dlssnr.dll') { continue }
        if ($vcRuntimeNames -contains $file.Name) { continue }
        $runtimeRecords += Get-DllRecord $file.FullName $relative 'Open Shaders upscaling/frame-generation runtime'
    }
    $vcRuntimeRecords = @()
    foreach ($runtime in $vcRuntimeFiles) {
        $vcRuntimeRecords += Get-DllRecord (Join-Path $core ('SKSE\Plugins\' + $runtime.Name)) ('SKSE/Plugins/' + $runtime.Name) 'Bundled x64 MSVC runtime for CommunityShaders'
        $vcRuntimeRecords += Get-DllRecord (Join-Path $core ('Shaders\Upscaling\Streamline\' + $runtime.Name)) ('Shaders/Upscaling/Streamline/' + $runtime.Name) 'Bundled x64 MSVC runtime for Streamline'
    }
    $runtimeRecords += $vcRuntimeRecords

    $includedCore = @(
        foreach ($file in (Get-ChildItem -LiteralPath $core -Recurse -File | Sort-Object FullName)) {
            $relative = Get-RelativePath $core $file.FullName
            [ordered]@{
                Path = $relative
                Bytes = $file.Length
                SHA256 = (Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash
            }
        }
    )

    $excluded = @(
        'Renderdoc developer tooling and payload'
        'textures, meshes, and ParticleLights generic game-content payloads already supplied by MGO/CSX'
        'TerrainHelper.esp already supplied by MGO/CSX'
        'No Feeder, RenoDX, ReShade, root proxy, or bridge DLL'
    )
    if ($DlssNrOnly) {
        $excluded += @(
            'FidelityFX runtime DLLs (FSR/FSR Frame Generation; not used by the DLSSNR-only MGO VR profile)'
            'StreamlineDX12 runtime DLLs (DLSS-G/Frame Generation path; Frame Generation is disabled for this profile)'
            'CommunityShaders.pdb (private diagnostics only; omitted from the slim runtime package)'
        )
    }
    elseif ($LeanFullVr) {
        $excluded += @(
            'CommunityShaders.pdb (private diagnostics only; omitted from the lean runtime package)'
            'StreamlineDX12 runtime directory (separate DX12/DLSS-G path; not used by the current Skyrim VR route)'
            'FidelityFX Frame Generation DLL (FSR3 frame-generation path; omitted for the VR test package)'
        )
    }
    if ($OmitVCRuntime) {
        $excluded += 'x64 MSVC runtime DLLs (requires a matching installed Microsoft Visual C++ Redistributable)'
    }

$manifest = [ordered]@{
        Name = $manifestName
        DisplayName = $mo2ModName
        Version = $Version
        Variant = 'single-mo2-fomod-private-dev-vr'
        GeneratedUtc = [DateTime]::UtcNow.ToString('o')
        SourceCommit = $sourceCommit
        SourceBranch = $sourceBranch
        SourceDirty = $sourceDirty
        RuntimeProfile = $runtimeProfile
        FidelityFXSubmoduleCommit = $ffxCommit
        DefaultSettings = [ordered]@{
            NeuralRendering = [ordered]@{
                Enabled = $true
                ModelResolutionPercent = 100
                ModelPreset = 'Default'
                Intensity = 2.00
                LocalTone = 2.00
                LocalStructure = 2.00
                SkinStructure = -1.00
                Style = 0
                AutomaticMask = $true
                PreUpscale = $false
                ClassicResolve = $true
                Multipass = $false
            }
            Foveated = [ordered]@{
                FirstRunCropPreset = 'Nasal Convergence 60%'
                FirstRunEdgeBlend = 'Feather (Oval)'
                FeatherWidthPx = 64
                FullEyeResetPreset = 'Full Eye'
                MasterSwitch = 'Opt-in / restart-gated'
            }
            OpenNRCapture = [ordered]@{
                Enabled = $false
                HotkeyPolling = 'Disabled until Enable capture is checked'
                RendererCaptureSetup = 'Skipped until Enable capture is checked'
                GPUReadbackAndWriter = 'Inactive until an explicit capture is started'
            }
        }
        Build = [ordered]@{
            Configuration = $buildConfiguration
            Generator = $buildGenerator
            AioSource = (Get-RelativePath $projectRoot $AioSource)
            CommunityShadersDll = Get-DllRecord $sourceDll 'SKSE/Plugins/CommunityShaders.dll' 'Open Shaders Skyrim plugin'
            CommunityShadersPdb = if ($DlssNrOnly -or $LeanFullVr) { $null } else { [ordered]@{
                Path = 'SKSE/Plugins/CommunityShaders.pdb'
                Bytes = (Get-Item -LiteralPath $sourcePdb).Length
                SHA256 = (Get-FileHash -LiteralPath $sourcePdb -Algorithm SHA256).Hash
            } }
        }
        Target = [ordered]@{
            GPU = 'RTX 50 / SM120 stock neural runtime selected for local RTX 5070 Ti testing'
            VR = $true
            Game = 'Skyrim VR / MGO'
        }
        RuntimeFiles = @($runtimeRecords)
        VCRuntimeBundled = (-not $OmitVCRuntime)
        VCRuntimeFiles = @($vcRuntimeRecords)
        IncludedCoreFiles = @($includedCore)
        Excluded = $excluded
        Acceptance = @(
            'Archive and file hashes are validated before handoff.'
            'Compilation and package integrity do not prove Skyrim VR loader, NGX Feature 18, two-eye delivery, or headset frame-time acceptance.'
            'NVAPI VRS is included as an optional default-off feature; it requires an NVIDIA driver exposing variable pixel rate shading and is not enabled by package installation.'
            'Fresh NR defaults: enabled, Default model preset, Full (100%) model resolution, classic bounded resolve, pre-upscale NR off, intensity 2.00, local tone/local structure 2.00, skin structure -1.00, Style Default (numeric style 0), Automatic Mask on. Fresh foveated presets select Nasal Convergence 60% with Feather and the oval edge mask when the restart-gated Foveated master switch is enabled; Center 75%, Nasal Convergence 50%, and Full Eye remain available.'
            'Reduced-resolution resolve is now resolution-aware: 90%/85% retain a much stronger bounded Feature 18 contribution, 75% is intermediate, and 50%/33% remain conservative for artifact control.'
            'Matched Residual is an optional reduced-resolution path using exact-area model input and conservative residual composition; it is not enabled by package installation.'
            'Experimental pre-upscale NR is optional, full-eye-only for VR, disabled with HDR/Frame Generation, and falls back to post-upscale NR when its native stereo guide contract is unavailable. DLSS Ray Reconstruction must be disabled for this experiment.'
            'Experimental 2x sequential NR is optional and off by default. It uses separate per-eye/per-stage Feature 18 resources and history, is restricted to the full-eye post-upscale route, and is intended for screenshots or benchmarks because it roughly doubles neural work.'
            'OpenNR Capture is fully opt-in and off by default. While disabled, the Present hook does not query the bracket hotkeys and the Feature 18 renderer skips capture setup; GPU readback, the writer queue, and disk output remain inactive.'
            if ($DlssNrOnly -or $LeanFullVr) { 'CommunityShaders.pdb is intentionally omitted; keep a symbol-bearing developer archive separately for private crash diagnostics.' } else { 'Use the included PDB only for private diagnostics; do not redistribute this archive.' }
        )
    }
    [IO.File]::WriteAllText((Join-Path $stage $manifestFileName), ($manifest | ConvertTo-Json -Depth 14) + [Environment]::NewLine, [Text.UTF8Encoding]::new($false))

$profileDescription = if ($DlssNrOnly) {
    'This profile keeps only the DLSSNR VR runtime: the standard Streamline DLSS/Reflex/PCL set plus nvngx_dlssnr.dll. FidelityFX and StreamlineDX12 frame-generation runtimes are omitted.'
} elseif ($LeanFullVr) {
    'This profile keeps the full Open Shaders VR feature/shader payload, standard Streamline DLSS/DLSSNR/Reflex/PCL, and FidelityFX upscaling. Debug symbols, StreamlineDX12, and FidelityFX Frame Generation are omitted as unused by the current Skyrim VR route.'
} else {
    'This profile contains the complete AIO upscaling runtime set for private development.'
}
$pdbDescription = if ($DlssNrOnly) {
    'No CommunityShaders.pdb; symbols are intentionally omitted from the slim runtime package.'
} elseif ($LeanFullVr) {
    'No CommunityShaders.pdb; symbols are intentionally omitted from the lean runtime package.'
} else {
    'SKSE/Plugins/CommunityShaders.pdb: private debugging symbols.'
}
$runtimeDescription = if ($DlssNrOnly) {
    'Streamline DLSS/Reflex/PCL and the stock RTX 50 DLSSNR runtime; no FSR or Frame Generation DLLs.'
} elseif ($LeanFullVr) {
    'Standard Streamline DLSS/DLSSNR/Reflex/PCL, FidelityFX upscaling, and the stock RTX 50 DLSSNR runtime; no StreamlineDX12 or FidelityFX Frame Generation DLLs.'
} else {
    'Streamline, StreamlineDX12, FidelityFX, and the stock RTX 50 DLSSNR runtime.'
}
$vcRuntimeDescription = if ($OmitVCRuntime) {
    'The package does not bundle the x64 MSVC runtime; install the matching Microsoft Visual C++ Redistributable separately.'
} else {
    'The x64 MSVC runtime DLLs required by CommunityShaders/Streamline are bundled beside both load locations.'
}
$changelogProfileDescription = if ($DlssNrOnly) {
    'Uses the DLSSNR-only VR package profile: FSR, StreamlineDX12, Frame Generation, and debug symbols are omitted because they are not used by the current Skyrim VR test route.'
} elseif ($LeanFullVr) {
    'Uses the lean-full VR package profile: FSR upscaling is retained, while CommunityShaders debug symbols, StreamlineDX12, and FidelityFX Frame Generation are omitted because they are not used by the current Skyrim VR test route.'
} else {
    'Uses the full AIO VR package profile with the complete Open Shaders upscaling runtime set for private development.'
}

    $readme = @"
$mo2ModName

This is a single-install private developer package for testing the committed
Open Shaders DLSSNR VR branch with MGO. It contains the freshly rebuilt
CommunityShaders.dll, the Open Shaders shader/resource payload, the selected
upscaling runtimes for this profile, and the stock-valid RTX 50 DLSSNR 310.8
runtime.

PACKAGE PROFILE
$runtimeProfile
$profileDescription

INSTALL
1. Make or select a copied MGO MO2 profile. Keep the known-good MGO profile
   available for rollback.
2. Install this .7z archive through MO2's Install Mod/archive button.
3. Enable the one installed mod. Do not install another DLSSNR core or runtime
   beside it.
4. In the test profile, disable Community Shaders Expanded (CSX), the CSX VR
   shader cache, any older DLSS5/DX11 bridge, RenoDX Feeder, ReShade DLSS
   wrappers, and Frame Generation for the first run.
5. Launch Skyrim VR through MO2. Press End, open Upscaling / Foveated DLSS,
   and confirm normal DLSS is working before evaluating Neural Rendering.
 6. OpenNR Capture is off by default and has no bracket-hotkey polling or renderer
    capture setup while disabled. Leave Enable capture unchecked for normal VR;
    enable it explicitly in the OpenNR Capture settings only when collecting
    training pairs, then the bracket keys become available for start/single/burst.
 7. Fresh NR defaults are: enabled, Default model preset, Full (100%) model
     resolution, Classic (bounded source) resolve, pre-upscale NR off, intensity
   2.00, local tone/local structure 2.00, skin structure -1.00, Style Default (numeric style 0),
    Automatic Mask on, UI Correction off, and experimental 2x sequential NR off.
    Foveated DLSS remains restart-gated and opt-in; once enabled, the fresh crop
    selection is Nasal Convergence 60% and the edge blend is Feather/oval at 64 px. Full Eye
    remains available as the explicit no-crop reset. Model Resolution (Cost)
    changes only the neural model workload. The selector also provides 90%, 85%,
    75%, 50%, and 33% steps.
 8. Reduced NR Resolve offers the default Classic path and an opt-in Matched
   Residual experiment. Matched Residual uses an exact-area input filter and
   composes the low-resolution model residual onto the full-resolution source;
   compare it at the same scene and head motion before keeping it enabled. The
   Classic resolve is resolution-aware: 90%/85% are substantially stronger,
   75% is intermediate, and 50%/33% remain conservative for artifact control.
 9. Experimental pre-upscale NR runs on Skyrim's native render image before
   DLSS. In VR it requires Full Eye + Default mode. It may reduce halos and
   NR cost at reduced model resolution, but can change color/exposure, lose
   fine texture, and fail with DLSS Ray Reconstruction. If the guide contract
   is unavailable, the existing post-upscale route remains the fallback.
 10. Experimental 2x sequential NR is available in the Neural Rendering settings.
   It performs two sequential Feature 18 evaluations per eye using an isolated
   intermediate resource and independent per-stage history. It is deliberately
   disabled for cropped VR and when pre-upscale NR is active. Enable it only for
   screenshots or benchmark captures, then return it to off for normal VR.
 11. NVAPI VRS is included but defaults off. Enable it separately only after a
   clean baseline; it requires a supported NVIDIA driver and should be tested
   with matched GPU frame-time captures. Full Eye means VRS has no useful
   foveated reduction until a centered subrect is selected.
  12. Full Eye is now a supported no-crop mode. Nasal Convergence 60% uses Feather/oval by
    default so the cropped neural region transitions into the stretched
    periphery without the old hard-copy rectangle. Dither remains available for
    comparison, while Hard Copy intentionally leaves a sharp boundary. Turn off
    Debug Visualize before judging the image.

WHAT IS INCLUDED
- SKSE/Plugins/CommunityShaders.dll: optimized Release build from the
  committed source checkout.
- $pdbDescription
- Open Shaders shader/config/resource payload needed by the isolated mod,
  excluding Renderdoc, generic textures/meshes/ParticleLights, and
  TerrainHelper.esp already present in MGO/CSX.
- DLSS Neural Rendering exposes Model Resolution (Cost): Full (100%), 90%,
  85%, 75%, 50%, and 33%. The display frame remains full resolution while
  Feature 18 runs at the selected internal model resolution.
- Reduced NR Resolve exposes Classic (bounded source) and optional Matched
  Residual. The latter uses exact-area input filtering and full-resolution
  residual composition only when the model resolution is below 100%. Classic
  resolve strength is resolution-aware: 90%/85% are stronger, while 50%/33%
  remain conservative for artifact control.
- Experimental pre-upscale NR is available as an explicit opt-in. It runs at
  the pre-DLSS hook, uses isolated full-eye stereo guides in VR, and falls
  back to the existing post-upscale path if preparation fails.
- Experimental 2x sequential NR is available as an explicit opt-in for
  screenshot/benchmark work. It allocates a per-eye intermediate image and
  separate Feature 18 history for each stage, and is automatically kept off for
  cropped VR and pre-upscale NR.
- OpenNR Capture is an explicit opt-in. It defaults off; while off, its bracket hotkeys,
  renderer capture setup, GPU readback, background writer, and disk output are
  inactive. Enable it in the Community Shaders settings only for pair collection; use [ for start/stop, ] for single, and the backslash key for burst.
- $vcRuntimeDescription
- The optional NVAPI VRS feature is included in the core plugin and is
  default-off. It shares the VR per-eye subrect controller, suspends during
  terrain blending/UI-sensitive transitions, and does not ship NVIDIA's
  driver-provided nvapi64.dll.
- $runtimeDescription

IMPORTANT
- This is a private, experimental developer handoff. The neural runtime is a
  proprietary NVIDIA binary and must not be redistributed publicly.
- This package does not install SKSEVR, Address Library, MGO, SteamVR,
  OpenXR/OpenComposite, or a Mod Organizer profile. Those remain dependencies.
- Do not add Feeder, RenoDX, ReShade, or a root-level proxy. This build uses the
  in-process Skyrim VR Open Shaders route.
- Frame Generation remains disabled for the initial VR test. In the
  DLSSNR-only profile its StreamlineDX12 and FidelityFX runtimes are not
  packaged. In the lean-full VR profile StreamlineDX12 and the FidelityFX
  Frame Generation DLL are omitted; FSR upscaling remains available.
- Enabling VRS is a separate experimental test. The NVIDIA display driver must
  provide the NVAPI variable-rate-shading capability; a missing capability is
  reported and leaves rendering on the normal path.

ROLLBACK
Disable this single mod and switch back to the known-good MGO profile. The
package does not edit saves, the physical Skyrim VR installation, or the MO2
profile itself.

The manifest records the source commit, submodule commit, every included file
hash, and every included upscaling runtime hash/signature state.
"@
    [IO.File]::WriteAllText((Join-Path $stage 'README-PRIVATE-FULL.txt'), $readme.Trim() + [Environment]::NewLine, [Text.UTF8Encoding]::new($false))

    $historyChangelogPath = Join-Path $projectRoot 'CHANGELOG.md'
    $latestChangelogPath = Join-Path $projectRoot ("CHANGELOG-$displayVersion.md")
    if (-not (Test-Path -LiteralPath $historyChangelogPath -PathType Leaf)) {
        throw "Cumulative changelog is missing: $historyChangelogPath"
    }
    if (-not (Test-Path -LiteralPath $latestChangelogPath -PathType Leaf)) {
        throw "Latest-version changelog is missing: $latestChangelogPath"
    }
    $historyChangelog = (Get-Content -LiteralPath $historyChangelogPath -Raw).Trim()
    $latestChangelog = (Get-Content -LiteralPath $latestChangelogPath -Raw).Trim()
    $changelog = @"
$mo2ModName $Version

- Rebuilt from source commit $sourceCommit.
- $changelogProfileDescription

$latestChangelog

This package is for private testing. A successful build/package does not equal
runtime acceptance; fresh Skyrim VR logs and headset frame-time evidence are
still required.
"@
    [IO.File]::WriteAllText((Join-Path $stage 'CHANGELOG.md'), $changelog.Trim() + [Environment]::NewLine, [Text.UTF8Encoding]::new($false))
    [IO.File]::WriteAllText((Join-Path $stage 'CHANGELOG-HISTORY.md'), $historyChangelog + [Environment]::NewLine, [Text.UTF8Encoding]::new($false))
    [IO.File]::WriteAllText((Join-Path $stage ("CHANGELOG-$displayVersion.md")), $latestChangelog + [Environment]::NewLine, [Text.UTF8Encoding]::new($false))

    $privateNotice = @"
PRIVATE THIRD-PARTY RUNTIME NOTICE

This archive contains proprietary NVIDIA/Streamline runtime binaries solely
for the owner's private internal developer testing. Do not upload, mirror, or
redistribute the archive. The stock neural runtime is nvngx_dlssnr.dll
310.8.0.0 with SHA-256:

$neuralHash

Authenticode status: $($neuralSignature.Status); signer:
$($neuralSignature.SignerCertificate.Subject)
"@
    [IO.File]::WriteAllText((Join-Path $stage 'PRIVATE-THIRD-PARTY-RUNTIME-NOTICE.txt'), $privateNotice.Trim() + [Environment]::NewLine, [Text.UTF8Encoding]::new($false))

    $licenses = Join-Path $stage 'LICENSES'
    New-Item -ItemType Directory -Force -Path $licenses | Out-Null
    Copy-Item -LiteralPath (Join-Path $sourceRepo 'COPYING') -Destination (Join-Path $licenses 'Open-Shaders-GPL-3.0.txt')

    $fomod = Join-Path $stage 'fomod'
    New-Item -ItemType Directory -Force -Path $fomod | Out-Null
    $info = @"
<?xml version="1.0" encoding="UTF-8"?>
<fomod>
  <Name>$mo2ModName</Name>
  <Author>DLSS5 SkyrimVR prototype contributors</Author>
  <Version>$Version</Version>
  <Website>https://github.com/YtzyFvra/skyrim-community-shaders</Website>
  <Description><![CDATA[Private single-install Open Shaders DLSS Neural Rendering VR $runtimeProfile developer package for MGO. MO2 display name: $mo2ModName.]]></Description>
</fomod>
"@
    [IO.File]::WriteAllText((Join-Path $fomod 'info.xml'), $info.Trim() + [Environment]::NewLine, [Text.UTF8Encoding]::new($false))
    $config = @"
<?xml version="1.0" encoding="UTF-8"?>
<config xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:noNamespaceSchemaLocation="http://qconsulting.ca/fo3/ModConfig5.0.xsd">
  <moduleName>$mo2ModName</moduleName>
  <installSteps order="Explicit">
    <installStep name="Install single private package">
      <optionalFileGroups order="Explicit">
        <group name="Single selected payload" type="SelectExactlyOne">
          <plugins order="Explicit">
            <plugin name="Install DLSSNR core and selected runtimes">
              <description>Installs the freshly rebuilt VR core, shaders, and the $runtimeProfile runtime set as one MO2 mod.</description>
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
    [IO.File]::WriteAllText((Join-Path $fomod 'ModuleConfig.xml'), $config.Trim() + [Environment]::NewLine, [Text.UTF8Encoding]::new($false))

    $sevenZip = $null
    $sevenZipCommand = Get-Command 7z.exe -ErrorAction SilentlyContinue
    if ($sevenZipCommand) {
        $sevenZip = $sevenZipCommand.Source
    } elseif (Test-Path -LiteralPath 'C:\Program Files\7-Zip\7z.exe') {
        $sevenZip = 'C:\Program Files\7-Zip\7z.exe'
    }

    if ($sevenZip) {
        Push-Location $stage
        try {
            & $sevenZip a -t7z -mx=5 -mmt=on $archive '*'
            if ($LASTEXITCODE -ne 0) { throw "7-Zip failed with exit code $LASTEXITCODE" }
        } finally {
            Pop-Location
        }
    } else {
        throw '7z.exe is required to create the canonical .7z package; install 7-Zip and retry.'
    }

    $archiveHash = (Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash
    $archiveSize = [math]::Round((Get-Item -LiteralPath $archive).Length / 1MB, 2)
    [pscustomobject]@{
        Archive = $archive
        ArchiveSHA256 = $archiveHash
        ArchiveMiB = $archiveSize
        SourceCommit = $sourceCommit
        FidelityFXSubmoduleCommit = $ffxCommit
        IncludedCoreFiles = $includedCore.Count
        IncludedUpscalingDlls = $runtimeRecords.Count
        RuntimeProfile = $runtimeProfile
        Variant = 'single-mo2-fomod-private-dev-vr'
    } | Format-List
} finally {
    if (Test-Path -LiteralPath $stage) {
        Remove-Item -LiteralPath $stage -Recurse -Force
    }
}
