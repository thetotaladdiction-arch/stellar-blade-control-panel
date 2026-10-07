#include <cstdio>

// sbcore's shim: the CppUserModBase ABI of the UE4SS.dll the game loads
// (fork d3d10044d1, 11 virtual slots, on_ui_init at slot 3). The build fails
// if its virtual order ever differs from that runtime (plan A1).
#include <Mod/CppUserModBase.hpp>

#include "sbcore/version.hpp"

#include "retry_point.hpp"

using namespace RC;

class SBRetryPointNativeMod : public CppUserModBase
{
  public:
    SBRetryPointNativeMod()
    {
        ModName = L"SBRetryPointNative";
        ModVersion = L"0.2.3";
        ModDescription = L"Explicit one-shot, GameThread-only Retry Point using Stellar Blade's warp request";
        ModAuthors = L"SBCheatGUI";
    }

    ~SBRetryPointNativeMod() override
    {
        sbretrypoint::shutdown();
    }

    auto on_unreal_init() -> void override
    {
        const bool ready = sbretrypoint::install();
        std::printf(
            "[SBRetryPointNative] v0.2.3 initialize=%s; GameThread-only=1 hooks=0 "
            "background-UObject-reads=0 direct-location-writes=0 save-writes=0 sbcore=%s.\n",
            ready ? "ready" : "refused", sbcore::kVersion);
    }

    auto on_update() -> void override
    {
        sbretrypoint::on_update();
    }
};

#define SB_RETRY_POINT_API __declspec(dllexport)
extern "C"
{
    SB_RETRY_POINT_API CppUserModBase* start_mod()
    {
        return new SBRetryPointNativeMod();
    }

    SB_RETRY_POINT_API void uninstall_mod(CppUserModBase* mod)
    {
        delete mod;
    }
}
