#include "god_identity.hpp"

#include "god_sites.hpp"

#include <cmath>
#include <cstring>
#include <cwchar>

#include <windows.h>

namespace sbgod::identity
{
    namespace
    {
        bool plausible_pointer(std::uint64_t address)
        {
            return address >= 0x10000ULL && address <= 0x7FFFFFFFFFFFULL && (address & 7ULL) == 0;
        }

        // SEH-isolated copy; the caller has already checked the region.
        bool seh_copy(void* out, const void* from, std::size_t size)
        {
            __try
            {
                std::memcpy(out, from, size);
                return true;
            }
            __except (EXCEPTION_EXECUTE_HANDLER)
            {
                return false;
            }
        }

        // Committed, not PAGE_GUARD / PAGE_NOACCESS, whole range inside one
        // region, then an SEH-protected copy. Never touches guard pages.
        bool read_bytes(std::uint64_t address, void* out, std::size_t size)
        {
            if (address < 0x10000ULL || address > 0x7FFFFFFFFFFFULL) return false;
            const auto* p = reinterpret_cast<const void*>(address);
            return sites::is_readable_region(p, size, false) && seh_copy(out, p, size);
        }

        bool read_u64(std::uint64_t address, std::uint64_t* out) { return read_bytes(address, out, sizeof(*out)); }
        bool read_u32(std::uint64_t address, std::uint32_t* out) { return read_bytes(address, out, sizeof(*out)); }
        bool read_i32(std::uint64_t address, std::int32_t* out) { return read_bytes(address, out, sizeof(*out)); }
        bool read_f32(std::uint64_t address, float* out) { return read_bytes(address, out, sizeof(*out)); }
    } // namespace

    const char* step_name(Step step)
    {
        switch (step)
        {
        case Step::Ok: return "ok";
        case Step::NoImage: return "no_image";
        case Step::NoLocalClient: return "no_local_client";
        case Step::ClientUnreadable: return "client_unreadable";
        case Step::NoTargetHolder: return "no_target_holder";
        case Step::HolderUnreadable: return "holder_unreadable";
        case Step::TargetIndexOutOfRange: return "target_index_out_of_range";
        case Step::TargetEntryNull: return "target_entry_null";
        case Step::EntryUnreadable: return "entry_unreadable";
        case Step::VtableMismatch: return "vtable_mismatch";
        case Step::ActorGuidInvalid: return "actor_guid_invalid";
        case Step::GuidMapInvalid: return "guid_map_invalid";
        case Step::GuidMapMissing: return "guid_map_missing";
        case Step::GuidMapMismatch: return "guid_map_mismatch";
        case Step::TableIdNotEve: return "table_id_not_eve";
        case Step::GuidMapNotLive: return "guid_map_actor_not_live";
        }
        return "unknown";
    }

    const char* reason_name(Reason reason)
    {
        switch (reason)
        {
        case Reason::Verified: return "verified";
        case Reason::HooksNotInstalled: return "hooks_not_installed";
        case Reason::GodOff: return "god_off";
        case Reason::Chain: return "chain";
        case Reason::StatsNotEveScale: return "stats_not_eve_scale";
        case Reason::UeNotChecked: return "ue_not_checked";
        case Reason::NoController: return "no_controller";
        case Reason::ControllerAmbiguous: return "controller_ambiguous";
        case Reason::NoPawn: return "no_pawn";
        case Reason::PawnNotAcknowledged: return "pawn_not_acknowledged";
        case Reason::NoPlayerState: return "no_playerstate";
        case Reason::NetGuidMismatch: return "netguid_mismatch";
        case Reason::UeException: return "ue_exception";
        case Reason::Unstable: return "unstable";
        case Reason::WaitingForHookCorroboration: return "waiting_for_hook_corroboration";
        }
        return "unknown";
    }

    bool read_actor_guid(const void* actor, std::uint32_t* guid)
    {
        if (!actor || !guid) return false;
        return read_u32(reinterpret_cast<std::uint64_t>(actor) + kActorGuidOffset, guid);
    }

    bool read_actor_table_id(const void* actor, std::uint32_t* table_id)
    {
        if (!actor || !table_id) return false;
        return read_u32(reinterpret_cast<std::uint64_t>(actor) + kActorTableIdOffset, table_id);
    }

    bool eve_scale_initial(float hp, float max_hp)
    {
        return std::isfinite(hp) && std::isfinite(max_hp) && max_hp >= kEveMinMaxHp
            && max_hp <= kEveInitialMaxMaxHp && hp >= 1.0f && hp <= max_hp + 1.0f;
    }

    bool eve_scale_continuing(float hp, float max_hp)
    {
        return std::isfinite(hp) && std::isfinite(max_hp) && max_hp >= kEveMinMaxHp
            && max_hp <= kEveContinuingMaxMaxHp && hp >= 0.0f && hp <= max_hp + 1.0f;
    }

    std::uint32_t live_set_pointer_hash(std::uint64_t key)
    {
        // 0xF8CD17..0xF8CD96, instruction for instruction. With C == 0 the
        // leading `A += B; A -= B; A -= C; A ^= C >> 13` of HashCombine is the
        // identity, which is why the compiled code starts at `B -= A`.
        std::uint32_t a = static_cast<std::uint32_t>(key >> 4); // shr r10,4
        std::uint32_t b = 0x9E3779B9u;                          // mov r9d,9E3779B9h
        std::uint32_t c = 0;
        b -= c; b -= a; b ^= (a << 8);
        c -= a; c -= b; c ^= (b >> 13);
        a -= b; a -= c; a ^= (c >> 12);
        b -= c; b -= a; b ^= (a << 16);
        c -= a; c -= b; c ^= (b >> 5);
        a -= b; a -= c; a ^= (c >> 3);
        b -= c; b -= a; b ^= (a << 10);
        c -= a; c -= b; c ^= (b >> 15);
        return c;
    }

    namespace
    {
        // One UE TSet (sparse element array + hash) as both probes read it.
        // Offsets are absolute from the holder.
        struct SetLayout
        {
            std::uint32_t elements;
            std::uint32_t num;
            std::uint32_t num_free;
            std::uint32_t hash_inline;
            std::uint32_t hash_secondary;
            std::uint32_t hash_size;
            std::uint32_t stride;
        };
        constexpr SetLayout kGuidMapLayout{kMapElementsOffset, kMapNumOffset, kMapNumFreeOffset, kMapHashInlineOffset,
                                           kMapHashSecondaryOffset, kMapHashSizeOffset, kMapElementStride};
        constexpr SetLayout kLiveSetLayout{kLiveSetElementsOffset, kLiveSetNumOffset, kLiveSetNumFreeOffset,
                                           kLiveSetHashInlineOffset, kLiveSetHashSecondaryOffset,
                                           kLiveSetHashSizeOffset, kLiveSetElementStride};

        // Finds the element whose key (key_size bytes at element+0) equals
        // `key`, walking the bucket chain exactly as the game does:
        //   Num == NumFreeIndices -> not found (0x1AACE96 / 0xF8CD06)
        //   table = secondary ? secondary : holder+inline; bucket = hash & (HashSize-1)
        //   index = table[bucket]; element = elements + index*0x18; next = [element+0x10]
        // Every read is bounded and SEH-isolated; anything the game would not
        // have produced (bad size, index out of range, cycle) is Invalid.
        MapResult probe_set(std::uint64_t holder, const SetLayout& l, std::uint32_t hash, std::uint64_t key,
                            std::size_t key_size, std::uint64_t* element_out)
        {
            *element_out = 0;
            std::int32_t num = 0;
            std::int32_t num_free = 0;
            std::int32_t hash_size = 0;
            std::uint64_t secondary = 0;
            std::uint64_t elements = 0;
            if (!read_i32(holder + l.num, &num) || !read_i32(holder + l.num_free, &num_free)
                || !read_i32(holder + l.hash_size, &hash_size) || !read_u64(holder + l.hash_secondary, &secondary)
                || !read_u64(holder + l.elements, &elements))
            {
                return MapResult::Invalid;
            }
            if (num == num_free) return MapResult::NotFound;
            if (num < 0 || num > kMaxMapNum || hash_size <= 0 || hash_size > kMaxHashSize
                || (hash_size & (hash_size - 1)) != 0)
            {
                return MapResult::Invalid;
            }
            // HashSize - 1 < 2^31, so masking the sign-extended 64-bit hash
            // the game computes equals masking the 32-bit value.
            const std::uint64_t table = secondary != 0 ? secondary : holder + l.hash_inline;
            const auto bucket = static_cast<std::uint64_t>(hash) & static_cast<std::uint64_t>(hash_size - 1);
            std::int32_t index = -1;
            if (!read_i32(table + bucket * sizeof(std::int32_t), &index)) return MapResult::Invalid;
            if (index != -1 && !plausible_pointer(elements)) return MapResult::Invalid;
            for (std::uint32_t steps = 0; index != -1; ++steps)
            {
                if (steps >= kMaxProbeSteps || index < 0 || index >= num) return MapResult::Invalid;
                const std::uint64_t element = elements + static_cast<std::uint64_t>(index) * l.stride;
                std::uint64_t element_key = 0;
                if (!read_bytes(element, &element_key, key_size)) return MapResult::Invalid;
                if (element_key == key)
                {
                    *element_out = element;
                    return MapResult::Found;
                }
                if (!read_i32(element + 0x10, &index)) return MapResult::Invalid;
            }
            return MapResult::NotFound;
        }
    } // namespace

    MapResult mirror_guid_map_lookup(std::uint64_t holder, std::uint32_t guid, std::uint64_t* actor_out)
    {
        if (actor_out) *actor_out = 0;
        if (!plausible_pointer(holder) || !actor_out) return MapResult::Invalid;
        // Chunk 1 (0x1AACE90..0x1AACF11): GUID TMap probe, key uint32 == guid.
        std::uint64_t element = 0;
        const auto by_guid = probe_set(holder, kGuidMapLayout, guid, guid, sizeof(std::uint32_t), &element);
        if (by_guid != MapResult::Found) return by_guid;
        // 0x1AACF03..0x1AACF1D: value pointer = element + 8, actor = [value].
        std::uint64_t actor = 0;
        if (!read_u64(element + 8, &actor)) return MapResult::Invalid;
        *actor_out = actor;
        // Chunk 2 (0x1AACF13..0x1AACF6B): FindId(holder+0x48, actor) via
        // 0xF8CCF0 (key = the actor pointer, PointerHash); INDEX_NONE ->
        // chunk 3 (0x1AACF6C) logs and returns null.
        std::uint64_t live_element = 0;
        const auto live = probe_set(holder, kLiveSetLayout, live_set_pointer_hash(actor), actor,
                                    sizeof(std::uint64_t), &live_element);
        if (live == MapResult::Invalid) return MapResult::Invalid;
        if (live != MapResult::Found) return MapResult::NotLive;
        return MapResult::Found;
    }

    ChainSample sample_chain(const std::byte* image)
    {
        ChainSample s{};
        if (!image)
        {
            s.step = Step::NoImage;
            return s;
        }
        const auto base = reinterpret_cast<std::uint64_t>(image);
        // The local-client cache is read, never created: the lazy getter
        // 0x1A97C40 is not called.
        std::uint64_t client = 0;
        if (!read_u64(base + kLocalClientCacheRva, &client))
        {
            s.step = Step::NoImage;
            return s;
        }
        s.client = client;
        if (client == 0)
        {
            s.step = Step::NoLocalClient;
            return s;
        }
        std::uint64_t holder = 0;
        if (!plausible_pointer(client) || !read_u64(client + kClientTargetHolderOffset, &holder))
        {
            s.step = Step::ClientUnreadable;
            return s;
        }
        // v1.3.1 (S9'): the game world's EventorActorGUID on the same client.
        // A miss only withholds the direct proof.
        s.eventor_read = read_u32(client + kGameWorldEventorGuidOffset, &s.eventor_guid);
        s.holder = holder;
        if (holder == 0)
        {
            s.step = Step::NoTargetHolder;
            return s;
        }
        std::int32_t index = -1;
        std::int32_t count = -1;
        std::uint64_t array = 0;
        if (!plausible_pointer(holder) || !read_i32(holder + kHolderIndexOffset, &index)
            || !read_i32(holder + kHolderCountOffset, &count) || !read_u64(holder + kHolderArrayOffset, &array))
        {
            s.step = Step::HolderUnreadable;
            return s;
        }
        s.index = index;
        s.count = count;
        if (count < 0 || count > kMaxHolderCount)
        {
            s.step = Step::HolderUnreadable;
            return s;
        }
        if (index < 0 || index >= count)
        {
            s.step = Step::TargetIndexOutOfRange;
            return s;
        }
        std::uint64_t actor = 0;
        if (!plausible_pointer(array)
            || !read_u64(array + static_cast<std::uint64_t>(index) * sizeof(std::uint64_t), &actor))
        {
            s.step = Step::HolderUnreadable;
            return s;
        }
        s.actor = actor;
        if (actor == 0)
        {
            s.step = Step::TargetEntryNull;
            return s;
        }
        if (!plausible_pointer(actor) || !read_u64(actor, &s.vtable)
            || !read_u64(actor + kActorIfaceOffset, &s.iface_vtable)
            || !read_u32(actor + kActorGuidOffset, &s.guid) || !read_u32(actor + kActorTableIdOffset, &s.table_id)
            || !read_f32(actor + kStatHpOffset, &s.hp) || !read_f32(actor + kStatMaxHpOffset, &s.max_hp)
            || !read_f32(actor + kStatShieldOffset, &s.shield))
        {
            s.step = Step::EntryUnreadable;
            return s;
        }
        s.stats_read = true;
        // v1.3.0 (S9'): the actor's PlayerId (E+0x4A0). A miss only withholds
        // the direct proof; the chain verdict below is v1.2.1's.
        s.player_id_read = read_i32(actor + kActorPlayerIdOffset, &s.player_id);
        s.vtables_ok = s.vtable == base + kFsbActorVtableRva && s.iface_vtable == base + kFsbActorIfaceVtableRva;
        if (!s.vtables_ok)
        {
            s.step = Step::VtableMismatch;
            return s;
        }
        if (s.guid == 0 || s.guid >= kMaxActorGuid)
        {
            s.step = Step::ActorGuidInvalid;
            return s;
        }
        s.map = mirror_guid_map_lookup(holder, s.guid, &s.mapped_actor);
        if (s.map == MapResult::Invalid)
        {
            s.step = Step::GuidMapInvalid;
            return s;
        }
        if (s.map == MapResult::NotFound)
        {
            s.step = Step::GuidMapMissing;
            return s;
        }
        if (s.map == MapResult::NotLive)
        {
            s.step = Step::GuidMapNotLive;
            return s;
        }
        if (s.mapped_actor != actor)
        {
            s.step = Step::GuidMapMismatch;
            return s;
        }
        if (s.table_id != kEveTableId)
        {
            s.step = Step::TableIdNotEve;
            return s;
        }
        s.step = Step::Ok;
        return s;
    }

    bool ue_ok(const UeSnapshot& ue, std::uint32_t guid, Reason* why)
    {
        Reason r = Reason::Verified;
        if (!ue.ran) r = Reason::UeNotChecked;
        else if (ue.exception) r = Reason::UeException;
        else if (ue.controllers_viable == 0) r = ue.controllers_found == 0 ? Reason::NoController : Reason::NoPawn;
        else if (ue.controllers_viable > 1) r = Reason::ControllerAmbiguous;
        else if (ue.controller == 0 || ue.pawn == 0) r = Reason::NoPawn;
        else if (!ue.pawn_acknowledged) r = Reason::PawnNotAcknowledged;
        else if (ue.player_state == 0) r = Reason::NoPlayerState;
        else if (ue.netguid_value != 0 && static_cast<std::uint32_t>(ue.netguid_value) != guid) r = Reason::NetGuidMismatch;
        if (why) *why = r;
        return r == Reason::Verified;
    }

    void reset_tracker(Tracker& t)
    {
        const auto changes = t.candidate_changes;
        const auto resume_actor = t.resume_actor;
        const auto resume_guid = t.resume_guid;
        t = Tracker{};
        t.candidate_changes = changes;
        t.resume_actor = resume_actor;
        t.resume_guid = resume_guid;
    }

    namespace
    {
        // v1.3.1: the resume memory is forgotten as soon as the chain reaches
        // that very pointer and the actor itself fails (freed or unreadable,
        // another vtable/GUID/type, no longer the game's map(G) or not in the
        // live set). Failures before the actor is reached (no client, no
        // holder, no current target: menus and loading) say nothing about it.
        void forget_resume_on_actor_failure(Tracker& t, const ChainSample& s)
        {
            if (t.resume_actor == 0 || s.actor != t.resume_actor) return;
            switch (s.step)
            {
            case Step::Ok:
                if (s.guid != t.resume_guid) break; // same pointer, new actor
                return;
            case Step::NoImage:
            case Step::NoLocalClient:
            case Step::ClientUnreadable:
            case Step::NoTargetHolder:
            case Step::HolderUnreadable:
            case Step::TargetIndexOutOfRange:
            case Step::TargetEntryNull:
                return;
            default:
                break;
            }
            t.resume_actor = 0;
            t.resume_guid = 0;
        }
    } // namespace

    Verdict evaluate(Tracker& t, const ChainSample& s, const UeSnapshot& ue, std::uint64_t corroborations,
                     std::uint64_t now_ms, bool count_sample)
    {
        Verdict v{};
        forget_resume_on_actor_failure(t, s);
        if (s.step != Step::Ok)
        {
            if (t.cand_actor != 0 || t.cand_guid != 0)
            {
                v.candidate_changed = true;
                ++t.candidate_changes;
            }
            reset_tracker(t);
            v.reason = Reason::Chain;
            return v;
        }
        if (s.actor != t.cand_actor || s.guid != t.cand_guid)
        {
            v.candidate_changed = true;
            ++t.candidate_changes;
            t.cand_actor = s.actor;
            t.cand_guid = s.guid;
            t.cand_since_ms = now_ms;
            t.cand_samples = 0;
            t.verified = false;
            t.verified_since_ms = 0;
            t.ue_attempts = 0;
            t.arm_path = ArmPath::None;
        }
        if (count_sample && t.cand_samples < 0xFFFFFFFFu) ++t.cand_samples;
        v.stable_ms = now_ms - t.cand_since_ms;

        // v1.3.1 resume: exactly the (E, G) verified earlier in this process,
        // re-proven S1..S6 on this very sample.
        // v1.3.2: a resume is a new arm, so it takes the INITIAL stats rule
        // (HP >= 1), exactly as a fresh verification. 1.3.1 used the
        // continuing rule (HP >= 0): God turned on at the death/retry screen
        // armed on the dead actor and the arm floor (MaxHP) was written into
        // it on the next tick. Only an already-armed pair keeps the continuing
        // rule. A refused resume keeps the memory and resumes on the first
        // sample with HP >= 1.
        const bool resumable = !t.verified && t.resume_actor != 0 && s.actor == t.resume_actor
            && s.guid == t.resume_guid;
        const bool stats_ok = t.verified ? eve_scale_continuing(s.hp, s.max_hp)
                                         : eve_scale_initial(s.hp, s.max_hp);
        if (!stats_ok)
        {
            t.verified = false;
            t.arm_path = ArmPath::None;
            v.reason = Reason::StatsNotEveScale;
            return v;
        }
        if (t.verified)
        {
            // Same actor, same GUID, chain/type/map/type-id re-proven this tick.
            v.verified = true;
            v.reason = Reason::Verified;
            v.arm_path = t.arm_path;
            v.direct = direct_proof(s);
            return v;
        }
        if (resumable)
        {
            t.verified = true;
            t.verified_since_ms = now_ms;
            t.arm_path = ArmPath::Resume;
            v.verified = true;
            v.resumed = true;
            v.reason = Reason::Verified;
            v.arm_path = ArmPath::Resume;
            v.direct = direct_proof(s);
            return v;
        }
        // The UE snapshot passed in belongs to the previous candidate when the
        // candidate just changed; the caller clears it and runs a fresh pass.
        const UeSnapshot none{};
        const UeSnapshot& current = v.candidate_changed ? none : ue;
        Reason ue_reason = Reason::UeNotChecked;
        const bool ue_good = ue_ok(current, s.guid, &ue_reason);
        // v1.3.1: the proof is judged once S7 holds (as in v1.3.0) but needs
        // no UE data itself: it is read on the chain walk.
        v.direct = ue_good ? direct_proof(s) : DirectProof::NotChecked;
        const std::uint64_t retry_ms = t.ue_attempts < kUeFastAttempts ? kUeRetryMs : kUeRetrySlowMs;
        v.want_ue_check = !ue_good && (!current.ran || now_ms - current.ran_ms >= retry_ms);
        if (v.want_ue_check && t.ue_attempts < 0xFFFFFFFFu) ++t.ue_attempts;
        if (!ue_good)
        {
            v.reason = ue_reason;
            return v;
        }
        const bool direct_ok = v.direct == DirectProof::Match;
        if (v.stable_ms < kStableMs || t.cand_samples < kStableSamples)
        {
            v.reason = Reason::Unstable;
            return v;
        }
        ArmPath path = ArmPath::None;
        if (direct_ok) path = ArmPath::Eventor;                          // S9'
        else if (corroborations != 0) path = ArmPath::HookCorroboration; // S9
        else
        {
            // v1.3.1: S1..S8 hold; the caller may treat the game's own call on
            // exactly this (E, G) as S9 (Verdict::ready).
            v.ready = true;
            v.reason = Reason::WaitingForHookCorroboration;
            return v;
        }
        t.verified = true;
        t.verified_since_ms = now_ms;
        t.arm_path = path;
        t.resume_actor = s.actor;
        t.resume_guid = s.guid;
        v.verified = true;
        v.reason = Reason::Verified;
        v.arm_path = path;
        return v;
    }

    bool is_vital_damage(int stat, float diff)
    {
        return (stat == 1 || stat == 7) && std::isfinite(diff) && diff < 0.0f;
    }

    // ---- v1.3.0 ------------------------------------------------------------

    const char* direct_proof_name(DirectProof proof)
    {
        switch (proof)
        {
        case DirectProof::NotChecked: return "not_checked";
        case DirectProof::NoPlayerState: return "no_playerstate";
        case DirectProof::ClassMismatch: return "class_mismatch";
        case DirectProof::FieldAbsent: return "field_absent";
        case DirectProof::OffsetMismatch: return "offset_mismatch";
        case DirectProof::Unread: return "unread";
        case DirectProof::Zero: return "zero";
        case DirectProof::Mismatch: return "mismatch";
        case DirectProof::Match: return "match";
        }
        return "unknown";
    }

    DirectProof direct_proof(const ChainSample& sample)
    {
        if (sample.step != Step::Ok) return DirectProof::NotChecked;
        if (!sample.eventor_read) return DirectProof::Unread;
        if (sample.eventor_guid == 0) return DirectProof::Zero;
        if (sample.guid == 0 || sample.eventor_guid != sample.guid) return DirectProof::Mismatch;
        return DirectProof::Match;
    }

    bool full_name_class_is(const wchar_t* full_name, std::size_t length, const wchar_t* class_name)
    {
        if (!full_name || !class_name) return false;
        const std::size_t want = std::wcslen(class_name);
        // "<Class> <Path>": the class token is exactly `class_name` and a
        // space follows it (a bare class name is not an object's full name).
        return want != 0 && length > want && std::wmemcmp(full_name, class_name, want) == 0 && full_name[want] == L' ';
    }

    const char* arm_path_name(ArmPath path)
    {
        switch (path)
        {
        case ArmPath::None: return "none";
        case ArmPath::Eventor: return "eventor_guid";
        case ArmPath::HookCorroboration: return "hook_corroboration";
        case ArmPath::Resume: return "resume";
        }
        return "unknown";
    }

    const char* first_hit_name(FirstHit state)
    {
        switch (state)
        {
        case FirstHit::Off: return "off";
        case FirstHit::Pending: return "pending";
        case FirstHit::Blocked: return "blocked";
        case FirstHit::NotBlocked: return "not_blocked";
        case FirstHit::Repaired: return "repaired";
        }
        return "unknown";
    }

    const char* hit_event_name(HitEvent event)
    {
        switch (event)
        {
        case HitEvent::None: return "none";
        case HitEvent::ApplyConsumed: return "apply_consumed";
        case HitEvent::SetterBlocked: return "setter_blocked";
        case HitEvent::ApplyLeak: return "apply_leak";
        case HitEvent::TickDrop: return "tick_drop";
        case HitEvent::LethalRestore: return "lethal_restore";
        case HitEvent::DeathCommand: return "death_command";
        case HitEvent::DiffBlocked: return "diff_blocked";
        case HitEvent::TickRepaired: return "tick_repaired";
        case HitEvent::DeathBlocked: return "death_blocked";
        }
        return "unknown";
    }

    HitClass hit_event_class(HitEvent event)
    {
        switch (event)
        {
        case HitEvent::None: return HitClass::None;
        case HitEvent::ApplyConsumed:
        case HitEvent::SetterBlocked:
        case HitEvent::DeathBlocked:
        case HitEvent::DiffBlocked: return HitClass::Blocked;
        case HitEvent::LethalRestore:
        case HitEvent::TickRepaired: return HitClass::Repaired;
        case HitEvent::ApplyLeak:
        case HitEvent::TickDrop:
        case HitEvent::DeathCommand: return HitClass::Leak;
        }
        return HitClass::Leak; // an unknown event is never silently a block
    }

    bool hit_event_is_leak(HitEvent event)
    {
        return hit_event_class(event) == HitClass::Leak;
    }

    void FirstHitWatch::arm(std::uint64_t now_ms) noexcept
    {
        // Off first, so a hook racing this re-arm is ignored rather than
        // counted against the new arm with stale counters.
        state_.store(static_cast<std::uint32_t>(FirstHit::Off), std::memory_order_release);
        first_.store(static_cast<std::uint32_t>(HitEvent::None), std::memory_order_relaxed);
        first_after_ms_.store(0, std::memory_order_relaxed);
        blocked_.store(0, std::memory_order_relaxed);
        leaks_.store(0, std::memory_order_relaxed);
        repairs_.store(0, std::memory_order_relaxed);
        lethal_saved_.store(0, std::memory_order_relaxed);
        last_leak_.store(static_cast<std::uint32_t>(HitEvent::None), std::memory_order_relaxed);
        armed_ms_.store(now_ms, std::memory_order_relaxed);
        arms_.fetch_add(1, std::memory_order_relaxed);
        state_.store(static_cast<std::uint32_t>(FirstHit::Pending), std::memory_order_release);
    }

    void FirstHitWatch::disarm() noexcept
    {
        state_.store(static_cast<std::uint32_t>(FirstHit::Off), std::memory_order_release);
    }

    void FirstHitWatch::note(HitEvent event, std::uint64_t now_ms) noexcept
    {
        if (event == HitEvent::None) return;
        if (state_.load(std::memory_order_acquire) == static_cast<std::uint32_t>(FirstHit::Off)) return;
        const auto cls = hit_event_class(event);
        FirstHit first_verdict = FirstHit::Blocked;
        if (cls == HitClass::Leak)
        {
            leaks_.fetch_add(1, std::memory_order_relaxed);
            last_leak_.store(static_cast<std::uint32_t>(event), std::memory_order_relaxed);
            first_verdict = FirstHit::NotBlocked;
        }
        else if (cls == HitClass::Repaired)
        {
            (event == HitEvent::LethalRestore ? lethal_saved_ : repairs_).fetch_add(1, std::memory_order_relaxed);
            first_verdict = FirstHit::Repaired;
        }
        else
        {
            blocked_.fetch_add(1, std::memory_order_relaxed);
        }
        auto expected = static_cast<std::uint32_t>(FirstHit::Pending);
        const auto verdict = static_cast<std::uint32_t>(first_verdict);
        if (state_.compare_exchange_strong(expected, verdict, std::memory_order_acq_rel))
        {
            first_.store(static_cast<std::uint32_t>(event), std::memory_order_relaxed);
            const auto armed = armed_ms_.load(std::memory_order_relaxed);
            first_after_ms_.store(now_ms >= armed ? now_ms - armed : 0, std::memory_order_relaxed);
        }
    }

    FirstHitWatch::Snapshot FirstHitWatch::snapshot() const noexcept
    {
        Snapshot s{};
        s.state = static_cast<FirstHit>(state_.load(std::memory_order_acquire));
        s.first = static_cast<HitEvent>(first_.load(std::memory_order_relaxed));
        s.first_after_ms = first_after_ms_.load(std::memory_order_relaxed);
        s.blocked = blocked_.load(std::memory_order_relaxed);
        s.leaks = leaks_.load(std::memory_order_relaxed);
        s.last_leak = static_cast<HitEvent>(last_leak_.load(std::memory_order_relaxed));
        s.arms = arms_.load(std::memory_order_relaxed);
        s.repairs = repairs_.load(std::memory_order_relaxed);
        s.lethal_saved = lethal_saved_.load(std::memory_order_relaxed);
        return s;
    }

    const char* protection_name(const FirstHitWatch::Snapshot& s)
    {
        if (s.state == FirstHit::Off) return "off";
        // v1.3.1: only real HP loss on Eve (a leak) is "damage got through".
        if (s.leaks != 0 || s.state == FirstHit::NotBlocked) return "damage_got_through";
        if (s.state == FirstHit::Blocked || s.state == FirstHit::Repaired) return "confirmed";
        return "pending_first_hit";
    }
} // namespace sbgod::identity
