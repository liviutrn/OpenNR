set(FFX_API_VK OFF)
set(FFX_API_DX12 OFF)
set(FFX_ALL OFF)
set(FFX_FSR3 ON)
set(FFX_FSR ON)
set(FFX_AUTO_COMPILE_SHADERS 1)

# The source directory is overridable for isolated worktrees that share a
# validated dependency checkout. This keeps the experiment independent from
# the main source worktree without copying a large submodule onto a full disk.
set(OPENNR_FFX_SOURCE_DIR
    "${CMAKE_SOURCE_DIR}/extern/FidelityFX-SDK"
    CACHE PATH
    "FidelityFX-SDK source checkout used by the OpenNR build"
)
if(NOT IS_DIRECTORY "${OPENNR_FFX_SOURCE_DIR}/sdk")
  message(FATAL_ERROR
    "FidelityFX-SDK sdk directory is missing: ${OPENNR_FFX_SOURCE_DIR}/sdk"
  )
endif()

# Note: extern/FidelityFX-SDK/sdk/CMakeLists.txt detects x64 via an exact
# STREQUAL on CMAKE_EXE_LINKER_FLAGS == "/machine:x64" when
# CMAKE_GENERATOR_PLATFORM is unset (Ninja). The ninja preset sets exactly
# that value; appending anything else to the variable breaks the configure.

add_subdirectory(
  "${OPENNR_FFX_SOURCE_DIR}/sdk"
  "${CMAKE_BINARY_DIR}/extern/FidelityFX-SDK/sdk"
)

# Upstream bug: the FFX dx11 backend's compile_shaders() leaks literal
# out-variable names (e.g. "FSR2_PERMUTATION_OUTPUTS") into the dependency
# list of the phony ffx_shader_permutations_dx11 target. The VS generator
# ignores the bogus deps; Ninja fails with "missing and no known rule".
# Pre-creating empty placeholder files at those paths satisfies Ninja without
# triggering rebuilds. If an SDK update adds a new leaked name, add it here.
if(NOT CMAKE_GENERATOR MATCHES "Visual Studio")
  set(_ffx_dx11_bindir
      "${CMAKE_BINARY_DIR}/extern/FidelityFX-SDK/sdk/src/backends/dx11"
  )
  foreach(
    _ffx_bogus_dep
    FSR1_PERMUTATION_OUTPUTS
    FSR2_PERMUTATION_OUTPUTS
    FSR3UPSCALER_PERMUTATION_OUTPUTS
    FRAMEINTERPOLATION_PERMUTATION_OUTPUTS
    OPTICALFLOW_PERMUTATION_OUTPUTS
  )
    if(NOT EXISTS "${_ffx_dx11_bindir}/${_ffx_bogus_dep}")
      file(
        WRITE "${_ffx_dx11_bindir}/${_ffx_bogus_dep}"
        "placeholder for upstream FFX CMake dependency-name leak; see cmake/FidelityFX-SDK.cmake\n"
      )
    endif()
  endforeach()
endif()

# The vendored SDK hardcodes its static libs' output to a single shared
# ${CMAKE_HOME_DIRECTORY}/bin/ffx_sdk directory (see its CMakeLists.txt),
# reused across every preset's separate build tree. That is unsafe for both
# reproducibility and disk-constrained worktrees: a package build can fill the
# source volume before the actual plugin link, and a later preset can reuse an
# archive made with incompatible /GL settings. Keep every MSVC preset's FFX
# archive inside its own build tree instead.
if(MSVC)
  foreach(
    _ffx_target
    ffx_backend_dx11_x64
    ffx_fsr3_x64
    ffx_fsr3upscaler_x64
    ffx_frameinterpolation_x64
    ffx_opticalflow_x64
  )
    if(TARGET ${_ffx_target})
      set_target_properties(
        ${_ffx_target} PROPERTIES
        ARCHIVE_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/ffx_sdk"
        ARCHIVE_OUTPUT_DIRECTORY_DEBUG "${CMAKE_BINARY_DIR}/ffx_sdk"
        ARCHIVE_OUTPUT_DIRECTORY_RELEASE "${CMAKE_BINARY_DIR}/ffx_sdk"
        ARCHIVE_OUTPUT_DIRECTORY_RELWITHDEBINFO "${CMAKE_BINARY_DIR}/ffx_sdk"
      )
    endif()
  endforeach()
endif()

target_link_libraries(
  ${PROJECT_NAME}
  PRIVATE
  ffx_backend_dx11_x64
  ffx_fsr3_x64
)
