$ErrorActionPreference = 'Stop'

$runtimePath = 'runtime/open-shaders/cmake/Streamline-Runtime.cmake'
$text = Get-Content $runtimePath -Raw
$startToken = 'if(NOT EXISTS "${OPENNR_DLSSNR_RUNTIME_SOURCE}")'
$endToken = 'list(APPEND STREAMLINE_RUNTIME_FILES "${_opennr_dlssnr_runtime_destination}")'
$start = $text.IndexOf($startToken)
$endStart = $text.IndexOf($endToken, $start)
if ($start -lt 0 -or $endStart -lt 0) { throw 'Could not locate DLSS-NR carrier staging block' }
$end = $endStart + $endToken.Length
$replacement = @(
  'if(EXISTS "${OPENNR_DLSSNR_RUNTIME_SOURCE}")',
  '    file(SIZE "${OPENNR_DLSSNR_RUNTIME_SOURCE}" _opennr_dlssnr_runtime_size)',
  '    if(_opennr_dlssnr_runtime_size LESS 1048576)',
  '        message(FATAL_ERROR',
  '            "OpenNR Feature 18 carrier is implausibly small: ${_opennr_dlssnr_runtime_size} bytes"',
  '        )',
  '    endif()',
  '    set(_opennr_dlssnr_runtime_destination',
  '        "${STREAMLINE_RUNTIME_DIRECTORY}/nvngx_dlssnr.dll"',
  '    )',
  '    file(COPY_FILE',
  '        "${OPENNR_DLSSNR_RUNTIME_SOURCE}"',
  '        "${_opennr_dlssnr_runtime_destination}"',
  '        ONLY_IF_DIFFERENT',
  '    )',
  '    list(APPEND STREAMLINE_RUNTIME_FILES "${_opennr_dlssnr_runtime_destination}")',
  'else()',
  '    message(WARNING',
  '        "Building public-source OpenNR 2.20.1-v01 without the locally supplied nvngx_dlssnr.dll carrier. "',
  '        "CommunityShaders.dll will still be compiled from the transformed v01 sources."',
  '    )',
  'endif()'
) -join "`n"
$text = $text.Substring(0,$start) + $replacement + $text.Substring($end)
Set-Content -Path $runtimePath -Value $text -NoNewline

$sourceValidator = 'runtime/open-shaders/cmake/ValidateOpenNRSourceContracts.cmake'
$v = Get-Content $sourceValidator -Raw
$needle = '   NOT EXISTS "${_dlssnr_carrier_path}" OR'
if (-not $v.Contains($needle)) { throw 'Could not locate carrier existence assertion in source validator' }
$v = $v.Replace($needle, '   FALSE OR')
$sizeStartToken = 'file(SIZE "${_dlssnr_carrier_path}" _source_dlssnr_size)'
$sizeStart = $v.IndexOf($sizeStartToken)
$sizeEndStart = $v.IndexOf('endif()', $sizeStart)
if ($sizeStart -lt 0 -or $sizeEndStart -lt 0) { throw 'Could not locate carrier size assertion in source validator' }
$sizeEnd = $sizeEndStart + 'endif()'.Length
$sizeBlock = $v.Substring($sizeStart,$sizeEnd-$sizeStart)
$v = $v.Substring(0,$sizeStart) + 'if(EXISTS "${_dlssnr_carrier_path}")' + "`n" + $sizeBlock + "`nendif()" + $v.Substring($sizeEnd)
Set-Content -Path $sourceValidator -Value $v -NoNewline

$packageValidator = 'runtime/open-shaders/cmake/ValidateOpenNRPackage.cmake'
$p = Get-Content $packageValidator -Raw
$requiredCarrier = '    "Shaders/Upscaling/Streamline/nvngx_dlssnr.dll"'
if (-not $p.Contains($requiredCarrier)) { throw 'Could not locate carrier manifest entry in package validator' }
$p = $p.Replace($requiredCarrier, '')
$pkgSizeStartToken = 'file(SIZE "${PACKAGE_ROOT}/Shaders/Upscaling/Streamline/nvngx_dlssnr.dll" _dlssnr_size)'
$pkgSizeStart = $p.IndexOf($pkgSizeStartToken)
$pkgSizeEndStart = $p.IndexOf('endif()', $pkgSizeStart)
if ($pkgSizeStart -lt 0 -or $pkgSizeEndStart -lt 0) { throw 'Could not locate carrier size assertion in package validator' }
$pkgSizeEnd = $pkgSizeEndStart + 'endif()'.Length
$pkgSizeBlock = $p.Substring($pkgSizeStart,$pkgSizeEnd-$pkgSizeStart)
$pkgWrapped = 'if(EXISTS "${PACKAGE_ROOT}/Shaders/Upscaling/Streamline/nvngx_dlssnr.dll")' + "`n" + $pkgSizeBlock + "`nelse()`n    set(_dlssnr_size 0)`nendif()"
$p = $p.Substring(0,$pkgSizeStart) + $pkgWrapped + $p.Substring($pkgSizeEnd)
$hashLine = 'file(SHA256 "${PACKAGE_ROOT}/Shaders/Upscaling/Streamline/nvngx_dlssnr.dll" _dlssnr_sha256)'
if (-not $p.Contains($hashLine)) { throw 'Could not locate carrier hash assertion in package validator' }
$hashReplacement = @(
  'if(EXISTS "${PACKAGE_ROOT}/Shaders/Upscaling/Streamline/nvngx_dlssnr.dll")',
  '    file(SHA256 "${PACKAGE_ROOT}/Shaders/Upscaling/Streamline/nvngx_dlssnr.dll" _dlssnr_sha256)',
  'else()',
  '    set(_dlssnr_sha256 "carrier-excluded")',
  'endif()'
) -join "`n"
$p = $p.Replace($hashLine,$hashReplacement)
Set-Content -Path $packageValidator -Value $p -NoNewline
Write-Host 'Carrier-excluded CI package rules applied.'
