cmake_minimum_required(VERSION 3.22)
project(GlamaryeSharpenUEVR LANGUAGES CXX)
if(NOT WIN32)
  message(FATAL_ERROR "UEVR DX12 plugin requires Windows")
endif()
add_library(GlamaryeSharpenUEVR SHARED
    src/plugin.cpp src/layer_bridge.cpp src/shader.hpp vendor/uevr/API.h)
target_compile_features(GlamaryeSharpenUEVR PRIVATE cxx_std_20)
target_include_directories(GlamaryeSharpenUEVR PRIVATE vendor src)
target_compile_definitions(GlamaryeSharpenUEVR PRIVATE UNICODE _UNICODE NOMINMAX)
target_compile_options(GlamaryeSharpenUEVR PRIVATE /W4 /EHsc)
target_link_libraries(GlamaryeSharpenUEVR PRIVATE d3d12 d3dcompiler dxgi)
set_target_properties(GlamaryeSharpenUEVR PROPERTIES
    OUTPUT_NAME "GlamaryeSharpenUEVR")

enable_testing()
add_executable(GlamaryeShaderTest tests/shader_compile.cpp src/shader.hpp)
target_include_directories(GlamaryeShaderTest PRIVATE src)
target_compile_features(GlamaryeShaderTest PRIVATE cxx_std_20)
target_link_libraries(GlamaryeShaderTest PRIVATE d3dcompiler)
add_test(NAME HLSL_Compilation COMMAND GlamaryeShaderTest)

add_executable(GlamaryeGpuTest tests/gpu_smoke.cpp vendor/uevr/API.h)
target_include_directories(GlamaryeGpuTest PRIVATE vendor)
target_compile_features(GlamaryeGpuTest PRIVATE cxx_std_20)
target_link_libraries(GlamaryeGpuTest PRIVATE d3d12 dxgi)
add_dependencies(GlamaryeGpuTest GlamaryeSharpenUEVR)
add_test(NAME DX12_WARP_Callback_Render COMMAND GlamaryeGpuTest)

add_test(NAME DX12_WARP_SRGB_Projection COMMAND GlamaryeGpuTest srgb)
add_test(NAME DX12_WARP_Typeless_SRGB_Projection COMMAND GlamaryeGpuTest typeless)

add_test(NAME DX12_WARP_Red_Grid COMMAND GlamaryeGpuTest debug)

# Simulated headset-side OpenXR lifecycle, including scene-vs-UI classification.
add_executable(GlamaryeOpenXRMock tests/openxr_mock.cpp vendor/uevr/API.h)
target_include_directories(GlamaryeOpenXRMock PRIVATE vendor src)
target_compile_features(GlamaryeOpenXRMock PRIVATE cxx_std_20)
target_link_libraries(GlamaryeOpenXRMock PRIVATE d3d12 dxgi)
add_test(NAME OpenXR_WARP_Scene_Integration COMMAND GlamaryeOpenXRMock)

include(FetchContent)
FetchContent_Declare(glam_xr_headers
    GIT_REPOSITORY https://github.com/KhronosGroup/OpenXR-SDK.git
    GIT_TAG 458984d7f59d1ae6dc1b597d94b02e4f7132eaba
    GIT_SHALLOW FALSE)
FetchContent_GetProperties(glam_xr_headers)
if(NOT glam_xr_headers_POPULATED)
    FetchContent_Populate(glam_xr_headers)
endif()
add_library(GlamaryeOpenXRLayer SHARED layer/openxr_layer.cpp)
target_compile_features(GlamaryeOpenXRLayer PRIVATE cxx_std_20)
target_compile_definitions(GlamaryeOpenXRLayer PRIVATE WIN32_LEAN_AND_MEAN NOMINMAX)
target_include_directories(GlamaryeOpenXRLayer PRIVATE
    "${glam_xr_headers_SOURCE_DIR}/include"
    "${glam_xr_headers_SOURCE_DIR}/src/common")
target_link_libraries(GlamaryeOpenXRLayer PRIVATE d3d12)
target_compile_options(GlamaryeOpenXRLayer PRIVATE /W4 /EHsc)

add_executable(GlamaryeLayerIntegration tests/openxr_layer_integration.cpp)
target_compile_features(GlamaryeLayerIntegration PRIVATE cxx_std_20)
target_include_directories(GlamaryeLayerIntegration PRIVATE
    vendor
    "${glam_xr_headers_SOURCE_DIR}/include"
    "${glam_xr_headers_SOURCE_DIR}/src/common")
target_link_libraries(GlamaryeLayerIntegration PRIVATE d3d12 dxgi)
add_dependencies(GlamaryeLayerIntegration GlamaryeSharpenUEVR GlamaryeOpenXRLayer)
add_test(NAME Khronos_OpenXR_Layer_And_GPU_Integration COMMAND GlamaryeLayerIntegration)

# Real DX12 WARP pixel-differential tests: 4 radii, original FXAA edge
# attenuation, isolated one-pixel wire suppression, multi-band mixing.
add_executable(GlamaryeRadiusAndLines tests/radius_and_lines.cpp)
target_compile_features(GlamaryeRadiusAndLines PRIVATE cxx_std_20)
target_include_directories(GlamaryeRadiusAndLines PRIVATE vendor)
target_link_libraries(GlamaryeRadiusAndLines PRIVATE d3d12 dxgi)
add_dependencies(GlamaryeRadiusAndLines GlamaryeSharpenUEVR)
add_test(NAME DX12_WARP_Radii_And_Thin_Lines COMMAND GlamaryeRadiusAndLines)

# Stable-release regression tests: fresh defaults, v0.1 settings migration,
# four independent settings, diagnostics off after restart and UI persistence.
add_executable(GlamaryeConfigRegression tests/config_regression.cpp vendor/uevr/API.h)
target_compile_features(GlamaryeConfigRegression PRIVATE cxx_std_20)
target_include_directories(GlamaryeConfigRegression PRIVATE vendor)
add_dependencies(GlamaryeConfigRegression GlamaryeSharpenUEVR)
foreach(case_name fresh old_big old_small explicit timing_saved ui_events)
    add_test(NAME Stable_Config_${case_name} COMMAND GlamaryeConfigRegression ${case_name})
endforeach()
