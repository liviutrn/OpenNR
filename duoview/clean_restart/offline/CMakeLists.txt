cmake_minimum_required(VERSION 3.20)
project(JoeyBaselineOfflineChecks LANGUAGES CXX)

if(NOT WIN32)
    message(FATAL_ERROR "The original Joey WARP tests require Windows")
endif()

foreach(root IN ITEMS JOEY_SOURCE JSON_SOURCE OPENXR_SOURCE)
    file(TO_CMAKE_PATH "${${root}}" ${root})
    if(NOT IS_DIRECTORY "${${root}}")
        message(FATAL_ERROR "Missing ${root} checkout")
    endif()
endforeach()

enable_testing()
set(CMAKE_MSVC_RUNTIME_LIBRARY "MultiThreaded$<$<CONFIG:Debug>:Debug>")

add_executable(mono-d3d11-tests "${JOEY_SOURCE}/tests/MonoD3D11Tests.cpp")
target_link_libraries(mono-d3d11-tests PRIVATE d3d11)
add_executable(mono-d3d12-tests "${JOEY_SOURCE}/tests/MonoD3D12Tests.cpp")
target_link_libraries(mono-d3d12-tests PRIVATE d3d12 dxgi)
add_executable(stalker2-native-policy-tests "${JOEY_SOURCE}/tests/Stalker2NativePolicyTests.cpp")
add_executable(stalker2-native-d3d12-tests "${JOEY_SOURCE}/tests/Stalker2NativeD3D12Tests.cpp")
target_link_libraries(stalker2-native-d3d12-tests PRIVATE d3d12 dxgi)

foreach(target IN ITEMS mono-d3d11-tests mono-d3d12-tests stalker2-native-policy-tests stalker2-native-d3d12-tests)
    target_compile_features(${target} PRIVATE cxx_std_23)
    target_include_directories(${target} PRIVATE
        "${JOEY_SOURCE}/src"
        "${JSON_SOURCE}/include"
        "${OPENXR_SOURCE}/include")
    add_test(NAME ${target} COMMAND ${target})
    set_tests_properties(${target} PROPERTIES TIMEOUT 30)
endforeach()
