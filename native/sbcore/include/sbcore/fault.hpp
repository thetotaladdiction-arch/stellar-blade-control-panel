#pragma once

// SEH fault capture, persistent breadcrumbs and the "faulted -> block writes"
// latch (A9, stage 1).
//
// Stage 1 policy (the only one enabled): a fault inside code we called (a
// UE4SS/engine/game function, or our own GameThread callback) is caught,
// written as one line to an append-only fault log, and latches two flags:
//   * this module's local latch, and
//   * the process-wide latch, a named manual-reset event
//     Local\SBCore.Tainted.<pid> that every sbcore native in the process sees.
// After either latch is set, writes_blocked() is true forever for this
// process: the native must make no further game write of any kind (including
// restores), and the dispatcher refuses to submit or run GameThread work.
// The game keeps running with the feature off, as God already did.
//
// Stage 2 (EXCEPTION_CONTINUE_SEARCH so the game's crash reporter writes a
// dump) is implemented as Policy::CrashToReporter but is NOT enabled; switch
// only after 3 sessions record zero breadcrumbs (plan A9 [R0927]).
//
// The filter is heap-free and CRT-free: it formats into a stack buffer and
// calls WriteFile on a handle opened at init(). STATUS_STACK_OVERFLOW is
// logged after the unwind (the filter runs on the exhausted stack) and the
// guard page is restored with _resetstkoflw().

#include <cstdint>
#include <string>

struct _EXCEPTION_POINTERS;

namespace sbcore::fault
{
    enum class Policy : std::uint8_t
    {
        ContinueFeatureOff = 0, // stage 1: handle, log, latch, continue with writes blocked
        CrashToReporter = 1,    // stage 2: log, latch, EXCEPTION_CONTINUE_SEARCH (not enabled)
    };

    struct Config
    {
        const char* native_name = nullptr;    // ASCII, e.g. "SBMovementNative"; copied
        const char* native_version = nullptr; // ASCII, e.g. "1.3.7"; copied
        std::wstring log_path;                // e.g. paths.in_mod(L"sbcore_faults.log"); empty = no file
        std::uint64_t log_cap_bytes = 1u << 20; // lines beyond the cap are dropped and counted
        Policy policy = Policy::ContinueFeatureOff;
        bool write_session_line = true;       // one "event=session_start" line per init
    };

    // Opens/creates the process-wide latch and the log handle. Returns false
    // if the latch event cannot be created or opened (the native must then
    // fail closed). Until init() succeeds, writes_blocked() is true.
    // Call once, from install(), before any game write.
    bool init(const Config& config);
    bool initialized();

    // True if this module faulted, any sbcore native in the process latched
    // the process-wide event, or init() never succeeded. Performs one
    // WaitForSingleObject(event, 0) until the latch is seen, then only an
    // atomic load. Use before every game write on the worker / GameThread.
    bool writes_blocked();

    // Atomic loads only (no syscall): the local latch, the cached process
    // latch, and !initialized. For hot hook paths; refresh the cache with
    // writes_blocked() or refresh_process_latch() from the worker each tick.
    bool writes_blocked_fast();
    bool refresh_process_latch();

    bool local_faulted();
    bool process_tainted(); // queries the event

    // Latch explicitly (e.g. an outcome that cannot be proven safe). Writes a
    // breadcrumb with code 0 and the given action.
    void taint(const char* action);

    // Runs fn(context) under the stage policy. Returns true if it returned
    // normally, false if it faulted (breadcrumb written, latches set).
    using GuardedFn = void (*)(void* context);
    bool guarded_call(GuardedFn fn, void* context, const char* action);

    // For a native's own __try blocks:
    //   __except (sbcore::fault::filter(GetExceptionInformation(), "action")) { ... }
    // then call sbcore::fault::after_handler() inside the __except block.
    int filter(_EXCEPTION_POINTERS* pointers, const char* action);
    void after_handler();

    struct Snapshot
    {
        bool initialized = false;
        bool latch_available = false;
        bool local_faulted = false;
        bool process_tainted = false;
        std::uint64_t fault_count = 0;
        std::uint32_t last_code = 0;
        std::uint64_t last_address = 0;
        std::uint64_t last_module_base = 0;
        char last_module_kind[8] = {}; // game / self / ue4ss / other / none
        char last_action[40] = {};
        std::uint64_t log_lines = 0;
        std::uint64_t log_failures = 0;
        std::uint64_t log_dropped = 0;
        std::uint64_t stack_overflows_reset = 0;
        Policy policy = Policy::ContinueFeatureOff;
    };
    Snapshot snapshot();

    const char* policy_name(Policy policy);

#if defined(SBCORE_TESTING)
    namespace testing
    {
        // Name of the process-wide latch event for this process.
        std::wstring latch_name();
    }
#endif
}
