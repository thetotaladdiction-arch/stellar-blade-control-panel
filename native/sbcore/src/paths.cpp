#include "sbcore/paths.hpp"

#include <array>
#include <cwctype>
#include <memory>

#include <windows.h>

namespace sbcore::paths
{
    namespace
    {
        constexpr DWORD kPathCapacity = 32768;

        bool module_file_name(HMODULE module, std::wstring& out)
        {
            auto buffer = std::make_unique<wchar_t[]>(kPathCapacity);
            SetLastError(ERROR_SUCCESS);
            const DWORD length = GetModuleFileNameW(module, buffer.get(), kPathCapacity);
            if (length == 0 || length >= kPathCapacity || GetLastError() == ERROR_INSUFFICIENT_BUFFER) return false;
            out.assign(buffer.get(), length);
            return true;
        }

        std::wstring join(const std::wstring& directory, std::wstring_view leaf)
        {
            std::wstring result = directory;
            if (!result.empty() && result.back() != L'\\' && result.back() != L'/') result.push_back(L'\\');
            result.append(leaf);
            return result;
        }

        std::wstring_view trim_separators(std::wstring_view path)
        {
            while (!path.empty() && (path.back() == L'\\' || path.back() == L'/')) path.remove_suffix(1);
            return path;
        }
    }

    std::wstring parent_directory(std::wstring_view path)
    {
        path = trim_separators(path);
        const auto slash = path.find_last_of(L"\\/");
        return slash == std::wstring_view::npos ? std::wstring{} : std::wstring(path.substr(0, slash));
    }

    std::wstring_view leaf_name(std::wstring_view path)
    {
        path = trim_separators(path);
        const auto slash = path.find_last_of(L"\\/");
        return slash == std::wstring_view::npos ? path : path.substr(slash + 1);
    }

    bool equals_ignore_case(std::wstring_view a, std::wstring_view b)
    {
        if (a.size() != b.size()) return false;
        for (std::size_t i = 0; i < a.size(); ++i)
        {
            if (std::towlower(a[i]) != std::towlower(b[i])) return false;
        }
        return true;
    }

    std::wstring ModulePaths::in_mod(std::wstring_view leaf) const
    {
        return join(mod_dir, leaf);
    }

    std::wstring ModulePaths::in_panel(std::wstring_view leaf) const
    {
        return join(panel_dir, leaf);
    }

    Error resolve_for_address(const void* address_in_module, ModulePaths& out, bool require_ue4ss_layout)
    {
        out = ModulePaths{};
        HMODULE module = nullptr;
        if (!address_in_module
            || !GetModuleHandleExW(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS | GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,
                                   static_cast<LPCWSTR>(address_in_module), &module))
        {
            return Error::ModuleHandle;
        }
        ModulePaths paths;
        if (!module_file_name(module, paths.dll_path)) return Error::ModuleFileName;
        paths.dll_dir = parent_directory(paths.dll_path);
        paths.mod_dir = parent_directory(paths.dll_dir);
        paths.mods_dir = parent_directory(paths.mod_dir);
        if (paths.dll_dir.empty() || paths.mod_dir.empty() || paths.mods_dir.empty()) return Error::Layout;
        if (require_ue4ss_layout
            && (!equals_ignore_case(leaf_name(paths.dll_dir), L"dlls")
                || !equals_ignore_case(leaf_name(paths.mods_dir), L"Mods")))
        {
            return Error::Layout;
        }
        paths.panel_dir = join(paths.mods_dir, kPanelDirName);
        if (!module_file_name(nullptr, paths.exe_path)) return Error::ExePath;
        out = std::move(paths);
        return Error::None;
    }

    Error resolve_this_module(ModulePaths& out, bool require_ue4ss_layout)
    {
        return resolve_for_address(reinterpret_cast<const void*>(&resolve_this_module), out, require_ue4ss_layout);
    }

    const char* error_name(Error error)
    {
        switch (error)
        {
        case Error::None: return "none";
        case Error::ModuleHandle: return "module_handle";
        case Error::ModuleFileName: return "module_file_name";
        case Error::Layout: return "layout";
        case Error::ExePath: return "exe_path";
        }
        return "unknown";
    }
}
