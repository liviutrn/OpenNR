cmake_minimum_required(VERSION 3.20)
project(UEVRQuadViewTests LANGUAGES CXX)
set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
add_executable(QuadViewProducerTests QuadViewTests.cpp)
if(MSVC)
  target_compile_options(QuadViewProducerTests PRIVATE /UNDEBUG)
else()
  target_compile_options(QuadViewProducerTests PRIVATE -UNDEBUG)
endif()
enable_testing()
add_test(NAME quadview-geometry-history-transaction COMMAND QuadViewProducerTests)
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
  set_tests_properties(quadview-stereo-shader-warp quadview-stereo-srgb-warp PROPERTIES TIMEOUT 60)
endif()
