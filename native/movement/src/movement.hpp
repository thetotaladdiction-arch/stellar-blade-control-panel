#pragma once

namespace sbmove
{
    // One version string for the UE4SS ModVersion, the heartbeat, the fault
    // log and the console line.
    inline constexpr char kVersion[] = "1.4.1";
    inline constexpr wchar_t kVersionW[] = L"1.4.1";
    inline constexpr char kModName[] = "SBMovementNative";

    // Called once when Unreal is ready. Returns true when the native armed:
    // module paths resolved, fault latch initialised, module pinned, the
    // sbcore exact-build gate passed and the GameThread dispatcher bound.
    bool install();

    // Called on UE4SS's worker tick. It performs file I/O and submits the
    // certified GameThread task; it never reads or writes Unreal objects.
    void on_update();

    // Called on unload. It never touches Unreal state from the worker thread.
    void uninstall();

    // Name of the first install step that failed ("none" once armed).
    const char* install_failed_step();
} // namespace sbmove
