#pragma once

// Fault-free memory probes (lifted unchanged from SBMovementNative 1.3.6 /
// SBRetryPointNative 0.1.1 / SBBossRetryNative 0.11.0). None of these can
// raise an exception: region checks use VirtualQuery and reads use
// ReadProcessMemory on the current process.

#include <cstddef>
#include <cstdint>

namespace sbcore::memory
{
    // Committed, not PAGE_GUARD/PAGE_NOACCESS, the whole range inside one
    // region, and executable when require_executable.
    bool is_readable_region(const void* address, std::size_t size, bool require_executable);

    // is_readable_region plus a writable protection.
    bool is_writable_region(const void* address, std::size_t size);

    // ReadProcessMemory(GetCurrentProcess()) of exactly size bytes.
    bool read_exact(const void* address, void* output, std::size_t size);

    // is_readable_region(address, size, true) and memcmp == 0.
    bool code_bytes_equal(const void* address, const std::uint8_t* expected, std::size_t size);

    // 0x10000 <= address <= 0x7FFFFFFFFFFF and the first pointer is readable.
    bool plausible_object(const void* object);
}
