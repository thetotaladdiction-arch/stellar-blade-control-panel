#define _CRT_RAND_S
// SBLiveAddNative - explicit, fail-closed direct Live Add for Stellar Blade.
//
// Contract with mods-overlay/SBLiveAddBridge/Scripts/main.lua
// (protocol "native-live-add-v4" since v0.5.0, bridge "trusted-live-add-only"):
//   request   -> Mods\SBCheatGUI\live_add_native_request.txt
//   result    -> Mods\SBCheatGUI\live_add_native_result.txt
//   heartbeat -> Mods\SBCheatGUI\live_add_native_heartbeat.txt
// and with the panel (same protocol string):
//   lease     -> Mods\SBCheatGUI\live_add_native_lease.txt
//   probe     -> Mods\SBCheatGUI\live_add_native_probe_request.txt
//             <- Mods\SBCheatGUI\live_add_native_probe_result.txt
//
// UE4SS calls on_update() on its worker. The worker performs bounded file I/O
// and TaskGraph submission only. Inventory bucket validation, the single
// game-owned authoritative item-add invocation, and the bounded
// verification read run in callbacks whose thread ID is checked against the
// exact shipping build's certified GameThread ID. No hook or UObject API is
// present, and no inventory, currency, or save field is written directly.
//
// v0.3.0 retargets the gate to the 2026-08-12 shipping build and adds a
// read-only first-use self-check. Every game function this module calls is
// gated on its complete byte image; the reflection layout of the RPC item
// struct and of ServerRequest_ItemBucketItemAdd, the singleton/manager map
// headers, the inventory bucket identity fields, and the game-owned item count
// reads are verified on the certified GameThread before any Add is accepted.
// A self-check failure is sticky for the session and keeps Live Add disabled.
//
// v0.3.1 (same build, same protocol): the RPC implementation does not add
// synchronously. In a standalone game it queues a request on the server-frame
// queue (0x1AF8DF0) and the server adds the item on a later server frame
// (0x1B0B4F0 -> 0x1BDA9D0). That server add silently adds nothing when the
// alias has no item-table row (0x1BDAA96 -> 0x1BDB5F5), when the item row's
// ValidConditionGroup fails, when the carry limit is already reached, and it
// clamps the count to the room left. v0.3.1 therefore looks up the row first
// and refuses without any game mutation when it is missing, reads the item's
// carry limit the way the game computes it (row MaxAmount or the actor stat
// named by MaxAmountOverrideActorStat), refuses when the bag is already full,
// sends at most the room left,
// refuses items the server would use on pickup instead of storing, polls the
// count every 100 ms for 5 s after the single add (longer, bounded, while the
// server frames stay frozen), and reports every measurement in its status.
//
// v0.4.0 (same build, same protocol, same add path) moves the shared plumbing
// onto sbcore 0.1.0 (the sibling checkout natives/sbcore, commit 7a81ea6):
//   * A1: the UE4SS base class is sbcore's corrected 11-slot shim (the build
//     fails unless its virtual order matches the loaded UE4SS.dll).
//   * A8/A11: the exact-build gate is sbcore::gate::validate: TDS/SOI/
//     ImageBase, the exe file size, the sbcore TaskGraph core manifest (with
//     the GGameThreadId initializer proof) and the legacy exact images, then
//     this module's own manifest below (every v0.3.1 region byte-for-byte,
//     plus .pdata function-begin checks where the image has them). The exe
//     SHA-256 is computed once per process and shared (sbcore::exe_identity).
//     GameThread work goes through sbcore::dispatch (the task bytes are those
//     of v0.3.1 / SBMovementNative 1.3.6).
//   * P1: every path is derived from this DLL's own location.
//   * A9 (stage 1): every fault inside a game call is written to the
//     persistent log Mods\SBLiveAddNative\sbcore_faults.log and latches the
//     process-wide sbcore write block; while it is set no game function is
//     entered (the feature stays off; crash-on-fault is not enabled).
//   * A12: heartbeat, status and result files are replaced atomically by
//     handle with POSIX semantics, without fsync, on change plus a liveness
//     beat (heartbeat 500 ms, status 1 s); files are read with FILE_SHARE_DELETE.
//   * A13: the periodic Refresh (and with it the first-use self-check) runs
//     only while the panel holds an Items lease
//     (Mods\SBCheatGUI\live_add_native_lease.txt: protocol, panel_pid,
//     issued_ms; 10 s, live panel process). Without a lease no GameThread
//     work is submitted at all; an accepted add and its verification still
//     run their own reads. Because the server frame is no longer sampled all
//     through gameplay, verification counts a frame index unchanged since the
//     add as paused without first having seen it advance (a first lease taken
//     while the game is paused would otherwise end the add as outcome
//     unknown after 5 s instead of waiting for the unpause, as v0.3.1 did).
//
// v0.5.0 (same build, same add path, same call arguments, no new game
// function and no new RVA; protocol native-live-add-v4, bridge v4) implements
// items-money-research/PLAN.md C1-C9:
//   * C1: the allowlist is generated from the v0.5 catalog's decisions by
//     tools/gen_item_allowlist.py (633 addable rows, 46 entitlement-gated
//     probe-only rows, watch-only replacement targets); excluded rows are
//     refused by absence. C1b: categories SkillPoint, Quest, SubQuest,
//     BulletPackage and SPLevel are refused in code whatever the list says.
//   * C2: before anything is sent the live item-table row must still carry
//     the catalog's category, MaxAmount and carry-limit stat, no
//     InventoryAlias redirect (use_canonical_alias) and no
//     ValidConditionGroup (entitlement_gated); otherwise data_mismatch.
//   * C3/C4: per-group quantities: stackables 1..99, one-per-player rows
//     exactly 1 and only while the current count is 0 (already_owned), Gold
//     (BetaCrystal) 1..1,000,000 per add and never above its 100,000,000 cap
//     minus the current Gold, other currencies 1..9,999. The bag room still
//     bounds what is sent.
//   * C5: stat-capped rows (ammo, Recovery_HP_Potion) need a readable carry
//     stat above 0 (locked_by_stat / limit_unknown).
//   * Unique instances (gear, exospines, suits) are added only after this
//     session read a count of 1 or more for an owned item of the same
//     category, which proves the count read sees instances (W0 gate 2);
//     otherwise instance_count_unproven.
//   * C6: the counts of the sentinel set and of the item's replacement
//     target are read with the add and at every verification read; a count
//     that grows reports side_effect_detected and locks the session.
//   * C7: a read-only probe command (live_add_native_probe_request.txt ->
//     live_add_native_probe_result.txt) labels every allowlisted item
//     (available / owned / at_limit / needs_dlc / locked_by_stat / ...), at
//     most 32 items per GameThread callback, using only the row lookup,
//     count read and stat read the add already uses.
//   * C8: the self-check samples one sentinel item per family (item
//     category) and requires its live row to match the catalog.
                                                                          
                                                                      
//     trailing "_<N>" off a name ("BS_11" is ("BS", 12)); 108 item-table
//     rows are keyed that way, and the first v0.5.0 build refused every
//     FName with a number, so 98 addable rows (suits BS_10..BS_102, their
//     recipes, 19 records) could never be added or probed. The number must
//     be exactly the one the alias text implies (fname_number_of, the exe's
//     ParseNumber 0x294D9C0), and that whole name is what the count read,
//     the row lookup, the watch, the probe and the add use.
//
// v0.5.1 (same add path, same arguments, no new game function or RVA; one
// more item-row byte read): rows whose AutoCharacterLevelUpType (row +0x188)
// is set are refused as item_auto_level_up (probe label auto_level_up). The
// server add's post-add hook 0x1BDCA30 levels the player up as soon as the
// count meets the next CharacterLevelTable row and removes the required items
// in the same frame (CanLevelUp 0x1BB9660, ChangeLevel 0x1BB9A40, RemoveItem
                                                                               
                                                                           
                                                                          
//
// v0.5.1 per-unit guard (same add path, same arguments, no new game function
// or RVA; one more item-row read, StackAmount at row +0x80): a row whose
// StackAmount is 1 shows one bag entry per unit, but the game keeps it as one
                                                                     
                                                                              
                                                                       
// otherwise adds the amount to the alias's first pocket (0x1BDAD37,
// 0x1BDADCB..0x1BDAE77), and the count read 0x1C3E6C0 sums every pocket of
// the alias (both pinned by tools/verify_live_add_offline.py). An add to an
// owned per-unit item (count above 0) is therefore sent only for the
// categories whose per-unit rows were traced that way (Core, Revival, Fish);
// any other per-unit row with a count above 0 is refused as
// item_per_unit_owned_unproven (probe label per_unit_unproven), and an
// unreadable StackAmount counts as per-unit. Adds from a count of 0 and every
// row with another StackAmount are decided exactly as in v0.5.0.

#include "live_add.hpp"

#include <algorithm>
#include <array>
#include <atomic>
#include <charconv>
#include <cstddef>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <limits>
#include <string>
#include <string_view>
#include <vector>

#include <windows.h>
#include <bcrypt.h>

#include "sbcore/sbcore.hpp"

namespace sbliveadd
{
    namespace
    {
        constexpr char kVersion[] = "0.5.1";
        constexpr char kProtocol[] = "native-live-add-v4";
        constexpr char kModuleName[] = "SBLiveAddNative";
        constexpr char kTrustedBridge[] = "trusted-live-add-only";
        constexpr char kResultStatusOk[] = "ok";
        constexpr char kCertifiedBuild[] =
            "SB-Win64-Shipping.exe 573AAFF1C9455F85EA6036EF6F6CCB0774DE4164722A296276FBBFC7FA87545C "
            "ts=6A6A3B74 soi=15981000";

        constexpr std::uint64_t kCommandPollMs = 50;
        constexpr std::uint64_t kBucketRefreshMs = 500;
        // A12: files are written on change (at most every 100 ms) plus a
        // liveness beat. The bridge treats the native heartbeat as stale when
        // its beat has not advanced for 8 of its 250 ms ticks (2 s), so the
        // heartbeat beat is 500 ms; the panel treats the status as stale after
        // 3 s (LIVE_ADD_NATIVE_STATUS_MAX_AGE_SEC), so the status beat is 1 s.
        constexpr std::uint64_t kHeartbeatBeatMs = 500;
        constexpr std::uint64_t kHeartbeatMinIntervalMs = 100;
        constexpr std::uint64_t kStatusBeatMs = 1'000;
        constexpr std::uint64_t kStatusMinIntervalMs = 100;
        // The worker looks at the heartbeat and the status at most this often
        // (UE4SS calls on_update every frame; v0.3.1 polled commands every 50 ms).
        constexpr std::uint64_t kPublishCheckMs = 50;
        // A13: the panel's Items lease (as SBMovementNative's state lease).
        constexpr std::uint64_t kPanelLeaseMs = 10'000;
        constexpr std::uint64_t kPanelLeaseFutureToleranceMs = 5'000;
        // Verification after the single add: first count read 100 ms after
        // the add, then every 100 ms for 5 s. While the server frames stay
        // frozen (the queued request cannot have been processed yet) it keeps
        // reading every 250 ms, bounded at 45 s after the add, and again for
        // 5 s once the frames resume. No step ever repeats the add.
        constexpr std::uint64_t kVerifyFirstDelayMs = 100;
        constexpr std::uint64_t kVerifyPollMs = 100;
        constexpr std::uint64_t kVerifyPausedPollMs = 250;
        constexpr std::uint64_t kVerifyWindowMs = 5'000;
        constexpr std::uint64_t kVerifyPausedWindowMs = 45'000;
        constexpr std::uint64_t kSmallFileMax = 4096;
        constexpr std::uint64_t kRequestMaxAgeSeconds = 3;
        constexpr std::uint64_t kRequestFutureSkewSeconds = 1;
        constexpr std::uint64_t kRequestMaxBeatDrift = 50;
        // v0.5.0 per-group quantities (PLAN C3). The protocol accepts at most
        // kMaxRequestQuantity; each allowlisted row carries its own per-add
        // maximum, which is always one of these.
        constexpr std::uint32_t kMaxStackQuantity = 99;
        constexpr std::uint32_t kMaxMoneyQuantity = 1'000'000;
        constexpr std::uint32_t kMaxCurrencyQuantity = 9'999;
        constexpr std::uint32_t kMaxRequestQuantity = kMaxMoneyQuantity;
        constexpr std::int32_t kMoneyGameMax = 100'000'000;
        constexpr std::int32_t kMaxPlausibleItemCount = 100'000'000;
        static_assert(kMoneyGameMax <= kMaxPlausibleItemCount);
        static_assert(static_cast<std::uint64_t>(kMoneyGameMax) + kMaxMoneyQuantity
                      < std::numeric_limits<std::uint32_t>::max());

        // ESBItemCategory (the game's reflected enum order). C1b: never
        // addable, whatever the generated list says.
        constexpr std::uint32_t kCategoryBetaCrystal = 1;
        constexpr std::uint32_t kCategoryGear = 2;
        constexpr std::uint32_t kCategoryExoSpine = 3;
        constexpr std::uint32_t kCategoryNanoSuit = 4;
        constexpr std::uint32_t kCategorySkillPoint = 6;
        constexpr std::uint32_t kCategoryQuest = 7;
        constexpr std::uint32_t kCategorySubQuest = 8;
        constexpr std::uint32_t kCategoryBulletPackage = 14;
        constexpr std::uint32_t kCategorySPLevel = 29;
        constexpr std::uint32_t kCategoryCount = 31;

        constexpr bool category_hard_denied(std::uint32_t category)
        {
            return category == kCategorySkillPoint || category == kCategoryQuest || category == kCategorySubQuest
                || category == kCategoryBulletPackage || category == kCategorySPLevel;
        }

        constexpr bool category_is_unique_instance(std::uint32_t category)
        {
            return category == kCategoryGear || category == kCategoryExoSpine || category == kCategoryNanoSuit;
        }

        // v0.5.1: the categories whose per-unit rows (StackAmount 1) were
        // traced through the server add's merge path (verify_live_add_offline
        // check server_add_per_unit_rows_merge): Core, Revival (WB Pump) and
        // Fish. An owned per-unit row of any other category is refused.
        constexpr std::uint32_t kCategoryCore = 11;
        constexpr std::uint32_t kCategoryRevival = 15;
        constexpr std::uint32_t kCategoryFish = 18;

        constexpr bool per_unit_add_proven(std::uint32_t category)
        {
            return category == kCategoryCore || category == kCategoryRevival || category == kCategoryFish;
        }
        static_assert(!per_unit_add_proven(kCategoryGear) && !per_unit_add_proven(kCategoryExoSpine)
                          && !per_unit_add_proven(kCategoryNanoSuit),
                      "unique-instance categories make one instance per unit");
        static_assert(!category_hard_denied(kCategoryCore) && !category_hard_denied(kCategoryRevival)
                          && !category_hard_denied(kCategoryFish),
                      "a proven per-unit category is never a hard-denied one");

        // How the native treats one allowlisted row (PLAN C1/C3/C4/C5).
        enum class ItemGroup : std::uint8_t
        {
            Stack = 1,       // 1..99, bounded by the bag room
            StatCapped,      // 1..99, the carry limit is an actor stat that must read above 0
            OnePerPlayer,    // exactly 1, only while the current count is 0
            UniqueInstance,  // exactly 1, count 0, and instance counting proven this session
            Money,           // BetaCrystal: 1..1,000,000, never above 100,000,000 in total
            Currency,        // 1..9,999, bounded by the bag room
            Gated,           // entitlement-gated: probe only, never added
            WatchOnly,       // a replacement target: its count is watched, never added or probed
        };

        struct AllowedItem
        {
            std::string_view alias;
            std::uint8_t category;       // ESBItemCategory the live row must have
            ItemGroup group;
            std::uint32_t per_add_max;   // 0: never addable
            std::int32_t game_max;       // the live row's MaxAmount (rows without a carry stat)
            std::uint8_t stat;           // the live row's MaxAmountOverrideActorStat (0: none)
            std::uint8_t flags;          // kItemFlag* (catalog information)
            std::int16_t replacement;    // kAllowedItems index of the replacement target, -1: none
        };
        constexpr std::uint8_t kItemFlagDefaultOn = 0x01;
        constexpr std::uint8_t kItemFlagOptIn = 0x02;
        constexpr std::uint8_t kItemFlagNeedsUserYes = 0x04;
        constexpr std::uint8_t kItemFlagQuestInput = 0x08;
        constexpr std::uint8_t kItemFlagTrophy = 0x10;
        constexpr std::uint8_t kItemFlagSentinel = 0x20;

        // ---- GENERATED by tools/gen_item_allowlist.py; do not edit -----------
        // Source: tools/catalog/catalog-v05.json (sb-liveadd-catalog/v0.5-data), SHA-256
        // 605000FB096A87A8EF0CC7B805CB001492F6052FA1C66C4C880AE5E0394205E6. 633 addable rows, 46 entitlement-gated
        // (probe only), the rest watch-only replacement targets. Sorted by
        // byte order for find_allowed_item(). Fields: alias, ESBItemCategory,
        // group, per-add max, the item-table MaxAmount and
        // MaxAmountOverrideActorStat the live row must still have, flags,
        // replacement target index (-1: none).
        constexpr char kAllowlistSchema[] = "sbliveadd-allowlist-v1";
        constexpr char kAllowlistCatalogSha256[] = "605000FB096A87A8EF0CC7B805CB001492F6052FA1C66C4C880AE5E0394205E6";
        constexpr std::size_t kAllowlistAddableCount = 633;
        constexpr std::size_t kAllowlistGatedCount = 46;
        constexpr std::array<AllowedItem, 680> kAllowedItems{{
            {"2DQuantumWafer", 10, ItemGroup::Stack, 99, 999999, 0, 0x29, -1},
            {"AdamCostume_001", 27, ItemGroup::OnePerPlayer, 1, 1, 0, 0x21, -1},
            {"AdamCostume_002", 27, ItemGroup::Gated, 0, 1, 0, 0x00, -1},
            {"AdamCostume_003", 27, ItemGroup::OnePerPlayer, 1, 1, 0, 0x01, 4},
            {"AdamCostume_003_Var2", 27, ItemGroup::OnePerPlayer, 1, 1, 0, 0x01, 314},
            {"AdamCostume_004", 27, ItemGroup::OnePerPlayer, 1, 1, 0, 0x01, 6},
            {"AdamCostume_004_Var2", 27, ItemGroup::OnePerPlayer, 1, 1, 0, 0x01, 314},
            {"AdamCostume_Christmas_01", 27, ItemGroup::OnePerPlayer, 1, 1, 0, 0x01, 315},
            {"AdamCostume_Nier_001", 27, ItemGroup::Gated, 0, 1, 0, 0x10, -1},
            {"BS_01", 4, ItemGroup::UniqueInstance, 1, 1, 0, 0x31, -1},
            {"BS_01_Var2", 4, ItemGroup::Gated, 0, 1, 0, 0x10, -1},
            {"BS_01_Var3", 4, ItemGroup::UniqueInstance, 1, 1, 0, 0x11, -1},
            {"BS_02", 4, ItemGroup::UniqueInstance, 1, 1, 0, 0x11, -1},
            {"BS_02_Var2", 4, ItemGroup::UniqueInstance, 1, 1, 0, 0x11, -1},
            {"BS_03", 4, ItemGroup::UniqueInstance, 1, 1, 0, 0x11, -1},
            {"BS_03_Var2", 4, ItemGroup::UniqueInstance, 1, 1, 0, 0x11, -1},
            {"BS_04", 4, ItemGroup::UniqueInstance, 1, 1, 0, 0x11, -1},
            {"BS_04_Var2", 4, ItemGroup::UniqueInstance, 1, 1, 0, 0x11, -1},
            {"BS_05_E", 4, ItemGroup::UniqueInstance, 1, 1, 0, 0x11, -1},
            {"BS_05_Var2_E", 4, ItemGroup::UniqueInstance, 1, 1, 0, 0x11, -1},
            {"BS_07", 4, ItemGroup::UniqueInstance, 1, 1, 0, 0x11, -1},
            {"BS_07_Var2", 4, ItemGroup::UniqueInstance, 1, 1, 0, 0x11, -1},
            {"BS_08", 4, ItemGroup::UniqueInstance, 1, 1, 0, 0x11, -1},
            {"BS_08_Var2", 4, ItemGroup::UniqueInstance, 1, 1, 0, 0x11, -1},
            {"BS_09_2", 4, ItemGroup::UniqueInstance, 1, 1, 0, 0x11, -1},
            {"BS_09_2_Var2", 4, ItemGroup::UniqueInstance, 1, 1, 0, 0x11, -1},
            {"BS_10", 4, ItemGroup::UniqueInstance, 1, 1, 0, 0x11, -1},
            {"BS_102", 4, ItemGroup::UniqueInstance, 1, 1, 0, 0x11, -1},
            {"BS_11", 4, ItemGroup::UniqueInstance, 1, 1, 0, 0x11, -1},
            {"BS_13", 4, ItemGroup::UniqueInstance, 1, 1, 0, 0x11, -1},
            {"BS_13_Var2", 4, ItemGroup::UniqueInstance, 1, 1, 0, 0x11, -1},
            {"BS_14_E", 4, ItemGroup::UniqueInstance, 1, 1, 0, 0x11, -1},
            {"BS_14_Var2_E", 4, ItemGroup::UniqueInstance, 1, 1, 0, 0x11, -1},
            {"BS_15", 4, ItemGroup::UniqueInstance, 1, 1, 0, 0x11, -1},
            {"BS_15_Var2_E", 4, ItemGroup::UniqueInstance, 1, 1, 0, 0x11, -1},
            {"BS_16", 4, ItemGroup::UniqueInstance, 1, 1, 0, 0x11, -1},
            {"BS_16_Var2", 4, ItemGroup::UniqueInstance, 1, 1, 0, 0x11, -1},
            {"BS_17", 4, ItemGroup::UniqueInstance, 1, 1, 0, 0x11, -1},
            {"BS_18", 4, ItemGroup::UniqueInstance, 1, 1, 0, 0x11, 314},
            {"BS_19", 4, ItemGroup::UniqueInstance, 1, 1, 0, 0x11, -1},
            {"BS_19_Var2", 4, ItemGroup::UniqueInstance, 1, 1, 0, 0x11, -1},
            {"BS_20", 4, ItemGroup::UniqueInstance, 1, 1, 0, 0x11, 42},
            {"BS_20_Var2", 4, ItemGroup::UniqueInstance, 1, 1, 0, 0x11, 52},
            {"BS_21", 4, ItemGroup::UniqueInstance, 1, 1, 0, 0x11, -1},
            {"BS_21_Var2", 4, ItemGroup::UniqueInstance, 1, 1, 0, 0x11, -1},
            {"BS_22", 4, ItemGroup::UniqueInstance, 1, 1, 0, 0x11, 314},
            {"BS_22_Var2_E", 4, ItemGroup::UniqueInstance, 1, 1, 0, 0x11, 314},
            {"BS_23", 4, ItemGroup::UniqueInstance, 1, 1, 0, 0x11, -1},
            {"BS_23_Var2", 4, ItemGroup::UniqueInstance, 1, 1, 0, 0x11, -1},
            {"BS_24_E", 4, ItemGroup::UniqueInstance, 1, 1, 0, 0x11, -1},
            {"BS_24_Var2", 4, ItemGroup::UniqueInstance, 1, 1, 0, 0x11, -1},
            {"BS_26", 4, ItemGroup::UniqueInstance, 1, 1, 0, 0x11, -1},
            {"BS_26_Var2", 4, ItemGroup::UniqueInstance, 1, 1, 0, 0x11, 314},
            {"BS_30", 4, ItemGroup::UniqueInstance, 1, 1, 0, 0x11, -1},
            {"BS_30_Var2", 4, ItemGroup::UniqueInstance, 1, 1, 0, 0x11, -1},
            {"BS_31", 4, ItemGroup::UniqueInstance, 1, 1, 0, 0x11, -1},
            {"BS_31_Var2", 4, ItemGroup::UniqueInstance, 1, 1, 0, 0x11, -1},
            {"BS_32", 4, ItemGroup::UniqueInstance, 1, 1, 0, 0x11, -1},
            {"BS_33", 4, ItemGroup::UniqueInstance, 1, 1, 0, 0x11, -1},
            {"BS_33_Var2", 4, ItemGroup::UniqueInstance, 1, 1, 0, 0x11, 314},
            {"BS_34", 4, ItemGroup::UniqueInstance, 1, 1, 0, 0x11, -1},
            {"BS_34_Var2", 4, ItemGroup::UniqueInstance, 1, 1, 0, 0x11, -1},
            {"BS_37", 4, ItemGroup::UniqueInstance, 1, 1, 0, 0x11, -1},
            {"BS_37_Var2", 4, ItemGroup::UniqueInstance, 1, 1, 0, 0x11, 59},
            {"BS_37_Var3", 4, ItemGroup::UniqueInstance, 1, 1, 0, 0x11, -1},
            {"BS_38", 4, ItemGroup::UniqueInstance, 1, 1, 0, 0x11, -1},
            {"BS_38_Var2", 4, ItemGroup::UniqueInstance, 1, 1, 0, 0x11, -1},
            {"BS_40", 4, ItemGroup::UniqueInstance, 1, 1, 0, 0x11, -1},
            {"BS_40_Var2", 4, ItemGroup::UniqueInstance, 1, 1, 0, 0x11, -1},
            {"BS_40_Var3", 4, ItemGroup::UniqueInstance, 1, 1, 0, 0x11, -1},
            {"BS_41", 4, ItemGroup::UniqueInstance, 1, 1, 0, 0x11, -1},
            {"BS_41_Var2", 4, ItemGroup::UniqueInstance, 1, 1, 0, 0x11, -1},
            {"BS_42", 4, ItemGroup::UniqueInstance, 1, 1, 0, 0x11, -1},
            {"BS_42_Var2", 4, ItemGroup::UniqueInstance, 1, 1, 0, 0x11, -1},
            {"BS_43", 4, ItemGroup::UniqueInstance, 1, 1, 0, 0x11, -1},
            {"BS_43_Var2", 4, ItemGroup::UniqueInstance, 1, 1, 0, 0x11, -1},
            {"BS_44", 4, ItemGroup::UniqueInstance, 1, 1, 0, 0x11, -1},
            {"BS_44_Var2", 4, ItemGroup::UniqueInstance, 1, 1, 0, 0x11, -1},
            {"BS_44_Var3_E", 4, ItemGroup::UniqueInstance, 1, 1, 0, 0x11, -1},
            {"BS_45", 4, ItemGroup::UniqueInstance, 1, 1, 0, 0x11, -1},
            {"BS_45_Var2", 4, ItemGroup::UniqueInstance, 1, 1, 0, 0x11, -1},
            {"BS_47", 4, ItemGroup::UniqueInstance, 1, 1, 0, 0x11, -1},
            {"BS_47_Var2", 4, ItemGroup::UniqueInstance, 1, 1, 0, 0x11, -1},
            {"BS_48", 4, ItemGroup::UniqueInstance, 1, 1, 0, 0x11, -1},
            {"BS_48_Var2", 4, ItemGroup::UniqueInstance, 1, 1, 0, 0x11, -1},
            {"BS_50", 4, ItemGroup::UniqueInstance, 1, 1, 0, 0x11, -1},
            {"BS_50_Var2", 4, ItemGroup::UniqueInstance, 1, 1, 0, 0x11, -1},
            {"BS_52", 4, ItemGroup::UniqueInstance, 1, 1, 0, 0x11, -1},
            {"BS_53", 4, ItemGroup::UniqueInstance, 1, 1, 0, 0x11, -1},
            {"BS_53_Var2", 4, ItemGroup::UniqueInstance, 1, 1, 0, 0x11, -1},
            {"BS_54", 4, ItemGroup::UniqueInstance, 1, 1, 0, 0x11, -1},
            {"BS_55", 4, ItemGroup::UniqueInstance, 1, 1, 0, 0x11, -1},
            {"BS_55_Var2", 4, ItemGroup::UniqueInstance, 1, 1, 0, 0x11, -1},
            {"BS_56", 4, ItemGroup::UniqueInstance, 1, 1, 0, 0x11, -1},
            {"BS_57", 4, ItemGroup::UniqueInstance, 1, 1, 0, 0x11, -1},
            {"BS_58", 4, ItemGroup::UniqueInstance, 1, 1, 0, 0x11, -1},
            {"BS_60", 4, ItemGroup::UniqueInstance, 1, 1, 0, 0x11, -1},
            {"BS_99", 4, ItemGroup::Gated, 0, 1, 0, 0x10, -1},
            {"BS_Bear", 4, ItemGroup::UniqueInstance, 1, 1, 0, 0x11, -1},
            {"BS_Bear_Var2", 4, ItemGroup::UniqueInstance, 1, 1, 0, 0x11, -1},
            {"BS_Black_Leather_bikini", 4, ItemGroup::UniqueInstance, 1, 1, 0, 0x11, -1},
            {"BS_Black_Leather_bikini_Var2", 4, ItemGroup::UniqueInstance, 1, 1, 0, 0x11, -1},
            {"BS_Blue_Suit_E", 4, ItemGroup::UniqueInstance, 1, 1, 0, 0x11, -1},
            {"BS_Christmas_01", 4, ItemGroup::UniqueInstance, 1, 1, 0, 0x11, 315},
            {"BS_Default", 4, ItemGroup::UniqueInstance, 1, 1, 0, 0x11, -1},
            {"BS_Default_Var2", 4, ItemGroup::Gated, 0, 1, 0, 0x10, -1},
            {"BS_Default_Var3", 4, ItemGroup::Gated, 0, 1, 0, 0x10, -1},
            {"BS_EVE_04", 4, ItemGroup::UniqueInstance, 1, 1, 0, 0x11, -1},
            {"BS_EVE_04_Var2", 4, ItemGroup::UniqueInstance, 1, 1, 0, 0x11, -1},
            {"BS_Green_Suit", 4, ItemGroup::UniqueInstance, 1, 1, 0, 0x11, -1},
            {"BS_Leather_Jean", 4, ItemGroup::UniqueInstance, 1, 1, 0, 0x11, -1},
            {"BS_Leather_Jean_Var2", 4, ItemGroup::UniqueInstance, 1, 1, 0, 0x11, -1},
            {"BS_Nier_01", 4, ItemGroup::Gated, 0, 1, 0, 0x10, -1},
            {"BS_Nier_02", 4, ItemGroup::Gated, 0, 1, 0, 0x10, -1},
            {"BS_Nier_03", 4, ItemGroup::Gated, 0, 1, 0, 0x10, -1},
            {"BS_Nier_04", 4, ItemGroup::Gated, 0, 1, 0, 0x10, -1},
            {"BS_Nikke_01", 4, ItemGroup::Gated, 0, 1, 0, 0x10, -1},
            {"BS_Nikke_02", 4, ItemGroup::Gated, 0, 1, 0, 0x10, -1},
            {"BS_Nikke_03", 4, ItemGroup::Gated, 0, 1, 0, 0x10, -1},
            {"BS_Nikke_04", 4, ItemGroup::Gated, 0, 1, 0, 0x10, -1},
            {"BS_Nikke_05", 4, ItemGroup::Gated, 0, 1, 0, 0x10, -1},
            {"BS_Nikke_06", 4, ItemGroup::Gated, 0, 1, 0, 0x10, -1},
            {"BS_OneMillion_01", 4, ItemGroup::UniqueInstance, 1, 1, 0, 0x11, -1},
            {"BS_Raven", 4, ItemGroup::UniqueInstance, 1, 1, 0, 0x11, -1},
            {"BS_RoyalGuard_01", 4, ItemGroup::UniqueInstance, 1, 1, 0, 0x11, -1},
            {"BS_Sailor_Jean", 4, ItemGroup::UniqueInstance, 1, 1, 0, 0x11, -1},
            {"BS_Sailor_Jean_Var2", 4, ItemGroup::UniqueInstance, 1, 1, 0, 0x11, -1},
            {"BS_SilverKunoichi", 4, ItemGroup::UniqueInstance, 1, 1, 0, 0x11, -1},
            {"BS_SilverKunoichi_Var2", 4, ItemGroup::UniqueInstance, 1, 1, 0, 0x11, -1},
            {"BS_White_Jean", 4, ItemGroup::UniqueInstance, 1, 1, 0, 0x11, -1},
            {"BS_White_Jean_Var2", 4, ItemGroup::UniqueInstance, 1, 1, 0, 0x11, -1},
            {"BS_Yellow_Suit", 4, ItemGroup::UniqueInstance, 1, 1, 0, 0x11, -1},
            {"BS_Yellow_Suit_Jacket", 4, ItemGroup::UniqueInstance, 1, 1, 0, 0x11, -1},
            {"BS_Yellow_Suit_Jacket_Var2", 4, ItemGroup::UniqueInstance, 1, 1, 0, 0x11, -1},
            {"BS_Yellow_Suit_Var2", 4, ItemGroup::UniqueInstance, 1, 1, 0, 0x11, -1},
            {"BetaCore", 11, ItemGroup::Stack, 99, 999999, 0, 0x32, -1},
            {"BetaCrystal", 1, ItemGroup::Money, 1000000, 100000000, 0, 0x36, -1},
            {"BodyCore", 11, ItemGroup::Stack, 99, 999999, 0, 0x12, -1},
            {"Bullet_Explosive", 13, ItemGroup::StatCapped, 99, 999999, 93, 0x21, -1},
            {"Bullet_Missile", 13, ItemGroup::StatCapped, 99, 999999, 90, 0x01, -1},
            {"Bullet_Nikke", 13, ItemGroup::StatCapped, 99, 999999, 92, 0x01, -1},
            {"Bullet_Normal", 13, ItemGroup::StatCapped, 99, 999999, 88, 0x01, -1},
            {"Bullet_Railgun", 13, ItemGroup::StatCapped, 99, 999999, 89, 0x01, -1},
            {"Bullet_Scatter", 13, ItemGroup::StatCapped, 99, 999999, 91, 0x01, -1},
            {"Can_001", 25, ItemGroup::OnePerPlayer, 1, 1, 0, 0x32, -1},
            {"Can_002", 25, ItemGroup::OnePerPlayer, 1, 1, 0, 0x1A, -1},
            {"Can_003", 25, ItemGroup::OnePerPlayer, 1, 1, 0, 0x12, -1},
            {"Can_004", 25, ItemGroup::OnePerPlayer, 1, 1, 0, 0x12, -1},
            {"Can_005", 25, ItemGroup::OnePerPlayer, 1, 1, 0, 0x12, -1},
            {"Can_006", 25, ItemGroup::OnePerPlayer, 1, 1, 0, 0x12, -1},
            {"Can_007", 25, ItemGroup::OnePerPlayer, 1, 1, 0, 0x12, -1},
            {"Can_008", 25, ItemGroup::OnePerPlayer, 1, 1, 0, 0x12, -1},
            {"Can_009", 25, ItemGroup::OnePerPlayer, 1, 1, 0, 0x12, -1},
            {"Can_010", 25, ItemGroup::OnePerPlayer, 1, 1, 0, 0x12, -1},
            {"Can_011", 25, ItemGroup::OnePerPlayer, 1, 1, 0, 0x12, -1},
            {"Can_012", 25, ItemGroup::OnePerPlayer, 1, 1, 0, 0x12, -1},
            {"Can_013", 25, ItemGroup::OnePerPlayer, 1, 1, 0, 0x12, -1},
            {"Can_014", 25, ItemGroup::OnePerPlayer, 1, 1, 0, 0x12, -1},
            {"Can_015", 25, ItemGroup::OnePerPlayer, 1, 1, 0, 0x12, -1},
            {"Can_016", 25, ItemGroup::OnePerPlayer, 1, 1, 0, 0x12, -1},
            {"Can_017", 25, ItemGroup::OnePerPlayer, 1, 1, 0, 0x12, -1},
            {"Can_018", 25, ItemGroup::OnePerPlayer, 1, 1, 0, 0x12, -1},
            {"Can_019", 25, ItemGroup::OnePerPlayer, 1, 1, 0, 0x12, -1},
            {"Can_020", 25, ItemGroup::OnePerPlayer, 1, 1, 0, 0x12, -1},
            {"Can_021", 25, ItemGroup::OnePerPlayer, 1, 1, 0, 0x12, -1},
            {"Can_022", 25, ItemGroup::OnePerPlayer, 1, 1, 0, 0x12, -1},
            {"Can_023", 25, ItemGroup::OnePerPlayer, 1, 1, 0, 0x12, -1},
            {"Can_024", 25, ItemGroup::OnePerPlayer, 1, 1, 0, 0x12, -1},
            {"Can_025", 25, ItemGroup::OnePerPlayer, 1, 1, 0, 0x12, -1},
            {"Can_026", 25, ItemGroup::OnePerPlayer, 1, 1, 0, 0x12, -1},
            {"Can_027", 25, ItemGroup::OnePerPlayer, 1, 1, 0, 0x12, -1},
            {"Can_028", 25, ItemGroup::OnePerPlayer, 1, 1, 0, 0x12, -1},
            {"Can_029", 25, ItemGroup::OnePerPlayer, 1, 1, 0, 0x12, -1},
            {"Can_030", 25, ItemGroup::OnePerPlayer, 1, 1, 0, 0x12, -1},
            {"Can_031", 25, ItemGroup::OnePerPlayer, 1, 1, 0, 0x12, -1},
            {"Can_032", 25, ItemGroup::OnePerPlayer, 1, 1, 0, 0x12, -1},
            {"Can_033", 25, ItemGroup::OnePerPlayer, 1, 1, 0, 0x12, -1},
            {"Can_034", 25, ItemGroup::OnePerPlayer, 1, 1, 0, 0x12, -1},
            {"Can_035", 25, ItemGroup::OnePerPlayer, 1, 1, 0, 0x12, -1},
            {"Can_036", 25, ItemGroup::OnePerPlayer, 1, 1, 0, 0x12, -1},
            {"Can_037", 25, ItemGroup::OnePerPlayer, 1, 1, 0, 0x12, -1},
            {"Can_038", 25, ItemGroup::OnePerPlayer, 1, 1, 0, 0x12, -1},
            {"Can_039", 25, ItemGroup::OnePerPlayer, 1, 1, 0, 0x12, -1},
            {"Can_040", 25, ItemGroup::OnePerPlayer, 1, 1, 0, 0x12, -1},
            {"Can_041", 25, ItemGroup::OnePerPlayer, 1, 1, 0, 0x12, -1},
            {"Can_042", 25, ItemGroup::OnePerPlayer, 1, 1, 0, 0x12, -1},
            {"Can_043", 25, ItemGroup::OnePerPlayer, 1, 1, 0, 0x12, -1},
            {"Can_044", 25, ItemGroup::OnePerPlayer, 1, 1, 0, 0x12, -1},
            {"Can_045", 25, ItemGroup::OnePerPlayer, 1, 1, 0, 0x12, -1},
            {"Can_046", 25, ItemGroup::OnePerPlayer, 1, 1, 0, 0x12, -1},
            {"Can_047", 25, ItemGroup::OnePerPlayer, 1, 1, 0, 0x12, -1},
            {"Can_048", 25, ItemGroup::OnePerPlayer, 1, 1, 0, 0x12, -1},
            {"Can_049", 25, ItemGroup::OnePerPlayer, 1, 1, 0, 0x12, -1},
            {"ConcussionGrenade", 16, ItemGroup::Stack, 99, 999999, 0, 0x31, -1},
            {"DesignPattern_BS_01", 24, ItemGroup::OnePerPlayer, 1, 1, 0, 0x31, -1},
            {"DesignPattern_BS_01_Var2", 24, ItemGroup::OnePerPlayer, 1, 1, 0, 0x11, -1},
            {"DesignPattern_BS_01_Var3", 24, ItemGroup::OnePerPlayer, 1, 1, 0, 0x11, -1},
            {"DesignPattern_BS_02", 24, ItemGroup::OnePerPlayer, 1, 1, 0, 0x11, -1},
            {"DesignPattern_BS_02_Var2", 24, ItemGroup::OnePerPlayer, 1, 1, 0, 0x11, -1},
            {"DesignPattern_BS_03", 24, ItemGroup::OnePerPlayer, 1, 1, 0, 0x11, -1},
            {"DesignPattern_BS_03_Var2", 24, ItemGroup::OnePerPlayer, 1, 1, 0, 0x11, -1},
            {"DesignPattern_BS_04", 24, ItemGroup::OnePerPlayer, 1, 1, 0, 0x11, 202},
            {"DesignPattern_BS_04_Var2", 24, ItemGroup::OnePerPlayer, 1, 1, 0, 0x11, 228},
            {"DesignPattern_BS_05", 24, ItemGroup::OnePerPlayer, 1, 1, 0, 0x11, 314},
            {"DesignPattern_BS_05_Var2", 24, ItemGroup::OnePerPlayer, 1, 1, 0, 0x11, 314},
            {"DesignPattern_BS_07", 24, ItemGroup::OnePerPlayer, 1, 1, 0, 0x11, 206},
            {"DesignPattern_BS_07_Var2", 24, ItemGroup::OnePerPlayer, 1, 1, 0, 0x11, 295},
            {"DesignPattern_BS_08", 24, ItemGroup::OnePerPlayer, 1, 1, 0, 0x11, -1},
            {"DesignPattern_BS_08_Var2", 24, ItemGroup::OnePerPlayer, 1, 1, 0, 0x11, -1},
            {"DesignPattern_BS_09_2", 24, ItemGroup::OnePerPlayer, 1, 1, 0, 0x11, 210},
            {"DesignPattern_BS_09_2_Var2", 24, ItemGroup::OnePerPlayer, 1, 1, 0, 0x11, 203},
            {"DesignPattern_BS_10", 24, ItemGroup::OnePerPlayer, 1, 1, 0, 0x11, -1},
            {"DesignPattern_BS_102", 24, ItemGroup::OnePerPlayer, 1, 1, 0, 0x11, -1},
            {"DesignPattern_BS_11", 24, ItemGroup::OnePerPlayer, 1, 1, 0, 0x11, -1},
            {"DesignPattern_BS_13", 24, ItemGroup::OnePerPlayer, 1, 1, 0, 0x11, 215},
            {"DesignPattern_BS_13_Var2", 24, ItemGroup::OnePerPlayer, 1, 1, 0, 0x11, 296},
            {"DesignPattern_BS_14", 24, ItemGroup::OnePerPlayer, 1, 1, 0, 0x11, 314},
            {"DesignPattern_BS_14_Var2", 24, ItemGroup::OnePerPlayer, 1, 1, 0, 0x11, 314},
            {"DesignPattern_BS_15", 24, ItemGroup::OnePerPlayer, 1, 1, 0, 0x11, -1},
            {"DesignPattern_BS_15_Var2", 24, ItemGroup::OnePerPlayer, 1, 1, 0, 0x11, 314},
            {"DesignPattern_BS_16", 24, ItemGroup::OnePerPlayer, 1, 1, 0, 0x11, 221},
            {"DesignPattern_BS_16_Var2", 24, ItemGroup::OnePerPlayer, 1, 1, 0, 0x11, 268},
            {"DesignPattern_BS_17", 24, ItemGroup::OnePerPlayer, 1, 1, 0, 0x11, -1},
            {"DesignPattern_BS_19", 24, ItemGroup::OnePerPlayer, 1, 1, 0, 0x11, -1},
            {"DesignPattern_BS_19_Var2", 24, ItemGroup::OnePerPlayer, 1, 1, 0, 0x11, -1},
            {"DesignPattern_BS_20", 24, ItemGroup::OnePerPlayer, 1, 1, 0, 0x11, -1},
            {"DesignPattern_BS_20_Var2", 24, ItemGroup::OnePerPlayer, 1, 1, 0, 0x11, -1},
            {"DesignPattern_BS_21", 24, ItemGroup::OnePerPlayer, 1, 1, 0, 0x11, 314},
            {"DesignPattern_BS_21_Var2", 24, ItemGroup::OnePerPlayer, 1, 1, 0, 0x11, 314},
            {"DesignPattern_BS_22", 24, ItemGroup::OnePerPlayer, 1, 1, 0, 0x11, -1},
            {"DesignPattern_BS_22_Var2", 24, ItemGroup::OnePerPlayer, 1, 1, 0, 0x11, -1},
            {"DesignPattern_BS_23", 24, ItemGroup::OnePerPlayer, 1, 1, 0, 0x11, -1},
            {"DesignPattern_BS_23_Var2", 24, ItemGroup::OnePerPlayer, 1, 1, 0, 0x11, -1},
            {"DesignPattern_BS_24", 24, ItemGroup::OnePerPlayer, 1, 1, 0, 0x11, 314},
            {"DesignPattern_BS_24_Var2", 24, ItemGroup::OnePerPlayer, 1, 1, 0, 0x11, 233},
            {"DesignPattern_BS_26", 24, ItemGroup::OnePerPlayer, 1, 1, 0, 0x11, -1},
            {"DesignPattern_BS_26_Var2", 24, ItemGroup::OnePerPlayer, 1, 1, 0, 0x11, -1},
            {"DesignPattern_BS_30", 24, ItemGroup::OnePerPlayer, 1, 1, 0, 0x11, -1},
            {"DesignPattern_BS_30_Var2", 24, ItemGroup::OnePerPlayer, 1, 1, 0, 0x11, -1},
            {"DesignPattern_BS_31", 24, ItemGroup::OnePerPlayer, 1, 1, 0, 0x11, 240},
            {"DesignPattern_BS_31_Var2", 24, ItemGroup::OnePerPlayer, 1, 1, 0, 0x11, 284},
            {"DesignPattern_BS_32", 24, ItemGroup::OnePerPlayer, 1, 1, 0, 0x11, -1},
            {"DesignPattern_BS_33", 24, ItemGroup::OnePerPlayer, 1, 1, 0, 0x11, -1},
            {"DesignPattern_BS_34", 24, ItemGroup::OnePerPlayer, 1, 1, 0, 0x11, 244},
            {"DesignPattern_BS_34_Var2", 24, ItemGroup::OnePerPlayer, 1, 1, 0, 0x11, 258},
            {"DesignPattern_BS_37", 24, ItemGroup::OnePerPlayer, 1, 1, 0, 0x11, 247},
            {"DesignPattern_BS_37_Var2", 24, ItemGroup::OnePerPlayer, 1, 1, 0, 0x11, -1},
            {"DesignPattern_BS_37_Var3", 24, ItemGroup::OnePerPlayer, 1, 1, 0, 0x11, 257},
            {"DesignPattern_BS_38", 24, ItemGroup::OnePerPlayer, 1, 1, 0, 0x11, 249},
            {"DesignPattern_BS_38_Var2", 24, ItemGroup::OnePerPlayer, 1, 1, 0, 0x11, 216},
            {"DesignPattern_BS_40", 24, ItemGroup::OnePerPlayer, 1, 1, 0, 0x11, 251},
            {"DesignPattern_BS_40_Var2", 24, ItemGroup::OnePerPlayer, 1, 1, 0, 0x11, 252},
            {"DesignPattern_BS_40_Var3", 24, ItemGroup::OnePerPlayer, 1, 1, 0, 0x11, 314},
            {"DesignPattern_BS_41", 24, ItemGroup::OnePerPlayer, 1, 1, 0, 0x11, 254},
            {"DesignPattern_BS_41_Var2", 24, ItemGroup::OnePerPlayer, 1, 1, 0, 0x11, 219},
            {"DesignPattern_BS_42", 24, ItemGroup::OnePerPlayer, 1, 1, 0, 0x11, 256},
            {"DesignPattern_BS_42_Var2", 24, ItemGroup::OnePerPlayer, 1, 1, 0, 0x11, 274},
            {"DesignPattern_BS_43", 24, ItemGroup::OnePerPlayer, 1, 1, 0, 0x11, 314},
            {"DesignPattern_BS_43_Var2", 24, ItemGroup::OnePerPlayer, 1, 1, 0, 0x11, 314},
            {"DesignPattern_BS_44", 24, ItemGroup::OnePerPlayer, 1, 1, 0, 0x11, 260},
            {"DesignPattern_BS_44_Var2", 24, ItemGroup::OnePerPlayer, 1, 1, 0, 0x11, 227},
            {"DesignPattern_BS_44_Var3", 24, ItemGroup::OnePerPlayer, 1, 1, 0, 0x11, -1},
            {"DesignPattern_BS_45", 24, ItemGroup::OnePerPlayer, 1, 1, 0, 0x11, 263},
            {"DesignPattern_BS_45_Var2", 24, ItemGroup::OnePerPlayer, 1, 1, 0, 0x11, 271},
            {"DesignPattern_BS_47", 24, ItemGroup::OnePerPlayer, 1, 1, 0, 0x11, 265},
            {"DesignPattern_BS_47_Var2", 24, ItemGroup::OnePerPlayer, 1, 1, 0, 0x11, 314},
            {"DesignPattern_BS_48", 24, ItemGroup::OnePerPlayer, 1, 1, 0, 0x11, -1},
            {"DesignPattern_BS_48_Var2", 24, ItemGroup::OnePerPlayer, 1, 1, 0, 0x11, -1},
            {"DesignPattern_BS_50", 24, ItemGroup::OnePerPlayer, 1, 1, 0, 0x11, 314},
            {"DesignPattern_BS_50_Var2", 24, ItemGroup::OnePerPlayer, 1, 1, 0, 0x11, 314},
            {"DesignPattern_BS_53", 24, ItemGroup::OnePerPlayer, 1, 1, 0, 0x11, -1},
            {"DesignPattern_BS_53_Var2", 24, ItemGroup::OnePerPlayer, 1, 1, 0, 0x11, 314},
            {"DesignPattern_BS_54", 24, ItemGroup::OnePerPlayer, 1, 1, 0, 0x11, 314},
            {"DesignPattern_BS_55", 24, ItemGroup::OnePerPlayer, 1, 1, 0, 0x11, -1},
            {"DesignPattern_BS_55_Var2", 24, ItemGroup::OnePerPlayer, 1, 1, 0, 0x11, 314},
            {"DesignPattern_BS_56", 24, ItemGroup::OnePerPlayer, 1, 1, 0, 0x11, -1},
            {"DesignPattern_BS_57", 24, ItemGroup::OnePerPlayer, 1, 1, 0, 0x11, -1},
            {"DesignPattern_BS_58", 24, ItemGroup::OnePerPlayer, 1, 1, 0, 0x11, -1},
            {"DesignPattern_BS_60", 24, ItemGroup::OnePerPlayer, 1, 1, 0, 0x11, -1},
            {"DesignPattern_BS_99", 24, ItemGroup::OnePerPlayer, 1, 1, 0, 0x11, -1},
            {"DesignPattern_BS_Bear", 24, ItemGroup::OnePerPlayer, 1, 1, 0, 0x11, -1},
            {"DesignPattern_BS_Bear_Var2", 24, ItemGroup::OnePerPlayer, 1, 1, 0, 0x11, -1},
            {"DesignPattern_BS_Black_Leather_bikini", 24, ItemGroup::OnePerPlayer, 1, 1, 0, 0x11, 283},
            {"DesignPattern_BS_Black_Leather_bikini_Var2", 24, ItemGroup::OnePerPlayer, 1, 1, 0, 0x11, 272},
            {"DesignPattern_BS_Blue_Suit", 24, ItemGroup::OnePerPlayer, 1, 1, 0, 0x11, 314},
            {"DesignPattern_BS_Default", 24, ItemGroup::OnePerPlayer, 1, 1, 0, 0x11, -1},
            {"DesignPattern_BS_Default_Var2", 24, ItemGroup::OnePerPlayer, 1, 1, 0, 0x11, -1},
            {"DesignPattern_BS_Default_Var3", 24, ItemGroup::OnePerPlayer, 1, 1, 0, 0x11, -1},
            {"DesignPattern_BS_EVE_04", 24, ItemGroup::OnePerPlayer, 1, 1, 0, 0x11, -1},
            {"DesignPattern_BS_EVE_04_Var2", 24, ItemGroup::OnePerPlayer, 1, 1, 0, 0x11, -1},
            {"DesignPattern_BS_Leather_Jean", 24, ItemGroup::OnePerPlayer, 1, 1, 0, 0x11, -1},
            {"DesignPattern_BS_Leather_Jean_Var2", 24, ItemGroup::OnePerPlayer, 1, 1, 0, 0x11, -1},
            {"DesignPattern_BS_Raven", 24, ItemGroup::OnePerPlayer, 1, 1, 0, 0x11, -1},
            {"DesignPattern_BS_Sailor_Jean", 24, ItemGroup::OnePerPlayer, 1, 1, 0, 0x11, 294},
            {"DesignPattern_BS_Sailor_Jean_Var2", 24, ItemGroup::OnePerPlayer, 1, 1, 0, 0x11, 269},
            {"DesignPattern_BS_SilverKunoichi", 24, ItemGroup::OnePerPlayer, 1, 1, 0, 0x11, 314},
            {"DesignPattern_BS_SilverKunoichi_Var2", 24, ItemGroup::OnePerPlayer, 1, 1, 0, 0x11, 314},
            {"DesignPattern_BS_White_Jean", 24, ItemGroup::OnePerPlayer, 1, 1, 0, 0x11, 298},
            {"DesignPattern_BS_White_Jean_Var2", 24, ItemGroup::OnePerPlayer, 1, 1, 0, 0x11, 217},
            {"DesignPattern_BS_Yellow_Suit", 24, ItemGroup::OnePerPlayer, 1, 1, 0, 0x11, -1},
            {"DesignPattern_BS_Yellow_Suit_Jacket", 24, ItemGroup::OnePerPlayer, 1, 1, 0, 0x11, 301},
            {"DesignPattern_BS_Yellow_Suit_Jacket_Var2", 24, ItemGroup::OnePerPlayer, 1, 1, 0, 0x11, 204},
            {"DesignPattern_BS_Yellow_Suit_Var2", 24, ItemGroup::OnePerPlayer, 1, 1, 0, 0x11, -1},
            {"DroneCore", 11, ItemGroup::Stack, 99, 999999, 0, 0x02, -1},
            {"DroneSeal_001", 28, ItemGroup::OnePerPlayer, 1, 1, 0, 0x21, -1},
            {"DroneSeal_002", 28, ItemGroup::OnePerPlayer, 1, 1, 0, 0x01, 306},
            {"DroneSeal_002_Var2", 28, ItemGroup::OnePerPlayer, 1, 1, 0, 0x01, 314},
            {"DroneSeal_003", 28, ItemGroup::Gated, 0, 1, 0, 0x00, -1},
            {"DroneSeal_004", 28, ItemGroup::OnePerPlayer, 1, 1, 0, 0x01, 309},
            {"DroneSeal_004_Var2", 28, ItemGroup::OnePerPlayer, 1, 1, 0, 0x01, 314},
            {"DroneSeal_005", 28, ItemGroup::Gated, 0, 1, 0, 0x00, -1},
            {"DroneSeal_Christmas_01", 28, ItemGroup::OnePerPlayer, 1, 1, 0, 0x01, 315},
            {"DroneSeal_Nier_001", 28, ItemGroup::Gated, 0, 1, 0, 0x10, -1},
            {"ECelluloseRayon", 10, ItemGroup::Stack, 99, 999999, 0, 0x01, -1},
            {"ETC_Item_VendingMachineCoin", 20, ItemGroup::Currency, 9999, 999999, 0, 0x32, -1},
            {"ETC_Item_VendingMachineCoin_Christmas", 20, ItemGroup::WatchOnly, 0, 999999, 0, 0x00, -1},
            {"Earring_001", 23, ItemGroup::OnePerPlayer, 1, 1, 0, 0x21, 317},
            {"Earring_001_Var2", 23, ItemGroup::OnePerPlayer, 1, 1, 0, 0x01, 331},
            {"Earring_002", 23, ItemGroup::OnePerPlayer, 1, 1, 0, 0x01, 319},
            {"Earring_002_Var2", 23, ItemGroup::OnePerPlayer, 1, 1, 0, 0x01, 332},
            {"Earring_003", 23, ItemGroup::OnePerPlayer, 1, 1, 0, 0x11, 321},
            {"Earring_003_Var2", 23, ItemGroup::OnePerPlayer, 1, 1, 0, 0x11, 314},
            {"Earring_004", 23, ItemGroup::OnePerPlayer, 1, 1, 0, 0x01, -1},
            {"Earring_005", 23, ItemGroup::Gated, 0, 1, 0, 0x10, 314},
            {"Earring_006", 23, ItemGroup::OnePerPlayer, 1, 1, 0, 0x01, -1},
            {"Earring_007", 23, ItemGroup::OnePerPlayer, 1, 1, 0, 0x01, -1},
            {"Earring_008", 23, ItemGroup::OnePerPlayer, 1, 1, 0, 0x01, 327},
            {"Earring_008_Var2", 23, ItemGroup::OnePerPlayer, 1, 1, 0, 0x01, 333},
            {"Earring_009", 23, ItemGroup::OnePerPlayer, 1, 1, 0, 0x01, -1},
            {"Earring_010", 23, ItemGroup::OnePerPlayer, 1, 1, 0, 0x01, -1},
            {"Earring_011", 23, ItemGroup::Gated, 0, 1, 0, 0x00, -1},
            {"Earring_012", 23, ItemGroup::OnePerPlayer, 1, 1, 0, 0x01, 314},
            {"Earring_013", 23, ItemGroup::OnePerPlayer, 1, 1, 0, 0x01, 314},
            {"Earring_014", 23, ItemGroup::OnePerPlayer, 1, 1, 0, 0x01, 314},
            {"Earring_015", 23, ItemGroup::OnePerPlayer, 1, 1, 0, 0x01, -1},
            {"Earring_016", 23, ItemGroup::OnePerPlayer, 1, 1, 0, 0x01, -1},
            {"Earring_017", 23, ItemGroup::OnePerPlayer, 1, 1, 0, 0x01, -1},
            {"Earring_018", 23, ItemGroup::OnePerPlayer, 1, 1, 0, 0x01, -1},
            {"Earring_Christmas_01", 23, ItemGroup::OnePerPlayer, 1, 1, 0, 0x01, 315},
            {"Earring_Christmas_02", 23, ItemGroup::OnePerPlayer, 1, 1, 0, 0x01, 315},
            {"ElastomerFiber", 10, ItemGroup::Stack, 99, 999999, 0, 0x01, -1},
            {"FaceAccessory_001", 22, ItemGroup::OnePerPlayer, 1, 1, 0, 0x21, -1},
            {"FaceAccessory_002", 22, ItemGroup::OnePerPlayer, 1, 1, 0, 0x11, 343},
            {"FaceAccessory_002_Var2", 22, ItemGroup::OnePerPlayer, 1, 1, 0, 0x11, 314},
            {"FaceAccessory_003", 22, ItemGroup::Gated, 0, 1, 0, 0x10, 314},
            {"FaceAccessory_004", 22, ItemGroup::OnePerPlayer, 1, 1, 0, 0x01, -1},
            {"FaceAccessory_005", 22, ItemGroup::OnePerPlayer, 1, 1, 0, 0x01, -1},
            {"FaceAccessory_006", 22, ItemGroup::OnePerPlayer, 1, 1, 0, 0x01, -1},
            {"FaceAccessory_007", 22, ItemGroup::OnePerPlayer, 1, 1, 0, 0x01, -1},
            {"FaceAccessory_008", 22, ItemGroup::OnePerPlayer, 1, 1, 0, 0x01, -1},
            {"FaceAccessory_009", 22, ItemGroup::OnePerPlayer, 1, 1, 0, 0x01, -1},
            {"FaceAccessory_010", 22, ItemGroup::OnePerPlayer, 1, 1, 0, 0x01, -1},
            {"FaceAccessory_011", 22, ItemGroup::OnePerPlayer, 1, 1, 0, 0x01, -1},
            {"FaceAccessory_012", 22, ItemGroup::Gated, 0, 1, 0, 0x00, -1},
            {"FaceAccessory_013", 22, ItemGroup::OnePerPlayer, 1, 1, 0, 0x01, -1},
            {"FaceAccessory_026", 22, ItemGroup::OnePerPlayer, 1, 1, 0, 0x01, -1},
            {"FaceAccessory_027", 22, ItemGroup::OnePerPlayer, 1, 1, 0, 0x01, -1},
            {"FaceAccessory_028", 22, ItemGroup::OnePerPlayer, 1, 1, 0, 0x01, -1},
            {"FaceAccessory_029", 22, ItemGroup::OnePerPlayer, 1, 1, 0, 0x01, -1},
            {"FaceAccessory_Christmas_01", 22, ItemGroup::OnePerPlayer, 1, 1, 0, 0x01, 315},
            {"FaceAccessory_Nier_001", 22, ItemGroup::Gated, 0, 1, 0, 0x10, -1},
            {"Fish_Arowana", 18, ItemGroup::Stack, 99, 999999, 0, 0x31, -1},
            {"Fish_Betta", 18, ItemGroup::Stack, 99, 999999, 0, 0x11, -1},
            {"Fish_Box1", 18, ItemGroup::Stack, 99, 999999, 0, 0x01, -1},
            {"Fish_Box2", 18, ItemGroup::Stack, 99, 999999, 0, 0x01, -1},
            {"Fish_Box3", 18, ItemGroup::Stack, 99, 999999, 0, 0x01, -1},
            {"Fish_Box4", 18, ItemGroup::Stack, 99, 999999, 0, 0x01, -1},
            {"Fish_ButterflyFish", 18, ItemGroup::Stack, 99, 999999, 0, 0x11, -1},
            {"Fish_CannedFish", 18, ItemGroup::Stack, 99, 999999, 0, 0x01, -1},
            {"Fish_CannerHam", 18, ItemGroup::Stack, 99, 999999, 0, 0x01, -1},
            {"Fish_ChannelCatfish", 18, ItemGroup::Stack, 99, 999999, 0, 0x19, -1},
            {"Fish_Dunkleosteus", 18, ItemGroup::Stack, 99, 999999, 0, 0x11, -1},
            {"Fish_FancyCarp", 18, ItemGroup::Stack, 99, 999999, 0, 0x11, -1},
            {"Fish_FishCake", 18, ItemGroup::Stack, 99, 999999, 0, 0x01, -1},
            {"Fish_FlyingFish", 18, ItemGroup::Stack, 99, 999999, 0, 0x11, -1},
            {"Fish_FootBallfish", 18, ItemGroup::Stack, 99, 999999, 0, 0x11, -1},
            {"Fish_Goby", 18, ItemGroup::Stack, 99, 999999, 0, 0x11, -1},
            {"Fish_GoldFish", 18, ItemGroup::Stack, 99, 999999, 0, 0x11, -1},
            {"Fish_GreatWhiteShark", 18, ItemGroup::Stack, 99, 999999, 0, 0x11, -1},
            {"Fish_Halibut", 18, ItemGroup::Stack, 99, 999999, 0, 0x19, -1},
            {"Fish_Lobster", 18, ItemGroup::Stack, 99, 999999, 0, 0x11, -1},
            {"Fish_Mahimahi", 18, ItemGroup::Stack, 99, 999999, 0, 0x11, -1},
            {"Fish_MolaMola", 18, ItemGroup::Stack, 99, 999999, 0, 0x11, -1},
            {"Fish_Nikke_Glasses", 18, ItemGroup::Gated, 0, 1, 0, 0x10, -1},
            {"Fish_Nikke_Laplace", 18, ItemGroup::Gated, 0, 1, 0, 0x10, -1},
            {"Fish_Nikke_Poli", 18, ItemGroup::Gated, 0, 1, 0, 0x10, -1},
            {"Fish_Nikke_Rapunzel", 18, ItemGroup::Gated, 0, 1, 0, 0x10, -1},
            {"Fish_Nikke_SnowWhite", 18, ItemGroup::Gated, 0, 1, 0, 0x10, -1},
            {"Fish_Nikke_Tape", 18, ItemGroup::Gated, 0, 1, 0, 0x10, -1},
            {"Fish_NuclearWaste", 18, ItemGroup::Stack, 99, 999999, 0, 0x01, -1},
            {"Fish_Pirarucu", 18, ItemGroup::Stack, 99, 999999, 0, 0x11, -1},
            {"Fish_PorcupineFish", 18, ItemGroup::Stack, 99, 999999, 0, 0x19, -1},
            {"Fish_SailFish", 18, ItemGroup::Stack, 99, 999999, 0, 0x11, -1},
            {"Fish_Salmon", 18, ItemGroup::Stack, 99, 999999, 0, 0x11, -1},
            {"Fish_SeaBass", 18, ItemGroup::Stack, 99, 999999, 0, 0x11, -1},
            {"Fish_SeaBream", 18, ItemGroup::Stack, 99, 999999, 0, 0x11, -1},
            {"Fish_Tire", 18, ItemGroup::Stack, 99, 999999, 0, 0x01, -1},
            {"Fish_Triggerfish", 18, ItemGroup::Stack, 99, 999999, 0, 0x11, -1},
            {"Fish_Tuna", 18, ItemGroup::Stack, 99, 999999, 0, 0x11, -1},
            {"Fish_WhaleShark", 18, ItemGroup::Stack, 99, 999999, 0, 0x19, -1},
            {"Fish_mackerel", 18, ItemGroup::Stack, 99, 999999, 0, 0x11, -1},
            {"FishingPoint", 20, ItemGroup::Currency, 9999, 999999, 0, 0x02, -1},
            {"FishingSkillBook1", 20, ItemGroup::OnePerPlayer, 1, 999999, 0, 0x12, -1},
            {"FishingSkillBook2", 20, ItemGroup::OnePerPlayer, 1, 999999, 0, 0x12, -1},
            {"FishingSkillBook3", 20, ItemGroup::OnePerPlayer, 1, 999999, 0, 0x12, -1},
            {"FishingSkillBook4", 20, ItemGroup::OnePerPlayer, 1, 999999, 0, 0x1A, -1},
            {"FlashGrenade", 16, ItemGroup::Stack, 99, 999999, 0, 0x01, -1},
            {"GearCore", 11, ItemGroup::Stack, 99, 999999, 0, 0x02, -1},
            {"Gear_AdditiveBetaSkillDamage_Common", 2, ItemGroup::UniqueInstance, 1, 1, 0, 0x21, 409},
            {"Gear_AdditiveBetaSkillDamage_Common_MK2", 2, ItemGroup::UniqueInstance, 1, 1, 0, 0x01, 314},
            {"Gear_AdditiveBetaSkillDamage_Rare", 2, ItemGroup::UniqueInstance, 1, 1, 0, 0x01, 411},
            {"Gear_AdditiveBetaSkillDamage_Rare_MK2", 2, ItemGroup::UniqueInstance, 1, 1, 0, 0x01, 314},
            {"Gear_AdditiveBetaSkillDamage_Uncommon", 2, ItemGroup::UniqueInstance, 1, 1, 0, 0x01, 413},
            {"Gear_AdditiveBetaSkillDamage_Uncommon_MK2", 2, ItemGroup::UniqueInstance, 1, 1, 0, 0x01, 314},
            {"Gear_AdditiveBustSkillDamage_Common", 2, ItemGroup::UniqueInstance, 1, 1, 0, 0x01, 415},
            {"Gear_AdditiveBustSkillDamage_Common_MK2", 2, ItemGroup::UniqueInstance, 1, 1, 0, 0x01, 314},
            {"Gear_AdditiveBustSkillDamage_Rare", 2, ItemGroup::UniqueInstance, 1, 1, 0, 0x11, 417},
            {"Gear_AdditiveBustSkillDamage_Rare_MK2", 2, ItemGroup::UniqueInstance, 1, 1, 0, 0x11, 314},
            {"Gear_AdditiveBustSkillDamage_Uncommon", 2, ItemGroup::UniqueInstance, 1, 1, 0, 0x01, 419},
            {"Gear_AdditiveBustSkillDamage_Uncommon_MK2", 2, ItemGroup::UniqueInstance, 1, 1, 0, 0x01, 314},
            {"Gear_AdditiveFixedDamage_Common", 2, ItemGroup::UniqueInstance, 1, 1, 0, 0x01, 421},
            {"Gear_AdditiveFixedDamage_Common_MK2", 2, ItemGroup::UniqueInstance, 1, 1, 0, 0x01, 314},
            {"Gear_AdditiveFixedDamage_Rare", 2, ItemGroup::UniqueInstance, 1, 1, 0, 0x01, 423},
            {"Gear_AdditiveFixedDamage_Rare_MK2", 2, ItemGroup::UniqueInstance, 1, 1, 0, 0x01, 314},
            {"Gear_AdditiveFixedDamage_Uncommon", 2, ItemGroup::UniqueInstance, 1, 1, 0, 0x01, 425},
            {"Gear_AdditiveFixedDamage_Uncommon_MK2", 2, ItemGroup::UniqueInstance, 1, 1, 0, 0x01, 314},
            {"Gear_AdditiveGiveAndReciveDamageRate_Common", 2, ItemGroup::UniqueInstance, 1, 1, 0, 0x01, 427},
            {"Gear_AdditiveGiveAndReciveDamageRate_Common_MK2", 2, ItemGroup::UniqueInstance, 1, 1, 0, 0x01, 314},
            {"Gear_AdditiveGiveAndReciveDamageRate_Rare", 2, ItemGroup::UniqueInstance, 1, 1, 0, 0x01, 429},
            {"Gear_AdditiveGiveAndReciveDamageRate_Rare_MK2", 2, ItemGroup::UniqueInstance, 1, 1, 0, 0x01, 314},
            {"Gear_AdditiveGiveAndReciveDamageRate_Uncommon", 2, ItemGroup::UniqueInstance, 1, 1, 0, 0x01, 431},
            {"Gear_AdditiveGiveAndReciveDamageRate_Uncommon_MK2", 2, ItemGroup::UniqueInstance, 1, 1, 0, 0x01, 314},
            {"Gear_AttackSpeed_Common", 2, ItemGroup::UniqueInstance, 1, 1, 0, 0x01, 433},
            {"Gear_AttackSpeed_Common_MK2", 2, ItemGroup::UniqueInstance, 1, 1, 0, 0x01, 314},
            {"Gear_AttackSpeed_Rare", 2, ItemGroup::UniqueInstance, 1, 1, 0, 0x01, 435},
            {"Gear_AttackSpeed_Rare_MK2", 2, ItemGroup::UniqueInstance, 1, 1, 0, 0x01, 314},
            {"Gear_AttackSpeed_Uncommon", 2, ItemGroup::UniqueInstance, 1, 1, 0, 0x01, 437},
            {"Gear_AttackSpeed_Uncommon_MK2", 2, ItemGroup::UniqueInstance, 1, 1, 0, 0x01, 314},
            {"Gear_BetaCrystalAdditiveRate_Common", 2, ItemGroup::UniqueInstance, 1, 1, 0, 0x01, 439},
            {"Gear_BetaCrystalAdditiveRate_Common_MK2", 2, ItemGroup::UniqueInstance, 1, 1, 0, 0x01, 314},
            {"Gear_BetaCrystalAdditiveRate_Rare", 2, ItemGroup::UniqueInstance, 1, 1, 0, 0x01, 441},
            {"Gear_BetaCrystalAdditiveRate_Rare_MK2", 2, ItemGroup::UniqueInstance, 1, 1, 0, 0x01, 314},
            {"Gear_BetaCrystalAdditiveRate_Uncommon", 2, ItemGroup::UniqueInstance, 1, 1, 0, 0x01, 443},
            {"Gear_BetaCrystalAdditiveRate_Uncommon_MK2", 2, ItemGroup::UniqueInstance, 1, 1, 0, 0x01, 314},
            {"Gear_BetaGaugeAdditiveRate_Common", 2, ItemGroup::UniqueInstance, 1, 1, 0, 0x01, 445},
            {"Gear_BetaGaugeAdditiveRate_Common_MK2", 2, ItemGroup::UniqueInstance, 1, 1, 0, 0x01, 314},
            {"Gear_BetaGaugeAdditiveRate_Rare", 2, ItemGroup::UniqueInstance, 1, 1, 0, 0x01, 447},
            {"Gear_BetaGaugeAdditiveRate_Rare_MK2", 2, ItemGroup::UniqueInstance, 1, 1, 0, 0x01, 314},
            {"Gear_BetaGaugeAdditiveRate_Uncommon", 2, ItemGroup::UniqueInstance, 1, 1, 0, 0x01, 449},
            {"Gear_BetaGaugeAdditiveRate_Uncommon_MK2", 2, ItemGroup::UniqueInstance, 1, 1, 0, 0x01, 314},
            {"Gear_BurstGaugeAdditiveRate_Common", 2, ItemGroup::UniqueInstance, 1, 1, 0, 0x01, 451},
            {"Gear_BurstGaugeAdditiveRate_Common_MK2", 2, ItemGroup::UniqueInstance, 1, 1, 0, 0x01, 314},
            {"Gear_BurstGaugeAdditiveRate_Rare", 2, ItemGroup::UniqueInstance, 1, 1, 0, 0x01, 453},
            {"Gear_BurstGaugeAdditiveRate_Rare_MK2", 2, ItemGroup::UniqueInstance, 1, 1, 0, 0x01, 314},
            {"Gear_BurstGaugeAdditiveRate_Uncommon", 2, ItemGroup::UniqueInstance, 1, 1, 0, 0x01, 455},
            {"Gear_BurstGaugeAdditiveRate_Uncommon_MK2", 2, ItemGroup::UniqueInstance, 1, 1, 0, 0x01, 314},
            {"Gear_ComboAttackAdditiveDamage_Common", 2, ItemGroup::UniqueInstance, 1, 1, 0, 0x01, 457},
            {"Gear_ComboAttackAdditiveDamage_Common_MK2", 2, ItemGroup::UniqueInstance, 1, 1, 0, 0x01, 314},
            {"Gear_ComboAttackAdditiveDamage_Rare", 2, ItemGroup::UniqueInstance, 1, 1, 0, 0x01, 459},
            {"Gear_ComboAttackAdditiveDamage_Rare_MK2", 2, ItemGroup::UniqueInstance, 1, 1, 0, 0x01, 314},
            {"Gear_ComboAttackAdditiveDamage_Uncommon", 2, ItemGroup::UniqueInstance, 1, 1, 0, 0x01, 461},
            {"Gear_ComboAttackAdditiveDamage_Uncommon_MK2", 2, ItemGroup::UniqueInstance, 1, 1, 0, 0x01, 314},
            {"Gear_CriticalPercentage_Common", 2, ItemGroup::UniqueInstance, 1, 1, 0, 0x01, 463},
            {"Gear_CriticalPercentage_Common_MK2", 2, ItemGroup::UniqueInstance, 1, 1, 0, 0x01, 314},
            {"Gear_CriticalPercentage_Rare", 2, ItemGroup::UniqueInstance, 1, 1, 0, 0x01, 465},
            {"Gear_CriticalPercentage_Rare_MK2", 2, ItemGroup::UniqueInstance, 1, 1, 0, 0x01, 314},
            {"Gear_CriticalPercentage_Uncommon", 2, ItemGroup::UniqueInstance, 1, 1, 0, 0x01, 467},
            {"Gear_CriticalPercentage_Uncommon_MK2", 2, ItemGroup::UniqueInstance, 1, 1, 0, 0x01, 314},
            {"Gear_CriticalValueRate_Common", 2, ItemGroup::UniqueInstance, 1, 1, 0, 0x01, 469},
            {"Gear_CriticalValueRate_Common_MK2", 2, ItemGroup::UniqueInstance, 1, 1, 0, 0x01, 314},
            {"Gear_CriticalValueRate_Rare", 2, ItemGroup::UniqueInstance, 1, 1, 0, 0x01, 471},
            {"Gear_CriticalValueRate_Rare_MK2", 2, ItemGroup::UniqueInstance, 1, 1, 0, 0x01, 314},
            {"Gear_CriticalValueRate_Uncommon", 2, ItemGroup::UniqueInstance, 1, 1, 0, 0x01, 473},
            {"Gear_CriticalValueRate_Uncommon_MK2", 2, ItemGroup::UniqueInstance, 1, 1, 0, 0x01, 314},
            {"Gear_GainBetaGaugeValueOnDamaged_Common", 2, ItemGroup::UniqueInstance, 1, 1, 0, 0x01, 475},
            {"Gear_GainBetaGaugeValueOnDamaged_Common_MK2", 2, ItemGroup::UniqueInstance, 1, 1, 0, 0x01, 314},
            {"Gear_GainBetaGaugeValueOnDamaged_Rare", 2, ItemGroup::UniqueInstance, 1, 1, 0, 0x01, 477},
            {"Gear_GainBetaGaugeValueOnDamaged_Rare_MK2", 2, ItemGroup::UniqueInstance, 1, 1, 0, 0x01, 314},
            {"Gear_GainBetaGaugeValueOnDamaged_Uncommon", 2, ItemGroup::UniqueInstance, 1, 1, 0, 0x01, 479},
            {"Gear_GainBetaGaugeValueOnDamaged_Uncommon_MK2", 2, ItemGroup::UniqueInstance, 1, 1, 0, 0x01, 314},
            {"Gear_GainBurstGaugeValueOnDamaged_Common", 2, ItemGroup::UniqueInstance, 1, 1, 0, 0x01, 481},
            {"Gear_GainBurstGaugeValueOnDamaged_Common_MK2", 2, ItemGroup::UniqueInstance, 1, 1, 0, 0x01, 314},
            {"Gear_GainBurstGaugeValueOnDamaged_Rare", 2, ItemGroup::UniqueInstance, 1, 1, 0, 0x01, 483},
            {"Gear_GainBurstGaugeValueOnDamaged_Rare_MK2", 2, ItemGroup::UniqueInstance, 1, 1, 0, 0x01, 314},
            {"Gear_GainBurstGaugeValueOnDamaged_Uncommon", 2, ItemGroup::UniqueInstance, 1, 1, 0, 0x01, 485},
            {"Gear_GainBurstGaugeValueOnDamaged_Uncommon_MK2", 2, ItemGroup::UniqueInstance, 1, 1, 0, 0x01, 314},
            {"Gear_HighHpDamageAdditiveRate_Common", 2, ItemGroup::UniqueInstance, 1, 1, 0, 0x01, 487},
            {"Gear_HighHpDamageAdditiveRate_Common_MK2", 2, ItemGroup::UniqueInstance, 1, 1, 0, 0x01, 314},
            {"Gear_HighHpDamageAdditiveRate_Rare", 2, ItemGroup::UniqueInstance, 1, 1, 0, 0x01, 489},
            {"Gear_HighHpDamageAdditiveRate_Rare_MK2", 2, ItemGroup::UniqueInstance, 1, 1, 0, 0x01, 314},
            {"Gear_HighHpDamageAdditiveRate_Uncommon", 2, ItemGroup::UniqueInstance, 1, 1, 0, 0x01, 491},
            {"Gear_HighHpDamageAdditiveRate_Uncommon_MK2", 2, ItemGroup::UniqueInstance, 1, 1, 0, 0x01, 314},
            {"Gear_KillEnemyAdditiveDamageRate_Common", 2, ItemGroup::UniqueInstance, 1, 1, 0, 0x01, 493},
            {"Gear_KillEnemyAdditiveDamageRate_Common_MK2", 2, ItemGroup::UniqueInstance, 1, 1, 0, 0x01, 314},
            {"Gear_KillEnemyAdditiveDamageRate_Rare", 2, ItemGroup::UniqueInstance, 1, 1, 0, 0x01, 495},
            {"Gear_KillEnemyAdditiveDamageRate_Rare_MK2", 2, ItemGroup::UniqueInstance, 1, 1, 0, 0x01, 314},
            {"Gear_KillEnemyAdditiveDamageRate_Uncommon", 2, ItemGroup::UniqueInstance, 1, 1, 0, 0x01, 497},
            {"Gear_KillEnemyAdditiveDamageRate_Uncommon_MK2", 2, ItemGroup::UniqueInstance, 1, 1, 0, 0x01, 314},
            {"Gear_KillEnemyHealHP_Common", 2, ItemGroup::UniqueInstance, 1, 1, 0, 0x01, 499},
            {"Gear_KillEnemyHealHP_Common_MK2", 2, ItemGroup::UniqueInstance, 1, 1, 0, 0x01, 314},
            {"Gear_KillEnemyHealHP_Rare", 2, ItemGroup::UniqueInstance, 1, 1, 0, 0x01, 501},
            {"Gear_KillEnemyHealHP_Rare_MK2", 2, ItemGroup::UniqueInstance, 1, 1, 0, 0x01, 314},
            {"Gear_KillEnemyHealHP_Uncommon", 2, ItemGroup::UniqueInstance, 1, 1, 0, 0x01, 503},
            {"Gear_KillEnemyHealHP_Uncommon_MK2", 2, ItemGroup::UniqueInstance, 1, 1, 0, 0x01, 314},
            {"Gear_LowHpDamageAdditiveRate_Common", 2, ItemGroup::UniqueInstance, 1, 1, 0, 0x01, 505},
            {"Gear_LowHpDamageAdditiveRate_Common_MK2", 2, ItemGroup::UniqueInstance, 1, 1, 0, 0x01, 314},
            {"Gear_LowHpDamageAdditiveRate_Rare", 2, ItemGroup::UniqueInstance, 1, 1, 0, 0x11, 507},
            {"Gear_LowHpDamageAdditiveRate_Rare_MK2", 2, ItemGroup::UniqueInstance, 1, 1, 0, 0x11, 314},
            {"Gear_LowHpDamageAdditiveRate_Uncommon", 2, ItemGroup::UniqueInstance, 1, 1, 0, 0x01, 509},
            {"Gear_LowHpDamageAdditiveRate_Uncommon_MK2", 2, ItemGroup::UniqueInstance, 1, 1, 0, 0x01, 314},
            {"Gear_MaxBurstGauge_Common", 2, ItemGroup::UniqueInstance, 1, 1, 0, 0x01, 511},
            {"Gear_MaxBurstGauge_Common_MK2", 2, ItemGroup::UniqueInstance, 1, 1, 0, 0x01, 314},
            {"Gear_MaxBurstGauge_Rare", 2, ItemGroup::UniqueInstance, 1, 1, 0, 0x01, 513},
            {"Gear_MaxBurstGauge_Rare_MK2", 2, ItemGroup::UniqueInstance, 1, 1, 0, 0x01, 314},
            {"Gear_MaxBurstGauge_Uncommon", 2, ItemGroup::UniqueInstance, 1, 1, 0, 0x01, 515},
            {"Gear_MaxBurstGauge_Uncommon_MK2", 2, ItemGroup::UniqueInstance, 1, 1, 0, 0x01, 314},
            {"Gear_MaxShield_Common", 2, ItemGroup::UniqueInstance, 1, 1, 0, 0x01, 517},
            {"Gear_MaxShield_Common_MK2", 2, ItemGroup::UniqueInstance, 1, 1, 0, 0x01, 314},
            {"Gear_MaxShield_Rare", 2, ItemGroup::UniqueInstance, 1, 1, 0, 0x11, 519},
            {"Gear_MaxShield_Rare_MK2", 2, ItemGroup::UniqueInstance, 1, 1, 0, 0x01, 314},
            {"Gear_MaxShield_Uncommon", 2, ItemGroup::UniqueInstance, 1, 1, 0, 0x01, 521},
            {"Gear_MaxShield_Uncommon_MK2", 2, ItemGroup::UniqueInstance, 1, 1, 0, 0x01, 314},
            {"Gear_MeleeAttackDamageReductionRate_Common", 2, ItemGroup::UniqueInstance, 1, 1, 0, 0x01, 523},
            {"Gear_MeleeAttackDamageReductionRate_Common_MK2", 2, ItemGroup::UniqueInstance, 1, 1, 0, 0x01, 314},
            {"Gear_MeleeAttackDamageReductionRate_Rare", 2, ItemGroup::UniqueInstance, 1, 1, 0, 0x01, 525},
            {"Gear_MeleeAttackDamageReductionRate_Rare_MK2", 2, ItemGroup::UniqueInstance, 1, 1, 0, 0x01, 314},
            {"Gear_MeleeAttackDamageReductionRate_Uncommon", 2, ItemGroup::UniqueInstance, 1, 1, 0, 0x01, 527},
            {"Gear_MeleeAttackDamageReductionRate_Uncommon_MK2", 2, ItemGroup::UniqueInstance, 1, 1, 0, 0x01, 314},
            {"Gear_MeleeRangeDamageReductionRate_Common", 2, ItemGroup::UniqueInstance, 1, 1, 0, 0x01, 529},
            {"Gear_MeleeRangeDamageReductionRate_Common_MK2", 2, ItemGroup::UniqueInstance, 1, 1, 0, 0x01, 314},
            {"Gear_MeleeRangeDamageReductionRate_Rare", 2, ItemGroup::UniqueInstance, 1, 1, 0, 0x01, 531},
            {"Gear_MeleeRangeDamageReductionRate_Rare_MK2", 2, ItemGroup::UniqueInstance, 1, 1, 0, 0x01, 314},
            {"Gear_MeleeRangeDamageReductionRate_Uncommon", 2, ItemGroup::UniqueInstance, 1, 1, 0, 0x01, 533},
            {"Gear_MeleeRangeDamageReductionRate_Uncommon_MK2", 2, ItemGroup::UniqueInstance, 1, 1, 0, 0x01, 314},
            {"Gear_RangeAttackDamageAdditiveRate_Common", 2, ItemGroup::UniqueInstance, 1, 1, 0, 0x01, 535},
            {"Gear_RangeAttackDamageAdditiveRate_Common_MK2", 2, ItemGroup::UniqueInstance, 1, 1, 0, 0x01, 314},
            {"Gear_RangeAttackDamageAdditiveRate_Rare", 2, ItemGroup::UniqueInstance, 1, 1, 0, 0x01, 537},
            {"Gear_RangeAttackDamageAdditiveRate_Rare_MK2", 2, ItemGroup::UniqueInstance, 1, 1, 0, 0x01, 314},
            {"Gear_RangeAttackDamageAdditiveRate_Uncommon", 2, ItemGroup::UniqueInstance, 1, 1, 0, 0x01, 539},
            {"Gear_RangeAttackDamageAdditiveRate_Uncommon_MK2", 2, ItemGroup::UniqueInstance, 1, 1, 0, 0x01, 314},
            {"Gear_RangeAttackDamageReductionRate_Common", 2, ItemGroup::UniqueInstance, 1, 1, 0, 0x01, 541},
            {"Gear_RangeAttackDamageReductionRate_Common_MK2", 2, ItemGroup::UniqueInstance, 1, 1, 0, 0x01, 314},
            {"Gear_RangeAttackDamageReductionRate_Rare", 2, ItemGroup::UniqueInstance, 1, 1, 0, 0x01, 543},
            {"Gear_RangeAttackDamageReductionRate_Rare_MK2", 2, ItemGroup::UniqueInstance, 1, 1, 0, 0x01, 314},
            {"Gear_RangeAttackDamageReductionRate_Uncommon", 2, ItemGroup::UniqueInstance, 1, 1, 0, 0x01, 545},
            {"Gear_RangeAttackDamageReductionRate_Uncommon_MK2", 2, ItemGroup::UniqueInstance, 1, 1, 0, 0x01, 314},
            {"Gear_SPExpAdditiveRate_Common", 2, ItemGroup::UniqueInstance, 1, 1, 0, 0x01, 547},
            {"Gear_SPExpAdditiveRate_Common_MK2", 2, ItemGroup::UniqueInstance, 1, 1, 0, 0x01, 314},
            {"Gear_SPExpAdditiveRate_Rare", 2, ItemGroup::UniqueInstance, 1, 1, 0, 0x01, 549},
            {"Gear_SPExpAdditiveRate_Rare_MK2", 2, ItemGroup::UniqueInstance, 1, 1, 0, 0x01, 314},
            {"Gear_SPExpAdditiveRate_Uncommon", 2, ItemGroup::UniqueInstance, 1, 1, 0, 0x01, 551},
            {"Gear_SPExpAdditiveRate_Uncommon_MK2", 2, ItemGroup::UniqueInstance, 1, 1, 0, 0x01, 314},
            {"Gear_ShieldAttackPowerRate_Common", 2, ItemGroup::UniqueInstance, 1, 1, 0, 0x01, 553},
            {"Gear_ShieldAttackPowerRate_Common_MK2", 2, ItemGroup::UniqueInstance, 1, 1, 0, 0x01, 314},
            {"Gear_ShieldAttackPowerRate_Rare", 2, ItemGroup::UniqueInstance, 1, 1, 0, 0x01, 555},
            {"Gear_ShieldAttackPowerRate_Rare_MK2", 2, ItemGroup::UniqueInstance, 1, 1, 0, 0x01, 314},
            {"Gear_ShieldAttackPowerRate_Uncommon", 2, ItemGroup::UniqueInstance, 1, 1, 0, 0x01, 557},
            {"Gear_ShieldAttackPowerRate_Uncommon_MK2", 2, ItemGroup::UniqueInstance, 1, 1, 0, 0x01, 314},
            {"Gear_ShieldIgnorePercentage_Common", 2, ItemGroup::UniqueInstance, 1, 1, 0, 0x01, 559},
            {"Gear_ShieldIgnorePercentage_Common_MK2", 2, ItemGroup::UniqueInstance, 1, 1, 0, 0x01, 314},
            {"Gear_ShieldIgnorePercentage_Rare", 2, ItemGroup::UniqueInstance, 1, 1, 0, 0x01, 561},
            {"Gear_ShieldIgnorePercentage_Rare_MK2", 2, ItemGroup::UniqueInstance, 1, 1, 0, 0x01, 314},
            {"Gear_ShieldIgnorePercentage_Uncommon", 2, ItemGroup::UniqueInstance, 1, 1, 0, 0x01, 563},
            {"Gear_ShieldIgnorePercentage_Uncommon_MK2", 2, ItemGroup::UniqueInstance, 1, 1, 0, 0x01, 314},
            {"HP_Potion", 5, ItemGroup::Stack, 99, 999999, 0, 0x29, -1},
            {"HP_Potion_Small", 5, ItemGroup::Stack, 99, 999999, 0, 0x01, -1},
            {"Hair_000", 21, ItemGroup::OnePerPlayer, 1, 1, 0, 0x21, -1},
            {"Hair_001", 21, ItemGroup::OnePerPlayer, 1, 1, 0, 0x01, -1},
            {"Hair_002", 21, ItemGroup::OnePerPlayer, 1, 1, 0, 0x01, -1},
            {"Hair_003", 21, ItemGroup::OnePerPlayer, 1, 1, 0, 0x01, -1},
            {"Hair_004", 21, ItemGroup::OnePerPlayer, 1, 1, 0, 0x01, -1},
            {"Hair_005", 21, ItemGroup::OnePerPlayer, 1, 1, 0, 0x01, -1},
            {"Hair_006", 21, ItemGroup::OnePerPlayer, 1, 1, 0, 0x01, -1},
            {"Hair_007", 21, ItemGroup::OnePerPlayer, 1, 1, 0, 0x01, -1},
            {"Hair_008", 21, ItemGroup::OnePerPlayer, 1, 1, 0, 0x01, -1},
            {"Hair_009", 21, ItemGroup::OnePerPlayer, 1, 1, 0, 0x01, -1},
            {"Hair_010", 21, ItemGroup::OnePerPlayer, 1, 1, 0, 0x01, -1},
            {"Hair_011", 21, ItemGroup::OnePerPlayer, 1, 1, 0, 0x01, -1},
            {"Hair_012", 21, ItemGroup::OnePerPlayer, 1, 1, 0, 0x01, -1},
            {"Hair_Christmas_01", 21, ItemGroup::OnePerPlayer, 1, 1, 0, 0x11, 315},
            {"Hair_Nier_001", 21, ItemGroup::Gated, 0, 1, 0, 0x10, -1},
            {"Hair_Nier_002", 21, ItemGroup::Gated, 0, 1, 0, 0x10, -1},
            {"Hair_Nier_003", 21, ItemGroup::Gated, 0, 1, 0, 0x10, -1},
            {"Hair_Nikke_01", 21, ItemGroup::Gated, 0, 1, 0, 0x10, -1},
            {"Hair_Nikke_02", 21, ItemGroup::Gated, 0, 1, 0, 0x10, -1},
            {"Hair_Nikke_03", 21, ItemGroup::Gated, 0, 1, 0, 0x10, -1},
            {"Hair_Nikke_04", 21, ItemGroup::Gated, 0, 1, 0, 0x10, -1},
            {"Hair_Nikke_05", 21, ItemGroup::Gated, 0, 1, 0, 0x10, -1},
            {"Hair_Nikke_06", 21, ItemGroup::Gated, 0, 1, 0, 0x10, -1},
            {"Hair_ShortTail", 0, ItemGroup::OnePerPlayer, 1, 1, 0, 0x22, -1},
            {"HealGrenade", 5, ItemGroup::Stack, 99, 999999, 0, 0x01, -1},
            {"HighDensityWafer", 10, ItemGroup::Stack, 99, 999999, 0, 0x01, -1},
            {"Item_Fish_Slice_Bait", 19, ItemGroup::Stack, 99, 999999, 0, 0x21, -1},
            {"Item_Lure_Megabait", 19, ItemGroup::Stack, 99, 999999, 0, 0x09, -1},
            {"Item_Lure_Weird", 19, ItemGroup::Stack, 99, 999999, 0, 0x01, -1},
            {"Item_Records_ATL_Memory_04", 30, ItemGroup::OnePerPlayer, 1, 1, 0, 0x32, -1},
            {"Item_Records_DED40_Memory_11", 30, ItemGroup::OnePerPlayer, 1, 1, 0, 0x12, -1},
            {"Item_Records_Day1_Memory_02", 30, ItemGroup::OnePerPlayer, 1, 1, 0, 0x12, -1},
            {"Item_Records_Day1_Memory_03", 30, ItemGroup::OnePerPlayer, 1, 1, 0, 0x12, -1},
            {"Item_Records_ETC_Memory_08", 30, ItemGroup::OnePerPlayer, 1, 1, 0, 0x12, -1},
            {"Item_Records_ETC_Memory_10", 30, ItemGroup::OnePerPlayer, 1, 1, 0, 0x12, -1},
            {"Item_Records_ETC_Memory_12", 30, ItemGroup::OnePerPlayer, 1, 1, 0, 0x12, -1},
            {"Item_Records_ME01_Memory_07", 30, ItemGroup::OnePerPlayer, 1, 1, 0, 0x12, -1},
            {"Item_Records_ME04_Memory_15", 30, ItemGroup::OnePerPlayer, 1, 1, 0, 0x12, -1},
            {"Item_Records_SE06_Memory_11", 30, ItemGroup::OnePerPlayer, 1, 1, 0, 0x12, -1},
            {"Item_Records_WLA_Memory_29", 30, ItemGroup::OnePerPlayer, 1, 1, 0, 0x12, -1},
            {"Item_Records_WLA_Memory_31", 30, ItemGroup::OnePerPlayer, 1, 1, 0, 0x12, -1},
            {"Item_Records_WLA_Memory_34", 30, ItemGroup::OnePerPlayer, 1, 1, 0, 0x12, -1},
            {"Item_Records_WLB_Memory_40", 30, ItemGroup::OnePerPlayer, 1, 1, 0, 0x1A, -1},
            {"Item_Records_WLB_Memory_41", 30, ItemGroup::OnePerPlayer, 1, 1, 0, 0x1A, -1},
            {"Item_Records_Xion_Memory_01", 30, ItemGroup::OnePerPlayer, 1, 1, 0, 0x12, -1},
            {"Item_Records_Xion_Memory_03", 30, ItemGroup::OnePerPlayer, 1, 1, 0, 0x1A, -1},
            {"Item_Records_Xion_Memory_04", 30, ItemGroup::OnePerPlayer, 1, 1, 0, 0x12, -1},
            {"Item_Records_Xion_Memory_05", 30, ItemGroup::OnePerPlayer, 1, 1, 0, 0x12, -1},
            {"Item_Records_Xion_Memory_06", 30, ItemGroup::OnePerPlayer, 1, 1, 0, 0x12, -1},
            {"Item_Records_Xion_Memory_07", 30, ItemGroup::OnePerPlayer, 1, 1, 0, 0x12, -1},
            {"Item_Records_Xion_Memory_08", 30, ItemGroup::OnePerPlayer, 1, 1, 0, 0x12, -1},
            {"Item_Records_Xion_Memory_16", 30, ItemGroup::OnePerPlayer, 1, 1, 0, 0x12, -1},
            {"Item_Records_Xion_Memory_17", 30, ItemGroup::OnePerPlayer, 1, 1, 0, 0x12, -1},
            {"Item_Records_Xion_Memory_18", 30, ItemGroup::OnePerPlayer, 1, 1, 0, 0x12, -1},
            {"Item_Records_Xion_Memory_21", 30, ItemGroup::OnePerPlayer, 1, 1, 0, 0x12, -1},
            {"Item_Records_Xion_Memory_22", 30, ItemGroup::OnePerPlayer, 1, 1, 0, 0x12, -1},
            {"Item_Records_Xion_Memory_23", 30, ItemGroup::OnePerPlayer, 1, 1, 0, 0x12, -1},
            {"Item_Records_Xion_Memory_24", 30, ItemGroup::OnePerPlayer, 1, 1, 0, 0x12, -1},
            {"Item_Records_Xion_Memory_25", 30, ItemGroup::OnePerPlayer, 1, 1, 0, 0x12, -1},
            {"Item_Records_Xion_Memory_29", 30, ItemGroup::OnePerPlayer, 1, 1, 0, 0x12, -1},
            {"Item_Shrimp_Bait", 19, ItemGroup::Stack, 99, 999999, 0, 0x01, -1},
            {"Item_Special_Bait", 19, ItemGroup::Stack, 99, 999999, 0, 0x01, -1},
            {"Item_Worm_Bait", 19, ItemGroup::Stack, 99, 999999, 0, 0x01, -1},
            {"LilyCostume_001", 26, ItemGroup::OnePerPlayer, 1, 1, 0, 0x21, -1},
            {"LilyCostume_002", 26, ItemGroup::Gated, 0, 1, 0, 0x00, -1},
            {"LilyCostume_003", 26, ItemGroup::OnePerPlayer, 1, 1, 0, 0x01, 632},
            {"LilyCostume_003_Var2", 26, ItemGroup::OnePerPlayer, 1, 1, 0, 0x01, 314},
            {"LilyCostume_004", 26, ItemGroup::OnePerPlayer, 1, 1, 0, 0x01, 634},
            {"LilyCostume_004_Var2", 26, ItemGroup::OnePerPlayer, 1, 1, 0, 0x01, 314},
            {"LilyCostume_Nier_001", 26, ItemGroup::Gated, 0, 1, 0, 0x10, -1},
            {"LowDensityWafer", 10, ItemGroup::Stack, 99, 999999, 0, 0x01, -1},
            {"Money_JunkIron_A", 20, ItemGroup::Currency, 9999, 999999, 0, 0x12, -1},
            {"Money_JunkIron_B", 20, ItemGroup::Currency, 9999, 999999, 0, 0x12, -1},
            {"Money_JunkIron_C", 20, ItemGroup::Currency, 9999, 999999, 0, 0x12, -1},
            {"Money_Nier", 20, ItemGroup::Gated, 0, 15, 0, 0x00, -1},
            {"Money_Nikke", 20, ItemGroup::Gated, 0, 10, 0, 0x00, -1},
            {"Nikke_AR", 20, ItemGroup::Gated, 0, 1, 0, 0x10, -1},
            {"Nikke_LP8", 0, ItemGroup::Gated, 0, 1, 0, 0x00, -1},
            {"Nikke_PhotomodeSitcker_Dororong", 20, ItemGroup::Gated, 0, 1, 0, 0x00, -1},
            {"PT_Burst", 3, ItemGroup::UniqueInstance, 1, 1, 0, 0x31, 646},
            {"PT_Burst_MK2", 3, ItemGroup::UniqueInstance, 1, 1, 0, 0x11, 314},
            {"PT_Combo", 3, ItemGroup::UniqueInstance, 1, 1, 0, 0x11, 648},
            {"PT_Combo_MK2", 3, ItemGroup::UniqueInstance, 1, 1, 0, 0x11, 314},
            {"PT_Crowd", 3, ItemGroup::UniqueInstance, 1, 1, 0, 0x11, 650},
            {"PT_Crowd_MK2", 3, ItemGroup::UniqueInstance, 1, 1, 0, 0x11, 314},
            {"PT_Down", 3, ItemGroup::UniqueInstance, 1, 1, 0, 0x11, 652},
            {"PT_Down_MK2", 3, ItemGroup::UniqueInstance, 1, 1, 0, 0x11, 314},
            {"PT_Grenade", 3, ItemGroup::UniqueInstance, 1, 1, 0, 0x11, 654},
            {"PT_Grenade_MK2", 3, ItemGroup::UniqueInstance, 1, 1, 0, 0x11, 314},
            {"PT_Guard", 3, ItemGroup::UniqueInstance, 1, 1, 0, 0x11, 656},
            {"PT_Guard_MK2", 3, ItemGroup::UniqueInstance, 1, 1, 0, 0x11, 314},
            {"PT_Recovery", 3, ItemGroup::UniqueInstance, 1, 1, 0, 0x11, 658},
            {"PT_Recovery_MK2", 3, ItemGroup::UniqueInstance, 1, 1, 0, 0x11, 314},
            {"PT_Shoot", 3, ItemGroup::UniqueInstance, 1, 1, 0, 0x11, 660},
            {"PT_Shoot_MK2", 3, ItemGroup::UniqueInstance, 1, 1, 0, 0x11, 314},
            {"PT_Skill", 3, ItemGroup::UniqueInstance, 1, 1, 0, 0x11, 662},
            {"PT_Skill_MK2", 3, ItemGroup::UniqueInstance, 1, 1, 0, 0x11, 314},
            {"PT_Stab", 3, ItemGroup::UniqueInstance, 1, 1, 0, 0x11, 664},
            {"PT_Stab_MK2", 3, ItemGroup::UniqueInstance, 1, 1, 0, 0x11, 314},
            {"PT_Survive", 3, ItemGroup::UniqueInstance, 1, 1, 0, 0x11, 666},
            {"PT_Survive_MK2", 3, ItemGroup::UniqueInstance, 1, 1, 0, 0x11, 314},
            {"PT_Tachy", 3, ItemGroup::UniqueInstance, 1, 1, 0, 0x11, 668},
            {"PT_Tachy_MK2", 3, ItemGroup::UniqueInstance, 1, 1, 0, 0x11, 314},
            {"PolymerOrganicFilm", 10, ItemGroup::Stack, 99, 999999, 0, 0x01, -1},
            {"PulseGrenade", 16, ItemGroup::Stack, 99, 999999, 0, 0x11, -1},
            {"Recovery_HP_Potion", 12, ItemGroup::StatCapped, 99, 999999, 87, 0x21, -1},
            {"ResurrectionItem", 15, ItemGroup::Stack, 99, 999999, 0, 0x39, -1},
            {"SPInitializer", 17, ItemGroup::Stack, 99, 999999, 0, 0x31, -1},
            {"TrapGrenade", 16, ItemGroup::Stack, 99, 999999, 0, 0x01, -1},
            {"TumblerCore", 11, ItemGroup::Stack, 99, 999999, 0, 0x02, -1},
            {"TurntableMusicBundle", 0, ItemGroup::OnePerPlayer, 1, 1, 0, 0x02, -1},
            {"TurntableMusicBundle2", 0, ItemGroup::OnePerPlayer, 1, 1, 0, 0x02, -1},
            {"WeaponCore", 11, ItemGroup::Stack, 99, 999999, 0, 0x12, -1},
            {"WeaponCore_Damaged", 11, ItemGroup::Stack, 99, 999999, 0, 0x02, -1},
        }};
        // C8: one self-check sentinel per family (item category), by row index.
        constexpr std::array<std::uint16_t, 25> kSentinelItems{{
            589, // Hair_ShortTail
            136, // BetaCrystal
            408, // Gear_AdditiveBetaSkillDamage_Common
            645, // PT_Burst
            9, // BS_01
            564, // HP_Potion
            0, // 2DQuantumWafer
            135, // BetaCore
            671, // Recovery_HP_Potion
            138, // Bullet_Explosive
            672, // ResurrectionItem
            193, // ConcussionGrenade
            673, // SPInitializer
            361, // Fish_Arowana
            592, // Item_Fish_Slice_Bait
            314, // ETC_Item_VendingMachineCoin
            566, // Hair_000
            341, // FaceAccessory_001
            316, // Earring_001
            194, // DesignPattern_BS_01
            144, // Can_001
            629, // LilyCostume_001
            1, // AdamCostume_001
            304, // DroneSeal_001
            595, // Item_Records_ATL_Memory_04
        }};
        // ---- end of generated allowlist ------------------------------------
        constexpr bool item_group_addable(ItemGroup group)
        {
            return group == ItemGroup::Stack || group == ItemGroup::StatCapped || group == ItemGroup::OnePerPlayer
                || group == ItemGroup::UniqueInstance || group == ItemGroup::Money || group == ItemGroup::Currency;
        }

        constexpr std::uint32_t group_per_add_max(ItemGroup group)
        {
            switch (group)
            {
            case ItemGroup::Stack:
            case ItemGroup::StatCapped: return kMaxStackQuantity;
            case ItemGroup::OnePerPlayer:
            case ItemGroup::UniqueInstance: return 1;
            case ItemGroup::Money: return kMaxMoneyQuantity;
            case ItemGroup::Currency: return kMaxCurrencyQuantity;
            case ItemGroup::Gated:
            case ItemGroup::WatchOnly: return 0;
            }
            return 0;
        }

        // Compile-time proof that the generated list keeps the policy the
        // generator validated: sorted and unique (binary search), no
        // hard-denied category, per-add maxima exactly the group's, money only
        // as BetaCrystal with its 100,000,000 cap, unique instances only in
        // the unique-instance categories, carry stats only on stat-capped
        // rows, replacement targets in range, and one sentinel per category.
        constexpr bool allowlist_is_valid()
        {
            std::size_t addable = 0;
            std::size_t gated = 0;
            for (std::size_t index = 0; index < kAllowedItems.size(); ++index)
            {
                const AllowedItem& item = kAllowedItems[index];
                if (item.alias.empty() || item.alias.size() >= 129) return false;
                if (index > 0 && !(kAllowedItems[index - 1].alias < item.alias)) return false;
                if (item.category >= kCategoryCount || category_hard_denied(item.category)) return false;
                if (item.per_add_max != group_per_add_max(item.group) || item.game_max <= 0) return false;
                if ((item.group == ItemGroup::UniqueInstance) != (item_group_addable(item.group)
                                                                  && category_is_unique_instance(item.category)))
                {
                    return false;
                }
                if (item.group == ItemGroup::UniqueInstance && item.game_max != 1) return false;
                if ((item.group == ItemGroup::Money)
                    != (item.alias == std::string_view("BetaCrystal") && item_group_addable(item.group)))
                {
                    return false;
                }
                if (item.group == ItemGroup::Money
                    && (item.game_max != kMoneyGameMax || item.category != kCategoryBetaCrystal))
                {
                    return false;
                }
                if ((item.stat != 0) != (item.group == ItemGroup::StatCapped)) return false;
                if (item.replacement < -1 || item.replacement >= static_cast<std::int32_t>(kAllowedItems.size())
                    || item.replacement == static_cast<std::int32_t>(index))
                {
                    return false;
                }
                if (item_group_addable(item.group)) ++addable;
                if (item.group == ItemGroup::Gated) ++gated;
            }
            if (addable != kAllowlistAddableCount || gated != kAllowlistGatedCount) return false;
            bool seen[kCategoryCount]{};
            for (const std::uint16_t sentinel : kSentinelItems)
            {
                if (sentinel >= kAllowedItems.size()) return false;
                const AllowedItem& item = kAllowedItems[sentinel];
                if (!item_group_addable(item.group) || (item.flags & kItemFlagSentinel) == 0 || seen[item.category])
                {
                    return false;
                }
                seen[item.category] = true;
            }
            for (const AllowedItem& item : kAllowedItems)
            {
                if (item_group_addable(item.group) && !seen[item.category]) return false;
            }
            return true;
        }
        static_assert(allowlist_is_valid(), "the generated item allowlist breaks the v0.5 policy");

        // C6: the watch set of one add: the sentinels plus the item's
        // replacement target.
        constexpr std::size_t kMaxWatch = 40;
        static_assert(kSentinelItems.size() + 1 <= kMaxWatch);

        // Binary search over the generated, sorted list. Exact (case-sensitive) names only.
        const AllowedItem* find_allowed_item(std::string_view alias)
        {
            const auto found = std::lower_bound(
                kAllowedItems.begin(), kAllowedItems.end(), alias,
                [](const AllowedItem& item, std::string_view name) { return item.alias < name; });
            if (found == kAllowedItems.end() || found->alias != alias) return nullptr;
            return &*found;
        }

        std::uint16_t allowed_item_index(const AllowedItem* item)
        {
            return static_cast<std::uint16_t>(item - kAllowedItems.data());
        }

        const char* item_group_name(ItemGroup group)
        {
            switch (group)
            {
            case ItemGroup::Stack: return "stack";
            case ItemGroup::StatCapped: return "stat_capped";
            case ItemGroup::OnePerPlayer: return "one_per_player";
            case ItemGroup::UniqueInstance: return "unique_instance";
            case ItemGroup::Money: return "money";
            case ItemGroup::Currency: return "currency";
            case ItemGroup::Gated: return "gated";
            case ItemGroup::WatchOnly: return "watch_only";
            }
            return "unknown";
        }

        // Certified for SB-Win64-Shipping.exe SHA-256
        // 573AAFF1C9455F85EA6036EF6F6CCB0774DE4164722A296276FBBFC7FA87545C
        // (Steam update of 2026-08-12). Every RVA and byte image below was
        // re-derived and verified against that file; see
        // tools/verify_live_add_offline.py and
        // SupportReports/LIVE_ADD_OFFLINE_EXE_VERIFICATION.json.
        constexpr std::uint32_t kExpectedTimestamp = 0x6A6A3B74;
        constexpr std::uint32_t kExpectedImageSize = 0x15981000;
        constexpr std::uint64_t kExpectedExecutableFileSize = 359'186'432;
        constexpr std::array<std::uint8_t, 32> kExpectedExecutableSha256{
            0x57, 0x3A, 0xAF, 0xF1, 0xC9, 0x45, 0x5F, 0x85,
            0xEA, 0x60, 0x36, 0xEF, 0x6F, 0x6C, 0xCB, 0x07,
            0x74, 0xDE, 0x41, 0x64, 0x72, 0x2A, 0x29, 0x62,
            0x76, 0xFB, 0xBF, 0xC7, 0xFA, 0x87, 0x54, 0x5C,
        };
        // Certified UE4SS.dll SHA-256:
        // F3F0229E8D046824C6D71DB256F1C9BBBDA9652A193643C28FA4E6C329E17670.
        constexpr std::uint32_t kExpectedUe4ssTimestamp = 0x685AC0B6;
        constexpr std::uint32_t kExpectedUe4ssImageSize = 0x01780000;
        constexpr std::uint64_t kExpectedUe4ssFileSize = 24'511'488;
        constexpr std::array<std::uint8_t, 32> kExpectedUe4ssSha256{
            0xF3, 0xF0, 0x22, 0x9E, 0x8D, 0x04, 0x68, 0x24,
            0xC6, 0xD7, 0x1D, 0xB2, 0x56, 0xF1, 0xC9, 0xBB,
            0xBD, 0xA9, 0x65, 0x2A, 0x19, 0x36, 0x43, 0xC2,
            0x8F, 0xA4, 0xE6, 0xC3, 0x29, 0xE1, 0x76, 0x70,
        };
        // This module's certification and sbcore's gate name the same build.
        static_assert(kExpectedTimestamp == sbcore::target::kTimestamp);
        static_assert(kExpectedImageSize == sbcore::target::kImageSize);
        static_assert(kExpectedExecutableFileSize == sbcore::target::kFileSize);
        static_assert(kExpectedExecutableSha256 == sbcore::target::kSha256);

        // TaskGraph set; identical to the live-proven SBMovementNative 1.3.6.
        // sbcore::dispatch builds the task; the byte images stay in this
        // module's manifest so its gate is never weaker than v0.3.1's.
        constexpr std::uintptr_t kCreateTaskRva = 0x112FA40;
        constexpr std::uintptr_t kSetupTaskRva = 0x112F670;
        constexpr std::uintptr_t kTaskVtableRva = 0x599C7D8;
        constexpr std::uintptr_t kTaskDestructorRva = 0x112F8A0;
        constexpr std::uintptr_t kTaskExecuteRva = 0x112F910;
        constexpr std::uintptr_t kGameThreadIdRva = 0x706B538;
        constexpr std::uintptr_t kGameThreadIdInitializerRva = 0xE36F95;
        static_assert(kCreateTaskRva == sbcore::taskgraph::kCreateTaskRva);
        static_assert(kSetupTaskRva == sbcore::taskgraph::kSetupTaskRva);
        static_assert(kTaskVtableRva == sbcore::taskgraph::kTaskVtableRva);
        static_assert(kTaskDestructorRva == sbcore::taskgraph::kTaskDestructorRva);
        static_assert(kTaskExecuteRva == sbcore::taskgraph::kTaskExecuteRva);
        static_assert(kGameThreadIdRva == sbcore::taskgraph::kGameThreadIdRva);
        static_assert(kGameThreadIdInitializerRva == sbcore::taskgraph::kGameThreadInitializerRva);

        // Inventory route. The three singletons are read directly and must be
        // non-null before any game function that would otherwise lazily create
        // them is called, so this module never triggers a game allocation.
        constexpr std::uintptr_t kBucketSingletonRva = 0x7032570;        // local client cache
        constexpr std::uintptr_t kLocalClientGetterRva = 0x1A97C40;
        constexpr std::size_t kLocalClientAllocationSize = 0x2230;
        constexpr std::uintptr_t kItemTableSingletonRva = 0x7032510;     // read by GetItemCountByAlias
        constexpr std::uintptr_t kItemTableGetterRva = 0x1A97F20;
        constexpr std::uintptr_t kItemTableGetterFastPathRva = 0x1A9807E;
        constexpr std::uintptr_t kAddSubsystemSingletonRva = 0x7032560;  // read by the add implementation
        constexpr std::uintptr_t kAddSubsystemGetterRva = 0x1A97B90;
        constexpr std::uintptr_t kAddSubsystemGetterFastPathRva = 0x1A97C32;
        constexpr std::uintptr_t kPrimaryBucketLookupRva = 0x1CC1090;
        constexpr std::uintptr_t kFindInventoryBucketRva = 0x1CC1110;
        constexpr std::uintptr_t kCurrentTargetGuidRva = 0x1CC2590;
        // 0x1C3E6C0 is the certified function; the byte-identical twin at
        // 0x1C3F610 differs in its callee displacements and is rejected by the
        // exact whole-function image below.
        constexpr std::uintptr_t kGetItemCountByAliasRva = 0x1C3E6C0;
        constexpr std::uintptr_t kFNameFromWideRva = 0x2938950;
        constexpr std::uintptr_t kNoneFNameIndexRva = 0x7012C80;
        constexpr std::uintptr_t kServerItemBucketAddRva = 0x23BA0C0;
        constexpr std::uintptr_t kRpcInstanceConverterRva = 0x1B980F0;
        constexpr std::uintptr_t kAlwaysTrueValidateRva = 0xE340E0;
        // Controller vtable: slot +0x13E0 = _Validate, +0x13E8 = _Implementation.
        // The exec thunk registered for "ServerRequest_ItemBucketItemAdd" calls
        // exactly these two slots.
        constexpr std::uintptr_t kControllerVtableRva = 0x5CC6798;
        constexpr std::size_t kServerAddValidateSlotOffset = 0x13E0;
        constexpr std::size_t kServerAddImplementationSlotOffset = 0x13E8;

        // v0.3.1 carry limit and diagnostics (see tools/verify_live_add_offline.py).
        // FindItemRow(item_table, unused, const FName*): the row lookup that
        // GetItemCountByAlias (0x1C3E6E1) and the client carry-limit function
        // call. rdx is overwritten before any use in it and in its callee.
        constexpr std::uintptr_t kItemRowLookupRva = 0x1A9A960;
        // Client carry limit (not called): row MaxAmount, or the current
        // target's actor stat [entry+0x118+stat*4] when the row names one.
        // Its gated image proves the row and stat offsets below.
        constexpr std::uintptr_t kItemMaxAmountRva = 0x1CC3630;
        // Server add (not called), two gated fragments: the ValidConditionGroup
        // and use-on-pickup checks, and the carry clamp
        // (max != 0 && cur + n > max: max <= cur adds nothing, else n = max - cur).
        constexpr std::uintptr_t kServerAddChecksRva = 0x1BDAABD;
        constexpr std::uintptr_t kServerAddClampRva = 0x1BDAD37;
        // Server-frame request queue (read only, for the status): getter,
        // global, and the enqueue step of the RPC implementation that keys
        // the queued add by the frame index at queue+0x14.
        constexpr std::uintptr_t kRequestQueueGetterRva = 0x1A97B20;
        constexpr std::uintptr_t kRequestQueueSingletonRva = 0x7032568;
        constexpr std::uintptr_t kRequestEnqueueRva = 0x1AF8DF0;
        constexpr std::size_t kRequestQueueFrameOffset = 0x14;
        // FSBItemTableProperty fields as read by the gated code above.
        constexpr std::size_t kItemTableAllocationSize = 0x28;
        constexpr std::size_t kItemRowSpan = 0x1B4;
        constexpr std::size_t kItemRowInventoryAliasOffset = 0x14;   // FName
        constexpr std::size_t kItemRowCategoryOffset = 0x70;         // uint8
        // v0.5.1: int32 StackAmount (1: one bag entry per unit). The server add
        // path never reads it (verify_live_add_offline: server_add_per_unit_rows_merge).
        constexpr std::size_t kItemRowStackAmountOffset = 0x80;
        constexpr std::size_t kItemRowMaxAmountOffset = 0x84;        // int32
        constexpr std::size_t kItemRowMaxAmountStatOffset = 0x88;    // uint8 ESBActorStatType
        constexpr std::size_t kItemRowUseOnPickupOffset = 0x134;     // bool InteractionImmidateUse
        // uint8 ESBCharacterLevelType AutoCharacterLevelUpType. The server add's
        // post-add hook 0x1BDCA30 reads it (0x1BDD13E) and, when the new count
        // meets the next CharacterLevelTable row, levels the player up through
        // 0x1BB9660/0x1BB9A40, which removes the required items (0x1BDE8C0).
        constexpr std::size_t kItemRowAutoLevelUpTypeOffset = 0x188;
        constexpr std::size_t kItemRowConditionGroupOffset = 0x1AC;  // FName ValidConditionGroup
        constexpr std::size_t kTargetEntryStatArrayOffset = 0x118;   // float[ESBActorStatType]
        constexpr float kMaxPlausibleCarryLimit = 100'000'000.0F;

        constexpr std::size_t kLocalClientInventoryManagerOffset = 0xE8;
        constexpr std::size_t kBucketGuidOffset = 0x30;
        constexpr std::size_t kBucketTypeOffset = 0x34;
        constexpr std::size_t kBucketTargetGuidOffset = 0x38;
        // CurrentTargetGuid (0x1CC2590, byte-gated whole body) reads
        // holder = [client+0xC8]; index = int32 [holder+0x3C]; it returns 0
        // unless 0 <= index < int32 [holder+0x30]; entry = [[holder+0x28] +
        // index*8]; then it tail-calls [[entry+0x10]+0x38](entry+0x10). The
        // chain is re-read here before every call so that virtual call can
        // only land on executable code inside the certified image.
        constexpr std::size_t kLocalClientTargetHolderOffset = 0xC8;
        constexpr std::size_t kTargetHolderArrayOffset = 0x28;
        constexpr std::size_t kTargetHolderCountOffset = 0x30;
        constexpr std::size_t kTargetHolderIndexOffset = 0x3C;
        constexpr std::size_t kTargetEntryInterfaceOffset = 0x10;
        constexpr std::size_t kTargetInterfaceGuidSlotOffset = 0x38;
        constexpr std::int32_t kMaxTargetHolderCount = 1 << 20;
        constexpr std::uint32_t kInventoryBucketType = 1;
        constexpr std::size_t kRpcItemInstanceSize = 0x80;
        constexpr std::size_t kServerAddParamsSize = 0xA0;

        // Inventory manager map headers, exactly as read by the byte-gated
        // PrimaryBucketLookup (0x1CC1090) and FindInventoryBucket (0x1CC1110).
        struct SparseMapLayout
        {
            const char* name;
            std::size_t data;
            std::size_t num;
            std::size_t max;
            std::size_t num_free;
            std::size_t hash_inline;
            std::size_t hash_heap;
            std::size_t hash_size;
            std::size_t element_stride;
        };
        constexpr SparseMapLayout kPrimaryBucketMap{
            "primary_bucket_map", 0x08, 0x10, 0x14, 0x3C, 0x40, 0x48, 0x50, 0x18};
        constexpr SparseMapLayout kTypeTargetMap{
            "type_target_map", 0x58, 0x60, 0x64, 0x8C, 0x90, 0x98, 0xA0, 0x60};
        constexpr std::int32_t kMaxSparseMapEntries = 1 << 20;

        // UE4CodeGen reflection records (static image data). Offsets are
        // relative to each record's NameUTF8 field.
        constexpr std::uintptr_t kRpcStructParamsNameFieldRva = 0x6DB1B78;
        constexpr std::uintptr_t kRpcStructNameRva = 0x5E6DAD0;
        constexpr std::uintptr_t kServerAddFunctionParamsNameFieldRva = 0x6DB8840;
        constexpr std::uintptr_t kServerAddFunctionNameRva = 0x5EA53C8;
        constexpr std::size_t kStructParamsSizeOfField = 0x08;
        constexpr std::size_t kStructParamsAlignOfField = 0x10;
        constexpr std::size_t kStructParamsPropertyArrayField = 0x18;
        constexpr std::size_t kStructParamsNumPropertiesField = 0x20;
        constexpr std::size_t kFunctionParamsStructureSizeField = 0x18;
        constexpr std::size_t kFunctionParamsPropertyArrayField = 0x20;
        constexpr std::size_t kFunctionParamsNumPropertiesField = 0x28;
        constexpr std::size_t kPropertyGenFlagsField = 0x18;
        constexpr std::size_t kPropertyArrayDimField = 0x20;
        constexpr std::size_t kPropertyOffsetField = 0x24;          // generic properties
        constexpr std::size_t kBoolPropertyElementSizeField = 0x24; // bool properties
        constexpr std::size_t kBoolPropertySizeOfOuterField = 0x28; // bool properties
        constexpr std::uint32_t kGenFlagsBool = 0x2C;

        struct ExpectedProperty
        {
            const char* name;
            std::uint32_t gen_flags;
            std::uint32_t offset; // ignored for bool properties
        };
        constexpr std::array<ExpectedProperty, 17> kRpcStructProperties{{
            {"SavedGuid", 0x19, 0x00},
            {"PocketGuid", 0x19, 0x10},
            {"ItemAlias", 0x14, 0x20},
            {"StatLevel", 0x06, 0x28},
            {"ItemCount", 0x06, 0x2C},
            {"ItemChargeCount", 0x06, 0x30},
            {"Equiped", kGenFlagsBool, 0},
            {"GearType", 0x00, 0x35},
            {"MatVarIndex", 0x03, 0x38},
            {"EquipStatAliasKeyArray", 0x03, 0x00},
            {"EquipStatAliasKeyArray", 0x16, 0x40},
            {"EquipStatAliasValueArray", 0x14, 0x00},
            {"EquipStatAliasValueArray", 0x16, 0x50},
            {"EquipStatRangeKeyArray", 0x03, 0x00},
            {"EquipStatRangeKeyArray", 0x16, 0x60},
            {"EquipStatRangeValueArray", 0x03, 0x00},
            {"EquipStatRangeValueArray", 0x16, 0x70},
        }};
        constexpr std::array<ExpectedProperty, 9> kServerAddParameters{{
            {"InType", 0x00, 0x00},
            {"InTargetGUID", 0x06, 0x04},
            {"InItemAlias", 0x14, 0x08},
            {"InItemCount", 0x06, 0x10},
            {"inStatLevel", 0x06, 0x14},
            {"bInNotifyUI", kGenFlagsBool, 0},
            {"bNotifyEnhanceUI", kGenFlagsBool, 0},
            {"bInEventLoad", kGenFlagsBool, 0},
            {"InItemInstance", 0x19, 0x20},
        }};

        // RVA 0x112FA40, 64 bytes. FGraphEventRef-style CreateTask entry (as SBMovementNative 1.3.6).
        constexpr std::array<std::uint8_t, 64> kCreateTaskSignature{
            0x48, 0x89, 0x5C, 0x24, 0x10, 0x48, 0x89, 0x6C,
            0x24, 0x20, 0x56, 0x57, 0x41, 0x54, 0x41, 0x56,
            0x41, 0x57, 0x48, 0x83, 0xEC, 0x20, 0x45, 0x33,
            0xE4, 0x45, 0x8B, 0xF8, 0x48, 0x8B, 0xEA, 0x48,
            0x8B, 0xF1, 0x48, 0x85, 0xD2, 0x74, 0x06, 0x44,
            0x8B, 0x72, 0x28, 0xEB, 0x03, 0x45, 0x8B, 0xF4,
            0x8B, 0x0D, 0x2A, 0xF6, 0xE4, 0x05, 0xFF, 0x15,
            0x5C, 0xDE, 0x47, 0x04, 0x48, 0x8B, 0xD8, 0x48,
        };
        // RVA 0x112F670, 42 bytes. TGraphTask setup/dispatch entry.
        constexpr std::array<std::uint8_t, 42> kSetupTaskSignature{
            0x4C, 0x8B, 0xDC, 0x45, 0x88, 0x4B, 0x20, 0x45,
            0x89, 0x43, 0x18, 0x49, 0x89, 0x4B, 0x08, 0x56,
            0x48, 0x81, 0xEC, 0xB0, 0x00, 0x00, 0x00, 0x4D,
            0x89, 0x7B, 0xC0, 0x48, 0x8B, 0xF1, 0x4C, 0x8B,
            0xFA, 0xC6, 0x41, 0x60, 0x01, 0x8B, 0x41, 0x50,
            0x33, 0xD2,
        };
        // RVA 0x112F910, 36 bytes. Task vtable slot 1 (execute); anchored by the vtable check.
        constexpr std::array<std::uint8_t, 36> kExecuteTaskSignature{
            0x48, 0x89, 0x5C, 0x24, 0x08, 0x48, 0x89, 0x74,
            0x24, 0x10, 0x57, 0x48, 0x83, 0xEC, 0x20, 0x48,
            0x8B, 0xF9, 0x41, 0x8B, 0xD8, 0x48, 0x8B, 0x49,
            0x20, 0x48, 0x8B, 0xF2, 0x48, 0x85, 0xC9, 0x75,
            0x04, 0x48, 0x8D, 0x4F,
        };
        // RVA 0x112F8A0, 102 bytes. Task vtable slot 0 (deleting destructor), whole function.
        constexpr std::array<std::uint8_t, 102> kTaskDestructorSignature{
            0x48, 0x89, 0x5C, 0x24, 0x08, 0x57, 0x48, 0x83,
            0xEC, 0x20, 0x48, 0x8D, 0x05, 0x27, 0xCF, 0x86,
            0x04, 0x48, 0x8B, 0xD9, 0x48, 0x89, 0x01, 0x8B,
            0xFA, 0x48, 0x8B, 0x49, 0x68, 0x48, 0x85, 0xC9,
            0x74, 0x05, 0xE8, 0x99, 0xA0, 0xD1, 0xFF, 0x48,
            0x8D, 0x05, 0x12, 0x4D, 0x7F, 0x04, 0x48, 0x89,
            0x03, 0x40, 0xF6, 0xC7, 0x01, 0x74, 0x21, 0x48,
            0x8B, 0x0D, 0x22, 0xBC, 0xF3, 0x05, 0x48, 0x85,
            0xC9, 0x75, 0x0C, 0xE8, 0xC8, 0x5A, 0x70, 0x01,
            0x48, 0x8B, 0x0D, 0x11, 0xBC, 0xF3, 0x05, 0x48,
            0x8B, 0x01, 0x48, 0x8B, 0xD3, 0xFF, 0x50, 0x30,
            0x48, 0x8B, 0xC3, 0x48, 0x8B, 0x5C, 0x24, 0x30,
            0x48, 0x83, 0xC4, 0x20, 0x5F, 0xC3,
        };
        // RVA 0xE36F95, 12 bytes. call [GetCurrentThreadId IAT 0x55AD878]; mov [0x706B538], eax.
        constexpr std::array<std::uint8_t, 12> kGameThreadIdInitializerSignature{
            0xFF, 0x15, 0xDD, 0x68, 0x77, 0x04, 0x89, 0x05,
            0x97, 0x45, 0x23, 0x06,
        };
        // RVA 0x1A97C40, 97 bytes. Whole getter; fast path returns [0x7032570].
        constexpr std::array<std::uint8_t, 97> kLocalClientGetterSignature{
            0x48, 0x83, 0xEC, 0x28, 0x48, 0x8B, 0x05, 0x25,
            0xA9, 0x59, 0x05, 0x48, 0x85, 0xC0, 0x75, 0x4C,
            0x48, 0x8B, 0x0D, 0xA9, 0x38, 0x5D, 0x05, 0x48,
            0x85, 0xC9, 0x75, 0x0C, 0xE8, 0x4F, 0xD7, 0xD9,
            0x00, 0x48, 0x8B, 0x0D, 0x98, 0x38, 0x5D, 0x05,
            0x48, 0x8B, 0x01, 0x45, 0x33, 0xC0, 0xBA, 0x30,
            0x22, 0x00, 0x00, 0xFF, 0x50, 0x10, 0x48, 0x85,
            0xC0, 0x74, 0x14, 0x48, 0x8B, 0xC8, 0xE8, 0xDD,
            0xFA, 0x1F, 0x00, 0x48, 0x89, 0x05, 0xE6, 0xA8,
            0x59, 0x05, 0x48, 0x83, 0xC4, 0x28, 0xC3, 0x48,
            0xC7, 0x05, 0xD6, 0xA8, 0x59, 0x05, 0x00, 0x00,
            0x00, 0x00, 0x33, 0xC0, 0x48, 0x83, 0xC4, 0x28,
            0xC3,
        };
        // RVA 0x1A97F20, 20 bytes. Getter prologue; mov rax,[0x7032510]; test; jne fast path.
        constexpr std::array<std::uint8_t, 20> kItemTableGetterSignature{
            0x48, 0x83, 0xEC, 0x28, 0x48, 0x8B, 0x05, 0xE5,
            0xA5, 0x59, 0x05, 0x48, 0x85, 0xC0, 0x0F, 0x85,
            0x4A, 0x01, 0x00, 0x00,
        };
        // RVA 0x1A9807E, 5 bytes. add rsp,28h; ret (returns the non-null global).
        constexpr std::array<std::uint8_t, 5> kItemTableGetterFastPathSignature{
            0x48, 0x83, 0xC4, 0x28, 0xC3,
        };
        // RVA 0x1A97B90, 20 bytes. Getter prologue; mov rax,[0x7032560]; test; jne fast path.
        constexpr std::array<std::uint8_t, 20> kAddSubsystemGetterSignature{
            0x48, 0x83, 0xEC, 0x28, 0x48, 0x8B, 0x05, 0xC5,
            0xA9, 0x59, 0x05, 0x48, 0x85, 0xC0, 0x0F, 0x85,
            0x8E, 0x00, 0x00, 0x00,
        };
        // RVA 0x1A97C32, 5 bytes. add rsp,28h; ret (returns the non-null global).
        constexpr std::array<std::uint8_t, 5> kAddSubsystemGetterFastPathSignature{
            0x48, 0x83, 0xC4, 0x28, 0xC3,
        };
        // RVA 0x1CC1090, 113 bytes. Whole leaf function (no RUNTIME_FUNCTION).
        constexpr std::array<std::uint8_t, 113> kPrimaryBucketLookupSignature{
            0x8B, 0x41, 0x10, 0x45, 0x33, 0xDB, 0x3B, 0x41,
            0x3C, 0x74, 0x4E, 0x4C, 0x8B, 0x41, 0x48, 0x4C,
            0x8D, 0x51, 0x40, 0x4C, 0x63, 0x49, 0x50, 0x49,
            0xFF, 0xC9, 0x48, 0x63, 0xC2, 0x4C, 0x23, 0xC8,
            0x4D, 0x85, 0xC0, 0x4D, 0x0F, 0x45, 0xD0, 0x43,
            0x8B, 0x04, 0x8A, 0x83, 0xF8, 0xFF, 0x74, 0x29,
            0x4C, 0x8B, 0x41, 0x08, 0x0F, 0x1F, 0x40, 0x00,
            0x0F, 0x1F, 0x84, 0x00, 0x00, 0x00, 0x00, 0x00,
            0x48, 0x63, 0xC8, 0x48, 0x8D, 0x04, 0x49, 0x41,
            0x39, 0x14, 0xC0, 0x49, 0x8D, 0x0C, 0xC0, 0x74,
            0x0C, 0x8B, 0x41, 0x10, 0x83, 0xF8, 0xFF, 0x75,
            0xE7, 0x49, 0x8B, 0xC3, 0xC3, 0x48, 0x85, 0xC9,
            0x48, 0x8D, 0x41, 0x08, 0x49, 0x0F, 0x44, 0xC3,
            0x48, 0x85, 0xC0, 0x74, 0xEC, 0x48, 0x8B, 0x00,
            0xC3,
        };
        // RVA 0x1CC1110, 258 bytes. Whole function.
        constexpr std::array<std::uint8_t, 258> kFindInventoryBucketSignature{
            0x48, 0x89, 0x5C, 0x24, 0x08, 0x57, 0x8B, 0x41,
            0x60, 0x48, 0x8B, 0xD9, 0x49, 0x63, 0xF8, 0x3B,
            0x81, 0x8C, 0x00, 0x00, 0x00, 0x74, 0x53, 0x4C,
            0x63, 0x91, 0xA0, 0x00, 0x00, 0x00, 0x4C, 0x8D,
            0x99, 0x90, 0x00, 0x00, 0x00, 0x4D, 0x8B, 0x4B,
            0x08, 0x49, 0xFF, 0xCA, 0x48, 0x63, 0xC2, 0x4C,
            0x23, 0xD0, 0x4D, 0x85, 0xC9, 0x4D, 0x0F, 0x45,
            0xD9, 0x43, 0x8B, 0x04, 0x93, 0x83, 0xF8, 0xFF,
            0x74, 0x28, 0x4C, 0x8B, 0x41, 0x58, 0x66, 0x66,
            0x0F, 0x1F, 0x84, 0x00, 0x00, 0x00, 0x00, 0x00,
            0x48, 0x63, 0xC8, 0x48, 0x8D, 0x0C, 0x49, 0x48,
            0xC1, 0xE1, 0x05, 0x49, 0x03, 0xC8, 0x39, 0x11,
            0x74, 0x11, 0x8B, 0x41, 0x58, 0x83, 0xF8, 0xFF,
            0x75, 0xE6, 0x33, 0xC0, 0x48, 0x8B, 0x5C, 0x24,
            0x10, 0x5F, 0xC3, 0x45, 0x33, 0xD2, 0x4C, 0x8D,
            0x49, 0x08, 0x48, 0x85, 0xC9, 0x4D, 0x0F, 0x44,
            0xCA, 0x4D, 0x85, 0xC9, 0x74, 0xE4, 0x41, 0x8B,
            0x41, 0x08, 0x41, 0x3B, 0x41, 0x34, 0x74, 0xDA,
            0x49, 0x8B, 0x49, 0x40, 0x4D, 0x8D, 0x41, 0x38,
            0x49, 0x63, 0x51, 0x48, 0x48, 0xFF, 0xCA, 0x48,
            0x23, 0xD7, 0x48, 0x85, 0xC9, 0x4C, 0x0F, 0x45,
            0xC1, 0x41, 0x8B, 0x04, 0x90, 0x83, 0xF8, 0xFF,
            0x74, 0xB8, 0x49, 0x8B, 0x11, 0x66, 0x66, 0x66,
            0x0F, 0x1F, 0x84, 0x00, 0x00, 0x00, 0x00, 0x00,
            0x48, 0x98, 0x48, 0xC1, 0xE0, 0x04, 0x48, 0x03,
            0xC2, 0x39, 0x38, 0x74, 0x11, 0x8B, 0x40, 0x08,
            0x83, 0xF8, 0xFF, 0x75, 0xEB, 0x33, 0xC0, 0x48,
            0x8B, 0x5C, 0x24, 0x10, 0x5F, 0xC3, 0x48, 0x85,
            0xC0, 0x48, 0x8D, 0x50, 0x04, 0x49, 0x0F, 0x44,
            0xD2, 0x48, 0x85, 0xD2, 0x0F, 0x84, 0x78, 0xFF,
            0xFF, 0xFF, 0x8B, 0x12, 0x48, 0x8B, 0xCB, 0x48,
            0x8B, 0x5C, 0x24, 0x10, 0x5F, 0xE9, 0x7E, 0xFE,
            0xFF, 0xFF,
        };
        // RVA 0x1CC2590, 74 bytes. Whole function.
        constexpr std::array<std::uint8_t, 74> kCurrentTargetGuidSignature{
            0x48, 0x83, 0xEC, 0x28, 0xE8, 0xA7, 0x56, 0xDD,
            0xFF, 0x48, 0x8B, 0x80, 0xC8, 0x00, 0x00, 0x00,
            0x48, 0x85, 0xC0, 0x74, 0x2E, 0x48, 0x63, 0x48,
            0x3C, 0x85, 0xC9, 0x78, 0x0F, 0x3B, 0x48, 0x30,
            0x7D, 0x0A, 0x48, 0x8B, 0x40, 0x28, 0x48, 0x8B,
            0x0C, 0xC8, 0xEB, 0x02, 0x33, 0xC9, 0x48, 0x85,
            0xC9, 0x74, 0x10, 0x48, 0x8B, 0x41, 0x10, 0x48,
            0x83, 0xC1, 0x10, 0x48, 0x83, 0xC4, 0x28, 0x48,
            0xFF, 0x60, 0x38, 0x33, 0xC0, 0x48, 0x83, 0xC4,
            0x28, 0xC3,
        };
        // RVA 0x1C3E6C0, 753 bytes. Whole function incl. 3 chained unwind parts.
        constexpr std::array<std::uint8_t, 753> kGetItemCountByAliasSignature{
            0x48, 0x89, 0x5C, 0x24, 0x20, 0x55, 0x56, 0x41,
            0x54, 0x48, 0x8B, 0xEC, 0x48, 0x83, 0xEC, 0x70,
            0x48, 0x8B, 0xDA, 0x48, 0x8B, 0xF1, 0xE8, 0x45,
            0x98, 0xE5, 0xFF, 0x48, 0x8B, 0xC8, 0x4C, 0x8B,
            0xC3, 0xE8, 0x7A, 0xC2, 0xE5, 0xFF, 0x4C, 0x8B,
            0xC0, 0x48, 0x85, 0xC0, 0x0F, 0x84, 0xA9, 0x00,
            0x00, 0x00, 0x83, 0x7E, 0x34, 0x01, 0x48, 0x8B,
            0x13, 0x75, 0x1B, 0x8B, 0x0D, 0x7F, 0x45, 0x3D,
            0x05, 0x39, 0x48, 0x14, 0x0F, 0x95, 0xC1, 0x83,
            0x78, 0x18, 0x00, 0x0F, 0x95, 0xC0, 0x0A, 0xC8,
            0x74, 0x04, 0x49, 0x8B, 0x50, 0x14, 0x8B, 0x86,
            0x98, 0x00, 0x00, 0x00, 0x3B, 0x86, 0xC4, 0x00,
            0x00, 0x00, 0x74, 0x77, 0x44, 0x0F, 0xB7, 0xCA,
            0x4C, 0x8D, 0x9E, 0xC8, 0x00, 0x00, 0x00, 0x4D,
            0x8B, 0x53, 0x08, 0x8B, 0xC2, 0xC1, 0xE8, 0x10,
            0x45, 0x8B, 0xC1, 0x41, 0xC1, 0xE8, 0x04, 0x44,
            0x03, 0xC0, 0x41, 0x8D, 0x0C, 0xC1, 0x48, 0x8B,
            0xC2, 0x48, 0xC1, 0xE8, 0x20, 0xC1, 0xE1, 0x10,
            0x44, 0x03, 0xC1, 0x41, 0x03, 0xC0, 0x41, 0x03,
            0xC1, 0x48, 0x63, 0xC8, 0x48, 0x63, 0x86, 0xD8,
            0x00, 0x00, 0x00, 0x48, 0xFF, 0xC8, 0x48, 0x23,
            0xC8, 0x4D, 0x85, 0xD2, 0x4D, 0x0F, 0x45, 0xDA,
            0x41, 0x8B, 0x04, 0x8B, 0x83, 0xF8, 0xFF, 0x74,
            0x22, 0x4C, 0x8B, 0x86, 0x90, 0x00, 0x00, 0x00,
            0x48, 0x63, 0xC8, 0x48, 0x8D, 0x0C, 0x49, 0x48,
            0xC1, 0xE1, 0x05, 0x49, 0x03, 0xC8, 0x48, 0x39,
            0x11, 0x74, 0x1B, 0x8B, 0x41, 0x58, 0x83, 0xF8,
            0xFF, 0x75, 0xE5, 0x33, 0xC0, 0x48, 0x8B, 0x9C,
            0x24, 0xA8, 0x00, 0x00, 0x00, 0x48, 0x83, 0xC4,
            0x70, 0x41, 0x5C, 0x5E, 0x5D, 0xC3, 0x45, 0x33,
            0xE4, 0x4C, 0x8D, 0x51, 0x08, 0x48, 0x85, 0xC9,
            0x4D, 0x0F, 0x44, 0xD4, 0x4D, 0x85, 0xD2, 0x74,
            0xDA, 0x41, 0x8B, 0x4A, 0x28, 0x45, 0x8B, 0xC4,
            0x48, 0x89, 0xBC, 0x24, 0x90, 0x00, 0x00, 0x00,
            0x49, 0x8D, 0x7A, 0x10, 0x4C, 0x89, 0xB4, 0x24,
            0x98, 0x00, 0x00, 0x00, 0x45, 0x8B, 0xF4, 0x4C,
            0x89, 0xBC, 0x24, 0xA0, 0x00, 0x00, 0x00, 0x41,
            0xBF, 0x01, 0x00, 0x00, 0x00, 0x41, 0x8B, 0xDC,
            0x45, 0x8B, 0xCC, 0x85, 0xC9, 0x74, 0x61, 0x48,
            0x8B, 0x47, 0x10, 0x4C, 0x8B, 0xDF, 0x48, 0x85,
            0xC0, 0x8B, 0xD9, 0x4C, 0x0F, 0x45, 0xD8, 0x8D,
            0x41, 0xFF, 0x99, 0x83, 0xE2, 0x1F, 0x03, 0xC2,
            0x41, 0x8B, 0x0B, 0xC1, 0xF8, 0x05, 0x85, 0xC9,
            0x75, 0x1E, 0x66, 0x0F, 0x1F, 0x44, 0x00, 0x00,
            0x49, 0x63, 0xC8, 0x41, 0x83, 0xC1, 0x20, 0x41,
            0xFF, 0xC0, 0x44, 0x3B, 0xC0, 0x7F, 0x29, 0x41,
            0x8B, 0x4C, 0x8B, 0x04, 0x85, 0xC9, 0x74, 0xE8,
            0x8B, 0xC1, 0xF7, 0xD8, 0x23, 0xC1, 0x44, 0x8B,
            0xF8, 0x48, 0x03, 0xC0, 0x48, 0x83, 0xC8, 0x01,
            0x48, 0x0F, 0xBD, 0xC8, 0xFF, 0xC9, 0x41, 0x03,
            0xC9, 0x3B, 0xCB, 0x0F, 0x4F, 0xCB, 0x8B, 0xD9,
            0x44, 0x89, 0x7D, 0xBC, 0x4C, 0x8B, 0xBC, 0x24,
            0xA0, 0x00, 0x00, 0x00, 0x89, 0x5D, 0xCC, 0x8B,
            0x45, 0xCC, 0x4C, 0x89, 0x55, 0xB0, 0x44, 0x89,
            0x45, 0xB8, 0x0F, 0x10, 0x45, 0xB0, 0x48, 0x89,
            0x7D, 0xC0, 0xC7, 0x45, 0xC8, 0xFF, 0xFF, 0xFF,
            0xFF, 0x0F, 0x10, 0x4D, 0xC0, 0x44, 0x89, 0x4D,
            0xD0, 0x0F, 0x11, 0x45, 0xD8, 0x89, 0x45, 0xD4,
            0xF2, 0x0F, 0x10, 0x45, 0xD0, 0xF2, 0x0F, 0x11,
            0x45, 0xF8, 0x0F, 0x11, 0x4D, 0xE8, 0x41, 0x3B,
            0x5A, 0x28, 0x0F, 0x8D, 0xE5, 0x00, 0x00, 0x00,
            0x8B, 0x45, 0xF4, 0x0F, 0x1F, 0x44, 0x00, 0x00,
            0x48, 0x98, 0x48, 0x8D, 0x14, 0x40, 0x48, 0x8B,
            0x45, 0xD8, 0x48, 0x8B, 0x08, 0x8B, 0x46, 0x48,
            0x0F, 0x10, 0x04, 0xD1, 0x0F, 0x11, 0x45, 0xB0,
            0x3B, 0x46, 0x74, 0x0F, 0x84, 0x9B, 0x00, 0x00,
            0x00, 0x48, 0x8D, 0x7E, 0x78, 0xBA, 0x10, 0x00,
            0x00, 0x00, 0x48, 0x8B, 0x5F, 0x08, 0x48, 0x8D,
            0x4D, 0xB0, 0xE8, 0x09, 0x72, 0xBF, 0x00, 0x48,
            0x63, 0xC8, 0x48, 0x63, 0x86, 0x88, 0x00, 0x00,
            0x00, 0x48, 0xFF, 0xC8, 0x48, 0x23, 0xC8, 0x48,
            0x85, 0xDB, 0x48, 0x0F, 0x45, 0xFB, 0x8B, 0x04,
            0x8F, 0x83, 0xF8, 0xFF, 0x74, 0x66, 0x4C, 0x8B,
            0x46, 0x40, 0x44, 0x8B, 0x4D, 0xBC, 0x44, 0x8B,
            0x55, 0xB8, 0x44, 0x8B, 0x5D, 0xB4, 0x8B, 0x5D,
            0xB0, 0x0F, 0x1F, 0x80, 0x00, 0x00, 0x00, 0x00,
            0x48, 0x63, 0xC8, 0x41, 0x8B, 0xD1, 0x48, 0x69,
            0xC1, 0x68, 0x01, 0x00, 0x00, 0x41, 0x8B, 0xCA,
            0x49, 0x03, 0xC0, 0x33, 0x48, 0x08, 0x33, 0x50,
            0x0C, 0x0B, 0xD1, 0x41, 0x8B, 0xCB, 0x33, 0x48,
            0x04, 0x0B, 0xD1, 0x8B, 0xCB, 0x33, 0x08, 0x0B,
            0xD1, 0x74, 0x0D, 0x8B, 0x80, 0x60, 0x01, 0x00,
            0x00, 0x83, 0xF8, 0xFF, 0x75, 0xCA, 0xEB, 0x14,
            0x48, 0x85, 0xC0, 0x48, 0x8D, 0x48, 0x10, 0x49,
            0x0F, 0x44, 0xCC, 0x48, 0x85, 0xC9, 0x74, 0x04,
            0x44, 0x03, 0x71, 0x34, 0x8B, 0x4D, 0xE4, 0xF7,
            0xD1, 0x21, 0x4D, 0xF0, 0x48, 0x8D, 0x4D, 0xE0,
            0xE8, 0x53, 0xC7, 0x20, 0xFF, 0x48, 0x8B, 0x4D,
            0xE8, 0x8B, 0x45, 0xF4, 0x3B, 0x41, 0x18, 0x0F,
            0x8C, 0x23, 0xFF, 0xFF, 0xFF, 0x48, 0x8B, 0xBC,
            0x24, 0x90, 0x00, 0x00, 0x00, 0x41, 0x8B, 0xC6,
            0x4C, 0x8B, 0xB4, 0x24, 0x98, 0x00, 0x00, 0x00,
            0x48, 0x8B, 0x9C, 0x24, 0xA8, 0x00, 0x00, 0x00,
            0x48, 0x83, 0xC4, 0x70, 0x41, 0x5C, 0x5E, 0x5D,
            0xC3,
        };
        // RVA 0x2938950, 195 bytes. Whole function.
        constexpr std::array<std::uint8_t, 195> kFNameFromWideSignature{
            0x48, 0x89, 0x5C, 0x24, 0x08, 0x57, 0x48, 0x83,
            0xEC, 0x30, 0x48, 0x8B, 0xD9, 0x41, 0x8B, 0xF8,
            0x33, 0xC9, 0x4C, 0x8B, 0xDA, 0x44, 0x8B, 0xD1,
            0x4C, 0x8B, 0xCA, 0x48, 0x85, 0xD2, 0x74, 0x23,
            0x0F, 0xB7, 0x02, 0x66, 0x85, 0xC0, 0x74, 0x1B,
            0x0F, 0x1F, 0x84, 0x00, 0x00, 0x00, 0x00, 0x00,
            0x49, 0x83, 0xC1, 0x02, 0x0F, 0xB7, 0xC0, 0x44,
            0x0B, 0xD0, 0x41, 0x0F, 0xB7, 0x01, 0x66, 0x85,
            0xC0, 0x75, 0xED, 0x41, 0xF7, 0xC2, 0x80, 0xFF,
            0xFF, 0xFF, 0x4C, 0x89, 0x5C, 0x24, 0x20, 0x0F,
            0x95, 0xC0, 0x4D, 0x2B, 0xCB, 0x88, 0x44, 0x24,
            0x2C, 0x0F, 0xB7, 0x44, 0x24, 0x2D, 0x49, 0xD1,
            0xF9, 0x66, 0x89, 0x44, 0x24, 0x2D, 0x0F, 0xB6,
            0x44, 0x24, 0x2F, 0x88, 0x44, 0x24, 0x2F, 0x44,
            0x89, 0x4C, 0x24, 0x28, 0x45, 0x85, 0xC9, 0x75,
            0x11, 0x48, 0x89, 0x0B, 0x48, 0x8B, 0xC3, 0x48,
            0x8B, 0x5C, 0x24, 0x40, 0x48, 0x83, 0xC4, 0x30,
            0x5F, 0xC3, 0x48, 0x8D, 0x54, 0x24, 0x28, 0x49,
            0x8B, 0xCB, 0xE8, 0xD9, 0x4F, 0x01, 0x00, 0x0F,
            0x28, 0x44, 0x24, 0x20, 0x48, 0x8D, 0x54, 0x24,
            0x20, 0x44, 0x8B, 0xC8, 0x66, 0x0F, 0x7F, 0x44,
            0x24, 0x20, 0x44, 0x8B, 0xC7, 0x48, 0x8B, 0xCB,
            0xE8, 0x7B, 0xF9, 0xFF, 0xFF, 0x48, 0x8B, 0xC3,
            0x48, 0x8B, 0x5C, 0x24, 0x40, 0x48, 0x83, 0xC4,
            0x30, 0x5F, 0xC3,
        };
        // RVA 0x23BA0C0, 361 bytes. Whole ServerRequest_ItemBucketItemAdd_Implementation.
        constexpr std::array<std::uint8_t, 361> kServerItemBucketAddSignature{
            0x48, 0x89, 0x5C, 0x24, 0x08, 0x4C, 0x89, 0x4C,
            0x24, 0x20, 0x57, 0x48, 0x81, 0xEC, 0xE0, 0x01,
            0x00, 0x00, 0x48, 0x8B, 0x05, 0x67, 0xB6, 0x96,
            0x04, 0x48, 0x33, 0xC4, 0x48, 0x89, 0x84, 0x24,
            0xD0, 0x01, 0x00, 0x00, 0x48, 0x8B, 0x8C, 0x24,
            0x38, 0x02, 0x00, 0x00, 0x41, 0x8B, 0xF8, 0x0F,
            0xB6, 0xDA, 0x48, 0x8D, 0x94, 0x24, 0x80, 0x00,
            0x00, 0x00, 0xE8, 0xF1, 0xDF, 0x7D, 0xFF, 0x8B,
            0x84, 0x24, 0x8C, 0x00, 0x00, 0x00, 0x0B, 0x84,
            0x24, 0x88, 0x00, 0x00, 0x00, 0x0B, 0x84, 0x24,
            0x84, 0x00, 0x00, 0x00, 0x0B, 0x84, 0x24, 0x80,
            0x00, 0x00, 0x00, 0x75, 0x7B, 0x33, 0xC0, 0x48,
            0x89, 0x44, 0x24, 0x60, 0x89, 0x44, 0x24, 0x68,
            0x48, 0x89, 0x44, 0x24, 0x70, 0x89, 0x44, 0x24,
            0x78, 0xE8, 0x5A, 0xDA, 0x6D, 0xFF, 0x0F, 0xB6,
            0x84, 0x24, 0x30, 0x02, 0x00, 0x00, 0x4C, 0x8D,
            0x8C, 0x24, 0x08, 0x02, 0x00, 0x00, 0x88, 0x44,
            0x24, 0x50, 0x44, 0x8B, 0xC7, 0x0F, 0xB6, 0x84,
            0x24, 0x28, 0x02, 0x00, 0x00, 0x8B, 0xD3, 0x88,
            0x44, 0x24, 0x48, 0x0F, 0xB6, 0x84, 0x24, 0x20,
            0x02, 0x00, 0x00, 0x88, 0x44, 0x24, 0x40, 0x48,
            0x8D, 0x44, 0x24, 0x60, 0x48, 0x89, 0x44, 0x24,
            0x38, 0x48, 0x8D, 0x44, 0x24, 0x70, 0x48, 0x89,
            0x44, 0x24, 0x30, 0x8B, 0x84, 0x24, 0x18, 0x02,
            0x00, 0x00, 0x89, 0x44, 0x24, 0x28, 0x8B, 0x84,
            0x24, 0x10, 0x02, 0x00, 0x00, 0x89, 0x44, 0x24,
            0x20, 0xE8, 0x5A, 0xEC, 0x73, 0xFF, 0xEB, 0x63,
            0x33, 0xC0, 0x48, 0x89, 0x44, 0x24, 0x70, 0x89,
            0x44, 0x24, 0x78, 0x48, 0x89, 0x44, 0x24, 0x60,
            0x89, 0x44, 0x24, 0x68, 0xE8, 0xDF, 0xD9, 0x6D,
            0xFF, 0x0F, 0xB6, 0x84, 0x24, 0x30, 0x02, 0x00,
            0x00, 0x4C, 0x8D, 0x8C, 0x24, 0x80, 0x00, 0x00,
            0x00, 0x88, 0x44, 0x24, 0x40, 0x44, 0x8B, 0xC7,
            0x0F, 0xB6, 0x84, 0x24, 0x28, 0x02, 0x00, 0x00,
            0x8B, 0xD3, 0x88, 0x44, 0x24, 0x38, 0x0F, 0xB6,
            0x84, 0x24, 0x20, 0x02, 0x00, 0x00, 0x88, 0x44,
            0x24, 0x30, 0x48, 0x8D, 0x44, 0x24, 0x70, 0x48,
            0x89, 0x44, 0x24, 0x28, 0x48, 0x8D, 0x44, 0x24,
            0x60, 0x48, 0x89, 0x44, 0x24, 0x20, 0xE8, 0x05,
            0xEF, 0x73, 0xFF, 0x48, 0x8D, 0x8C, 0x24, 0x80,
            0x00, 0x00, 0x00, 0xE8, 0xB8, 0x30, 0x67, 0xFF,
            0x48, 0x8B, 0x8C, 0x24, 0xD0, 0x01, 0x00, 0x00,
            0x48, 0x33, 0xCC, 0xE8, 0x38, 0xF8, 0x01, 0x03,
            0x48, 0x8B, 0x9C, 0x24, 0xF0, 0x01, 0x00, 0x00,
            0x48, 0x81, 0xC4, 0xE0, 0x01, 0x00, 0x00, 0x5F,
            0xC3,
        };
        // RVA 0x1B980F0, 233 bytes. Whole FSBItemInstanceForRPC consumer (reads bytes 0x00..0x7B).
        constexpr std::array<std::uint8_t, 233> kRpcInstanceConverterSignature{
            0x48, 0x89, 0x5C, 0x24, 0x08, 0x48, 0x89, 0x6C,
            0x24, 0x10, 0x48, 0x89, 0x74, 0x24, 0x18, 0x57,
            0x48, 0x83, 0xEC, 0x20, 0x48, 0x8B, 0xD9, 0x48,
            0x8B, 0xEA, 0x48, 0x8B, 0xCA, 0xE8, 0x5E, 0x50,
            0xE9, 0xFF, 0x0F, 0x10, 0x03, 0x33, 0xFF, 0x8B,
            0xF7, 0x0F, 0x11, 0x01, 0x0F, 0x10, 0x43, 0x10,
            0x0F, 0x11, 0x41, 0x10, 0x48, 0x8B, 0x43, 0x20,
            0x48, 0x89, 0x41, 0x20, 0x8B, 0x43, 0x28, 0x89,
            0x41, 0x30, 0x8B, 0x43, 0x2C, 0x89, 0x41, 0x34,
            0x8B, 0x43, 0x30, 0x89, 0x41, 0x38, 0x0F, 0xB6,
            0x43, 0x34, 0x88, 0x41, 0x3C, 0x0F, 0xB6, 0x43,
            0x35, 0x88, 0x81, 0xE8, 0x00, 0x00, 0x00, 0x8B,
            0x43, 0x38, 0x89, 0x41, 0x40, 0x39, 0x7B, 0x48,
            0x7E, 0x2E, 0x66, 0x0F, 0x1F, 0x44, 0x00, 0x00,
            0x3B, 0x73, 0x58, 0x7D, 0x1C, 0x48, 0x8B, 0x43,
            0x50, 0x48, 0x63, 0xCE, 0x4C, 0x8D, 0x04, 0xC8,
            0x48, 0x8B, 0x43, 0x40, 0x48, 0x8D, 0x14, 0x88,
            0x48, 0x8D, 0x4D, 0x48, 0xE8, 0x6F, 0x2A, 0x00,
            0x00, 0xFF, 0xC6, 0x3B, 0x73, 0x48, 0x7C, 0xD8,
            0x39, 0x7B, 0x68, 0x7E, 0x34, 0x0F, 0x1F, 0x00,
            0x3B, 0x7B, 0x78, 0x7D, 0x25, 0x4C, 0x8B, 0x43,
            0x70, 0x48, 0x8B, 0x53, 0x60, 0x48, 0x63, 0xC7,
            0x48, 0x8D, 0x0C, 0x85, 0x00, 0x00, 0x00, 0x00,
            0x4C, 0x03, 0xC1, 0x48, 0x03, 0xD1, 0x48, 0x8D,
            0x8D, 0x98, 0x00, 0x00, 0x00, 0xE8, 0x36, 0xF5,
            0x68, 0xFF, 0xFF, 0xC7, 0x3B, 0x7B, 0x68, 0x7C,
            0xCF, 0x48, 0x8B, 0x5C, 0x24, 0x30, 0x48, 0x8B,
            0xC5, 0x48, 0x8B, 0x6C, 0x24, 0x38, 0x48, 0x8B,
            0x74, 0x24, 0x40, 0x48, 0x83, 0xC4, 0x20, 0x5F,
            0xC3,
        };
        // RVA 0xE340E0, 3 bytes. mov al,1; ret (ServerRequest_ItemBucketItemAdd_Validate slot).
        constexpr std::array<std::uint8_t, 3> kAlwaysTrueValidateSignature{
            0xB0, 0x01, 0xC3,
        };
        // RVA 0x1A9A960, 94 bytes. Whole FindItemRow(item_table, unused, const FName*); called.
        constexpr std::array<std::uint8_t, 94> kItemRowLookupSignature{
            0x40, 0x53, 0x48, 0x83, 0xEC, 0x20, 0x8B, 0x05,
            0x14, 0x83, 0x57, 0x05, 0x41, 0x39, 0x00, 0x0F,
            0x94, 0xC2, 0x41, 0x83, 0x78, 0x04, 0x00, 0x0F,
            0x94, 0xC0, 0x84, 0xD0, 0x75, 0x38, 0x48, 0x8B,
            0x49, 0x20, 0x48, 0x85, 0xC9, 0x74, 0x2F, 0x4D,
            0x8B, 0x00, 0xE8, 0xD1, 0x3C, 0x00, 0x00, 0x48,
            0x8B, 0xD8, 0x48, 0x85, 0xC0, 0x74, 0x1F, 0x80,
            0x78, 0x08, 0x00, 0x75, 0x10, 0x48, 0x8B, 0x08,
            0xC6, 0x40, 0x08, 0x01, 0x48, 0x8B, 0x51, 0x20,
            0x48, 0x8B, 0xC8, 0xFF, 0xD2, 0x48, 0x8B, 0xC3,
            0x48, 0x83, 0xC4, 0x20, 0x5B, 0xC3, 0x33, 0xC0,
            0x48, 0x83, 0xC4, 0x20, 0x5B, 0xC3,
        };
        // RVA 0x1CC3630, 201 bytes. Whole client carry-limit function (row +0x84/+0x88, stat [entry+0x118+stat*4]); not called.
        constexpr std::array<std::uint8_t, 201> kItemMaxAmountSignature{
            0x48, 0x89, 0x5C, 0x24, 0x08, 0x57, 0x48, 0x83,
            0xEC, 0x20, 0x48, 0x83, 0x3D, 0x2E, 0xEF, 0x36,
            0x05, 0x00, 0x48, 0x8B, 0xFA, 0x0F, 0x84, 0xA1,
            0x00, 0x00, 0x00, 0xE8, 0xF0, 0x45, 0xDD, 0xFF,
            0x48, 0x8B, 0x80, 0xC8, 0x00, 0x00, 0x00, 0x48,
            0x85, 0xC0, 0x0F, 0x84, 0x8C, 0x00, 0x00, 0x00,
            0x48, 0x63, 0x48, 0x3C, 0x33, 0xDB, 0x85, 0xC9,
            0x78, 0x0F, 0x3B, 0x48, 0x30, 0x7D, 0x0A, 0x48,
            0x8B, 0x40, 0x28, 0x48, 0x8B, 0x14, 0xC8, 0xEB,
            0x03, 0x48, 0x8B, 0xD3, 0x48, 0x85, 0xD2, 0x74,
            0x6B, 0xE8, 0xBA, 0x45, 0xDD, 0xFF, 0x48, 0x8B,
            0x80, 0xC8, 0x00, 0x00, 0x00, 0x48, 0x85, 0xC0,
            0x74, 0x15, 0x48, 0x63, 0x48, 0x3C, 0x85, 0xC9,
            0x78, 0x0D, 0x3B, 0x48, 0x30, 0x7D, 0x08, 0x48,
            0x8B, 0x40, 0x28, 0x48, 0x8B, 0x1C, 0xC8, 0xE8,
            0x74, 0x48, 0xDD, 0xFF, 0x48, 0x8B, 0xC8, 0x4C,
            0x8B, 0xC7, 0xE8, 0xA9, 0x72, 0xDD, 0xFF, 0x48,
            0x85, 0xC0, 0x74, 0x30, 0x0F, 0xB6, 0x88, 0x88,
            0x00, 0x00, 0x00, 0x84, 0xC9, 0x74, 0x14, 0xF3,
            0x0F, 0x2C, 0x84, 0x8B, 0x18, 0x01, 0x00, 0x00,
            0x48, 0x8B, 0x5C, 0x24, 0x30, 0x48, 0x83, 0xC4,
            0x20, 0x5F, 0xC3, 0x8B, 0x80, 0x84, 0x00, 0x00,
            0x00, 0x48, 0x8B, 0x5C, 0x24, 0x30, 0x48, 0x83,
            0xC4, 0x20, 0x5F, 0xC3, 0x48, 0x8B, 0x5C, 0x24,
            0x30, 0x33, 0xC0, 0x48, 0x83, 0xC4, 0x20, 0x5F,
            0xC3,
        };
        // RVA 0x1BDAABD, 336 bytes. Server add fragment: ValidConditionGroup (+0x1AC), InventoryAlias redirect (+0x14), use on pickup (+0x134); not called.
        constexpr std::array<std::uint8_t, 336> kServerAddChecksSignature{
            0x83, 0xBF, 0xB0, 0x01, 0x00, 0x00, 0x00, 0x8B,
            0x05, 0xB6, 0x81, 0x43, 0x05, 0x0F, 0x95, 0xC1,
            0x48, 0x89, 0x9C, 0x24, 0x68, 0x01, 0x00, 0x00,
            0x39, 0x87, 0xAC, 0x01, 0x00, 0x00, 0x4C, 0x89,
            0xB4, 0x24, 0x58, 0x01, 0x00, 0x00, 0x0F, 0x95,
            0xC0, 0x0A, 0xC8, 0x74, 0x7D, 0x41, 0x8B, 0x5F,
            0x34, 0xE8, 0x2D, 0xD0, 0xEB, 0xFF, 0x48, 0x8B,
            0xC8, 0x8B, 0xD3, 0xE8, 0xB3, 0xBF, 0xEF, 0xFF,
            0x4C, 0x8B, 0xF0, 0x48, 0x85, 0xC0, 0x74, 0x62,
            0x48, 0x8B, 0x58, 0x60, 0x48, 0x85, 0xDB, 0x74,
            0x59, 0xE8, 0x7D, 0xD3, 0xEB, 0xFF, 0x4C, 0x8B,
            0x87, 0xAC, 0x01, 0x00, 0x00, 0x4C, 0x8D, 0x4B,
            0x10, 0x48, 0x8B, 0xC8, 0x48, 0x8D, 0x55, 0xB0,
            0xE8, 0xA6, 0x0A, 0x0B, 0x00, 0x48, 0x8B, 0x4D,
            0xB0, 0x48, 0x85, 0xC9, 0x74, 0x2B, 0x49, 0x8B,
            0x46, 0x60, 0xBB, 0x00, 0x00, 0x00, 0x00, 0x48,
            0x85, 0xC0, 0x48, 0x8D, 0x50, 0x10, 0x48, 0x0F,
            0x44, 0xD3, 0xE8, 0x04, 0x00, 0x0B, 0x00, 0x84,
            0xC0, 0x75, 0x0E, 0x48, 0x8D, 0x4D, 0xB0, 0xE8,
            0x77, 0xEB, 0x25, 0xFF, 0xE9, 0x87, 0x0A, 0x00,
            0x00, 0x48, 0x8D, 0x4D, 0xB0, 0xE8, 0x69, 0xEB,
            0x25, 0xFF, 0x41, 0x83, 0x7F, 0x30, 0x01, 0x4C,
            0x8B, 0xF7, 0x48, 0x89, 0x7C, 0x24, 0x78, 0x0F,
            0x85, 0x93, 0x00, 0x00, 0x00, 0x8B, 0x05, 0x00,
            0x81, 0x43, 0x05, 0x39, 0x47, 0x14, 0x48, 0x89,
            0x7C, 0x24, 0x78, 0x0F, 0x95, 0xC1, 0x83, 0x7F,
            0x18, 0x00, 0x0F, 0x95, 0xC0, 0x0A, 0xC8, 0x74,
            0x2E, 0xE8, 0x85, 0xD3, 0xEB, 0xFF, 0x48, 0x8B,
            0xC8, 0x4C, 0x8D, 0x47, 0x14, 0xE8, 0xB9, 0xFD,
            0xEB, 0xFF, 0x48, 0x89, 0x7C, 0x24, 0x78, 0x48,
            0x85, 0xC0, 0x74, 0x13, 0x48, 0x8B, 0x4F, 0x14,
            0x4C, 0x8B, 0xF0, 0x48, 0x89, 0x8D, 0xA8, 0x00,
            0x00, 0x00, 0x48, 0x89, 0x44, 0x24, 0x78, 0x41,
            0x83, 0x7F, 0x30, 0x01, 0x75, 0x42, 0x41, 0x80,
            0xBE, 0x34, 0x01, 0x00, 0x00, 0x00, 0x74, 0x38,
            0x41, 0x8B, 0x5F, 0x34, 0xE8, 0x42, 0xCF, 0xEB,
            0xFF, 0x48, 0x8B, 0xC8, 0x8B, 0xD3, 0xE8, 0xC8,
            0xBE, 0xEF, 0xFF, 0x48, 0x85, 0xC0, 0x0F, 0x84,
            0xF4, 0x09, 0x00, 0x00, 0x48, 0x8B, 0x95, 0xA8,
            0x00, 0x00, 0x00, 0x4C, 0x8B, 0xC8, 0x44, 0x8B,
            0xC6, 0x48, 0x89, 0x44, 0x24, 0x20, 0xE8, 0xC8,
            0x4B, 0x00, 0x00, 0xE9, 0xD8, 0x09, 0x00, 0x00,
        };
        // RVA 0x1BDAD37, 121 bytes. Server add fragment: carry clamp via 0x1BE0330/0x1BE01F0; not called.
        constexpr std::array<std::uint8_t, 121> kServerAddClampSignature{
            0x41, 0x8B, 0x47, 0x30, 0x41, 0x0F, 0xB6, 0x4E,
            0x70, 0x89, 0x44, 0x24, 0x74, 0x8D, 0x41, 0xFE,
            0xA8, 0xFD, 0x74, 0x09, 0x80, 0xF9, 0x03, 0x74,
            0x04, 0x32, 0xDB, 0xEB, 0x02, 0xB3, 0x01, 0x41,
            0x80, 0x7F, 0x38, 0x00, 0x44, 0x8B, 0xF6, 0x89,
            0x74, 0x24, 0x70, 0x74, 0x4C, 0x48, 0x8D, 0x95,
            0xA8, 0x00, 0x00, 0x00, 0x49, 0x8B, 0xCF, 0xE8,
            0xBD, 0x55, 0x00, 0x00, 0x48, 0x8D, 0x95, 0xA8,
            0x00, 0x00, 0x00, 0x49, 0x8B, 0xCF, 0x8B, 0xF8,
            0xE8, 0x6C, 0x54, 0x00, 0x00, 0x89, 0x74, 0x24,
            0x70, 0x85, 0xC0, 0x74, 0x24, 0x8D, 0x0C, 0x3E,
            0x89, 0x74, 0x24, 0x70, 0x3B, 0xC8, 0x76, 0x19,
            0x3B, 0xC7, 0x0F, 0x86, 0x46, 0x08, 0x00, 0x00,
            0x44, 0x8B, 0xF0, 0x44, 0x2B, 0xF7, 0x44, 0x89,
            0x74, 0x24, 0x70, 0x0F, 0x84, 0x35, 0x08, 0x00,
            0x00,
        };
        // RVA 0x1A97B20, 97 bytes. Whole getter; fast path returns [0x7032568] (server-frame request queue).
        constexpr std::array<std::uint8_t, 97> kRequestQueueGetterSignature{
            0x48, 0x83, 0xEC, 0x28, 0x48, 0x8B, 0x05, 0x3D,
            0xAA, 0x59, 0x05, 0x48, 0x85, 0xC0, 0x75, 0x4C,
            0x48, 0x8B, 0x0D, 0xC9, 0x39, 0x5D, 0x05, 0x48,
            0x85, 0xC9, 0x75, 0x0C, 0xE8, 0x6F, 0xD8, 0xD9,
            0x00, 0x48, 0x8B, 0x0D, 0xB8, 0x39, 0x5D, 0x05,
            0x48, 0x8B, 0x01, 0x45, 0x33, 0xC0, 0xBA, 0x88,
            0x06, 0x00, 0x00, 0xFF, 0x50, 0x10, 0x48, 0x85,
            0xC0, 0x74, 0x14, 0x48, 0x8B, 0xC8, 0xE8, 0x9D,
            0x2B, 0x03, 0x00, 0x48, 0x89, 0x05, 0xFE, 0xA9,
            0x59, 0x05, 0x48, 0x83, 0xC4, 0x28, 0xC3, 0x48,
            0xC7, 0x05, 0xEE, 0xA9, 0x59, 0x05, 0x00, 0x00,
            0x00, 0x00, 0x33, 0xC0, 0x48, 0x83, 0xC4, 0x28,
            0xC3,
        };
        // RVA 0x1AF8DF0, 770 bytes. Whole enqueue step of the RPC implementation; keys the add by queue+0x14; not called.
        constexpr std::array<std::uint8_t, 770> kRequestEnqueueSignature{
            0x48, 0x89, 0x5C, 0x24, 0x10, 0x48, 0x89, 0x6C,
            0x24, 0x18, 0x56, 0x57, 0x41, 0x55, 0x41, 0x56,
            0x41, 0x57, 0x48, 0x83, 0xEC, 0x40, 0x4C, 0x8B,
            0xBC, 0x24, 0xA8, 0x00, 0x00, 0x00, 0x48, 0x8D,
            0x44, 0x24, 0x20, 0x45, 0x33, 0xED, 0x49, 0x8B,
            0xD9, 0x4C, 0x89, 0x6C, 0x24, 0x20, 0x41, 0x8B,
            0xF8, 0x44, 0x89, 0x6C, 0x24, 0x28, 0x8B, 0xEA,
            0x4C, 0x3B, 0xF8, 0x74, 0x19, 0x45, 0x39, 0x6F,
            0x08, 0x74, 0x13, 0x49, 0x8B, 0x0F, 0x48, 0x85,
            0xC9, 0x74, 0x0B, 0x48, 0x8B, 0x01, 0x48, 0x8D,
            0x54, 0x24, 0x20, 0xFF, 0x50, 0x40, 0x4C, 0x8B,
            0xB4, 0x24, 0xA0, 0x00, 0x00, 0x00, 0x48, 0x8D,
            0x44, 0x24, 0x30, 0x4C, 0x89, 0x6C, 0x24, 0x30,
            0x44, 0x89, 0x6C, 0x24, 0x38, 0x4C, 0x3B, 0xF0,
            0x74, 0x19, 0x45, 0x39, 0x6E, 0x08, 0x74, 0x13,
            0x49, 0x8B, 0x0E, 0x48, 0x85, 0xC9, 0x74, 0x0B,
            0x48, 0x8B, 0x01, 0x48, 0x8D, 0x54, 0x24, 0x30,
            0xFF, 0x50, 0x40, 0x4C, 0x8D, 0x44, 0x24, 0x20,
            0x48, 0x8D, 0x54, 0x24, 0x30, 0xE8, 0x06, 0xF6,
            0x04, 0x00, 0x48, 0x8B, 0xF0, 0x48, 0x85, 0xC0,
            0x0F, 0x84, 0xE3, 0x01, 0x00, 0x00, 0x89, 0x68,
            0x10, 0x89, 0x78, 0x14, 0x48, 0x8B, 0x0B, 0x48,
            0x89, 0x48, 0x18, 0x8B, 0x8C, 0x24, 0x90, 0x00,
            0x00, 0x00, 0x89, 0x48, 0x20, 0x8B, 0x8C, 0x24,
            0x98, 0x00, 0x00, 0x00, 0x89, 0x48, 0x24, 0x0F,
            0xB6, 0x8C, 0x24, 0xB0, 0x00, 0x00, 0x00, 0x88,
            0x88, 0x78, 0x01, 0x00, 0x00, 0x0F, 0xB6, 0x8C,
            0x24, 0xB8, 0x00, 0x00, 0x00, 0x88, 0x88, 0x79,
            0x01, 0x00, 0x00, 0x0F, 0xB6, 0x84, 0x24, 0xC0,
            0x00, 0x00, 0x00, 0x88, 0x86, 0x7A, 0x01, 0x00,
            0x00, 0xC6, 0x86, 0x7B, 0x01, 0x00, 0x00, 0x01,
            0xE8, 0xB3, 0xEB, 0xF9, 0xFF, 0x48, 0x8B, 0xD8,
            0x8B, 0x40, 0x14, 0x83, 0xF8, 0x04, 0x0F, 0x85,
            0xA6, 0x01, 0x00, 0x00, 0xE8, 0x0F, 0x34, 0x82,
            0x00, 0x48, 0x85, 0xC0, 0x74, 0x0D, 0x48, 0x8B,
            0xC8, 0xE8, 0x52, 0x04, 0x47, 0x02, 0x89, 0x43,
            0x14, 0xEB, 0x48, 0xE8, 0x68, 0x37, 0x82, 0x00,
            0x48, 0x85, 0xC0, 0x74, 0x0D, 0x48, 0x8B, 0xC8,
            0xE8, 0x3B, 0x04, 0x47, 0x02, 0x89, 0x43, 0x14,
            0xEB, 0x31, 0x48, 0x8B, 0x05, 0xE7, 0x29, 0x50,
            0x05, 0x48, 0x85, 0xC0, 0x74, 0x25, 0x48, 0x8B,
            0x88, 0x28, 0x02, 0x00, 0x00, 0x48, 0x85, 0xC9,
            0x74, 0x19, 0x48, 0x8B, 0x41, 0x30, 0x48, 0x85,
            0xC0, 0x74, 0x10, 0x80, 0xB8, 0x4C, 0x02, 0x00,
            0x00, 0x01, 0x75, 0x07, 0xC7, 0x43, 0x14, 0x01,
            0x00, 0x00, 0x00, 0x8B, 0x43, 0x14, 0x83, 0xF8,
            0x04, 0x0F, 0x85, 0x3B, 0x01, 0x00, 0x00, 0x44,
            0x89, 0x6B, 0x14, 0x4C, 0x89, 0x64, 0x24, 0x70,
            0xE8, 0xAB, 0xEB, 0xF9, 0xFF, 0x48, 0x8B, 0xD8,
            0x4C, 0x8D, 0xA0, 0xB8, 0x00, 0x00, 0x00, 0x49,
            0x8B, 0xCC, 0xFF, 0x15, 0x68, 0x49, 0xAB, 0x03,
            0x8B, 0x4B, 0x14, 0x44, 0x38, 0x6B, 0x08, 0x8B,
            0x43, 0x20, 0x8D, 0x79, 0x01, 0x0F, 0x44, 0xF9,
            0x3B, 0x43, 0x4C, 0x74, 0x4C, 0x48, 0x8B, 0x4B,
            0x58, 0x48, 0x8D, 0x53, 0x50, 0x48, 0x63, 0x43,
            0x60, 0x48, 0xFF, 0xC8, 0x48, 0x63, 0xEF, 0x48,
            0x23, 0xC5, 0x48, 0x85, 0xC9, 0x48, 0x0F, 0x45,
            0xD1, 0x8B, 0x04, 0x82, 0x83, 0xF8, 0xFF, 0x74,
            0x28, 0x48, 0x8B, 0x53, 0x18, 0x66, 0x66, 0x66,
            0x0F, 0x1F, 0x84, 0x00, 0x00, 0x00, 0x00, 0x00,
            0x48, 0x63, 0xC8, 0x48, 0xC1, 0xE1, 0x05, 0x39,
            0x3C, 0x11, 0x0F, 0x84, 0x04, 0x01, 0x00, 0x00,
            0x8B, 0x44, 0x11, 0x18, 0x83, 0xF8, 0xFF, 0x75,
            0xE7, 0x48, 0x63, 0xEF, 0x48, 0x8D, 0x94, 0x24,
            0xC8, 0x00, 0x00, 0x00, 0x89, 0xBC, 0x24, 0xC8,
            0x00, 0x00, 0x00, 0x48, 0x8D, 0x4B, 0x18, 0xE8,
            0x9C, 0xB5, 0xFE, 0xFF, 0x8B, 0x43, 0x20, 0x3B,
            0x43, 0x4C, 0x74, 0x3A, 0x48, 0x8B, 0x43, 0x58,
            0x48, 0x8D, 0x53, 0x50, 0x48, 0x63, 0x4B, 0x60,
            0x48, 0xFF, 0xC9, 0x48, 0x23, 0xCD, 0x48, 0x85,
            0xC0, 0x48, 0x0F, 0x45, 0xD0, 0x8B, 0x04, 0x8A,
            0x83, 0xF8, 0xFF, 0x74, 0x19, 0x48, 0x8B, 0x53,
            0x18, 0x48, 0x98, 0x48, 0xC1, 0xE0, 0x05, 0x48,
            0x03, 0xC2, 0x39, 0x38, 0x74, 0x0B, 0x8B, 0x40,
            0x18, 0x83, 0xF8, 0xFF, 0x75, 0xEB, 0x49, 0x8B,
            0xC5, 0x48, 0x63, 0x78, 0x10, 0x48, 0x8D, 0x58,
            0x08, 0x8D, 0x47, 0x01, 0x89, 0x43, 0x08, 0x3B,
            0x43, 0x0C, 0x7E, 0x08, 0x48, 0x8B, 0xCB, 0xE8,
            0x9C, 0xEE, 0x34, 0xFF, 0x48, 0x8B, 0x03, 0x49,
            0x8B, 0xCC, 0x48, 0x89, 0x34, 0xF8, 0xFF, 0x15,
            0x84, 0x48, 0xAB, 0x03, 0x4C, 0x8B, 0x64, 0x24,
            0x70, 0x49, 0x8B, 0xCE, 0xE8, 0x1F, 0xC6, 0x34,
            0xFF, 0x49, 0x8B, 0xCF, 0x48, 0x8B, 0x5C, 0x24,
            0x78, 0x48, 0x8B, 0xAC, 0x24, 0x80, 0x00, 0x00,
            0x00, 0x48, 0x83, 0xC4, 0x40, 0x41, 0x5F, 0x41,
            0x5E, 0x41, 0x5D, 0x5F, 0x5E, 0xE9, 0xFE, 0xC5,
            0x34, 0xFF, 0x83, 0xF8, 0x03, 0x0F, 0x85, 0xC0,
            0xFE, 0xFF, 0xFF, 0xE8, 0xF0, 0xE9, 0xF9, 0xFF,
            0xE8, 0xCB, 0x35, 0x82, 0x00, 0x48, 0x8B, 0xD8,
            0x48, 0x85, 0xC0, 0x74, 0x18, 0x48, 0x8B, 0xC8,
            0xE8, 0x9B, 0x02, 0x47, 0x02, 0x83, 0xF8, 0x03,
            0x75, 0x0B, 0x48, 0x8B, 0xD6, 0x48, 0x8B, 0xCB,
            0xE8, 0x5B, 0x9E, 0x8B, 0x00, 0x48, 0x8B, 0x06,
            0xBA, 0x01, 0x00, 0x00, 0x00, 0x48, 0x8B, 0xCE,
            0xFF, 0x10, 0xEB, 0x95, 0x83, 0xF8, 0xFF, 0x0F,
            0x85, 0x17, 0xFF, 0xFF, 0xFF, 0xE9, 0xFA, 0xFE,
            0xFF, 0xFF,
        };
        // ---- This module's gate manifest (A11) -------------------------------
        // sbcore::gate::validate runs it after the sbcore core manifest. It
        // holds every v0.3.1 code region byte-for-byte: no byte is masked, so
        // every rel32/disp32 is compared exactly, which at this fixed image
        // base also fixes its target. sbcore checks at most 512 bytes per
        // entry, so the two longer whole functions are checked in two
        // consecutive parts under their v0.3.1 name. function_begin is set
        // where the image's own .pdata starts a function at the rva (verified
        // offline by tools/verify_live_add_offline.py); the two getter fast
        // paths are chained unwind fragments and stay anchored by their
        // getters' jne rel32 instead.
        using sbcore::gate::Role;
        constexpr std::size_t kCheckChunk = sbcore::gate::kMaxCheckSize;
        constexpr auto kExactMask = [] {
            std::array<std::uint8_t, kCheckChunk> mask{};
            for (auto& byte : mask) byte = 0xFF;
            return mask;
        }();

        constexpr sbcore::gate::CodeCheck exact_check(const char* name, std::uintptr_t rva, const std::uint8_t* bytes,
                                                      std::size_t size, bool function_begin, Role role)
        {
            return sbcore::gate::CodeCheck{name, static_cast<std::uint32_t>(rva), static_cast<std::uint16_t>(size),
                                           bytes, kExactMask.data(), nullptr, 0, function_begin, role};
        }

        static_assert(kGetItemCountByAliasSignature.size() > kCheckChunk
                      && kGetItemCountByAliasSignature.size() <= 2 * kCheckChunk);
        static_assert(kRequestEnqueueSignature.size() > kCheckChunk
                      && kRequestEnqueueSignature.size() <= 2 * kCheckChunk);

        constexpr sbcore::gate::CodeCheck kLiveAddCode[] = {
            exact_check("create_task", kCreateTaskRva, kCreateTaskSignature.data(), kCreateTaskSignature.size(),
                        true, Role::Called),
            exact_check("setup_task", kSetupTaskRva, kSetupTaskSignature.data(), kSetupTaskSignature.size(),
                        true, Role::Called),
            exact_check("execute_task", kTaskExecuteRva, kExecuteTaskSignature.data(), kExecuteTaskSignature.size(),
                        true, Role::Reference),
            exact_check("task_destructor", kTaskDestructorRva, kTaskDestructorSignature.data(),
                        kTaskDestructorSignature.size(), true, Role::Called),
            exact_check("game_thread_id_initializer", kGameThreadIdInitializerRva,
                        kGameThreadIdInitializerSignature.data(), kGameThreadIdInitializerSignature.size(),
                        false, Role::Anchor),
            exact_check("local_client_getter", kLocalClientGetterRva, kLocalClientGetterSignature.data(),
                        kLocalClientGetterSignature.size(), true, Role::Anchor),
            exact_check("item_table_getter", kItemTableGetterRva, kItemTableGetterSignature.data(),
                        kItemTableGetterSignature.size(), true, Role::Anchor),
            exact_check("item_table_getter_fast_path", kItemTableGetterFastPathRva,
                        kItemTableGetterFastPathSignature.data(), kItemTableGetterFastPathSignature.size(),
                        false, Role::Anchor),
            exact_check("add_subsystem_getter", kAddSubsystemGetterRva, kAddSubsystemGetterSignature.data(),
                        kAddSubsystemGetterSignature.size(), true, Role::Anchor),
            exact_check("add_subsystem_getter_fast_path", kAddSubsystemGetterFastPathRva,
                        kAddSubsystemGetterFastPathSignature.data(), kAddSubsystemGetterFastPathSignature.size(),
                        false, Role::Anchor),
            exact_check("primary_bucket_lookup", kPrimaryBucketLookupRva, kPrimaryBucketLookupSignature.data(),
                        kPrimaryBucketLookupSignature.size(), false, Role::Called),
            exact_check("find_inventory_bucket", kFindInventoryBucketRva, kFindInventoryBucketSignature.data(),
                        kFindInventoryBucketSignature.size(), true, Role::Called),
            exact_check("current_target_guid", kCurrentTargetGuidRva, kCurrentTargetGuidSignature.data(),
                        kCurrentTargetGuidSignature.size(), true, Role::Called),
            exact_check("get_item_count_by_alias", kGetItemCountByAliasRva, kGetItemCountByAliasSignature.data(),
                        kCheckChunk, true, Role::Called),
            exact_check("get_item_count_by_alias", kGetItemCountByAliasRva + kCheckChunk,
                        kGetItemCountByAliasSignature.data() + kCheckChunk,
                        kGetItemCountByAliasSignature.size() - kCheckChunk, false, Role::Called),
            exact_check("fname_from_wide", kFNameFromWideRva, kFNameFromWideSignature.data(),
                        kFNameFromWideSignature.size(), true, Role::Called),
            exact_check("server_item_bucket_add", kServerItemBucketAddRva, kServerItemBucketAddSignature.data(),
                        kServerItemBucketAddSignature.size(), true, Role::Called),
            exact_check("rpc_instance_converter", kRpcInstanceConverterRva, kRpcInstanceConverterSignature.data(),
                        kRpcInstanceConverterSignature.size(), true, Role::Reference),
            exact_check("always_true_validate", kAlwaysTrueValidateRva, kAlwaysTrueValidateSignature.data(),
                        kAlwaysTrueValidateSignature.size(), false, Role::Reference),
            exact_check("item_row_lookup", kItemRowLookupRva, kItemRowLookupSignature.data(),
                        kItemRowLookupSignature.size(), true, Role::Called),
            exact_check("item_max_amount", kItemMaxAmountRva, kItemMaxAmountSignature.data(),
                        kItemMaxAmountSignature.size(), true, Role::Anchor),
            exact_check("server_add_checks", kServerAddChecksRva, kServerAddChecksSignature.data(),
                        kServerAddChecksSignature.size(), false, Role::Reference),
            exact_check("server_add_clamp", kServerAddClampRva, kServerAddClampSignature.data(),
                        kServerAddClampSignature.size(), false, Role::Reference),
            exact_check("request_queue_getter", kRequestQueueGetterRva, kRequestQueueGetterSignature.data(),
                        kRequestQueueGetterSignature.size(), true, Role::Anchor),
            exact_check("request_enqueue", kRequestEnqueueRva, kRequestEnqueueSignature.data(), kCheckChunk,
                        true, Role::Reference),
            exact_check("request_enqueue", kRequestEnqueueRva + kCheckChunk,
                        kRequestEnqueueSignature.data() + kCheckChunk,
                        kRequestEnqueueSignature.size() - kCheckChunk, false, Role::Reference),
        };
        // Both task slots and the RPC implementation slot. Their targets are
        // .pdata function begins (sbcore requires it). The _Validate slot's
        // target (0xE340E0, mov al,1; ret) is a leaf without a .pdata entry,
        // so private_gate_failure() checks that slot after the manifest.
        constexpr sbcore::gate::SlotCheck kLiveAddSlots[] = {
            {"task_vtable", static_cast<std::uint32_t>(kTaskVtableRva), 0,
             static_cast<std::uint32_t>(kTaskDestructorRva)},
            {"task_vtable", static_cast<std::uint32_t>(kTaskVtableRva), sizeof(void*),
             static_cast<std::uint32_t>(kTaskExecuteRva)},
            {"controller_vtable", static_cast<std::uint32_t>(kControllerVtableRva),
             static_cast<std::uint32_t>(kServerAddImplementationSlotOffset),
             static_cast<std::uint32_t>(kServerItemBucketAddRva)},
        };
        constexpr sbcore::gate::GlobalCheck kLiveAddGlobals[] = {
            {"game_thread_id_global", static_cast<std::uint32_t>(kGameThreadIdRva), sizeof(std::uint32_t), false},
            {"local_client_global", static_cast<std::uint32_t>(kBucketSingletonRva), sizeof(void*), false},
            {"item_table_global", static_cast<std::uint32_t>(kItemTableSingletonRva), sizeof(void*), false},
            {"add_subsystem_global", static_cast<std::uint32_t>(kAddSubsystemSingletonRva), sizeof(void*), false},
            {"none_fname_global", static_cast<std::uint32_t>(kNoneFNameIndexRva), sizeof(std::uint32_t), false},
            {"request_queue_global", static_cast<std::uint32_t>(kRequestQueueSingletonRva), sizeof(void*), false},
        };
        constexpr sbcore::gate::Manifest kLiveAddManifest =
            sbcore::gate::make_manifest("sbliveadd", kLiveAddCode, kLiveAddSlots, kLiveAddGlobals);

        using PrimaryBucketLookupFn = void* (__fastcall*)(void* manager, std::uint32_t bucket_id);
        using FindInventoryBucketFn = void* (__fastcall*)(void* manager,
                                                          std::uint32_t bucket_type,
                                                          std::uint32_t target_guid);
        using CurrentTargetGuidFn = std::uint32_t (__fastcall*)();
        using GetItemCountByAliasFn = std::int32_t (__fastcall*)(
            void* bucket, const std::uint64_t* alias_name);
        using FNameFromWideFn = std::uint64_t* (__fastcall*)(
            std::uint64_t* out_name, const wchar_t* text, std::uint32_t find_type);
        // ServerRequest_ItemBucketItemAdd_Implementation. Parameter order and
        // widths match the reflected RPC parameter frame (9 parameters, 0xA0 bytes). The
        // first (this) argument is never read by the certified body.
        using ServerItemBucketAddFn = void(__fastcall*)(void* unused_context, std::uint8_t bucket_type,
                                                        std::uint32_t target_guid, std::uint64_t item_alias,
                                                        std::uint32_t count, std::uint32_t stat_level,
                                                        std::uint8_t notify_ui, std::uint8_t notify_enhance_ui,
                                                        std::uint8_t event_load, void* rpc_item_instance);
        // FindItemRow. The second argument is never read (see kItemRowLookupRva).
        using ItemRowLookupFn = void* (__fastcall*)(void* item_table, std::uint64_t unused,
                                                    const std::uint64_t* alias_name);

        enum class Action : std::uint32_t
        {
            None,
            Refresh,
            Add,
            Verify,
            Probe,  // v0.5.0: one read-only chunk of a probe
        };

        enum class Phase : std::uint32_t
        {
            Idle,
            Refreshing,
            AddPending,
            AddRequested,
            VerifyPending,
            Done,
            Fault,
        };

        enum class Result : std::uint32_t
        {
            None,
            Ready,
            BuildMismatch,
            WrongThread,
            RequestInvalid,
            RequestStale,
            SessionMismatch,
            DuplicateRequest,
            PolicyBlocked,
            BucketNotReady,
            TargetNotReady,
            ContextChanged,
            CountMismatch,
            AddRequested,
            AddedVerified,
            NotVerified,
            AddException,
            DispatchFailed,
            DispatchException,
            Busy,
            SelfCheckNotPassed,
            SelfCheckFailed,
            SubsystemNotReady,
            AtCapacity,
            UsedOnPickup,
            ItemRowNotFound,
            // v0.5.0 (appended: the numeric values above are unchanged)
            QuantityNotAllowed,
            CategoryDenied,
            UseCanonicalAlias,
            EntitlementGated,
            DataMismatch,
            AlreadyOwned,
            LockedByStat,
            LimitUnknown,
            InstanceCountUnproven,
            SideEffectDetected,
            SessionLocked,
            PanelLeaseMissing,
            // v0.5.1 (appended: the numeric values above are unchanged)
            AutoLevelUp,
            PerUnitOwnedUnproven,
        };

        // How the game limits the count of one item in the inventory bucket.
        enum class MaxState : std::uint32_t
        {
            Unknown,  // the limit could not be read
            NoLimit,  // the game's limit value is 0 (the server add does not clamp)
            Limit,    // the server add clamps to this value
        };

        struct ItemCapacity
        {
            bool row_found{};
            bool inventory_redirect{};
            bool condition_group{};
            bool use_on_pickup{};
            std::uint32_t auto_level_type{};  // v0.5.1: AutoCharacterLevelUpType (0: none)
            bool stack_amount_read{};         // v0.5.1: StackAmount was read
            std::int32_t stack_amount{};      // v0.5.1: StackAmount (1: one bag entry per unit)
            std::uint32_t category{};
            std::uint32_t stat{};  // v0.5.0: the effective row's MaxAmountOverrideActorStat
            MaxState max_state{MaxState::Unknown};
            std::uint32_t max_value{};
            const char* max_source{"unknown"};
        };

        // v0.5.0: the one decision an add and a probe share (PLAN C2-C5).
        struct ItemDecision
        {
            Result result{Result::None};  // None: send qty_send
            std::uint32_t qty_send{};
            const char* reason{"none"};
        };

        struct CapacityDecision
        {
            bool refuse{};
            std::uint32_t qty_send{};
        };

        enum class VerifyStep : std::uint32_t
        {
            Verified,
            Mismatch,
            Continue,
            ContinuePaused,
            Unverified,
        };

        enum class SelfCheckState : std::uint32_t
        {
            Pending,
            Passed,
            Failed,
        };

        enum class BucketStatus : std::uint32_t
        {
            Absent,
            Inconsistent,
            Exception,
            TargetChain,
            Ok,
        };

        enum class TargetChain : std::uint32_t
        {
            NoTarget,   // CurrentTargetGuid would return 0 without a virtual call
            Callable,   // every link readable; the virtual target is in-image code
            Invalid,    // unreadable link or a virtual target outside image code
        };

        std::atomic<bool> g_running{false};
        std::atomic<bool> g_install_attempted{false};
        std::atomic<bool> g_shutting_down{false};
        std::atomic<bool> g_ready{false};
        // This module's own dispatch latch (sticky): set by any dispatch
        // failure, as in v0.3.1. sbcore::dispatch keeps its own poison flag.
        std::atomic<bool> g_dispatch_poisoned{false};
        std::atomic<bool> g_outcome_unknown{false};
        std::atomic<Action> g_pending_action{Action::None};
        std::atomic<Phase> g_phase{Phase::Idle};
        std::atomic<Result> g_result{Result::None};
        std::atomic<std::uint64_t> g_server_add_calls{0};
        std::atomic<std::uint64_t> g_bucket_refresh_count{0};
        std::atomic<std::uint64_t> g_heartbeat_beat{0};
        std::atomic<std::uint32_t> g_worker_thread_id{0};
        std::atomic<std::uint32_t> g_last_exception{0};
        std::atomic<sbcore::dispatch::SubmitResult> g_last_submit_result{sbcore::dispatch::SubmitResult::NotBound};
        std::atomic<std::uint64_t> g_actions_abandoned_blocked{0};
        // A13: the panel's Items lease, evaluated by the worker only.
        std::atomic<bool> g_panel_lease_fresh{false};
        std::atomic<bool> g_verify_scheduled{false};
        std::atomic<std::uint64_t> g_verify_due_tick{0};
        std::atomic<std::uint32_t> g_inventory_bucket_guid{0};
        std::atomic<std::uint32_t> g_inventory_target_guid{0};
        std::atomic<std::uint64_t> g_last_panel_seq{0};
        std::atomic<const char*> g_gate_failed_check{"not_run"};
        std::atomic<bool> g_gate_passed{false};
        std::atomic<SelfCheckState> g_self_check_state{SelfCheckState::Pending};
        std::atomic<const char*> g_self_check_step{"not_started"};
        std::atomic<std::uint64_t> g_self_check_attempts{0};
        std::atomic<bool> g_self_check_reflection_passed{false};
        std::atomic<std::uint32_t> g_self_check_aliases_resolved{0};
        std::atomic<std::uint32_t> g_self_check_aliases_read{0};
        std::atomic<std::uint32_t> g_self_check_bucket_guid{0};
        std::atomic<std::uint32_t> g_self_check_target_guid{0};
        std::atomic<std::uint32_t> g_self_check_primary_entries{0};
        std::atomic<std::uint32_t> g_self_check_type_entries{0};
        // v0.5.0 (C8): the sentinel FName indices the passed self-check
        // resolved. Written and read on the certified GameThread only (the
        // self-check, execute_add); the status reads the atomic count.
        std::array<std::uint64_t, kSentinelItems.size()> g_sentinel_names{};
        std::atomic<std::uint32_t> g_sentinels_resolved{0};
        // Bit (1 << category) for gear, exospine and suit: this session read a
        // count of 1 or more for an allowlisted item of that category, so the
        // game's count read sees unique instances there (PLAN W0 gate 2).
        std::atomic<std::uint32_t> g_instance_evidence{0};
        // C6: a watched count grew with an add. Sticky: no further add or probe.
        std::atomic<bool> g_side_effect_latched{false};
        // Session latch: once set (by a failed self-check, an exception in
        // any game function, or an invalid CurrentTargetGuid chain), no game
        // function is entered again until the game restarts.
        std::atomic<bool> g_game_code_disabled{false};
        std::atomic<const char*> g_game_code_disabled_reason{"none"};
        std::atomic<std::uint64_t> g_game_code_entries{0};
        std::atomic<std::uint64_t> g_game_code_refused{0};

        SRWLOCK g_session_lock = SRWLOCK_INIT;
        SRWLOCK g_update_lock = SRWLOCK_INIT;
        SRWLOCK g_mutation_lock = SRWLOCK_INIT;
        std::string g_session;

        // C6: one watched count (an item other than the one added).
        struct WatchEntry
        {
            std::uint16_t item{};
            std::uint64_t name{};  // the whole FName (0: not in the name pool when the add was sent)
            std::uint32_t before{};
        };

        // Trivially destructible: execute_add holds it next to its __try.
        struct WatchSet
        {
            std::uint32_t count{};
            std::array<WatchEntry, kMaxWatch> entries{};
        };

        struct PendingAdd
        {
            bool active{};
            std::uint64_t panel_seq{};
            std::string session;
            std::string request_id;
            std::string alias;
            std::uint64_t issued_unix_s{};
            std::uint64_t native_beat{};
            std::uint32_t alias_index{};
            std::uint32_t qty{};
            std::uint32_t before{};
            std::uint32_t bucket_guid{};
            std::uint32_t target_guid{};
            std::uint64_t started_tick{};
            std::uint64_t expires_tick{};
            bool mutation_attempted{};
            // v0.3.1: filled in by execute_add / execute_verify.
            std::uint32_t qty_sent{};
            std::uint64_t add_tick{};
            bool frame_at_add_known{};
            std::uint32_t frame_at_add{};
            std::uint64_t frames_resumed_tick{};
            std::uint32_t verify_polls{};
            ItemCapacity capacity{};
            // v0.5.0: the allowlisted row and the C6 watch set read with the add.
            std::uint16_t item_index{};
            WatchSet watch{};
                                                                           
            // number the alias implies) this module resolved and sent; every
            // verification read re-resolves the alias and must get it again.
            std::uint64_t alias_name{};
        };
        SRWLOCK g_pending_lock = SRWLOCK_INIT;
        PendingAdd g_pending{};

        // Measurements of the last add attempt, published in the status file
        // only. Never read back by any decision.
        struct AddReport
        {
            std::string alias;
            std::uint32_t qty_requested{};
            std::uint32_t qty_sent{};
            bool before_known{};
            std::uint32_t before{};
            bool after_known{};
            std::uint32_t after{};
            ItemCapacity capacity{};
            bool capacity_read{};
            std::uint64_t verify_window_ms{};
            std::uint32_t verify_polls{};
            bool paused_wait{};   // waiting on frozen server frames right now
            bool paused_seen{};   // this add waited on frozen server frames at least once
            bool frame_at_add_known{};
            std::uint32_t frame_at_add{};
            const char* outcome{"none"};
            // v0.5.0
            const char* group{"none"};
            const char* refusal_reason{"none"};
            std::uint32_t watch_count{};
            std::string watch_changed;
        };
        SRWLOCK g_report_lock = SRWLOCK_INIT;
        AddReport g_report{};
        // Self-check snapshot: alias:count:limit:flags for every sentinel.
        std::string g_alias_snapshot{"not_run"};

        // Server-frame index of the request queue (read only). "live" once two
        // GameThread samples differed this session.
        std::atomic<bool> g_server_frame_known{false};
        std::atomic<bool> g_server_frame_live{false};
        std::atomic<std::uint32_t> g_server_frame_last{0};

        struct PendingResult
        {
            bool active{};
            bool ok{};
            bool terminal{};
            std::string session;
            std::string request_id;
            std::uint64_t panel_seq{};
            std::string status;
            std::string detail;
            std::uint32_t bucket_guid{};
            std::uint32_t before{};
            std::uint32_t after{};
        };
        SRWLOCK g_result_lock = SRWLOCK_INIT;
        PendingResult g_pending_result{};

        // ---- v0.5.0 (C7): the read-only probe ---------------------------------
        // The panel writes Mods\SBCheatGUI\live_add_native_probe_request.txt;
        // the worker validates it, the certified GameThread reads at most
        // kProbeChunk items per callback (FName lookup, count read, row lookup
        // and carry stat: exactly the reads an add makes), and the worker
        // publishes Mods\SBCheatGUI\live_add_native_probe_result.txt.
        constexpr std::size_t kProbeChunk = 32;
        constexpr std::size_t kProbeMaxListed = 64;
        constexpr std::uint64_t kProbeRequestMaxAgeSeconds = 5;
        constexpr std::size_t kProbeRequestMaxBytes = 8192;

        struct ProbeReading
        {
            bool taken{};
            bool name_found{};
            bool count_ok{};
            std::uint32_t count{};
            ItemCapacity capacity{};
        };

        struct ProbeJob
        {
            bool active{};    // accepted or refused; its result is not published yet
            bool finished{};  // every reading taken, or refused/aborted (status)
            std::uint64_t generation{};
            std::string session;
            std::string probe_id;
            std::vector<std::uint16_t> items;
            std::vector<ProbeReading> readings;
            std::size_t cursor{};
            bool bucket_known{};
            std::uint32_t bucket_guid{};
            std::uint32_t target_guid{};
            std::uint32_t chunks{};
            Result status{Result::None};  // None: ok
        };
        SRWLOCK g_probe_lock = SRWLOCK_INIT;
        ProbeJob g_probe{};
        std::string g_probe_last_id{"none"};  // under g_probe_lock
        std::atomic<bool> g_probe_running{false};  // active && !finished: the worker's scheduling hint
        std::atomic<std::uint64_t> g_probe_generation{0};
        std::atomic<std::uint64_t> g_probe_requests{0};
        std::atomic<std::uint64_t> g_probe_refused{0};
        std::atomic<std::uint64_t> g_probe_chunks{0};
        std::atomic<std::uint64_t> g_probe_publishes{0};
        std::atomic<Result> g_probe_last_status{Result::None};
        std::atomic<std::uint32_t> g_probe_items_total{0};
        std::atomic<std::uint32_t> g_probe_items_done{0};

        std::byte* g_image{};
        // P1: every path comes from this DLL's own location (sbcore::paths).
        std::wstring g_mod_directory;
        std::wstring g_request_path;
        std::wstring g_request_claim_path;
        std::wstring g_result_path;
        std::wstring g_heartbeat_path;
        std::wstring g_status_path;
        std::wstring g_status_temp_path;
        std::wstring g_lease_path;
        std::wstring g_probe_request_path;
        std::wstring g_probe_claim_path;
        std::wstring g_probe_result_path;
        std::uint64_t g_last_command_poll_tick{};
        std::uint64_t g_last_bucket_refresh_tick{};
        std::uint64_t g_last_publish_check_tick{};

        // A12 files. Used by the UE4SS worker only (install and shutdown hold
        // g_update_lock, as run_update does). No fsync: the rename by handle
        // is what makes each replace atomic for readers.
        sbcore::status::Writer g_result_writer;
        sbcore::status::Writer g_heartbeat_writer;
        sbcore::status::Writer g_probe_writer;
        sbcore::status::Publisher g_status_publisher;
        struct HeartbeatPacing
        {
            bool attempted{};
            bool published{};
            bool last_failed{};
            std::uint64_t last_attempt_ms{};
            std::uint64_t last_success_ms{};
            std::uint64_t last_hash{};
            std::uint64_t sequence{};
        };
        HeartbeatPacing g_heartbeat_pacing{};

        // A13: the panel's Items lease (worker only).
        enum class LeaseState : std::uint32_t
        {
            NotRead,
            Missing,
            Unreadable,
            Malformed,
            Invalid,
            Future,
            Stale,
            PanelGone,
            Fresh,
        };
        sbcore::status::StableReader g_lease_reader;
        std::atomic<LeaseState> g_panel_lease_state{LeaseState::NotRead};
        std::atomic<std::uint32_t> g_panel_lease_pid{0};

        // A8/A11: the gate result and the shared exe identity (install only).
        sbcore::gate::Result g_gate_result{};
        sbcore::exe_identity::Info g_exe_identity{};
        std::atomic<bool> g_exe_identity_checked{false};
        std::atomic<sbcore::status::ReadResult> g_last_request_read{sbcore::status::ReadResult::Missing};

        const char* phase_name(Phase phase)
        {
            switch (phase)
            {
            case Phase::Idle: return "idle";
            case Phase::Refreshing: return "refreshing";
            case Phase::AddPending: return "add_pending";
            case Phase::AddRequested: return "add_requested";
            case Phase::VerifyPending: return "verify_pending";
            case Phase::Done: return "done";
            case Phase::Fault: return "fault";
            }
            return "unknown";
        }

        const char* result_name(Result result)
        {
            switch (result)
            {
            case Result::None: return "none";
            case Result::Ready: return "ready";
            case Result::BuildMismatch: return "build_mismatch";
            case Result::WrongThread: return "wrong_thread";
            case Result::RequestInvalid: return "request_invalid";
            case Result::RequestStale: return "request_stale";
            case Result::SessionMismatch: return "session_mismatch";
            case Result::DuplicateRequest: return "duplicate_request";
            case Result::PolicyBlocked: return "policy_blocked";
            case Result::BucketNotReady: return "inventory_bucket_not_ready";
            case Result::TargetNotReady: return "inventory_target_not_ready";
            case Result::ContextChanged: return "inventory_context_changed";
            case Result::CountMismatch: return "inventory_count_mismatch";
            case Result::AddRequested: return "game_owned_add_requested";
            case Result::AddedVerified: return "added_verified";
            case Result::NotVerified: return "authoritative_server_no_verified_count_change";
            case Result::AddException: return "authoritative_server_item_add_exception";
            case Result::DispatchFailed: return "dispatch_failed";
            case Result::DispatchException: return "dispatch_exception";
            case Result::Busy: return "busy";
            case Result::SelfCheckNotPassed: return "self_check_not_passed";
            case Result::SelfCheckFailed: return "self_check_failed";
            case Result::SubsystemNotReady: return "game_subsystem_not_ready";
            case Result::AtCapacity: return "inventory_at_capacity";
            case Result::UsedOnPickup: return "item_used_on_pickup";
            case Result::ItemRowNotFound: return "item_row_not_found";
            case Result::QuantityNotAllowed: return "quantity_not_allowed";
            case Result::CategoryDenied: return "category_denied";
            case Result::UseCanonicalAlias: return "use_canonical_alias";
            case Result::EntitlementGated: return "entitlement_gated";
            case Result::DataMismatch: return "data_mismatch";
            case Result::AlreadyOwned: return "already_owned";
            case Result::LockedByStat: return "locked_by_stat";
            case Result::LimitUnknown: return "limit_unknown";
            case Result::InstanceCountUnproven: return "instance_count_unproven";
            case Result::SideEffectDetected: return "side_effect_detected";
            case Result::SessionLocked: return "session_locked";
            case Result::PanelLeaseMissing: return "panel_lease_missing";
            case Result::AutoLevelUp: return "item_auto_level_up";
            case Result::PerUnitOwnedUnproven: return "item_per_unit_owned_unproven";
            }
            return "unknown";
        }

        const char* max_state_name(MaxState state)
        {
            switch (state)
            {
            case MaxState::Unknown: return "unknown";
            case MaxState::NoLimit: return "none";
            case MaxState::Limit: return "limit";
            }
            return "unknown";
        }

        // Pure: mirrors the server clamp at 0x1BDAD88 for a known limit.
        CapacityDecision decide_capacity(MaxState state, std::uint32_t max_value,
                                         std::uint32_t before, std::uint32_t qty)
        {
            if (state != MaxState::Limit || max_value == 0) return {false, qty};
            if (before >= max_value) return {true, 0};
            const std::uint32_t room = max_value - before;
            return {false, qty < room ? qty : room};
        }

        // Pure: whether a verification read sees the server frames frozen
        // since the add (UWorld paused: the frame tick passes zero delta, so
        // the queued request cannot have been processed yet). v0.3.1 also
        // required that this session had already seen the frame index
        // advance; that evidence came from the unconditional 500 ms Refresh,
        // which sampled the frame all through gameplay. Under A13 the frame is
        // sampled only while the panel holds an Items lease, so a first lease
        // taken while the game is paused never sees an advance, and v0.3.1's
        // rule would end that add as not verified (outcome unknown, Live Add
        // locked for the session) after 5 s instead of waiting for the
        // unpause as v0.3.1 did. An index unchanged since the add therefore
        // counts as frozen whether or not an advance was seen before. The
        // wait stays bounded by kVerifyPausedWindowMs, reads only and never
        // repeats the add; a running game advances the index, so nothing
        // changes there.
        bool frames_frozen_since_add(bool frame_comparable, std::uint32_t frame, std::uint32_t frame_at_add)
        {
            return frame_comparable && frame == frame_at_add;
        }

        // Pure: one verification read. since_resume_ms is UINT64_MAX while
        // the server frames have not advanced past the add.
        VerifyStep decide_verify(std::uint32_t before, std::uint32_t sent, std::uint32_t after,
                                 std::uint64_t since_add_ms, bool frames_frozen,
                                 std::uint64_t since_resume_ms)
        {
            const std::uint64_t expected = static_cast<std::uint64_t>(before) + sent;
            if (after == expected) return VerifyStep::Verified;
            if (after > expected) return VerifyStep::Mismatch;
            if (since_add_ms < kVerifyWindowMs) return VerifyStep::Continue;
            if (since_add_ms >= kVerifyPausedWindowMs) return VerifyStep::Unverified;
            if (frames_frozen) return VerifyStep::ContinuePaused;
            if (since_resume_ms < kVerifyWindowMs) return VerifyStep::Continue;
            return VerifyStep::Unverified;
        }

        // Pure (v0.5.1): the live row keeps one bag entry per unit
        // (StackAmount 1). An unreadable StackAmount counts as per-unit.
        bool live_row_is_per_unit(const ItemCapacity& live)
        {
            return !live.stack_amount_read || live.stack_amount == 1;
        }

        // Pure (C2): nullptr while the live row still says what the catalog
        // says, else the reason token. A stat-capped row's limit is its actor
        // stat, judged by decide_item (C5).
        const char* row_mismatch(const AllowedItem& item, const ItemCapacity& live)
        {
            if (!live.row_found) return "row_not_found";
            if (live.inventory_redirect) return "inventory_alias_redirect";
            if (live.condition_group) return "condition_group";
            if (live.use_on_pickup) return "used_on_pickup";
            if (live.category != item.category) return "category";
            if (live.stat != item.stat) return "carry_stat";
            if (item.stat == 0)
            {
                if (live.max_state == MaxState::Unknown) return "max_unreadable";
                if (item.game_max <= 0 || live.max_value != static_cast<std::uint32_t>(item.game_max)) return "max_amount";
            }
            return nullptr;
        }

        // Pure: the one decision an add (and, with qty 1, a probe) makes from
        // the allowlisted row, the live row (read_item_capacity), the current
        // count and whether this session proved that the count read sees
        // unique instances of the item's category. Result::None means: send
        // exactly qty_send. Nothing here reads or calls the game.
        ItemDecision decide_item(const AllowedItem& item, const ItemCapacity& live, std::uint32_t before,
                                 std::uint32_t qty, bool instances_proven)
        {
            if (item.group == ItemGroup::Gated) return {Result::EntitlementGated, 0, "catalog_entitlement_gated"};
            if (!item_group_addable(item.group) || item.per_add_max == 0) return {Result::PolicyBlocked, 0, "not_addable"};
            if (qty == 0 || qty > item.per_add_max) return {Result::QuantityNotAllowed, 0, "quantity"};
            if (!live.row_found) return {Result::ItemRowNotFound, 0, "row_not_found"};
            // C1b, in code: whatever the list or the live row says.
            if (category_hard_denied(item.category) || category_hard_denied(live.category))
                return {Result::CategoryDenied, 0, "category_denied"};
            if (live.inventory_redirect) return {Result::UseCanonicalAlias, 0, "inventory_alias_redirect"};
            if (live.condition_group) return {Result::EntitlementGated, 0, "condition_group"};
            if (live.use_on_pickup) return {Result::UsedOnPickup, 0, "used_on_pickup"};
            // v0.5.1: the game spends these items itself. After every add the
            // server levels the player up (Body: max HP, Beta: max Beta
            // energy) as soon as the count meets the next CharacterLevelTable
            // row, removing the required items in the same frame (Beta Core
                                                                              
            // equals before + sent, and the add is a progression change, so
            // such a row is refused whatever the list says.
            if (live.auto_level_type != 0) return {Result::AutoLevelUp, 0, "auto_level_up"};
            if (const char* mismatch = row_mismatch(item, live)) return {Result::DataMismatch, 0, mismatch};
            if (item.stat != 0)
            {
                // C5: the limit is the current target's actor stat. Unreadable:
                // unknown. 0: the ammo type is not unlocked (and the server
                // would not clamp at all).
                if (live.max_state == MaxState::Unknown) return {Result::LimitUnknown, 0, "carry_stat_unreadable"};
                if (live.max_state != MaxState::Limit || live.max_value == 0)
                    return {Result::LockedByStat, 0, "carry_stat_zero"};
            }
            // Every addable row is clamped by the game: never send without a known limit.
            if (live.max_state != MaxState::Limit || live.max_value == 0)
                return {Result::LimitUnknown, 0, "no_limit"};
            if (item.group == ItemGroup::OnePerPlayer || item.group == ItemGroup::UniqueInstance)
            {
                // C4: an owned MaxAmount-1 item would be swapped for its
                // replacement (_MK2, _Var2 or Vitcoin) by the server.
                if (before != 0) return {Result::AlreadyOwned, 0, "already_owned"};
                if (qty != 1) return {Result::QuantityNotAllowed, 0, "quantity"};
                if (item.group == ItemGroup::UniqueInstance && !instances_proven)
                    return {Result::InstanceCountUnproven, 0, "instance_count_unproven"};
            }
            // v0.5.1: adding to an owned per-unit item is sent only for the
            // categories whose server add was traced to merge into the one
            // existing pocket, which the count read sums (see the header).
            if (before != 0 && live_row_is_per_unit(live) && !per_unit_add_proven(live.category))
                return {Result::PerUnitOwnedUnproven, 0, "per_unit_owned_unproven"};
            const CapacityDecision capacity = decide_capacity(live.max_state, live.max_value, before, qty);
            if (capacity.refuse) return {Result::AtCapacity, 0, "at_capacity"};
            if (capacity.qty_send == 0 || capacity.qty_send > qty || capacity.qty_send > item.per_add_max)
                return {Result::RequestInvalid, 0, "quantity_bound"};
            // Gold: never above 100,000,000 minus the current Gold (and no row
            // ever above its limit).
            if (static_cast<std::uint64_t>(before) + capacity.qty_send > live.max_value)
                return {Result::AtCapacity, 0, "over_limit"};
            return {Result::None, capacity.qty_send, "none"};
        }

        struct ProbeLabel
        {
            const char* state;
            std::uint32_t addable_now;  // the most one add would send now (0: not addable)
        };

        // Pure (C7): the probe label of one reading. It is the decision an add
        // of 1 would get, so a label never promises more than an add does.
        ProbeLabel probe_label(const AllowedItem& item, const ProbeReading& reading, bool instances_proven)
        {
            if (!reading.taken) return {"not_read", 0};
            if (!reading.name_found || !reading.capacity.row_found) return {"not_in_game", 0};
            if (!reading.count_ok) return {"unreadable", 0};
            const ItemDecision decision = decide_item(item, reading.capacity, reading.count, 1, instances_proven);
            switch (decision.result)
            {
            case Result::None:
            {
                const std::uint32_t room = reading.capacity.max_value - reading.count;  // decide_item: count < max
                return {"available", room < item.per_add_max ? room : item.per_add_max};
            }
            case Result::AlreadyOwned: return {"owned", 0};
            case Result::AtCapacity: return {"at_limit", 0};
            case Result::EntitlementGated: return {"needs_dlc", 0};
            case Result::LockedByStat: return {"locked_by_stat", 0};
            case Result::LimitUnknown: return {"limit_unknown", 0};
            case Result::InstanceCountUnproven: return {"unproven", 0};
            case Result::ItemRowNotFound: return {"not_in_game", 0};
            case Result::AutoLevelUp: return {"auto_level_up", 0};
            case Result::PerUnitOwnedUnproven: return {"per_unit_unproven", 0};
            default: return {"data_mismatch", 0};
            }
        }

        // Pure (C6): a watched count that grew is a side effect of the add; a
        // count that fell is only reported. (The add itself removes items only
        // through the auto level-up of the added row, which decide_item refuses.)
        enum class WatchChange : std::uint32_t
        {
            Same,
            Grew,
            Fell,
        };

        WatchChange watch_change(std::uint32_t before, std::uint32_t now)
        {
            if (now > before) return WatchChange::Grew;
            if (now < before) return WatchChange::Fell;
            return WatchChange::Same;
        }

        bool instances_proven_for(std::uint32_t category)
        {
            return category_is_unique_instance(category)
                && (g_instance_evidence.load(std::memory_order_acquire) & (1U << category)) != 0;
        }

        // GameThread: a count of 1 or more read for an owned gear, exospine or
        // suit proves the game's count read sees unique instances there.
        void note_item_count(const AllowedItem& item, std::uint32_t count)
        {
            if (count >= 1 && category_is_unique_instance(item.category))
                g_instance_evidence.fetch_or(1U << item.category, std::memory_order_acq_rel);
        }

        std::string instance_evidence_text()
        {
            const std::uint32_t evidence = g_instance_evidence.load(std::memory_order_acquire);
            std::string text = "gear:";
            text += (evidence & (1U << kCategoryGear)) ? '1' : '0';
            text += ",exospine:";
            text += (evidence & (1U << kCategoryExoSpine)) ? '1' : '0';
            text += ",nanosuit:";
            text += (evidence & (1U << kCategoryNanoSuit)) ? '1' : '0';
            return text;
        }

        const char* self_check_state_name(SelfCheckState state)
        {
            switch (state)
            {
            case SelfCheckState::Pending: return "pending";
            case SelfCheckState::Passed: return "pass";
            case SelfCheckState::Failed: return "fail";
            }
            return "unknown";
        }

        bool self_check_passed()
        {
            return g_self_check_state.load(std::memory_order_acquire) == SelfCheckState::Passed;
        }

        bool self_check_failed()
        {
            return g_self_check_state.load(std::memory_order_acquire) == SelfCheckState::Failed;
        }

        // True while game functions may still be entered this session: the
        // image gate has passed, the self-check has not failed, no game
        // function has faulted, and (A9) no sbcore native in this process has
        // latched the process-wide write block. Checked before every Refresh
        // is scheduled or dispatched and at the top of every game-code wrapper.
        bool game_code_allowed()
        {
            return g_image != nullptr
                && !g_game_code_disabled.load(std::memory_order_acquire)
                && g_self_check_state.load(std::memory_order_acquire) != SelfCheckState::Failed
                && !sbcore::fault::writes_blocked_fast();
        }

        // Every wrapper that calls a game function enters through here first.
        bool enter_game_code()
        {
            if (!game_code_allowed())
            {
                g_game_code_refused.fetch_add(1, std::memory_order_relaxed);
                return false;
            }
            g_game_code_entries.fetch_add(1, std::memory_order_relaxed);
            return true;
        }

        // Sticky for the session. It also fails the self-check (keeping the
        // first failure step when it had already failed), so the heartbeat
        // reports ready=0 and every request is answered self_check_failed.
        void disable_game_code(const char* reason)
        {
            bool expected = false;
            if (g_game_code_disabled.compare_exchange_strong(
                    expected, true, std::memory_order_acq_rel, std::memory_order_acquire))
            {
                g_game_code_disabled_reason.store(reason, std::memory_order_release);
            }
            if (g_self_check_state.load(std::memory_order_acquire) != SelfCheckState::Failed)
            {
                g_self_check_step.store(reason, std::memory_order_release);
                g_self_check_state.store(SelfCheckState::Failed, std::memory_order_release);
            }
        }

        // An exception inside game code means the game frame was unwound
        // without its own cleanup; nothing in the game is entered again. The
        // handler's filter (sbcore::fault::filter) has already written the
        // persistent breadcrumb and latched the process-wide write block.
        void game_code_exception(const char* site, DWORD code)
        {
            g_last_exception.store(code, std::memory_order_release);
            disable_game_code(site);
        }

        // A9: another sbcore native (or this one) latched the process-wide
        // write block. Worker only; sticky for the session.
        void observe_process_write_block()
        {
            if (sbcore::fault::writes_blocked()) disable_game_code("sbcore_writes_blocked");
        }

        // sbcore's fault-free probes (VirtualQuery / ReadProcessMemory): no
        // exception can be raised by a probe, so no SEH is needed around them.
        using sbcore::memory::is_readable_region;

        bool safe_read_u64(const void* base, std::size_t byte_offset, std::uint64_t* out)
        {
            if (!base || !out) return false;
            std::uint64_t value = 0;
            if (!sbcore::memory::read_exact(reinterpret_cast<const std::uint8_t*>(base) + byte_offset, &value,
                                            sizeof(value)))
            {
                return false;
            }
            *out = value;
            return true;
        }

        bool safe_read_u32(const void* base, std::size_t byte_offset, std::uint32_t* out)
        {
            if (!base || !out) return false;
            std::uint32_t value = 0;
            if (!sbcore::memory::read_exact(reinterpret_cast<const std::uint8_t*>(base) + byte_offset, &value,
                                            sizeof(value)))
            {
                return false;
            }
            *out = value;
            return true;
        }

        bool is_readable_process_pointer(std::uint64_t address)
        {
            if (address < 0x10000ULL || address > 0x7FFFFFFFFFFFULL) return false;
            MEMORY_BASIC_INFORMATION mbi{};
            if (VirtualQuery(reinterpret_cast<void*>(address), &mbi, sizeof(mbi)) != sizeof(mbi)) return false;
            if (mbi.State != MEM_COMMIT) return false;
            const DWORD blocked = PAGE_NOACCESS | PAGE_GUARD;
            return (mbi.Protect & blocked) == 0;
        }

        bool is_readable_range(std::uint64_t address, std::size_t size)
        {
            return is_readable_process_pointer(address)
                && is_readable_region(reinterpret_cast<const void*>(address), size, false);
        }

        // Reads a singleton pointer from the image without calling its getter.
        // Returns false when the global is unreadable; *out is 0 when unset.
        bool read_image_global_pointer(std::uintptr_t rva, std::uint64_t* out)
        {
            if (out) *out = 0;
            if (!g_image || !out) return false;
            return safe_read_u64(g_image + rva, 0, out);
        }

        bool image_global_is_live(std::uintptr_t rva)
        {
            std::uint64_t value = 0;
            return read_image_global_pointer(rva, &value) && is_readable_process_pointer(value);
        }

        bool image_contains(std::uint64_t address, std::size_t size)
        {
            if (!g_image || size == 0 || size > kExpectedImageSize) return false;
            const auto start = reinterpret_cast<std::uint64_t>(g_image);
            return address >= start && address - start <= kExpectedImageSize - size;
        }

        // Read-only mirror of CurrentTargetGuid's own reads. Nothing is called.
        // Callable only when every link is readable, the interface vtable lies
        // inside the certified image and its slot points at executable code
        // inside the image.
        TargetChain inspect_current_target_chain(std::uint64_t client, std::uint64_t* entry_out = nullptr)
        {
            if (entry_out) *entry_out = 0;
            if (!is_readable_range(client, kLocalClientTargetHolderOffset + sizeof(std::uint64_t)))
                return TargetChain::Invalid;
            std::uint64_t holder = 0;
            if (!safe_read_u64(reinterpret_cast<const void*>(client), kLocalClientTargetHolderOffset, &holder))
                return TargetChain::Invalid;
            if (holder == 0) return TargetChain::NoTarget;
            if (!is_readable_range(holder, kTargetHolderIndexOffset + sizeof(std::uint32_t)))
                return TargetChain::Invalid;
            const auto* holder_pointer = reinterpret_cast<const void*>(holder);
            std::uint32_t raw_index = 0;
            std::uint32_t raw_count = 0;
            std::uint64_t array = 0;
            if (!safe_read_u32(holder_pointer, kTargetHolderIndexOffset, &raw_index)
                || !safe_read_u32(holder_pointer, kTargetHolderCountOffset, &raw_count)
                || !safe_read_u64(holder_pointer, kTargetHolderArrayOffset, &array))
            {
                return TargetChain::Invalid;
            }
            const auto index = static_cast<std::int32_t>(raw_index);
            const auto count = static_cast<std::int32_t>(raw_count);
            if (count < 0 || count > kMaxTargetHolderCount) return TargetChain::Invalid;
            if (index < 0 || index >= count) return TargetChain::NoTarget;
            if (!is_readable_process_pointer(array)) return TargetChain::Invalid;
            const std::uint64_t slot = array + static_cast<std::uint64_t>(index) * sizeof(std::uint64_t);
            std::uint64_t entry = 0;
            if (!is_readable_range(slot, sizeof(std::uint64_t))
                || !safe_read_u64(reinterpret_cast<const void*>(slot), 0, &entry))
            {
                return TargetChain::Invalid;
            }
            if (entry == 0) return TargetChain::NoTarget;
            std::uint64_t vtable = 0;
            if (!is_readable_range(entry, kTargetEntryInterfaceOffset + sizeof(std::uint64_t))
                || !safe_read_u64(reinterpret_cast<const void*>(entry), kTargetEntryInterfaceOffset, &vtable))
            {
                return TargetChain::Invalid;
            }
            constexpr std::size_t vtable_span = kTargetInterfaceGuidSlotOffset + sizeof(std::uint64_t);
            std::uint64_t target = 0;
            if (!image_contains(vtable, vtable_span)
                || !is_readable_region(reinterpret_cast<const void*>(vtable), vtable_span, false)
                || !safe_read_u64(reinterpret_cast<const void*>(vtable), kTargetInterfaceGuidSlotOffset, &target))
            {
                return TargetChain::Invalid;
            }
            if (!image_contains(target, 1)
                || !is_readable_region(reinterpret_cast<const void*>(target), 1, true))
            {
                return TargetChain::Invalid;
            }
            if (entry_out) *entry_out = entry;
            return TargetChain::Callable;
        }

        // Read only: the current target's actor stat, as the client carry-limit
        // function 0x1CC3630 reads it ([entry + 0x118 + stat * 4], float).
        bool read_target_actor_stat(std::uint32_t stat, float* value_out)
        {
            if (value_out) *value_out = 0.0F;
            if (!value_out || stat == 0 || stat > 0xFF) return false;
            std::uint64_t client = 0;
            if (!read_image_global_pointer(kBucketSingletonRva, &client)
                || !is_readable_range(client, kLocalClientAllocationSize))
            {
                return false;
            }
            std::uint64_t entry = 0;
            if (inspect_current_target_chain(client, &entry) != TargetChain::Callable || entry == 0)
                return false;
            const std::uint64_t address = entry + kTargetEntryStatArrayOffset
                + static_cast<std::uint64_t>(stat) * sizeof(float);
            std::uint32_t raw = 0;
            if (!is_readable_range(address, sizeof(raw))
                || !safe_read_u32(reinterpret_cast<const void*>(address), 0, &raw))
            {
                return false;
            }
            std::memcpy(value_out, &raw, sizeof(raw));
            return true;
        }

        // Read only: the server-frame index of the request queue.
        bool read_server_frame(std::uint32_t* frame_out)
        {
            if (frame_out) *frame_out = 0;
            std::uint64_t queue = 0;
            if (!frame_out || !read_image_global_pointer(kRequestQueueSingletonRva, &queue)
                || !is_readable_range(queue, kRequestQueueFrameOffset + sizeof(std::uint32_t)))
            {
                return false;
            }
            return safe_read_u32(reinterpret_cast<const void*>(queue), kRequestQueueFrameOffset, frame_out);
        }

        // GameThread only. Marks the frame index live once it changes.
        bool sample_server_frame(std::uint32_t* frame_out = nullptr)
        {
            std::uint32_t frame = 0;
            if (!read_server_frame(&frame))
            {
                g_server_frame_known.store(false, std::memory_order_release);
                return false;
            }
            const bool had = g_server_frame_known.exchange(true, std::memory_order_acq_rel);
            const std::uint32_t previous = g_server_frame_last.exchange(frame, std::memory_order_acq_rel);
            if (had && previous != frame) g_server_frame_live.store(true, std::memory_order_release);
            if (frame_out) *frame_out = frame;
            return true;
        }

        bool leaf_is(std::wstring_view path, const wchar_t* expected)
        {
            const std::wstring_view leaf = sbcore::paths::leaf_name(path);
            return !leaf.empty() && expected && sbcore::paths::equals_ignore_case(leaf, expected);
        }

        bool is_plain_directory(const std::wstring& path)
        {
            const DWORD attributes = GetFileAttributesW(path.c_str());
            return attributes != INVALID_FILE_ATTRIBUTES
                && (attributes & FILE_ATTRIBUTE_DIRECTORY) != 0
                && (attributes & FILE_ATTRIBUTE_REPARSE_POINT) == 0;
        }

        std::wstring g_fault_log_path;
        std::wstring g_exe_path;

        // P1: every path is derived from this DLL's own location,
        // ...\ue4ss\Mods\SBLiveAddNative\dlls\main.dll (sbcore::paths checks
        // the dlls / Mods layout); nothing names an install folder.
        bool resolve_runtime_paths()
        {
            sbcore::paths::ModulePaths paths;
            if (sbcore::paths::resolve_this_module(paths, true) != sbcore::paths::Error::None) return false;
            if (!leaf_is(paths.dll_path, L"main.dll")
                || !leaf_is(paths.dll_dir, L"dlls")
                || !leaf_is(paths.mod_dir, L"SBLiveAddNative")
                || !leaf_is(paths.mods_dir, L"Mods")
                || !is_plain_directory(paths.dll_dir)
                || !is_plain_directory(paths.mod_dir)
                || !is_plain_directory(paths.mods_dir))
            {
                return false;
            }
            if (!leaf_is(paths.panel_dir, L"SBCheatGUI")
                || !is_plain_directory(paths.panel_dir)) return false;
            g_mod_directory = paths.mod_dir;
            g_exe_path = paths.exe_path;
            g_request_path = paths.in_panel(L"live_add_native_request.txt");
            g_request_claim_path = paths.in_panel(L"live_add_native_request.claimed");
            g_result_path = paths.in_panel(L"live_add_native_result.txt");
            g_heartbeat_path = paths.in_panel(L"live_add_native_heartbeat.txt");
            g_lease_path = paths.in_panel(L"live_add_native_lease.txt");
            g_probe_request_path = paths.in_panel(L"live_add_native_probe_request.txt");
            g_probe_claim_path = paths.in_panel(L"live_add_native_probe_request.claimed");
            g_probe_result_path = paths.in_panel(L"live_add_native_probe_result.txt");
            g_status_path = paths.in_mod(L"live_add_native_status.txt");
            g_status_temp_path = paths.in_mod(L"live_add_native_status.tmp");
            g_fault_log_path = paths.in_mod(L"sbcore_faults.log");
            for (const std::wstring* claim : {&g_request_claim_path, &g_probe_claim_path})
            {
                const DWORD claim_attributes = GetFileAttributesW(claim->c_str());
                if (claim_attributes != INVALID_FILE_ATTRIBUTES
                    && ((claim_attributes & FILE_ATTRIBUTE_DIRECTORY) != 0
                        || DeleteFileW(claim->c_str()) == FALSE))
                {
                    return false;
                }
            }
            return true;
        }

        // A12 writers and the A13 lease reader, on the resolved paths.
        bool configure_files()
        {
            sbcore::status::Publisher::Options status_options{};
            status_options.module = kModuleName;
            status_options.module_version = kVersion;
            status_options.beat_ms = kStatusBeatMs;
            status_options.min_interval_ms = kStatusMinIntervalMs;
            sbcore::status::StableReader::Options lease_options{};
            lease_options.max_bytes = kSmallFileMax;
            return g_result_writer.configure(g_result_path, g_result_path + L".tmp")
                && g_heartbeat_writer.configure(g_heartbeat_path, g_heartbeat_path + L".tmp")
                && g_probe_writer.configure(g_probe_result_path, g_probe_result_path + L".tmp")
                && g_status_publisher.configure(status_options, g_status_path, g_status_temp_path)
                && g_lease_reader.configure(g_lease_path, lease_options);
        }

        // A9 stage 1: persistent breadcrumbs + the process-wide write block.
        bool init_fault_capture()
        {
            sbcore::fault::Config config{};
            config.native_name = kModuleName;
            config.native_version = kVersion;
            config.log_path = g_fault_log_path;
            config.policy = sbcore::fault::Policy::ContinueFeatureOff;
            return sbcore::fault::init(config);
        }

        bool verify_module_file_sha256(
            HMODULE module, const wchar_t* expected_leaf,
            std::uint64_t expected_file_size, std::uint32_t expected_timestamp,
            std::uint32_t expected_image_size,
            const std::array<std::uint8_t, 32>& expected_sha256)
        {
            if (!module || !expected_leaf) return false;
            auto* image = reinterpret_cast<std::byte*>(module);
            if (!is_readable_region(image, sizeof(IMAGE_DOS_HEADER), false)) return false;
            const auto* dos = reinterpret_cast<const IMAGE_DOS_HEADER*>(image);
            if (dos->e_magic != IMAGE_DOS_SIGNATURE || dos->e_lfanew <= 0) return false;
            const auto* nt = reinterpret_cast<const IMAGE_NT_HEADERS64*>(image + dos->e_lfanew);
            if (!is_readable_region(nt, sizeof(*nt), false)
                || nt->Signature != IMAGE_NT_SIGNATURE
                || nt->FileHeader.Machine != IMAGE_FILE_MACHINE_AMD64
                || nt->FileHeader.TimeDateStamp != expected_timestamp
                || nt->OptionalHeader.SizeOfImage != expected_image_size)
            {
                return false;
            }
            std::array<wchar_t, 32768> path{};
            const DWORD path_length = GetModuleFileNameW(
                module, path.data(), static_cast<DWORD>(path.size()));
            if (path_length == 0 || path_length >= path.size()
                || !leaf_is(std::wstring(path.data(), path_length),
                            expected_leaf))
            {
                return false;
            }
            HANDLE file = CreateFileW(
                path.data(), GENERIC_READ, FILE_SHARE_READ | FILE_SHARE_DELETE,
                nullptr, OPEN_EXISTING,
                FILE_ATTRIBUTE_NORMAL | FILE_FLAG_OPEN_REPARSE_POINT
                    | FILE_FLAG_SEQUENTIAL_SCAN,
                nullptr);
            if (file == INVALID_HANDLE_VALUE) return false;
            BY_HANDLE_FILE_INFORMATION information{};
            LARGE_INTEGER file_size{};
            const bool file_identity_ok = GetFileInformationByHandle(file, &information)
                && (information.dwFileAttributes
                    & (FILE_ATTRIBUTE_DIRECTORY | FILE_ATTRIBUTE_REPARSE_POINT)) == 0
                && information.nNumberOfLinks == 1
                && GetFileSizeEx(file, &file_size)
                && file_size.QuadPart == static_cast<LONGLONG>(expected_file_size);
            if (!file_identity_ok)
            {
                CloseHandle(file);
                return false;
            }

            BCRYPT_ALG_HANDLE algorithm = nullptr;
            BCRYPT_HASH_HANDLE hash = nullptr;
            PUCHAR hash_object = nullptr;
            PUCHAR read_buffer = nullptr;
            bool verified = false;
            do
            {
                if (!BCRYPT_SUCCESS(BCryptOpenAlgorithmProvider(
                        &algorithm, BCRYPT_SHA256_ALGORITHM, nullptr, 0))) break;
                DWORD object_length = 0;
                DWORD hash_length = 0;
                DWORD property_size = 0;
                if (!BCRYPT_SUCCESS(BCryptGetProperty(
                        algorithm, BCRYPT_OBJECT_LENGTH,
                        reinterpret_cast<PUCHAR>(&object_length), sizeof(object_length),
                        &property_size, 0))
                    || property_size != sizeof(object_length)
                    || object_length == 0 || object_length > 1'048'576)
                {
                    break;
                }
                if (!BCRYPT_SUCCESS(BCryptGetProperty(
                        algorithm, BCRYPT_HASH_LENGTH,
                        reinterpret_cast<PUCHAR>(&hash_length), sizeof(hash_length),
                        &property_size, 0))
                    || property_size != sizeof(hash_length)
                    || hash_length != expected_sha256.size())
                {
                    break;
                }
                hash_object = static_cast<PUCHAR>(
                    HeapAlloc(GetProcessHeap(), HEAP_ZERO_MEMORY, object_length));
                constexpr DWORD kReadBufferSize = 1'048'576;
                read_buffer = static_cast<PUCHAR>(
                    HeapAlloc(GetProcessHeap(), 0, kReadBufferSize));
                if (!hash_object || !read_buffer) break;
                if (!BCRYPT_SUCCESS(BCryptCreateHash(
                        algorithm, &hash, hash_object, object_length,
                        nullptr, 0, 0))) break;
                std::uint64_t total = 0;
                bool read_ok = true;
                while (total < expected_file_size)
                {
                    DWORD bytes_read = 0;
                    if (!ReadFile(file, read_buffer, kReadBufferSize, &bytes_read, nullptr)
                        || bytes_read == 0
                        || total + bytes_read > expected_file_size
                        || !BCRYPT_SUCCESS(BCryptHashData(hash, read_buffer, bytes_read, 0)))
                    {
                        read_ok = false;
                        break;
                    }
                    total += bytes_read;
                }
                if (!read_ok || total != expected_file_size) break;
                std::array<std::uint8_t, 32> digest{};
                if (!BCRYPT_SUCCESS(BCryptFinishHash(
                        hash, digest.data(), static_cast<ULONG>(digest.size()), 0))) break;
                verified = digest == expected_sha256;
            } while (false);

            if (hash) BCryptDestroyHash(hash);
            if (hash_object) HeapFree(GetProcessHeap(), 0, hash_object);
            if (read_buffer) HeapFree(GetProcessHeap(), 0, read_buffer);
            if (algorithm) BCryptCloseAlgorithmProvider(algorithm, 0);
            CloseHandle(file);
            return verified;
        }

        // The exe must be SB-Win64-Shipping.exe with the certified SHA-256.
        // The digest is computed once per process and shared by every sbcore
        // native (sbcore::exe_identity; reused only if the file identity is
        // unchanged). Reparse points, hard links and size mismatches are
        // refused before hashing.
        bool verify_executable_identity()
        {
            if (!leaf_is(g_exe_path, L"SB-Win64-Shipping.exe")) return false;
            g_exe_identity = sbcore::exe_identity::verify_sha256(
                nullptr, kExpectedExecutableFileSize, kExpectedExecutableSha256);
            g_exe_identity_checked.store(true, std::memory_order_release);
            return g_exe_identity.result == sbcore::exe_identity::Result::Match;
        }

        bool image_pointer_equals(const void* slot, const std::byte* image, std::uintptr_t rva)
        {
            std::uint64_t value = 0;
            return is_readable_region(slot, sizeof(void*), false)
                && safe_read_u64(slot, 0, &value)
                && value == reinterpret_cast<std::uint64_t>(image + rva);
        }

        // Checks sbcore's manifest types cannot express: the RPC _Validate
        // slot must point at 0xE340E0 (a leaf without a .pdata entry, so not
        // a SlotCheck). Returns nullptr or the v0.3.1 check name.
        const char* private_gate_failure(const std::byte* image)
        {
            if (!image) return "image";
            if (!image_pointer_equals(image + kControllerVtableRva + kServerAddValidateSlotOffset,
                                      image, kAlwaysTrueValidateRva))
            {
                return "controller_vtable";
            }
            return nullptr;
        }

        // This module's own checks without sbcore's PE / file-size / core
        // stages: every code region, both vtables and every global v0.3.1
        // checked, in the same order and under the same names. Returns
        // nullptr on success or the name of the first failed check. Reads only.
        const char* verify_image_signatures(const std::byte* image)
        {
            if (!image) return "image";
            for (const auto& check : kLiveAddCode)
            {
                if (sbcore::gate::validate_code_check(image, check) != sbcore::gate::Reason::None) return check.name;
            }
            for (const auto& check : kLiveAddSlots)
            {
                if (sbcore::gate::validate_slot_check(image, check) != sbcore::gate::Reason::None) return check.name;
            }
            if (const char* failed = private_gate_failure(image)) return failed;
            for (const auto& check : kLiveAddGlobals)
            {
                if (sbcore::gate::validate_global_check(image, check) != sbcore::gate::Reason::None) return check.name;
            }
            return nullptr;
        }

        // The whole exact-build gate, validate-all-before-anything: sbcore's
        // PE identity, exe file size, TaskGraph core manifest and legacy
        // exact images, then this module's manifest and private checks, then
        // the exe SHA-256; only then is the GameThread dispatcher bound and
        // the image handed to the game-code wrappers.
        bool resolve_exact_build()
        {
            static const sbcore::gate::Manifest* const kExtraManifests[] = {&kLiveAddManifest};
            g_gate_result = sbcore::gate::validate_running_process(kExtraManifests, 1);
            if (!g_gate_result.passed)
            {
                g_gate_failed_check.store(g_gate_result.failed_check[0] ? g_gate_result.failed_check : "gate",
                                          std::memory_order_release);
                return false;
            }
            std::byte* image = g_gate_result.image;
            if (const char* failed = private_gate_failure(image))
            {
                g_gate_failed_check.store(failed, std::memory_order_release);
                return false;
            }
            if (!verify_executable_identity())
            {
                g_gate_failed_check.store("executable_identity", std::memory_order_release);
                return false;
            }
            if (!sbcore::dispatch::bind(g_gate_result))
            {
                g_gate_failed_check.store("dispatch_bind", std::memory_order_release);
                return false;
            }
            g_image = image;
            g_gate_failed_check.store("none", std::memory_order_release);
            g_gate_passed.store(true, std::memory_order_release);
            return true;
        }

        std::uint64_t unix_time_ms()
        {
            return sbcore::lease::unix_time_ms();
        }

        void generate_session()
        {
            std::array<unsigned char, 16> bytes{};
            for (auto& byte : bytes)
            {
                unsigned int value{};
                if (rand_s(&value) != 0)
                {
                    value = static_cast<unsigned int>(
                        GetTickCount64() ^ reinterpret_cast<std::uintptr_t>(&byte));
                }
                byte = static_cast<unsigned char>(value & 0xFFU);
            }
            static constexpr char kHex[] = "0123456789abcdef";
            std::string session;
            session.reserve(32);
            for (unsigned char byte : bytes)
            {
                session.push_back(kHex[(byte >> 4) & 0x0F]);
                session.push_back(kHex[byte & 0x0F]);
            }
            AcquireSRWLockExclusive(&g_session_lock);
            g_session = session;
            ReleaseSRWLockExclusive(&g_session_lock);
        }

        std::string session_copy()
        {
            AcquireSRWLockShared(&g_session_lock);
            const std::string copy = g_session;
            ReleaseSRWLockShared(&g_session_lock);
            return copy;
        }

        // A12 reader: FILE_SHARE_READ|WRITE|DELETE, reparse points, hard
        // links, directories, empty, oversized and NUL-containing files refused.
        bool read_small_file(const std::wstring& path, std::string& output)
        {
            const auto result = sbcore::status::read_small_file(path, output, kSmallFileMax);
            g_last_request_read.store(result, std::memory_order_release);
            return result == sbcore::status::ReadResult::Ok;
        }

        bool valid_hex_token(std::string_view token, std::size_t min, std::size_t max)
        {
            if (token.size() < min || token.size() > max) return false;
            return std::all_of(token.begin(), token.end(), [](char c) {
                return (c >= '0' && c <= '9') || (c >= 'a' && c <= 'f') || (c >= 'A' && c <= 'F');
            });
        }

        // Canonical unsigned decimal only: no sign, whitespace, prefix, or
        // leading zero, at most 20 digits, and no overflow.
        bool parse_unsigned(std::string_view text, std::uint64_t& value)
        {
            if (text.empty() || text.size() > 20) return false;
            if (!std::all_of(text.begin(), text.end(), [](char c) {
                    return c >= '0' && c <= '9';
                })) return false;
            if (text.size() > 1 && text.front() == '0') return false;
            std::uint64_t parsed{};
            const auto result = std::from_chars(
                text.data(), text.data() + text.size(), parsed, 10);
            if (result.ec != std::errc{} || result.ptr != text.data() + text.size())
                return false;
            value = parsed;
            return true;
        }

                                                                           
        // splits off an alias (FName::Init -> ParseNumber, 0x294D9C0, called
        // by the gated kFNameFromWideRva body). A trailing "_<digits>" with
        // 1..10 digits, not the whole name, and no leading zero unless it is
        // the single digit "0", whose value is below 0x7FFFFFFF, becomes the
        // number value + 1 and leaves the name without it: "BS_11" is
        // ("BS", 12) and "BS_09_2" is ("BS_09", 3), while "BS_01" and
        // "Can_033" keep number 0. The item table keys its rows by these
        // FNames (108 of the 770 rows carry a number), so a row is found only
        // with the number. Pure.
        constexpr std::uint32_t fname_number_of(std::string_view name)
        {
            std::size_t digits = 0;
            while (digits < name.size() && name[name.size() - 1 - digits] >= '0'
                   && name[name.size() - 1 - digits] <= '9')
            {
                ++digits;
            }
            if (digits == 0 || digits >= name.size() || digits > 10 || name[name.size() - 1 - digits] != '_') return 0;
            const std::size_t first = name.size() - digits;
            if (digits != 1 && name[first] == '0') return 0;
            std::uint64_t value = 0;
            for (std::size_t index = first; index < name.size(); ++index)
                value = value * 10 + static_cast<std::uint64_t>(name[index] - '0');
            if (value >= 0x7FFFFFFFULL) return 0;
            return static_cast<std::uint32_t>(value + 1);
        }
        static_assert(fname_number_of("BS_11") == 12 && fname_number_of("BS_09_2") == 3
                      && fname_number_of("BS_01") == 0 && fname_number_of("Can_033") == 0
                      && fname_number_of("BS_0") == 1 && fname_number_of("BS11") == 0 && fname_number_of("_5") == 6
                      && fname_number_of("5") == 0 && fname_number_of("X_2147483646") == 0x7FFFFFFF
                      && fname_number_of("X_2147483647") == 0 && fname_number_of("X_12345678901") == 0);

        // Pure: the FName (comparison index | number << 32) an FNAME_Find of
        // alias returned. Accepted only when its number is exactly the one
        // the alias text implies, so the name always stands for the whole
        // alias (v0.3.0-v0.5.0 required number 0 and so could not name any
        // numbered item row). *name_out is 0 when the name is not in the pool.
        bool accept_found_fname(std::string_view alias, std::uint64_t resolved, std::uint32_t none_index,
                                std::uint64_t* name_out)
        {
            if (!name_out) return false;
            *name_out = 0;
            const auto comparison_index = static_cast<std::uint32_t>(resolved);
            const auto number = static_cast<std::uint32_t>(resolved >> 32U);
            const std::uint32_t expected_number = fname_number_of(alias);
            if (comparison_index == none_index || comparison_index == 0)
                return number == 0 || number == expected_number;
            if (number != expected_number) return false;
            *name_out = resolved;
            return true;
        }

        // FNAME_Find (0) is lookup-only; it never inserts a name. Returns
        // false on exception, a malformed alias or an unexpected number;
        // *name_out is the whole FName (with its number), 0 when the name
        // does not exist in the name pool.
        bool lookup_alias_fname(std::string_view alias, std::uint64_t* name_out)
        {
            if (name_out) *name_out = 0;
            if (!g_image || !name_out || alias.empty() || alias.size() >= 129) return false;
            std::array<wchar_t, 129> wide_alias{};
            for (std::size_t index = 0; index < alias.size(); ++index)
            {
                const unsigned char character = static_cast<unsigned char>(alias[index]);
                if (character < 0x20 || character > 0x7E) return false;
                wide_alias[index] = static_cast<wchar_t>(character);
            }
            std::uint64_t resolved_name = 0;
            std::uint64_t* returned = nullptr;
            auto* fname_from_wide = reinterpret_cast<FNameFromWideFn>(
                g_image + kFNameFromWideRva);
            if (!enter_game_code()) return false;
#if defined(_MSC_VER)
            __try
            {
#endif
                returned = fname_from_wide(&resolved_name, wide_alias.data(), 0);
#if defined(_MSC_VER)
            }
            __except (sbcore::fault::filter(GetExceptionInformation(), "exception_in_fname_find"))
            {
                sbcore::fault::after_handler();
                game_code_exception("exception_in_fname_find", GetExceptionCode());
                return false;
            }
#endif
            std::uint32_t none_index = 0;
            if (!safe_read_u32(g_image + kNoneFNameIndexRva, 0, &none_index)) return false;
            if (returned != &resolved_name) return false;
            return accept_found_fname(alias, resolved_name, none_index, name_out);
        }

        // The bridge's FName index must be exactly the comparison index a
        // lookup-only FNAME_Find of an addable allowlisted alias returns. The
        // whole FName (with the number the alias text implies) is this
        // module's own lookup, never the bridge's.
        bool resolve_allowed_alias_name(std::string_view alias, std::uint32_t claimed_index,
                                        std::uint64_t* name_out)
        {
            if (name_out) *name_out = 0;
            const AllowedItem* item = find_allowed_item(alias);
            if (!g_image || !name_out || claimed_index == 0 || !item || !item_group_addable(item->group)
                || alias.empty() || alias.size() >= 129)
            {
                return false;
            }
            std::uint64_t resolved = 0;
            if (!lookup_alias_fname(alias, &resolved) || resolved == 0
                || static_cast<std::uint32_t>(resolved) != claimed_index)
            {
                return false;
            }
            *name_out = resolved;
            return true;
        }

        bool request_expired(const PendingAdd& request)
        {
            return request.expires_tick == 0 || GetTickCount64() >= request.expires_tick;
        }

        struct SparseMapHeader
        {
            std::uint64_t data{};
            std::int32_t num{};
            std::int32_t max{};
            std::int32_t num_free{};
            std::uint64_t hash_heap{};
            std::int32_t hash_size{};
        };

        // Pure invariant check of one TSparseArray/TSet header. *empty is set
        // when the game's lookup returns before touching elements or hash.
        bool sparse_map_header_valid(const SparseMapHeader& header, bool* empty)
        {
            if (empty) *empty = false;
            if (header.num < 0 || header.max < header.num || header.max > kMaxSparseMapEntries
                || header.num_free < 0 || header.num_free > header.num)
            {
                return false;
            }
            const bool is_empty = header.num == header.num_free;
            if (empty) *empty = is_empty;
            if (is_empty) return true;
            if (header.data < 0x10000ULL || header.data > 0x7FFFFFFFFFFFULL) return false;
            if (header.hash_size <= 0 || header.hash_size > kMaxSparseMapEntries
                || (header.hash_size & (header.hash_size - 1)) != 0)
            {
                return false;
            }
            if (header.hash_heap != 0
                && (header.hash_heap < 0x10000ULL || header.hash_heap > 0x7FFFFFFFFFFFULL))
            {
                return false;
            }
            // TSet hash storage is TInlineAllocator<1>: inline only for one slot.
            if (header.hash_heap == 0 && header.hash_size != 1) return false;
            return true;
        }

        bool read_sparse_map_header(std::uint64_t manager, const SparseMapLayout& layout,
                                    SparseMapHeader* header)
        {
            const auto* base = reinterpret_cast<const void*>(manager);
            std::uint32_t num = 0, max = 0, num_free = 0, hash_size = 0;
            if (!safe_read_u64(base, layout.data, &header->data)
                || !safe_read_u32(base, layout.num, &num)
                || !safe_read_u32(base, layout.max, &max)
                || !safe_read_u32(base, layout.num_free, &num_free)
                || !safe_read_u64(base, layout.hash_heap, &header->hash_heap)
                || !safe_read_u32(base, layout.hash_size, &hash_size))
            {
                return false;
            }
            header->num = static_cast<std::int32_t>(num);
            header->max = static_cast<std::int32_t>(max);
            header->num_free = static_cast<std::int32_t>(num_free);
            header->hash_size = static_cast<std::int32_t>(hash_size);
            return true;
        }

        // Read-only validation of the manager map headers used by the gated
        // lookup functions. Returns false on a structural violation; *has_entries
        // is false while either map is empty (lobby, loading).
        bool validate_inventory_manager(std::uint64_t manager, bool* has_entries)
        {
            if (has_entries) *has_entries = false;
            if (!is_readable_range(manager, kTypeTargetMap.hash_size + sizeof(std::uint32_t)))
                return false;
            bool all_present = true;
            for (const SparseMapLayout* layout : {&kPrimaryBucketMap, &kTypeTargetMap})
            {
                SparseMapHeader header{};
                bool empty = false;
                if (!read_sparse_map_header(manager, *layout, &header)
                    || !sparse_map_header_valid(header, &empty))
                {
                    return false;
                }
                if (layout == &kPrimaryBucketMap)
                    g_self_check_primary_entries.store(
                        static_cast<std::uint32_t>(header.num - header.num_free), std::memory_order_release);
                else
                    g_self_check_type_entries.store(
                        static_cast<std::uint32_t>(header.num - header.num_free), std::memory_order_release);
                if (empty)
                {
                    all_present = false;
                    continue;
                }
                const std::uint64_t element_bytes =
                    static_cast<std::uint64_t>(header.num) * layout->element_stride;
                const std::uint64_t hash_storage = header.hash_heap != 0
                    ? header.hash_heap : manager + layout->hash_inline;
                if (!is_readable_range(header.data, static_cast<std::size_t>(element_bytes))
                    || !is_readable_range(hash_storage,
                                          static_cast<std::size_t>(header.hash_size) * sizeof(std::int32_t)))
                {
                    return false;
                }
            }
            if (has_entries) *has_entries = all_present;
            return true;
        }

        // Resolves the local player's inventory bucket through game-owned
        // lookups only. The local client singleton is read directly and must
        // be live and readable for its whole allocation before CurrentTargetGuid
        // (whose getter would otherwise allocate it) is called, and the
        // CurrentTargetGuid chain must be inspected Callable first. Only
        // reached from the self-check, from refresh_bucket after the
        // self-check passed, and from execute_add/execute_verify.
        void* find_inventory_bucket(std::uint32_t* bucket_guid_out,
                                    std::uint32_t* target_guid_out,
                                    BucketStatus* status_out = nullptr)
        {
            if (bucket_guid_out) *bucket_guid_out = 0;
            if (target_guid_out) *target_guid_out = 0;
            auto set_status = [&](BucketStatus status) {
                if (status_out) *status_out = status;
            };
            set_status(BucketStatus::Absent);
            if (!enter_game_code()) return nullptr;
            std::uint64_t singleton = 0;
            if (!read_image_global_pointer(kBucketSingletonRva, &singleton)
                || !is_readable_process_pointer(singleton)) return nullptr;
            if (!is_readable_range(singleton, kLocalClientAllocationSize))
            {
                set_status(BucketStatus::Inconsistent);
                return nullptr;
            }
            std::uint64_t manager = 0;
            if (!safe_read_u64(reinterpret_cast<void*>(singleton), kLocalClientInventoryManagerOffset, &manager)
                || !is_readable_process_pointer(manager)) return nullptr;
            bool has_entries = false;
            if (!validate_inventory_manager(manager, &has_entries))
            {
                set_status(BucketStatus::Inconsistent);
                return nullptr;
            }
            if (!has_entries) return nullptr;
            const TargetChain chain = inspect_current_target_chain(singleton);
            if (chain == TargetChain::Invalid)
            {
                disable_game_code("current_target_chain");
                set_status(BucketStatus::TargetChain);
                return nullptr;
            }
            if (chain != TargetChain::Callable) return nullptr;
            auto* current_target_guid = reinterpret_cast<CurrentTargetGuidFn>(
                g_image + kCurrentTargetGuidRva);
            auto* find_bucket = reinterpret_cast<FindInventoryBucketFn>(
                g_image + kFindInventoryBucketRva);
            auto* primary_lookup = reinterpret_cast<PrimaryBucketLookupFn>(
                g_image + kPrimaryBucketLookupRva);
            std::uint32_t target_guid = 0;
            void* bucket = nullptr;
#if defined(_MSC_VER)
            __try
            {
#endif
                target_guid = current_target_guid();
                if (target_guid != 0)
                {
                    bucket = find_bucket(reinterpret_cast<void*>(manager), 1, target_guid);
                }
#if defined(_MSC_VER)
            }
            __except (sbcore::fault::filter(GetExceptionInformation(), "exception_in_find_inventory_bucket"))
            {
                sbcore::fault::after_handler();
                game_code_exception("exception_in_find_inventory_bucket", GetExceptionCode());
                set_status(BucketStatus::Exception);
                return nullptr;
            }
#endif
            if (target_guid == 0 || bucket == nullptr) return nullptr;
            if (!is_readable_range(reinterpret_cast<std::uint64_t>(bucket),
                                   kBucketTargetGuidOffset + sizeof(std::uint32_t)))
            {
                set_status(BucketStatus::Inconsistent);
                return nullptr;
            }
            std::uint32_t bucket_guid = 0;
            std::uint32_t bucket_type = 0;
            std::uint32_t bucket_target_guid = 0;
            if (!safe_read_u32(bucket, kBucketGuidOffset, &bucket_guid)
                || !safe_read_u32(bucket, kBucketTypeOffset, &bucket_type)
                || !safe_read_u32(bucket, kBucketTargetGuidOffset, &bucket_target_guid)
                || bucket_guid == 0
                || bucket_type != kInventoryBucketType || bucket_target_guid != target_guid)
            {
                set_status(BucketStatus::Inconsistent);
                return nullptr;
            }
            void* primary_bucket = nullptr;
            void* stable_bucket = nullptr;
            void* stable_primary_bucket = nullptr;
            std::uint32_t stable_target_guid = 0;
            const TargetChain stable_chain = inspect_current_target_chain(singleton);
            if (stable_chain != TargetChain::Callable)
            {
                if (stable_chain == TargetChain::Invalid) disable_game_code("current_target_chain");
                set_status(stable_chain == TargetChain::Invalid
                               ? BucketStatus::TargetChain : BucketStatus::Inconsistent);
                return nullptr;
            }
#if defined(_MSC_VER)
            __try
            {
#endif
                primary_bucket = primary_lookup(reinterpret_cast<void*>(manager), bucket_guid);
                stable_target_guid = current_target_guid();
                stable_bucket = find_bucket(
                    reinterpret_cast<void*>(manager), 1, target_guid);
                stable_primary_bucket = primary_lookup(reinterpret_cast<void*>(manager), bucket_guid);
#if defined(_MSC_VER)
            }
            __except (sbcore::fault::filter(GetExceptionInformation(), "exception_in_find_inventory_bucket"))
            {
                sbcore::fault::after_handler();
                game_code_exception("exception_in_find_inventory_bucket", GetExceptionCode());
                set_status(BucketStatus::Exception);
                return nullptr;
            }
#endif
            if (primary_bucket != bucket || stable_primary_bucket != bucket
                || stable_bucket != bucket || stable_target_guid != target_guid)
            {
                set_status(BucketStatus::Inconsistent);
                return nullptr;
            }
            if (bucket_guid_out) *bucket_guid_out = bucket_guid;
            if (target_guid_out) *target_guid_out = target_guid;
            set_status(BucketStatus::Ok);
            return bucket;
        }

        // Game-owned count read. The item table singleton must already be
        // live so the count function's getter takes its read-only fast path.
        // alias_name is the whole FName from lookup_alias_fname (comparison
        // index and number), passed by address as the game passes its own.
        bool read_inventory_count(void* bucket, std::uint64_t alias_name,
                                  std::uint32_t* count_out)
        {
            if (count_out) *count_out = 0;
            if (!bucket || static_cast<std::uint32_t>(alias_name) == 0 || !count_out || !g_image) return false;
            if (!image_global_is_live(kItemTableSingletonRva)) return false;
            auto* get_item_count = reinterpret_cast<GetItemCountByAliasFn>(
                g_image + kGetItemCountByAliasRva);
            std::int32_t signed_count = -1;
            if (!enter_game_code()) return false;
#if defined(_MSC_VER)
            __try
            {
#endif
                signed_count = get_item_count(bucket, &alias_name);
#if defined(_MSC_VER)
            }
            __except (sbcore::fault::filter(GetExceptionInformation(), "exception_in_get_item_count"))
            {
                sbcore::fault::after_handler();
                game_code_exception("exception_in_get_item_count", GetExceptionCode());
                return false;
            }
#endif
            if (signed_count < 0 || signed_count > kMaxPlausibleItemCount) return false;
            *count_out = static_cast<std::uint32_t>(signed_count);
            return true;
        }

        // Game-owned item-table row lookup (FindItemRow). The item table
        // singleton must already be live; the row must be readable for every
        // field this module reads. Returns nullptr for an unknown alias.
        const void* lookup_item_row(std::uint64_t alias_name)
        {
            if (!g_image || static_cast<std::uint32_t>(alias_name) == 0) return nullptr;
            std::uint64_t table = 0;
            if (!read_image_global_pointer(kItemTableSingletonRva, &table)
                || !is_readable_range(table, kItemTableAllocationSize))
            {
                return nullptr;
            }
            auto* row_lookup = reinterpret_cast<ItemRowLookupFn>(g_image + kItemRowLookupRva);
            void* row = nullptr;
            if (!enter_game_code()) return nullptr;
#if defined(_MSC_VER)
            __try
            {
#endif
                row = row_lookup(reinterpret_cast<void*>(table), 0, &alias_name);
#if defined(_MSC_VER)
            }
            __except (sbcore::fault::filter(GetExceptionInformation(), "exception_in_item_row_lookup"))
            {
                sbcore::fault::after_handler();
                game_code_exception("exception_in_item_row_lookup", GetExceptionCode());
                return nullptr;
            }
#endif
            if (!row || !is_readable_range(reinterpret_cast<std::uint64_t>(row), kItemRowSpan)) return nullptr;
            return row;
        }

        std::uint8_t row_u8(const void* row, std::size_t offset)
        {
            std::uint32_t value = 0;
            // Aligned 4-byte read that stays inside the checked row span.
            const std::size_t aligned = offset & ~static_cast<std::size_t>(3);
            if (!safe_read_u32(row, aligned, &value)) return 0;
            return static_cast<std::uint8_t>(value >> ((offset - aligned) * 8U));
        }

        bool fname_is_none(std::uint64_t name, std::uint32_t none_index)
        {
            return static_cast<std::uint32_t>(name) == none_index && (name >> 32U) == 0;
        }

        // The carry limit exactly as the server add computes it for an
        // inventory bucket (0x1BDAB67 redirect, 0x1BE01F0 limit): the row of
        // the item's InventoryAlias when it has one, its MaxAmount, or the
        // actor stat named by MaxAmountOverrideActorStat. Reads only, apart
        // from the game-owned row lookups (which the count read already makes).
        ItemCapacity read_item_capacity(std::uint64_t alias_name)
        {
            ItemCapacity info{};
            std::uint32_t none_index = 0;
            if (!g_image || !safe_read_u32(g_image + kNoneFNameIndexRva, 0, &none_index)) return info;
            if (!image_global_is_live(kItemTableSingletonRva)) return info;
            const void* row = lookup_item_row(alias_name);
            if (!row) return info;
            info.row_found = true;
            std::uint64_t condition_group = 0;
            if (safe_read_u64(row, kItemRowConditionGroupOffset, &condition_group))
                info.condition_group = !fname_is_none(condition_group, none_index);
            const void* effective = row;
            std::uint64_t inventory_alias = 0;
            if (safe_read_u64(row, kItemRowInventoryAliasOffset, &inventory_alias)
                && !fname_is_none(inventory_alias, none_index))
            {
                info.inventory_redirect = true;
                if (const void* inventory_row = lookup_item_row(inventory_alias)) effective = inventory_row;
                if (!game_code_allowed()) return info;
            }
            info.category = row_u8(effective, kItemRowCategoryOffset);
            info.use_on_pickup = row_u8(effective, kItemRowUseOnPickupOffset) != 0;
            info.auto_level_type = row_u8(effective, kItemRowAutoLevelUpTypeOffset);
            std::uint32_t stack_raw = 0;
            info.stack_amount_read = safe_read_u32(effective, kItemRowStackAmountOffset, &stack_raw);
            info.stack_amount = static_cast<std::int32_t>(stack_raw);
            const std::uint32_t stat = row_u8(effective, kItemRowMaxAmountStatOffset);
            info.stat = stat;
            if (stat != 0)
            {
                float value = 0.0F;
                if (!read_target_actor_stat(stat, &value) || !(value >= 0.0F) || value > kMaxPlausibleCarryLimit)
                    return info;
                info.max_source = "actor_stat";
                info.max_value = static_cast<std::uint32_t>(value);
            }
            else
            {
                std::uint32_t raw = 0;
                if (!safe_read_u32(effective, kItemRowMaxAmountOffset, &raw)) return info;
                const auto table_max = static_cast<std::int32_t>(raw);
                info.max_source = "item_table";
                // A negative limit never clamps (the server compares unsigned).
                info.max_value = table_max > 0 ? static_cast<std::uint32_t>(table_max) : 0U;
            }
            info.max_state = info.max_value == 0 ? MaxState::NoLimit : MaxState::Limit;
            return info;
        }

        bool image_c_string_equals(const std::byte* image, std::uint64_t address, const char* expected)
        {
            if (!image || !expected) return false;
            const auto image_start = reinterpret_cast<std::uint64_t>(image);
            const std::size_t length = std::strlen(expected);
            if (address < image_start || address + length + 1 > image_start + kExpectedImageSize
                || !is_readable_region(reinterpret_cast<const void*>(address), length + 1, false))
            {
                return false;
            }
            return std::memcmp(reinterpret_cast<const void*>(address), expected, length + 1) == 0;
        }

        bool image_record_readable(const std::byte* image, std::uint64_t address, std::size_t size)
        {
            const auto image_start = reinterpret_cast<std::uint64_t>(image);
            return address >= image_start && address + size <= image_start + kExpectedImageSize
                && is_readable_region(reinterpret_cast<const void*>(address), size, false);
        }

        template <std::size_t N>
        const char* verify_property_records(const std::byte* image, std::uint64_t array_address,
                                            const std::array<ExpectedProperty, N>& expected,
                                            std::uint32_t outer_size, const char* failure)
        {
            if (!image_record_readable(image, array_address, N * sizeof(std::uint64_t))) return failure;
            for (std::size_t index = 0; index < N; ++index)
            {
                std::uint64_t record = 0;
                std::uint64_t name = 0;
                std::uint32_t gen_flags = 0;
                std::uint32_t array_dim = 0;
                std::uint32_t offset_or_size = 0;
                if (!safe_read_u64(reinterpret_cast<const void*>(array_address), index * 8, &record)
                    || !image_record_readable(image, record, 0x30)
                    || !safe_read_u64(reinterpret_cast<const void*>(record), 0, &name)
                    || !safe_read_u32(reinterpret_cast<const void*>(record), kPropertyGenFlagsField, &gen_flags)
                    || !safe_read_u32(reinterpret_cast<const void*>(record), kPropertyArrayDimField, &array_dim)
                    || !image_c_string_equals(image, name, expected[index].name)
                    || gen_flags != expected[index].gen_flags || array_dim != 1)
                {
                    return failure;
                }
                if (expected[index].gen_flags == kGenFlagsBool)
                {
                    std::uint32_t element_size = 0;
                    std::uint32_t size_of_outer = 0;
                    if (!safe_read_u32(reinterpret_cast<const void*>(record), kBoolPropertyElementSizeField,
                                       &element_size)
                        || !safe_read_u32(reinterpret_cast<const void*>(record), kBoolPropertySizeOfOuterField,
                                          &size_of_outer)
                        || element_size != 1 || size_of_outer != outer_size)
                    {
                        return failure;
                    }
                }
                else if (!safe_read_u32(reinterpret_cast<const void*>(record), kPropertyOffsetField,
                                        &offset_or_size)
                         || offset_or_size != expected[index].offset)
                {
                    return failure;
                }
            }
            return nullptr;
        }

        // Read-only check of the UE4CodeGen reflection records in the loaded
        // image: FSBItemInstanceForRPC must still be 0x80 bytes with the
        // certified field offsets, and ServerRequest_ItemBucketItemAdd must
        // still take the certified nine parameters in a 0xA0-byte frame.
        const char* verify_reflection_layout(const std::byte* image)
        {
            if (!image) return "rpc_reflection_image";
            const auto* struct_record = image + kRpcStructParamsNameFieldRva;
            std::uint64_t struct_name = 0, size_of = 0, align_of = 0, struct_properties = 0;
            std::uint32_t struct_property_count = 0;
            if (!image_record_readable(image, reinterpret_cast<std::uint64_t>(struct_record), 0x28)
                || !safe_read_u64(struct_record, 0, &struct_name)
                || !safe_read_u64(struct_record, kStructParamsSizeOfField, &size_of)
                || !safe_read_u64(struct_record, kStructParamsAlignOfField, &align_of)
                || !safe_read_u64(struct_record, kStructParamsPropertyArrayField, &struct_properties)
                || !safe_read_u32(struct_record, kStructParamsNumPropertiesField, &struct_property_count)
                || struct_name != reinterpret_cast<std::uint64_t>(image + kRpcStructNameRva)
                || !image_c_string_equals(image, struct_name, "SBItemInstanceForRPC"))
            {
                return "rpc_struct_record";
            }
            if (size_of != kRpcItemInstanceSize || align_of != 8
                || struct_property_count != kRpcStructProperties.size())
            {
                return "rpc_struct_size";
            }
            if (const char* failed = verify_property_records(
                    image, struct_properties, kRpcStructProperties,
                    static_cast<std::uint32_t>(kRpcItemInstanceSize), "rpc_struct_fields"))
            {
                return failed;
            }
            const auto* function_record = image + kServerAddFunctionParamsNameFieldRva;
            std::uint64_t function_name = 0, structure_size = 0, function_properties = 0;
            std::uint32_t function_property_count = 0;
            if (!image_record_readable(image, reinterpret_cast<std::uint64_t>(function_record), 0x30)
                || !safe_read_u64(function_record, 0, &function_name)
                || !safe_read_u64(function_record, kFunctionParamsStructureSizeField, &structure_size)
                || !safe_read_u64(function_record, kFunctionParamsPropertyArrayField, &function_properties)
                || !safe_read_u32(function_record, kFunctionParamsNumPropertiesField, &function_property_count)
                || function_name != reinterpret_cast<std::uint64_t>(image + kServerAddFunctionNameRva)
                || !image_c_string_equals(image, function_name, "ServerRequest_ItemBucketItemAdd"))
            {
                return "server_add_function_record";
            }
            if (structure_size != kServerAddParamsSize
                || function_property_count != kServerAddParameters.size()
                || kServerAddParameters.back().offset + kRpcItemInstanceSize != kServerAddParamsSize)
            {
                return "server_add_parameter_frame";
            }
            return verify_property_records(
                image, function_properties, kServerAddParameters,
                static_cast<std::uint32_t>(kServerAddParamsSize), "server_add_parameters");
        }

        struct SnapshotEntry
        {
            std::string_view alias;
            std::uint64_t name{};
            std::uint32_t count{};
            ItemCapacity capacity{};
        };

        void append_limit(std::string& out, const ItemCapacity& capacity)
        {
            if (capacity.max_state == MaxState::Limit) out += std::to_string(capacity.max_value);
            else out += max_state_name(capacity.max_state);
        }

        // alias:count:limit:c<condition>u<use-on-pickup>, comma separated, of
        // every sentinel (the rows the self-check itself read; no game call).
        void capture_alias_snapshot(const SnapshotEntry* entries, std::size_t size)
        {
            std::string text;
            for (std::size_t index = 0; index < size; ++index)
            {
                const ItemCapacity& capacity = entries[index].capacity;
                if (!text.empty()) text += ',';
                text.append(entries[index].alias.data(), entries[index].alias.size());
                text += ':';
                text += std::to_string(entries[index].count);
                text += ':';
                append_limit(text, capacity);
                text += capacity.row_found ? (capacity.condition_group ? ":c1" : ":c0") : ":c?";
                text += capacity.row_found ? (capacity.use_on_pickup ? "u1" : "u0") : "u?";
            }
            if (text.empty()) text = "none";
            AcquireSRWLockExclusive(&g_report_lock);
            g_alias_snapshot = text;
            ReleaseSRWLockExclusive(&g_report_lock);
        }

        void self_check_pending(const char* step)
        {
            g_self_check_step.store(step, std::memory_order_release);
        }

        void self_check_fail(const char* step)
        {
            g_self_check_step.store(step, std::memory_order_release);
            g_self_check_state.store(SelfCheckState::Failed, std::memory_order_release);
            bool expected = false;
            if (g_game_code_disabled.compare_exchange_strong(
                    expected, true, std::memory_order_acq_rel, std::memory_order_acquire))
            {
                g_game_code_disabled_reason.store(step, std::memory_order_release);
            }
        }

        // First-use self-check. Runs only inside the certified GameThread
        // callback, reads only, and must pass before any Add is accepted.
        // Absent game state (lobby/loading) keeps it pending; any structural
        // mismatch fails it for the rest of the session.
        void run_self_check()
        {
            if (g_self_check_state.load(std::memory_order_acquire) != SelfCheckState::Pending) return;
            g_self_check_attempts.fetch_add(1, std::memory_order_relaxed);
            if (!g_self_check_reflection_passed.load(std::memory_order_acquire))
            {
                if (const char* failed = verify_reflection_layout(g_image))
                {
                    self_check_fail(failed);
                    return;
                }
                g_self_check_reflection_passed.store(true, std::memory_order_release);
            }
            std::uint64_t client = 0;
            if (!read_image_global_pointer(kBucketSingletonRva, &client))
            {
                self_check_fail("local_client_global");
                return;
            }
            if (client == 0)
            {
                self_check_pending("local_client_absent");
                return;
            }
            if (!is_readable_range(client, kLocalClientAllocationSize))
            {
                self_check_fail("local_client_unreadable");
                return;
            }
            std::uint64_t manager = 0;
            if (!safe_read_u64(reinterpret_cast<const void*>(client), kLocalClientInventoryManagerOffset, &manager))
            {
                self_check_fail("inventory_manager_pointer");
                return;
            }
            if (manager == 0)
            {
                self_check_pending("inventory_manager_absent");
                return;
            }
            bool has_entries = false;
            if (!validate_inventory_manager(manager, &has_entries))
            {
                self_check_fail("inventory_manager_layout");
                return;
            }
            if (!has_entries)
            {
                self_check_pending("inventory_manager_empty");
                return;
            }
            if (!image_global_is_live(kItemTableSingletonRva))
            {
                self_check_pending("item_table_absent");
                return;
            }
            if (!image_global_is_live(kAddSubsystemSingletonRva))
            {
                self_check_pending("add_subsystem_absent");
                return;
            }
            BucketStatus bucket_status = BucketStatus::Absent;
            std::uint32_t bucket_guid = 0;
            std::uint32_t target_guid = 0;
            void* bucket = find_inventory_bucket(&bucket_guid, &target_guid, &bucket_status);
            if (bucket_status == BucketStatus::Absent)
            {
                self_check_pending("inventory_bucket_absent");
                return;
            }
            if (bucket_status != BucketStatus::Ok || !bucket)
            {
                self_check_fail(bucket_status == BucketStatus::Exception ? "inventory_bucket_exception"
                                : bucket_status == BucketStatus::TargetChain ? "current_target_chain"
                                : "inventory_bucket_identity");
                return;
            }
            g_self_check_bucket_guid.store(bucket_guid, std::memory_order_release);
            g_self_check_target_guid.store(target_guid, std::memory_order_release);
            // C8: one sentinel item per family (item category) of the
            // generated allowlist: its name, two equal count reads, and below
            // its live row, which must still match the catalog.
            std::uint32_t resolved = 0;
            std::uint32_t read = 0;
            std::array<SnapshotEntry, kSentinelItems.size()> snapshot{};
            std::array<std::uint64_t, kSentinelItems.size()> sentinel_names{};
            for (std::size_t position = 0; position < kSentinelItems.size(); ++position)
            {
                const AllowedItem& item = kAllowedItems[kSentinelItems[position]];
                std::uint64_t alias_name = 0;
                if (!lookup_alias_fname(item.alias, &alias_name))
                {
                    self_check_fail("alias_name_lookup");
                    return;
                }
                if (alias_name == 0) continue;
                ++resolved;
                sentinel_names[position] = alias_name;
                std::uint32_t first = 0;
                std::uint32_t second = 0;
                if (!read_inventory_count(bucket, alias_name, &first)
                    || !read_inventory_count(bucket, alias_name, &second)
                    || first != second)
                {
                    self_check_fail("item_count_read");
                    return;
                }
                ++read;
                snapshot[position].alias = item.alias;
                snapshot[position].name = alias_name;
                snapshot[position].count = first;
            }
            g_self_check_aliases_resolved.store(resolved, std::memory_order_release);
            g_self_check_aliases_read.store(read, std::memory_order_release);
            if (resolved == 0)
            {
                self_check_pending("alias_names_absent");
                return;
            }
            // The item table's row names are FNames: once one sentinel name
            // exists they all must (a missing one is a changed game data set).
            if (resolved != kSentinelItems.size())
            {
                self_check_fail("sentinel_name_absent");
                return;
            }
            std::uint32_t stable_bucket_guid = 0;
            std::uint32_t stable_target_guid = 0;
            BucketStatus stable_status = BucketStatus::Absent;
            void* stable_bucket = find_inventory_bucket(&stable_bucket_guid, &stable_target_guid, &stable_status);
            if (stable_status != BucketStatus::Ok || stable_bucket != bucket
                || stable_bucket_guid != bucket_guid || stable_target_guid != target_guid)
            {
                self_check_fail("inventory_bucket_unstable");
                return;
            }
            for (std::size_t position = 0; position < kSentinelItems.size(); ++position)
            {
                const AllowedItem& item = kAllowedItems[kSentinelItems[position]];
                snapshot[position].capacity = read_item_capacity(sentinel_names[position]);
                // A game fault inside the row lookup has already failed the check.
                if (!game_code_allowed()) return;
                if (row_mismatch(item, snapshot[position].capacity) != nullptr
                    || category_hard_denied(snapshot[position].capacity.category))
                {
                    self_check_fail("sentinel_row_mismatch");
                    return;
                }
            }
            for (std::size_t position = 0; position < kSentinelItems.size(); ++position)
                note_item_count(kAllowedItems[kSentinelItems[position]], snapshot[position].count);
            g_sentinel_names = sentinel_names;
            g_sentinels_resolved.store(resolved, std::memory_order_release);
            g_self_check_step.store("passed", std::memory_order_release);
            g_self_check_state.store(SelfCheckState::Passed, std::memory_order_release);
            // Diagnostics only (no game call): every sentinel's count and limit.
            capture_alias_snapshot(snapshot.data(), snapshot.size());
        }

        void clear_published_bucket()
        {
            g_inventory_bucket_guid.store(0, std::memory_order_release);
            g_inventory_target_guid.store(0, std::memory_order_release);
        }

        // GameThread Refresh. After a failed self-check or any game-code
        // fault it calls nothing. While the self-check is pending, the only
        // game calls are the self-check's own, made after its reflection,
        // client-readability and singleton-live steps; the bucket lookup
        // runs on its own only once the self-check has passed.
        void refresh_bucket()
        {
            g_bucket_refresh_count.fetch_add(1, std::memory_order_relaxed);
            if (!game_code_allowed())
            {
                clear_published_bucket();
                return;
            }
            if (!self_check_passed())
            {
                clear_published_bucket();
                run_self_check();
                if (!self_check_passed() || !game_code_allowed()) return;
                g_inventory_bucket_guid.store(
                    g_self_check_bucket_guid.load(std::memory_order_acquire), std::memory_order_release);
                g_inventory_target_guid.store(
                    g_self_check_target_guid.load(std::memory_order_acquire), std::memory_order_release);
                return;
            }
            std::uint32_t bucket_guid = 0;
            std::uint32_t target_guid = 0;
            find_inventory_bucket(&bucket_guid, &target_guid);
            if (!game_code_allowed())
            {
                clear_published_bucket();
                return;
            }
            g_inventory_bucket_guid.store(bucket_guid, std::memory_order_release);
            g_inventory_target_guid.store(target_guid, std::memory_order_release);
            sample_server_frame();
        }

        // Refresh is never scheduled or dispatched once game code is off, and
        // (A13) only while the panel holds a fresh Items lease.
        bool refresh_may_be_scheduled(Action pending_action, bool verify_scheduled)
        {
            return game_code_allowed() && g_panel_lease_fresh.load(std::memory_order_acquire)
                && pending_action == Action::None && !verify_scheduled;
        }

        PendingAdd pending_copy()
        {
            AcquireSRWLockShared(&g_pending_lock);
            const PendingAdd copy = g_pending;
            ReleaseSRWLockShared(&g_pending_lock);
            return copy;
        }

        bool pending_active()
        {
            AcquireSRWLockShared(&g_pending_lock);
            const bool active = g_pending.active;
            ReleaseSRWLockShared(&g_pending_lock);
            return active;
        }

        void clear_pending()
        {
            AcquireSRWLockExclusive(&g_pending_lock);
            g_pending = {};
            ReleaseSRWLockExclusive(&g_pending_lock);
        }

        bool result_slot_empty()
        {
            AcquireSRWLockShared(&g_result_lock);
            const bool empty = !g_pending_result.active;
            ReleaseSRWLockShared(&g_result_lock);
            return empty;
        }

        // Status-only record of the last add attempt.
        void report_start(const PendingAdd& request)
        {
            AcquireSRWLockExclusive(&g_report_lock);
            g_report = {};
            g_report.alias = request.alias;
            g_report.qty_requested = request.qty;
            g_report.outcome = "adding";
            const AllowedItem* item = find_allowed_item(request.alias);
            g_report.group = item ? item_group_name(item->group) : "none";
            ReleaseSRWLockExclusive(&g_report_lock);
        }

        void report_refusal_reason(const char* reason)
        {
            AcquireSRWLockExclusive(&g_report_lock);
            g_report.refusal_reason = reason ? reason : "unknown";
            ReleaseSRWLockExclusive(&g_report_lock);
        }

        void report_watch(std::uint32_t watch_count, std::string_view changed)
        {
            AcquireSRWLockExclusive(&g_report_lock);
            g_report.watch_count = watch_count;
            g_report.watch_changed.assign(changed.data(), changed.size());
            ReleaseSRWLockExclusive(&g_report_lock);
        }

        void report_before(std::uint32_t before, const ItemCapacity& capacity, bool capacity_read)
        {
            AcquireSRWLockExclusive(&g_report_lock);
            g_report.before_known = true;
            g_report.before = before;
            g_report.capacity = capacity;
            g_report.capacity_read = capacity_read;
            ReleaseSRWLockExclusive(&g_report_lock);
        }

        void report_sent(std::uint32_t qty_sent, bool frame_known, std::uint32_t frame)
        {
            AcquireSRWLockExclusive(&g_report_lock);
            g_report.qty_sent = qty_sent;
            g_report.frame_at_add_known = frame_known;
            g_report.frame_at_add = frame;
            ReleaseSRWLockExclusive(&g_report_lock);
        }

        void report_poll(std::uint32_t after, std::uint32_t polls, std::uint64_t window_ms, bool paused_wait)
        {
            AcquireSRWLockExclusive(&g_report_lock);
            g_report.after_known = true;
            g_report.after = after;
            g_report.verify_polls = polls;
            g_report.verify_window_ms = window_ms;
            g_report.paused_wait = paused_wait;
            if (paused_wait) g_report.paused_seen = true;
            ReleaseSRWLockExclusive(&g_report_lock);
        }

        void report_outcome(const char* outcome)
        {
            AcquireSRWLockExclusive(&g_report_lock);
            g_report.outcome = outcome ? outcome : "unknown";
            g_report.paused_wait = false;
            ReleaseSRWLockExclusive(&g_report_lock);
        }

        bool store_result(bool ok, bool terminal, Result result, const PendingAdd& request,
                          std::uint32_t bucket_guid, std::uint32_t before, std::uint32_t after,
                          const char* extra = nullptr)
        {
            AcquireSRWLockExclusive(&g_result_lock);
            // A result is immutable until it has been durably published. Even an
            // identical correlation cannot replace an earlier outcome.
            if (g_pending_result.active)
            {
                ReleaseSRWLockExclusive(&g_result_lock);
                g_dispatch_poisoned.store(true, std::memory_order_release);
                return false;
            }
            g_pending_result.active = true;
            g_pending_result.ok = ok;
            g_pending_result.terminal = terminal;
            g_pending_result.session = request.session;
            g_pending_result.request_id = request.request_id;
            g_pending_result.panel_seq = request.panel_seq;
            g_pending_result.status = ok ? kResultStatusOk : result_name(result);
            g_pending_result.bucket_guid = bucket_guid;
            g_pending_result.before = before;
            g_pending_result.after = after;
            if (ok)
            {
                char detail[256]{};
                std::snprintf(detail, sizeof(detail),
                              "native_live_add:verified panel_seq=%llu request=%s bucket=%u "
                              "before=%u after=%u watched=%u | persistence:not_verified",
                              static_cast<unsigned long long>(request.panel_seq),
                              request.request_id.c_str(), bucket_guid, before, after, request.watch.count);
                g_pending_result.detail = detail;
            }
            else
            {
                g_pending_result.detail = result_name(result);
                if (extra && *extra)
                {
                    // One line of plain tokens; the bridge forwards it verbatim.
                    std::size_t length = 0;
                    while (length < 400 && extra[length] != '\0') ++length;
                    g_pending_result.detail += ' ';
                    g_pending_result.detail.append(extra, length);
                }
            }
            ReleaseSRWLockExclusive(&g_result_lock);
            if (!terminal)
            {
                g_outcome_unknown.store(true, std::memory_order_release);
            }
            return true;
        }

        // Plain tokens for a result detail and the status file.
        // The same text as limit_token, into a caller buffer (no heap object).
        void format_limit(char* out, std::size_t size, const ItemCapacity& capacity)
        {
            if (capacity.max_state == MaxState::Limit) std::snprintf(out, size, "%u", capacity.max_value);
            else std::snprintf(out, size, "%s", max_state_name(capacity.max_state));
        }

        std::string limit_token(const ItemCapacity& capacity, bool capacity_read)
        {
            if (!capacity_read) return "unknown";
            if (capacity.max_state == MaxState::Limit) return std::to_string(capacity.max_value);
            return max_state_name(capacity.max_state);
        }

        // C6: the counts watched around one add: every sentinel except the
        // item itself, and the item's replacement target (the item the server
        // grants instead when a MaxAmount-1 item is already owned). GameThread
        // only; reads only (FNAME_Find and the count read).
        bool capture_watch_set(void* bucket, std::uint16_t item_index, WatchSet& out)
        {
            const AllowedItem& item = kAllowedItems[item_index];
            out.count = 0;
            auto add_entry = [&](std::uint16_t watched, std::uint64_t name) -> bool {
                if (watched == item_index) return true;
                for (std::uint32_t index = 0; index < out.count; ++index)
                {
                    if (out.entries[index].item == watched) return true;
                }
                if (out.count >= out.entries.size()) return false;
                std::uint32_t count = 0;
                // A name the pool does not hold has no count yet (0); it is
                // looked up again at every verification read.
                if (name != 0 && !read_inventory_count(bucket, name, &count)) return false;
                out.entries[out.count++] = {watched, name, count};
                return true;
            };
            for (std::size_t position = 0; position < kSentinelItems.size(); ++position)
            {
                if (g_sentinel_names[position] == 0) return false;
                if (!add_entry(kSentinelItems[position], g_sentinel_names[position])) return false;
            }
            if (item.replacement >= 0)
            {
                const auto target = static_cast<std::uint16_t>(item.replacement);
                std::uint64_t name = 0;
                if (!lookup_alias_fname(kAllowedItems[target].alias, &name)) return false;
                if (!add_entry(target, name)) return false;
            }
            return game_code_allowed();
        }

        struct WatchResult
        {
            bool read_ok{true};
            std::uint32_t grew{};
            std::uint32_t fell{};
            std::string changed;  // alias:before->now, comma separated (bounded)
        };

        // C6, at every verification read: the watch set again. GameThread only.
        WatchResult compare_watch_set(void* bucket, const WatchSet& watch)
        {
            WatchResult result{};
            for (std::uint32_t index = 0; index < watch.count && index < watch.entries.size(); ++index)
            {
                const WatchEntry& entry = watch.entries[index];
                std::uint64_t name = entry.name;
                if (name == 0 && !lookup_alias_fname(kAllowedItems[entry.item].alias, &name))
                {
                    result.read_ok = false;
                    return result;
                }
                std::uint32_t now = 0;
                if (name != 0 && !read_inventory_count(bucket, name, &now))
                {
                    result.read_ok = false;
                    return result;
                }
                const WatchChange change = watch_change(entry.before, now);
                if (change == WatchChange::Same) continue;
                if (change == WatchChange::Grew) ++result.grew;
                else ++result.fell;
                if (result.changed.size() < 240)
                {
                    if (!result.changed.empty()) result.changed += ',';
                    const std::string_view alias = kAllowedItems[entry.item].alias;
                    result.changed.append(alias.data(), alias.size());
                    result.changed += ':';
                    result.changed += std::to_string(entry.before);
                    result.changed += "->";
                    result.changed += std::to_string(now);
                }
            }
            return result;
        }

        void execute_add(const PendingAdd& request)
        {
            report_start(request);
            auto fail = [&](Result result, std::uint32_t bucket_guid,
                            std::uint32_t before, std::uint32_t after,
                            const char* extra = nullptr) {
                store_result(false, true, result, request, bucket_guid, before, after, extra);
                clear_pending();
                g_phase.store(Phase::Done, std::memory_order_release);
                g_result.store(result, std::memory_order_release);
                report_outcome(result_name(result));
            };
            if (request_expired(request))
            {
                fail(Result::RequestStale, 0, 0, 0);
                return;
            }
            if (!self_check_passed())
            {
                fail(self_check_failed() ? Result::SelfCheckFailed : Result::SelfCheckNotPassed, 0, 0, 0);
                return;
            }
            const AllowedItem* item = find_allowed_item(request.alias);
            std::uint64_t alias_name = 0;
            if (!item || !resolve_allowed_alias_name(request.alias, request.alias_index, &alias_name))
            {
                fail(Result::PolicyBlocked, 0, 0, 0);
                return;
            }
            const std::uint16_t item_index = allowed_item_index(item);
            std::uint32_t bucket_guid = 0;
            std::uint32_t target_guid = 0;
            void* bucket = find_inventory_bucket(&bucket_guid, &target_guid);
            if (!bucket)
            {
                fail(Result::BucketNotReady, 0, 0, 0);
                return;
            }
            std::uint32_t before = 0;
            if (!read_inventory_count(bucket, alias_name, &before))
            {
                fail(Result::BucketNotReady, bucket_guid, 0, 0);
                return;
            }
            note_item_count(*item, before);
            if (!image_global_is_live(kAddSubsystemSingletonRva))
            {
                fail(Result::SubsystemNotReady, bucket_guid, before, before);
                return;
            }
            // The live item-table row and carry limit, read before anything is sent.
            const ItemCapacity capacity = read_item_capacity(alias_name);
            report_before(before, capacity, true);
            if (!game_code_allowed())
            {
                fail(Result::SelfCheckFailed, bucket_guid, before, before);
                return;
            }
            // v0.5.0 (C1b-C5): the one per-group decision. The server add looks
            // the same row up (0x1BDAA96) and adds nothing without it, adds
            // nothing when ValidConditionGroup fails, uses a use-on-pickup item
            // instead of storing it (0x1BDABCB), swaps an owned MaxAmount-1
            // item for its replacement (0x1BDA730) and clamps to the room left
            // (0x1BDAD88); every such case is refused here, before any call.
            const ItemDecision decision =
                decide_item(*item, capacity, before, request.qty, instances_proven_for(item->category));
            char detail[320]{};
            if (decision.result != Result::None)
            {
                char limit[24]{};
                format_limit(limit, sizeof(limit), capacity);
                std::snprintf(detail, sizeof(detail),
                              "alias=%s group=%s reason=%s before=%u max=%s source=%s category=%u",
                              request.alias.c_str(), item_group_name(item->group), decision.reason, before,
                              limit, capacity.max_source, capacity.category);
                report_refusal_reason(decision.reason);
                fail(decision.result, bucket_guid, before, before, detail);
                return;
            }
            const std::uint32_t qty_send = decision.qty_send;
            if (qty_send == 0 || qty_send > request.qty || qty_send > item->per_add_max)
            {
                fail(Result::RequestInvalid, bucket_guid, before, before);
                return;
            }
            // C6: the watch set's counts, read before the add is sent.
            WatchSet watched{};
            if (!capture_watch_set(bucket, item_index, watched))
            {
                fail(game_code_allowed() ? Result::BucketNotReady : Result::SelfCheckFailed, bucket_guid, before,
                     before, "watch_set_unreadable");
                return;
            }
            auto* server_add = reinterpret_cast<ServerItemBucketAddFn>(g_image + kServerItemBucketAddRva);
            alignas(16) unsigned char rpc_item_instance[kRpcItemInstanceSize]{};
            bool call_completed = false;
            if (g_shutting_down.load(std::memory_order_acquire) || request_expired(request))
            {
                fail(Result::RequestStale, bucket_guid, before, before);
                return;
            }
            std::uint64_t stable_alias_name = 0;
            if (!resolve_allowed_alias_name(request.alias, request.alias_index, &stable_alias_name)
                || stable_alias_name != alias_name)
            {
                fail(Result::PolicyBlocked, bucket_guid, before, before);
                return;
            }
            std::uint32_t stable_bucket_guid = 0;
            std::uint32_t stable_target_guid = 0;
            std::uint32_t stable_before = 0;
            void* stable_bucket = find_inventory_bucket(
                &stable_bucket_guid, &stable_target_guid);
            if (stable_bucket != bucket || stable_bucket_guid != bucket_guid
                || stable_target_guid != target_guid
                || !read_inventory_count(stable_bucket, alias_name, &stable_before)
                || stable_before != before)
            {
                fail(Result::ContextChanged, stable_bucket_guid, before, stable_before);
                return;
            }
            std::uint32_t frame_at_add = 0;
            const bool frame_known = sample_server_frame(&frame_at_add);
            if (!enter_game_code())
            {
                fail(Result::SelfCheckFailed, bucket_guid, before, before);
                return;
            }
            bool pending_matches = false;
            AcquireSRWLockExclusive(&g_pending_lock);
            pending_matches = g_pending.active
                && g_pending.panel_seq == request.panel_seq
                && g_pending.request_id == request.request_id
                && g_pending.session == request.session;
            if (pending_matches) g_pending.mutation_attempted = true;
            ReleaseSRWLockExclusive(&g_pending_lock);
            if (!pending_matches)
            {
                fail(Result::ContextChanged, bucket_guid, before, before);
                return;
            }
            report_sent(qty_send, frame_known, frame_at_add);
            report_watch(watched.count, "none");
#if defined(_MSC_VER)
            __try
            {
#endif
                // The single authoritative game-owned add, byte-identical in
                // its arguments to the certified Worm Bait call: inventory
                // bucket type 1, the verified target, one allowlisted alias
                // (its whole FName: for an alias without a number suffix,
                // such as Item_Worm_Bait, the same 64-bit value as v0.4.0),
                // the decided quantity (per group, at most the room left under
                // the known carry limit), stat level 1, notify UI, no enhance
                // UI, not an event load, and a zeroed (new-item)
                // FSBItemInstanceForRPC. The implementation returns nothing;
                // it queues the add for a later server frame.
                server_add(nullptr, static_cast<std::uint8_t>(kInventoryBucketType), target_guid,
                           alias_name, qty_send, 1, 1, 0, 0, rpc_item_instance);
                call_completed = true;
#if defined(_MSC_VER)
            }
            __except (sbcore::fault::filter(GetExceptionInformation(), "exception_in_server_item_bucket_add"))
            {
                sbcore::fault::after_handler();
                game_code_exception("exception_in_server_item_bucket_add", GetExceptionCode());
                call_completed = false;
            }
#endif
            if (!call_completed)
            {
                store_result(false, false, Result::AddException, request,
                             bucket_guid, before, before);
                clear_pending();
                g_phase.store(Phase::Done, std::memory_order_release);
                g_result.store(Result::AddException, std::memory_order_release);
                report_outcome(result_name(Result::AddException));
                return;
            }
            const std::uint64_t add_tick = GetTickCount64();
            g_server_add_calls.fetch_add(1, std::memory_order_relaxed);
            AcquireSRWLockExclusive(&g_pending_lock);
            g_pending.before = before;
            g_pending.bucket_guid = bucket_guid;
            g_pending.target_guid = target_guid;
            g_pending.qty_sent = qty_send;
            g_pending.add_tick = add_tick;
            g_pending.frame_at_add_known = frame_known;
            g_pending.frame_at_add = frame_at_add;
            g_pending.frames_resumed_tick = 0;
            g_pending.verify_polls = 0;
            g_pending.capacity = capacity;
            g_pending.item_index = item_index;
            g_pending.watch = watched;
            g_pending.alias_name = alias_name;
            ReleaseSRWLockExclusive(&g_pending_lock);
            g_phase.store(Phase::VerifyPending, std::memory_order_release);
            g_result.store(Result::AddRequested, std::memory_order_release);
            g_verify_due_tick.store(add_tick + kVerifyFirstDelayMs, std::memory_order_release);
            g_verify_scheduled.store(true, std::memory_order_release);
        }

        void execute_verify(const PendingAdd& request)
        {
            auto fail = [&](Result result, std::uint32_t bucket_guid,
                            std::uint32_t after, const char* extra = nullptr) {
                store_result(false, false, result, request,
                             bucket_guid, request.before, after, extra);
                clear_pending();
                g_phase.store(Phase::Done, std::memory_order_release);
                g_result.store(result, std::memory_order_release);
                report_outcome(result_name(result));
            };
            if (g_shutting_down.load(std::memory_order_acquire))
            {
                // Shutdown owns the correlated outcome and will publish it
                // after this action releases the mutation rundown lock.
                return;
            }
            if (!game_code_allowed())
            {
                // The add already ran; with game code off it cannot be
                // verified, so the outcome stays unknown (terminal=0).
                fail(Result::NotVerified, request.bucket_guid, request.before);
                return;
            }
            std::uint64_t alias_name = 0;
            if (!resolve_allowed_alias_name(request.alias, request.alias_index, &alias_name)
                || alias_name != request.alias_name)
            {
                fail(Result::PolicyBlocked, request.bucket_guid, request.before);
                return;
            }
            std::uint32_t bucket_guid = 0;
            std::uint32_t target_guid = 0;
            void* bucket = find_inventory_bucket(&bucket_guid, &target_guid);
            std::uint32_t after = 0;
            if (!bucket || !read_inventory_count(
                    bucket, alias_name, &after))
            {
                fail(Result::ContextChanged, bucket_guid, after);
                return;
            }
            if (bucket_guid != request.bucket_guid
                || target_guid != request.target_guid)
            {
                fail(Result::ContextChanged, bucket_guid, after);
                return;
            }
            // C6: no other watched count may grow with this add.
            const WatchResult watch = compare_watch_set(bucket, request.watch);
            if (!watch.read_ok)
            {
                fail(game_code_allowed() ? Result::ContextChanged : Result::NotVerified, bucket_guid, after,
                     "watch_set_unreadable");
                return;
            }
            report_watch(request.watch.count, watch.changed.empty() ? std::string_view("none")
                                                                     : std::string_view(watch.changed));
            if (watch.grew != 0)
            {
                // Another item was granted with this add (for example the
                // server's replacement for an item the count read missed). The
                // outcome is known, so the result is terminal, but the session
                // is locked: no further add or probe until the game restarts.
                g_side_effect_latched.store(true, std::memory_order_release);
                char side_effect[400]{};
                std::snprintf(side_effect, sizeof(side_effect), "before=%u after=%u sent=%u grew=%u fell=%u changed=%s",
                              request.before, after, request.qty_sent, watch.grew, watch.fell, watch.changed.c_str());
                store_result(false, true, Result::SideEffectDetected, request, bucket_guid, request.before, after,
                             side_effect);
                clear_pending();
                g_phase.store(Phase::Done, std::memory_order_release);
                g_result.store(Result::SideEffectDetected, std::memory_order_release);
                report_outcome(result_name(Result::SideEffectDetected));
                return;
            }
            const std::uint64_t now = GetTickCount64();
            const std::uint64_t since_add = now - request.add_tick;
            std::uint32_t frame = 0;
            const bool frame_known = sample_server_frame(&frame);
            const bool frame_comparable = frame_known && request.frame_at_add_known;
            std::uint64_t resumed_tick = request.frames_resumed_tick;
            if (frame_comparable && frame != request.frame_at_add && resumed_tick == 0) resumed_tick = now;
            // Frozen when the frame index has not moved since the add (see
            // frames_frozen_since_add: A13 no longer samples it while idle).
            const bool frames_frozen = frames_frozen_since_add(frame_comparable, frame, request.frame_at_add);
            const std::uint64_t since_resume = resumed_tick == 0
                ? std::numeric_limits<std::uint64_t>::max() : now - resumed_tick;
            const std::uint32_t polls = request.verify_polls + 1;
            const std::uint64_t expected_after =
                static_cast<std::uint64_t>(request.before) + request.qty_sent;
            const VerifyStep step = decide_verify(
                request.before, request.qty_sent, after, since_add, frames_frozen, since_resume);
            report_poll(after, polls, since_add, step == VerifyStep::ContinuePaused);
            const std::string frames_since_add = frame_comparable
                ? std::to_string(frame - request.frame_at_add) : std::string("unknown");
            char detail[320]{};
            std::snprintf(detail, sizeof(detail),
                          "before=%u after=%u sent=%u requested=%u window_ms=%llu polls=%u max=%s "
                          "condition_group=%u frames_since_add=%s",
                          request.before, after, request.qty_sent, request.qty,
                          static_cast<unsigned long long>(since_add), polls,
                          limit_token(request.capacity, true).c_str(),
                          request.capacity.condition_group ? 1U : 0U,
                          frames_since_add.c_str());
            if (step == VerifyStep::Verified && after == expected_after)
            {
                store_result(true, true, Result::AddedVerified, request,
                             bucket_guid, request.before, after);
                clear_pending();
                g_phase.store(Phase::Done, std::memory_order_release);
                g_result.store(Result::AddedVerified, std::memory_order_release);
                report_outcome(result_name(Result::AddedVerified));
                return;
            }
            if (step == VerifyStep::Mismatch && after > expected_after)
            {
                fail(Result::CountMismatch, bucket_guid, after, detail);
                return;
            }
            if (step == VerifyStep::Unverified)
            {
                fail(Result::NotVerified, bucket_guid, after, detail);
                return;
            }
            AcquireSRWLockExclusive(&g_pending_lock);
            if (g_pending.active && g_pending.panel_seq == request.panel_seq
                && g_pending.request_id == request.request_id)
            {
                g_pending.verify_polls = polls;
                g_pending.frames_resumed_tick = resumed_tick;
            }
            ReleaseSRWLockExclusive(&g_pending_lock);
            const std::uint64_t delay =
                step == VerifyStep::ContinuePaused ? kVerifyPausedPollMs : kVerifyPollMs;
            g_verify_due_tick.store(now + delay, std::memory_order_release);
            g_verify_scheduled.store(true, std::memory_order_release);
        }

        // v0.5.0 (C7), defined with the probe below.
        void execute_probe_chunk();
        void finish_running_probe(Result status);

        void run_game_thread_action(Action action)
        {
            if (action == Action::Probe)
            {
                if (!game_code_allowed())
                {
                    finish_running_probe(Result::SelfCheckFailed);
                    return;
                }
                // A13: a chunk queued before the lease lapsed does no game
                // work; the worker ends the probe (panel_lease_missing).
                if (!g_panel_lease_fresh.load(std::memory_order_acquire)) return;
                execute_probe_chunk();
                return;
            }
            if (action == Action::Refresh)
            {
                if (!game_code_allowed())
                {
                    clear_published_bucket();
                    return;
                }
                // A13: a Refresh queued before the panel lease lapsed does no
                // game work.
                if (!g_panel_lease_fresh.load(std::memory_order_acquire))
                {
                    clear_published_bucket();
                    return;
                }
                refresh_bucket();
                g_phase.store(Phase::Refreshing, std::memory_order_release);
                return;
            }
            const PendingAdd request = pending_copy();
            if (!request.active)
            {
                g_phase.store(Phase::Idle, std::memory_order_release);
                return;
            }
            if (action == Action::Add)
            {
                execute_add(request);
                return;
            }
            if (action == Action::Verify)
            {
                execute_verify(request);
                return;
            }
        }

        void execute_game_thread_action(Action action)
        {
            AcquireSRWLockExclusive(&g_mutation_lock);
#if defined(_MSC_VER)
            __try
            {
                if (!g_shutting_down.load(std::memory_order_acquire))
                    run_game_thread_action(action);
            }
            __finally
            {
                ReleaseSRWLockExclusive(&g_mutation_lock);
            }
#else
            if (!g_shutting_down.load(std::memory_order_acquire))
                run_game_thread_action(action);
            ReleaseSRWLockExclusive(&g_mutation_lock);
#endif
        }

        void record_dispatch_failure_locked(Action action, Result result)
        {
            // A running probe ends with the dispatch failure (nothing of it
            // can run any more); it is read-only, so no outcome is unknown.
            finish_running_probe(result);
            const PendingAdd request = pending_copy();
            if (request.active)
            {
                const bool ambiguous = action == Action::Verify || request.mutation_attempted;
                store_result(false, !ambiguous, result, request,
                             request.bucket_guid, request.before, request.before);
                clear_pending();
            }
            g_verify_scheduled.store(false, std::memory_order_release);
            g_result.store(result, std::memory_order_release);
            g_phase.store(Phase::Fault, std::memory_order_release);
            g_dispatch_poisoned.store(true, std::memory_order_release);
        }

        void record_dispatch_failure(Action action, Result result)
        {
            AcquireSRWLockExclusive(&g_mutation_lock);
#if defined(_MSC_VER)
            __try
            {
                record_dispatch_failure_locked(action, result);
            }
            __finally
            {
                ReleaseSRWLockExclusive(&g_mutation_lock);
            }
#else
            record_dispatch_failure_locked(action, result);
            ReleaseSRWLockExclusive(&g_mutation_lock);
#endif
        }

        // A9: the process-wide write block is set, so no queued action may run
        // on the GameThread any more (sbcore refuses the task). Answer it on the
        // worker exactly as the GameThread path answers a session whose game
        // code is off: an add that never reached the game is refused
        // (self_check_failed, terminal); a started add stays unverified
        // (not terminal). No game function is reachable from here.
        void abandon_action_writes_blocked(Action action)
        {
            Action expected = action;
            g_pending_action.compare_exchange_strong(
                expected, Action::None, std::memory_order_acq_rel, std::memory_order_acquire);
            g_actions_abandoned_blocked.fetch_add(1, std::memory_order_relaxed);
            // A running probe reads nothing more (read-only: no outcome to keep).
            finish_running_probe(Result::SelfCheckFailed);
            if (action == Action::Refresh || action == Action::Probe)
            {
                clear_published_bucket();
                return;
            }
            AcquireSRWLockExclusive(&g_mutation_lock);
            const PendingAdd request = pending_copy();
            if (request.active)
            {
                if (action == Action::Verify || request.mutation_attempted)
                {
                    store_result(false, false, Result::NotVerified, request,
                                 request.bucket_guid, request.before, request.before);
                    g_result.store(Result::NotVerified, std::memory_order_release);
                    report_outcome(result_name(Result::NotVerified));
                }
                else
                {
                    report_start(request);
                    store_result(false, true, Result::SelfCheckFailed, request, 0, 0, 0);
                    g_result.store(Result::SelfCheckFailed, std::memory_order_release);
                    report_outcome(result_name(Result::SelfCheckFailed));
                }
                clear_pending();
                g_phase.store(Phase::Done, std::memory_order_release);
            }
            g_verify_scheduled.store(false, std::memory_order_release);
            ReleaseSRWLockExclusive(&g_mutation_lock);
        }

        // The GameThread entry. sbcore::dispatch calls it only on the
        // certified GameThread (its id re-read from the gate-proven
        // GGameThreadId global at invoke time), only while the fault latch is
        // clear, and under sbcore::fault::guarded_call. The action is taken
        // first, so a shutdown drops it as in v0.3.1.
        void game_thread_callback(std::uint64_t sequence)
        {
            (void)sequence;
            const Action action = g_pending_action.exchange(Action::None, std::memory_order_acq_rel);
            if (g_shutting_down.load(std::memory_order_acquire) || action == Action::None) return;
#if defined(_MSC_VER)
            __try { execute_game_thread_action(action); }
            __except (sbcore::fault::filter(GetExceptionInformation(), "exception_in_game_thread_action"))
            {
                sbcore::fault::after_handler();
                game_code_exception("exception_in_game_thread_action", GetExceptionCode());
                record_dispatch_failure(action, Result::DispatchException);
            }
#else
            execute_game_thread_action(action);
#endif
        }

        // Worker, every tick: turn an sbcore dispatcher that poisoned itself
        // while running a task (a callback invoked on a thread that is not the
        // certified GameThread) into this module's correlated fault, as v0.3.1
        // recorded WrongThread from its own invoke function.
        void reconcile_dispatcher()
        {
            if (g_dispatch_poisoned.load(std::memory_order_acquire)) return;
            const auto counters = sbcore::dispatch::counters();
            if (!counters.poisoned || counters.pending) return;
            const Action action = g_pending_action.exchange(Action::None, std::memory_order_acq_rel);
            if (counters.last_exception != 0)
                g_last_exception.store(counters.last_exception, std::memory_order_release);
            record_dispatch_failure(action, counters.wrong_thread != 0 ? Result::WrongThread : Result::DispatchException);
        }

        bool dispatch_action()
        {
            const Action action = g_pending_action.load(std::memory_order_acquire);
            if (action == Action::Refresh && !game_code_allowed())
            {
                Action queued_refresh = Action::Refresh;
                g_pending_action.compare_exchange_strong(
                    queued_refresh, Action::None, std::memory_order_acq_rel, std::memory_order_acquire);
                return false;
            }
            if (action == Action::Probe && !game_code_allowed())
            {
                Action queued_probe = Action::Probe;
                g_pending_action.compare_exchange_strong(
                    queued_probe, Action::None, std::memory_order_acq_rel, std::memory_order_acquire);
                finish_running_probe(Result::SelfCheckFailed);
                return false;
            }
            if (!g_ready.load(std::memory_order_acquire)
                || g_shutting_down.load(std::memory_order_acquire)
                || g_dispatch_poisoned.load(std::memory_order_acquire)
                || action == Action::None)
            {
                return false;
            }
            // sbcore builds the same FFunctionGraphTask as v0.3.1 and runs
            // game_thread_callback on the certified GameThread.
            const auto submitted = sbcore::dispatch::submit(&game_thread_callback);
            g_last_submit_result.store(submitted, std::memory_order_release);
            switch (submitted)
            {
            case sbcore::dispatch::SubmitResult::Submitted:
                return true;
            case sbcore::dispatch::SubmitResult::Busy:          // one task in flight; it takes the queued action
            case sbcore::dispatch::SubmitResult::ShuttingDown:  // shutdown answers the pending add
            case sbcore::dispatch::SubmitResult::NotBound:
            case sbcore::dispatch::SubmitResult::NoCallback:
                return false;
            case sbcore::dispatch::SubmitResult::WritesBlocked:
                disable_game_code("sbcore_writes_blocked");
                abandon_action_writes_blocked(action);
                return false;
            case sbcore::dispatch::SubmitResult::Poisoned:
                reconcile_dispatcher();
                return false;
            case sbcore::dispatch::SubmitResult::CreateRejected:
            case sbcore::dispatch::SubmitResult::VtableMismatch:
            case sbcore::dispatch::SubmitResult::Exception:
                break;
            }
            // Nothing was queued, or (Exception) it cannot be known whether
            // it was: sbcore keeps its lease and poison; this module records
            // the failure for the action and stops dispatching, as v0.3.1 did.
            const auto counters = sbcore::dispatch::counters();
            if (counters.last_exception != 0)
                g_last_exception.store(counters.last_exception, std::memory_order_release);
            g_pending_action.store(Action::None, std::memory_order_release);
            record_dispatch_failure(action, Result::DispatchFailed);
            return false;
        }

        bool request_line(const std::string& line, std::string& key, std::string& value)
        {
            const auto equals = line.find('=');
            if (equals == std::string::npos) return false;
            key = line.substr(0, equals);
            value = line.substr(equals + 1);
            return true;
        }

        struct RequestFields
        {
            std::string protocol, bridge, session, request_id, alias;
            std::uint64_t panel_seq{};
            std::uint64_t issued_unix_s{};
            std::uint64_t native_beat{};
            std::uint64_t alias_index{};
            std::uint64_t qty{};
            bool saw_protocol{}, saw_bridge{}, saw_session{}, saw_request_id{};
            bool saw_panel_seq{}, saw_issued_unix_s{}, saw_native_beat{};
            bool saw_alias{}, saw_alias_index{}, saw_qty{}, invalid_format{};
        };

        struct RequestContext
        {
            std::string module_session;
            std::uint64_t now_unix_s{};
            std::uint64_t current_native_beat{};
            std::uint64_t last_panel_seq{};
            bool bucket_ready{};
            bool self_check_passed{};
            bool self_check_failed{};
            bool busy{};
        };

        struct RequestVerdict
        {
            Result result{Result::None}; // None means accept
            bool correlated{};           // a rejection may be published
            std::uint64_t age_seconds{};
            RequestFields fields;
        };

        RequestFields parse_request_fields(const std::string& text)
        {
            RequestFields fields{};
            std::size_t position{};
            while (position < text.size())
            {
                const auto end = text.find('\n', position);
                std::string line = text.substr(
                    position, end == std::string::npos ? text.size() - position : end - position);
                position = end == std::string::npos ? text.size() : end + 1;
                if (!line.empty() && line.back() == '\r') line.pop_back();
                std::string key, value;
                if (!request_line(line, key, value))
                {
                    fields.invalid_format = true;
                    continue;
                }
                std::uint64_t parsed{};
                if (key == "protocol" && !fields.saw_protocol) { fields.protocol = value; fields.saw_protocol = true; }
                else if (key == "bridge" && !fields.saw_bridge) { fields.bridge = value; fields.saw_bridge = true; }
                else if (key == "session" && !fields.saw_session) { fields.session = value; fields.saw_session = true; }
                else if (key == "request_id" && !fields.saw_request_id) { fields.request_id = value; fields.saw_request_id = true; }
                else if (key == "panel_seq" && !fields.saw_panel_seq && parse_unsigned(value, parsed)) { fields.panel_seq = parsed; fields.saw_panel_seq = true; }
                else if (key == "issued_unix_s" && !fields.saw_issued_unix_s && parse_unsigned(value, parsed)) { fields.issued_unix_s = parsed; fields.saw_issued_unix_s = true; }
                else if (key == "native_beat" && !fields.saw_native_beat && parse_unsigned(value, parsed)) { fields.native_beat = parsed; fields.saw_native_beat = true; }
                else if (key == "alias" && !fields.saw_alias) { fields.alias = value; fields.saw_alias = true; }
                else if (key == "alias_index" && !fields.saw_alias_index && parse_unsigned(value, parsed)) { fields.alias_index = parsed; fields.saw_alias_index = true; }
                else if (key == "qty" && !fields.saw_qty && parse_unsigned(value, parsed)) { fields.qty = parsed; fields.saw_qty = true; }
                else fields.invalid_format = true;
            }
            return fields;
        }

        // Pure protocol decision for one claimed request body.
        RequestVerdict evaluate_request(const std::string& text, const RequestContext& context)
        {
            RequestVerdict verdict{};
            verdict.fields = parse_request_fields(text);
            const RequestFields& f = verdict.fields;
            verdict.correlated = f.saw_session && f.saw_request_id && f.saw_panel_seq
                && valid_hex_token(f.session, 32, 64)
                && valid_hex_token(f.request_id, 32, 64)
                && f.panel_seq > 0;
            if (f.invalid_format || !f.saw_protocol || f.protocol != kProtocol
                || !f.saw_bridge || !f.saw_alias || !f.saw_issued_unix_s || !f.saw_native_beat)
            {
                verdict.result = Result::RequestInvalid;
                return verdict;
            }
            if (!verdict.correlated)
            {
                verdict.result = Result::RequestInvalid;
                return verdict;
            }
            if (f.session != context.module_session || !valid_hex_token(context.module_session, 32, 64))
            {
                verdict.result = Result::SessionMismatch;
                return verdict;
            }
            // v0.5.0: the alias must be a row of the generated allowlist (exact
            // case); excluded rows are absent and watch-only rows never addable.
            const AllowedItem* item = find_allowed_item(f.alias);
            if (f.bridge != kTrustedBridge || !item || item->group == ItemGroup::WatchOnly)
            {
                verdict.result = Result::PolicyBlocked;
                return verdict;
            }
            const bool future_time = f.issued_unix_s > context.now_unix_s
                && f.issued_unix_s - context.now_unix_s > kRequestFutureSkewSeconds;
            verdict.age_seconds = f.issued_unix_s <= context.now_unix_s
                ? context.now_unix_s - f.issued_unix_s : 0;
            const bool stale_time = f.issued_unix_s == 0 || future_time
                || verdict.age_seconds + 1 >= kRequestMaxAgeSeconds;
            const bool stale_beat = f.native_beat == 0 || f.native_beat > context.current_native_beat
                || context.current_native_beat - f.native_beat > kRequestMaxBeatDrift;
            if (stale_time || stale_beat)
            {
                verdict.result = Result::RequestStale;
                return verdict;
            }
            if (f.panel_seq <= context.last_panel_seq)
            {
                verdict.result = Result::DuplicateRequest;
                return verdict;
            }
            if (f.alias_index == 0 || f.alias_index > 0xFFFFFFFFULL
                || f.qty == 0 || f.qty > kMaxRequestQuantity
                || !f.saw_alias_index || !f.saw_qty)
            {
                verdict.result = Result::RequestInvalid;
                return verdict;
            }
            // C3: the per-group range of this row (probe-only rows allow nothing).
            if (item->group == ItemGroup::Gated)
            {
                verdict.result = Result::EntitlementGated;
                return verdict;
            }
            if (f.qty > item->per_add_max)
            {
                verdict.result = Result::QuantityNotAllowed;
                return verdict;
            }
            if (!context.self_check_passed)
            {
                verdict.result = context.self_check_failed ? Result::SelfCheckFailed : Result::SelfCheckNotPassed;
                return verdict;
            }
            if (!context.bucket_ready)
            {
                verdict.result = Result::BucketNotReady;
                return verdict;
            }
            if (context.busy)
            {
                verdict.result = Result::Busy;
                return verdict;
            }
            return verdict;
        }

        void poll_request()
        {
            if (!MoveFileExW(g_request_path.c_str(), g_request_claim_path.c_str(),
                             MOVEFILE_WRITE_THROUGH))
            {
                return;
            }
            std::string text;
            const bool read_ok = read_small_file(g_request_claim_path, text);
            const bool delete_ok = DeleteFileW(g_request_claim_path.c_str()) != FALSE;
            if (!read_ok || !delete_ok)
            {
                if (!delete_ok)
                {
                    g_dispatch_poisoned.store(true, std::memory_order_release);
                    g_phase.store(Phase::Fault, std::memory_order_release);
                    g_result.store(Result::RequestInvalid, std::memory_order_release);
                }
                return;
            }
            AcquireSRWLockExclusive(&g_mutation_lock);
            const bool competing_operation = pending_active() || !result_slot_empty();
            ReleaseSRWLockExclusive(&g_mutation_lock);
            if (competing_operation) return;
            // An unknown outcome, or (v0.5.0, C6) a watched count that grew
            // with an add, locks the session: no further add is accepted.
            if (g_outcome_unknown.load(std::memory_order_acquire)
                || g_side_effect_latched.load(std::memory_order_acquire))
            {
                return;
            }
            const DWORD result_attributes = GetFileAttributesW(g_result_path.c_str());
            if (result_attributes != INVALID_FILE_ATTRIBUTES
                || GetLastError() != ERROR_FILE_NOT_FOUND)
            {
                return;
            }

            RequestContext context{};
            context.module_session = session_copy();
            context.now_unix_s = unix_time_ms() / 1'000ULL;
            context.current_native_beat = g_heartbeat_beat.load(std::memory_order_acquire);
            context.last_panel_seq = g_last_panel_seq.load(std::memory_order_acquire);
            context.bucket_ready = g_inventory_bucket_guid.load(std::memory_order_acquire) != 0;
            context.self_check_passed = self_check_passed();
            context.self_check_failed = self_check_failed();
            // v0.5.0: a read-only probe chunk in flight does not make an add
            // wait (the in-flight task takes whatever action is queued when it
            // runs; the probe resumes after the add's verification).
            context.busy = (sbcore::dispatch::counters().pending && !g_probe_running.load(std::memory_order_acquire))
                || g_pending_action.load(std::memory_order_acquire) == Action::Add
                || g_verify_scheduled.load(std::memory_order_acquire)
                || pending_copy().active;
            const RequestVerdict verdict = evaluate_request(text, context);
            const RequestFields& fields = verdict.fields;

            auto reject = [&](Result result) {
                if (!verdict.correlated) return;
                PendingAdd request{};
                request.active = true;
                request.panel_seq = fields.panel_seq;
                request.session = fields.session;
                request.request_id = fields.request_id;
                store_result(false, true, result, request, 0, 0, 0);
                g_phase.store(Phase::Done, std::memory_order_release);
                g_result.store(result, std::memory_order_release);
            };
            if (verdict.result != Result::None)
            {
                reject(verdict.result);
                return;
            }

            const auto now = GetTickCount64();
            const std::uint64_t remaining_ms =
                (kRequestMaxAgeSeconds - verdict.age_seconds - 1) * 1'000ULL;
            PendingAdd request{};
            request.active = true;
            request.panel_seq = fields.panel_seq;
            request.session = fields.session;
            request.request_id = fields.request_id;
            request.alias = fields.alias;
            request.issued_unix_s = fields.issued_unix_s;
            request.native_beat = fields.native_beat;
            request.alias_index = static_cast<std::uint32_t>(fields.alias_index);
            request.qty = static_cast<std::uint32_t>(fields.qty);
            request.started_tick = now;
            request.expires_tick = now + remaining_ms;
            AcquireSRWLockExclusive(&g_mutation_lock);
            SetLastError(ERROR_SUCCESS);
            const DWORD final_result_attributes = GetFileAttributesW(g_result_path.c_str());
            const DWORD final_result_error = final_result_attributes == INVALID_FILE_ATTRIBUTES
                ? GetLastError() : ERROR_SUCCESS;
            if (g_shutting_down.load(std::memory_order_acquire)
                || !result_slot_empty()
                || final_result_attributes != INVALID_FILE_ATTRIBUTES
                || final_result_error != ERROR_FILE_NOT_FOUND)
            {
                ReleaseSRWLockExclusive(&g_mutation_lock);
                return;
            }
            AcquireSRWLockExclusive(&g_pending_lock);
            g_pending = request;
            ReleaseSRWLockExclusive(&g_pending_lock);
            g_last_panel_seq.store(fields.panel_seq, std::memory_order_release);
            g_phase.store(Phase::AddPending, std::memory_order_release);
            g_result.store(Result::None, std::memory_order_release);
            g_pending_action.store(Action::Add, std::memory_order_release);
            ReleaseSRWLockExclusive(&g_mutation_lock);
        }

        // ---- A13: the panel's Items lease ------------------------------------
        struct PanelLease
        {
            bool valid{};
            std::uint32_t panel_pid{};
            std::uint64_t issued_ms{};
        };

        // Pure. Mods\SBCheatGUI\live_add_native_lease.txt holds exactly
        //   protocol=native-live-add-v4
        //   panel_pid=<the panel's process id>
        //   issued_ms=<Unix time in ms when the panel wrote it>
        // once each, canonical decimals, nothing else (fail closed, as a request).
        PanelLease parse_panel_lease(const std::string& text)
        {
            PanelLease lease{};
            bool saw_protocol{}, saw_pid{}, saw_issued{}, invalid{};
            std::uint64_t pid{};
            std::uint64_t issued{};
            std::size_t position{};
            while (position < text.size())
            {
                const auto end = text.find('\n', position);
                std::string line = text.substr(
                    position, end == std::string::npos ? text.size() - position : end - position);
                position = end == std::string::npos ? text.size() : end + 1;
                if (!line.empty() && line.back() == '\r') line.pop_back();
                std::string key, value;
                if (!request_line(line, key, value))
                {
                    invalid = true;
                    continue;
                }
                std::uint64_t parsed{};
                if (key == "protocol" && !saw_protocol) { saw_protocol = true; invalid = invalid || value != kProtocol; }
                else if (key == "panel_pid" && !saw_pid && parse_unsigned(value, parsed)) { pid = parsed; saw_pid = true; }
                else if (key == "issued_ms" && !saw_issued && parse_unsigned(value, parsed)) { issued = parsed; saw_issued = true; }
                else invalid = true;
            }
            if (invalid || !saw_protocol || !saw_pid || !saw_issued
                || pid == 0 || pid > 0xFFFFFFFFULL || issued == 0)
            {
                return lease;
            }
            lease.valid = true;
            lease.panel_pid = static_cast<std::uint32_t>(pid);
            lease.issued_ms = issued;
            return lease;
        }

        const char* lease_state_name(LeaseState state)
        {
            switch (state)
            {
            case LeaseState::NotRead: return "not_read";
            case LeaseState::Missing: return "missing";
            case LeaseState::Unreadable: return "unreadable";
            case LeaseState::Malformed: return "malformed";
            case LeaseState::Invalid: return "invalid";
            case LeaseState::Future: return "future";
            case LeaseState::Stale: return "stale";
            case LeaseState::PanelGone: return "panel_gone";
            case LeaseState::Fresh: return "fresh";
            }
            return "unknown";
        }

        // Pure: the lease decision for already-read lease text.
        LeaseState evaluate_panel_lease(const std::string& text, std::uint64_t now_unix_ms, bool check_process,
                                        std::uint32_t* pid_out, std::uint64_t* age_out)
        {
            if (pid_out) *pid_out = 0;
            if (age_out) *age_out = 0;
            const PanelLease lease = parse_panel_lease(text);
            if (!lease.valid) return LeaseState::Malformed;
            const auto evaluation = sbcore::lease::evaluate(lease.panel_pid, lease.issued_ms, now_unix_ms, kPanelLeaseMs,
                                                            kPanelLeaseFutureToleranceMs, check_process);
            if (pid_out) *pid_out = lease.panel_pid;
            if (age_out) *age_out = evaluation.age_ms;
            switch (evaluation.state)
            {
            case sbcore::lease::State::Fresh: return LeaseState::Fresh;
            case sbcore::lease::State::Invalid: return LeaseState::Invalid;
            case sbcore::lease::State::Future: return LeaseState::Future;
            case sbcore::lease::State::Stale: return LeaseState::Stale;
            case sbcore::lease::State::PanelGone: return LeaseState::PanelGone;
            }
            return LeaseState::Invalid;
        }

        // Worker only: reads the lease (a replace in progress is bridged for
        // 500 ms by the StableReader) and publishes whether GameThread
        // refresh work is allowed. Reads files only; never touches the game.
        bool refresh_panel_lease(std::uint64_t now_tick)
        {
            const auto read = g_lease_reader.read(now_tick);
            LeaseState state = LeaseState::Unreadable;
            std::uint32_t pid = 0;
            if (read.effective == sbcore::status::ReadResult::Ok)
            {
                state = evaluate_panel_lease(g_lease_reader.content(), unix_time_ms(), true, &pid, nullptr);
            }
            else if (read.effective == sbcore::status::ReadResult::Missing)
            {
                state = LeaseState::Missing;
            }
            g_panel_lease_pid.store(pid, std::memory_order_release);
            g_panel_lease_state.store(state, std::memory_order_release);
            const bool fresh = state == LeaseState::Fresh;
            g_panel_lease_fresh.store(fresh, std::memory_order_release);
            return fresh;
        }

        // ---- v0.5.0 (C7): the read-only probe --------------------------------
        // Request, written by the panel (replaced atomically, like the lease):
        //   protocol=native-live-add-v4
        //   session=<this module's session, from the heartbeat>
        //   probe_id=<32-64 hex characters>
        //   issued_unix_s=<Unix seconds; at most 5 s old>
        //   aliases=*            every addable and entitlement-gated row
        //   aliases=A,B,...      1..64 distinct allowlisted names (exact case)
        // Result (Mods\SBCheatGUI\live_add_native_probe_result.txt), CRLF lines:
        //   protocol, module, version, session, probe_id, status (ok or the
        //   refusal), items, bucket_guid, instance_evidence,
        //   allowlist_catalog_sha256, then per item
        //   item.<alias>=<state>|<count>|<max>|<addable_now>, then end=1.
        struct ProbeFields
        {
            std::string protocol, session, probe_id, aliases;
            std::uint64_t issued_unix_s{};
            bool saw_protocol{}, saw_session{}, saw_probe_id{}, saw_issued_unix_s{}, saw_aliases{};
            bool invalid_format{};
        };

        struct ProbeContext
        {
            std::string module_session;
            std::uint64_t now_unix_s{};
            bool self_check_passed{};
            bool self_check_failed{};
            bool session_locked{};
            bool lease_fresh{};
        };

        struct ProbeVerdict
        {
            Result result{Result::None};  // None: accept
            bool correlated{};            // a refusal may be published
            ProbeFields fields;
            std::vector<std::uint16_t> items;
        };

        ProbeFields parse_probe_fields(const std::string& text)
        {
            ProbeFields fields{};
            std::size_t position{};
            while (position < text.size())
            {
                const auto end = text.find('\n', position);
                std::string line = text.substr(
                    position, end == std::string::npos ? text.size() - position : end - position);
                position = end == std::string::npos ? text.size() : end + 1;
                if (!line.empty() && line.back() == '\r') line.pop_back();
                std::string key, value;
                if (!request_line(line, key, value))
                {
                    fields.invalid_format = true;
                    continue;
                }
                std::uint64_t parsed{};
                if (key == "protocol" && !fields.saw_protocol) { fields.protocol = value; fields.saw_protocol = true; }
                else if (key == "session" && !fields.saw_session) { fields.session = value; fields.saw_session = true; }
                else if (key == "probe_id" && !fields.saw_probe_id) { fields.probe_id = value; fields.saw_probe_id = true; }
                else if (key == "issued_unix_s" && !fields.saw_issued_unix_s && parse_unsigned(value, parsed)) { fields.issued_unix_s = parsed; fields.saw_issued_unix_s = true; }
                else if (key == "aliases" && !fields.saw_aliases) { fields.aliases = value; fields.saw_aliases = true; }
                else fields.invalid_format = true;
            }
            return fields;
        }

        // Pure: "*" is every addable and entitlement-gated row; otherwise 1..64
        // distinct allowlisted names separated by single commas.
        Result parse_probe_aliases(std::string_view value, std::vector<std::uint16_t>& items)
        {
            items.clear();
            if (value == "*")
            {
                for (std::size_t index = 0; index < kAllowedItems.size(); ++index)
                {
                    if (kAllowedItems[index].group != ItemGroup::WatchOnly)
                        items.push_back(static_cast<std::uint16_t>(index));
                }
                return Result::None;
            }
            std::size_t position = 0;
            while (true)
            {
                const std::size_t comma = value.find(',', position);
                const std::string_view name = value.substr(
                    position, comma == std::string_view::npos ? std::string_view::npos : comma - position);
                if (name.empty() || items.size() >= kProbeMaxListed)
                {
                    items.clear();
                    return Result::RequestInvalid;
                }
                const AllowedItem* item = find_allowed_item(name);
                if (!item || item->group == ItemGroup::WatchOnly)
                {
                    items.clear();
                    return Result::PolicyBlocked;
                }
                const std::uint16_t index = allowed_item_index(item);
                if (std::find(items.begin(), items.end(), index) != items.end())
                {
                    items.clear();
                    return Result::RequestInvalid;
                }
                items.push_back(index);
                if (comma == std::string_view::npos) return Result::None;
                position = comma + 1;
            }
        }

        // Pure protocol decision for one claimed probe request.
        ProbeVerdict evaluate_probe_request(const std::string& text, const ProbeContext& context)
        {
            ProbeVerdict verdict{};
            verdict.fields = parse_probe_fields(text);
            const ProbeFields& f = verdict.fields;
            verdict.correlated = f.saw_session && f.saw_probe_id && valid_hex_token(f.session, 32, 64)
                && valid_hex_token(f.probe_id, 32, 64);
            if (f.invalid_format || !f.saw_protocol || f.protocol != kProtocol || !f.saw_issued_unix_s
                || !f.saw_aliases || !verdict.correlated)
            {
                verdict.result = Result::RequestInvalid;
                return verdict;
            }
            if (f.session != context.module_session || !valid_hex_token(context.module_session, 32, 64))
            {
                verdict.result = Result::SessionMismatch;
                return verdict;
            }
            const bool future_time = f.issued_unix_s > context.now_unix_s
                && f.issued_unix_s - context.now_unix_s > kRequestFutureSkewSeconds;
            const std::uint64_t age = f.issued_unix_s <= context.now_unix_s ? context.now_unix_s - f.issued_unix_s : 0;
            if (f.issued_unix_s == 0 || future_time || age > kProbeRequestMaxAgeSeconds)
            {
                verdict.result = Result::RequestStale;
                return verdict;
            }
            const Result aliases = parse_probe_aliases(f.aliases, verdict.items);
            if (aliases != Result::None)
            {
                verdict.result = aliases;
                return verdict;
            }
            if (!context.self_check_passed)
            {
                verdict.result = context.self_check_failed ? Result::SelfCheckFailed : Result::SelfCheckNotPassed;
                return verdict;
            }
            if (context.session_locked)
            {
                verdict.result = Result::SessionLocked;
                return verdict;
            }
            if (!context.lease_fresh)
            {
                verdict.result = Result::PanelLeaseMissing;
                return verdict;
            }
            return verdict;
        }

        // An add whose outcome is unknown, a watched side effect, a stopped
        // dispatcher or game code switched off: nothing may be probed.
        bool session_locked()
        {
            return g_outcome_unknown.load(std::memory_order_acquire)
                || g_side_effect_latched.load(std::memory_order_acquire)
                || g_dispatch_poisoned.load(std::memory_order_acquire)
                || !game_code_allowed();
        }

        // Ends the probe that is still reading (if any) with status; the worker
        // publishes it. Callable from the worker and the GameThread.
        void finish_running_probe(Result status)
        {
            AcquireSRWLockExclusive(&g_probe_lock);
            if (g_probe.active && !g_probe.finished)
            {
                g_probe.finished = true;
                g_probe.status = status;
                g_probe_running.store(false, std::memory_order_release);
            }
            ReleaseSRWLockExclusive(&g_probe_lock);
        }

        void finish_probe_generation(std::uint64_t generation, Result status)
        {
            AcquireSRWLockExclusive(&g_probe_lock);
            if (g_probe.active && !g_probe.finished && g_probe.generation == generation)
            {
                g_probe.finished = true;
                g_probe.status = status;
                g_probe_running.store(false, std::memory_order_release);
            }
            ReleaseSRWLockExclusive(&g_probe_lock);
        }

        // Worker: claim, validate and accept (or refuse) one probe request. A
        // newer probe supersedes one still reading (its result is never
        // published). Nothing here touches the game.
        void poll_probe_request()
        {
            if (!MoveFileExW(g_probe_request_path.c_str(), g_probe_claim_path.c_str(), MOVEFILE_WRITE_THROUGH))
            {
                return;
            }
            std::string text;
            const auto read = sbcore::status::read_small_file(g_probe_claim_path, text, kProbeRequestMaxBytes);
            const bool delete_ok = DeleteFileW(g_probe_claim_path.c_str()) != FALSE;
            g_probe_requests.fetch_add(1, std::memory_order_relaxed);
            if (read != sbcore::status::ReadResult::Ok || !delete_ok)
            {
                g_probe_refused.fetch_add(1, std::memory_order_relaxed);
                return;
            }
            ProbeContext context{};
            context.module_session = session_copy();
            context.now_unix_s = unix_time_ms() / 1'000ULL;
            context.self_check_passed = self_check_passed();
            context.self_check_failed = self_check_failed();
            context.session_locked = session_locked();
            context.lease_fresh = g_panel_lease_fresh.load(std::memory_order_acquire);
            ProbeVerdict verdict = evaluate_probe_request(text, context);
            if (!verdict.correlated)
            {
                g_probe_refused.fetch_add(1, std::memory_order_relaxed);
                return;
            }
            ProbeJob job{};
            job.active = true;
            job.generation = g_probe_generation.fetch_add(1, std::memory_order_acq_rel) + 1;
            job.session = verdict.fields.session;
            job.probe_id = verdict.fields.probe_id;
            if (verdict.result != Result::None)
            {
                job.finished = true;
                job.status = verdict.result;
                g_probe_refused.fetch_add(1, std::memory_order_relaxed);
            }
            else
            {
                job.items = std::move(verdict.items);
                job.readings.assign(job.items.size(), ProbeReading{});
            }
            const auto total = static_cast<std::uint32_t>(job.items.size());
            const bool running = !job.finished;
            AcquireSRWLockExclusive(&g_probe_lock);
            g_probe = std::move(job);
            g_probe_last_id = g_probe.probe_id;
            g_probe_running.store(running, std::memory_order_release);
            ReleaseSRWLockExclusive(&g_probe_lock);
            g_probe_items_total.store(total, std::memory_order_release);
            g_probe_items_done.store(0, std::memory_order_release);
        }

        // GameThread: the next chunk (at most kProbeChunk items) of the running
        // probe. Per item: FNAME_Find, the count read and the row lookup with
        // its carry limit, exactly the reads an add makes; nothing is written.
        void execute_probe_chunk()
        {
            std::uint64_t generation = 0;
            std::size_t start = 0;
            std::size_t chunk_size = 0;
            std::array<std::uint16_t, kProbeChunk> chunk{};
            bool bucket_known = false;
            std::uint32_t job_bucket_guid = 0;
            std::uint32_t job_target_guid = 0;
            AcquireSRWLockShared(&g_probe_lock);
            const bool runnable = g_probe.active && !g_probe.finished && g_probe.cursor < g_probe.items.size();
            if (runnable)
            {
                generation = g_probe.generation;
                start = g_probe.cursor;
                chunk_size = (std::min)(kProbeChunk, g_probe.items.size() - start);
                for (std::size_t index = 0; index < chunk_size; ++index) chunk[index] = g_probe.items[start + index];
                bucket_known = g_probe.bucket_known;
                job_bucket_guid = g_probe.bucket_guid;
                job_target_guid = g_probe.target_guid;
            }
            ReleaseSRWLockShared(&g_probe_lock);
            if (!runnable) return;
            g_probe_chunks.fetch_add(1, std::memory_order_relaxed);  // chunk callbacks run
            if (!self_check_passed())
            {
                finish_probe_generation(generation, self_check_failed() ? Result::SelfCheckFailed
                                                                        : Result::SelfCheckNotPassed);
                return;
            }
            std::uint32_t bucket_guid = 0;
            std::uint32_t target_guid = 0;
            void* bucket = find_inventory_bucket(&bucket_guid, &target_guid);
            if (!bucket)
            {
                finish_probe_generation(generation, game_code_allowed() ? Result::BucketNotReady
                                                                        : Result::SelfCheckFailed);
                return;
            }
            if (bucket_known && (bucket_guid != job_bucket_guid || target_guid != job_target_guid))
            {
                finish_probe_generation(generation, Result::ContextChanged);
                return;
            }
            std::array<ProbeReading, kProbeChunk> readings{};
            for (std::size_t index = 0; index < chunk_size; ++index)
            {
                const AllowedItem& item = kAllowedItems[chunk[index]];
                ProbeReading& reading = readings[index];
                reading.taken = true;
                std::uint64_t name = 0;
                const bool looked_up = lookup_alias_fname(item.alias, &name);
                if (!game_code_allowed())
                {
                    finish_probe_generation(generation, Result::SelfCheckFailed);
                    return;
                }
                if (!looked_up || name == 0) continue;
                reading.name_found = true;
                reading.count_ok = read_inventory_count(bucket, name, &reading.count);
                if (!game_code_allowed())
                {
                    finish_probe_generation(generation, Result::SelfCheckFailed);
                    return;
                }
                if (reading.count_ok) note_item_count(item, reading.count);
                reading.capacity = read_item_capacity(name);
                if (!game_code_allowed())
                {
                    finish_probe_generation(generation, Result::SelfCheckFailed);
                    return;
                }
            }
            AcquireSRWLockExclusive(&g_probe_lock);
            if (g_probe.active && !g_probe.finished && g_probe.generation == generation && g_probe.cursor == start)
            {
                for (std::size_t index = 0; index < chunk_size; ++index) g_probe.readings[start + index] = readings[index];
                g_probe.cursor = start + chunk_size;
                ++g_probe.chunks;
                g_probe.bucket_known = true;
                g_probe.bucket_guid = bucket_guid;
                g_probe.target_guid = target_guid;
                g_probe_items_done.store(static_cast<std::uint32_t>(g_probe.cursor), std::memory_order_release);
                if (g_probe.cursor >= g_probe.items.size())
                {
                    g_probe.finished = true;
                    g_probe.status = Result::None;
                    g_probe_running.store(false, std::memory_order_release);
                }
            }
            ReleaseSRWLockExclusive(&g_probe_lock);
        }

        // Worker: a probe chunk is queued only while the probe is reading, the
        // panel holds a fresh Items lease, game code is allowed, the self-check
        // passed and no add or verification is pending (an add goes first).
        bool probe_may_be_scheduled(Action pending_action, bool verify_scheduled)
        {
            return g_probe_running.load(std::memory_order_acquire) && game_code_allowed() && self_check_passed()
                && g_panel_lease_fresh.load(std::memory_order_acquire) && g_ready.load(std::memory_order_acquire)
                && !g_dispatch_poisoned.load(std::memory_order_acquire) && pending_action == Action::None
                && !verify_scheduled && !pending_active();
        }

        // Worker: end a reading probe whose preconditions are gone.
        void supervise_probe()
        {
            if (!g_probe_running.load(std::memory_order_acquire)) return;
            if (!game_code_allowed()) finish_running_probe(Result::SelfCheckFailed);
            else if (session_locked()) finish_running_probe(Result::SessionLocked);
            else if (!g_panel_lease_fresh.load(std::memory_order_acquire)) finish_running_probe(Result::PanelLeaseMissing);
        }

        // Pure: the probe result body.
        std::string format_probe_result(const ProbeJob& job, const std::string& evidence)
        {
            std::string body;
            body.reserve(128 + job.items.size() * 72);
            auto line = [&](const char* key, std::string_view value) {
                body += key;
                body += '=';
                body.append(value.data(), value.size());
                body += "\r\n";
            };
            line("protocol", kProtocol);
            line("module", kModuleName);
            line("version", kVersion);
            line("session", job.session);
            line("probe_id", job.probe_id);
            const bool ok = job.status == Result::None;
            line("status", ok ? std::string_view("ok") : std::string_view(result_name(job.status)));
            line("items", std::to_string(ok ? job.items.size() : 0));
            line("bucket_guid", std::to_string(job.bucket_known ? job.bucket_guid : 0));
            line("instance_evidence", evidence);
            line("allowlist_catalog_sha256", kAllowlistCatalogSha256);
            if (ok)
            {
                for (std::size_t index = 0; index < job.items.size() && index < job.readings.size(); ++index)
                {
                    const AllowedItem& item = kAllowedItems[job.items[index]];
                    const ProbeReading& reading = job.readings[index];
                    const ProbeLabel label = probe_label(item, reading, instances_proven_for(item.category));
                    body += "item.";
                    body.append(item.alias.data(), item.alias.size());
                    body += '=';
                    body += label.state;
                    body += '|';
                    body += reading.name_found && reading.count_ok ? std::to_string(reading.count) : std::string("unknown");
                    body += '|';
                    body += reading.name_found ? limit_token(reading.capacity, true) : std::string("unknown");
                    body += '|';
                    body += std::to_string(label.addable_now);
                    body += "\r\n";
                }
            }
            line("end", "1");
            return body;
        }

        // Worker: publish a finished probe (the reply stays until it is written).
        void write_probe_result_file()
        {
            AcquireSRWLockShared(&g_probe_lock);
            const bool due = g_probe.active && g_probe.finished;
            ProbeJob job{};
            if (due) job = g_probe;
            ReleaseSRWLockShared(&g_probe_lock);
            if (!due) return;
            const std::string body = format_probe_result(job, instance_evidence_text());
            if (g_probe_writer.publish(body) != sbcore::status::PublishResult::Published) return;
            AcquireSRWLockExclusive(&g_probe_lock);
            if (g_probe.active && g_probe.finished && g_probe.generation == job.generation)
            {
                g_probe.active = false;
                g_probe.items.clear();
                g_probe.readings.clear();
            }
            ReleaseSRWLockExclusive(&g_probe_lock);
            g_probe_publishes.fetch_add(1, std::memory_order_relaxed);
            g_probe_last_status.store(job.status, std::memory_order_release);
        }

        const char* probe_state_name()
        {
            if (g_probe_running.load(std::memory_order_acquire)) return "reading";
            AcquireSRWLockShared(&g_probe_lock);
            const bool publishing = g_probe.active && g_probe.finished;
            ReleaseSRWLockShared(&g_probe_lock);
            if (publishing) return "publishing";
            return g_probe_publishes.load(std::memory_order_acquire) != 0 ? "done" : "idle";
        }

        // ---- A12: result, heartbeat and status files ------------------------
        void write_result_file()
        {
            AcquireSRWLockExclusive(&g_result_lock);
            if (!g_pending_result.active)
            {
                ReleaseSRWLockExclusive(&g_result_lock);
                return;
            }
            const PendingResult result = g_pending_result;
            ReleaseSRWLockExclusive(&g_result_lock);

            char body[2048]{};
            const int length = std::snprintf(body, sizeof(body),
                "protocol=%s\r\nsession=%s\r\nrequest_id=%s\r\npanel_seq=%llu\r\n"
                "status=%s\r\nterminal=%u\r\nbucket_guid=%u\r\nbefore=%u\r\nafter=%u\r\ndetail=%s\r\n",
                kProtocol, result.session.c_str(), result.request_id.c_str(),
                static_cast<unsigned long long>(result.panel_seq),
                result.status.c_str(), result.terminal ? 1U : 0U,
                result.bucket_guid, result.before, result.after,
                result.detail.c_str());
            if (length <= 0 || static_cast<std::size_t>(length) >= sizeof(body)) return;
            // The reply record keeps its v0.3.1 bytes (no header). A failed
            // write never replaces a published result; the slot stays full and
            // is retried on the next tick.
            if (g_result_writer.publish(std::string_view(body, static_cast<std::size_t>(length)))
                == sbcore::status::PublishResult::Published)
            {
                AcquireSRWLockExclusive(&g_result_lock);
                if (g_pending_result.active
                    && g_pending_result.panel_seq == result.panel_seq
                    && g_pending_result.request_id == result.request_id
                    && g_pending_result.session == result.session)
                {
                    g_pending_result = {};
                }
                ReleaseSRWLockExclusive(&g_result_lock);
            }
        }

        bool heartbeat_ready()
        {
            return g_ready.load(std::memory_order_acquire)
                && !g_dispatch_poisoned.load(std::memory_order_acquire)
                && !g_outcome_unknown.load(std::memory_order_acquire)
                && !g_side_effect_latched.load(std::memory_order_acquire)
                && !g_game_code_disabled.load(std::memory_order_acquire)
                && g_self_check_state.load(std::memory_order_acquire) == SelfCheckState::Passed;
        }

        // The v0.3.1 heartbeat body, byte for byte. Returns its length or 0.
        std::size_t format_heartbeat_body(char* body, std::size_t capacity, std::uint64_t beat,
                                          const std::string& session, bool ready, std::uint32_t bucket_guid,
                                          std::uint32_t target_guid, SelfCheckState self_check)
        {
            const int length = std::snprintf(body, capacity,
                "protocol=%s\r\nmodule=%s\r\nversion=%s\r\nready=%u\r\nsession=%s\r\nbeat=%llu\r\n"
                "inventory_bucket_guid=%u\r\ninventory_target_guid=%u\r\nselfcheck=%s\r\n",
                kProtocol, kModuleName, kVersion, ready ? 1U : 0U, session.c_str(),
                static_cast<unsigned long long>(beat), bucket_guid, target_guid,
                self_check_state_name(self_check));
            return length > 0 && static_cast<std::size_t>(length) < capacity ? static_cast<std::size_t>(length) : 0;
        }

        // The sbcore status header (the same keys sbcore::status::Publisher
        // writes), for the files this module assembles itself.
        void add_sbcore_header(sbcore::status::Builder& header, std::uint64_t sequence,
                               const sbcore::status::WriterCounters& counters)
        {
            header.add_u64("sbcore_protocol", sbcore::kStatusProtocol);
            header.add_str("sbcore_version", sbcore::kVersion);
            header.add_str("sbcore_module", kModuleName);
            header.add_str("sbcore_module_version", kVersion);
            header.add_u64("sbcore_pid", GetCurrentProcessId());
            header.add_u64("sbcore_seq", sequence);
            header.add_u64("sbcore_write_failures", counters.write_failures);
            header.add_u64("sbcore_rename_failures", counters.rename_failures);
        }

        // Heartbeat for the bridge: the sbcore header, then the v0.3.1 body
        // byte for byte (its session is empty while the module is not ready,
        // which sbcore's Builder would refuse, so the body is formatted here).
        // Written when its content changes (at most every 100 ms) and at
        // least every 500 ms; the beat advances with every write attempt.
        void write_heartbeat(bool force)
        {
            if (!g_heartbeat_writer.configured()) return;
            const std::uint64_t now = GetTickCount64();
            const std::string session = session_copy();
            const SelfCheckState self_check = g_self_check_state.load(std::memory_order_acquire);
            const bool ready = heartbeat_ready();
            const std::uint32_t bucket_guid = g_inventory_bucket_guid.load(std::memory_order_acquire);
            const std::uint32_t target_guid = g_inventory_target_guid.load(std::memory_order_acquire);
            char content[256]{};
            std::snprintf(content, sizeof(content), "%u|%s|%u|%u|%s", ready ? 1U : 0U, session.c_str(),
                          bucket_guid, target_guid, self_check_state_name(self_check));
            const std::uint64_t hash = sbcore::status::fnv1a64(content);
            HeartbeatPacing& pacing = g_heartbeat_pacing;
            if (!force)
            {
                const bool due = !pacing.published || pacing.last_failed || hash != pacing.last_hash
                    || now - pacing.last_success_ms >= kHeartbeatBeatMs;
                if (!due) return;
                if (pacing.attempted && now - pacing.last_attempt_ms < kHeartbeatMinIntervalMs) return;
            }
            pacing.attempted = true;
            pacing.last_attempt_ms = now;
            const std::uint64_t beat = g_heartbeat_beat.fetch_add(1, std::memory_order_acq_rel) + 1;
            char header_buffer[512];
            sbcore::status::Builder header(header_buffer, sizeof(header_buffer));
            add_sbcore_header(header, pacing.sequence + 1, g_heartbeat_writer.counters());
            char body[1024]{};
            const std::size_t length = format_heartbeat_body(body, sizeof(body), beat, session, ready,
                                                             bucket_guid, target_guid, self_check);
            if (!header.ok() || length == 0)
            {
                pacing.last_failed = true;
                return;
            }
            std::string text(header.view());
            text.append(body, length);
            if (g_heartbeat_writer.publish(text) == sbcore::status::PublishResult::Published)
            {
                pacing.published = true;
                pacing.last_failed = false;
                pacing.last_success_ms = now;
                pacing.last_hash = hash;
                ++pacing.sequence;
            }
            else
            {
                pacing.last_failed = true;
            }
        }

        // Every v0.3.1 status field, in order and with the same text, then
        // the v0.4.0 fields (appended). sbcore's Publisher prepends its header.
        void build_status(sbcore::status::Builder& body)
        {
            const PendingAdd pending = pending_copy();
            const auto worker = g_worker_thread_id.load(std::memory_order_acquire);
            const auto dispatch = sbcore::dispatch::counters();
            const auto callback = dispatch.callback_thread;
            const auto certified = dispatch.certified_game_thread;
            const char* gate_failed = g_gate_failed_check.load(std::memory_order_acquire);
            const SelfCheckState self_check = g_self_check_state.load(std::memory_order_acquire);
            AcquireSRWLockShared(&g_report_lock);
            const AddReport report = g_report;
            const std::string alias_snapshot = g_alias_snapshot;
            ReleaseSRWLockShared(&g_report_lock);
            const bool frame_known = g_server_frame_known.load(std::memory_order_acquire);
            const std::string frame_last = frame_known
                ? std::to_string(g_server_frame_last.load(std::memory_order_acquire)) : std::string("unknown");
            const std::string frame_at_add = report.frame_at_add_known
                ? std::to_string(report.frame_at_add) : std::string("unknown");
            const std::string count_before = report.before_known
                ? std::to_string(report.before) : std::string("unknown");
            const std::string count_after = report.after_known
                ? std::to_string(report.after) : std::string("unknown");
            const ItemCapacity& capacity = report.capacity;
            // Row flags are only known when the row itself was read.
            const char* row_flag_unknown = report.capacity_read && capacity.row_found ? "0" : "unknown";

            body.add_str("version", kVersion);
            body.add_str("protocol", kProtocol);
            body.add_str("certified_build", kCertifiedBuild);
            body.add_bool("ready", g_ready.load());
            body.add_bool("shutting_down", g_shutting_down.load());
            body.add_str("gate", g_gate_passed.load() ? "pass" : "fail");
            body.add_str("gate_failed_check", gate_failed && *gate_failed ? gate_failed : "unknown");
            body.add_str("selfcheck", self_check_state_name(self_check));
            body.add_str("selfcheck_step", g_self_check_step.load(std::memory_order_acquire));
            body.add_u64("selfcheck_attempts", g_self_check_attempts.load());
            body.add_bool("selfcheck_rpc_reflection", g_self_check_reflection_passed.load());
            body.add_u64("selfcheck_aliases_resolved", g_self_check_aliases_resolved.load());
            body.add_u64("selfcheck_aliases_read", g_self_check_aliases_read.load());
            body.add_u64("selfcheck_bucket_guid", g_self_check_bucket_guid.load());
            body.add_u64("selfcheck_target_guid", g_self_check_target_guid.load());
            body.add_u64("selfcheck_primary_map_entries", g_self_check_primary_entries.load());
            body.add_u64("selfcheck_type_map_entries", g_self_check_type_entries.load());
            body.add_bool("module_pinned", sbcore::module::pinned());
            body.add_bool("dispatch_poisoned", g_dispatch_poisoned.load());
            body.add_bool("outcome_unknown", g_outcome_unknown.load());
            body.add_bool("game_code_disabled", g_game_code_disabled.load());
            body.add_str("game_code_disabled_reason", g_game_code_disabled_reason.load(std::memory_order_acquire));
            body.add_u64("game_code_entries", g_game_code_entries.load());
            body.add_u64("game_code_refused", g_game_code_refused.load());
            body.add_str("hooks", "0");
            body.add_str("uobject_api_calls", "0");
            body.add_str("background_uobject_reads", "0");
            body.add_str("server_add_arg1", "null_signature_proven_unused");
            body.add_str("direct_inventory_writes", "0");
            body.add_str("direct_wallet_writes", "0");
            body.add_str("save_game_writes", "0");
            body.add_u64("worker_thread", worker);
            body.add_u64("callback_thread", callback);
            body.add_u64("certified_game_thread", certified);
            body.add_bool("callback_on_game_thread", callback != 0 && callback == certified);
            body.add_u64("submit_count", dispatch.submit_count);
            body.add_u64("callback_count", dispatch.callback_count);
            body.add_u64("destroy_count", dispatch.destroy_count);
            body.add_u64("server_add_calls", g_server_add_calls.load());
            body.add_u64("bucket_refresh_count", g_bucket_refresh_count.load());
            body.add_u64("inventory_bucket_guid", g_inventory_bucket_guid.load());
            body.add_u64("inventory_target_guid", g_inventory_target_guid.load());
            body.add_u64("last_panel_seq", g_last_panel_seq.load());
            body.add_bool("pending", pending.active);
            body.add_str("phase", phase_name(g_phase.load(std::memory_order_acquire)));
            body.add_str("result", result_name(g_result.load(std::memory_order_acquire)));
            body.add_hex32("last_exception", g_last_exception.load());
            // The v0.3.1 last-add block.
            body.add_str("last_alias", report.alias.empty() ? std::string_view("none") : std::string_view(report.alias));
            body.add_str("last_outcome", report.outcome ? report.outcome : "unknown");
            body.add_u64("last_qty_requested", report.qty_requested);
            body.add_u64("last_qty_sent", report.qty_sent);
            body.add_str("count_before", count_before);
            body.add_str("count_after_last", count_after);
            body.add_str("count_max_if_known", limit_token(capacity, report.capacity_read));
            body.add_str("count_max_source", report.capacity_read ? capacity.max_source : "unknown");
            body.add_str("item_row_found", report.capacity_read ? (capacity.row_found ? "1" : "0") : "unknown");
            body.add_str("item_inventory_alias_redirect", capacity.inventory_redirect ? "1" : row_flag_unknown);
            body.add_str("item_condition_group", capacity.condition_group ? "1" : row_flag_unknown);
            body.add_str("item_used_on_pickup", capacity.use_on_pickup ? "1" : row_flag_unknown);
            body.add_str("item_category", report.capacity_read && capacity.row_found
                                              ? std::to_string(capacity.category) : std::string("unknown"));
            body.add_u64("verify_window_ms", report.verify_window_ms);
            body.add_u64("verify_polls", report.verify_polls);
            body.add_bool("verify_paused_wait", report.paused_wait);
            body.add_bool("verify_paused_seen", report.paused_seen);
            body.add_str("rpc_return", "none_void_function_queues_server_frame_request");
            body.add_str("server_frame_at_add", frame_at_add);
            body.add_str("server_frame_last", frame_last);
            body.add_bool("server_frame_live", g_server_frame_live.load(std::memory_order_acquire));
            body.add_str("alias_snapshot_at_selfcheck", alias_snapshot.empty() ? std::string_view("none")
                                                                                  : std::string_view(alias_snapshot));
            // ---- v0.4.0 (appended) ----
            // A13: GameThread refresh is lease-driven. (No lease age or read
            // counter here: they would change the body, and so rewrite the
            // file, on every lease read while idle.)
            body.add_str("refresh_requires_panel_lease", "1");
            body.add_str("panel_lease", lease_state_name(g_panel_lease_state.load(std::memory_order_acquire)));
            body.add_u64("panel_lease_pid", g_panel_lease_pid.load());
            // A8/A11: the sbcore gate.
            body.add_str("gate_reason", g_gate_passed.load() ? "none" : sbcore::gate::reason_name(g_gate_result.reason));
            body.add_str("gate_failed_manifest", g_gate_result.failed_manifest[0] ? g_gate_result.failed_manifest : "none");
            body.add_u64("gate_code_checks", g_gate_result.code_checks_passed);
            body.add_u64("gate_slot_checks", g_gate_result.slot_checks_passed);
            body.add_u64("gate_global_checks", g_gate_result.global_checks_passed);
            body.add_u64("gate_manifests", g_gate_result.manifests_passed);
            const bool exe_checked = g_exe_identity_checked.load(std::memory_order_acquire);
            body.add_str("exe_sha256", exe_checked ? sbcore::exe_identity::result_name(g_exe_identity.result) : "not_checked");
            body.add_bool("exe_sha256_computed_here", exe_checked && g_exe_identity.computed_here);
            // sbcore::dispatch (the task bytes are v0.3.1's).
            body.add_u64("dispatch_submit_attempts", dispatch.submit_attempts);
            body.add_u64("dispatch_callbacks_run", dispatch.callbacks_run);
            body.add_u64("dispatch_skipped_blocked", dispatch.skipped_blocked);
            body.add_u64("dispatch_skipped_shutdown", dispatch.skipped_shutdown);
            body.add_u64("dispatch_wrong_thread", dispatch.wrong_thread);
            body.add_u64("dispatch_released_pre_setup", dispatch.released_pre_setup);
            body.add_u64("dispatch_last_submitted_sequence", dispatch.last_submitted_sequence);
            body.add_u64("dispatch_last_completed_sequence", dispatch.last_completed_sequence);
            body.add_bool("dispatch_in_flight", dispatch.pending);
            body.add_bool("dispatch_sbcore_poisoned", dispatch.poisoned);
            body.add_str("dispatch_last_submit",
                         sbcore::dispatch::submit_result_name(g_last_submit_result.load(std::memory_order_acquire)));
            body.add_u64("actions_abandoned_writes_blocked", g_actions_abandoned_blocked.load());
            // A9 stage 1: fault capture and the process-wide write block.
            const auto fault = sbcore::fault::snapshot();
            body.add_str("fault_policy", sbcore::fault::policy_name(fault.policy));
            body.add_bool("fault_initialized", fault.initialized);
            body.add_bool("fault_latch_available", fault.latch_available);
            body.add_bool("fault_local", fault.local_faulted);
            body.add_bool("fault_process_tainted", fault.process_tainted);
            body.add_bool("writes_blocked", sbcore::fault::writes_blocked_fast());
            body.add_u64("fault_count", fault.fault_count);
            body.add_hex32("fault_last_code", fault.last_code);
            body.add_str("fault_last_action", fault.last_action);
            body.add_str("fault_last_module", fault.last_module_kind);
            body.add_u64("fault_log_lines", fault.log_lines);
            body.add_u64("fault_log_failures", fault.log_failures);
            body.add_u64("fault_log_dropped", fault.log_dropped);
            // A12: the other two files this module writes, and its reader.
            const auto& heartbeat = g_heartbeat_writer.counters();
            body.add_u64("heartbeat_publishes", heartbeat.publishes);
            body.add_u64("heartbeat_write_failures", heartbeat.write_failures);
            body.add_u64("heartbeat_rename_failures", heartbeat.rename_failures);
            body.add_u64("heartbeat_rename_retries", heartbeat.rename_retries);
            const auto& result_counters = g_result_writer.counters();
            body.add_u64("result_publishes", result_counters.publishes);
            body.add_u64("result_write_failures", result_counters.write_failures);
            body.add_u64("result_rename_failures", result_counters.rename_failures);
            body.add_u64("status_rename_retries", g_status_publisher.writer().counters().rename_retries);
            body.add_str("request_read", sbcore::status::read_result_name(g_last_request_read.load(std::memory_order_acquire)));
            // ---- v0.5.0 (appended) ----
            // C1: the generated allowlist this build carries.
            body.add_str("allowlist_schema", kAllowlistSchema);
            body.add_str("allowlist_catalog_sha256", kAllowlistCatalogSha256);
            body.add_u64("allowlist_items", kAllowedItems.size());
            body.add_u64("allowlist_addable", kAllowlistAddableCount);
            body.add_u64("allowlist_gated", kAllowlistGatedCount);
            body.add_u64("max_request_quantity", kMaxRequestQuantity);
            // C8: sentinels; unique-instance counting proven this session.
            body.add_u64("sentinels", kSentinelItems.size());
            body.add_u64("sentinels_resolved", g_sentinels_resolved.load());
            body.add_str("instance_evidence", instance_evidence_text());
            // C3-C6: the last add's group, refusal reason and watch set.
            body.add_str("last_group", report.group ? report.group : "none");
            body.add_str("last_refusal_reason", report.refusal_reason ? report.refusal_reason : "none");
            body.add_u64("last_watch_count", report.watch_count);
            body.add_str("last_watch_changed", report.watch_changed.empty() ? std::string_view("none")
                                                                           : std::string_view(report.watch_changed));
            body.add_bool("side_effect_latched", g_side_effect_latched.load());
            // C7: the probe.
            std::string probe_last_id;
            AcquireSRWLockShared(&g_probe_lock);
            probe_last_id = g_probe_last_id;
            ReleaseSRWLockShared(&g_probe_lock);
            const Result probe_status = g_probe_last_status.load(std::memory_order_acquire);
            body.add_str("probe_state", probe_state_name());
            body.add_str("probe_last_id", probe_last_id.empty() ? std::string_view("none") : std::string_view(probe_last_id));
            body.add_str("probe_last_status", g_probe_publishes.load() == 0 ? "none"
                                              : probe_status == Result::None ? "ok" : result_name(probe_status));
            body.add_u64("probe_requests", g_probe_requests.load());
            body.add_u64("probe_refused", g_probe_refused.load());
            body.add_u64("probe_items_total", g_probe_items_total.load());
            body.add_u64("probe_items_done", g_probe_items_done.load());
            body.add_u64("probe_chunks", g_probe_chunks.load());
            body.add_u64("probe_publishes", g_probe_publishes.load());
            body.add_u64("probe_chunk_max", kProbeChunk);
            const auto& probe_counters = g_probe_writer.counters();
            body.add_u64("probe_write_failures", probe_counters.write_failures + probe_counters.rename_failures);
            // ---- v0.5.1 (appended) ----
            // The last add's AutoCharacterLevelUpType flag and StackAmount.
            body.add_str("item_auto_level_up", capacity.auto_level_type != 0 ? "1" : row_flag_unknown);
            body.add_str("item_stack_amount", report.capacity_read && capacity.row_found && capacity.stack_amount_read
                                                  ? std::to_string(capacity.stack_amount) : std::string("unknown"));
        }

        char g_status_buffer[16384];

        void write_status(bool force)
        {
            if (!g_status_publisher.writer().configured()) return;
            sbcore::status::Builder body(g_status_buffer, sizeof(g_status_buffer));
            build_status(body);
            g_status_publisher.maybe_publish(body, GetTickCount64(), force);
        }
    }

    bool verify_ue4ss_runtime()
    {
        return verify_module_file_sha256(
            GetModuleHandleW(L"UE4SS.dll"), L"UE4SS.dll",
            kExpectedUe4ssFileSize, kExpectedUe4ssTimestamp,
            kExpectedUe4ssImageSize, kExpectedUe4ssSha256);
    }

    bool install()
    {
        bool first_install = false;
        if (!g_install_attempted.compare_exchange_strong(
                first_install, true, std::memory_order_acq_rel, std::memory_order_acquire))
        {
            return false;
        }
        g_shutting_down.store(false, std::memory_order_release);
        // README order: paths (P1), fault capture (A9), pin, gate (A8/A11),
        // dispatcher bind. Any failure fails closed.
        bool ready = resolve_runtime_paths() && configure_files();
        if (!ready) g_gate_failed_check.store("runtime_paths", std::memory_order_release);
        if (ready)
        {
            ready = init_fault_capture();
            if (!ready) g_gate_failed_check.store("fault_init", std::memory_order_release);
        }
        if (ready)
        {
            ready = sbcore::module::pin_this_module();
            if (!ready) g_gate_failed_check.store("module_pin", std::memory_order_release);
        }
        if (ready) ready = resolve_exact_build();
        g_ready.store(ready, std::memory_order_release);
        if (ready)
        {
            generate_session();
        }
        if (!ready)
        {
            g_phase.store(Phase::Fault, std::memory_order_release);
            g_result.store(Result::BuildMismatch, std::memory_order_release);
        }
        // The worker starts only after the first publication (same lock as
        // run_update and shutdown), so the writers are never used concurrently.
        AcquireSRWLockExclusive(&g_update_lock);
        write_heartbeat(true);
        write_status(true);
        g_running.store(true, std::memory_order_release);
        ReleaseSRWLockExclusive(&g_update_lock);
        return ready;
    }

    void run_update()
    {
        if (!g_running.load(std::memory_order_acquire)) return;
        if (g_worker_thread_id.load(std::memory_order_relaxed) == 0)
            g_worker_thread_id.store(GetCurrentThreadId(), std::memory_order_release);
        const auto now = GetTickCount64();
        // A9: a fault anywhere in this process stops all game code here too.
        observe_process_write_block();
        // A task that sbcore refused to run (wrong thread) is recorded as a
        // correlated fault, as v0.3.1 recorded it from its invoke function.
        reconcile_dispatcher();
        if (now - g_last_command_poll_tick >= kCommandPollMs)
        {
            g_last_command_poll_tick = now;
            poll_request();
            poll_probe_request();
        }
        if (now - g_last_bucket_refresh_tick >= kBucketRefreshMs)
        {
            g_last_bucket_refresh_tick = now;
            // A13: no GameThread work while idle. A Refresh (and the first-use
            // self-check it runs) is scheduled only while the panel holds a
            // fresh Items lease; without one the published bucket is cleared.
            if (!refresh_panel_lease(now))
            {
                clear_published_bucket();
            }
            else if (refresh_may_be_scheduled(g_pending_action.load(std::memory_order_acquire),
                                              g_verify_scheduled.load(std::memory_order_acquire)))
            {
                g_pending_action.store(Action::Refresh, std::memory_order_release);
            }
        }
        if (g_verify_scheduled.load(std::memory_order_acquire)
            && now >= g_verify_due_tick.load(std::memory_order_acquire))
        {
            g_verify_scheduled.store(false, std::memory_order_release);
            g_pending_action.store(Action::Verify, std::memory_order_release);
        }
        // v0.5.0 (C7): a reading probe takes its next chunk whenever nothing
        // else is queued (an add or its verification always goes first).
        supervise_probe();
        if (probe_may_be_scheduled(g_pending_action.load(std::memory_order_acquire),
                                   g_verify_scheduled.load(std::memory_order_acquire)))
        {
            Action idle = Action::None;
            g_pending_action.compare_exchange_strong(idle, Action::Probe, std::memory_order_acq_rel,
                                                     std::memory_order_acquire);
        }
        if (g_pending_action.load(std::memory_order_acquire) != Action::None)
            dispatch_action();
        write_result_file();
        write_probe_result_file();
        if (now - g_last_publish_check_tick >= kPublishCheckMs)
        {
            g_last_publish_check_tick = now;
            write_heartbeat(false);
            write_status(false);
        }
    }

    void on_update()
    {
        AcquireSRWLockExclusive(&g_update_lock);
#if defined(_MSC_VER)
        __try
        {
            run_update();
        }
        __finally
        {
            ReleaseSRWLockExclusive(&g_update_lock);
        }
#else
        run_update();
        ReleaseSRWLockExclusive(&g_update_lock);
#endif
    }

    void shutdown()
    {
        g_shutting_down.store(true, std::memory_order_release);
        g_running.store(false, std::memory_order_release);
        // A task already queued runs no callback from here on.
        sbcore::dispatch::shutdown();
        AcquireSRWLockExclusive(&g_update_lock);
        AcquireSRWLockExclusive(&g_mutation_lock);
        g_ready.store(false, std::memory_order_release);
        g_pending_action.store(Action::None, std::memory_order_release);
        g_verify_scheduled.store(false, std::memory_order_release);
        const PendingAdd request = pending_copy();
        if (request.active)
        {
            if (request.mutation_attempted)
            {
                store_result(false, false, Result::NotVerified, request,
                             request.bucket_guid, request.before, request.before);
            }
            else
            {
                store_result(false, true, Result::DispatchFailed, request,
                             request.bucket_guid, request.before, request.before);
            }
        }
        clear_pending();
        ReleaseSRWLockExclusive(&g_mutation_lock);
        write_result_file();
        write_heartbeat(true);
        write_status(true);
        ReleaseSRWLockExclusive(&g_update_lock);
    }

#if defined(SBLIVEADD_PROTOCOL_TEST)
    // Offline test surface. Compiled only into tools/tests/protocol_harness.exe,
    // never into the shipped DLL (the build defines no SBLIVEADD_PROTOCOL_TEST).
    namespace test
    {
        struct Verdict
        {
            const char* result;
            bool correlated;
        };

        Verdict evaluate(const char* text, const char* module_session, std::uint64_t now_unix_s,
                         std::uint64_t current_beat, std::uint64_t last_panel_seq,
                         bool bucket_ready, bool self_check_ok, bool busy,
                         bool self_check_failed_state = false)
        {
            RequestContext context{};
            context.module_session = module_session;
            context.now_unix_s = now_unix_s;
            context.current_native_beat = current_beat;
            context.last_panel_seq = last_panel_seq;
            context.bucket_ready = bucket_ready;
            context.self_check_passed = self_check_ok;
            context.self_check_failed = self_check_failed_state;
            context.busy = busy;
            const RequestVerdict verdict = evaluate_request(text, context);
            return {verdict.result == Result::None ? "accept" : result_name(verdict.result),
                    verdict.correlated};
        }

        bool parse(const char* text, std::uint64_t* value)
        {
            std::uint64_t parsed = 0;
            const bool ok = parse_unsigned(text, parsed);
            if (ok && value) *value = parsed;
            return ok;
        }

        bool map_header_valid(std::uint64_t data, std::int32_t num, std::int32_t max,
                              std::int32_t num_free, std::uint64_t hash_heap,
                              std::int32_t hash_size, bool* empty)
        {
            SparseMapHeader header{};
            header.data = data;
            header.num = num;
            header.max = max;
            header.num_free = num_free;
            header.hash_heap = hash_heap;
            header.hash_size = hash_size;
            return sparse_map_header_valid(header, empty);
        }

        const char* image_signatures(const void* image)
        {
            return verify_image_signatures(static_cast<const std::byte*>(image));
        }

        const char* reflection_layout(const void* image)
        {
            return verify_reflection_layout(static_cast<const std::byte*>(image));
        }

        // ---- v0.5.0: the generated allowlist and its decisions ----
        std::size_t allowlist_size() { return kAllowedItems.size(); }
        std::size_t allowlist_addable() { return kAllowlistAddableCount; }
        std::size_t allowlist_gated() { return kAllowlistGatedCount; }
        std::size_t sentinel_count() { return kSentinelItems.size(); }
        std::uint32_t max_request_quantity() { return kMaxRequestQuantity; }
        const char* catalog_sha256() { return kAllowlistCatalogSha256; }
        bool allowlist_valid() { return allowlist_is_valid(); }

        struct ItemInfo
        {
            bool found;
            const char* group;
            std::uint32_t per_add_max;
            std::uint32_t category;
            std::int32_t game_max;
            std::uint32_t stat;
            const char* replacement;
            bool sentinel;
        };

        ItemInfo item_info(const char* alias)
        {
            const AllowedItem* item = find_allowed_item(alias ? alias : "");
            if (!item) return {false, "none", 0, 0, 0, 0, "none", false};
            return {true, item_group_name(item->group), item->per_add_max, item->category, item->game_max, item->stat,
                    item->replacement >= 0 ? kAllowedItems[static_cast<std::size_t>(item->replacement)].alias.data() : "none",
                    (item->flags & kItemFlagSentinel) != 0};
        }

        const char* sentinel_alias(std::size_t position)
        {
            return position < kSentinelItems.size() ? kAllowedItems[kSentinelItems[position]].alias.data() : nullptr;
        }

                                                                             
        // FNAME_Find result (pure; no game function).
        std::uint32_t fname_number(const char* alias) { return fname_number_of(alias ? alias : ""); }

        bool accept_fname(const char* alias, std::uint64_t resolved, std::uint32_t none_index, std::uint64_t* name_out)
        {
            return accept_found_fname(alias ? alias : "", resolved, none_index, name_out);
        }

        // Rows of the allowlist whose FName carries a number (addable, all).
        std::size_t numbered_rows(bool addable_only)
        {
            std::size_t count = 0;
            for (const AllowedItem& item : kAllowedItems)
            {
                if (fname_number_of(item.alias) != 0 && (!addable_only || item_group_addable(item.group))) ++count;
            }
            return count;
        }

        // A live row as read_item_capacity reports it. max_state: 0 unknown,
        // 1 none (0), 2 limit.
        struct Live
        {
            bool row_found;
            bool redirect;
            bool condition_group;
            bool use_on_pickup;
            std::uint32_t category;
            std::uint32_t stat;
            int max_state;
            std::uint32_t max_value;
            std::uint32_t auto_level_type;  // v0.5.1, last so older initializers still mean 0
            std::int32_t stack_amount;      // v0.5.1 (0 in older initializers: not per-unit)
            bool stack_amount_unreadable;   // v0.5.1
        };

        ItemCapacity capacity_of(const Live& live)
        {
            ItemCapacity capacity{};
            capacity.row_found = live.row_found;
            capacity.inventory_redirect = live.redirect;
            capacity.condition_group = live.condition_group;
            capacity.use_on_pickup = live.use_on_pickup;
            capacity.auto_level_type = live.auto_level_type;
            capacity.stack_amount_read = !live.stack_amount_unreadable;
            capacity.stack_amount = live.stack_amount;
            capacity.category = live.category;
            capacity.stat = live.stat;
            capacity.max_state = static_cast<MaxState>(live.max_state);
            capacity.max_value = live.max_value;
            capacity.max_source = live.stat != 0 ? "actor_stat" : "item_table";
            return capacity;
        }

        // The live row the catalog promises for this alias (stat rows: stat_value).
        Live catalog_row(const char* alias, std::uint32_t stat_value = 30)
        {
            const AllowedItem* item = find_allowed_item(alias ? alias : "");
            if (!item) return {};
            Live live{true, false, false, false, item->category, item->stat, 2,
                      item->stat != 0 ? stat_value : static_cast<std::uint32_t>(item->game_max)};
            if (item->stat != 0 && stat_value == 0) live.max_state = 1;
            return live;
        }

        struct Decision
        {
            const char* result;
            std::uint32_t qty;
            const char* reason;
        };

        Decision decide(const char* alias, const Live& live, std::uint32_t before, std::uint32_t qty, bool proven)
        {
            const AllowedItem* item = find_allowed_item(alias ? alias : "");
            if (!item) return {"not_allowlisted", 0, "none"};
            const ItemDecision decision = decide_item(*item, capacity_of(live), before, qty, proven);
            return {decision.result == Result::None ? "send" : result_name(decision.result), decision.qty_send,
                    decision.reason};
        }

        const char* row_check(const char* alias, const Live& live)
        {
            const AllowedItem* item = find_allowed_item(alias ? alias : "");
            return item ? row_mismatch(*item, capacity_of(live)) : "not_allowlisted";
        }

        struct Label
        {
            const char* state;
            std::uint32_t addable_now;
        };

        Label probe_item(const char* alias, bool name_found, bool count_ok, std::uint32_t count, const Live& live,
                         bool proven)
        {
            const AllowedItem* item = find_allowed_item(alias ? alias : "");
            if (!item) return {"not_allowlisted", 0};
            ProbeReading reading{};
            reading.taken = true;
            reading.name_found = name_found;
            reading.count_ok = count_ok;
            reading.count = count;
            reading.capacity = capacity_of(live);
            const ProbeLabel label = probe_label(*item, reading, proven);
            return {label.state, label.addable_now};
        }

        const char* watch(std::uint32_t before, std::uint32_t now)
        {
            switch (watch_change(before, now))
            {
            case WatchChange::Same: return "same";
            case WatchChange::Grew: return "grew";
            case WatchChange::Fell: return "fell";
            }
            return "unknown";
        }

        struct ProbeEval
        {
            const char* result;
            bool correlated;
            std::size_t items;
        };

        ProbeEval probe_request(const char* text, const char* session, std::uint64_t now_unix_s, bool self_check_ok,
                                bool self_check_failed_state = false, bool locked = false, bool lease_fresh = true)
        {
            ProbeContext context{};
            context.module_session = session;
            context.now_unix_s = now_unix_s;
            context.self_check_passed = self_check_ok;
            context.self_check_failed = self_check_failed_state;
            context.session_locked = locked;
            context.lease_fresh = lease_fresh;
            const ProbeVerdict verdict = evaluate_probe_request(text, context);
            return {verdict.result == Result::None ? "accept" : result_name(verdict.result), verdict.correlated,
                    verdict.items.size()};
        }

        // A finished probe of the given aliases with every reading taken from
        // the catalog row and the given count.
        std::string probe_body(const char* session, const char* probe_id, const std::vector<std::string>& aliases,
                               std::uint32_t count, int status)
        {
            ProbeJob job{};
            job.active = true;
            job.finished = true;
            job.session = session;
            job.probe_id = probe_id;
            job.status = static_cast<Result>(status);
            job.bucket_known = true;
            job.bucket_guid = 229;
            for (const auto& alias : aliases)
            {
                const AllowedItem* item = find_allowed_item(alias);
                if (!item) continue;
                job.items.push_back(allowed_item_index(item));
                ProbeReading reading{};
                reading.taken = true;
                reading.name_found = true;
                reading.count_ok = true;
                reading.count = count;
                reading.capacity = capacity_of(catalog_row(alias.c_str()));
                job.readings.push_back(reading);
            }
            return format_probe_result(job, instance_evidence_text());
        }

        void set_instance_evidence(std::uint32_t bits) { g_instance_evidence.store(bits, std::memory_order_release); }
        std::string instance_evidence() { return instance_evidence_text(); }
        bool proven(std::uint32_t category) { return instances_proven_for(category); }
        void note_count(const char* alias, std::uint32_t count)
        {
            if (const AllowedItem* item = find_allowed_item(alias ? alias : "")) note_item_count(*item, count);
        }
        void set_side_effect_latched(bool latched) { g_side_effect_latched.store(latched, std::memory_order_release); }
        bool side_effect_latched() { return g_side_effect_latched.load(std::memory_order_acquire); }
        bool ready_for_heartbeat() { return heartbeat_ready(); }
        const char* probe_state() { return probe_state_name(); }
        std::uint64_t probe_publishes() { return g_probe_publishes.load(std::memory_order_acquire); }
        std::uint64_t probe_chunks() { return g_probe_chunks.load(std::memory_order_acquire); }
        bool probe_running() { return g_probe_running.load(std::memory_order_acquire); }
        bool probe_schedulable() { return probe_may_be_scheduled(Action::None, false); }
        std::uint32_t max_stack_quantity() { return kMaxStackQuantity; }
        bool per_unit_proven(std::uint32_t category) { return per_unit_add_proven(category); }

        // Refresh/self-check gate surface. The harness only drives these
        // with image states in which no game function can be reached (the
        // client global unset, or a CurrentTargetGuid chain that is NoTarget
        // or Invalid), and counts wrapper entries to prove the ordering.
        void set_image(void* image) { g_image = static_cast<std::byte*>(image); }

        void reset_session_state()
        {
            g_self_check_state.store(SelfCheckState::Pending, std::memory_order_release);
            g_self_check_step.store("not_started", std::memory_order_release);
            g_self_check_reflection_passed.store(false, std::memory_order_release);
            g_game_code_disabled.store(false, std::memory_order_release);
            g_game_code_disabled_reason.store("none", std::memory_order_release);
            g_game_code_entries.store(0, std::memory_order_release);
            g_game_code_refused.store(0, std::memory_order_release);
            g_inventory_bucket_guid.store(0, std::memory_order_release);
            g_inventory_target_guid.store(0, std::memory_order_release);
            g_pending_action.store(Action::None, std::memory_order_release);
            g_server_frame_known.store(false, std::memory_order_release);
            g_server_frame_live.store(false, std::memory_order_release);
            g_server_frame_last.store(0, std::memory_order_release);
            // The refresh-gate cases model a panel that holds the Items lease.
            g_panel_lease_fresh.store(true, std::memory_order_release);
            // v0.5.0
            g_instance_evidence.store(0, std::memory_order_release);
            g_side_effect_latched.store(false, std::memory_order_release);
            g_sentinels_resolved.store(0, std::memory_order_release);
            g_sentinel_names = {};
            AcquireSRWLockExclusive(&g_probe_lock);
            g_probe = {};
            ReleaseSRWLockExclusive(&g_probe_lock);
            g_probe_running.store(false, std::memory_order_release);
        }

        // v0.3.1 pure decisions and read-only helpers.
        struct Capacity
        {
            bool refuse;
            std::uint32_t qty;
        };

        Capacity capacity(int state, std::uint32_t max_value, std::uint32_t before, std::uint32_t qty)
        {
            const CapacityDecision decision =
                decide_capacity(static_cast<MaxState>(state), max_value, before, qty);
            return {decision.refuse, decision.qty_send};
        }

        const char* verify(std::uint32_t before, std::uint32_t sent, std::uint32_t after,
                           std::uint64_t since_add_ms, bool frames_frozen, std::uint64_t since_resume_ms)
        {
            switch (decide_verify(before, sent, after, since_add_ms, frames_frozen, since_resume_ms))
            {
            case VerifyStep::Verified: return "verified";
            case VerifyStep::Mismatch: return "mismatch";
            case VerifyStep::Continue: return "continue";
            case VerifyStep::ContinuePaused: return "continue_paused";
            case VerifyStep::Unverified: return "unverified";
            }
            return "unknown";
        }

        bool frames_frozen(bool frame_comparable, std::uint32_t frame, std::uint32_t frame_at_add)
        {
            return frames_frozen_since_add(frame_comparable, frame, frame_at_add);
        }

        std::uint64_t verify_window_ms() { return kVerifyWindowMs; }
        std::uint64_t verify_paused_window_ms() { return kVerifyPausedWindowMs; }
        bool target_actor_stat(std::uint32_t stat, float* value) { return read_target_actor_stat(stat, value); }
        bool server_frame(std::uint32_t* frame) { return read_server_frame(frame); }
        bool sample_frame() { return sample_server_frame(); }
        bool server_frame_live() { return g_server_frame_live.load(std::memory_order_acquire); }
        std::uint8_t row_byte(const void* row, std::size_t offset) { return row_u8(row, offset); }
        bool name_is_none(std::uint64_t name, std::uint32_t none_index) { return fname_is_none(name, none_index); }
        const char* result_text(int result) { return result_name(static_cast<Result>(result)); }

        void force_self_check_state(int state)
        {
            g_self_check_state.store(static_cast<SelfCheckState>(state), std::memory_order_release);
        }

        int self_check_state() { return static_cast<int>(g_self_check_state.load(std::memory_order_acquire)); }
        const char* self_check_step() { return g_self_check_step.load(std::memory_order_acquire); }
        bool game_code_is_disabled() { return g_game_code_disabled.load(std::memory_order_acquire); }
        const char* game_code_reason() { return g_game_code_disabled_reason.load(std::memory_order_acquire); }
        std::uint64_t game_code_entries() { return g_game_code_entries.load(std::memory_order_acquire); }
        std::uint64_t game_code_refused() { return g_game_code_refused.load(std::memory_order_acquire); }
        void disable(const char* reason) { disable_game_code(reason); }

        void seed_published_bucket(std::uint32_t bucket_guid, std::uint32_t target_guid)
        {
            g_inventory_bucket_guid.store(bucket_guid, std::memory_order_release);
            g_inventory_target_guid.store(target_guid, std::memory_order_release);
        }

        std::uint32_t published_bucket_guid() { return g_inventory_bucket_guid.load(std::memory_order_acquire); }
        std::uint32_t published_target_guid() { return g_inventory_target_guid.load(std::memory_order_acquire); }

        void game_thread_refresh() { run_game_thread_action(Action::Refresh); }

        bool refresh_schedulable(bool verify_scheduled)
        {
            return refresh_may_be_scheduled(Action::None, verify_scheduled);
        }

        // Queues a Refresh and runs the dispatcher. True when the dispatcher
        // dropped the queued Refresh (game code off). The harness never sets
        // g_ready, so an allowed Refresh stops at the ready check and no task
        // is created.
        bool dispatch_drops_refresh()
        {
            g_pending_action.store(Action::Refresh, std::memory_order_release);
            dispatch_action();
            const bool dropped = g_pending_action.load(std::memory_order_acquire) == Action::None;
            g_pending_action.store(Action::None, std::memory_order_release);
            return dropped;
        }

        int target_chain(std::uint64_t client)
        {
            return static_cast<int>(inspect_current_target_chain(client));
        }

        // ---- v0.4.0: the sbcore gate, lease, dispatch and file surfaces ----
        sbcore::gate::Result full_gate(void* image, const wchar_t* exe_path)
        {
            static const sbcore::gate::Manifest* const extra[] = {&kLiveAddManifest};
            return sbcore::gate::validate(static_cast<std::byte*>(image), exe_path, extra, 1);
        }

        const sbcore::gate::Manifest& manifest() { return kLiveAddManifest; }
        const char* private_gate(const void* image) { return private_gate_failure(static_cast<const std::byte*>(image)); }

        bool lease_parses(const char* text) { return parse_panel_lease(text).valid; }

        const char* lease(const char* text, std::uint64_t now_unix_ms, bool check_process,
                          std::uint32_t* pid = nullptr, std::uint64_t* age = nullptr)
        {
            return lease_state_name(evaluate_panel_lease(text, now_unix_ms, check_process, pid, age));
        }

        void set_panel_lease_fresh(bool fresh) { g_panel_lease_fresh.store(fresh, std::memory_order_release); }
        bool panel_lease_fresh() { return g_panel_lease_fresh.load(std::memory_order_acquire); }
        const char* panel_lease_state() { return lease_state_name(g_panel_lease_state.load(std::memory_order_acquire)); }

        // Points every file at <root>\SBCheatGUI and <root>\SBLiveAddNative
        // (the harness's own work folder) and configures the writers.
        bool use_directory(const std::wstring& root)
        {
            const std::wstring panel = root + L"\\SBCheatGUI";
            const std::wstring mod = root + L"\\SBLiveAddNative";
            CreateDirectoryW(panel.c_str(), nullptr);
            CreateDirectoryW(mod.c_str(), nullptr);
            if (!is_plain_directory(panel) || !is_plain_directory(mod)) return false;
            g_mod_directory = mod;
            g_request_path = panel + L"\\live_add_native_request.txt";
            g_request_claim_path = panel + L"\\live_add_native_request.claimed";
            g_result_path = panel + L"\\live_add_native_result.txt";
            g_heartbeat_path = panel + L"\\live_add_native_heartbeat.txt";
            g_lease_path = panel + L"\\live_add_native_lease.txt";
            g_probe_request_path = panel + L"\\live_add_native_probe_request.txt";
            g_probe_claim_path = panel + L"\\live_add_native_probe_request.claimed";
            g_probe_result_path = panel + L"\\live_add_native_probe_result.txt";
            g_status_path = mod + L"\\live_add_native_status.txt";
            g_status_temp_path = mod + L"\\live_add_native_status.tmp";
            return configure_files();
        }

        void set_ready(bool ready) { g_ready.store(ready, std::memory_order_release); }
        void set_running(bool running) { g_running.store(running, std::memory_order_release); }

        void set_session(const char* session)
        {
            AcquireSRWLockExclusive(&g_session_lock);
            g_session = session ? session : "";
            ReleaseSRWLockExclusive(&g_session_lock);
        }

        void update() { on_update(); }
        std::uint64_t heartbeat_beat() { return g_heartbeat_beat.load(std::memory_order_acquire); }

        std::string heartbeat_body(std::uint64_t beat, const char* session, bool ready, std::uint32_t bucket_guid,
                                   std::uint32_t target_guid, int self_check)
        {
            char body[1024]{};
            const std::size_t length = format_heartbeat_body(body, sizeof(body), beat, session ? session : "", ready,
                                                             bucket_guid, target_guid,
                                                             static_cast<SelfCheckState>(self_check));
            return std::string(body, length);
        }

        struct StatusBuild
        {
            bool ok;
            std::string error;
            std::string text;
            std::size_t keys;
        };

        StatusBuild build_status_text()
        {
            static char buffer[16384];
            sbcore::status::Builder body(buffer, sizeof(buffer));
            build_status(body);
            return {body.ok(), body.error(), std::string(body.view()), body.key_count()};
        }

        bool dispatch_poisoned() { return g_dispatch_poisoned.load(std::memory_order_acquire); }
        const char* last_result() { return result_name(g_result.load(std::memory_order_acquire)); }
        const char* phase() { return phase_name(g_phase.load(std::memory_order_acquire)); }
        int pending_action() { return static_cast<int>(g_pending_action.load(std::memory_order_acquire)); }
        bool pending_add_active() { return pending_active(); }
        std::uint64_t bucket_refreshes() { return g_bucket_refresh_count.load(std::memory_order_acquire); }
        std::uint64_t actions_abandoned() { return g_actions_abandoned_blocked.load(std::memory_order_acquire); }
        void observe_write_block() { observe_process_write_block(); }

        // A pending add whose single game call already happened (the Verify
        // path); no game function is reachable from the helpers it feeds.
        void seed_attempted_add(std::uint64_t panel_seq, const char* session, const char* request_id)
        {
            PendingAdd request{};
            request.active = true;
            request.panel_seq = panel_seq;
            request.session = session;
            request.request_id = request_id;
            request.alias = "PulseGrenade";
            request.qty = 1;
            request.before = 3;
            request.bucket_guid = 0x11;
            request.target_guid = 0x22;
            request.mutation_attempted = true;
            request.qty_sent = 1;
            AcquireSRWLockExclusive(&g_pending_lock);
            g_pending = request;
            ReleaseSRWLockExclusive(&g_pending_lock);
            g_verify_scheduled.store(false, std::memory_order_release);
            g_pending_action.store(Action::Verify, std::memory_order_release);
        }
    }
#endif
}
