[CmdletBinding()]
param(
    [string]$ProjectRoot = 'D:\.CODEX_Projects\DLSS_5_SKYRIM',
    [string]$SourceRoot = '',
    [string]$SdkVersion = ''
)

$ErrorActionPreference = 'Stop'
if ([string]::IsNullOrWhiteSpace($SourceRoot)) {
    $SourceRoot = Join-Path $ProjectRoot 'vendor\dlss5-dx11-bridge-v1.0.18\src'
}
$buildRoot = Join-Path $ProjectRoot 'build\dlss5-dx11-bridge-v1.0.18'
New-Item -ItemType Directory -Force -Path $buildRoot | Out-Null

$msvcCandidates = @(
    'C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Tools\MSVC\14.44.35207',
    'C:\Program Files\Microsoft Visual Studio\2022\BuildTools\VC\Tools\MSVC\14.44.35207'
)
$msvcRoot = $msvcCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
if (-not $msvcRoot) { throw 'MSVC 2022 toolchain was not found.' }

$sdkRoot = 'C:\Program Files (x86)\Windows Kits\10'
$sdkIncludeRoot = Join-Path $sdkRoot 'Include'
$sdkLibRoot = Join-Path $sdkRoot 'Lib'
if ([string]::IsNullOrWhiteSpace($SdkVersion)) {
    $SdkVersion = Get-ChildItem -LiteralPath $sdkIncludeRoot -Directory |
        Where-Object { Test-Path -LiteralPath (Join-Path $_.FullName 'um\Windows.h') } |
        Sort-Object Name -Descending |
        Select-Object -First 1 -ExpandProperty Name
}
if (-not $SdkVersion) { throw 'A Windows SDK with um\Windows.h was not found.' }

$cl = Join-Path $msvcRoot 'bin\Hostx64\x64\cl.exe'
$rc = Join-Path $sdkRoot "bin\$SdkVersion\x64\rc.exe"
$shared = Join-Path $sdkIncludeRoot "$SdkVersion\shared"
$um = Join-Path $sdkIncludeRoot "$SdkVersion\um"
$ucrt = Join-Path $sdkIncludeRoot "$SdkVersion\ucrt"
$vcLib = Join-Path $msvcRoot 'lib\x64'
$umLib = Join-Path $sdkLibRoot "$SdkVersion\um\x64"
$ucrtLib = Join-Path $sdkLibRoot "$SdkVersion\ucrt\x64"
$resource = Join-Path $buildRoot 'version.res'
$output = Join-Path $buildRoot 'dlss5-dx11-bridge.addon64'

foreach ($path in @($SourceRoot, $cl, $rc, $shared, $um, $ucrt, $vcLib, $umLib, $ucrtLib)) {
    if (-not (Test-Path -LiteralPath $path)) { throw "Required build path not found: $path" }
}

Push-Location $SourceRoot
try {
    & $rc '/nologo' '/I' $shared '/I' $um '/I' $ucrt '/fo' $resource 'version.rc'
    if ($LASTEXITCODE -ne 0) { throw "rc.exe failed with exit code $LASTEXITCODE." }

    $clArgs = @(
        '/nologo', '/LD', '/EHsc', '/O2', '/MT',
        ('/I' + (Join-Path $msvcRoot 'include')), ('/I' + $shared), ('/I' + $um), ('/I' + $ucrt),
        'dlss5-dx11-bridge.cpp', $resource, '/link', ('/OUT:' + $output),
        ('/LIBPATH:' + $vcLib), ('/LIBPATH:' + $umLib), ('/LIBPATH:' + $ucrtLib),
        'kernel32.lib', 'user32.lib', 'advapi32.lib'
    )
    & $cl @clArgs
    if ($LASTEXITCODE -ne 0) { throw "cl.exe failed with exit code $LASTEXITCODE." }
}
finally {
    Pop-Location
}

$info = Get-Item -LiteralPath $output
[pscustomobject]@{
    Output = $info.FullName
    Version = $info.VersionInfo.FileVersion
    Size = $info.Length
    SHA256 = (Get-FileHash -LiteralPath $info.FullName -Algorithm SHA256).Hash
    SdkVersion = $SdkVersion
} | Format-List
