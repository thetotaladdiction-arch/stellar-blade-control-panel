#pragma once

// Exe SHA-256, computed once per process and shared by every sbcore native
// (A11). The first native to ask hashes the file while holding the named
// mutex Local\SBCore.ExeSha256.Lock.<pid> and stores the digest with the
// file's identity (volume serial, file index, size, last write time) in the
// named section Local\SBCore.ExeSha256.<pid>. Later callers reuse the digest
// only if the identity of the file they open is unchanged.
//
// Optional stage of the gate: natives that pinned the SHA-256 (LiveAdd) use
// it; the TDS/SOI/size gate stays mandatory for every native either way.

#include <array>
#include <cstdint>

namespace sbcore::exe_identity
{
    enum class Result : std::uint8_t
    {
        Match = 0,
        Mismatch,
        OpenFailed,
        NotPlain,     // reparse point / hard-linked / directory
        SizeMismatch, // cheap pre-check before hashing
        HashFailed,
    };

    struct Info
    {
        Result result = Result::OpenFailed;
        bool computed_here = false; // false = reused the shared digest
        bool shared_ok = false;     // the process-wide cache was usable (a failure only costs time)
        std::uint64_t file_size = 0;
        std::array<std::uint8_t, 32> digest{};
    };

    // exe_path nullptr = the running process image.
    Info verify_sha256(const wchar_t* exe_path, std::uint64_t expected_size,
                       const std::array<std::uint8_t, 32>& expected_sha256);

    // verify_sha256(nullptr, target::kFileSize, target::kSha256).
    Info verify_running_exe();

    const char* result_name(Result result);
}
