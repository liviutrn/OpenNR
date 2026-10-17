cmake_minimum_required(VERSION 3.20)
project(JoeyQuadPairContracts LANGUAGES CXX)
enable_testing()
find_package(Threads REQUIRED)

function(add_portable_test name source)
 add_executable(${name} ${source})
 target_compile_features(${name} PRIVATE cxx_std_20)
 target_link_libraries(${name} PRIVATE Threads::Threads)
 if(MSVC)
  target_compile_options(${name} PRIVATE /W4 /WX /permissive- /EHsc)
 else()
  target_compile_options(${name} PRIVATE -Wall -Wextra -Werror -pedantic)
 endif()
 add_test(NAME ${name} COMMAND ${name})
endfunction()

add_portable_test(QuadPairLedgerTests tests/QuadPairLedgerTests.cpp)
add_portable_test(QuadPairCoordinatorTests tests/QuadPairCoordinatorTests.cpp)
add_portable_test(FourHistoryLeaseTests tests/FourHistoryLeaseTests.cpp)
add_portable_test(NativePairHistoryOwnerTests tests/NativePairHistoryOwnerTests.cpp)
# Verifies the previously failed v22 source contract without invoking its
# nonportable UEVR backend; all three are CPU-only test executables.
add_portable_test(DuoViewStage10Tests ../duoview/stage10_state_tests.cpp)
