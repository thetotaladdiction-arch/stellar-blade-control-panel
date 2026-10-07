// SBMovementNative - hook-free movement and camera controls for Stellar Blade.
//
// UE4SS calls CppUserModBase::on_update() on its event-loop worker, not the
// shipping GameThread. The worker therefore does file I/O and TaskGraph
// submission only. Every UObject lookup, reflected property read, and property
// write below runs inside the exact-build GameThread callback certified by the
// boss-retry project. No UFunction hook, ProcessEvent hook, UObject worker read,
// engine timing write, VSync write, or frame-rate cap is used.
//
// 1.4.0 (sbcore): the private gate, TaskGraph dispatch, SEH handling, status
// writer, state reader, memory probes and UE4SS shim of 1.3.6 are replaced by
// the shared sbcore library (natives/sbcore, pinned in SBCORE_PIN.txt):
                                                                           
                                                                            
//          TaskGraph core manifest with the GGameThreadId initializer proof,
//          and 1.3.6's own exact byte images (never weaker than before);
//   * A8   sbcore dispatch writes the byte-identical task; an exception inside
//          CreateTask/Setup keeps the lease (BossRetry rule);
//   * A9   stage 1: a fault is logged to Mods\SBMovementNative\sbcore_faults.log
//          and latches Local\SBCore.Tainted.<pid>; from then on no game write
//          of any kind (restores included) and no GameThread work. The game
//          keeps running with the feature off (no crash-on-fault);
//   * A12  the heartbeat is replaced atomically (CREATE_NEW temp + POSIX
//          rename, no fsync) and the panel's state file is read with
//          FILE_SHARE_DELETE through a 500 ms grace reader.
// Everything else - the parser, lease, one-shot scheduling, capture/restore
// rules and every 1.3.6 heartbeat field - is unchanged. New heartbeat keys
// are only added (sbcore_* header and fields after `error`).
//
// 1.4.1: a UE4SS hot reload (Ctrl+R; EnableHotReloadSystem = 1 in the live
// UE4SS-settings.ini) calls uninstall_mod and then start_mod/on_unreal_init on
// the same pinned module. 1.3.6 re-armed there; 1.4.0 returned early from the
// second install() and had made sbcore dispatch shut down for good, so the
// worker stopped, the heartbeat went stale and whatever was applied stayed
// applied with no restore for the rest of the session. install() re-arms
// again (every arming step re-runs), and a task that was queued across the
// unload is re-requested once after the reload.

#include "movement.hpp"
#include "ue4ss_minimal.hpp"

#include <array>
#include <atomic>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <new>
#include <string>
#include <string_view>
#include <vector>

#include <windows.h>

#include "sbcore/sbcore.hpp"

namespace sbmove
{
    namespace
    {
        // P1: leaves only. Folders come from sbcore::paths (this DLL's location):
        //   state      <Mods>\SBCheatGUI\native_movement_state.txt   (panel-written)
        //   heartbeat  <Mods>\SBMovementNative\heartbeat.txt (+ heartbeat.tmp)
        //   fault log  <Mods>\SBMovementNative\sbcore_faults.log
        constexpr wchar_t kStateLeaf[] = L"native_movement_state.txt";
        constexpr wchar_t kHeartbeatLeaf[] = L"heartbeat.txt";
        constexpr wchar_t kHeartbeatTempLeaf[] = L"heartbeat.tmp";
        constexpr wchar_t kFaultLogLeaf[] = L"sbcore_faults.log";
        constexpr char kArchitecture[] = "fully_event_driven_taskgraph_game_thread_one_shot";

        constexpr float kMinMultiplier = 0.5f;
        constexpr float kMaxMultiplier = 3.0f;
        constexpr float kMinRequestedFov = 50.0f;
        // Keep the user's full usable requested range available. Some shipped
        // areas reveal missing scenery above 100, but that is a documented
        // visual limitation rather than an unsafe native state. Stay below
        // the 180-degree perspective singularity.
        constexpr float kMaxRequestedFov = 170.0f;
        constexpr std::uint64_t kStateLeaseMs = 10'000;
        constexpr std::uint64_t kFutureClockToleranceMs = 5'000;

        constexpr std::uint64_t kStatePollMs = 200;
        constexpr std::uint64_t kAcquireRetryMs = 250;
        // The panel treats the heartbeat as stale after 2.0 s
        // (MOVEMENT_HEARTBEAT_FRESH_SEC); beat <= max_age / 3.
        constexpr std::uint64_t kHeartbeatMs = 500;
        // A panel replace can leave the state name absent for a few ms; bridge
        // it so Movement does not switch off and back on (two extra tasks).
        constexpr std::uint64_t kStateGraceMs = 500;
        constexpr std::size_t kStateMaxBytes = 4096;
        constexpr std::size_t kHeartbeatCapacity = 8192;

        enum class ErrorCode : std::uint32_t
        {
            None,
            BuildMismatch,
            StateMissing,
            StateInvalid,
            StateStale,
            PanelGone,
            DispatchFailed,
            DispatchException,
            WrongThread,
            NoPawn,
            NoCamera,
            NoManualFov,
            NoMovement,
            NoJump,
            // New in 1.4.0.
            InstallFailed, // an install step other than the build gate failed
            WritesBlocked, // the sbcore fault latch is set (A9): feature off
        };

        // The first install step that failed. Done = armed.
        enum class InstallStep : std::uint8_t
        {
            NotRun,
            Allocation,
            Paths,
            FaultInit,
            Pin,
            Gate,
            Bind,
            Done,
        };

        constexpr std::size_t kSpeedFieldCount = 7;
        constexpr const wchar_t* kSpeedNames[kSpeedFieldCount]{
            L"MaxWalkSpeed",
            L"MaxGuardRunSpeed",
            L"MaxLockOnRunSpeed",
            L"MaxLockOnWalkSpeed",
            L"MaxJoggingRunSpeed",
            L"MaxRunSpeedOverride",
            L"MaxWalkSpeedOverride",
        };
        constexpr std::size_t kFirstOverrideField = 5;
        constexpr const wchar_t* kCameraNames[]{L"FollowCamera", L"CameraComponent", L"Camera"};

        std::atomic<bool> g_running{false};
        // Set by uninstall(), cleared by the next install() (UE4SS hot reload,
        // as 1.3.6). While set, a GameThread task that was already queued runs
        // no Movement code (execute_game_thread_update returns at once).
        std::atomic<bool> g_shutting_down{false};
        std::atomic<bool> g_ready{false};
        std::atomic<InstallStep> g_install_step{InstallStep::NotRun};
        std::atomic<std::uint32_t> g_worker_thread_id{0};
        std::atomic<std::uint64_t> g_install_count{0};
        // GameThread tasks that ran while unloaded and therefore applied nothing.
        std::atomic<std::uint64_t> g_unload_skipped_callbacks{0};

        std::atomic<bool> g_request_fresh{false};
        std::atomic<bool> g_enabled{false};
        std::atomic<float> g_speed_mult{1.0f};
        std::atomic<float> g_jump_mult{1.0f};
        std::atomic<float> g_fov_deg{0.0f};
        std::atomic<std::uint64_t> g_panel_sequence{0};
        std::atomic<std::uint32_t> g_panel_pid{0};
        std::atomic<std::uint64_t> g_state_age_ms{UINT64_MAX};
        // Only semantic state changes require a GameThread task while movement
        // is disabled. Panel lease renewals update panel_sequence/issued_ms but
        // deliberately do not increment this revision.
        std::atomic<std::uint64_t> g_desired_revision{0};
        std::atomic<std::uint64_t> g_last_dispatched_revision{0};
        std::atomic<std::uint64_t> g_steady_dispatch_skips{0};

        std::atomic<std::uint64_t> g_pawn_telemetry{0};
        std::atomic<std::uint64_t> g_camera_telemetry{0};
        std::atomic<bool> g_movement_applied_telemetry{false};
        std::atomic<bool> g_fov_applied_telemetry{false};
        std::atomic<float> g_base_jump_telemetry{0.0f};
        std::atomic<float> g_live_jump_telemetry{0.0f};
        std::atomic<float> g_base_manual_fov_telemetry{0.0f};
        std::atomic<bool> g_base_manual_mode_telemetry{false};
        std::atomic<bool> g_live_manual_mode_telemetry{false};
        std::atomic<float> g_live_camera_fov_telemetry{0.0f};
        std::atomic<float> g_live_manual_fov_telemetry{0.0f};
        std::atomic<float> g_live_override_fov_telemetry{0.0f};
        std::atomic<float> g_live_current_fov_telemetry{0.0f};
        std::atomic<float> g_live_engine_fov_telemetry{0.0f};
        std::array<std::atomic<float>, kSpeedFieldCount> g_base_speed_telemetry{};
        std::array<std::atomic<float>, kSpeedFieldCount> g_live_speed_telemetry{};
        std::atomic<std::uint64_t> g_writes{0};
        std::atomic<ErrorCode> g_error{ErrorCode::None};

        // GameThread-owned state. Never read by the UE4SS worker.
        std::uint64_t gt_pawn{};
        std::uint64_t gt_camera{};
        bool gt_movement_base_captured{};
        bool gt_movement_applied{};
        float gt_base_jump{};
        std::array<float, kSpeedFieldCount> gt_base_speeds{};
        std::array<bool, kSpeedFieldCount> gt_speed_valid{};
        bool gt_fov_base_captured{};
        bool gt_fov_applied{};
        bool gt_base_manual_mode{};
        float gt_base_manual_fov{};
        float gt_last_fov_target{};

        // Worker-owned state, guarded by g_worker_lock (install, on_update and
        // uninstall may run on different UE4SS threads). Allocated by install()
        // and deliberately never freed: the module is pinned, and UE4SS may call
        // uninstall_mod() after this DLL's static destructors ran at process
        // exit, so nothing the unload path touches may have a destructor.
        struct WorkerState
        {
            sbcore::paths::ModulePaths paths;
            bool paths_ok = false;
            sbcore::gate::Result gate;
            bool gate_ran = false;
            sbcore::status::StableReader state_reader;
            bool reader_ok = false;
            sbcore::status::Publisher publisher;
            bool publisher_ok = false;
            sbcore::status::ReadResult state_read_raw = sbcore::status::ReadResult::Missing;
            sbcore::status::ReadResult state_read_effective = sbcore::status::ReadResult::Missing;
            std::uint64_t seen_wrong_thread = 0;
            std::uint64_t seen_unload_skips = 0;
            std::uint64_t heartbeat_build_failures = 0;
            std::uint64_t last_state_poll_tick = 0;
            std::uint64_t last_dispatch_tick = 0;
            std::uint64_t last_heartbeat_tick = 0;
            char heartbeat_buffer[kHeartbeatCapacity];
        };
        SRWLOCK g_worker_lock = SRWLOCK_INIT;
        WorkerState* g_worker = nullptr;

#if defined(SBMOVE_TESTING)
        // Offline harness only (never in the staged DLL): a fake TaskGraph image
        // in place of the exact-build gate, and a controllable tick clock.
        std::atomic<const void*> g_test_fake_image{nullptr};
        std::atomic<std::uint64_t> g_test_clock{0};
#endif

        std::uint64_t tick_now()
        {
#if defined(SBMOVE_TESTING)
            if (const auto now = g_test_clock.load(std::memory_order_acquire)) return now;
#endif
            return GetTickCount64();
        }

        const char* error_name(ErrorCode code)
        {
            switch (code)
            {
            case ErrorCode::None: return "none";
            case ErrorCode::BuildMismatch: return "build-mismatch";
            case ErrorCode::StateMissing: return "state-missing";
            case ErrorCode::StateInvalid: return "state-invalid";
            case ErrorCode::StateStale: return "state-stale";
            case ErrorCode::PanelGone: return "panel-gone";
            case ErrorCode::DispatchFailed: return "dispatch-failed";
            case ErrorCode::DispatchException: return "dispatch-exception";
            case ErrorCode::WrongThread: return "wrong-thread";
            case ErrorCode::NoPawn: return "no-pawn";
            case ErrorCode::NoCamera: return "no-camera";
            case ErrorCode::NoManualFov: return "no-ManualCameraFov";
            case ErrorCode::NoMovement: return "no-CharacterMovement";
            case ErrorCode::NoJump: return "no-JumpZVelocity";
            case ErrorCode::InstallFailed: return "install-failed";
            case ErrorCode::WritesBlocked: return "writes-blocked";
            }
            return "unknown";
        }

        const char* install_step_name(InstallStep step)
        {
            switch (step)
            {
            case InstallStep::NotRun: return "not_run";
            case InstallStep::Allocation: return "allocation";
            case InstallStep::Paths: return "paths";
            case InstallStep::FaultInit: return "fault_init";
            case InstallStep::Pin: return "pin";
            case InstallStep::Gate: return "gate";
            case InstallStep::Bind: return "bind";
            case InstallStep::Done: return "none";
            }
            return "unknown";
        }

        // A9 stage 1: after any fault (this native or any other sbcore native
        // in the process) no game write of any kind, restores included.
        bool game_writes_allowed()
        {
            return !sbcore::fault::writes_blocked();
        }

        sbcore::gate::Result run_gate()
        {
#if defined(SBMOVE_TESTING)
            if (const void* image = g_test_fake_image.load(std::memory_order_acquire))
            {
                sbcore::gate::Result fake;
                fake.passed = true;
                fake.image = static_cast<std::byte*>(const_cast<void*>(image));
                fake.timestamp = sbcore::target::kTimestamp;
                fake.image_size = sbcore::target::kImageSize;
                fake.exe_file_size = sbcore::target::kFileSize;
                return fake;
            }
#endif
            // Movement calls no engine code beyond the TaskGraph (properties
            // are resolved by reflected name through UE4SS), so sbcore's core
            // manifest plus its legacy exact images - which include every byte
            // image 1.3.6 pinned - is the complete gate. No extra manifest.
            return sbcore::gate::validate_running_process(nullptr, 0);
        }

        void publish_inactive_request(ErrorCode error)
        {
            bool changed = g_request_fresh.exchange(false, std::memory_order_acq_rel);
            changed = g_enabled.exchange(false, std::memory_order_acq_rel) || changed;
            const float previous_fov = g_fov_deg.exchange(0.0f, std::memory_order_acq_rel);
            changed = std::fabs(previous_fov) > 0.05f || changed;
            g_error.store(error, std::memory_order_release);
            if (changed) g_desired_revision.fetch_add(1, std::memory_order_acq_rel);
        }

        struct DesiredState
        {
            bool enabled{};
            float speed = 1.0f;
            float jump = 1.0f;
            float fov{};
            std::uint64_t sequence{};
            std::uint64_t issued_ms{};
            std::uint32_t panel_pid{};
        };

        // The 1.3.6 parser, unchanged: key=value lines, CRLF or LF, unknown keys
        // ignored, all seven keys required, ranges enforced. False = invalid.
        bool parse_desired_state(const std::string& text, DesiredState& out)
        {
            bool enabled{};
            float speed = 1.0f;
            float jump = 1.0f;
            float fov{};
            std::uint64_t sequence{};
            std::uint64_t issued_ms{};
            std::uint32_t panel_pid{};
            bool saw_enabled{}, saw_speed{}, saw_jump{}, saw_fov{}, saw_seq{}, saw_issued{}, saw_pid{};

            try
            {
                std::size_t pos{};
                while (pos < text.size())
                {
                    const auto end = text.find('\n', pos);
                    std::string line = text.substr(pos, end == std::string::npos ? text.size() - pos : end - pos);
                    pos = end == std::string::npos ? text.size() : end + 1;
                    if (!line.empty() && line.back() == '\r') line.pop_back();
                    const auto equals = line.find('=');
                    if (equals == std::string::npos) continue;
                    const auto key = line.substr(0, equals);
                    const auto value = line.substr(equals + 1);
                    if (key == "enabled") { enabled = value == "1"; saw_enabled = true; }
                    else if (key == "speed") { speed = std::stof(value); saw_speed = true; }
                    else if (key == "jump") { jump = std::stof(value); saw_jump = true; }
                    else if (key == "fov_deg") { fov = std::stof(value); saw_fov = true; }
                    else if (key == "seq") { sequence = std::stoull(value); saw_seq = true; }
                    else if (key == "issued_ms") { issued_ms = std::stoull(value); saw_issued = true; }
                    else if (key == "panel_pid") { panel_pid = static_cast<std::uint32_t>(std::stoul(value)); saw_pid = true; }
                }
            }
            catch (...)
            {
                return false;
            }

            const bool complete = saw_enabled && saw_speed && saw_jump && saw_fov
                && saw_seq && saw_issued && saw_pid;
            const bool values_valid = std::isfinite(speed) && std::isfinite(jump) && std::isfinite(fov)
                && speed >= kMinMultiplier && speed <= kMaxMultiplier
                && jump >= kMinMultiplier && jump <= kMaxMultiplier
                && fov >= kMinRequestedFov && fov <= kMaxRequestedFov
                && sequence != 0 && issued_ms != 0 && panel_pid != 0;
            if (!complete || !values_valid) return false;

            out.enabled = enabled;
            out.speed = speed;
            out.jump = jump;
            out.fov = fov;
            out.sequence = sequence;
            out.issued_ms = issued_ms;
            out.panel_pid = panel_pid;
            return true;
        }

        // Caller holds g_worker_lock.
        void refresh_desired_state(WorkerState& worker, std::uint64_t now_tick)
        {
            if (!worker.reader_ok)
            {
                publish_inactive_request(ErrorCode::StateMissing);
                return;
            }
            const auto read = worker.state_reader.read(now_tick);
            worker.state_read_raw = read.raw;
            worker.state_read_effective = read.effective;
            if (read.effective != sbcore::status::ReadResult::Ok)
            {
                // Missing/Busy beyond the grace window, or a hard read failure
                // (reparse point, hard link, empty, oversized, NUL): 1.3.6
                // reported every unreadable state file as state-missing.
                publish_inactive_request(ErrorCode::StateMissing);
                return;
            }

            DesiredState desired;
            if (!parse_desired_state(worker.state_reader.content(), desired))
            {
                publish_inactive_request(ErrorCode::StateInvalid);
                return;
            }

            const auto lease = sbcore::lease::evaluate(desired.panel_pid, desired.issued_ms, sbcore::lease::unix_time_ms(),
                                                       kStateLeaseMs, kFutureClockToleranceMs, true);
            g_state_age_ms.store(lease.age_ms, std::memory_order_release);
            g_panel_pid.store(desired.panel_pid, std::memory_order_release);
            g_panel_sequence.store(desired.sequence, std::memory_order_release);
            switch (lease.state)
            {
            case sbcore::lease::State::Fresh:
                break;
            case sbcore::lease::State::Future:
            case sbcore::lease::State::Stale:
                publish_inactive_request(ErrorCode::StateStale);
                return;
            case sbcore::lease::State::PanelGone:
                publish_inactive_request(ErrorCode::PanelGone);
                return;
            case sbcore::lease::State::Invalid:
            default:
                publish_inactive_request(ErrorCode::StateInvalid);
                return;
            }

            const bool semantic_change = !g_request_fresh.load(std::memory_order_acquire)
                || g_enabled.load(std::memory_order_acquire) != desired.enabled
                || std::fabs(g_speed_mult.load(std::memory_order_acquire) - desired.speed) > 0.0005f
                || std::fabs(g_jump_mult.load(std::memory_order_acquire) - desired.jump) > 0.0005f
                || std::fabs(g_fov_deg.load(std::memory_order_acquire) - desired.fov) > 0.05f;
            g_speed_mult.store(desired.speed, std::memory_order_release);
            g_jump_mult.store(desired.jump, std::memory_order_release);
            g_fov_deg.store(desired.fov, std::memory_order_release);
            g_enabled.store(desired.enabled, std::memory_order_release);
            g_request_fresh.store(true, std::memory_order_release);
            g_error.store(ErrorCode::None, std::memory_order_release);
            if (semantic_change) g_desired_revision.fetch_add(1, std::memory_order_acq_rel);
        }

        float* float_property(RC::Unreal::UObject* object, const wchar_t* name)
        {
            if (!sbcore::memory::plausible_object(object)) return nullptr;
            void* field{};
            try { field = object->GetValuePtrByPropertyNameInChain(name); }
            catch (...) { return nullptr; }
            return sbcore::memory::is_writable_region(field, sizeof(float)) ? reinterpret_cast<float*>(field) : nullptr;
        }

        bool* bool_property(RC::Unreal::UObject* object, const wchar_t* name)
        {
            if (!sbcore::memory::plausible_object(object)) return nullptr;
            void* field{};
            try { field = object->GetValuePtrByPropertyNameInChain(name); }
            catch (...) { return nullptr; }
            return sbcore::memory::is_writable_region(field, sizeof(bool)) ? reinterpret_cast<bool*>(field) : nullptr;
        }

        RC::Unreal::UObject* object_property(RC::Unreal::UObject* object, const wchar_t* name)
        {
            if (!sbcore::memory::plausible_object(object)) return nullptr;
            void* field{};
            try { field = object->GetValuePtrByPropertyNameInChain(name); }
            catch (...) { return nullptr; }
            if (!sbcore::memory::is_readable_region(field, sizeof(void*), false)) return nullptr;
            auto* value = *reinterpret_cast<RC::Unreal::UObject**>(field);
            return sbcore::memory::plausible_object(value) ? value : nullptr;
        }

        RC::Unreal::UObject* find_player_pawn()
        {
            std::vector<RC::Unreal::UObject*> controllers;
            try { RC::Unreal::UObjectGlobals::FindAllOf(L"SBNetworkPlayerController", controllers); }
            catch (...) { return nullptr; }
            for (auto it = controllers.rbegin(); it != controllers.rend(); ++it)
            {
                if (auto* pawn = object_property(*it, L"Pawn")) return pawn;
            }
            return nullptr;
        }

        RC::Unreal::UObject* find_camera(RC::Unreal::UObject* pawn)
        {
            for (const auto* name : kCameraNames)
            {
                if (auto* camera = object_property(pawn, name)) return camera;
            }
            return nullptr;
        }

        bool plausible_speed(float value)
        {
            return std::isfinite(value) && value >= 10.0f && value <= 5000.0f;
        }

        bool plausible_fov(float value)
        {
            return std::isfinite(value) && value >= 30.0f && value <= 160.0f;
        }

        void reset_movement_for_new_pawn(std::uint64_t pawn)
        {
            gt_pawn = pawn;
            gt_movement_base_captured = false;
            gt_movement_applied = false;
            gt_base_jump = 0.0f;
            gt_base_speeds.fill(0.0f);
            gt_speed_valid.fill(false);
            g_pawn_telemetry.store(pawn, std::memory_order_release);
            g_movement_applied_telemetry.store(false, std::memory_order_release);
        }

        void reset_camera_for_new_object(std::uint64_t camera)
        {
            gt_camera = camera;
            gt_fov_base_captured = false;
            gt_fov_applied = false;
            gt_base_manual_mode = false;
            gt_base_manual_fov = 0.0f;
            gt_last_fov_target = 0.0f;
            g_camera_telemetry.store(camera, std::memory_order_release);
            g_fov_applied_telemetry.store(false, std::memory_order_release);
        }

        void update_fov(RC::Unreal::UObject* pawn)
        {
            auto* camera = find_camera(pawn);
            if (!camera)
            {
                reset_camera_for_new_object(0);
                g_error.store(ErrorCode::NoCamera, std::memory_order_release);
                return;
            }
            const auto camera_address = reinterpret_cast<std::uint64_t>(camera);
            if (camera_address != gt_camera) reset_camera_for_new_object(camera_address);

            float* camera_fov = float_property(camera, L"CameraFov");
            bool* manual_mode = bool_property(camera, L"bManualCameraFovMode");
            float* manual_fov = float_property(camera, L"ManualCameraFov");
            float* override_fov = float_property(camera, L"CameraFovOverride");
            float* current_fov = float_property(camera, L"CurrentFov");
            float* engine_fov = float_property(camera, L"FieldOfView");
            g_live_camera_fov_telemetry.store(camera_fov ? *camera_fov : 0.0f, std::memory_order_release);
            g_live_manual_mode_telemetry.store(manual_mode && *manual_mode, std::memory_order_release);
            g_live_manual_fov_telemetry.store(manual_fov ? *manual_fov : 0.0f, std::memory_order_release);
            g_live_override_fov_telemetry.store(override_fov ? *override_fov : 0.0f, std::memory_order_release);
            g_live_current_fov_telemetry.store(current_fov ? *current_fov : 0.0f, std::memory_order_release);
            g_live_engine_fov_telemetry.store(engine_fov ? *engine_fov : 0.0f, std::memory_order_release);

            if (!manual_mode || !manual_fov)
            {
                g_error.store(ErrorCode::NoManualFov, std::memory_order_release);
                return;
            }
            if (!gt_fov_base_captured)
            {
                if (!plausible_fov(*manual_fov)) return;
                gt_base_manual_mode = *manual_mode;
                gt_base_manual_fov = *manual_fov;
                gt_fov_base_captured = true;
                g_base_manual_mode_telemetry.store(gt_base_manual_mode, std::memory_order_release);
                g_base_manual_fov_telemetry.store(gt_base_manual_fov, std::memory_order_release);
            }

            // A9: a fault anywhere in the process since this task started ends
            // all writes, including the restore of the captured pair.
            if (!game_writes_allowed()) return;

            const float target = g_request_fresh.load(std::memory_order_acquire)
                ? g_fov_deg.load(std::memory_order_acquire) : 0.0f;
            if (target < kMinRequestedFov || target > kMaxRequestedFov)
            {
                if (gt_fov_applied)
                {
                    if (std::fabs(*manual_fov - gt_base_manual_fov) > 0.05f)
                    {
                        *manual_fov = gt_base_manual_fov;
                        g_writes.fetch_add(1, std::memory_order_relaxed);
                    }
                    if (*manual_mode != gt_base_manual_mode)
                    {
                        *manual_mode = gt_base_manual_mode;
                        g_writes.fetch_add(1, std::memory_order_relaxed);
                    }
                }
                gt_fov_applied = false;
                gt_last_fov_target = 0.0f;
            }
            else if (std::fabs(target - gt_last_fov_target) > 0.05f)
            {
                // ManualCameraFov is ignored unless Stellar Blade's own manual
                // mode flag is enabled. A target equal to the captured baseline
                // restores the complete game-owned pair instead of leaving manual
                // mode enabled at a numerically identical value. This preserves
                // Stellar Blade's own sprint/boost camera behavior at stock FOV.
                // CurrentFov and the override fields remain entirely game-owned.
                const bool target_is_base =
                    std::fabs(target - gt_base_manual_fov) <= 0.05f;
                if (target_is_base)
                {
                    if (std::fabs(*manual_fov - gt_base_manual_fov) > 0.05f)
                    {
                        *manual_fov = gt_base_manual_fov;
                        g_writes.fetch_add(1, std::memory_order_relaxed);
                    }
                    if (*manual_mode != gt_base_manual_mode)
                    {
                        *manual_mode = gt_base_manual_mode;
                        g_writes.fetch_add(1, std::memory_order_relaxed);
                    }
                    gt_fov_applied = false;
                }
                else
                {
                    if (!*manual_mode)
                    {
                        *manual_mode = true;
                        g_writes.fetch_add(1, std::memory_order_relaxed);
                    }
                    if (std::fabs(*manual_fov - target) > 0.05f)
                    {
                        *manual_fov = target;
                        g_writes.fetch_add(1, std::memory_order_relaxed);
                    }
                    gt_fov_applied = true;
                }
                gt_last_fov_target = target;
            }
            g_fov_applied_telemetry.store(gt_fov_applied, std::memory_order_release);
            g_live_manual_mode_telemetry.store(*manual_mode, std::memory_order_release);
            g_live_manual_fov_telemetry.store(*manual_fov, std::memory_order_release);
        }

        void restore_movement(RC::Unreal::UObject* movement)
        {
            if (!gt_movement_applied || !gt_movement_base_captured) return;
            if (!game_writes_allowed()) return; // A9: no restore after a fault either
            if (auto* jump = float_property(movement, L"JumpZVelocity")) *jump = gt_base_jump;
            for (std::size_t i = 0; i < kSpeedFieldCount; ++i)
            {
                if (!gt_speed_valid[i]) continue;
                if (auto* field = float_property(movement, kSpeedNames[i])) *field = gt_base_speeds[i];
            }
            gt_movement_applied = false;
            g_movement_applied_telemetry.store(false, std::memory_order_release);
            g_writes.fetch_add(1, std::memory_order_relaxed);
        }

        void update_movement(RC::Unreal::UObject* pawn)
        {
            auto* movement = object_property(pawn, L"CharacterMovement");
            if (!movement)
            {
                g_error.store(ErrorCode::NoMovement, std::memory_order_release);
                return;
            }
            auto* jump = float_property(movement, L"JumpZVelocity");
            if (!jump)
            {
                g_error.store(ErrorCode::NoJump, std::memory_order_release);
                return;
            }

            if (!gt_movement_base_captured)
            {
                if (!std::isfinite(*jump) || *jump <= 0.0f) return;
                gt_base_jump = *jump;
                g_base_jump_telemetry.store(gt_base_jump, std::memory_order_release);
                for (std::size_t i = 0; i < kSpeedFieldCount; ++i)
                {
                    auto* field = float_property(movement, kSpeedNames[i]);
                    gt_speed_valid[i] = field && plausible_speed(*field);
                    gt_base_speeds[i] = gt_speed_valid[i] ? *field : 0.0f;
                    g_base_speed_telemetry[i].store(gt_base_speeds[i], std::memory_order_release);
                }
                gt_movement_base_captured = true;
            }

            const bool enabled = g_request_fresh.load(std::memory_order_acquire)
                && g_enabled.load(std::memory_order_acquire);
            if (!enabled)
            {
                restore_movement(movement);
            }
            else if (game_writes_allowed())
            {
                bool wrote{};
                const float wanted_jump = gt_base_jump * g_jump_mult.load(std::memory_order_acquire);
                if (std::fabs(*jump - wanted_jump) > 0.5f) { *jump = wanted_jump; wrote = true; }
                const float speed = g_speed_mult.load(std::memory_order_acquire);
                for (std::size_t i = 0; i < kSpeedFieldCount; ++i)
                {
                    if (!gt_speed_valid[i]) continue;
                    if (i >= kFirstOverrideField && gt_base_speeds[i] <= 0.0f) continue;
                    if (auto* field = float_property(movement, kSpeedNames[i]))
                    {
                        const float wanted = gt_base_speeds[i] * speed;
                        if (std::fabs(*field - wanted) > 0.5f) { *field = wanted; wrote = true; }
                    }
                }
                if (wrote) g_writes.fetch_add(1, std::memory_order_relaxed);
                gt_movement_applied = true;
                g_movement_applied_telemetry.store(true, std::memory_order_release);
            }

            g_live_jump_telemetry.store(*jump, std::memory_order_release);
            for (std::size_t i = 0; i < kSpeedFieldCount; ++i)
            {
                auto* field = float_property(movement, kSpeedNames[i]);
                g_live_speed_telemetry[i].store(field ? *field : 0.0f, std::memory_order_release);
            }
        }

        // Runs only on the certified GameThread: sbcore::dispatch calls it after
        // proving the executing thread equals the gate-proven GGameThreadId,
        // only while no fault latch is set, and always under
        // sbcore::fault::guarded_call (a fault is logged, latches every sbcore
        // native in the process off, and poisons the dispatcher).
        void execute_game_thread_update(std::uint64_t)
        {
            // A task queued before uninstall() runs no Movement code (1.3.6
            // skipped it in its invoke). The worker re-requests the current
            // state once if the mod is installed again (UE4SS hot reload).
            if (g_shutting_down.load(std::memory_order_acquire))
            {
                g_unload_skipped_callbacks.fetch_add(1, std::memory_order_acq_rel);
                return;
            }
            if (!game_writes_allowed()) return; // the dispatcher also checks
            // Clear only the prior callback's diagnostic before attempting the
            // current acquisition.  Any error published by update_fov() or
            // update_movement() must survive so the worker schedules its
            // bounded acquisition retry instead of treating a partial load as
            // settled steady state.
            g_error.store(ErrorCode::None, std::memory_order_release);
            auto* pawn = find_player_pawn();
            if (!pawn)
            {
                reset_movement_for_new_pawn(0);
                reset_camera_for_new_object(0);
                g_error.store(ErrorCode::NoPawn, std::memory_order_release);
                return;
            }
            const auto pawn_address = reinterpret_cast<std::uint64_t>(pawn);
            if (pawn_address != gt_pawn) reset_movement_for_new_pawn(pawn_address);

            update_fov(pawn);
            update_movement(pawn);
        }

        // 1.3.6 returned early (no error) when not ready, shutting down,
        // poisoned or busy, and reported dispatch-failed when an attempted
        // submission did not reach Setup. sbcore's results map one to one.
        bool dispatch_update()
        {
            if (!g_ready.load(std::memory_order_acquire) || g_shutting_down.load(std::memory_order_acquire)) return false;
            using Result = sbcore::dispatch::SubmitResult;
            switch (sbcore::dispatch::submit(&execute_game_thread_update))
            {
            case Result::Submitted:
                return true;
            case Result::CreateRejected:
            case Result::VtableMismatch:
            case Result::Exception:
                g_error.store(ErrorCode::DispatchFailed, std::memory_order_release);
                return false;
            case Result::NotBound:
            case Result::ShuttingDown:
            case Result::Poisoned:
            case Result::WritesBlocked:
            case Result::Busy:
            case Result::NoCallback:
            default:
                return false;
            }
        }

        // What the heartbeat's `error` reports. 1.3.6 overwrote its install
        // error with the next state read, so a build mismatch never reached the
        // panel; an unarmed native now always names its failed install step
        // (A11), and a latched fault (A9) is never shown as a healthy state.
        ErrorCode reported_error()
        {
            const auto step = g_install_step.load(std::memory_order_acquire);
            if (step != InstallStep::Done)
            {
                return step == InstallStep::Gate ? ErrorCode::BuildMismatch : ErrorCode::InstallFailed;
            }
            if (sbcore::fault::writes_blocked())
            {
                const auto snapshot = sbcore::fault::snapshot();
                if (snapshot.local_faulted)
                {
                    if (std::strcmp(snapshot.last_action, "game_thread_callback") == 0) return ErrorCode::DispatchException;
                    if (std::strcmp(snapshot.last_action, "taskgraph_submit") == 0) return ErrorCode::DispatchFailed;
                }
                return ErrorCode::WritesBlocked;
            }
            return g_error.load(std::memory_order_acquire);
        }

        void add_live_base(sbcore::status::Builder& body, const char* key, float live, float base)
        {
            char text[128];
            const int length = std::snprintf(text, sizeof(text), "%.1f/%.1f", static_cast<double>(live), static_cast<double>(base));
            if (length <= 0 || static_cast<std::size_t>(length) >= sizeof(text))
            {
                body.add_str(key, std::string_view{}); // refuses the whole body
                return;
            }
            body.add_str(key, std::string_view(text, static_cast<std::size_t>(length)));
        }

        const char* or_none(const char* text)
        {
            return text && *text ? text : "none";
        }

        // Caller holds g_worker_lock.
        void publish_heartbeat(WorkerState& worker)
        {
            if (!worker.publisher_ok) return;
            const auto dispatch = sbcore::dispatch::counters();
            // A wrong-thread invoke poisons the dispatcher (sbcore); 1.3.6 also
            // reported it once as error=wrong-thread.
            if (dispatch.wrong_thread > worker.seen_wrong_thread)
            {
                worker.seen_wrong_thread = dispatch.wrong_thread;
                g_error.store(ErrorCode::WrongThread, std::memory_order_release);
            }
            sbcore::fault::refresh_process_latch();
            const auto fault = sbcore::fault::snapshot();
            const bool blocked = sbcore::fault::writes_blocked();

            sbcore::status::Builder body(worker.heartbeat_buffer, sizeof(worker.heartbeat_buffer));
            const auto worker_thread = g_worker_thread_id.load(std::memory_order_acquire);
            const auto callback = dispatch.callback_thread;
            const auto certified = dispatch.certified_game_thread;
            // ---- the 1.3.6 fields, same keys, order and formatting ----
            body.add_str("version", kVersion);
            body.add_str("architecture", kArchitecture);
            body.add_bool("ready", g_ready.load());
            body.add_bool("module_pinned", sbcore::module::pinned());
            body.add_bool("dispatch_poisoned", dispatch.poisoned);
            body.add_u64("worker_thread", worker_thread);
            body.add_u64("callback_thread", callback);
            body.add_u64("certified_game_thread", certified);
            body.add_bool("callback_on_game_thread", callback != 0 && callback == certified);
            body.add_u64("submit_count", dispatch.submit_count);
            body.add_u64("callback_count", dispatch.callback_count);
            body.add_u64("destroy_count", dispatch.destroy_count);
            body.add_u64("last_completed_sequence", dispatch.last_completed_sequence);
            body.add_hex32("last_exception", dispatch.last_exception);
            body.add_u64("desired_revision", g_desired_revision.load());
            body.add_u64("last_dispatched_revision", g_last_dispatched_revision.load());
            body.add_u64("steady_dispatch_skips", g_steady_dispatch_skips.load());
            body.add_bool("request_fresh", g_request_fresh.load());
            body.add_u64("panel_pid", g_panel_pid.load());
            body.add_u64("panel_sequence", g_panel_sequence.load());
            body.add_u64("state_age_ms", g_state_age_ms.load());
            body.add_bool("enabled", g_enabled.load());
            body.add_float("speed", g_speed_mult.load(), 2);
            body.add_float("jump", g_jump_mult.load(), 2);
            body.add_float("fov_target", g_fov_deg.load(), 1);
            body.add_u64("pawn", g_pawn_telemetry.load());
            body.add_u64("camera", g_camera_telemetry.load());
            body.add_bool("movement_applied", g_movement_applied_telemetry.load());
            body.add_bool("fov_applied", g_fov_applied_telemetry.load());
            body.add_float("base_jump", g_base_jump_telemetry.load(), 1);
            body.add_float("live_jump", g_live_jump_telemetry.load(), 1);
            body.add_bool("base_bManualCameraFovMode", g_base_manual_mode_telemetry.load());
            body.add_float("base_ManualCameraFov", g_base_manual_fov_telemetry.load(), 1);
            body.add_float("CameraFov", g_live_camera_fov_telemetry.load(), 1);
            body.add_bool("bManualCameraFovMode", g_live_manual_mode_telemetry.load());
            body.add_float("ManualCameraFov", g_live_manual_fov_telemetry.load(), 1);
            body.add_float("CameraFovOverride", g_live_override_fov_telemetry.load(), 1);
            body.add_float("CurrentFov", g_live_current_fov_telemetry.load(), 1);
            body.add_float("FieldOfView", g_live_engine_fov_telemetry.load(), 1);
            constexpr const char* labels[kSpeedFieldCount]{
                "walk", "guard_run", "lockon_run", "lockon_walk", "jog",
                "run_override", "walk_override",
            };
            for (std::size_t i = 0; i < kSpeedFieldCount; ++i)
                add_live_base(body, labels[i], g_live_speed_telemetry[i].load(), g_base_speed_telemetry[i].load());
            body.add_u64("writes", g_writes.load());
            body.add_str("error", error_name(reported_error()));

            // ---- appended in 1.4.0 (new keys only) ----
            body.add_str("install_failed_step", install_step_name(g_install_step.load()));
            body.add_bool("gate_passed", worker.gate.passed);
            body.add_str("gate_reason", worker.gate_ran ? sbcore::gate::reason_name(worker.gate.reason) : "not_run");
            body.add_str("gate_failed_check", or_none(worker.gate.failed_check));
            body.add_str("gate_failed_manifest", or_none(worker.gate.failed_manifest));
            body.add_u64("gate_manifests_passed", worker.gate.manifests_passed);
            body.add_u64("gate_code_checks_passed", worker.gate.code_checks_passed);
            body.add_u64("gate_slot_checks_passed", worker.gate.slot_checks_passed);
            body.add_u64("gate_global_checks_passed", worker.gate.global_checks_passed);
            body.add_hex32("gate_timestamp", worker.gate.timestamp);
            body.add_hex32("gate_image_size", worker.gate.image_size);
            body.add_u64("gate_exe_file_size", worker.gate.exe_file_size);
            body.add_bool("writes_blocked", blocked);
            body.add_bool("fault_initialized", fault.initialized);
            body.add_bool("fault_local", fault.local_faulted);
            body.add_bool("fault_process_tainted", fault.process_tainted);
            body.add_u64("fault_count", fault.fault_count);
            body.add_hex32("fault_last_code", fault.last_code);
            body.add_str("fault_last_action", or_none(fault.last_action));
            body.add_str("fault_last_module", or_none(fault.last_module_kind));
            body.add_str("fault_policy", sbcore::fault::policy_name(fault.policy));
            body.add_u64("fault_log_lines", fault.log_lines);
            body.add_u64("fault_log_failures", fault.log_failures);
            body.add_u64("fault_log_dropped", fault.log_dropped);
            body.add_bool("dispatch_bound", dispatch.bound);
            body.add_bool("dispatch_pending", dispatch.pending);
            body.add_str("dispatch_last_result", sbcore::dispatch::submit_result_name(dispatch.last_result));
            body.add_u64("dispatch_submit_attempts", dispatch.submit_attempts);
            body.add_u64("dispatch_callbacks_run", dispatch.callbacks_run);
            body.add_u64("dispatch_skipped_blocked", dispatch.skipped_blocked);
            body.add_u64("dispatch_skipped_shutdown", dispatch.skipped_shutdown);
            body.add_u64("dispatch_wrong_thread", dispatch.wrong_thread);
            body.add_u64("dispatch_released_pre_setup", dispatch.released_pre_setup);
            body.add_u64("dispatch_last_submitted_sequence", dispatch.last_submitted_sequence);
            body.add_str("state_read", sbcore::status::read_result_name(worker.state_read_raw));
            body.add_str("state_read_effective", sbcore::status::read_result_name(worker.state_read_effective));
            body.add_u64("state_grace_hits", worker.state_reader.grace_hits());
            const auto& writer = worker.publisher.writer().counters();
            body.add_u64("status_publishes", writer.publishes);
            body.add_u64("status_rename_retries", writer.rename_retries);
            body.add_u64("status_fallback_renames", writer.fallback_renames);
            body.add_u64("status_last_error", writer.last_error);
            body.add_u64("heartbeat_build_failures", worker.heartbeat_build_failures);
            // ---- appended in 1.4.1 (new keys only) ----
            body.add_u64("install_count", g_install_count.load());
            body.add_u64("unload_skipped_callbacks", g_unload_skipped_callbacks.load());

            if (!body.ok())
            {
                // Never publish a body the panel's strict parser would reject;
                // the previous good heartbeat stays in place and goes stale.
                ++worker.heartbeat_build_failures;
                return;
            }
            worker.publisher.maybe_publish(body, tick_now(), true);
        }

        // Caller holds g_worker_lock and has checked !g_running.
        //
        // Runs on the first on_unreal_init and again on every UE4SS hot reload
        // (Ctrl+R: uninstall_mod, FreeLibrary of this pinned module, start_mod,
        // on_unreal_init). 1.3.6 re-armed on that second install; so does this:
        // the pinned module keeps its WorkerState, the GameThread-owned captured
        // bases (a later disable restores the game's own values) and the sbcore
        // fault latch (a fault stays latched across a reload). Every arming step
        // after the paths - fault init, pin, the exact-build gate, the
        // dispatcher binding - runs again, as 1.3.6 re-ran pin and gate.
        bool install_locked()
        {
            if (!g_worker)
            {
                auto* created = new (std::nothrow) WorkerState();
                if (!created)
                {
                    g_install_step.store(InstallStep::Allocation, std::memory_order_release);
                    return false;
                }
                g_worker = created;
            }
            auto* worker = g_worker;
            g_install_count.fetch_add(1, std::memory_order_acq_rel);

            // 1. P1: every path from this DLL's own location. Without a
            //    Mods\<Mod>\dlls layout there is nowhere safe to report to, so
            //    the native stays completely inert (fail closed).
            if (!worker->paths_ok)
            {
                if (sbcore::paths::resolve_this_module(worker->paths) != sbcore::paths::Error::None)
                {
                    g_install_step.store(InstallStep::Paths, std::memory_order_release);
                    g_error.store(ErrorCode::InstallFailed, std::memory_order_release);
                    return false;
                }
                worker->paths_ok = true;
                sbcore::status::StableReader::Options reader_options;
                reader_options.max_bytes = kStateMaxBytes;
                reader_options.grace_ms = kStateGraceMs;
                worker->reader_ok = worker->state_reader.configure(worker->paths.in_panel(kStateLeaf), reader_options);
                sbcore::status::Publisher::Options publisher_options;
                publisher_options.module = kModName;
                publisher_options.module_version = kVersion;
                publisher_options.beat_ms = kHeartbeatMs;
                publisher_options.min_interval_ms = kHeartbeatMs;
                worker->publisher_ok = worker->publisher.configure(publisher_options, worker->paths.in_mod(kHeartbeatLeaf),
                                                                   worker->paths.in_mod(kHeartbeatTempLeaf));
            }
            // Only now may a queued task run Movement code again.
            g_shutting_down.store(false, std::memory_order_release);

            InstallStep failed = InstallStep::Done;
            // 2. A9: the process-wide latch and the persistent fault log.
            sbcore::fault::Config fault_config;
            fault_config.native_name = kModName;
            fault_config.native_version = kVersion;
            fault_config.log_path = worker->paths.in_mod(kFaultLogLeaf);
            if (!sbcore::fault::init(fault_config))
            {
                failed = InstallStep::FaultInit;
            }
            // 3. Never unloaded while a task may point into this DLL.
            else if (!sbcore::module::pin_this_module())
            {
                failed = InstallStep::Pin;
            }
            else
            {
                // 4. A11: the exact build (read-only).
                worker->gate = run_gate();
                worker->gate_ran = true;
                if (!worker->gate.passed) failed = InstallStep::Gate;
                // 5. The certified GameThread TaskGraph.
                else if (!sbcore::dispatch::bind(worker->gate)) failed = InstallStep::Bind;
            }

            const bool ready = failed == InstallStep::Done;
            g_install_step.store(failed, std::memory_order_release);
            g_ready.store(ready, std::memory_order_release);
            if (!ready)
            {
                g_error.store(failed == InstallStep::Gate ? ErrorCode::BuildMismatch : ErrorCode::InstallFailed,
                              std::memory_order_release);
            }
            refresh_desired_state(*worker, tick_now());
            publish_heartbeat(*worker);
            // Heartbeats and state telemetry continue while unarmed (as 1.3.6);
            // dispatch_update() refuses every submission unless ready.
            g_running.store(true, std::memory_order_release);
            return ready;
        }

        // Caller holds g_worker_lock.
        void on_update_locked(WorkerState& worker)
        {
            if (g_worker_thread_id.load(std::memory_order_relaxed) == 0)
                g_worker_thread_id.store(GetCurrentThreadId(), std::memory_order_release);
            const auto now = tick_now();
            if (now - worker.last_state_poll_tick >= kStatePollMs)
            {
                worker.last_state_poll_tick = now;
                refresh_desired_state(worker, now);
            }
            // A task that was queued across an unload applied nothing, yet its
            // revision counts as dispatched: after the reload, request the
            // current state once more (one task, on the certified GameThread).
            const auto unload_skips = g_unload_skipped_callbacks.load(std::memory_order_acquire);
            if (unload_skips != worker.seen_unload_skips)
            {
                worker.seen_unload_skips = unload_skips;
                g_desired_revision.fetch_add(1, std::memory_order_acq_rel);
            }
            const auto desired_revision = g_desired_revision.load(std::memory_order_acquire);
            const bool semantic_update_pending = desired_revision
                != g_last_dispatched_revision.load(std::memory_order_acquire);
            // FOV and Movement are both one-shot. After the requested values are
            // applied, an unchanged panel lease causes no Unreal lookup, reflected
            // read, or TaskGraph submission. This deliberately removes the old
            // ten-per-second Movement maintenance path as well as the FOV audit
            // path; either one can hitch the GameThread while Eve is moving. Lease
            // expiry still increments desired_revision and schedules one restore.
            // A semantic request can arrive during startup/loading before a valid
            // pawn or camera exists. Retry only that unresolved acquisition at a
            // bounded cadence; once both identities are known, steady-state FOV
            // returns to zero GameThread submissions.
            const auto last_error = g_error.load(std::memory_order_acquire);
            const bool acquire_initial_targets = g_request_fresh.load(std::memory_order_acquire)
                && (g_pawn_telemetry.load(std::memory_order_acquire) == 0
                    || g_camera_telemetry.load(std::memory_order_acquire) == 0
                    || last_error == ErrorCode::NoManualFov
                    || last_error == ErrorCode::NoMovement
                    || last_error == ErrorCode::NoJump)
                && now - worker.last_dispatch_tick >= kAcquireRetryMs;
            if (semantic_update_pending || acquire_initial_targets)
            {
                if (dispatch_update())
                {
                    worker.last_dispatch_tick = now;
                    g_last_dispatched_revision.store(desired_revision, std::memory_order_release);
                }
            }
            else
            {
                g_steady_dispatch_skips.fetch_add(1, std::memory_order_relaxed);
            }
            if (now - worker.last_heartbeat_tick >= kHeartbeatMs)
            {
                worker.last_heartbeat_tick = now;
                publish_heartbeat(worker);
            }
        }
    }

    bool install()
    {
        AcquireSRWLockExclusive(&g_worker_lock);
        // Installed and not unloaded since: nothing to do (as 1.3.6). After
        // uninstall() this re-arms (UE4SS hot reload).
        const bool ready = g_running.load(std::memory_order_acquire) ? g_ready.load(std::memory_order_acquire)
                                                                      : install_locked();
        ReleaseSRWLockExclusive(&g_worker_lock);
        return ready;
    }

    void on_update()
    {
        if (!g_running.load(std::memory_order_acquire)) return;
        AcquireSRWLockExclusive(&g_worker_lock);
        if (g_running.load(std::memory_order_acquire) && g_worker) on_update_locked(*g_worker);
        ReleaseSRWLockExclusive(&g_worker_lock);
    }

    void uninstall()
    {
        // Never touch Unreal state from UE4SS's unload/worker path. Runtime
        // disable and lease expiry restore owned values in the GameThread task;
        // process teardown discards all remaining process memory. A task that
        // is still queued runs no Movement code (g_shutting_down, checked first
        // in execute_game_thread_update) and dispatch_update() submits nothing.
        // sbcore::dispatch::shutdown() is deliberately not used: it cannot be
        // undone, and UE4SS calls uninstall_mod only for a hot reload
        // (reinstall_mods), after which install() must re-arm as 1.3.6 did.
        g_shutting_down.store(true, std::memory_order_release);
        AcquireSRWLockExclusive(&g_worker_lock);
        g_running.store(false, std::memory_order_release);
        if (g_worker) publish_heartbeat(*g_worker);
        ReleaseSRWLockExclusive(&g_worker_lock);
    }

    const char* install_failed_step()
    {
        return install_step_name(g_install_step.load(std::memory_order_acquire));
    }
}

#if defined(SBMOVE_TESTING)
// Offline harness hooks. Compiled only into the test DLL (SBMOVE_TESTING);
// tools/check_pe.py fails the staged DLL if it exports anything but
// start_mod and uninstall_mod.
extern "C" __declspec(dllexport) void sbmove_testing_set_fake_image(const void* image)
{
    sbmove::g_test_fake_image.store(image, std::memory_order_release);
}

extern "C" __declspec(dllexport) void sbmove_testing_set_clock(std::uint64_t now_ms)
{
    sbmove::g_test_clock.store(now_ms, std::memory_order_release);
}
#endif
