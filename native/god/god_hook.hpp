#pragma once

#include <cstdint>

// v1.3.2: one literal for the heartbeat/log version and the UE4SS ModVersion
// (dllmain.cpp widens it with L"" ...; 1.3.1 still reported ModVersion 1.3.0).
#define SBGOD_VERSION_STRING "1.3.5"

namespace sbgod
{
    inline constexpr const char* kVersion = SBGOD_VERSION_STRING;

    // FSB simulation actor layout on SB-Win64-Shipping.exe TDS 0x6A6A3B74.
    //
    // Stat[] at actor+0x118 is proven by instruction bytes that the installer
    // re-validates before any patch: SetActorStat+0x2B
    // `movss [rbx+rdi*4+118h], xmm0` (rbx = actor, rdi = stat type) and the
    // ApplyStatExecute anchor `movss xmm8, [r15+rax*4+118h]`.
    inline constexpr std::uint32_t kStatArrayOffset = 0x118;
    inline constexpr int kStatHp = 1;
    inline constexpr int kStatMaxHp = 2;
    inline constexpr int kStatShield = 7;

    // Confirmed-player maintain/restore (progressed saves can exceed 2500 HP).
    inline constexpr float kMaxPlayerHp = 100000.0f;
    inline constexpr float kMaxPlayerShield = 100000.0f;

    // The actor GUID is the uint32 the game's own accessor returns: the actor
    // interface lives at +0x10 and its vtable slot +0x38 is 0xE4D660
    // `mov eax,[rcx+20h]; ret`, i.e. actor+0x30. CurrentTargetGuid
    // (0x1CC2590) and ApplyStatExecute (0x1B1F8DB) call exactly that slot.
    // All of it is byte-validated before install (god_sites.cpp anchors).
    inline constexpr std::uint32_t kActorGuidOffset = 0x30;

    // actor+0x10C is a per-type id, NOT the GUID (v1.1.0 treated it as the
    // GUID): Eve's is 100 in story and Boss Challenge, and same-type enemies
    // share one value. Used only as one identity signal and in telemetry.
    inline constexpr std::uint32_t kActorTableIdOffset = 0x10C;

    bool install();
    void uninstall();
    void on_update();
    bool hooks_installed();
    const char* install_error();

#if defined(SBGOD_WORKER_TEST_EXPORTS)
    // Offline worker-test module only (tools/worker_module.cpp); never compiled
    // into the staged DLL. Runs God's production leaf probe (safe_read_u32)
    // on an arbitrary address so the test can prove how a miss is classified.
    namespace testing
    {
        bool probe_read_u32(const void* address, std::uint32_t* out);
    }
#endif
} // namespace sbgod
