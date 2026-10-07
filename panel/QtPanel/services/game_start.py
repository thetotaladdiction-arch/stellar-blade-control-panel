'Follow game startup until its process opens a window or survives the settling interval. Refuse direct fallback for signed-out Steam. Apply the credentials grace period and ignore log records older than the current Steam process; use native window creation timestamps for age.'































from __future__ import annotations

import ctypes
import re
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

STEAM_SIGNED_OUT_MESSAGE = (
    "Steam is waiting for a sign-in. Choose your account in Steam (or sign in), then press Start game again."
)
GAME_EXITED_MESSAGE = "Stellar Blade closed while it was starting. Press Start game to try again."
# What stays in the top bar after the toast (until the next Start game, the
# game running, or - for Steam - Steam signing in or closing).
STEAM_SIGNED_OUT_NOTE = "Steam is waiting for a sign-in"
GAME_EXITED_NOTE = "The game closed while starting"
_START_NOTES = {STEAM_SIGNED_OUT_MESSAGE: STEAM_SIGNED_OUT_NOTE, GAME_EXITED_MESSAGE: GAME_EXITED_NOTE}


def start_note_for(message: str) -> str:
    """The top bar's lasting note for a Start game result ("" for none)."""
    return _START_NOTES.get(str(message or ""), "")

                                                                            
                                                                            
                                                             
                                                                             
                                                                               
CREDENTIALS_GRACE_SECONDS = 30.0
# The windows Steam shows while it waits (also briefly on an automatic sign-in).
SIGN_IN_WINDOW_TITLES = ("sign in to steam", "steam sign in", "steam login")

_LOGIN_LINE = re.compile(
    r"^\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\].*?SetLoginState:\s*([A-Za-z]+)"
)
# logs/webhelper.txt: "[stamp] SP DesktopLoginWindow_uid0: Created window: ..."
_SIGN_IN_WINDOW_CREATED = re.compile(
    r"^\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\]\s*SP DesktopLoginWindow_uid\d+: Created window"
)


@dataclass(frozen=True)
class SteamLogin:
    """What Steam says about its sign-in right now."""

    running: bool
    # HKCU\\Software\\Valve\\Steam\\ActiveProcess\\ActiveUser of the running
    # Steam: 0 while nobody is signed in; None when it can't be read.
    active_user: int | None = None
    # The last "SetLoginState: X" the running Steam wrote in
    # logs/steamui_login.txt ("" none yet or unknown) and how many seconds ago.
    login_state: str = ""
    state_age: float | None = None
    # A visible "Sign in to Steam" window and for how many seconds it has
    # been open (None when not seen): from Steam's own log when it names the
    # window's creation, else from this panel's first sighting.
    sign_in_window: bool = False
    window_age: float | None = None
    # When Steam created that window (a time.time() value; None when only
    # the panel's own sighting is known).
    window_since: float | None = None

    @property
    def signed_in(self) -> bool:
        return self.running and (bool(self.active_user) or (self.login_state or "").strip() == "Success")

    @property
    def signed_out(self) -> bool:
        if not self.running or self.active_user:
            return False
        state = (self.login_state or "").strip()
        if state == "WaitingForCredentials":
            # Also every automatic sign-in's first seconds (with the window).
            return self.state_age is not None and self.state_age >= CREDENTIALS_GRACE_SECONDS
        if state:
            return False  # signing in, or signed in
        # No state from this Steam (none written yet, or the log can't be
        # read): only a sign-in window that stayed.
        return (self.sign_in_window and self.window_age is not None
                and self.window_age >= CREDENTIALS_GRACE_SECONDS)

    def describe(self) -> str:
        return (
            f"Steam running={self.running} active_user={self.active_user} "
            f"login_state={self.login_state or '(unknown)'} "
            f"age={'?' if self.state_age is None else f'{self.state_age:.0f}s'} "
            f"sign_in_window={self.sign_in_window}"
            + ("" if self.window_age is None
               else f" for {self.window_age:.0f}s"
               + (f" (since {time.strftime('%H:%M:%S', time.localtime(self.window_since))})"
                  if self.window_since is not None else " (seen by the panel)"))
        )


def parse_login_state(text: str, now: float | None = None,
                      since: float | None = None) -> tuple[str, float | None]:
    """The last login state in steamui_login.txt and its age in seconds
    (Steam stamps its log in local time; ``now`` is a time.time() value).
    With ``since`` (when the running Steam started, a time.time() value),
    lines stamped before that second belong to an earlier Steam and are
    ignored."""
    floor = None if since is None else float(int(since))
    for line in reversed((text or "").splitlines()):
        match = _LOGIN_LINE.match(line.strip())
        if not match:
            continue
        try:
            stamp = time.mktime(time.strptime(match.group(1), "%Y-%m-%d %H:%M:%S"))
        except (OverflowError, ValueError):
            if floor is not None:
                continue  # can't tell which Steam wrote it
            return match.group(2), None
        if floor is not None and stamp < floor:
            break  # this line and every earlier one are an earlier Steam's
        return match.group(2), max(0.0, (time.time() if now is None else now) - stamp)
    return "", None


def parse_sign_in_window_since(text: str, since: float | None = None) -> float | None:
    """When the running Steam created its sign-in window, from the tail of
    logs/webhelper.txt (a time.time() value; None when the log does not say).
    With ``since`` (when the running Steam started), a window created before
    that second was an earlier Steam's."""
    floor = None if since is None else float(int(since))
    for line in reversed((text or "").splitlines()):
        match = _SIGN_IN_WINDOW_CREATED.match(line.strip())
        if not match:
            continue
        try:
            stamp = time.mktime(time.strptime(match.group(1), "%Y-%m-%d %H:%M:%S"))
        except (OverflowError, ValueError):
            return None
        if floor is not None and stamp < floor:
            return None
        return stamp
    return None


def _read_tail(path: Path, size: int) -> str:
    with path.open("rb") as handle:
        handle.seek(0, 2)
        end = handle.tell()
        handle.seek(max(0, end - size))
        return handle.read().decode("utf-8", errors="replace")


@dataclass(frozen=True)
class StartWatch:
    """How a start ended: ``running``, ``exited``, ``signed-out`` or
    ``not-started``."""

    outcome: str
    detail: str

    @property
    def ok(self) -> bool:
        return self.outcome == "running"


def follow_game_start(
    game_pid: Callable[[], int],
    has_window: Callable[[int], bool],
    steam_login: Callable[[], SteamLogin],
    timeout: float,
    *,
    settle: float = 12.0,
    relaunch_grace: float = 4.0,
    poll: float = 0.5,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> StartWatch:
    """Follow the game's process from the launch request to a real start.

    ``running`` once the process shows its window, or has stayed up for
    ``settle`` seconds. A process that exits is given ``relaunch_grace``
    seconds for a replacement (Steam may start it again); without one the
    start ended: ``signed-out`` when Steam is signed out, else ``exited``.
    While nothing has started yet, a signed-out Steam ends the wait at once
    (the game can't start until someone signs in).
    """
    start = clock()
    deadline = start + max(poll, float(timeout))
    pid_seen = 0
    first_seen = 0.0
    gone_since: float | None = None
    lived = 0.0
    while True:
        now = clock()
        pid = int(game_pid() or 0)
        if pid:
            if pid != pid_seen:
                pid_seen, first_seen = pid, now
            gone_since = None
            if has_window(pid):
                return StartWatch("running", f"the game's window is open (pid {pid}, {now - first_seen:.1f}s)")
            if now - first_seen >= settle:
                return StartWatch("running", f"the game kept running for {now - first_seen:.1f}s (pid {pid})")
        elif pid_seen:
            if gone_since is None:
                gone_since, lived = now, now - first_seen
            if now - gone_since >= relaunch_grace:
                login = steam_login()
                if login.signed_out:
                    return StartWatch("signed-out", f"the game exited after {lived:.1f}s; {login.describe()}")
                return StartWatch("exited", f"the game exited after {lived:.1f}s without opening its window")
        else:
            login = steam_login()
            if login.signed_out:
                return StartWatch("signed-out", f"no game process; {login.describe()}")
        if now >= deadline:
            break
        sleep(poll)
    if pid_seen and gone_since is None:
        # Still starting at the deadline: the process is alive, which is
        # what the old check called a start; the panel's status poll follows it.
        return StartWatch("running", f"the game is still starting after {clock() - first_seen:.1f}s (pid {pid_seen})")
    if pid_seen:
        login = steam_login()
        if login.signed_out:
            return StartWatch("signed-out", f"the game exited after {lived:.1f}s; {login.describe()}")
        return StartWatch("exited", f"the game exited after {lived:.1f}s without opening its window")
    login = steam_login()
    if login.signed_out:
        return StartWatch("signed-out", f"no game process within {timeout:.0f}s; {login.describe()}")
    return StartWatch("not-started", f"no game process within {timeout:.0f}s")


# -- Windows probes -----------------------------------------------------------


def _visible_window_titles(pid: int | None = None) -> list[str]:
    """Titles of the visible top-level windows (of one process when ``pid``)."""
    if sys.platform != "win32":
        return []
    titles: list[str] = []
    try:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        enum_proc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

        def visit(hwnd, _lparam):
            try:
                if not user32.IsWindowVisible(hwnd):
                    return True
                if pid is not None:
                    owner = ctypes.c_ulong(0)
                    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
                    if int(owner.value) != int(pid):
                        return True
                length = int(user32.GetWindowTextLengthW(hwnd))
                buffer = ctypes.create_unicode_buffer(max(1, length + 1))
                user32.GetWindowTextW(hwnd, buffer, len(buffer))
                titles.append(buffer.value)
            except (OSError, TypeError, ValueError, ctypes.ArgumentError):
                return True  # never raise into EnumWindows; skip this window
            return True

        user32.EnumWindows(enum_proc(visit), 0)
    except (AttributeError, OSError):
        return []
    return titles


def process_has_window(pid: int) -> bool:
    """The process owns a visible top-level window (the game's own window)."""
    return bool(pid) and len(_visible_window_titles(int(pid))) > 0


def process_started_at(pid: int) -> float | None:
    """When the process started, as a time.time() value (None if unknown)."""
    if sys.platform != "win32" or not pid:
        return None
    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.restype = ctypes.c_void_p
        kernel32.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_bool, ctypes.c_ulong]
        kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
        kernel32.GetProcessTimes.argtypes = [ctypes.c_void_p] + [ctypes.POINTER(ctypes.c_ulonglong)] * 4
        handle = kernel32.OpenProcess(0x1000, False, int(pid))  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return None
        try:
            created, exited, kernel, user = (ctypes.c_ulonglong() for _ in range(4))
            if not kernel32.GetProcessTimes(handle, ctypes.byref(created), ctypes.byref(exited),
                                            ctypes.byref(kernel), ctypes.byref(user)):
                return None
        finally:
            kernel32.CloseHandle(handle)
        # FILETIME: 100 ns ticks since 1601-01-01 UTC.
        return (created.value - 116444736000000000) / 10_000_000
    except (AttributeError, OSError, TypeError, ValueError, ctypes.ArgumentError):
        return None


def _steam_active_process() -> tuple[int | None, int | None]:
    """(Steam's pid, ActiveUser) from HKCU\\Software\\Valve\\Steam\\ActiveProcess."""
    if sys.platform != "win32":
        return None, None
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam\ActiveProcess") as key:
            values = {}
            for name in ("pid", "ActiveUser"):
                try:
                    values[name] = int(winreg.QueryValueEx(key, name)[0])
                except (OSError, TypeError, ValueError):
                    values[name] = None
            return values["pid"], values["ActiveUser"]
    except OSError:
        return None, None


# steam pid -> when this panel first saw its sign-in window (clock() value).
_sign_in_window_since: dict[int, float] = {}


def read_steam_login(steam_pid: int, steam_root: Path | None, *,
                     clock: Callable[[], float] = time.monotonic) -> SteamLogin:
    """Steam's sign-in state on this PC (``steam_pid`` 0 = Steam not running)."""
    if not steam_pid:
        _sign_in_window_since.clear()
        return SteamLogin(running=False)
    registry_pid, active_user = _steam_active_process()
    if registry_pid is not None and registry_pid != int(steam_pid):
        active_user = None  # left over from an earlier Steam
    started = process_started_at(int(steam_pid))
    state, age = "", None
    if steam_root is not None:
        try:
            text = _read_tail(Path(steam_root) / "logs" / "steamui_login.txt", 16384)
            state, age = parse_login_state(text, since=started)
        except OSError:
            pass
    titles = {title.strip().casefold() for title in _visible_window_titles()}
    window = any(title in titles for title in SIGN_IN_WINDOW_TITLES)
    for pid in [pid for pid in _sign_in_window_since if pid != int(steam_pid) or not window]:
        del _sign_in_window_since[pid]
    window_age = window_since = None
    if window:
        now = clock()
        window_age = now - _sign_in_window_since.setdefault(int(steam_pid), now)
        if steam_root is not None:
                                                                         
                                                                     
            try:
                created = parse_sign_in_window_since(
                    _read_tail(Path(steam_root) / "logs" / "webhelper.txt", 65536), since=started)
            except OSError:
                created = None
            if created is not None:
                window_since = created
                window_age = max(window_age, time.time() - created)
    return SteamLogin(
        running=True,
        active_user=active_user,
        login_state=state,
        state_age=age,
        sign_in_window=window,
        window_age=window_age,
        window_since=window_since,
    )
