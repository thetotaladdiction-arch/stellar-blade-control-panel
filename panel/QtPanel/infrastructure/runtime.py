from __future__ import annotations

import os
import sys
import time
from pathlib import Path


def discover_mod_root(start: Path) -> Path:
    """Find SBCheatGUI root even when the panel EXE lives in QtPanel/dist/."""
    path = start.resolve()
    for _ in range(8):
        if (path / "VERSION").is_file() and (path / "assets").is_dir():
            return path
        if path.parent == path:
            break
        path = path.parent
    return start.resolve()


def resolve_runtime_paths() -> tuple[Path, Path]:
    """Return the external mod root and the bundled/source resource root."""
    if getattr(sys, "frozen", False):
        mod_root = discover_mod_root(Path(sys.executable).resolve().parent)
        resource_root = Path(getattr(sys, "_MEIPASS", mod_root))
        return mod_root, resource_root
    qt_root = Path(__file__).resolve().parents[1]
    return qt_root.parent, qt_root


def development_qml_requested(argv=None, environ=None) -> bool:
    """Live disk QML is opt-in for frozen builds, never an accidental fallback."""
    args = list(sys.argv if argv is None else argv)
    env = os.environ if environ is None else environ
    return "--dev-qml" in args or str(env.get("SBCHEATGUI_DEV_QML", "")).strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def resolve_qml_path(mod_root: Path, resource_root: Path, *, frozen=None, dev_mode=None) -> Path:
    """Resolve a deterministic production or explicitly requested development QML source."""
    disk_qml = mod_root / "QtPanel" / "main.qml"
    bundled_qml = resource_root / "main.qml"
    is_frozen = bool(getattr(sys, "frozen", False) if frozen is None else frozen)
    use_dev_qml = development_qml_requested() if dev_mode is None else bool(dev_mode)

    if is_frozen and not use_dev_qml and bundled_qml.is_file():
        return bundled_qml.resolve()
    if disk_qml.is_file():
        return disk_qml.resolve()
    if bundled_qml.is_file():
        return bundled_qml.resolve()
    return (bundled_qml if is_frozen and not use_dev_qml else disk_qml).resolve()


def write_qml_source_marker(mod_root: Path, resource_root: Path, qml_path: Path) -> None:
    try:
        marker = mod_root / "panel_qml_source.txt"
        try:
            qml_path.resolve().relative_to(resource_root.resolve())
            source_mode = "bundled-exe" if getattr(sys, "frozen", False) else "live-disk"
        except ValueError:
            source_mode = "live-disk"
        try:
            modified = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(qml_path.stat().st_mtime))
        except OSError:
            modified = ""
        marker.write_text(
            f"source={source_mode}\npath={qml_path}\nmtime={modified}\n",
            encoding="utf-8",
        )
    except OSError:
        pass


def write_panel_running_version(mod_root: Path, version: str) -> None:
    try:
        (mod_root / "panel_running_version.txt").write_text(version.strip() + "\n", encoding="utf-8")
    except OSError:
        pass
