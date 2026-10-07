#include "sbcore/memory.hpp"

#include <cstring>

#include <windows.h>

namespace sbcore::memory
{
    bool is_readable_region(const void* address, std::size_t size, bool require_executable)
    {
        if (!address || size == 0) return false;
        MEMORY_BASIC_INFORMATION info{};
        if (VirtualQuery(address, &info, sizeof(info)) != sizeof(info)
            || info.State != MEM_COMMIT
            || (info.Protect & (PAGE_GUARD | PAGE_NOACCESS)) != 0)
        {
            return false;
        }
        const auto start = reinterpret_cast<std::uintptr_t>(address);
        const auto end = reinterpret_cast<std::uintptr_t>(info.BaseAddress) + info.RegionSize;
        if (start > end || size > end - start) return false;
        const DWORD executable =
            PAGE_EXECUTE | PAGE_EXECUTE_READ | PAGE_EXECUTE_READWRITE | PAGE_EXECUTE_WRITECOPY;
        return !require_executable || (info.Protect & executable) != 0;
    }

    bool is_writable_region(const void* address, std::size_t size)
    {
        if (!is_readable_region(address, size, false)) return false;
        MEMORY_BASIC_INFORMATION info{};
        if (VirtualQuery(address, &info, sizeof(info)) != sizeof(info)) return false;
        const DWORD writable = PAGE_READWRITE | PAGE_WRITECOPY | PAGE_EXECUTE_READWRITE | PAGE_EXECUTE_WRITECOPY;
        return (info.Protect & writable) != 0;
    }

    bool read_exact(const void* address, void* output, std::size_t size)
    {
        SIZE_T read = 0;
        return address && output && size > 0
            && ReadProcessMemory(GetCurrentProcess(), address, output, size, &read)
            && read == size;
    }

    bool code_bytes_equal(const void* address, const std::uint8_t* expected, std::size_t size)
    {
        return expected && is_readable_region(address, size, true) && std::memcmp(address, expected, size) == 0;
    }

    bool plausible_object(const void* object)
    {
        const auto address = reinterpret_cast<std::uintptr_t>(object);
        return address >= 0x10000 && address <= 0x7FFFFFFFFFFFULL
            && is_readable_region(object, sizeof(void*), false);
    }
}
