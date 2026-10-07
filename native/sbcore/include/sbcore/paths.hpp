#pragma once

// Module-relative path resolution (P1). Every path a native uses is derived
// from the location of its own DLL, never from a hardcoded install path:
//
//   dll_path   ...\ue4ss\Mods\<ModName>\dlls\main.dll
//   dll_dir    ...\ue4ss\Mods\<ModName>\dlls
//   mod_dir    ...\ue4ss\Mods\<ModName>
//   mods_dir   ...\ue4ss\Mods
//   panel_dir  ...\ue4ss\Mods\SBCheatGUI
//   exe_path   the running process image (SB-Win64-Shipping.exe in the game)

#include <string>
#include <string_view>

namespace sbcore::paths
{
    enum class Error : unsigned
    {
        None = 0,
        ModuleHandle,   // GetModuleHandleExW(FROM_ADDRESS) failed
        ModuleFileName, // GetModuleFileNameW failed or truncated
        Layout,         // not <Mods>\<ModName>\dlls\<file>.dll (require_ue4ss_layout)
        ExePath,        // GetModuleFileNameW(nullptr) failed or truncated
    };

    struct ModulePaths
    {
        std::wstring dll_path;
        std::wstring dll_dir;
        std::wstring mod_dir;
        std::wstring mods_dir;
        std::wstring panel_dir;
        std::wstring exe_path;

        std::wstring in_mod(std::wstring_view leaf) const;   // mod_dir \ leaf
        std::wstring in_panel(std::wstring_view leaf) const; // panel_dir \ leaf
    };

    inline constexpr wchar_t kPanelDirName[] = L"SBCheatGUI";

    // Resolves the paths of the module that contains address_in_module.
    // With require_ue4ss_layout, the DLL's folder must be named "dlls" and its
    // grandparent "Mods" (case-insensitive), as UE4SS loads C++ mods.
    Error resolve_for_address(const void* address_in_module, ModulePaths& out, bool require_ue4ss_layout = true);

    // resolve_for_address(address inside the DLL that linked sbcore).
    Error resolve_this_module(ModulePaths& out, bool require_ue4ss_layout = true);

    const char* error_name(Error error);

    // Helpers (exposed for tests): trailing separators are ignored.
    std::wstring parent_directory(std::wstring_view path);
    std::wstring_view leaf_name(std::wstring_view path);
    bool equals_ignore_case(std::wstring_view a, std::wstring_view b);
}
