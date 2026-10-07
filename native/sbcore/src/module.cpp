#include "sbcore/module.hpp"

#include <atomic>

#include <windows.h>

namespace sbcore::module
{
    namespace
    {
        std::atomic<bool> g_pinned{false};
    }

    void* this_module()
    {
        HMODULE module = nullptr;
        if (!GetModuleHandleExW(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS | GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,
                                reinterpret_cast<LPCWSTR>(&this_module), &module))
        {
            return nullptr;
        }
        return module;
    }

    bool pin_this_module()
    {
        if (g_pinned.load(std::memory_order_acquire)) return true;
        HMODULE module = nullptr;
        if (!GetModuleHandleExW(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS | GET_MODULE_HANDLE_EX_FLAG_PIN,
                                reinterpret_cast<LPCWSTR>(&pin_this_module), &module))
        {
            return false;
        }
        g_pinned.store(true, std::memory_order_release);
        return true;
    }

    bool pinned()
    {
        return g_pinned.load(std::memory_order_acquire);
    }
}
