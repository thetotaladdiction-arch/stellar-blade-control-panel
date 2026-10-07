#pragma once

// Exact-build site table and fail-closed patcher for SBGodNative v1.2.0.
//
// Certified only for SB-Win64-Shipping.exe
//   SHA-256 573AAFF1C9455F85EA6036EF6F6CCB0774DE4164722A296276FBBFC7FA87545C
//   TimeDateStamp 0x6A6A3B74, SizeOfImage 0x15981000, 359,186,432 bytes,
//   ImageBase 0x140000000, no ASLR.
//
// Every value below was re-derived offline from the exe file bytes
// (tools/verify_sites.py): each hook entry is a .pdata RUNTIME_FUNCTION
// BeginAddress preceded by CC padding, each patch length ends on a whole
// instruction boundary with no RIP-relative or relative-branch instruction in
// the copied prologue, and every byte window is compared exactly.
//
// v1.2.0: the install decision is sbcore's exact-build gate (god_gate.cpp),
// which also validates these tables as God's extra manifest. The TaskGraph
// signatures and RVAs moved to sbcore (taskgraph_manifest.generated.hpp,
// dispatched by sbcore::dispatch); validate_image() keeps the per-site/anchor
// flags for the heartbeat, the .rdata anchors, and patch_all()'s own re-check.
//
// This unit has no UE4SS or sbcore dependency so the identical code is
// exercised by the offline harness (tools/offline_harness.cpp) against the
// exe file mapped at its RVAs.

#include <atomic>
#include <cstddef>
#include <cstdint>

namespace sbgod::sites
{
    inline constexpr std::uint32_t kExpectedTimestamp = 0x6A6A3B74;
    inline constexpr std::uint32_t kExpectedImageSize = 0x15981000;
    inline constexpr std::uint64_t kExpectedExeFileSize = 359186432ULL;

    enum SiteId : std::uint32_t
    {
        kSetActorStat = 0,     // FSB actor stat setter (Stat[] at actor+0x118)
        kApplyStatExecute = 1, // FSBActorApplyStat::Execute(cmd)
        kDeadExecute = 2,      // FSBActorDead::Execute(cmd)
        kDeathTransition = 3,  // actor death transition (11 arguments)
        kActorStateChange = 4, // actor-state counter mutator (actor, tag, add, clear)
        // ---- v1.3.1 ----
        kApplyStatDiff = 5,    // FSB actor ApplyStatDiff(E, stat, ctx, diff, u8, u8, i32) -> bool (the Stat[] write
                               // every server-side damage/heal goes through BEFORE any ApplyStat command exists)
        kSiteCount = 6,
    };
    // Sites 0..4 keep their v1.1.0 heartbeat keys; site 5 is reported inside
    // god_fast_arm (the heartbeat is at sbcore's 256-key limit and every
    // v1.1.2 key must stay an exact prefix).
    inline constexpr std::uint32_t kSiteCountV110 = 5;

    enum AnchorId : std::uint32_t
    {
        kAnchorApplyStatSetterCall = 0,  // ApplyStatExecute: SetActorStat(actor, [cmd+0x14], [cmd+0x24])
        kAnchorApplyStatDiffCall = 1,    // ApplyStatExecute: reads cmd +0x14/+0x18/+0x1C/+0x1D/+0x20/+0x24 and Stat[] +0x118
        kAnchorDeadExecuteFieldsCall = 2,// DeadExecute: cmd +0x14/+0x18/+0x1C/+0x20/+0x24/+0x25 -> DeathTransition
        kAnchorDeadLocalCall = 3,        // local FSBActorDead caller of DeathTransition
        kAnchorStateScopedCall = 4,      // scoped authoritative-stat caller of ActorStateChange
        kAnchorGameThreadIdInit = 5,     // mov [GGameThreadId], eax
        // ---- v1.1.1 player-identity chain (god_identity.cpp) ----
        kAnchorLocalClientCacheLoad = 6, // local-client getter: mov rax,[rip -> 0x7032570] (cache read, never called)
        kAnchorCurrentTargetGuid = 7,    // whole CurrentTargetGuid: holder +0xC8, index +0x3C, count +0x30, array +0x28, iface +0x10 slot +0x38
        kAnchorActorGuidAccessor = 8,    // 0xE4D660 `mov eax,[rcx+20h]; ret` between int3 padding -> GUID at actor+0x30
        kAnchorActorIfaceGuidSlot = 9,   // .rdata: iface vtable 0x5BF67D0 slot +0x38 == 0x140E4D660
        kAnchorActorVtableHead = 10,     // .rdata: FSB actor vtable 0x5BF6730 first two slots
        kAnchorApplyStatLookupCall = 11, // ApplyStatExecute: LocalClient()->[+0xC8] lookup([cmd+0x10]) via 0x1AACE90
        kAnchorGuidMapLookup = 12,       // 0x1AACE90, whole function (3 .pdata chunks) mirrored read-only by the identity pass
        // ---- v1.1.2 ----
        kAnchorLiveSetProbe = 13,        // 0xF8CCF0 TSet<actor*> FindId on holder+0x48 (lookup chunk 2), mirrored read-only
        // ---- v1.3.1 ----
        kAnchorApplyStatDiffServerCall = 14,   // 0x1BA8720: ApplyStatDiff([owner+0x60], stat, ctx, diff, 3 stack args)
        kAnchorApplyStatDiffServerResult = 15, // `test al,al / je <exit>`: false -> no command, no death path
        kAnchorGameWorldInitCall = 16,         // LocalClient() -> FSBGameWorld::Init(this): the chain's client IS the game world
        kAnchorEventorGuidInitLog = 17,        // Init logs [this+0x80] as "EventorActorGUID" (the S9' direct proof field)
        kAnchorCount = 18,
    };
    // Anchors 0..5 keep their v1.1.0 heartbeat position; 6..13 are the v1.1.1/
    // v1.1.2 keys appended after them; 14.. (v1.3.1) are reported inside
    // god_fast_arm only (sbcore's 256-key heartbeat limit).
    inline constexpr std::uint32_t kAnchorCountV110 = 6;
    inline constexpr std::uint32_t kAnchorCountV112 = 14;

    enum class JumpBackRegister : std::uint8_t
    {
        Rax, // 48 B8 imm64 / FF E0
        R11, // 49 BB imm64 / 41 FF E3
    };

    struct HookSite
    {
        const char* name;
        const char* heartbeat_key;
        std::uintptr_t rva;
        std::size_t patch_len;
        const std::uint8_t* window; // exact bytes at rva (window_len >= patch_len)
        std::size_t window_len;
        JumpBackRegister jump_back;
    };

    enum class RelKind : std::uint8_t
    {
        None,
        CallAtEnd,   // E8 rel32 occupies the last five bytes; destination must equal rel_target_rva
        RipDisp32At2, // two-byte opcode + disp32 (six-byte instruction at the start); destination == rel_target_rva
        RipDisp32At3  // REX + opcode + modrm + disp32 (seven-byte instruction at the start); destination == rel_target_rva
    };

    struct Anchor
    {
        const char* name;
        const char* heartbeat_key;
        std::uintptr_t rva;
        const std::uint8_t* bytes;
        std::size_t len;
        RelKind rel_kind;
        std::uintptr_t rel_target_rva;
        bool code = true; // false: read-only data (.rdata); not required to be executable
    };

    // Return addresses (RVAs) compared against _ReturnAddress() by the hooks.
    inline constexpr std::uintptr_t kDeadNetworkReturnRva = 0x1B201BF;     // after DeadExecute's DeathTransition call
    inline constexpr std::uintptr_t kDeadLocalReturnRva = 0x1BAE8B1;       // after the local caller's DeathTransition call
    inline constexpr std::uintptr_t kStateScopedReturnRva = 0x1BADED5;     // after the scoped ActorStateChange call
    inline constexpr std::uintptr_t kApplyStatSetterReturnRva = 0x1B1F96A; // after ApplyStatExecute's SetActorStat call
    // v1.3.1: the two (and only) callers of ApplyStatDiff 0x1A64CE0.
    inline constexpr std::uintptr_t kApplyStatDiffRva = 0x1A64CE0;
    inline constexpr std::uintptr_t kApplyDiffServerReturnRva = 0x1BA8823; // server-side apply 0x1BA8720 (the real hit)
    inline constexpr std::uintptr_t kApplyDiffEchoReturnRva = 0x1B1F82B;   // ApplyStatExecute's replay of the command
    // v1.3.1 S9' direct proof: FSBGameWorld::Init (called on LocalClient()).
    inline constexpr std::uintptr_t kGameWorldInitRva = 0x1C97CA0;
    inline constexpr std::uintptr_t kEventorInitLogFormatRva = 0x5C14920;  // L"FSBGameWorld::Init, ... EventorActorGUID : %d"

    // GGameThreadId (the GameThreadIdInit anchor's store target). The
    // TaskGraph RVAs live in sbcore::taskgraph since v1.2.0; god_gate.cpp
    // static_asserts that this value equals sbcore's.
    inline constexpr std::uintptr_t kGameThreadIdRva = 0x706B538;

    // v1.1.1 player-identity chain (read-only; see god_identity.hpp). Each
    // value is proven by an anchor above and re-checked by verify_sites.py.
    inline constexpr std::uintptr_t kLocalClientCacheRva = 0x7032570;  // LocalClientCacheLoad
    inline constexpr std::uintptr_t kActorVtableRva = 0x5BF6730;       // ActorVtableHead (E+0x00)
    inline constexpr std::uintptr_t kActorIfaceVtableRva = 0x5BF67D0;  // E+0x10
    inline constexpr std::uintptr_t kActorIfaceGuidSlotOffset = 0x38;  // CurrentTargetGuid `jmp [rax+38h]`
    inline constexpr std::uintptr_t kActorGuidAccessorRva = 0xE4D660;  // ActorGuidAccessor
    inline constexpr std::uintptr_t kGuidMapLookupRva = 0x1AACE90;     // ApplyStatLookupCall target
    inline constexpr std::uintptr_t kLiveSetProbeRva = 0xF8CCF0;       // called by GuidMapLookup chunk 2 (0x1AACF2F)

    extern const HookSite kSites[kSiteCount];
    extern const Anchor kAnchors[kAnchorCount];

    struct ValidationReport
    {
        bool headers_ok{};
        std::uint32_t timestamp{};
        std::uint32_t size_of_image{};
        std::uint16_t machine{};
        bool site_ok[kSiteCount]{};
        bool anchor_ok[kAnchorCount]{};
        bool all_ok{};
        char first_error[64]{};
    };

    // Read-only. Checks PE identity, then every hook site and anchor; never
    // stops at the first failure so the heartbeat can report every flag.
    // `require_executable` is true in the game. (The TaskGraph signatures
    // are validated by sbcore's gate since v1.2.0.)
    ValidationReport validate_image(const std::byte* image, bool require_executable);

    struct PatchState
    {
        bool installed{};
        void* trampoline_block{};
        void* originals[kSiteCount]{};
        std::uint8_t saved[kSiteCount][32]{};
        std::size_t saved_len[kSiteCount]{};
        char error[64]{};
    };

    // Fail-closed installer. Re-validates every site window immediately
    // before patching, allocates every trampoline, and changes the protection
    // of every target before the first code byte is written. Any failure
    // reverts the protections already changed, frees the trampolines and
    // returns false with zero code bytes written. Each trampoline address is
    // published to original_slots[i] before any entry jump is written, so a
    // hook can never observe a null original.
    bool patch_all(std::byte* image, void* const handlers[kSiteCount],
                   std::atomic<void*>* const original_slots[kSiteCount], PatchState& state);

    // Region helpers shared with the hook unit.
    bool is_readable_region(const void* address, std::size_t size, bool require_executable);
    bool bytes_equal(const std::byte* address, const std::uint8_t* expected, std::size_t size, bool require_executable);
} // namespace sbgod::sites
