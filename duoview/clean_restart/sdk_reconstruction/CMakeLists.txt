cmake_minimum_required(VERSION 3.20)
project(JoeySdkReconstructionChecks LANGUAGES CXX)

if(NOT WIN32 OR NOT CMAKE_SIZEOF_VOID_P EQUAL 8)
    message(FATAL_ERROR "Original SDK differential tests require Windows x64")
endif()

enable_testing()
add_executable(sdk-memory-differential-tests
    src/DiscoveryMemory.cpp tests/WindowsMemoryTests.cpp)
target_compile_features(sdk-memory-differential-tests PRIVATE cxx_std_23)
target_include_directories(sdk-memory-differential-tests PRIVATE include tests)
if(MSVC)
    target_compile_options(sdk-memory-differential-tests PRIVATE /W4 /WX)
endif()
add_test(NAME sdk-memory-differential-tests COMMAND sdk-memory-differential-tests)
set_tests_properties(sdk-memory-differential-tests PROPERTIES TIMEOUT 30)
