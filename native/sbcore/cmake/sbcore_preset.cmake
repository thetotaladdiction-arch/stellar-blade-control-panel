# sbcore native build preset (plan A8). Include after add_subdirectory(sbcore)
# or from sbcore's own CMakeLists.
#
#   sbcore_apply_native_preset(<target>)
#       /MD /W4 /WX /permissive- /sdl /GS /guard:cf /ZH:SHA_256 /Brepro /Z7 + reproducible link
#   sbcore_stage_native_dll(<target> <OUTPUT_NAME> <STAGE_DIR>)
#       output <STAGE_DIR>/<OUTPUT_NAME>.DO-NOT-INSTALL.dll (+ .pdb), and a post-build
#       check that fails if the DLL contains "SteamLibrary" (plan P1).
#
# Nothing here writes outside the build tree and the given stage directory.

set(SBCORE_PRESET_COMPILE_OPTIONS
    /W4 /WX /permissive- /sdl /GS /guard:cf /ZH:SHA_256 /Brepro /utf-8 /EHsc /Zc:__cplusplus)
set(SBCORE_PRESET_LINK_OPTIONS
    /guard:cf /DYNAMICBASE /HIGHENTROPYVA /NXCOMPAT /INCREMENTAL:NO /DEBUG:FULL /OPT:REF /OPT:ICF /WX /Brepro)
set(SBCORE_PRESET_DEFINITIONS NOMINMAX WIN32_LEAN_AND_MEAN UNICODE _UNICODE)

function(sbcore_apply_native_preset target)
    target_compile_features(${target} PRIVATE cxx_std_20)
    target_compile_definitions(${target} PRIVATE ${SBCORE_PRESET_DEFINITIONS})
    target_compile_options(${target} PRIVATE ${SBCORE_PRESET_COMPILE_OPTIONS})
    get_target_property(_type ${target} TYPE)
    if(_type STREQUAL "SHARED_LIBRARY" OR _type STREQUAL "EXECUTABLE" OR _type STREQUAL "MODULE_LIBRARY")
        target_link_options(${target} PRIVATE ${SBCORE_PRESET_LINK_OPTIONS})
    endif()
    set_property(TARGET ${target} PROPERTY MSVC_RUNTIME_LIBRARY "MultiThreadedDLL")
    set_property(TARGET ${target} PROPERTY MSVC_DEBUG_INFORMATION_FORMAT "Embedded")
endfunction()

function(sbcore_stage_native_dll target output_name stage_dir)
    if(NOT output_name MATCHES "\\.DO-NOT-INSTALL$")
        set(output_name "${output_name}.DO-NOT-INSTALL")
    endif()
    set_target_properties(${target} PROPERTIES
        OUTPUT_NAME "${output_name}"
        RUNTIME_OUTPUT_DIRECTORY "${stage_dir}"
        RUNTIME_OUTPUT_DIRECTORY_RELEASE "${stage_dir}"
        PDB_OUTPUT_DIRECTORY "${stage_dir}"
        ARCHIVE_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/lib")
    add_custom_command(TARGET ${target} POST_BUILD
        COMMAND "${Python3_EXECUTABLE}" "${SBCORE_ROOT}/tools/check_no_hardcoded_paths.py" "$<TARGET_FILE:${target}>"
        COMMENT "sbcore: ${output_name}.dll must not contain SteamLibrary"
        VERBATIM)
endfunction()
