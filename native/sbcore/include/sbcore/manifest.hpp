#pragma once

// Gate manifest types. The field order of Reloc/CodeCheck/SlotCheck is the
// same as SBBossRetryNative's sbsig types, so autorepair/gen_signatures.py
// output converts mechanically.

#include <cstddef>
#include <cstdint>

namespace sbcore::gate
{
    struct Reloc
    {
        std::uint16_t field_offset; // disp32/rel32 position inside the pattern
        std::uint16_t instr_end;    // end of that instruction inside the pattern
        std::uint32_t target_rva;   // RVA the field must resolve to
    };

    enum class Role : std::uint8_t
    {
        Called = 1,    // a function this native calls
        Anchor = 2,    // code that proves a global/offset (read-only)
        Reference = 3, // context bytes, validated but never called
        PatchSite = 4, // code this native rewrites: must lie inside .trace
    };

    // A code check passes only when every unmasked byte matches, every masked
    // byte belongs to exactly one relocation field, every relocation resolves
    // to its recorded target, and (if function_begin) the image's .pdata says
    // a function starts at rva. Masking therefore never weakens validation.
    struct CodeCheck
    {
        const char* name;
        std::uint32_t rva;
        std::uint16_t size; // <= kMaxCheckSize
        const std::uint8_t* bytes;
        const std::uint8_t* mask; // 0xFF = compare, 0x00 = relocation field
        const Reloc* relocs;
        std::uint8_t reloc_count;
        bool function_begin;
        Role role;
    };

    // *(image + vtable_rva + slot_offset) must equal image + target_rva and
    // target_rva must be a .pdata function begin.
    struct SlotCheck
    {
        const char* name;
        std::uint32_t vtable_rva;
        std::uint32_t slot_offset;
        std::uint32_t target_rva;
    };

    // image + rva .. + size must be committed and readable (and writable when
    // requested). Proves nothing about the content; pair it with an Anchor.
    struct GlobalCheck
    {
        const char* name;
        std::uint32_t rva;
        std::uint32_t size;
        bool writable;
    };

    struct Manifest
    {
        const char* name;
        const CodeCheck* code;
        std::size_t code_count;
        const SlotCheck* slots;
        std::size_t slot_count;
        const GlobalCheck* globals;
        std::size_t global_count;
    };

    inline constexpr std::size_t kMaxCheckSize = 512;

    template <std::size_t C, std::size_t S, std::size_t G>
    constexpr Manifest make_manifest(const char* name,
                                     const CodeCheck (&code)[C],
                                     const SlotCheck (&slots)[S],
                                     const GlobalCheck (&globals)[G])
    {
        return Manifest{name, code, C, slots, S, globals, G};
    }
}
