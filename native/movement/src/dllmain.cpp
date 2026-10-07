#include <cstdio>

#include <Mod/CppUserModBase.hpp>

#include "movement.hpp"

using namespace RC;

// The base class comes from sbcore's shim (shim_include/Mod/CppUserModBase.hpp):
// the 11-slot CppUserModBase of the UE4SS.dll the game loads (fork d3d10044d1,
// on_ui_init at slot 3). sbcore's build fails if that order ever differs.
class SBMovementNativeMod : public CppUserModBase
{
  public:
    SBMovementNativeMod()
    {
        ModName = L"SBMovementNative";
        ModVersion = sbmove::kVersionW;
        ModDescription = L"Event-driven GameThread movement, jump, and one-shot FOV - no hooks";
        ModAuthors = L"SBCheatGUI";
    }

    ~SBMovementNativeMod() override
    {
        // Stops dispatch and writes a final heartbeat. It never touches Unreal
        // state from the unload path: runtime disable and lease expiry restore
        // owned values in the GameThread task, and process teardown discards
        // the rest. A UE4SS hot reload then calls on_unreal_init on a new
        // instance, which re-arms (sbmove::install).
        sbmove::uninstall();
    }

    auto on_unreal_init() -> void override
    {
        if (sbmove::install())
        {
            std::printf("[SBMovementNative] v%s ready (fully event-driven TaskGraph GameThread, extended FOV range, no hooks, sbcore)\n",
                        sbmove::kVersion);
        }
        else
        {
            std::printf("[SBMovementNative] v%s NOT armed (failed step: %s); movement stays off\n", sbmove::kVersion,
                        sbmove::install_failed_step());
        }
    }

    auto on_update() -> void override
    {
        sbmove::on_update();
    }
};

#define SBMOVE_NATIVE_API __declspec(dllexport)
extern "C"
{
    SBMOVE_NATIVE_API CppUserModBase* start_mod()
    {
        return new SBMovementNativeMod();
    }

    SBMOVE_NATIVE_API void uninstall_mod(CppUserModBase* mod)
    {
        delete mod;
    }
}
