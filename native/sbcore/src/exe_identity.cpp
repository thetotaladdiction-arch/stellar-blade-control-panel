#include "sbcore/exe_identity.hpp"

#include <cstring>
#include <memory>
#include <string>

#include <windows.h>

#include <bcrypt.h>

#include "sbcore/build_target.hpp"

namespace sbcore::exe_identity
{
    namespace
    {
        constexpr std::uint32_t kMagic = 0x31434253; // "SBC1"
        constexpr std::uint32_t kComputed = 1;

        struct FileIdentity
        {
            std::uint64_t volume = 0;
            std::uint64_t index = 0;
            std::uint64_t size = 0;
            std::uint64_t last_write = 0;
            bool operator==(const FileIdentity&) const = default;
        };

        struct SharedRecord
        {
            std::uint32_t magic;
            std::uint32_t state;
            FileIdentity identity;
            std::uint8_t digest[32];
        };
        static_assert(sizeof(SharedRecord) <= 4096);

        // The section must outlive every call: a named object dies with its
        // last handle. Each module keeps its handle and view for the process
        // lifetime (created under the named mutex, never closed).
        SharedRecord* g_view = nullptr;

        std::wstring object_name(const wchar_t* prefix)
        {
            return std::wstring(prefix) + std::to_wstring(GetCurrentProcessId());
        }

        bool hash_file(HANDLE file, std::uint64_t size, std::array<std::uint8_t, 32>& digest)
        {
            LARGE_INTEGER zero{};
            if (!SetFilePointerEx(file, zero, nullptr, FILE_BEGIN)) return false;
            BCRYPT_ALG_HANDLE algorithm = nullptr;
            BCRYPT_HASH_HANDLE hash = nullptr;
            bool ok = false;
            constexpr DWORD kChunk = 1u << 20;
            auto buffer = std::make_unique<std::uint8_t[]>(kChunk);
            do
            {
                if (!BCRYPT_SUCCESS(BCryptOpenAlgorithmProvider(&algorithm, BCRYPT_SHA256_ALGORITHM, nullptr, 0))) break;
                // Object memory is allocated by CNG when pbHashObject is null (Windows 7+).
                if (!BCRYPT_SUCCESS(BCryptCreateHash(algorithm, &hash, nullptr, 0, nullptr, 0, 0))) break;
                std::uint64_t total = 0;
                bool read_ok = true;
                while (total < size)
                {
                    DWORD read = 0;
                    if (!ReadFile(file, buffer.get(), kChunk, &read, nullptr) || read == 0 || total + read > size
                        || !BCRYPT_SUCCESS(BCryptHashData(hash, buffer.get(), read, 0)))
                    {
                        read_ok = false;
                        break;
                    }
                    total += read;
                }
                if (!read_ok || total != size) break;
                ok = BCRYPT_SUCCESS(BCryptFinishHash(hash, digest.data(), static_cast<ULONG>(digest.size()), 0));
            } while (false);
            if (hash) BCryptDestroyHash(hash);
            if (algorithm) BCryptCloseAlgorithmProvider(algorithm, 0);
            return ok;
        }
    }

    Info verify_sha256(const wchar_t* exe_path, std::uint64_t expected_size, const std::array<std::uint8_t, 32>& expected_sha256)
    {
        Info info;
        std::wstring path;
        if (exe_path)
        {
            path = exe_path;
        }
        else
        {
            auto buffer = std::make_unique<wchar_t[]>(32768);
            const DWORD length = GetModuleFileNameW(nullptr, buffer.get(), 32768);
            if (length == 0 || length >= 32768) return info;
            path.assign(buffer.get(), length);
        }
        const HANDLE file = CreateFileW(path.c_str(), GENERIC_READ, FILE_SHARE_READ | FILE_SHARE_DELETE, nullptr, OPEN_EXISTING,
                                        FILE_ATTRIBUTE_NORMAL | FILE_FLAG_OPEN_REPARSE_POINT | FILE_FLAG_SEQUENTIAL_SCAN, nullptr);
        if (file == INVALID_HANDLE_VALUE) return info;
        BY_HANDLE_FILE_INFORMATION information{};
        if (!GetFileInformationByHandle(file, &information)
            || (information.dwFileAttributes & (FILE_ATTRIBUTE_DIRECTORY | FILE_ATTRIBUTE_REPARSE_POINT)) != 0
            || information.nNumberOfLinks != 1)
        {
            CloseHandle(file);
            info.result = Result::NotPlain;
            return info;
        }
        FileIdentity identity;
        identity.volume = information.dwVolumeSerialNumber;
        identity.index = (static_cast<std::uint64_t>(information.nFileIndexHigh) << 32) | information.nFileIndexLow;
        identity.size = (static_cast<std::uint64_t>(information.nFileSizeHigh) << 32) | information.nFileSizeLow;
        identity.last_write = (static_cast<std::uint64_t>(information.ftLastWriteTime.dwHighDateTime) << 32)
            | information.ftLastWriteTime.dwLowDateTime;
        info.file_size = identity.size;
        if (identity.size != expected_size)
        {
            CloseHandle(file);
            info.result = Result::SizeMismatch;
            return info;
        }

        // Process-wide cache. Any failure here only costs time: the digest is
        // then computed locally and never trusted from shared memory.
        const HANDLE mutex = CreateMutexW(nullptr, FALSE, object_name(L"Local\\SBCore.ExeSha256.Lock.").c_str());
        bool locked = false;
        if (mutex)
        {
            const DWORD wait = WaitForSingleObject(mutex, 120'000);
            locked = wait == WAIT_OBJECT_0 || wait == WAIT_ABANDONED;
        }
        SharedRecord* record = nullptr;
        if (locked)
        {
            if (!g_view)
            {
                const HANDLE section = CreateFileMappingW(INVALID_HANDLE_VALUE, nullptr, PAGE_READWRITE, 0, 4096,
                                                          object_name(L"Local\\SBCore.ExeSha256.").c_str());
                if (section)
                {
                    g_view = static_cast<SharedRecord*>(MapViewOfFile(section, FILE_MAP_READ | FILE_MAP_WRITE, 0, 0, sizeof(SharedRecord)));
                    if (!g_view) CloseHandle(section); // else: kept open for the process lifetime
                }
            }
            record = g_view;
        }
        info.shared_ok = record != nullptr;

        bool have_digest = false;
        if (record && record->magic == kMagic && record->state == kComputed && record->identity == identity)
        {
            std::memcpy(info.digest.data(), record->digest, info.digest.size());
            have_digest = true;
            info.computed_here = false;
        }
        if (!have_digest)
        {
            if (hash_file(file, identity.size, info.digest))
            {
                have_digest = true;
                info.computed_here = true;
                if (record)
                {
                    record->state = 0;
                    MemoryBarrier();
                    record->magic = kMagic;
                    record->identity = identity;
                    std::memcpy(record->digest, info.digest.data(), info.digest.size());
                    MemoryBarrier();
                    record->state = kComputed;
                }
            }
        }
        if (locked) ReleaseMutex(mutex);
        if (mutex) CloseHandle(mutex);
        CloseHandle(file);
        if (!have_digest)
        {
            info.result = Result::HashFailed;
            return info;
        }
        info.result = info.digest == expected_sha256 ? Result::Match : Result::Mismatch;
        return info;
    }

    Info verify_running_exe()
    {
        return verify_sha256(nullptr, target::kFileSize, target::kSha256);
    }

    const char* result_name(Result result)
    {
        switch (result)
        {
        case Result::Match: return "match";
        case Result::Mismatch: return "mismatch";
        case Result::OpenFailed: return "open_failed";
        case Result::NotPlain: return "not_plain";
        case Result::SizeMismatch: return "size_mismatch";
        case Result::HashFailed: return "hash_failed";
        }
        return "unknown";
    }
}
