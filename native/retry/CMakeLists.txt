cmake_minimum_required(VERSION 3.25)

# SBRetryPointNative 0.2.3 on sbcore (plan A1/A8/A9 stage 1/A11/A12/P1).
#
# Isolated build. Outputs:
#   stage/main-v0.2.3.DO-NOT-INSTALL.dll (+ .pdb)   the native (never installed from here)
#   <build>/tests/*                                   offline harness and verifiers (ctest)
# Nothing in this project writes into the game folder. The game exe, UE4SS.dll
# and a live point file are only ever READ by the optional tests.

project(SBRetryPointNative VERSION 0.2.3 LANGUAGES CXX)

if(NOT MSVC OR NOT CMAKE_SIZEOF_VOID_P EQUAL 8)
    message(FATAL_ERROR "SBRetryPointNative targets MSVC x64 only")
endif()

set(SBRP_ROOT "${CMAKE_CURRENT_SOURCE_DIR}")
set(SBRP_STAGE_DIR "${SBRP_ROOT}/stage" CACHE PATH "Staging directory for the DO-NOT-INSTALL DLL")
option(SBRP_BUILD_TESTS "Build the offline harness and verifiers" ON)
set(SBRP_GAME_EXE "" CACHE FILEPATH "SB-Win64-Shipping.exe, read-only, for the legacy-gate parity test (empty = skipped)")
set(SBRP_UE4SS_DLL "" CACHE FILEPATH "UE4SS.dll, read-only, to check every import against its exports (empty = skipped)")
set(SBRP_PANEL_DIR "" CACHE PATH "Panel QtPanel folder, read-only, for the panel-contract verdicts (empty = skipped)")
set(SBRP_LIVE_POINT_FILE "" CACHE FILEPATH "A retry_point.txt written by v0.1.1, read-only, for the compatibility case (empty = skipped)")

# ---- sbcore at its pinned commit (git submodule extern/sbcore) ---------------
set(SBRP_SBCORE_DIR "${SBRP_ROOT}/extern/sbcore")
set(SBRP_SBCORE_COMMIT "7a81ea67361ae989b08339056a2ce3b74018cb39")
set(SBRP_LEGACY_COMMIT "00cab4cd65f344bea51dda61674bdc9e4e22d250" CACHE STRING "The verbatim v0.1.1 import commit (legacy status contract)")
find_package(Git REQUIRED)
execute_process(COMMAND "${GIT_EXECUTABLE}" -C "${SBRP_SBCORE_DIR}" rev-parse HEAD
                OUTPUT_VARIABLE _sbcore_head OUTPUT_STRIP_TRAILING_WHITESPACE RESULT_VARIABLE _sbcore_rc)
if(NOT _sbcore_rc EQUAL 0 OR NOT _sbcore_head STREQUAL SBRP_SBCORE_COMMIT)
    message(FATAL_ERROR "extern/sbcore must be at the pinned commit ${SBRP_SBCORE_COMMIT} (found '${_sbcore_head}'). "
                        "Run: git -c protocol.file.allow=always submodule update --init")
endif()
execute_process(COMMAND "${GIT_EXECUTABLE}" -C "${SBRP_SBCORE_DIR}" status --porcelain
                OUTPUT_VARIABLE _sbcore_dirty OUTPUT_STRIP_TRAILING_WHITESPACE)
if(NOT _sbcore_dirty STREQUAL "")
    message(FATAL_ERROR "extern/sbcore has local changes; the pinned sbcore must be byte-exact:\n${_sbcore_dirty}")
endif()
add_subdirectory("${SBRP_SBCORE_DIR}" sbcore EXCLUDE_FROM_ALL)
# sbcore_apply_native_preset() reads SBCORE_PRESET_* from the CALLER's scope,
# and sbcore sets them only inside its own directory scope. Include the pinned
# preset here as well, or targets defined in this project would silently build
# without /W4 /WX /sdl /guard:cf /Brepro and the reproducible link options.
include("${SBRP_SBCORE_DIR}/cmake/sbcore_preset.cmake")
if(NOT SBCORE_PRESET_COMPILE_OPTIONS OR NOT SBCORE_PRESET_LINK_OPTIONS)
    message(FATAL_ERROR "sbcore preset options are empty")
endif()

# ---- UE4SS import library for exactly the 7 symbols this native uses --------
set(SBRP_UE4SS_IMPLIB "${CMAKE_BINARY_DIR}/lib/sbretrypoint_ue4ss.lib")
add_custom_command(
    OUTPUT "${SBRP_UE4SS_IMPLIB}"
    COMMAND "${CMAKE_AR}" /nologo /Brepro /machine:x64 "/def:${SBRP_ROOT}/ue4ss/UE4SS.def" "/out:${SBRP_UE4SS_IMPLIB}"
    DEPENDS "${SBRP_ROOT}/ue4ss/UE4SS.def"
    COMMENT "SBRetryPointNative: UE4SS import library from ue4ss/UE4SS.def"
    VERBATIM)
add_custom_target(sbrp_ue4ss_implib DEPENDS "${SBRP_UE4SS_IMPLIB}")

# ---- The native ----------------------------------------------------------------
add_library(SBRetryPointNative SHARED dllmain.cpp retry_point.cpp)
sbcore_apply_native_preset(SBRetryPointNative)
target_include_directories(SBRetryPointNative PRIVATE "${SBRP_ROOT}")
target_link_libraries(SBRetryPointNative PRIVATE sbcore::sbcore "${SBRP_UE4SS_IMPLIB}")
add_dependencies(SBRetryPointNative sbrp_ue4ss_implib)
sbcore_stage_native_dll(SBRetryPointNative "main-v${PROJECT_VERSION}" "${SBRP_STAGE_DIR}")

if(SBRP_BUILD_TESTS)
    enable_testing()
    add_subdirectory(tests)
endif()
