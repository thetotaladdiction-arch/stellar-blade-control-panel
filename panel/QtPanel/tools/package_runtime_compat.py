from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable, Mapping


BinaryEntry = tuple[str, str, str]


def remove_root_icu_overrides(binaries: Iterable[BinaryEntry]) -> list[BinaryEntry]:
    """Let Qt resolve Windows ICU instead of packaging unrelated PATH copies."""
    updated = []
    for destination, source, typecode in binaries:
        normalized = destination.replace("\\", "/")
        name = normalized.casefold()
        is_root = "/" not in normalized
        is_icu_override = name.endswith(".dll") and name.startswith(
            ("icuuc", "icuin", "icudt")
        )
        if is_root and is_icu_override:
            continue
        updated.append((destination, source, typecode))
    return updated


def replace_root_msvc_runtime(
    binaries: Iterable[BinaryEntry], replacements: Mapping[str, Path]
) -> list[BinaryEntry]:
    """Replace stale root MSVC DLLs while retaining scoped dependency copies."""
    checked: dict[str, Path] = {}
    for destination, source in replacements.items():
        source = Path(source).resolve()
        if not source.is_file():
            raise FileNotFoundError(f"Required package runtime is missing: {destination}")
        checked[destination] = source

    root_names = {name.casefold() for name in checked}
    updated = []
    for destination, source, typecode in binaries:
        normalized = destination.replace("\\", "/")
        if "/" not in normalized and normalized.casefold() in root_names:
            continue
        updated.append((destination, source, typecode))
    updated.extend(
        (destination, str(source), "BINARY")
        for destination, source in checked.items()
    )
    return updated


# Qt modules the panel never imports. PyInstaller's QtQml hook collects every
# QML module in PySide6/qml plus each plugin's Qt DLLs, so without this filter
# the exe carried QtWebEngine (Qt6WebEngineCore.dll alone is 195 MB, and it
# could never run: QtWebEngineProcess.exe and its resources are not bundled),
# Qt 3D, Quick 3D, Charts, Graphs, PDF, Location, the virtual keyboard and more.
# The panel's QML imports only QtQuick, QtQuick.Controls(.Material) and
# QtQuick.Layouts/Window/Shapes/Effects. Qt Multimedia went with the
# Dashboard video in 2.5.504 build 4 (with its FFmpeg libraries, below).
UNUSED_QML_MODULES = (
    "Qt3D",
    "QtCharts",
    "QtDataVisualization",
    "QtGraphs",
    "QtLocation",
    "QtMultimedia",
    "QtPositioning",
    "QtQml/StateMachine",
    "QtQuick/Pdf",
    "QtQuick/Scene2D",
    "QtQuick/Scene3D",
    # GPL-3.0-only in open-source Qt (see GPL_ONLY_QT_DLL_PREFIXES); unused.
    "QtQuick/Timeline",
    "QtQuick/VirtualKeyboard",
    "QtQuick3D",
    "QtRemoteObjects",
    "QtScxml",
    "QtSensors",
    "QtTest",
    "QtTextToSpeech",
    "QtWebChannel",
    "QtWebEngine",
    "QtWebSockets",
    "QtWebView",
)

# Qt DLL name prefixes (case-insensitive, under PySide6/) that belong only to
# the modules above. Anything the kept modules link against stays.
UNUSED_QT_DLL_PREFIXES = (
    # Qt Multimedia's FFmpeg backend (avcodec-61.dll and friends).
    "avcodec",
    "avformat",
    "avutil",
    "qt63d",
    "qt6charts",
    "qt6datavisualization",
    "qt6graphs",
    "qt6location",
    "qt6multimedia",
    "qt6pdf",
    "qt6positioning",
    "qt6quick3d",
    "qt6quicktest",
    "qt6quicktimeline",
    "qt6remoteobjects",
    "qt6scxml",
    "qt6sensors",
    "qt6spatialaudio",
    "qt6statemachine",
    "swresample",
    "swscale",
    "qt6test",
    "qt6texttospeech",
    "qt6virtualkeyboard",
    "qt6webchannel",
    "qt6webengine",
    "qt6websockets",
    "qt6webview",
)

                                                                          
                                                                      
                                                                             
                                                                            
                                                                            
                                                                            
                                                                  
                                               
GPL_ONLY_QT_DLL_PREFIXES = (
    "qt6canvaspainter",
    "qt6coap",
    "qt6graphs",
    "qt6grpc",
    "qt6httpserver",
    "qt6lottie",
    "qt6mqtt",
    "qt6networkauth",
    "qt6qmlcompiler",
    "qt6quick3d",
    "qt6quicktimeline",
    "qt6virtualkeyboard",
    "qt6waylandcompositor",
)

# Qt plugin folders (PySide6/plugins/<name>) that only the modules above load.
UNUSED_QT_PLUGIN_DIRS = (
    "geometryloaders",
    "geoservices",
    "multimedia",
    "position",
    "renderers",
    "renderplugins",
    "sceneparsers",
    "sensors",
    "texttospeech",
    "virtualkeyboard",
    "webview",
)

# Single plugins in otherwise-needed folders that link a removed module's DLL
# (found by checking every kept binary's PE imports against the removed set).
UNUSED_QT_PLUGIN_FILES = (
    "imageformats/qpdf.dll",
    "platforminputcontexts/qtvirtualkeyboardplugin.dll",
    "qmltooling/qmldbg_quick3dprofiler.dll",
)


def is_unused_qt_entry(destination: str) -> bool:
    """True for a packaged file that belongs only to an unused Qt module."""
    normalized = destination.replace("\\", "/")
    parts = normalized.split("/")
    if not parts or parts[0] != "PySide6" or len(parts) < 2:
        return False
    if parts[1] == "qml" and len(parts) > 2:
        relative = "/".join(parts[2:])
        return any(
            relative == module or relative.startswith(module + "/")
            for module in UNUSED_QML_MODULES
        )
    if parts[1] == "plugins" and len(parts) > 3:
        relative = "/".join(parts[2:]).casefold()
        return parts[2].casefold() in UNUSED_QT_PLUGIN_DIRS or relative in UNUSED_QT_PLUGIN_FILES
    if len(parts) == 2:
        name = parts[1].casefold()
        return name.endswith(".dll") and name.startswith(
            UNUSED_QT_DLL_PREFIXES + GPL_ONLY_QT_DLL_PREFIXES
        )
    return False


def gpl_only_qt_entries(names: Iterable[str]) -> list[str]:
    """Packaged names that belong to a GPL-only Qt module (must be empty)."""
    found = []
    for destination in names:
        normalized = destination.replace("\\", "/")
        base = normalized.rsplit("/", 1)[-1].casefold()
        in_timeline_qml = "/qml/QtQuick/Timeline/" in "/" + normalized + "/"
        if (base.endswith(".dll") and base.startswith(GPL_ONLY_QT_DLL_PREFIXES)) or in_timeline_qml:
            found.append(destination)
    return found


# In-game test results change with every build of a game mod, so they belong in
# the release texts (README / CHANGELOG / Nexus page), which the release gate
# checks (make_release.py: <!--VERIFY:...--> markers and the in-game results
# ledger). A sentence inside the exe can't be corrected without a rebuild and
# no gate reads it (build 4k review, 2026-09-29), so the panel's own words and
# the bundled QML/JS never carry one: tests/test_boss_revive_card.py checks
# the sources, make_release.py the texts inside the release exe.
IN_GAME_TEST_CLAIM = re.compile(
    r"\b[Tt]ested (?:in|against|on|with)\b|\b(?:checked|run|proven|tested) in the game\b"
)


def in_game_test_claims(name: str, text: str) -> list[str]:
    """Lines of ``text`` that claim an in-game test result (must be empty)."""
    return [
        f"{name}:{number}: {line.strip()[:120]}"
        for number, line in enumerate(text.splitlines(), 1)
        if IN_GAME_TEST_CLAIM.search(line)
    ]


def remove_unused_qt_modules(entries: Iterable[BinaryEntry]) -> list[BinaryEntry]:
    """Drop the packaged files of Qt modules the panel never imports."""
    return [entry for entry in entries if not is_unused_qt_entry(entry[0])]
