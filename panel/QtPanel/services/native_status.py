"""One truthful status vocabulary for every native game-mod card.

Each native (Movement, God Mode, Retry Point, Instant Boss Restart, Items &
Money) writes its own ``key=value`` status file while the game runs. A card
must describe what that file proves *now*, never what local prerequisites
(DLL present, hash pinned, templates loaded) merely allow. Every card
therefore shows exactly one of:

* **Ready** - a fresh status from this game session proves the mod armed on
  the current game build and passed its own safety checks.
* **Waiting for game** - the game is closed, or it is starting and the mod has
  not reported yet.
* **Needs update** - the mod reported that the installed game build is not the
  one it was made for (for example after a Steam update), or the installed mod
  file is a known earlier version that was made for a previous game build.
* **Off** - the mod is not installed or not turned on.
* **Couldn't start safely** - the mod or its file failed a safety check, so it
  stays off.

The copy returned here is plain player language; internal reasons are kept in
``reason`` for the activity log and support reports.
"""

from __future__ import annotations

import hashlib
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, Mapping


NATIVE_READY = "ready"
NATIVE_WAITING = "waiting"
NATIVE_NEEDS_UPDATE = "needs_update"
NATIVE_OFF = "off"
NATIVE_UNSAFE = "unsafe"

NATIVE_STATE_LABELS = {
    NATIVE_READY: "Ready",
    NATIVE_WAITING: "Waiting for game",
    NATIVE_NEEDS_UPDATE: "Needs update",
    NATIVE_OFF: "Off",
    NATIVE_UNSAFE: "Couldn't start safely",
}

GAME_UPDATED_TEXT = "Game updated – this mod needs an update before it can run."
NOT_INSTALLED_TEXT = "Not installed or turned off."
UNTRUSTED_FILE_TEXT = (
    "The installed mod file is not the approved version, so it stays off."
)
GAME_CLOSED_TEXT = "Starts working when Stellar Blade is running."
NO_REPORT_TEXT = "Waiting for the game mod to report in."
UNSAFE_TEXT = "Couldn't start safely, so it stays off. Nothing was changed in your game."
READY_TEXT = "Ready."

# Steam build 24463856 (2026-08-12): SB-Win64-Shipping.exe PE header values.
CURRENT_GAME_TIMESTAMP = 0x6A6A3B74
CURRENT_GAME_IMAGE_SIZE = 0x15981000

STATUS_MAX_BYTES = 64 * 1024
STATUS_FUTURE_TOLERANCE_SEC = 2.0

_BUILD_MISMATCH_KEYS = (
    "result",
    "error",
    "phase",
    "reason",
    "fault",
    "build_status",
    # SBGodNative v1.1.0 names the first failed install check here.
    "install_error",
)
# Values that mean "this is not the game executable the mod was made for".
_BUILD_MISMATCH_VALUES = frozenset({"build_mismatch", "exe_file_size_mismatch"})
_HEX_WORD_RE = re.compile(r"(?<![0-9A-Fa-f])(?:0[xX])?([0-9A-Fa-f]{8})(?![0-9A-Fa-f])")


@dataclass(frozen=True)
class NativeStatusSnapshot:
    """One read of a native status file."""

    values: dict[str, str] = field(default_factory=dict)
    age: float | None = None
    fresh: bool = False
    exists: bool = False


@dataclass(frozen=True)
class NativeVerdict:
    state: str
    detail: str
    reason: str
    # Optional plainer word for a sub-state, for example "Safety check" while
    # God Mode's one-time in-game check runs. It changes only the card text:
    # ``state`` (and so the chip colour and every readiness rule) is unchanged.
    label_text: str = ""

    @property
    def label(self) -> str:
        return self.label_text or NATIVE_STATE_LABELS[self.state]

    @property
    def ready(self) -> bool:
        return self.state == NATIVE_READY

    def as_qml(self) -> dict[str, object]:
        return {
            "state": self.state,
            "label": self.label,
            "detail": self.detail,
            "ready": self.ready,
        }


def parse_status_text(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key and key not in values:
            values[key] = value.strip()
    return values


def read_native_status(
    path: Path,
    *,
    max_age: float,
    now: float | None = None,
) -> NativeStatusSnapshot:
    """Read a bounded status file and judge its freshness by mtime."""
    path = Path(path)
    try:
        stat = path.stat()
    except OSError:
        return NativeStatusSnapshot()
    timestamp = time.time() if now is None else float(now)
    age = timestamp - stat.st_mtime
    fresh = -STATUS_FUTURE_TOLERANCE_SEC <= age <= float(max_age)
    if stat.st_size > STATUS_MAX_BYTES:
        return NativeStatusSnapshot({}, age, False, True)
    try:
        text = path.read_bytes().decode("utf-8", errors="replace")
    except OSError:
        return NativeStatusSnapshot({}, age, False, True)
    values = parse_status_text(text)
    return NativeStatusSnapshot(values, age, bool(fresh and values), True)


def reports_build_mismatch(values: Mapping[str, str]) -> bool:
    """True when the native itself says the game build is not its build."""
    for key in _BUILD_MISMATCH_KEYS:
        value = str(values.get(key, "")).strip().lower().replace("-", "_")
        if value in _BUILD_MISMATCH_VALUES:
            return True
    for key in ("build_match", "build_ok", "exe_build_match"):
        if str(values.get(key, "")).strip() == "0":
            return True
    return False


def _hex_or_int(value: object) -> int | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return int(text, 0)
    except ValueError:
        try:
            return int(text, 16)
        except ValueError:
            return None


def reports_current_build(
    values: Mapping[str, str],
    *,
    timestamp: int = CURRENT_GAME_TIMESTAMP,
    image_size: int = CURRENT_GAME_IMAGE_SIZE,
) -> bool:
    """True only for explicit proof that the native gated on this exact exe.

    Accepted forms (all name both PE values, so a bare ``build_ok=1`` is not
    enough):

    * ``build=0x6A6A3B74/0x15981000`` (any separator, ``0x`` optional)
    * ``exe_timestamp=0x6A6A3B74`` plus ``exe_image_size=0x15981000``
      (``build_timestamp``/``build_image_size`` are accepted aliases)
    """
    words = {int(match, 16) for match in _HEX_WORD_RE.findall(str(values.get("build", "")))}
    if timestamp in words and image_size in words:
        return True
    stamp = _hex_or_int(values.get("exe_timestamp") or values.get("build_timestamp"))
    size = _hex_or_int(values.get("exe_image_size") or values.get("build_image_size"))
    return stamp == timestamp and size == image_size


_HASH_CACHE: dict[tuple[str, int, int], str] = {}


def file_sha256(path: Path) -> str:
    """Lower-case SHA-256, cached by (path, size, mtime) so polls stay cheap."""
    path = Path(path)
    stat = path.stat()
    key = (str(path.resolve()).casefold(), int(stat.st_size), int(stat.st_mtime_ns))
    cached = _HASH_CACHE.get(key)
    if cached is not None:
        return cached
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    value = digest.hexdigest()
    if len(_HASH_CACHE) > 64:
        _HASH_CACHE.clear()
    _HASH_CACHE[key] = value
    return value


def _sha_set(values: Iterable[str]) -> frozenset[str]:
    return frozenset(str(value).strip().lower() for value in values if str(value).strip())


@dataclass(frozen=True)
class NativeInstall:
    """What is on disk for one native: never proof that it runs."""

    installed: bool
    trusted: bool
    superseded: bool
    identity: str


def native_install_identity(
    marker: Path,
    dll: Path,
    trusted_sha256: Iterable[str],
    superseded_sha256: Iterable[str] = (),
) -> NativeInstall:
    """Classify a native's files.

    ``superseded_sha256`` lists earlier approved builds that were made for a
    previous game build. They are never trusted, but the card can say
    "Needs update" instead of calling a known file unsafe.
    """
    allowed = _sha_set(trusted_sha256)
    earlier = _sha_set(superseded_sha256) - allowed
    if not Path(marker).is_file() or not Path(dll).is_file():
        return NativeInstall(False, False, False, "missing")
    try:
        identity = file_sha256(Path(dll))
    except OSError as exc:
        return NativeInstall(True, False, False, f"hash-{type(exc).__name__}")
    return NativeInstall(True, identity in allowed, identity in earlier, identity)


def native_install_state(
    marker: Path,
    dll: Path,
    trusted_sha256: Iterable[str],
) -> tuple[bool, bool, str]:
    """Return ``(installed, trusted, identity)`` for a native's files."""
    install = native_install_identity(marker, dll, trusted_sha256)
    return install.installed, install.trusted, install.identity


def file_is_superseded(path: Path, superseded_sha256: Iterable[str]) -> bool:
    """True when ``path`` is one of the listed earlier builds (read-only)."""
    earlier = _sha_set(superseded_sha256)
    if not earlier:
        return False
    try:
        return Path(path).is_file() and file_sha256(Path(path)) in earlier
    except OSError:
        return False


def native_verdict(
    *,
    installed: bool,
    trusted: bool,
    game_running: bool,
    snapshot: NativeStatusSnapshot,
    interpret: Callable[[Mapping[str, str]], tuple[str, str]],
    waiting_text: str = GAME_CLOSED_TEXT,
    superseded: bool = False,
) -> NativeVerdict:
    """Derive one card state from install truth plus the native's own report.

    ``interpret`` sees only a fresh status from the running game and returns
    ``(state, reason)``; a build mismatch is recognised generically first.
    ``superseded`` marks an untrusted file that is a known earlier build made
    for a previous game build: it reads "Needs update", never "Ready".
    """
    if not installed:
        return NativeVerdict(NATIVE_OFF, NOT_INSTALLED_TEXT, "not-installed")
    if not trusted:
        if superseded:
            return NativeVerdict(NATIVE_NEEDS_UPDATE, GAME_UPDATED_TEXT, "superseded-file")
        return NativeVerdict(NATIVE_UNSAFE, UNTRUSTED_FILE_TEXT, "untrusted-file")
    if not game_running:
        return NativeVerdict(NATIVE_WAITING, waiting_text, "game-closed")
    if not snapshot.fresh or not snapshot.values:
        reason = "status-missing" if not snapshot.exists else "status-stale"
        return NativeVerdict(NATIVE_WAITING, NO_REPORT_TEXT, reason)
    values = snapshot.values
    if reports_build_mismatch(values):
        return NativeVerdict(NATIVE_NEEDS_UPDATE, GAME_UPDATED_TEXT, "build-mismatch")
    try:
        state, reason = interpret(values)
    except Exception as exc:  # a malformed report must never read as ready
        return NativeVerdict(NATIVE_UNSAFE, UNSAFE_TEXT, f"interpret-{type(exc).__name__}")
    if state == NATIVE_READY:
        return NativeVerdict(NATIVE_READY, READY_TEXT, reason or "ready")
    if state == NATIVE_NEEDS_UPDATE:
        return NativeVerdict(NATIVE_NEEDS_UPDATE, GAME_UPDATED_TEXT, reason or "needs-update")
    if state == NATIVE_WAITING:
        return NativeVerdict(NATIVE_WAITING, NO_REPORT_TEXT, reason or "waiting")
    return NativeVerdict(NATIVE_UNSAFE, UNSAFE_TEXT, reason or "unsafe")


def off_verdict(reason: str = "not-installed") -> NativeVerdict:
    return NativeVerdict(NATIVE_OFF, NOT_INSTALLED_TEXT, reason)
