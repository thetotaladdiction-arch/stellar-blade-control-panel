cmake_minimum_required(VERSION 3.25)

# SBLiveAddNative v0.5.1 on sbcore (plan A8; items v0.5 C1-C9, v0.5.1 guards). Builds the DLL only; nothing
# here writes outside the build tree and SBLIVEADD_STAGE_DIR, and the staged
# file always carries a DO-NOT-INSTALL name. Build-LiveAddNative.ps1 is the
# supported entry point (two clean reproducible builds, BelowNormal, -j <= 4).

set(TARGET SBLiveAddNative)
project(${TARGET} VERSION 0.5.1 LANGUAGES CXX)

# sbcore at its pinned commit (Build-LiveAddNative.ps1 checks the commit and a
# clean tree before configuring). Default: the sibling checkout
# shared sbcore checkout, found relative to this file.
set(SBCORE_DIR "${CMAKE_CURRENT_SOURCE_DIR}/../../../sbcore" CACHE PATH "sbcore checkout (pinned commit)")
get_filename_component(SBCORE_DIR "${SBCORE_DIR}" ABSOLUTE)
if(NOT EXISTS "${SBCORE_DIR}/CMakeLists.txt")
    message(FATAL_ERROR "sbcore not found at ${SBCORE_DIR}")
endif()
set(SBLIVEADD_STAGE_DIR "${CMAKE_BINARY_DIR}/stage" CACHE PATH "Where the DO-NOT-INSTALL DLL is written")

# sbcore's tests and shim probe default to OFF as a subdirectory. Its A1
# check (shim virtual order vs RE-UE4SS d3d10044d1 and the UE4SS.dll slot
# table) runs before sbcore.lib builds, so this DLL cannot link a wrong shim.
add_subdirectory("${SBCORE_DIR}" sbcore EXCLUDE_FROM_ALL)
# The preset's option lists (SBCORE_PRESET_*) are ordinary variables of
# sbcore's own directory scope; sbcore_apply_native_preset() called from here
# would read them as empty and build an unhardened, non-reproducible DLL.
# Including the preset file sets them in this scope too (same file, same
# commit). Build-LiveAddNative.ps1 and the binary verifier check the flags.
include("${SBCORE_DIR}/cmake/sbcore_preset.cmake")
if(NOT SBCORE_PRESET_COMPILE_OPTIONS OR NOT SBCORE_PRESET_LINK_OPTIONS OR NOT SBCORE_PRESET_DEFINITIONS)
    message(FATAL_ERROR "sbcore preset option lists are empty")
endif()

add_library(${TARGET} SHARED
    dllmain.cpp
    live_add.cpp
)
target_include_directories(${TARGET} PRIVATE "${CMAKE_CURRENT_SOURCE_DIR}")
# /MD /W4 /WX /permissive- /sdl /GS /guard:cf /ZH:SHA_256 /Brepro /utf-8 /EHsc,
# embedded debug info, /guard:cf /DYNAMICBASE /HIGHENTROPYVA /NXCOMPAT
# /INCREMENTAL:NO /DEBUG:FULL /OPT:REF /OPT:ICF /WX /Brepro.
sbcore_apply_native_preset(${TARGET})
# sbcore::ue4ss: UE4SS.lib generated from sbcore's UE4SS.def (this module
# imports only the CppUserModBase constructor and destructor).
target_link_libraries(${TARGET} PRIVATE sbcore::sbcore sbcore::ue4ss bcrypt)
# <stage>/SBLiveAddNative-v0.5.1-main.DO-NOT-INSTALL.dll (+ .pdb), and a
# post-build check that the DLL contains no hardcoded install path (plan P1).
sbcore_stage_native_dll(${TARGET} "SBLiveAddNative-v0.5.1-main" "${SBLIVEADD_STAGE_DIR}")
