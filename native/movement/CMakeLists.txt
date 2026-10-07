cmake_minimum_required(VERSION 3.25)

# SBMovementNative 1.4.1 on sbcore (plan A8/A1/A9 stage 1/A11/A12/P1).
#
# Isolated build. Outputs:
#   stage/SBMovementNative-main-v<version>.DO-NOT-INSTALL.dll (+ .pdb)   the native (never installed from here)
#   <build>/tests/*                                                 offline harness (ctest)
# Nothing in this project writes into the game folder or starts the game.
# Build with Build-Movement.ps1 (BelowNormal priority, <= 4 jobs, two clean
# builds that must hash identically).

project(SBMovementNative VERSION 1.4.1 LANGUAGES CXX)

# One version: the heartbeat, ModVersion and fault log use src/movement.hpp,
# the staged file name uses PROJECT_VERSION. They must agree.
file(STRINGS "${CMAKE_CURRENT_SOURCE_DIR}/src/movement.hpp" _sbmove_version_line REGEX "char kVersion")
if(NOT _sbmove_version_line MATCHES "\"${PROJECT_VERSION}\"")
    message(FATAL_ERROR "src/movement.hpp kVersion (${_sbmove_version_line}) != project version ${PROJECT_VERSION}")
endif()

if(NOT MSVC OR NOT CMAKE_SIZEOF_VOID_P EQUAL 8)
    message(FATAL_ERROR "SBMovementNative targets MSVC x64 only")
endif()

set(SBMOVE_SBCORE_DIR "${CMAKE_CURRENT_SOURCE_DIR}/../sbcore" CACHE PATH "sbcore checkout at the commit pinned in SBCORE_PIN.txt")
set(SBMOVE_STAGE_DIR "${CMAKE_CURRENT_SOURCE_DIR}/stage" CACHE PATH "Staging directory for the DO-NOT-INSTALL DLL")
set(SBMOVE_PANEL_QTPANEL "" CACHE PATH "Panel QtPanel folder for the read-only acceptance cross-check (empty = skipped)")
option(SBMOVE_BUILD_TESTS "Build the offline harness" ON)

find_package(Python3 3.10 REQUIRED COMPONENTS Interpreter)

# ---- sbcore at the pinned commit ---------------------------------------------
# Checked at configure time and again on every build (the custom target has no
# output, so it always runs): the build fails unless the sbcore checkout is
# exactly the pinned commit with a clean tree.
set(SBMOVE_PIN_CHECK "${CMAKE_CURRENT_SOURCE_DIR}/tools/check_sbcore_pin.py")
execute_process(
    COMMAND "${Python3_EXECUTABLE}" "${SBMOVE_PIN_CHECK}" "${CMAKE_CURRENT_SOURCE_DIR}/SBCORE_PIN.txt" "${SBMOVE_SBCORE_DIR}"
    RESULT_VARIABLE _pin_result)
if(NOT _pin_result EQUAL 0)
    message(FATAL_ERROR "sbcore is not at the pinned commit (see SBCORE_PIN.txt)")
endif()
add_custom_target(sbmove_sbcore_pin_check ALL
    COMMAND "${Python3_EXECUTABLE}" "${SBMOVE_PIN_CHECK}" "${CMAKE_CURRENT_SOURCE_DIR}/SBCORE_PIN.txt" "${SBMOVE_SBCORE_DIR}"
    COMMENT "SBMovementNative: sbcore must be at the pinned commit with a clean tree"
    VERBATIM)

# sbcore's own build step fails unless its UE4SS shim has the runtime's
# virtual order (A1); its tests and shim probe stay off as a subdirectory.
add_subdirectory("${SBMOVE_SBCORE_DIR}" sbcore EXCLUDE_FROM_ALL)
add_dependencies(sbcore sbmove_sbcore_pin_check)
# The preset's option lists (SBCORE_PRESET_*) are ordinary variables of the
# sbcore directory scope; sbcore_apply_native_preset() reads them from the
# CALLER's scope. Without this include they are empty here and the native
# silently builds without /W4 /WX /sdl /guard:cf /Brepro and the hardened
# link flags. Include the pinned preset file so they exist in this scope too.
include("${SBMOVE_SBCORE_DIR}/cmake/sbcore_preset.cmake")
if(NOT SBCORE_PRESET_COMPILE_OPTIONS MATCHES "/guard:cf" OR NOT SBCORE_PRESET_LINK_OPTIONS MATCHES "/Brepro")
    message(FATAL_ERROR "sbcore native preset options are not visible in this scope")
endif()

set(SBMOVE_SOURCES
    "${CMAKE_CURRENT_SOURCE_DIR}/src/dllmain.cpp"
    "${CMAKE_CURRENT_SOURCE_DIR}/src/movement.cpp")

# ---- the native ---------------------------------------------------------------
add_library(SBMovementNative SHARED ${SBMOVE_SOURCES})
sbcore_apply_native_preset(SBMovementNative)
target_include_directories(SBMovementNative PRIVATE "${CMAKE_CURRENT_SOURCE_DIR}/src")
target_link_libraries(SBMovementNative PRIVATE sbcore::sbcore sbcore::ue4ss)
sbcore_stage_native_dll(SBMovementNative "SBMovementNative-main-v${PROJECT_VERSION}" "${SBMOVE_STAGE_DIR}")
add_custom_command(TARGET SBMovementNative POST_BUILD
    COMMAND "${Python3_EXECUTABLE}" "${CMAKE_CURRENT_SOURCE_DIR}/tools/check_pe.py" --kind production
            --def "${SBCORE_ROOT}/ue4ss/UE4SS.def" "$<TARGET_FILE:SBMovementNative>"
    COMMENT "SBMovementNative: PE checks (preset flags, /MD, UE4SS imports, exports)"
    VERBATIM)

if(SBMOVE_BUILD_TESTS)
    enable_testing()
    add_subdirectory(tests)
endif()
