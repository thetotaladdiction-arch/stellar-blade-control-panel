#pragma once

// Panel lease helpers (lifted from SBMovementNative 1.3.6). A native acts on a
// panel request only while the request is fresh and the panel process that
// wrote it is alive. Used for lease-driven GameThread work (A13).

#include <cstdint>

namespace sbcore::lease
{
    // Milliseconds since the Unix epoch (GetSystemTimeAsFileTime).
    std::uint64_t unix_time_ms();

    // OpenProcess(QUERY_LIMITED_INFORMATION) + GetExitCodeProcess == STILL_ACTIVE.
    bool process_alive(std::uint32_t pid);

    enum class State : std::uint8_t
    {
        Fresh = 0,
        Invalid,   // pid 0 or issued_ms 0
        Future,    // issued more than future_tolerance_ms in the future
        Stale,     // older than lease_ms
        PanelGone, // the issuing process is not alive
    };

    struct Evaluation
    {
        State state = State::Invalid;
        std::uint64_t age_ms = 0;
    };

    Evaluation evaluate(std::uint32_t panel_pid, std::uint64_t issued_ms, std::uint64_t now_ms,
                        std::uint64_t lease_ms, std::uint64_t future_tolerance_ms, bool check_process = true);

    const char* state_name(State state);
}
