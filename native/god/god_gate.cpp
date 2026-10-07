#include "god_gate.hpp"

#include <cstdio>
#include <cstring>
#include <memory>
#include <string>

#include <windows.h>

#include "sbcore/build_target.hpp"
#include "sbcore/taskgraph_manifest.generated.hpp"

namespace sbgod::gate
{
    namespace
    {
        namespace sb = sbcore::gate;

        // The build God's tables were derived for is the one sbcore certifies.
        static_assert(sites::kExpectedTimestamp == sbcore::target::kTimestamp);
        static_assert(sites::kExpectedImageSize == sbcore::target::kImageSize);
        static_assert(sites::kExpectedExeFileSize == sbcore::target::kFileSize);
        static_assert(sites::kGameThreadIdRva == sbcore::taskgraph::kGameThreadIdRva);

        constexpr std::size_t kMaxCode = sites::kSiteCount * 2 + sites::kAnchorCount;
        constexpr std::uint8_t kPadding[2] = {0xCC, 0xCC};

        bool whole_function_anchor(std::uint32_t id)
        {
            // .pdata RUNTIME_FUNCTION BeginAddress at the anchor rva (verify_sites.py).
            return id == sites::kAnchorCurrentTargetGuid || id == sites::kAnchorGuidMapLookup
                || id == sites::kAnchorLiveSetProbe;
        }

        struct Storage
        {
            sb::CodeCheck code[kMaxCode]{};
            std::size_t code_count = 0;
            sb::GlobalCheck globals[sites::kAnchorCount]{};
            std::size_t global_count = 0;
            sb::Reloc relocs[sites::kAnchorCount]{};
            std::uint8_t masks[kMaxCode][sb::kMaxCheckSize]{};
            char padding_names[sites::kSiteCount][48]{};
            sb::Manifest manifest{};
            bool valid = true;
        };

        std::uint8_t* full_mask(Storage& s, std::size_t index, std::size_t size)
        {
            if (size == 0 || size > sb::kMaxCheckSize)
            {
                s.valid = false;
                return s.masks[index];
            }
            std::memset(s.masks[index], 0xFF, size);
            return s.masks[index];
        }

        Storage* build()
        {
            auto* s = new Storage{}; // lives for the process (the module is pinned)
            for (std::uint32_t i = 0; i < sites::kSiteCount; ++i)
            {
                const auto& site = sites::kSites[i];
                auto& patch = s->code[s->code_count];
                patch.name = site.name;
                patch.rva = static_cast<std::uint32_t>(site.rva);
                patch.size = static_cast<std::uint16_t>(site.window_len);
                patch.bytes = site.window;
                patch.mask = full_mask(*s, s->code_count, site.window_len);
                patch.relocs = nullptr;
                patch.reloc_count = 0;
                patch.function_begin = true;
                patch.role = sb::Role::PatchSite;
                ++s->code_count;

                std::snprintf(s->padding_names[i], sizeof(s->padding_names[i]), "%s_padding", site.name);
                auto& pad = s->code[s->code_count];
                pad.name = s->padding_names[i];
                pad.rva = static_cast<std::uint32_t>(site.rva - sizeof(kPadding));
                pad.size = sizeof(kPadding);
                pad.bytes = kPadding;
                pad.mask = full_mask(*s, s->code_count, sizeof(kPadding));
                pad.relocs = nullptr;
                pad.reloc_count = 0;
                pad.function_begin = false;
                pad.role = sb::Role::Reference;
                ++s->code_count;
            }
            for (std::uint32_t i = 0; i < sites::kAnchorCount; ++i)
            {
                const auto& anchor = sites::kAnchors[i];
                if (!anchor.code)
                {
                    // .rdata: an sbcore CodeCheck requires executable memory, so the
                    // bytes stay with sites::validate_image; the gate proves the range.
                    auto& global = s->globals[s->global_count++];
                    global.name = anchor.name;
                    global.rva = static_cast<std::uint32_t>(anchor.rva);
                    global.size = static_cast<std::uint32_t>(anchor.len);
                    global.writable = false;
                    continue;
                }
                auto& check = s->code[s->code_count];
                check.name = anchor.name;
                check.rva = static_cast<std::uint32_t>(anchor.rva);
                check.size = static_cast<std::uint16_t>(anchor.len);
                check.bytes = anchor.bytes;
                auto* mask = full_mask(*s, s->code_count, anchor.len);
                check.mask = mask;
                check.relocs = nullptr;
                check.reloc_count = 0;
                check.function_begin = whole_function_anchor(i);
                check.role = sb::Role::Anchor;
                std::uint16_t field = 0;
                std::uint16_t end = 0;
                switch (anchor.rel_kind)
                {
                case sites::RelKind::None:
                    break;
                case sites::RelKind::CallAtEnd:
                    if (anchor.len < 5 || anchor.bytes[anchor.len - 5] != 0xE8) s->valid = false;
                    field = static_cast<std::uint16_t>(anchor.len - 4);
                    end = static_cast<std::uint16_t>(anchor.len);
                    break;
                case sites::RelKind::RipDisp32At2:
                    field = 2;
                    end = 6;
                    break;
                case sites::RelKind::RipDisp32At3:
                    field = 3;
                    end = 7;
                    break;
                }
                if (anchor.rel_kind != sites::RelKind::None)
                {
                    if (end > anchor.len)
                    {
                        s->valid = false;
                    }
                    else
                    {
                        auto& reloc = s->relocs[i];
                        reloc.field_offset = field;
                        reloc.instr_end = end;
                        reloc.target_rva = static_cast<std::uint32_t>(anchor.rel_target_rva);
                        std::memset(mask + field, 0x00, 4);
                        check.relocs = &reloc;
                        check.reloc_count = 1;
                    }
                }
                ++s->code_count;
            }
            // A malformed table must never pass: an empty name makes every
            // sbcore check report ManifestInvalid.
            s->manifest = sb::Manifest{kManifestName, s->code, s->valid ? s->code_count : 1, nullptr, 0, s->globals,
                                       s->global_count};
            if (!s->valid) s->code[0].name = nullptr;
            return s;
        }

        bool starts_with(const char* text, const char* prefix)
        {
            return text && std::strncmp(text, prefix, std::strlen(prefix)) == 0;
        }

        void set_text(char (&buffer)[64], const char* format, const char* value)
        {
            std::snprintf(buffer, sizeof(buffer), format, value);
        }

        // The failed God-manifest check back to the v1.1.x install_error name.
        void god_check_error(char (&buffer)[64], const char* check)
        {
            for (std::uint32_t i = 0; i < sites::kSiteCount; ++i)
            {
                const char* name = sites::kSites[i].name;
                const std::size_t n = std::strlen(name);
                if (std::strncmp(check, name, n) == 0 && (check[n] == '\0' || std::strcmp(check + n, "_padding") == 0))
                {
                    set_text(buffer, "site-mismatch:%s", name);
                    return;
                }
            }
            for (std::uint32_t i = 0; i < sites::kAnchorCount; ++i)
            {
                if (std::strcmp(check, sites::kAnchors[i].name) == 0)
                {
                    set_text(buffer, "anchor-mismatch:%s", check);
                    return;
                }
            }
            set_text(buffer, "gate:%s", check[0] ? check : "unknown");
        }

        std::uint64_t file_size_telemetry(const wchar_t* exe_path)
        {
            std::wstring path;
            if (exe_path)
            {
                path = exe_path;
            }
            else
            {
                constexpr DWORD kCapacity = 32768;
                const auto buffer = std::make_unique<wchar_t[]>(kCapacity);
                const DWORD length = GetModuleFileNameW(nullptr, buffer.get(), kCapacity);
                if (length == 0 || length >= kCapacity) return 0;
                path.assign(buffer.get(), length);
            }
            WIN32_FILE_ATTRIBUTE_DATA data{};
            if (!GetFileAttributesExW(path.c_str(), GetFileExInfoStandard, &data)) return 0;
            return (static_cast<std::uint64_t>(data.nFileSizeHigh) << 32) | data.nFileSizeLow;
        }
    } // namespace

    const sbcore::gate::Manifest& manifest()
    {
        static const Storage* storage = build();
        return storage->manifest;
    }

    Outcome evaluate(std::byte* image, const wchar_t* exe_path)
    {
        Outcome out{};
        const sb::Manifest* extra[] = {&manifest()};
        out.core = sb::validate(image, exe_path, extra, 1);
        out.god = sites::validate_image(image, true);

        const auto reason = out.core.reason;
        out.build_ok = out.core.passed
            || (reason != sb::Reason::ImageAbsent && reason != sb::Reason::DosHeader && reason != sb::Reason::PeIdentity
                && reason != sb::Reason::ImageBase);
        out.exe_file_size_ok = out.build_ok && (out.core.passed || reason != sb::Reason::ExeFileSize);
        out.exe_file_size = out.core.exe_file_size != 0 ? out.core.exe_file_size : file_size_telemetry(exe_path);
        out.taskgraph_ok = out.core.passed || out.core.manifests_passed >= 2;
        out.all_ok = out.core.passed && out.god.all_ok;

        if (out.all_ok)
        {
            set_text(out.install_error, "%s", "none");
        }
        else if (!out.build_ok)
        {
            set_text(out.install_error, "%s", "build_mismatch");
        }
        else if (!out.exe_file_size_ok)
        {
            set_text(out.install_error, "%s", "exe_file_size_mismatch");
        }
        else if (!out.core.passed)
        {
            if (std::strcmp(out.core.failed_manifest, kManifestName) == 0)
                god_check_error(out.install_error, out.core.failed_check);
            else if (starts_with(out.core.failed_manifest, "sbcore_"))
                set_text(out.install_error, "%s", "taskgraph-mismatch");
            else
                set_text(out.install_error, "gate:%s", out.core.failed_check[0] ? out.core.failed_check : "unknown");
        }
        else
        {
            set_text(out.install_error, "%s", out.god.first_error[0] ? out.god.first_error : "validation_failed");
        }
        return out;
    }
} // namespace sbgod::gate
