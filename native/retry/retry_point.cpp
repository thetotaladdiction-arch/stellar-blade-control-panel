// SBRetryPointNative - explicit, fail-closed Retry Point for Stellar Blade.
//
// UE4SS calls on_update() on its worker. That worker performs bounded file I/O
// and TaskGraph submission only. Every UObject lookup/read and the single
// game-owned ServerRequest_WarpPosition action run in a callback that sbcore's
// dispatcher runs only when the executing thread equals the gate-proven
// GGameThreadId of the exact shipping build. No hook is registered and no
// direct actor-location field is written.
//
// v0.2.0: the private gate, TaskGraph dispatch, status writer, SEH handling,
// UE4SS shim and module paths of v0.1.1 are replaced by sbcore 0.1.0 (plan
// A1, A8, A9 stage 1, A11, A12, P1). Behaviour and every v0.1.1 status field
// are kept; new status fields are appended after last_exception.
//
// v0.2.1: v0.1.1 was /MT, so its CRT locale was private and always "C". The
// /MD build shares ucrtbase's process-global locale with UE4SS.dll and the
// game (both import setlocale). Every floating-point number in the point file
// and in point_x/y/z is therefore formatted and parsed with an explicit "C"
// locale, so the bytes are v0.1.1's whatever that global locale is.
//
// v0.2.2: the loaded-area check. While the bound panel keeps a fresh watch
// lease (Mods/SBCheatGUI/retry_point_watch.txt, same pid/token/issued_ms rules
// as a command) and a point is saved, one GameThread task every
// kWorldCheckIntervalMs reads the loaded World's name (the Set Point/Return
// walk, reads only) and publishes current_world_hash, so the panel can say
// "another area" before Return is pressed. Nothing is read without that
// lease, a check never changes phase/result or the command sequences, a user
// command always goes first, and a check never runs after a fault latched.
//
// v0.2.3: the check is cheap. 0.2.2 found the controller with FindAllOf on
// every check, which walks every UObject: 14 ms at the title screen and
                                                                        
                                                                          
                                                                          
// its World directly, after proving it is still that object (same first
// pointer, same full name). A viewport that no longer proves itself is
// dropped and the next check walks again.

#include "retry_point.hpp"
#include "ue4ss_minimal.hpp"

#include "sbcore/sbcore.hpp"

#include <algorithm>
#include <array>
#include <atomic>
#include <cerrno>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <limits>
#include <string>
#include <string_view>
#include <vector>

#include <locale.h> // _create_locale, _locale_t (UCRT)
#include <stdio.h>  // _snprintf_s_l
#include <stdlib.h> // _strtof_l, _strtoull_l

#include <windows.h>

namespace sbretrypoint
{
    namespace
    {
        constexpr char kVersion[] = "0.2.3";
        constexpr char kNativeName[] = "SBRetryPointNative";
        constexpr char kArchitecture[] = "explicit_one_shot_taskgraph_game_thread_game_owned_warp";
        constexpr std::uint32_t kCommandSchema = 1;
        constexpr std::uint32_t kPointSchema = 1;
        constexpr std::uint64_t kCommandLeaseMs = 5'000;
        constexpr std::uint64_t kFutureClockToleranceMs = 2'000;
        constexpr std::uint64_t kVerifyDelayMs = 500;
        constexpr std::uint64_t kCommandPollMs = 50;
        // v0.2.2 loaded-area check: the panel's watch lease is read every
        // kWatchPollMs and lasts kWatchLeaseMs (the command lease); while it is
        // fresh and a point is saved, one read-only GameThread check runs
        // every kWorldCheckIntervalMs.
        constexpr std::uint32_t kWatchSchema = 1;
        constexpr std::uint64_t kWatchPollMs = 250;
        constexpr std::uint64_t kWatchLeaseMs = 5'000;
        constexpr std::uint64_t kWorldCheckIntervalMs = 3'000;
        // The body is rebuilt at most every 100 ms (the v0.1.1 cadence) and
        // written when it changed, plus a liveness beat. The panel treats a
        // Retry Point status older than 1.5 s as stale: beat <= 1.5 s / 3.
        constexpr std::uint64_t kStatusTickMs = 100;
        constexpr std::uint64_t kStatusBeatMs = 500;
        constexpr float kAlreadyThereDistance = 75.0F;
        constexpr float kVerifyDistance = 180.0F;
        constexpr float kMaxReturnDistance = 5'000'000.0F;
        constexpr float kMaxCoordinateMagnitude = 20'000'000.0F;
        constexpr std::uint64_t kPointChecksumSalt = 0xA47E11B5D39C620FULL;
        constexpr wchar_t kWarpFunctionName[] = L"ServerRequest_WarpPosition";
        constexpr wchar_t kWarpFunctionFullName[] =
            L"Function /Script/SB.SBNetworkPlayerController:ServerRequest_WarpPosition";

        // The exact-build gate (TDS 0x6A6A3B74 / SOI 0x15981000, exe size,
        // TaskGraph + GGameThreadId manifest and the exact 64/42/36/12-byte
        // images v0.1.1 pinned) is sbcore::gate; this native touches no other
        // exe code or data, so it passes no extra manifest.

        struct Vector3f
        {
            float x{};
            float y{};
            float z{};
        };
        static_assert(sizeof(Vector3f) == 0xC);

        struct Rotator3f
        {
            float pitch{};
            float yaw{};
            float roll{};
        };
        static_assert(sizeof(Rotator3f) == 0xC);

        struct WarpPositionParams
        {
            std::int32_t player_id{};
            Vector3f location{};
            Rotator3f rotation{};
        };
        static_assert(sizeof(WarpPositionParams) == 0x1C);

        struct PointData
        {
            bool valid{};
            std::uint64_t world_hash{};
            Vector3f location{};
            Rotator3f rotation{};
            std::uint64_t checksum{};
        };

        struct LiveContext
        {
            RC::Unreal::UObject* controller{};
            RC::Unreal::UObject* pawn{};
            RC::Unreal::UObject* player_state{};
            RC::Unreal::UObject* world{};
            std::int32_t player_id{};
            PointData current{};
        };

        enum class Action : std::uint32_t
        {
            None,
            Save,
            Return,
            Verify,
            WorldCheck, // v0.2.2: read the loaded World only (never a command answer)
        };

        enum class Phase : std::uint32_t
        {
            Idle,
            SavePending,
            SaveCaptured,
            Saved,
            ReturnPending,
            VerifyPending,
            Returned,
            Cleared,
            Fault,
        };

        enum class Result : std::uint32_t
        {
            None,
            Saved,
            Cleared,
            Returned,
            AlreadyAtPoint,
            CommandInvalid,
            CommandStale,
            PanelGone,
            PanelSessionMismatch,
            Busy,
            PointMissing,
            PointInvalid,
            PointWriteFailed,
            BuildMismatch,
            WrongThread,
            ContextInvalid,
            WorldMismatch,
            TargetTooFar,
            FunctionMissing,
            FunctionIdentityMismatch,
            WarpRequested,
            VerificationFailed,
            DispatchFailed,
            DispatchException,
            // 0.2.0 (appended):
            WritesBlocked,         // a fault latched sbcore's write block (this or another native)
            FaultLatchUnavailable, // sbcore::fault::init could not create the process latch
        };

        // v0.2.2: the panel's watch lease, as last read.
        enum class Watch : std::uint32_t
        {
            None,           // no watch file
            Active,         // fresh lease from the bound (or now bound) panel
            Invalid,        // malformed, wrong schema or token format
            Stale,          // older than kWatchLeaseMs, from the future, or issued_ms=0
            PanelGone,      // the watching panel process is not alive
            SessionMismatch // another live panel is bound
        };

        enum class WorldCheck : std::uint32_t
        {
            None,
            Ok,
            ContextInvalid,
            DispatchFailed, // no more checks in this game session
        };

        enum class InstallStep : std::uint32_t
        {
            None,
            Paths,
            FaultInit,
            Pin,
            Gate,
            Bind,
        };

        std::atomic<bool> g_running{false};
        std::atomic<bool> g_shutting_down{false};
        std::atomic<bool> g_ready{false};
        // This module's own GameThread action faulted (v0.1.1 dispatch_poisoned).
        std::atomic<bool> g_dispatch_poisoned{false};
        std::atomic<Action> g_pending_action{Action::None};
        std::atomic<Phase> g_phase{Phase::Idle};
        std::atomic<Result> g_result{Result::None};
        std::atomic<std::uint64_t> g_active_command_sequence{0};
        std::atomic<std::uint64_t> g_last_seen_command_sequence{0};
        std::atomic<std::uint64_t> g_last_completed_command_sequence{0};
        std::atomic<std::uint64_t> g_game_owned_warp_calls{0};
        std::atomic<std::uint32_t> g_worker_thread_id{0};
        std::atomic<std::uint32_t> g_last_exception{0};
        std::atomic<bool> g_point_file_dirty{false};
        std::atomic<bool> g_verify_scheduled{false};
        std::atomic<std::uint64_t> g_verify_due_tick{0};
        std::atomic<std::uint64_t> g_current_world_hash{0};
        std::atomic<std::uint64_t> g_current_controller{0};
        std::atomic<std::uint64_t> g_current_pawn{0};
        std::atomic<InstallStep> g_install_failed_step{InstallStep::None};
        // v0.2.2 loaded-area check.
        std::atomic<Watch> g_watch{Watch::None};
        // The task in flight (if any) was submitted for a world check and has
        // not picked up a user action: a user command is not "busy" behind it.
        std::atomic<bool> g_task_is_world_check{false};
        std::atomic<WorldCheck> g_world_check_result{WorldCheck::None};
        std::atomic<std::uint64_t> g_world_checks{0};
        std::atomic<std::uint64_t> g_world_check_failures{0};
        std::atomic<std::uint64_t> g_world_checked_unix_ms{0};
        std::atomic<std::uint64_t> g_world_check_last_us{0};
        std::atomic<std::uint64_t> g_world_check_max_us{0};
        // v0.2.3: full walks (FindAllOf) the checks needed; the rest read the
        // cached viewport's World.
        std::atomic<std::uint64_t> g_world_check_full_walks{0};
        std::atomic<bool> g_world_check_cached{false}; // the last check used the cached viewport
        // GameThread only (the check's callback): the viewport the last full
        // walk found, with what proves it is still that object.
        RC::Unreal::UObject* g_cached_viewport{};
        std::uint64_t g_cached_viewport_first{};
        std::wstring g_cached_viewport_name;

        SRWLOCK g_point_lock = SRWLOCK_INIT;
        PointData g_point{};

        std::wstring g_command_path;
        std::wstring g_watch_path;
        std::wstring g_point_path;
        std::wstring g_point_temp_path;
        sbcore::status::Writer g_point_writer; // install() and the UE4SS worker only

        // Status publishing may run from install(), the worker and shutdown().
        SRWLOCK g_status_lock = SRWLOCK_INIT;
        sbcore::status::Publisher g_status_publisher; // under g_status_lock
        bool g_status_configured{};                   // under g_status_lock
        sbcore::gate::Result g_gate{};                // under g_status_lock
        char g_status_buffer[8192]{};                 // under g_status_lock
        std::uint64_t g_status_body_errors{};         // under g_status_lock

        // UE4SS worker only.
        std::uint32_t g_bound_panel_pid{};
        std::string g_bound_panel_token;
        std::uint64_t g_last_command_poll_tick{};
        std::uint64_t g_last_watch_poll_tick{};
        std::uint64_t g_last_world_check_tick{};
        bool g_watch_was_active{};
        // The last well-formed watch lease read (a replace can hide the file
        // for a few ms; the remembered lease still expires on time).
        struct WatchLease
        {
            bool valid{};
            std::uint32_t panel_pid{};
            std::uint64_t issued_ms{};
            std::string token;
        };
        WatchLease g_watch_lease;
        std::uint64_t g_last_status_tick{};
        std::uint64_t g_seen_wrong_thread{};
        std::uint64_t g_seen_skipped_blocked{};

        const char* phase_name(Phase phase)
        {
            switch (phase)
            {
            case Phase::Idle: return "idle";
            case Phase::SavePending: return "save_pending";
            case Phase::SaveCaptured: return "save_captured";
            case Phase::Saved: return "saved";
            case Phase::ReturnPending: return "return_pending";
            case Phase::VerifyPending: return "verify_pending";
            case Phase::Returned: return "returned";
            case Phase::Cleared: return "cleared";
            case Phase::Fault: return "fault";
            }
            return "unknown";
        }

        const char* result_name(Result result)
        {
            switch (result)
            {
            case Result::None: return "none";
            case Result::Saved: return "saved";
            case Result::Cleared: return "cleared";
            case Result::Returned: return "returned_verified";
            case Result::AlreadyAtPoint: return "already_at_point";
            case Result::CommandInvalid: return "command_invalid";
            case Result::CommandStale: return "command_stale";
            case Result::PanelGone: return "panel_gone";
            case Result::PanelSessionMismatch: return "panel_session_mismatch";
            case Result::Busy: return "busy";
            case Result::PointMissing: return "point_missing";
            case Result::PointInvalid: return "point_invalid_or_modified";
            case Result::PointWriteFailed: return "point_write_failed";
            case Result::BuildMismatch: return "build_mismatch";
            case Result::WrongThread: return "wrong_thread";
            case Result::ContextInvalid: return "live_context_invalid";
            case Result::WorldMismatch: return "different_loaded_world";
            case Result::TargetTooFar: return "target_distance_refused";
            case Result::FunctionMissing: return "warp_function_missing";
            case Result::FunctionIdentityMismatch: return "warp_function_identity_mismatch";
            case Result::WarpRequested: return "game_owned_warp_requested";
            case Result::VerificationFailed: return "return_not_verified";
            case Result::DispatchFailed: return "dispatch_failed";
            case Result::DispatchException: return "dispatch_exception";
            case Result::WritesBlocked: return "writes_blocked_after_fault";
            case Result::FaultLatchUnavailable: return "fault_latch_unavailable";
            }
            return "unknown";
        }

        const char* watch_name(Watch watch)
        {
            switch (watch)
            {
            case Watch::None: return "none";
            case Watch::Active: return "active";
            case Watch::Invalid: return "invalid";
            case Watch::Stale: return "stale";
            case Watch::PanelGone: return "panel_gone";
            case Watch::SessionMismatch: return "panel_session_mismatch";
            }
            return "unknown";
        }

        const char* world_check_name(WorldCheck check)
        {
            switch (check)
            {
            case WorldCheck::None: return "none";
            case WorldCheck::Ok: return "ok";
            case WorldCheck::ContextInvalid: return "live_context_invalid";
            case WorldCheck::DispatchFailed: return "dispatch_failed";
            }
            return "unknown";
        }

        const char* install_step_name(InstallStep step)
        {
            switch (step)
            {
            case InstallStep::None: return "none";
            case InstallStep::Paths: return "paths";
            case InstallStep::FaultInit: return "fault_init";
            case InstallStep::Pin: return "pin";
            case InstallStep::Gate: return "gate";
            case InstallStep::Bind: return "bind";
            }
            return "unknown";
        }

        // The "C" locale v0.1.1's private /MT CRT always used. Created once and
        // never freed (the module is pinned). nullptr only if the CRT is out of
        // memory: point-file floats then fail closed.
        _locale_t c_locale()
        {
            static const _locale_t locale = _create_locale(LC_ALL, "C");
            return locale;
        }

        bool valid_token(std::string_view token)
        {
            if (token.size() != 32) return false;
            return std::all_of(token.begin(), token.end(), [](char c) {
                return (c >= '0' && c <= '9') || (c >= 'a' && c <= 'f') || (c >= 'A' && c <= 'F');
            });
        }

        std::uint64_t fnv1a_bytes(std::uint64_t hash, const void* data, std::size_t size)
        {
            const auto* bytes = static_cast<const std::uint8_t*>(data);
            for (std::size_t i = 0; i < size; ++i)
            {
                hash ^= bytes[i];
                hash *= 1099511628211ULL;
            }
            return hash;
        }

        std::uint64_t hash_world_name(const std::wstring& name)
        {
            return fnv1a_bytes(1469598103934665603ULL, name.data(), name.size() * sizeof(wchar_t));
        }

        std::uint64_t point_checksum(const PointData& point)
        {
            std::uint64_t hash = 1469598103934665603ULL;
            hash = fnv1a_bytes(hash, &kPointChecksumSalt, sizeof(kPointChecksumSalt));
            hash = fnv1a_bytes(hash, &point.world_hash, sizeof(point.world_hash));
            hash = fnv1a_bytes(hash, &point.location, sizeof(point.location));
            hash = fnv1a_bytes(hash, &point.rotation, sizeof(point.rotation));
            return hash;
        }

        bool finite_vector(const Vector3f& value)
        {
            return std::isfinite(value.x) && std::isfinite(value.y) && std::isfinite(value.z)
                && std::fabs(value.x) <= kMaxCoordinateMagnitude
                && std::fabs(value.y) <= kMaxCoordinateMagnitude
                && std::fabs(value.z) <= kMaxCoordinateMagnitude;
        }

        bool finite_rotation(const Rotator3f& value)
        {
            return std::isfinite(value.pitch) && std::isfinite(value.yaw) && std::isfinite(value.roll)
                && std::fabs(value.pitch) <= 1'000'000.0F
                && std::fabs(value.yaw) <= 1'000'000.0F
                && std::fabs(value.roll) <= 1'000'000.0F;
        }

        bool valid_point(const PointData& point)
        {
            return point.valid && point.world_hash != 0 && finite_vector(point.location)
                && finite_rotation(point.rotation) && point.checksum == point_checksum(point);
        }

        float distance_between(const Vector3f& a, const Vector3f& b)
        {
            const double dx = static_cast<double>(a.x) - b.x;
            const double dy = static_cast<double>(a.y) - b.y;
            const double dz = static_cast<double>(a.z) - b.z;
            const double squared = dx * dx + dy * dy + dz * dz;
            if (!std::isfinite(squared)) return std::numeric_limits<float>::infinity();
            return static_cast<float>(std::sqrt(squared));
        }

        PointData point_copy()
        {
            AcquireSRWLockShared(&g_point_lock);
            const PointData copy = g_point;
            ReleaseSRWLockShared(&g_point_lock);
            return copy;
        }

        void replace_point(const PointData& point)
        {
            AcquireSRWLockExclusive(&g_point_lock);
            g_point = point;
            ReleaseSRWLockExclusive(&g_point_lock);
        }

        // Same bytes as v0.1.1 (fprintf to a "wb" stream in the "C" locale),
        // written through sbcore's Writer: CREATE_NEW temp, checked write,
        // FlushFileBuffers (the point is persistent state), POSIX rename over
        // the final name.
        bool write_point_file()
        {
            const PointData point = point_copy();
            const _locale_t locale = c_locale();
            if (!valid_point(point) || !locale) return false;
            char text[512];
            const int length = _snprintf_s_l(
                text, sizeof(text), _TRUNCATE,
                "schema=%u\r\n"
                "world_hash=%016llX\r\n"
                "x=%.9g\r\ny=%.9g\r\nz=%.9g\r\n"
                "pitch=%.9g\r\nyaw=%.9g\r\nroll=%.9g\r\n"
                "checksum=%016llX\r\n",
                locale,
                kPointSchema,
                static_cast<unsigned long long>(point.world_hash),
                static_cast<double>(point.location.x), static_cast<double>(point.location.y),
                static_cast<double>(point.location.z),
                static_cast<double>(point.rotation.pitch), static_cast<double>(point.rotation.yaw),
                static_cast<double>(point.rotation.roll),
                static_cast<unsigned long long>(point.checksum));
            if (length <= 0 || static_cast<std::size_t>(length) >= sizeof(text)) return false;
            return g_point_writer.publish(std::string_view(text, static_cast<std::size_t>(length)), true)
                == sbcore::status::PublishResult::Published;
        }

        bool parse_unsigned(std::string_view text, std::uint64_t& value, int base = 10)
        {
            if (text.empty() || text.size() > 32) return false;
            std::string copy(text);
            char* end{};
            errno = 0;
            // Digits do not depend on the locale (only leading white space
            // does); use the "C" locale when it exists, as v0.1.1 did.
            const _locale_t locale = c_locale();
            const auto parsed = locale ? _strtoull_l(copy.c_str(), &end, base, locale)
                                       : std::strtoull(copy.c_str(), &end, base);
            if (errno != 0 || !end || *end != '\0') return false;
            value = parsed;
            return true;
        }

        bool parse_float(std::string_view text, float& value)
        {
            if (text.empty() || text.size() > 48) return false;
            const _locale_t locale = c_locale();
            if (!locale) return false; // never parse a point in whatever the global locale is
            std::string copy(text);
            char* end{};
            errno = 0;
            const float parsed = _strtof_l(copy.c_str(), &end, locale);
            if (errno != 0 || !end || *end != '\0' || !std::isfinite(parsed)) return false;
            value = parsed;
            return true;
        }

        bool load_point_file()
        {
            std::string text;
            if (sbcore::status::read_small_file(g_point_path, text) != sbcore::status::ReadResult::Ok) return false;
            PointData point{};
            std::uint64_t schema{};
            bool saw_schema{}, saw_world{}, saw_x{}, saw_y{}, saw_z{};
            bool saw_pitch{}, saw_yaw{}, saw_roll{}, saw_checksum{};
            bool invalid_format{};
            std::size_t position{};
            while (position < text.size())
            {
                const auto end = text.find('\n', position);
                std::string line = text.substr(position, end == std::string::npos ? text.size() - position : end - position);
                position = end == std::string::npos ? text.size() : end + 1;
                if (!line.empty() && line.back() == '\r') line.pop_back();
                const auto equals = line.find('=');
                if (equals == std::string::npos)
                {
                    invalid_format = true;
                    continue;
                }
                const std::string_view key(line.data(), equals);
                const std::string_view value(line.data() + equals + 1, line.size() - equals - 1);
                std::uint64_t unsigned_value{};
                if (key == "schema" && !saw_schema && parse_unsigned(value, unsigned_value)) { schema = unsigned_value; saw_schema = true; }
                else if (key == "world_hash" && !saw_world && parse_unsigned(value, unsigned_value, 16)) { point.world_hash = unsigned_value; saw_world = true; }
                else if (key == "x" && !saw_x) saw_x = parse_float(value, point.location.x);
                else if (key == "y" && !saw_y) saw_y = parse_float(value, point.location.y);
                else if (key == "z" && !saw_z) saw_z = parse_float(value, point.location.z);
                else if (key == "pitch" && !saw_pitch) saw_pitch = parse_float(value, point.rotation.pitch);
                else if (key == "yaw" && !saw_yaw) saw_yaw = parse_float(value, point.rotation.yaw);
                else if (key == "roll" && !saw_roll) saw_roll = parse_float(value, point.rotation.roll);
                else if (key == "checksum" && !saw_checksum && parse_unsigned(value, unsigned_value, 16)) { point.checksum = unsigned_value; saw_checksum = true; }
                else invalid_format = true;
            }
            point.valid = !invalid_format && schema == kPointSchema && saw_schema && saw_world && saw_x && saw_y && saw_z
                && saw_pitch && saw_yaw && saw_roll && saw_checksum;
            if (!valid_point(point)) return false;
            replace_point(point);
            return true;
        }

        template <typename T>
        bool read_value_property(RC::Unreal::UObject* object, const wchar_t* name, T& value)
        {
            value = {};
            if (!sbcore::memory::plausible_object(object)) return false;
            try
            {
                void* field = object->GetValuePtrByPropertyNameInChain(name);
                return field && sbcore::memory::read_exact(field, &value, sizeof(value));
            }
            catch (...)
            {
                return false;
            }
        }

        bool read_object_property(
            RC::Unreal::UObject* object,
            const wchar_t* name,
            RC::Unreal::UObject*& value)
        {
            value = nullptr;
            return read_value_property(object, name, value) && sbcore::memory::plausible_object(value);
        }

        bool resolve_live_context(LiveContext& context)
        {
            context = {};
            std::vector<RC::Unreal::UObject*> controllers;
            try { RC::Unreal::UObjectGlobals::FindAllOf(L"SBNetworkPlayerController", controllers); }
            catch (...) { return false; }

            std::uint32_t viable{};
            for (auto* controller : controllers)
            {
                if (!sbcore::memory::plausible_object(controller)) continue;
                std::wstring name;
                try { name = controller->GetFullName(); }
                catch (...) { continue; }
                if (name.rfind(L"SBNetworkPlayerController ", 0) != 0
                    || name.find(L"Default__") != std::wstring::npos)
                {
                    continue;
                }
                RC::Unreal::UObject* pawn{};
                RC::Unreal::UObject* player_state{};
                if (!read_object_property(controller, L"Pawn", pawn)
                    || !read_object_property(controller, L"PlayerState", player_state))
                {
                    continue;
                }
                ++viable;
                if (viable == 1)
                {
                    context.controller = controller;
                    context.pawn = pawn;
                    context.player_state = player_state;
                }
            }
            if (viable != 1 || !context.controller || !context.pawn || !context.player_state) return false;

            RC::Unreal::UObject* acknowledged{};
            RC::Unreal::UObject* local_player{};
            RC::Unreal::UObject* controller_backref{};
            RC::Unreal::UObject* viewport{};
            RC::Unreal::UObject* world{};
            RC::Unreal::UObject* camera_manager{};
            RC::Unreal::UObject* view_target{};
            RC::Unreal::UObject* root{};
            RC::Unreal::UObject* pending_visibility{};
            RC::Unreal::UObject* pending_invisibility{};

            if (!read_object_property(context.controller, L"AcknowledgedPawn", acknowledged)
                || acknowledged != context.pawn
                || !read_object_property(context.controller, L"Player", local_player)
                || !read_object_property(local_player, L"PlayerController", controller_backref)
                || controller_backref != context.controller
                || !read_object_property(local_player, L"ViewportClient", viewport)
                || !read_object_property(viewport, L"World", world)
                || !read_object_property(context.controller, L"PlayerCameraManager", camera_manager)
                || !read_object_property(camera_manager, L"ViewTarget", view_target)
                || view_target != context.pawn
                || !read_object_property(context.pawn, L"RootComponent", root))
            {
                return false;
            }

            // These fields legitimately contain null while the world is stable.
            if (!read_value_property(world, L"CurrentLevelPendingVisibility", pending_visibility)
                || !read_value_property(world, L"CurrentLevelPendingInvisibility", pending_invisibility)
                || pending_visibility || pending_invisibility)
            {
                return false;
            }

            if (!read_value_property(context.player_state, L"PlayerId", context.player_id)
                || context.player_id <= 0 || context.player_id > 1'000'000
                || !read_value_property(root, L"RelativeLocation", context.current.location)
                || !read_value_property(root, L"RelativeRotation", context.current.rotation)
                || !finite_vector(context.current.location)
                || !finite_rotation(context.current.rotation))
            {
                return false;
            }

            std::wstring world_name;
            try { world_name = world->GetFullName(); }
            catch (...) { return false; }
            if (world_name.rfind(L"World /Game/", 0) != 0) return false;
            context.world = world;
            context.current.valid = true;
            context.current.world_hash = hash_world_name(world_name);
            context.current.checksum = point_checksum(context.current);
            if (!valid_point(context.current)) return false;
            g_current_world_hash.store(context.current.world_hash, std::memory_order_release);
            g_current_controller.store(reinterpret_cast<std::uint64_t>(context.controller), std::memory_order_release);
            g_current_pawn.store(reinterpret_cast<std::uint64_t>(context.pawn), std::memory_order_release);
            return true;
        }

        // v0.2.2 loaded-area check (GameThread, reads only): the World of the
        // one local SBNetworkPlayerController, found as resolve_live_context
        // finds it (controller -> Player -> ViewportClient -> World, the
        // LocalPlayer's back-reference must be that controller) and hashed
        // the same way. It does not need Eve's pawn or the camera, so it also
        // answers during a cutscene. False (nothing changes) when the chain
        // is not whole or not unique.
        bool resolve_loaded_world_hash(std::uint64_t& hash)
        {
            hash = 0;
            std::vector<RC::Unreal::UObject*> controllers;
            try { RC::Unreal::UObjectGlobals::FindAllOf(L"SBNetworkPlayerController", controllers); }
            catch (...) { return false; }

            std::uint32_t viable{};
            RC::Unreal::UObject* found{};
            RC::Unreal::UObject* found_viewport{};
            for (auto* controller : controllers)
            {
                if (!sbcore::memory::plausible_object(controller)) continue;
                std::wstring name;
                try { name = controller->GetFullName(); }
                catch (...) { continue; }
                if (name.rfind(L"SBNetworkPlayerController ", 0) != 0
                    || name.find(L"Default__") != std::wstring::npos)
                {
                    continue;
                }
                RC::Unreal::UObject* local_player{};
                RC::Unreal::UObject* controller_backref{};
                RC::Unreal::UObject* viewport{};
                RC::Unreal::UObject* world{};
                if (!read_object_property(controller, L"Player", local_player)
                    || !read_object_property(local_player, L"PlayerController", controller_backref)
                    || controller_backref != controller
                    || !read_object_property(local_player, L"ViewportClient", viewport)
                    || !read_object_property(viewport, L"World", world))
                {
                    continue;
                }
                ++viable;
                if (viable == 1)
                {
                    found = world;
                    found_viewport = viewport;
                }
            }
            if (viable != 1 || !found) return false;

            // v0.2.3: remember the viewport for the next checks.
            std::uint64_t first{};
            std::wstring viewport_name;
            try { viewport_name = found_viewport->GetFullName(); }
            catch (...) { viewport_name.clear(); }
            if (!viewport_name.empty() && sbcore::memory::read_exact(found_viewport, &first, sizeof(first)))
            {
                g_cached_viewport = found_viewport;
                g_cached_viewport_first = first;
                g_cached_viewport_name = std::move(viewport_name);
            }

            std::wstring world_name;
            try { world_name = found->GetFullName(); }
            catch (...) { return false; }
            if (world_name.rfind(L"World /Game/", 0) != 0) return false;
            hash = hash_world_name(world_name);
            return hash != 0;
        }

        enum class CachedWorld
        {
            Ok,
            NoWorld, // the viewport is still itself but shows no /Game/ World now (loading)
            Invalid, // the viewport no longer proves itself: dropped
        };

        // v0.2.3 (GameThread, reads only): the World the cached viewport shows.
        CachedWorld read_cached_viewport_world(std::uint64_t& hash)
        {
            hash = 0;
            RC::Unreal::UObject* viewport = g_cached_viewport;
            std::uint64_t first{};
            if (!sbcore::memory::plausible_object(viewport)
                || !sbcore::memory::read_exact(viewport, &first, sizeof(first))
                || first != g_cached_viewport_first)
            {
                return CachedWorld::Invalid;
            }
            std::wstring name;
            try { name = viewport->GetFullName(); }
            catch (...) { return CachedWorld::Invalid; }
            if (name != g_cached_viewport_name) return CachedWorld::Invalid;
            RC::Unreal::UObject* world{};
            if (!read_object_property(viewport, L"World", world)) return CachedWorld::NoWorld;
            std::wstring world_name;
            try { world_name = world->GetFullName(); }
            catch (...) { return CachedWorld::NoWorld; }
            if (world_name.rfind(L"World /Game/", 0) != 0) return CachedWorld::NoWorld;
            hash = hash_world_name(world_name);
            return hash != 0 ? CachedWorld::Ok : CachedWorld::NoWorld;
        }

        std::uint64_t unix_time_ms()
        {
            return sbcore::lease::unix_time_ms();
        }

        // Runs only inside sbcore's dispatcher callback (certified GameThread).
        // Never touches phase, result or the command sequences: those belong
        // to the panel's commands.
        void execute_world_check()
        {
            LARGE_INTEGER frequency{};
            LARGE_INTEGER begin{};
            QueryPerformanceFrequency(&frequency);
            QueryPerformanceCounter(&begin);
            std::uint64_t hash{};
            bool ok = false;
            bool cached = false;
            if (g_cached_viewport)
            {
                switch (read_cached_viewport_world(hash))
                {
                case CachedWorld::Ok:
                    ok = true;
                    cached = true;
                    break;
                case CachedWorld::NoWorld:
                    cached = true; // a loading screen: no walk, nothing changes
                    break;
                case CachedWorld::Invalid:
                    g_cached_viewport = nullptr;
                    g_cached_viewport_first = 0;
                    g_cached_viewport_name.clear();
                    break;
                }
            }
            if (!cached)
            {
                g_world_check_full_walks.fetch_add(1, std::memory_order_acq_rel);
                ok = resolve_loaded_world_hash(hash);
            }
            g_world_check_cached.store(cached, std::memory_order_release);
            LARGE_INTEGER end{};
            QueryPerformanceCounter(&end);
            const std::uint64_t elapsed_us = frequency.QuadPart > 0
                ? static_cast<std::uint64_t>((end.QuadPart - begin.QuadPart) * 1'000'000LL / frequency.QuadPart)
                : 0;
            g_world_check_last_us.store(elapsed_us, std::memory_order_release);
            if (elapsed_us > g_world_check_max_us.load(std::memory_order_acquire))
                g_world_check_max_us.store(elapsed_us, std::memory_order_release);
            if (ok)
            {
                g_current_world_hash.store(hash, std::memory_order_release);
                g_world_checked_unix_ms.store(unix_time_ms(), std::memory_order_release);
                g_world_checks.fetch_add(1, std::memory_order_acq_rel);
                g_world_check_result.store(WorldCheck::Ok, std::memory_order_release);
            }
            else
            {
                g_world_check_failures.fetch_add(1, std::memory_order_acq_rel);
                g_world_check_result.store(WorldCheck::ContextInvalid, std::memory_order_release);
            }
        }

        void complete_command(std::uint64_t sequence, Phase phase, Result result)
        {
            g_phase.store(phase, std::memory_order_release);
            g_result.store(result, std::memory_order_release);
            g_last_completed_command_sequence.store(sequence, std::memory_order_release);
        }

        // Runs only inside sbcore's dispatcher callback, i.e. on the certified
        // GameThread and only while sbcore::fault::writes_blocked() was false.
        void execute_game_thread_action(Action action, std::uint64_t sequence)
        {
            LiveContext context{};
            if (!resolve_live_context(context))
            {
                complete_command(sequence, Phase::Fault, Result::ContextInvalid);
                return;
            }

            if (action == Action::Save)
            {
                replace_point(context.current);
                g_point_file_dirty.store(true, std::memory_order_release);
                g_phase.store(Phase::SaveCaptured, std::memory_order_release);
                g_result.store(Result::None, std::memory_order_release);
                return;
            }

            const PointData target = point_copy();
            if (!valid_point(target))
            {
                complete_command(sequence, Phase::Fault, Result::PointInvalid);
                return;
            }
            if (context.current.world_hash != target.world_hash)
            {
                complete_command(sequence, Phase::Fault, Result::WorldMismatch);
                return;
            }
            const float distance = distance_between(context.current.location, target.location);

            if (action == Action::Verify)
            {
                complete_command(
                    sequence,
                    distance <= kVerifyDistance ? Phase::Returned : Phase::Fault,
                    distance <= kVerifyDistance ? Result::Returned : Result::VerificationFailed);
                return;
            }

            if (action != Action::Return)
            {
                complete_command(sequence, Phase::Fault, Result::CommandInvalid);
                return;
            }
            if (distance <= kAlreadyThereDistance)
            {
                complete_command(sequence, Phase::Returned, Result::AlreadyAtPoint);
                return;
            }
            if (!std::isfinite(distance) || distance > kMaxReturnDistance)
            {
                complete_command(sequence, Phase::Fault, Result::TargetTooFar);
                return;
            }

            RC::Unreal::UFunction* function{};
            try { function = context.controller->GetFunctionByNameInChain(kWarpFunctionName); }
            catch (...) { function = nullptr; }
            if (!sbcore::memory::plausible_object(function))
            {
                complete_command(sequence, Phase::Fault, Result::FunctionMissing);
                return;
            }
            std::wstring function_name;
            try { function_name = function->GetFullName(); }
            catch (...) { function_name.clear(); }
            if (function_name != kWarpFunctionFullName)
            {
                complete_command(sequence, Phase::Fault, Result::FunctionIdentityMismatch);
                return;
            }

            // A9: the one game write. Re-check the process-wide latch right
            // before it (another native may have faulted since the dispatch).
            if (sbcore::fault::writes_blocked())
            {
                complete_command(sequence, Phase::Fault, Result::WritesBlocked);
                return;
            }

            WarpPositionParams params{};
            params.player_id = context.player_id;
            params.location = target.location;
            params.rotation = target.rotation;
            context.controller->ProcessEvent(function, &params);
            g_game_owned_warp_calls.fetch_add(1, std::memory_order_relaxed);
            g_phase.store(Phase::VerifyPending, std::memory_order_release);
            g_result.store(Result::WarpRequested, std::memory_order_release);
            g_verify_due_tick.store(GetTickCount64() + kVerifyDelayMs, std::memory_order_release);
            g_verify_scheduled.store(true, std::memory_order_release);
        }

        // sbcore dispatcher callback (GameThread). A fault inside the action
        // (UE4SS, engine or game code) is handled here, as in v0.1.1, but now
        // through sbcore's filter: one persistent breadcrumb line and the
        // process-wide write latch (A9 stage 1: continue with the feature off).
        void game_thread_callback(std::uint64_t /*dispatch_sequence*/)
        {
            const Action action = g_pending_action.exchange(Action::None, std::memory_order_acq_rel);
            const auto command_sequence = g_active_command_sequence.load(std::memory_order_acquire);
            // v0.2.2: a user action queued behind a world check's task runs in
            // that task instead; from here on the task is the user's.
            if (action != Action::WorldCheck) g_task_is_world_check.store(false, std::memory_order_release);
            if (action == Action::None || g_shutting_down.load(std::memory_order_acquire)) return;
            __try
            {
                if (action == Action::WorldCheck) execute_world_check();
                else execute_game_thread_action(action, command_sequence);
            }
            __except (sbcore::fault::filter(GetExceptionInformation(), "retry_point_game_thread_action"))
            {
                sbcore::fault::after_handler();
                g_last_exception.store(GetExceptionCode(), std::memory_order_release);
                g_result.store(Result::DispatchException, std::memory_order_release);
                g_phase.store(Phase::Fault, std::memory_order_release);
                g_dispatch_poisoned.store(true, std::memory_order_release);
            }
        }

        // An accepted action that can no longer run because a fault latched
        // the write block: drop it and answer the command.
        void refuse_pending_writes_blocked()
        {
            const Action dropped = g_pending_action.exchange(Action::None, std::memory_order_acq_rel);
            // A dropped world check answers no command.
            if (dropped == Action::None || dropped == Action::WorldCheck) return;
            complete_command(
                g_active_command_sequence.load(std::memory_order_acquire), Phase::Fault, Result::WritesBlocked);
        }

        // Outcomes the dispatcher decided without running the callback.
        void reconcile_dispatch()
        {
            if (!sbcore::dispatch::bound()) return;
            const auto counters = sbcore::dispatch::counters();
            if (counters.wrong_thread != g_seen_wrong_thread)
            {
                // v0.1.1 on a wrong thread: the action was dropped, nothing
                // ran, the dispatcher is poisoned (sbcore poisoned it).
                g_seen_wrong_thread = counters.wrong_thread;
                g_pending_action.store(Action::None, std::memory_order_release);
                g_result.store(Result::WrongThread, std::memory_order_release);
                g_phase.store(Phase::Fault, std::memory_order_release);
            }
            if (counters.skipped_blocked != g_seen_skipped_blocked)
            {
                g_seen_skipped_blocked = counters.skipped_blocked;
                refuse_pending_writes_blocked();
            }
        }

        bool dispatch_action()
        {
            if (!g_ready.load(std::memory_order_acquire)
                || g_shutting_down.load(std::memory_order_acquire)
                || g_dispatch_poisoned.load(std::memory_order_acquire)
                || g_pending_action.load(std::memory_order_acquire) == Action::None)
            {
                return false;
            }
            // v0.1.1 returned here without touching the dispatcher while it was
            // poisoned or a task was in flight; keep that (no submit churn).
            const auto counters = sbcore::dispatch::counters();
            if (counters.poisoned || counters.pending) return false;
            const bool world_check = g_pending_action.load(std::memory_order_acquire) == Action::WorldCheck;
            using sbcore::dispatch::SubmitResult;
            switch (sbcore::dispatch::submit(&game_thread_callback))
            {
            case SubmitResult::Submitted:
                g_task_is_world_check.store(world_check, std::memory_order_release);
                return true;
            case SubmitResult::WritesBlocked:
                refuse_pending_writes_blocked();
                return false;
            case SubmitResult::CreateRejected:
            case SubmitResult::VtableMismatch:
            case SubmitResult::Exception:
                if (world_check)
                {
                    // v0.2.2: no command is answered and no further check is
                    // made in this game session; a user command reports the
                    // failure itself when it is sent.
                    Action expected = Action::WorldCheck;
                    g_pending_action.compare_exchange_strong(expected, Action::None, std::memory_order_acq_rel);
                    g_world_check_result.store(WorldCheck::DispatchFailed, std::memory_order_release);
                    return false;
                }
                // v0.1.1: a failed CreateTask/Setup drops the action and
                // reports it. (sbcore keeps the lease after an exception
                // inside CreateTask/Setup: the task may already be queued.)
                g_pending_action.store(Action::None, std::memory_order_release);
                g_result.store(Result::DispatchFailed, std::memory_order_release);
                g_phase.store(Phase::Fault, std::memory_order_release);
                return false;
            case SubmitResult::NotBound:
            case SubmitResult::ShuttingDown:
            case SubmitResult::Poisoned:
            case SubmitResult::Busy:
            case SubmitResult::NoCallback:
                // Refused before anything was created: the action stays
                // queued, as in v0.1.1.
                return false;
            }
            return false;
        }

        void clear_point(std::uint64_t sequence)
        {
            replace_point(PointData{});
            DeleteFileW(g_point_path.c_str());
            DeleteFileW(g_point_temp_path.c_str());
            g_verify_scheduled.store(false, std::memory_order_release);
            g_pending_action.store(Action::None, std::memory_order_release);
            complete_command(sequence, Phase::Cleared, Result::Cleared);
        }

        void poll_command()
        {
            std::string text;
            if (sbcore::status::read_small_file(g_command_path, text) != sbcore::status::ReadResult::Ok) return;
            std::uint64_t schema{}, sequence{}, issued_ms{}, panel_pid{};
            std::string command;
            std::string token;
            bool saw_schema{}, saw_sequence{}, saw_command{}, saw_issued{}, saw_pid{}, saw_token{};
            bool invalid_format{};
            std::size_t position{};
            while (position < text.size())
            {
                const auto end = text.find('\n', position);
                std::string line = text.substr(position, end == std::string::npos ? text.size() - position : end - position);
                position = end == std::string::npos ? text.size() : end + 1;
                if (!line.empty() && line.back() == '\r') line.pop_back();
                const auto equals = line.find('=');
                if (equals == std::string::npos)
                {
                    invalid_format = true;
                    continue;
                }
                const std::string key = line.substr(0, equals);
                const std::string value = line.substr(equals + 1);
                std::uint64_t parsed{};
                if (key == "schema" && !saw_schema && parse_unsigned(value, parsed)) { schema = parsed; saw_schema = true; }
                else if (key == "seq" && !saw_sequence && parse_unsigned(value, parsed)) { sequence = parsed; saw_sequence = true; }
                else if (key == "cmd" && !saw_command) { command = value; saw_command = true; }
                else if (key == "issued_ms" && !saw_issued && parse_unsigned(value, parsed)) { issued_ms = parsed; saw_issued = true; }
                else if (key == "panel_pid" && !saw_pid && parse_unsigned(value, parsed)) { panel_pid = parsed; saw_pid = true; }
                else if (key == "token" && !saw_token) { token = value; saw_token = true; }
                else invalid_format = true;
            }
            const auto previous = g_last_seen_command_sequence.load(std::memory_order_acquire);
            if (!saw_sequence || sequence == 0 || sequence <= previous) return;
            g_last_seen_command_sequence.store(sequence, std::memory_order_release);

            if (invalid_format || !saw_schema || schema != kCommandSchema || !saw_command || !saw_issued
                || !saw_pid || !saw_token || !valid_token(token)
                || panel_pid == 0 || panel_pid > std::numeric_limits<std::uint32_t>::max()
                || (command != "save" && command != "return" && command != "clear"))
            {
                complete_command(sequence, Phase::Fault, Result::CommandInvalid);
                return;
            }
            // Same rules as v0.1.1: more than 2 s in the future or older than
            // 5 s is stale (issued_ms=0 too), then the sender must be alive.
            const auto lease = sbcore::lease::evaluate(
                static_cast<std::uint32_t>(panel_pid), issued_ms, sbcore::lease::unix_time_ms(),
                kCommandLeaseMs, kFutureClockToleranceMs, true);
            if (lease.state == sbcore::lease::State::PanelGone)
            {
                complete_command(sequence, Phase::Fault, Result::PanelGone);
                return;
            }
            if (lease.state != sbcore::lease::State::Fresh)
            {
                complete_command(sequence, Phase::Fault, Result::CommandStale);
                return;
            }
            if (g_bound_panel_pid != 0 && !sbcore::lease::process_alive(g_bound_panel_pid))
            {
                g_bound_panel_pid = 0;
                g_bound_panel_token.clear();
            }
            if (g_bound_panel_pid == 0)
            {
                g_bound_panel_pid = static_cast<std::uint32_t>(panel_pid);
                g_bound_panel_token = token;
            }
            else if (g_bound_panel_pid != panel_pid || g_bound_panel_token != token)
            {
                complete_command(sequence, Phase::Fault, Result::PanelSessionMismatch);
                return;
            }
            // v0.2.2: a world check (queued, or the task in flight) never
            // makes a command "busy": the command's action replaces a queued
            // check, or waits for the check's task and runs right after it.
            const Action queued = g_pending_action.load(std::memory_order_acquire);
            const bool task_is_world_check = g_task_is_world_check.load(std::memory_order_acquire);
            if ((sbcore::dispatch::counters().pending && !task_is_world_check)
                || (queued != Action::None && queued != Action::WorldCheck)
                || g_verify_scheduled.load(std::memory_order_acquire))
            {
                complete_command(sequence, Phase::Fault, Result::Busy);
                return;
            }
            // A9: after any fault in this process no Save/Return is accepted.
            // Clear only removes this mod's own point file.
            if (command != "clear" && sbcore::fault::initialized() && sbcore::fault::writes_blocked())
            {
                complete_command(sequence, Phase::Fault, Result::WritesBlocked);
                return;
            }
            g_active_command_sequence.store(sequence, std::memory_order_release);
            if (command == "clear")
            {
                clear_point(sequence);
                return;
            }
            if (command == "return" && !load_point_file())
            {
                complete_command(
                    sequence, Phase::Fault,
                    GetFileAttributesW(g_point_path.c_str()) == INVALID_FILE_ATTRIBUTES
                        ? Result::PointMissing : Result::PointInvalid);
                return;
            }
            g_result.store(Result::None, std::memory_order_release);
            g_phase.store(command == "save" ? Phase::SavePending : Phase::ReturnPending,
                          std::memory_order_release);
            g_pending_action.store(command == "save" ? Action::Save : Action::Return,
                                   std::memory_order_release);
        }

        // v0.2.2: the panel's watch lease (Mods/SBCheatGUI/retry_point_watch.txt:
        // schema, panel_pid, token, issued_ms). It is fresh under the command
        // rules (not older than kWatchLeaseMs, not from the future, the panel
        // alive) and it binds the panel exactly as a first command would; a
        // watch from another live panel is ignored.
        void poll_watch()
        {
            std::string text;
            const auto read = sbcore::status::read_small_file(g_watch_path, text);
            if (read == sbcore::status::ReadResult::Ok)
            {
                std::uint64_t schema{}, issued_ms{}, panel_pid{};
                std::string token;
                bool saw_schema{}, saw_issued{}, saw_pid{}, saw_token{};
                bool invalid_format{};
                std::size_t position{};
                while (position < text.size())
                {
                    const auto end = text.find('\n', position);
                    std::string line = text.substr(position, end == std::string::npos ? text.size() - position : end - position);
                    position = end == std::string::npos ? text.size() : end + 1;
                    if (!line.empty() && line.back() == '\r') line.pop_back();
                    const auto equals = line.find('=');
                    if (equals == std::string::npos)
                    {
                        invalid_format = true;
                        continue;
                    }
                    const std::string key = line.substr(0, equals);
                    const std::string value = line.substr(equals + 1);
                    std::uint64_t parsed{};
                    if (key == "schema" && !saw_schema && parse_unsigned(value, parsed)) { schema = parsed; saw_schema = true; }
                    else if (key == "issued_ms" && !saw_issued && parse_unsigned(value, parsed)) { issued_ms = parsed; saw_issued = true; }
                    else if (key == "panel_pid" && !saw_pid && parse_unsigned(value, parsed)) { panel_pid = parsed; saw_pid = true; }
                    else if (key == "token" && !saw_token) { token = value; saw_token = true; }
                    else invalid_format = true;
                }
                if (invalid_format || !saw_schema || schema != kWatchSchema || !saw_issued || !saw_pid || !saw_token
                    || !valid_token(token) || panel_pid == 0 || panel_pid > std::numeric_limits<std::uint32_t>::max())
                {
                    g_watch_lease = {};
                    g_watch.store(Watch::Invalid, std::memory_order_release);
                    return;
                }
                g_watch_lease.valid = true;
                g_watch_lease.panel_pid = static_cast<std::uint32_t>(panel_pid);
                g_watch_lease.issued_ms = issued_ms;
                g_watch_lease.token = token;
            }
            else if (!g_watch_lease.valid)
            {
                g_watch.store(read == sbcore::status::ReadResult::Missing ? Watch::None : Watch::Invalid,
                              std::memory_order_release);
                return;
            }

            const auto lease = sbcore::lease::evaluate(
                g_watch_lease.panel_pid, g_watch_lease.issued_ms, sbcore::lease::unix_time_ms(),
                kWatchLeaseMs, kFutureClockToleranceMs, true);
            if (lease.state == sbcore::lease::State::PanelGone)
            {
                g_watch.store(Watch::PanelGone, std::memory_order_release);
                return;
            }
            if (lease.state != sbcore::lease::State::Fresh)
            {
                g_watch.store(Watch::Stale, std::memory_order_release);
                return;
            }
            if (g_bound_panel_pid != 0 && !sbcore::lease::process_alive(g_bound_panel_pid))
            {
                g_bound_panel_pid = 0;
                g_bound_panel_token.clear();
            }
            if (g_bound_panel_pid == 0)
            {
                g_bound_panel_pid = g_watch_lease.panel_pid;
                g_bound_panel_token = g_watch_lease.token;
            }
            else if (g_bound_panel_pid != g_watch_lease.panel_pid || g_bound_panel_token != g_watch_lease.token)
            {
                g_watch.store(Watch::SessionMismatch, std::memory_order_release);
                return;
            }
            g_watch.store(Watch::Active, std::memory_order_release);
        }

        // v0.2.2: queue one read-only world check when the watch is active, a
        // point is saved, nothing else is queued, running or awaiting its
        // verification, and no fault has latched: right away when the watch
        // starts, then every kWorldCheckIntervalMs.
        void schedule_world_check(std::uint64_t now)
        {
            const bool active = g_watch.load(std::memory_order_acquire) == Watch::Active;
            const bool started = active && !g_watch_was_active;
            g_watch_was_active = active;
            if (!active
                || !g_ready.load(std::memory_order_acquire)
                || g_shutting_down.load(std::memory_order_acquire)
                || g_dispatch_poisoned.load(std::memory_order_acquire)
                || g_world_check_result.load(std::memory_order_acquire) == WorldCheck::DispatchFailed
                || (sbcore::fault::initialized() && sbcore::fault::writes_blocked())
                || g_verify_scheduled.load(std::memory_order_acquire)
                || g_pending_action.load(std::memory_order_acquire) != Action::None
                || sbcore::dispatch::counters().pending
                || !valid_point(point_copy()))
            {
                // A check that could not start now runs as soon as it can.
                if (started) g_watch_was_active = false;
                return;
            }
            if (!started && now - g_last_world_check_tick < kWorldCheckIntervalMs) return;
            Action expected = Action::None;
            if (g_pending_action.compare_exchange_strong(expected, Action::WorldCheck, std::memory_order_acq_rel))
                g_last_world_check_tick = now;
        }

        void add_hex16_plain(sbcore::status::Builder& body, const char* key, std::uint64_t value)
        {
            char text[24];
            const int length = std::snprintf(text, sizeof(text), "%016llX", static_cast<unsigned long long>(value));
            body.add_str(key, std::string_view(text, length > 0 ? static_cast<std::size_t>(length) : 0));
        }

        // v0.1.1's fprintf("%.3f") in the "C" locale. sbcore's Builder::add_float
        // formats in the process-global locale (1000,500 under a comma locale).
        void add_fixed3(sbcore::status::Builder& body, const char* key, float value)
        {
            char text[64];
            const _locale_t locale = c_locale();
            const int length = locale
                ? _snprintf_s_l(text, sizeof(text), _TRUNCATE, "%.3f", locale, static_cast<double>(value))
                : -1;
            if (length > 0) body.add_str(key, std::string_view(text, static_cast<std::size_t>(length)));
            else body.add_float(key, value, 3);
        }

        const char* or_none(const char* text)
        {
            return text && text[0] ? text : "none";
        }

        // Caller holds g_status_lock.
        void build_status_body(sbcore::status::Builder& body)
        {
            const PointData point = point_copy();
            const auto dispatch = sbcore::dispatch::counters();
            const auto fault = sbcore::fault::snapshot();
            const bool fault_initialized = sbcore::fault::initialized();
            const bool writes_blocked = sbcore::fault::writes_blocked();
            const bool local_poisoned = g_dispatch_poisoned.load(std::memory_order_acquire);
            // v0.1.1 meaning: the dispatcher can no longer be used. A write
            // block after any fault in the process means exactly that.
            const bool poisoned = local_poisoned || dispatch.poisoned || (fault_initialized && writes_blocked);
            const auto worker = g_worker_thread_id.load(std::memory_order_acquire);
            const auto callback = dispatch.callback_thread;
            const auto certified = dispatch.certified_game_thread;
            const auto local_exception = g_last_exception.load(std::memory_order_acquire);
            const auto last_exception = local_exception != 0 ? local_exception : dispatch.last_exception;

            // ---- v0.1.1 fields: same keys, order and formats ----
            body.add_str("version", kVersion);
            body.add_str("architecture", kArchitecture);
            body.add_bool("ready", g_ready.load());
            body.add_bool("module_pinned", sbcore::module::pinned());
            body.add_bool("dispatch_poisoned", poisoned);
            body.add_u64("hooks", 0);
            body.add_u64("background_uobject_reads", 0);
            body.add_u64("direct_location_writes", 0);
            body.add_u64("save_game_writes", 0);
            body.add_u64("worker_thread", worker);
            body.add_u64("callback_thread", callback);
            body.add_u64("certified_game_thread", certified);
            body.add_bool("callback_on_game_thread", callback != 0 && callback == certified);
            body.add_u64("submit_count", dispatch.submit_count);
            body.add_u64("callback_count", dispatch.callback_count);
            body.add_u64("destroy_count", dispatch.destroy_count);
            body.add_u64("last_seen_command_sequence", g_last_seen_command_sequence.load());
            body.add_u64("last_completed_command_sequence", g_last_completed_command_sequence.load());
            body.add_u64("bound_panel_pid", g_bound_panel_pid);
            body.add_str("phase", phase_name(g_phase.load(std::memory_order_acquire)));
            body.add_str("result", result_name(g_result.load(std::memory_order_acquire)));
            body.add_bool("point_valid", valid_point(point));
            add_hex16_plain(body, "point_world_hash", point.world_hash);
            add_fixed3(body, "point_x", point.location.x);
            add_fixed3(body, "point_y", point.location.y);
            add_fixed3(body, "point_z", point.location.z);
            add_hex16_plain(body, "current_world_hash", g_current_world_hash.load());
            body.add_u64("current_controller", g_current_controller.load());
            body.add_u64("current_pawn", g_current_pawn.load());
            body.add_u64("game_owned_warp_calls", g_game_owned_warp_calls.load());
            body.add_hex32("last_exception", last_exception);

            // ---- 0.2.0 fields (appended; none is read by panel 2.5.499) ----
            body.add_str("install_failed_step", install_step_name(g_install_failed_step.load()));
            body.add_bool("gate_passed", g_gate.passed);
            body.add_str("gate_failed_check", or_none(g_gate.failed_check));
            body.add_str("gate_failed_manifest", or_none(g_gate.failed_manifest));
            body.add_str("gate_reason", sbcore::gate::reason_name(g_gate.reason));
            body.add_hex32("gate_timestamp", g_gate.timestamp);
            body.add_hex32("gate_image_size", g_gate.image_size);
            body.add_u64("gate_exe_file_size", g_gate.exe_file_size);
            body.add_u64("gate_code_checks", g_gate.code_checks_passed);
            body.add_u64("gate_slot_checks", g_gate.slot_checks_passed);
            body.add_u64("gate_global_checks", g_gate.global_checks_passed);
            body.add_u64("gate_manifests", g_gate.manifests_passed);
            body.add_bool("writes_blocked", writes_blocked);
            body.add_bool("fault_initialized", fault_initialized);
            body.add_bool("fault_latch_available", fault.latch_available);
            body.add_bool("fault_local", fault.local_faulted);
            body.add_bool("fault_process_tainted", fault.process_tainted);
            body.add_str("fault_policy", sbcore::fault::policy_name(fault.policy));
            body.add_u64("fault_count", fault.fault_count);
            body.add_hex32("fault_last_code", fault.last_code);
            body.add_str("fault_last_action", or_none(fault.last_action));
            body.add_str("fault_last_module", or_none(fault.last_module_kind));
            body.add_u64("fault_log_lines", fault.log_lines);
            body.add_u64("fault_log_failures", fault.log_failures);
            body.add_u64("fault_log_dropped", fault.log_dropped);
            body.add_bool("dispatch_bound", dispatch.bound);
            body.add_bool("dispatch_pending", dispatch.pending);
            body.add_bool("dispatch_local_poisoned", local_poisoned);
            body.add_bool("dispatch_sbcore_poisoned", dispatch.poisoned);
            body.add_str("dispatch_last_result", sbcore::dispatch::submit_result_name(dispatch.last_result));
            body.add_u64("dispatch_submit_attempts", dispatch.submit_attempts);
            body.add_u64("dispatch_callbacks_run", dispatch.callbacks_run);
            body.add_u64("dispatch_skipped_blocked", dispatch.skipped_blocked);
            body.add_u64("dispatch_skipped_shutdown", dispatch.skipped_shutdown);
            body.add_u64("dispatch_wrong_thread", dispatch.wrong_thread);
            body.add_u64("dispatch_released_pre_setup", dispatch.released_pre_setup);
            body.add_u64("dispatch_last_submitted_sequence", dispatch.last_submitted_sequence);
            body.add_u64("dispatch_last_completed_sequence", dispatch.last_completed_sequence);
            body.add_hex32("dispatch_last_exception", dispatch.last_exception);
            const auto& point_writer = g_point_writer.counters();
            body.add_u64("point_writes", point_writer.publishes);
            body.add_u64("point_write_failures", point_writer.write_failures);
            body.add_u64("point_rename_failures", point_writer.rename_failures);
            body.add_u64("status_beat_ms", kStatusBeatMs);
            body.add_u64("status_body_errors", g_status_body_errors);

            // ---- 0.2.2 fields (appended): the loaded-area check ----
            body.add_bool("world_check_supported", true);
            body.add_str("world_watch", watch_name(g_watch.load(std::memory_order_acquire)));
            body.add_str("world_check_result", world_check_name(g_world_check_result.load(std::memory_order_acquire)));
            body.add_u64("world_checks", g_world_checks.load(std::memory_order_acquire));
            body.add_u64("world_check_failures", g_world_check_failures.load(std::memory_order_acquire));
            body.add_u64("world_checked_ms", g_world_checked_unix_ms.load(std::memory_order_acquire));
            body.add_u64("world_check_last_us", g_world_check_last_us.load(std::memory_order_acquire));
            body.add_u64("world_check_max_us", g_world_check_max_us.load(std::memory_order_acquire));
            body.add_u64("world_check_interval_ms", kWorldCheckIntervalMs);
            // ---- 0.2.3 fields (appended) ----
            body.add_u64("world_check_full_walks", g_world_check_full_walks.load(std::memory_order_acquire));
            body.add_bool("world_check_cached", g_world_check_cached.load(std::memory_order_acquire));
        }

        void publish_status(std::uint64_t now, bool force)
        {
            AcquireSRWLockExclusive(&g_status_lock);
            if (g_status_configured)
            {
                sbcore::status::Builder body(g_status_buffer, sizeof(g_status_buffer));
                build_status_body(body);
                // A refused body is never published: the last good file stays.
                if (!body.ok()) ++g_status_body_errors;
                else g_status_publisher.maybe_publish(body, now, force);
            }
            ReleaseSRWLockExclusive(&g_status_lock);
        }

        bool configure_paths(const sbcore::paths::ModulePaths& paths)
        {
            // P1: every path from this DLL's own location
            // (<Mods>\SBRetryPointNative\dlls\main.dll), never a fixed install path.
            g_command_path = paths.in_panel(L"retry_point_command.txt");
            g_watch_path = paths.in_panel(L"retry_point_watch.txt");
            g_point_path = paths.in_panel(L"retry_point.txt");
            g_point_temp_path = paths.in_panel(L"retry_point.tmp");
            const bool point_ok = g_point_writer.configure(g_point_path, g_point_temp_path);
            sbcore::status::Publisher::Options options;
            options.module = kNativeName;
            options.module_version = kVersion;
            options.beat_ms = kStatusBeatMs;
            options.min_interval_ms = kStatusTickMs;
            AcquireSRWLockExclusive(&g_status_lock);
            g_status_configured = g_status_publisher.configure(
                options, paths.in_mod(L"retry_point_status.txt"), paths.in_mod(L"retry_point_status.tmp"));
            const bool status_ok = g_status_configured;
            ReleaseSRWLockExclusive(&g_status_lock);
            return point_ok && status_ok;
        }

        bool finish_install(InstallStep failed)
        {
            const bool ready = failed == InstallStep::None;
            g_install_failed_step.store(failed, std::memory_order_release);
            g_ready.store(ready, std::memory_order_release);
            if (!ready)
            {
                g_phase.store(Phase::Fault, std::memory_order_release);
                g_result.store(
                    failed == InstallStep::FaultInit ? Result::FaultLatchUnavailable : Result::BuildMismatch,
                    std::memory_order_release);
            }
            if (!g_point_path.empty()) load_point_file();
            publish_status(GetTickCount64(), true);
            return ready;
        }

        // install() order (sbcore README): paths, fault latch, pin, gate, bind.
        // test_gate replaces the running process's gate (offline harness only).
        bool install_steps(const sbcore::paths::ModulePaths& paths, sbcore::paths::Error path_error,
                           const sbcore::gate::Result* test_gate)
        {
            if (path_error != sbcore::paths::Error::None || !configure_paths(paths))
            {
                return finish_install(InstallStep::Paths);
            }
            sbcore::fault::Config fault;
            fault.native_name = kNativeName;
            fault.native_version = kVersion;
            fault.log_path = paths.in_mod(L"sbcore_faults.log");
            if (!sbcore::fault::init(fault)) return finish_install(InstallStep::FaultInit);
            if (!sbcore::module::pin_this_module()) return finish_install(InstallStep::Pin);
            const sbcore::gate::Result gate = test_gate ? *test_gate : sbcore::gate::validate_running_process(nullptr, 0);
            AcquireSRWLockExclusive(&g_status_lock);
            g_gate = gate;
            ReleaseSRWLockExclusive(&g_status_lock);
            if (!gate.passed) return finish_install(InstallStep::Gate);
            if (!sbcore::dispatch::bind(gate)) return finish_install(InstallStep::Bind);
            return finish_install(InstallStep::None);
        }
    }

    bool install()
    {
        if (g_running.exchange(true, std::memory_order_acq_rel)) return g_ready.load();
        g_shutting_down.store(false, std::memory_order_release);
        sbcore::paths::ModulePaths paths;
        const auto path_error = sbcore::paths::resolve_this_module(paths);
        return install_steps(paths, path_error, nullptr);
    }

    void on_update()
    {
        if (!g_running.load(std::memory_order_acquire)) return;
        if (g_worker_thread_id.load(std::memory_order_relaxed) == 0)
            g_worker_thread_id.store(GetCurrentThreadId(), std::memory_order_release);
        sbcore::fault::refresh_process_latch();
        reconcile_dispatch();
        const auto now = GetTickCount64();
        if (now - g_last_command_poll_tick >= kCommandPollMs)
        {
            g_last_command_poll_tick = now;
            poll_command();
        }
        // v0.2.2: after the command poll, so a command read in the same pass
        // goes first.
        if (now - g_last_watch_poll_tick >= kWatchPollMs)
        {
            g_last_watch_poll_tick = now;
            poll_watch();
        }
        if (g_point_file_dirty.exchange(false, std::memory_order_acq_rel))
        {
            const auto sequence = g_active_command_sequence.load(std::memory_order_acquire);
            const bool written = write_point_file();
            complete_command(
                sequence,
                written ? Phase::Saved : Phase::Fault,
                written ? Result::Saved : Result::PointWriteFailed);
        }
        if (g_verify_scheduled.load(std::memory_order_acquire)
            && now >= g_verify_due_tick.load(std::memory_order_acquire))
        {
            g_verify_scheduled.store(false, std::memory_order_release);
            g_pending_action.store(Action::Verify, std::memory_order_release);
        }
        schedule_world_check(now);
        if (g_pending_action.load(std::memory_order_acquire) != Action::None)
            dispatch_action();
        if (now - g_last_status_tick >= kStatusTickMs)
        {
            g_last_status_tick = now;
            publish_status(now, false);
        }
    }

    void shutdown()
    {
        g_shutting_down.store(true, std::memory_order_release);
        sbcore::dispatch::shutdown();
        g_running.store(false, std::memory_order_release);
        g_pending_action.store(Action::None, std::memory_order_release);
        g_verify_scheduled.store(false, std::memory_order_release);
        publish_status(GetTickCount64(), true);
    }

#if defined(SBRETRYPOINT_TESTING)
    namespace testing
    {
        bool install_with(const sbcore::paths::ModulePaths& paths, sbcore::paths::Error path_error,
                          const sbcore::gate::Result& gate)
        {
            if (g_running.exchange(true, std::memory_order_acq_rel)) return g_ready.load();
            g_shutting_down.store(false, std::memory_order_release);
            return install_steps(paths, path_error, &gate);
        }
    }
#endif
}
