if(NOT DEFINED SOURCE_ROOT OR NOT IS_DIRECTORY "${SOURCE_ROOT}")
    message(FATAL_ERROR "OpenNR source contract validation requires a valid SOURCE_ROOT")
endif()

set(_integration_path "${SOURCE_ROOT}/src/Features/Upscaling/NeuralRendering/Integration.cpp")
set(_upscaling_path "${SOURCE_ROOT}/src/Features/Upscaling.cpp")
if(NOT EXISTS "${_integration_path}" OR NOT EXISTS "${_upscaling_path}")
    message(FATAL_ERROR "OpenNR source contract validation could not find the Neural Rendering integration sources")
endif()

file(READ "${_integration_path}" _integration)
file(READ "${_upscaling_path}" _upscaling)

set(_icon_loader_path "${SOURCE_ROOT}/src/Menu/IconLoader.cpp")
set(_branding_path "${SOURCE_ROOT}/package/OpenNR-BRANDING.txt")
set(_feature_list_path "${SOURCE_ROOT}/src/Menu/FeatureListRenderer.cpp")
set(_menu_path "${SOURCE_ROOT}/src/Menu.cpp")
set(_menu_header_path "${SOURCE_ROOT}/src/Menu/MenuHeaderRenderer.cpp")
set(_upscaling_page_path "${SOURCE_ROOT}/src/Features/Upscaling.cpp")
set(_overlay_renderer_path "${SOURCE_ROOT}/src/Menu/OverlayRenderer.cpp")
set(_helper_client_path "${SOURCE_ROOT}/src/Features/VR/HelperClient.cpp")
set(_foveated_render_path "${SOURCE_ROOT}/src/Features/Upscaling/FoveatedRender.cpp")
set(_foveated_params_path "${SOURCE_ROOT}/src/Features/Upscaling/FoveatedRender/Params.cpp")
set(_native_openvr_gaze_header_path "${SOURCE_ROOT}/src/Features/Upscaling/NativeOpenVRGaze.h")
set(_native_openvr_gaze_source_path "${SOURCE_ROOT}/src/Features/Upscaling/NativeOpenVRGaze.cpp")
set(_future_pipeline_path "${SOURCE_ROOT}/src/Features/Upscaling/NeuralRendering/FuturePipeline.h")
set(_runtime_header_path "${SOURCE_ROOT}/src/Features/Upscaling/NeuralRendering/Runtime.h")
set(_runtime_source_path "${SOURCE_ROOT}/src/Features/Upscaling/NeuralRendering/Runtime.cpp")
set(_renderer_path "${SOURCE_ROOT}/src/Features/Upscaling/NeuralRendering/Renderer.cpp")
set(_skylighting_header_path "${SOURCE_ROOT}/src/Features/Skylighting.h")
set(_skylighting_source_path "${SOURCE_ROOT}/src/Features/Skylighting.cpp")
set(_shared_data_path "${SOURCE_ROOT}/package/Shaders/Common/SharedData.hlsli")
set(_skylighting_shader_path "${SOURCE_ROOT}/features/Skylighting/Shaders/Skylighting/Skylighting.hlsli")
set(_skylighting_update_shader_path "${SOURCE_ROOT}/features/Skylighting/Shaders/Skylighting/UpdateProbesCS.hlsl")
set(_cmake_path "${SOURCE_ROOT}/CMakeLists.txt")
set(_presets_path "${SOURCE_ROOT}/CMakePresets.json")
set(_streamline_runtime_path "${SOURCE_ROOT}/cmake/Streamline-Runtime.cmake")
set(_temporal_shader_path "${SOURCE_ROOT}/features/Upscaling/Shaders/Upscaling/NeuralRendering/TemporalReuseCS.hlsl")
set(_dlssnr_carrier_path "${SOURCE_ROOT}/package/Shaders/Upscaling/Streamline/nvngx_dlssnr.dll")
set(_vr_helper_runtime_path "${SOURCE_ROOT}/package/SKSE/Plugins/imgui-vr-helper.dll")
if(DEFINED OPENNR_DLSSNR_RUNTIME_SOURCE)
    set(_dlssnr_carrier_path "${OPENNR_DLSSNR_RUNTIME_SOURCE}")
endif()
if(DEFINED OPENNR_IMGUI_HELPER_SOURCE)
    set(_vr_helper_runtime_path "${OPENNR_IMGUI_HELPER_SOURCE}")
endif()
set(_vr_helper_config_path "${SOURCE_ROOT}/package/SKSE/Plugins/ImGuiVRHelper.toml")
if(NOT EXISTS "${_icon_loader_path}" OR NOT EXISTS "${_branding_path}" OR
   NOT EXISTS "${_feature_list_path}" OR NOT EXISTS "${_upscaling_page_path}" OR
   NOT EXISTS "${_menu_path}" OR NOT EXISTS "${_menu_header_path}" OR
   NOT EXISTS "${_overlay_renderer_path}" OR NOT EXISTS "${_helper_client_path}" OR
   NOT EXISTS "${_foveated_render_path}" OR
   NOT EXISTS "${_foveated_params_path}" OR
   NOT EXISTS "${_native_openvr_gaze_header_path}" OR NOT EXISTS "${_native_openvr_gaze_source_path}" OR
   NOT EXISTS "${_future_pipeline_path}" OR NOT EXISTS "${_cmake_path}" OR
   NOT EXISTS "${_runtime_header_path}" OR NOT EXISTS "${_runtime_source_path}" OR
   NOT EXISTS "${_renderer_path}" OR NOT EXISTS "${_skylighting_header_path}" OR
   NOT EXISTS "${_skylighting_source_path}" OR NOT EXISTS "${_shared_data_path}" OR
   NOT EXISTS "${_skylighting_shader_path}" OR NOT EXISTS "${_skylighting_update_shader_path}" OR
   NOT EXISTS "${_presets_path}" OR NOT EXISTS "${_streamline_runtime_path}" OR
   NOT EXISTS "${_temporal_shader_path}" OR
   NOT EXISTS "${_vr_helper_runtime_path}" OR NOT EXISTS "${_vr_helper_config_path}")
    message(FATAL_ERROR
        "OpenNR source contract validation could not find one or more release contracts"
    )
endif()
if(NOT OPENNR_EXTERNAL_DLSSNR_RUNTIME AND NOT EXISTS "${_dlssnr_carrier_path}")
    message(FATAL_ERROR "OpenNR source contract validation could not find the Feature 18 carrier")
endif()
file(READ "${_icon_loader_path}" _icon_loader)
file(READ "${_branding_path}" _branding)
file(READ "${_feature_list_path}" _feature_list)
file(READ "${_menu_path}" _menu)
file(READ "${_menu_header_path}" _menu_header)
file(READ "${_upscaling_page_path}" _upscaling_page)
file(READ "${_overlay_renderer_path}" _overlay_renderer)
file(READ "${_helper_client_path}" _helper_client)
file(READ "${_foveated_render_path}" _foveated_render)
file(READ "${_foveated_params_path}" _foveated_params)
file(READ "${_native_openvr_gaze_header_path}" _native_openvr_gaze_header)
file(READ "${_native_openvr_gaze_source_path}" _native_openvr_gaze_source)
file(READ "${_future_pipeline_path}" _future_pipeline)
file(READ "${_runtime_header_path}" _runtime_header)
file(READ "${_runtime_source_path}" _runtime_source)
file(READ "${_renderer_path}" _renderer)
file(READ "${_skylighting_header_path}" _skylighting_header)
file(READ "${_skylighting_source_path}" _skylighting_source)
file(READ "${_shared_data_path}" _shared_data)
file(READ "${_skylighting_shader_path}" _skylighting_shader)
file(READ "${_skylighting_update_shader_path}" _skylighting_update_shader)
file(READ "${_cmake_path}" _cmake)
file(READ "${_presets_path}" _presets)
file(READ "${_streamline_runtime_path}" _streamline_runtime)

set(_feature_source_paths
    "${SOURCE_ROOT}/src/Features/GrassOptimizations.cpp"
    "${SOURCE_ROOT}/src/Features/GrassOptimizations/HiZPyramid.cpp"
    "${SOURCE_ROOT}/src/Features/VR/DynamicNearClip.cpp"
    "${SOURCE_ROOT}/src/Features/Skylighting.cpp"
    "${SOURCE_ROOT}/src/Features/VRS.cpp"
    "${SOURCE_ROOT}/src/Features/Effects11.cpp"
    "${SOURCE_ROOT}/src/Features/Effects11/SettingManager.cpp"
    "${SOURCE_ROOT}/src/XSEPlugin.cpp"
    "${SOURCE_ROOT}/package/Shaders/Lighting.hlsl"
)
foreach(_feature_source IN LISTS _feature_source_paths)
    if(NOT EXISTS "${_feature_source}")
        message(FATAL_ERROR
            "OpenNR feature-chain source contract is missing: ${_feature_source}"
        )
    endif()
endforeach()

foreach(_contract IN ITEMS
    "Feature18GuideContract"
    "NVSDK_NGX_Parameter_DLSS_Feature_Create_Flags"
    "NVSDK_NGX_Parameter_DLSS_Input_MV_SubrectBase_X"
    "DLSSNR.MVecLowRes"
)
    string(FIND "${_runtime_header}${_runtime_source}" "${_contract}" _contract_index)
    if(_contract_index EQUAL -1)
        message(FATAL_ERROR
            "OpenNR native Feature 18 guide contract missing: ${_contract}\n"
            "The runtime could silently misinterpret per-eye color, depth, or motion-vector resources."
        )
    endif()
endforeach()

foreach(_contract IN ITEMS
    "firstInputWidth"
    "guide.motionVectorsLowResolution"
)
    string(FIND "${_renderer}" "${_contract}" _contract_index)
    if(_contract_index EQUAL -1)
        message(FATAL_ERROR
            "OpenNR renderer guide wiring missing: ${_contract}\n"
            "The Feature 18 cascade would lose its exact first-input or MV-resolution metadata."
        )
    endif()
endforeach()

foreach(_contract IN ITEMS
    "ProbeGridQuality"
    "EnableIncrementalProbeUpdates"
    "queuedSetupResources"
    "ApplyOcclusionCornerFrustum"
)
    string(FIND "${_skylighting_header}${_skylighting_source}" "${_contract}" _contract_index)
    if(_contract_index EQUAL -1)
        message(FATAL_ERROR
            "OpenNR Skylighting scheduling contract missing: ${_contract}\n"
            "The validated grid/scheduling/four-corner port would be incomplete."
        )
    endif()
endforeach()

foreach(_contract IN ITEMS
    "ProbeUpdateSliceStart"
    "GetArrayDims"
    "probeTexID"
)
    string(FIND "${_shared_data}${_skylighting_shader}${_skylighting_update_shader}" "${_contract}" _contract_index)
    if(_contract_index EQUAL -1)
        message(FATAL_ERROR
            "OpenNR Skylighting shader contract missing: ${_contract}\n"
            "The runtime grid/slice settings would not reach the shader path."
        )
    endif()
endforeach()

# Skylighting's settings live in the SharedData namespace.  An unqualified
# reference compiles only in some tooling contexts and then fails the game's
# runtime shader compiler for every shader that includes Skylighting.hlsli.
foreach(_contract IN ITEMS
    "GetArraySize(SharedData::skylightingSettings)"
    "return lerp(SharedData::skylightingSettings.MinDiffuseVisibility"
    "return lerp(SharedData::skylightingSettings.MinSpecularVisibility"
)
    string(FIND "${_skylighting_shader}" "${_contract}" _contract_index)
    if(_contract_index EQUAL -1)
        message(FATAL_ERROR
            "OpenNR Skylighting shader qualification contract missing: ${_contract}\n"
            "The runtime shader compiler would reject the common Skylighting include."
        )
    endif()
endforeach()

foreach(_forbidden_contract IN ITEMS
    "GetArraySize(skylightingSettings)"
    "return lerp(skylightingSettings.MinDiffuseVisibility"
    "return lerp(skylightingSettings.MinSpecularVisibility"
)
    string(FIND "${_skylighting_shader}" "${_forbidden_contract}" _forbidden_index)
    if(NOT _forbidden_index EQUAL -1)
        message(FATAL_ERROR
            "OpenNR Skylighting shader contains an unqualified settings reference: ${_forbidden_contract}\n"
            "The package must use SharedData::skylightingSettings."
        )
    endif()
endforeach()

set(_qualified_update_contract "const SharedData::SkylightingSettings settings = SharedData::skylightingSettings;")
string(FIND "${_skylighting_update_shader}" "${_qualified_update_contract}" _update_contract_index)
if(_update_contract_index EQUAL -1)
    message(FATAL_ERROR
        "OpenNR UpdateProbesCS shader qualification contract is missing\n"
        "The compute shader must read SharedData::skylightingSettings."
    )
endif()
set(_unqualified_update_contract "const SharedData::SkylightingSettings settings = skylightingSettings;")
string(FIND "${_skylighting_update_shader}" "${_unqualified_update_contract}" _bad_update_index)
if(NOT _bad_update_index EQUAL -1)
    message(FATAL_ERROR
        "OpenNR UpdateProbesCS shader contains an unqualified settings reference\n"
        "The package must use SharedData::skylightingSettings."
    )
endif()

# Keep the probe address arithmetic unsigned: ArrayOrigin is intentionally a
# wrapped coordinate, so clamping a signed difference aliases wrapped bands to
# cell zero. Also normalize shadow visibility by the number of valid samples
# during warm-up; a cleared bitmask means "unknown", not 31 shadowed samples.
set(_wrapped_cell_contract "uint3 cellID = (probeTexID - settings.ArrayOrigin.xyz) % arrayDims;")
string(FIND "${_skylighting_update_shader}" "${_wrapped_cell_contract}" _wrapped_cell_index)
if(_wrapped_cell_index EQUAL -1)
    message(FATAL_ERROR
        "OpenNR Skylighting wrapped-cell contract is missing\n"
        "Probe addressing must preserve unsigned toroidal subtraction."
    )
endif()
set(_shadow_history_contract "const uint shadowHistoryFrames = max(1u, min(outAccumFramesArray[probeTexID], 32u));")
string(FIND "${_skylighting_update_shader}" "${_shadow_history_contract}" _shadow_history_index)
if(_shadow_history_index EQUAL -1)
    message(FATAL_ERROR
        "OpenNR Skylighting shadow-history warm-up contract is missing\n"
        "Freshly reset probes must not fade toward black while samples accumulate."
    )
endif()
set(_bad_wrapped_cell_contract "uint3 cellID = uint3(max(signedCellID")
string(FIND "${_skylighting_update_shader}" "${_bad_wrapped_cell_contract}" _bad_wrapped_cell_index)
if(NOT _bad_wrapped_cell_index EQUAL -1)
    message(FATAL_ERROR
        "OpenNR Skylighting shader contains the signed/clamped wrapped-cell regression"
    )
endif()
set(_bad_shadow_history_contract "float shadow = float(countbits(bitmask)) / 32.0;")
string(FIND "${_skylighting_update_shader}" "${_bad_shadow_history_contract}" _bad_shadow_history_index)
if(NOT _bad_shadow_history_index EQUAL -1)
    message(FATAL_ERROR
        "OpenNR Skylighting shader contains the fixed-32 warm-up regression"
    )
endif()

file(READ "${SOURCE_ROOT}/src/Features/GrassOptimizations.cpp" _grass_optimizations)
file(READ "${SOURCE_ROOT}/src/Features/GrassOptimizations/HiZPyramid.cpp" _grass_hiz)
file(READ "${SOURCE_ROOT}/src/Features/VR/DynamicNearClip.cpp" _dynamic_near_clip)
file(READ "${SOURCE_ROOT}/src/Features/Skylighting.cpp" _skylighting)
file(READ "${SOURCE_ROOT}/src/Features/VRS.cpp" _vrs)
file(READ "${SOURCE_ROOT}/src/Features/Effects11.cpp" _effects11)
file(READ "${SOURCE_ROOT}/src/Features/Effects11/SettingManager.cpp" _effects11_settings)
file(READ "${SOURCE_ROOT}/src/XSEPlugin.cpp" _xse_plugin)
file(READ "${SOURCE_ROOT}/package/Shaders/Lighting.hlsl" _lighting)

set(_feature_chain_text
    "${_grass_optimizations}${_grass_hiz}${_dynamic_near_clip}${_skylighting}${_vrs}${_effects11}${_effects11_settings}${_xse_plugin}${_lighting}"
)
foreach(_contract IN ITEMS
    "GrassOptimizations::OnVisible"
    "GrassOptimizations::VanillaOnVisible"
    "SPD.hlsl"
    "dynamic near clip"
    "validOccluder"
    "SIMPLE_TREE_WETNESS"
    "0.264.0"
    "RegisterUxActions"
    "currentValue"
    "SuspendVRS"
)
    string(FIND "${_feature_chain_text}" "${_contract}" _contract_index)
    if(_contract_index EQUAL -1)
        message(FATAL_ERROR
            "OpenNR pre-rebrand feature-chain contract missing: ${_contract}\n"
            "The older Open Shaders/DLSSNR-VR feature lineage would regress."
        )
    endif()
endforeach()

if(NOT OPENNR_EXTERNAL_DLSSNR_RUNTIME)
    file(SIZE "${_dlssnr_carrier_path}" _source_dlssnr_size)
    if(_source_dlssnr_size LESS 1048576)
        message(FATAL_ERROR
            "OpenNR source contract found an implausibly small native Feature 18 carrier: ${_source_dlssnr_size} bytes"
        )
    endif()
endif()

file(SIZE "${_vr_helper_runtime_path}" _source_vr_helper_size)
if(_source_vr_helper_size LESS 524288)
    message(FATAL_ERROR
        "OpenNR source contract found an implausibly small ImGuiVRHelper runtime: ${_source_vr_helper_size} bytes"
    )
endif()
file(SHA256 "${_vr_helper_runtime_path}" _source_vr_helper_sha256)
if(NOT _source_vr_helper_sha256 STREQUAL "bf2941d4513a37d526d37fd8bf657823e3dbf2c31a085ed28c6ee224c828eba6")
    message(FATAL_ERROR
        "OpenNR source contract rejected an unverified ImGuiVRHelper runtime hash: ${_source_vr_helper_sha256}"
    )
endif()

set(_integration_contracts
    "bool IsGameMenuOpen()"
    "return consoleOpen || (state && state->isLoadingMenuOpen);"
    "bool menuChanged = false;"
    "FoveatedRenderImpl::Core::InvalidateTemporalState();"
    "if (temporalSuppressed || IsGameMenuOpen())"
)
foreach(_contract IN LISTS _integration_contracts)
    string(FIND "${_integration}" "${_contract}" _contract_index)
    if(_contract_index EQUAL -1)
        message(FATAL_ERROR
            "OpenNR source contract missing from Integration.cpp: ${_contract}\n"
            "The ordinary-menu NR preservation path is incomplete."
        )
    endif()
endforeach()

set(_old_menu_suppression "return consoleOpen || (state && state->IsPausedOrMenuOpen(ui));")
string(FIND "${_integration}" "${_old_menu_suppression}" _old_integration_index)
if(NOT _old_integration_index EQUAL -1)
    message(FATAL_ERROR
        "OpenNR source contract rejected the blanket IsPausedOrMenuOpen temporal suppression path"
    )
endif()

set(_upscaling_contracts
    "const bool temporalOverlayOpen = consoleOpen || (st && st->isLoadingMenuOpen);"
    "const bool menuGuidesReady = !menuOpen || menuCameraMVsValid || (st && st->worldRenderedThisFrame);"
    "!temporalOverlayOpen && menuGuidesReady"
)
foreach(_contract IN LISTS _upscaling_contracts)
    string(FIND "${_upscaling}" "${_contract}" _contract_index)
    if(_contract_index EQUAL -1)
        message(FATAL_ERROR
            "OpenNR source contract missing from Upscaling.cpp: ${_contract}\n"
            "The ordinary-menu guide gate is incomplete."
        )
    endif()
endforeach()

foreach(_contract IN ITEMS
    "key == VK_F6"
    "neuralRenderingEnabled"
    "NeuralRendering::RequestHistoryReset()"
    "VRFontScale"
)
    string(FIND "${_menu}" "${_contract}" _contract_index)
    if(_contract_index EQUAL -1)
        message(FATAL_ERROR
            "OpenNR input contract missing from Menu.cpp: ${_contract}\n"
            "The documented F6 Neural Rendering toggle is incomplete."
        )
    endif()
endforeach()

set(_branding_contracts
    "OpenNR Logo"
    "opennr-logo.png"
)
foreach(_contract IN LISTS _branding_contracts)
    string(FIND "${_icon_loader}" "${_contract}" _contract_index)
    if(_contract_index EQUAL -1)
        message(FATAL_ERROR
            "OpenNR branding contract missing from IconLoader.cpp: ${_contract}\n"
            "The runtime would fall back to the old Community Shaders logo."
        )
    endif()
endforeach()

string(FIND "${_icon_loader}" "Community Shaders Logo" _legacy_logo_index)
if(NOT _legacy_logo_index EQUAL -1)
    message(FATAL_ERROR
        "OpenNR branding contract rejected the legacy Community Shaders logo path in IconLoader.cpp"
    )
endif()

string(FIND "${_branding}" "OpenNR Capture is a related feature integrated into this package." _branding_index)
if(_branding_index EQUAL -1)
    message(FATAL_ERROR
        "OpenNR branding manifest is incomplete: package/OpenNR-BRANDING.txt must describe the capture boundary"
    )
endif()

foreach(_contract IN ITEMS
    "BuiltInMenu{ T(\"menu.features.dlssnr\", \"Neural Rendering\"), \"DLSSNR\""
    "BuiltInMenu{ T(\"menu.features.upscaling\", \"Upscaling\"), \"Upscaling\""
    "DrawDLSSNRPage()"
    "globals::features::upscaling.DrawSettings()"
    "separatorBefore"
)
    string(FIND "${_feature_list}" "${_contract}" _contract_index)
    if(_contract_index EQUAL -1)
        message(FATAL_ERROR
            "OpenNR menu contract missing from FeatureListRenderer.cpp: ${_contract}\n"
            "The dedicated Neural Rendering page would regress or disappear from the in-game menu."
        )
    endif()
endforeach()

foreach(_contract IN ITEMS
    "auto displayTitle = std::format(\"OpenNR {}\", versionStr);"
    "auto title = std::format(\"{}###CommunityShaders\", displayTitle);"
)
    string(FIND "${_menu}" "${_contract}" _contract_index)
    if(_contract_index EQUAL -1)
        message(FATAL_ERROR
            "OpenNR user-facing title contract missing from Menu.cpp: ${_contract}\n"
            "The menu title must remain exactly OpenNR <version>."
        )
    endif()
endforeach()

string(FIND "${_menu_header}" "auto title = std::format(\"OpenNR {}\", versionStr);" _menu_header_title_index)
if(_menu_header_title_index EQUAL -1)
    message(FATAL_ERROR
        "OpenNR user-facing header title contract missing from MenuHeaderRenderer.cpp"
    )
endif()

foreach(_contract IN ITEMS
    "NativeOpenVRGaze::Config"
    "NativeOpenVRGaze::ResolveForFrame"
    "neuralRenderingEyeTrackedFoveation"
    "Native OpenVR gaze provider"
)
    string(FIND "${_foveated_render}${_foveated_params}${_integration}" "${_contract}" _contract_index)
    if(_contract_index EQUAL -1)
        message(FATAL_ERROR
            "OpenNR native OpenVR eye-tracking wiring missing: ${_contract}\n"
            "The experimental provider must stay opt-in and fail closed through the existing foveated/NR path."
        )
    endif()
endforeach()

foreach(_contract IN ITEMS
    "IVRSystem_026"
    "GetEyeTrackedFoveationCenter"
    "kEyeTrackedFoveationCenterVtableIndex"
    "VR_GetGenericInterface"
    "GetInitToken"
)
    string(FIND "${_native_openvr_gaze_header}${_native_openvr_gaze_source}" "${_contract}" _contract_index)
    if(_contract_index EQUAL -1)
        message(FATAL_ERROR
            "OpenNR native OpenVR eye-tracking ABI contract missing: ${_contract}"
        )
    endif()
endforeach()

foreach(_contract IN ITEMS
    "void Upscaling::DrawDLSSNRPage()"
    "Temporal Stability"
    "neuralRenderingTemporalReuseCadence"
    "neuralRenderingTemporalReuseResetAfterSkip"
)
    string(FIND "${_upscaling_page}${_foveated_render}" "${_contract}" _contract_index)
    if(_contract_index EQUAL -1)
        message(FATAL_ERROR
            "OpenNR Neural Rendering UI contract missing: ${_contract}\n"
            "The temporal-reuse controls or dedicated page would regress."
        )
    endif()
endforeach()

foreach(_contract IN ITEMS
    "ApplyVRPanelDisplaySize()"
    "DesktopMirrorDrawData"
    "BackgroundBlur::RenderDrawData"
    "RenderHelperToPanel()"
)
    string(FIND "${_overlay_renderer}" "${_contract}" _contract_index)
    if(_contract_index EQUAL -1)
        message(FATAL_ERROR
            "OpenNR menu rendering contract missing from OverlayRenderer.cpp: ${_contract}\n"
            "VR panel sizing, desktop fitting, or helper-panel submission would regress."
        )
    endif()
endforeach()

foreach(_contract IN ITEMS
    "GetPointer(g_client.Id(), &pointerU, &pointerV, nullptr)"
    "g_client.PumpInput(pointerInPanel, clampedDeadzone)"
)
    string(FIND "${_helper_client}" "${_contract}" _contract_index)
    if(_contract_index EQUAL -1)
        message(FATAL_ERROR
            "OpenNR desktop/VR input ownership contract missing from HelperClient.cpp: ${_contract}\n"
            "The helper must not park or replace the desktop cursor when the wand is off-panel."
        )
    endif()
endforeach()

foreach(_contract IN ITEMS
    "VERSION 2.15.1"
    "does not match OpenNR"
    "OPENNR_LEAN_PACKAGE"
)
    string(FIND "${_cmake}" "${_contract}" _contract_index)
    if(_contract_index EQUAL -1)
        message(FATAL_ERROR
            "OpenNR release contract missing from CMakeLists.txt: ${_contract}"
        )
    endif()
endforeach()

foreach(_contract IN ITEMS
    "\"SKSE_SUPPORT_XBYAK\": \"ON\""
    "\"OPENNR_LEAN_PACKAGE\": \"ON\""
    "\"AIO_INCLUDE_OPENNR_CAPTURE\": \"ON\""
)
    string(FIND "${_presets}" "${_contract}" _contract_index)
    if(_contract_index EQUAL -1)
        message(FATAL_ERROR
            "OpenNR package preset contract missing from CMakePresets.json: ${_contract}"
        )
    endif()
endforeach()

foreach(_contract IN ITEMS
    "OPENNR_DLSSNR_RUNTIME_SOURCE"
    "file(COPY_FILE"
    "nvngx_dlssnr.dll"
)
    string(FIND "${_streamline_runtime}" "${_contract}" _contract_index)
    if(_contract_index EQUAL -1)
        message(FATAL_ERROR
            "OpenNR Feature 18 staging contract missing from Streamline-Runtime.cmake: ${_contract}"
        )
    endif()
endforeach()

foreach(_contract IN ITEMS
    "struct AsyncOwnershipContract"
    "static constexpr bool kRuntimeEnabled = false;"
    "struct DepthMatchedResidualFillContract"
    "struct PeripheralCompressionContract"
)
    string(FIND "${_future_pipeline}" "${_contract}" _contract_index)
    if(_contract_index EQUAL -1)
        message(FATAL_ERROR
            "OpenNR future-pipeline boundary missing from FuturePipeline.h: ${_contract}"
        )
    endif()
endforeach()

message(STATUS "OpenNR runtime source contracts passed (ordinary menus preserve NR; loading/console remain fail-closed; branded logo contract present)")
