#include "sbcore/fault.hpp"

#include <atomic>
#include <cstdint>
#include <cstring>

#include <windows.h>

#include <malloc.h> // _resetstkoflw

#include "sbcore/version.hpp"

namespace sbcore::fault
{
    namespace
    {
        // ---- State (atomics only; read from any thread, the filter included) ----
        std::atomic<bool> g_initialized{false};
        std::atomic<bool> g_latch_available{false};
        std::atomic<bool> g_local_faulted{false};
        std::atomic<bool> g_process_seen{false};
        std::atomic<std::uint8_t> g_policy{static_cast<std::uint8_t>(Policy::ContinueFeatureOff)};
        HANDLE g_latch_event = nullptr;                 // written once in init() before g_initialized
        HANDLE g_log_file = INVALID_HANDLE_VALUE;       // written once in init() before g_initialized
        std::uint64_t g_log_cap = 1u << 20;
        char g_native_name[48] = "unknown";
        char g_native_version[24] = "unknown";
        std::uintptr_t g_exe_base = 0;
        std::uintptr_t g_self_base = 0;
        std::uintptr_t g_ue4ss_base = 0;

        std::atomic<std::uint64_t> g_fault_count{0};
        std::atomic<std::uint32_t> g_last_code{0};
        std::atomic<std::uint64_t> g_last_address{0};
        std::atomic<std::uint64_t> g_last_module_base{0};
        std::atomic<std::uint8_t> g_last_module_kind{0};
        std::atomic<const char*> g_last_action{nullptr};
        std::atomic<std::uint64_t> g_log_lines{0};
        std::atomic<std::uint64_t> g_log_failures{0};
        std::atomic<std::uint64_t> g_log_dropped{0};
        std::atomic<std::uint64_t> g_stack_resets{0};

        // Per-thread capture of the fault being handled. Plain POD in static
        // TLS: no constructor, no heap, valid inside the filter.
        struct Capture
        {
            std::uint32_t code;
            std::uint32_t av_op;
            std::uint64_t address;
            std::uint64_t av_target;
            std::uint64_t module_base;
            std::uint64_t sequence;
            std::uint8_t module_kind;
            bool has_av;
            bool pending_stack_overflow;
            const char* action;
        };
        thread_local Capture t_capture;

        constexpr const char* kModuleKinds[] = {"none", "game", "self", "ue4ss", "other"};

        // ---- Heap-free, CRT-free line formatting ------------------------------
        struct Line
        {
            char text[640];
            std::size_t length;

            void put(const char* value)
            {
                for (std::size_t i = 0; value && value[i] && length + 3 < sizeof(text); ++i)
                {
                    const char c = value[i];
                    text[length++] = (c > 0x20 && c < 0x7F) ? c : '_';
                }
            }
            void key(const char* name)
            {
                if (length && length + 1 < sizeof(text)) text[length++] = ' ';
                put(name);
                if (length + 3 < sizeof(text)) text[length++] = '=';
            }
            void dec(std::uint64_t value)
            {
                char digits[24];
                std::size_t n = 0;
                do
                {
                    digits[n++] = static_cast<char>('0' + value % 10);
                    value /= 10;
                } while (value && n < sizeof(digits));
                while (n && length + 3 < sizeof(text)) text[length++] = digits[--n];
            }
            void hex(std::uint64_t value, int width)
            {
                static constexpr char kHex[] = "0123456789ABCDEF";
                if (length + 3 < sizeof(text)) text[length++] = '0';
                if (length + 3 < sizeof(text)) text[length++] = 'x';
                for (int shift = (width - 1) * 4; shift >= 0; shift -= 4)
                {
                    if (length + 3 < sizeof(text)) text[length++] = kHex[(value >> shift) & 0xF];
                }
            }
            void end()
            {
                text[length++] = '\r';
                text[length++] = '\n';
            }
        };

        std::uint64_t unix_ms()
        {
            FILETIME file_time{};
            GetSystemTimeAsFileTime(&file_time);
            ULARGE_INTEGER ticks{};
            ticks.LowPart = file_time.dwLowDateTime;
            ticks.HighPart = file_time.dwHighDateTime;
            constexpr std::uint64_t kEpoch = 116444736000000000ULL;
            return ticks.QuadPart >= kEpoch ? (ticks.QuadPart - kEpoch) / 10'000ULL : 0;
        }

        void header(Line& line, const char* event)
        {
            line.length = 0;
            line.key("event");
            line.put(event);
            line.key("utc_ms");
            line.dec(unix_ms());
            line.key("pid");
            line.dec(GetCurrentProcessId());
            line.key("tid");
            line.dec(GetCurrentThreadId());
            line.key("native");
            line.put(g_native_name);
            line.key("native_version");
            line.put(g_native_version);
            line.key("sbcore");
            line.put(kVersion);
        }

        // One WriteFile on a FILE_APPEND_DATA handle opened at init: no heap,
        // no path parsing, atomic append on local NTFS.
        void write_line(Line& line)
        {
            line.end();
            const HANDLE file = g_log_file;
            if (file == INVALID_HANDLE_VALUE)
            {
                g_log_failures.fetch_add(1, std::memory_order_relaxed);
                return;
            }
            LARGE_INTEGER size{};
            if (GetFileSizeEx(file, &size) && static_cast<std::uint64_t>(size.QuadPart) + line.length > g_log_cap)
            {
                g_log_dropped.fetch_add(1, std::memory_order_relaxed);
                return;
            }
            DWORD written = 0;
            if (WriteFile(file, line.text, static_cast<DWORD>(line.length), &written, nullptr) && written == line.length)
            {
                g_log_lines.fetch_add(1, std::memory_order_relaxed);
            }
            else
            {
                g_log_failures.fetch_add(1, std::memory_order_relaxed);
            }
        }

        std::uint8_t classify(std::uint64_t address, std::uint64_t& base_out)
        {
            PVOID base = nullptr;
            RtlPcToFileHeader(reinterpret_cast<PVOID>(address), &base);
            base_out = reinterpret_cast<std::uint64_t>(base);
            if (!base) return 0;
            if (base_out == g_self_base) return 2; // first: in tests self is also the process image
            if (base_out == g_exe_base) return 1;
            if (g_ue4ss_base && base_out == g_ue4ss_base) return 3;
            return 4;
        }

        void set_latches()
        {
            g_local_faulted.store(true, std::memory_order_release);
            if (g_latch_event) SetEvent(g_latch_event);
        }

        void publish_capture(const Capture& capture)
        {
            g_last_code.store(capture.code, std::memory_order_relaxed);
            g_last_address.store(capture.address, std::memory_order_relaxed);
            g_last_module_base.store(capture.module_base, std::memory_order_relaxed);
            g_last_module_kind.store(capture.module_kind, std::memory_order_relaxed);
            g_last_action.store(capture.action, std::memory_order_release);
        }

        void write_fault_line(const Capture& capture)
        {
            Line line;
            header(line, capture.code == 0 ? "taint" : "fault");
            line.key("n");
            line.dec(capture.sequence);
            line.key("action");
            line.put(capture.action ? capture.action : "unknown");
            line.key("code");
            line.hex(capture.code, 8);
            line.key("address");
            line.hex(capture.address, 16);
            line.key("module");
            line.put(kModuleKinds[capture.module_kind < 5 ? capture.module_kind : 0]);
            line.key("module_base");
            line.hex(capture.module_base, 16);
            line.key("offset");
            line.hex(capture.module_base ? capture.address - capture.module_base : 0, 8);
            line.key("av_op");
            line.put(!capture.has_av ? "-" : capture.av_op == 0 ? "read" : capture.av_op == 1 ? "write" : capture.av_op == 8 ? "execute" : "other");
            line.key("av_target");
            line.hex(capture.has_av ? capture.av_target : 0, 16);
            line.key("policy");
            line.put(policy_name(static_cast<Policy>(g_policy.load(std::memory_order_relaxed))));
            write_line(line);
        }

        void copy_ascii(char* destination, std::size_t capacity, const char* source)
        {
            std::size_t i = 0;
            for (; source && source[i] && i + 1 < capacity; ++i)
            {
                const char c = source[i];
                destination[i] = (c > 0x20 && c < 0x7F) ? c : '_';
            }
            if (i == 0 && capacity > 7)
            {
                std::memcpy(destination, "unknown", 8);
                return;
            }
            destination[i] = '\0';
        }

        std::uintptr_t module_base_of(const void* address)
        {
            HMODULE module = nullptr;
            GetModuleHandleExW(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS | GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,
                               static_cast<LPCWSTR>(address), &module);
            return reinterpret_cast<std::uintptr_t>(module);
        }

        void latch_name(wchar_t* buffer, std::size_t capacity)
        {
            // Local\SBCore.Tainted.<pid>
            static constexpr wchar_t kPrefix[] = L"Local\\SBCore.Tainted.";
            std::size_t n = 0;
            for (; kPrefix[n] && n + 1 < capacity; ++n) buffer[n] = kPrefix[n];
            wchar_t digits[16];
            std::size_t d = 0;
            DWORD pid = GetCurrentProcessId();
            do
            {
                digits[d++] = static_cast<wchar_t>(L'0' + pid % 10);
                pid /= 10;
            } while (pid && d < 16);
            while (d && n + 1 < capacity) buffer[n++] = digits[--d];
            buffer[n] = L'\0';
        }
    }

    bool init(const Config& config)
    {
        if (g_initialized.load(std::memory_order_acquire)) return true;
        copy_ascii(g_native_name, sizeof(g_native_name), config.native_name);
        copy_ascii(g_native_version, sizeof(g_native_version), config.native_version);
        g_log_cap = config.log_cap_bytes;
        g_policy.store(static_cast<std::uint8_t>(config.policy), std::memory_order_relaxed);
        g_exe_base = reinterpret_cast<std::uintptr_t>(GetModuleHandleW(nullptr));
        g_self_base = module_base_of(reinterpret_cast<const void*>(&init));
        g_ue4ss_base = reinterpret_cast<std::uintptr_t>(GetModuleHandleW(L"UE4SS.dll"));

        wchar_t name[64];
        latch_name(name, 64);
        g_latch_event = CreateEventW(nullptr, TRUE, FALSE, name);
        g_latch_available.store(g_latch_event != nullptr, std::memory_order_release);

        if (!config.log_path.empty())
        {
            const HANDLE file = CreateFileW(config.log_path.c_str(), FILE_APPEND_DATA | FILE_READ_ATTRIBUTES,
                                            FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE, nullptr, OPEN_ALWAYS,
                                            FILE_ATTRIBUTE_NORMAL | FILE_FLAG_OPEN_REPARSE_POINT, nullptr);
            BY_HANDLE_FILE_INFORMATION information{};
            if (file != INVALID_HANDLE_VALUE && GetFileInformationByHandle(file, &information)
                && (information.dwFileAttributes & (FILE_ATTRIBUTE_DIRECTORY | FILE_ATTRIBUTE_REPARSE_POINT)) == 0
                && information.nNumberOfLinks == 1)
            {
                g_log_file = file;
            }
            else
            {
                if (file != INVALID_HANDLE_VALUE) CloseHandle(file);
                g_log_failures.fetch_add(1, std::memory_order_relaxed);
            }
        }

        if (!g_latch_event) return false; // fail closed: g_initialized stays false
        g_initialized.store(true, std::memory_order_release);

        if (config.write_session_line && g_log_file != INVALID_HANDLE_VALUE)
        {
            Line line;
            header(line, "session_start");
            line.key("policy");
            line.put(policy_name(config.policy));
            line.key("exe_base");
            line.hex(g_exe_base, 16);
            line.key("self_base");
            line.hex(g_self_base, 16);
            line.key("process_tainted");
            line.dec(WaitForSingleObject(g_latch_event, 0) == WAIT_OBJECT_0 ? 1 : 0);
            write_line(line);
        }
        return true;
    }

    bool initialized()
    {
        return g_initialized.load(std::memory_order_acquire);
    }

    bool writes_blocked_fast()
    {
        return !g_initialized.load(std::memory_order_acquire)
            || g_local_faulted.load(std::memory_order_acquire)
            || g_process_seen.load(std::memory_order_acquire);
    }

    bool refresh_process_latch()
    {
        if (g_process_seen.load(std::memory_order_acquire)) return true;
        const HANDLE event = g_latch_event;
        if (!event) return false;
        const DWORD wait = WaitForSingleObject(event, 0);
        if (wait == WAIT_OBJECT_0 || wait == WAIT_FAILED)
        {
            g_process_seen.store(true, std::memory_order_release);
            return true;
        }
        return false;
    }

    bool writes_blocked()
    {
        if (writes_blocked_fast()) return true;
        return refresh_process_latch();
    }

    bool local_faulted()
    {
        return g_local_faulted.load(std::memory_order_acquire);
    }

    bool process_tainted()
    {
        return refresh_process_latch();
    }

    void taint(const char* action)
    {
        Capture capture{};
        capture.action = action ? action : "taint";
        capture.sequence = g_fault_count.fetch_add(1, std::memory_order_acq_rel) + 1;
        set_latches();
        publish_capture(capture);
        write_fault_line(capture);
    }

    int filter(_EXCEPTION_POINTERS* pointers, const char* action)
    {
        const auto policy = static_cast<Policy>(g_policy.load(std::memory_order_relaxed));
        const int disposition = policy == Policy::CrashToReporter ? EXCEPTION_CONTINUE_SEARCH : EXCEPTION_EXECUTE_HANDLER;
        Capture& capture = t_capture;
        capture = Capture{};
        capture.action = action ? action : "unknown";
        const EXCEPTION_RECORD* record = pointers ? pointers->ExceptionRecord : nullptr;
        if (record)
        {
            capture.code = record->ExceptionCode;
            capture.address = reinterpret_cast<std::uint64_t>(record->ExceptionAddress);
            if ((record->ExceptionCode == EXCEPTION_ACCESS_VIOLATION || record->ExceptionCode == EXCEPTION_IN_PAGE_ERROR)
                && record->NumberParameters >= 2)
            {
                capture.has_av = true;
                capture.av_op = static_cast<std::uint32_t>(record->ExceptionInformation[0]);
                capture.av_target = record->ExceptionInformation[1];
            }
        }
        capture.sequence = g_fault_count.fetch_add(1, std::memory_order_acq_rel) + 1;
        set_latches();
        if (capture.code == static_cast<std::uint32_t>(STATUS_STACK_OVERFLOW))
        {
            // The filter runs on the exhausted stack: record only. The line is
            // written by after_handler() once the stack has been unwound.
            capture.module_kind = 0;
            capture.pending_stack_overflow = policy == Policy::ContinueFeatureOff;
            publish_capture(capture);
            return disposition;
        }
        capture.module_kind = classify(capture.address, capture.module_base);
        publish_capture(capture);
        write_fault_line(capture);
        return disposition;
    }

    void after_handler()
    {
        Capture& capture = t_capture;
        if (!capture.pending_stack_overflow) return;
        capture.pending_stack_overflow = false;
        capture.module_kind = classify(capture.address, capture.module_base);
        publish_capture(capture);
        write_fault_line(capture);
        if (_resetstkoflw()) g_stack_resets.fetch_add(1, std::memory_order_relaxed);
    }

    bool guarded_call(GuardedFn fn, void* context, const char* action)
    {
        if (!fn) return false;
        bool returned = false;
        __try
        {
            fn(context);
            returned = true;
        }
        __except (filter(GetExceptionInformation(), action))
        {
            returned = false;
        }
        if (!returned) after_handler();
        return returned;
    }

    Snapshot snapshot()
    {
        Snapshot s;
        s.initialized = g_initialized.load(std::memory_order_acquire);
        s.latch_available = g_latch_available.load(std::memory_order_acquire);
        s.local_faulted = g_local_faulted.load(std::memory_order_acquire);
        s.process_tainted = g_process_seen.load(std::memory_order_acquire)
            || (g_latch_event && WaitForSingleObject(g_latch_event, 0) == WAIT_OBJECT_0);
        s.fault_count = g_fault_count.load(std::memory_order_acquire);
        s.last_code = g_last_code.load(std::memory_order_relaxed);
        s.last_address = g_last_address.load(std::memory_order_relaxed);
        s.last_module_base = g_last_module_base.load(std::memory_order_relaxed);
        const auto kind = g_last_module_kind.load(std::memory_order_relaxed);
        copy_ascii(s.last_module_kind, sizeof(s.last_module_kind), kModuleKinds[kind < 5 ? kind : 0]);
        const char* action = g_last_action.load(std::memory_order_acquire);
        copy_ascii(s.last_action, sizeof(s.last_action), action ? action : "none");
        s.log_lines = g_log_lines.load(std::memory_order_relaxed);
        s.log_failures = g_log_failures.load(std::memory_order_relaxed);
        s.log_dropped = g_log_dropped.load(std::memory_order_relaxed);
        s.stack_overflows_reset = g_stack_resets.load(std::memory_order_relaxed);
        s.policy = static_cast<Policy>(g_policy.load(std::memory_order_relaxed));
        return s;
    }

    const char* policy_name(Policy policy)
    {
        switch (policy)
        {
        case Policy::ContinueFeatureOff: return "continue_feature_off";
        case Policy::CrashToReporter: return "crash_to_reporter";
        }
        return "unknown";
    }

#if defined(SBCORE_TESTING)
    namespace testing
    {
        std::wstring latch_name()
        {
            wchar_t name[64];
            fault::latch_name(name, 64);
            return name;
        }
    }
#endif
}
