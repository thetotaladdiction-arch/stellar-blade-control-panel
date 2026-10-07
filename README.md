# Stellar Blade Mod Suite — source review — version 2.6.11

Source snapshot for Nexus Mods compiled-code review of upload 17076. Public source URL: https://github.com/thetotaladdiction-arch/stellar-blade-control-panel/tree/v2.6.11

This snapshot contains the custom panel's 37 Python modules, 120 packaged UI/assets and required build inputs; production source for God 1.3.5, LiveAdd 0.5.1, Movement 1.4.1 and RetryPoint 0.2.3; shared native ABI/core; and the two Lua scripts. It contains no compiled executable/DLL, repository history, player saves/settings, authentication material or internal audit logs.

Read [BUILD.md](BUILD.md) and [PANEL-BUILD.md](PANEL-BUILD.md) for tool versions, portable build steps and their limits. [SHIPPED-BINARY-MAPPING.json](SHIPPED-BINARY-MAPPING.json) identifies the exact binary ZIP already submitted to Nexus. [SOURCE-MANIFEST.json](SOURCE-MANIFEST.json) inventories supplied relative source paths/hashes. Support copies neutralize private comments and documentation strings. Python operational AST/co_code/callables were checked with __doc__ constants normalized; native non-comment tokens are unchanged. Documentation and line metadata may differ. Portable recipes have not been built, and arbitrary-path rebuilds are not claimed byte-identical to the shipped binaries.

The existing [Source Review LICENSE](LICENSE) applies to original code/artwork. It permits inspection and personal verification builds; it does not authorize redistribution or modified releases. Third-party dependencies retain their own licenses. UE4SS upstream: https://github.com/Chrisr0/RE-UE4SS ; pinned ABI headers and MIT license are included under native/sbcore/third_party/RE-UE4SS.

The source-only snapshot is intended for review, not an alternate game installation package. Nothing needs to write to installed game/player files to inspect or compile it.
