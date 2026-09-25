if(NOT DEFINED PACKAGE_ROOT OR NOT IS_DIRECTORY "${PACKAGE_ROOT}")
    message(FATAL_ERROR "OpenNR package validation requires a valid PACKAGE_ROOT")
endif()

if(NOT DEFINED EXPECT_LEAN_PACKAGE)
    set(EXPECT_LEAN_PACKAGE OFF)
endif()
if(NOT DEFINED EXPECT_OPENNR_CAPTURE)
    set(EXPECT_OPENNR_CAPTURE OFF)
endif()
if(NOT DEFINED EXPECT_NATIVE_EYE_TRACKING)
    set(EXPECT_NATIVE_EYE_TRACKING OFF)
endif()
if(NOT DEFINED EXPECT_OPENNR_VERSION)
    set(EXPECT_OPENNR_VERSION "")
endif()
if(NOT DEFINED EXPECT_EXTERNAL_DLSSNR_RUNTIME)
    set(EXPECT_EXTERNAL_DLSSNR_RUNTIME OFF)
endif()

set(_required_paths
    "SKSE/Plugins/CommunityShaders.dll"
    "SKSE/Plugins/imgui-vr-helper.dll"
    "SKSE/Plugins/ImGuiVRHelper.toml"
    "SKSE/Plugins/CommunityShaders/Translations/en.json"
    "OpenNR-BRANDING.txt"
    "Interface/CommunityShaders/OpenNR Logo/opennr-logo.png"
    "Shaders/Features/Upscaling.ini"
    "Shaders/Features/GrassOptimizations.ini"
    "Shaders/Features/Skylighting.ini"
    "Shaders/Features/WetnessEffects.ini"
    "Shaders/Features/VR.ini"
    "Shaders/Features/VRS.ini"
    "Shaders/Common/TemporalReproject.hlsli"
    "Shaders/Common/VRStereoEffects.hlsli"
    "Shaders/DynamicNearClipCS.hlsl"
    "Shaders/GrassOptimizations/GrassCullingCS.hlsl"
    "Shaders/GrassOptimizations/GrassHiZCS.hlsl"
    "Shaders/GrassOptimizations/SPD/SPD.hlsl"
    "Shaders/Skylighting/Skylighting.hlsli"
    "Shaders/WetnessEffects/WetnessEffects.hlsli"
    "Shaders/Upscaling/NeuralRendering/TemporalReuseCS.hlsl"
    "Shaders/Upscaling/Streamline/nvngx_dlss.dll"
)
if(NOT EXPECT_EXTERNAL_DLSSNR_RUNTIME)
    list(APPEND _required_paths "Shaders/Upscaling/Streamline/nvngx_dlssnr.dll")
endif()

if(EXPECT_OPENNR_VERSION)
    set(_expected_changelog "OPENNR-${EXPECT_OPENNR_VERSION}-CHANGELOG.md")
    list(APPEND _required_paths "${_expected_changelog}")
endif()

if(EXPECT_OPENNR_CAPTURE)
    list(APPEND _required_paths "Shaders/Features/OpenNRCapture.ini")
endif()

if(EXPECT_NATIVE_EYE_TRACKING)
    # The experiment is an in-process provider compiled into CommunityShaders.dll.
    # It deliberately does not ship an OpenVR/OpenXR runtime or an interposer layer.
    list(APPEND _required_paths "OpenNR-EyeTracking.md")
endif()

set(_missing_paths "")
foreach(_relative_path IN LISTS _required_paths)
    if(NOT EXISTS "${PACKAGE_ROOT}/${_relative_path}")
        list(APPEND _missing_paths "${_relative_path}")
    endif()
endforeach()

if(_missing_paths)
    string(REPLACE ";" "\n  - " _missing_text "${_missing_paths}")
    message(FATAL_ERROR
        "OpenNR AIO manifest is incomplete. Missing:\n  - ${_missing_text}\n"
        "The package was not accepted."
    )
endif()

if(EXPECT_OPENNR_VERSION)
    # A stale changelog or experiment note is a user-visible version regression
    # even when the binary and shaders are current.  Release stages must carry
    # exactly one version-matched changelog at their root.
    file(
        GLOB
        _version_changelogs
        RELATIVE "${PACKAGE_ROOT}"
        "${PACKAGE_ROOT}/OPENNR-*-CHANGELOG.md"
    )
    list(LENGTH _version_changelogs _changelog_count)
    if(NOT _changelog_count EQUAL 1)
        message(FATAL_ERROR
            "OpenNR package must contain exactly one versioned changelog; found ${_changelog_count}"
        )
    endif()
    list(GET _version_changelogs 0 _actual_changelog)
    if(NOT _actual_changelog STREQUAL _expected_changelog)
        message(FATAL_ERROR
            "OpenNR package changelog is ${_actual_changelog}; expected ${_expected_changelog}"
        )
    endif()
    file(READ "${PACKAGE_ROOT}/${_expected_changelog}" _changelog_text)
    string(FIND "${_changelog_text}" "# OpenNR ${EXPECT_OPENNR_VERSION}" _changelog_version_index)
    if(_changelog_version_index EQUAL -1)
        message(FATAL_ERROR
            "OpenNR package changelog does not identify OpenNR ${EXPECT_OPENNR_VERSION}"
        )
    endif()
    if(EXPECT_NATIVE_EYE_TRACKING)
        file(READ "${PACKAGE_ROOT}/OpenNR-EyeTracking.md" _eye_tracking_notes)
        string(FIND "${_eye_tracking_notes}" "OpenNR ${EXPECT_OPENNR_VERSION}" _eye_tracking_version_index)
        if(_eye_tracking_version_index EQUAL -1)
            message(FATAL_ERROR
                "OpenNR eye-tracking notes do not identify OpenNR ${EXPECT_OPENNR_VERSION}"
            )
        endif()
    endif()
endif()

# Validate the actual packaged shader text as well as the source worktree.
# This catches a copy/staging regression even when the C++ build and binary
# manifest are otherwise healthy.
set(_packaged_skylighting_shader "${PACKAGE_ROOT}/Shaders/Skylighting/Skylighting.hlsli")
set(_packaged_update_shader "${PACKAGE_ROOT}/Shaders/Skylighting/UpdateProbesCS.hlsl")
file(READ "${_packaged_skylighting_shader}" _packaged_skylighting_text)
file(READ "${_packaged_update_shader}" _packaged_update_text)
foreach(_contract IN ITEMS
    "GetArraySize(SharedData::skylightingSettings)"
    "return lerp(SharedData::skylightingSettings.MinDiffuseVisibility"
    "return lerp(SharedData::skylightingSettings.MinSpecularVisibility"
)
    string(FIND "${_packaged_skylighting_text}" "${_contract}" _contract_index)
    if(_contract_index EQUAL -1)
        message(FATAL_ERROR
            "OpenNR package contains an invalid Skylighting shader: missing ${_contract}"
        )
    endif()
endforeach()
foreach(_forbidden_contract IN ITEMS
    "GetArraySize(skylightingSettings)"
    "return lerp(skylightingSettings.MinDiffuseVisibility"
    "return lerp(skylightingSettings.MinSpecularVisibility"
)
    string(FIND "${_packaged_skylighting_text}" "${_forbidden_contract}" _forbidden_index)
    if(NOT _forbidden_index EQUAL -1)
        message(FATAL_ERROR
            "OpenNR package contains an unqualified Skylighting settings reference: ${_forbidden_contract}"
        )
    endif()
endforeach()
string(FIND "${_packaged_update_text}" "const SharedData::SkylightingSettings settings = SharedData::skylightingSettings;" _update_contract_index)
if(_update_contract_index EQUAL -1)
    message(FATAL_ERROR
        "OpenNR package contains an invalid UpdateProbesCS shader: missing qualified Skylighting settings reference"
    )
endif()
string(FIND "${_packaged_update_text}" "const SharedData::SkylightingSettings settings = skylightingSettings;" _bad_update_index)
if(NOT _bad_update_index EQUAL -1)
    message(FATAL_ERROR
        "OpenNR package contains an unqualified UpdateProbesCS Skylighting settings reference"
    )
endif()

if(EXPECT_LEAN_PACKAGE)
    set(_forbidden_lean_paths
        "OpenXR"
        "Renderdoc"
        "Shaders/Features/RenderDoc.ini"
        "SKSE/Plugins/CommunityShaders.pdb"
    )
    set(_unexpected_lean_paths "")
    foreach(_relative_path IN LISTS _forbidden_lean_paths)
        if(EXISTS "${PACKAGE_ROOT}/${_relative_path}")
            list(APPEND _unexpected_lean_paths "${_relative_path}")
        endif()
    endforeach()
    if(_unexpected_lean_paths)
        string(REPLACE ";" "\n  - " _unexpected_text "${_unexpected_lean_paths}")
        message(FATAL_ERROR
            "OpenNR lean archive still contains optional payloads:\n  - ${_unexpected_text}\n"
            "The package was not accepted."
        )
    endif()
endif()

file(SIZE "${PACKAGE_ROOT}/SKSE/Plugins/CommunityShaders.dll" _plugin_size)
if(_plugin_size LESS 1048576)
    message(FATAL_ERROR
        "OpenNR AIO manifest contains an implausibly small CommunityShaders.dll (${_plugin_size} bytes)"
    )
endif()

file(SHA256 "${PACKAGE_ROOT}/SKSE/Plugins/CommunityShaders.dll" _plugin_sha256)
message(STATUS "OpenNR AIO manifest validation passed")
message(STATUS "  CommunityShaders.dll: ${_plugin_size} bytes, SHA-256 ${_plugin_sha256}")
if(EXPECT_EXTERNAL_DLSSNR_RUNTIME)
    message(STATUS "  nvngx_dlssnr.dll: preserved from the existing OpenNR installation")
else()
    file(SIZE "${PACKAGE_ROOT}/Shaders/Upscaling/Streamline/nvngx_dlssnr.dll" _dlssnr_size)
    if(_dlssnr_size LESS 1048576)
        message(FATAL_ERROR
            "OpenNR AIO manifest contains an implausibly small nvngx_dlssnr.dll (${_dlssnr_size} bytes)"
        )
    endif()
    file(SHA256 "${PACKAGE_ROOT}/Shaders/Upscaling/Streamline/nvngx_dlssnr.dll" _dlssnr_sha256)
    message(STATUS "  nvngx_dlssnr.dll: ${_dlssnr_size} bytes, SHA-256 ${_dlssnr_sha256}")
endif()
message(STATUS "  Capture payload: ${EXPECT_OPENNR_CAPTURE}")
message(STATUS "  Native OpenVR eye-tracking: ${EXPECT_NATIVE_EYE_TRACKING}")
message(STATUS "  Lean archive boundary: ${EXPECT_LEAN_PACKAGE}")
