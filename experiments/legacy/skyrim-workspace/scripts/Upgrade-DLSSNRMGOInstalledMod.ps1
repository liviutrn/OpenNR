[CmdletBinding()]
param(
    [string]$MgoRoot = 'E:\MGO-RC3-fresh',
    [string]$Archive = 'D:\.CODEX_Projects\DLSS_5_SKYRIM\dist\DLSSNR-MGO-VR-0.4.3-mgo-vr.8-private-dev-PRIVATE-FULL-MO2.zip',
    [string]$ProfileName = 'Mad God Overhaul - NSFW'
)

$ErrorActionPreference = 'Stop'
$expectedVersion = '0.4.3-mgo-vr.8-private-dev'
$expectedArchiveHash = '7F4A8E2EBE3E18E1261DAEE6647BC2612EDA217136DAB6C74B7128B90C99415E'
$expectedCommunityShadersHash = 'ABDB09E0A618B557980F8A09B8F5F82665140A67AB9E1D9CCC2EAEBC742AC70B'
$expectedNeuralHash = 'E16BCF15E16E13F527491CDF7845B2FE6521A738D8F7C9C721866A8496E1FC8E'
$expectedModelShaderHash = 'DF912A33F78218664CD32517514CDB9CAB62CF5B5BDA7F6DF445EFC34FA89E17'

function Get-FullPath([string]$Path) {
    return [IO.Path]::GetFullPath($Path)
}

function Test-ContainedPath([string]$Child, [string]$Parent) {
    $parentWithSeparator = $Parent.TrimEnd('\') + '\'
    return $Child.StartsWith($parentWithSeparator, [StringComparison]::OrdinalIgnoreCase)
}

$root = Get-FullPath $MgoRoot
$modsRoot = Get-FullPath (Join-Path $root 'mods')
$oldMod = Get-FullPath (Join-Path $modsRoot 'DLSSNR')
$backupRoot = Get-FullPath (Join-Path $root 'backups')
$tempRoot = Get-FullPath (Join-Path $root '__temp__')
$profileRoot = Get-FullPath (Join-Path $root ('profiles\' + $ProfileName))
$modlistPath = Get-FullPath (Join-Path $profileRoot 'modlist.txt')
$mo2IniPath = Get-FullPath (Join-Path $root 'ModOrganizer.ini')
$archive = Get-FullPath $Archive
$seven = 'C:\Program Files\7-Zip\7z.exe'

if ($root -ne 'E:\MGO-RC3-fresh') {
    throw "Refusing an unexpected MGO root: $root"
}
if (-not (Test-ContainedPath $oldMod $modsRoot)) {
    throw "The resolved mod path is outside the expected mods directory: $oldMod"
}
foreach ($path in @($oldMod, $archive, $modlistPath, $mo2IniPath)) {
    if (-not (Test-Path -LiteralPath $path)) {
        throw "Required path is missing: $path"
    }
}
if (-not (Test-Path -LiteralPath $oldMod -PathType Container)) {
    throw "Current DLSSNR path is not a directory: $oldMod"
}
if (-not (Test-Path -LiteralPath $archive -PathType Leaf)) {
    throw "0.4.3 package is not a file: $archive"
}
if (-not (Test-Path -LiteralPath $seven -PathType Leaf)) {
    throw "7-Zip is missing: $seven"
}

$running = @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
    $_.Name -match '(?i)^(SkyrimVR|sksevr_loader|sksevr|ModOrganizer|ModOrganizer2)(\.exe)?$'
})
if ($running.Count -gt 0) {
    throw "Skyrim VR, SKSEVR, or MO2 is running; close it before the mod swap: $($running.Name -join ', ')"
}

$modlistText = Get-Content -LiteralPath $modlistPath
if (-not ($modlistText -contains '+DLSSNR')) {
    throw "The selected profile does not have +DLSSNR enabled; refusing to guess a replacement entry."
}
$mo2Text = Get-Content -LiteralPath $mo2IniPath -Raw
if ($mo2Text -notmatch [regex]::Escape("selected_profile=@ByteArray($ProfileName)")) {
    throw "MO2 selected profile does not match '$ProfileName'; refusing to change the installation."
}

$reparse = @(Get-Item -LiteralPath $oldMod -Force; Get-ChildItem -LiteralPath $oldMod -Recurse -Force) |
    Where-Object { $_.Attributes -band [IO.FileAttributes]::ReparsePoint }
if ($reparse.Count -gt 0) {
    throw "The current DLSSNR mod contains reparse points; refusing to move it."
}

$archiveHash = (Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash
if ($archiveHash -ne $expectedArchiveHash) {
    throw "0.4.3 package hash mismatch: $archiveHash"
}

$oldMeta = Get-Content -LiteralPath (Join-Path $oldMod 'meta.ini') -Raw
$oldVersion = if ($oldMeta -match '(?m)^version=(.+)$') { $matches[1].Trim() } else { 'unknown' }
$modlistBefore = (Get-FileHash -LiteralPath $modlistPath -Algorithm SHA256).Hash
$mo2IniBefore = (Get-FileHash -LiteralPath $mo2IniPath -Algorithm SHA256).Hash

New-Item -ItemType Directory -Force -Path $backupRoot | Out-Null
New-Item -ItemType Directory -Force -Path $tempRoot | Out-Null
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$backup = Get-FullPath (Join-Path $backupRoot "DLSSNR-before-0.4.3-$stamp")
$stage = Get-FullPath (Join-Path $tempRoot "DLSSNR-0.4.3-stage-$stamp")
$failed = Get-FullPath (Join-Path $backupRoot "DLSSNR-failed-0.4.3-$stamp")
foreach ($path in @($backup, $stage, $failed)) {
    if (Test-Path -LiteralPath $path) {
        throw "Unexpected existing transaction path: $path"
    }
}
if (-not (Test-ContainedPath $backup $backupRoot) -or -not (Test-ContainedPath $stage $tempRoot)) {
    throw 'A transaction path escaped its intended directory.'
}

New-Item -ItemType Directory -Path $stage | Out-Null
$oldMoved = $false
$newMoved = $false
try {
    & $seven x $archive '00 - DLSSNR Core/*' "-o$stage" '-y' '-bso0' '-bsp0'
    if ($LASTEXITCODE -ne 0) {
        throw "7-Zip extraction failed with exit code $LASTEXITCODE"
    }

    $coreStage = Join-Path $stage '00 - DLSSNR Core'
    if (-not (Test-Path -LiteralPath $coreStage -PathType Container)) {
        throw 'The FOMOD core payload was not found after extraction.'
    }
    $required = @(
        (Join-Path $coreStage 'meta.ini'),
        (Join-Path $coreStage 'SKSE\Plugins\CommunityShaders.dll'),
        (Join-Path $coreStage 'SKSE\Plugins\CommunityShaders.pdb'),
        (Join-Path $coreStage 'Shaders\Upscaling\NeuralRendering\ModelResolutionCS.hlsl'),
        (Join-Path $coreStage 'Shaders\Upscaling\Streamline\nvngx_dlssnr.dll'),
        (Join-Path $coreStage 'Shaders\Upscaling\StreamlineDX12\nvngx_dlss.dll'),
        (Join-Path $coreStage 'Shaders\Upscaling\FidelityFX\amd_fidelityfx_upscaler_dx12.dll')
    )
    foreach ($path in $required) {
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
            throw "Required staged file is missing: $path"
        }
    }
    $stagedMeta = Get-Content -LiteralPath (Join-Path $coreStage 'meta.ini') -Raw
    if ($stagedMeta -notmatch [regex]::Escape("version=$expectedVersion")) {
        throw "Staged meta.ini does not identify $expectedVersion"
    }
    $coreFiles = @(Get-ChildItem -LiteralPath $coreStage -Recurse -File -Force)
    if ($coreFiles.Count -ne 456) {
        throw "Unexpected staged core file count: $($coreFiles.Count), expected 456."
    }
    $stagedCommunityHash = (Get-FileHash -LiteralPath (Join-Path $coreStage 'SKSE\Plugins\CommunityShaders.dll') -Algorithm SHA256).Hash
    $stagedNeuralHash = (Get-FileHash -LiteralPath (Join-Path $coreStage 'Shaders\Upscaling\Streamline\nvngx_dlssnr.dll') -Algorithm SHA256).Hash
    $stagedModelHash = (Get-FileHash -LiteralPath (Join-Path $coreStage 'Shaders\Upscaling\NeuralRendering\ModelResolutionCS.hlsl') -Algorithm SHA256).Hash
    if ($stagedCommunityHash -ne $expectedCommunityShadersHash) { throw "Staged CommunityShaders hash mismatch: $stagedCommunityHash" }
    if ($stagedNeuralHash -ne $expectedNeuralHash) { throw "Staged neural runtime hash mismatch: $stagedNeuralHash" }
    if ($stagedModelHash -ne $expectedModelShaderHash) { throw "Staged model shader hash mismatch: $stagedModelHash" }

    try {
        Move-Item -LiteralPath $oldMod -Destination $backup
        $oldMoved = $true
        Move-Item -LiteralPath $coreStage -Destination $oldMod
        $newMoved = $true

        $installedMeta = Get-Content -LiteralPath (Join-Path $oldMod 'meta.ini') -Raw
        $installedCommunityHash = (Get-FileHash -LiteralPath (Join-Path $oldMod 'SKSE\Plugins\CommunityShaders.dll') -Algorithm SHA256).Hash
        $installedNeuralHash = (Get-FileHash -LiteralPath (Join-Path $oldMod 'Shaders\Upscaling\Streamline\nvngx_dlssnr.dll') -Algorithm SHA256).Hash
        if ($installedMeta -notmatch [regex]::Escape("version=$expectedVersion")) { throw 'Installed meta.ini does not identify 0.4.3.' }
        if ($installedCommunityHash -ne $expectedCommunityShadersHash) { throw "Installed CommunityShaders hash mismatch: $installedCommunityHash" }
        if ($installedNeuralHash -ne $expectedNeuralHash) { throw "Installed neural runtime hash mismatch: $installedNeuralHash" }
        if ((Get-FileHash -LiteralPath $modlistPath -Algorithm SHA256).Hash -ne $modlistBefore) { throw 'Active profile modlist changed during the upgrade.' }
        if ((Get-FileHash -LiteralPath $mo2IniPath -Algorithm SHA256).Hash -ne $mo2IniBefore) { throw 'MO2 configuration changed during the upgrade.' }
    } catch {
        $rollbackError = $null
        try {
            if (Test-Path -LiteralPath $oldMod) {
                Move-Item -LiteralPath $oldMod -Destination $failed
            }
            if ($oldMoved -and (Test-Path -LiteralPath $backup) -and -not (Test-Path -LiteralPath $oldMod)) {
                Move-Item -LiteralPath $backup -Destination $oldMod
            }
        } catch {
            $rollbackError = $_.Exception.Message
        }
        if ($rollbackError) {
            throw "Upgrade failed and rollback also failed: $rollbackError"
        }
        throw
    }

    $installedFiles = @(Get-ChildItem -LiteralPath $oldMod -Recurse -File -Force)
    [pscustomobject]@{
        ActiveProfile = $ProfileName
        ModPath = $oldMod
        PreviousVersion = $oldVersion
        InstalledVersion = $expectedVersion
        InstalledFiles = $installedFiles.Count
        CommunityShadersSHA256 = $installedCommunityHash
        NeuralRuntimeSHA256 = $installedNeuralHash
        PreviousModBackup = $backup
        ProfileModlistUnchanged = $true
        MO2ConfigUnchanged = $true
    } | Format-List
} finally {
    if (Test-Path -LiteralPath $stage) {
        Remove-Item -LiteralPath $stage -Recurse -Force
    }
}
