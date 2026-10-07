# Third-party notices

Stellar Blade Mod Suite 2.6.11. The mod's own code and interface artwork are (c) Rynstreme; see PERMISSIONS.md. This file lists the third-party software inside the download and where its license text is. The full texts are in the `LICENSES` folder next to this file.

## Inside the panel (`Stellar Blade Control Panel.exe`)

The panel is a single-file program made with PyInstaller. When it starts, it unpacks the libraries below into a temporary folder and loads them from there. None of them was modified.

| Component | Version | License | Text in LICENSES/ |
|---|---|---|---|
| Qt libraries: Core, Gui, Widgets, OpenGL, OpenGLWidgets, Network, Concurrent, Sql, Svg, Qml (+ Core, Models, Meta, WorkerScript, LocalStorage, Network, XmlListModel), Quick, Quick Controls 2 and its styles, Quick Dialogs 2, Quick Layouts, Quick Effects, Quick Particles, Quick Shapes, Quick Templates 2, Quick Vector Image (+ Generator, Helpers), Shader Tools, Qt Labs modules, Qt 5 Compat Graphical Effects, and the Qt plugins for Windows, image formats, icon engines, TLS, network information and QML tooling | 6.11.1 (from the PySide6 6.11.1 wheels on PyPI) | LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only. Checked per module against the SPDX headers of the Qt 6.11.1 sources, including Qt Quick Vector Image (qtdeclarative) and the Qt Shader Tools library. Qt Quick Timeline, which open-source Qt offers under GPL-3.0 only, is not included, and neither is Qt Multimedia (so no FFmpeg). | `Qt-LGPL-3.0.txt`, `GPL-3.0.txt` |
| Qt for Python: PySide6 and Shiboken6 | 6.11.1 | LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only | `Qt-LGPL-3.0.txt`, `GPL-3.0.txt` |
| Third-party code inside those Qt libraries (for example zlib, libpng, libjpeg-turbo, libwebp, libtiff, FreeType, HarfBuzz, PCRE2, double-conversion, md4c, SPIRV-Cross and glslang in Shader Tools) | as shipped with Qt 6.11.1 | each component's own license (mostly permissive: zlib, libpng, IJG, BSD, MIT, Apache-2.0, FTL) | `Qt-third-party.txt` (every component with its copyright and license text, as published by The Qt Company) |
| Mesa llvmpipe software OpenGL (`opengl32sw.dll`), as shipped with Qt | as shipped with Qt 6.11.1 | MIT | `Mesa-MIT.txt` |
| Python runtime | 3.14 | PSF License Agreement (the file also carries the licenses of the libraries CPython includes) | `Python-PSF-2.0.txt` |
| OpenSSL (`libssl-3`, `libcrypto-3`, and Qt's `libssl-3-x64`, `libcrypto-3-x64`) | 3.x | Apache-2.0 | `OpenSSL-Apache-2.0.txt` |
| libffi (`libffi-8`) | 3.x | MIT | `libffi-MIT.txt` |
| PyInstaller bootloader | 6.21.0 | GPL-2.0-or-later with the PyInstaller bootloader exception (programs built with it may use any license) | `PyInstaller-COPYING.txt` |
| Microsoft Visual C++ runtime and Universal CRT DLLs (`vcruntime140`, `msvcp140`, `concrt140`, `ucrtbase`, `api-ms-win-*`) | 14.x | Microsoft Visual C++ Redistributable license terms | (redistributable files; no separate text) |

### Qt and PySide6 (LGPL-3.0)

The panel uses Qt and PySide6 under the LGPL-3.0 option. GPL-3.0.txt is included only because the LGPL-3.0 text refers to it; the Mod Suite's own code and artwork are not under the GPL or LGPL (see PERMISSIONS.md).

The Qt and PySide6 libraries inside the panel are the unmodified binaries from the PySide6, PySide6-Essentials, PySide6-Addons and Shiboken6 6.11.1 wheels on PyPI (https://pypi.org/project/PySide6/6.11.1/). Their source code is available from The Qt Company at https://download.qt.io/official_releases/qt/6.11/ and https://download.qt.io/official_releases/QtForPython/pyside6/, and as the PySide6 6.11.1 source distribution on PyPI.

The panel is built from its own Python and QML source with PyInstaller. To use the panel with other or modified Qt / PySide6 6.11 libraries, ask the author on the mod's Nexus Mods page (https://www.nexusmods.com/stellarblade/mods/3479) for the panel's source and build script, and rebuild it against your libraries.

## Inside the game mods (`SBGodNative`, `SBLiveAddNative`, `SBMovementNative`, `SBRetryPointNative`)

| Component | License | Text in LICENSES/ |
|---|---|---|
| RE-UE4SS C++ mod interface headers (the game mods are built against UE4SS's mod interface) | MIT | `RE-UE4SS-MIT.txt` |
| Microsoft Visual C++ runtime (the game mods load the system copy that the Microsoft Visual C++ Redistributable installs; that installer is not in the download) | Microsoft terms | - |

## UE4SS (included)

The game mods load through UE4SS. The download includes the UE4SS build they were tested with: UE4SS for Stellar Blade by Chrisr0 (https://github.com/Chrisr0/RE-UE4SS), based on RE-UE4SS by the UE4SS team (https://github.com/UE4SS-RE/RE-UE4SS). Its log identifies it as "UE4SS - v3.0.1 Beta #0 - Git SHA #d3d1004".

| Files (under `SB\Binaries\Win64`) | License | Text |
|---|---|---|
| `dwmapi.dll` (UE4SS loader), `ue4ss\UE4SS.dll`, `ue4ss\UE4SS-settings.ini`, `ue4ss\VTableLayout.ini`, `ue4ss\UE4SS_Signatures\GUObjectArray.lua`, `ue4ss\UE4SS_Signatures\GNatives.lua`, `ue4ss\Mods\shared\UEHelpers\UEHelpers.lua` | MIT, Copyright (c) 2022 Narknon | `ue4ss\LICENSE`, as shipped with that build (the same text as `LICENSES/RE-UE4SS-MIT.txt`) |

UE4SS is itself built from further open-source components; see its repositories above for their notices.

## Not included (separate downloads)

- RivaTuner Statistics Server and MSI Afterburner. Optional; the overlay reads them when they run.
- Intel PresentMon is not included in this version.
