param([string]$Dependencies='C:\OpenNR\Dependencies\runtime-2.15.0')
$ErrorActionPreference = 'Stop'
$workspace = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$vendor=Join-Path $workspace 'runtime\open-shaders'
$destination=Join-Path (& python (Join-Path $workspace 'tools\opennr_paths.py') build) 'teacher_sequence_bench'
if($LASTEXITCODE -ne 0){throw 'Invalid build path'}
New-Item -ItemType Directory -Force -Path $destination | Out-Null
$developerShell = 'C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvars64.bat'
$runtime = Join-Path $vendor 'src\Features\Upscaling\NeuralRendering'
$sdk = Join-Path $Dependencies 'Streamline-DX12\external\ngx-sdk\include'
$benchmarkHeaders = Join-Path $workspace 'native\teacher_bench'
$commands = @"
@echo off
call "$developerShell"
if errorlevel 1 exit /b 1
cd /d "$destination"
cl /nologo /std:c++20 /EHsc /O2 /DNOMINMAX /DUNICODE /D_UNICODE /I"$PSScriptRoot" /I"$benchmarkHeaders" /I"$runtime" /I"$vendor\src" /I"$sdk" "$PSScriptRoot\main.cpp" "$runtime\Runtime.cpp" /Fe:teacher_sequence_bench.exe /link d3d12.lib dxgi.lib version.lib psapi.lib
if errorlevel 1 exit /b 1
"@
$script = Join-Path $destination 'build.cmd'
[IO.File]::WriteAllText($script, $commands)
& cmd.exe /c $script
if ($LASTEXITCODE -ne 0) { throw 'Teacher sequence harness compilation failed' }
