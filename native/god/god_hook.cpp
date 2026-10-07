// SBGodNative v1.3.5 - native God Mode for Stellar Blade.
//
                                                                     
                                                                               
// Unlimited Burst Energy as two switches of their own, see "Unlimited Beta /
// Burst energy" below. God Mode's own decisions are unchanged; the only thing
// that widens is WHEN the GameThread identity tick runs (also while an energy
// switch is on). Every addition is marked "beta-burst r1".
//
                                                                               
                                                                              
// on the dead actor and never writes the MaxHP arm floor into it
// (god_identity.cpp evaluate); UE4SS ModVersion now comes from kVersion.
//
// v1.3.1 (GOD-130-DIAGNOSIS.md: "Hit got through" in Boss Challenge):
//   * F1 block at the source. The game writes Eve's HP inside the server-side
//     stat apply 0x1BA8720 -> ApplyStatDiff 0x1A64CE0 BEFORE any ApplyStat
//     command exists, so every earlier version only consumed the echo and
//     repaired the pool one GameThread tick (~41 ms) later. A sixth hook on
//     ApplyStatDiff (exactly two callers, both anchored; 7 arguments, the
//     body reads no stack argument beyond the seventh) returns false - the
//     function's own "no change" result, also what the game returns for an
//     HP-immune actor - for a finite negative HP/Shield change of the proven
//     Eve (pointer, GUID and type id re-read) while God is armed. The server
//     apply then exits at 0x1BA9683: no Stat[] write, no ApplyStat command,
//     no pending death, no DeathTransition. Nothing is written to the game.
//     The ApplyStat consume, the setter guard, the per-tick restore and the
//     lethal restore stay as fallbacks and now report any bypass.
//   * F2 no first-hit gap after a stage change / restart. When S1..S8 hold
//     and only S9 is missing, the GameThread publishes (E, G) as "ready"; the
//     game's own damage call on exactly that actor is S9 and is withheld the
//     same way (skip only). Hits that still land while God is on but not yet
//     armed are counted (unarmed_hits), never hidden.
//   * Resume: a God off/on toggle or a transient chain gap re-arms at once on
//     the (E, G) already verified in this process (same pointer, same GUID,
//     S1..S6 re-proven on the tick); no UE pass, no 1 s wait, no hit wait.
//   * S9' fast arm: FSBGameWorld.EventorActorGUID (local client +0x80) == G.
//     v1.3.0's E+0x4A0 PlayerId was 0 on every live sample.
//   * Truthful report (F4): repaired dips (same-tick restore) and saved lethal
//     hits are counted apart from leaks; god_protection=damage_got_through
//     only for real HP loss on Eve (still below the floor after the repair,
//     or a death command for her GUID). v1.3.0 counted every repaired dip.
//   * native_hook.log (F5): every line carries local wall-clock time; arm,
//     disarm, candidate change and leak events are logged from the GameThread
//     through a lock-free ring (the worker writes); the log is appended across
//     game starts (rotated at 2 MiB) instead of truncated.
//   * Heartbeat: still exactly 256 keys, every v1.1.2 key an exact prefix; the
//     sixth site and the four new anchors are reported inside god_fast_arm.
//
// v1.3.0 (fast arm; exact-build gate, hook sites, anchors and patching
// unchanged from v1.2.1):
//   * God arms about one second after the save loads instead of after Eve's
//     first hit. The ninth identity signal (the game passing Eve's actor/GUID
//     to a stat hook, i.e. her first hit) may now also be met by the game's
//     own player link: the local controller's PlayerState, exactly class
//     SBNetworkPlayerState (GetFullName), whose reflected PlayerId sits at
//     +0x2CC and equals the PlayerId the game's FSBActorManager stamped on E
//     (E+0x4A0; god_identity.hpp S9'). S1..S8 are unchanged, including S4
                                                                            
                                                                         
                                                                       
                                                                           
//     decides as before.
//   * After every arm the first hit is still watched: consumed by the
//     ApplyStat hook or kept by the setter hook = blocked; a passed-through
//     ApplyStat that lowered Eve's HP, an HP drop between two GameThread
//     ticks (MaxHP unchanged, from 3 s after the arm), a lethal restore or a
//     death command for her GUID = not blocked (shield-only drops are
//     counted as telemetry). Reported in the heartbeat (god_protection =
//     pending_first_hit | confirmed | damage_got_through, details in
//     god_fast_arm; sbcore's 256-key limit leaves room for exactly these two
//     keys) and in native_hook.log; nothing is silently ignored, and the
//     existing restore fallbacks keep running.
//   * One more UE4SS import: UObject::GetFullName (in sbcore's pinned
//     UE4SS.def; called live by SBBossRetryNative and SBRetryPointNative),
//     GameThread only, only while an identity is being verified.
//
                                                                       
                                                                            
//     behaviour). Windows reports that #GP access violation with the address
//     0xFFFFFFFFFFFFFFFF, so v1.2.0's on-the-probed-bytes test failed and a
//     single bad-pointer read latched every sbcore native off for the process
//     (worker test E reproduces it).
//   * The hooks read the dispatcher's poison directly (god_live()), so a
//     failed GameThread certification disarms God at once, as v1.1.2's
//     callback did, instead of on the next worker tick.
//   * heartbeat dispatch_poisoned=1 also while a fault is latched: the
//     GameThread dispatch is stopped for the process, and the panel's existing
//     contract then shows "Couldn't start safely" instead of "Ready" (God off)
//     or "Switching on" (God on) for a God that can never arm again.
//
// v1.2.0 (sbcore port; hook sites, patching, identity and protection logic
// unchanged):
//   * A1: the UE4SS shim is sbcore's (11 virtual slots, on_ui_init at slot 3,
//     as the loaded UE4SS d3d10044d1); its order is checked on every build.
//   * A8/A11: the install gate is sbcore::gate (PE identity incl. ImageBase,
//     exe size, the generated TaskGraph/GameThread manifest incl. the
//     GGameThreadId initializer relocation proof, the legacy exact images)
//     with God's sites/anchors as an extra manifest (god_gate.cpp); God's own
//     validator still reports every per-site flag and the .rdata anchors.
//     GameThread work goes through sbcore::dispatch (same task bytes; an
//     exception inside CreateTask/Setup now keeps the lease and poisons).
//   * P1: every path is derived from this DLL's location
//     (Mods\SBGodNative\dlls\main.dll): no hardcoded install path.
//   * A9 stage 1: the GameThread callback runs under sbcore::fault; a fault
//     is logged to Mods\SBGodNative\sbcore_faults.log and latches game writes
//     off for the rest of the process (every sbcore native). God then passes
//     every hook through and writes nothing. Leaf memory probes still treat
//     an access violation on the probed bytes as a plain miss; any other
//     exception inside a probe is logged and latched. No crash-on-fault.
//   * A12: the heartbeat is published through sbcore::status::Writer
//     (CREATE_NEW temp, checked write, POSIX rename by handle with retry, no
//     flush), on change plus a 1 s liveness beat; native_god_state.txt is
//     read with FILE_SHARE_DELETE through StableReader (500 ms grace).
//   * Every v1.1.2 heartbeat key keeps its name, order and format (lines now
//     end in CRLF); new keys are appended after them.
//
                                                                       
                                                                              
//     (0x1AACF13) only returns the GUID map's actor when that pointer is a
//     member of the live-actor set at holder+0x48 (0xF8CCF0); otherwise the
//     game logs and returns null. v1.1.1 mirrored and byte-validated only the
//     first chunk, so a GUID entry naming an unregistered (stale) actor passed
//     S4. The full function and 0xF8CCF0 are now anchors, and an offline
//     differential test runs the game's own machine code against the mirror.
//   * Hooks re-check the verified actor's type id (100) as well as its pointer
//     and GUID before protecting it.
//   * A failing UE pass (FindAllOf, 70-112 ms) backs off from 1 s to 5 s after
//     three attempts per candidate; a re-evaluation after the UE pass no
//     longer counts the same chain sample twice.
//
// v1.1.1 (player identity fix; everything else as v1.1.0):
//   * The actor GUID is read at actor+0x30, the field the game's own GUID
//     accessor reads (actor interface at +0x10, vtable slot +0x38 ->
//     0xE4D660 `mov eax,[rcx+20h]`). v1.1.0 read +0x10C, which is Eve's
//     per-type id (100), not her GUID.
//   * Eve's FSB actor is identified through the local client's current-target
//     chain and a read-only mirror of ApplyStatExecute's own GUID lookup
//     (god_identity.cpp), with nine independent signals required before God
//     may arm. The pawn "Property"/"ActorProperty" reflection and the pawn
//     pointer scan (never able to reach the actor on this build) are removed,
//     as are every heuristic "learn from a hit" path: the only actor God ever
//     protects or writes is the verified one.
//   * FindAllOf runs only while an identity is being verified (at most once
//     per second), no longer every second while God is on (it cost 70-110 ms
//     of GameThread time per call).
//   * Per-step identity diagnostics are appended to the heartbeat.
//
// v1.1.0 (ported from Dev v1.0.36):
//   * Exact executable gate (TimeDateStamp, SizeOfImage, machine, exe file
//     size) and byte validation of EVERY hook site, semantic anchor and
//     TaskGraph signature before any VirtualProtect or code write. A mismatch
//     anywhere installs nothing (god_sites.cpp).
//   * All UObject/reflection work (FindAllOf, reflected property reads) and
//     every maintenance stat write run inside a certified TaskGraph
//     GameThread callback (the SBMovementNative v1.3.6 pattern). The UE4SS
//     worker only does file I/O, atomics and task submission.
//   * The native_item_request Live Add bridge is removed.
//   * Stat writes go only to the instruction-proven Stat[] slots of an actor
//     the game itself passed in, or of the verified player actor after its
//     identity is re-proven on the same GameThread tick.
//   * Panel-pointer hints in native_god_state.txt (actorptr/bagptr/
//     playerguid) are reported but never dereferenced.
//   * The DLL is pinned; on unload the hooks stay installed in pass-through
//     mode instead of rewriting live code and freeing trampolines.

#include "god_hook.hpp"
#include "god_gate.hpp"
#include "god_identity.hpp"
#include "god_sites.hpp"
#include "god_state.hpp"
#include "ue4ss_minimal.hpp"

#include <algorithm>
#include <array>
#include <atomic>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <iterator>
#include <string>
#include <vector>

#include <windows.h>

#include <intrin.h>

#include "sbcore/dispatch.hpp"
#include "sbcore/fault.hpp"
#include "sbcore/gate.hpp"
#include "sbcore/memory.hpp"
#include "sbcore/module.hpp"
#include "sbcore/paths.hpp"
#include "sbcore/status.hpp"
#include "sbcore/version.hpp"

static_assert(sbgod::kActorGuidOffset == sbgod::identity::kActorGuidOffset);
static_assert(sbgod::kActorTableIdOffset == sbgod::identity::kActorTableIdOffset);
static_assert(sbgod::kStatArrayOffset == sbgod::identity::kStatArrayOffset);
static_assert(sbgod::identity::kStatHpOffset == sbgod::kStatArrayOffset + sbgod::kStatHp * 4);
static_assert(sbgod::identity::kStatMaxHpOffset == sbgod::kStatArrayOffset + sbgod::kStatMaxHp * 4);
static_assert(sbgod::identity::kStatShieldOffset == sbgod::kStatArrayOffset + sbgod::kStatShield * 4);

namespace
{
    namespace sites = sbgod::sites;
    namespace id = sbgod::identity;

    using SetActorStatFn = void(__fastcall*)(void* actor, int stat_type, float value, void* unused_r8, std::uint8_t flag);
    using ActorApplyStatExecuteFn = void(__fastcall*)(void* apply_stat);
    using ActorDeadExecuteFn = void(__fastcall*)(void* dead_command);
    using ActorDeathTransitionFn = bool(__fastcall*)(
        void* actor,
        int cause_actor_guid,
        int hit_skill_id,
        int effect_id,
        void* output_actor,
        int cause_actor_runtime_id,
        void* output_data,
        std::uint8_t do_not_reset_sp_exp,
        void* optional_context,
        std::uint8_t force_dead,
        std::uint8_t local_request);
    using ActorStateChangeFn = void(__fastcall*)(void* actor, int state_tag, std::uint8_t add, std::uint8_t clear);
    // v1.3.1: 0x1A64CE0. rcx = FSB actor, edx = stat, r8 = ctx, xmm3 = diff,
    // [rsp+28h] u8 (read at [rbp+6Fh]), [rsp+30h] u8 ([rbp+77h]), [rsp+38h]
    // i32 ([rbp+7Fh]) at entry; returns true when Stat[] changed.
    using ApplyStatDiffFn = bool(__fastcall*)(void* actor, int stat_type, void* context, float diff,
                                              std::uint8_t arg5, std::uint8_t arg6, int arg7);

    // Telemetry only: the id that v1.0.x read at +0x10C of the actor passed
                                                                             
    // it is known to be a per-type id, not a GUID; kept for the predicate mask.
    constexpr std::uint32_t kPlayerDeathProxyRuntimeId = 20010u;

    // ---- Files (P1: resolved from this DLL's own location at install) -------
    //   Mods\SBCheatGUI\native_god_state.txt   panel -> native (desired state)
    //   Mods\SBCheatGUI\native_heartbeat.txt   native -> panel (temp: native_heartbeat.tmp)
    //   Mods\SBGodNative\native_hook.log       install + periodic debug log
    //   Mods\SBGodNative\sbcore_faults.log     A9 breadcrumbs (append-only)
    constexpr wchar_t kStateFileName[] = L"native_god_state.txt";
    constexpr wchar_t kHeartbeatFileName[] = L"native_heartbeat.txt";
    constexpr wchar_t kHeartbeatTempFileName[] = L"native_heartbeat.tmp";
    constexpr wchar_t kHookLogFileName[] = L"native_hook.log";
    constexpr wchar_t kFaultLogFileName[] = L"sbcore_faults.log";
    constexpr char kModuleName[] = "SBGodNative";

    sbcore::paths::ModulePaths g_paths{};         // written once by install() before g_paths_ready
    std::atomic<bool> g_paths_ready{false};
    sbcore::paths::Error g_paths_error{sbcore::paths::Error::None};
    std::wstring g_state_path;
    std::wstring g_log_path;
    sbcore::status::StableReader g_state_reader{}; // worker (and install) only
    std::atomic<sbcore::status::ReadResult> g_state_read_result{sbcore::status::ReadResult::Missing};

    // ---- Cadences ---------------------------------------------------------
    constexpr std::uint64_t kStatePollMs = 100;        // native_god_state.txt poll (v1.0.36: 15 ticks)
    constexpr std::uint64_t kGameThreadPeriodMs = 50;  // GameThread identity + maintenance while God is wanted
    constexpr std::uint64_t kHeartbeatPeriodMs = 500;  // heartbeat check; published when changed
    constexpr std::uint64_t kHeartbeatBeatMs = 1000;   // A12 liveness beat (panel max age 15 s)
    constexpr std::uint64_t kStateGraceMs = 500;       // StableReader grace for the panel's replace window
    constexpr int kLogEveryStatePolls = 120;           // ~12 s, as v1.0.36

    // ---- Self-check thresholds -------------------------------------------
    constexpr std::uint64_t kHookMatchesToPass = 3;
    constexpr std::uint64_t kHookMismatchesToFail = 3;

    // ---- Install / build status (written once by install) ----------------
    std::atomic<bool> g_install_done{false};
    std::atomic<bool> g_module_pinned{false};
    std::atomic<bool> g_build_ok{false};
    std::atomic<std::uint32_t> g_build_timestamp{0};
    std::atomic<std::uint32_t> g_build_size_of_image{0};
    std::atomic<std::uint64_t> g_exe_file_size{0};
    std::atomic<bool> g_exe_file_size_ok{false};
    std::atomic<bool> g_validation_all_ok{false};
    std::atomic<bool> g_site_ok[sites::kSiteCount]{};
    std::atomic<bool> g_anchor_ok[sites::kAnchorCount]{};
    std::atomic<bool> g_taskgraph_ok{false};
    std::atomic<bool> g_hooks_installed{false};
    char g_install_error[64] = "not-installed";
    // sbcore gate result (written once by install before g_install_done).
    std::atomic<sbcore::gate::Reason> g_gate_reason{sbcore::gate::Reason::None};
    std::atomic<bool> g_gate_ran{false};
    char g_gate_failed[96] = "none";
    std::atomic<std::uint32_t> g_gate_checks_passed{0};

    sites::PatchState g_patch{};
    std::atomic<void*> g_original_slots[sites::kSiteCount]{};

    std::byte* g_image{}; // the gate-certified exe image (identity chain reads)

    std::atomic<std::uint64_t> g_ret_dead_network{0};
    std::atomic<std::uint64_t> g_ret_dead_local{0};
    std::atomic<std::uint64_t> g_ret_state_scoped{0};
    std::atomic<std::uint64_t> g_ret_apply_setter{0};
    std::atomic<std::uint64_t> g_ret_diff_server{0}; // v1.3.1: ApplyStatDiff called by the server apply (the hit)
    std::atomic<std::uint64_t> g_ret_diff_echo{0};   // v1.3.1: ApplyStatDiff called by ApplyStatExecute (the replay)

    template <class Fn>
    Fn original(sites::SiteId id)
    {
        return reinterpret_cast<Fn>(g_original_slots[id].load(std::memory_order_acquire));
    }

    // ---- Lifecycle / dispatch state ---------------------------------------
    // The TaskGraph dispatch itself (lease, sequence, poison, counters) is
    // sbcore::dispatch; its counters feed the v1.1.x heartbeat keys.
    std::atomic<bool> g_running{false};
    std::atomic<bool> g_shutting_down{false};
    std::atomic<std::uint32_t> g_worker_thread_id{0};
    std::atomic<std::uint64_t> g_probe_misses{0}; // handled AVs on probed bytes (not latched)
    std::atomic<std::uint64_t> g_gt_last_us{0};
    std::atomic<std::uint64_t> g_gt_max_us{0};
    std::atomic<std::uint64_t> g_identity_count{0};    // UE (FindAllOf) passes
    std::atomic<std::uint64_t> g_identity_last_us{0};
    std::atomic<std::uint64_t> g_identity_max_us{0};
    std::atomic<bool> g_identity_pawn_found{false};

    // ---- Desired configuration (worker-parsed) ----------------------------
    std::atomic<bool> g_desired_god{false};
    std::atomic<bool> g_state_file_ok{false};
    std::atomic<std::uint32_t> g_state_playerguid{0};
    std::atomic<std::uint64_t> g_state_actorptr{0};
    std::atomic<std::uint64_t> g_state_bagptr{0};
    std::atomic<std::uint64_t> g_config_revision{0};
    std::uint64_t g_last_dispatched_revision{0}; // worker-owned
    std::uint64_t g_last_state_poll_tick{0};     // worker-owned
    std::uint64_t g_last_dispatch_tick{0};       // worker-owned
    std::uint64_t g_last_heartbeat_tick{0};      // worker-owned
    int g_log_counter{0};                        // worker-owned

    // GameThread-owned.
    bool gt_prev_armed{false};
    id::Tracker gt_tracker{};
    id::UeSnapshot gt_ue{};
    // v1.3.0 first-hit watch: the verified actor's pool as the previous
    // maintenance tick left it (TickDrop detection).
    bool gt_fh_prev_valid{false};
    float gt_fh_prev_hp{0.0f};
    float gt_fh_prev_shield{0.0f};
    float gt_fh_prev_max_hp{0.0f};

    // ---- v1.3.0 fast arm / first-hit watch (published by the GameThread) ----
    id::FirstHitWatch g_first_hit{};                               // hooks note(), GameThread arm()/disarm()
    std::atomic<id::ArmPath> g_arm_path{id::ArmPath::None};        // path of the current verified identity
    std::atomic<id::ArmPath> g_last_arm_path{id::ArmPath::None};   // path of the last arm
    std::atomic<id::DirectProof> g_direct_proof{id::DirectProof::NotChecked};
    std::atomic<std::uint64_t> g_arm_after_candidate_ms{0};        // last arm: ms since the candidate appeared
    std::atomic<std::uint64_t> g_fast_arms{0};
    std::atomic<std::uint64_t> g_hook_arms{0};
    std::atomic<bool> g_ue_class_ok{false};
    std::atomic<bool> g_ue_netguid_read{false};
    std::atomic<std::int32_t> g_ue_player_id{0};       // reflected PlayerState.PlayerId (0 = unread/absent)
    std::atomic<bool> g_ue_player_id_at_offset{false}; // reflected address == PlayerState+0x2CC
    std::atomic<std::int32_t> g_id_player_id{0};       // E+0x4A0 of the current chain sample
    std::atomic<std::uint32_t> g_apply_leak_last_guid{0}; // command GUID of the last ApplyLeak
    // Shield-only drops of the verified actor while armed (telemetry; HP is
    // what "damage reached Eve" means, the shield is restored as before).
    std::atomic<std::uint64_t> g_shield_drops{0};
    // TickDrop is judged only this long after an arm: a direct HP write while
    // the freshly loaded actor settles is not a hit. Hits inside the window
    // are still caught by ApplyLeak / LethalRestore / DeathCommand.
    constexpr std::uint64_t kTickDropGraceMs = 3000;
    std::uint64_t gt_armed_ms{0}; // GameThread-owned

    // ---- v1.3.1 (hooks count with relaxed atomics; the GameThread publishes) ----
    std::atomic<std::uint64_t> g_diff_blocks{0};       // F1: negative vital diffs withheld from the armed Eve
    std::atomic<std::uint64_t> g_diff_echo_blocks{0};  //     ... of them from ApplyStatExecute's replay call
    std::atomic<std::uint64_t> g_prearm_blocks{0};     // F2: withheld from the ready candidate (S9 on that call)
    std::atomic<std::uint64_t> g_unarmed_hits{0};      // server-side hits on the candidate while God on but not armed
    std::atomic<std::uint64_t> g_apply_drops{0};       // passed-through ApplyStat commands that lowered Eve's HP (telemetry)
    std::atomic<std::uint64_t> g_resume_arms{0};
    std::atomic<std::uint64_t> g_ready_actor{0};       // F2: (E, G) with S1..S8 proven, S9 missing (0 = none)
    std::atomic<std::uint32_t> g_ready_guid{0};
    std::atomic<std::uint32_t> g_eventor_guid{0};      // FSBGameWorld.EventorActorGUID of the last chain sample
    std::atomic<bool> g_v131_sites_ok{false};          // the ApplyStatDiff site + the four v1.3.1 anchors validated
    // GameThread-owned: the last verdict said "ready" for this pair.
    bool gt_ready_pending{false};
    std::uint64_t gt_ready_actor{0};
    std::uint32_t gt_ready_guid{0};
    std::uint64_t gt_logged_leaks{0};
    std::uint64_t gt_armed_actor{0}; // the actor/GUID of the current arm (for the disarm event)
    std::uint32_t gt_armed_guid{0};

    // ---- Implementation beta-burst r1: Unlimited Beta / Burst energy ----
    // Offline tested only: not built into a DLL, not installed, not live-tested.
    //
    // Two switches of their own, independent of God Mode: the panel lines
    // betalive= and burstlive= in native_god_state.txt (a missing line is OFF).
    // Nothing is written to the game and no save is touched. The feature only
    // answers, or changes one argument of, a call the game itself makes to
    // ApplyStatDiff 0x1A64CE0 for the verified Eve. Exe 573AAFF1...545C:
    //   * Beta is Stat[14] (current, actor+0x150) and Stat[15] (max, +0x154);
    //     Burst is Stat[18] (+0x160) and Stat[19] (+0x164). A Burst change does
    //     nothing unless int(Stat[116], +0x2E8, UnlockBurstGauge) >= 1.
    //   * A skill spends through the server-side apply 0x1BA8720 with the
    //     negated cost (0x1BF5989..0x1BF5ACB) and can only start while
    //     cost <= current (0x1C770D3 Burst, 0x1C77133 Beta).
    //   * Never drains: a finite negative change of that gauge is answered
    //     "no change" without calling the game. That is the function's own
    //     result at 0x1A65A4A and exactly what the game does for Beta while the
    //     actor has state 61 InfiniteBetaGaugeEnergy (0x1A6535B..0x1A6536F).
    //     The server apply then leaves at 0x1BA9683 (anchor
    //     ApplyStatDiffServerResult), as it does for God's F1 block.
    //   * Fill: when the game itself adds energy to that gauge (a hit, a parry,
    //     the restore after a load, an item) the amount is raised to
    //     max - current. The game clamps to max itself (0x1A653FA / 0x1A655DE)
    //     and sends its own stat-change event with that amount. The first gain
    //     fills the bar; after that it never drains, so every skill stays
    //     usable (the cost check reads the same float).
    //   * Optional and OFF unless the panel writes energytopup=1: while a bar
    //     is below max, the GameThread asks the game's own ApplyStatDiff (the
    //     trampoline, never this hook) for max - current with the argument
    //     pattern of the game's own restore-after-load (0x1BB5BE2..0x1BB5C30
    //     through 0x1BA87ED..0x1BA881E: context 0, both flags 0, id 0), and
    //     only on the thread on which the game was seen making its own
    //     server-side stat calls for this Eve. This is the one call the game
                                                                         
    // Who is Eve: the nine-signal identity God already uses, with pointer, GUID
    // and type id re-read on every call (is_confirmed_player_actor). The
    // GameThread identity tick now also runs while an energy switch is on. God
    // still arms only when God is wanted, and every HP / Shield decision still
    // needs god_live(): with God off no damage is ever withheld.
    // Only the proven server-side caller is touched (return address 0x1BA8823).
    // ApplyStatExecute's replay (0x1B1F826) runs only when the cached net mode
    // is 3 = client (0x1B1F7F3 `cmp eax,3 / jne`) and is left alone.
    constexpr int kStatBetaGauge = 14;
    constexpr int kStatBurstGauge = 18;
    constexpr std::uint32_t kBetaNowOffset = 0x150;
    constexpr std::uint32_t kBetaMaxOffset = 0x154;
    constexpr std::uint32_t kBurstNowOffset = 0x160;
    constexpr std::uint32_t kBurstMaxOffset = 0x164;
    constexpr std::uint32_t kBurstUnlockOffset = 0x2E8;
    static_assert(kBetaNowOffset == sbgod::kStatArrayOffset + kStatBetaGauge * 4);
    static_assert(kBetaMaxOffset == sbgod::kStatArrayOffset + (kStatBetaGauge + 1) * 4);
    static_assert(kBurstNowOffset == sbgod::kStatArrayOffset + kStatBurstGauge * 4);
    static_assert(kBurstMaxOffset == sbgod::kStatArrayOffset + (kStatBurstGauge + 1) * 4);
    static_assert(kBurstUnlockOffset == sbgod::kStatArrayOffset + 116 * 4);
    // A pool is believed only up to this max (shipped base max: Beta 1000,
    // Burst 1600). It also keeps every raised amount far below 2^31, where the
    // game's own cvttss2si clamp would turn a sum into 0.
    constexpr float kMaxEnergyPool = 100000.0f;
    constexpr char kEnergyId[] = "beta-burst-r1";
    constexpr std::uint64_t kEnergyTopupPeriodMs = 1000; // optional top-up: at most one call per gauge per second
    constexpr std::uint32_t kEnergyTopupGiveUp = 3;      // ... and it stops after three calls in a row that did not fill

    enum EnergyGauge : std::size_t { kEnergyBeta = 0, kEnergyBurst = 1, kEnergyGaugeCount = 2 };

    // Desired configuration (worker-parsed, native_god_state.txt).
    std::atomic<bool> g_desired_beta{false};
    std::atomic<bool> g_desired_burst{false};
    std::atomic<bool> g_desired_topup{false};
    // install(): every energy byte window matched this exe. A mismatch never
    // stops God Mode; only the energy switches stay off ("not_supported").
    std::atomic<bool> g_energy_sites_ok{false};
    char g_energy_site_error[48] = "not_checked"; // written once by install() before g_install_done
    std::atomic<bool> g_energy_live{false};       // armed by the GameThread; see energy_live()
    std::atomic<std::uint32_t> g_gt_thread_id{0}; // the thread sbcore::dispatch runs the callback on
    std::atomic<std::uint64_t> g_energy_arms{0};
    std::atomic<std::uint64_t> g_energy_spend_blocks[kEnergyGaugeCount]{}; // negative changes answered "no change"
    std::atomic<std::uint64_t> g_energy_fills[kEnergyGaugeCount]{};        // the game's own gains raised to max - current
    std::atomic<std::uint64_t> g_energy_topups[kEnergyGaugeCount]{};       // optional GameThread top-up calls
    std::atomic<std::uint64_t> g_energy_topup_noeffect{0};                 // ... that did not leave the bar full
    std::atomic<std::uint64_t> g_energy_pool_refused{0};   // unreadable / unbelievable pool, or Burst locked: passed through
    std::atomic<std::uint64_t> g_energy_other_caller{0};   // a call that did not come from the server-side apply: passed through
    std::atomic<std::uint64_t> g_energy_setter_lowered{0}; // telemetry: SetActorStat lowered a switched-on gauge (never withheld)
    // Where the game makes its own server-side stat calls for the verified Eve
    // (any stat) while an energy switch is armed: on the GameThread, or not.
    std::atomic<std::uint64_t> g_energy_calls_gt{0};
    std::atomic<std::uint64_t> g_energy_calls_other{0};
    // The verified Eve's own numbers as the last GameThread tick read them
    // (-1 = not read): Beta now / max, Burst now / max, Burst unlock.
    enum EnergyPoolSlot : std::size_t { kPoolBetaNow, kPoolBetaMax, kPoolBurstNow, kPoolBurstMax, kPoolBurstUnlock, kPoolSlotCount };
    std::atomic<std::int32_t> g_energy_pool[kPoolSlotCount]{-1, -1, -1, -1, -1};
    // GameThread-owned.
    bool gt_prev_desired_god{false};
    bool gt_prev_energy_armed{false};
    bool gt_energy_topup_tried[kEnergyGaugeCount]{};
    std::uint64_t gt_energy_topup_ms[kEnergyGaugeCount]{};
    std::uint32_t gt_energy_topup_misses[kEnergyGaugeCount]{};

    struct EnergySwitches
    {
        bool beta{};
        bool burst{};
        bool topup{};
    };

    // Pure (no I/O, no globals). The energy lines of native_god_state.txt:
    //   betalive=1    burstlive=1    energytopup=1
    // Strict on purpose, because OFF is the safe answer: a key counts only at
    // the start of a line, ON is exactly the value "1", and anything else, a
    // missing line or a key that appears more than once is OFF. A CR before
    // the LF is accepted and a Ctrl-Z ends the input, as in the text-mode
    // parser of the other four keys (god_state.cpp), which is untouched.
    EnergySwitches parse_energy_switches(std::string_view raw)
    {
        static constexpr std::string_view keys[3]{"betalive=", "burstlive=", "energytopup="};
        bool on[3]{};
        int seen[3]{};
        std::size_t pos = 0;
        while (pos < raw.size())
        {
            std::size_t end = pos;
            while (end < raw.size() && raw[end] != '\n' && raw[end] != '\x1A') ++end;
            std::string_view line = raw.substr(pos, end - pos);
            if (!line.empty() && line.back() == '\r') line.remove_suffix(1);
            for (int i = 0; i < 3; ++i)
            {
                if (line.substr(0, keys[i].size()) != keys[i]) continue;
                ++seen[i];
                on[i] = line.substr(keys[i].size()) == "1";
            }
            if (end < raw.size() && raw[end] == '\x1A') break;
            pos = end + 1;
        }
        EnergySwitches out{};
        out.beta = seen[0] == 1 && on[0];
        out.burst = seen[1] == 1 && on[1];
        out.topup = seen[2] == 1 && on[2];
        return out;
    }

    // v1.3.0: one damage event for the first-hit watch (any thread; atomics only).
    void note_hit_event(id::HitEvent event)
    {
        g_first_hit.note(event, GetTickCount64());
    }

    // ---- v1.3.1 native_hook.log events (F5) ------------------------------------
    // Producer: the GameThread only (single producer). Consumer: the worker
    // only (drain_log_events). A full ring drops the newest event and counts it.
    enum class LogKind : std::uint32_t { Candidate, Armed, Disarmed, Leak, EnergyArmed, EnergyDisarmed }; // last two: beta-burst r1
    struct LogEvent
    {
        std::uint64_t filetime; // UTC FILETIME at the event
        LogKind kind;
        std::uint32_t guid;
        std::uint64_t actor;
        std::uint64_t a;
        std::uint64_t b;
        std::uint64_t c;
        std::uint32_t d;
        std::uint32_t e;
    };
    constexpr std::uint32_t kLogRing = 64;
    LogEvent g_log_ring[kLogRing]{};
    std::atomic<std::uint32_t> g_log_head{0}; // next slot the GameThread writes
    std::atomic<std::uint32_t> g_log_tail{0}; // next slot the worker reads
    std::atomic<std::uint64_t> g_log_dropped{0};

    std::uint64_t filetime_now()
    {
        FILETIME ft{};
        GetSystemTimeAsFileTime(&ft);
        return (static_cast<std::uint64_t>(ft.dwHighDateTime) << 32) | ft.dwLowDateTime;
    }

    void gt_log_event(LogKind kind, std::uint64_t actor, std::uint32_t guid, std::uint64_t a, std::uint64_t b,
                      std::uint64_t c, std::uint32_t d, std::uint32_t e)
    {
        const auto head = g_log_head.load(std::memory_order_relaxed);
        const auto tail = g_log_tail.load(std::memory_order_acquire);
        if (head - tail >= kLogRing)
        {
            g_log_dropped.fetch_add(1, std::memory_order_relaxed);
            return;
        }
        g_log_ring[head % kLogRing] = LogEvent{filetime_now(), kind, guid, actor, a, b, c, d, e};
        g_log_head.store(head + 1, std::memory_order_release);
    }

    // ---- God runtime state --------------------------------------------------
    std::atomic<bool> g_god_live{false}; // armed by the GameThread; see god_live()

    bool dispatch_poisoned()
    {
        return sbcore::dispatch::counters().poisoned;
    }

    // Effective protection, read by the hooks: armed AND no fault latched in
    // this process (A9: after any sbcore native faulted, God makes no game
    // write of any kind and every hook passes the call through unchanged)
    // AND the GameThread dispatch is not poisoned. v1.2.1: v1.1.2 cleared
    // g_god_live inside the TaskGraph callback the moment the GameThread
    // certification failed; sbcore's dispatcher only poisons itself there, so
    // the hooks now read the poison directly instead of protecting until the
    // next worker tick. Atomics only: safe on every game thread.
    bool god_live(std::memory_order order = std::memory_order_acquire)
    {
        return g_god_live.load(order) && !sbcore::fault::writes_blocked_fast() && !dispatch_poisoned();
    }

    // The GameThread dispatch is stopped for the rest of this process: the
    // dispatcher is poisoned, or a fault is latched (sbcore refuses to submit
    // and skips every queued callback). Reported as dispatch_poisoned so the
    // panel's v1.1.x contract reads a latched God as "couldn't start safely".
    bool dispatch_stopped()
    {
        return dispatch_poisoned() || sbcore::fault::writes_blocked();
    }

    // Verified identity (written only by the GameThread identity pass).
    std::atomic<bool> g_identity_verified{false};
    std::atomic<std::uint32_t> g_player_guid{0};        // heartbeat "guid": the verified actor GUID (+0x30)
    std::atomic<std::uint32_t> g_player_combat_guid{0}; // the ApplyStat stream GUID == g_player_guid
    std::atomic<std::uint64_t> g_live_combat_actor{0};
    std::atomic<std::uint64_t> g_combat_guid_binds{0};  // number of identity verifications
    thread_local bool g_in_player_execute_apply = false;
    thread_local std::uint32_t tl_apply_cmd_guid = 0;
    thread_local std::uint32_t tl_dead_cmd_guid = 0;
    // Test-only provenance: plugin TLS/atomics; no game-memory writes.
    thread_local std::uint64_t tl_death_probe_sequence = 0;

    std::atomic<std::uint64_t> g_actor_ptr{0}; // controller pawn (GameThread UE pass only; telemetry)
    std::atomic<std::uint64_t> g_bag_ptr{0};   // the verified FSB actor base (telemetry)
    std::atomic<void*> g_learned_actor{nullptr};
    std::atomic<std::uint32_t> g_learned_guid{0};

    std::atomic<std::uint64_t> g_blocks{0};
    std::atomic<std::uint64_t> g_hits{0};
    std::atomic<std::uint64_t> g_protect_checks{0};
    std::atomic<std::uint64_t> g_execute_hits{0};
    std::atomic<std::uint64_t> g_execute_blocks{0};
    std::atomic<std::uint64_t> g_fatal_zero_blocks{0};
    std::atomic<std::uint64_t> g_fatal_branch_skips{0};
    std::atomic<std::uint64_t> g_fatal_chain_blocks{0};
    std::atomic<std::uint64_t> g_fatal_guard_actor{0};
    std::atomic<std::uint32_t> g_fatal_guard_tick{0};
    std::atomic<std::uint64_t> g_actor_dead_hits{0};
    std::atomic<std::uint64_t> g_actor_dead_blocks{0};
    std::atomic<std::uint64_t> g_actor_dead_last_actor{0};
    std::atomic<std::uint32_t> g_actor_dead_last_guid{0};
    std::atomic<std::uint64_t> g_actor_dead_last_return_address{0};
    std::atomic<std::uint32_t> g_actor_dead_last_tick{0};
    std::atomic<std::uint32_t> g_actor_dead_after_player_execute_ms{0xFFFFFFFFu};
    std::atomic<std::uint32_t> g_actor_dead_after_setter_ms{0xFFFFFFFFu};
    std::atomic<std::uint32_t> g_actor_dead_predicate_mask{0};
    // Implementation r2: GUID of the protected Eve whose last accepted
    // death was a kind-1 death with HP left (fall, kill volume, laser: let
    // through by design). Written by hook_actor_death_transition, consumed
    // by the Dead command that follows (hook_actor_dead_execute). 0 = none.
    std::atomic<std::uint32_t> g_design_death_guid{0};
    std::atomic<std::uint32_t> g_actor_dead_world_hits{0};
    std::atomic<std::uint64_t> g_pending_death_actor{0};
    std::atomic<std::uint32_t> g_pending_death_tick{0};

    std::atomic<std::uint64_t> g_state20_hits{0};
    std::atomic<std::uint64_t> g_state20_add_hits{0};
    std::atomic<std::uint64_t> g_state20_remove_hits{0};
    std::atomic<std::uint64_t> g_state20_clear_hits{0};
    std::atomic<std::uint64_t> g_state20_last_actor{0};
    std::atomic<std::uint32_t> g_state20_last_guid_10c{0};
    std::atomic<std::uint32_t> g_state20_last_guid_10{0};
    std::atomic<std::uint64_t> g_state20_last_return_address{0};
    std::atomic<std::uint32_t> g_state20_last_tick{0};
    std::atomic<std::uint32_t> g_state20_last_after_player_execute_ms{0xFFFFFFFFu};
    std::atomic<std::uint8_t> g_state20_last_add{0};
    std::atomic<std::uint8_t> g_state20_last_clear{0};
    std::atomic<float> g_state20_last_hp{0.0f};
    std::atomic<float> g_state20_last_max_hp{0.0f};
    std::atomic<float> g_state20_last_shield{0.0f};
    std::atomic<std::uint64_t> g_state20_add_actor{0};
    std::atomic<std::uint32_t> g_state20_add_guid_10c{0};
    std::atomic<std::uint64_t> g_state20_add_return_address{0};
    std::atomic<std::uint32_t> g_state20_add_tick{0};
    std::atomic<std::uint32_t> g_state20_add_after_player_execute_ms{0xFFFFFFFFu};
    std::atomic<float> g_state20_add_hp{0.0f};
    std::atomic<float> g_state20_add_max_hp{0.0f};
    std::atomic<float> g_state20_add_shield{0.0f};
    std::atomic<std::uint64_t> g_state20_lethal_restores{0};
    std::atomic<std::uint64_t> g_state20_restore_actor{0};
    std::atomic<std::uint32_t> g_state20_restore_tick{0};
    std::atomic<float> g_state20_restore_hp{0.0f};
    std::atomic<float> g_state20_restore_shield{0.0f};
    std::atomic<std::uint8_t> g_state20_restore_pawn{0};

    // Hook callbacks only publish primitive telemetry. File I/O stays on the
    // UE4SS worker so shutdown never races a callback writer.
    std::atomic<std::uint64_t> g_setter_vital_hits{0};
    std::atomic<std::uint64_t> g_setter_vital_negative_hits{0};
    std::atomic<std::uint64_t> g_setter_vital_last_actor{0};
    std::atomic<int> g_setter_vital_last_stat{-1};
    std::atomic<float> g_setter_vital_last_value{0.0f};
    std::atomic<int> g_setter_vital_guid_offset{-1};
    std::atomic<float> g_setter_vital_actor_hp{0.0f};
    std::atomic<float> g_setter_vital_actor_max_hp{0.0f};
    std::atomic<float> g_setter_vital_actor_shield{0.0f};
    std::atomic<std::uint32_t> g_setter_vital_tick{0};
    std::atomic<std::uint32_t> g_setter_after_player_execute_ms{0xFFFFFFFFu};
    std::atomic<std::uint64_t> g_setter_vital_return_address{0};
    std::atomic<std::uint64_t> g_guid_candidate_hits{0};
    std::atomic<std::uint64_t> g_guid_candidate_actor{0};
    std::atomic<int> g_guid_candidate_offset{-1};
    std::atomic<int> g_guid_candidate_stat{-1};
    std::atomic<float> g_guid_candidate_value{0.0f};

    std::atomic<std::uint64_t> g_execute_vital_hits{0};
    std::atomic<std::uint64_t> g_execute_player_vital_hits{0};
    std::atomic<std::uint32_t> g_execute_vital_last_guid{0};
    std::atomic<int> g_execute_vital_last_stat{-1};
    std::atomic<float> g_execute_vital_last_diff{0.0f};
    std::atomic<float> g_execute_vital_last_result{0.0f};
    std::atomic<std::uint32_t> g_last_player_execute_tick{0};

    std::atomic<std::uint64_t> g_dead_execute_hits{0};
    std::atomic<std::uint64_t> g_dead_execute_player_candidates{0};
    std::atomic<std::uint32_t> g_dead_execute_last_guid{0};
    std::atomic<int> g_dead_execute_last_cause_guid{0};
    std::atomic<int> g_dead_execute_last_skill_id{0};
    std::atomic<int> g_dead_execute_last_effect_id{0};
    std::atomic<int> g_dead_execute_last_cause_runtime_id{0};
    std::atomic<std::uint8_t> g_dead_execute_last_force_dead{0};
    std::atomic<std::uint8_t> g_dead_execute_last_local_request{0};
    std::atomic<std::uint32_t> g_dead_execute_last_tick{0};
    std::atomic<std::uint32_t> g_dead_execute_after_player_execute_ms{0xFFFFFFFFu};
    std::atomic<std::uint32_t> g_dead_execute_predicate_mask{0};

    std::atomic<int> g_last_stat{-1};
    std::atomic<std::uint64_t> g_last_actor{0};
    std::atomic<std::uint64_t> g_maintain_ticks{0};
    std::atomic<std::uint64_t> g_maintain_restores{0};
    std::atomic<std::uint64_t> g_maintain_verify_rejects{0};
    std::atomic<float> g_hp_floor{0.0f};
    std::atomic<float> g_sim_hp_floor{0.0f};
    std::atomic<float> g_sim_shield_floor{0.0f};
    std::atomic<float> g_shield_now_telemetry{0.0f};

    std::atomic<std::uint64_t> g_player_controller_ptr{0};
    std::atomic<std::uint64_t> g_player_state_ptr{0};

    // ---- Runtime self-check (read-only) -----------------------------------
    // Hook samples: at the two call sites whose callee receives the actor the
    // game looked up by the command's ActorGUID, the uint32 at
    // actor+kActorGuidOffset (0x30) must equal that GUID. These sites run
    // only on a stat mismatch / a death, so they are corroboration, not the
    // primary proof; the primary proof is the identity chain.
    std::atomic<std::uint64_t> g_sc_hook_matches{0};
    std::atomic<std::uint64_t> g_sc_hook_mismatches{0};
    std::atomic<std::uint32_t> g_sc_hook_last_source{0}; // 1 apply->setter, 2 dead->transition
    std::atomic<std::uint32_t> g_sc_hook_last_expected{0};
    std::atomic<std::uint32_t> g_sc_hook_last_observed{0};
    std::atomic<bool> g_sc_fail_sticky{false};
    std::atomic<bool> g_sc_pass_latched{false};

    // v1.0.36-era "reflect" keys now describe the identity chain.
    enum class ReflectStatus : std::uint32_t { None, Pass, GuidMismatch, StatsImplausible, NoActor, NoPawn, Pending };
    enum class ReflectSource : std::uint32_t { None, LocalClientChain };
    std::atomic<ReflectStatus> g_sc_reflect_status{ReflectStatus::None};
    std::atomic<ReflectSource> g_sc_reflect_source{ReflectSource::None};
    std::atomic<std::uint64_t> g_sc_reflect_samples{0};
    std::atomic<std::uint64_t> g_sc_reflect_passes{0};
    std::atomic<std::uint64_t> g_sc_reflect_mismatches{0};

    // ---- v1.1.1 identity diagnostics (published by the GameThread) ---------
    std::atomic<id::Step> g_id_step{id::Step::NoImage};
    std::atomic<id::Reason> g_id_reason{id::Reason::GodOff};
    std::atomic<std::uint64_t> g_id_client{0};
    std::atomic<std::uint64_t> g_id_holder{0};
    std::atomic<std::int32_t> g_id_index{-1};
    std::atomic<std::int32_t> g_id_count{-1};
    std::atomic<std::uint64_t> g_id_actor{0};
    std::atomic<bool> g_id_vtables_ok{false};
    std::atomic<std::uint32_t> g_id_guid{0};
    std::atomic<std::uint64_t> g_id_mapped_actor{0};
    std::atomic<std::uint32_t> g_id_table_id{0};
    std::atomic<float> g_id_hp{0.0f};
    std::atomic<float> g_id_max_hp{0.0f};
    std::atomic<std::uint64_t> g_id_stable_ms{0};
    std::atomic<std::uint32_t> g_id_samples{0};
    std::atomic<std::uint64_t> g_id_candidate_changes{0};
    std::atomic<std::uint32_t> g_ue_controllers_found{0};
    std::atomic<std::uint32_t> g_ue_controllers_viable{0};
    std::atomic<bool> g_ue_pawn_acknowledged{false};
    std::atomic<std::uint64_t> g_ue_netguid_field{0};
    std::atomic<std::int32_t> g_ue_netguid_value{0};
    std::atomic<bool> g_ue_ran{false};
    std::atomic<bool> g_ue_exception{false};

    // Hook corroboration of the current candidate (published by the GameThread).
    std::atomic<std::uint64_t> g_cand_actor_pub{0};
    std::atomic<std::uint32_t> g_cand_guid_pub{0};
    std::atomic<std::uint64_t> g_cand_corroborations{0};
    std::atomic<std::uint64_t> g_hook_actor_last{0};
    std::atomic<std::uint32_t> g_hook_actor_guid_last{0};
    std::atomic<std::uint32_t> g_hook_actor_source_last{0}; // 1 SetActorStat, 2 ActorStateChange 0x20
    std::atomic<std::uint32_t> g_hook_apply_guid_last{0};

    enum class SelfCheck : std::uint32_t { Blocked, Pending, Pass, Fail };

    const char* reflect_status_name(ReflectStatus s)
    {
        switch (s)
        {
        case ReflectStatus::None: return "none";
        case ReflectStatus::Pass: return "pass";
        case ReflectStatus::GuidMismatch: return "guid_mismatch";
        case ReflectStatus::StatsImplausible: return "stats_implausible";
        case ReflectStatus::NoActor: return "no_actor";
        case ReflectStatus::NoPawn: return "no_pawn";
        case ReflectStatus::Pending: return "pending";
        }
        return "unknown";
    }

    const char* reflect_source_name(ReflectSource s)
    {
        switch (s)
        {
        case ReflectSource::None: return "none";
        case ReflectSource::LocalClientChain: return "local_client_chain";
        }
        return "unknown";
    }

    const char* selfcheck_name(SelfCheck s)
    {
        switch (s)
        {
        case SelfCheck::Blocked: return "blocked";
        case SelfCheck::Pending: return "pending";
        case SelfCheck::Pass: return "pass";
        case SelfCheck::Fail: return "fail";
        }
        return "unknown";
    }

    const char* hook_source_name(std::uint32_t source)
    {
        switch (source)
        {
        case 1: return "set_actor_stat";
        case 2: return "state20";
        default: return "none";
        }
    }

    // "chain:<step>" for a chain failure, otherwise the identity reason.
    void identity_reason_text(char* out, std::size_t size)
    {
        if (!g_hooks_installed.load(std::memory_order_acquire))
        {
            std::snprintf(out, size, "%s", id::reason_name(id::Reason::HooksNotInstalled));
            return;
        }
        if (!g_desired_god.load(std::memory_order_acquire))
        {
            std::snprintf(out, size, "%s", id::reason_name(id::Reason::GodOff));
            return;
        }
        if (sbcore::dispatch::counters().callback_count == 0)
        {
            std::snprintf(out, size, "waiting_for_game_thread");
            return;
        }
        const auto reason = g_id_reason.load(std::memory_order_acquire);
        if (reason == id::Reason::Chain)
            std::snprintf(out, size, "chain:%s", id::step_name(g_id_step.load(std::memory_order_acquire)));
        else
            std::snprintf(out, size, "%s", id::reason_name(reason));
    }

    // Pure evaluation over the counters; latches pass/fail.
    SelfCheck evaluate_selfcheck(const char** reason)
    {
        const char* why = "waiting_for_identity";
        SelfCheck result = SelfCheck::Pending;
        const auto matches = g_sc_hook_matches.load(std::memory_order_acquire);
        const auto mismatches = g_sc_hook_mismatches.load(std::memory_order_acquire);
        if (!g_hooks_installed.load(std::memory_order_acquire))
        {
            why = "hooks_not_installed";
            result = SelfCheck::Blocked;
        }
        else if (g_sc_fail_sticky.load(std::memory_order_acquire)
                 || (mismatches >= kHookMismatchesToFail && matches == 0))
        {
            g_sc_fail_sticky.store(true, std::memory_order_release);
            g_sc_pass_latched.store(false, std::memory_order_release);
            why = "hook_guid_offset_mismatch";
            result = SelfCheck::Fail;
        }
        else
        {
            // >= 3 exact matches with >= 90 % agreement independently proves
            // the +0x30 GUID offset at the command-lookup call sites.
            const bool hook_pass = matches >= kHookMatchesToPass && matches >= 9 * mismatches;
            const bool identity_now = g_identity_verified.load(std::memory_order_acquire);
            // Any hook mismatch with no match at all contradicts the offset:
            // never arm (or stay armed) on that evidence, even if latched.
            const bool contradicted = mismatches > 0 && matches == 0;
            if (!contradicted && (identity_now || hook_pass || g_sc_pass_latched.load(std::memory_order_acquire)))
            {
                g_sc_pass_latched.store(true, std::memory_order_release);
                why = identity_now ? "chain_identity_verified" : (hook_pass ? "hook_guid_offset_verified" : "latched");
                result = SelfCheck::Pass;
            }
            else if (mismatches > 0)
            {
                why = "hook_guid_offset_disputed";
            }
            else if (!g_desired_god.load(std::memory_order_acquire))
            {
                why = "god_off";
            }
        }
        if (reason) *reason = why;
        return result;
    }

    // ---- Safe memory helpers (A9 stage 1: SEH only around leaf probes) ------

    // An access violation / in-page error on the probed bytes is an expected
    // probe miss (a stale or foreign pointer): handled, the probe fails,
    // nothing is latched, as in v1.1.2. Any other exception inside a probe is
    // unexpected: sbcore::fault writes a breadcrumb and latches game writes
    // off for the process; under the enabled stage-1 policy it is still
    // handled here (the feature goes off, the game keeps running).
    //
    // v1.2.1: x64 raises #GP, not #PF, for a NON-CANONICAL address (e.g. a
    // garbage pointer 0xDEADBEEFDEADBEEF), and Windows reports that access
    // violation with the address 0xFFFFFFFFFFFFFFFF ("unknown"). v1.2.0's
    // range test rejected it and latched every sbcore native off for the
    // process on a plain bad-pointer read (measured: worker test E). A probe
    // whose own range is not canonical can only fault that way, so it is a
    // miss as well.
    constexpr std::uintptr_t kCanonicalUserTop = 0x00007FFFFFFFFFFFULL;
    constexpr std::uintptr_t kCanonicalKernelBottom = 0xFFFF800000000000ULL;
    constexpr std::uintptr_t kUnknownFaultAddress = ~static_cast<std::uintptr_t>(0);

    bool is_canonical(std::uintptr_t address)
    {
        return address <= kCanonicalUserTop || address >= kCanonicalKernelBottom;
    }

    bool range_is_canonical(std::uintptr_t low, std::size_t size)
    {
        if (size == 0) return is_canonical(low);
        const std::uintptr_t high = low + (size - 1);
        return high >= low && is_canonical(low) && is_canonical(high)
            && ((low <= kCanonicalUserTop) == (high <= kCanonicalUserTop));
    }

    int probe_filter(EXCEPTION_POINTERS* info, const void* begin, std::size_t size, const char* action)
    {
        const EXCEPTION_RECORD* record = info ? info->ExceptionRecord : nullptr;
        if (record
            && (record->ExceptionCode == EXCEPTION_ACCESS_VIOLATION || record->ExceptionCode == EXCEPTION_IN_PAGE_ERROR)
            && record->NumberParameters >= 2)
        {
            const auto target = static_cast<std::uintptr_t>(record->ExceptionInformation[1]);
            const auto low = reinterpret_cast<std::uintptr_t>(begin);
            const bool on_probed_bytes = target >= low && target - low < size;
            const bool non_canonical_probe = record->ExceptionCode == EXCEPTION_ACCESS_VIOLATION
                && target == kUnknownFaultAddress && !range_is_canonical(low, size);
            if (on_probed_bytes || non_canonical_probe)
            {
                g_probe_misses.fetch_add(1, std::memory_order_relaxed);
                return EXCEPTION_EXECUTE_HANDLER;
            }
        }
        return sbcore::fault::filter(info, action);
    }

    bool safe_read_float(const void* base, std::uint32_t byte_offset, float* out)
    {
        if (!base || !out) return false;
        const auto* at = reinterpret_cast<const std::uint8_t*>(base) + byte_offset;
        __try
        {
            *out = *reinterpret_cast<const float*>(at);
            return true;
        }
        __except (probe_filter(GetExceptionInformation(), at, sizeof(float), "god_probe_read"))
        {
            sbcore::fault::after_handler();
            return false;
        }
    }

    bool safe_read_u32(const void* base, std::uint32_t byte_offset, std::uint32_t* out)
    {
        if (!base || !out) return false;
        const auto* at = reinterpret_cast<const std::uint8_t*>(base) + byte_offset;
        __try
        {
            *out = *reinterpret_cast<const std::uint32_t*>(at);
            return true;
        }
        __except (probe_filter(GetExceptionInformation(), at, sizeof(std::uint32_t), "god_probe_read"))
        {
            sbcore::fault::after_handler();
            return false;
        }
    }

    bool is_writable_address(const void* address, std::size_t size)
    {
        return sbcore::memory::is_writable_region(address, size);
    }

    // ---- Stat helpers (instruction-proven layout only) ----------------------

    float read_stat(const void* actor, int stat_type)
    {
        float value = 0.0f;
        if (!actor || stat_type < 0 || stat_type > 64) return 0.0f;
        safe_read_float(actor, sbgod::kStatArrayOffset + static_cast<std::uint32_t>(stat_type) * sizeof(float), &value);
        return value;
    }

    // Writes only HP or Shield into the proven Stat[] array, and never once a
    // fault is latched in this process (A9).
    bool write_stat(void* actor, int stat_type, float value)
    {
        if (!actor || (stat_type != sbgod::kStatHp && stat_type != sbgod::kStatShield)) return false;
        if (!std::isfinite(value)) return false;
        if (sbcore::fault::writes_blocked_fast()) return false;
        auto* slot = reinterpret_cast<std::uint8_t*>(actor) + sbgod::kStatArrayOffset
            + static_cast<std::uint32_t>(stat_type) * sizeof(float);
        __try
        {
            *reinterpret_cast<float*>(slot) = value;
            return true;
        }
        __except (probe_filter(GetExceptionInformation(), slot, sizeof(float), "god_stat_write"))
        {
            sbcore::fault::after_handler();
            return false;
        }
    }

    // Hooks only: the game passed `actor` in, so a plain SEH read suffices.
    bool hook_read_actor_guid(const void* actor, std::uint32_t* guid)
    {
        return safe_read_u32(actor, sbgod::kActorGuidOffset, guid);
    }

    int find_guid_offset_for_telemetry(const void* actor, std::uint32_t want)
    {
        if (!actor || want == 0) return -1;
        for (std::uint32_t off = 0; off <= 0x200; off += 4)
        {
            std::uint32_t guid = 0;
            if (safe_read_u32(actor, off, &guid) && guid == want) return static_cast<int>(off);
        }
        return -1;
    }

    float read_player_hp(const void* actor)
    {
        if (!actor) return 0.0f;
        float hp = read_stat(actor, sbgod::kStatHp);
        const float max_hp = read_stat(actor, sbgod::kStatMaxHp);
        if (hp > max_hp + 1.0f && max_hp > 50.0f) hp = max_hp;
        return hp;
    }

    float sanitize_hp_floor(float floor)
    {
        if (!std::isfinite(floor) || floor <= 100.0f || floor > sbgod::kMaxPlayerHp) return 0.0f;
        return floor;
    }

    // The verified actor is re-checked before every maintenance write: GUID
    // (+0x30) and type id (+0x10C) unchanged, a live stat block, writable
    // Stat[] slots. The GameThread identity pass re-proved the chain on the
    // same tick; a freed or reused actor fails here and nothing is written.
    bool verify_learned_identity(const void* actor)
    {
        const auto learned_guid = g_learned_guid.load(std::memory_order_acquire);
        std::uint32_t guid = 0;
        std::uint32_t table_id = 0;
        if (!actor || learned_guid == 0 || !id::read_actor_guid(actor, &guid) || guid != learned_guid) return false;
        if (!id::read_actor_table_id(actor, &table_id) || table_id != id::kEveTableId) return false;
        const float hp = read_stat(actor, sbgod::kStatHp);
        const float max_hp = read_stat(actor, sbgod::kStatMaxHp);
        return id::eve_scale_continuing(hp, max_hp)
            && is_writable_address(reinterpret_cast<const std::uint8_t*>(actor) + sbgod::kStatArrayOffset,
                                   (sbgod::kStatShield + 1) * sizeof(float));
    }

    // ---- Protection logic (verified actor only) ------------------------------

    // Floors and per-event telemetry; never touches the verified identity.
    void reset_god_runtime_caches()
    {
        g_live_combat_actor.store(0, std::memory_order_relaxed);
        g_hp_floor.store(0.0f, std::memory_order_relaxed);
        g_sim_hp_floor.store(0.0f, std::memory_order_relaxed);
        g_sim_shield_floor.store(0.0f, std::memory_order_relaxed);
        g_setter_vital_last_actor.store(0, std::memory_order_relaxed);
        g_setter_vital_last_stat.store(-1, std::memory_order_relaxed);
        g_setter_vital_last_value.store(0.0f, std::memory_order_relaxed);
        g_setter_vital_guid_offset.store(-1, std::memory_order_relaxed);
        g_setter_vital_actor_hp.store(0.0f, std::memory_order_relaxed);
        g_setter_vital_actor_max_hp.store(0.0f, std::memory_order_relaxed);
        g_setter_vital_actor_shield.store(0.0f, std::memory_order_relaxed);
        g_setter_vital_tick.store(0, std::memory_order_relaxed);
        g_setter_after_player_execute_ms.store(0xFFFFFFFFu, std::memory_order_relaxed);
        g_setter_vital_return_address.store(0, std::memory_order_relaxed);
        g_last_player_execute_tick.store(0, std::memory_order_relaxed);
        g_dead_execute_last_guid.store(0, std::memory_order_relaxed);
        g_dead_execute_last_cause_guid.store(0, std::memory_order_relaxed);
        g_dead_execute_last_skill_id.store(0, std::memory_order_relaxed);
        g_dead_execute_last_effect_id.store(0, std::memory_order_relaxed);
        g_dead_execute_last_cause_runtime_id.store(0, std::memory_order_relaxed);
        g_dead_execute_last_force_dead.store(0, std::memory_order_relaxed);
        g_dead_execute_last_local_request.store(0, std::memory_order_relaxed);
        g_dead_execute_last_tick.store(0, std::memory_order_relaxed);
        g_dead_execute_after_player_execute_ms.store(0xFFFFFFFFu, std::memory_order_relaxed);
        g_dead_execute_predicate_mask.store(0, std::memory_order_relaxed);
        g_fatal_guard_actor.store(0, std::memory_order_relaxed);
        g_fatal_guard_tick.store(0, std::memory_order_relaxed);
        g_actor_dead_last_actor.store(0, std::memory_order_relaxed);
        g_actor_dead_last_guid.store(0, std::memory_order_relaxed);
        g_actor_dead_last_return_address.store(0, std::memory_order_relaxed);
        g_actor_dead_last_tick.store(0, std::memory_order_relaxed);
        g_actor_dead_after_player_execute_ms.store(0xFFFFFFFFu, std::memory_order_relaxed);
        g_actor_dead_after_setter_ms.store(0xFFFFFFFFu, std::memory_order_relaxed);
        g_actor_dead_predicate_mask.store(0, std::memory_order_relaxed);
        g_design_death_guid.store(0, std::memory_order_relaxed);
        g_actor_dead_world_hits.store(0, std::memory_order_relaxed);
        g_pending_death_actor.store(0, std::memory_order_relaxed);
        g_pending_death_tick.store(0, std::memory_order_relaxed);
        g_guid_candidate_actor.store(0, std::memory_order_relaxed);
        g_guid_candidate_offset.store(-1, std::memory_order_relaxed);
        g_guid_candidate_stat.store(-1, std::memory_order_relaxed);
        g_guid_candidate_value.store(0.0f, std::memory_order_relaxed);
    }

    // READ-ONLY diagnostic additions. Preserve shipping guard evaluation order.
    enum DeathProbeSlot : std::size_t
    {
        DpSeq, DpTick, DpThread, DpCommandGuid, DpActor, DpExpectedGuid,
        DpHelperGuid, DpObservedGuid, DpTableId, DpEvaluated, DpPassed, DpAction,
        DpReturnSeq, DpTransitionSeq, DpTransitionTick, DpTransitionThread,
        DpTransitionActor, DpTransitionGuid, DpTransitionCaller,
        DpParseFailedSeq, DpParseFailedTick, DpCount
    };
    struct DeathProbeTrace { std::array<std::uint64_t, DpAction + 1> values{}; };
    std::array<std::atomic<std::uint64_t>, DpCount> g_death_probe_values{};
    std::atomic_flag g_death_probe_writer = ATOMIC_FLAG_INIT;
    std::atomic<std::uint64_t> g_death_probe_version{0}, g_death_probe_dropped{0};
    std::atomic<std::uint64_t> g_death_probe_withheld{0}, g_death_probe_original_calls{0}, g_death_probe_original_returns{0};
    std::atomic<std::uint64_t> g_death_probe_attempts{0}, g_death_probe_fields_failed{0};

    bool death_probe_predicate(DeathProbeTrace& t, unsigned bit, bool passed)
    {
        t.values[DpEvaluated] |= 1ull << bit;
        if (passed) t.values[DpPassed] |= 1ull << bit;
        return passed;
    }
    template<std::size_t N>
    void death_probe_publish(std::size_t offset, const std::array<std::uint64_t, N>& values)
    {
        // Nonblocking writer; report dropped records, never spin in a hook.
        if (g_death_probe_writer.test_and_set(std::memory_order_acquire))
        { g_death_probe_dropped.fetch_add(1, std::memory_order_relaxed); return; }
        g_death_probe_version.fetch_add(1, std::memory_order_acq_rel);
        for (std::size_t i = 0; i < N; ++i) g_death_probe_values[offset + i].store(values[i], std::memory_order_relaxed);
        g_death_probe_version.fetch_add(1, std::memory_order_release);
        g_death_probe_writer.clear(std::memory_order_release);
    }
    bool death_probe_snapshot(std::array<std::uint64_t, DpCount>& values)
    {
        for (unsigned attempt = 0; attempt < 3; ++attempt)
        {
            const auto before = g_death_probe_version.load(std::memory_order_acquire);
            if ((before & 1u) != 0) continue;
            for (std::size_t i = 0; i < DpCount; ++i) values[i] = g_death_probe_values[i].load(std::memory_order_relaxed);
            std::atomic_thread_fence(std::memory_order_acquire);
            const auto after = g_death_probe_version.load(std::memory_order_acquire);
            if (before == after && (after & 1u) == 0) return true;
        }
        return false;
    }
    bool death_probe_is_protected_actor(const void* actor, DeathProbeTrace& t)
    {
        // Same checks/reads as is_protected_actor/is_confirmed_player_actor.
        g_protect_checks.fetch_add(1, std::memory_order_relaxed);
        if (!death_probe_predicate(t, 4, god_live())) return false;
        if (!death_probe_predicate(t, 5, actor != nullptr)) return false;
        const void* learned = g_learned_actor.load(std::memory_order_acquire);
        if (!death_probe_predicate(t, 6, learned != nullptr)
            || !death_probe_predicate(t, 7, actor == learned)) return false;
        const auto want = g_learned_guid.load(std::memory_order_acquire);
        t.values[DpHelperGuid] = want;
        std::uint32_t guid = 0, table_id = 0;
        if (!death_probe_predicate(t, 8, want != 0)) return false;
        const auto guid_ok = hook_read_actor_guid(actor, &guid);
        t.values[DpObservedGuid] = guid;
        if (!death_probe_predicate(t, 9, guid_ok)
            || !death_probe_predicate(t, 10, guid == want)) return false;
        const auto table_ok = safe_read_u32(actor, sbgod::kActorTableIdOffset, &table_id);
        t.values[DpTableId] = table_id;
        return death_probe_predicate(t, 11, table_ok)
            && death_probe_predicate(t, 12, table_id == id::kEveTableId);
    }

    // The only protected actor: the one the GameThread verified, with its
    // GUID still in place. Hooks call this with an actor the game passed in.
    bool is_confirmed_player_actor(const void* actor)
    {
        if (!actor) return false;
        const void* learned = g_learned_actor.load(std::memory_order_acquire);
        if (learned == nullptr || actor != learned) return false;
        const auto want = g_learned_guid.load(std::memory_order_acquire);
        std::uint32_t guid = 0;
        std::uint32_t table_id = 0;
        // The type id is re-read as well: between two GameThread ticks a
        // reused allocation at the learned address is protected only if it
        // still carries both the verified GUID and Eve's type id.
        return want != 0 && hook_read_actor_guid(actor, &guid) && guid == want
            && safe_read_u32(actor, sbgod::kActorTableIdOffset, &table_id) && table_id == id::kEveTableId;
    }

    bool is_protected_actor(const void* actor)
    {
        g_protect_checks.fetch_add(1, std::memory_order_relaxed);
        return god_live() && is_confirmed_player_actor(actor);
    }

    bool is_player_execute_apply(std::uint32_t actor_guid)
    {
        const auto want = g_learned_guid.load(std::memory_order_acquire);
        return actor_guid != 0 && want != 0 && actor_guid == want;
    }

    // ---- Implementation beta-burst r1: hook-side helpers -----------------

    // An energy switch is on and this exe was proven to be the one the energy
    // code was written for. Atomics only: any thread.
    bool energy_wanted()
    {
        return (g_desired_beta.load(std::memory_order_acquire) || g_desired_burst.load(std::memory_order_acquire))
            && g_energy_sites_ok.load(std::memory_order_acquire);
    }

    // Effective energy state, read by the hooks: armed by the GameThread AND
    // no fault latched in this process AND the dispatcher not poisoned (the
    // same three conditions as god_live()) AND the GUID-offset self-check has
    // not failed. That last one is read here because no GameThread update is
    // dispatched any more once it has failed, so no tick would disarm.
    // Atomics only: any thread.
    bool energy_live(std::memory_order order = std::memory_order_acquire)
    {
        return g_energy_live.load(order) && !g_sc_fail_sticky.load(std::memory_order_acquire)
            && !sbcore::fault::writes_blocked_fast() && !dispatch_poisoned();
    }

    struct EnergyPool
    {
        float now{};
        float max{};
    };

    // Guarded reads with a real result (never read_stat's 0-on-miss). True
    // only for a pool that can be believed: finite, 1 <= max <=
    // kMaxEnergyPool, 0 <= now <= max, and for Burst an unlocked gauge (the
    // game's own test at 0x1A6554E is int(Stat[116]) >= 1). Anything else
    // leaves the call to the game untouched.
    bool energy_read_pool(const void* actor, bool beta, EnergyPool* out)
    {
        float now = 0.0f;
        float max = 0.0f;
        if (!safe_read_float(actor, beta ? kBetaNowOffset : kBurstNowOffset, &now)
            || !safe_read_float(actor, beta ? kBetaMaxOffset : kBurstMaxOffset, &max))
            return false;
        if (!std::isfinite(now) || !std::isfinite(max) || max < 1.0f || max > kMaxEnergyPool || now < 0.0f || now > max)
            return false;
        if (!beta)
        {
            float unlock = 0.0f;
            if (!safe_read_float(actor, kBurstUnlockOffset, &unlock) || !std::isfinite(unlock) || unlock < 1.0f
                || unlock > kMaxEnergyPool)
                return false;
        }
        out->now = now;
        out->max = max;
        return true;
    }

    enum class EnergyAction : std::uint32_t { Pass, Refuse, Raise };

    // ApplyStatDiff hook only. `actor` is the one the game passed in, `diff`
    // the change it asks for on Stat[14] or Stat[18]. Refuse = answer "no
    // change" without calling the game; Raise = call the game with *raised
    // instead of diff; Pass = the game's own call, unchanged. Reads only.
    EnergyAction energy_decide(const void* actor, int stat_type, float diff, std::uint64_t return_address, float* raised)
    {
        const bool beta = stat_type == kStatBetaGauge;
        // The cheapest tests first: this runs for every actor's Beta / Burst change.
        if (!(beta ? g_desired_beta : g_desired_burst).load(std::memory_order_relaxed)) return EnergyAction::Pass;
        if (!energy_live()) return EnergyAction::Pass;
        if (!is_confirmed_player_actor(actor)) return EnergyAction::Pass;
        if (return_address != g_ret_diff_server.load(std::memory_order_relaxed))
        {
            g_energy_other_caller.fetch_add(1, std::memory_order_relaxed);
            return EnergyAction::Pass;
        }
        // Not a finite number: left to the game. (It cannot arrive here from the server apply, which
        // truncates its value to an integer at 0x1BA87E1 first; ApplyStatDiff itself zeroes a NaN at
        // 0x1A64D10 `_isnan`.) 0: nothing to do.
        if (!std::isfinite(diff) || diff == 0.0f) return EnergyAction::Pass;
        EnergyPool pool{};
        if (!energy_read_pool(actor, beta, &pool))
        {
            g_energy_pool_refused.fetch_add(1, std::memory_order_relaxed);
            return EnergyAction::Pass;
        }
        const auto gauge = beta ? kEnergyBeta : kEnergyBurst;
        if (diff < 0.0f)
        {
            g_energy_spend_blocks[gauge].fetch_add(1, std::memory_order_relaxed);
            return EnergyAction::Refuse;
        }
        // A gain. Raised, never lowered: an amount that already fills the bar is the game's own.
        const float missing = pool.max - pool.now;
        if (missing > diff)
        {
            *raised = missing;
            g_energy_fills[gauge].fetch_add(1, std::memory_order_relaxed);
            return EnergyAction::Raise;
        }
        return EnergyAction::Pass;
    }

    // ApplyStatDiff hook only, any stat: on which thread does the game make
    // its own server-side stat calls for the verified Eve? Telemetry, and the
    // proof of thread the optional top-up needs. Counted only while armed.
    void energy_note_server_call(const void* actor, std::uint64_t return_address)
    {
        if (!g_energy_live.load(std::memory_order_relaxed)) return;
        if (return_address != g_ret_diff_server.load(std::memory_order_relaxed)) return;
        if (!is_confirmed_player_actor(actor)) return;
        const auto game_thread = g_gt_thread_id.load(std::memory_order_relaxed);
        (game_thread != 0 && GetCurrentThreadId() == game_thread ? g_energy_calls_gt : g_energy_calls_other)
            .fetch_add(1, std::memory_order_relaxed);
    }

    // SetActorStat hook only. Telemetry: the game set a switched-on gauge of
    // the verified Eve to a lower value through the direct setter (a scripted
    // "set value", never a skill cost). Nothing is withheld here.
    void energy_note_setter(const void* actor, int stat_type, float value)
    {
        if (stat_type != kStatBetaGauge && stat_type != kStatBurstGauge) return;
        const bool beta = stat_type == kStatBetaGauge;
        if (!(beta ? g_desired_beta : g_desired_burst).load(std::memory_order_relaxed)) return;
        if (!energy_live(std::memory_order_relaxed) || !is_confirmed_player_actor(actor)) return;
        float now = 0.0f;
        if (std::isfinite(value) && safe_read_float(actor, beta ? kBetaNowOffset : kBurstNowOffset, &now)
            && std::isfinite(now) && value + 0.5f < now)
            g_energy_setter_lowered.fetch_add(1, std::memory_order_relaxed);
    }

    float hp_floor_for_actor(const void* actor, bool prefer_max_hp)
    {
        if (!actor) return 0.0f;
        const float hp_now = read_player_hp(actor);
        float floor = (hp_now > 100.0f) ? hp_now : 0.0f;
        if (prefer_max_hp)
        {
            const float max_hp = read_stat(actor, sbgod::kStatMaxHp);
            if (max_hp > floor && max_hp >= 150.0f && max_hp <= sbgod::kMaxPlayerHp) floor = max_hp;
        }
        return sanitize_hp_floor(floor);
    }

    bool follow_live_combat_actor(const void* actor)
    {
        if (!actor || !god_live(std::memory_order_relaxed)) return false;
        if (!is_confirmed_player_actor(actor)) return false;
        const float hp = read_player_hp(actor);
        float floor = sanitize_hp_floor(g_hp_floor.load(std::memory_order_relaxed));
        if (hp > floor && hp <= sbgod::kMaxPlayerHp) floor = hp;
        if (floor > 0.0f)
        {
            g_hp_floor.store(floor, std::memory_order_relaxed);
            g_sim_hp_floor.store(floor, std::memory_order_relaxed);
        }
        const float shield = read_stat(actor, sbgod::kStatShield);
        float sh_floor = g_sim_shield_floor.load(std::memory_order_relaxed);
        if (shield > sh_floor && shield <= sbgod::kMaxPlayerShield) sh_floor = shield;
        if (sh_floor > 0.0f && sh_floor <= sbgod::kMaxPlayerShield)
            g_sim_shield_floor.store(sh_floor, std::memory_order_relaxed);
        return true;
    }

    // GameThread only, before g_god_live becomes true.
    void arm_god_floors_from_actor(const void* actor)
    {
        if (!actor) return;
        const float hp_floor = hp_floor_for_actor(actor, true);
        const float shield_now = read_stat(actor, sbgod::kStatShield);
        const float sh_floor = (shield_now > 0.0f && shield_now <= sbgod::kMaxPlayerShield) ? shield_now : 0.0f;
        if (hp_floor > 0.0f) g_hp_floor.store(hp_floor, std::memory_order_relaxed);
        if (hp_floor > 0.0f) g_sim_hp_floor.store(hp_floor, std::memory_order_relaxed);
        if (sh_floor > 0.0f) g_sim_shield_floor.store(sh_floor, std::memory_order_relaxed);
    }

    // Only the proven Stat[] slots are written (v1.0.36 guessed offsets are gone).
    void restore_player_hp(void* actor, float hp_floor, float sh_floor)
    {
        if (!actor) return;
        if (hp_floor > 100.0f) write_stat(actor, sbgod::kStatHp, hp_floor);
        if (sh_floor > 0.0f) write_stat(actor, sbgod::kStatShield, sh_floor);
    }

    bool restore_hp_shield_if_dropped(void* actor, float hp_before, float shield_before)
    {
        const float hp_floor = g_sim_hp_floor.load(std::memory_order_relaxed);
        const float sh_floor = g_sim_shield_floor.load(std::memory_order_relaxed);
        float target_hp = hp_before;
        float target_shield = shield_before;
        if (hp_floor > target_hp) target_hp = hp_floor;
        if (sh_floor > target_shield) target_shield = sh_floor;
        const float hp_after = read_player_hp(actor);
        const float shield_after = read_stat(actor, sbgod::kStatShield);
        if (target_hp > 100.0f && hp_after + 0.5f < target_hp)
        {
            restore_player_hp(actor, target_hp, target_shield);
            return true;
        }
        if (target_shield > 0.0f && shield_after + 0.5f < target_shield)
        {
            restore_player_hp(actor, target_hp, target_shield);
            return true;
        }
        return false;
    }

    bool maintain_one_actor(void* actor, float* hp_floor_io, float* sh_floor_io)
    {
        if (!actor) return false;
        const float hp = read_player_hp(actor);
        const float shield = read_stat(actor, sbgod::kStatShield);
        float hp_floor = *hp_floor_io;
        float sh_floor = *sh_floor_io;
        if (hp > 50.0f && hp <= sbgod::kMaxPlayerHp && hp > hp_floor + 0.5f)
        {
            hp_floor = hp;
            g_sim_hp_floor.store(hp_floor, std::memory_order_relaxed);
            g_hp_floor.store(hp_floor, std::memory_order_relaxed);
        }
        if (shield > sh_floor + 0.5f && shield <= sbgod::kMaxPlayerShield)
        {
            sh_floor = shield;
            g_sim_shield_floor.store(sh_floor, std::memory_order_relaxed);
        }
        bool restored = false;
        if (hp_floor > 100.0f && hp + 0.5f < hp_floor)
        {
            restore_player_hp(actor, hp_floor, sh_floor);
            restored = true;
        }
        else if (sh_floor > 0.0f && shield + 0.5f < sh_floor)
        {
            restore_player_hp(actor, hp_floor, sh_floor);
            restored = true;
        }
        *hp_floor_io = hp_floor;
        *sh_floor_io = sh_floor;
        return restored;
    }

    // GameThread only, after the identity pass re-proved the actor this tick.
    void maintain_god_hp()
    {
        if (!god_live(std::memory_order_relaxed)) return;
        g_maintain_ticks.fetch_add(1, std::memory_order_relaxed);
        void* actor = g_learned_actor.load(std::memory_order_relaxed);
        if (!actor) return;
        if (!verify_learned_identity(actor))
        {
            g_maintain_verify_rejects.fetch_add(1, std::memory_order_relaxed);
            return;
        }
        // v1.3.0: HP fell since the previous tick left it (MaxHP unchanged, so
        // not a MaxHP clamp; past the post-arm grace): damage reached Eve
        // between ticks. A shield-only drop is telemetry. v1.3.1 judges it
        // after this tick's restore: back at the floor = repaired, still
        // below = a real leak.
        bool hp_dropped = false;
        {
            const float hp_now = read_player_hp(actor);
            const float shield_now = read_stat(actor, sbgod::kStatShield);
            const float max_now = read_stat(actor, sbgod::kStatMaxHp);
            const std::uint64_t now_ms = GetTickCount64();
            if (gt_fh_prev_valid && max_now == gt_fh_prev_max_hp)
            {
                if (std::isfinite(hp_now) && hp_now + 0.5f < gt_fh_prev_hp)
                {
                    hp_dropped = now_ms >= gt_armed_ms + kTickDropGraceMs;
                }
                else if (std::isfinite(shield_now) && shield_now + 0.5f < gt_fh_prev_shield)
                {
                    g_shield_drops.fetch_add(1, std::memory_order_relaxed);
                }
            }
        }
        follow_live_combat_actor(actor);
        float hp_floor = sanitize_hp_floor(g_sim_hp_floor.load(std::memory_order_relaxed));
        if (hp_floor <= 0.0f) hp_floor = sanitize_hp_floor(g_hp_floor.load(std::memory_order_relaxed));
        float sh_floor = g_sim_shield_floor.load(std::memory_order_relaxed);
        if (sh_floor > sbgod::kMaxPlayerShield) sh_floor = 0.0f;
        if (maintain_one_actor(actor, &hp_floor, &sh_floor))
        {
            g_maintain_restores.fetch_add(1, std::memory_order_relaxed);
            g_blocks.fetch_add(1, std::memory_order_relaxed);
        }
        if (hp_dropped)
        {
            const float hp_after = read_player_hp(actor);
            const bool repaired = hp_floor > 100.0f && std::isfinite(hp_after) && hp_after + 0.5f >= hp_floor;
            note_hit_event(repaired ? id::HitEvent::TickRepaired : id::HitEvent::TickDrop);
        }
        // The pool as this tick leaves it (after any restore).
        gt_fh_prev_hp = read_player_hp(actor);
        gt_fh_prev_shield = read_stat(actor, sbgod::kStatShield);
        gt_fh_prev_max_hp = read_stat(actor, sbgod::kStatMaxHp);
        gt_fh_prev_valid = std::isfinite(gt_fh_prev_hp) && std::isfinite(gt_fh_prev_shield)
            && std::isfinite(gt_fh_prev_max_hp);
    }

    void note_hook_hit(void* actor, int stat_type)
    {
        g_hits.fetch_add(1, std::memory_order_relaxed);
        g_last_stat.store(stat_type, std::memory_order_relaxed);
        g_last_actor.store(reinterpret_cast<std::uint64_t>(actor), std::memory_order_relaxed);
    }

    // ---- Hook corroboration and self-check sampling (read-only) ----------

    // The game passed `actor` to a stat hook: remember its GUID and count a
    // corroboration when it is the current identity candidate.
    void note_stat_hook_actor(const void* actor, std::uint32_t source)
    {
        if (!actor) return;
        std::uint32_t guid = 0;
        if (!hook_read_actor_guid(actor, &guid)) return;
        g_hook_actor_last.store(reinterpret_cast<std::uint64_t>(actor), std::memory_order_relaxed);
        g_hook_actor_guid_last.store(guid, std::memory_order_relaxed);
        g_hook_actor_source_last.store(source, std::memory_order_relaxed);
        const auto cand_actor = g_cand_actor_pub.load(std::memory_order_acquire);
        const auto cand_guid = g_cand_guid_pub.load(std::memory_order_acquire);
        if (cand_actor != 0 && cand_guid != 0 && reinterpret_cast<std::uint64_t>(actor) == cand_actor && guid == cand_guid)
            g_cand_corroborations.fetch_add(1, std::memory_order_acq_rel);
    }

    void note_state_hook_actor(const void* actor)
    {
        const auto cand_actor = g_cand_actor_pub.load(std::memory_order_acquire);
        if (!actor || cand_actor == 0 || reinterpret_cast<std::uint64_t>(actor) != cand_actor) return;
        std::uint32_t guid = 0;
        const auto cand_guid = g_cand_guid_pub.load(std::memory_order_acquire);
        if (cand_guid != 0 && hook_read_actor_guid(actor, &guid) && guid == cand_guid)
            g_cand_corroborations.fetch_add(1, std::memory_order_acq_rel);
    }

    void note_apply_command_guid(std::uint32_t guid)
    {
        g_hook_apply_guid_last.store(guid, std::memory_order_relaxed);
        const auto cand_guid = g_cand_guid_pub.load(std::memory_order_acquire);
        if (guid != 0 && cand_guid != 0 && guid == cand_guid)
            g_cand_corroborations.fetch_add(1, std::memory_order_acq_rel);
    }

    // v1.3.1: the actor passed in is still the published identity candidate:
    // same pointer (compared first: the ApplyStatDiff hook runs for every
    // actor's stat change), same GUID at +0x30, Eve's type id at +0x10C.
    bool is_candidate_actor(const void* actor, std::uint64_t cand_actor, std::uint32_t cand_guid)
    {
        if (!actor || cand_actor == 0 || cand_guid == 0 || reinterpret_cast<std::uint64_t>(actor) != cand_actor)
            return false;
        std::uint32_t guid = 0;
        std::uint32_t table_id = 0;
        return hook_read_actor_guid(actor, &guid) && guid == cand_guid
            && safe_read_u32(actor, sbgod::kActorTableIdOffset, &table_id) && table_id == id::kEveTableId;
    }

    // v1.3.1: the game applies a stat change to the identity candidate (S9
    // evidence, as SetActorStat / ActorStateChange / ApplyStat already are).
    // Returns whether `actor` is that candidate.
    bool note_diff_hook_actor(const void* actor)
    {
        const auto cand_actor = g_cand_actor_pub.load(std::memory_order_acquire);
        if (cand_actor == 0 || reinterpret_cast<std::uint64_t>(actor) != cand_actor) return false;
        if (!is_candidate_actor(actor, cand_actor, g_cand_guid_pub.load(std::memory_order_acquire))) return false;
        g_cand_corroborations.fetch_add(1, std::memory_order_acq_rel);
        return true;
    }

    // v1.3.1 F2: God is wanted, not armed, no fault/poison, and `actor` is the
    // candidate the GameThread proved S1..S8 for on its last tick (pointer,
    // GUID and type id re-read here). Only then may a hook withhold a hit
    // before the arm; the hook's own call is the ninth signal.
    bool is_ready_candidate(const void* actor)
    {
        const auto ready_actor = g_ready_actor.load(std::memory_order_acquire);
        if (ready_actor == 0 || reinterpret_cast<std::uint64_t>(actor) != ready_actor) return false;
        if (!g_desired_god.load(std::memory_order_acquire) || g_god_live.load(std::memory_order_acquire)
            || sbcore::fault::writes_blocked_fast() || dispatch_poisoned()
            || g_shutting_down.load(std::memory_order_acquire))
            return false;
        return is_candidate_actor(actor, ready_actor, g_ready_guid.load(std::memory_order_acquire));
    }

    // v1.3.1 F2 for ApplyStatExecute: the command's GUID names the ready
    // candidate, which still carries that GUID and Eve's type id.
    bool is_ready_candidate_guid(std::uint32_t guid)
    {
        const auto ready_guid = g_ready_guid.load(std::memory_order_acquire);
        const auto ready_actor = g_ready_actor.load(std::memory_order_acquire);
        if (guid == 0 || ready_guid == 0 || ready_actor == 0 || guid != ready_guid) return false;
        return is_ready_candidate(reinterpret_cast<const void*>(ready_actor));
    }

    void record_guid_sample(const void* actor, std::uint32_t expected, std::uint32_t source)
    {
        std::uint32_t observed = 0;
        if (!expected || !hook_read_actor_guid(actor, &observed)) return;
        g_sc_hook_last_source.store(source, std::memory_order_relaxed);
        g_sc_hook_last_expected.store(expected, std::memory_order_relaxed);
        g_sc_hook_last_observed.store(observed, std::memory_order_relaxed);
        if (observed == expected)
        {
            g_sc_hook_matches.fetch_add(1, std::memory_order_acq_rel);
            return;
        }
        const auto mismatches = g_sc_hook_mismatches.fetch_add(1, std::memory_order_acq_rel) + 1;
        if (mismatches >= kHookMismatchesToFail && g_sc_hook_matches.load(std::memory_order_acquire) == 0)
        {
            // Definitive evidence the GUID offset is wrong: disarm at once.
            g_sc_fail_sticky.store(true, std::memory_order_release);
            g_god_live.store(false, std::memory_order_release);
            g_energy_live.store(false, std::memory_order_release); // beta-burst r1: the energy switches as well
        }
    }

    // ---- Hooks ----------------------------------------------------------------

    bool run_god_protected_stat_write(void* actor, int stat_type, float value, void* unused_r8, std::uint8_t flag)
    {
        auto* set_actor_stat = original<SetActorStatFn>(sites::kSetActorStat);
        if (stat_type == sbgod::kStatHp || stat_type == sbgod::kStatShield)
        {
            const float hp_floor = std::max(g_sim_hp_floor.load(std::memory_order_relaxed),
                                            g_hp_floor.load(std::memory_order_relaxed));
            const float sh_floor = g_sim_shield_floor.load(std::memory_order_relaxed);
            const float floor = (stat_type == sbgod::kStatHp) ? hp_floor : sh_floor;
            if (floor > 100.0f && value + 0.5f < floor)
            {
                g_blocks.fetch_add(1, std::memory_order_relaxed);
                note_hit_event(id::HitEvent::SetterBlocked);
                restore_player_hp(actor, (stat_type == sbgod::kStatHp) ? floor : hp_floor,
                                  (stat_type == sbgod::kStatShield) ? floor : sh_floor);
                return true;
            }
            if (value < 0.0f)
            {
                g_blocks.fetch_add(1, std::memory_order_relaxed);
                note_hit_event(id::HitEvent::SetterBlocked);
                return true;
            }
        }
        const float hp_before = read_player_hp(actor);
        const float shield_before = read_stat(actor, sbgod::kStatShield);
        set_actor_stat(actor, stat_type, value, unused_r8, flag);
        if (restore_hp_shield_if_dropped(actor, hp_before, shield_before))
        {
            g_blocks.fetch_add(1, std::memory_order_relaxed);
            note_hit_event(id::HitEvent::SetterBlocked);
        }
        return true;
    }

    void __fastcall hook_set_actor_stat(void* actor, int stat_type, float value, void* unused_r8, std::uint8_t flag)
    {
        auto* set_actor_stat = original<SetActorStatFn>(sites::kSetActorStat);
        if (!set_actor_stat) return; // unreachable: published before the entry jump
        auto** return_address_slot = reinterpret_cast<void**>(_AddressOfReturnAddress());
        const auto return_address = reinterpret_cast<std::uint64_t>(*return_address_slot);

        // Self-check: ApplyStatExecute passes the actor it looked up by the
        // command's ActorGUID (r15) at this exact call site.
        if (tl_apply_cmd_guid != 0 && return_address == g_ret_apply_setter.load(std::memory_order_relaxed))
        {
            record_guid_sample(actor, tl_apply_cmd_guid, 1);
        }
        note_stat_hook_actor(actor, 1);
        energy_note_setter(actor, stat_type, value); // beta-burst r1: telemetry only, reads only

        note_hook_hit(actor, stat_type);
        if (!god_live())
        {
            // v1.3.1 F2: a lower HP/Shield value for the ready candidate is
            // withheld (the call above already counted as S9).
            if ((stat_type == sbgod::kStatHp || stat_type == sbgod::kStatShield) && std::isfinite(value)
                && is_ready_candidate(actor))
            {
                const float current = read_stat(actor, stat_type);
                if (std::isfinite(current) && value + 0.5f < current)
                {
                    g_prearm_blocks.fetch_add(1, std::memory_order_relaxed);
                    return;
                }
            }
            set_actor_stat(actor, stat_type, value, unused_r8, flag);
            return;
        }

        const void* learned = g_learned_actor.load(std::memory_order_relaxed);
        const bool vital = stat_type == sbgod::kStatHp || stat_type == sbgod::kStatShield;
        const auto telemetry_guid = g_learned_guid.load(std::memory_order_relaxed);
        const int telemetry_guid_offset = find_guid_offset_for_telemetry(actor, telemetry_guid);
        const auto setter_tick = GetTickCount();
        const auto player_execute_tick = g_last_player_execute_tick.load(std::memory_order_relaxed);

        if (vital)
        {
            g_setter_vital_hits.fetch_add(1, std::memory_order_relaxed);
            if (value < 0.0f) g_setter_vital_negative_hits.fetch_add(1, std::memory_order_relaxed);
            g_setter_vital_last_actor.store(reinterpret_cast<std::uint64_t>(actor), std::memory_order_relaxed);
            g_setter_vital_last_stat.store(stat_type, std::memory_order_relaxed);
            g_setter_vital_last_value.store(value, std::memory_order_relaxed);
            g_setter_vital_guid_offset.store(telemetry_guid_offset, std::memory_order_relaxed);
            g_setter_vital_actor_hp.store(read_stat(actor, sbgod::kStatHp), std::memory_order_relaxed);
            g_setter_vital_actor_max_hp.store(read_stat(actor, sbgod::kStatMaxHp), std::memory_order_relaxed);
            g_setter_vital_actor_shield.store(read_stat(actor, sbgod::kStatShield), std::memory_order_relaxed);
            g_setter_vital_tick.store(setter_tick, std::memory_order_relaxed);
            g_setter_after_player_execute_ms.store(
                player_execute_tick != 0 ? setter_tick - player_execute_tick : 0xFFFFFFFFu, std::memory_order_relaxed);
            g_setter_vital_return_address.store(return_address, std::memory_order_relaxed);

            const auto pending_actor = g_pending_death_actor.load(std::memory_order_relaxed);
            const auto pending_tick = g_pending_death_tick.load(std::memory_order_relaxed);
            const bool exact_pending_fatal_zero = stat_type == sbgod::kStatHp && value <= 0.0f
                && pending_actor != 0 && pending_actor == reinterpret_cast<std::uint64_t>(actor)
                && pending_tick != 0 && setter_tick - pending_tick <= 64u && is_confirmed_player_actor(actor);
            if (exact_pending_fatal_zero)
            {
                // The paired actor-death transition was already rejected.
                g_fatal_zero_blocks.fetch_add(1, std::memory_order_relaxed);
                g_blocks.fetch_add(1, std::memory_order_relaxed);
                note_hit_event(id::HitEvent::SetterBlocked);
                g_pending_death_actor.store(0, std::memory_order_relaxed);
                g_pending_death_tick.store(0, std::memory_order_relaxed);
                return;
            }
        }

        if (actor != learned && telemetry_guid_offset >= 0)
        {
            g_guid_candidate_hits.fetch_add(1, std::memory_order_relaxed);
            g_guid_candidate_actor.store(reinterpret_cast<std::uint64_t>(actor), std::memory_order_relaxed);
            g_guid_candidate_offset.store(telemetry_guid_offset, std::memory_order_relaxed);
            g_guid_candidate_stat.store(stat_type, std::memory_order_relaxed);
            g_guid_candidate_value.store(value, std::memory_order_relaxed);
        }

        if (vital && g_in_player_execute_apply)
        {
            g_live_combat_actor.store(reinterpret_cast<std::uint64_t>(actor), std::memory_order_relaxed);
        }

        // Only the verified actor (same pointer, same GUID) is ever protected.
        if (!is_protected_actor(actor))
        {
            set_actor_stat(actor, stat_type, value, unused_r8, flag);
            return;
        }
        follow_live_combat_actor(actor);
        if (value < 0.0f && vital)
        {
            g_blocks.fetch_add(1, std::memory_order_relaxed);
            note_hit_event(id::HitEvent::SetterBlocked);
            return;
        }
        run_god_protected_stat_write(actor, stat_type, value, unused_r8, flag);
    }

    void __fastcall hook_actor_dead_execute(void* dead_command)
    {
        auto* dead_execute = original<ActorDeadExecuteFn>(sites::kDeadExecute);
        if (!dead_execute) return; // unreachable: published before the entry jump
        const auto probe_sequence = g_death_probe_attempts.fetch_add(1, std::memory_order_relaxed) + 1u;

        std::uint32_t actor_guid = 0;
        int cause_actor_guid = 0;
        int hit_skill_id = 0;
        int effect_id = 0;
        int cause_actor_runtime_id = 0;
        std::uint8_t force_dead = 0;
        std::uint8_t local_request = 0;
        bool fields_ok = false;
        if (dead_command)
        {
            // FSBActorDead layout, proven by the DeadExecuteFieldsCall anchor:
            // ActorGUID +0x10, cause +0x14, skill +0x18, effect +0x1C,
            // runtime id +0x20, force_dead +0x24, local_request +0x25.
            __try
            {
                auto* bytes = reinterpret_cast<std::uint8_t*>(dead_command);
                actor_guid = *reinterpret_cast<std::uint32_t*>(bytes + 0x10);
                cause_actor_guid = *reinterpret_cast<int*>(bytes + 0x14);
                hit_skill_id = *reinterpret_cast<int*>(bytes + 0x18);
                effect_id = *reinterpret_cast<int*>(bytes + 0x1C);
                cause_actor_runtime_id = *reinterpret_cast<int*>(bytes + 0x20);
                force_dead = *(bytes + 0x24);
                local_request = *(bytes + 0x25);
                fields_ok = true;
            }
            __except (probe_filter(GetExceptionInformation(), dead_command, 0x26, "god_dead_command_read"))
            {
                sbcore::fault::after_handler();
                fields_ok = false;
            }
        }
        if (!fields_ok)
        {
            // Keep the original passthrough and legacy command TLS untouched.
            // Scope only private diagnostic TLS, including null/unreadable commands.
            g_death_probe_fields_failed.fetch_add(1, std::memory_order_relaxed);
            g_death_probe_original_calls.fetch_add(1, std::memory_order_relaxed);
            death_probe_publish(DpParseFailedSeq, std::array<std::uint64_t, 2>{probe_sequence, GetTickCount()});
            const auto previous_probe = tl_death_probe_sequence;
            tl_death_probe_sequence = probe_sequence;
            dead_execute(dead_command);
            g_death_probe_original_returns.fetch_add(1, std::memory_order_relaxed);
            tl_death_probe_sequence = previous_probe;
            return;
        }

        const auto dead_tick = GetTickCount();
        const auto player_execute_tick = g_last_player_execute_tick.load(std::memory_order_relaxed);
        const auto after_player_execute_ms = player_execute_tick != 0 ? dead_tick - player_execute_tick : 0xFFFFFFFFu;
        const auto learned_guid = g_learned_guid.load(std::memory_order_relaxed);
        g_dead_execute_hits.fetch_add(1, std::memory_order_relaxed);
        if (actor_guid == kPlayerDeathProxyRuntimeId || (learned_guid != 0 && actor_guid == learned_guid))
            g_dead_execute_player_candidates.fetch_add(1, std::memory_order_relaxed);
        g_dead_execute_last_guid.store(actor_guid, std::memory_order_relaxed);
        g_dead_execute_last_cause_guid.store(cause_actor_guid, std::memory_order_relaxed);
        g_dead_execute_last_skill_id.store(hit_skill_id, std::memory_order_relaxed);
        g_dead_execute_last_effect_id.store(effect_id, std::memory_order_relaxed);
        g_dead_execute_last_cause_runtime_id.store(cause_actor_runtime_id, std::memory_order_relaxed);
        g_dead_execute_last_force_dead.store(force_dead, std::memory_order_relaxed);
        g_dead_execute_last_local_request.store(local_request, std::memory_order_relaxed);
        g_dead_execute_last_tick.store(dead_tick, std::memory_order_relaxed);
        g_dead_execute_after_player_execute_ms.store(after_player_execute_ms, std::memory_order_relaxed);

        const auto combat_guid = g_player_combat_guid.load(std::memory_order_relaxed);
        const auto execute_guid = g_execute_vital_last_guid.load(std::memory_order_relaxed);
        const auto execute_stat = g_execute_vital_last_stat.load(std::memory_order_relaxed);
        const auto execute_diff = g_execute_vital_last_diff.load(std::memory_order_relaxed);
        const bool identity_verified = g_identity_verified.load(std::memory_order_relaxed);
        std::uint32_t predicate_mask = 0;
        if (god_live(std::memory_order_relaxed)) predicate_mask |= 1u << 0;
        if (actor_guid == kPlayerDeathProxyRuntimeId) predicate_mask |= 1u << 1;
        if (after_player_execute_ms <= 128u) predicate_mask |= 1u << 2;
        if (execute_guid == combat_guid && combat_guid != 0) predicate_mask |= 1u << 3;
        if (execute_stat == sbgod::kStatHp || execute_stat == sbgod::kStatShield) predicate_mask |= 1u << 4;
        if (execute_diff < 0.0f) predicate_mask |= 1u << 5;
        if (identity_verified) predicate_mask |= 1u << 6;
        if (g_learned_actor.load(std::memory_order_relaxed) != nullptr) predicate_mask |= 1u << 7;
        if (g_hp_floor.load(std::memory_order_relaxed) > 0.0f) predicate_mask |= 1u << 8;
        if (learned_guid != 0 && actor_guid == learned_guid) predicate_mask |= 1u << 9;
        if (g_execute_player_vital_hits.load(std::memory_order_relaxed) > 0) predicate_mask |= 1u << 10;
        // Implementation r2 (offline tested only): a Dead command that
        // belongs to a kind-1 death the fix let through with HP left (fall, kill
        // volume, laser) is the game's own rule, not damage that got through.
        // hook_actor_death_transition leaves that Eve's GUID in
        // g_design_death_guid when the game accepted such a death; the first
        // Dead command for that GUID consumes it and is not booked as a leak.
        // New dead_execute_predicate_mask bits: 11 = this command was one;
        // 16-23 = how many so far (stops at 255). The count is carried over
        // from command to command, so enemy deaths do not erase it;
        // reset_god_runtime_caches clears it with the rest of the mask.
        auto design_death_guid = actor_guid;
        const bool design_death = actor_guid != 0
            && g_design_death_guid.compare_exchange_strong(design_death_guid, 0, std::memory_order_acq_rel);
        std::uint32_t design_deaths = g_dead_execute_predicate_mask.load(std::memory_order_relaxed) & (0xFFu << 16);
        if (design_death)
        {
            predicate_mask |= 1u << 11;
            if (design_deaths != (0xFFu << 16)) design_deaths += 1u << 16;
        }
        predicate_mask |= design_deaths;
        g_dead_execute_predicate_mask.store(predicate_mask, std::memory_order_relaxed);

        // v1.3.3 withheld Execute here; that hold is removed (see the block
        // below). The v4 predicate chain stays as a read-only diagnostic and
        // still re-reads the armed local Eve identity, never a cached GUID only.
        const auto* protected_actor = g_learned_actor.load(std::memory_order_acquire);
        DeathProbeTrace probe;
        probe.values[DpSeq] = probe_sequence; probe.values[DpTick] = dead_tick;
        probe.values[DpThread] = GetCurrentThreadId(); probe.values[DpCommandGuid] = actor_guid;
        probe.values[DpActor] = reinterpret_cast<std::uint64_t>(protected_actor);
        probe.values[DpExpectedGuid] = learned_guid;
        const bool probe_player_candidate = learned_guid != 0 && actor_guid == learned_guid;
        if (death_probe_predicate(probe, 0, actor_guid != 0)
            && death_probe_predicate(probe, 1, actor_guid == g_learned_guid.load(std::memory_order_acquire))
            && death_probe_predicate(probe, 2, g_identity_verified.load(std::memory_order_acquire))
            && death_probe_predicate(probe, 3, god_live())
            && death_probe_is_protected_actor(protected_actor, probe)
            && death_probe_predicate(probe, 13, protected_actor == g_learned_actor.load(std::memory_order_acquire))
            && death_probe_predicate(probe, 14, actor_guid == g_learned_guid.load(std::memory_order_acquire))
            && death_probe_predicate(probe, 15, god_live()))
        {
            // Implementation on the v4 probe source (offline tested only,
            // not installed, not live-tested): Execute is no longer withheld.
            // In single player the Dead command is created at 0x1BAE91E, only
            // after the local DeathTransition call (0x1BAE8AC) returned true,
            // so Eve's death (life state 3, or Coma 2 when a revival item
            // applies) is already committed when this hook runs. Execute
            // itself calls DeathTransition only when the cached net mode is
            // 3 = client (0x1B20162 `cmp eax,3 / jne 0x1B201BF`). Withholding
            // the command could not save Eve and booked a real death as
                                                                         
                                                                         
            // death is stopped in hook_actor_death_transition instead.
            // Nothing to do here: evaluated/passed mask 0xFFFF with action 2
            // now reads "a Dead command for the armed, current Eve was
            // executed". death_probe_withheld stays in the heartbeat and
            // reads 0.
        }

        // v1.3.0: a death command for the verified GUID while God is armed
        // means damage reached Eve; the first-hit watch reports it.
        // r2: except the command of a by-design kind-1 death (see above).
        if (learned_guid != 0 && actor_guid == learned_guid && god_live(std::memory_order_relaxed) && !design_death)
            note_hit_event(id::HitEvent::DeathCommand);

        // The command layer remains telemetry-only (v1.0.36). The command GUID
        // is scoped for the self-check sample in the DeathTransition hook.
        g_death_probe_original_calls.fetch_add(1, std::memory_order_relaxed);
        probe.values[DpAction] = 2; // Original call boundary reached.
        if (probe_player_candidate) death_probe_publish(0, probe.values);
        const auto previous = tl_dead_cmd_guid;
        const auto previous_probe = tl_death_probe_sequence;
        tl_dead_cmd_guid = actor_guid;
        tl_death_probe_sequence = probe_sequence;
        dead_execute(dead_command);
        g_death_probe_original_returns.fetch_add(1, std::memory_order_relaxed);
        if (probe_player_candidate) death_probe_publish(DpReturnSeq, std::array<std::uint64_t, 1>{probe_sequence});
        tl_death_probe_sequence = previous_probe;
        tl_dead_cmd_guid = previous;
    }

    void __fastcall hook_actor_state_change(void* actor, int state_tag, std::uint8_t add, std::uint8_t clear)
    {
        auto* state_change = original<ActorStateChangeFn>(sites::kActorStateChange);
        if (!state_change) return; // unreachable: published before the entry jump

        note_state_hook_actor(actor);
        if (state_tag == 0x20)
        {
            std::uint32_t guid_10c = 0;
            std::uint32_t guid_10 = 0;
            safe_read_u32(actor, sbgod::kActorTableIdOffset, &guid_10c);
            safe_read_u32(actor, 0x10, &guid_10);
            const auto tick = GetTickCount();
            const auto player_execute_tick = g_last_player_execute_tick.load(std::memory_order_relaxed);
            const auto after_player_execute_ms = player_execute_tick != 0 ? tick - player_execute_tick : 0xFFFFFFFFu;
            const auto return_address = reinterpret_cast<std::uint64_t>(_ReturnAddress());
            const auto actor_address = reinterpret_cast<std::uint64_t>(actor);
            const float hp = read_stat(actor, sbgod::kStatHp);
            const float max_hp = read_stat(actor, sbgod::kStatMaxHp);
            const float shield = read_stat(actor, sbgod::kStatShield);
            note_stat_hook_actor(actor, 2);

            g_state20_hits.fetch_add(1, std::memory_order_relaxed);
            if (clear) g_state20_clear_hits.fetch_add(1, std::memory_order_relaxed);
            else if (add) g_state20_add_hits.fetch_add(1, std::memory_order_relaxed);
            else g_state20_remove_hits.fetch_add(1, std::memory_order_relaxed);

            g_state20_last_actor.store(actor_address, std::memory_order_relaxed);
            g_state20_last_guid_10c.store(guid_10c, std::memory_order_relaxed);
            g_state20_last_guid_10.store(guid_10, std::memory_order_relaxed);
            g_state20_last_return_address.store(return_address, std::memory_order_relaxed);
            g_state20_last_tick.store(tick, std::memory_order_relaxed);
            g_state20_last_after_player_execute_ms.store(after_player_execute_ms, std::memory_order_relaxed);
            g_state20_last_add.store(add, std::memory_order_relaxed);
            g_state20_last_clear.store(clear, std::memory_order_relaxed);
            g_state20_last_hp.store(hp, std::memory_order_relaxed);
            g_state20_last_max_hp.store(max_hp, std::memory_order_relaxed);
            g_state20_last_shield.store(shield, std::memory_order_relaxed);

            if (add && !clear)
            {
                g_state20_add_actor.store(actor_address, std::memory_order_relaxed);
                g_state20_add_guid_10c.store(guid_10c, std::memory_order_relaxed);
                g_state20_add_return_address.store(return_address, std::memory_order_relaxed);
                g_state20_add_tick.store(tick, std::memory_order_relaxed);
                g_state20_add_after_player_execute_ms.store(after_player_execute_ms, std::memory_order_relaxed);
                g_state20_add_hp.store(hp, std::memory_order_relaxed);
                g_state20_add_max_hp.store(max_hp, std::memory_order_relaxed);
                g_state20_add_shield.store(shield, std::memory_order_relaxed);
            }

            // The 0x20 state is the game's scoped authoritative-stat update.
            // Its exact removal point is the final safe point after the HP
            // snapshot reaches zero and before death commands run. Restore
            // only the verified Eve actor's proven HP slot.
            const auto add_actor = g_state20_add_actor.load(std::memory_order_relaxed);
            const auto add_tick = g_state20_add_tick.load(std::memory_order_relaxed);
            const float add_hp = g_state20_add_hp.load(std::memory_order_relaxed);
            const bool scoped_remove = !add && !clear
                && return_address == g_ret_state_scoped.load(std::memory_order_relaxed);
            const bool exact_eve_actor = god_live(std::memory_order_relaxed) && actor_address != 0
                && is_confirmed_player_actor(actor) && guid_10c == id::kEveTableId;
            const bool paired_live_snapshot = add_tick != 0 && tick - add_tick <= 1000u && add_actor == actor_address
                && std::isfinite(add_hp) && add_hp > 100.0f && add_hp <= sbgod::kMaxPlayerHp;
            const bool lethal_snapshot = std::isfinite(hp) && hp <= 0.5f && std::isfinite(max_hp)
                && max_hp > 100.0f && max_hp <= sbgod::kMaxPlayerHp;
            if (scoped_remove && exact_eve_actor && paired_live_snapshot && lethal_snapshot)
            {
                write_stat(actor, sbgod::kStatHp, add_hp);
                const float restored_hp = read_stat(actor, sbgod::kStatHp);
                if (std::isfinite(restored_hp) && restored_hp > 100.0f)
                {
                    g_state20_lethal_restores.fetch_add(1, std::memory_order_relaxed);
                    g_state20_restore_actor.store(actor_address, std::memory_order_relaxed);
                    g_state20_restore_tick.store(tick, std::memory_order_relaxed);
                    g_state20_restore_hp.store(restored_hp, std::memory_order_relaxed);
                    g_state20_restore_shield.store(shield, std::memory_order_relaxed);
                    g_state20_restore_pawn.store(0u, std::memory_order_relaxed);
                    g_blocks.fetch_add(1, std::memory_order_relaxed);
                    note_hit_event(id::HitEvent::LethalRestore);
                }
            }
        }
        // Preserve the game's scoped-state mutation.
        state_change(actor, state_tag, add, clear);
    }

    // Implementation r2: the life state the forced-death block reads,
    // tied to the exe by bytes like an anchor. install() refuses with
    // "anchor-mismatch:DeathLifeStateRead" when either run differs, so the
    // block never reads an offset this exe does not use. DeathTransition
    // 0x1A6ED60, exe 573AAFF1...545C:
    //   0x1A6EEEF  41 8B 86 00 26 00 00  mov eax,[r14+2600h]  ESBActorLifeState
    //   0x1A6EEF6  83 F8 02              cmp eax,2            Coma
    //   0x1A6EEF9  75 60                 jne 0x1A6EF5B
    //   0x1A6EF5B  83 F8 01              cmp eax,1            Spawn (alive)
    //   0x1A6EF5E  74 05                 je  0x1A6EF65        -> can kill
    //   0x1A6EF60  83 F8 06              cmp eax,6            Spawning
    //   0x1A6EF63  75 16                 jne 0x1A6EF7B        -> "not dead"
                                                      
    // dis-deathtransition-1A6ED60.txt (lines 103-105, 129-132); they were not
                                                
    constexpr std::uint32_t kActorLifeStateOffset = 0x2600;
    constexpr std::uint32_t kLifeStateReadRva = 0x1A6EEEF;
    constexpr std::uint8_t kLifeStateRead[] = {0x41, 0x8B, 0x86, 0x00, 0x26, 0x00, 0x00, 0x83, 0xF8, 0x02, 0x75, 0x60};
    constexpr std::uint32_t kLifeStateKillTestRva = 0x1A6EF5B;
    constexpr std::uint8_t kLifeStateKillTest[] = {0x83, 0xF8, 0x01, 0x74, 0x05, 0x83, 0xF8, 0x06, 0x75, 0x16};
    static_assert(kLifeStateRead[3] == (kActorLifeStateOffset & 0xFFu) && kLifeStateRead[4] == (kActorLifeStateOffset >> 8)
                  && kLifeStateRead[5] == 0 && kLifeStateRead[6] == 0);

    // Guarded reads only (an unreadable image answers false, never faults).
    template <std::size_t N>
    bool image_bytes_match(const std::byte* image, std::uint32_t rva, const std::uint8_t (&want)[N])
    {
        static_assert(N >= sizeof(std::uint32_t));
        if (!image) return false;
        for (std::uint32_t at = 0; at < N; at += sizeof(std::uint32_t))
        {
            // Whole 4-byte reads; the last one overlaps instead of running past the run.
            const std::uint32_t offset = at + sizeof(std::uint32_t) <= N
                ? at : static_cast<std::uint32_t>(N - sizeof(std::uint32_t));
            std::uint32_t expected = 0;
            std::uint32_t found = 0;
            std::memcpy(&expected, want + offset, sizeof(expected));
            if (!safe_read_u32(image, rva + offset, &found) || found != expected) return false;
        }
        return true;
    }

    bool life_state_read_site_ok(const std::byte* image)
    {
        return image_bytes_match(image, kLifeStateReadRva, kLifeStateRead)
            && image_bytes_match(image, kLifeStateKillTestRva, kLifeStateKillTest);
    }

    // ---- Implementation beta-burst r1: the energy code tied to the exe ----
    // Ten byte windows (158 bytes), read from the exe file 573AAFF1...545C by
                                                                          
    // sections. install() checks them after the hooks are in. A mismatch never
    // stops God Mode: the energy switches stay off and report
    // "not_supported/<name>".
    //   0x1A65A70  ApplyStatDiff jump targets, slots 7..9:
    //              stat 14 -> 0x1A6535B, stat 15 -> 0x1A6549E, stat 18 -> 0x1A6554E
    //   0x1A65A9D  ApplyStatDiff slot bytes of stats 14..19 (07 08 0E 0E 09 0A)
    //   0x1A6535B  mov edx,3Dh / mov rcx,rsi / call 0x1A64B40 / test al,al / je +9 /
    //              comiss xmm7,xmm6 / jb 0x1A65A4A      state 61 and diff < 0 -> "no change"
    //   0x1A65375  comiss xmm7,xmm6 / lea rdi,[rsi+150h] / movss xmm9,[rdi] / ...   current Beta
    //   0x1A653FA  cvttss2si eax,[rsi+154h] / cmp edx,eax / cmovl eax,edx          clamp to max Beta
    //   0x1A6554E  cvttss2si eax,[rsi+2E8h] / test eax,eax / jle 0x1A65A4A /
    //              comiss xmm7,xmm6 / lea rdi,[rsi+160h] / movss xmm9,[rdi] / ...   unlock, current Burst
    //   0x1A655DE  cvttss2si eax,[rsi+164h] / cmp ecx,eax / cmovl eax,ecx          clamp to max Burst
    //   0x1A65A4A  xor al,al / jmp 0x1A64FE5                                       the "no change" result
    //   0x1C770D3  comiss xmm7,[r15+160h] / jbe 0x1C7713D     skill cost <= Burst passes
    //   0x1C77133  comiss xmm7,[r15+150h] / ja 0x1C770DD      skill cost >  Beta fails
    constexpr std::uint32_t kEnergyStatDispatchRva = 0x1A65A70;
    constexpr std::uint8_t kEnergyStatDispatchBytes[] = {0x5B, 0x53, 0xA6, 0x01, 0x9E, 0x54, 0xA6, 0x01, 0x4E, 0x55, 0xA6, 0x01};
    constexpr std::uint32_t kEnergyStatSlotsRva = 0x1A65A9D;
    constexpr std::uint8_t kEnergyStatSlotsBytes[] = {0x07, 0x08, 0x0E, 0x0E, 0x09, 0x0A};
    constexpr std::uint32_t kEnergyBetaGateRva = 0x1A6535B;
    constexpr std::uint8_t kEnergyBetaGateBytes[] = {0xBA, 0x3D, 0x00, 0x00, 0x00, 0x48, 0x8B, 0xCE, 0xE8, 0xD8, 0xF7, 0xFF, 0xFF,
                                                     0x84, 0xC0, 0x74, 0x09, 0x0F, 0x2F, 0xFE, 0x0F, 0x82, 0xD5, 0x06, 0x00, 0x00};
    constexpr std::uint32_t kEnergyBetaStoreRva = 0x1A65375;
    constexpr std::uint8_t kEnergyBetaStoreBytes[] = {0x0F, 0x2F, 0xFE, 0x48, 0x8D, 0xBE, 0x50, 0x01, 0x00, 0x00, 0xF3, 0x44,
                                                      0x0F, 0x10, 0x0F, 0x0F, 0x28, 0xD7, 0x41, 0x0F, 0x28, 0xE1, 0x76, 0x5B};
    constexpr std::uint32_t kEnergyBetaClampRva = 0x1A653FA;
    constexpr std::uint8_t kEnergyBetaClampBytes[] = {0xF3, 0x0F, 0x2C, 0x86, 0x54, 0x01, 0x00, 0x00, 0x3B, 0xD0, 0x0F, 0x4C, 0xC2};
    constexpr std::uint32_t kEnergyBurstHeadRva = 0x1A6554E;
    constexpr std::uint8_t kEnergyBurstHeadBytes[] = {0xF3, 0x0F, 0x2C, 0x86, 0xE8, 0x02, 0x00, 0x00, 0x85, 0xC0, 0x0F, 0x8E, 0xEC,
                                                      0x04, 0x00, 0x00, 0x0F, 0x2F, 0xFE, 0x48, 0x8D, 0xBE, 0x60, 0x01, 0x00, 0x00,
                                                      0xF3, 0x44, 0x0F, 0x10, 0x0F, 0x41, 0x0F, 0x28, 0xE1, 0x76, 0x5B};
    constexpr std::uint32_t kEnergyBurstClampRva = 0x1A655DE;
    constexpr std::uint8_t kEnergyBurstClampBytes[] = {0xF3, 0x0F, 0x2C, 0x86, 0x64, 0x01, 0x00, 0x00, 0x3B, 0xC8, 0x0F, 0x4C, 0xC1};
    constexpr std::uint32_t kEnergyNoChangeExitRva = 0x1A65A4A;
    constexpr std::uint8_t kEnergyNoChangeExitBytes[] = {0x32, 0xC0, 0xE9, 0x94, 0xF5, 0xFF, 0xFF};
    constexpr std::uint32_t kEnergyCostBurstRva = 0x1C770D3;
    constexpr std::uint8_t kEnergyCostBurstBytes[] = {0x41, 0x0F, 0x2F, 0xBF, 0x60, 0x01, 0x00, 0x00, 0x76, 0x60};
    constexpr std::uint32_t kEnergyCostBetaRva = 0x1C77133;
    constexpr std::uint8_t kEnergyCostBetaBytes[] = {0x41, 0x0F, 0x2F, 0xBF, 0x50, 0x01, 0x00, 0x00, 0x77, 0xA0};
    // The offsets the hook reads are the ones inside those instructions.
    static_assert(kEnergyBetaStoreBytes[6] == (kBetaNowOffset & 0xFFu) && kEnergyBetaStoreBytes[7] == (kBetaNowOffset >> 8));
    static_assert(kEnergyBetaClampBytes[4] == (kBetaMaxOffset & 0xFFu) && kEnergyBetaClampBytes[5] == (kBetaMaxOffset >> 8));
    static_assert(kEnergyBurstHeadBytes[4] == (kBurstUnlockOffset & 0xFFu) && kEnergyBurstHeadBytes[5] == (kBurstUnlockOffset >> 8));
    static_assert(kEnergyBurstHeadBytes[22] == (kBurstNowOffset & 0xFFu) && kEnergyBurstHeadBytes[23] == (kBurstNowOffset >> 8));
    static_assert(kEnergyBurstClampBytes[4] == (kBurstMaxOffset & 0xFFu) && kEnergyBurstClampBytes[5] == (kBurstMaxOffset >> 8));
    static_assert(kEnergyCostBetaBytes[4] == (kBetaNowOffset & 0xFFu) && kEnergyCostBurstBytes[4] == (kBurstNowOffset & 0xFFu));

    // The name of the first window that does not match, or nullptr when all
    // ten do. Guarded reads only (an unreadable image is a mismatch).
    const char* energy_sites_failed(const std::byte* image)
    {
        if (!image_bytes_match(image, kEnergyStatDispatchRva, kEnergyStatDispatchBytes)) return "EnergyStatDispatch";
        if (!image_bytes_match(image, kEnergyStatSlotsRva, kEnergyStatSlotsBytes)) return "EnergyStatSlots";
        if (!image_bytes_match(image, kEnergyBetaGateRva, kEnergyBetaGateBytes)) return "EnergyBetaGate";
        if (!image_bytes_match(image, kEnergyBetaStoreRva, kEnergyBetaStoreBytes)) return "EnergyBetaStore";
        if (!image_bytes_match(image, kEnergyBetaClampRva, kEnergyBetaClampBytes)) return "EnergyBetaClamp";
        if (!image_bytes_match(image, kEnergyBurstHeadRva, kEnergyBurstHeadBytes)) return "EnergyBurstHead";
        if (!image_bytes_match(image, kEnergyBurstClampRva, kEnergyBurstClampBytes)) return "EnergyBurstClamp";
        if (!image_bytes_match(image, kEnergyNoChangeExitRva, kEnergyNoChangeExitBytes)) return "EnergyNoChangeExit";
        if (!image_bytes_match(image, kEnergyCostBurstRva, kEnergyCostBurstBytes)) return "EnergyCostBurst";
        if (!image_bytes_match(image, kEnergyCostBetaRva, kEnergyCostBetaBytes)) return "EnergyCostBeta";
        return nullptr;
    }

    bool __fastcall hook_actor_death_transition(void* actor, int cause_actor_guid, int hit_skill_id, int effect_id,
                                                void* output_actor, int cause_actor_runtime_id, void* output_data,
                                                std::uint8_t do_not_reset_sp_exp, void* optional_context,
                                                std::uint8_t force_dead, std::uint8_t local_request)
    {
        auto* transition = original<ActorDeathTransitionFn>(sites::kDeathTransition);
        if (!transition) return false; // unreachable: published before the entry jump

        const auto return_address = reinterpret_cast<std::uint64_t>(_ReturnAddress());
        // Self-check: DeadExecute passes the actor it looked up by the
        // command's ActorGUID (r13) at this exact call site.
        if (tl_dead_cmd_guid != 0 && return_address == g_ret_dead_network.load(std::memory_order_relaxed))
        {
            record_guid_sample(actor, tl_dead_cmd_guid, 2);
        }

        std::uint32_t actor_guid = 0;
        hook_read_actor_guid(actor, &actor_guid);
        const auto actor_dead_tick = GetTickCount();
        death_probe_publish(DpTransitionSeq, std::array<std::uint64_t, 6>{
            tl_death_probe_sequence, actor_dead_tick, GetCurrentThreadId(),
            reinterpret_cast<std::uint64_t>(actor), actor_guid, return_address});
        g_actor_dead_hits.fetch_add(1, std::memory_order_relaxed);
        const auto actor_dead_world_hit = g_actor_dead_world_hits.fetch_add(1, std::memory_order_relaxed) + 1u;
        g_actor_dead_last_actor.store(reinterpret_cast<std::uint64_t>(actor), std::memory_order_relaxed);
        g_actor_dead_last_guid.store(actor_guid, std::memory_order_relaxed);
        g_actor_dead_last_return_address.store(return_address, std::memory_order_relaxed);
        g_actor_dead_last_tick.store(actor_dead_tick, std::memory_order_relaxed);

        const auto actor_address = reinterpret_cast<std::uint64_t>(actor);
        const auto combat_guid = g_player_combat_guid.load(std::memory_order_relaxed);
        const auto setter_actor = g_setter_vital_last_actor.load(std::memory_order_relaxed);
        const auto setter_after_player_ms = g_setter_after_player_execute_ms.load(std::memory_order_relaxed);
        const auto setter_tick = g_setter_vital_tick.load(std::memory_order_relaxed);
        const auto player_execute_tick = g_last_player_execute_tick.load(std::memory_order_relaxed);
        const auto after_player_execute_ms = player_execute_tick != 0 ? actor_dead_tick - player_execute_tick : 0xFFFFFFFFu;
        const auto after_setter_ms = setter_tick != 0 ? actor_dead_tick - setter_tick : 0xFFFFFFFFu;
        g_actor_dead_after_player_execute_ms.store(after_player_execute_ms, std::memory_order_relaxed);
        g_actor_dead_after_setter_ms.store(after_setter_ms, std::memory_order_relaxed);

        const bool verified_shipping_caller = return_address == g_ret_dead_local.load(std::memory_order_relaxed);
        const bool live = god_live(std::memory_order_relaxed);
        const bool identity_verified = g_identity_verified.load(std::memory_order_relaxed);
        const bool stable_player_context = live && verified_shipping_caller && actor != nullptr && actor_guid != 0
            && combat_guid != 0 && identity_verified
            && g_learned_actor.load(std::memory_order_relaxed) != nullptr
            && g_hp_floor.load(std::memory_order_relaxed) > 0.0f
            && g_execute_player_vital_hits.load(std::memory_order_relaxed) > 0;
        const bool verified_by_setter = stable_player_context && setter_actor != 0 && actor_address == setter_actor
            && g_setter_vital_last_stat.load(std::memory_order_relaxed) == sbgod::kStatHp
            && g_setter_vital_last_value.load(std::memory_order_relaxed) <= 0.0f && setter_after_player_ms <= 64u;
        const auto execute_guid = g_execute_vital_last_guid.load(std::memory_order_relaxed);
        const auto execute_stat = g_execute_vital_last_stat.load(std::memory_order_relaxed);
        const auto execute_diff = g_execute_vital_last_diff.load(std::memory_order_relaxed);
        const auto execute_result = g_execute_vital_last_result.load(std::memory_order_relaxed);
        const auto fatal_guard_actor = g_fatal_guard_actor.load(std::memory_order_relaxed);
        const bool verified_by_recent_execute = stable_player_context && actor_guid == combat_guid
            && actor_dead_world_hit >= 2u && after_player_execute_ms <= 64u && execute_guid == combat_guid
            && (execute_stat == sbgod::kStatHp || execute_stat == sbgod::kStatShield) && execute_diff < 0.0f;
        const bool verified_by_latched_guard = stable_player_context && actor_guid == combat_guid
            && actor_dead_world_hit >= 2u && fatal_guard_actor != 0 && actor_address == fatal_guard_actor;
        std::uint32_t predicate_mask = 0;
        if (live) predicate_mask |= 1u << 0;
        if (verified_shipping_caller) predicate_mask |= 1u << 1;
        if (actor_guid != 0 && actor_guid == combat_guid) predicate_mask |= 1u << 2;
        if (after_player_execute_ms <= 64u) predicate_mask |= 1u << 3;
        if (execute_guid == combat_guid && combat_guid != 0) predicate_mask |= 1u << 4;
        if (execute_stat == sbgod::kStatHp || execute_stat == sbgod::kStatShield) predicate_mask |= 1u << 5;
        if (execute_diff < 0.0f) predicate_mask |= 1u << 6;
        if (execute_result <= 0.0f) predicate_mask |= 1u << 7;
        if (identity_verified) predicate_mask |= 1u << 8;
        if (g_learned_actor.load(std::memory_order_relaxed) != nullptr) predicate_mask |= 1u << 9;
        if (g_hp_floor.load(std::memory_order_relaxed) > 0.0f) predicate_mask |= 1u << 10;
        if (verified_by_setter) predicate_mask |= 1u << 11;
        if (verified_by_recent_execute) predicate_mask |= 1u << 12;
        if (actor_dead_world_hit >= 2u) predicate_mask |= 1u << 13;
        if (verified_by_latched_guard) predicate_mask |= 1u << 14;

        // Implementation r2 on the v4 probe source (offline tested only,
        // not installed, not live-tested): forced deaths.
        //
        // The 8th argument (named do_not_reset_sp_exp above) is the game's
        // death kind. Exe 573AAFF1...545C, DeathTransition 0x1A6ED60 reads the
        // actor life state (ESBActorLifeState) at [r14+2600h] (0x1A6EEEF;
        // bytes checked at install, life_state_read_site_ok), then the kind
        // at [rbp+0C8h]:
        //   life state 2 (Coma): only kind 1 proceeds (0x1A6EEFB); any other
        //     kind returns false at 0x1A6EF7B;
        //   life state 1 (Spawn, i.e. alive) or 6 (Spawning), 0x1A6EF5B..63:
        //     kind 0 with HP > 0 returns false at 0x1A6EF7B (the game's own
        //     re-check, the path F1 relies on); kind != 0 jumps to 0x1A6EFB4,
        //     calls SetActorStat(E, HP, 0.0) and then writes life state 3
        //     (Dead) at 0x1A6F0AC with no HP re-check, so God's setter block
        //     keeps the HP number and Eve goes down anyway;
        //   every other life state (0 None, 3 Dead, 4 Despawn, 5 Destroy)
        //     returns false at 0x1A6EF7B.
        // Where the kind comes from (all through the local death function
        // 0x1BAE5D0, kind = its 6th argument, forwarded at 0x1BAE891):
        //   kind 1: effect action 49 ImmediateDeath (0x1BC9C66), constant 1 at
        //     0x1BA0A5F and 0x1BB0671: level kill volumes, falls, lasers, the
        //     sand trap, summons, and at 0x1BB0671 an actor whose HP is
        //     already 0. Falls and kill volumes need the death to warp Eve
        //     back, so kind 1 passes.
        //   kind 2: exactly one code source, effect action 50
        //     ImmediateDeathPossibleRevival (`C6 44 24 28 02` at 0x1BC9CAE),
        //     i.e. EffectTable row 315, applied by four boss attacks:
        //     Providence area bomb (effect 5054106, skill 5054033), Raven
        //     Beast FlyRoutine2_Hit1, Elder phase 2 KillRoutine2_Hit1,
        //     Scarlet PhaseChange1_EndShieldOwn_Hit1. The deferral records
        //     replay the stored kind through the same local death function
        //     and reach this hook with the same return address.
        // The block needs kind 2, the proven local caller, the armed,
        // verified, current Eve and life state 1 or 6: the only two life
        // states in which the game's function can kill. That is not proof
        // the game would have killed on this very call: before it reads the
        // life state the game can already answer "not dead" (failed lookups,
        // 0x1A6EDE0 and 0x1A6EDF4), and it does work there that a block
        // skips (a one-time call at 0x1A6EE0E, calls on both sides of the
        // actor flag +0x49A at 0x1A6EE19..0x1A6EEC2, a counter add at
        // 0x1A6EEEC). So actor_dead_blocks can be a little higher than the
        // deaths really stopped, and what skipping that work does is not
        // known. Returning false without calling the original is this
        // function's own "not dead" result: the local caller tests it at
        // 0x1BAE8B1 (`test al,al / je 0x1BAF282`) and creates no Dead command
        // (created only later, at 0x1BAE91E). Nothing is written to the game;
        // both callers zero the two output slots themselves. Life states
        // 0/2/3/4/5 and an unreadable life state go to the original, which
        // returns false there by itself: telemetry only, never counted as a
        // block. The predicate has no time window, so a repeated request is
        // answered the same way.
        //
        // actor_dead_predicate_mask bits added here:
        //   15 kind 1, 16 kind 2: the call just seen (any actor).
        //   17-31 are Eve's record. They are carried over from call to call,
        //   so the death of another actor does not erase them;
        //   reset_god_runtime_caches clears them with the rest of the mask.
        //     17    a kind-2 request aimed at the protected Eve by the local
        //           caller was seen; 18-22 describe the latest one:
        //     18    its life state was read, 19-21 the value (7 = 7 or more),
        //     22    it was blocked;
        //     23-29 life states 0..6 seen on such requests so far;
        //     30    a request whose life state could not be read was seen;
        //     31    a kind-2 request aimed at the protected Eve came from a
        //           caller other than the local one (never blocked: the
        //           "not dead" answer is only proven for the local caller).
        // The record is read, changed and stored without a lock, as this mask
        // always was: two calls at the same instant on different threads
        // could lose one update of the record. The block decision and the
        // counters do not depend on it.
        constexpr std::uint32_t kEveRecordBits = 0xFFFE0000u; // 17-31
        constexpr std::uint32_t kEveSeenBits = 0xFF800000u;   // 23-31
        const std::uint8_t death_kind = do_not_reset_sp_exp;
        if (death_kind == 1u) predicate_mask |= 1u << 15;
        if (death_kind == 2u) predicate_mask |= 1u << 16;
        std::uint32_t eve_record = g_actor_dead_predicate_mask.load(std::memory_order_relaxed) & kEveRecordBits;
        const bool protected_eve = (death_kind == 1u || death_kind == 2u) && actor != nullptr
            && g_identity_verified.load(std::memory_order_acquire) && god_live()
            && is_protected_actor(actor) && god_live();
        bool block = false;
        if (protected_eve && death_kind == 2u)
        {
            if (!verified_shipping_caller) eve_record |= 1u << 31;
            else
            {
                eve_record = (eve_record & kEveSeenBits) | (1u << 17);
                std::uint32_t life_state = 0;
                if (safe_read_u32(actor, kActorLifeStateOffset, &life_state))
                {
                    const std::uint32_t shown = life_state < 7u ? life_state : 7u;
                    eve_record |= (1u << 18) | (shown << 19);
                    if (shown < 7u) eve_record |= 1u << (23u + shown);
                    block = life_state == 1u || life_state == 6u;
                    if (block) eve_record |= 1u << 22;
                }
                else eve_record |= 1u << 30;
            }
        }
        // A kind-1 death of the same Eve while she still has HP is the game's
        // own rule (fall, kill volume, laser). HP is Stat[1] at +0x11C, the
        // float the game itself tests at 0x1A6EF68; it is read before the
        // game zeroes it. One kind-1 source follows real damage: 0x1BB063B
        // (`cvttss2si eax,[rsi+11Ch] / test eax,eax / jg`) asks for kind 1
        // only when int(HP) <= 0, i.e. HP below 1. "HP >= 1" excludes exactly
        // that source, so such a death stays a leak.
        const bool design_death = protected_eve && death_kind == 1u && verified_shipping_caller
            && read_stat(actor, sbgod::kStatHp) >= 1.0f;
        predicate_mask |= eve_record;
        g_actor_dead_predicate_mask.store(predicate_mask, std::memory_order_relaxed);
        if (block)
        {
            g_actor_dead_blocks.fetch_add(1, std::memory_order_relaxed);
            g_blocks.fetch_add(1, std::memory_order_relaxed);
            note_hit_event(id::HitEvent::DeathBlocked);
            return false;
        }

        // Every other call goes to the game unchanged. (v1.0.26 judged this
        // result "ignored" from FSBActorDead::Execute's call 0x1B201BA, which
        // runs only when the cached net mode is 3; in single player the local
        // caller above is the only one and it does test the result.)
        const bool died = transition(actor, cause_actor_guid, hit_skill_id, effect_id, output_actor,
                                     cause_actor_runtime_id, output_data, do_not_reset_sp_exp, optional_context,
                                     force_dead, local_request);
        // The game accepted a death: tell hook_actor_dead_execute whether the
        // Dead command that follows is a by-design one. Any other accepted
        // death of the same GUID withdraws an unused mark, so a real death
        // can never inherit it.
        if (died && actor_guid != 0)
        {
            if (design_death) g_design_death_guid.store(actor_guid, std::memory_order_release);
            else
            {
                auto unused_mark = actor_guid;
                g_design_death_guid.compare_exchange_strong(unused_mark, 0, std::memory_order_acq_rel);
            }
        }
        return died;
    }

    void __fastcall hook_actor_apply_stat_execute(void* apply_stat)
    {
        auto* apply_execute = original<ActorApplyStatExecuteFn>(sites::kApplyStatExecute);
        g_execute_hits.fetch_add(1, std::memory_order_relaxed);
        if (!apply_execute) return; // unreachable: published before the entry jump

        // FSBActorApplyStat layout, proven by the ApplyStat anchors:
        // ActorGUID +0x10, StatType +0x14, DiffValue +0x18, ResultValue +0x24.
        std::uint32_t actor_guid = 0;
        int stat_type = -1;
        float diff_value = 0.0f;
        float result_value = 0.0f;
        bool fields_ok = false;
        if (apply_stat)
        {
            __try
            {
                auto* bytes = reinterpret_cast<std::uint8_t*>(apply_stat);
                actor_guid = *reinterpret_cast<std::uint32_t*>(bytes + 0x10);
                stat_type = *reinterpret_cast<int*>(bytes + 0x14);
                diff_value = *reinterpret_cast<float*>(bytes + 0x18);
                result_value = *reinterpret_cast<float*>(bytes + 0x24);
                fields_ok = true;
            }
            __except (probe_filter(GetExceptionInformation(), apply_stat, 0x28, "god_apply_command_read"))
            {
                sbcore::fault::after_handler();
                fields_ok = false;
            }
        }
        if (fields_ok) note_apply_command_guid(actor_guid);

        const auto previous_cmd_guid = tl_apply_cmd_guid;
        // v1.3.1 F2: a damage command for the ready candidate's GUID before
        // the arm is consumed (the command itself was the S9 evidence above).
        if (fields_ok && id::is_vital_damage(stat_type, diff_value) && !god_live() && is_ready_candidate_guid(actor_guid))
        {
            g_prearm_blocks.fetch_add(1, std::memory_order_relaxed);
            return;
        }
        if (!fields_ok || !god_live())
        {
            tl_apply_cmd_guid = fields_ok ? actor_guid : 0;
            apply_execute(apply_stat);
            tl_apply_cmd_guid = previous_cmd_guid;
            return;
        }

        g_last_stat.store(stat_type, std::memory_order_relaxed);
        const bool vital = stat_type == sbgod::kStatHp || stat_type == sbgod::kStatShield;
        if (vital)
        {
            g_execute_vital_hits.fetch_add(1, std::memory_order_relaxed);
            g_execute_vital_last_guid.store(actor_guid, std::memory_order_relaxed);
            g_execute_vital_last_stat.store(stat_type, std::memory_order_relaxed);
            g_execute_vital_last_diff.store(diff_value, std::memory_order_relaxed);
            g_execute_vital_last_result.store(result_value, std::memory_order_relaxed);
        }
        if (!vital)
        {
            tl_apply_cmd_guid = actor_guid;
            apply_execute(apply_stat);
            tl_apply_cmd_guid = previous_cmd_guid;
            return;
        }

        // The command GUID is resolved by the game in the same actor table the
        // identity pass proved maps the verified GUID to the verified actor.
        const bool is_player = is_player_execute_apply(actor_guid);
        if (is_player)
        {
            g_execute_player_vital_hits.fetch_add(1, std::memory_order_relaxed);
            g_last_player_execute_tick.store(GetTickCount(), std::memory_order_relaxed);

            float preserve_value = (stat_type == sbgod::kStatHp)
                ? std::max(g_sim_hp_floor.load(std::memory_order_relaxed), g_hp_floor.load(std::memory_order_relaxed))
                : g_sim_shield_floor.load(std::memory_order_relaxed);
            void* learned = g_learned_actor.load(std::memory_order_relaxed);
            if (learned != nullptr && is_confirmed_player_actor(learned))
            {
                const float live_value = (stat_type == sbgod::kStatHp) ? read_player_hp(learned)
                                                                       : read_stat(learned, sbgod::kStatShield);
                if (std::isfinite(live_value) && live_value > preserve_value) preserve_value = live_value;
            }
            const bool negative_damage = diff_value < 0.0f;
            if (negative_damage && std::isfinite(result_value))
            {
                // ResultValue is authoritative post-change state. Reconstruct
                // the pre-damage value so the first protected hit is safe.
                const float pre_damage_value = result_value - diff_value;
                const float sane_max = (stat_type == sbgod::kStatHp) ? sbgod::kMaxPlayerHp : sbgod::kMaxPlayerShield;
                if (pre_damage_value > 0.0f && pre_damage_value <= sane_max && pre_damage_value > preserve_value)
                    preserve_value = pre_damage_value;
            }
            const bool result_would_drop = preserve_value > 0.0f && result_value + 0.5f < preserve_value;
            if (negative_damage || result_would_drop)
            {
                // Consume only the verified player damage event before its
                // downstream fatal setter path can run (v1.0.36 behaviour).
                g_execute_blocks.fetch_add(1, std::memory_order_relaxed);
                g_blocks.fetch_add(1, std::memory_order_relaxed);
                note_hit_event(id::HitEvent::ApplyConsumed);
                return;
            }
        }

        // v1.3.0: this vital command is passed through while God is armed.
        // If it lowers the verified actor's HP/Shield, damage reached Eve
        // (read-only; the per-tick restore still repairs the pool). v1.3.1:
        // telemetry (apply_drops); the next tick classifies the drop as
        // repaired or leaked, so one dip is never counted twice.
        void* watched = g_learned_actor.load(std::memory_order_relaxed);
        const bool watch = watched != nullptr && is_confirmed_player_actor(watched);
        const float watched_hp_before = watch ? read_player_hp(watched) : 0.0f;
        const float watched_shield_before = watch ? read_stat(watched, sbgod::kStatShield) : 0.0f;

        const bool previous_scope = g_in_player_execute_apply;
        g_in_player_execute_apply = is_player;
        tl_apply_cmd_guid = actor_guid;
        apply_execute(apply_stat);
        tl_apply_cmd_guid = previous_cmd_guid;
        g_in_player_execute_apply = previous_scope;

        if (watch && god_live(std::memory_order_relaxed) && is_confirmed_player_actor(watched))
        {
            const float hp_after = read_player_hp(watched);
            const float shield_after = read_stat(watched, sbgod::kStatShield);
            if (std::isfinite(hp_after) && std::isfinite(watched_hp_before) && hp_after + 0.5f < watched_hp_before)
            {
                g_apply_leak_last_guid.store(actor_guid, std::memory_order_relaxed);
                g_apply_drops.fetch_add(1, std::memory_order_relaxed);
            }
            else if (std::isfinite(shield_after) && std::isfinite(watched_shield_before)
                     && shield_after + 0.5f < watched_shield_before)
            {
                g_shield_drops.fetch_add(1, std::memory_order_relaxed);
            }
        }
    }

    // v1.3.1 F1/F2: FSB actor ApplyStatDiff 0x1A64CE0, called by the
    // server-side stat apply (0x1BA881E, every damage/heal source) and by
    // ApplyStatExecute's replay (0x1B1F826); no other caller or reference
    // exists (verify_sites.py). Returning false without calling the original
    // is the function's own "no change" result (0x1A65A4A `xor al,al`, also
    // taken for an HP-immune actor): the server apply exits at 0x1BA9683 with
    // no Stat[] write, no ApplyStat command, no pending death. Only a finite
    // negative HP/Shield change of the proven Eve is withheld; every other
    // call goes to the game unchanged, and nothing is ever written here.
    bool __fastcall hook_apply_stat_diff(void* actor, int stat_type, void* context, float diff, std::uint8_t arg5,
                                         std::uint8_t arg6, int arg7)
    {
        auto* apply_diff = original<ApplyStatDiffFn>(sites::kApplyStatDiff);
        if (!apply_diff) return false; // unreachable: published before the entry jump

        // S9 evidence: the game changes a stat of the identity candidate.
        const bool candidate = note_diff_hook_actor(actor);
        if (id::is_vital_damage(stat_type, diff))
        {
            const auto return_address = reinterpret_cast<std::uint64_t>(_ReturnAddress());
            // god_live() first: the heartbeat's `checks` keeps counting only
            // protection decisions made while armed (enemy hits pass here too).
            if (god_live() && is_protected_actor(actor))
            {
                g_diff_blocks.fetch_add(1, std::memory_order_relaxed);
                if (return_address == g_ret_diff_echo.load(std::memory_order_relaxed))
                    g_diff_echo_blocks.fetch_add(1, std::memory_order_relaxed);
                g_blocks.fetch_add(1, std::memory_order_relaxed);
                note_hit_event(id::HitEvent::DiffBlocked);
                return false;
            }
            if (candidate && is_ready_candidate(actor))
            {
                g_prearm_blocks.fetch_add(1, std::memory_order_relaxed);
                return false;
            }
            // A hit that lands while God is wanted but not armed yet (loading,
            // S7/S8 still running): counted once, at the server-side apply.
            if (candidate && g_desired_god.load(std::memory_order_relaxed) && !god_live(std::memory_order_relaxed)
                && return_address == g_ret_diff_server.load(std::memory_order_relaxed))
            {
                g_unarmed_hits.fetch_add(1, std::memory_order_relaxed);
            }
        }
        // Implementation beta-burst r1 (offline tested only). Stat 14 /
        // 18 of the verified Eve while that gauge's switch is armed: a spend
        // is answered "no change" (this function's own result), a gain is
        // raised to max - current (the game clamps and reports it itself).
        // Every other call, every other actor and every other stat reaches
        // the game exactly as before. Reads only; nothing is written.
        const auto energy_return = reinterpret_cast<std::uint64_t>(_ReturnAddress());
        energy_note_server_call(actor, energy_return);
        if (stat_type == kStatBetaGauge || stat_type == kStatBurstGauge)
        {
            float raised = diff;
            switch (energy_decide(actor, stat_type, diff, energy_return, &raised))
            {
            case EnergyAction::Refuse: return false;
            case EnergyAction::Raise: diff = raised; break;
            case EnergyAction::Pass: break;
            }
        }
        return apply_diff(actor, stat_type, context, diff, arg5, arg6, arg7);
    }

    // ---- GameThread identity (UObject work + read-only chain) ----------------

    bool plausible_object(const void* object)
    {
        // 0x10000 <= address <= 0x7FFFFFFFFFFF and a readable first pointer
        // (identical to the v1.1.2 helper; now sbcore's shared probe).
        return sbcore::memory::plausible_object(object);
    }

    void* property_value_ptr(RC::Unreal::UObject* object, const wchar_t* name)
    {
        if (!plausible_object(object)) return nullptr;
        void* field{};
        try
        {
            field = object->GetValuePtrByPropertyNameInChain(name);
        }
        catch (...)
        {
            return nullptr;
        }
        return sites::is_readable_region(field, sizeof(std::uint32_t), false) ? field : nullptr;
    }

    RC::Unreal::UObject* object_property(RC::Unreal::UObject* object, const wchar_t* name)
    {
        void* field = property_value_ptr(object, name);
        if (!field || !sites::is_readable_region(field, sizeof(void*), false)) return nullptr;
        auto* value = *reinterpret_cast<RC::Unreal::UObject**>(field);
        return plausible_object(value) ? value : nullptr;
    }

    std::uint64_t qpc_us()
    {
        LARGE_INTEGER frequency{};
        LARGE_INTEGER now{};
        QueryPerformanceFrequency(&frequency);
        QueryPerformanceCounter(&now);
        const auto f = static_cast<std::uint64_t>(frequency.QuadPart > 0 ? frequency.QuadPart : 1);
        const auto t = static_cast<std::uint64_t>(now.QuadPart);
        return (t / f) * 1'000'000ULL + (t % f) * 1'000'000ULL / f;
    }

    void store_max(std::atomic<std::uint64_t>& target, std::uint64_t value)
    {
        auto current = target.load(std::memory_order_relaxed);
        while (value > current && !target.compare_exchange_weak(current, value, std::memory_order_relaxed)) {}
    }

    // GameThread only (inside the certified TaskGraph callback). The only
    // UObject work in this DLL: find the local player's controller, pawn and
    // PlayerState, read PlayerState.ActorNetGuid (ASBNetworkPlayerState
    // +0x3C8 in the CXXHeaderDump) for the S7 cross-check and, v1.3.0,
    // PlayerState.PlayerId (APlayerState +0x2CC) for the S9' player link.
    id::UeSnapshot gt_run_ue_pass(std::uint64_t now_ms)
    {
        id::UeSnapshot ue{};
        ue.ran = true;
        ue.ran_ms = now_ms;
        const auto start = qpc_us();
        std::vector<RC::Unreal::UObject*> controllers{};
        try
        {
            RC::Unreal::UObjectGlobals::FindAllOf(L"SBNetworkPlayerController", controllers);
        }
        catch (...)
        {
            ue.exception = true;
        }
        RC::Unreal::UObject* chosen = nullptr;
        for (auto* controller : controllers)
        {
            if (!plausible_object(controller)) continue;
            ++ue.controllers_found;
            auto* pawn = object_property(controller, L"Pawn");
            if (!pawn) continue;
            ++ue.controllers_viable;
            if (!chosen)
            {
                chosen = controller;
                ue.controller = reinterpret_cast<std::uint64_t>(controller);
                ue.pawn = reinterpret_cast<std::uint64_t>(pawn);
            }
        }
        if (chosen && ue.controllers_viable == 1)
        {
            auto* acknowledged = object_property(chosen, L"AcknowledgedPawn");
            ue.pawn_acknowledged = acknowledged != nullptr && reinterpret_cast<std::uint64_t>(acknowledged) == ue.pawn;
            if (auto* player_state = object_property(chosen, L"PlayerState"))
            {
                ue.player_state = reinterpret_cast<std::uint64_t>(player_state);
                // v1.3.0 (S9'): the exact class, from the object's own full
                // name ("SBNetworkPlayerState /Game/...PersistentLevel.
                                                                              
                // failure here only withholds the direct proof.
                try
                {
                    const std::wstring full_name = player_state->GetFullName();
                    ue.player_state_class_ok =
                        id::full_name_class_is(full_name.c_str(), full_name.size(), id::kPlayerStateClassName);
                }
                catch (...)
                {
                    ue.player_state_class_ok = false;
                }
                if (void* field = property_value_ptr(player_state, L"ActorNetGuid"))
                {
                    ue.netguid_field = reinterpret_cast<std::uint64_t>(field);
                    std::uint32_t raw = 0;
                    if (safe_read_u32(field, 0, &raw))
                    {
                        ue.netguid_value = static_cast<std::int32_t>(raw);
                        ue.netguid_read = true;
                    }
                }
                // v1.3.0 (S9'): APlayerState::PlayerId through reflection;
                // direct_proof() requires the address to be +0x2CC.
                if (void* field = property_value_ptr(player_state, L"PlayerId"))
                {
                    ue.player_id_field = reinterpret_cast<std::uint64_t>(field);
                    std::uint32_t raw = 0;
                    if (safe_read_u32(field, 0, &raw))
                    {
                        ue.player_id_value = static_cast<std::int32_t>(raw);
                        ue.player_id_read = true;
                    }
                }
            }
        }
        const auto elapsed = qpc_us() - start;
        g_identity_count.fetch_add(1, std::memory_order_relaxed);
        g_identity_last_us.store(elapsed, std::memory_order_relaxed);
        store_max(g_identity_max_us, elapsed);
        g_identity_pawn_found.store(ue.pawn != 0, std::memory_order_release);
        g_player_controller_ptr.store(ue.controller, std::memory_order_relaxed);
        g_actor_ptr.store(ue.pawn, std::memory_order_relaxed);
        g_player_state_ptr.store(ue.player_state, std::memory_order_relaxed);
        return ue;
    }

    void publish_ue(const id::UeSnapshot& ue)
    {
        g_ue_ran.store(ue.ran, std::memory_order_relaxed);
        g_ue_exception.store(ue.exception, std::memory_order_relaxed);
        g_ue_controllers_found.store(ue.controllers_found, std::memory_order_relaxed);
        g_ue_controllers_viable.store(ue.controllers_viable, std::memory_order_relaxed);
        g_ue_pawn_acknowledged.store(ue.pawn_acknowledged, std::memory_order_relaxed);
        g_ue_netguid_field.store(ue.netguid_field, std::memory_order_relaxed);
        g_ue_netguid_value.store(ue.netguid_value, std::memory_order_relaxed);
        g_ue_class_ok.store(ue.player_state_class_ok, std::memory_order_relaxed);
        g_ue_netguid_read.store(ue.netguid_read, std::memory_order_relaxed);
        g_ue_player_id.store(ue.player_id_read ? ue.player_id_value : 0, std::memory_order_relaxed);
        g_ue_player_id_at_offset.store(ue.player_id_field != 0
                                           && ue.player_id_field == ue.player_state + id::kPlayerStatePlayerIdOffset,
                                       std::memory_order_relaxed);
    }

    void clear_verified_identity()
    {
        g_identity_verified.store(false, std::memory_order_release);
        g_learned_actor.store(nullptr, std::memory_order_release);
        g_learned_guid.store(0, std::memory_order_release);
        g_player_guid.store(0, std::memory_order_relaxed);
        g_player_combat_guid.store(0, std::memory_order_relaxed);
        g_bag_ptr.store(0, std::memory_order_relaxed);
    }

    void publish_candidate(std::uint64_t actor, std::uint32_t guid)
    {
        g_cand_actor_pub.store(0, std::memory_order_release);
        g_cand_guid_pub.store(0, std::memory_order_release);
        g_cand_corroborations.store(0, std::memory_order_release);
        g_cand_guid_pub.store(guid, std::memory_order_release);
        g_cand_actor_pub.store(actor, std::memory_order_release);
    }

    // v1.3.1 F2: GameThread only. (0, 0) withdraws the ready pair.
    void publish_ready(std::uint64_t actor, std::uint32_t guid)
    {
        if (actor == 0 || guid == 0)
        {
            g_ready_actor.store(0, std::memory_order_release);
            g_ready_guid.store(0, std::memory_order_release);
            return;
        }
        if (g_ready_actor.load(std::memory_order_relaxed) == actor && g_ready_guid.load(std::memory_order_relaxed) == guid)
            return;
        g_ready_actor.store(0, std::memory_order_release);
        g_ready_guid.store(guid, std::memory_order_release);
        g_ready_actor.store(actor, std::memory_order_release);
    }

    void reset_identity_tracking()
    {
        // v1.3.1: the resume memory survives God off (id::reset_tracker).
        id::reset_tracker(gt_tracker);
        gt_ue = id::UeSnapshot{};
        publish_ue(gt_ue);
        publish_candidate(0, 0);
        publish_ready(0, 0);
        gt_ready_pending = false;
        clear_verified_identity();
        g_arm_path.store(id::ArmPath::None, std::memory_order_relaxed);
        g_direct_proof.store(id::DirectProof::NotChecked, std::memory_order_relaxed);
    }

    ReflectStatus reflect_status_for(const id::Verdict& v, const id::ChainSample& s)
    {
        if (v.verified) return ReflectStatus::Pass;
        switch (v.reason)
        {
        case id::Reason::Chain:
            return (s.step == id::Step::GuidMapMismatch || s.step == id::Step::GuidMapMissing
                    || s.step == id::Step::GuidMapNotLive || s.step == id::Step::TableIdNotEve)
                ? ReflectStatus::GuidMismatch
                : ReflectStatus::NoActor;
        case id::Reason::StatsNotEveScale: return ReflectStatus::StatsImplausible;
        case id::Reason::NetGuidMismatch: return ReflectStatus::GuidMismatch;
        case id::Reason::NoController:
        case id::Reason::ControllerAmbiguous:
        case id::Reason::NoPawn:
        case id::Reason::PawnNotAcknowledged:
        case id::Reason::NoPlayerState:
        case id::Reason::UeException: return ReflectStatus::NoPawn;
        default: return ReflectStatus::Pending;
        }
    }

    // GameThread only: one identity tick (chain every tick, UE pass only
    // while a candidate is being verified).
    void gt_identity_tick(std::uint64_t now_ms)
    {
        const auto sample = id::sample_chain(g_image);
        auto verdict = id::evaluate(gt_tracker, sample, gt_ue, g_cand_corroborations.load(std::memory_order_acquire),
                                    now_ms);
        if (verdict.candidate_changed)
        {
            gt_ue = id::UeSnapshot{};
            publish_candidate(sample.step == id::Step::Ok ? sample.actor : 0,
                              sample.step == id::Step::Ok ? sample.guid : 0);
            publish_ready(0, 0);
            clear_verified_identity();
            // v1.3.1 F5: every candidate change is logged (step, E, G).
            gt_log_event(LogKind::Candidate, sample.step == id::Step::Ok ? sample.actor : 0,
                         sample.step == id::Step::Ok ? sample.guid : 0, gt_tracker.candidate_changes,
                         static_cast<std::uint64_t>(sample.eventor_guid), 0, static_cast<std::uint32_t>(sample.step),
                         static_cast<std::uint32_t>(verdict.reason));
        }
        if (verdict.want_ue_check)
        {
            gt_ue = gt_run_ue_pass(now_ms);
            // Same chain sample, re-judged with the fresh UE snapshot: not a new sample.
            verdict = id::evaluate(gt_tracker, sample, gt_ue, g_cand_corroborations.load(std::memory_order_acquire),
                                   now_ms, false);
        }
        publish_ue(gt_ue);

        g_id_step.store(sample.step, std::memory_order_relaxed);
        g_id_client.store(sample.client, std::memory_order_relaxed);
        g_id_holder.store(sample.holder, std::memory_order_relaxed);
        g_id_index.store(sample.index, std::memory_order_relaxed);
        g_id_count.store(sample.count, std::memory_order_relaxed);
        g_id_actor.store(sample.actor, std::memory_order_relaxed);
        g_id_vtables_ok.store(sample.vtables_ok, std::memory_order_relaxed);
        g_id_guid.store(sample.guid, std::memory_order_relaxed);
        g_id_mapped_actor.store(sample.mapped_actor, std::memory_order_relaxed);
        g_id_table_id.store(sample.table_id, std::memory_order_relaxed);
        g_id_hp.store(sample.hp, std::memory_order_relaxed);
        g_id_max_hp.store(sample.max_hp, std::memory_order_relaxed);
        g_id_player_id.store(sample.player_id_read ? sample.player_id : 0, std::memory_order_relaxed);
        g_eventor_guid.store(sample.eventor_read ? sample.eventor_guid : 0, std::memory_order_relaxed);
        gt_ready_pending = verdict.ready && sample.step == id::Step::Ok;
        gt_ready_actor = gt_ready_pending ? sample.actor : 0;
        gt_ready_guid = gt_ready_pending ? sample.guid : 0;
        g_id_stable_ms.store(verdict.stable_ms, std::memory_order_relaxed);
        g_id_samples.store(gt_tracker.cand_samples, std::memory_order_relaxed);
        g_id_candidate_changes.store(gt_tracker.candidate_changes, std::memory_order_relaxed);
        g_direct_proof.store(verdict.direct, std::memory_order_relaxed);
        g_arm_path.store(verdict.verified ? verdict.arm_path : id::ArmPath::None, std::memory_order_relaxed);
        g_id_reason.store(verdict.reason, std::memory_order_release);

        if (sample.step == id::Step::Ok)
        {
            g_sc_reflect_samples.fetch_add(1, std::memory_order_relaxed);
            g_sc_reflect_source.store(ReflectSource::LocalClientChain, std::memory_order_relaxed);
        }
        if (verdict.verified) g_sc_reflect_passes.fetch_add(1, std::memory_order_relaxed);
        if (verdict.reason == id::Reason::NetGuidMismatch
            || (verdict.reason == id::Reason::Chain
                && (sample.step == id::Step::GuidMapMismatch || sample.step == id::Step::GuidMapNotLive)))
        {
            g_sc_reflect_mismatches.fetch_add(1, std::memory_order_relaxed);
        }
        g_sc_reflect_status.store(reflect_status_for(verdict, sample), std::memory_order_release);

        if (verdict.verified)
        {
            auto* actor = reinterpret_cast<void*>(sample.actor);
            if (g_learned_actor.load(std::memory_order_relaxed) != actor
                || g_learned_guid.load(std::memory_order_relaxed) != sample.guid)
            {
                g_combat_guid_binds.fetch_add(1, std::memory_order_relaxed);
            }
            g_learned_guid.store(sample.guid, std::memory_order_release);
            g_learned_actor.store(actor, std::memory_order_release);
            g_player_guid.store(sample.guid, std::memory_order_relaxed);
            g_player_combat_guid.store(sample.guid, std::memory_order_relaxed);
            g_bag_ptr.store(sample.actor, std::memory_order_relaxed);
            g_identity_verified.store(true, std::memory_order_release);
        }
        else
        {
            clear_verified_identity();
        }
    }

    // GameThread only: arm/disarm transitions. Floors are computed from the
    // verified actor before protection becomes visible to the hooks.
    void gt_apply_arming(bool armed_next, std::uint64_t now_ms)
    {
        const bool rearm = armed_next && !gt_prev_armed;
        if (!armed_next)
        {
            g_god_live.store(false, std::memory_order_release);
            if (gt_prev_armed)
            {
                // v1.3.1 F5: the ended arm's totals and why it ended.
                const auto fh = g_first_hit.snapshot();
                gt_log_event(LogKind::Disarmed, gt_armed_actor, gt_armed_guid, fh.blocked, fh.repairs + fh.lethal_saved,
                             fh.leaks, static_cast<std::uint32_t>(g_id_reason.load(std::memory_order_relaxed)),
                             static_cast<std::uint32_t>(g_id_step.load(std::memory_order_relaxed)));
                gt_armed_actor = 0;
                gt_armed_guid = 0;
                reset_god_runtime_caches();
                g_first_hit.disarm();
            }
            gt_fh_prev_valid = false;
            gt_prev_armed = false;
            return;
        }
        if (rearm)
        {
            reset_god_runtime_caches();
            arm_god_floors_from_actor(g_learned_actor.load(std::memory_order_acquire));
            // v1.3.0: every arm is followed by a first-hit watch.
            const auto path = g_arm_path.load(std::memory_order_relaxed);
            g_last_arm_path.store(path, std::memory_order_relaxed);
            if (path == id::ArmPath::Eventor) g_fast_arms.fetch_add(1, std::memory_order_relaxed);
            else if (path == id::ArmPath::Resume) g_resume_arms.fetch_add(1, std::memory_order_relaxed);
            else g_hook_arms.fetch_add(1, std::memory_order_relaxed);
            const auto after_ms = now_ms >= gt_tracker.cand_since_ms ? now_ms - gt_tracker.cand_since_ms : 0;
            g_arm_after_candidate_ms.store(after_ms, std::memory_order_relaxed);
            gt_fh_prev_valid = false;
            gt_armed_ms = now_ms;
            g_first_hit.arm(now_ms);
            gt_logged_leaks = 0;
            gt_armed_actor = reinterpret_cast<std::uint64_t>(g_learned_actor.load(std::memory_order_relaxed));
            gt_armed_guid = g_learned_guid.load(std::memory_order_relaxed);
            gt_log_event(LogKind::Armed, gt_armed_actor, gt_armed_guid, after_ms,
                         g_unarmed_hits.load(std::memory_order_relaxed), g_prearm_blocks.load(std::memory_order_relaxed),
                         static_cast<std::uint32_t>(path), static_cast<std::uint32_t>(g_direct_proof.load(std::memory_order_relaxed)));
        }
        g_god_live.store(true, std::memory_order_release);
        gt_prev_armed = true;
        // v1.3.1 F5: a real leak is logged when it happens (once per new leak count).
        const auto fh = g_first_hit.snapshot();
        if (fh.leaks > gt_logged_leaks)
        {
            gt_logged_leaks = fh.leaks;
            gt_log_event(LogKind::Leak, reinterpret_cast<std::uint64_t>(g_learned_actor.load(std::memory_order_relaxed)),
                         g_learned_guid.load(std::memory_order_relaxed), fh.leaks, fh.repairs, fh.lethal_saved,
                         static_cast<std::uint32_t>(fh.last_leak), static_cast<std::uint32_t>(fh.state));
        }
    }

    // ---- Implementation beta-burst r1: GameThread side ------------------

    // native_hook.log: an energy disarm because the switch itself went off (not an identity reason).
    constexpr std::uint32_t kEnergySwitchedOff = 0xFFFFFFFFu;

    std::int32_t energy_pool_value(const void* actor, std::uint32_t byte_offset)
    {
        float value = 0.0f;
        if (!actor || !safe_read_float(actor, byte_offset, &value) || !std::isfinite(value) || value < 0.0f
            || value > kMaxEnergyPool)
            return -1;
        return static_cast<std::int32_t>(value);
    }

    // Optional (energytopup=1). GameThread only, right after the identity tick
    // re-proved the actor. The game's own ApplyStatDiff - the trampoline, so
    // this hook is not re-entered - is asked for max - current with the
    // arguments the game's own restore-after-load reaches it with
    // (0x1BB5C01..0x1BB5C30 -> 0x1BA87ED..0x1BA881E: context 0, both flags 0,
    // id 0). The game clamps, stores and reports the change itself. Not done:
    // before the game was seen making its own server-side stat calls for this
    // Eve on this thread; ever, once one was seen on another thread; for a
    // dead Eve; for an unbelievable pool or a locked Burst gauge; more than
    // once a second per gauge; after three calls in a row that did not fill.
    void gt_energy_topup(void* actor, std::uint64_t now_ms)
    {
        if (!g_desired_topup.load(std::memory_order_relaxed) || !actor) return;
        if (g_energy_calls_gt.load(std::memory_order_relaxed) == 0
            || g_energy_calls_other.load(std::memory_order_relaxed) != 0)
            return;
        if (!verify_learned_identity(actor) || !(read_stat(actor, sbgod::kStatHp) >= 1.0f)) return;
        auto* apply_diff = original<ApplyStatDiffFn>(sites::kApplyStatDiff);
        if (!apply_diff) return;
        // An engine callback may revoke this authority. Revalidate before each
        // gauge and after each return, before reading or submitting anything else.
        const auto topup_authorized = [actor]() {
            return g_desired_topup.load(std::memory_order_acquire) && energy_live()
                && g_identity_verified.load(std::memory_order_acquire)
                && g_learned_actor.load(std::memory_order_acquire) == actor
                && !g_shutting_down.load(std::memory_order_acquire)
                && g_gt_thread_id.load(std::memory_order_acquire) == GetCurrentThreadId()
                && g_energy_calls_gt.load(std::memory_order_acquire) != 0
                && g_energy_calls_other.load(std::memory_order_acquire) == 0
                && verify_learned_identity(actor) && read_stat(actor, sbgod::kStatHp) >= 1.0f;
        };
        for (std::size_t gauge = 0; gauge < kEnergyGaugeCount; ++gauge)
        {
            if (!topup_authorized()) return;
            const bool beta = gauge == kEnergyBeta;
            if (!(beta ? g_desired_beta : g_desired_burst).load(std::memory_order_relaxed)) continue;
            if (gt_energy_topup_misses[gauge] >= kEnergyTopupGiveUp) continue;
            if (gt_energy_topup_tried[gauge] && now_ms - gt_energy_topup_ms[gauge] < kEnergyTopupPeriodMs) continue;
            EnergyPool pool{};
            if (!energy_read_pool(actor, beta, &pool) || pool.now + 0.5f >= pool.max) continue;
            gt_energy_topup_tried[gauge] = true;
            gt_energy_topup_ms[gauge] = now_ms;
            g_energy_topups[gauge].fetch_add(1, std::memory_order_relaxed);
            apply_diff(actor, beta ? kStatBetaGauge : kStatBurstGauge, nullptr, pool.max - pool.now, 0, 0, 0);
            if (!topup_authorized()) return;
            EnergyPool after{};
            if (energy_read_pool(actor, beta, &after) && after.now + 0.5f >= after.max)
            {
                gt_energy_topup_misses[gauge] = 0;
            }
            else
            {
                ++gt_energy_topup_misses[gauge];
                g_energy_topup_noeffect.fetch_add(1, std::memory_order_relaxed);
            }
        }
    }

    // GameThread only, once per update after God's own arming. Arms the energy
    // switches on the same proof God needs (hooks in, self-check passed,
    // identity verified on this tick, no fault, no poison, not shutting down)
    // but independently of g_desired_god, and publishes Eve's own numbers.
    void gt_energy_tick(bool wanted, SelfCheck selfcheck, std::uint64_t now_ms)
    {
        g_gt_thread_id.store(GetCurrentThreadId(), std::memory_order_relaxed);
        const bool armed_next = wanted && g_hooks_installed.load(std::memory_order_acquire)
            && selfcheck == SelfCheck::Pass && g_identity_verified.load(std::memory_order_acquire)
            && !dispatch_poisoned() && !sbcore::fault::writes_blocked()
            && !g_shutting_down.load(std::memory_order_acquire);
        void* actor = g_learned_actor.load(std::memory_order_acquire);
        if (armed_next && !gt_prev_energy_armed)
        {
            for (std::size_t gauge = 0; gauge < kEnergyGaugeCount; ++gauge)
            {
                gt_energy_topup_tried[gauge] = false;
                gt_energy_topup_ms[gauge] = 0;
                gt_energy_topup_misses[gauge] = 0;
            }
            const auto arms = g_energy_arms.fetch_add(1, std::memory_order_relaxed) + 1u;
            const std::uint64_t switches = (g_desired_beta.load(std::memory_order_relaxed) ? 1u : 0u)
                | (g_desired_burst.load(std::memory_order_relaxed) ? 2u : 0u)
                | (g_desired_topup.load(std::memory_order_relaxed) ? 4u : 0u);
            gt_log_event(LogKind::EnergyArmed, reinterpret_cast<std::uint64_t>(actor),
                         g_learned_guid.load(std::memory_order_relaxed), switches, arms, 0,
                         static_cast<std::uint32_t>(g_arm_path.load(std::memory_order_relaxed)),
                         static_cast<std::uint32_t>(g_direct_proof.load(std::memory_order_relaxed)));
        }
        else if (!armed_next && gt_prev_energy_armed)
        {
            gt_log_event(LogKind::EnergyDisarmed, 0, 0,
                         g_energy_spend_blocks[kEnergyBeta].load(std::memory_order_relaxed)
                             + g_energy_spend_blocks[kEnergyBurst].load(std::memory_order_relaxed),
                         g_energy_fills[kEnergyBeta].load(std::memory_order_relaxed)
                             + g_energy_fills[kEnergyBurst].load(std::memory_order_relaxed),
                         g_energy_topups[kEnergyBeta].load(std::memory_order_relaxed)
                             + g_energy_topups[kEnergyBurst].load(std::memory_order_relaxed),
                         wanted ? static_cast<std::uint32_t>(g_id_reason.load(std::memory_order_relaxed)) : kEnergySwitchedOff,
                         static_cast<std::uint32_t>(g_id_step.load(std::memory_order_relaxed)));
        }
        g_energy_live.store(armed_next, std::memory_order_release);
        gt_prev_energy_armed = armed_next;

        const void* shown = armed_next ? actor : nullptr;
        g_energy_pool[kPoolBetaNow].store(energy_pool_value(shown, kBetaNowOffset), std::memory_order_relaxed);
        g_energy_pool[kPoolBetaMax].store(energy_pool_value(shown, kBetaMaxOffset), std::memory_order_relaxed);
        g_energy_pool[kPoolBurstNow].store(energy_pool_value(shown, kBurstNowOffset), std::memory_order_relaxed);
        g_energy_pool[kPoolBurstMax].store(energy_pool_value(shown, kBurstMaxOffset), std::memory_order_relaxed);
        g_energy_pool[kPoolBurstUnlock].store(energy_pool_value(shown, kBurstUnlockOffset), std::memory_order_relaxed);
        if (armed_next) gt_energy_topup(actor, now_ms);
    }

    // GameThread only: sbcore::dispatch runs this on the certified GameThread,
    // under sbcore::fault::guarded_call, and never while a fault is latched.
    void execute_game_thread_update(std::uint64_t)
    {
        // Process teardown / uninstall owns all remaining values (v1.1.2's
        // invoke skipped the update the same way; sbcore's own shutdown is not
        // used so that a UE4SS hot reload of this pinned module can resume).
        if (g_shutting_down.load(std::memory_order_acquire)) return;
        const auto start_us = qpc_us();
        const auto now = GetTickCount64();
        const bool desired = g_desired_god.load(std::memory_order_acquire);
        // Implementation beta-burst r1: an energy switch also needs to
        // know who Eve is, so the identity tick runs while God OR an energy
        // switch is wanted. Until now the identity was forgotten on every tick
        // with God off, so God switched on always verified again from a clean
        // tracker: at once through the resume rule, with its INITIAL stats
        // rule (v1.3.2: never on a dead Eve). The same happens here on the
        // first tick that sees God on after a tick that saw it off, also when
        // the identity was being held for the energy switches. With both
        // energy switches off nothing changes: the tracker is already clean
        // on that tick and the reset is a repeat.
        const bool energy = energy_wanted();
        const bool god_on_edge = desired && !gt_prev_desired_god;
        gt_prev_desired_god = desired;

        if ((desired || energy) && !g_sc_fail_sticky.load(std::memory_order_acquire))
        {
            if (god_on_edge) reset_identity_tracking();
            gt_identity_tick(now);
        }
        else
        {
            // God off (or offset disproved): forget the candidate so turning
            // God on again re-verifies from scratch, including a fresh hook
            // corroboration.
            reset_identity_tracking();
            if (!desired) g_id_reason.store(id::Reason::GodOff, std::memory_order_release);
        }

        const auto selfcheck = evaluate_selfcheck(nullptr);
        const bool armed_next = desired && g_hooks_installed.load(std::memory_order_acquire)
            && selfcheck == SelfCheck::Pass && g_identity_verified.load(std::memory_order_acquire)
            && !dispatch_poisoned() && !sbcore::fault::writes_blocked()
            && !g_shutting_down.load(std::memory_order_acquire);
        // v1.3.1 F2: publish the ready pair only when every arming condition
        // except S9 holds: the next tick arms on the hook's own evidence. A
        // self-check that failed or is contradicted (hook GUID mismatches with
        // no match) never readies anything.
        {
            const auto matches = g_sc_hook_matches.load(std::memory_order_acquire);
            const auto mismatches = g_sc_hook_mismatches.load(std::memory_order_acquire);
            const bool contradicted = mismatches > 0 && matches == 0;
            const bool ready_ok = desired && gt_ready_pending && g_hooks_installed.load(std::memory_order_acquire)
                && selfcheck != SelfCheck::Fail && selfcheck != SelfCheck::Blocked && !contradicted
                && !g_sc_fail_sticky.load(std::memory_order_acquire) && !g_identity_verified.load(std::memory_order_acquire)
                && !dispatch_poisoned() && !sbcore::fault::writes_blocked()
                && !g_shutting_down.load(std::memory_order_acquire);
            publish_ready(ready_ok ? gt_ready_actor : 0, ready_ok ? gt_ready_guid : 0);
        }
        gt_apply_arming(armed_next, now);
        if (armed_next) maintain_god_hp();
        gt_energy_tick(energy, selfcheck, now); // beta-burst r1: never touches g_god_live, floors or HP

        const void* learned = g_learned_actor.load(std::memory_order_relaxed);
        g_shield_now_telemetry.store(learned ? read_stat(learned, sbgod::kStatShield) : 0.0f,
                                     std::memory_order_relaxed);

        const auto elapsed_us = qpc_us() - start_us;
        g_gt_last_us.store(elapsed_us, std::memory_order_relaxed);
        store_max(g_gt_max_us, elapsed_us);
    }

    // Worker only. sbcore::dispatch builds the same FFunctionGraphTask as
    // v1.1.2 (CreateTask(AnyThread) / +0x10 invoke / +0x30 callable vtable /
    // +0x38 payload / +0x50 = GameThread / Setup) and runs
    // execute_game_thread_update only on the thread that equals the gate-proven
    // GGameThreadId, only while no fault is latched, and under
    // sbcore::fault::guarded_call (breadcrumb + latch + poison on a fault).
    bool dispatch_update()
    {
        if (g_shutting_down.load(std::memory_order_acquire)) return false;
        const auto result = sbcore::dispatch::submit(&execute_game_thread_update);
        // A poisoned dispatcher or a latched fault disarms at once (v1.1.2 did
        // the same on poison); the hooks already see the latch via god_live().
        if (dispatch_stopped()) g_god_live.store(false, std::memory_order_release);
        return result == sbcore::dispatch::SubmitResult::Submitted;
    }

    // ---- Worker: configuration, heartbeat, log ------------------------------

    std::atomic<bool> g_state_busy{false};
    std::atomic<bool> g_state_from_cache{false};

    // Worker only: file I/O and atomics. The pointer hints are recorded for
    // telemetry but never dereferenced (they can come from another process
    // lifetime); identity comes only from the GameThread identity pass.
    //
    // A12: the file is read with FILE_SHARE_READ|WRITE|DELETE (the panel's
    // POSIX-rename replace is never blocked by this reader); reparse points,
    // hard links, empty, >4 KiB and NUL-containing files are refused. A
    // missing/busy file keeps the last good content for 500 ms (the panel's
    // replace window), then - as before - the previous desired state is kept
    // and state_file_ok=0. The bytes are parsed exactly as v1.1.2's text-mode
    // fgets loop (god_state.cpp).
    void refresh_desired_state()
    {
        if (!g_paths_ready.load(std::memory_order_acquire)) return;
        bool expected = false;
        if (!g_state_busy.compare_exchange_strong(expected, true, std::memory_order_acq_rel)) return;
        const auto read = g_state_reader.read(GetTickCount64());
        g_state_read_result.store(read.raw, std::memory_order_relaxed);
        g_state_from_cache.store(read.from_cache, std::memory_order_relaxed);
        if (read.effective != sbcore::status::ReadResult::Ok)
        {
            g_state_file_ok.store(false, std::memory_order_relaxed);
            g_state_busy.store(false, std::memory_order_release);
            return; // keep the previous desired state, as v1.0.36
        }
        const auto parsed = sbgod::state::parse_state_text(g_state_reader.content(),
                                                           g_desired_god.load(std::memory_order_relaxed));
        const auto energy = parse_energy_switches(g_state_reader.content()); // beta-burst r1: missing line = OFF
        g_state_busy.store(false, std::memory_order_release);
        g_state_file_ok.store(true, std::memory_order_relaxed);
        g_state_playerguid.store(parsed.player_guid, std::memory_order_relaxed);
        g_state_actorptr.store(parsed.actor_ptr, std::memory_order_relaxed);
        g_state_bagptr.store(parsed.bag_ptr, std::memory_order_relaxed);
        const bool previous = g_desired_god.exchange(parsed.god, std::memory_order_acq_rel);
        if (previous != parsed.god)
        {
            g_config_revision.fetch_add(1, std::memory_order_acq_rel);
        }
        // beta-burst r1: a changed energy switch asks for a GameThread update at once, like a God toggle.
        const bool beta_changed = g_desired_beta.exchange(energy.beta, std::memory_order_acq_rel) != energy.beta;
        const bool burst_changed = g_desired_burst.exchange(energy.burst, std::memory_order_acq_rel) != energy.burst;
        const bool topup_changed = g_desired_topup.exchange(energy.topup, std::memory_order_acq_rel) != energy.topup;
        if (beta_changed || burst_changed || topup_changed) g_config_revision.fetch_add(1, std::memory_order_acq_rel);
    }

    // ---- v1.3.1 F5: wall-clock timestamps, events, append + rotation ----------
    constexpr std::uint64_t kHookLogRotateBytes = 2ULL * 1024 * 1024;
    bool g_logged_desired{false}; // worker-owned: the desired state last written to the log
    unsigned g_logged_energy{0};  // worker-owned (beta-burst r1): bit 0 Beta, 1 Burst, 2 top-up as last written

    void format_local_time(std::uint64_t filetime, char* out, std::size_t size)
    {
        FILETIME utc{};
        utc.dwLowDateTime = static_cast<DWORD>(filetime & 0xFFFFFFFFULL);
        utc.dwHighDateTime = static_cast<DWORD>(filetime >> 32);
        SYSTEMTIME st_utc{};
        SYSTEMTIME st{};
        if (!FileTimeToSystemTime(&utc, &st_utc))
        {
            std::snprintf(out, size, "0000-00-00 00:00:00.000");
            return;
        }
        if (!SystemTimeToTzSpecificLocalTime(nullptr, &st_utc, &st)) st = st_utc;
        std::snprintf(out, size, "%04u-%02u-%02u %02u:%02u:%02u.%03u", st.wYear, st.wMonth, st.wDay, st.wHour, st.wMinute,
                      st.wSecond, st.wMilliseconds);
    }

    void print_timestamp(FILE* log, std::uint64_t filetime)
    {
        char text[32];
        format_local_time(filetime, text, sizeof(text));
        std::fprintf(log, "%s ", text);
    }

    // Worker only (single consumer of the GameThread's ring).
    void drain_log_events(FILE* log)
    {
        auto tail = g_log_tail.load(std::memory_order_relaxed);
        const auto head = g_log_head.load(std::memory_order_acquire);
        for (; tail != head; ++tail)
        {
            const LogEvent e = g_log_ring[tail % kLogRing];
            print_timestamp(log, e.filetime);
            switch (e.kind)
            {
            case LogKind::Candidate:
                std::fprintf(log, "event=candidate actor=%llX guid=%u step=%s reason=%s candidate_changes=%llu eventor_guid=%llu\n",
                             static_cast<unsigned long long>(e.actor), e.guid, id::step_name(static_cast<id::Step>(e.d)),
                             id::reason_name(static_cast<id::Reason>(e.e)), static_cast<unsigned long long>(e.a),
                             static_cast<unsigned long long>(e.b));
                break;
            case LogKind::Armed:
                std::fprintf(log, "event=armed actor=%llX guid=%u path=%s proof=%s arm_after_candidate_ms=%llu "
                                  "unarmed_hits_total=%llu prearm_blocks_total=%llu\n",
                             static_cast<unsigned long long>(e.actor), e.guid, id::arm_path_name(static_cast<id::ArmPath>(e.d)),
                             id::direct_proof_name(static_cast<id::DirectProof>(e.e)), static_cast<unsigned long long>(e.a),
                             static_cast<unsigned long long>(e.b), static_cast<unsigned long long>(e.c));
                break;
            case LogKind::Disarmed:
                std::fprintf(log, "event=disarmed actor=%llX guid=%u reason=%s step=%s blocked=%llu repaired=%llu leaks=%llu\n",
                             static_cast<unsigned long long>(e.actor), e.guid, id::reason_name(static_cast<id::Reason>(e.d)),
                             id::step_name(static_cast<id::Step>(e.e)), static_cast<unsigned long long>(e.a),
                             static_cast<unsigned long long>(e.b), static_cast<unsigned long long>(e.c));
                break;
            case LogKind::Leak:
                std::fprintf(log, "event=leak actor=%llX guid=%u leaks=%llu repairs=%llu lethal_saved=%llu last_leak=%s first_hit=%s\n",
                             static_cast<unsigned long long>(e.actor), e.guid, static_cast<unsigned long long>(e.a),
                             static_cast<unsigned long long>(e.b), static_cast<unsigned long long>(e.c),
                             id::hit_event_name(static_cast<id::HitEvent>(e.d)),
                             id::first_hit_name(static_cast<id::FirstHit>(e.e)));
                break;
            case LogKind::EnergyArmed: // beta-burst r1
                std::fprintf(log, "event=energy_armed actor=%llX guid=%u beta=%d burst=%d topup=%d arms=%llu path=%s proof=%s\n",
                             static_cast<unsigned long long>(e.actor), e.guid, (e.a & 1u) != 0 ? 1 : 0,
                             (e.a & 2u) != 0 ? 1 : 0, (e.a & 4u) != 0 ? 1 : 0, static_cast<unsigned long long>(e.b),
                             id::arm_path_name(static_cast<id::ArmPath>(e.d)),
                             id::direct_proof_name(static_cast<id::DirectProof>(e.e)));
                break;
            case LogKind::EnergyDisarmed: // beta-burst r1
                std::fprintf(log, "event=energy_disarmed reason=%s step=%s spend_blocks=%llu fills=%llu topups=%llu\n",
                             e.d == 0xFFFFFFFFu ? "switch_off" : id::reason_name(static_cast<id::Reason>(e.d)),
                             id::step_name(static_cast<id::Step>(e.e)), static_cast<unsigned long long>(e.a),
                             static_cast<unsigned long long>(e.b), static_cast<unsigned long long>(e.c));
                break;
            }
        }
        g_log_tail.store(tail, std::memory_order_release);
    }

    // Worker only: GameThread events and God on/off transitions, when any.
    void write_log_events()
    {
        if (!g_paths_ready.load(std::memory_order_acquire)) return;
        const bool desired = g_desired_god.load(std::memory_order_acquire);
        const bool pending = g_log_head.load(std::memory_order_acquire) != g_log_tail.load(std::memory_order_relaxed);
        const unsigned energy = (g_desired_beta.load(std::memory_order_acquire) ? 1u : 0u)
            | (g_desired_burst.load(std::memory_order_acquire) ? 2u : 0u)
            | (g_desired_topup.load(std::memory_order_acquire) ? 4u : 0u); // beta-burst r1
        if (!pending && desired == g_logged_desired && energy == g_logged_energy) return;
        FILE* log = nullptr;
        if (_wfopen_s(&log, g_log_path.c_str(), L"a") != 0 || !log) return;
        if (desired != g_logged_desired)
        {
            print_timestamp(log, filetime_now());
            std::fprintf(log, "event=%s\n", desired ? "god_on" : "god_off");
            g_logged_desired = desired;
        }
        if (energy != g_logged_energy)
        {
            print_timestamp(log, filetime_now());
            std::fprintf(log, "event=energy_switch beta=%d burst=%d topup=%d supported=%d\n", (energy & 1u) != 0 ? 1 : 0,
                         (energy & 2u) != 0 ? 1 : 0, (energy & 4u) != 0 ? 1 : 0,
                         g_energy_sites_ok.load(std::memory_order_acquire) ? 1 : 0);
            g_logged_energy = energy;
        }
        drain_log_events(log);
        std::fclose(log);
    }

    void append_debug_log()
    {
        if (!g_paths_ready.load(std::memory_order_acquire)) return;
        FILE* log = nullptr;
        if (_wfopen_s(&log, g_log_path.c_str(), L"a") != 0 || !log) return;
        const char* reason = nullptr;
        const auto sc = evaluate_selfcheck(&reason);
        char identity_reason[64]{};
        identity_reason_text(identity_reason, sizeof(identity_reason));
        const auto fh = g_first_hit.snapshot();
        print_timestamp(log, filetime_now());
        std::fprintf(log,
                     "godlive=%d armed=%d hooks=%d selfcheck=%s guid=%u actorptr=%llX bagptr=%llX hits=%llu blocks=%llu "
                     "checks=%llu learned=%p last_stat=%d last_actor=%llX exec_hits=%llu exec_blocks=%llu "
                     "identity=%s target_actor=%llX actor_guid=%u table_id=%u corroborations=%llu writes_blocked=%d "
                     "arm_path=%s fast_arm_proof=%s protection=%s first_hit=%s first_source=%s leaks=%llu "
                     "repairs=%llu lethal_saved=%llu diff_blocks=%llu prearm_blocks=%llu unarmed_hits=%llu "
                     "resume_arms=%llu eventor_guid=%u apply_drops=%llu log_dropped=%llu\n",
                     g_desired_god.load() ? 1 : 0, god_live() ? 1 : 0, g_hooks_installed.load() ? 1 : 0,
                     selfcheck_name(sc), g_player_guid.load(),
                     static_cast<unsigned long long>(g_actor_ptr.load()),
                     static_cast<unsigned long long>(g_bag_ptr.load()),
                     static_cast<unsigned long long>(g_hits.load()),
                     static_cast<unsigned long long>(g_blocks.load()),
                     static_cast<unsigned long long>(g_protect_checks.load()), g_learned_actor.load(),
                     g_last_stat.load(), static_cast<unsigned long long>(g_last_actor.load()),
                     static_cast<unsigned long long>(g_execute_hits.load()),
                     static_cast<unsigned long long>(g_execute_blocks.load()), identity_reason,
                     static_cast<unsigned long long>(g_id_actor.load()), g_id_guid.load(), g_id_table_id.load(),
                     static_cast<unsigned long long>(g_cand_corroborations.load()),
                     sbcore::fault::writes_blocked() ? 1 : 0, id::arm_path_name(g_arm_path.load()),
                     id::direct_proof_name(g_direct_proof.load()), id::protection_name(fh), id::first_hit_name(fh.state),
                     id::hit_event_name(fh.first), static_cast<unsigned long long>(fh.leaks),
                     static_cast<unsigned long long>(fh.repairs), static_cast<unsigned long long>(fh.lethal_saved),
                     static_cast<unsigned long long>(g_diff_blocks.load()),
                     static_cast<unsigned long long>(g_prearm_blocks.load()),
                     static_cast<unsigned long long>(g_unarmed_hits.load()),
                     static_cast<unsigned long long>(g_resume_arms.load()), g_eventor_guid.load(),
                     static_cast<unsigned long long>(g_apply_drops.load()),
                     static_cast<unsigned long long>(g_log_dropped.load()));
        std::fclose(log);
    }

    void write_install_log()
    {
        if (!g_paths_ready.load(std::memory_order_acquire)) return;
        // v1.3.1 F5: append (earlier sessions stay for comparison); above
        // 2 MiB the log moves to native_hook.prev.log first (one generation).
        {
            WIN32_FILE_ATTRIBUTE_DATA data{};
            if (GetFileAttributesExW(g_log_path.c_str(), GetFileExInfoStandard, &data)
                && ((static_cast<std::uint64_t>(data.nFileSizeHigh) << 32) | data.nFileSizeLow) > kHookLogRotateBytes)
            {
                const std::wstring previous = g_log_path.substr(0, g_log_path.size() - 4) + L".prev.log";
                MoveFileExW(g_log_path.c_str(), previous.c_str(), MOVEFILE_REPLACE_EXISTING);
            }
        }
        FILE* log = nullptr;
        if (_wfopen_s(&log, g_log_path.c_str(), L"a") != 0 || !log) return;
        print_timestamp(log, filetime_now());
        std::fprintf(log, "session_start pid=%lu ", GetCurrentProcessId());
        std::fprintf(log, "installed=%d version=%s build=%08X/%08X build_ok=%d exe_file_size=%llu exe_file_size_ok=%d "
                          "validation_all_ok=%d taskgraph_ok=%d module_pinned=%d error=%s",
                     g_hooks_installed.load() ? 1 : 0, sbgod::kVersion, g_build_timestamp.load(),
                     g_build_size_of_image.load(), g_build_ok.load() ? 1 : 0,
                     static_cast<unsigned long long>(g_exe_file_size.load()), g_exe_file_size_ok.load() ? 1 : 0,
                     g_validation_all_ok.load() ? 1 : 0, g_taskgraph_ok.load() ? 1 : 0,
                     g_module_pinned.load() ? 1 : 0, g_install_error);
        for (std::uint32_t i = 0; i < sites::kSiteCount; ++i)
            std::fprintf(log, " %s=%d@%llX", sites::kSites[i].name, g_site_ok[i].load() ? 1 : 0,
                         static_cast<unsigned long long>(0x140000000ULL + sites::kSites[i].rva));
        for (std::uint32_t i = 0; i < sites::kAnchorCount; ++i)
            std::fprintf(log, " %s=%d", sites::kAnchors[i].name, g_anchor_ok[i].load() ? 1 : 0);
        std::fprintf(log, " sbcore=%s gate_reason=%s gate_failed=%s gate_checks_passed=%u fault_log=%s\n", sbcore::kVersion,
                     sbcore::gate::reason_name(g_gate_reason.load()), g_gate_failed, g_gate_checks_passed.load(),
                     sbcore::fault::snapshot().log_failures == 0 ? "ok" : "unavailable");
        print_timestamp(log, filetime_now()); // beta-burst r1
        std::fprintf(log, "energy_id=%s energy_sites_ok=%d energy_site_error=%s\n", kEnergyId,
                     g_energy_sites_ok.load() ? 1 : 0, g_energy_site_error);
        std::fclose(log);
    }

    void log_heartbeat_build_error(const char* error)
    {
        static std::atomic<bool> logged{false};
        if (logged.exchange(true) || !g_paths_ready.load(std::memory_order_acquire)) return;
        FILE* log = nullptr;
        if (_wfopen_s(&log, g_log_path.c_str(), L"a") != 0 || !log) return;
        print_timestamp(log, filetime_now());
        std::fprintf(log, "heartbeat_build_error=%s\n", error ? error : "unknown");
        std::fclose(log);
    }

    // ---- Heartbeat (A12) ------------------------------------------------------
    //
    // native_heartbeat.txt keeps every v1.1.2 key, in order and in the same
    // text format (lines end in CRLF since v1.2.0); v1.2.0 keys and the
    // sbcore header keys are appended. Published through
    // sbcore::status::Writer: CREATE_NEW temp (native_heartbeat.tmp), checked
    // write, POSIX rename of that handle over the final name with a bounded
    // retry, no flush; a failed write never replaces the previous file.
    // Checked every 500 ms; written when anything except `beat` and the
    // sbcore_* keys changed, and at least every second (panel max age 15 s).

    sbcore::status::Writer g_heartbeat_writer{}; // configured once by install() before g_paths_ready
    std::atomic<bool> g_heartbeat_busy{false};
    std::uint64_t g_heartbeat_beat{0};           // guarded by g_heartbeat_busy
    std::uint64_t g_heartbeat_last_ms{0};
    std::uint64_t g_heartbeat_fingerprint{0};
    bool g_heartbeat_published{false};
    char g_heartbeat_buffer[16384];

    void add_hex(sbcore::status::Builder& b, const char* key, std::uint64_t value) // "%llX"
    {
        char text[24];
        std::snprintf(text, sizeof(text), "%llX", static_cast<unsigned long long>(value));
        b.add_str(key, text);
    }

    void add_hex_prefixed(sbcore::status::Builder& b, const char* key, std::uint32_t value) // "0x%X"
    {
        char text[16];
        std::snprintf(text, sizeof(text), "0x%X", value);
        b.add_str(key, text);
    }

    void add_flag(sbcore::status::Builder& b, const char* key, bool value)
    {
        b.add_u64(key, value ? 1U : 0U);
    }

    void add_text(sbcore::status::Builder& b, const char* key, const char* value)
    {
        b.add_str(key, value && value[0] ? value : "unknown");
    }

    const char* state_read_text(char* buffer, std::size_t size)
    {
        const auto raw = sbcore::status::read_result_name(g_state_read_result.load(std::memory_order_relaxed));
        if (g_state_from_cache.load(std::memory_order_relaxed)) std::snprintf(buffer, size, "grace_%s", raw);
        else std::snprintf(buffer, size, "%s", raw);
        return buffer;
    }

    // Implementation beta-burst r1: the one word the panel shows for the
    // energy switches. Never contains ';' or ':' (it is packed into
    // god_fast_arm). Worker only.
    //   off                      no energy switch is on
    //   active                   armed: the switched-on gauges do not drain
    //   hooks_not_installed      God's install refused (see install_error)
    //   not_supported/<window>   this exe is not the one the energy code was written for
    //   stopped                  a fault is latched or the GameThread dispatch is poisoned
    //   waiting_for_game_thread  no GameThread update has run yet
    //   identity_check_failed    the GUID-offset self-check failed (God is off for the same reason)
    //   waiting_for_eve/<why>    Eve is not verified yet: the identity reason, '.' for ':'
    void energy_state_text(char* out, std::size_t size)
    {
        if (!g_desired_beta.load(std::memory_order_acquire) && !g_desired_burst.load(std::memory_order_acquire))
        {
            std::snprintf(out, size, "off");
            return;
        }
        if (!g_hooks_installed.load(std::memory_order_acquire))
        {
            std::snprintf(out, size, "hooks_not_installed");
            return;
        }
        if (!g_energy_sites_ok.load(std::memory_order_acquire))
        {
            std::snprintf(out, size, "not_supported/%s", g_energy_site_error);
            return;
        }
        if (dispatch_stopped())
        {
            std::snprintf(out, size, "stopped");
            return;
        }
        if (energy_live())
        {
            std::snprintf(out, size, "active");
            return;
        }
        if (g_gt_thread_id.load(std::memory_order_acquire) == 0)
        {
            std::snprintf(out, size, "waiting_for_game_thread");
            return;
        }
        if (g_sc_fail_sticky.load(std::memory_order_acquire))
        {
            std::snprintf(out, size, "identity_check_failed");
            return;
        }
        const auto reason = g_id_reason.load(std::memory_order_acquire);
        if (reason == id::Reason::Chain)
            std::snprintf(out, size, "waiting_for_eve/chain.%s", id::step_name(g_id_step.load(std::memory_order_acquire)));
        else
            std::snprintf(out, size, "waiting_for_eve/%s", id::reason_name(reason));
    }

    // Every key after `beat`, in the v1.1.2 order, then the v1.2.0 keys.
    void append_heartbeat_fields(sbcore::status::Builder& b)
    {
        const void* learned = g_learned_actor.load(std::memory_order_relaxed);
        const auto dispatch = sbcore::dispatch::counters();

        // Keys and order of v1.0.36 are preserved; retired features print 0.
        b.add_i64("godlive", g_desired_god.load() ? 1 : 0);
        b.add_u64("hits", g_hits.load());
        b.add_u64("blocks", g_blocks.load());
        b.add_u64("checks", g_protect_checks.load());
        add_hex(b, "learned", reinterpret_cast<std::uint64_t>(learned));
        add_hex(b, "actorptr", g_actor_ptr.load());
        add_hex(b, "bagptr", g_bag_ptr.load());
        b.add_str("property_field", "0");
        b.add_str("actor_property_field", "0");
        add_hex(b, "player_state", g_player_state_ptr.load());
        b.add_u64("guid", g_player_guid.load());
        for (const char* retired : {"actor_info_hits", "actor_info_last_guid", "actor_jump_hits", "actor_jump_last_guid",
                                    "bucket_create_hits", "inventory_bucket_guid", "inventory_target_guid", "save_game",
                                    "item_map", "item_map_data", "item_map_num", "item_map_max", "inventory_data",
                                    "inventory_num", "inventory_max"})
            b.add_str(retired, "0");
        b.add_i64("last_stat", g_last_stat.load());
        add_hex(b, "last_actor", g_last_actor.load());
        b.add_u64("exec_hits", g_execute_hits.load());
        b.add_u64("exec_blocks", g_execute_blocks.load());
        b.add_u64("maintain", g_maintain_ticks.load());
        b.add_u64("maintain_restores", g_maintain_restores.load());
        b.add_float("hp_floor", g_hp_floor.load(), 1);
        b.add_i64("hp_byte_off", learned ? static_cast<int>(sbgod::kStatArrayOffset + sbgod::kStatHp * sizeof(float)) : -1);
        b.add_str("pawn_hp_off", "-1");
        b.add_str("pawn_hp_now", "0.0");
        b.add_str("pawn_hp_slots", "0");
        b.add_float("shield_now", g_shield_now_telemetry.load(), 1);
        b.add_float("shield_floor", g_sim_shield_floor.load(), 1);

        b.add_u64("setter_vital_hits", g_setter_vital_hits.load());
        b.add_u64("setter_vital_negative_hits", g_setter_vital_negative_hits.load());
        add_hex(b, "setter_vital_last_actor", g_setter_vital_last_actor.load());
        b.add_i64("setter_vital_last_stat", g_setter_vital_last_stat.load());
        b.add_float("setter_vital_last_value", g_setter_vital_last_value.load(), 3);
        b.add_i64("setter_vital_guid_offset", g_setter_vital_guid_offset.load());
        b.add_u64("guid_candidate_hits", g_guid_candidate_hits.load());
        add_hex(b, "guid_candidate_actor", g_guid_candidate_actor.load());
        b.add_i64("guid_candidate_offset", g_guid_candidate_offset.load());
        b.add_i64("guid_candidate_stat", g_guid_candidate_stat.load());
        b.add_float("guid_candidate_value", g_guid_candidate_value.load(), 3);
        b.add_u64("exec_vital_hits", g_execute_vital_hits.load());
        b.add_u64("exec_player_vital_hits", g_execute_player_vital_hits.load());
        b.add_u64("exec_vital_last_guid", g_execute_vital_last_guid.load());
        b.add_i64("exec_vital_last_stat", g_execute_vital_last_stat.load());
        b.add_float("exec_vital_last_diff", g_execute_vital_last_diff.load(), 3);
        b.add_float("exec_vital_last_result", g_execute_vital_last_result.load(), 3);

        b.add_u64("combat_guid", g_player_combat_guid.load());
        add_hex(b, "live_combat_actor", g_live_combat_actor.load());
        b.add_u64("combat_guid_binds", g_combat_guid_binds.load());

        b.add_float("setter_vital_actor_hp", g_setter_vital_actor_hp.load(), 3);
        b.add_float("setter_vital_actor_max_hp", g_setter_vital_actor_max_hp.load(), 3);
        b.add_float("setter_vital_actor_shield", g_setter_vital_actor_shield.load(), 3);
        b.add_u64("setter_vital_tick", g_setter_vital_tick.load());
        b.add_u64("setter_after_player_execute_ms", g_setter_after_player_execute_ms.load());
        add_hex(b, "setter_vital_return_address", g_setter_vital_return_address.load());
        b.add_u64("fatal_zero_blocks", g_fatal_zero_blocks.load());
        b.add_u64("fatal_branch_skips", g_fatal_branch_skips.load());
        b.add_u64("fatal_chain_blocks", g_fatal_chain_blocks.load());
        add_hex(b, "fatal_guard_actor", g_fatal_guard_actor.load());
        b.add_u64("fatal_guard_tick", g_fatal_guard_tick.load());
        b.add_u64("last_player_execute_tick", g_last_player_execute_tick.load());
        b.add_u64("actor_dead_hits", g_actor_dead_hits.load());
        b.add_u64("actor_dead_blocks", g_actor_dead_blocks.load());
        add_hex(b, "actor_dead_last_actor", g_actor_dead_last_actor.load());
        b.add_u64("actor_dead_last_guid", g_actor_dead_last_guid.load());
        add_hex(b, "actor_dead_last_return_address", g_actor_dead_last_return_address.load());
        b.add_u64("actor_dead_last_tick", g_actor_dead_last_tick.load());
        b.add_u64("actor_dead_after_player_execute_ms", g_actor_dead_after_player_execute_ms.load());
        b.add_u64("actor_dead_after_setter_ms", g_actor_dead_after_setter_ms.load());
        b.add_u64("actor_dead_predicate_mask", g_actor_dead_predicate_mask.load());
        b.add_u64("actor_dead_world_hits", g_actor_dead_world_hits.load());
        add_hex(b, "pending_death_actor", g_pending_death_actor.load());
        b.add_u64("pending_death_tick", g_pending_death_tick.load());

        b.add_u64("dead_execute_hits", g_dead_execute_hits.load());
        b.add_u64("dead_execute_player_candidates", g_dead_execute_player_candidates.load());
        b.add_u64("dead_execute_last_guid", g_dead_execute_last_guid.load());
        b.add_i64("dead_execute_last_cause_guid", g_dead_execute_last_cause_guid.load());
        b.add_i64("dead_execute_last_skill_id", g_dead_execute_last_skill_id.load());
        b.add_i64("dead_execute_last_effect_id", g_dead_execute_last_effect_id.load());
        b.add_i64("dead_execute_last_cause_runtime_id", g_dead_execute_last_cause_runtime_id.load());
        b.add_u64("dead_execute_last_force_dead", g_dead_execute_last_force_dead.load());
        b.add_u64("dead_execute_last_local_request", g_dead_execute_last_local_request.load());
        b.add_u64("dead_execute_last_tick", g_dead_execute_last_tick.load());
        b.add_u64("dead_execute_after_player_execute_ms", g_dead_execute_after_player_execute_ms.load());
        b.add_u64("dead_execute_predicate_mask", g_dead_execute_predicate_mask.load());

        b.add_u64("state20_hits", g_state20_hits.load());
        b.add_u64("state20_add_hits", g_state20_add_hits.load());
        b.add_u64("state20_remove_hits", g_state20_remove_hits.load());
        b.add_u64("state20_clear_hits", g_state20_clear_hits.load());
        add_hex(b, "state20_last_actor", g_state20_last_actor.load());
        b.add_u64("state20_last_guid_10c", g_state20_last_guid_10c.load());
        b.add_u64("state20_last_guid_10", g_state20_last_guid_10.load());
        add_hex(b, "state20_last_return_address", g_state20_last_return_address.load());
        b.add_u64("state20_last_tick", g_state20_last_tick.load());
        b.add_u64("state20_last_after_player_execute_ms", g_state20_last_after_player_execute_ms.load());
        b.add_u64("state20_last_add", g_state20_last_add.load());
        b.add_u64("state20_last_clear", g_state20_last_clear.load());
        b.add_float("state20_last_hp", g_state20_last_hp.load(), 3);
        b.add_float("state20_last_max_hp", g_state20_last_max_hp.load(), 3);
        b.add_float("state20_last_shield", g_state20_last_shield.load(), 3);
        add_hex(b, "state20_add_actor", g_state20_add_actor.load());
        b.add_u64("state20_add_guid_10c", g_state20_add_guid_10c.load());
        add_hex(b, "state20_add_return_address", g_state20_add_return_address.load());
        b.add_u64("state20_add_tick", g_state20_add_tick.load());
        b.add_u64("state20_add_after_player_execute_ms", g_state20_add_after_player_execute_ms.load());
        b.add_float("state20_add_hp", g_state20_add_hp.load(), 3);
        b.add_float("state20_add_max_hp", g_state20_add_max_hp.load(), 3);
        b.add_float("state20_add_shield", g_state20_add_shield.load(), 3);
        b.add_u64("state20_lethal_restores", g_state20_lethal_restores.load());
        add_hex(b, "state20_restore_actor", g_state20_restore_actor.load());
        b.add_u64("state20_restore_tick", g_state20_restore_tick.load());
        b.add_float("state20_restore_hp", g_state20_restore_hp.load(), 3);
        b.add_float("state20_restore_shield", g_state20_restore_shield.load(), 3);
        b.add_u64("state20_restore_pawn", g_state20_restore_pawn.load());

        // ---- v1.1.0 additions (appended; older readers ignore them) ----
        const char* sc_reason = nullptr;
        const auto sc = evaluate_selfcheck(&sc_reason);
        char identity_reason[64]{};
        identity_reason_text(identity_reason, sizeof(identity_reason));
        if (sc == SelfCheck::Pending && std::strcmp(sc_reason, "waiting_for_identity") == 0) sc_reason = identity_reason;
        const auto worker = g_worker_thread_id.load(std::memory_order_acquire);
        const auto callback = dispatch.callback_thread;
        const auto certified = dispatch.certified_game_thread;
        char text[128];
        b.add_str("version", sbgod::kVersion);
        b.add_str("architecture", "exact_build_validated_hooks_taskgraph_game_thread_no_item_bridge");
        std::snprintf(text, sizeof(text), "%08X/%08X", g_build_timestamp.load(), g_build_size_of_image.load());
        b.add_str("build", text);
        std::snprintf(text, sizeof(text), "%08X/%08X", sites::kExpectedTimestamp, sites::kExpectedImageSize);
        b.add_str("build_expected", text);
        add_flag(b, "build_ok", g_build_ok.load());
        b.add_u64("exe_file_size", g_exe_file_size.load());
        add_flag(b, "exe_file_size_ok", g_exe_file_size_ok.load());
        add_flag(b, "validation_all_ok", g_validation_all_ok.load());
        add_flag(b, "hooks_installed", g_hooks_installed.load());
        add_text(b, "install_error", g_install_done.load(std::memory_order_acquire) ? g_install_error : "pending");
        // v1.3.1: the five v1.1.0 site keys only (the sixth site is reported in
        // god_fast_arm; validation_all_ok covers every site and anchor).
        for (std::uint32_t i = 0; i < sites::kSiteCountV110; ++i)
            add_flag(b, sites::kSites[i].heartbeat_key, g_site_ok[i].load());
        // The six v1.1.0 anchors keep their keys and positions here; the
        // v1.1.1 identity anchors are appended at the end.
        for (std::uint32_t i = 0; i < sites::kAnchorCountV110; ++i)
            add_flag(b, sites::kAnchors[i].heartbeat_key, g_anchor_ok[i].load());
        add_flag(b, "taskgraph_ok", g_taskgraph_ok.load());
        add_flag(b, "module_pinned", g_module_pinned.load());
        add_flag(b, "dispatch_poisoned", dispatch_stopped()); // v1.2.1: poisoned or fault-latched
        b.add_u64("worker_thread", worker);
        b.add_u64("callback_thread", callback);
        b.add_u64("certified_game_thread", certified);
        add_flag(b, "callback_on_game_thread", callback != 0 && callback == certified);
        b.add_u64("submit_count", dispatch.submit_count);
        b.add_u64("callback_count", dispatch.callback_count);
        b.add_u64("destroy_count", dispatch.destroy_count);
        b.add_u64("last_completed_sequence", dispatch.last_completed_sequence);
        b.add_hex32("last_exception", dispatch.last_exception);
        b.add_u64("gt_last_us", g_gt_last_us.load());
        b.add_u64("gt_max_us", g_gt_max_us.load());
        b.add_u64("identity_refresh_count", g_identity_count.load());
        b.add_u64("identity_last_us", g_identity_last_us.load());
        b.add_u64("identity_max_us", g_identity_max_us.load());
        add_flag(b, "identity_pawn_found", g_identity_pawn_found.load());
        add_flag(b, "god_desired", g_desired_god.load());
        add_flag(b, "god_armed", god_live());
        add_text(b, "selfcheck", selfcheck_name(sc));
        add_text(b, "selfcheck_reason", sc_reason ? sc_reason : "none");
        add_hex_prefixed(b, "selfcheck_guid_offset", sbgod::kActorGuidOffset);
        b.add_u64("selfcheck_hook_matches", g_sc_hook_matches.load());
        b.add_u64("selfcheck_hook_mismatches", g_sc_hook_mismatches.load());
        b.add_u64("selfcheck_hook_last_source", g_sc_hook_last_source.load());
        b.add_u64("selfcheck_hook_last_expected", g_sc_hook_last_expected.load());
        b.add_u64("selfcheck_hook_last_observed", g_sc_hook_last_observed.load());
        add_text(b, "selfcheck_reflect_status", reflect_status_name(g_sc_reflect_status.load()));
        add_text(b, "selfcheck_reflect_source", reflect_source_name(g_sc_reflect_source.load()));
        b.add_u64("selfcheck_reflect_samples", g_sc_reflect_samples.load());
        b.add_u64("selfcheck_reflect_passes", g_sc_reflect_passes.load());
        b.add_u64("selfcheck_reflect_mismatches", g_sc_reflect_mismatches.load());
        b.add_u64("selfcheck_reflect_guid_10c", g_id_table_id.load());
        b.add_u64("selfcheck_reflect_actor_net_guid", static_cast<std::uint32_t>(g_ue_netguid_value.load()));
        b.add_float("selfcheck_reflect_hp", g_id_hp.load(), 1);
        b.add_float("selfcheck_reflect_max_hp", g_id_max_hp.load(), 1);
        b.add_u64("learned_guid", g_learned_guid.load());
        b.add_u64("maintain_verify_rejects", g_maintain_verify_rejects.load());
        add_flag(b, "state_file_ok", g_state_file_ok.load());
        b.add_u64("state_playerguid", g_state_playerguid.load());
        add_hex(b, "state_actorptr", g_state_actorptr.load());
        add_hex(b, "state_bagptr", g_state_bagptr.load());
        b.add_str("state_pointer_hints_used", "0");
        b.add_str("item_bridge", "removed");

        // ---- v1.1.1 additions (appended after every v1.1.0 key) ----
        const auto netguid = g_ue_netguid_value.load();
        const auto id_guid = g_id_guid.load();
        const char* netguid_link = !g_ue_ran.load() ? "not_checked"
            : g_ue_netguid_field.load() == 0       ? "absent"
            : netguid == 0                         ? "zero"
            : static_cast<std::uint32_t>(netguid) == id_guid ? "match"
                                                             : "mismatch";
        b.add_str("identity_rule", "local_client_chain+guid30_accessor+guid_map_mirror+live_set_member+table_id_100"
                                   "+eve_stats+ue_controller+stable_1s+eventor_guid_link_or_hook_corroboration"
                                   "+resume_same_actor_and_guid");
        add_hex_prefixed(b, "selfcheck_actor_guid_offset", sbgod::kActorGuidOffset);
        add_hex_prefixed(b, "selfcheck_table_id_offset", sbgod::kActorTableIdOffset);
        add_text(b, "selfcheck_step_reason", identity_reason);
        add_flag(b, "selfcheck_step_identity_verified", g_identity_verified.load());
        add_text(b, "selfcheck_step_chain", id::step_name(g_id_step.load()));
        add_hex(b, "selfcheck_step_local_client", g_id_client.load());
        add_hex(b, "selfcheck_step_target_holder", g_id_holder.load());
        b.add_i64("selfcheck_step_target_index", g_id_index.load());
        b.add_i64("selfcheck_step_target_count", g_id_count.load());
        add_hex(b, "selfcheck_step_target_actor", g_id_actor.load());
        add_flag(b, "selfcheck_step_vtables_ok", g_id_vtables_ok.load());
        b.add_u64("selfcheck_step_actor_guid", id_guid);
        add_hex(b, "selfcheck_step_mapped_actor", g_id_mapped_actor.load());
        b.add_u64("selfcheck_step_table_id", g_id_table_id.load());
        b.add_float("selfcheck_step_hp", g_id_hp.load(), 1);
        b.add_float("selfcheck_step_max_hp", g_id_max_hp.load(), 1);
        b.add_u64("selfcheck_step_stable_ms", g_id_stable_ms.load());
        b.add_u64("selfcheck_step_stable_samples", g_id_samples.load());
        b.add_u64("selfcheck_step_candidate_changes", g_id_candidate_changes.load());
        b.add_u64("selfcheck_step_ue_runs", g_identity_count.load());
        add_flag(b, "selfcheck_step_ue_exception", g_ue_exception.load());
        b.add_u64("selfcheck_step_controllers_found", g_ue_controllers_found.load());
        b.add_u64("selfcheck_step_controllers_viable", g_ue_controllers_viable.load());
        add_hex(b, "selfcheck_step_controller", g_player_controller_ptr.load());
        add_hex(b, "selfcheck_step_pawn", g_actor_ptr.load());
        add_flag(b, "selfcheck_step_pawn_acknowledged", g_ue_pawn_acknowledged.load());
        add_hex(b, "selfcheck_step_playerstate", g_player_state_ptr.load());
        add_hex(b, "selfcheck_step_netguid_prop", g_ue_netguid_field.load());
        b.add_i64("selfcheck_step_netguid_value", netguid);
        add_text(b, "selfcheck_step_netguid_link", netguid_link);
        add_hex(b, "selfcheck_step_candidate_actor", g_cand_actor_pub.load());
        b.add_u64("selfcheck_step_candidate_guid", g_cand_guid_pub.load());
        b.add_u64("selfcheck_step_hook_corroborations", g_cand_corroborations.load());
        add_hex(b, "selfcheck_step_hook_actor_last", g_hook_actor_last.load());
        b.add_u64("selfcheck_step_hook_actor_guid_last", g_hook_actor_guid_last.load());
        add_text(b, "selfcheck_step_hook_actor_source_last", hook_source_name(g_hook_actor_source_last.load()));
        b.add_u64("selfcheck_step_hook_apply_guid_last", g_hook_apply_guid_last.load());
        for (std::uint32_t i = sites::kAnchorCountV110; i < sites::kAnchorCountV112; ++i)
            add_flag(b, sites::kAnchors[i].heartbeat_key, g_anchor_ok[i].load());

        // ---- v1.2.0 additions (appended after every v1.1.2 key) ----
        const auto fault = sbcore::fault::snapshot();
        add_text(b, "gate_reason", g_gate_ran.load(std::memory_order_acquire)
                                       ? sbcore::gate::reason_name(g_gate_reason.load()) : "not_run");
        add_text(b, "gate_failed", g_gate_ran.load(std::memory_order_acquire) ? g_gate_failed : "not_run");
        b.add_u64("gate_checks_passed", g_gate_checks_passed.load());
        add_flag(b, "fault_writes_blocked", sbcore::fault::writes_blocked());
        b.add_u64("fault_count", fault.fault_count);
        if (fault.fault_count == 0) std::snprintf(text, sizeof(text), "none");
        else std::snprintf(text, sizeof(text), "0x%08X@%s", fault.last_code, fault.last_action);
        add_text(b, "fault_last", text);
        b.add_u64("probe_misses", g_probe_misses.load());
        char state_read[40];
        add_text(b, "state_file_read", state_read_text(state_read, sizeof(state_read)));
        add_text(b, "dispatch_last_result", sbcore::dispatch::submit_result_name(dispatch.last_result));

        // ---- v1.3.0 additions (appended after every v1.2.1 key) ----
        // sbcore's Builder takes at most 256 keys and v1.2.1 wrote 254, so the
        // v1.3.0 state is exactly two keys: the panel-facing verdict and one
        // compact diagnostics value.
        const auto fh = g_first_hit.snapshot();
        add_text(b, "god_protection", id::protection_name(fh));
        // v1.3.1: the v1.3.0 fields keep their names and order (the panel
        // reads `proof`); the v1.3.1 fields are appended. fast_arms counts
        // eventor-proof arms; leak_guid is the GUID of the last passed-through
        // ApplyStat that lowered Eve's HP (apply_drops).
        char fast[4096];
        const int fast_size = std::snprintf(fast, sizeof(fast),
                      "path:%s;last_path:%s;proof:%s;class_ok:%d;ps_player_id:%d;actor_player_id:%d;"
                      "player_id_offset_ok:%d;"
                      "arm_after_candidate_ms:%llu;fast_arms:%llu;hook_arms:%llu;first_hit:%s;first_source:%s;"
                      "first_after_arm_ms:%llu;blocked:%llu;leaks:%llu;last_leak:%s;leak_guid:%u;shield_drops:%llu;"
                      "repairs:%llu;lethal_saved:%llu;diff_blocks:%llu;diff_echo_blocks:%llu;prearm_blocks:%llu;"
                      "unarmed_hits:%llu;apply_drops:%llu;resume_arms:%llu;eventor_guid:%u;ready:%d;"
                      "v131_sites_ok:%d;log_dropped:%llu;death_probe_id:134-forced-death-block-r2",
                      id::arm_path_name(g_arm_path.load()), id::arm_path_name(g_last_arm_path.load()),
                      id::direct_proof_name(g_direct_proof.load()), g_ue_class_ok.load() ? 1 : 0,
                      g_ue_player_id.load(), g_id_player_id.load(), g_ue_player_id_at_offset.load() ? 1 : 0,
                      static_cast<unsigned long long>(g_arm_after_candidate_ms.load()),
                      static_cast<unsigned long long>(g_fast_arms.load()),
                      static_cast<unsigned long long>(g_hook_arms.load()), id::first_hit_name(fh.state),
                      id::hit_event_name(fh.first), static_cast<unsigned long long>(fh.first_after_ms),
                      static_cast<unsigned long long>(fh.blocked), static_cast<unsigned long long>(fh.leaks),
                      id::hit_event_name(fh.last_leak), g_apply_leak_last_guid.load(),
                      static_cast<unsigned long long>(g_shield_drops.load()),
                      static_cast<unsigned long long>(fh.repairs), static_cast<unsigned long long>(fh.lethal_saved),
                      static_cast<unsigned long long>(g_diff_blocks.load()),
                      static_cast<unsigned long long>(g_diff_echo_blocks.load()),
                      static_cast<unsigned long long>(g_prearm_blocks.load()),
                      static_cast<unsigned long long>(g_unarmed_hits.load()),
                      static_cast<unsigned long long>(g_apply_drops.load()),
                      static_cast<unsigned long long>(g_resume_arms.load()), g_eventor_guid.load(),
                      g_ready_actor.load() != 0 ? 1 : 0, g_v131_sites_ok.load() ? 1 : 0,
                      static_cast<unsigned long long>(g_log_dropped.load()));
        // Keep the complete production schema at sbcore's existing 256-key
        // limit. The panel reads the first `proof` field; all prior names,
        // order and values above stay intact. Only cached diagnostic scalars
        // follow them. A formatting failure poisons the Builder, never
        // publishing a truncated record or a partial readiness footer.
        bool fast_ok = fast_size > 0 && static_cast<std::size_t>(fast_size) < sizeof(fast);
        std::size_t fast_used = fast_ok ? static_cast<std::size_t>(fast_size) : 0;
        const auto append_probe = [&](const char* name, std::uint64_t value) {
            if (!fast_ok) return;
            const auto remaining = sizeof(fast) - fast_used;
            const int count = std::snprintf(fast + fast_used, remaining, ";%s:%llu", name,
                                            static_cast<unsigned long long>(value));
            fast_ok = count > 0 && static_cast<std::size_t>(count) < remaining;
            if (fast_ok) fast_used += static_cast<std::size_t>(count);
        };
        append_probe("death_probe_attempts", g_death_probe_attempts.load());
        append_probe("death_probe_fields_failed", g_death_probe_fields_failed.load());
        append_probe("death_probe_withheld", g_death_probe_withheld.load());
        append_probe("death_probe_original_calls", g_death_probe_original_calls.load());
        append_probe("death_probe_original_returns", g_death_probe_original_returns.load());
        append_probe("death_probe_dropped", g_death_probe_dropped.load());
        std::array<std::uint64_t, DpCount> death_probe{};
        const bool death_probe_valid = death_probe_snapshot(death_probe);
        append_probe("death_probe_snapshot_valid", death_probe_valid ? 1u : 0u);
        static constexpr std::array<const char*, DpCount> probe_names{
            "death_probe_sequence", "death_probe_tick", "death_probe_thread", "death_probe_command_guid",
            "death_probe_actor", "death_probe_expected_guid", "death_probe_helper_guid", "death_probe_observed_guid",
            "death_probe_table_id", "death_probe_evaluated_mask", "death_probe_passed_mask", "death_probe_action",
            "death_probe_return_sequence", "death_probe_transition_parent_sequence", "death_probe_transition_tick",
            "death_probe_transition_thread", "death_probe_transition_actor", "death_probe_transition_guid",
            "death_probe_transition_caller", "death_probe_parse_failed_sequence", "death_probe_parse_failed_tick"};
        if (death_probe_valid)
            for (std::size_t i = 0; i < DpCount; ++i) append_probe(probe_names[i], death_probe[i]);
        // Implementation beta-burst r1: the energy record, 26 fields after
        // every existing one (no new key: the heartbeat is at sbcore's 256-key
        // limit). Same rules as above: a field that does not fit poisons the
        // whole value, never a cut-off record. Pool numbers are -1 when not read.
        const auto append_text = [&](const char* name, const char* value) {
            if (!fast_ok) return;
            const auto remaining = sizeof(fast) - fast_used;
            const int count = std::snprintf(fast + fast_used, remaining, ";%s:%s", name, value && value[0] ? value : "unknown");
            fast_ok = count > 0 && static_cast<std::size_t>(count) < remaining;
            if (fast_ok) fast_used += static_cast<std::size_t>(count);
        };
        const auto append_signed = [&](const char* name, std::int64_t value) {
            if (!fast_ok) return;
            const auto remaining = sizeof(fast) - fast_used;
            const int count = std::snprintf(fast + fast_used, remaining, ";%s:%lld", name, static_cast<long long>(value));
            fast_ok = count > 0 && static_cast<std::size_t>(count) < remaining;
            if (fast_ok) fast_used += static_cast<std::size_t>(count);
        };
        char energy_state[96];
        energy_state_text(energy_state, sizeof(energy_state));
        append_text("energy_id", kEnergyId);
        append_probe("energy_beta", g_desired_beta.load() ? 1u : 0u);
        append_probe("energy_burst", g_desired_burst.load() ? 1u : 0u);
        append_probe("energy_topup", g_desired_topup.load() ? 1u : 0u);
        append_probe("energy_armed", energy_live() ? 1u : 0u);
        append_text("energy_state", energy_state);
        append_probe("energy_sites_ok", g_energy_sites_ok.load() ? 1u : 0u);
        append_probe("energy_arms", g_energy_arms.load());
        append_probe("beta_spend_blocks", g_energy_spend_blocks[kEnergyBeta].load());
        append_probe("burst_spend_blocks", g_energy_spend_blocks[kEnergyBurst].load());
        append_probe("beta_fills", g_energy_fills[kEnergyBeta].load());
        append_probe("burst_fills", g_energy_fills[kEnergyBurst].load());
        append_probe("beta_topups", g_energy_topups[kEnergyBeta].load());
        append_probe("burst_topups", g_energy_topups[kEnergyBurst].load());
        append_probe("energy_topup_noeffect", g_energy_topup_noeffect.load());
        append_probe("energy_pool_refused", g_energy_pool_refused.load());
        append_probe("energy_other_caller", g_energy_other_caller.load());
        append_probe("energy_setter_lowered", g_energy_setter_lowered.load());
        append_probe("energy_calls_gt", g_energy_calls_gt.load());
        append_probe("energy_calls_other", g_energy_calls_other.load());
        append_signed("beta_now", g_energy_pool[kPoolBetaNow].load());
        append_signed("beta_max", g_energy_pool[kPoolBetaMax].load());
        append_signed("burst_now", g_energy_pool[kPoolBurstNow].load());
        append_signed("burst_max", g_energy_pool[kPoolBurstMax].load());
        append_signed("burst_unlocked", g_energy_pool[kPoolBurstUnlock].load());
        append_probe("energy_gt_thread", g_gt_thread_id.load());
        if (fast_ok) b.add_str("god_fast_arm", std::string_view(fast, fast_used));
        else b.add_str("god_fast_arm", {}); // Builder empty_value: retain the last complete file.
    }

    // install() and on_update() may run on different UE4SS threads; only one
    // writer may own the temporary file at a time.
    void write_native_heartbeat(bool force)
    {
        if (!g_paths_ready.load(std::memory_order_acquire)) return;
        bool expected = false;
        if (!g_heartbeat_busy.compare_exchange_strong(expected, true, std::memory_order_acq_rel)) return;
        sbcore::status::Builder b(g_heartbeat_buffer, sizeof(g_heartbeat_buffer));
        const auto beat = g_heartbeat_beat + 1;
        b.add_u64("beat", beat);
        const std::size_t fields_begin = b.view().size();
        append_heartbeat_fields(b);
        const std::size_t fields_end = b.view().size();
        const auto& counters = g_heartbeat_writer.counters();
        b.add_u64("sbcore_protocol", sbcore::kStatusProtocol);
        b.add_str("sbcore_version", sbcore::kVersion);
        b.add_str("sbcore_module", kModuleName);
        b.add_str("sbcore_module_version", sbgod::kVersion);
        b.add_u64("sbcore_pid", GetCurrentProcessId());
        b.add_u64("sbcore_seq", beat);
        b.add_u64("sbcore_write_failures", counters.write_failures);
        b.add_u64("sbcore_rename_failures", counters.rename_failures);
        if (!b.ok())
        {
            // Never publish (or truncate to) a body the panel's parser would reject.
            log_heartbeat_build_error(b.error());
            g_heartbeat_busy.store(false, std::memory_order_release);
            return;
        }
        const auto now = GetTickCount64();
        const auto fingerprint = sbcore::status::fnv1a64(b.view().substr(fields_begin, fields_end - fields_begin));
        const bool beat_due = !g_heartbeat_published || now - g_heartbeat_last_ms >= kHeartbeatBeatMs;
        if (force || beat_due || fingerprint != g_heartbeat_fingerprint)
        {
            if (g_heartbeat_writer.publish(b.view()) == sbcore::status::PublishResult::Published)
            {
                g_heartbeat_beat = beat;
                g_heartbeat_last_ms = now;
                g_heartbeat_fingerprint = fingerprint;
                g_heartbeat_published = true;
            }
        }
        g_heartbeat_busy.store(false, std::memory_order_release);
    }

    void set_install_error(const char* text)
    {
        if (g_install_error[0] == '\0' || std::strcmp(g_install_error, "not-installed") == 0)
            std::snprintf(g_install_error, sizeof(g_install_error), "%s", text);
    }

    // P1: every file is derived from this DLL's location; fails closed unless
    // the DLL sits in <...>\Mods\<ModName>\dlls. Written once, before
    // g_paths_ready is released.
    bool resolve_paths()
    {
        if (g_paths_ready.load(std::memory_order_acquire)) return true;
        sbcore::paths::ModulePaths paths;
        g_paths_error = sbcore::paths::resolve_this_module(paths);
        if (g_paths_error != sbcore::paths::Error::None) return false;
        sbcore::status::StableReader::Options reader{};
        reader.max_bytes = 4096;
        reader.grace_ms = kStateGraceMs;
        if (!g_heartbeat_writer.configure(paths.in_panel(kHeartbeatFileName), paths.in_panel(kHeartbeatTempFileName))
            || !g_state_reader.configure(paths.in_panel(kStateFileName), reader))
        {
            g_paths_error = sbcore::paths::Error::Layout;
            return false;
        }
        g_state_path = paths.in_panel(kStateFileName);
        g_log_path = paths.in_mod(kHookLogFileName);
        g_paths = std::move(paths);
        g_paths_ready.store(true, std::memory_order_release);
        return true;
    }

    void record_gate(const sbgod::gate::Outcome& outcome)
    {
        g_gate_reason.store(outcome.core.reason, std::memory_order_relaxed);
        g_gate_checks_passed.store(outcome.core.code_checks_passed + outcome.core.slot_checks_passed
                                       + outcome.core.global_checks_passed,
                                   std::memory_order_relaxed);
        if (outcome.core.passed)
            std::snprintf(g_gate_failed, sizeof(g_gate_failed), "none");
        else
            std::snprintf(g_gate_failed, sizeof(g_gate_failed), "%s/%s",
                          outcome.core.failed_manifest[0] ? outcome.core.failed_manifest : "unknown",
                          outcome.core.failed_check[0] ? outcome.core.failed_check : "unknown");
        g_gate_ran.store(true, std::memory_order_release);
    }
} // namespace

namespace sbgod
{
    bool hooks_installed()
    {
        return g_hooks_installed.load(std::memory_order_acquire);
    }

    const char* install_error()
    {
        return g_install_error;
    }

    bool install()
    {
        if (g_running.exchange(true, std::memory_order_acq_rel))
        {
            return g_hooks_installed.load(std::memory_order_acquire);
        }
        g_shutting_down.store(false, std::memory_order_release);

        // 1. P1: where am I. Without a proven Mods\<Mod>\dlls location there
        //    is no path to report through, so nothing at all is written.
        if (!resolve_paths())
        {
            char text[64];
            std::snprintf(text, sizeof(text), "paths_%s", sbcore::paths::error_name(g_paths_error));
            g_install_error[0] = '\0';
            set_install_error(text);
            g_hooks_installed.store(false, std::memory_order_release);
            g_install_done.store(true, std::memory_order_release);
            return false;
        }

        // 2. A9 stage 1: breadcrumb log + the process-wide write latch. Until
        //    this succeeds sbcore treats every game write as blocked.
        sbcore::fault::Config fault{};
        fault.native_name = kModuleName;
        fault.native_version = sbgod::kVersion;
        fault.log_path = g_paths.in_mod(kFaultLogFileName);
        fault.policy = sbcore::fault::Policy::ContinueFeatureOff;
        const bool fault_ready = sbcore::fault::init(fault);

        refresh_desired_state();

        // A hot-reloaded copy of this pinned module keeps its first install.
        if (g_patch.installed)
        {
            g_hooks_installed.store(true, std::memory_order_release);
            g_install_done.store(true, std::memory_order_release);
            write_native_heartbeat(true);
            return true;
        }

        // 3. A8/A11: the exact-build gate (sbcore + God's manifest), then
        //    God's own per-site validator. Read-only.
        auto* image = reinterpret_cast<std::byte*>(GetModuleHandleW(nullptr));
        const auto outcome = sbgod::gate::evaluate(image, nullptr);
        record_gate(outcome);
        g_build_timestamp.store(outcome.core.timestamp != 0 ? outcome.core.timestamp : outcome.god.timestamp,
                                std::memory_order_relaxed);
        g_build_size_of_image.store(outcome.core.image_size != 0 ? outcome.core.image_size : outcome.god.size_of_image,
                                    std::memory_order_relaxed);
        g_build_ok.store(outcome.build_ok, std::memory_order_relaxed);
        for (std::uint32_t i = 0; i < sites::kSiteCount; ++i) g_site_ok[i].store(outcome.god.site_ok[i]);
        for (std::uint32_t i = 0; i < sites::kAnchorCount; ++i) g_anchor_ok[i].store(outcome.god.anchor_ok[i]);
        {
            bool v131 = outcome.god.site_ok[sites::kApplyStatDiff];
            for (std::uint32_t i = sites::kAnchorCountV112; i < sites::kAnchorCount; ++i)
                v131 = v131 && outcome.god.anchor_ok[i];
            g_v131_sites_ok.store(v131, std::memory_order_relaxed);
        }
        g_taskgraph_ok.store(outcome.taskgraph_ok, std::memory_order_relaxed);
        g_validation_all_ok.store(outcome.all_ok, std::memory_order_relaxed);
        g_exe_file_size.store(outcome.exe_file_size, std::memory_order_relaxed);
        g_exe_file_size_ok.store(outcome.exe_file_size_ok, std::memory_order_relaxed);

        g_install_error[0] = '\0';
        bool ok = true;
        if (!outcome.all_ok)
        {
            set_install_error(outcome.install_error);
            ok = false;
        }
        else if (!life_state_read_site_ok(image))
        {
            // Implementation r2: same refusal as a failed anchor. No
            // hook is installed when DeathTransition does not read the life
            // state at +0x2600 the way the forced-death block expects.
            set_install_error("anchor-mismatch:DeathLifeStateRead");
            ok = false;
        }
        else if (!fault_ready)
        {
            set_install_error("fault_latch_unavailable");
            ok = false;
        }
        else if (sbcore::fault::writes_blocked())
        {
            // Another sbcore native already faulted in this process: no code
            // write of any kind (A9).
            set_install_error("writes_blocked");
            ok = false;
        }
        else if (!sbcore::module::pin_this_module())
        {
            // Without a pinned module an unload could leave jumps into freed code.
            set_install_error("module_pin_failed");
            ok = false;
        }
        else
        {
            g_module_pinned.store(true, std::memory_order_release);
            if (!sbcore::dispatch::bind(outcome.core))
            {
                set_install_error("dispatch_bind_failed");
                ok = false;
            }
        }

        if (ok)
        {
            g_image = image;
            const auto base = reinterpret_cast<std::uint64_t>(image);
            g_ret_dead_network.store(base + sites::kDeadNetworkReturnRva, std::memory_order_release);
            g_ret_dead_local.store(base + sites::kDeadLocalReturnRva, std::memory_order_release);
            g_ret_state_scoped.store(base + sites::kStateScopedReturnRva, std::memory_order_release);
            g_ret_apply_setter.store(base + sites::kApplyStatSetterReturnRva, std::memory_order_release);
            g_ret_diff_server.store(base + sites::kApplyDiffServerReturnRva, std::memory_order_release);
            g_ret_diff_echo.store(base + sites::kApplyDiffEchoReturnRva, std::memory_order_release);

            void* handlers[sites::kSiteCount]{};
            handlers[sites::kSetActorStat] = reinterpret_cast<void*>(&hook_set_actor_stat);
            handlers[sites::kApplyStatExecute] = reinterpret_cast<void*>(&hook_actor_apply_stat_execute);
            handlers[sites::kDeadExecute] = reinterpret_cast<void*>(&hook_actor_dead_execute);
            handlers[sites::kDeathTransition] = reinterpret_cast<void*>(&hook_actor_death_transition);
            handlers[sites::kActorStateChange] = reinterpret_cast<void*>(&hook_actor_state_change);
            handlers[sites::kApplyStatDiff] = reinterpret_cast<void*>(&hook_apply_stat_diff);
            std::atomic<void*>* slots[sites::kSiteCount]{};
            for (std::uint32_t i = 0; i < sites::kSiteCount; ++i) slots[i] = &g_original_slots[i];
            if (!sites::patch_all(image, handlers, slots, g_patch))
            {
                set_install_error(g_patch.error[0] ? g_patch.error : "patch_failed");
                ok = false;
            }
        }
        if (ok)
        {
            std::snprintf(g_install_error, sizeof(g_install_error), "none");
        }
        // Implementation beta-burst r1: the energy byte windows. A
        // mismatch is never an install error: God Mode is unaffected and only
        // the energy switches stay off, reported as not_supported/<window>.
        {
            const char* failed = ok ? energy_sites_failed(image) : "hooks_not_installed";
            std::snprintf(g_energy_site_error, sizeof(g_energy_site_error), "%s", failed ? failed : "none");
            g_energy_sites_ok.store(ok && failed == nullptr, std::memory_order_release);
        }
        g_hooks_installed.store(ok, std::memory_order_release);
        g_install_done.store(true, std::memory_order_release);
        write_install_log();
        write_native_heartbeat(true);
        return ok;
    }

    void on_update()
    {
        if (!g_running.load(std::memory_order_acquire) || !g_paths_ready.load(std::memory_order_acquire)) return;
        if (g_worker_thread_id.load(std::memory_order_relaxed) == 0)
            g_worker_thread_id.store(GetCurrentThreadId(), std::memory_order_release);
        const auto now = GetTickCount64();

        // A9: pick up a fault latched by any sbcore native (hooks read the
        // cached flag through god_live()).
        sbcore::fault::refresh_process_latch();

        if (now - g_last_state_poll_tick >= kStatePollMs)
        {
            g_last_state_poll_tick = now;
            refresh_desired_state();
            write_log_events(); // v1.3.1 F5: GameThread events and God on/off, within ~100 ms
            if (++g_log_counter >= kLogEveryStatePolls)
            {
                g_log_counter = 0;
                append_debug_log();
            }
        }

        const bool desired = g_desired_god.load(std::memory_order_acquire);
        // Disarming is always safe from any thread; arming happens only on
        // the GameThread after the identity is verified.
        if (!desired || dispatch_stopped()) g_god_live.store(false, std::memory_order_release);
        // beta-burst r1: the same for the energy switches (arming is GameThread-only, as for God).
        const bool energy = energy_wanted();
        if (!energy || dispatch_stopped()) g_energy_live.store(false, std::memory_order_release);

        if (g_hooks_installed.load(std::memory_order_acquire) && !dispatch_poisoned()
            && !g_shutting_down.load(std::memory_order_acquire))
        {
            const auto revision = g_config_revision.load(std::memory_order_acquire);
            const bool transition = revision != g_last_dispatched_revision;
            const bool periodic = (desired || energy) && !g_sc_fail_sticky.load(std::memory_order_acquire)
                && now - g_last_dispatch_tick >= kGameThreadPeriodMs;
            if ((transition || periodic) && dispatch_update())
            {
                g_last_dispatch_tick = now;
                g_last_dispatched_revision = revision;
            }
        }

        if (now - g_last_heartbeat_tick >= kHeartbeatPeriodMs)
        {
            g_last_heartbeat_tick = now;
            write_native_heartbeat(false);
        }
    }

    void uninstall()
    {
        // Never rewrite live game code or free trampolines on unload: a game
        // thread may be executing them. The module is pinned, so the hooks
        // stay valid and simply pass every call through while disarmed.
        g_shutting_down.store(true, std::memory_order_release);
        g_god_live.store(false, std::memory_order_release);
        g_energy_live.store(false, std::memory_order_release); // beta-burst r1
        g_running.store(false, std::memory_order_release);
        write_native_heartbeat(true);
    }

#if defined(SBGOD_WORKER_TEST_EXPORTS)
    namespace testing
    {
        bool probe_read_u32(const void* address, std::uint32_t* out)
        {
            return safe_read_u32(address, 0, out);
        }
    } // namespace testing
#endif
} // namespace sbgod
