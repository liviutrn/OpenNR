$ErrorActionPreference = "Stop"

$streamlinePath = "runtime/open-shaders/cmake/Streamline-Runtime.cmake"
$validatorPath = "runtime/open-shaders/cmake/ValidateOpenNRSourceContracts.cmake"
$cmakePath = "runtime/open-shaders/CMakeLists.txt"

# 1. Packaging: when OPENNR_EXTERNAL_DLSSNR_RUNTIME=ON, preserve the user's
# already-installed nvngx_dlssnr.dll instead of requiring a carrier in source.
$streamline = Get-Content $streamlinePath -Raw
if (-not $streamline.Contains('OpenNR update package will preserve the installed nvngx_dlssnr.dll')) {
    $startMarker = 'if(NOT EXISTS "${OPENNR_DLSSNR_RUNTIME_SOURCE}")'
    $endMarker = 'list(APPEND STREAMLINE_RUNTIME_FILES "${_opennr_dlssnr_runtime_destination}")'
    $start = $streamline.IndexOf($startMarker)
    $end = if ($start -ge 0) { $streamline.IndexOf($endMarker, $start) } else { -1 }
    if ($start -lt 0 -or $end -lt 0) {
        throw "Expected frozen Feature 18 packaging block not found"
    }
    $end += $endMarker.Length
    $replacement = @'
if(NOT EXISTS "${OPENNR_DLSSNR_RUNTIME_SOURCE}")
    if(OPENNR_EXTERNAL_DLSSNR_RUNTIME)
        message(STATUS "OpenNR update package will preserve the installed nvngx_dlssnr.dll")
    else()
        message(FATAL_ERROR
            "OpenNR Feature 18 carrier is missing: ${OPENNR_DLSSNR_RUNTIME_SOURCE}. "
            "Supply the validated nvngx_dlssnr.dll before packaging."
        )
    endif()
else()
    file(SIZE "${OPENNR_DLSSNR_RUNTIME_SOURCE}" _opennr_dlssnr_runtime_size)
    if(_opennr_dlssnr_runtime_size LESS 1048576)
        message(FATAL_ERROR
            "OpenNR Feature 18 carrier is implausibly small: ${_opennr_dlssnr_runtime_size} bytes"
        )
    endif()
    set(_opennr_dlssnr_runtime_destination
        "${STREAMLINE_RUNTIME_DIRECTORY}/nvngx_dlssnr.dll"
    )
    file(COPY_FILE
        "${OPENNR_DLSSNR_RUNTIME_SOURCE}"
        "${_opennr_dlssnr_runtime_destination}"
        ONLY_IF_DIFFERENT
    )
    list(APPEND STREAMLINE_RUNTIME_FILES "${_opennr_dlssnr_runtime_destination}")
endif()
'@
    $streamline = $streamline.Substring(0, $start) + $replacement + $streamline.Substring($end)
    Set-Content -Path $streamlinePath -Value $streamline -Encoding utf8 -NoNewline
}

# 2. Validator: match the already-successful build-21 behavior. The carrier is
# mandatory only for self-contained packages, not external-runtime update builds.
$validator = Get-Content $validatorPath -Raw
$genericCarrier = 'NOT EXISTS "${_temporal_shader_path}" OR NOT EXISTS "${_dlssnr_carrier_path}" OR'
if ($validator.Contains($genericCarrier)) {
    $validator = $validator.Replace($genericCarrier, 'NOT EXISTS "${_temporal_shader_path}" OR')
}
$conditionalCarrier = 'if(NOT OPENNR_EXTERNAL_DLSSNR_RUNTIME AND NOT EXISTS "${_dlssnr_carrier_path}")'
if (-not $validator.Contains($conditionalCarrier)) {
    $readMarker = 'file(READ "${_icon_loader_path}" _icon_loader)'
    if (-not $validator.Contains($readMarker)) {
        throw "Validator insertion point not found"
    }
    $carrierCheck = @'
if(NOT OPENNR_EXTERNAL_DLSSNR_RUNTIME AND NOT EXISTS "${_dlssnr_carrier_path}")
    message(FATAL_ERROR "OpenNR source contract validation could not find the Feature 18 carrier")
endif()
'@
    $validator = $validator.Replace($readMarker, $carrierCheck + "`n" + $readMarker)
    Set-Content -Path $validatorPath -Value $validator -Encoding utf8 -NoNewline
}

# 3. Pass the external-runtime mode into the validator, as build 21 does.
$cmake = Get-Content $cmakePath -Raw
$externalArg = '-DOPENNR_EXTERNAL_DLSSNR_RUNTIME=${OPENNR_EXTERNAL_DLSSNR_RUNTIME}'
if (-not $cmake.Contains($externalArg)) {
    $sourceArg = '-DOPENNR_DLSSNR_RUNTIME_SOURCE=${OPENNR_DLSSNR_RUNTIME_SOURCE}'
    if (-not $cmake.Contains($sourceArg)) {
        throw "Validate-OpenNR-Source command insertion point not found"
    }
    $cmake = $cmake.Replace($sourceArg, $sourceArg + "`n        " + $externalArg)
    Set-Content -Path $cmakePath -Value $cmake -Encoding utf8 -NoNewline
}

# Refuse accidental edits outside the three build-system compatibility files.
$allowed = @(
    $streamlinePath.Replace('/', '\'),
    $validatorPath.Replace('/', '\'),
    $cmakePath.Replace('/', '\')
)
$changed = @(git diff --name-only | ForEach-Object { $_.Trim().Replace('/', '\') } | Where-Object { $_ })
$unexpected = @($changed | Where-Object { $_ -notin $allowed })
if ($unexpected.Count -gt 0) {
    throw "Unexpected files changed by compatibility preparation: $($unexpected -join ', ')"
}

git diff --check -- $streamlinePath $validatorPath $cmakePath
if ($LASTEXITCODE -ne 0) { throw "Compatibility patch produced an invalid diff" }

Write-Host "Applied frozen-source external-runtime compatibility only."
Write-Host "Compiled C++ and shader sources remain unchanged."
