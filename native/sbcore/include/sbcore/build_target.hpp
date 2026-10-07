#pragma once

// The one Stellar Blade build every sbcore native is certified for.
// SB-Win64-Shipping.exe, Steam update of 2026-08-12.

#include <array>
#include <cstdint>

#include "sbcore/taskgraph_manifest.generated.hpp"

namespace sbcore::target
{
    inline constexpr std::uint32_t kTimestamp = 0x6A6A3B74;  // IMAGE_FILE_HEADER.TimeDateStamp
    inline constexpr std::uint32_t kImageSize = 0x15981000;  // IMAGE_OPTIONAL_HEADER.SizeOfImage
    inline constexpr std::uint64_t kFileSize = 359186432ULL; // bytes on disk
    inline constexpr std::uint64_t kImageBase = 0x140000000ULL; // no ASLR, no .reloc
    inline constexpr char kSha256Hex[] = "573AAFF1C9455F85EA6036EF6F6CCB0774DE4164722A296276FBBFC7FA87545C";
    inline constexpr std::array<std::uint8_t, 32> kSha256{
        0x57, 0x3A, 0xAF, 0xF1, 0xC9, 0x45, 0x5F, 0x85, 0xEA, 0x60, 0x36, 0xEF, 0x6F, 0x6C, 0xCB, 0x07,
        0x74, 0xDE, 0x41, 0x64, 0x72, 0x2A, 0x29, 0x62, 0x76, 0xFB, 0xBF, 0xC7, 0xFA, 0x87, 0x54, 0x5C,
    };

    // The generated TaskGraph manifest and this header must name the same build.
    static_assert(taskgraph::kExpectedTimestamp == kTimestamp);
    static_assert(taskgraph::kExpectedImageSize == kImageSize);
    static_assert(taskgraph::kExpectedFileSize == kFileSize);
}
