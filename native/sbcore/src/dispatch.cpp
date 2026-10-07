#include "sbcore/dispatch.hpp"

#include <atomic>
#include <cstddef>

#include <windows.h>

#include "sbcore/fault.hpp"
#include "sbcore/gate.hpp"
#include "sbcore/memory.hpp"
#include "sbcore/taskgraph_manifest.generated.hpp"

namespace sbcore::dispatch
{
    namespace
    {
        // Layouts exactly as SBMovementNative 1.3.6 movement.cpp:87-114,
        // SBRetryPointNative 0.1.1 retry_point.cpp:136-162, SBGodNative 1.1.2.
        struct TaskConstruction
        {
            void* task{};
            void* prerequisites{};
            std::uint32_t current_thread{};
            std::uint32_t padding{};
        };
        static_assert(sizeof(TaskConstruction) == 0x18);

        struct DispatchPayload
        {
            std::uint64_t sequence{};
            std::uint64_t reserved_a{};
            std::uint64_t reserved_b{};
        };
        static_assert(sizeof(DispatchPayload) == 0x18);

        struct CallableVtable
        {
            void (*copy_to_empty_storage)(void*, void*);
            void* (*get_callable)(void*);
            void (*destroy)(void*);
            void (*destruct)(void*, std::uint8_t);
        };

        using CreateTaskFn = TaskConstruction* (*)(TaskConstruction*, void*, std::uint32_t);
        using SetupTaskFn = void (*)(void*, void*, std::uint32_t, bool);
        using DeleteTaskFn = void* (*)(void*, std::uint32_t);

        constexpr std::uint32_t kAnyThread = 0xFF;
        constexpr std::uint32_t kTaskGraphTargetThread = 2;
        constexpr std::size_t kTaskInvokeOffset = 0x10;
        constexpr std::size_t kTaskHeapStorageOffset = 0x20;
        constexpr std::size_t kTaskCallableVtableOffset = 0x30;
        constexpr std::size_t kTaskPayloadOffset = 0x38;
        constexpr std::size_t kTaskTargetThreadOffset = 0x50;
        constexpr std::size_t kTaskReleaseProbeSize = 0x70;

        // Written only by bind() before g_bound is released.
        CreateTaskFn g_create_task = nullptr;
        SetupTaskFn g_setup_task = nullptr;
        DeleteTaskFn g_delete_task = nullptr;
        const void* g_task_vtable = nullptr;
        const std::uint32_t* g_game_thread_id = nullptr;
        const std::byte* g_bound_image = nullptr;

        std::atomic<bool> g_bound{false};
        std::atomic<bool> g_shutting_down{false};
        std::atomic<bool> g_pending{false};
        std::atomic<bool> g_poisoned{false};
        std::atomic<Callback> g_callback{nullptr};
        std::atomic<std::uint64_t> g_sequence{0};
        std::atomic<std::uint64_t> g_submit_attempts{0};
        std::atomic<std::uint64_t> g_submit_count{0};
        std::atomic<std::uint64_t> g_callback_count{0};
        std::atomic<std::uint64_t> g_callbacks_run{0};
        std::atomic<std::uint64_t> g_destroy_count{0};
        std::atomic<std::uint64_t> g_skipped_blocked{0};
        std::atomic<std::uint64_t> g_skipped_shutdown{0};
        std::atomic<std::uint64_t> g_wrong_thread{0};
        std::atomic<std::uint64_t> g_released_pre_setup{0};
        std::atomic<std::uint64_t> g_last_submitted{0};
        std::atomic<std::uint64_t> g_last_completed{0};
        std::atomic<std::uint32_t> g_callback_thread{0};
        std::atomic<std::uint32_t> g_certified_thread{0};
        std::atomic<std::uint32_t> g_last_exception{0};
        std::atomic<SubmitResult> g_last_result{SubmitResult::NotBound};

        void copy_to_empty_storage(void*, void*) {}
        void* get_callable(void* storage) { return static_cast<std::byte*>(storage) + sizeof(void*); }
        void destroy_callable(void*) { g_destroy_count.fetch_add(1, std::memory_order_relaxed); }
        void destruct_callable(void* storage, std::uint8_t) { destroy_callable(storage); }
        const CallableVtable g_callable_vtable{
            &copy_to_empty_storage, &get_callable, &destroy_callable, &destruct_callable,
        };

        struct CallbackContext
        {
            Callback callback;
            std::uint64_t sequence;
        };

        void run_callback(void* raw)
        {
            const auto* context = static_cast<const CallbackContext*>(raw);
            context->callback(context->sequence);
        }

        // The GameThread entry. The engine's ExecuteTask calls
        // (task+0x10)(get_callable(task+0x30)) == invoke_dispatch(task+0x38).
        void invoke_dispatch(void* raw_payload)
        {
            const auto* payload = static_cast<const DispatchPayload*>(raw_payload);
            const std::uint64_t sequence = payload->sequence;
            const auto callback_thread = GetCurrentThreadId();
            g_callback_thread.store(callback_thread, std::memory_order_release);
            std::uint32_t certified_thread = 0;
            const bool thread_known = g_game_thread_id
                && memory::read_exact(g_game_thread_id, &certified_thread, sizeof(certified_thread));
            g_certified_thread.store(certified_thread, std::memory_order_release);

            if (g_shutting_down.load(std::memory_order_acquire))
            {
                // Process teardown owns all remaining values.
                g_skipped_shutdown.fetch_add(1, std::memory_order_relaxed);
            }
            else if (!thread_known || certified_thread == 0 || callback_thread != certified_thread)
            {
                g_wrong_thread.fetch_add(1, std::memory_order_relaxed);
                g_poisoned.store(true, std::memory_order_release);
            }
            else if (fault::writes_blocked())
            {
                g_skipped_blocked.fetch_add(1, std::memory_order_relaxed);
            }
            else
            {
                CallbackContext context{g_callback.load(std::memory_order_acquire), sequence};
                if (context.callback)
                {
                    if (fault::guarded_call(&run_callback, &context, "game_thread_callback"))
                    {
                        g_callbacks_run.fetch_add(1, std::memory_order_relaxed);
                    }
                    else
                    {
                        g_last_exception.store(fault::snapshot().last_code, std::memory_order_release);
                        g_poisoned.store(true, std::memory_order_release);
                    }
                }
            }
            g_callback_count.fetch_add(1, std::memory_order_relaxed);
            // Release the lease first, then publish completion (BossRetry rule):
            // a coordinator that observes the completed sequence can submit.
            g_pending.store(false, std::memory_order_release);
            g_last_completed.store(sequence, std::memory_order_release);
        }

        bool release_pre_setup_task(void* raw_task)
        {
            if (!raw_task || !g_delete_task || !memory::is_readable_region(raw_task, kTaskReleaseProbeSize, false))
            {
                return raw_task == nullptr;
            }
            if (*static_cast<void**>(raw_task) != g_task_vtable) return false;
            g_delete_task(raw_task, 1);
            g_released_pre_setup.fetch_add(1, std::memory_order_relaxed);
            return true;
        }

        struct SubmitContext
        {
            std::uint64_t sequence;
            SubmitResult result;
        };

        void submit_body(void* raw)
        {
            auto* context = static_cast<SubmitContext*>(raw);
            TaskConstruction construction{};
            auto* returned = g_create_task(&construction, nullptr, kAnyThread);
            if (returned != &construction || !construction.task || construction.prerequisites
                || construction.current_thread != kAnyThread)
            {
                if (!release_pre_setup_task(construction.task)) g_poisoned.store(true, std::memory_order_release);
                context->result = SubmitResult::CreateRejected;
                return;
            }
            auto* task = static_cast<std::byte*>(construction.task);
            if (*reinterpret_cast<void**>(task) != g_task_vtable)
            {
                g_poisoned.store(true, std::memory_order_release);
                context->result = SubmitResult::VtableMismatch;
                return;
            }
            *reinterpret_cast<void (**)(void*)>(task + kTaskInvokeOffset) = &invoke_dispatch;
            *reinterpret_cast<void**>(task + kTaskHeapStorageOffset) = nullptr;
            *reinterpret_cast<const CallableVtable**>(task + kTaskCallableVtableOffset) = &g_callable_vtable;
            auto* payload = reinterpret_cast<DispatchPayload*>(task + kTaskPayloadOffset);
            payload->sequence = context->sequence;
            payload->reserved_a = 0;
            payload->reserved_b = 0;
            *reinterpret_cast<std::uint32_t*>(task + kTaskTargetThreadOffset) = kTaskGraphTargetThread;
            g_setup_task(construction.task, construction.prerequisites, construction.current_thread, true);
            context->result = SubmitResult::Submitted;
        }

        SubmitResult finish(SubmitResult result)
        {
            g_last_result.store(result, std::memory_order_release);
            return result;
        }
    }

    bool bind(const gate::Result& passed_gate)
    {
        if (!passed_gate.passed || !passed_gate.image) return false;
        if (g_bound.load(std::memory_order_acquire)) return g_bound_image == passed_gate.image;
        const std::byte* image = passed_gate.image;
        g_create_task = reinterpret_cast<CreateTaskFn>(const_cast<std::byte*>(image + taskgraph::kCreateTaskRva));
        g_setup_task = reinterpret_cast<SetupTaskFn>(const_cast<std::byte*>(image + taskgraph::kSetupTaskRva));
        g_delete_task = reinterpret_cast<DeleteTaskFn>(const_cast<std::byte*>(image + taskgraph::kTaskDestructorRva));
        g_task_vtable = image + taskgraph::kTaskVtableRva;
        g_game_thread_id = reinterpret_cast<const std::uint32_t*>(image + taskgraph::kGameThreadIdRva);
        g_bound_image = image;
        g_bound.store(true, std::memory_order_release);
        return true;
    }

    bool bound()
    {
        return g_bound.load(std::memory_order_acquire);
    }

    void shutdown()
    {
        g_shutting_down.store(true, std::memory_order_release);
    }

    SubmitResult submit(Callback callback)
    {
        g_submit_attempts.fetch_add(1, std::memory_order_relaxed);
        if (!callback) return finish(SubmitResult::NoCallback);
        if (!g_bound.load(std::memory_order_acquire)) return finish(SubmitResult::NotBound);
        if (g_shutting_down.load(std::memory_order_acquire)) return finish(SubmitResult::ShuttingDown);
        if (g_poisoned.load(std::memory_order_acquire)) return finish(SubmitResult::Poisoned);
        if (fault::writes_blocked()) return finish(SubmitResult::WritesBlocked);
        bool expected = false;
        if (!g_pending.compare_exchange_strong(expected, true, std::memory_order_acq_rel, std::memory_order_acquire))
        {
            return finish(SubmitResult::Busy);
        }
        const auto sequence = g_sequence.fetch_add(1, std::memory_order_acq_rel) + 1;
        g_callback.store(callback, std::memory_order_release);
        SubmitContext context{sequence, SubmitResult::Exception};
        if (!fault::guarded_call(&submit_body, &context, "taskgraph_submit"))
        {
            // Ambiguous: the task may already be queued. Keep the lease, poison.
            g_last_exception.store(fault::snapshot().last_code, std::memory_order_release);
            g_poisoned.store(true, std::memory_order_release);
            return finish(SubmitResult::Exception);
        }
        if (context.result == SubmitResult::Submitted)
        {
            g_submit_count.fetch_add(1, std::memory_order_relaxed);
            g_last_submitted.store(sequence, std::memory_order_release);
        }
        else
        {
            g_pending.store(false, std::memory_order_release);
        }
        return finish(context.result);
    }

    bool on_game_thread()
    {
        std::uint32_t certified = 0;
        return g_game_thread_id && memory::read_exact(g_game_thread_id, &certified, sizeof(certified))
            && certified != 0 && certified == GetCurrentThreadId();
    }

    Counters counters()
    {
        Counters c;
        c.bound = g_bound.load(std::memory_order_acquire);
        c.poisoned = g_poisoned.load(std::memory_order_acquire);
        c.pending = g_pending.load(std::memory_order_acquire);
        c.shutting_down = g_shutting_down.load(std::memory_order_acquire);
        c.submit_attempts = g_submit_attempts.load(std::memory_order_relaxed);
        c.submit_count = g_submit_count.load(std::memory_order_relaxed);
        c.callback_count = g_callback_count.load(std::memory_order_relaxed);
        c.callbacks_run = g_callbacks_run.load(std::memory_order_relaxed);
        c.destroy_count = g_destroy_count.load(std::memory_order_relaxed);
        c.skipped_blocked = g_skipped_blocked.load(std::memory_order_relaxed);
        c.skipped_shutdown = g_skipped_shutdown.load(std::memory_order_relaxed);
        c.wrong_thread = g_wrong_thread.load(std::memory_order_relaxed);
        c.released_pre_setup = g_released_pre_setup.load(std::memory_order_relaxed);
        c.last_submitted_sequence = g_last_submitted.load(std::memory_order_acquire);
        c.last_completed_sequence = g_last_completed.load(std::memory_order_acquire);
        c.callback_thread = g_callback_thread.load(std::memory_order_acquire);
        c.certified_game_thread = g_certified_thread.load(std::memory_order_acquire);
        c.last_exception = g_last_exception.load(std::memory_order_acquire);
        c.last_result = g_last_result.load(std::memory_order_acquire);
        return c;
    }

    const char* submit_result_name(SubmitResult result)
    {
        switch (result)
        {
        case SubmitResult::Submitted: return "submitted";
        case SubmitResult::NotBound: return "not_bound";
        case SubmitResult::ShuttingDown: return "shutting_down";
        case SubmitResult::Poisoned: return "poisoned";
        case SubmitResult::WritesBlocked: return "writes_blocked";
        case SubmitResult::Busy: return "busy";
        case SubmitResult::NoCallback: return "no_callback";
        case SubmitResult::CreateRejected: return "create_rejected";
        case SubmitResult::VtableMismatch: return "vtable_mismatch";
        case SubmitResult::Exception: return "exception";
        }
        return "unknown";
    }

#if defined(SBCORE_TESTING)
    namespace testing
    {
        static_assert(sizeof(testing::TaskConstruction) == sizeof(dispatch::TaskConstruction));

        void bind(const Bindings& bindings)
        {
            g_create_task = reinterpret_cast<dispatch::CreateTaskFn>(bindings.create_task);
            g_setup_task = bindings.setup_task;
            g_delete_task = bindings.delete_task;
            g_task_vtable = bindings.task_vtable;
            g_game_thread_id = bindings.game_thread_id;
            g_bound_image = nullptr;
            g_bound.store(true, std::memory_order_release);
        }

        void reset()
        {
            g_bound.store(false);
            g_shutting_down.store(false);
            g_pending.store(false);
            g_poisoned.store(false);
            g_callback.store(nullptr);
        }

        const void* invoke_function()
        {
            return reinterpret_cast<const void*>(&invoke_dispatch);
        }

        const void* callable_vtable()
        {
            return &g_callable_vtable;
        }
    }
#endif
}
