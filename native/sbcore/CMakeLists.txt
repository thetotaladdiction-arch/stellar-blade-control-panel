cmake_minimum_required(VERSION 3.25)

# sbcore - the shared core of the Stellar Blade natives (plan A1/A8/A9/A11/A12/P1).
#
# Isolated build. Outputs:
#   <build>/lib/sbcore.lib                          static library natives link
#   stage/sbcore-shim-probe.DO-NOT-INSTALL.dll      A1 in-game diagnostics mod (never installed from here)
#   <build>/tests/*                                 offline tests (ctest)
# Nothing in this project writes into the game folder. The game exe and
# UE4SS.dll are only ever READ by the optional tests (SBCORE_GAME_EXE,
# SBCORE_UE4SS_DLL).

project(sbcore VERSION 0.1.0 LANGUAGES CXX)

if(NOT MSVC OR NOT CMAKE_SIZEOF_VOID_P EQUAL 8)
    message(FATAL_ERROR "sbcore targets MSVC x64 only")
endif()

set(SBCORE_ROOT "${CMAKE_CURRENT_SOURCE_DIR}" CACHE INTERNAL "")
set(SBCORE_STAGE_DIR "${CMAKE_CURRENT_SOURCE_DIR}/stage" CACHE PATH "Staging directory for DO-NOT-INSTALL DLLs")
option(SBCORE_BUILD_TESTS "Build the sbcore offline tests" ${PROJECT_IS_TOP_LEVEL})
option(SBCORE_BUILD_SHIM_PROBE "Build the staged shim diagnostics DLL" ${PROJECT_IS_TOP_LEVEL})
set(SBCORE_GAME_EXE "" CACHE FILEPATH "SB-Win64-Shipping.exe, read-only, for the offline gate test (empty = skipped)")
set(SBCORE_UE4SS_DLL "" CACHE FILEPATH "UE4SS.dll, read-only, for the vtable probe test (empty = skipped)")

find_package(Python3 3.10 REQUIRED COMPONENTS Interpreter)
include("${CMAKE_CURRENT_SOURCE_DIR}/cmake/sbcore_preset.cmake")

# ---- A1: the build fails unless the shim has the runtime's virtual order ----
set(SBCORE_SHIM "${CMAKE_CURRENT_SOURCE_DIR}/shim_include/Mod/CppUserModBase.hpp")
set(SBCORE_RUNTIME_HEADER "${CMAKE_CURRENT_SOURCE_DIR}/third_party/RE-UE4SS/d3d10044d1/CppUserModBase.hpp")
set(SBCORE_RUNTIME_TABLE "${CMAKE_CURRENT_SOURCE_DIR}/ue4ss/runtime_vtable_d3d10044d1.txt")
set(SBCORE_VTABLE_STAMP "${CMAKE_CURRENT_BINARY_DIR}/sbcore_vtable_order.stamp")
add_custom_command(
    OUTPUT "${SBCORE_VTABLE_STAMP}"
    COMMAND "${Python3_EXECUTABLE}" "${CMAKE_CURRENT_SOURCE_DIR}/tools/check_vtable_order.py"
            --shim "${SBCORE_SHIM}"
            --runtime-header "${SBCORE_RUNTIME_HEADER}"
            --runtime-table "${SBCORE_RUNTIME_TABLE}"
            --stamp "${SBCORE_VTABLE_STAMP}"
    DEPENDS "${CMAKE_CURRENT_SOURCE_DIR}/tools/check_vtable_order.py" "${SBCORE_SHIM}"
            "${SBCORE_RUNTIME_HEADER}" "${SBCORE_RUNTIME_TABLE}"
    COMMENT "sbcore: UE4SS shim virtual order vs RE-UE4SS d3d10044d1 and the UE4SS.dll slot table"
    VERBATIM)
add_custom_target(sbcore_vtable_order_check ALL DEPENDS "${SBCORE_VTABLE_STAMP}")

# ---- The library --------------------------------------------------------------
set(SBCORE_SOURCES
    "${SBCORE_ROOT}/src/dispatch.cpp"
    "${SBCORE_ROOT}/src/exe_identity.cpp"
    "${SBCORE_ROOT}/src/fault.cpp"
    "${SBCORE_ROOT}/src/gate.cpp"
    "${SBCORE_ROOT}/src/lease.cpp"
    "${SBCORE_ROOT}/src/memory.cpp"
    "${SBCORE_ROOT}/src/module.cpp"
    "${SBCORE_ROOT}/src/paths.cpp"
    "${SBCORE_ROOT}/src/status.cpp")

function(sbcore_define_library target testing)
    add_library(${target} STATIC ${SBCORE_SOURCES})
    target_include_directories(${target} PUBLIC "${SBCORE_ROOT}/include")
    # Third-party ABI surface: a system include, so /W4 /WX covers our code only.
    target_include_directories(${target} SYSTEM PUBLIC "${SBCORE_ROOT}/shim_include")
    target_compile_features(${target} PUBLIC cxx_std_20)
    target_compile_definitions(${target} PUBLIC ${SBCORE_PRESET_DEFINITIONS})
    target_compile_options(${target} PRIVATE ${SBCORE_PRESET_COMPILE_OPTIONS})
    target_link_libraries(${target} PUBLIC bcrypt)
    set_property(TARGET ${target} PROPERTY MSVC_RUNTIME_LIBRARY "MultiThreadedDLL")
    set_property(TARGET ${target} PROPERTY MSVC_DEBUG_INFORMATION_FORMAT "Embedded")
    set_property(TARGET ${target} PROPERTY STATIC_LIBRARY_OPTIONS /Brepro)
    set_property(TARGET ${target} PROPERTY ARCHIVE_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/lib")
    if(testing)
        target_compile_definitions(${target} PUBLIC SBCORE_TESTING=1)
    endif()
    add_dependencies(${target} sbcore_vtable_order_check)
endfunction()

sbcore_define_library(sbcore OFF)
add_library(sbcore::sbcore ALIAS sbcore)
add_custom_command(TARGET sbcore POST_BUILD
    COMMAND "${Python3_EXECUTABLE}" "${SBCORE_ROOT}/tools/check_no_hardcoded_paths.py" "$<TARGET_FILE:sbcore>"
    COMMENT "sbcore: sbcore.lib must not contain SteamLibrary"
    VERBATIM)

# ---- UE4SS import library (ctor/dtor + the three UObject exports), from a .def --
set(SBCORE_UE4SS_IMPLIB "${CMAKE_BINARY_DIR}/lib/UE4SS.lib")
add_custom_command(
    OUTPUT "${SBCORE_UE4SS_IMPLIB}"
    COMMAND "${CMAKE_AR}" /nologo /Brepro /machine:x64 "/def:${SBCORE_ROOT}/ue4ss/UE4SS.def"
            "/out:${SBCORE_UE4SS_IMPLIB}"
    DEPENDS "${SBCORE_ROOT}/ue4ss/UE4SS.def"
    COMMENT "sbcore: UE4SS import library from ue4ss/UE4SS.def"
    VERBATIM)
add_custom_target(sbcore_ue4ss_implib DEPENDS "${SBCORE_UE4SS_IMPLIB}")
add_library(sbcore_ue4ss INTERFACE)
add_dependencies(sbcore_ue4ss sbcore_ue4ss_implib)
target_link_libraries(sbcore_ue4ss INTERFACE "${SBCORE_UE4SS_IMPLIB}")
add_library(sbcore::ue4ss ALIAS sbcore_ue4ss)

# ---- A1 in-game diagnostics mod (staged, never installed by this project) ----
if(SBCORE_BUILD_SHIM_PROBE)
    add_library(sbcore_shim_probe SHARED probe/shim_probe.cpp)
    sbcore_apply_native_preset(sbcore_shim_probe)
    target_link_libraries(sbcore_shim_probe PRIVATE sbcore sbcore_ue4ss)
    sbcore_stage_native_dll(sbcore_shim_probe "sbcore-shim-probe" "${SBCORE_STAGE_DIR}")
endif()

if(SBCORE_BUILD_TESTS)
    enable_testing()
    add_subdirectory(tests)
endif()
