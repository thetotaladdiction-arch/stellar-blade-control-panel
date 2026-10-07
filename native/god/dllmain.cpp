// <Mod/CppUserModBase.hpp> resolves to sbcore's shim (shim_include/): the
// CppUserModBase ABI of the UE4SS.dll the game loads (RE-UE4SS d3d10044d1,
// 11 virtual slots, on_ui_init at slot 3). sbcore's build fails if that
// shim's virtual order ever differs from the runtime's (plan A1).
#include <Mod/CppUserModBase.hpp>

#include <cstdio>

#include "god_hook.hpp"

using namespace RC;

class SBGodNativeMod : public CppUserModBase
{
  public:
    SBGodNativeMod()
    {
        ModName = L"SBGodNative";
        ModVersion = L"" SBGOD_VERSION_STRING; // v1.3.2: from god_hook.hpp (was a stale L"1.3.0")
        ModDescription = L"Native god mode - exact-build validated hooks, verified player identity, GameThread TaskGraph (sbcore)";
        ModAuthors = L"SBCheatGUI";
    }

    ~SBGodNativeMod() override
    {
        // Disarms only. The module is pinned and the hooks stay installed in
        // pass-through mode; live game code is never rewritten on unload.
        sbgod::uninstall();
    }

    auto on_unreal_init() -> void override
    {
        if (sbgod::install())
        {
            printf("[SBGodNative] v%s hooks installed (exact build 6A6A3B74/15981000, sbcore gate passed, all sites validated)\n",
                   sbgod::kVersion);
        }
        else
        {
            printf("[SBGodNative] v%s NOT installed (fail closed): %s\n", sbgod::kVersion, sbgod::install_error());
        }
    }

    auto on_update() -> void override
    {
        sbgod::on_update();
    }
};

#define SBGOD_NATIVE_API __declspec(dllexport)
extern "C"
{
    SBGOD_NATIVE_API CppUserModBase* start_mod()
    {
        return new SBGodNativeMod();
    }

    SBGOD_NATIVE_API void uninstall_mod(CppUserModBase* mod)
    {
        delete mod;
    }
}
