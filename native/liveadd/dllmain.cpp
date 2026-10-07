// The UE4SS base class comes from sbcore's shim (A1): the 11-slot
// CppUserModBase of the UE4SS.dll the game loads (RE-UE4SS d3d10044d1). The
// build fails unless its virtual order matches that DLL.
#include <Mod/CppUserModBase.hpp>

#include <cstdio>

#include "live_add.hpp"

using namespace RC;

class SBLiveAddNativeMod : public CppUserModBase
{
  public:
    SBLiveAddNativeMod()
    {
        ModName = L"SBLiveAddNative";
        ModVersion = L"0.5.1";
        ModDescription = L"Explicit one-shot, GameThread-only Live Add using Stellar Blade's authoritative item-bucket request";
        ModAuthors = L"SBCheatGUI";
    }

    ~SBLiveAddNativeMod() override
    {
        sbliveadd::shutdown();
    }

    auto on_unreal_init() -> void override
    {
        const bool ready = sbliveadd::install();
        printf(
            "[SBLiveAddNative] v0.5.1 (sbcore 0.1.0, protocol native-live-add-v4) initialize=%s; GameThread-only=1 "
            "hooks=0 first-use-self-check=1 carry-limit-check=1 generated-allowlist=1 per-group-limits=1 "
            "side-effect-watch=1 read-only-probe=1 auto-level-refusal=1 per-unit-guard=1 lease-driven-refresh=1 fault-log=1 UObject-APIs=0 "
            "direct-inventory-writes=0 direct-wallet-writes=0 save-writes=0.\n",
            ready ? "ready" : "refused");
    }

    auto on_update() -> void override
    {
        sbliveadd::on_update();
    }
};

#define SB_LIVE_ADD_API __declspec(dllexport)
extern "C"
{
    SB_LIVE_ADD_API CppUserModBase* start_mod()
    {
        if (!sbliveadd::verify_ue4ss_runtime())
        {
            printf("[SBLiveAddNative] Refused: UE4SS runtime identity mismatch.\n");
            return nullptr;
        }
        return new SBLiveAddNativeMod();
    }

    SB_LIVE_ADD_API void uninstall_mod(CppUserModBase* mod)
    {
        delete mod;
    }
}
