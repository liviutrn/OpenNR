cmake_minimum_required(VERSION 3.31)
project(OpenNRPackagedValidation LANGUAGES CXX)
find_package(cppwinrt CONFIG REQUIRED)
find_package(spdlog CONFIG REQUIRED)
add_executable(opennr_packaged_validation test-packaged-warp.cpp
  ../../runtime/open-shaders/src/Utils/ShaderInclude.cpp)
target_compile_features(opennr_packaged_validation PRIVATE cxx_std_20)
target_compile_definitions(opennr_packaged_validation PRIVATE NOMINMAX)
target_compile_options(opennr_packaged_validation PRIVATE /W4 /WX /EHsc /utf-8)
target_link_libraries(opennr_packaged_validation PRIVATE Microsoft::CppWinRT spdlog::spdlog
  d3d11 d3dcompiler)
