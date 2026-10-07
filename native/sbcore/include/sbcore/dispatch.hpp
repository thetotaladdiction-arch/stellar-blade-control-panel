#pragma once

// TaskGraph GameThread dispatch, lifted from SBMovementNative 1.3.6 /
// SBRetryPointNative 0.1.1 / SBGodNative 1.1.2 with BossRetry 0.11.0's lease
// rule. The task the game sees is byte-for-byte what those natives build:
//
//   FFunctionGraphTask::CreateTask(&construction, nullptr, AnyThread=0xFF)
//   task+0x10 = invoke function        task+0x20 = nullptr (inline storage)
//   task+0x30 = callable vtable {copy, get_callable(+8), destroy, destruct}
//   task+0x38 = payload {sequence, 0, 0}
//   task+0x50 = 2 (the GameThread)
//   TGraphTask::Setup(task, prerequisites, current_thread, true)
//
// The callback runs only if the executing thread equals the value of the
// gate-proven GGameThreadId global at that moment; otherwise the dispatcher
// is poisoned and nothing runs. The callback runs under fault::guarded_call.
//
// Lease: one task in flight per module. A clean refusal before Setup releases
// the lease. An exception inside CreateTask/Setup is ambiguous (the task may
// already be queued), so the lease stays held and the dispatcher is poisoned
// (BossRetry rule; Movement/God released it, which could allow a second task
// if poison were ever cleared). The completion counter is published after the
// lease is released, so a coordinator that sees it can submit at once.
//
// Only one dispatcher exists per module (the invoke function has no context
// pointer; the payload bytes stay identical to the lifted natives).

#include <cstdint>

namespace sbcore::gate
{
    struct Result;
}

namespace sbcore::dispatch
{
    using Callback = void (*)(std::uint64_t sequence);

    enum class SubmitResult : std::uint8_t
    {
        Submitted = 0,
        NotBound,       // bind() never succeeded
        ShuttingDown,
        Poisoned,
        WritesBlocked,  // fault latch set (this module or process-wide)
        Busy,           // a task is still in flight
        NoCallback,
        CreateRejected, // CreateTask returned an unexpected construction (task released)
        VtableMismatch, // the created task is not an FFunctionGraphTask (poisoned)
        Exception,      // fault inside CreateTask/Setup (poisoned, lease held)
    };

    // Binds to the image of a passed gate result. Refuses if !passed.
    bool bind(const gate::Result& passed_gate);
    bool bound();

    // Stop submitting; a task already queued runs no callback.
    void shutdown();

    SubmitResult submit(Callback callback);

    // Inside a callback: true if the current thread is the certified GameThread.
    bool on_game_thread();

    struct Counters
    {
        bool bound = false;
        bool poisoned = false;
        bool pending = false;
        bool shutting_down = false;
        std::uint64_t submit_attempts = 0;
        std::uint64_t submit_count = 0;       // tasks handed to Setup
        std::uint64_t callback_count = 0;     // invoke() entries (any outcome)
        std::uint64_t callbacks_run = 0;      // native callback actually executed
        std::uint64_t destroy_count = 0;      // callable destroy() calls from the engine
        std::uint64_t skipped_blocked = 0;    // invoke() skipped: writes blocked
        std::uint64_t skipped_shutdown = 0;
        std::uint64_t wrong_thread = 0;
        std::uint64_t released_pre_setup = 0; // tasks released via the destructor
        std::uint64_t last_submitted_sequence = 0;
        std::uint64_t last_completed_sequence = 0;
        std::uint32_t callback_thread = 0;
        std::uint32_t certified_game_thread = 0;
        std::uint32_t last_exception = 0;
        SubmitResult last_result = SubmitResult::NotBound;
    };
    Counters counters();

    const char* submit_result_name(SubmitResult result);

#if defined(SBCORE_TESTING)
    namespace testing
    {
        struct TaskConstruction
        {
            void* task;
            void* prerequisites;
            std::uint32_t current_thread;
            std::uint32_t padding;
        };
        using CreateTaskFn = TaskConstruction* (*)(TaskConstruction*, void*, std::uint32_t);
        using SetupTaskFn = void (*)(void*, void*, std::uint32_t, bool);
        using DeleteTaskFn = void* (*)(void*, std::uint32_t);

        struct Bindings
        {
            CreateTaskFn create_task;
            SetupTaskFn setup_task;
            DeleteTaskFn delete_task;
            const void* task_vtable;
            const std::uint32_t* game_thread_id;
        };
        // Binds to a fake TaskGraph (tests only; not compiled into sbcore.lib).
        void bind(const Bindings& bindings);
        void reset();
        // The invoke function and callable vtable the dispatcher writes.
        const void* invoke_function();
        const void* callable_vtable();
    }
#endif
}
