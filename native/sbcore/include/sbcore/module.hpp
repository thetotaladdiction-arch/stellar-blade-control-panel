#pragma once

// The DLL that links sbcore (each native links its own copy of this static
// library, so "this module" is always the native's own DLL).

namespace sbcore::module
{
    // Base address (HMODULE) of the DLL that linked sbcore, or nullptr.
    void* this_module();

    // GetModuleHandleExW(FROM_ADDRESS | PIN): the DLL can never be unloaded,
    // so TaskGraph tasks, hooks and callbacks that point into it stay valid.
    // Idempotent. Returns false (and pinned() stays false) on failure.
    bool pin_this_module();
    bool pinned();
}
