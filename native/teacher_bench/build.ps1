$ErrorActionPreference='Stop'
$workspace=Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$vendor='D:\.CODEX_Projects\DLSS_5_SKYRIM\vendor\open-shaders-dlssnr-vr-091bfb4d'
$destination=Join-Path $workspace 'out\teacher_bench_build'
New-Item -ItemType Directory -Force -Path $destination | Out-Null
$developerShell='C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvars64.bat'
$runtime=Join-Path $vendor 'src\Features\Upscaling\NeuralRendering'
$sdk=Join-Path $vendor 'extern\Streamline-DX12\external\ngx-sdk\include'
$commands=@"
@echo off
call "$developerShell"
if errorlevel 1 exit /b 1
cd /d "$destination"
cl /nologo /std:c++20 /EHsc /O2 /DNOMINMAX /DUNICODE /D_UNICODE /I"$PSScriptRoot" /I"$runtime" /I"$sdk" "$PSScriptRoot\main.cpp" "$runtime\Runtime.cpp" /Fe:teacher_bench.exe /link d3d12.lib dxgi.lib version.lib psapi.lib
if errorlevel 1 exit /b 1
cl /nologo /std:c++20 /EHsc /O2 /LD /DOPENNR_BENCH_LIBRARY /DNOMINMAX /DUNICODE /D_UNICODE /I"$PSScriptRoot" /I"$runtime" /I"E:\OpenNR-VR-Poc-Venv\Lib\site-packages\nvidia\cuda_runtime\include" "$PSScriptRoot\main.cpp" /Fe:opennr_texture_bridge.dll /link d3d12.lib dxgi.lib
"@
$script=Join-Path $destination 'build.cmd'
[IO.File]::WriteAllText($script,$commands)
& cmd.exe /c $script
if ($LASTEXITCODE -ne 0) { throw 'Teacher harness compilation failed' }
