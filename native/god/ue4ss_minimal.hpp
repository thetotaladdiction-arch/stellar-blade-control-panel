#pragma once

#include <string>
#include <vector>

// Minimal declarations for the three ABI-stable UObject exports God uses. The
// loaded UE4SS.dll (RE-UE4SS fork d3d10044d1) exports all three; the import
// library is sbcore's (ue4ss/UE4SS.def), whose live-DLL test checks every
// import against that DLL. Keeping this surface tiny avoids coupling the mod
// to private Unreal Engine headers. The offline worker module defines
// SBGOD_UE4SS_IMPORT as empty and links local stubs.
#ifndef SBGOD_UE4SS_IMPORT
#define SBGOD_UE4SS_IMPORT __declspec(dllimport)
#endif

namespace RC::Unreal
{
    class UObject
    {
      public:
        SBGOD_UE4SS_IMPORT void* GetValuePtrByPropertyNameInChain(const wchar_t* property_name);
        SBGOD_UE4SS_IMPORT std::wstring GetFullName(UObject* stop_outer = nullptr) const;
    };

    namespace UObjectGlobals
    {
        SBGOD_UE4SS_IMPORT void FindAllOf(const wchar_t* class_name, std::vector<UObject*>& objects);
    }
}
