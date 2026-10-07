# Stellar Blade Mod Suite 2.6.11: source supplied for Nexus upload 17076

This is a support source snapshot of the custom Python/QML panel, four custom native DLLs, shared native core, and Lua mods. It excludes repository history, tests, logs, player data, settings, authentication material and executable binaries. Nexus already has the uploaded release ZIP. SHIPPED-BINARY-MAPPING.json identifies those exact binaries.

## Source provenance and limitations

Public source-review snapshot URL: https://github.com/thetotaladdiction-arch/stellar-blade-control-panel/tree/v2.6.11

This snapshot retains the existing repository Source Review LICENSE unchanged. The original public main branch and older releases are separate historical snapshots. 

The panel snapshot is the build 273, public version2.6.11. God 1.3.5 production source selection was verified against frozen manifest E88A9AFD4770F43F18D5C8ECEDF16F974B7DCEFCF8CBC3409C4318ECB3BE21A3; support comment redactions are disclosed below. LiveAdd 0.5.1, Movement 1.4.1, RetryPoint 0.2.3 and sbcore 0.1.0 production provenance was verified before selection. SOURCE-MANIFEST.json records supplied relative file paths and SHA256. The private original/support comparison audit remains outside this source snapshot. Comments and documentation strings were neutralized in support copies. Operational AST and compiled co_code/callables were compared with __doc__ constants normalized; documentation and line metadata may differ. Runtime logic is preserved. This packet has not been compiled. Comments, line metadata, packaging paths/toolchains and standalone build recipes can change resulting binary hashes. It is a code-review/rebuild source snapshot, not a claim of bit-identical reproduction.

Public upstream UE4SS fork: https://github.com/Chrisr0/RE-UE4SS
The ABI headers used by these natives are pinned to https://github.com/UE4SS-RE/RE-UE4SS/commit/d3d10044d12566b869de56164bdaf5dbf36067b8 (recorded loaded runtime short SHA d3d1004). The MIT license and pinned headers are supplied under native/sbcore/third_party/RE-UE4SS. This snapshot uses its small ABI shim and exact import definitions; it does not redistribute the UE4SS binary. Native methods intentionally require the particular supported game/runtime identity and may refuse other versions.

## Native build

Recorded original native toolchain: MSVC x64 compiler 19.51.36248, VC Tools 14.51.36231, Windows SDK 10.0.26100.0, CMake 4.3.1-msvc1, Ninja 1.13.2, Python 3.14.6. Run from an x64 Native Tools command prompt, with Python/CMake/Ninja on PATH:

```powershell
cmake -S native -B build-native -G Ninja -DCMAKE_BUILD_TYPE=Release -DCMAKE_CXX_COMPILER=cl
cmake --build build-native --parallel 2 --target SBGodNative SBLiveAddNative SBMovementNative SBRetryPointNative
```

The new native/CMakeLists.txt is a documented portable production-target wrapper. It links the supplied shared core, retains the original hardening preset and import definitions, and runs sbcore's ABI-order/hardcoded-path build checks. It omits offline test targets and original checkout-specific Git metadata checks. Original per-native CMake recipes are also provided for inspection; God’s original recipe references excluded test sources, and Movement/Retry recipes require a clean sbcore Git checkout at 7a81ea67361ae989b08339056a2ce3b74018cb39. Original per-target recipes require their original Git checkout; use the portable wrapper for this snapshot. RetryPoint’s original byte-reproducibility evidence was specific to its original absolute checkout path.

## Lua

Lua files are interpreted UE4SS scripts, not compiled native binaries. lua/SBInstantBossRestart/main.lua is the actual public 0.5.2 source; lua/SBLiveAddBridge/main.lua is the live-add bridge. Install only through the normal release instructions, not from this source attachment. No live game or player-file operation is necessary to review or compile this packet.

## Panel build

Recorded original: CPython 3.14.6, PyInstaller 6.21.0, hooks-contrib 2026.6. Current installed build environment metadata additionally records PySide6/shiboken6/Addons/Essentials6.11.1 and Pillow 12.3.0. Use Windows x64 and a virtual environment; dependencies come from their public upstream distributions. No DLLs/wheels are included. The portable panel steps and exact asset selection are described in PANEL-BUILD.md.

## Scope

This snapshot contains production review/build inputs and applicable licenses. It excludes compiled binaries, repository history and application data. Source hashes inventory the supplied files; original binary hashes are mapped separately.
