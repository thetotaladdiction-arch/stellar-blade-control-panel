"""Leftovers of an old UE4SS install sitting directly in ``Binaries\\Win64``.

The mod suite runs UE4SS from ``Binaries\\Win64\\ue4ss\\`` (loaded through
``dwmapi.dll``).  Older UE4SS releases were unpacked straight into
``Binaries\\Win64``: ``UE4SS.dll``, ``UE4SS-settings.ini``, the
``UE4SS_Signatures`` folder and an ``xinput1_3.dll`` loader.  When those are
still there, two copies of UE4SS can start with the game.

Rules this module keeps:

* Only the four names above, and only directly in ``Binaries\\Win64``.  The
  current ``ue4ss`` folder, ``dwmapi.dll`` and everything else are never
  looked at.
* ``xinput1_3.dll`` is also the file name other tools use.  It counts as a
  leftover only when a UE4SS file sits next to it or the DLL itself names
  UE4SS, so another tool's loader is never moved.
* Nothing is deleted.  The leftovers are moved (renamed) into a new, dated
  backup folder in the same ``Binaries\\Win64`` folder.  If one of them
  cannot be moved, the ones already moved go back, so the folder is never
  left half-changed.
"""

from __future__ import annotations

import datetime as _dt
import os
from dataclasses import dataclass
from pathlib import Path

UE4SS_MARKERS = ("UE4SS.dll", "UE4SS-settings.ini", "UE4SS_Signatures")
UE4SS_LOADER = "xinput1_3.dll"
OLD_UE4SS_NAMES = (*UE4SS_MARKERS, UE4SS_LOADER)
BACKUP_PREFIX = "Old UE4SS files "
# A UE4SS proxy DLL names the DLL it loads; 4 MB is far above any loader.
_LOADER_SCAN_LIMIT = 4 * 1024 * 1024


@dataclass(frozen=True)
class MoveResult:
    backup_dir: Path
    moved: tuple[str, ...]


def win64_dir_for(sb_root: Path) -> Path:
    return Path(sb_root) / "Binaries" / "Win64"


def _entries_by_name(win64: Path) -> dict[str, Path]:
    try:
        with os.scandir(win64) as entries:
            return {entry.name.casefold(): Path(entry.path) for entry in entries}
    except OSError:
        return {}


def _loader_names_ue4ss(path: Path) -> bool:
    try:
        if not path.is_file() or path.stat().st_size > _LOADER_SCAN_LIMIT:
            return False
        data = path.read_bytes().lower()
    except OSError:
        return False
    # The name appears as plain bytes or as UTF-16 in a Windows DLL.
    return b"ue4ss" in data or "ue4ss".encode("utf-16-le") in data


def find_leftovers(win64: Path) -> list[Path]:
    """The old UE4SS files directly in ``win64``, in a fixed order."""

    entries = _entries_by_name(Path(win64))
    found = [
        entries[name.casefold()] for name in UE4SS_MARKERS if name.casefold() in entries
    ]
    loader = entries.get(UE4SS_LOADER.casefold())
    if loader is not None and (found or _loader_names_ue4ss(loader)):
        found.append(loader)
    return found


def _new_backup_dir(win64: Path, now: _dt.datetime) -> Path:
    base = f"{BACKUP_PREFIX}{now:%Y-%m-%d %H%M%S}"
    candidate = win64 / base
    number = 2
    while candidate.exists():
        candidate = win64 / f"{base} ({number})"
        number += 1
    return candidate


def move_to_backup(win64: Path, now: _dt.datetime | None = None) -> MoveResult:
    """Move every leftover into a new dated folder next to them.

    Raises ``FileNotFoundError`` when there is nothing to move and
    ``OSError`` when a file cannot be moved (after moving the others back).
    """

    win64 = Path(win64)
    leftovers = find_leftovers(win64)
    if not leftovers:
        raise FileNotFoundError(f"no old UE4SS files in {win64}")
    backup_dir = _new_backup_dir(win64, now or _dt.datetime.now().astimezone())
    backup_dir.mkdir()
    moved: list[tuple[Path, Path]] = []
    try:
        for source in leftovers:
            target = backup_dir / source.name
            source.rename(target)
            moved.append((source, target))
    except OSError:
        for source, target in reversed(moved):
            try:
                target.rename(source)
            except OSError:
                pass
        try:
            backup_dir.rmdir()  # only when empty: everything went back
        except OSError:
            pass
        raise
    return MoveResult(
        backup_dir=backup_dir, moved=tuple(source.name for source, _ in moved)
    )


def leftovers_text(names: list[str]) -> str:
    """``UE4SS.dll, UE4SS-settings.ini and xinput1_3.dll``."""

    if len(names) <= 1:
        return "".join(names)
    return ", ".join(names[:-1]) + " and " + names[-1]
