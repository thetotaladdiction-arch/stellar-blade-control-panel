"""Retry Point (SBRetryPointNative) and the game-mod safety profile.

The file name is historical. Instant Boss Restart is the SBInstantBossRestart
game mod (services/instant_boss_restart.py) since 2.5.504 build 4k; the old
boss paths that lived here (the death-screen picture watcher that pressed R,
the SBBossRetryNative boss auto-return and its trust pins) are gone, and
the profile below switches SBBossRetryNative off with a backup of its marker.
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping

from services.god_service import trusted_native_god
from services.native_status import (
    NATIVE_READY,
    NATIVE_UNSAFE,
    NativeVerdict,
    native_install_state,
    native_verdict,
    read_native_status,
)
from services.process_service import is_pid_alive


# These modules register persistent UE4SS UFunction hooks, poll transient
# objects, or were used only for reverse-engineering. Merely leaving one of the
# failed retry hooks registered across world teardown has crashed Stellar Blade
# 1.4.1, so the external retry profile always disables them. SBBossRetryNative
# (the old boss auto-return) is retired in 2.5.504 build 4k: it failed its own
# start-up check on this game build and never acted, and SBInstantBossRestart
# replaces it. Its DLL stays; only its enabled.txt is moved to a backup.
UNSAFE_IN_PROCESS_MODS = (
    "BossAutoReturn",
    "SBBossRetryNative",
    "SBBossProbe",
    "SBBossTestPilot",
    "SBCheatGUI",
    "SBGlobalProbe",
    "SBReflectionProbe",
    "SBStatProbe",
    "SBUsmapDump",
)
# ``mods.txt`` contains UE4SS built-ins rather than the folder mods above.
# Scope repair to the one built-in this profile has explicitly classified;
# unrelated user entries must never be rewritten merely because they are on.
UNSAFE_BUILTIN_MODS = frozenset({"consoleenablermod"})
NATIVE_GAMEPLAY_BRIDGE = "SBGodNative"
NATIVE_RETRY_POINT_BRIDGE = "SBRetryPointNative"
RETRY_POINT_NATIVE_VERSION = "0.2.3"
                                                                          
                                                                            
                                                                          
                                                                    
RETRY_POINT_NATIVE_VERSIONS = frozenset({"0.1.1", "0.2.1", RETRY_POINT_NATIVE_VERSION})
RETRY_POINT_NATIVE_ARCHITECTURE = (
    "explicit_one_shot_taskgraph_game_thread_game_owned_warp"
)
TRUSTED_RETRY_POINT_NATIVE_SHA256 = frozenset(
    {
                                                                        
                                                                           
                                                         
                                                                          
                                                                           
                                                                          
                                                                           
                                                                   
        "360877da3e235f0aae0c9059404b1e5f19ebbe9a4fcfb6254d6ac4fe7365fdab",
                                                                          
                                                                       
                                                                          
                                                                             
                                                                             
                                                                   
        "30cabb05cb812756a179baaac89843e042bbbc96c8baf310dea43466a79e62ca",
        # v0.1.1 one-shot candidate for game build 0x6A6A3B74/0x15981000.
        # Captures on the certified GameThread and
        # invokes only SBNetworkPlayerController:ServerRequest_WarpPosition;
        # it has no hooks, background UObject reads, or direct location writes.
        "ea319b3996094531b6bee3c421e2eda0f3fa59c8ee1979dfc7608d7e3cd09081",
    }
)
# The native records a command's sequence as seen *before* its freshness and
# panel checks, and binds a panel only after them. A leftover command file from
# an earlier session is therefore seen and rejected with one of these results
# while no panel is bound and no game-thread work has happened.
RETRY_POINT_UNBOUND_REJECTED_RESULTS = frozenset(
    {"command_stale", "panel_gone", "command_invalid"}
)
RETRY_POINT_STATUS_MAX_AGE_SEC = 1.5
# A status written while one Set Point / Return task runs (see
# retry_point_single_task_in_flight); a mismatch only once the same counts
# last this long (RetryPointCountsGuard).
RETRY_POINT_TASK_IN_FLIGHT = "ready-task-in-flight"
RETRY_POINT_COUNTS_SETTLE_SEC = 2.0
_ACTIVE_MOD_LINE = re.compile(r"^(\s*[^;#\s][^:\r\n]*?\s*:\s*)1(\s*(?:[;#].*)?)$")


@dataclass(frozen=True)
class HookFreeProfileResult:
    safe: bool
    changed: bool
    disabled_markers: tuple[str, ...]
    disabled_builtins: tuple[str, ...]
    backups: tuple[str, ...]
    detail: str
    native_bridge_ready: bool = False
    enabled_markers: tuple[str, ...] = ()


def _unique_backup_path(path: Path, stamp: str) -> Path:
    candidate = path.with_name(f"{path.stem}.pre-boss-retry-safe-{stamp}{path.suffix}")
    index = 2
    while candidate.exists():
        candidate = path.with_name(
            f"{path.stem}.pre-boss-retry-safe-{stamp}-{index}{path.suffix}"
        )
        index += 1
    return candidate


def _disabled_mods_text(text: str) -> tuple[str, tuple[str, ...]]:
    disabled: list[str] = []
    output: list[str] = []
    for raw in text.splitlines(keepends=True):
        body = raw.rstrip("\r\n")
        newline = raw[len(body) :]
        match = _ACTIVE_MOD_LINE.fullmatch(body)
        if match:
            name = match.group(1).split(":", 1)[0].strip()
            if name.casefold() in UNSAFE_BUILTIN_MODS:
                disabled.append(name)
                body = f"{match.group(1)}0{match.group(2)}"
        output.append(body + newline)
    return "".join(output), tuple(disabled)


def _native_bridge_paths(root: Path) -> tuple[Path, Path]:
    folder = root / NATIVE_GAMEPLAY_BRIDGE
    return folder / "enabled.txt", folder / "dlls" / "main.dll"


def _native_retry_point_paths(root: Path) -> tuple[Path, Path]:
    folder = root / NATIVE_RETRY_POINT_BRIDGE
    return folder / "enabled.txt", folder / "dlls" / "main.dll"


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _trusted_native_retry_point(dll: Path) -> tuple[bool, str]:
    if not dll.is_file():
        return False, "missing"
    try:
        digest = _sha256_file(dll)
    except OSError as exc:
        return False, f"hash-{type(exc).__name__}"
    return digest in TRUSTED_RETRY_POINT_NATIVE_SHA256, digest


def retry_point_native_ready(mods_root: Path) -> tuple[bool, str]:
    """Return whether the exact trusted Retry Point DLL is installed and enabled."""
    marker, dll = _native_retry_point_paths(Path(mods_root))
    trusted, identity = _trusted_native_retry_point(dll)
    return trusted and marker.is_file(), identity


def _telemetry_int(status: Mapping[str, object], key: str) -> int | None:
    try:
        value = int(str(status.get(key, "")).strip(), 0)
    except (TypeError, ValueError):
        return None
    return value if value >= 0 else None


def retry_point_telemetry_ready(
    status: Mapping[str, object],
    *,
    expected_panel_pid: int | None = None,
    pid_alive: Callable[[int], bool | None] = is_pid_alive,
) -> tuple[bool, str]:
    """Validate the complete fail-closed Retry Point telemetry contract.

    A newly loaded module can be ready before its first explicit action has
    produced a callback. After any submitted action, the callback must be on
    the certified GameThread and TaskGraph lifecycle counts must balance, or
    have exactly the shape of one task still running (submit >= callback >=
    destroy, submit - destroy == 1): the native publishes the three counts
    from separate atomics about twice a second, so a status written while a
    Set Point or Return runs reads n+1/n/n or n+1/n+1/n. That shape is
    reported as ``RETRY_POINT_TASK_IN_FLIGHT``; RetryPointCountsGuard turns
    it into a mismatch once the same counts last RETRY_POINT_COUNTS_SETTLE_SEC.
    Any other imbalance is a mismatch at once.

    From v0.2.3 the panel's watch lease (retry_point_watch.txt) binds the
    panel before any command, and the area checks it asks for are GameThread
    tasks too: with ``world_check_supported=1`` a module bound to this panel
    with no command seen yet is this panel's session, and one bound by an
    earlier panel's watch that has exited is ready to be rebound.

    A module still bound to a panel process that has exited is ready to be
    rebound by this panel's first command (the native drops a dead binding
    before it binds the sender), but only when that process is proven dead,
    every seen command has completed, nothing is queued or running and the
    TaskGraph counts balance. A live or unknown bound process is refused;
    the native's own session and liveness checks stay authoritative.
    """
    if any(
        key in status for key in ("token", "session_token", "bound_panel_token")
    ):
        return False, "contract-mismatch:secret-telemetry"

    if str(status.get("version", "")) not in RETRY_POINT_NATIVE_VERSIONS:
        return False, "contract-mismatch:version"
    required = {
        "architecture": RETRY_POINT_NATIVE_ARCHITECTURE,
        "ready": "1",
        "module_pinned": "1",
        "dispatch_poisoned": "0",
        "hooks": "0",
        "background_uobject_reads": "0",
        "direct_location_writes": "0",
        "save_game_writes": "0",
    }
    for key, expected in required.items():
        if str(status.get(key, "")) != expected:
            return False, f"contract-mismatch:{key}"

    last_exception = _telemetry_int(status, "last_exception")
    if last_exception != 0:
        return False, "contract-mismatch:last_exception"

    last_seen = _telemetry_int(status, "last_seen_command_sequence")
    last_completed = _telemetry_int(status, "last_completed_command_sequence")
    bound_panel_pid = _telemetry_int(status, "bound_panel_pid")
    counts = tuple(
        _telemetry_int(status, key)
        for key in ("submit_count", "callback_count", "destroy_count")
    )
    if last_seen is None or last_completed is None or bound_panel_pid is None:
        return False, "contract-mismatch:panel-session"
    if last_completed > last_seen:
        return False, "contract-mismatch:panel-session"
    rebind = False
    watch_binds = str(status.get("world_check_supported", "")).strip() == "1"
    if last_seen == 0:
        if last_completed != 0:
            return False, "contract-mismatch:panel-session"
        if bound_panel_pid != 0:
            # v0.2.3: bound by a watch lease, before any command.
            if not watch_binds or expected_panel_pid is None or expected_panel_pid <= 0:
                return False, "contract-mismatch:panel-session"
            if bound_panel_pid != expected_panel_pid:
                # An earlier panel's watch: only a proven-dead panel whose
                # checks have all finished can be replaced by this panel's.
                if any(value is None for value in counts) or not (
                    len(set(counts)) == 1 or retry_point_single_task_in_flight(counts)
                ):
                    return False, "contract-mismatch:panel-session"
                try:
                    bound_alive = pid_alive(bound_panel_pid)
                except Exception:  # noqa: BLE001 - liveness unknown -> fail closed
                    bound_alive = None
                if bound_alive is not False:
                    return False, "contract-mismatch:panel-session"
                rebind = True
    elif bound_panel_pid == 0:
        # A leftover command (for example from a panel that has since closed)
        # was seen and rejected before any panel was bound, and nothing ran on
        # the game thread. Without this case the panel waited for a binding
        # that only its own first command can create: a permanent deadlock.
        if (
            last_completed == last_seen
            and str(status.get("result", "")) in RETRY_POINT_UNBOUND_REJECTED_RESULTS
            and counts == (0, 0, 0)
        ):
            return True, "ready-awaiting-first-command"
        return False, "contract-mismatch:panel-session"
    elif expected_panel_pid is None or expected_panel_pid <= 0:
        return False, "contract-mismatch:panel-session"
    elif bound_panel_pid != expected_panel_pid:
        # Bound to another panel. Only a proven-dead earlier panel whose
        # last action fully finished can be replaced by this panel's first
        # command; otherwise this stays refused.
        if not _retry_point_idle_for_rebind(status, last_seen, last_completed, counts):
            return False, "contract-mismatch:panel-session"
        try:
            bound_alive = pid_alive(bound_panel_pid)
        except Exception:  # noqa: BLE001 - liveness unknown -> fail closed
            bound_alive = None
        if bound_alive is not False:
            return False, "contract-mismatch:panel-session"
        rebind = True

    if any(value is None for value in counts):
        return False, "contract-mismatch:taskgraph-counts"
    submit_count, callback_count, destroy_count = counts
    if submit_count == callback_count == destroy_count == 0:
        return True, "ready-awaiting-rebind" if rebind else "ready-awaiting-first-callback"
    in_flight = False
    if submit_count != callback_count or callback_count != destroy_count:
        if not retry_point_single_task_in_flight(counts):
            return False, "contract-mismatch:taskgraph-counts"
        in_flight = True
        if callback_count == 0:
            # The first task of this game session: no callback to certify yet.
            return True, RETRY_POINT_TASK_IN_FLIGHT

    callback_thread = _telemetry_int(status, "callback_thread")
    certified_thread = _telemetry_int(status, "certified_game_thread")
    if (
        callback_thread is None
        or certified_thread is None
        or certified_thread == 0
        or callback_thread != certified_thread
        or str(status.get("callback_on_game_thread", "")) != "1"
    ):
        return False, "contract-mismatch:callback-thread"
    if in_flight:
        return True, RETRY_POINT_TASK_IN_FLIGHT
    return True, "ready-awaiting-rebind" if rebind else "ready-callback-certified"


def retry_point_single_task_in_flight(counts: tuple[int | None, ...]) -> bool:
    """True for TaskGraph counts that are one task still running.

    submit_count, callback_count and destroy_count grow in that order for
    every task, so a status read mid-task is n+1/n/n (submitted) or
    n+1/n+1/n (its callback ran, not yet destroyed). Anything else (a count
    ahead of the one before it, or two tasks outstanding) is a real mismatch.
    """
    if len(counts) != 3 or any(value is None for value in counts):
        return False
    submit_count, callback_count, destroy_count = counts
    return (
        submit_count >= callback_count >= destroy_count
        and submit_count - destroy_count == 1
    )


def retry_point_world_check_in_flight(status: Mapping[str, object]) -> bool:
    'True when the one task in flight can only be an area check (0.2.3).'









    if str(status.get("world_check_supported", "")).strip() != "1":
        return False
    last_seen = _telemetry_int(status, "last_seen_command_sequence")
    last_completed = _telemetry_int(status, "last_completed_command_sequence")
    if last_seen is None or last_completed is None or last_seen != last_completed:
        return False
    return str(status.get("phase", "")).strip() in RETRY_POINT_IDLE_PHASES


class RetryPointCountsGuard:
    """Tells one Retry Point task still running from a real count mismatch.

    ``retry_point_telemetry_ready`` accepts the shape of one running task
    (RETRY_POINT_TASK_IN_FLIGHT). A task finishes within a frame or two, so
    when the very same unbalanced counts are still reported after
    ``settle_sec`` the task is stuck or the counts are wrong: from then on
    the verdict is ``contract-mismatch:taskgraph-counts`` again, until the
    counts move. Any other verdict passes through unchanged and resets it.
    An area check in flight (retry_point_world_check_in_flight) is never
    escalated: the game may never run it as it closes or while it loads.
    """

    def __init__(
        self,
        settle_sec: float = RETRY_POINT_COUNTS_SETTLE_SEC,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._settle_sec = float(settle_sec)
        self._clock = clock
        self._counts: tuple[int | None, ...] | None = None
        self._since = 0.0

    def settle(
        self, status: Mapping[str, object], ready: bool, detail: str
    ) -> tuple[bool, str]:
        if not ready or detail != RETRY_POINT_TASK_IN_FLIGHT:
            self._counts = None
            return ready, detail
        if retry_point_world_check_in_flight(status):
            # An area check the game did not run (yet): the game is closing
            # or loading. It changes nothing, so it is never a fault.
            self._counts = None
            return ready, detail
        counts = tuple(
            _telemetry_int(status, key)
            for key in ("submit_count", "callback_count", "destroy_count")
        )
        now = self._clock()
        if counts != self._counts:
            self._counts = counts
            self._since = now
        if now - self._since >= self._settle_sec:
            return False, "contract-mismatch:taskgraph-counts"
        return True, detail


# Phases in which the native has no action queued, dispatched or awaiting
# verification. Anything else (save_pending, save_captured, return_pending,
# verify_pending, unknown) means work may still be in flight.
RETRY_POINT_IDLE_PHASES = frozenset({"idle", "saved", "returned", "cleared", "fault"})


def _retry_point_idle_for_rebind(
    status: Mapping[str, object],
    last_seen: int,
    last_completed: int,
    counts: tuple[int | None, ...],
) -> bool:
    """True only when the native reports no pending or in-flight work."""
    if last_seen <= 0 or last_completed != last_seen:
        return False
    if any(value is None for value in counts) or len(set(counts)) != 1:
        return False
    if str(status.get("phase", "")) not in RETRY_POINT_IDLE_PHASES:
        return False
    # "busy" means a newer command was refused because an earlier action was
    # still queued, so last_completed can equal last_seen while work runs.
    if str(status.get("result", "")) in {"", "busy", "none"}:
        return False
    return True


def remove_orphaned_retry_point_command(
    command_file: Path,
    *,
    game_running: bool,
    pid_alive: Callable[[int], bool | None] = is_pid_alive,
) -> bool:
    """Delete a Retry Point command whose sending panel no longer exists.

    Runs only while the game is closed (the native is not loaded, so nothing
    can be reading the file). A command from a live process is never touched.
    Returns True when the file was removed.
    """
    if game_running:
        return False
    path = Path(command_file)
    try:
        if not path.is_file() or path.stat().st_size > 4096:
            return False
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    panel_pid = 0
    for line in text.splitlines():
        key, separator, value = line.partition("=")
        if separator and key.strip() == "panel_pid":
            try:
                panel_pid = int(value.strip(), 10)
            except ValueError:
                panel_pid = 0
            break
    if panel_pid > 0:
        alive = pid_alive(panel_pid)
        if alive is None or alive:
            # Unknown or alive: leave it; the native rejects it safely anyway.
            return False
    try:
        path.unlink()
    except FileNotFoundError:
        return False
    except OSError:
        return False
    return True


def remove_finished_retry_point_command(
    command_file: Path,
    *,
    own_pid: int,
    game_running: bool,
    last_completed_sequence: int | None,
) -> bool:
    "Delete this panel's own Retry Point command once it can do nothing more."










    if own_pid <= 0:
        return False
    path = Path(command_file)
    try:
        if not path.is_file() or path.stat().st_size > 4096:
            return False
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    values: dict[str, str] = {}
    for line in text.splitlines():
        key, separator, value = line.partition("=")
        if separator:
            values[key.strip()] = value.strip()
    try:
        panel_pid = int(values.get("panel_pid", ""), 10)
        sequence = int(values.get("seq", ""), 10)
    except ValueError:
        return False
    if panel_pid != own_pid or sequence <= 0:
        return False
    if game_running and (last_completed_sequence is None or sequence > last_completed_sequence):
        return False
    try:
        path.unlink()
    except OSError:
        return False
    return True


RETRY_POINT_AREA_NONE = "none"
RETRY_POINT_AREA_HERE = "here"
RETRY_POINT_AREA_ELSEWHERE = "elsewhere"
RETRY_POINT_AREA_UNCHECKED = "unchecked"


def _world_hash(value: object) -> int:
    try:
        return int(str(value or "").strip(), 16)
    except ValueError:
        return 0


def retry_point_area(status: Mapping[str, object]) -> str:
    """Where the saved point is, as far as the Retry Point game mod checked.

    SBRetryPointNative 0.2.1 learns the loaded area (current_world_hash) only
    while a Set Point or Return runs on the game thread; 0.2.3 also checks it
    every 3 s while this panel keeps its watch lease and a point is saved
    (``retry_point_area_live``). 0 means it has not checked yet in this game
    session. Returns:
    "none": no valid saved point;
    "here": its last check found Eve in the point's area;
    "elsewhere": its last check found her in another area (what a Return
    refused with different_loaded_world leaves behind);
    "unchecked": a point is saved but the area is not known yet (Return
    checks it first and moves nothing if it differs).
    """
    if str(status.get("point_valid", "")).strip() != "1":
        return RETRY_POINT_AREA_NONE
    point = _world_hash(status.get("point_world_hash"))
    current = _world_hash(status.get("current_world_hash"))
    if point == 0 or current == 0:
        return RETRY_POINT_AREA_UNCHECKED
    return RETRY_POINT_AREA_HERE if current == point else RETRY_POINT_AREA_ELSEWHERE


def retry_point_area_live(status: Mapping[str, object]) -> bool:
    """True when the game mod keeps the area current by itself (v0.2.3 world
    checks under this panel's watch lease), so "elsewhere" means Eve is in
    another area now, not only at the last Set Point or Return."""
    return (
        str(status.get("world_check_supported", "")).strip() == "1"
        and str(status.get("world_watch", "")).strip() == "active"
        and _telemetry_int(status, "world_checks") not in (None, 0)
    )


def retry_point_watch_wanted(status: Mapping[str, object]) -> bool:
    """Whether the panel should keep the watch lease fresh: the game mod
    supports area checks (v0.2.3) and a point is saved."""
    return (
        str(status.get("world_check_supported", "")).strip() == "1"
        and str(status.get("point_valid", "")).strip() == "1"
    )


def interpret_retry_point_status(
    status: Mapping[str, object],
    *,
    expected_panel_pid: int | None,
) -> tuple[str, str]:
    ok, detail = retry_point_telemetry_ready(status, expected_panel_pid=expected_panel_pid)
    return (NATIVE_READY if ok else NATIVE_UNSAFE), detail


def retry_point_verdict(
    mods_root: Path,
    *,
    game_running: bool,
    expected_panel_pid: int | None,
    now: float | None = None,
) -> NativeVerdict:
    marker, dll = _native_retry_point_paths(Path(mods_root))
    installed, trusted, _identity = native_install_state(
        marker, dll, TRUSTED_RETRY_POINT_NATIVE_SHA256
    )
    snapshot = read_native_status(
        Path(mods_root) / NATIVE_RETRY_POINT_BRIDGE / "retry_point_status.txt",
        max_age=RETRY_POINT_STATUS_MAX_AGE_SEC,
        now=now,
    )
    return native_verdict(
        installed=installed,
        trusted=trusted,
        game_running=game_running,
        snapshot=snapshot,
        interpret=lambda values: interpret_retry_point_status(
            values, expected_panel_pid=expected_panel_pid
        ),
    )


def inspect_hook_free_retry_profile(mods_root: Path) -> HookFreeProfileResult:
    """Read-only verification for external retry plus the safe native bridge."""
    root = Path(mods_root)
    errors: list[str] = []
    active_markers = tuple(
        name for name in UNSAFE_IN_PROCESS_MODS if (root / name / "enabled.txt").is_file()
    )
    native_marker, native_dll = _native_bridge_paths(root)
    native_trusted, native_identity = trusted_native_god(native_dll)
    native_enabled = native_marker.is_file()
    native_ready = native_trusted and native_enabled
    point_marker, point_dll = _native_retry_point_paths(root)
    point_trusted, point_identity = _trusted_native_retry_point(point_dll)
    point_enabled = point_marker.is_file()
    active_builtins: tuple[str, ...] = ()
    mods_file = root / "mods.txt"
    if mods_file.is_file():
        try:
            _, active_builtins = _disabled_mods_text(
                mods_file.read_text(encoding="utf-8", errors="replace")
            )
        except OSError as exc:
            errors.append(f"mods.txt:{type(exc).__name__}")

    # A standalone external-retry install may not ship the native gameplay
    # bridge. When the bridge DLL is installed, however, a missing marker is a
    # repairable profile fault because live God Mode would otherwise be dead.
    safe = (
        not errors
        and not active_markers
        and not active_builtins
        and (native_trusted == native_enabled)
        and (point_trusted == point_enabled)
    )
    if safe:
        detail = (
            "safe-retry-native-profile-active"
            if native_ready
            else "hook-free-profile-active"
        )
    else:
        problems = errors + [f"active:{name}" for name in active_markers]
        problems.extend(f"active-builtin:{name}" for name in active_builtins)
        if native_enabled and not native_trusted:
            problems.append(f"native-god-untrusted:{native_identity}")
        elif native_trusted and not native_enabled:
            problems.append("native-god-disabled:SBGodNative")
        if point_enabled and not point_trusted:
            problems.append(f"native-retry-point-untrusted:{point_identity}")
        elif point_trusted and not point_enabled:
            problems.append("native-retry-point-disabled:SBRetryPointNative")
        detail = "hook-free-profile-unsafe-" + ",".join(problems)
    return HookFreeProfileResult(
        safe=safe,
        changed=False,
        disabled_markers=active_markers,
        disabled_builtins=active_builtins,
        backups=(),
        detail=detail,
        native_bridge_ready=native_ready,
    )


def enforce_hook_free_retry_profile(mods_root: Path) -> HookFreeProfileResult:
    """Disable unsafe hooks and enable the shutdown-hardened native bridge.

    Only direct children of ``Mods`` are considered, so old release archives
    nested under SBCheatGUI are never touched.  The operation is idempotent and
    verifies the final state before reporting it safe.
    """
    root = Path(mods_root)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    disabled_markers: list[str] = []
    disabled_builtins: tuple[str, ...] = ()
    backups: list[str] = []
    errors: list[str] = []
    enabled_markers: list[str] = []

    for mod_name in UNSAFE_IN_PROCESS_MODS:
        marker = root / mod_name / "enabled.txt"
        if not marker.is_file():
            continue
        try:
            backup = _unique_backup_path(marker, stamp)
            marker.replace(backup)
            disabled_markers.append(mod_name)
            backups.append(str(backup))
        except OSError as exc:
            errors.append(f"{mod_name}:{type(exc).__name__}")

    native_marker, native_dll = _native_bridge_paths(root)
    native_trusted, native_identity = trusted_native_god(native_dll)
    if native_trusted and not native_marker.is_file():
        try:
            native_marker.parent.mkdir(parents=True, exist_ok=True)
            native_marker.write_text("", encoding="ascii")
            enabled_markers.append(NATIVE_GAMEPLAY_BRIDGE)
        except OSError as exc:
            errors.append(f"{NATIVE_GAMEPLAY_BRIDGE}:{type(exc).__name__}")
    elif not native_trusted and native_marker.is_file():
        try:
            backup = _unique_backup_path(native_marker, stamp)
            native_marker.replace(backup)
            disabled_markers.append(NATIVE_GAMEPLAY_BRIDGE)
            backups.append(str(backup))
        except OSError as exc:
            errors.append(f"{NATIVE_GAMEPLAY_BRIDGE}:{type(exc).__name__}")

    point_marker, point_dll = _native_retry_point_paths(root)
    point_trusted, point_identity = _trusted_native_retry_point(point_dll)
    if point_trusted and not point_marker.is_file():
        try:
            point_marker.parent.mkdir(parents=True, exist_ok=True)
            point_marker.write_text("", encoding="ascii")
            enabled_markers.append(NATIVE_RETRY_POINT_BRIDGE)
        except OSError as exc:
            errors.append(f"{NATIVE_RETRY_POINT_BRIDGE}:{type(exc).__name__}")
    elif not point_trusted and point_marker.is_file():
        try:
            backup = _unique_backup_path(point_marker, stamp)
            point_marker.replace(backup)
            disabled_markers.append(NATIVE_RETRY_POINT_BRIDGE)
            backups.append(str(backup))
        except OSError as exc:
            errors.append(f"{NATIVE_RETRY_POINT_BRIDGE}:{type(exc).__name__}")

    mods_file = root / "mods.txt"
    if mods_file.is_file():
        try:
            original = mods_file.read_text(encoding="utf-8", errors="replace")
            updated, disabled_builtins = _disabled_mods_text(original)
            if disabled_builtins:
                backup = _unique_backup_path(mods_file, stamp)
                shutil.copy2(mods_file, backup)
                temporary = mods_file.with_name(f"{mods_file.name}.boss-retry.tmp")
                temporary.write_text(updated, encoding="utf-8")
                os.replace(temporary, mods_file)
                backups.append(str(backup))
        except OSError as exc:
            errors.append(f"mods.txt:{type(exc).__name__}")

    remaining_markers = [
        name for name in UNSAFE_IN_PROCESS_MODS if (root / name / "enabled.txt").is_file()
    ]
    remaining_builtins: tuple[str, ...] = ()
    if mods_file.is_file():
        try:
            _, remaining_builtins = _disabled_mods_text(
                mods_file.read_text(encoding="utf-8", errors="replace")
            )
        except OSError as exc:
            errors.append(f"verify-mods.txt:{type(exc).__name__}")

    native_enabled = native_marker.is_file()
    native_ready = native_trusted and native_enabled
    point_enabled = point_marker.is_file()
    safe = (
        not errors
        and not remaining_markers
        and not remaining_builtins
        and (native_trusted == native_enabled)
        and (point_trusted == point_enabled)
    )
    changed = bool(disabled_markers or disabled_builtins or enabled_markers)
    if safe and changed:
        detail = (
            f"safe-retry-profile-applied-disabled-{len(disabled_markers)}"
            f"-builtins-{len(disabled_builtins)}"
            f"-native-enabled-{len(enabled_markers)}"
        )
    elif safe:
        detail = (
            "safe-retry-native-profile-already-active"
            if native_ready
            else "hook-free-profile-already-active"
        )
    else:
        problems = errors + [f"active:{name}" for name in remaining_markers]
        problems.extend(f"active-builtin:{name}" for name in remaining_builtins)
        if native_enabled and not native_trusted:
            problems.append(f"native-god-untrusted:{native_identity}")
        elif native_trusted and not native_enabled:
            problems.append("native-god-disabled:SBGodNative")
        if point_enabled and not point_trusted:
            problems.append(f"native-retry-point-untrusted:{point_identity}")
        elif point_trusted and not point_enabled:
            problems.append("native-retry-point-disabled:SBRetryPointNative")
        detail = "hook-free-profile-failed-" + ",".join(problems)
    return HookFreeProfileResult(
        safe=safe,
        changed=changed,
        disabled_markers=tuple(disabled_markers),
        disabled_builtins=disabled_builtins,
        backups=tuple(backups),
        detail=detail,
        native_bridge_ready=native_ready,
        enabled_markers=tuple(enabled_markers),
    )
