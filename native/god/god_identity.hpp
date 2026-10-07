#pragma once

// Player-actor identity for SBGodNative v1.3.1 (no UE4SS dependency, so the
// offline identity test links it directly).
//
// Why this exists (v1.1.0 root cause, see VERIFY.txt):
//   * v1.1.0 read the actor GUID at actor+0x10C. On build 0x6A6A3B74 that
//     field is NOT the GUID: the game's own GUID accessor (vtable slot +0x38
//     of the actor interface at actor+0x10 -> 0xE4D660 `mov eax,[rcx+20h]`)
//     reads actor+0x30. +0x10C is a per-type id (Eve = 100, repeated across
//     same-type enemies), which is why "the player's GUID is 100" held in the
//     v1.0.x logs while the ApplyStat stream used another number (235, 228).
//   * v1.1.0 looked for the actor from the UE pawn (reflected "Property" /
//     "ActorProperty", then a pointer scan of pawn+0..0x3000). The FSB actor is
//     not reachable from the pawn that way (no such reflected property exists
//     on ASBCharacter; the actor lives in the local client's actor table), so
//     the reflection sample was always `no_actor`, and the hook sample site
//     (ApplyStat -> SetActorStat at 0x1B1F965) only runs on a server/local
//     stat mismatch, so it never sampled in normal play. God never armed.
//
// v1.1.1 identifies Eve's FSB actor through the local client's current-target
// chain -- the same read-only chain SBLiveAddNative v0.3.1 uses live on this
// build, and the same actor table ApplyStatExecute resolves [cmd+0x10] in --
// and requires every one of these independent signals before God may arm:
//   S1 chain     local-client cache -> target holder -> array[index] = E
//   S2 type      E+0x00 / E+0x10 are the certified FSB actor vtables, whose
//                GUID slot is the validated accessor (proves GUID at E+0x30)
//   S3 guid      G = E+0x30 is a compact non-zero id
//   S4 map       the read-only mirror of ApplyStatExecute's GUID lookup
//                (0x1AACE90 over holder+0x98) maps G back to exactly E, and
//                E is a member of the live-actor set at holder+0x48 that the
//                same function checks before returning (v1.1.2; v1.1.1 stopped
//                at the first .pdata chunk and accepted unregistered actors)
//   S5 type id   E+0x10C == 100 (Eve's per-type id; the v1.0.x "GUID 100")
//   S6 stats     Eve-scale HP/MaxHP in the instruction-proven Stat[] slots
//   S7 UE        exactly one live SBNetworkPlayerController with Pawn ==
//                AcknowledgedPawn and a PlayerState; PlayerState.ActorNetGuid,
//                when non-zero, must equal G (a contradiction blocks arming)
//   S8 stable    the same (E, G) on consecutive GameThread samples for >= 1 s
//   S9 hook      the game itself passed E (SetActorStat / ActorStateChange) or
//                G (ApplyStatExecute) to a hook while (E, G) was the candidate
//
// v1.3.0 fast arm: S9 waited for the game to touch Eve's stats (in practice
// her first hit), so the panel showed "Safety check" until then.
//
                                                                
                                                                          
// field in single player: its only writer (0x1B2C814, inside
// FSBActorManager::ChangePlayerActor) runs only when the net-mode word
                                                                           
                                                                        
                                                 
//
// The proof the game DOES fill in single player is the player id that links
// the FSB player actor to the local PlayerController:
//   * FSBActorManager::CreateActor (0x1AAC240; its log format names
//     "ActorGUID, bPlayer, PlayerId, PlayerIndex") stores its PlayerId
//     argument at E+0x4A0 (0x1AAC32C) before the actor enters the player
//     array and SetPlayerIndex (holder+0x3C) selects it; ChangePlayerActor
//     moves the id to the new player actor (0x1B2C735) and zeroes it on the
//     old one (0x1B2C73B). Only the actor currently owned by a player has it.
//   * The same id is UE's APlayerState::PlayerId (+0x2CC, reflected): the
//     game keys its SBNetworkGameMode PlayerId -> PlayerController map with
//     it (0x21FEE50, used by ChangePlayerActor at 0x1B2C7D2 with E+0x4A0) and
//     compares controllers by PlayerState(+0x2D0, IsA SBNetworkPlayerState)
//     .PlayerId(+0x2CC) when walking that map (0x22B73A0 / 0x22B73DE).
//     FSBActorLogicObject::CreateClientActor finds the player actor the same
//     way (`cmp eax, [rsi+4A0h]` over the player array, 0x1BA6E5B).
//   * Live: PlayerState.PlayerId is set in single player. SBRetryPointNative
//     reads this reflected field (it requires > 0) and passes it to the
//     game's own ServerRequest_WarpPosition(PlayerId, ...), which moved Eve
                                                              
                                                                           
//     tools\probe_player_id_readonly.py reads both ids from a running game
//     (evidence\live_playerid_probe_v130.txt).
// S9 is now satisfied by EITHER the hook evidence above OR the direct proof
//   S9' player   the local controller's PlayerState is exactly class
//                SBNetworkPlayerState (GetFullName class token), its reflected
//                PlayerId property sits at PlayerState+0x2CC, and its value is
//                non-zero and equal to E+0x4A0 (read on the same chain sample
//                that yields E and G)
// on top of S1..S8 unchanged (S4 is the damage path's own lookup: G -> E, so
// the GUID God protects is the one the damage path reports for E).
// Review B2: nothing is re-read. Both ids exist before E becomes the player
// actor (CreateActor writes E+0x4A0 before SetPlayerIndex; UE assigns
// PlayerId at login), so a zero or a mismatch at the one UE pass v1.2.1
// already runs simply leaves the decision to S9 exactly as v1.2.1 did: no
// extra FindAllOf. After any arm the first hit is still watched
// (FirstHitWatch): a hit that is not blocked is reported in the heartbeat,
// never silently.
//
                                             
                                                                     
//     read-only probe (evidence/live_playerid_probe_v130.txt) read 0 there on
//     Eve and on every other player-array actor, so the proof was always
//     `zero` and the fast arm never fired. The direct proof is now the game
//     world's own record of the player actor: the local-client cache the
//     chain already reads IS FSBGameWorld (LocalClient() -> FSBGameWorld::Init
//     (this), anchor GameWorldInitCall), and Init logs [this+0x80] as
//     "EventorActorGUID" (anchor EventorGuidInitLog). The same probe read
//     client+0x80 == 235 == G on Eve in all four samples. It is read on the
//     same chain walk as E and G, needs no UE work, and S1..S8 stay mandatory.
//   * Resume: once an (E, G) was verified in this process, the SAME pointer
//     with the SAME GUID (re-proven S1..S6 on this tick) re-verifies at once
                                                                              
                                                                             
                                                                              
//     failure of that pointer (freed, other GUID, other type, no longer in the
//     GUID map / live set) forgets it.
//     v1.3.2: the resume sample must pass the INITIAL stats rule (HP >= 1,
//     MaxHP <= kEveInitialMaxMaxHp), never the continuing one: 1.3.1 resumed
//     on HP 0 (God turned on at the death/retry screen) and the arm wrote the
//     MaxHP floor into the dead actor. A refused resume keeps the memory.
//   * Ready: when S1..S8 pass and only S9 is missing, the verdict says so
//     (Verdict::ready); the GameThread publishes (E, G) and the hooks treat the
//     game's own call on exactly that actor (pointer, GUID, type id re-read)
//     as S9 and withhold that hit (a skipped game write, never a new one).

#include "god_sites.hpp"

#include <atomic>
#include <cstddef>
#include <cstdint>

namespace sbgod::identity
{
    // ---- Instruction-proven layout (anchors in god_sites.cpp) -------------
    inline constexpr std::uintptr_t kLocalClientCacheRva = sites::kLocalClientCacheRva;    // 0x1A97C44 mov rax,[rip+..]
    inline constexpr std::uintptr_t kFsbActorVtableRva = sites::kActorVtableRva;           // E+0x00 (all table actors)
    inline constexpr std::uintptr_t kFsbActorIfaceVtableRva = sites::kActorIfaceVtableRva; // E+0x10, slot +0x38 -> 0xE4D660
    inline constexpr std::uint32_t kClientTargetHolderOffset = 0xC8;     // CurrentTargetGuid / ApplyStat
    inline constexpr std::uint32_t kHolderArrayOffset = 0x28;
    inline constexpr std::uint32_t kHolderCountOffset = 0x30;
    inline constexpr std::uint32_t kHolderIndexOffset = 0x3C;
    // TMap<uint32 guid, actor*> probed by 0x1AACE90 (rcx = holder):
    inline constexpr std::uint32_t kMapElementsOffset = 0x98;  // element data pointer
    inline constexpr std::uint32_t kMapNumOffset = 0xA0;       // sparse array Num
    inline constexpr std::uint32_t kMapNumFreeOffset = 0xCC;   // NumFreeIndices (Num == NumFree -> empty)
    inline constexpr std::uint32_t kMapHashInlineOffset = 0xD0;
    inline constexpr std::uint32_t kMapHashSecondaryOffset = 0xD8;
    inline constexpr std::uint32_t kMapHashSizeOffset = 0xE0;
    inline constexpr std::uint32_t kMapElementStride = 0x18;   // key +0, value +8, next +0x10
    // v1.1.2: 0x1AACE90 does NOT return the mapped actor directly. Its second
    // .pdata chunk (0x1AACF13) probes a second set at holder+0x48 keyed by the
    // actor pointer (0xF8CCF0, UE4 PointerHash) and returns the actor only if
    // it is still a member; otherwise it logs an error and returns null. The
    // mirror repeats that membership probe (same TSet layout, 0x48 lower).
    inline constexpr std::uint32_t kLiveSetElementsOffset = 0x48;   // 0x1AACF28 lea rdi,[r11+48h]; [rdi]
    inline constexpr std::uint32_t kLiveSetNumOffset = 0x50;        // [rdi+8]
    inline constexpr std::uint32_t kLiveSetNumFreeOffset = 0x7C;    // [rdi+34h]
    inline constexpr std::uint32_t kLiveSetHashInlineOffset = 0x80; // rdi+38h
    inline constexpr std::uint32_t kLiveSetHashSecondaryOffset = 0x88; // [rdi+40h]
    inline constexpr std::uint32_t kLiveSetHashSizeOffset = 0x90;   // [rdi+48h]
    inline constexpr std::uint32_t kLiveSetElementStride = 0x18;    // key actor* +0, next +0x10
    inline constexpr std::uint32_t kActorIfaceOffset = 0x10;
    inline constexpr std::uint32_t kActorGuidOffset = 0x30;    // iface + 0x20 (accessor 0xE4D660)
    inline constexpr std::uint32_t kActorTableIdOffset = 0x10C;
    inline constexpr std::uint32_t kEveTableId = 100;
    inline constexpr std::uint32_t kStatArrayOffset = 0x118;
    inline constexpr std::uint32_t kStatHpOffset = kStatArrayOffset + 1 * 4;
    inline constexpr std::uint32_t kStatMaxHpOffset = kStatArrayOffset + 2 * 4;
    inline constexpr std::uint32_t kStatShieldOffset = kStatArrayOffset + 7 * 4;

    inline constexpr std::int32_t kMaxHolderCount = 1 << 20;
    inline constexpr std::int32_t kMaxHashSize = 1 << 24;
    inline constexpr std::int32_t kMaxMapNum = 1 << 22;
    inline constexpr std::uint32_t kMaxProbeSteps = 4096;
    inline constexpr std::uint32_t kMaxActorGuid = 0x10000000u;

    // Initial verification wants a live Eve-scale pool; a verified actor keeps
    // passing with any finite HP in [0, max] so a lethal frame never disarms.
    inline constexpr float kEveMinMaxHp = 200.0f;
    inline constexpr float kEveInitialMaxMaxHp = 12000.0f;
    inline constexpr float kEveContinuingMaxMaxHp = 100000.0f;

    inline constexpr std::uint64_t kStableMs = 1000;
    inline constexpr std::uint32_t kStableSamples = 3;
    // A failed UE pass (FindAllOf costs 70-112 ms of GameThread time) is
    // retried after 1 s for the first attempts of a candidate, then every 5 s,
    // so a persistent S7 failure cannot stutter the game once per second.
    inline constexpr std::uint64_t kUeRetryMs = 1000;
    inline constexpr std::uint64_t kUeRetrySlowMs = 5000;
    inline constexpr std::uint32_t kUeFastAttempts = 3;

    // ---- v1.3.0 fast arm (S9') ---------------------------------------------
    // ASBNetworkPlayerState::ActorNetGuid: CXXHeaderDump +0x3C8, live object
    // dump `IntProperty /Script/SB.SBNetworkPlayerState:ActorNetGuid [o: 3C8]`,
    // and the game's writer `mov [rbx+3C8h], r14d` at 0x1B2C814 (verify_sites.py
    // compares this constant with that store). Only S7's contradiction check
    // reads it: the writer is network-mode only, so it is 0 in single player.
    inline constexpr std::uint32_t kPlayerStateNetGuidOffset = 0x3C8;
    inline constexpr const wchar_t* kPlayerStateClassName = L"SBNetworkPlayerState";
    // APlayerState::PlayerId: CXXHeaderDump Engine.hpp +0x2CC, live object dump
    // `IntProperty /Script/Engine.PlayerState:PlayerId [o: 2CC]`, and the
    // game's own reads `cmp/mov [r13+2CCh]` after IsA(SBNetworkPlayerState) at
    // 0x22B73A0 / 0x22B73DE (verify_sites.py). The UE pass reads it through
    // reflection and requires the reflected address to be PlayerState+0x2CC.
    inline constexpr std::uint32_t kPlayerStatePlayerIdOffset = 0x2CC;
    // FSB actor PlayerId: FSBActorManager::CreateActor `mov [rbx+4A0h], eax`
    // (0x1AAC32C, its PlayerId argument), ChangePlayerActor `mov [rdi+4A0h],
    // eax` / `mov dword ptr [r12+4A0h], 0` (0x1B2C735 / 0x1B2C73B)
    // (verify_sites.py compares this constant with those stores).
    inline constexpr std::uint32_t kActorPlayerIdOffset = 0x4A0;
    // v1.3.1 S9': FSBGameWorld (the local-client object) +0x80 =
    // CurrentZoneInfo.EventorActorGUID (anchor EventorGuidInitLog; verify_sites.py
    // compares this constant with Init's `mov r9d,[rsi+80h]` for that format).
    inline constexpr std::uint32_t kGameWorldEventorGuidOffset = 0x80;

    enum class Step : std::uint32_t
    {
        Ok,
        NoImage,
        NoLocalClient,
        ClientUnreadable,
        NoTargetHolder,
        HolderUnreadable,
        TargetIndexOutOfRange,
        TargetEntryNull,
        EntryUnreadable,
        VtableMismatch,
        ActorGuidInvalid,
        GuidMapInvalid,
        GuidMapMissing,
        GuidMapMismatch,
        TableIdNotEve,
        GuidMapNotLive, // v1.1.2: map(G) names an actor that is not in the live set (the game returns null)
    };
    const char* step_name(Step step);

    // NotLive: the GUID map has an entry, but its actor is not a member of the
    // live set at holder+0x48, so the game's own lookup returns null.
    enum class MapResult : std::uint32_t { Found, NotFound, Invalid, NotLive };

    // One read-only walk of the chain. Never calls game code, never writes.
    struct ChainSample
    {
        Step step{Step::NoImage};
        std::uint64_t client{};
        std::uint64_t holder{};
        std::int32_t index{-1};
        std::int32_t count{-1};
        std::uint64_t actor{};
        std::uint64_t vtable{};
        std::uint64_t iface_vtable{};
        bool vtables_ok{};
        std::uint32_t guid{};
        MapResult map{MapResult::Invalid};
        std::uint64_t mapped_actor{};
        std::uint32_t table_id{};
        float hp{};
        float max_hp{};
        float shield{};
        bool stats_read{};
        // v1.3.0: E+0x4A0, read on the same walk as E and G. It never decides
        // `step`. v1.3.1: telemetry only (0 on this build in single player).
        std::int32_t player_id{};
        bool player_id_read{};
        // v1.3.1 (S9'): FSBGameWorld.CurrentZoneInfo.EventorActorGUID, read
        // from the same client on the same walk. It never decides `step`.
        std::uint32_t eventor_guid{};
        bool eventor_read{};
    };

    // `image` is the certified module base (0x140000000 in the game).
    ChainSample sample_chain(const std::byte* image);

    // Read-only mirror of the whole of 0x1AACE90 (all three .pdata chunks):
    // the GUID TMap probe, then the live-set membership probe of the mapped
    // actor (0xF8CCF0). Found only when the game would return the actor.
    // `actor_out` is the GUID map's value when Found or NotLive, else 0.
    MapResult mirror_guid_map_lookup(std::uint64_t holder, std::uint32_t guid, std::uint64_t* actor_out);

    // 0xF8CD17..0xF8CDA0: UE4 PointerHash(key) = HashCombine((uint32)(key >> 4), 0).
    std::uint32_t live_set_pointer_hash(std::uint64_t key);

    // Reads E+0x30 through the proven offset (SEH-safe). False if unreadable.
    bool read_actor_guid(const void* actor, std::uint32_t* guid);
    bool read_actor_table_id(const void* actor, std::uint32_t* table_id);

    bool eve_scale_initial(float hp, float max_hp);
    bool eve_scale_continuing(float hp, float max_hp);

    // UE-side snapshot (filled by the GameThread reflection pass only).
    struct UeSnapshot
    {
        bool ran{};
        std::uint64_t ran_ms{};
        std::uint32_t controllers_found{};
        std::uint32_t controllers_viable{};
        std::uint64_t controller{};
        std::uint64_t pawn{};
        bool pawn_acknowledged{};
        std::uint64_t player_state{};
        std::uint64_t netguid_field{};
        std::int32_t netguid_value{};
        bool exception{};
        // v1.3.0 (S9'): filled only when player_state != 0. A failure here
        // never fails ue_ok(); it only withholds the direct proof.
        bool player_state_class_ok{}; // GetFullName class token == kPlayerStateClassName
        bool netguid_read{};          // the reflected ActorNetGuid was read (SEH-safe; S7 telemetry)
        std::uint64_t player_id_field{}; // reflected APlayerState::PlayerId address (0 = absent)
        std::int32_t player_id_value{};
        bool player_id_read{};           // the reflected PlayerId was read (SEH-safe)
    };

    // Why the direct proof (S9') does or does not hold. v1.3.1: the proof is
    // FSBGameWorld.EventorActorGUID == G (the values NoPlayerState ..
    // OffsetMismatch belonged to the v1.3.0 PlayerId link and are no longer
    // produced; their names stay reserved for old logs).
    enum class DirectProof : std::uint32_t
    {
        NotChecked,     // no Ok chain sample, or S7 (UE) has not passed for this candidate yet
        NoPlayerState,  // (v1.3.0 only)
        ClassMismatch,  // (v1.3.0 only)
        FieldAbsent,    // (v1.3.0 only)
        OffsetMismatch, // (v1.3.0 only)
        Unread,         // client+0x80 could not be read
        Zero,           // EventorActorGUID is 0 (no player actor recorded)
        Mismatch,       // non-zero and != G: the world names another actor
        Match,          // EventorActorGUID == G != 0: S9' holds
    };
    const char* direct_proof_name(DirectProof proof);

    // Pure: the S9' verdict for one chain sample (EventorActorGUID and G come
    // from the same walk). NotChecked unless the sample's step is Ok.
    DirectProof direct_proof(const ChainSample& sample);

    // True when `full_name` (UObject::GetFullName: "<Class> <Outer.Path>")
    // names exactly `class_name` as its class token.
    bool full_name_class_is(const wchar_t* full_name, std::size_t length, const wchar_t* class_name);

    // How the current identity was verified (heartbeat god_fast_arm path).
    // v1.3.1: Eventor replaces v1.3.0's PlayerId (same slot), Resume is new.
    enum class ArmPath : std::uint32_t { None, Eventor, HookCorroboration, Resume };
    const char* arm_path_name(ArmPath path);

    // v1.3.1: the stat change the hooks withhold from the proven Eve: a finite,
    // strictly negative change of HP (1) or Shield (7). Anything else (heals,
    // other stats, NaN/inf which the game itself zeroes, -0) passes through.
    bool is_vital_damage(int stat, float diff);

    enum class Reason : std::uint32_t
    {
        Verified,
        HooksNotInstalled,
        GodOff,
        Chain,              // see ChainSample::step
        StatsNotEveScale,
        UeNotChecked,
        NoController,
        ControllerAmbiguous,
        NoPawn,
        PawnNotAcknowledged,
        NoPlayerState,
        NetGuidMismatch,
        UeException,
        Unstable,
        WaitingForHookCorroboration,
    };
    const char* reason_name(Reason reason);

    // GameThread-owned candidate tracker.
    struct Tracker
    {
        std::uint64_t cand_actor{};
        std::uint32_t cand_guid{};
        std::uint64_t cand_since_ms{};
        std::uint32_t cand_samples{};
        bool verified{};
        std::uint64_t verified_since_ms{};
        std::uint64_t candidate_changes{};
        std::uint32_t ue_attempts{}; // UE passes requested for this candidate (v1.2.1 rule only)
        ArmPath arm_path{ArmPath::None}; // v1.3.0: set when verified
        // v1.3.1: the last (E, G) verified in this process. Survives every
        // tracker reset (chain gap, God off); cleared only by a per-actor
        // chain failure of that pointer, or replaced by the next verification.
        std::uint64_t resume_actor{};
        std::uint32_t resume_guid{};
    };

    struct Verdict
    {
        bool verified{};
        Reason reason{Reason::Chain};
        bool candidate_changed{}; // caller resets hook corroboration and the UE snapshot
        bool want_ue_check{};     // caller should run the UE pass on this tick
        std::uint64_t stable_ms{};
        ArmPath arm_path{ArmPath::None};           // v1.3.0: how `verified` was reached
        DirectProof direct{DirectProof::NotChecked}; // v1.3.0: S9' for this sample
        bool ready{};    // v1.3.1: S1..S8 hold on this sample and only S9 is missing
        bool resumed{};  // v1.3.1: verified on this sample by the resume rule
    };

    // Clears the tracker for a new candidate search while keeping the
    // counters and the resume memory (v1.3.1).
    void reset_tracker(Tracker& tracker);

    // Pure decision over one chain sample. `ue` must belong to the current
    // candidate (the caller clears it when candidate_changed is reported).
    // `count_sample` is false when the caller re-evaluates the same sample
    // after a UE pass, so one chain sample is never counted twice.
    Verdict evaluate(Tracker& tracker, const ChainSample& sample, const UeSnapshot& ue,
                     std::uint64_t corroborations, std::uint64_t now_ms, bool count_sample = true);

    // True when the UE snapshot, taken for the current candidate, contains no
    // missing piece and no contradiction of `guid`. `why` receives the reason.
    bool ue_ok(const UeSnapshot& ue, std::uint32_t guid, Reason* why);

    // ---- v1.3.0 first-hit watch (v1.3.1 classes) ----------------------------
    // Every arm (any path) starts a watch. The first damage event on the
    // verified actor after the arm decides the verdict. v1.3.1 sorts every
    // event into one of three classes (GOD-130-DIAGNOSIS.md F4):
    //   blocked  - the damage never reached Eve's pool;
    //   repaired - it reached the pool and God put it back before it could
    //              matter: the same GameThread tick restored HP to the floor,
    //              or the lethal fallback restored the pre-hit HP before the
    //              game's death processing ran (Eve kept her HP; 1.2.1's
    //              "2000/2000" was exactly this);
    //   leak     - real HP loss on Eve: HP still below the floor after the
    //              repair attempt, or a death command for her GUID.
    // Only leaks make god_protection = damage_got_through; repairs are
    // counted and reported separately (heartbeat, native_hook.log).
    enum class FirstHit : std::uint32_t { Off, Pending, Blocked, NotBlocked, Repaired };
    enum class HitEvent : std::uint32_t
    {
        None,
        // Blocked: the damage never reached Eve's pool.
        ApplyConsumed, // ApplyStatExecute consumed a damage command for the verified GUID
        SetterBlocked, // the SetActorStat hook kept the verified actor's HP/Shield
        // Leak: real HP loss on Eve.
        ApplyLeak,     // (v1.3.0 only; v1.3.1 counts passed-through drops as telemetry and lets the tick classify them)
        TickDrop,      // v1.3.1: HP fell between two ticks (MaxHP unchanged) and was STILL below the floor after the restore
        // Repaired (v1.3.1; v1.3.0 counted this as a leak).
        LethalRestore, // the scoped stat update left HP at 0 and the lethal fallback restored the pre-hit HP
        // Leak.
        DeathCommand,  // the game issued a death command for the verified GUID
        // ---- v1.3.1 ----
        DiffBlocked,   // blocked: the ApplyStatDiff hook withheld the change before the game wrote Stat[]
        TickRepaired,  // repaired: HP fell between two ticks and this tick's restore brought it back to the floor
        DeathBlocked,  // blocked: the death command for the armed, current Eve was withheld
    };
    enum class HitClass : std::uint32_t { None, Blocked, Repaired, Leak };
    const char* first_hit_name(FirstHit state);
    const char* hit_event_name(HitEvent event);
    HitClass hit_event_class(HitEvent event);
    bool hit_event_is_leak(HitEvent event);

    class FirstHitWatch
    {
      public:
        struct Snapshot
        {
            FirstHit state{FirstHit::Off};
            HitEvent first{HitEvent::None};
            std::uint64_t first_after_ms{};
            std::uint64_t blocked{};
            std::uint64_t leaks{};
            HitEvent last_leak{HitEvent::None};
            std::uint64_t arms{};
            std::uint64_t repairs{};      // v1.3.1: TickRepaired events this arm
            std::uint64_t lethal_saved{}; // v1.3.1: LethalRestore events this arm
        };

        // GameThread: a new arm -> Pending with cleared counters.
        void arm(std::uint64_t now_ms) noexcept;
        // GameThread: disarmed -> Off (counters kept for the heartbeat).
        void disarm() noexcept;
        // Any thread (hooks). Ignored while Off.
        void note(HitEvent event, std::uint64_t now_ms) noexcept;
        Snapshot snapshot() const noexcept;

      private:
        std::atomic<std::uint32_t> state_{static_cast<std::uint32_t>(FirstHit::Off)};
        std::atomic<std::uint32_t> first_{static_cast<std::uint32_t>(HitEvent::None)};
        std::atomic<std::uint64_t> armed_ms_{0};
        std::atomic<std::uint64_t> first_after_ms_{0};
        std::atomic<std::uint64_t> blocked_{0};
        std::atomic<std::uint64_t> leaks_{0};
        std::atomic<std::uint32_t> last_leak_{static_cast<std::uint32_t>(HitEvent::None)};
        std::atomic<std::uint64_t> arms_{0};
        std::atomic<std::uint64_t> repairs_{0};
        std::atomic<std::uint64_t> lethal_saved_{0};
    };

    // "off" | "pending_first_hit" | "confirmed" | "damage_got_through"
    const char* protection_name(const FirstHitWatch::Snapshot& snapshot);
} // namespace sbgod::identity
