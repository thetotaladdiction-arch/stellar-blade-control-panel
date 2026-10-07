#include "sbcore/gate.hpp"

#include <array>
#include <cstring>
#include <memory>

#include <windows.h>

#include "sbcore/build_target.hpp"
#include "sbcore/memory.hpp"
#include "sbcore/taskgraph_manifest.generated.hpp"

namespace sbcore::gate
{
    namespace
    {
        using memory::is_readable_region;
        using memory::read_exact;

        // Exact images pinned by SBMovementNative 1.3.6 and SBRetryPointNative
        // 0.1.1 (movement.cpp:61-85, retry_point.cpp:61-90). Kept so the sbcore
        // core is never weaker than any gate it replaces: create_task here
        // covers 64 bytes (the generated check covers 63).
        constexpr std::uint8_t kLegacyCreateTask[64] = {
            0x48, 0x89, 0x5C, 0x24, 0x10, 0x48, 0x89, 0x6C, 0x24, 0x20, 0x56, 0x57, 0x41, 0x54, 0x41, 0x56,
            0x41, 0x57, 0x48, 0x83, 0xEC, 0x20, 0x45, 0x33, 0xE4, 0x45, 0x8B, 0xF8, 0x48, 0x8B, 0xEA, 0x48,
            0x8B, 0xF1, 0x48, 0x85, 0xD2, 0x74, 0x06, 0x44, 0x8B, 0x72, 0x28, 0xEB, 0x03, 0x45, 0x8B, 0xF4,
            0x8B, 0x0D, 0x2A, 0xF6, 0xE4, 0x05, 0xFF, 0x15, 0x5C, 0xDE, 0x47, 0x04, 0x48, 0x8B, 0xD8, 0x48,
        };
        constexpr std::uint8_t kLegacySetupTask[42] = {
            0x4C, 0x8B, 0xDC, 0x45, 0x88, 0x4B, 0x20, 0x45, 0x89, 0x43, 0x18, 0x49, 0x89, 0x4B, 0x08, 0x56,
            0x48, 0x81, 0xEC, 0xB0, 0x00, 0x00, 0x00, 0x4D, 0x89, 0x7B, 0xC0, 0x48, 0x8B, 0xF1, 0x4C, 0x8B,
            0xFA, 0xC6, 0x41, 0x60, 0x01, 0x8B, 0x41, 0x50, 0x33, 0xD2,
        };
        constexpr std::uint8_t kLegacyExecuteTask[36] = {
            0x48, 0x89, 0x5C, 0x24, 0x08, 0x48, 0x89, 0x74, 0x24, 0x10, 0x57, 0x48, 0x83, 0xEC, 0x20, 0x48,
            0x8B, 0xF9, 0x41, 0x8B, 0xD8, 0x48, 0x8B, 0x49, 0x20, 0x48, 0x8B, 0xF2, 0x48, 0x85, 0xC9, 0x75,
            0x04, 0x48, 0x8D, 0x4F,
        };
        constexpr std::uint8_t kLegacyGameThreadInitializer[12] = {
            0xFF, 0x15, 0xDD, 0x68, 0x77, 0x04, 0x89, 0x05, 0x97, 0x45, 0x23, 0x06,
        };
        constexpr std::uint8_t kAllFF[64] = {
            0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF,
            0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF,
            0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF,
            0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF,
        };

        constexpr CodeCheck kLegacyCode[] = {
            {"legacy_create_task_64", taskgraph::kCreateTaskRva, 64, kLegacyCreateTask, kAllFF, nullptr, 0, true, Role::Called},
            {"legacy_setup_task_42", taskgraph::kSetupTaskRva, 42, kLegacySetupTask, kAllFF, nullptr, 0, true, Role::Called},
            {"legacy_execute_task_36", taskgraph::kTaskExecuteRva, 36, kLegacyExecuteTask, kAllFF, nullptr, 0, true, Role::Called},
            {"legacy_game_thread_initializer_12", taskgraph::kGameThreadInitializerRva, 12, kLegacyGameThreadInitializer, kAllFF, nullptr, 0, false, Role::Anchor},
        };
        constexpr SlotCheck kNoSlots[1] = {{"", 0, 0, 0}};
        constexpr GlobalCheck kNoGlobals[1] = {{"", 0, 0, false}};

        constexpr Manifest kCoreManifest = make_manifest(
            "sbcore_taskgraph", taskgraph::kCodeChecks, taskgraph::kSlotChecks, taskgraph::kGlobalChecks);
        constexpr Manifest kLegacyManifest{"sbcore_legacy_exact", kLegacyCode, std::size(kLegacyCode), kNoSlots, 0, kNoGlobals, 0};

        void copy_name(char* destination, std::size_t capacity, const char* source)
        {
            if (!destination || capacity == 0) return;
            std::size_t i = 0;
            for (; source && source[i] && i + 1 < capacity; ++i) destination[i] = source[i];
            destination[i] = '\0';
        }

        bool fail(Result& result, Reason reason, const char* check, const char* manifest)
        {
            result.passed = false;
            result.reason = reason;
            copy_name(result.failed_check, sizeof(result.failed_check), check);
            copy_name(result.failed_manifest, sizeof(result.failed_manifest), manifest);
            return false;
        }

        // The loaded image's own exception directory (.pdata) is the authority
        // on where functions begin. RtlLookupFunctionEntry only reads it.
        bool is_function_begin(const std::byte* image, std::uint32_t rva)
        {
            DWORD64 image_base = 0;
            const auto* entry = RtlLookupFunctionEntry(reinterpret_cast<DWORD64>(image + rva), &image_base, nullptr);
            return entry && image_base == reinterpret_cast<DWORD64>(image) && entry->BeginAddress == rva;
        }

        const IMAGE_NT_HEADERS64* nt_headers(const std::byte* image)
        {
            if (!image || !is_readable_region(image, sizeof(IMAGE_DOS_HEADER), false)) return nullptr;
            const auto* dos = reinterpret_cast<const IMAGE_DOS_HEADER*>(image);
            if (dos->e_magic != IMAGE_DOS_SIGNATURE || dos->e_lfanew <= 0) return nullptr;
            const auto* nt = reinterpret_cast<const IMAGE_NT_HEADERS64*>(image + dos->e_lfanew);
            if (!is_readable_region(nt, sizeof(*nt), false) || nt->Signature != IMAGE_NT_SIGNATURE) return nullptr;
            return nt;
        }

        bool exe_file_size(const wchar_t* exe_path, std::uint64_t& size_out)
        {
            constexpr DWORD kCapacity = 32768;
            const auto path = std::make_unique<wchar_t[]>(kCapacity);
            if (exe_path)
            {
                if (wcscpy_s(path.get(), kCapacity, exe_path) != 0) return false;
            }
            else
            {
                const DWORD length = GetModuleFileNameW(nullptr, path.get(), kCapacity);
                if (length == 0 || length >= kCapacity) return false;
            }
            WIN32_FILE_ATTRIBUTE_DATA attributes{};
            if (!GetFileAttributesExW(path.get(), GetFileExInfoStandard, &attributes)) return false;
            ULARGE_INTEGER size{};
            size.LowPart = attributes.nFileSizeLow;
            size.HighPart = attributes.nFileSizeHigh;
            size_out = size.QuadPart;
            return true;
        }

        bool run_manifest(const std::byte* image, const Manifest& manifest, Result& result)
        {
            for (std::size_t i = 0; i < manifest.code_count; ++i)
            {
                const auto reason = validate_code_check(image, manifest.code[i]);
                if (reason != Reason::None) return fail(result, reason, manifest.code[i].name, manifest.name);
                ++result.code_checks_passed;
            }
            for (std::size_t i = 0; i < manifest.slot_count; ++i)
            {
                const auto reason = validate_slot_check(image, manifest.slots[i]);
                if (reason != Reason::None) return fail(result, reason, manifest.slots[i].name, manifest.name);
                ++result.slot_checks_passed;
            }
            for (std::size_t i = 0; i < manifest.global_count; ++i)
            {
                const auto reason = validate_global_check(image, manifest.globals[i]);
                if (reason != Reason::None) return fail(result, reason, manifest.globals[i].name, manifest.name);
                ++result.global_checks_passed;
            }
            ++result.manifests_passed;
            return true;
        }
    }

    const Manifest& core_manifest()
    {
        return kCoreManifest;
    }

    const Manifest& legacy_exact_manifest()
    {
        return kLegacyManifest;
    }

    bool rva_in_section(const std::byte* image, std::uint32_t rva, std::uint32_t size, const char* section_name)
    {
        const auto* nt = nt_headers(image);
        if (!nt || !section_name) return false;
        const auto* section = IMAGE_FIRST_SECTION(nt);
        const auto count = nt->FileHeader.NumberOfSections;
        if (!is_readable_region(section, sizeof(IMAGE_SECTION_HEADER) * count, false)) return false;
        for (unsigned i = 0; i < count; ++i)
        {
            char name[IMAGE_SIZEOF_SHORT_NAME + 1] = {};
            std::memcpy(name, section[i].Name, IMAGE_SIZEOF_SHORT_NAME);
            if (std::strcmp(name, section_name) != 0) continue;
            const std::uint64_t begin = section[i].VirtualAddress;
            const std::uint64_t extent = section[i].Misc.VirtualSize ? section[i].Misc.VirtualSize : section[i].SizeOfRawData;
            if (static_cast<std::uint64_t>(rva) >= begin && static_cast<std::uint64_t>(rva) + size <= begin + extent) return true;
        }
        return false;
    }

    Reason validate_code_check(const std::byte* image, const CodeCheck& check)
    {
        std::array<bool, kMaxCheckSize> covered{};
        if (!check.name || check.size == 0 || check.size > covered.size() || !check.bytes || !check.mask
            || (check.reloc_count != 0 && !check.relocs)
            || static_cast<std::uint64_t>(check.rva) + check.size > target::kImageSize)
        {
            return Reason::ManifestInvalid;
        }
        const auto* code = image + check.rva;
        if (!is_readable_region(code, check.size, true)) return Reason::Unreadable;
        for (std::size_t index = 0; index < check.reloc_count; ++index)
        {
            const auto& reloc = check.relocs[index];
            if (reloc.field_offset + 4U > reloc.instr_end || reloc.instr_end > check.size
                || reloc.target_rva >= target::kImageSize)
            {
                return Reason::ManifestInvalid;
            }
            for (std::size_t byte = 0; byte < 4; ++byte)
            {
                if (covered[reloc.field_offset + byte]) return Reason::ManifestInvalid; // overlapping fields
                covered[reloc.field_offset + byte] = true;
            }
        }
        for (std::size_t index = 0; index < check.size; ++index)
        {
            const auto mask = check.mask[index];
            if (mask != 0x00 && mask != 0xFF) return Reason::ManifestInvalid;
            if ((mask == 0x00) != covered[index]) return Reason::ManifestInvalid;
        }
        for (std::size_t index = 0; index < check.size; ++index)
        {
            if (check.mask[index] == 0xFF && std::to_integer<std::uint8_t>(code[index]) != check.bytes[index])
            {
                return Reason::Bytes;
            }
        }
        for (std::size_t index = 0; index < check.reloc_count; ++index)
        {
            const auto& reloc = check.relocs[index];
            std::int32_t displacement = 0;
            std::memcpy(&displacement, code + reloc.field_offset, sizeof(displacement));
            const auto resolved = static_cast<std::int64_t>(check.rva) + static_cast<std::int64_t>(reloc.instr_end)
                + displacement;
            if (resolved != static_cast<std::int64_t>(reloc.target_rva)) return Reason::Relocation;
        }
        if (check.function_begin && !is_function_begin(image, check.rva)) return Reason::FunctionBegin;
        if (check.role == Role::PatchSite && !rva_in_section(image, check.rva, check.size, ".trace"))
        {
            return Reason::Section;
        }
        return Reason::None;
    }

    Reason validate_slot_check(const std::byte* image, const SlotCheck& check)
    {
        if (!check.name || check.target_rva >= target::kImageSize
            || static_cast<std::uint64_t>(check.vtable_rva) + check.slot_offset + sizeof(void*) > target::kImageSize)
        {
            return Reason::ManifestInvalid;
        }
        std::uintptr_t value = 0;
        const auto* slot = image + check.vtable_rva + check.slot_offset;
        if (!is_readable_region(slot, sizeof(value), false) || !read_exact(slot, &value, sizeof(value)))
        {
            return Reason::Unreadable;
        }
        if (value != reinterpret_cast<std::uintptr_t>(image + check.target_rva)) return Reason::Slot;
        if (!is_function_begin(image, check.target_rva)) return Reason::FunctionBegin;
        return Reason::None;
    }

    Reason validate_global_check(const std::byte* image, const GlobalCheck& check)
    {
        if (!check.name || check.size == 0 || static_cast<std::uint64_t>(check.rva) + check.size > target::kImageSize)
        {
            return Reason::ManifestInvalid;
        }
        if (!is_readable_region(image + check.rva, check.size, false)) return Reason::Unreadable;
        if (check.writable && !memory::is_writable_region(image + check.rva, check.size)) return Reason::Writable;
        return Reason::None;
    }

    Result validate(std::byte* image, const wchar_t* exe_path, const Manifest* const* extra, std::size_t extra_count)
    {
        Result result;
        if (!image || !is_readable_region(image, sizeof(IMAGE_DOS_HEADER), false))
        {
            fail(result, Reason::ImageAbsent, "image_absent", "pe");
            return result;
        }
        const auto* dos = reinterpret_cast<const IMAGE_DOS_HEADER*>(image);
        if (dos->e_magic != IMAGE_DOS_SIGNATURE || dos->e_lfanew <= 0)
        {
            fail(result, Reason::DosHeader, "dos_header", "pe");
            return result;
        }
        const auto* nt = reinterpret_cast<const IMAGE_NT_HEADERS64*>(image + dos->e_lfanew);
        if (!is_readable_region(nt, sizeof(*nt), false) || nt->Signature != IMAGE_NT_SIGNATURE
            || nt->FileHeader.Machine != IMAGE_FILE_MACHINE_AMD64)
        {
            fail(result, Reason::PeIdentity, "pe_timestamp_or_image_size", "pe");
            return result;
        }
        result.timestamp = nt->FileHeader.TimeDateStamp;
        result.image_size = nt->OptionalHeader.SizeOfImage;
        if (result.timestamp != target::kTimestamp || result.image_size != target::kImageSize)
        {
            fail(result, Reason::PeIdentity, "pe_timestamp_or_image_size", "pe");
            return result;
        }
        if (nt->OptionalHeader.ImageBase != target::kImageBase)
        {
            fail(result, Reason::ImageBase, "pe_image_base", "pe");
            return result;
        }
        if (!exe_file_size(exe_path, result.exe_file_size) || result.exe_file_size != target::kFileSize)
        {
            fail(result, Reason::ExeFileSize, "exe_file_size", "pe");
            return result;
        }
        if (!run_manifest(image, kCoreManifest, result)) return result;
        if (!run_manifest(image, kLegacyManifest, result)) return result;
        for (std::size_t i = 0; i < extra_count; ++i)
        {
            if (!extra || !extra[i])
            {
                fail(result, Reason::ManifestInvalid, "null_manifest", "extra");
                return result;
            }
            if (!run_manifest(image, *extra[i], result)) return result;
        }
        result.passed = true;
        result.reason = Reason::None;
        result.image = image;
        return result;
    }

    Result validate_running_process(const Manifest* const* extra, std::size_t extra_count)
    {
        return validate(reinterpret_cast<std::byte*>(GetModuleHandleW(nullptr)), nullptr, extra, extra_count);
    }

    const char* reason_name(Reason reason)
    {
        switch (reason)
        {
        case Reason::None: return "none";
        case Reason::ImageAbsent: return "image_absent";
        case Reason::DosHeader: return "dos_header";
        case Reason::PeIdentity: return "pe_identity";
        case Reason::ImageBase: return "image_base";
        case Reason::ExeFileSize: return "exe_file_size";
        case Reason::ManifestInvalid: return "manifest_invalid";
        case Reason::Unreadable: return "unreadable";
        case Reason::Bytes: return "bytes";
        case Reason::Relocation: return "relocation";
        case Reason::FunctionBegin: return "function_begin";
        case Reason::Slot: return "slot";
        case Reason::Section: return "section";
        case Reason::Writable: return "writable";
        }
        return "unknown";
    }
}
