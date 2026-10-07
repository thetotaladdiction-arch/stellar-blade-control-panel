#pragma once

// The exact-build gate (A8 "gate", A11). One validator for every native:
//
//   1. PE identity: AMD64, TimeDateStamp 0x6A6A3B74, SizeOfImage 0x15981000,
//      header ImageBase 0x140000000;
//   2. the exe file on disk is 359,186,432 bytes;
//   3. the sbcore TaskGraph core manifest (CreateTask, Setup, ExecuteTask,
//      the task destructor, the task vtable slots and the GGameThreadId
//      initializer store that proves the GameThread id global), plus the exact
//      64/42/36/12-byte images SBMovementNative/SBRetryPointNative pinned, so
//      the core is never weaker than any gate it replaces;
//   4. every extra manifest the native passes, in order.
//
// Reads only. Stops at the first failure and names it. Nothing may be
// written, called or hooked in the game before validate() passes.

#include <cstddef>
#include <cstdint>

#include "sbcore/manifest.hpp"

namespace sbcore::gate
{
    enum class Reason : std::uint8_t
    {
        None = 0,
        ImageAbsent,     // no image / unreadable DOS header
        DosHeader,       // bad MZ or e_lfanew
        PeIdentity,      // machine, TimeDateStamp or SizeOfImage
        ImageBase,       // header ImageBase is not 0x140000000
        ExeFileSize,     // on-disk size differs or file unreadable
        ManifestInvalid, // malformed check (mask/reloc/size) - a sbcore/native bug
        Unreadable,      // code/slot/global range not committed/readable/executable
        Bytes,           // an unmasked byte differs
        Relocation,      // a disp32/rel32 resolves to a different target
        FunctionBegin,   // .pdata does not start a function at the rva
        Slot,            // vtable slot points elsewhere
        Section,         // a PatchSite outside .trace
        Writable,        // global required writable is not
    };

    struct Result
    {
        bool passed = false;
        Reason reason = Reason::None;
        char failed_check[64] = {}; // "" when passed; else the check name (legacy names kept)
        char failed_manifest[32] = {};
        std::byte* image = nullptr;
        std::uint32_t timestamp = 0;
        std::uint32_t image_size = 0;
        std::uint64_t exe_file_size = 0;
        std::uint32_t code_checks_passed = 0;
        std::uint32_t slot_checks_passed = 0;
        std::uint32_t global_checks_passed = 0;
        std::uint32_t manifests_passed = 0;
    };

    // The sbcore core manifest (TaskGraph + GameThread) and the legacy exact
    // images. Always validated first; exposed for tests and for autorepair.
    const Manifest& core_manifest();
    const Manifest& legacy_exact_manifest();

    // image: the mapped exe (the running process: GetModuleHandleW(nullptr)).
    // exe_path: the file whose size is checked; nullptr = the running exe.
    Result validate(std::byte* image, const wchar_t* exe_path, const Manifest* const* extra, std::size_t extra_count);

    // validate(GetModuleHandleW(nullptr), nullptr, extra, extra_count).
    Result validate_running_process(const Manifest* const* extra, std::size_t extra_count);

    // Single-check validators (exposed for native self-tests).
    Reason validate_code_check(const std::byte* image, const CodeCheck& check);
    Reason validate_slot_check(const std::byte* image, const SlotCheck& check);
    Reason validate_global_check(const std::byte* image, const GlobalCheck& check);

    // True if [rva, rva+size) lies inside the named section of the image.
    bool rva_in_section(const std::byte* image, std::uint32_t rva, std::uint32_t size, const char* section_name);

    const char* reason_name(Reason reason);
}
