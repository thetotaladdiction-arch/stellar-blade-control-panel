"""One declared component selection for packaging and production QML checks."""
from __future__ import annotations
import sys
from pathlib import Path

PARKED_COMPONENTS = frozenset({
    "R50AuthoredPoseRig.qml", "R50LiveScene.qml", "R50LocalizedCleaningRig.qml",
    "R50SemanticMaskScene.qml", "R50SkinnedCleaningRig.qml", "R50WpeLiveEffects.qml",
})


def production_component_files(qt_root: Path) -> list[Path]:
    components = qt_root / "components"
    return sorted(path for path in components.rglob("*") if path.is_file()
                  and path.relative_to(components).as_posix() not in PARKED_COMPONENTS)


def component_package_data(qt_root: Path) -> list[tuple[str, str]]:
    components = qt_root / "components"
    return [(str(path), (Path("components") / path.relative_to(components).parent).as_posix())
            for path in production_component_files(qt_root)]


def production_qml_files(qt_root: Path) -> list[Path]:
    files = [qt_root / "main.qml"]
    for directory in ("pages", "DesignSystem"):
        files.extend((qt_root / directory).glob("*.qml"))
    files.extend(path for path in production_component_files(qt_root) if path.suffix.lower() == ".qml")
    return sorted(files)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: production_qml.py QT_ROOT")
    for path in production_qml_files(Path(sys.argv[1])):
        print(path)
