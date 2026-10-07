#pragma once

#include <string>
#include <vector>

// Minimal declarations for the ABI-stable UE4SS UObject exports used here.
// They are imported through sbcore's ue4ss/UE4SS.def (the same mangled names
// 1.3.6 imported). Keeping this surface tiny avoids coupling the mod to
// private Unreal Engine headers. Every call happens on the certified
// GameThread only.
namespace RC::Unreal
{
    class UObject
    {
      public:
        __declspec(dllimport) void* GetValuePtrByPropertyNameInChain(const wchar_t* property_name);
        __declspec(dllimport) std::wstring GetFullName(UObject* stop_outer = nullptr) const;
    };

    namespace UObjectGlobals
    {
        __declspec(dllimport) void FindAllOf(const wchar_t* class_name, std::vector<UObject*>& objects);
    }
}
