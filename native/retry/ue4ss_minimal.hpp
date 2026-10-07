#pragma once

#include <string>
#include <vector>

// Minimal UE4SS import surface (the UE4SS.dll the game loads: RE-UE4SS fork
// d3d10044d1; ue4ss/UE4SS.def lists every import and a test checks each one
// against that DLL's exports). This module invokes one reflected game action
// only after an explicit file command reaches the certified GameThread; it
// does not register ProcessEvent/UFunction hooks.
//
// The offline harness defines SBRETRYPOINT_UE4SS_API as empty and supplies a
// fake UObject graph instead of UE4SS.dll.
#if !defined(SBRETRYPOINT_UE4SS_API)
#define SBRETRYPOINT_UE4SS_API __declspec(dllimport)
#endif

namespace RC::Unreal
{
    class UFunction;

    class UObject
    {
      public:
        SBRETRYPOINT_UE4SS_API void* GetValuePtrByPropertyNameInChain(const wchar_t* property_name);
        SBRETRYPOINT_UE4SS_API std::wstring GetFullName(UObject* stop_outer = nullptr) const;
        SBRETRYPOINT_UE4SS_API UFunction* GetFunctionByNameInChain(const wchar_t* name);
        SBRETRYPOINT_UE4SS_API void ProcessEvent(UFunction* function, void* params);
    };

    class UFunction : public UObject
    {
    };

    namespace UObjectGlobals
    {
        SBRETRYPOINT_UE4SS_API void FindAllOf(
            const wchar_t* class_name,
            std::vector<UObject*>& objects);
    }
}
