"""One-click bug report (Support > Get help > Create Bug Report).

One zip in the panel's own reports folder (``SBCheatGUI/SupportReports``,
never the desktop) with what the mod author needs to see what happened:

* the panel log, its crash file and the Activity log;
* each game mod's own status, settings and log files
  (``Mods/SB*/*.log``, ``*.txt``, files with ``status`` in the name);
* ``UE4SS.log`` and the UE4SS mod list;
* the newest game crash folder, if there is one (text files only: the
  minidump can hold memory contents, so it stays out);
* the panel settings;
* ``versions.txt``: the panel, game and Steam build ids, and the size and
  SHA-256 of every mod file (panel program, game mods, UE4SS, pak mods).

Personal data is stripped from every text before it is written: the Windows
user name (in paths and on its own) becomes ``<user>``, the PC name
``<pc>``, and Steam ids, e-mail addresses, IP addresses, tokens, passwords
and the crash file's login/machine/account ids are removed. Save files
(``*.sav``) and anything that looks like a credential file are never read.

The builder only reads files and writes the zip; nothing else in the game or
mod folders changes, and earlier reports are never removed (only the
player decides what to delete). Every missing or unreadable file is listed in
``MANIFEST.txt`` instead of stopping the report.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import os
import platform
import re
import subprocess
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

REPORT_PREFIX = "BugReport-"
# Text files are cut to their newest part.
MAX_TEXT_BYTES = 512 * 1024
MAX_HASH_BYTES = 512 * 1024 * 1024
MAX_HASHED_FILES = 3000

# The one line shown after a report is made (and in the Activity log).
SEND_HINT = "Send this file to the mod author with a short description of what happened."

# The panel's own folder holds its source in a developer install, so only
# these files are copied from it (name in the folder -> name in the zip).
PANEL_TEXT_FILES = (
    ("VERSION", "panel/VERSION.txt"),
    ("panel_settings.txt", "panel/panel_settings.txt"),
    ("gui_state.txt", "panel/gui_state.txt"),
    ("panel_renderer_status.txt", "panel/panel_renderer_status.txt"),
    ("panel_running_version.txt", "panel/panel_running_version.txt"),
    ("performance_diagnostics.txt", "panel/performance_diagnostics.txt"),
    ("uncapped_graphics_status.txt", "panel/uncapped_graphics_status.txt"),
    ("hotkeys.ini", "panel/hotkeys.ini"),
    ("sbcheat_heartbeat.txt", "panel/sbcheat_heartbeat.txt"),
    ("item_spawn_status.txt", "panel/item_spawn_status.txt"),
    ("item_probe.txt", "panel/item_probe.txt"),
    ("retry_point_status.txt", "panel/retry_point_status.txt"),
    ("logs/panel.log", "panel/panel.log"),
    ("logs/panel.log.1", "panel/panel.log.1"),
    ("logs/panel-crash.txt", "panel/panel-crash.txt"),
)
# Panel-folder files whose size and SHA-256 go into versions.txt.
PANEL_HASH_SUFFIXES = {".exe", ".dll", ".ps1", ".vbs", ".bat", ".lua", ".ini"}
PANEL_HASH_NAMES = ("VERSION", "PATCH_NOTES.md", "QtPanel/UI_REVISION")
PANEL_HASH_DIRS = ("Scripts", "dlls")

UE4SS_FILES = (
    ("UE4SS-settings.ini", "ue4ss/UE4SS-settings.ini"),
    ("Mods/mods.txt", "ue4ss/mods.txt"),
    ("Mods/mods.json", "ue4ss/mods.json"),
)
UE4SS_HASH_FILES = (
    "../dwmapi.dll",
    "UE4SS.dll",
    "UE4SS-settings.ini",
    "VTableLayout.ini",
    "Mods/mods.txt",
    "Mods/mods.json",
)

_SKIP_DIRS = {
    ".git", ".worktrees", "__pycache__", "node_modules", "build", "dist",
    "SupportReports", "SaveBackups", "backups", "logs",
}
_CRASH_TEXT_SUFFIXES = {".xml", ".runtime-xml", ".log", ".ini", ".txt", ".json"}
_SECRET_NAME = re.compile(
    r"(?i)(token|secret|password|passwd|credential|cookie|rclone|\.env$|api[_-]?key|\.pem$|\.key$)"
)


def _never_read(path: Path) -> bool:
    """Save files and anything named like a credential are never opened."""
    name = path.name
    if path.suffix.casefold() == ".sav" or "savegames" in str(path).casefold():
        return True
    return bool(_SECRET_NAME.search(name))


class Redactor:
    """Removes personal data from report text (see the module docstring)."""

    _USERS_SEGMENT = re.compile(r"(?i)([\\/]Users[\\/])(?!<user>)[^\\/\r\n\"'<>|:*?]+")
    # Quoted keys and values include escapes; unquoted secrets may contain spaces.
    _SECRET_ASSIGNMENT = re.compile(
        r'''(?P<key>"(?:\\.|[^"\\\r\n])*"|'(?:\\.|[^'\\\r\n])*'|\b[A-Za-z0-9_.-]+)'''
        r"(?P<sep>\s*[:=]\s*)"
    )
    _SECRET_VALUE = re.compile(
        r'''"(?:\\.|[^"\\\r\n])*"?|'(?:\\.|[^'\\\r\n])*'?|[^\r\n,;&}]+'''
    )
    _SECRET_KEY = re.compile(
        r"(?i)(?:token|api[_-]?key|apikey|authorization|password|passwd|secret)$"
    )
    _BEARER = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{8,}")
    _STEAM_ID = re.compile(r"(?<!\d)7656119\d{10}(?!\d)")
    _EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+")
    # Ambiguous four-part numbers are versions only in a version field/context.
    _VERSION_FIELD = re.compile(
        r'''(?i)\b(?:[A-Za-z0-9_.-]*version|windows)["']?[ \t]*[:=]?[ \t]*["']?v?'''
        r"(?P<number>\d+(?:\.\d+){3})(?![\d.])"
    )
    _IPV4 = re.compile(
        r"(?<![\d.])(?:(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)\.){3}"
        r"(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)(?![\d.])"
    )
    # Unreal crash context fields that identify the player or the PC.
    _CRASH_IDS = re.compile(
        r"(?is)<(LoginId|EpicAccountId|MachineId|UserName|UserDescription|UserActivityHint"
        r"|ComputerName|UserEmail|EpicEmail|PlayerId|SteamId)>(.*?)</\1>"
    )

    def __init__(self, user_name: str = "", computer_name: str = ""):
        self._words: list[tuple[re.Pattern[str], str]] = []
        for word, marker in ((user_name, "<user>"), (computer_name, "<pc>")):
            word = (word or "").strip()
            # A one- or two-letter name would blank out ordinary words.
            if len(word) >= 3:
                self._words.append((
                    re.compile(r"(?i)(?<![A-Za-z0-9])" + re.escape(word) + r"(?![A-Za-z0-9])"),
                    marker,
                ))

    def text(self, value: str) -> str:
        safe = self._CRASH_IDS.sub(
            lambda m: f"<{m.group(1)}>{'removed' if m.group(2).strip() else ''}</{m.group(1)}>", value
        )
        safe = self._redact_secrets(safe)
        safe = self._BEARER.sub("Bearer <removed>", safe)
        safe = self._STEAM_ID.sub("<steam-id>", safe)
        safe = self._EMAIL.sub("<email>", safe)
        version_spans = {m.span("number") for m in self._VERSION_FIELD.finditer(safe)}
        safe = self._IPV4.sub(
            lambda m: m.group() if m.span() in version_spans else "<ip>", safe
        )
        safe = self._USERS_SEGMENT.sub(r"\1<user>", safe)
        for pattern, marker in self._words:
            safe = pattern.sub(marker, safe)
        return safe

    @classmethod
    def _redact_secrets(cls, text: str) -> str:
        pieces = []
        end = 0
        # Only consume values for secret keys. Other fields can contain nested
        # credentials or be followed by a secret assignment on the same line.
        for match in cls._SECRET_ASSIGNMENT.finditer(text):
            if match.start() < end:
                continue
            key = match.group("key")
            if key.startswith('"'):
                try:
                    name = json.loads(key)
                except ValueError:
                    name = key.strip('"')
            else:
                name = key.strip("'")
            if not cls._SECRET_KEY.search(name):
                continue
            if text[match.end():match.end() + 1] in ("[", "{"):
                value_end = cls._container_end(text, match.end())
                pieces.append(text[end:match.start()])
                pieces.append(key + match.group("sep") + '"<removed>"')
                end = value_end
                continue
            value_match = cls._SECRET_VALUE.match(text, match.end())
            if value_match is None:
                continue
            value = value_match.group()
            quote = value[:1] if value.startswith(('"', "'")) else ""
            closing = quote if quote and len(value) > 1 and value.endswith(quote) else ""
            pieces.append(text[end:match.start()])
            pieces.append(key + match.group("sep") + quote + "<removed>" + closing)
            end = value_match.end()
        pieces.append(text[end:])
        return "".join(pieces)

    @staticmethod
    def _container_end(text: str, start: int) -> int:
        """End of a secret array/object, respecting nested containers and strings."""
        stack = []
        quote = ""
        escaped = False
        for pos in range(start, len(text)):
            char = text[pos]
            if quote:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == quote:
                    quote = ""
            elif char in ('"', "'"):
                quote = char
            elif char in ("[", "{"):
                stack.append("]" if char == "[" else "}")
            elif char in ("]", "}"):
                if not stack or char != stack.pop():
                    return len(text)  # malformed secret: discard the remaining tail
                if not stack:
                    return pos + 1
        return len(text)  # a truncated container must not expose its remaining values


@dataclass(frozen=True)
class BugReportSources:
    """Where the report reads from; the Backend fills it from its own paths."""

    mod_root: Path                      # ue4ss/Mods/SBCheatGUI
    reports_dir: Path                   # the panel's own reports folder
    panel_version: str = "unknown"
    activity_log: Path | None = None
    game_exe: Path | None = None
    app_manifest: Path | None = None
    paks_mods_dir: Path | None = None
    crash_root: Path | None = None      # %LOCALAPPDATA%/SB/Saved/Crashes
    panel_exe: Path | None = None
    extra_texts: dict[str, str] = field(default_factory=dict)

    @property
    def mods_root(self) -> Path:
        return self.mod_root.parent

    @property
    def ue4ss_root(self) -> Path:
        return self.mods_root.parent

    @property
    def win64_dir(self) -> Path:
        return self.ue4ss_root.parent


def default_crash_root() -> Path | None:
    local = os.environ.get("LOCALAPPDATA", "")
    return Path(local) / "SB" / "Saved" / "Crashes" if local else None


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _read_tail(path: Path, limit: int = MAX_TEXT_BYTES) -> str:
    with path.open("rb") as stream:
        head = stream.read(3)
        encoding = "utf-8-sig"
        if head.startswith(b"\xff\xfe"):
            encoding = "utf-16-le"
        elif head.startswith(b"\xfe\xff"):
            encoding = "utf-16-be"
        size = stream.seek(0, os.SEEK_END)
        start = max(0, size - limit)
        if encoding.startswith("utf-16"):
            start += start % 2  # the tail must start at a complete code unit
        stream.seek(start)
        data = stream.read()
    text = data.decode(encoding, errors="replace").removeprefix("\ufeff")
    if start > 0:
        # Drop the cut first line and say that the start is left out.
        text = "[... earlier lines left out ...]\n" + text.split("\n", 1)[-1]
    return text


def _manifest_value(text: str, key: str) -> str:
    match = re.search(r'"' + re.escape(key) + r'"\s+"([^"]*)"', text)
    return match.group(1) if match else ""


def _stamp(ts: float) -> str:
    return _dt.datetime.fromtimestamp(ts).astimezone().strftime("%Y-%m-%d %H:%M")


def newest_crash_dir(crash_root: Path | None) -> Path | None:
    if crash_root is None or not crash_root.is_dir():
        return None
    try:
        dirs = [p for p in crash_root.iterdir() if p.is_dir()]
    except OSError:
        return None
    return max(dirs, key=lambda p: p.stat().st_mtime, default=None)


class _Report:
    def __init__(self, sources: BugReportSources, redactor: Redactor):
        self.sources = sources
        self.redactor = redactor
        self.entries: dict[str, str] = {}
        self.notes: list[str] = []

    def add_text(self, name: str, text: str) -> None:
        self.entries[name] = self.redactor.text(text)

    def add_file(self, path: Path, name: str) -> None:
        if _never_read(path) or not path.is_file():
            return
        try:
            self.add_text(name, _read_tail(path))
        except OSError as exc:
            self.notes.append(f"Could not read {name}: {exc.strerror or exc}")

    # -- collectors ---------------------------------------------------------

    def panel(self) -> None:
        root = self.sources.mod_root
        for rel, name in PANEL_TEXT_FILES:
            self.add_file(root / rel, name)
        if self.sources.activity_log is not None:
            self.add_file(self.sources.activity_log, "panel/activity_log.txt")
        for name, text in self.sources.extra_texts.items():
            self.add_text(f"panel/{name}", text)

    def game_mods(self) -> None:
        mods = self.sources.mods_root
        try:
            folders = sorted(p for p in mods.iterdir() if p.is_dir() and p.name.startswith("SB"))
        except OSError as exc:
            self.notes.append(f"Could not list the game mods folder: {exc.strerror or exc}")
            return
        own = self.sources.mod_root.resolve()
        for folder in folders:
            if folder.resolve() == own:
                continue
            try:
                files = sorted(p for p in folder.iterdir() if p.is_file())
            except OSError:
                continue
            for path in files:
                lower = path.name.casefold()
                if path.suffix.casefold() in {".log", ".txt"} or "status" in lower:
                    self.add_file(path, f"game-mods/{folder.name}/{path.name}")

    def ue4ss(self) -> None:
        root = self.sources.ue4ss_root
        self.add_file(root / "UE4SS.log", "ue4ss/UE4SS.log")
        for rel, name in UE4SS_FILES:
            self.add_file(root / rel, name)

    def last_crash(self) -> None:
        crash = newest_crash_dir(self.sources.crash_root)
        if crash is None:
            self.notes.append("No game crash folder found.")
            return
        self.notes.append(f"Newest game crash: {_stamp(crash.stat().st_mtime)}")
        for path in sorted(p for p in crash.iterdir() if p.is_file()):
            suffix = path.suffix.casefold()
            if path.name.casefold().endswith(".runtime-xml") or suffix in _CRASH_TEXT_SUFFIXES:
                self.add_file(path, f"last-crash/{path.name}")
            else:
                self.notes.append(
                    f"Left out {path.name} from the crash folder (it can hold personal data)."
                )

    # -- versions -----------------------------------------------------------

    def _hash_line(self, path: Path, label: str) -> str:
        try:
            stat = path.stat()
        except OSError:
            return f"{label}  missing"
        if stat.st_size > MAX_HASH_BYTES:
            return f"{label}  {stat.st_size} bytes  (too big to hash)"
        try:
            return f"{label}  {stat.st_size} bytes  sha256 {_sha256(path)}"
        except OSError as exc:
            return f"{label}  {stat.st_size} bytes  (could not read: {exc.strerror or exc})"

    def _walk(self, top: Path) -> list[Path]:
        found: list[Path] = []
        for dirpath, dirnames, filenames in os.walk(top):
            dirnames[:] = sorted(d for d in dirnames if d not in _SKIP_DIRS)
            for name in sorted(filenames):
                path = Path(dirpath) / name
                if not _never_read(path):
                    found.append(path)
        return found

    def mod_files(self) -> list[Path]:
        src = self.sources
        files: list[Path] = []
        root = src.mod_root
        try:
            files += sorted(
                p for p in root.iterdir()
                if p.is_file() and p.suffix.casefold() in PANEL_HASH_SUFFIXES
            )
        except OSError:
            pass
        files += [root / rel for rel in PANEL_HASH_NAMES if (root / rel).is_file()]
        for rel in PANEL_HASH_DIRS:
            if (root / rel).is_dir():
                files += self._walk(root / rel)
        own = root.resolve()
        try:
            folders = sorted(p for p in src.mods_root.iterdir() if p.is_dir() and p.name.startswith("SB"))
        except OSError:
            folders = []
        for folder in folders:
            if folder.resolve() != own:
                files += self._walk(folder)
        if (src.mods_root / "shared").is_dir():
            files += self._walk(src.mods_root / "shared")
        files += [src.ue4ss_root / rel for rel in UE4SS_HASH_FILES if (src.ue4ss_root / rel).is_file()]
        if src.paks_mods_dir is not None and src.paks_mods_dir.is_dir():
            files += self._walk(src.paks_mods_dir)
        unique: dict[str, Path] = {}
        for path in files:
            unique.setdefault(os.path.normcase(os.path.abspath(path)), path)
        return list(unique.values())

    def _relative(self, path: Path) -> str:
        # Win64 for the mods and UE4SS, SB for the pak mods (Content/Paks/~mods).
        win64 = self.sources.win64_dir
        for base in (win64, win64.parent.parent):
            try:
                rel = os.path.relpath(path, base)
            except ValueError:  # another drive
                continue
            if not rel.startswith(".."):
                return Path(rel).as_posix()
        return ""

    def versions(self) -> None:
        src = self.sources
        lines = [
            f"Panel version: {src.panel_version}",
            f"Report made: {_dt.datetime.now().astimezone().strftime('%Y-%m-%d %H:%M:%S')}",
            f"Windows: {platform.version()} ({platform.machine()})",
            f"CPU: {cpu_display_name()}",
        ]
        if src.panel_exe is not None and src.panel_exe.is_file():
            lines.append(self._hash_line(src.panel_exe, f"Panel program: {src.panel_exe.name}"))
        if src.game_exe is not None:
            game = self._hash_line(src.game_exe, f"Game program: {src.game_exe.name}")
            if src.game_exe.is_file():
                game += f"  modified {_stamp(src.game_exe.stat().st_mtime)}"
            lines.append(game)
        if src.app_manifest is not None and src.app_manifest.is_file():
            try:
                acf = src.app_manifest.read_text(encoding="utf-8", errors="replace")
            except OSError:
                acf = ""
            updated = _manifest_value(acf, "LastUpdated")
            lines.append(
                "Steam build id: " + (_manifest_value(acf, "buildid") or "unknown")
                + (f"  target {_manifest_value(acf, 'TargetBuildID')}" if _manifest_value(acf, "TargetBuildID") else "")
                + (f"  updated {_stamp(float(updated))}" if updated.isdigit() else "")
            )
        else:
            lines.append("Steam build id: no Steam manifest found")
        lines += ["", "Mod files (path, size, SHA-256):"]
        files = self.mod_files()
        if len(files) > MAX_HASHED_FILES:
            self.notes.append(f"Listed the first {MAX_HASHED_FILES} of {len(files)} mod files.")
            files = files[:MAX_HASHED_FILES]
        for path in files:
            rel = self._relative(path) or path.name
            lines.append(self._hash_line(path, rel))
        self.add_text("versions.txt", "\n".join(lines) + "\n")

    def manifest(self) -> None:
        lines = [
            "Stellar Blade Mod Suite bug report",
            SEND_HINT,
            "",
            "Personal data is removed: your Windows user name and PC name, Steam ids,",
            "e-mail and IP addresses, tokens and passwords. Save files and the crash",
            "dump are never included.",
            "",
            *self.notes,
            "",
            "Files:",
            *(f"{name}  {len(text.encode('utf-8'))} bytes" for name, text in sorted(self.entries.items())),
        ]
        self.entries["MANIFEST.txt"] = self.redactor.text("\n".join(lines) + "\n")


def cpu_display_name() -> str:
    try:
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0"
        ) as key:
            return str(winreg.QueryValueEx(key, "ProcessorNameString")[0]).strip()
    except (ImportError, OSError):
        return platform.processor() or "unknown"


def build_bug_report(
    sources: BugReportSources,
    *,
    now: _dt.datetime | None = None,
    user_name: str | None = None,
    computer_name: str | None = None,
) -> Path:
    """Write the zip and return its path (see the module docstring)."""
    user = os.environ.get("USERNAME", "") if user_name is None else user_name
    if not user and user_name is None:
        user = Path(os.path.expanduser("~")).name
    pc = os.environ.get("COMPUTERNAME", "") if computer_name is None else computer_name
    report = _Report(sources, Redactor(user, pc))
    for step in (report.panel, report.game_mods, report.ue4ss, report.last_crash, report.versions):
        try:
            step()
        except Exception as exc:  # noqa: BLE001 - one broken part never stops the report
            report.notes.append(f"Part of the report failed ({step.__name__}): {exc}")
    report.manifest()

    reports_dir = sources.reports_dir
    reports_dir.mkdir(parents=True, exist_ok=True)
    stamp = (now or _dt.datetime.now().astimezone()).strftime("%Y%m%d-%H%M%S")
    target = reports_dir / f"{REPORT_PREFIX}{stamp}.zip"
    counter = 2
    while target.exists():
        target = reports_dir / f"{REPORT_PREFIX}{stamp}-{counter}.zip"
        counter += 1
    partial = target.with_suffix(".zip.partial")
    try:
        with zipfile.ZipFile(partial, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
            for name, text in sorted(report.entries.items()):
                archive.writestr(name, text.encode("utf-8"))
        os.replace(partial, target)
    finally:
        if partial.exists():
            partial.unlink()
    return target


def reveal_in_explorer(path: Path, popen=subprocess.Popen) -> None:
    """Open File Explorer with ``path`` selected."""
    # explorer.exe wants "/select," and the quoted path as one argument; a
    # list argument would quote the whole "/select,..." pair.
    popen(f'explorer.exe /select,"{Path(path)}"')
