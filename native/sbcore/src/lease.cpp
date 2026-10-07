#include "sbcore/lease.hpp"

#include <windows.h>

namespace sbcore::lease
{
    std::uint64_t unix_time_ms()
    {
        FILETIME file_time{};
        GetSystemTimeAsFileTime(&file_time);
        ULARGE_INTEGER ticks{};
        ticks.LowPart = file_time.dwLowDateTime;
        ticks.HighPart = file_time.dwHighDateTime;
        constexpr std::uint64_t kWindowsToUnixTicks = 116444736000000000ULL;
        return ticks.QuadPart >= kWindowsToUnixTicks ? (ticks.QuadPart - kWindowsToUnixTicks) / 10'000ULL : 0;
    }

    bool process_alive(std::uint32_t pid)
    {
        if (pid == 0) return false;
        HANDLE process = OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION | SYNCHRONIZE, FALSE, pid);
        if (!process) return false;
        DWORD exit_code = 0;
        const bool alive = GetExitCodeProcess(process, &exit_code) && exit_code == STILL_ACTIVE;
        CloseHandle(process);
        return alive;
    }

    Evaluation evaluate(std::uint32_t panel_pid, std::uint64_t issued_ms, std::uint64_t now_ms,
                        std::uint64_t lease_ms, std::uint64_t future_tolerance_ms, bool check_process)
    {
        Evaluation result;
        if (panel_pid == 0 || issued_ms == 0)
        {
            result.state = State::Invalid;
            return result;
        }
        result.age_ms = now_ms >= issued_ms ? now_ms - issued_ms : 0;
        if (issued_ms > now_ms && issued_ms - now_ms > future_tolerance_ms)
        {
            result.state = State::Future;
            return result;
        }
        if (result.age_ms > lease_ms)
        {
            result.state = State::Stale;
            return result;
        }
        if (check_process && !process_alive(panel_pid))
        {
            result.state = State::PanelGone;
            return result;
        }
        result.state = State::Fresh;
        return result;
    }

    const char* state_name(State state)
    {
        switch (state)
        {
        case State::Fresh: return "fresh";
        case State::Invalid: return "invalid";
        case State::Future: return "future";
        case State::Stale: return "stale";
        case State::PanelGone: return "panel_gone";
        }
        return "unknown";
    }
}
