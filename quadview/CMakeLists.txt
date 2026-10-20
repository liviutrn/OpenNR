cmake_minimum_required(VERSION 3.20)
project(UEVRQuadViewTests LANGUAGES CXX)
set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
# Full gaze/stabilization contracts use production DuoView headers from the
# pinned OpenNR tree. Standalone recovery ZIPs intentionally contain only
# the QuadView overlay, so do not fabricate stand-in production headers.
option(QUADVIEW_REQUIRE_DUOVIEW_TESTS "Require the pinned DuoView test dependency (CI gate)" OFF)
set(QUADVIEW_DUOVIEW_DIR "${CMAKE_CURRENT_SOURCE_DIR}/../duoview")
if(EXISTS "${QUADVIEW_DUOVIEW_DIR}/DuoViewGaze.hpp" AND
   EXISTS "${QUADVIEW_DUOVIEW_DIR}/DuoViewCropStability.hpp" AND
   EXISTS "${QUADVIEW_DUOVIEW_DIR}/DuoViewConfig.hpp" AND
   EXISTS "${QUADVIEW_DUOVIEW_DIR}/DuoViewFrame.hpp" AND
   EXISTS "${QUADVIEW_DUOVIEW_DIR}/DuoViewGeometry.hpp")
  add_executable(QuadViewProducerTests QuadViewTests.cpp)
  target_include_directories(QuadViewProducerTests PRIVATE "${QUADVIEW_DUOVIEW_DIR}")
  if(MSVC)
    target_compile_options(QuadViewProducerTests PRIVATE /UNDEBUG)
  else()
    target_compile_options(QuadViewProducerTests PRIVATE -UNDEBUG)
  endif()
  set(QUADVIEW_FULL_PRODUCER_TESTS ON)
elseif(QUADVIEW_REQUIRE_DUOVIEW_TESTS)
  message(FATAL_ERROR "Exact pinned production DuoView headers are missing; refusing an incomplete CI validation")
else()
  message(WARNING "Recovery ZIP lacks production DuoView headers: QuadViewProducerTests are UNAVAILABLE (not passed)")
endif()
enable_testing()
# Recovery-session property tests; independent of DuoView and restricted SDK headers.
add_executable(QuadViewResumeContractTests ResumeContractTests.cpp)
add_test(NAME quadview-settings-layout-properties COMMAND QuadViewResumeContractTests)
set_tests_properties(quadview-settings-layout-properties PROPERTIES TIMEOUT 60)
if(QUADVIEW_FULL_PRODUCER_TESTS)
  add_test(NAME quadview-geometry-history-transaction COMMAND QuadViewProducerTests)
endif()
find_package(Threads REQUIRED)
add_executable(QuadViewAsyncTests QuadViewAsyncTests.cpp)
target_link_libraries(QuadViewAsyncTests PRIVATE Threads::Threads)
add_test(NAME quadview-asynchronous-delivery COMMAND QuadViewAsyncTests)
set_tests_properties(quadview-asynchronous-delivery PROPERTIES TIMEOUT 60)
if(WIN32)
  find_package(Python3 REQUIRED COMPONENTS Interpreter)
  add_custom_command(OUTPUT "${CMAKE_CURRENT_BINARY_DIR}/QuadViewShaderBytecode.hpp"
    COMMAND "${Python3_EXECUTABLE}" "${CMAKE_CURRENT_SOURCE_DIR}/embed_shader.py"
      "${CMAKE_CURRENT_BINARY_DIR}/QuadViewShaderBytecode.hpp"
    DEPENDS embed_shader.py QuadViewComposite.hlsl)
  add_executable(QuadViewShaderWarpTests QuadViewShaderWarpTest.cpp
    "${CMAKE_CURRENT_BINARY_DIR}/QuadViewShaderBytecode.hpp")
  target_include_directories(QuadViewShaderWarpTests PRIVATE "${CMAKE_CURRENT_BINARY_DIR}")
  target_link_libraries(QuadViewShaderWarpTests PRIVATE d3d12 dxgi d3dcompiler)
  add_test(NAME quadview-stereo-shader-warp
    COMMAND QuadViewShaderWarpTests "${CMAKE_CURRENT_SOURCE_DIR}/QuadViewComposite.hlsl")
  add_test(NAME quadview-stereo-srgb-warp
    COMMAND QuadViewShaderWarpTests "${CMAKE_CURRENT_SOURCE_DIR}/QuadViewComposite.hlsl" --srgb)
  add_test(NAME quadview-stereo-typeless-warp
    COMMAND QuadViewShaderWarpTests "${CMAKE_CURRENT_SOURCE_DIR}/QuadViewComposite.hlsl" --typeless)
  set_tests_properties(quadview-stereo-shader-warp quadview-stereo-srgb-warp quadview-stereo-typeless-warp PROPERTIES TIMEOUT 60)
endif()
