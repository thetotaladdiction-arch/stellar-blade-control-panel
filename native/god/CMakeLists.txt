cmake_minimum_required(VERSION 3.25)

# SBGodNative v1.3.2 - isolated build on sbcore (plan A1/A8/A9/A11/A12/P1).
#
# The DLL is staged ONLY into ${CMAKE_CURRENT_SOURCE_DIR}/../stage as
# main-v1.3.2.DO-NOT-INSTALL.dll (+ .pdb). Earlier artifacts in stage\ are
# left untouched. Nothing in this project writes into the game's folder; the
# exe is only READ by the offline harnesses (argument, never a default path).
#
# sbcore is linked from SBCORE_DIR at the commit pinned in ../SBCORE_PIN.txt
# (Build-SbGod.ps1 refuses any other commit or a dirty sbcore tree). Its build
# step fails if the UE4SS shim's virtual order differs from the loaded
# UE4SS.dll (A1), and its stage helper fails if the DLL contains
# "SteamLibrary" (P1).

set(TARGET SBGodNative)
project(${TARGET} LANGUAGES CXX)

set(SBGOD_VERSION "1.3.5")
set(SBGOD_STAGE_DIR "${CMAKE_CURRENT_SOURCE_DIR}/../stage")
set(SBGOD_TOOLS_DIR "${CMAKE_CURRENT_SOURCE_DIR}/../tools")
set(SBGOD_HARNESS_DIR "${CMAKE_BINARY_DIR}/harness")
set(SBCORE_DIR "${CMAKE_CURRENT_SOURCE_DIR}/../../sbcore" CACHE PATH "sbcore checkout at the pinned commit")

find_package(Python3 3.10 REQUIRED COMPONENTS Interpreter)
add_subdirectory("${SBCORE_DIR}" sbcore EXCLUDE_FROM_ALL)
# The preset variables live in the including scope (sbcore_preset.cmake).
include("${SBCORE_DIR}/cmake/sbcore_preset.cmake")

# Everything God runs in the game except the UE4SS entry class.
set(SBGOD_CORE_SOURCES
    "${CMAKE_CURRENT_SOURCE_DIR}/god_hook.cpp"
    "${CMAKE_CURRENT_SOURCE_DIR}/god_identity.cpp"
    "${CMAKE_CURRENT_SOURCE_DIR}/god_sites.cpp"
    "${CMAKE_CURRENT_SOURCE_DIR}/god_gate.cpp"
    "${CMAKE_CURRENT_SOURCE_DIR}/god_state.cpp")

# ---- The native -----------------------------------------------------------------
add_library(${TARGET} SHARED dllmain.cpp ${SBGOD_CORE_SOURCES})
sbcore_apply_native_preset(${TARGET})
target_include_directories(${TARGET} PRIVATE "${CMAKE_CURRENT_SOURCE_DIR}")
# sbcore::sbcore brings sbcore's include dir and its UE4SS shim (SYSTEM);
# sbcore::ue4ss is the import library generated from sbcore/ue4ss/UE4SS.def.
target_link_libraries(${TARGET} PRIVATE sbcore::sbcore sbcore::ue4ss)
sbcore_stage_native_dll(${TARGET} "main-v${SBGOD_VERSION}" "${SBGOD_STAGE_DIR}")

# ---- Offline tools (never touch the game, the game folder or Mods) ---------------
function(sbgod_tool target)
    target_include_directories(${target} PRIVATE "${CMAKE_CURRENT_SOURCE_DIR}" "${SBGOD_TOOLS_DIR}")
    target_compile_features(${target} PRIVATE cxx_std_20)
    target_compile_definitions(${target} PRIVATE NOMINMAX WIN32_LEAN_AND_MEAN UNICODE _UNICODE)
    target_compile_options(${target} PRIVATE /EHsc /permissive- /utf-8 /W4 /WX /Brepro)
    target_link_options(${target} PRIVATE /Brepro)
    set_property(TARGET ${target} PROPERTY MSVC_RUNTIME_LIBRARY "MultiThreadedDLL")
    set_target_properties(${target} PROPERTIES
        RUNTIME_OUTPUT_DIRECTORY "${SBGOD_HARNESS_DIR}"
        RUNTIME_OUTPUT_DIRECTORY_RELEASE "${SBGOD_HARNESS_DIR}")
endfunction()

# 1. Offline harness: God's validator/patcher (god_sites.cpp) and the v1.2.0
#    install gate (god_gate.cpp = sbcore gate + God manifest) against the exe
#    file mapped at 0x140000000 with its .pdata registered.
add_executable(sbgod_offline_harness "${SBGOD_TOOLS_DIR}/offline_harness.cpp"
    "${CMAKE_CURRENT_SOURCE_DIR}/god_sites.cpp" "${CMAKE_CURRENT_SOURCE_DIR}/god_gate.cpp")
sbgod_tool(sbgod_offline_harness)
target_link_libraries(sbgod_offline_harness PRIVATE sbcore::sbcore)
target_link_options(sbgod_offline_harness PRIVATE /DYNAMICBASE /HIGHENTROPYVA /BASE:0x7FF710000000)

# 2. Identity test: god_identity.cpp against synthetic game memory.
add_executable(sbgod_identity_test "${SBGOD_TOOLS_DIR}/identity_test.cpp"
    "${CMAKE_CURRENT_SOURCE_DIR}/god_identity.cpp" "${CMAKE_CURRENT_SOURCE_DIR}/god_sites.cpp")
sbgod_tool(sbgod_identity_test)

# 3. Lookup differential test: the game's own lookup machine code (exe mapped
#    into this test process only) against the read-only mirror.
add_executable(sbgod_lookup_difftest "${SBGOD_TOOLS_DIR}/lookup_difftest.cpp"
    "${CMAKE_CURRENT_SOURCE_DIR}/god_identity.cpp" "${CMAKE_CURRENT_SOURCE_DIR}/god_sites.cpp")
sbgod_tool(sbgod_lookup_difftest)
target_link_options(sbgod_lookup_difftest PRIVATE /DYNAMICBASE /HIGHENTROPYVA /BASE:0x7FF710000000)

# 4. State-file parser: god_state.cpp vs the verbatim v1.1.2 fgets loop.
add_executable(sbgod_state_parse_test "${SBGOD_TOOLS_DIR}/state_parse_test.cpp"
    "${CMAKE_CURRENT_SOURCE_DIR}/god_state.cpp")
sbgod_tool(sbgod_state_parse_test)

# 5. Worker test: the production god_hook.cpp & co. with the native preset in a
#    test DLL (local UE4SS stubs), loaded by the test exe from a fake
#    <root>\ue4ss\Mods\SBGodNative\dlls\main.dll tree under build\testroot, so
#    P1 path resolution, the fail-closed install, the heartbeat and the A12
#    file exchange run exactly as in the game - outside the certified exe.
add_library(sbgod_worker_module SHARED "${SBGOD_TOOLS_DIR}/worker_module.cpp" ${SBGOD_CORE_SOURCES})
sbcore_apply_native_preset(sbgod_worker_module)
target_include_directories(sbgod_worker_module PRIVATE "${CMAKE_CURRENT_SOURCE_DIR}")
# SBGOD_WORKER_TEST_EXPORTS adds sbgod::testing::probe_read_u32 (the production
# leaf probe on a test-chosen address); the staged DLL never defines it.
target_compile_definitions(sbgod_worker_module PRIVATE "SBGOD_UE4SS_IMPORT=" SBGOD_WORKER_TEST_EXPORTS)
target_link_libraries(sbgod_worker_module PRIVATE sbcore::sbcore)
set_target_properties(sbgod_worker_module PROPERTIES
    RUNTIME_OUTPUT_DIRECTORY "${SBGOD_HARNESS_DIR}"
    RUNTIME_OUTPUT_DIRECTORY_RELEASE "${SBGOD_HARNESS_DIR}"
    PDB_OUTPUT_DIRECTORY "${SBGOD_HARNESS_DIR}"
    ARCHIVE_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/lib")

add_executable(sbgod_worker_test "${SBGOD_TOOLS_DIR}/worker_test.cpp")
sbgod_tool(sbgod_worker_test)
target_link_libraries(sbgod_worker_test PRIVATE sbcore::sbcore)
add_dependencies(sbgod_worker_test sbgod_worker_module)

# Staged offline predicate contracts; no install/game/process actions.
add_executable(sbgod_death_probe_predicates "${SBGOD_TOOLS_DIR}/death_command.regression.cpp"
    "${CMAKE_CURRENT_SOURCE_DIR}/god_identity.cpp" "${CMAKE_CURRENT_SOURCE_DIR}/god_sites.cpp"
    "${CMAKE_CURRENT_SOURCE_DIR}/god_gate.cpp" "${CMAKE_CURRENT_SOURCE_DIR}/god_state.cpp")
sbgod_tool(sbgod_death_probe_predicates)
target_compile_definitions(sbgod_death_probe_predicates PRIVATE "SBGOD_UE4SS_IMPORT=" SBGOD_WORKER_TEST_EXPORTS)
target_link_libraries(sbgod_death_probe_predicates PRIVATE sbcore::sbcore)


# Full production heartbeat emission, with only offline cached-scalar fixtures.
foreach(hb_target sbgod_heartbeat_regression sbgod_heartbeat_baseline)
    add_executable(${hb_target} "${SBGOD_TOOLS_DIR}/heartbeat.regression.cpp"
        "${CMAKE_CURRENT_SOURCE_DIR}/god_identity.cpp" "${CMAKE_CURRENT_SOURCE_DIR}/god_sites.cpp"
        "${CMAKE_CURRENT_SOURCE_DIR}/god_gate.cpp" "${CMAKE_CURRENT_SOURCE_DIR}/god_state.cpp")
    sbgod_tool(${hb_target})
    target_compile_definitions(${hb_target} PRIVATE "SBGOD_UE4SS_IMPORT=" SBGOD_WORKER_TEST_EXPORTS)
    target_link_libraries(${hb_target} PRIVATE sbcore::sbcore)
endforeach()
target_compile_definitions(sbgod_heartbeat_baseline PRIVATE SBGOD_HEARTBEAT_BASELINE)

# Actual production death hooks against synthetic actor memory (implementation r2).
add_executable(sbgod_death_transition "${SBGOD_TOOLS_DIR}/death_transition.regression.cpp"
    "${CMAKE_CURRENT_SOURCE_DIR}/god_identity.cpp" "${CMAKE_CURRENT_SOURCE_DIR}/god_sites.cpp"
    "${CMAKE_CURRENT_SOURCE_DIR}/god_gate.cpp" "${CMAKE_CURRENT_SOURCE_DIR}/god_state.cpp")
sbgod_tool(sbgod_death_transition)
target_compile_definitions(sbgod_death_transition PRIVATE "SBGOD_UE4SS_IMPORT=" SBGOD_WORKER_TEST_EXPORTS)
target_link_libraries(sbgod_death_transition PRIVATE sbcore::sbcore)

# Actual production energy hooks against synthetic actor memory; never gameplay.
add_executable(sbgod_beta_burst "${SBGOD_TOOLS_DIR}/beta_burst.regression.cpp"
    "${CMAKE_CURRENT_SOURCE_DIR}/god_identity.cpp" "${CMAKE_CURRENT_SOURCE_DIR}/god_sites.cpp"
    "${CMAKE_CURRENT_SOURCE_DIR}/god_gate.cpp" "${CMAKE_CURRENT_SOURCE_DIR}/god_state.cpp")
sbgod_tool(sbgod_beta_burst)
target_compile_definitions(sbgod_beta_burst PRIVATE "SBGOD_UE4SS_IMPORT=" SBGOD_WORKER_TEST_EXPORTS)
target_link_libraries(sbgod_beta_burst PRIVATE sbcore::sbcore)
