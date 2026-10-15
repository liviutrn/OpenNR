cmake_minimum_required(VERSION 3.20)
project(stable_source_mask_d3d12_tests LANGUAGES CXX)

if(NOT WIN32)
    message(FATAL_ERROR "The stable-source-mask WARP tests require Windows and D3D12.")
endif()

enable_testing()

add_executable(stable_source_mask_d3d12_tests stable_source_mask_d3d12_tests.cpp)
target_compile_features(stable_source_mask_d3d12_tests PRIVATE cxx_std_17)
target_include_directories(stable_source_mask_d3d12_tests PRIVATE
    "${CMAKE_CURRENT_LIST_DIR}/support"
    "${CMAKE_CURRENT_LIST_DIR}/..")
target_link_libraries(stable_source_mask_d3d12_tests PRIVATE d3d12 dxgi d3dcompiler)

if(MSVC)
    target_compile_options(stable_source_mask_d3d12_tests PRIVATE /W4 /WX /permissive-)
else()
    target_compile_options(stable_source_mask_d3d12_tests PRIVATE -Wall -Wextra -Werror)
endif()

add_test(NAME stable_source_mask_d3d12_warp COMMAND stable_source_mask_d3d12_tests)
set_tests_properties(stable_source_mask_d3d12_warp PROPERTIES
    SKIP_RETURN_CODE 77
    TIMEOUT 180)
