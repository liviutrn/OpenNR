[CmdletBinding()]
param(
    [string]$BuildRoot = 'E:\OpenNR_Builds\2.15.0',
    [string]$Dependencies = 'C:\OpenNR\Dependencies\runtime-2.15.0',
    [string]$SourceRoot,
    [string[]]$Targets = @('CommunityShaders', 'cpp_tests'),
    [bool]$CaptureEnabled = $true,
    [switch]$ConfigureOnly
)
$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
if (-not $SourceRoot) { $SourceRoot = Join-Path $repo 'runtime\open-shaders' }
$python = Get-Command python -ErrorAction Stop
$BuildRoot = & $python.Source (Join-Path $PSScriptRoot 'opennr_paths.py') build --path $BuildRoot
if ($LASTEXITCODE -ne 0) { throw 'Invalid external build destination' }
$vswhere = Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio\Installer\vswhere.exe'
$vs = & $vswhere -latest -products '*' -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath
if (-not $vs) { throw 'MSVC C++ tools are required' }
$cmake = Join-Path $vs 'Common7\IDE\CommonExtensions\Microsoft\CMake\CMake\bin\cmake.exe'
$vcvars = Join-Path $vs 'VC\Auxiliary\Build\vcvars64.bat'
$vcpkg = Join-Path $vs 'VC\vcpkg\scripts\buildsystems\vcpkg.cmake'
New-Item -ItemType Directory -Force -Path $BuildRoot | Out-Null
$captureValue = if ($CaptureEnabled) { 'ON' } else { 'OFF' }
$arguments = @(
    '-S', "`"$SourceRoot`"", '-B', "`"$BuildRoot`"", '-G', '"Visual Studio 17 2022"', '-A', 'x64',
    "`"-DCMAKE_TOOLCHAIN_FILE=$vcpkg`"", '-DVCPKG_MANIFEST_INSTALL=OFF',
    "`"-DVCPKG_INSTALLED_DIR=$Dependencies\vcpkg_installed`"", '-DVCPKG_TARGET_TRIPLET=x64-windows-static-md-release',
    "`"-DOPENNR_COMMONLIB_SOURCE_DIR=$Dependencies\CommonLibSSE-NG`"",
    "`"-DCOMMONLIB_PREBUILT_DIR=$Dependencies\CommonLib-prebuilt`"",
    "`"-DOPENNR_STREAMLINE_SOURCE_DIR=$Dependencies\Streamline-DX12`"",
    "`"-DOPENNR_FFX_SOURCE_DIR=$Dependencies\FidelityFX-SDK`"",
    "`"-DOPENNR_NVAPI_SOURCE_DIR=$Dependencies\nvapi`"",
    "`"-DOPENNR_DLSSNR_RUNTIME_SOURCE=$Dependencies\private-runtime\nvngx_dlssnr.dll`"",
    "`"-DOPENNR_IMGUI_HELPER_SOURCE=$Dependencies\private-runtime\imgui-vr-helper.dll`"",
    "`"-DDIST_PATH=$BuildRoot\dist`"",
    "`"-DFETCHCONTENT_SOURCE_DIR_CATCH2=$Dependencies\catch2-src`"",
    "`"-DFETCHCONTENT_SOURCE_DIR_IMGUIVRHELPER=$Dependencies\imguivrhelper-src`"",
    "`"-DFETCHCONTENT_SOURCE_DIR_HDE64=$Dependencies\hde64-src`"",
    '-DAUTO_PLUGIN_DEPLOYMENT=OFF', '-DBUILD_CPP_TESTS=ON', '-DBUILD_SHADER_TESTS=OFF',
    "-DBUILD_OPENNR_CAPTURE=$captureValue", "-DAIO_INCLUDE_OPENNR_CAPTURE=$captureValue", '-DOPENNR_LEAN_PACKAGE=ON',
    '-DAIO_INCLUDE_NON_AUTOUPLOAD=OFF', '-DAIO_ZIP_TO_DIST=OFF', '-DZIP_TO_DIST=OFF',
    '-DSKSE_SUPPORT_XBYAK=ON', '-DENABLE_SKYRIM_SE=ON', '-DENABLE_SKYRIM_AE=ON', '-DENABLE_SKYRIM_VR=ON',
    '-DCMAKE_INTERPROCEDURAL_OPTIMIZATION=OFF', '-DSC_DEVFAST_OPTS=OFF', '-DSC_COMPILE_PDB=OFF',
    '-DCMAKE_POLICY_VERSION_MINIMUM=3.5'
)
$lines = @('@echo off', "call `"$vcvars`"", 'if errorlevel 1 exit /b 1', "`"$cmake`" $($arguments -join ' ')", 'if errorlevel 1 exit /b 1')
if (-not $ConfigureOnly) {
    $lines += "`"$cmake`" --build `"$BuildRoot`" --config Release --target $($Targets -join ' ') --parallel 4"
    $lines += 'if errorlevel 1 exit /b 1'
}
$script = Join-Path $BuildRoot 'build-opennr.cmd'
[IO.File]::WriteAllLines($script, $lines)
& cmd.exe /d /c $script
if ($LASTEXITCODE -ne 0) { throw "OpenNR build failed: $LASTEXITCODE" }
