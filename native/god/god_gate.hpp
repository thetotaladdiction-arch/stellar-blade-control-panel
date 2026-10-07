#pragma once

// SBGodNative v1.2.0 install gate (plan A8/A11): the sbcore exact-build gate
// plus God's own site/anchor validator, and the mapping of their result onto
// the heartbeat fields the panel reads.
//
//   1. sbcore::gate::validate(image, exe, {God manifest}):
//        PE identity (AMD64, TDS 0x6A6A3B74, SOI 0x15981000, ImageBase
//        0x140000000), the exe file size (359,186,432 bytes), the sbcore
//        TaskGraph/GameThread core manifest (incl. the GGameThreadId
//        initializer relocation proof), the Movement/RetryPoint legacy exact
//        images, then God's manifest (below). Stops at the first failure.
//   2. sbgod::sites::validate_image(image, true): every hook window with its
//        CC CC padding, every anchor incl. the two .rdata data anchors that an
//        sbcore CodeCheck cannot express (it requires executable memory).
//        Never stops early, so every heartbeat flag is reported.
//
// Both must pass. The God manifest holds, in this order: each hook site as a
// PatchSite (exact window, .pdata function begin, inside .trace) followed by
// its 2-byte CC padding, every code anchor (rel32/disp32 fields as relocations
// with their proven targets, whole-function anchors as .pdata function
// begins), and the two .rdata anchors as readable globals.

#include <cstddef>
#include <cstdint>

#include "god_sites.hpp"
#include "sbcore/gate.hpp"

namespace sbgod::gate
{
    inline constexpr const char* kManifestName = "sbgod_1_2_0";

    // Built once from sites::kSites / sites::kAnchors (thread-safe static).
    const sbcore::gate::Manifest& manifest();

    struct Outcome
    {
        sbcore::gate::Result core{};        // sbcore gate incl. the God manifest
        sites::ValidationReport god{};      // God's own validator (heartbeat flags)
        bool build_ok = false;              // the PE stage passed (panel: build_ok)
        std::uint64_t exe_file_size = 0;    // telemetry (the decision is sbcore's)
        bool exe_file_size_ok = false;      // the exe-size stage passed
        bool taskgraph_ok = false;          // sbcore core + legacy manifests passed
        bool all_ok = false;                // both validators passed
        char install_error[64] = {};        // "none" when all_ok, else the v1.1.x name
    };

    // image: the mapped exe (GetModuleHandleW(nullptr) in the game).
    // exe_path: the file whose size is checked (nullptr = the running exe).
    Outcome evaluate(std::byte* image, const wchar_t* exe_path);
} // namespace sbgod::gate
