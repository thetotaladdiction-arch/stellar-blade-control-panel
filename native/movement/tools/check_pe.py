#!/usr/bin/env python3
"""PE checks for the SBMovementNative DLLs (plan A8 preset, A1 imports, P1).

Usage: check_pe.py --kind production|testable --def UE4SS.def DLL

Fails (exit 1) unless:
  * AMD64, DYNAMIC_BASE, HIGH_ENTROPY_VA, NX_COMPAT and GUARD_CF are set and
    the load config says CF_INSTRUMENTED;
  * the CRT is the shared one (/MD): MSVCP140.dll and VCRUNTIME140.dll are
    imported (1.3.6 linked the static CRT and passed std::wstring across the
    UE4SS boundary);
  * UE4SS.dll imports are a subset of sbcore's ue4ss/UE4SS.def and include the
    CppUserModBase constructor and destructor;
  * every imported DLL is on the allow-list below;
  * the exports are exactly start_mod and uninstall_mod (production) or those
    plus the two sbmove_testing_* hooks (testable): the offline hooks can never
    reach a staged DLL;
  * the file contains no "SteamLibrary" (ASCII or UTF-16LE).
Exit 2 = unreadable input.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pefile

ALLOWED_DLLS = {
    "ue4ss.dll",
    "kernel32.dll",
    "bcrypt.dll",
    "msvcp140.dll",
    "vcruntime140.dll",
    "vcruntime140_1.dll",
}
ALLOWED_DLL_PREFIXES = ("api-ms-win-crt-",)
PRODUCTION_EXPORTS = {"start_mod", "uninstall_mod"}
TESTABLE_EXPORTS = PRODUCTION_EXPORTS | {"sbmove_testing_set_fake_image", "sbmove_testing_set_clock"}
CTOR = "??0CppUserModBase@RC@@QEAA@XZ"
DTOR = "??1CppUserModBase@RC@@UEAA@XZ"


def read_def(path: Path) -> set[str]:
    names = set()
    in_exports = False
    for raw in path.read_text(encoding="ascii").splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.upper() == "EXPORTS":
            in_exports = True
            continue
        if in_exports:
            names.add(line.split()[0])
    return names


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--kind", choices=("production", "testable"), required=True)
    parser.add_argument("--def", dest="def_path", type=Path, required=True)
    parser.add_argument("dll", type=Path)
    args = parser.parse_args()
    try:
        blob = args.dll.read_bytes()
        def_names = read_def(args.def_path)
        pe = pefile.PE(data=blob)
    except (OSError, pefile.PEFormatError) as error:
        print(f"UNREADABLE: {error}")
        return 2

    failures: list[str] = []

    def check(condition: bool, what: str) -> None:
        print(("PASS " if condition else "FAIL ") + what)
        if not condition:
            failures.append(what)

    check(pe.FILE_HEADER.Machine == 0x8664, "machine AMD64")
    characteristics = pe.OPTIONAL_HEADER.DllCharacteristics
    for bit, name in ((0x20, "HIGH_ENTROPY_VA"), (0x40, "DYNAMIC_BASE"), (0x100, "NX_COMPAT"), (0x4000, "GUARD_CF")):
        check(bool(characteristics & bit), f"DllCharacteristics {name}")
    guard_flags = None
    if hasattr(pe, "DIRECTORY_ENTRY_LOAD_CONFIG"):
        guard_flags = getattr(pe.DIRECTORY_ENTRY_LOAD_CONFIG.struct, "GuardFlags", None)
    check(guard_flags is not None and bool(guard_flags & 0x100), f"load config GuardFlags CF_INSTRUMENTED ({guard_flags!r})")

    imports: dict[str, set[str]] = {}
    for entry in getattr(pe, "DIRECTORY_ENTRY_IMPORT", []):
        dll = entry.dll.decode("ascii").lower()
        imports[dll] = {imp.name.decode("ascii") for imp in entry.imports if imp.name}
    print("imports: " + ", ".join(sorted(imports)))
    check("msvcp140.dll" in imports and "vcruntime140.dll" in imports, "shared CRT (/MD): MSVCP140 + VCRUNTIME140 imported")
    unexpected = [dll for dll in imports if dll not in ALLOWED_DLLS and not dll.startswith(ALLOWED_DLL_PREFIXES)]
    check(not unexpected, f"only allow-listed DLLs imported (unexpected: {unexpected})")
    ue4ss = imports.get("ue4ss.dll", set())
    for name in sorted(ue4ss):
        print(f"  UE4SS.dll!{name}")
    check(bool(ue4ss) and ue4ss <= def_names, "UE4SS.dll imports are a subset of sbcore ue4ss/UE4SS.def")
    check(CTOR in ue4ss and DTOR in ue4ss, "CppUserModBase ctor and dtor imported from UE4SS.dll")

    exports = set()
    if hasattr(pe, "DIRECTORY_ENTRY_EXPORT"):
        exports = {symbol.name.decode("ascii") for symbol in pe.DIRECTORY_ENTRY_EXPORT.symbols if symbol.name}
    expected = PRODUCTION_EXPORTS if args.kind == "production" else TESTABLE_EXPORTS
    check(exports == expected, f"exports == {sorted(expected)} (got {sorted(exports)})")

    lowered = blob.lower()
    for encoding in ("ascii", "utf-16-le"):
        check(lowered.find("steamlibrary".encode(encoding)) < 0, f"no 'SteamLibrary' ({encoding})")

    print(("OK " if not failures else "FAILED ") + f"{args.dll} ({args.kind}, {len(blob)} bytes)")
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
