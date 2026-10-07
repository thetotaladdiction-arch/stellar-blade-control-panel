"Save history: automatic, verified snapshots of the game's save folder,"



















































from __future__ import annotations

import datetime as _dt
import hashlib
import json
import os
import re
import shutil
import stat
import sys
import time
import zipfile
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path

ROOT_NAME = "StellarBlade-SaveSnapshots"
MANIFEST_DIR = ".manifests"
INCOMING_PREFIX = ".incoming-"
# Pruned snapshots stay here with their manifests, each packed into one zip.
RECYCLE_DIR = ".recycle"
PACK_SUFFIX = ".zip"
NAME_FORMAT = "%Y-%m-%d_%H%M%S"
NAME_RE = re.compile(r"^\d{4}-\d{2}-\d{2}_\d{6}(?:-\d{1,3})?$")
# Registered manual copies remain separate from automatic generation.
MANUAL_NAME_RE = re.compile(r"^\d{4}-\d{2}-\d{2}_manual-before-close$")
MANIFEST_SCHEMA = 1
# A save folder far larger than this is not a Stellar Blade save folder.
MAX_TOTAL_BYTES = 2 * 1024 * 1024 * 1024
READ_ATTEMPTS = 3
CHUNK = 1024 * 1024
# The game writes a save as several files within a second or two; a
# snapshot waits until nothing in the folder changed for this long.
SETTLE_SEC = 5.0
# Steam's own file, not a save: a restore leaves it alone.
RESTORE_SKIP = frozenset({"steam_autocloud.vdf"})
# Keep the current graphics settings even when an older snapshot has them.
# Snapshots still back them up and notice settings changes as before.
RESTORE_SETTINGS_SKIP = frozenset({"stellarbladesetting.sav", "stellarbladesetting_old.sav"})
# Why a snapshot was made (the manifest's "reason"), in plain words.
REASON_BEFORE_RESTORE = "before restore"
REASON_GAME_SAVED = "game saved"
REASON_LABELS = {
    "manual": "Manual backup",
    "panel start": "Panel opened",
    "game start": "Game started",
    REASON_GAME_SAVED: "Game saved",
    "backup button": "Backed up by you",
    REASON_BEFORE_RESTORE: "Before restore",
}
RESTORED_TEXT = "Restored. Start the game and load your save."


# Time-thinned retention (``retained``). Ages count back from the newest
# copy (from now instead if a copy is dated in the future), so time with the
# panel open and no save thins nothing. Buckets follow the local clock
# (10:40-10:49, 10:00-10:59, the calendar day) and keep their newest copy,
# so a bucket's pick never changes once it has passed and each coarser pick
# is also the finer one's: nothing a later tier needs is pruned by an
# earlier one. Each tier keeps its newest ``count`` buckets that have a copy
# and every bucket within ``span`` of the newest copy, so it holds
# max(count, buckets in span) buckets: at most 19, 49 and 31. Build 4i
# counted the span alone, so the first save after a break longer than 30
# days moved every copy but "Before restore" out of the list (build 4i
# review). Now the first save after a break of any length moves out only
# the extra copies of the 15 minutes before it (one per 10 minutes stays)
# and at most the two oldest buckets of each tier (tests/test_save_history.py).
RECENT_WINDOW = _dt.timedelta(minutes=15)
RECENT_CAP = 40


def _ten_minutes(when: _dt.datetime) -> tuple:
    return (when.date(), when.hour, when.minute // 10)


def _hour(when: _dt.datetime) -> tuple:
    return (when.date(), when.hour)


def _day(when: _dt.datetime) -> _dt.date:
    return when.date()


# (span, bucket, count): the newest copy of each bucket that is within span
# of the newest copy or among the newest count buckets that have a copy.
THINNING: tuple[tuple[_dt.timedelta, Callable[[_dt.datetime], object], int], ...] = (
    (_dt.timedelta(hours=3), _ten_minutes, 18),
    (_dt.timedelta(days=2), _hour, 48),
    (_dt.timedelta(days=30), _day, 30),
)


class SnapshotError(RuntimeError):
    """The snapshot could not be made safely; nothing was kept."""


@dataclass(frozen=True)
class SnapshotInfo:
    name: str
    path: Path
    created: _dt.datetime
    files: int
    total_bytes: int
    reason: str = ""
    # Plain words for the Save history list ("Game saved", "Before restore").
    label: str = ""


@dataclass
class SnapshotResult:
    state: str  # "created" | "unchanged" | "no-saves"
    message: str
    snapshot: SnapshotInfo | None = None
    removed: list[str] = field(default_factory=list)


def default_save_root(environ: dict | None = None) -> Path | None:
    """The game's save folder: the Steam build uses %LOCALAPPDATA%."""

    env = os.environ if environ is None else environ
    candidates: list[Path] = []
    local = env.get("LOCALAPPDATA")
    if local:
        candidates.append(Path(local) / "SB" / "Saved" / "SaveGames")
    profile = env.get("USERPROFILE")
    if profile:
        candidates.append(Path(profile) / "Documents" / "My Games" / "SB" / "Saved" / "SaveGames")
    for candidate in candidates:
        if candidate.is_dir():
            return candidate
    return candidates[0] if candidates else None


def default_snapshot_root(mod_root: Path) -> Path:
    """``<drive the mod is installed on>\\StellarBlade-SaveSnapshots``.

    Resolved from the panel's own location (no hard-coded drive): the
    installed panel lives on the game's drive, so for a game on drive D: this is
    ``D:\\StellarBlade-SaveSnapshots``.
    """

    # abspath, not resolve(): the drive the player sees, even if a folder
    # on the way is a junction to somewhere else.
    anchor = Path(os.path.abspath(mod_root)).anchor or Path.cwd().anchor
    return Path(anchor) / ROOT_NAME


# --------------------------------------------------------------------------
# Reading the game's files without ever blocking the game.


def _open_shared(path: Path):
    """Open ``path`` read-only, sharing read, write *and* delete.

    Python's ``open`` does not share delete access on Windows, so a game
    that saves by writing a temporary file and renaming it over the old save
    would fail while we held the old one open.  CreateFileW with
    FILE_SHARE_DELETE avoids that.
    """

    if sys.platform != "win32":
        return open(path, "rb")
    import ctypes
    import msvcrt
    from ctypes import wintypes

    GENERIC_READ = 0x80000000
    SHARE_ALL = 0x00000001 | 0x00000002 | 0x00000004
    OPEN_EXISTING = 3
    FILE_ATTRIBUTE_NORMAL = 0x80
    FILE_FLAG_SEQUENTIAL_SCAN = 0x08000000

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    create = kernel32.CreateFileW
    create.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    create.restype = wintypes.HANDLE
    handle = create(
        str(path),
        GENERIC_READ,
        SHARE_ALL,
        None,
        OPEN_EXISTING,
        FILE_ATTRIBUTE_NORMAL | FILE_FLAG_SEQUENTIAL_SCAN,
        None,
    )
    invalid = ctypes.c_void_p(-1).value
    if handle is None or handle == invalid:
        raise OSError(ctypes.get_last_error(), "Could not open save file for reading", str(path))
    try:
        fd = msvcrt.open_osfhandle(handle, os.O_RDONLY | getattr(os, "O_BINARY", 0))
    except Exception:
        kernel32.CloseHandle(wintypes.HANDLE(handle))
        raise
    return os.fdopen(fd, "rb")


def _stat_key(path: Path) -> tuple[int, int]:
    st = os.stat(path)
    return st.st_size, st.st_mtime_ns


def _hash_source(path: Path) -> tuple[str, int, int, int]:
    """Hash one save file; retried until it is stable while being read."""

    last_error: Exception | None = None
    for _ in range(READ_ATTEMPTS):
        try:
            before = _stat_key(path)
            digest = hashlib.sha256()
            size = 0
            with _open_shared(path) as stream:
                while chunk := stream.read(CHUNK):
                    digest.update(chunk)
                    size += len(chunk)
            after = _stat_key(path)
        except OSError as exc:
            last_error = exc
            continue
        if before == after and size == after[0]:
            st = os.stat(path)
            return digest.hexdigest(), size, st.st_mtime_ns, st.st_atime_ns
        last_error = SnapshotError(f"{path.name} changed while it was being read")
    raise SnapshotError(f"Could not read {path.name} steadily: {last_error}")


def _copy_verified(source: Path, dest: Path, expected_sha: str, expected_size: int) -> None:
    """Copy ``source`` to ``dest`` and prove the copy has the expected hash."""

    last_error: Exception | None = None
    for _ in range(READ_ATTEMPTS):
        try:
            before = _stat_key(source)
            digest = hashlib.sha256()
            dest.parent.mkdir(parents=True, exist_ok=True)
            with _open_shared(source) as src, open(dest, "wb") as out:
                while chunk := src.read(CHUNK):
                    digest.update(chunk)
                    out.write(chunk)
                out.flush()
                os.fsync(out.fileno())
            after = _stat_key(source)
        except OSError as exc:
            last_error = exc
            continue
        if before != after or digest.hexdigest() != expected_sha:
            # The game saved between the scan and the copy: the whole
            # snapshot is re-scanned by the caller.
            raise _SourceChanged(source.name)
        written = hashlib.sha256()
        with open(dest, "rb") as check:
            while chunk := check.read(CHUNK):
                written.update(chunk)
        if written.hexdigest() != expected_sha or dest.stat().st_size != expected_size:
            last_error = SnapshotError(f"The copy of {source.name} did not match the save")
            continue
        st = os.stat(source)
        os.utime(dest, ns=(st.st_atime_ns, st.st_mtime_ns))
        return
    raise SnapshotError(f"Could not copy {source.name}: {last_error}")


class _SourceChanged(Exception):
    pass


# --------------------------------------------------------------------------
# Scanning.


def _is_inside(child: Path, parent: Path) -> bool:
    try:
        child.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def _is_link_or_junction(path: Path) -> bool:
    try:
        if path.is_symlink():
            return True
        attrs = getattr(os.lstat(path), "st_file_attributes", 0)
        return bool(attrs & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))
    except OSError:
        return True


def scan_saves(save_root: Path) -> dict[str, dict]:
    """``{relative posix path: {sha256, size, mtime_ns}}`` for every save file.

    Links and junctions are skipped so the scan never leaves the folder.
    """

    files: dict[str, dict] = {}
    total = 0
    for dirpath, dirnames, filenames in os.walk(save_root, followlinks=False):
        base = Path(dirpath)
        dirnames[:] = sorted(d for d in dirnames if not _is_link_or_junction(base / d))
        for name in sorted(filenames):
            path = base / name
            if _is_link_or_junction(path) or not path.is_file():
                continue
            sha, size, mtime_ns, _atime = _hash_source(path)
            total += size
            if total > MAX_TOTAL_BYTES:
                raise SnapshotError("The save folder is unexpectedly large; no snapshot was made.")
            rel = path.relative_to(save_root).as_posix()
            files[rel] = {"sha256": sha, "size": size, "mtime_ns": mtime_ns}
    return files


# --------------------------------------------------------------------------
# The snapshot store.


def _manifest_path(root: Path, name: str) -> Path:
    return root / MANIFEST_DIR / f"{name}.json"


def _manual_snapshot_name(name: str) -> bool:
    if not isinstance(name, str) or not MANUAL_NAME_RE.fullmatch(name):
        return False
    try:
        _dt.datetime.strptime(name[:10], "%Y-%m-%d")
    except ValueError:
        return False
    return True


def _accepted_snapshot_name(name: str) -> bool:
    return isinstance(name, str) and (bool(NAME_RE.fullmatch(name)) or _manual_snapshot_name(name))


def _manual_paths_safe(root: Path, data: dict) -> bool:
    """A registered manual tree, with valid metadata, no links or extra files."""
    if not isinstance(data, dict) or data.get("schema") != MANIFEST_SCHEMA:
        return False
    if not _manual_snapshot_name(data.get("name")) or data.get("reason") != "manual":
        return False
    files = data.get("files")
    if not isinstance(files, dict) or not files:
        return False
    for relative, meta in files.items():
        if not isinstance(relative, str) or _safe_relative(relative) is None or not isinstance(meta, dict):
            return False
        if type(meta.get("size")) is not int or meta["size"] < 0:
            return False
        if not isinstance(meta.get("sha256"), str) or not re.fullmatch(r"[0-9a-f]{64}", meta["sha256"]):
            return False
    try:
        created = _dt.datetime.fromisoformat(data.get("created"))
    except (TypeError, ValueError):
        return False
    if created.tzinfo is not None:
        return False
    folder = root / data["name"]
    if not folder.is_dir() or any(_is_link_or_junction(p) for p in (folder, *folder.parents)):
        return False
    actual = set()
    for base, directories, names in os.walk(folder, followlinks=False):
        parent = Path(base)
        if any(_is_link_or_junction(parent / name) for name in directories):
            return False
        for name in names:
            path = parent / name
            if _is_link_or_junction(path) or not path.is_file() or path.stat().st_nlink != 1:
                return False
            relative = path.relative_to(folder).as_posix()
            if _safe_relative(relative) is None or not _is_inside(path, folder):
                return False
            actual.add(relative)
    return actual == set(files)


def _read_manifest(root: Path, name: str) -> dict | None:
    try:
        path = _manifest_path(root, name)
        if _manual_snapshot_name(name):
            if _is_link_or_junction(path) or _is_link_or_junction(path.parent) or path.stat().st_nlink != 1:
                return None
            data = json.loads(path.read_text(encoding="utf-8"))
            if not _manual_paths_safe(root, data):
                return None
        else:
            data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or data.get("schema") != MANIFEST_SCHEMA or data.get("name") != name:
        return None
    if not isinstance(data.get("files"), dict):
        return None
    return data


def list_snapshots(root: Path) -> list[SnapshotInfo]:
    """Snapshots this module made, newest first."""

    out: list[SnapshotInfo] = []
    try:
        entries = list(os.scandir(root))
    except OSError:
        return out
    for entry in entries:
        if not _accepted_snapshot_name(entry.name):
            continue
        path = Path(entry.path)
        if _is_link_or_junction(path) or not entry.is_dir(follow_symlinks=False):
            continue
        manifest = _read_manifest(root, entry.name)
        if manifest is None:
            continue
        try:
            created = _dt.datetime.fromisoformat(str(manifest.get("created")))
        except ValueError:
            created = _dt.datetime.strptime(entry.name[:17], NAME_FORMAT)
        files = manifest["files"]
        out.append(
            SnapshotInfo(
                name=entry.name,
                path=path,
                created=created,
                files=len(files),
                total_bytes=sum(int(v.get("size", 0)) for v in files.values()),
                reason=str(manifest.get("reason") or ""),
                label=snapshot_label(manifest),
            )
        )
    out.sort(key=lambda s: (s.created, s.name), reverse=True)
    return out


def _write_json_atomic(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with open(tmp, "w", encoding="utf-8", newline="\n") as stream:
        json.dump(data, stream, indent=1, sort_keys=True)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(tmp, path)


def _remove_tree(path: Path, root: Path) -> None:
    """Delete one folder this module owns, never anything outside ``root``."""

    if path.parent.resolve() != root.resolve() or _is_link_or_junction(path):
        raise SnapshotError(f"Refused to remove {path}")

    def _writable(func, target, _exc):
        os.chmod(target, stat.S_IWRITE)
        func(target)

    if sys.version_info >= (3, 12):
        shutil.rmtree(path, onexc=_writable)
    else:
        shutil.rmtree(path, onerror=_writable)


def _clean_leftovers(root: Path) -> None:
    """Remove half-built snapshots from an interrupted run and orphan manifests."""

    try:
        entries = list(os.scandir(root))
    except OSError:
        return
    names = {e.name for e in entries}
    for entry in entries:
        if entry.name.startswith(INCOMING_PREFIX) and entry.is_dir(follow_symlinks=False):
            try:
                _remove_tree(Path(entry.path), root)
            except (OSError, SnapshotError):
                pass
    manifests = root / MANIFEST_DIR
    try:
        for entry in os.scandir(manifests):
            stem = entry.name[:-5] if entry.name.endswith(".json") else ""
            if stem and NAME_RE.match(stem) and stem not in names:
                Path(entry.path).unlink(missing_ok=True)
    except OSError:
        pass


def _pack_recycled(area: Path, name: str) -> bool:
    """Pack the pruned snapshot ``.recycle/<name>/`` into ``<name>.zip``.

    Its manifest (``.recycle/.manifests/<name>.json``) lists every file with
    its size and SHA-256. The folder must hold exactly those files; the zip
    is written beside it under a temporary name, every member is read back
    and must match its manifest entry, and only then is the zip given its
    name and the plain folder removed. On any doubt the folder stays as it
    is (it is tried again at the next prune). True when packed.
    """

    folder = area / name
    try:
        data = json.loads((area / MANIFEST_DIR / f"{name}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    if not isinstance(data, dict):
        return False
    files = data.get("files")
    if data.get("schema") != MANIFEST_SCHEMA or not isinstance(files, dict) or not files:
        return False
    target = area / f"{name}{PACK_SUFFIX}"
    if target.exists() or _is_link_or_junction(folder) or not folder.is_dir():
        return False
    try:
        on_disk: set[str] = set()
        for dirpath, dirnames, filenames in os.walk(folder, followlinks=False):
            base = Path(dirpath)
            if any(_is_link_or_junction(base / d) for d in dirnames):
                return False
            for filename in filenames:
                path = base / filename
                if _is_link_or_junction(path):
                    return False
                on_disk.add(path.relative_to(folder).as_posix())
    except OSError:
        return False
    if on_disk != set(files) or any(_safe_relative(str(rel)) is None for rel in files):
        return False
    tmp = area / f".{name}{PACK_SUFFIX}.{os.getpid()}.tmp"
    try:
        with zipfile.ZipFile(tmp, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6,
                             strict_timestamps=False) as archive:
            for rel in sorted(files):
                archive.write(folder / Path(rel), arcname=rel)
        with zipfile.ZipFile(tmp) as archive:
            if sorted(archive.namelist()) != sorted(files):
                raise SnapshotError("the packed copy does not list the same files")
            for rel, meta in files.items():
                digest = hashlib.sha256()
                size = 0
                with archive.open(rel) as stream:
                    while chunk := stream.read(CHUNK):
                        digest.update(chunk)
                        size += len(chunk)
                if not isinstance(meta, dict) or size != int(meta.get("size", -1)) or digest.hexdigest() != meta.get("sha256"):
                    raise SnapshotError(f"the packed copy of {rel} does not match")
        os.replace(tmp, target)
    except (OSError, ValueError, zipfile.BadZipFile, SnapshotError):
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        return False
    try:
        _remove_tree(folder, area)
    except (OSError, SnapshotError):
        pass  # the zip is whole; a folder left beside it changes nothing
    return True


def _pack_recycle_area(root: Path) -> None:
    """Pack every plain pruned snapshot in ``.recycle`` (see _pack_recycled)."""

    area = root / RECYCLE_DIR
    try:
        names = [
            e.name for e in os.scandir(area)
            if not e.name.startswith(".") and e.is_dir(follow_symlinks=False)
            and (area / MANIFEST_DIR / f"{e.name}.json").is_file()
        ]
    except OSError:
        return
    for name in sorted(names):
        _pack_recycled(area, name)


def retained(
    snapshots: Iterable[SnapshotInfo],
    *,
    now: _dt.datetime | None = None,
    protect: Iterable[str] = (),
) -> set[str]:
    """The names time-thinned retention keeps.

    The newest copy; every "Before restore" copy; the newest ``RECENT_CAP``
    copies of the last ``RECENT_WINDOW``; then the newest copy of each
    10-minute, hour and day bucket within ``THINNING``'s spans or among its
    newest ``count`` buckets that have a copy (time away from the game does
    not count); and every name in ``protect``. "Before restore" copies are
    left out of the buckets, so they never stand in for the game's own
    saves.
    """

    keep = set(protect)
    ordered = sorted(snapshots, key=lambda s: (s.created, s.name), reverse=True)
    if not ordered:
        return keep
    newest = ordered[0].created
    # Local wall-clock time, like the snapshot names.
    clock = now if now is not None else _dt.datetime.now()  # noqa: DTZ005
    try:
        anchor = min(clock, newest)
    except TypeError:  # manifest times with a time zone: count from the newest
        anchor = newest
    keep.add(ordered[0].name)
    regular = []
    for info in ordered:
        if info.reason == REASON_BEFORE_RESTORE:
            keep.add(info.name)
        else:
            regular.append(info)

    recent = [info.name for info in regular if anchor - info.created <= RECENT_WINDOW]
    keep.update(recent[:RECENT_CAP])
    for span, bucket, count in THINNING:
        seen: set = set()
        for info in regular:  # newest first: each bucket's first is its newest
            key = bucket(info.created)
            if key in seen:
                continue
            if len(seen) >= count and anchor - info.created > span:
                break  # older copies are outside the span too, count reached
            seen.add(key)
            keep.add(info.name)
    return keep


def prune(
    root: Path,
    *,
    now: _dt.datetime | None = None,
    protect: Iterable[str] = (),
) -> list[str]:
    """Thin out older snapshots (``retained``; every name in ``protect`` stays).

    Nothing is thrown away: each pruned snapshot moves, with its manifest,
    into ``.recycle`` inside the snapshot folder and is packed there into
    one zip (checked file by file). Returns the names moved.
    """

    # Manual originals never enter automatic retention or recycling.
    snapshots = [info for info in list_snapshots(root) if NAME_RE.fullmatch(info.name)]
    protected = retained(snapshots, now=now, protect=protect)
    area = root / RECYCLE_DIR
    moved: list[str] = []
    for info in snapshots:
        if info.name in protected:
            continue
        try:
            if info.path.parent.resolve() != root.resolve() or _is_link_or_junction(info.path):
                continue
            (area / MANIFEST_DIR).mkdir(parents=True, exist_ok=True)
            destination = area / info.name
            if destination.exists():
                destination = area / f"{info.name}-{os.getpid()}-{int(time.time())}"
            os.replace(info.path, destination)
            manifest = _manifest_path(root, info.name)
            if manifest.is_file():
                os.replace(manifest, area / MANIFEST_DIR / f"{destination.name}.json")
            moved.append(info.name)
        except OSError:
            continue
    if moved:
        _hide(area)
        _pack_recycle_area(root)
    return moved


def snapshot_intact(root: Path, name: str) -> bool:
    """True when every file of snapshot ``name`` still matches its manifest."""

    manifest = _read_manifest(root, name)
    folder = root / name
    if manifest is None or not folder.is_dir():
        return False
    for rel, meta in manifest["files"].items():
        path = folder / Path(rel)
        try:
            if path.stat().st_size != int(meta.get("size", -1)):
                return False
            digest = hashlib.sha256()
            with open(path, "rb") as stream:
                while chunk := stream.read(CHUNK):
                    digest.update(chunk)
        except OSError:
            return False
        if digest.hexdigest() != meta.get("sha256"):
            return False
    return True


def _unique_name(root: Path, now: _dt.datetime) -> str:
    base = now.strftime(NAME_FORMAT)
    name = base
    n = 1
    while (root / name).exists() or _manifest_path(root, name).exists():
        n += 1
        name = f"{base}-{n}"
    return name


def _hide(path: Path) -> None:
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.kernel32.SetFileAttributesW(str(path), 0x02)  # FILE_ATTRIBUTE_HIDDEN
    except Exception:
        pass


def take_snapshot(
    save_root: Path | None,
    snapshot_root: Path,
    *,
    reason: str = "",
    thin: bool = True,
    now: _dt.datetime | None = None,
    force: bool = False,
    protect: Iterable[str] = (),
) -> SnapshotResult:
    """Copy the save folder into a new verified snapshot (if it changed).

    ``force`` makes a new snapshot even when the saves equal the newest one
    (the "Before restore" copy a restore can be undone with). ``thin=False``
    prunes nothing; ``protect`` names snapshots pruning must keep. ``now``
    is the snapshot's time and the time pruning counts ages from.
    """

    def _prune() -> list[str]:
        if not thin:
            return []
        return prune(snapshot_root, now=now, protect=protect)

    if save_root is None or not Path(save_root).is_dir():
        return SnapshotResult("no-saves", "No Stellar Blade save folder was found, so there is nothing to snapshot.")
    save_root = Path(save_root)
    snapshot_root = Path(snapshot_root)
    if _is_inside(snapshot_root, save_root) or _is_inside(save_root, snapshot_root):
        raise SnapshotError("The snapshot folder must be outside the game's save folder.")

    snapshot_root.mkdir(parents=True, exist_ok=True)
    (snapshot_root / MANIFEST_DIR).mkdir(exist_ok=True)
    _hide(snapshot_root / MANIFEST_DIR)
    _clean_leftovers(snapshot_root)

    for _attempt in range(READ_ATTEMPTS):
        files = scan_saves(save_root)
        if not files:
            return SnapshotResult("no-saves", "The save folder is empty, so there is nothing to snapshot.")
        existing = list_snapshots(snapshot_root)
        current = {k: (v["sha256"], v["size"]) for k, v in files.items()}
        previous: dict = {}
        if existing:
            newest = _read_manifest(snapshot_root, existing[0].name) or {}
            previous = {k: (v.get("sha256"), v.get("size")) for k, v in newest.get("files", {}).items()}
            # Identical saves are not copied again, as long as the newest
            # snapshot on disk is still whole (someone may have edited it).
            if not force and previous == current and snapshot_intact(snapshot_root, existing[0].name):
                removed = _prune()
                return SnapshotResult(
                    "unchanged",
                    "Saves unchanged since the last snapshot; no new copy needed.",
                    existing[0],
                    removed,
                )

        stamp = now or _dt.datetime.now().replace(microsecond=0)
        name = _unique_name(snapshot_root, stamp)
        incoming = snapshot_root / f"{INCOMING_PREFIX}{name}-{os.getpid()}"
        incoming.mkdir()
        try:
            for rel, meta in files.items():
                _copy_verified(save_root / rel, incoming / Path(rel), meta["sha256"], meta["size"])
        except _SourceChanged:
            _remove_tree(incoming, snapshot_root)
            continue
        except BaseException:
            try:
                _remove_tree(incoming, snapshot_root)
            except (OSError, SnapshotError):
                pass
            raise

        total = sum(int(v["size"]) for v in files.values())
        manifest = {
            "schema": MANIFEST_SCHEMA,
            "name": name,
            "created": stamp.isoformat(),
            "reason": reason,
            "source": str(save_root),
            "files": files,
            "total_bytes": total,
            # What differs from the snapshot before it (Save history words:
            # "Game saved" or "Settings saved").
            "changed": sorted(k for k in current if previous.get(k) != current[k])
            + sorted(k for k in previous if k not in current),
        }
        _write_json_atomic(_manifest_path(snapshot_root, name), manifest)
        try:
            os.replace(incoming, snapshot_root / name)
        except OSError:
            _manifest_path(snapshot_root, name).unlink(missing_ok=True)
            _remove_tree(incoming, snapshot_root)
            raise
        info = SnapshotInfo(
            name, snapshot_root / name, stamp, len(files), total, reason, snapshot_label(manifest)
        )
        removed = _prune()
        mb = total / (1024 * 1024)
        return SnapshotResult(
            "created",
            f"Save snapshot {name} made and verified ({len(files)} files, {mb:.1f} MB).",
            info,
            removed,
        )
    raise SnapshotError("The game kept writing its saves; the snapshot will be tried again next time.")


def summary_text(snapshots: list[SnapshotInfo], now: _dt.datetime | None = None) -> str:
    "The Support row's value, e.g. ``3 kept, last Sep 28, 1:53 AM``."

    if not snapshots:
        return "None yet"
    newest = snapshots[0].created
    return f"{len(snapshots)} kept, last {newest:%b} {newest.day}, {clock_text(newest)}"


def snapshot_label(manifest: dict) -> str:
    """Plain words for why a snapshot was made ("Game saved", "Before restore")."""

    reason = str(manifest.get("reason") or "")
    if reason == REASON_GAME_SAVED:
        names = [
            Path(str(rel)).name.lower()
            for rel in manifest.get("changed") or []
            if Path(str(rel)).name not in RESTORE_SKIP
        ]
        if names and all("setting" in name for name in names):
            return "Settings saved"
        return "Game saved"
    return REASON_LABELS.get(reason, "Backup")


def clock_text(moment: _dt.datetime) -> str:
    """12-hour clock as players read it: ``7:49 AM``, ``10:10 PM``."""

    return f"{moment:%I:%M %p}".lstrip("0")


def when_text(created: _dt.datetime, now: _dt.datetime | None = None) -> str:
    """``Today, 7:49 AM``, ``Yesterday, 10:10 PM`` or ``Sep 27, 10:10 PM``."""

    today = now.date() if now is not None else _dt.date(*time.localtime()[:3])
    clock = clock_text(created)
    if created.date() == today:
        return f"Today, {clock}"
    if created.date() == today - _dt.timedelta(days=1):
        return f"Yesterday, {clock}"
    return f"{created:%b} {created.day}, {clock}"


def history_rows(snapshots: list[SnapshotInfo], now: _dt.datetime | None = None) -> list[dict]:
    """Support > Save history rows, newest first: name, when and label."""

    return [
        {"name": info.name, "when": when_text(info.created, now), "label": info.label or "Backup"}
        for info in snapshots
    ]


# --------------------------------------------------------------------------
# Putting a snapshot back.


class RestoreRefused(SnapshotError):
    """The restore did not run; no save file was changed."""


# RestoreFailed.outcome: what the save folder holds after a failed restore.
RESTORE_UNCHANGED = "unchanged"  # nothing in the save folder was written
RESTORE_ROLLED_BACK = "rolled_back"  # every file it changed is as it was before
RESTORE_PARTIAL = "partial"  # some files are the restored copy, some are not


class RestoreFailed(SnapshotError):
    """The restore started but could not finish.

    ``outcome`` is RESTORE_UNCHANGED, RESTORE_ROLLED_BACK or RESTORE_PARTIAL
    and ``backup`` names the "Before restore" snapshot ("" if the save folder
    was empty): with RESTORE_PARTIAL, restoring it puts the save back.
    """

    def __init__(self, message: str, outcome: str, backup: str = "") -> None:
        super().__init__(message)
        self.outcome = outcome
        self.backup = backup


@dataclass
class RestoreResult:
    state: str  # "restored"
    message: str
    restored: str
    # The "Before restore" snapshot ("" when the save folder was empty):
    # restoring it is the undo.
    backup: str = ""
    files: list[str] = field(default_factory=list)


def _safe_relative(rel: str) -> Path | None:
    path = Path(rel)
    if path.is_absolute() or path.drive or not path.parts:
        return None
    if any(part in ("", ".", "..") for part in path.parts):
        return None
    return path


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        while chunk := stream.read(CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def _stage_file(source: Path, staged: Path, expected_sha: str) -> None:
    """Copy one snapshot file next to its place in the save folder and prove
    the copy has the snapshot's hash (the save itself is not touched yet)."""

    digest = hashlib.sha256()
    with open(source, "rb") as src, open(staged, "wb") as out:
        while chunk := src.read(CHUNK):
            digest.update(chunk)
            out.write(chunk)
        out.flush()
        os.fsync(out.fileno())
    if digest.hexdigest() != expected_sha or _file_sha256(staged) != expected_sha:
        raise SnapshotError(f"The copy of {source.name} did not match the saved copy")


@dataclass
class _Swap:
    """What a restore has changed in the save folder so far."""

    swapped: list[str] = field(default_factory=list)
    # Files the save folder did not have before (only this restore made them).
    created: list[str] = field(default_factory=list)


def _put_files_back(
    folder: Path,
    plan: list[tuple[str, Path, dict]],
    save_root: Path,
    game_running: Callable[[], bool],
    swap: _Swap,
    *,
    dated_now: bool = True,
) -> None:
    """Stage every file of ``plan`` (verified), then swap them into the save
    folder, recording each one in ``swap``. ``dated_now``: modified time now
    (Steam Cloud keeps the newest); otherwise the time the manifest records
    (putting the save back exactly as it was)."""

    staged: list[tuple[str, Path, Path, dict]] = []
    try:
        for rel, relative, meta in plan:
            dest = save_root / relative
            dest.parent.mkdir(parents=True, exist_ok=True)
            tmp = dest.with_name(f".{dest.name}.restore-{os.getpid()}.tmp")
            _stage_file(folder / relative, tmp, str(meta.get("sha256")))
            staged.append((rel, tmp, dest, meta))
        if game_running():
            raise RestoreRefused(
                "Stellar Blade started while restoring, so nothing was changed. "
                "Close the game and press Restore again."
            )
        for rel, tmp, dest, meta in staged:
            existed = dest.exists()
            os.replace(tmp, dest)
            swap.swapped.append(rel)
            if not existed:
                swap.created.append(rel)
            recorded = meta.get("mtime_ns")
            if dated_now or not isinstance(recorded, int):
                os.utime(dest, None)
            else:
                os.utime(dest, ns=(recorded, recorded))
            if _file_sha256(dest) != meta.get("sha256"):
                raise SnapshotError(f"{dest.name} did not match after the restore")
    finally:
        for _rel, tmp, _dest, _meta in staged:
            try:
                tmp.unlink(missing_ok=True)  # only this restore's own temporary copies
            except OSError:
                pass


def _restore_plan(root: Path, name: str, *, allow_empty: bool = False) -> list[tuple[str, Path, dict]]:
    manifest = _read_manifest(root, name)
    if manifest is None or not snapshot_intact(root, name):
        raise RestoreRefused("That save copy is damaged or missing, so nothing was changed.")
    plan: list[tuple[str, Path, dict]] = []
    for rel, meta in sorted(manifest["files"].items()):
        relative = _safe_relative(str(rel))
        if relative is None or not isinstance(meta, dict):
            raise RestoreRefused("That save copy is damaged or missing, so nothing was changed.")
        if relative.name in RESTORE_SKIP or relative.name.casefold() in RESTORE_SETTINGS_SKIP:
            continue
        plan.append((str(rel), relative, meta))
    if not plan and not allow_empty:
        raise RestoreRefused("That save copy has no save files, so nothing was changed.")
    return plan


def _undo_swap(root: Path, backup: str, swap: _Swap, save_root: Path) -> None:
    """Put back every file a failed restore changed: each one the save
    folder had comes back from the "Before restore" copy with its old
    modified time, and each one it did not have (only the restore made it)
    is removed again. Raises when that cannot be done in full."""

    before = {rel: (relative, meta) for rel, relative, meta in _restore_plan(root, backup, allow_empty=True)} if backup else {}
    changed = [rel for rel in swap.swapped if rel not in swap.created]
    missing = [rel for rel in changed if rel not in before]
    if missing:
        raise SnapshotError(f"no earlier copy of {', '.join(missing)}")
    plan = [(rel, before[rel][0], before[rel][1]) for rel in changed]
    if plan:
        _put_files_back(root / backup, plan, save_root, lambda: False, _Swap(), dated_now=False)
    for rel in swap.created:
        (save_root / Path(rel)).unlink(missing_ok=True)


def restore_snapshot(
    save_root: Path | None,
    snapshot_root: Path,
    name: str,
    *,
    game_running: Callable[[], bool],
    now: _dt.datetime | None = None,
) -> RestoreResult:
    """Put snapshot ``name`` back into the game's save folder.

    Only while the game is closed (``game_running`` is asked before anything
    is written and again right before the swap). The current saves are
    snapshotted first ("Before restore"). Then every file of the snapshot
    (Steam's steam_autocloud.vdf and current graphics settings excepted) is
    copied back as a whole file,
    verified by SHA-256, and dated now. Files in the save folder that the
    snapshot does not have are left alone.

    Raises RestoreRefused when it did not start (nothing changed), and
    RestoreFailed when it could not finish; its ``outcome`` says what the
    save folder holds then: RESTORE_UNCHANGED, RESTORE_ROLLED_BACK (every
    file it had changed is back as it was, from the "Before restore" copy)
    or RESTORE_PARTIAL (that could not be done in full: restoring
    ``backup`` puts the save back).
    """

    if save_root is None:
        raise RestoreRefused("No Stellar Blade save folder was found, so nothing was restored.")
    save_root = Path(save_root)
    root = Path(snapshot_root)
    if not _accepted_snapshot_name(name or ""):
        raise RestoreRefused("That save copy wasn't found, so nothing was changed.")
    if _is_inside(root, save_root) or _is_inside(save_root, root):
        raise RestoreRefused("The save copies must be outside the game's save folder.")
    if game_running():
        raise RestoreRefused("Close Stellar Blade first, then press Restore again. Nothing was changed.")
    plan = _restore_plan(root, name)
    if _manual_snapshot_name(name):
        # Keep the new manual entry within the existing whole-file restore.
        for _rel, relative, _meta in plan:
            destination = save_root / relative
            for candidate in (destination, *destination.parents):
                if os.path.lexists(candidate) and _is_link_or_junction(candidate):
                    raise RestoreRefused("That restore path is a link, so nothing was changed.")
            if destination.exists() and destination.stat().st_nlink != 1:
                raise RestoreRefused("That restore file is linked, so nothing was changed.")

    # 1. The saves as they are now, so the restore can be undone.
    backup = ""
    try:
        if save_root.is_dir():
            before = take_snapshot(save_root, root, reason=REASON_BEFORE_RESTORE, thin=False, now=now, force=True)
            if before.state == "created" and before.snapshot is not None:
                backup = before.snapshot.name
        save_root.mkdir(parents=True, exist_ok=True)
    except (OSError, SnapshotError) as exc:
        raise RestoreFailed(
            f"the current save could not be copied first, so nothing was changed: {exc}", RESTORE_UNCHANGED
        ) from exc

    # 2. Whole files back, each verified, dated now.
    swap = _Swap()
    try:
        _put_files_back(root / name, plan, save_root, game_running, swap)
    except RestoreRefused:
        raise
    except (OSError, SnapshotError) as exc:
        if not swap.swapped:
            raise RestoreFailed(
                f"stopped before any save file changed: {exc}", RESTORE_UNCHANGED, backup
            ) from exc
        try:
            _undo_swap(root, backup, swap, save_root)
        except (OSError, SnapshotError) as undo_exc:
            raise RestoreFailed(
                f"stopped part way ({exc}); putting the changed files back failed too ({undo_exc}); "
                f"{len(swap.swapped)} file(s) are the restored copy",
                RESTORE_PARTIAL,
                backup,
            ) from exc
        raise RestoreFailed(
            f"stopped part way ({exc}); the {len(swap.swapped)} file(s) it had changed were put back",
            RESTORE_ROLLED_BACK,
            backup,
        ) from exc

    try:
        prune(root, now=now, protect={name, backup})
    except (OSError, SnapshotError):
        pass  # the restore itself is done; pruning runs again next time
    return RestoreResult("restored", RESTORED_TEXT, name, backup, swap.swapped)


# --------------------------------------------------------------------------
# Noticing that the game wrote its saves.


def save_signature(save_root: Path | None) -> tuple:
    """Every save file's path, size and modified time: a cheap way to see
    that the game wrote its saves (nothing is opened or read)."""

    if save_root is None:
        return ()
    found: list[tuple[str, int, int]] = []
    try:
        for dirpath, dirnames, filenames in os.walk(save_root, followlinks=False):
            base = Path(dirpath)
            dirnames[:] = [d for d in dirnames if not _is_link_or_junction(base / d)]
            for name in filenames:
                if name in RESTORE_SKIP or name.endswith(".tmp"):
                    continue
                try:
                    st = os.stat(base / name)
                except OSError:
                    continue
                found.append(((base / name).relative_to(save_root).as_posix(), st.st_size, st.st_mtime_ns))
    except OSError:
        return ()
    return tuple(sorted(found))


class SaveWriteWatcher:
    """Says when the game has written its save folder and the writes settled.

    ``poll`` is called every couple of seconds while the game runs. It
    returns True once per change: after the folder's signature changed and
    then stayed the same for ``settle_sec``. ``prime`` takes the current
    folder as already snapshotted (panel start, after a restore); ``retry``
    asks for another snapshot after one could not be made.
    """

    _RETRY = ("retry",)

    def __init__(
        self,
        settle_sec: float = SETTLE_SEC,
        *,
        clock: Callable[[], float] = time.monotonic,
        signature: Callable[[Path | None], tuple] = save_signature,
    ) -> None:
        self._settle_sec = float(settle_sec)
        self._clock = clock
        self._signature = signature
        self._baseline: tuple | None = None
        self._seen: tuple | None = None
        self._changed_at = 0.0

    def prime(self, save_root: Path | None) -> None:
        signature = self._signature(save_root)
        self._baseline = signature
        self._seen = signature
        self._changed_at = self._clock()

    def retry(self) -> None:
        self._baseline = self._RETRY

    def poll(self, save_root: Path | None) -> bool:
        signature = self._signature(save_root)
        now = self._clock()
        if self._baseline is None:
            self._baseline = signature
            self._seen = signature
            self._changed_at = now
            return False
        if signature != self._seen:
            self._seen = signature
            self._changed_at = now
            return False
        if signature and signature != self._baseline and now - self._changed_at >= self._settle_sec:
            self._baseline = signature
            return True
        return False
