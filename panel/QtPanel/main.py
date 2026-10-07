import csv
import datetime
import html
import json
import math
import os
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path


_PROCESS_EXTENSION_POINT_DISABLE_POLICY = 6


def apply_windows_extension_point_mitigation(
    platform_name: str | None = None,
    api=None,
) -> tuple[bool, str]:
    """Block legacy process-extension DLL injection before Qt is imported.

    RTSS and capture utilities can inject generic Win32 hooks even when their
    Vulkan implicit layers have been opted out.  Windows' process-local
    ExtensionPointDisable mitigation blocks AppInit DLLs and global Windows
    hooks without changing any setting in the game or another process.

    ``api`` is injectable so the call can be unit-tested without changing the
    test runner's process policy.  It receives ``(policy_id, flags)`` and may
    return either a boolean or ``(boolean, win32_error)``.
    """
    platform_name = sys.platform if platform_name is None else platform_name
    if platform_name != "win32":
        return False, "not-required"

    try:
        if api is None:
            import ctypes

            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            setter = kernel32.SetProcessMitigationPolicy
            setter.argtypes = [ctypes.c_int, ctypes.c_void_p, ctypes.c_size_t]
            setter.restype = ctypes.c_bool

            def api(policy_id: int, flags: int):
                policy = ctypes.c_uint32(flags)
                ok = bool(
                    setter(
                        policy_id,
                        ctypes.byref(policy),
                        ctypes.sizeof(policy),
                    )
                )
                return ok, int(ctypes.get_last_error()) if not ok else 0

        result = api(_PROCESS_EXTENSION_POINT_DISABLE_POLICY, 1)
        if isinstance(result, tuple):
            enabled = bool(result[0])
            error = int(result[1] or 0)
        else:
            enabled = bool(result)
            error = 0
        if enabled:
            return True, "enabled"
        return False, f"failed-win32-{error}" if error else "failed"
    except (AttributeError, OSError, TypeError, ValueError) as exc:
        return False, f"failed-{type(exc).__name__}"


# This must run before any PySide/Qt import.  Calling it from ``main()`` would
# leave a window where delayed injectors can enter while Qt is being imported.
(
    _EXTENSION_POINT_MITIGATION_ENABLED,
    _EXTENSION_POINT_MITIGATION_STATUS,
) = apply_windows_extension_point_mitigation()

from PySide6.QtCore import (
    QObject,
    Property,
    QRect,
    QTimer,
    QThread,
    QThreadPool,
    QUrl,
    Signal,
    QSize,
    Slot,
)
from PySide6.QtGui import (
    QDesktopServices,
    QFont,
    QGuiApplication,
    QIcon,
    QImageReader,
    QSurfaceFormat,
    QWindow,
)
from PySide6.QtQml import QQmlApplicationEngine, QQmlEngine
from PySide6.QtQuick import QQuickWindow
# Load the Controls runtime before QQmlApplicationEngine resolves the
# qtquickcontrols2plugin.  On the standalone Python runtime, the QML plugin is
# loaded from a nested directory and Windows otherwise does not always resolve
# its Qt6QuickControls2 dependency even though the wheel contains it.
import PySide6.QtQuickControls2  # noqa: F401

from infrastructure.runtime import (
    development_qml_requested,
    resolve_qml_path,
    resolve_runtime_paths,
    write_panel_running_version,
    write_qml_source_marker,
)
from infrastructure.panel_log import install_panel_logging
from infrastructure.window_placement import (
    MIN_HEIGHT as WINDOW_MIN_HEIGHT,
    MIN_WIDTH as WINDOW_MIN_WIDTH,
    Box as WindowBox,
    ScreenDesc,
    current_dock_mode,
    dock_rect,
    placement_to_settings,
    restore_placement,
    screen_from_qscreen,
)
from infrastructure.tasks import BackendJob, BackendTaskRunner, FnRunnable
from infrastructure.file_watch import CoalescedFileWatcher
from infrastructure.native_files import replace_file, write_bytes_replace
from infrastructure.system_motion import windows_animations_enabled
from controllers.performance_controller import PerformanceController
from controllers.game_telemetry_controller import GameTelemetryController
from models.catalog_filter import CatalogFilterProxyModel
from models.item_model import ItemListModel

from services.god_service import (
    ENERGY_NEEDS_UPDATE,
    ENERGY_OFF,
    ENERGY_UNSAFE,
    EnergyStatus,
    apply_pending_god_pak_changes,
    energy_native_supported,
    energy_status,
    god_heartbeat_armed,
    god_heartbeat_verdict,
    prepare_live_god_mode,
    read_native_energy_state,
    reset_native_god_state,
    restore_god_pak_backup,
    superseded_native_god,
    sync_god_paks_with_state,
    write_native_energy_state,
    write_native_god_state,
)
from services.native_status import (
    GAME_UPDATED_TEXT,
    NATIVE_NEEDS_UPDATE,
    NATIVE_OFF,
    NATIVE_READY,
    NATIVE_UNSAFE,
    NATIVE_WAITING,
    NativeStatusSnapshot,
    NativeVerdict,
    native_install_state,
    native_verdict,
    read_native_status,
)
from services.health_service import HealthContext, run_health_check
from services.heartbeat_service import clear_stale_heartbeat_files, evaluate_connection
from services.movement_stability import (
    ACCEPTED_VERSIONS as MOVEMENT_NATIVE_VERSIONS,
    EXPECTED_ARCHITECTURE as MOVEMENT_NATIVE_ARCHITECTURE,
    TRUSTED_DLL_SHA256 as MOVEMENT_NATIVE_TRUSTED_SHA256,
    sha256_file,
)
from services.mod_reload_service import bump_mod_reload_seq
from services.bug_report import (
    SEND_HINT as BUG_REPORT_SEND_HINT,
    BugReportSources,
    build_bug_report,
    default_crash_root,
    reveal_in_explorer,
)
from services.update_check import (
    check_due as update_check_due,
    fetch_update_info,
    is_newer as version_is_newer,
    read_update_source,
    safe_download_url,
)
from services.old_ue4ss_files import (
    find_leftovers as find_old_ue4ss_files,
    leftovers_text as old_ue4ss_text,
    move_to_backup as move_old_ue4ss_files,
    win64_dir_for,
)
from services.save_snapshots import (
    REASON_GAME_SAVED,
    RESTORE_PARTIAL,
    RESTORE_ROLLED_BACK,
    RESTORED_TEXT,
    RestoreFailed,
    RestoreRefused,
    SaveWriteWatcher,
    default_save_root,
    default_snapshot_root,
    history_rows as save_history_rows,
    list_snapshots,
    restore_snapshot,
    summary_text as save_snapshot_summary_text,
    take_snapshot,
)
from services.process_service import find_process_id, is_process_running
from services.game_start import (
    GAME_EXITED_MESSAGE,
    STEAM_SIGNED_OUT_MESSAGE,
    STEAM_SIGNED_OUT_NOTE,
    SteamLogin,
    StartWatch,
    follow_game_start,
    process_has_window,
    process_started_at,
    read_steam_login,
    start_note_for,
)
from services.boss_retry_service import (
    RetryPointCountsGuard,
    enforce_hook_free_retry_profile,
    inspect_hook_free_retry_profile,
    remove_finished_retry_point_command,
    remove_orphaned_retry_point_command,
    retry_point_area,
    retry_point_area_live,
    retry_point_native_ready,
    retry_point_telemetry_ready,
    retry_point_watch_wanted,
)
from services.instant_boss_restart import (
    FALLBACK_REASONS as BOSS_FALLBACK_REASONS,
    MOD_FOLDER as BOSS_RESTART_FOLDER,
    STATUS_NAME as BOSS_RESTART_STATUS_NAME,
    IbrFiles,
    IbrInstall,
    ensure_marker as ensure_boss_restart_marker,
    ibr_card,
    write_switch as write_boss_restart_switch,
)
from services.item_policy import (
    load_policy_database,
    policy_database_summary,
)
# Items & Money v0.5: the generated catalog (PLAN C10) and the read-only probe
# that labels every item (PLAN C7).
from services.item_catalog import (
    CATALOG_FILE_NAME as ITEMS_CATALOG_FILE_NAME,
    MONEY_ALIAS,
    MONEY_CONFIRM_AT,
    MONEY_CONFIRM_SEC,
    PanelCatalog,
    TOGGLE_KEYS as ITEMS_TOGGLE_KEYS,
    catalog_paths,
    display_rows,
    load_catalog,
)
from services.item_probe import (
    CHIP_KINDS,
    CHIP_LABELS,
    CHIP_READY,
    DLC_REASON,
    PROBE_MAX_LISTED,
    PROBE_STATUS_STATES,
    PROBE_REFRESH_SEC,
    PROBE_REQUEST_FILE,
    PROBE_REQUEST_TIMEOUT_SEC,
    PROBE_RESULT_FILE,
    PROBE_RESULT_MAX_BYTES,
    ProbeEntry,
    ProbeError,
    format_probe_request,
    item_chip,
    parse_probe_result,
    per_add_limit,
    state_reason,
)
# Items & Money uses only the audited Live Add v3 route. The retired
# SBItemDropNative route is never driven, pinned or enabled by this panel.
from services.item_live_add_service import (
    LIVE_ADD_LEASE_FILE,
    LIVE_ADD_LEASE_HELD,
    LIVE_ADD_LEASE_OFF,
    LIVE_ADD_LEASE_RENEW_SEC,
    LIVE_ADD_LEASE_SETTLE_SEC,
    LIVE_ADD_LEASE_SETTLING,
    LIVE_ADD_LEASE_STALE_GAP_SEC,
    LIVE_ADD_LEGACY_MAX_QTY,
    LIVE_ADD_NATIVE_STATUS_FILE,
    LIVE_ADD_NATIVE_STATUS_MAX_AGE_SEC,
    PROBE_CAPABLE_LIVE_ADD_NATIVE_SHA256,
    build_live_add_updates,
    evaluate_live_add,
    format_live_add_lease,
    friendly_live_add_result,
    installed_live_add_native_protocol,
    is_safe_refusal,
    live_add_route_protocol,
    live_add_status_matches,
    native_probe_capable,
    result_outcome_unknown,
    trusted_live_add_protocol,
)
from services.native_status import file_sha256


APP_DISPLAY_NAME = "Stellar Blade Mod Suite"
LEGACY_APP_DISPLAY_NAME = "Stellar Blade Control Panel"
MOVEMENT_HEARTBEAT_FRESH_SEC = 2.0
                                                                              
                                                                              
                                                                          
                                                                          
                
                                                                    
PATCH_NOTES_VERSION_RE = re.compile(r"^#\s*v(\d[\w.]*)\s*(?:-\s*(\d{4}-\d{2}-\d{2}))?")
RETRY_POINT_SAVED_TEXT = "Point saved. Return works only in the area where you set it."
RETRY_POINT_KEPT_TEXT = "A point is saved. Return works only in the area where you set it."
# Answers that are news once (a notice), not a state for the card line.
RETRY_POINT_SUCCESS_RESULTS = frozenset({"saved", "returned_verified", "already_at_point"})
                                                                        
                                                                           
                                                               
RETRY_POINT_RETURN_SUCCESS_RESULTS = frozenset({"returned_verified", "already_at_point"})
RETRY_POINT_SUCCESS_LINE_SEC = 15.0
# Save history: how often the save folder's file times are looked at while
# the game runs, and for how long after it closes (it saves on the way out).
SAVE_WATCH_INTERVAL_MS = 2000
SAVE_WATCH_AFTER_CLOSE_SEC = 60.0
SAVE_HISTORY_LINE = "Made a choice you regret? Close the game, pick a time from before it, press Restore."
SAVE_UNDONE_TEXT = "Undone. Your save is back to how it was before the restore. Start the game and load your save."
# A restore that could not finish: the words follow what the save folder
# holds then (services/save_snapshots.RestoreFailed.outcome).
SAVE_RESTORE_UNCHANGED_TEXT = "Couldn't restore that copy, so your save wasn't changed."
SAVE_RESTORE_ROLLED_BACK_TEXT = "Couldn't finish the restore, so your save was put back as it was."
SAVE_RESTORE_PARTIAL_TEXT = (
    "The restore stopped part way and couldn't put your save back by itself. "
    "With the game closed, press Undo restore to get it back."
)
SAVE_RESTORE_PARTIAL_NO_BACKUP_TEXT = (
    "The restore stopped part way. With the game closed, press Restore again."
)
SAVE_RESTORE_UNKNOWN_TEXT = (
    "The restore ran into a problem and may not have finished. If your save doesn't load, "
    "restore the newest “Before restore” copy with the game closed."
)
RETRY_POINT_ELSEWHERE_TEXT = (
    "The last Return found Eve in another area. Go back to where you set the point, "
    "then press Return again."
)
# Retry Point game mod 0.2.3 checks the loaded area every 3 s while a point is
# saved, so the card can say so before Return is pressed.
RETRY_POINT_ELSEWHERE_NOW_TEXT = "Eve is in another area now. Return works in the area where you set the point."
# How often the panel renews the game mod's 5 s watch lease.
RETRY_POINT_WATCH_REFRESH_SEC = 2.0
# The main window is titled "Stellar Blade Mod Suite v<version>" once QML
# loads; before that (or without a version) it carries the bare name.
PANEL_WINDOW_TITLE_PREFIXES = (APP_DISPLAY_NAME + " v", LEGACY_APP_DISPLAY_NAME + " v")
_WS_EX_TOOLWINDOW = 0x00000080
_WS_EX_TRANSPARENT = 0x00000020
_WS_EX_NOACTIVATE = 0x08000000
_GWL_EXSTYLE = -20
ISSUE_LOG_MAX_BYTES = 256 * 1024
PERFORMANCE_OVERLAY_SIZES = ("compact", "standard", "large")


def is_panel_main_window(title: str, ex_style: int) -> bool:
    """Whether a top-level window is this app's main panel window.

    Tool, click-through, and no-activate windows (the in-game metrics HUD)
    are never the panel, whatever their title says.
    """
    if int(ex_style) & (_WS_EX_TOOLWINDOW | _WS_EX_TRANSPARENT | _WS_EX_NOACTIVATE):
        return False
    text = (title or "").strip().casefold()
    if not text:
        return False
    if text in (APP_DISPLAY_NAME.casefold(), LEGACY_APP_DISPLAY_NAME.casefold()):
        return True
    return any(text.startswith(prefix.casefold()) for prefix in PANEL_WINDOW_TITLE_PREFIXES)


# Movement heartbeat errors that only mean "no playable character or camera
# yet" (menus, loading) or "no fresh request"; they are waiting, not faults.
MOVEMENT_WAITING_ERRORS = frozenset(
    {
        "no-pawn",
        "no-camera",
        "no-manualcamerafov",
        "no-charactermovement",
        "no-jumpzvelocity",
        "state-missing",
        "state-stale",
        "panel-gone",
    }
)


def interpret_movement_heartbeat(heartbeat) -> tuple[str, str]:
    """Card state for a fresh SBMovementNative heartbeat from the running game."""
    if str(heartbeat.get("version", "")) not in MOVEMENT_NATIVE_VERSIONS:
        return NATIVE_UNSAFE, "safety-check-failed:version"
    required = {
        "architecture": MOVEMENT_NATIVE_ARCHITECTURE,
        "ready": "1",
        "module_pinned": "1",
        "dispatch_poisoned": "0",
        "last_exception": "0x00000000",
    }
    for key, expected in required.items():
        if str(heartbeat.get(key, "")) != expected:
            return NATIVE_UNSAFE, f"safety-check-failed:{key}"
    error = str(heartbeat.get("error", "")).strip().lower()
    if error in MOVEMENT_WAITING_ERRORS:
        return NATIVE_WAITING, f"error-{error}"
    if error != "none":
        return NATIVE_UNSAFE, f"error-{error or 'missing'}"
    counts = tuple(
        _native_integer(heartbeat, key)
        for key in ("submit_count", "callback_count", "destroy_count")
    )
    if any(value is None for value in counts):
        return NATIVE_UNSAFE, "safety-check-failed:counts"
    if counts[0] != counts[1] or counts[1] != counts[2]:
        # One request is on its way to the game thread right now.
        return NATIVE_WAITING, "request-in-flight"
    if counts[0] == 0:
        return NATIVE_READY, "ready-awaiting-first-request"
    ready, _movement, _fov = native_movement_live_state(
        heartbeat, game_running=True, heartbeat_fresh=True
    )
    return (NATIVE_READY, "ready-callback-certified") if ready else (
        NATIVE_UNSAFE,
        "safety-check-failed:callback-thread",
    )


def normalize_overlay_size(value: str) -> str:
    value = str(value or "").strip().casefold()
    return value if value in PERFORMANCE_OVERLAY_SIZES else "standard"


def format_issue_line(level: str, area: str, message: str, now: float | None = None) -> str:
    """One activity-log line with a full local ISO date and time."""
    stamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(time.time() if now is None else now))
    return f"[{stamp}] {level} | qml-{area} | {message}"


_ISSUE_LINE = re.compile(r"^(\[[^\]]*\])\s+([A-Z]+)\s+\|\s+[^|]*?\s+\|\s?(.*)$")


def _strip_issue_detail(message: str) -> str:
    """``message [technical detail]`` -> ``message`` (_append_issue's form)."""
    text = message.rstrip()
    if not text.endswith("]"):
        return text
    depth = 0
    for index in range(len(text) - 1, -1, -1):
        char = text[index]
        if char == "]":
            depth += 1
        elif char == "[":
            depth -= 1
            if depth == 0:
                if index > 0 and text[index - 1] == " " and text[:index].strip():
                    return text[:index].rstrip()
                return text
    return text


def plain_issue_line(line: str) -> str:
    "One activity-log line in plain words for Support's Activity log:"





    match = _ISSUE_LINE.match(line)
    if not match:
        return line
    stamp, _level, message = match.groups()
    return f"{_plain_stamp(stamp)} {_strip_issue_detail(message)}"


def _plain_stamp(stamp: str) -> str:
    "``[2026-09-29 19:51:00]`` -> ``[Sep 29, 7:51 PM]``, and an old version's ``[13:22:44]`` ->"

    text = stamp.strip("[]")
    for pattern, dated in (("%Y-%m-%d %H:%M:%S", True), ("%H:%M:%S", False)):
        try:
            moment = time.strptime(text, pattern)
        except ValueError:
            continue
        clock = time.strftime("%I:%M %p", moment).lstrip("0")
        return f"[{time.strftime('%b', moment)} {moment.tm_mday}, {clock}]" if dated else f"[{clock}]"
    return stamp


def plain_issue_log(text: str) -> str:
    return "\n".join(plain_issue_line(line) for line in text.split("\n")) if text else ""


def rotate_issue_log(path: Path, max_bytes: int = ISSUE_LOG_MAX_BYTES) -> bool:
    """Keep the activity log bounded: move a full log to ``<name>.1.txt``.

    One previous generation is kept; an older ``.1`` file is replaced.
    """
    try:
        if path.stat().st_size < max_bytes:
            return False
    except OSError:
        return False
    rotated = path.with_name(f"{path.stem}.1{path.suffix}")
    try:
        os.replace(path, rotated)
    except OSError:
        return False
    return True


def trusted_native_movement(mod_root: Path) -> tuple[bool, str]:
    """Require the exact audited SBMovementNative DLL and its enable marker."""
    native_root = Path(mod_root).parent / "SBMovementNative"
    marker = native_root / "enabled.txt"
    dll = native_root / "dlls" / "main.dll"
    if not marker.is_file():
        return False, "disabled"
    if not dll.is_file():
        return False, "missing"
    try:
        digest = sha256_file(dll)
    except OSError as exc:
        return False, f"hash-{type(exc).__name__}"
    return digest.upper() in MOVEMENT_NATIVE_TRUSTED_SHA256, digest


def _native_integer(values: dict[str, str], key: str, *, base: int = 10) -> int | None:
    try:
        value = int(str(values.get(key, "")).strip(), base)
    except (TypeError, ValueError):
        return None
    return value if value >= 0 else None


def native_movement_live_state(
    heartbeat: dict[str, str],
    *,
    game_running: bool,
    heartbeat_fresh: bool,
) -> tuple[bool, bool, bool]:
    """Return build-ready, movement-applied, and FOV-applied proof."""
    if not game_running or not heartbeat_fresh:
        return False, False, False
    if str(heartbeat.get("version", "")) not in MOVEMENT_NATIVE_VERSIONS:
        return False, False, False
    required = {
        "architecture": MOVEMENT_NATIVE_ARCHITECTURE,
        "ready": "1",
        "module_pinned": "1",
        "dispatch_poisoned": "0",
        "last_exception": "0x00000000",
        "error": "none",
    }
    if any(str(heartbeat.get(key, "")) != value for key, value in required.items()):
        return False, False, False

    counts = tuple(
        _native_integer(heartbeat, key)
        for key in ("submit_count", "callback_count", "destroy_count")
    )
    if any(value is None for value in counts):
        return False, False, False
    submit_count, callback_count, destroy_count = counts
    if submit_count == callback_count == destroy_count == 0:
        return True, False, False
    if submit_count != callback_count or callback_count != destroy_count:
        return False, False, False

    callback_thread = _native_integer(heartbeat, "callback_thread")
    certified_thread = _native_integer(heartbeat, "certified_game_thread")
    callback_certified = bool(
        callback_thread
        and callback_thread == certified_thread
        and heartbeat.get("callback_on_game_thread") == "1"
    )
    if not callback_certified:
        return False, False, False
    request_fresh = heartbeat.get("request_fresh") == "1"
    movement_applied = bool(
        request_fresh
        and heartbeat.get("enabled") == "1"
        and heartbeat.get("movement_applied") == "1"
    )
    fov_applied = bool(request_fresh and heartbeat.get("fov_applied") == "1")
    return True, movement_applied, fov_applied


def native_god_protection_applied(
    heartbeat: dict[str, str],
    *,
    game_running: bool,
    native_ready: bool,
    heartbeat_fresh: bool,
) -> bool:
    """Accept ACTIVE as soon as the native itself reports God armed.

    SBGodNative arms (``god_armed=1``) only after its runtime self-check
    passed and it verified Eve's identity; from that moment every hit on Eve
    is blocked, so the chip and HUD say "Active" right away instead of
    waiting for a first blocked hit (``blocks`` > 0). The heartbeat must still
    be fresh, from this game process, prove the hooks are installed on this
    exact game build and name the verified player (``guid`` or ``actorptr``).
    ``godlive`` only echoes the panel's desired state, and ``learned``/``blocks``
    can stay nonzero after the native disarms, so they are never proof.
    """
    if not game_running or not native_ready or not heartbeat_fresh:
        return False
    if heartbeat.get("godlive") != "1":
        return False
    if not god_heartbeat_armed(heartbeat):
        return False
    beat = _native_integer(heartbeat, "beat")
    actor = _native_integer(heartbeat, "actorptr", base=16)
    guid = _native_integer(heartbeat, "guid")
    return bool(beat and (actor or guid))

def set_windows_app_user_model_id() -> None:
    """Required on Windows so taskbar uses our EXE icon instead of generic python/bootloader."""
    if sys.platform != "win32":
        return
    try:
        import ctypes

        app_id = "SBCheatGUI.StellarBladeModSuite.1"
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(app_id)
    except Exception:
        pass


_PANEL_MUTEX_HANDLE = None
_PANEL_MUTEX_NAME = "Global\\StellarBlade.ControlPanel"
_SUPPORTED_RENDERERS = {"vulkan", "d3d11", "d3d12", "opengl", "software"}
_DISABLED_GRAPHICS_HOOKS: list[str] = []
_RENDERER_SELECTION_REASON = "not selected"
_RENDERER_SAFE_MODE_REASON = ""


def isolate_panel_graphics_process() -> list[str]:
    """Keep third-party capture/overlay layers out of this panel where possible.

    These layers are useful inside games, but injecting several of them into a
    Qt Quick utility process caused access violations in Overwolf and NVIDIA
    graphics modules. Each registered Vulkan layer advertises its own official
    opt-out environment variable. Generic injectors such as RTSS additionally
    require a per-application exclusion profile, which the support helper
    installs. These settings do not touch the game process, renderer
    synchronization, or frame pacing.
    """
    global _DISABLED_GRAPHICS_HOOKS

    # Stable opt-outs cover the common layers even if registry discovery is
    # unavailable or a launcher updates its installation directory.
    opt_outs: dict[str, str] = {
        "DISABLE_VULKAN_OW_OVERLAY_LAYER": "1",
        "DISABLE_VULKAN_OW_OBS_CAPTURE": "1",
        "DISABLE_RTSS_LAYER": "1",
        "DISABLE_VULKAN_OBS_CAPTURE": "1",
        "DISABLE_VK_LAYER_VALVE_steam_overlay_1": "1",
        "DISABLE_VK_LAYER_VALVE_steam_fossilize_1": "1",
        "EOS_OVERLAY_DISABLE_VULKAN_WIN64": "1",
    }
    layer_names: set[str] = set()

    if sys.platform == "win32":
        try:
            import winreg

            registry_locations = (
                (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Khronos\Vulkan\ImplicitLayers"),
                (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Khronos\Vulkan\ImplicitLayers"),
            )
            graphics_hook_tokens = (
                "overlay",
                "capture",
                "hook",
                "overwolf",
                "obs",
                "rtss",
                "steam",
                "wallpaper",
                "eos",
            )
            for hive, key_name in registry_locations:
                try:
                    key = winreg.OpenKey(hive, key_name, 0, winreg.KEY_READ)
                except OSError:
                    continue
                with key:
                    index = 0
                    while True:
                        try:
                            manifest_path, _enabled, _kind = winreg.EnumValue(key, index)
                        except OSError:
                            break
                        index += 1
                        try:
                            manifest = json.loads(
                                Path(manifest_path).read_text(encoding="utf-8-sig")
                            )
                            layer = manifest.get("layer", {})
                            identity = " ".join(
                                str(layer.get(field, ""))
                                for field in ("name", "description", "library_path")
                            ).casefold()
                            if not any(token in identity for token in graphics_hook_tokens):
                                continue
                            name = str(layer.get("name", "graphics hook")).strip()
                            if name:
                                layer_names.add(name)
                            for env_name, env_value in layer.get(
                                "disable_environment", {}
                            ).items():
                                if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,95}", str(env_name)):
                                    opt_outs[str(env_name)] = str(env_value)
                        except (OSError, UnicodeError, json.JSONDecodeError, TypeError):
                            continue
        except (ImportError, OSError):
            pass

    for env_name, env_value in opt_outs.items():
        os.environ[env_name] = env_value

    _DISABLED_GRAPHICS_HOOKS = sorted(layer_names) or [
        "Overwolf/OBS/RTSS/Steam/EOS overlay layers"
    ]
    return list(_DISABLED_GRAPHICS_HOOKS)


def loaded_graphics_hook_modules() -> list[str]:
    """Return known overlay/capture DLLs that still entered this process."""
    if sys.platform != "win32":
        return []
    try:
        import ctypes
        from ctypes import wintypes

        class MODULEENTRY32W(ctypes.Structure):
            _fields_ = [
                ("dwSize", wintypes.DWORD),
                ("th32ModuleID", wintypes.DWORD),
                ("th32ProcessID", wintypes.DWORD),
                ("GlblcntUsage", wintypes.DWORD),
                ("ProccntUsage", wintypes.DWORD),
                ("modBaseAddr", ctypes.POINTER(ctypes.c_byte)),
                ("modBaseSize", wintypes.DWORD),
                ("hModule", wintypes.HMODULE),
                ("szModule", wintypes.WCHAR * 256),
                ("szExePath", wintypes.WCHAR * 260),
            ]

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
        kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
        kernel32.Module32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(MODULEENTRY32W)]
        kernel32.Module32FirstW.restype = wintypes.BOOL
        kernel32.Module32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(MODULEENTRY32W)]
        kernel32.Module32NextW.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]

        snapshot = kernel32.CreateToolhelp32Snapshot(0x00000008 | 0x00000010, 0)
        if snapshot in (None, wintypes.HANDLE(-1).value):
            return []
        hook_tokens = (
            "owclient",
            "ow-graphics",
            "rtssvk",
            "rtsshooks",
            "graphics-hook",
            "nvspcap",
            "gameoverlayrenderer",
            "steamoverlayvulkan",
            "eosovh",
        )
        matches: set[str] = set()
        try:
            entry = MODULEENTRY32W()
            entry.dwSize = ctypes.sizeof(entry)
            present = bool(kernel32.Module32FirstW(snapshot, ctypes.byref(entry)))
            while present:
                module_name = str(entry.szModule).strip()
                if any(token in module_name.casefold() for token in hook_tokens):
                    matches.add(module_name)
                present = bool(kernel32.Module32NextW(snapshot, ctypes.byref(entry)))
        finally:
            kernel32.CloseHandle(snapshot)
        return sorted(matches, key=str.casefold)
    except (AttributeError, OSError, TypeError, ValueError):
        return []


_PANEL_GRAPHICS_FAULT_TOKENS = (
    "nvoglv64",
    "owclient",
    "nvspcap",
    "rtsshooks",
    "rtssvk",
    "rtss",
)


def recent_panel_graphics_crash_reason(
    roots: list[Path] | tuple[Path, ...] | None = None,
    now: float | None = None,
    max_age_hours: float = 72.0,
    newer_than: float | None = None,
) -> str:
    """Return a concise reason for a recent graphics-hook panel WER.

    Only reports whose application is the packaged control panel and whose
    *faulting module* matches a known live-panel crash family are considered.
    Merely having a graphics DLL loaded is not enough to trigger safe mode.
    """
    if sys.platform != "win32" and roots is None:
        return ""
    if roots is None:
        program_data = Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData"))
        local_data = Path(os.environ.get("LOCALAPPDATA", ""))
        roots = (
            program_data / "Microsoft" / "Windows" / "WER" / "ReportArchive",
            program_data / "Microsoft" / "Windows" / "WER" / "ReportQueue",
            local_data / "Microsoft" / "Windows" / "WER" / "ReportArchive",
            local_data / "Microsoft" / "Windows" / "WER" / "ReportQueue",
        )

    now = time.time() if now is None else float(now)
    cutoff = now - max(0.0, float(max_age_hours)) * 3600.0
    if newer_than is not None:
                                                                          
                                                                              
                                                                     
        cutoff = max(cutoff, float(newer_than))
    candidates: list[tuple[float, Path]] = []
    for root in roots:
        try:
            reports = list(Path(root).glob("AppCrash_Stellar Blade Co_*/Report.wer"))
            reports += list(Path(root).glob("AppCrash_Stellar Blade Mo_*/Report.wer"))
            for report in reports:
                try:
                    modified = report.stat().st_mtime
                except OSError:
                    continue
                if modified >= cutoff:
                    candidates.append((modified, report))
        except OSError:
            continue

    for modified, report in sorted(candidates, key=lambda pair: pair[0], reverse=True):
        try:
            text = report.read_text(encoding="utf-16", errors="replace")
            if (
                f"{APP_DISPLAY_NAME}.exe" not in text
                and f"{LEGACY_APP_DISPLAY_NAME}.exe" not in text
            ):
                continue
            match = re.search(r"(?im)^Sig\[3\]\.Value\s*=\s*([^\r\n]+)", text)
            if not match:
                continue
            module = match.group(1).strip()
            if not any(token in module.casefold() for token in _PANEL_GRAPHICS_FAULT_TOKENS):
                continue
            age_minutes = max(0, int(round((now - modified) / 60.0)))
            return f"recent panel WER fault in {module} ({age_minutes} min ago)"
        except (OSError, UnicodeError):
            continue
    return ""


def rtss_panel_profile_verified(
    profiles_dir: Path | None = None,
    executable_name: str | None = None,
) -> bool:
    """True only when the current executable has ``EnableHooking=0`` in RTSS."""
    if profiles_dir is None:
        rtss_root = Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"))
        profiles_dir = rtss_root / "RivaTuner Statistics Server" / "Profiles"
    executable_name = (executable_name or Path(sys.executable).name).strip()
    if not executable_name:
        return False
    profile = Path(profiles_dir) / f"{executable_name}.cfg"
    try:
        section = ""
        for raw_line in profile.read_text(encoding="utf-8-sig", errors="replace").splitlines():
            line = raw_line.strip()
            if line.startswith("[") and line.endswith("]"):
                section = line[1:-1].strip().casefold()
                continue
            if section != "hooking" or "=" not in line:
                continue
            key, value = line.split("=", 1)
            if key.strip().casefold() == "enablehooking":
                return value.strip() == "0"
    except OSError:
        pass
    return False


def rtss_is_running() -> bool:
    """Use the native process probe; retain a bounded fallback for portability."""
    native = is_process_running("RTSS.exe")
    if native is not None:
        return bool(native)
    try:
        proc = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq RTSS.exe"],
            capture_output=True,
            text=True,
            timeout=3,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return "rtss.exe" in (proc.stdout or "").casefold()
    except (OSError, subprocess.SubprocessError):
        return False


def choose_panel_renderer(
    explicit_renderer: str = "",
    preferred_renderer: str = "d3d11",
    crash_reason: str = "",
    rtss_running: bool = False,
    rtss_profile_ok: bool = False,
    mitigation_status: str = "enabled",
    platform_name: str | None = None,
) -> tuple[str, str, str]:
    'Choose hardware Direct3D 11 when safe, otherwise the proven software path.'















    platform_name = sys.platform if platform_name is None else platform_name
    explicit = explicit_renderer.strip().casefold()
    if explicit in _SUPPORTED_RENDERERS:
        return explicit, f"explicit --renderer override: {explicit}", ""

    unsafe_reasons: list[str] = []
    if crash_reason:
        unsafe_reasons.append(crash_reason.strip())
    if rtss_running and not rtss_profile_ok:
        unsafe_reasons.append("RTSS is running without a verified panel EnableHooking=0 profile")
    if platform_name == "win32" and mitigation_status != "enabled":
        unsafe_reasons.append(f"Windows extension-point mitigation {mitigation_status}")
    if unsafe_reasons:
        reason = "; ".join(unsafe_reasons)
        return "software", f"automatic compatibility safety mode: {reason}", reason

    preferred = preferred_renderer.strip().casefold()
    renderer = preferred if preferred in _SUPPORTED_RENDERERS else "d3d11"
    return renderer, f"safe renderer selection: {renderer}", ""


def read_external_frame_policy() -> str:
    """Read configured caps; this does not claim the game is using the profile."""
    parts: list[str] = []
    profiles = (Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"))
                / "RivaTuner Statistics Server" / "Profiles")
    profile = next((profiles / name for name in ("SB-Win64-Shipping.exe.cfg", "SB-Win64-Shipping.exe")
                    if (profiles / name).is_file()), profiles / "Global")
    try:
        text = profile.read_text(encoding="utf-8-sig", errors="replace")
        values = dict(re.findall(r"(?m)^\s*(Limit|LimitDenominator)\s*=\s*([0-9.]+)\s*$", text))
        # A game profile without its own limit inherits Global.
        if "Limit" not in values and profile.name != "Global":
            text = (profiles / "Global").read_text(encoding="utf-8-sig", errors="replace")
            values = dict(re.findall(r"(?m)^\s*(Limit|LimitDenominator)\s*=\s*([0-9.]+)\s*$", text))
            profile = profiles / "Global"
        denominator = float(values.get("LimitDenominator", "1"))
        if denominator <= 0:
            raise ValueError("invalid limit denominator")
        limit = float(values.get("Limit", "0")) / denominator
        label = "Global profile" if profile.name == "Global" else "game profile"
        parts.append(f"RivaTuner {label}: " + ("no frame cap configured" if limit <= 0 else f"{limit:g} FPS"))
    except FileNotFoundError:
        parts.append("No RivaTuner profile found")
    except (OSError, TypeError, ValueError):
        parts.append("RivaTuner profile could not be read")
    parts.append("RivaTuner running" if is_process_running("RTSS.exe") else "RivaTuner stopped; configured cap is inactive")
    game_settings = (
        Path(os.environ.get("LOCALAPPDATA", ""))
        / "SB"
        / "Saved"
        / "Config"
        / "WindowsNoEditor"
        / "GameUserSettings.ini"
    )
    try:
        game_text = game_settings.read_text(encoding="utf-8-sig", errors="replace")
        vsync_values = re.findall(
            r"(?im)^(?:bVSync|bUseVSync)\s*=\s*(True|False)\s*$",
            game_text,
        )
        vsync_on = any(value.casefold() == "true" for value in vsync_values)
        rate_match = re.search(
            r"(?im)^FrameRateLimit\s*=\s*([0-9.]+)\s*$",
            game_text,
        )
        rate_limit = float(rate_match.group(1)) if rate_match else 0.0
        named_limit = re.search(r"(?im)^FrameLimit\s*=\s*([^\r\n]+)$", game_text)
        named_unlimited = not named_limit or "unlimited" in named_limit.group(1).casefold()
        parts.append("game VSync on" if vsync_on else "game VSync off")
        if rate_limit > 0:
            parts.append(f"game limit {rate_limit:g} FPS")
        elif named_unlimited:
            parts.append("game FPS unlimited")
        else:
            parts.append("game named FPS limit active")
    except (OSError, TypeError, ValueError):
        parts.append("game frame policy unavailable")
    return "; ".join(parts)


def command_line_value(prefix: str, default: str = "") -> str:
    """Read either --name=value or --name value without mutating argv."""
    for index, argument in enumerate(sys.argv):
        if argument.startswith(prefix + "="):
            return argument.split("=", 1)[1].strip()
        if argument == prefix and index + 1 < len(sys.argv):
            candidate = sys.argv[index + 1]
            if not candidate.startswith("--"):
                return candidate.strip()
    return default


                                                                        
                                                                           
                                                                         
                                                                         
                          
PANEL_RENDER_LOOP = "threaded"
PANEL_FRAME_CAP_TEXT = (
    "follows the monitor refresh (vsync), 60 frames/s minimum while the panel moves; "
    "no redraws while nothing changes; every page is a still image"
)


def configure_qt_renderer() -> str:
    'Configure the Qt Quick renderer before any panel window exists.'

















    global _RENDERER_SELECTION_REASON, _RENDERER_SAFE_MODE_REASON

    isolate_panel_graphics_process()
    explicit_renderer = command_line_value("--renderer", "")
    preferred_renderer = os.environ.get("SBCHEATGUI_RENDERER", "d3d11")
    try:
        renderer_build_path = Path(sys.executable) if getattr(sys, "frozen", False) else Path(__file__)
        renderer_build_time = renderer_build_path.stat().st_mtime
    except OSError:
        renderer_build_time = None
    requested, selection_reason, safe_mode_reason = choose_panel_renderer(
        explicit_renderer=explicit_renderer,
        preferred_renderer=preferred_renderer,
        crash_reason=recent_panel_graphics_crash_reason(newer_than=renderer_build_time),
        rtss_running=rtss_is_running(),
        rtss_profile_ok=rtss_panel_profile_verified(),
        mitigation_status=_EXTENSION_POINT_MITIGATION_STATUS,
    )
    _RENDERER_SELECTION_REASON = selection_reason
    _RENDERER_SAFE_MODE_REASON = safe_mode_reason
    render_loop = command_line_value(
        "--render-loop",
        os.environ.get("SBCHEATGUI_RENDER_LOOP", PANEL_RENDER_LOOP),
    ).casefold()
    if render_loop not in {"threaded", "basic"}:
        render_loop = PANEL_RENDER_LOOP

    # Do not inherit the old development setting that disabled Qt's normal
    # display pacing.  That made the panel's living wallpaper and HUD render as
    # fast as possible even though the monitor could not display those frames,
    # consuming multiple CPU cores while the game was running.  This affects
    # only the panel process; it does not change the game's VSync or FPS limit.
    os.environ.pop("QSG_NO_VSYNC", None)
    os.environ.pop("QSG_USE_SIMPLE_ANIMATION_DRIVER", None)
    os.environ.pop("QSG_FIXED_ANIMATION_STEP", None)

    if requested == "software":
        os.environ["QT_QUICK_BACKEND"] = "software"
        os.environ["QSG_RENDER_LOOP"] = "basic"
        os.environ.pop("QSG_RHI_BACKEND", None)
    else:
        os.environ.pop("QT_QUICK_BACKEND", None)
        os.environ["QSG_RHI_BACKEND"] = requested
        os.environ["QSG_RENDER_LOOP"] = render_loop
    return requested


def try_acquire_panel_mutex() -> bool:
    """Match WinForms OverlayGUI — one desktop panel per machine/session."""
    global _PANEL_MUTEX_HANDLE
    if sys.platform != "win32":
        return True
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32
        handle = kernel32.CreateMutexW(None, True, _PANEL_MUTEX_NAME)
        if not handle:
            return True
        _PANEL_MUTEX_HANDLE = handle
        return kernel32.GetLastError() != 183  # ERROR_ALREADY_EXISTS
    except Exception:
        return True


# The saved maximize is re-checked this long after a restore (the
# launcher's bring-to-front lands within about a second of the window).
MAXIMIZE_GUARD_SECONDS = 5.0
MAXIMIZE_CHECK_DELAYS_MS = (250, 750, 1500, 3000, 5000)


def place_window_exactly(window, rect: QRect, attempts: int = 3) -> QRect:
    'Give ``window`` the client rect ``rect`` (Qt logical), exactly.'










    rect = QRect(rect)
    result = QRect()
    for _ in range(max(1, int(attempts))):
        window.setGeometry(rect)
        result = QRect(window.geometry())
        if result == rect:
            break
    return result


def focus_existing_panel(mod_root: Path) -> None:
    if sys.platform == "win32":
        try:
            import ctypes

            user32 = ctypes.windll.user32
            matches: list[int] = []
            enum_proc_type = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

            get_ex_style = getattr(user32, "GetWindowLongPtrW", None) or user32.GetWindowLongW
            get_ex_style.argtypes = [ctypes.c_void_p, ctypes.c_int]
            get_ex_style.restype = ctypes.c_ssize_t

            @enum_proc_type
            def _find_panel(hwnd, _lparam):
                length = user32.GetWindowTextLengthW(hwnd)
                if length <= 0:
                    return True
                title = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, title, length + 1)
                # Never pick the click-through metrics HUD (a tool window that
                # does not activate) - restoring it could also un-hide it.
                if is_panel_main_window(title.value, int(get_ex_style(hwnd, _GWL_EXSTYLE)) & 0xFFFFFFFF):
                    matches.append(int(hwnd))
                    return False
                return True

            user32.EnumWindows(_find_panel, 0)
            if matches:
                hwnd = matches[0]
                # SW_RESTORE only brings back a minimized window: on a
                # maximized one it un-maximizes (2.5.504 build 4). SW_SHOW
                # shows a hidden window in the state it had.
                iconic = bool(user32.IsIconic(hwnd))
                user32.ShowWindowAsync(hwnd, 9 if iconic else 5)  # SW_RESTORE / SW_SHOW
                # Briefly lift the existing window above fullscreen/borderless apps,
                # then return it to normal z-order so it does not remain intrusive.
                flags = 0x0001 | 0x0002 | 0x0040  # SWP_NOSIZE | SWP_NOMOVE | SWP_SHOWWINDOW
                user32.SetWindowPos(hwnd, -1, 0, 0, 0, 0, flags)  # HWND_TOPMOST
                user32.SetWindowPos(hwnd, -2, 0, 0, 0, 0, flags)  # HWND_NOTOPMOST
                user32.BringWindowToTop(hwnd)
                user32.SetForegroundWindow(hwnd)
                return
        except Exception:
            pass
    launcher = mod_root / "Show-Panel-ForceVisible.ps1"
    if not launcher.exists():
        return
    try:
        subprocess.Popen(
            [
                "powershell.exe",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-WindowStyle",
                "Hidden",
                "-File",
                str(launcher),
            ],
            cwd=str(mod_root),
            env={**os.environ, "SBCHEATGUI_SILENT_LAUNCH": "1"},
        )
    except Exception:
        pass


def resolve_icon_path(mod_root: Path, resource_root: Path) -> Path | None:
    candidates = [
        mod_root / "eve.ico",
        resource_root / "eve.ico",
        mod_root / "assets" / "eve-mod-icon-256.png",
        resource_root / "assets" / "eve-mod-icon-256.png",
    ]
    return next((p for p in candidates if p.exists()), None)


def load_app_icon(mod_root: Path, resource_root: Path) -> tuple[QIcon | None, Path | None]:
    """Load the Eve mod icon from disk/bundle with explicit sizes for Windows taskbar."""
    path = resolve_icon_path(mod_root, resource_root)
    if path is None:
        return None, None

    icon = QIcon()
    if path.suffix.lower() == ".ico":
        for size in (16, 20, 24, 32, 40, 48, 64, 128, 256):
            icon.addFile(str(path), QSize(size, size))
    else:
        for size in (16, 24, 32, 48, 64, 128, 256):
            icon.addFile(str(path), QSize(size, size))
    if icon.isNull():
        icon = QIcon(str(path))
    return (icon if not icon.isNull() else None), path


def apply_native_windows_icons(window, icon_path: Path) -> None:
    """Force HWND small/large icons from eve.ico (Qt taskbar fallback on Windows)."""
    if sys.platform != "win32" or not icon_path or not icon_path.exists():
        return
    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        lr_loadfromfile = 0x0010
        image_icon = 1
        wm_seticon = 0x0080
        icon_small = 0
        icon_big = 1
        ico = str(icon_path.resolve())

        hwnd = wintypes.HWND(int(window.winId()))
        h_small = user32.LoadImageW(None, ico, image_icon, 16, 16, lr_loadfromfile)
        h_big = user32.LoadImageW(None, ico, image_icon, 48, 48, lr_loadfromfile)
        if h_big:
            user32.SendMessageW(hwnd, wm_seticon, icon_big, h_big)
        if h_small:
            user32.SendMessageW(hwnd, wm_seticon, icon_small, h_small)
    except Exception:
        pass


def read_kv(path: Path) -> dict:
    data = {}
    if not path.exists():
        return data
    try:
        for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
            if "=" in raw:
                k, v = raw.split("=", 1)
                data[k.strip()] = v.strip()
    except Exception:
        return data
    return data


def write_kv_atomic(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    for raw_key, raw_value in data.items():
        key = str(raw_key)
        value = str(raw_value)
        if not key or "=" in key or re.search(r"[\x00-\x1f\x7f]", key):
            raise ValueError(f"Unsafe key-value key: {key!r}")
        if re.search(r"[\x00-\x1f\x7f]", value):
            raise ValueError(f"Unsafe control character in value for {key}")
        lines.append(f"{key}={value}")
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{time.time_ns()}.tmp")
    try:
        with tmp.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write("\n".join(lines) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        # POSIX-semantics rename with a short retry (A12): a native reading
        # the file (Movement state, Retry Point command) no longer makes the
        # replace fail with "access denied".
        replace_file(tmp, path)
    finally:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass


def parse_tool_output(text: str) -> dict:
    out = {}
    for raw in text.splitlines():
        if "=" in raw:
            k, v = raw.split("=", 1)
            out[k.strip().lower()] = v.strip()
    return out


FRIENDLY_NAME_OVERRIDES = {
    "Recovery_HP_Potion": "Healing Potion",
    "SPInitializer": "Initializer",
    "PulseGrenade": "Pulse Grenade",
    "BetaCrystal": "Beta Crystal",
    "GearCore": "Gear Core",
    "DroneCore": "Drone Core",
    "TumblerCore": "Tumbler Core",
    "ETC_Item_VendingMachineCoin": "Vending Machine Coin",
    "LowDensityWafer": "Low Density Wafer",
    "HighDensityWafer": "High Density Wafer",
    "2DQuantumWafer": "2D Quantum Wafer",
    "ECelluloseRayon": "Cellulose Rayon",
    "PolymerOrganicFilm": "Polymer Organic Film",
    "ElastomerFiber": "Elastomer Fiber",
}


def _title_keep_codes(text: str) -> str:
    small = {"of", "the", "and", "or", "to", "in"}
    words = []
    for idx, word in enumerate(text.split()):
        raw = word.strip()
        if not raw:
            continue
        if re.fullmatch(r"[A-Z]{2,}|\d+[A-Z]*|[A-Z]+\d+", raw):
            words.append(raw)
        elif idx > 0 and raw.lower() in small:
            words.append(raw.lower())
        else:
            words.append(raw[:1].upper() + raw[1:].lower())
    return " ".join(words)


def friendly_god_files_message(result) -> tuple[str, bool]:
    """Plain words for a God Mode file sync result: ``(message, show_toast)``.

    The technical message (pak names, ``~mods``) goes to the activity log as
    detail; a routine success is logged without a toast.
    """
    if result.ok:
        return "God Mode files are in place.", False
    text = str(result.message or "").lower()
    if result.locked or "in use" in text or "still loaded" in text:
        return (
            "Some God Mode files are still in use by the game. "
            "Quit Stellar Blade fully, then reopen the panel.",
            True,
        )
    if result.state == "missing" or "missing" in text:
        return (
            "Some God Mode files are missing. Close Stellar Blade and run "
            "One-Click Repair on Support.",
            True,
        )
    return (
        "God Mode files need attention. Close Stellar Blade and run "
        "One-Click Repair on Support.",
        True,
    )


def friendly_alias_name(alias: str) -> str:
    alias = (alias or "").strip()
    if not alias:
        return ""
    if alias in FRIENDLY_NAME_OVERRIDES:
        return FRIENDLY_NAME_OVERRIDES[alias]

    bs_match = re.match(r"^BS_(.+)$", alias)
    if bs_match:
        tail = bs_match.group(1)
        number_variant = re.match(r"^(\d+)_(\d+)$", tail)
        if number_variant:
            return f"Body Suit {number_variant.group(1)}-{number_variant.group(2)}"
        variant = re.match(r"^(\d+)_Var(\d+)$", tail, flags=re.IGNORECASE)
        if variant:
            return f"Body Suit {variant.group(1)} Variant {variant.group(2)}"
        if re.match(r"^\d+$", tail):
            return f"Body Suit {tail}"
        tail = re.sub(r"_Suit$", "", tail, flags=re.IGNORECASE)
        tail = tail.replace("_", " ")
        tail = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", tail)
        return "Body Suit " + _title_keep_codes(re.sub(r"\s+", " ", tail).strip())

    text = alias
    text = re.sub(r"^(Item|Util|ETC)_", "", text, flags=re.IGNORECASE)
    rarity = ""
    rarity_match = re.search(r"_(Common|Rare|Epic|Hero)$", text, flags=re.IGNORECASE)
    if rarity_match:
        rarity = f" ({rarity_match.group(1).title()})"
        text = text[: rarity_match.start()]
    text = text.replace("_", " ")
    text = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", text)
    text = re.sub(r"(?<=[A-Z])(?=[A-Z][a-z])", " ", text)
    text = re.sub(r"\bHP\b", "Health", text)
    text = re.sub(r"\bSP\b", "SP", text)
    text = re.sub(r"\bBS\s+(\d+)(?:\s+Var\s*(\d+))?\b", lambda m: f"Body Suit {m.group(1)}" + (f" Variant {m.group(2)}" if m.group(2) else ""), text, flags=re.IGNORECASE)
    text = re.sub(r"\bDesign\s*Pattern\s+BS\s+(\d+)\s+(\d+)\b", r"Design Pattern Body Suit \1-\2", text, flags=re.IGNORECASE)
    text = re.sub(r"\bDesign\s*Pattern\s+(\d+)\b", r"Design Pattern \1", text, flags=re.IGNORECASE)
    text = re.sub(r"\bDrone\s*Seal\b", "Drone Seal", text, flags=re.IGNORECASE)
    text = re.sub(r"\bAdam\s*Costume\b", "Adam Costume", text, flags=re.IGNORECASE)
    text = re.sub(r"\bLily\s*Costume\b", "Lily Costume", text, flags=re.IGNORECASE)
    text = re.sub(r"\bOne\s*Million\b", "One Million", text, flags=re.IGNORECASE)
    text = re.sub(r"\bJunk\s*Iron\b", "Junk Iron", text, flags=re.IGNORECASE)
    text = re.sub(r"\bAmmo\b", "Ammo", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+", " ", text).strip()
    return _title_keep_codes(text) + rarity


def friendly_display_name(alias: str, raw_name: str = "", category: str = "") -> str:
    name = (raw_name or "").strip()
    name = re.sub(r"\s*\[save:\s*.*?\]", "", name, flags=re.IGNORECASE).strip()
    caution = ""
    if re.search(r"\(caution\)$", name, flags=re.IGNORECASE):
        caution = " (Caution)"
        name = re.sub(r"\s*\(caution\)$", "", name, flags=re.IGNORECASE).strip()
    name = re.sub(r"^Save:\s*", "", name, flags=re.IGNORECASE).strip()
    name = name.replace("Healing Pot", "Healing Potion")
    name = re.sub(r"\bDesignpattern\b", "Design Pattern", name, flags=re.IGNORECASE)
    name = re.sub(r"\bDroneseal\b", "Drone Seal", name, flags=re.IGNORECASE)
    name = re.sub(r"\bAdamcostume\b", "Adam Costume", name, flags=re.IGNORECASE)
    name = re.sub(r"\bLilycostume\b", "Lily Costume", name, flags=re.IGNORECASE)
    name = re.sub(r"\bOnemillion\b", "One Million", name, flags=re.IGNORECASE)
    name = re.sub(r"\bJunkiron\b", "Junk Iron", name, flags=re.IGNORECASE)
    name = re.sub(r"\bBS\s+(\d+)\s+(\d+)\b", r"Body Suit \1-\2", name, flags=re.IGNORECASE)
    name = re.sub(r"\bBS\s+(\d+)\b", r"Body Suit \1", name, flags=re.IGNORECASE)
    name = re.sub(r"\bBS\s+Green\s+Suit\b", "Body Suit Green", name, flags=re.IGNORECASE)
    name = re.sub(r"\bBS\s+One\s+Million\s+(\d+)\b", r"Body Suit One Million \1", name, flags=re.IGNORECASE)
    name = re.sub(r"\s+", " ", name).strip()

    technical = (
        not name
        or name == alias
        or "_" in name
        or re.match(r"^(Item|Util|ETC|Gear)_", name, flags=re.IGNORECASE)
    )
    if technical:
        name = friendly_alias_name(alias)
    return (name or alias or "Unknown Item") + caution


STEAM_APP_ID = "3489700"
GAME_PROCESS_NAME = "SB-Win64-Shipping.exe"
GAME_EXE_RELATIVE = Path("Binaries") / "Win64" / GAME_PROCESS_NAME
# Update notice: the first check waits until the panel has settled, then
# every hour the panel asks whether a day has passed (update_check.check_due).
UPDATE_FIRST_CHECK_MS = 30_000
UPDATE_RECHECK_MS = 60 * 60 * 1000

# Out of the box the overlay shows only what a player reads mid-fight: frame
# rate, frame time, 1% low, GPU/CPU load and temperature, and God Mode. Clock
# limits, power and health rows are troubleshooting detail (Settings > In-game
# overlay > More numbers). A saved choice always wins over these defaults.
PERFORMANCE_OVERLAY_DEFAULTS = {
    "fps": True,
    "frameTime": True,
    "onePercentLow": True,
    "pointOnePercentLow": False,
    "frameGraph": False,
    "pacing": False,
    "stutters": False,
    "minAvgMax": False,
    "gpuFrameTime": False,
    "gpuUsage": True,
    "gpuTemperature": True,
    "gpuPower": False,
    "gpuClock": False,
    "gpuFan": False,
    "gpuThrottle": False,
    "vram": False,
    "cpuUsage": True,
    "cpuTemperature": True,
    "cpuLimit": False,
    "hardwareHealth": False,
    "cpuPower": False,
    "cpuClock": False,
    "ram": False,
    "resolution": False,
    "connection": False,
    "godMode": True,
}

# Clock-limit, power-cap and "hardware health" reasons are diagnostics: the
# Support page shows them and the HUD never draws them, whatever an older
# panel_settings.txt says. The keys stay above only so old settings parse.
HUD_DIAGNOSTIC_ONLY_METRICS = frozenset({"gpuThrottle", "cpuLimit", "hardwareHealth"})


class Backend(QObject):
    statusChanged = Signal()
    logChanged = Signal()
    itemsChanged = Signal()
    selectedItemChanged = Signal()
    movementChanged = Signal()
    bossChanged = Signal()
    retryPointChanged = Signal()
    liveAddChanged = Signal()
    nativeStatusChanged = Signal()
    settingsChanged = Signal()
    godChanged = Signal()
    energyChanged = Signal()
    infrastructureChanged = Signal()
    healthChanged = Signal()
    operationMessage = Signal(str)
    # The same toast with its activity-log level ("OK", "INFO", "WARN",
    # "ERROR"), so the panel can colour it and keep errors on screen.
    operationNotice = Signal(str, str)
    gameStartNoteChanged = Signal()
    rendererChanged = Signal()
    saveSnapshotsChanged = Signal()
    oldUe4ssChanged = Signal()
    updateChanged = Signal()
    bugReportChanged = Signal()
    # (UpdateInfo | None, fallback download page) from the update thread.
    _updateCheckDone = Signal(object)

    def __init__(self, mod_root: Path, requested_renderer: str = "unknown"):
        super().__init__()
        self.mod_root = mod_root
        self._renderer_requested = requested_renderer
        self._renderer_actual = "initializing"
        self._renderer_selection_reason = _RENDERER_SELECTION_REASON
        self._renderer_safe_mode_reason = _RENDERER_SAFE_MODE_REASON
        self._extension_mitigation_status = _EXTENSION_POINT_MITIGATION_STATUS
        self._remaining_graphics_hooks: list[str] = []
        self.qt_root = Path(__file__).resolve().parent
        bundled_assets = Path(getattr(sys, "_MEIPASS", self.qt_root)) / "assets"
        self.bundled_assets_dir = bundled_assets
        self.assets_dir = self.mod_root / "assets"
        if not self.assets_dir.exists() and bundled_assets.exists():
            self.assets_dir = bundled_assets
        try:
            self.sb_root = self.mod_root.parents[4]
        except IndexError:
            self.sb_root = self.mod_root
        try:
            self.steamapps_root = self.sb_root.parents[2]
        except IndexError:
            self.steamapps_root = self.mod_root
        self.game_exe = self.sb_root / GAME_EXE_RELATIVE
        # Support > Fix problems: an old UE4SS unpacked straight into Win64.
        self.win64_dir = win64_dir_for(self.sb_root)
        self._old_ue4ss_files = [path.name for path in find_old_ue4ss_files(self.win64_dir)]
        self.app_manifest_file = self.steamapps_root / f"appmanifest_{STEAM_APP_ID}.acf"
        self.paks_mods_dir = self.sb_root / "Content" / "Paks" / "~mods"
        self.disabled_paks_dir = self.mod_root / "disabled_paks"

        self.version_file = self.mod_root / "VERSION"
        self.state_file = self.mod_root / "gui_state.txt"
        self.reset_request_file = self.mod_root / "runtime_reset_request.txt"
        self.heartbeat_file = self.mod_root / "sbcheat_heartbeat.txt"
        self.spawn_status_file = self.mod_root / "item_spawn_status.txt"
        self.item_probe_file = self.mod_root / "item_probe.txt"
        self.issue_log_file = self.mod_root / "item_issue_log.txt"
        self.catalog_file = self.mod_root / "item_catalog.txt"
        self.database_file = self.mod_root / "data" / "item_database.txt"
        self.save_candidates_file = self.mod_root / "save_item_candidates.txt"
        self.policy_file = self.mod_root / "data" / "item_policy.json"
        self._policy_db = load_policy_database(self.mod_root)
        self.save_tools = self.mod_root / "SaveTools.ps1"
        self.settings_file = self.mod_root / "panel_settings.txt"
        self.support_script = self.mod_root / "Create-SupportReport.ps1"
        self.support_reports_dir = self.mod_root / "SupportReports"
        mods_root = self.mod_root.parent
        # Instant Boss Restart = the SBInstantBossRestart game mod: its switch
        # (settings.txt) and its status (status.txt) live in its own folder.
        self.ibr_dir = mods_root / BOSS_RESTART_FOLDER
        self.retry_point_root = mods_root / "SBRetryPointNative"
        self.retry_point_dll = self.retry_point_root / "dlls" / "main.dll"
        self.retry_point_marker = self.retry_point_root / "enabled.txt"
        self.retry_point_status_file = self.retry_point_root / "retry_point_status.txt"
        self.retry_point_command_file = self.mod_root / "retry_point_command.txt"
        # Game mod 0.2.3: while this lease is fresh it checks the loaded area.
        self.retry_point_watch_file = self.mod_root / "retry_point_watch.txt"
        self.retry_point_file = self.mod_root / "retry_point.txt"
        self.retry_point_temp_file = self.mod_root / "retry_point.tmp"
        # Items & Money: the audited Live Add v3 bridge plus the dedicated
        # SBLiveAddNative. SBItemDropNative is retired and never driven.
        self.live_add_root = mods_root / "SBLiveAddBridge"
        self.live_add_script = self.live_add_root / "Scripts" / "main.lua"
        self.live_add_marker = self.live_add_root / "enabled.txt"
        self.live_add_native_root = mods_root / "SBLiveAddNative"
        self.live_add_native_dll = self.live_add_native_root / "dlls" / "main.dll"
        self.live_add_native_marker = self.live_add_native_root / "enabled.txt"
        self.live_add_native_status_file = self.live_add_native_root / LIVE_ADD_NATIVE_STATUS_FILE
        # v0.5 probe (PLAN C7): both files live next to the Items lease.
        self.live_add_probe_request_file = self.mod_root / PROBE_REQUEST_FILE
        self.live_add_probe_result_file = self.mod_root / PROBE_RESULT_FILE
        self.items_catalog_file = self.mod_root / "data" / ITEMS_CATALOG_FILE_NAME

        self._performance = PerformanceController(self)
        bundled_tools = Path(getattr(sys, "_MEIPASS", self.qt_root)) / "tools" / "PresentMon" / "PresentMon.exe"
        disk_tools = self.mod_root / "tools" / "PresentMon" / "PresentMon.exe"
        self._game_telemetry = GameTelemetryController(
            bundled_tools if bundled_tools.is_file() else disk_tools,
            self,
        )
        self._game_telemetry.hardwareWarning.connect(self._on_hardware_warning)
        self._items_model = ItemListModel(self)
        self._items_proxy = CatalogFilterProxyModel(self)
        self._items_proxy.setSourceModel(self._items_model)
        self._items_proxy.performanceChanged.connect(
            lambda: self._performance.record_catalog_filter(self._items_proxy.last_filter_ms)
        )
        self._version = self._read_version()
        self._ui_revision = self._read_ui_revision()
        self._patch_notes = self._read_patch_notes()
        self._game_running = False
        self._game_running_cached = False
        self._game_check_running = False
        # The top bar's lasting note after a Start game that ended on its own
        # (services/game_start.start_note_for) and its full words for the tooltip.
        self._game_start_note = ""
        self._game_start_note_detail = ""
        self._mod_connected = False
        self._connection_tier = "closed"
        self._lua_ready = False
        self._status_text = "Checking status..."
        self._status_detail = ""
        self._spawn_api = ""
        self._issue_log = ""
        self._selected_alias = ""
        self._selected_name = "Pick an item"
        self._qty = 1
        self._item_policy_level = "UNKNOWN"
        self._item_policy_text = "Pick an item"
        self._item_policy_detail = "Select an item to see whether it is safe, save-only, caution, blocked, or missing from the current save."
        self._item_policy_db_summary = "Policy database not loaded yet."
        self._item_live_supported = False
        self._item_last_result = ""
        # The Money card's own result line: a Gold (or other currency) add
        # reports here, never under Add Item.
        self._money_last_result = ""
        # The game session those two lines belong to ("" = game closed);
        # see _refresh_live_add_status.
        self._add_results_session = ""
        self._live_add_installed = False
        self._live_add_trusted = False
        self._live_add_ready = False
        self._live_add_busy = False
        self._live_add_phase = "waiting"
        self._live_add_status = "Not installed or turned off."
        self._live_add_expected_session = ""
        self._live_add_expected_request_id = ""
        self._live_add_expected_sequence = 0
        self._live_add_expected_alias = ""
        self._live_add_expected_name = "item"
        self._live_add_expected_qty = 1
        # A13 Items lease (SBLiveAddNative 0.4.0): renewed only while the Items
        # & Money page is open or an add is in flight, so the native does no
        # GameThread work while nobody is adding items.
        self.live_add_lease_file = self.mod_root / LIVE_ADD_LEASE_FILE
        self._live_add_lease_written_at = float("-inf")
        self._live_add_lease_started_at = float("-inf")
        self._live_add_lease_error_logged = False
        # Money goes through the same game-owned add as items (v0.5: Gold is
        # BetaCrystal, 1..1,000,000 per add); the wallet is never written.
        self._money_status_state = "checking"
        self._money_live_add_ready = False
        # One plain line on the Money card (it has no second helper line).
        self._money_live_add_status = "Gold can be added once Items & Money is ready."
        self._money_alias = MONEY_ALIAS
        self._money_balance = -1
        self._money_max_add = 0
        # A large money add (MONEY_CONFIRM_AT or more) waits for a second,
        # explicit "Add" on the Money card; it is never sent on one click.
        self._money_confirm_amount = 0
        self._money_confirm_alias = ""
        self._money_confirm_at = float("-inf")
        self._live_add_expected_currency = False
        # Items & Money v0.5 catalog + probe state.
        self._items_catalog = PanelCatalog()
        self._items_optins = {key: False for key in ITEMS_TOGGLE_KEYS}
        self._items_mode = "none"
        self._items_route_ok = False
        self._items_chip_signature: tuple | None = None
        self._live_add_probe_seen = False
        self._probe_id = ""
        self._probe_scope_all = False
        self._probe_session = ""
        self._probe_issued_at = float("-inf")
        self._probe_finished_at = float("-inf")
        self._probe_retry_after = float("-inf")
        self._probe_full_wanted = True
        self._probe_pending_aliases: set[str] = set()
        self._probe_entries: dict[str, ProbeEntry] = {}
        self._probe_answered_all = False
        self._probe_version = 0
        self._probe_result_signature: tuple[int, int] | None = None
        self._probe_error_logged = False
        # Screenshot automation only (--items-fixture): chip states for
        # review captures without a running game. Never set otherwise.
        self._items_fixture: dict | None = None
        self._selected_row: dict = {}
        self._selected_chip = ""
        self._selected_chip_reason = ""
        self._selected_max_qty = 0
        self._live_probe_ready_cached = False
        self._live_probe_text_cached = "No live probe exists yet."
        self._health_level = "UNKNOWN"
        self._health_summary = "Not checked yet"
        self._health_detail = "Run Health Check to verify files, folders, paks, save tools, reports, and current game/mod connection."
        self._health_report = ""
        self._game_was_running = self._is_game_running()
        self._game_running = self._game_was_running
        self._game_running_cached = self._game_running
        # A closed game cannot own a valid heartbeat. Remove even a recently
        # written lease on panel startup so a prior clean shutdown never leaves
        # the next session waiting for a heartbeat reset.
        if not self._game_running:
            clear_stale_heartbeat_files(self.mod_root, force=True)
            # Likewise an Items lease or probe request left by an earlier
            # panel process.
            for stale in (self.live_add_lease_file, self.live_add_probe_request_file):
                try:
                    stale.unlink(missing_ok=True)
                except OSError:
                    pass
        self._filter = ""
        self._category = "All"
        self._speed = 1.0
        self._walk = 1.0
        self._jump = 1.0
        self._fov = 75.0  # absolute degrees; live gameplay baseline on this build
        # Whether speed/jump should apply. FOV is independent of this. All three
        # controls publish live, but speed/jump activate only after their sliders
        # are actually moved; opening the panel alone never enables movement.
        self._movement_enabled = False
        self._movement_seq = max(1, time.time_ns())
        self._retry_point_seq = max(1, time.time_ns())
        self._retry_point_token = secrets.token_hex(16)
        self._retry_point_installed = False
        self._retry_point_available = False
        self._retry_point_saved = False
        # Return whenever a point is saved and the game mod is ready (it checks
        # the area on every Return); retry_point_area names where it last
        # found Eve, as advice.
        self._retry_point_can_return = False
        self._retry_point_area = "none"
        self._retry_point_busy = False
        self._retry_point_phase = "offline"
        self._retry_point_status = "The Retry Point game mod is not installed."
        self._retry_point_identity = "missing"
        self._retry_point_pending_seq = 0
        self._retry_point_pending_command = ""
        self._retry_point_command_started = 0.0
        # One Set Point / Return still running reads as unbalanced TaskGraph
        # counts for a moment; only the same counts lasting ~2 s are a fault.
        self._retry_point_counts_guard = RetryPointCountsGuard()
        self._retry_point_success_text = ""
        self._retry_point_success_until = 0.0
        # The area comes from the game mod's own checks (0.2.3 watch lease).
        self._retry_point_area_live = False
        self._retry_point_watch_at = float("-inf")
        self._retry_point_watch_written = False
        # One truthful state per native card (see services/native_status.py).
        self._native_status: dict[str, dict[str, object]] = {
            key: NativeVerdict(NATIVE_WAITING, "Checking...", "initial").as_qml()
            for key in ("movement", "god", "retryPoint", "boss", "items")
        }
        self._native_status_reasons: dict[str, str] = {}
        self._god_verdict = NativeVerdict(NATIVE_WAITING, "Checking...", "initial")
        self._live_add_status_label = "Waiting for game"
        self._live_add_status_state = NATIVE_WAITING
        self._live_add_added_until = 0.0
        self._live_add_added_text = ""
        self._live_add_notice_until = 0.0
        self._live_add_notice_text = ""
        self._catalog_rows: list[dict] = []
        self._catalog_duplicate_count = 0
        self._categories = ["All"]
        # Instant Boss Restart: the switch, the game mod's verdict and words.
        self._ibr_files = IbrFiles(self.ibr_dir)
        # Screenshot automation only (--ui-fixture): (install, switch, status)
        # replayed instead of the files on disk.
        self._ibr_fixture: tuple[IbrInstall, bool, dict[str, str] | None] | None = None
        # (game process id, its start time) for "written in this game session".
        self._ibr_started: tuple[int, float | None] = (0, None)
        self._boss_enabled = False
        self._boss_ready = False
        # The screen is black while the game mod restarts the fight.
        self._boss_reviving = False
        self._boss_retry_count = 0
        self._boss_status_text = "Checking Instant Boss Restart..."
        self._boss_diagnostics = "Not checked yet."
        self._boss_technical_diagnostics = "Not checked yet."
        self._boss_supports_story = False
        self._external_frame_policy_summary = "Not checked yet."
        # (game session, restarts, last result, its time) already in the log.
        self._boss_log_key: tuple = ()
        # Screenshot automation only (--ui-fixture): the recorded state stays
        # on screen because the panel's own polling is stopped for that run.
        self._ui_fixture_active = False
        self._job_history: list[str] = ["No backend jobs yet."]
        self._last_job_summary = "No backend jobs yet."
        settings = read_kv(self.settings_file)
        self._always_on_top = settings.get("onTop") == "1"
        # Items & Money opt-in groups (off until the player turns them on).
        self._items_optins = {
            key: settings.get(f"itemsOptIn_{key}", "0") == "1" for key in ITEMS_TOGGLE_KEYS
        }
        self._stellar_accent = settings.get("stellarAccent", "1") != "0"
        # Windows "Animation effects" off -> the interface stops sliding and
        # scaling (colour fades stay). Re-read on every manual refresh.
        self._reduce_motion = not windows_animations_enabled()
        self._performance_overlay_enabled = settings.get("perfOverlayEnabled", "0") == "1"
        self._performance_overlay_size = normalize_overlay_size(settings.get("perfOverlaySize", "standard"))
        self._performance_overlay_metrics = {
            key: (
                settings.get(f"perfMetric_{key}", "1" if default else "0") == "1"
                and key not in HUD_DIAGNOSTIC_ONLY_METRICS
            )
            for key, default in PERFORMANCE_OVERLAY_DEFAULTS.items()
        }
        self._game_telemetry.set_overlay_active(self._performance_overlay_enabled)
        # Hardware notices are off unless the user turns them on; even then
        # they are rate-limited to one per ten minutes.
        self._hardware_alerts = settings.get("hardwareAlerts", "0") == "1"
        self._game_telemetry.set_alerts_enabled(self._hardware_alerts)
        # Unlimited Beta / Burst energy (Gameplay, under God Mode): the two
        # switches as the player left them. They are remembered here and
        # published to the God Mode game mod's state file; the card's verdict
        # comes from that game mod's own report (refresh_status).
        self._energy_beta = settings.get("energyBeta", "0") == "1"
        self._energy_burst = settings.get("energyBurst", "0") == "1"
        self._energy_status = EnergyStatus(ENERGY_OFF, "checking", False)
        self._energy_logged: tuple[str, str] = ("", "")
        # Update notice (services/update_check.py): at most once a day, in the
        # background, silent on failure. A newer version shows one quiet line
        # on the Dashboard and Support; nothing downloads, nothing pops up.
        self._update_check_enabled = bool(read_update_source(self.mod_root).version_url) and settings.get("updateCheck", "1") != "0"
        try:
            self._update_checked_at = float(settings.get("updateCheckedAt", "0") or 0)
        except ValueError:
            self._update_checked_at = 0.0
        latest = settings.get("updateLatestVersion", "")
        known_newer = self._update_check_enabled and version_is_newer(latest, self._version)
        self._update_version = latest if known_newer else ""
        self._update_url = safe_download_url(settings.get("updateLatestUrl", "")) if known_newer else ""
        self._update_check_running = False
        self._updateCheckDone.connect(self._on_update_check_done)
        self._update_timer = QTimer(self)
        self._update_timer.setInterval(UPDATE_RECHECK_MS)
        self._update_timer.timeout.connect(self._maybe_check_for_update)
        self._update_timer.start()
        QTimer.singleShot(UPDATE_FIRST_CHECK_MS, self._maybe_check_for_update)
        self._last_bug_report = ""
        # Remembered field of view. Persisted here so the slider comes back to
        # the user's chosen angle after a panel or game restart, and pushed to
        # the mod's state file now so a running game picks it up immediately.
        try:
            self._fov = max(50.0, min(170.0, float(settings.get("fovDegrees", "75"))))
        except (TypeError, ValueError):
            self._fov = 75.0
        if self._native_movement_installed():
            self._write_native_movement_state(quiet=True)
        self._active_page = "gameplay"  # Every new launch opens Gameplay; navigation remains normal.
        self._dock_mode = settings.get("dock", "free") or "free"
        self._dock_restore_done = False
        self._dock_restore_attempts = 0
        self._window = None
        # Window memory: the last un-maximized rect and the screen it was on
        # (tracked while the window is Windowed), and whether it was
        # maximized before a minimize or the close.
        self._normal_rect: WindowBox | None = None
        self._normal_screen: ScreenDesc | None = None
        self._window_was_maximized = settings.get("maximized", "0") == "1"
        self._maximized_screen: ScreenDesc | None = None
        self._last_window_visibility = None
        # The saved maximize sticks: until this monotonic time a restored
        # maximized window that turns Windowed is maximized again (the
        # launcher's bring-to-front used SW_RESTORE, which un-maximized it).
        self._maximize_guard_until = 0.0
        # True while the panel itself places the window (its own Windowed
        # step before a new rect is not an un-maximize to undo).
        self._placing_window = False
        # Off until main() enables it (see enable_window_memory).
        self._window_memory_enabled = False
        self._geometry_persist_timer = QTimer(self)
        self._geometry_persist_timer.setSingleShot(True)
        self._geometry_persist_timer.setInterval(500)
        self._geometry_persist_timer.timeout.connect(self._persist_window_geometry)
        self._game_was_running = self._is_game_running()
        self._game_pid_cached = find_process_id(GAME_PROCESS_NAME) or 0
        # A verified profile that existed while the game was closed is valid
        # preparation for the next launch, even when the user starts the game
        # from Steam instead of this panel.
        # When the game is closed, repair the next-launch profile immediately:
        # unsafe Lua/retry hooks remain disabled while the shutdown-hardened
        # SBGodNative bridge is enabled for live God Mode. A running process is
        # inspected only; changing markers cannot alter modules already loaded.
        initial_profile = (
            inspect_hook_free_retry_profile(mods_root)
            if self._game_running
            else enforce_hook_free_retry_profile(mods_root)
        )
        self._hook_free_profile_safe = initial_profile.safe
        self._hook_free_profile_status = initial_profile.detail
        self._native_god_ready = bool(initial_profile.native_bridge_ready)
        self._native_god_applied = False
        # The trusted God Mode game mod and its marker are on disk (the
        # energy switches live in the same game mod).
        self._native_god_installed = bool(initial_profile.native_bridge_ready)
        self._tasks = BackendTaskRunner(max_threads=2, parent=self)
        self._tasks.activeChanged.connect(self.infrastructureChanged.emit)
        self._probe_pool = QThreadPool(self)
        self._probe_pool.setMaxThreadCount(1)
        # Save snapshots run on their own low-priority thread so they never
        # make the Support buttons say "Working" or wait behind a repair.
        # Off until main() enables them: automation runs (--smoke,
        # --screenshot) must not add snapshots or push real ones out.
        self._snapshot_pool = QThreadPool(self)
        self._snapshot_pool.setMaxThreadCount(1)
        self._save_snapshots_enabled = False
        self._save_snapshot_job = None
        self._save_snapshot_pending = ""
        self._save_snapshot_root = default_snapshot_root(self.mod_root)
        self._save_snapshot_note = ""
        self._save_snapshot_reason = ""
        try:
            existing_snapshots = list_snapshots(self._save_snapshot_root)
        except OSError:
            existing_snapshots = []
        self._save_snapshot_summary = save_snapshot_summary_text(existing_snapshots)
        # Save history (Support): the snapshots newest first, and Restore.
        # A snapshot is also made each time the game writes its saves: the
        # watcher looks at the save folder's file sizes and times every 2 s
        # while the game runs (and for a minute after it closes) and asks
        # for one once the writes have settled for 5 s.
        self._save_history_rows = save_history_rows(existing_snapshots)
        self._save_restore_job = None
        self._save_restore_pending = ""
        self._save_restore_note = ""
        self._save_undo_name = ""
        self._save_watch = SaveWriteWatcher()
        self._save_watch_until = 0.0
        self._save_watch_timer = QTimer(self)
        self._save_watch_timer.setInterval(SAVE_WATCH_INTERVAL_MS)
        self._save_watch_timer.timeout.connect(self._poll_save_writes)
        self._status_signature = None
        self._spawn_result_signature = None

        self._file_watch = CoalescedFileWatcher(
            {
                "status": self.heartbeat_file,
                "status_spawn": self.spawn_status_file,
                "status_state": self.state_file,
                "status_reset": self.reset_request_file,
                "status_boss": self.ibr_dir / BOSS_RESTART_STATUS_NAME,
                "log": self.issue_log_file,
                # The generated v0.5 catalog is the only item list (PLAN
                # C10); the old live and save-candidate lists are not read.
                "catalog_database": self.items_catalog_file,
            },
            self,
        )
        self._file_watch.changed.connect(self._on_watched_file_changed)

        self._filter_timer = QTimer(self)
        self._filter_timer.setSingleShot(True)
        self._filter_timer.setInterval(50)
        self._filter_timer.timeout.connect(self._apply_filter)

        self._load_catalog()
        self._apply_runtime_reset_request()
        self._load_movement_from_state()
        self._ensure_god_mode_default_off()
        self._ensure_mod_reload_watchers()
        self._god_enabled = self._read_god_enabled()
        if self._god_enabled and self._game_running:
            QTimer.singleShot(600, self._nudge_god_reapply)
        # A game that is already running gets the remembered energy switches,
        # after God Mode's own line above has been written.
        if self._game_running:
            QTimer.singleShot(700, self._publish_energy_switches)
        self._remove_orphaned_retry_point_command_at_start()
        # A watch lease left by a panel that has closed: this panel writes its
        # own once it is needed.
        self._remove_retry_point_watch()
        self._refresh_boss_status()
        self._refresh_retry_point_status()
        self._refresh_live_add_status()
        self.refresh_status()
        self.refresh_log()

        self._status_timer = QTimer(self)
        # Process existence has no reliable cross-process file event, so retain
        # one slow recovery probe. Heartbeat/state/log/catalog updates are event-driven.
        self._status_timer.setInterval(2000)
        self._status_timer.timeout.connect(self.refresh_status)
        self._status_timer.start()

        # Instant Boss Restart, Retry Point and Live Add talk to game mods,
        # so their fast timers run only while the game runs. With the game
        # closed, the 2 s status refresh keeps those cards current.
        self._boss_timer = QTimer(self)
        self._boss_timer.setInterval(500)
        self._boss_timer.timeout.connect(self._refresh_boss_status)

        self._retry_point_timer = QTimer(self)
        self._retry_point_timer.setInterval(250)
        self._retry_point_timer.timeout.connect(self._refresh_retry_point_status)

        self._live_add_timer = QTimer(self)
        self._live_add_timer.setInterval(250)
        self._live_add_timer.timeout.connect(self._refresh_live_add_status)
        self._sync_game_timers()

    def _game_timers(self) -> tuple[QTimer, ...]:
        return tuple(
            timer for timer in (
                getattr(self, "_boss_timer", None),
                getattr(self, "_retry_point_timer", None),
                getattr(self, "_live_add_timer", None),
            ) if timer is not None
        )

    def _sync_game_timers(self) -> None:
        """Fast game-feature timers run only while the game process exists."""
        running = bool(self._game_running)
        for timer in self._game_timers():
            if running and not timer.isActive():
                timer.start()
            elif not running and timer.isActive():
                timer.stop()

    @Slot(str)
    def _on_watched_file_changed(self, tag: str) -> None:
        if tag == "log":
            self.refresh_log()
            return
        if tag.startswith("catalog_"):
            self._load_catalog()
            self.itemsChanged.emit()
            return
        if tag == "status_reset":
            self._apply_runtime_reset_request()
        self.refresh_status()

    def _apply_runtime_reset_request(self) -> bool:
        """Commit the in-game reset hotkey through the panel-owned state writer."""
        if not self.reset_request_file.is_file():
            return False
        previous = read_kv(self.state_file)
        state = self._default_state()
        for key in ("itemseq", "itemprobeseq", "healseq", "spawnseq"):
            state[key] = previous.get(key, state[key])
        try:
            state["godseq"] = str(max(0, int(previous.get("godseq", "0"))) + 1)
        except (TypeError, ValueError):
            state["godseq"] = "1"
        try:
            write_kv_atomic(self.state_file, state)
            self.reset_request_file.unlink(missing_ok=True)
        except OSError:
            return False
        self._speed = self._walk = self._jump = 1.0
        self._movement_enabled = False
        # FOV is an independent, remembered setting. Preserve it while the
        # reset disables movement, then publish that safe state immediately.
        if self._native_movement_installed():
            self._write_native_movement_state(quiet=True)
        if hasattr(self, "_god_enabled"):
            self._god_enabled = False
            self.godChanged.emit()
        self.movementChanged.emit()
        return True

    def _load_movement_from_state(self) -> None:
        state = read_kv(self.state_file)
        try:
            self._speed = max(0.5, min(3.0, float(state.get("speed", "1.0") or "1.0")))
        except Exception:
            self._speed = 1.0
        try:
            self._walk = max(0.5, min(3.0, float(state.get("walk", "1.0") or "1.0")))
        except Exception:
            self._walk = 1.0
        try:
            self._jump = max(0.5, min(3.0, float(state.get("jump", "1.0") or "1.0")))
        except Exception:
            self._jump = 1.0
        self.movementChanged.emit()

    def _ensure_mod_reload_watchers(self) -> None:
        """Start background watchers that queue in-game soft reload when scripts change."""
        if not (self.mod_root / "dev_mode.on").is_file():
            return
        watcher = self.mod_root / "Panel-ModReload-Watcher.ps1"
        if not watcher.is_file():
            return
        try:
            subprocess.Popen(
                [
                    "powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
                    "-WindowStyle", "Hidden", "-File", str(watcher),
                ],
                cwd=str(self.mod_root),
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except Exception:
            pass

    def _request_mod_reload(self, reason: str = "panel") -> None:
        if bump_mod_reload_seq(self.mod_root, self.state_file):
            self._append_issue(
                "OK", "mod", "Asked the game mods to reload their settings.",
                f"mod reload queued: {reason}", toast=False,
            )

    def _read_god_enabled(self) -> bool:
        state = read_kv(self.state_file)
        return state.get("godlive", "0") == "1"

    def _nudge_god_reapply(self) -> None:
        """Bump godseq so Lua/native re-arm without a manual OFF/ON toggle."""
        state = read_kv(self.state_file)
        if state.get("godlive", "0") != "1":
            return
        try:
            seq = int(state.get("godseq", "0")) + 1
        except Exception:
            seq = 1
        self._update_state({"godlive": "1", "godseq": seq, "god": "0"})
        # The safe profile intentionally keeps the legacy Lua bridge offline.
        # Re-arm the native guard directly after refresh_status() clears its
        # stale state on the game-closed -> game-running transition.
        write_native_god_state(self.mod_root, True)
        prepare_live_god_mode(self.mod_root, self.paks_mods_dir, self.disabled_paks_dir)
        self._god_enabled = True
        self.godChanged.emit()

    def _ensure_god_mode_default_off(self) -> None:
        """Clear legacy god=1 flag; keep explicit godlive user choice."""
        state = read_kv(self.state_file)
        if state.get("god", "0") == "1":
            try:
                seq = int(state.get("godseq", "0")) + 1
            except Exception:
                seq = 1
            self._update_state({"god": "0", "godseq": seq})
        self._god_enabled = self._read_god_enabled()
        restore_god_pak_backup(self.disabled_paks_dir, self.mod_root)
        if not self._game_running:
            apply_pending_god_pak_changes(self.mod_root, self.paks_mods_dir, self.disabled_paks_dir)
        self._migrate_live_god_paks(log=False)

    def _migrate_live_god_paks(self, log: bool = True) -> None:
        result = sync_god_paks_with_state(
            self.mod_root,
            self.paks_mods_dir,
            self.disabled_paks_dir,
            self._game_running,
        )
        if result is None:
            return
        if log and result.message:
            level = "OK" if result.ok else "WARN"
            message, toast = friendly_god_files_message(result)
            self._append_issue(level, "god", message, result.message, toast=toast)

    def _energy_native_supported(self) -> bool:
        """The installed God Mode game mod file is a build with the energy switches."""
        return energy_native_supported(self.mod_root.parent / "SBGodNative" / "dlls" / "main.dll")

    def _publish_energy_switches(self) -> None:
        """Write the remembered energy switches for the game mod to read.

        Called once the game is found running (panel start, game start): the
        state file was just reset, or is left over from an earlier session. A
        game mod without the switches gets both off. Nothing is written when
        the file already says so, and God Mode's own lines are never changed.
        """
        if self._ui_fixture_active:
            return
        usable = bool(self._native_god_installed) and self._energy_native_supported()
        beta = bool(self._energy_beta and usable)
        burst = bool(self._energy_burst and usable)
        if read_native_energy_state(self.mod_root) == {"betalive": beta, "burstlive": burst}:
            return
        try:
            write_native_energy_state(
                self.mod_root,
                beta_live=beta,
                burst_live=burst,
                god_live_default=self._read_god_enabled(),
            )
        except (OSError, ValueError) as exc:
            self._append_issue(
                "WARN",
                "energy",
                "Couldn't set the unlimited energy switches for this game session. Turn them off and on again.",
                f"native_god_state.txt: {type(exc).__name__}: {exc}",
            )

    def _refresh_energy_status(self, conn=None) -> None:
        """The Unlimited energy card, from the God Mode game mod's own report."""
        if self._ui_fixture_active:
            return
        if conn is None:
            conn = evaluate_connection(self.mod_root, bool(self._game_running))
        status = energy_status(
            beta_wanted=self._energy_beta,
            burst_wanted=self._energy_burst,
            installed=bool(self._native_god_installed),
            supported=self._energy_native_supported(),
            god_state=self._god_verdict.state,
            game_running=bool(self._game_running),
            heartbeat=conn.native_heartbeat,
            heartbeat_fresh=conn.native_fresh,
        )
        logged = (status.state, status.reason)
        if logged != self._energy_logged:
            self._energy_logged = logged
            wanted = self._energy_beta or self._energy_burst
            if wanted and status.state in (ENERGY_UNSAFE, ENERGY_NEEDS_UPDATE):
                # Once per change and only while a switch is on. The card says
                # it in plain words; the reason is for the activity log.
                self._append_issue(
                    "WARN",
                    "energy",
                    "Unlimited energy isn't running. Its card on Gameplay says why.",
                    f"reason: {status.reason}" + (f"; {status.detail}" if status.detail else ""),
                    toast=False,
                )
            if status.reason in ("switching-on", "switching-off"):
                # The game mod's report does not echo the panel's switches.
                # Usually it has not read the file yet. If the file itself is
                # not what the panel set (a lost write, an edit by hand), it
                # is written again, once per change.
                self._publish_energy_switches()
        if status != self._energy_status:
            self._energy_status = status
            self.energyChanged.emit()

    def _read_version(self) -> str:
        try:
            return self.version_file.read_text(encoding="utf-8").strip()
        except Exception:
            return "unknown"

    def _read_ui_revision(self) -> str:
        ui_file = self.mod_root / "QtPanel" / "UI_REVISION"
        try:
            return ui_file.read_text(encoding="utf-8").strip() or "unknown"
        except Exception:
            return "unknown"

                                                                          
                                                                           
                                                                           
                                                                  
    PATCH_NOTES_VERSIONS_SHOWN = 4
    PATCH_NOTES_CHARS_SHOWN = 16000

    def _read_patch_notes(self) -> str:
        notes_file = self.mod_root / "PATCH_NOTES.md"
        try:
            text = notes_file.read_text(encoding="utf-8").strip()
        except (OSError, UnicodeError):
            return "What's new isn't available right now."
        return self._friendly_patch_notes(self._newest_patch_notes(text))

    @staticmethod
    def _friendly_patch_notes(text: str) -> str:
        """Support > What's new as the player reads it (Qt StyledText): no
        file title, "Version 2.5.504 · Sep 28, 2026" headings without the
        build notes in brackets, and each bullet as one list item whose
        hard-wrapped lines are joined, so it fills the box's width."""
        blocks: list[str] = []
        items: list[str] = []
        paragraph: list[str] = []

        def plain(words: str) -> str:
            # Markdown marks (`file`, **bold**) are not shown as symbols.
            return html.escape(words.replace("`", "").replace("**", ""), quote=False)

        def close() -> None:
            if paragraph:
                blocks.append("<p>" + plain(" ".join(paragraph)) + "</p>")
                paragraph.clear()
            if items:
                blocks.append("<ul>" + "".join(f"<li>{plain(item)}</li>" for item in items) + "</ul>")
                items.clear()

        for raw in text.splitlines():
            line = raw.strip()
            version = PATCH_NOTES_VERSION_RE.match(line)
            if version:
                close()
                heading = f"Version {version.group(1)}"
                if version.group(2):
                    day = datetime.date.fromisoformat(version.group(2))
                    heading += f" · {day:%b} {day.day}, {day.year}"
                blocks.append(f"<p><b>{plain(heading)}</b></p>")
            elif line.startswith("##"):
                close()
                blocks.append(f"<p><b>{plain(line.lstrip('#').strip())}</b></p>")
            elif line.startswith("#"):
                # The file's own title ("... Patch Notes") is not shown.
                close()
            elif line.startswith(("- ", "* ")):
                if paragraph:
                    close()
                items.append(line[2:].strip())
            elif not line:
                close()
            elif items:
                items[-1] += " " + line
            else:
                paragraph.append(line)
        close()
        return "".join(blocks)

    @classmethod
    def _newest_patch_notes(cls, text: str) -> str:
        """The newest few version sections ("# v..."), whole lines only."""
        lines = text.splitlines()
        kept: list[str] = []
        versions = 0
        size = 0
        for line in lines:
            if line.startswith("# v"):
                versions += 1
                if versions > cls.PATCH_NOTES_VERSIONS_SHOWN:
                    break
            if size + len(line) + 1 > cls.PATCH_NOTES_CHARS_SHOWN and versions > 1:
                break
            kept.append(line)
            size += len(line) + 1
        shown = "\n".join(kept).rstrip()
        if len(kept) < len(lines):
            shown += "\n\nOlder versions are in PATCH_NOTES.md in the panel folder."
        return shown

    def _is_game_running(self) -> bool:
        native = is_process_running(GAME_PROCESS_NAME)
        if native is not None:
            return native
        try:
            proc = subprocess.run(
                ["tasklist", "/FI", f"IMAGENAME eq {GAME_PROCESS_NAME}"],
                capture_output=True,
                text=True,
                timeout=3,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            return GAME_PROCESS_NAME in (proc.stdout or "")
        except Exception:
            return False

    def _kick_game_check(self) -> None:
        """Run the blocking `tasklist` game probe on a worker thread and cache the
        result. The 1s status poll reads the cached bool instead of blocking the
        GUI thread on a subprocess every tick (that stall made animations stutter).
        Setting a bool from the worker is GIL-atomic; a stale read is harmless."""
        if self._game_check_running:
            return
        self._game_check_running = True

        def probe() -> None:
            try:
                pid = find_process_id(GAME_PROCESS_NAME)
                if pid is None:
                    self._game_running_cached = self._is_game_running()
                    self._game_pid_cached = 0
                else:
                    self._game_pid_cached = int(pid)
                    self._game_running_cached = self._game_pid_cached > 0
                if self._game_start_note == STEAM_SIGNED_OUT_NOTE:
                    # For _recheck_game_start_note (the top bar's Steam note).
                    self._steam_note_login = self._steam_login_state()
            finally:
                self._game_check_running = False

        self._probe_pool.start(FnRunnable(probe))

    def _is_steam_running(self) -> bool:
        try:
            proc = subprocess.run(
                ["tasklist", "/FI", "IMAGENAME eq steam.exe"],
                capture_output=True,
                text=True,
                timeout=3,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            return "steam.exe" in (proc.stdout or "").lower()
        except Exception:
            return False

    def _visible_crash_reporter_windows(self) -> list[str]:
        """Return visible PlayStation crash-reporter window titles.

        ``crs-handler.exe`` also runs normally beside the game, so process
        presence alone is not a launch blocker. A titled window is the stale
        post-crash dialog that makes Steam remain in WaitingPrevProcess.
        """
        if sys.platform != "win32":
            return []
        try:
            proc = subprocess.run(
                ["tasklist", "/FI", "IMAGENAME eq crs-handler.exe", "/V", "/FO", "CSV", "/NH"],
                capture_output=True,
                text=True,
                timeout=3,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            titles: list[str] = []
            for row in csv.reader((proc.stdout or "").splitlines()):
                if len(row) < 2 or row[0].strip().lower() != "crs-handler.exe":
                    continue
                title = row[-1].strip()
                if title and title.lower() not in {"n/a", "unknown"}:
                    titles.append(title)
            return titles
        except Exception:
            return []

    def _game_process_snapshot(self) -> str:
        try:
            proc = subprocess.run(
                ["tasklist", "/FI", f"IMAGENAME eq {GAME_PROCESS_NAME}", "/FO", "LIST"],
                capture_output=True,
                text=True,
                timeout=3,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            text = ((proc.stdout or "") + "\n" + (proc.stderr or "")).strip()
            return text or "No tasklist output."
        except Exception as exc:
            return f"Could not read process snapshot: {exc}"

    def _heartbeat_alive(self) -> bool:
        """Backward-compat: Lua heartbeat file mtime within 8s."""
        return evaluate_connection(self.mod_root, True).lua_fresh

    def _native_god_active(self) -> bool:
        """Backward-compat: native heartbeat reports godlive=1."""
        conn = evaluate_connection(self.mod_root, True)
        return conn.native_fresh and conn.native_heartbeat.get("godlive") == "1"

    def _native_hook_recent(self) -> bool:
        """Backward-compat: native heartbeat file mtime within 8s."""
        return evaluate_connection(self.mod_root, True).native_fresh

    def _manifest_value(self, key: str) -> str:
        if not self.app_manifest_file.exists():
            return ""
        try:
            text = self.app_manifest_file.read_text(encoding="utf-8", errors="replace")
            match = re.search(r'"' + re.escape(key) + r'"\s+"([^"]*)"', text)
            if not match:
                return ""
            return match.group(1).replace("\\\\", "\\")
        except Exception:
            return ""

    def _steam_exe_candidates(self) -> list[Path]:
        candidates: list[Path] = []
        manifest_launcher = self._manifest_value("LauncherPath")
        if manifest_launcher:
            candidates.append(Path(manifest_launcher))
        for raw in (
            os.environ.get("STEAMEXE", ""),
            os.environ.get("SteamPath", ""),
            r"C:\Program Files (x86)\Steam\steam.exe",
            r"C:\Program Files\Steam\steam.exe",
        ):
            if raw:
                path = Path(raw)
                if path.is_dir():
                    path = path / "steam.exe"
                candidates.append(path)

        unique: list[Path] = []
        seen: set[str] = set()
        for candidate in candidates:
            key = str(candidate).lower()
            if key in seen:
                continue
            seen.add(key)
            unique.append(candidate)
        return unique

    def _steam_root(self) -> Path | None:
        """The Steam folder (logs/steamui_login.txt lives there)."""
        for candidate in self._steam_exe_candidates():
            if candidate.exists():
                return candidate.parent
        return None

    def _steam_login_state(self) -> SteamLogin:
        pid = find_process_id("steam.exe")
        if pid is None:
            pid = 1 if self._is_steam_running() else 0
        return read_steam_login(int(pid), self._steam_root())

    def _game_pid_now(self) -> int:
        pid = find_process_id(GAME_PROCESS_NAME)
        if pid is None:
            return 1 if self._is_game_running() else 0
        return int(pid)

    def _follow_game_start(self, attempts: list[str], label: str, timeout: float) -> StartWatch:
        """Follow the game's own process until it really started or ended
        (services/game_start.py); build 3 counted 2 s alive as a start."""
        watch = follow_game_start(self._game_pid_now, process_has_window, self._steam_login_state, timeout)
        attempts.append(f"{label}: {watch.outcome} - {watch.detail}")
        return watch

    def _launch_warning(self, message: str, attempts: list[str]) -> dict:
        result = {"ok": False, "level": "WARN", "message": message, "attempts": attempts}
        result["report"] = str(self._write_launch_report(result))
        return result

    def _write_launch_report(self, result: dict) -> Path:
        stamp = time.strftime("%Y%m%d-%H%M%S")
        self.support_reports_dir.mkdir(parents=True, exist_ok=True)
        report = self.support_reports_dir / f"GameLaunchDiagnostic-{stamp}.txt"
        lines = [
            "SBCheatGUI Game Launch Diagnostic",
            f"Created: {time.strftime('%Y-%m-%d %H:%M:%S %z')}",
            f"Version: {self._read_version()}",
            f"Result: {'OK' if result.get('ok') else 'FAIL'}",
            f"Message: {result.get('message', '')}",
            f"Steam app id: {STEAM_APP_ID}",
            f"Manifest: {self.app_manifest_file}",
            f"Manifest exists: {self.app_manifest_file.exists()}",
            f"Manifest InstallDir: {self._manifest_value('installdir') or '(missing)'}",
            f"Manifest LauncherPath: {self._manifest_value('LauncherPath') or '(missing)'}",
            f"Steam running now: {self._is_steam_running()}",
            f"Visible PlayStation crash reporter: {', '.join(self._visible_crash_reporter_windows()) or '(none)'}",
            f"Steam candidates: {', '.join(str(p) + (' [exists]' if p.exists() else ' [missing]') for p in self._steam_exe_candidates())}",
            f"Game exe: {self.game_exe}",
            f"Game exe exists: {self.game_exe.exists()}",
            f"Game running now: {self._is_game_running()}",
            "",
            "Game process snapshot:",
            self._game_process_snapshot(),
            "",
            "Attempts:",
        ]
        lines.extend(f"- {attempt}" for attempt in result.get("attempts", []))
        report.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return report

    def _launch_game_worker(self) -> dict:
        attempts: list[str] = []
        if self._is_game_running():
            return {"ok": True, "message": "Stellar Blade is already running.", "attempts": ["already_running"]}

        profile = enforce_hook_free_retry_profile(self.mod_root.parent)
        self._hook_free_profile_safe = profile.safe
        self._hook_free_profile_status = profile.detail
        self.movementChanged.emit()
        attempts.append(f"Safe gameplay profile: {profile.detail}")
        if not profile.safe:
            result = {
                "ok": False,
                "message": (
                    "Stellar Blade wasn't started because the game mods couldn't "
                    "be set up safely. Run One-Click Repair on Support."
                ),
                "attempts": attempts,
            }
            result["report"] = str(self._write_launch_report(result))
            return result

        crash_windows = self._visible_crash_reporter_windows()
        if crash_windows:
            result = {
                "ok": False,
                "message": (
                    "A PlayStation Report Problem window is blocking Steam. "
                    "Close that window (Report or Don't Report), then press Start game again."
                ),
                "attempts": [f"Visible crash reporter: {title}" for title in crash_windows],
            }
            result["report"] = str(self._write_launch_report(result))
            return result

        steam_was_running = self._is_steam_running()
        attempts.append(f"Steam running before launch: {steam_was_running}")
        login = self._steam_login_state()
        attempts.append(f"Steam sign-in before launch: {login.describe()}")
        if login.signed_out:
            # Nothing can start the game until someone signs in: a direct
            # start would only hand itself back to the signed-out Steam.
            return self._launch_warning(STEAM_SIGNED_OUT_MESSAGE, attempts)
        launch_sent = False

        def finished(watch: StartWatch, ok_message: str) -> dict | None:
            """The result once a watch ended the start; None to try the
            next way (nothing started)."""
            if watch.ok:
                return {"ok": True, "level": "OK", "message": ok_message, "attempts": attempts}
            if watch.outcome == "signed-out":
                return self._launch_warning(STEAM_SIGNED_OUT_MESSAGE, attempts)
            if watch.outcome == "exited":
                return self._launch_warning(GAME_EXITED_MESSAGE, attempts)
            return None

        # One Steam URI only — a second URI/applaunch while the first is still starting spawns duplicate games.
        uri = f"steam://rungameid/{STEAM_APP_ID}"
        try:
            os.startfile(uri)
            launch_sent = True
            attempts.append(f"Steam URI sent: {uri}")
            # A Steam that was closed (or is still signing in) first starts and
            # signs in; a signed-out one is only named after its 30 s wait.
            steam_ready = steam_was_running and login.signed_in
            watch = self._follow_game_start(attempts, f"Steam URI ({uri})", 20.0 if steam_ready else 60.0)
            result = finished(watch, "Stellar Blade started through Steam.")
            if result is not None:
                return result
        except Exception as exc:
            attempts.append(f"Steam URI failed ({uri}): {exc}")

        if self._is_game_running():
            return {"ok": True, "level": "OK", "message": "Stellar Blade is running.", "attempts": attempts}

        # A successful URI dispatch already asked Steam to start this app. Do
        # not send a second -applaunch request; proceed to the local fallback.
        for steam_exe in ([] if launch_sent else self._steam_exe_candidates()):
            if self._is_game_running():
                return {"ok": True, "level": "OK", "message": "Stellar Blade is running.", "attempts": attempts}
            if not steam_exe.exists():
                attempts.append(f"Steam client missing: {steam_exe}")
                continue
            try:
                subprocess.Popen(
                    [str(steam_exe), "-applaunch", STEAM_APP_ID],
                    cwd=str(steam_exe.parent),
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                launch_sent = True
                attempts.append(f"Steam -applaunch sent: {steam_exe} -applaunch {STEAM_APP_ID}")
                watch = self._follow_game_start(attempts, f"Steam -applaunch ({steam_exe})", 45.0)
                result = finished(watch, "Stellar Blade started through Steam.")
                if result is not None:
                    return result
            except Exception as exc:
                attempts.append(f"Steam -applaunch failed from {steam_exe}: {exc}")

        if self._is_game_running():
            return {"ok": True, "level": "OK", "message": "Stellar Blade is running.", "attempts": attempts}

        login = self._steam_login_state()
        if login.signed_out:
            attempts.append(f"Steam sign-in before the direct start: {login.describe()}")
            return self._launch_warning(STEAM_SIGNED_OUT_MESSAGE, attempts)

        if self.game_exe.exists():
            try:
                subprocess.Popen(
                    [str(self.game_exe)],
                    cwd=str(self.game_exe.parent),
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                launch_sent = True
                attempts.append(f"Direct EXE fallback sent: {self.game_exe}")
                watch = self._follow_game_start(attempts, "Direct EXE fallback", 20.0)
                result = finished(watch, "Stellar Blade started directly because Steam did not respond.")
                if result is not None:
                    return result
            except Exception as exc:
                attempts.append(f"Direct EXE fallback failed: {exc}")
        else:
            attempts.append(f"Game EXE missing: {self.game_exe}")

        if self._is_game_running():
            return {"ok": True, "level": "OK", "message": "Stellar Blade is running.", "attempts": attempts}

        reason = (
            "Steam didn't start the game. Check Steam, then try again."
            if launch_sent
            else "Couldn't find Steam or the game to start it. Check that Steam is installed."
        )
        result = {"ok": False, "level": "ERROR", "message": reason, "attempts": attempts}
        result["report"] = str(self._write_launch_report(result))
        return result

    def _catalog_row_priority(self, row: dict) -> tuple[int, int, str]:
        alias = str(row.get("alias") or "")
        source = str(row.get("source") or "")
        source_rank = {"database": 30, "live": 20, "save": 10}.get(source, 0)
        canonical_rank = 8 if re.match(r"^(Item|Util|ETC|Gear)_", alias, flags=re.IGNORECASE) else 0
        return source_rank + canonical_rank, len(alias), alias

    def _load_catalog(self) -> None:
        """Load the generated v0.5 catalog (PLAN C10) into the item list.

        Listed rows (default items plus the opt-in groups that are on) fill
        the list; excluded items, opt-in items that are off and the Money
        card's currencies follow as search-only rows with a plain reason.
        """
        catalog = load_catalog(catalog_paths(self.mod_root))
        if catalog.error and catalog.error != self._items_catalog.error:
            self._append_issue(
                "WARN", "items", "The item list couldn't be loaded. Run One-Click Repair on Support.",
                catalog.error, toast=False,
            )
        self._items_catalog = catalog
        self._rebuild_item_rows()

    def _rebuild_item_rows(self) -> None:
        rows = display_rows(self._items_catalog, self._items_optins)
        self._catalog_rows = rows
        self._items_model.set_rows(rows)
        listed = [row for row in rows if row["listed"]]
        present = {row["category"] for row in listed}
        self._categories = ["All"] + [
            name for name in self._items_catalog.category_order if name in present
        ]
        self._item_policy_db_summary = (
            f"{len(listed)} items in the list, {len(rows) - len(listed)} more found only by search"
        )
        self._items_chip_signature = None
        self._apply_item_chips()
        self._apply_filter()

    def _apply_filter(self) -> None:
        if self._items_proxy.set_query(self._filter, self._category):
            self.itemsChanged.emit()

    def _items_listed_count(self) -> int:
        return sum(1 for row in self._catalog_rows if row.get("listed"))

    def _items_match_counts(self) -> tuple[int, int]:
        """(listed, search-only) rows the current search and category show."""
        proxy = self._items_proxy
        listed = hidden = 0
        for index in range(proxy.rowCount()):
            if proxy.data(proxy.index(index, 0), ItemListModel.ListedRole) is False:
                hidden += 1
            else:
                listed += 1
        return listed, hidden

    # -- Items & Money v0.5: what the installed game mod can do -------------

    def _items_mode_now(self) -> str:
        """``probe`` (v0.5 game mod), ``legacy`` (a trusted Live Add v3 game
        mod: only its embedded allowlist) or ``none`` (not installed, turned
        off, untrusted or needing an update: rows stay quiet)."""
        if self._items_fixture is not None:
            return str(self._items_fixture.get("mode") or "probe")
        if not (self._live_add_installed and self._live_add_trusted):
            return "none"
        if self._live_add_probe_seen:
            return "probe"
        try:
            native_sha = file_sha256(self.live_add_native_dll).upper()
        except OSError:
            native_sha = ""
        if native_sha and native_sha in {sha.upper() for sha in PROBE_CAPABLE_LIVE_ADD_NATIVE_SHA256}:
            return "probe"
        return "legacy"

    def _items_route_ok_now(self) -> bool:
        if self._items_fixture is not None:
            return bool(self._items_fixture.get("route_ready", True))
        # An add in flight keeps the route healthy: chips must not blink off
        # while one item is being added.
        return bool(self._live_add_ready or self._live_add_phase == "adding")

    def _probe_entry(self, alias: str) -> ProbeEntry | None:
        return self._probe_entries.get(alias)

    def _apply_item_chips(self) -> None:
        """Label every listed row (Ready / Owned / At limit / Needs DLC /
        Not available) from the probe answers or the older game mod's list."""
        mode = self._items_mode_now()
        route_ok = self._items_route_ok_now()
        signature = (mode, route_ok, self._probe_version, self._probe_answered_all, len(self._catalog_rows))
        if signature == self._items_chip_signature:
            return
        self._items_chip_signature = signature
        self._items_mode = mode
        self._items_route_ok = route_ok
        updates: dict[str, tuple[str, str, str, str]] = {}
        for row in self._catalog_rows:
            if not row.get("listed"):
                continue
            chip, reason = item_chip(
                row,
                self._probe_entry(row["alias"]),
                route_ready=route_ok,
                mode=mode,
                answered_all=self._probe_answered_all,
            )
            updates[row["alias"]] = (chip, CHIP_LABELS.get(chip, ""), CHIP_KINDS.get(chip, "off"), reason)
        self._items_model.set_chips(updates)
        self._refresh_selected_item()
        self._refresh_money_state()

    def _refresh_selected_item(self) -> None:
        """The Add card: chip, reason and quantity limit of the chosen item."""
        row = self._catalog_row_for_alias(self._selected_alias) or {}
        mode = self._items_mode
        if not row:
            values = ("UNKNOWN", False, "", "", 0)
        elif not row.get("listed"):
            chip = row.get("chip") or ""
            values = ("BLOCKED", False, chip, row.get("listReason") or "", 0)
        else:
            chip = row.get("chip") or ""
            reason = row.get("chipReason") or ""
            limit = per_add_limit(row, self._probe_entry(row["alias"]), mode=mode)
            supported = mode != "none" and chip not in {"not_available", "needs_dlc"}
            values = ("SAFE", supported, chip, reason, limit)
        level, supported, chip, reason, limit = values
        changed = (
            row != self._selected_row
            or level != self._item_policy_level
            or supported != self._item_live_supported
            or chip != self._selected_chip
            or reason != self._selected_chip_reason
            or limit != self._selected_max_qty
        )
        self._selected_row = row
        self._item_policy_level = level
        self._item_policy_text = reason
        self._item_policy_detail = reason
        self._item_live_supported = supported
        self._selected_chip = chip
        self._selected_chip_reason = reason
        self._selected_max_qty = limit
        if limit and self._qty > limit:
            self._qty = limit
            changed = True
        if changed:
            self.selectedItemChanged.emit()

    def _money_row(self) -> dict:
        return self._catalog_row_for_alias(self._money_alias) or {}

    def _refresh_money_state(self) -> None:
        """The Money card: balance, the most one add may send, and one line."""
        row = self._money_row()
        name = str(row.get("name") or "Gold")
        mode = self._items_mode
        route_ok = self._items_route_ok
        entry = self._probe_entry(self._money_alias) if row else None
        balance = entry.count if entry is not None and entry.state in {"available", "at_limit"} else -1
        tier = int(row.get("max") or 0)
        state = "not_available"
        ready = False
        max_add = tier
        if not row:
            text = "The item list couldn't be loaded. Run One-Click Repair on Support."
            max_add = 0
        elif mode == "none":
            text = (
                "The Items & Money game mod is not installed."
                if not self._live_add_installed
                else f"{name} can be added once Items & Money is ready."
            )
        elif mode == "legacy":
            text = f"Adding {name} comes with the next Items & Money update."
        elif self._live_add_busy:
            state = "adding"
            text = "Adding... one request at a time."
        elif not route_ok:
            text = f"{name} can be added once Items & Money is ready."
        elif entry is None:
            state = "not_available" if self._probe_answered_all else "checking"
            text = (
                f"Adding {name} is off in the Items & Money game mod for now."
                if self._probe_answered_all
                else f"Checking your {name}..."
            )
        elif entry.state == "available" and entry.addable_now > 0:
            state = "ready"
            ready = True
            max_add = max(0, min(tier, entry.addable_now))
            text = f"You have {entry.count:,} {name}. Add up to {max_add:,} at a time."
        elif entry.state in {"available", "at_limit"}:
            state = "at_limit"
            max_add = 0
            limit = f" ({entry.max:,})" if entry.max else ""
            text = f"You have the most {name} the game allows{limit}."
        elif entry.state == "needs_dlc":
            state = "needs_dlc"
            text = DLC_REASON
        elif entry.state == "not_read":
            state = "checking"
            text = f"Checking your {name}..."
        else:
            reason = state_reason(entry.state) or "The game didn't confirm how much you can carry."
            text = f"{name} can't be added right now. {reason}"
        # A pending large-amount confirmation lapses as soon as it could no
        # longer be sent exactly as confirmed.
        confirm = self._money_confirm_amount
        if confirm and (
            not ready
            or self._money_confirm_alias != self._money_alias
            or confirm > max_add
            or time.monotonic() - self._money_confirm_at > MONEY_CONFIRM_SEC
        ):
            confirm = 0
        values = {
            "_money_status_state": state,
            "_money_live_add_ready": ready,
            "_money_live_add_status": text,
            "_money_balance": balance,
            "_money_max_add": max_add,
            "_money_confirm_amount": confirm,
        }
        if any(getattr(self, key) != value for key, value in values.items()):
            for key, value in values.items():
                setattr(self, key, value)
            self.liveAddChanged.emit()

    def _append_issue(
        self, level: str, area: str, message: str, detail: str = "", *, toast: bool = True
    ) -> None:
        """Write one activity-log line and show ``message`` as a toast.

        ``message`` is what the player reads, in plain words. ``detail`` is
        the technical reason (codes, file names, paths); it goes only to the
        activity log on Support and to support reports. ``toast=False`` keeps
        routine housekeeping in the log and out of the player's way.
        """
        logged = f"{message} [{detail}]" if detail else message
        line = format_issue_line(level, area, logged)
        try:
            rotate_issue_log(self.issue_log_file)
            with self.issue_log_file.open("a", encoding="utf-8") as f:
                f.write(line + "\n")
        except Exception:
            pass
        if toast:
            self.operationMessage.emit(message)
            self.operationNotice.emit(message, level)
        self.refresh_log()

    def use_scratch_issue_log(self) -> None:
        """Automation runs (captures, pace probe, smoke) keep their lines out
        of the real activity log: they write to a copy in a temporary folder.
        2.5.504 review: every capture run added a once-per-session game-mod
        note, so the captured log repeated it every 10-20 s. The copy goes
        away when the run ends."""
        self._scratch_log_dir = tempfile.TemporaryDirectory(prefix="sbpanel-run-")
        scratch = Path(self._scratch_log_dir.name) / self.issue_log_file.name
        try:
            shutil.copyfile(self.issue_log_file, scratch)
        except OSError:
            pass
        self.issue_log_file = scratch
        self.refresh_log()

    def _read_issue_tail(self) -> str:
        'The newest 90 activity-log lines, newest first.'





        # No file yet, or an empty one: "" lets Support show its friendly
        # "No activity yet" line instead of a file message.
        if not self.issue_log_file.exists():
            return ""
        try:
            with self.issue_log_file.open("rb") as stream:
                size = stream.seek(0, os.SEEK_END)
                start = max(0, size - 256 * 1024)
                stream.seek(start, os.SEEK_SET)
                raw = stream.read(256 * 1024)
            lines = raw.decode("utf-8", errors="replace").splitlines()
            if start > 0 and lines:
                lines = lines[1:]
            lines = [line for line in lines if line.strip()]
            return "\n".join(reversed(lines[-90:])) if lines else ""
        except Exception as exc:
            return f"Could not read the activity log: {exc}"

    def _default_state(self) -> dict:
        return {
            "god": "0",
            "speed": "1.0",
            "walk": "1.0",
            "jump": "1.0",
            "itemcount": "0",
            "itemseq": "0",
            "itemclass": "BP_EquipInvenData_C",
            "itemprop": "Count",
            "itemalias": "",
            "itemprobeseq": "0",
            "healseq": "0",
            "godlive": "0",
            "godseq": "0",
            "spawnalias": "",
            "spawnqty": "1",
            "spawnlevel": "0",
            "spawnmode": "inventory",
            "spawnseq": "0",
            "spawnsession": "",
            "spawnrequest": "",
            "spawnissuedunixs": "0",
            "modsreloadseq": "0",
        }

    def _update_state(self, updates: dict) -> None:
        state = self._default_state()
        state.update(read_kv(self.state_file))
        state.update({k: str(v) for k, v in updates.items()})
        write_kv_atomic(self.state_file, state)

    def _inc_state_seq(self, key: str) -> int:
        state = self._default_state()
        state.update(read_kv(self.state_file))
        try:
            seq = int(state.get(key, "0")) + 1
        except Exception:
            seq = 1
        state[key] = str(seq)
        write_kv_atomic(self.state_file, state)
        return seq

    def _run_save_tool(self, action: str) -> dict:
        if action not in {"Backup", "Audit"}:
            raise RuntimeError("The public Mod Suite only permits read-only audit and backup actions.")
        if not self.save_tools.exists():
            raise RuntimeError("SaveTools.ps1 is missing.")
        cmd = [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(self.save_tools),
            "-Action",
            action,
        ]
        proc = subprocess.run(
            cmd,
            cwd=str(self.mod_root),
            capture_output=True,
            text=True,
            timeout=90,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        text = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
        parsed = parse_tool_output(text)
        if proc.returncode != 0 or parsed.get("ok") == "0":
            raise RuntimeError(parsed.get("message") or text.strip() or f"{action} failed")
        return parsed

    def _live_probe_ready(self) -> tuple[bool, str]:
        if not self.item_probe_file.exists():
            return False, "No live probe exists yet. Open the in-game Bag tab and refresh catalog first."
        try:
            age = time.time() - self.item_probe_file.stat().st_mtime
            if age > 300:
                return False, "Live probe is stale. Load Eve, open the Bag tab, then refresh catalog."
            live_aliases = 0
            for raw in self.item_probe_file.read_text(encoding="utf-8", errors="replace").splitlines():
                if raw.startswith("LIVE_ALIASES="):
                    live_aliases = int(raw.split("=", 1)[1].strip() or "0")
                    break
            if live_aliases <= 0:
                return False, "Live probe has 0 loaded inventory rows. Open the matching Bag tab and refresh catalog first."
            return True, f"Live probe ready with {live_aliases} loaded rows."
        except Exception as exc:
            return False, f"Could not read live probe: {exc}"

    def _save_panel_setting(self, key: str, value: str) -> None:
        settings = read_kv(self.settings_file)
        settings[key] = value
        write_kv_atomic(self.settings_file, settings)

    @staticmethod
    def _normalize_active_page(page: str) -> str:
        value = str(page or "gameplay").strip().lower()
        if value in {"gameplay", "items", "settings", "support"}:
            return value
        return "gameplay"

    def attach_window(self, window) -> None:
        self._window = window
        self._performance.attach_window(window)
        self._dock_restore_done = False
        self._dock_restore_attempts = 0
        try:
            window.visibilityChanged.connect(self._on_window_visibility_changed)
        except Exception:
            pass
        for signal_name in ("xChanged", "yChanged", "widthChanged", "heightChanged"):
            try:
                getattr(window, signal_name).connect(self._schedule_geometry_persist)
            except Exception:
                pass
        try:
            self._last_window_visibility = window.visibility()
        except RuntimeError:
            self._last_window_visibility = None
        # Back where it was closed before its first frame is drawn; the timed
        # retries below cover a window the system has not placed yet.
        self._try_apply_saved_dock()
        self._schedule_saved_dock_apply()
        QTimer.singleShot(3500, self._show_window_if_hidden)

    def enable_window_memory(self) -> None:
        """The real panel reopens where it was closed (main() turns this on).
        Automation runs (--smoke, --screenshot) neither move the window to
        the saved place nor overwrite it."""
        self._window_memory_enabled = True

    def _schedule_geometry_persist(self) -> None:
        # Debounced: the rect is read once moving/resizing has settled, so
        # the size Windows reports mid-maximize never becomes the saved
        # (un-maximized) size.
        if self._dock_restore_done and self._window is not None:
            self._geometry_persist_timer.start()

    def _persist_window_on_close(self) -> None:
        # Not before the saved place was applied: the window still sits at
        # the default rect then, and saving it would overwrite the real
        # placement (2.5.504 review: a close before a restore retry
        # succeeded lost the saved window).
        if self._window is None or not self._dock_restore_done:
            return
        self._persist_window_geometry()
        if self._dock_mode and self._window_memory_enabled:
            self._save_panel_setting("dock", self._dock_mode)

    @Slot()
    def persistWindowPlacement(self) -> None:
        self._persist_window_on_close()

    @staticmethod
    def _visibility_name(visibility) -> str:
        for name in ("Windowed", "Maximized", "FullScreen", "Minimized", "Hidden"):
            try:
                if visibility == getattr(QWindow.Visibility, name):
                    return name
            except (AttributeError, TypeError):
                pass
        return "Other"

    def _window_screens(self) -> tuple[list[ScreenDesc], int]:
        """Every connected screen as the placement helper sees it, and the
        primary one's index."""
        screens = list(QGuiApplication.screens() or [])
        primary = QGuiApplication.primaryScreen()
        index = next((i for i, screen in enumerate(screens) if screen is primary), 0)
        return [screen_from_qscreen(screen) for screen in screens], index

    def _window_screen_desc(self) -> ScreenDesc | None:
        try:
            screen = self._window.screen() if self._window is not None else None
        except RuntimeError:
            screen = None
        return screen_from_qscreen(screen) if screen is not None else None

    def _window_title_height(self) -> int:
        """The window's title bar (top frame margin), kept on screen when a
        saved rect has to be moved; 32 before Windows has framed it."""
        try:
            top = int(self._window.frameMargins().top())
        except (AttributeError, RuntimeError):
            top = 0
        return top if top > 0 else 32

    def _track_normal_geometry(self) -> None:
        """Remember the un-maximized rect and its screen.

        Read while the window is Windowed and settled (debounced), or at the
        close when it was Windowed just before; a maximized or minimized
        window keeps the last normal rect it had.
        """
        window = self._window
        if window is None:
            return
        try:
            visibility = self._visibility_name(window.visibility())
        except RuntimeError:
            return
        if visibility in ("Maximized", "FullScreen"):
            self._window_was_maximized = True
            self._maximized_screen = self._window_screen_desc()
            return
        if visibility == "Hidden":
            # The close: the window was Windowed right before, so its last
            # rect is the one to keep.
            if self._visibility_name(self._last_window_visibility) != "Windowed":
                return
        elif visibility != "Windowed":
            return
        else:
            self._window_was_maximized = False
        rect = window.geometry()
        if rect.width() <= 0 or rect.height() <= 0:
            return
        self._normal_rect = WindowBox(rect.x(), rect.y(), rect.width(), rect.height())
        self._normal_screen = self._window_screen_desc()

    def _show_window_if_hidden(self) -> None:
        if self._window is None:
            return
        try:
            if not self._window.property("visible"):
                self._window.setProperty("visible", True)
            self._activate_window()
        except Exception:
            pass

    def _on_window_visibility_changed(self, visibility) -> None:
        try:
            visible = visibility in (
                QWindow.Visibility.Windowed,
                QWindow.Visibility.Maximized,
                QWindow.Visibility.FullScreen,
            )
        except Exception:
            visible = int(visibility) in (2, 4, 5)
        if visible and not self._dock_restore_done:
            QTimer.singleShot(40, self._try_apply_saved_dock)
        name = self._visibility_name(visibility)
        if name in ("Maximized", "FullScreen"):
            self._window_was_maximized = True
            self._maximized_screen = self._window_screen_desc()
        elif name == "Windowed":
            if self._maximize_guard_active() and not self._placing_window:
                # Un-maximized right after the restore by something else
                # (a launcher's SW_RESTORE): maximize it again.
                self._schedule_maximize_check(0)
            self._window_was_maximized = False
        if name == "Hidden" and self._dock_restore_done:
            # Windows can unsnap to the old normal rect while hiding.
            # Keep the settled rect or the flush from QML onClosing.
            self._persist_window_geometry(track=False)
        else:
            self._schedule_geometry_persist()
        self._last_window_visibility = visibility

    def _schedule_saved_dock_apply(self) -> None:
        for delay in (0, 80, 200, 400, 800, 1500, 2500, 4000):
            QTimer.singleShot(delay, self._try_apply_saved_dock)

    def _persist_window_geometry(self, track: bool = True) -> None:
        """Save the window's place: its screen (name, serial, model), the
        un-maximized rect relative to that screen, and whether it is
        maximized (window_placement.placement_to_settings)."""
        if self._window is None or not self._window_memory_enabled:
            return
        try:
            if track:
                self._track_normal_geometry()
            if self._normal_rect is None:
                return
            maximized = bool(self._window_was_maximized)
            updates = placement_to_settings(
                self._normal_rect,
                self._normal_screen,
                maximized,
                (self._maximized_screen or self._normal_screen) if maximized else None,
            )
            self._sync_dock_mode_to_window(maximized)
            settings = read_kv(self.settings_file)
            settings.update(updates)
            settings["dock"] = self._dock_mode or settings.get("dock", "free")
            write_kv_atomic(self.settings_file, settings)
        except Exception:
            pass

    def _sync_dock_mode_to_window(self, maximized: bool) -> None:
        """Settings > Screen position says where the window really is: a
        side or Center only while the window still sits at that dock's rect
        on its screen, Maximized while maximized, otherwise Free (build 3
        kept "Left side" after the window was moved freely)."""
        mode = current_dock_mode(
            self._normal_rect,
            self._normal_screen,
            maximized,
            self._dock_mode or "free",
        )
        if mode != (self._dock_mode or "free"):
            self._dock_mode = mode
            self.settingsChanged.emit()

    def _maximize_window(self) -> bool:
        try:
            self._window.setVisibility(QWindow.Visibility.Maximized)
        except Exception:
            try:
                self._window.setVisibility(QWindow.Maximized)
            except Exception:
                return False
        self._activate_window()
        return True

    def _restore_saved_rect(self) -> bool:
        """Put the window back at the saved size and place on the saved
        screen, maximized there if it was (window_placement.restore_placement:
        any size down to the window minimum, mixed DPI, a missing screen falls
        back to the primary one)."""
        if self._window is None or not self._window_memory_enabled:
            return False
        settings = read_kv(self.settings_file)
        screens, primary = self._window_screens()
        docked = (self._dock_mode or "free").strip().lower() not in ("free", "")
        placement = restore_placement(
            settings,
            screens,
            primary,
            min_size=(WINDOW_MIN_WIDTH, WINDOW_MIN_HEIGHT),
            # A docked rect is the dock's own layout (flush with the screen
            # edge); a free one keeps its title bar reachable.
            top_reserve=0 if docked else self._window_title_height(),
        )
        if placement is None:
            return False
        box = placement.rect
        # The normal rect first, on the saved screen, so maximizing happens
        # on that monitor and un-maximizing later returns to this rect.
        ok = self._set_window_geometry(QRect(box.x, box.y, box.width, box.height))
        if ok and placement.maximized:
            ok = self._maximize_window()
        if ok:
            self._normal_rect = box
            self._normal_screen = screens[placement.screen_index]
            self._window_was_maximized = placement.maximized
            self._maximized_screen = screens[placement.screen_index] if placement.maximized else None
            if placement.maximized:
                                                                         
                                                                        
                                                                    
                self._maximize_guard_until = time.monotonic() + MAXIMIZE_GUARD_SECONDS
                for delay in MAXIMIZE_CHECK_DELAYS_MS:
                    self._schedule_maximize_check(delay)
        return ok

    def _maximize_guard_active(self) -> bool:
        return time.monotonic() < self._maximize_guard_until

    def _schedule_maximize_check(self, delay_ms: int) -> None:
        QTimer.singleShot(int(delay_ms), self._verify_restored_maximize)

    def _verify_restored_maximize(self) -> None:
        """Maximized again on the saved monitor if something un-maximized
        the restored window during the guard (the user's own un-maximize
        after that is kept)."""
        if self._window is None or not self._maximize_guard_active():
            return
        try:
            name = self._visibility_name(self._window.visibility())
        except RuntimeError:
            return
        if name != "Windowed" or self._placing_window:
            return
        target = self._maximized_screen or self._normal_screen
        current = self._window_screen_desc()
        if (
            target is not None
            and self._normal_rect is not None
            and (current is None or current.name != target.name)
        ):
            box = self._normal_rect
            self._set_window_geometry(QRect(box.x, box.y, box.width, box.height))
        if self._maximize_window():
            self._window_was_maximized = True
            self._maximized_screen = target
            self._schedule_geometry_persist()

    def _restore_free_geometry(self) -> bool:
        return self._restore_saved_rect()

    def _ensure_window_on_screen(self) -> bool:
        if self._window is None:
            return False
        try:
            rect = self._window.geometry()
            screens = QGuiApplication.screens() or []
            for screen in screens:
                if screen.availableGeometry().intersects(rect):
                    return True
            geo = self._available_window_geometry()
            w = max(WINDOW_MIN_WIDTH, min(rect.width(), geo.width()))
            h = max(WINDOW_MIN_HEIGHT, min(rect.height(), geo.height()))
            return self._set_window_geometry(
                QRect(geo.x() + (geo.width() - w) // 2, geo.y() + (geo.height() - h) // 2, w, h)
            )
        except Exception:
            return False

    def _try_apply_saved_dock(self) -> None:
        if self._dock_restore_done or self._window is None:
            return
        self._dock_restore_attempts += 1
        mode = (self._dock_mode or "free").strip().lower()
        settings = read_kv(self.settings_file)
        saved_dock = (settings.get("dock", "free") or "free").strip().lower()
        ok = False
        restored = False
        if settings.get("bounds") == "1" and saved_dock == mode:
            ok = restored = self._restore_saved_rect()
        if not ok and mode and mode != "free":
            ok = self._apply_dock_mode(mode, save=False)
        elif not ok:
            ok = restored = self._restore_saved_rect()
            if not ok and self._window_memory_enabled and settings.get("bounds") != "1":
                # Nothing saved yet (first start): keep the default place and
                # start remembering moves and resizes now.
                ok = True
        if ok:
            # A restore already knows the state it set; reading the window
            # back could catch a maximize that Windows has not applied yet.
            self._persist_window_geometry(track=not restored)
            self._dock_restore_done = True
            self._show_window_if_hidden()
        elif self._dock_restore_attempts >= 14:
            self._dock_restore_done = True
            self._show_window_if_hidden()
        if not ok and self._dock_restore_attempts >= 4:
            self._ensure_window_on_screen()

    def _activate_window(self) -> None:
        if self._window is None:
            return
        for method_name in ("raise_", "requestActivate"):
            try:
                method = getattr(self._window, method_name, None)
                if method is not None:
                    method()
            except Exception:
                pass

    def _available_window_geometry(self):
        screen = None
        try:
            if self._window is not None:
                screen = self._window.screen()
        except Exception:
            screen = None
        if screen is None:
            screen = QGuiApplication.primaryScreen()
        if screen is None:
            return QRect(0, 0, 1280, 900)
        return screen.availableGeometry()

    def _set_window_geometry(self, rect: QRect) -> bool:
        if self._window is None:
            return False
        self._placing_window = True
        try:
            try:
                self._window.setVisibility(QWindow.Windowed)
            except Exception:
                try:
                    self._window.setVisibility(QWindow.Visibility.Windowed)
                except Exception:
                    pass
        finally:
            self._placing_window = False
        try:
            place_window_exactly(self._window, rect)
            self._activate_window()
            return True
        except Exception:
            try:
                self._window.setX(rect.x())
                self._window.setY(rect.y())
                self._window.setWidth(rect.width())
                self._window.setHeight(rect.height())
                self._activate_window()
                return True
            except Exception:
                return False

    def _apply_dock_mode(self, mode: str, save: bool = True) -> bool:
        mode = (mode or "center").strip().lower()
        if mode not in {"left", "right", "top", "bottom", "center", "max", "free"}:
            mode = "center"
        if self._window is None:
            if save:
                self._dock_mode = mode
                self._save_panel_setting("dock", mode)
                self.settingsChanged.emit()
            return False

        if save:
            # The user chose a place: nothing re-maximizes behind them.
            self._maximize_guard_until = 0.0
        geo = self._available_window_geometry()
        ax, ay, aw, ah = geo.x(), geo.y(), geo.width(), geo.height()
        ok = False
        docked = dock_rect(mode, WindowBox(ax, ay, aw, ah))

        if mode == "max":
            try:
                self._window.setVisibility(QWindow.Maximized)
                self._activate_window()
                ok = True
            except Exception:
                try:
                    self._window.setVisibility(QWindow.Visibility.Maximized)
                    self._activate_window()
                    ok = True
                except Exception:
                    ok = self._set_window_geometry(QRect(ax, ay, aw, ah))
        elif docked is not None:
            ok = self._set_window_geometry(QRect(docked.x, docked.y, docked.width, docked.height))
        else:
            ok = True

        if save:
            self._dock_mode = mode
            self._save_panel_setting("dock", mode)
            self.settingsChanged.emit()
        if ok:
            self._persist_window_geometry()
            if mode != "free":
                self._dock_restore_done = True
        return ok

    def _ibr_game_started_at(self) -> float | None:
        """When this game process started (cached per process), or None."""
        pid = int(self._game_pid_cached or 0) if self._game_running_cached else 0
        if pid <= 0:
            return None
        if self._ibr_started[0] != pid:
            self._ibr_started = (pid, process_started_at(pid))
        return self._ibr_started[1]

    def _ibr_inputs(self) -> tuple[IbrInstall, bool, dict[str, str] | None]:
        """The game mod's install, the switch and its status (files on disk,
        or the recorded ones of a --ui-fixture run)."""
        if self._ibr_fixture is not None:
            return self._ibr_fixture
        return self._ibr_files.install(), self._ibr_files.switch(), self._ibr_files.status()

    def _refresh_boss_status(self) -> None:
        """Instant Boss Restart's card from the SBInstantBossRestart game mod.

        The player presses the game's own Revive; the game mod does the rest
        in the game (black screen, Eve at the arena's intro, the boss intro).
        The panel only shows what the game mod's status.txt says for this
        game session and owns the switch (settings.txt, read at every death).
        """
        install, switch_on, status = self._ibr_inputs()
        game_running = bool(self._game_running_cached)
        card = ibr_card(
            install,
            switch_on,
            status,
            game_running=game_running,
            game_started_at=self._ibr_game_started_at() if game_running else None,
            now=time.time(),
        )
        self._set_native_status("boss", card.verdict)
        if game_running:
            self._log_boss_events(card)
        values = {
            "_boss_enabled": card.enabled,
            "_boss_ready": card.ready,
            "_boss_reviving": card.restarting,
            "_boss_retry_count": card.restarts,
            "_boss_status_text": card.line,
            "_boss_diagnostics": card.detail,
            "_boss_technical_diagnostics": card.technical_detail,
            "_boss_supports_story": bool(install.trusted and install.version != "0.4.0"),
        }
        changed = any(getattr(self, name) != value for name, value in values.items())
        for name, value in values.items():
            setattr(self, name, value)
        if changed:
            self.bossChanged.emit()

    def _log_boss_events(self, card) -> None:
        """One quiet activity-log line per restart and per normal respawn
        (no toast: nothing pops up over the game)."""
        key = (card.loaded, card.restarts, card.last, card.last_at)
        previous = self._boss_log_key
        self._boss_log_key = key
        if not card.loaded or not previous or previous[0] != card.loaded or key == previous:
            return
        for restart in range(previous[1] + 1, card.restarts + 1):
            self._append_issue(
                "OK", "boss", f"The boss fight started over (restart {restart}).", card.detail, toast=False
            )
        if card.last in BOSS_FALLBACK_REASONS and (card.last, card.last_at) != (previous[2], previous[3]):
            self._append_issue(
                "INFO",
                "boss",
                f"The last Revive used the normal respawn: {BOSS_FALLBACK_REASONS[card.last]}.",
                card.detail,
                toast=False,
            )

    def _native_movement_paths(self) -> tuple[Path, Path, Path]:
        """(dll, enabled marker, state file) for the native movement mod."""
        mods_root = self.mod_root.parent
        mod_dir = mods_root / "SBMovementNative"
        return (
            mod_dir / "dlls" / "main.dll",
            mod_dir / "enabled.txt",
            self.mod_root / "native_movement_state.txt",
        )

    def _native_movement_installed(self) -> bool:
        """True only for the exact audited DLL with its enable marker present."""
        return trusted_native_movement(self.mod_root)[0]

    def _native_movement_live_state(self) -> tuple[bool, bool, bool]:
        if not self._native_movement_installed():
            return False, False, False
        heartbeat_path = self.mod_root.parent / "SBMovementNative" / "heartbeat.txt"
        try:
            age = time.time() - heartbeat_path.stat().st_mtime
            fresh = -2.0 <= age <= MOVEMENT_HEARTBEAT_FRESH_SEC
            heartbeat = read_kv(heartbeat_path) if fresh else {}
        except OSError:
            heartbeat = {}
            fresh = False
        return native_movement_live_state(
            heartbeat,
            game_running=bool(self._game_running_cached),
            heartbeat_fresh=fresh,
        )

    def _write_native_movement_state(self, quiet: bool = False) -> bool:
        """Publish the current speed/jump/FOV for the native mod to pick up.

        `enabled` gates speed and jump only; FOV always applies live from
        fov_deg, so a bare FOV change does not switch movement on.
        """
        if not self._native_movement_installed():
            if not quiet:
                self._append_issue(
                    "ERROR",
                    "movement",
                    "Movement and field of view couldn't be applied: the movement game mod "
                    "isn't installed or couldn't start safely.",
                    "movement/FOV not published: the exact trusted native mod is unavailable",
                )
            return False
        _, _, state_path = self._native_movement_paths()
        self._movement_seq += 1
        payload = {
            "enabled": 1 if self._movement_enabled else 0,
            "speed": f"{self._speed:.3f}",
            "jump": f"{self._jump:.3f}",
            "fov_deg": f"{self._fov:.1f}",
            # This is a renewable panel lease, not a timeless command. The
            # native mod restores its owned values if this PID exits or this
            # timestamp stops advancing, preventing a stale panel session from
            # silently re-enabling movement on a later game launch.
            "seq": self._movement_seq,
            "issued_ms": int(time.time() * 1000),
            "panel_pid": os.getpid(),
        }
        try:
            write_kv_atomic(state_path, payload)
            return True
        except (OSError, ValueError) as exc:
            if not quiet:
                self._append_issue("ERROR", "movement", "Couldn't save your movement settings.", str(exc))
            return False

    def _set_native_status(self, key: str, verdict: NativeVerdict, *, label: str | None = None) -> None:
        """Publish one card state and log real problems once per change."""
        entry = verdict.as_qml()
        if label:
            entry["label"] = label
        previous_reason = self._native_status_reasons.get(key)
        self._native_status_reasons[key] = verdict.reason
        if previous_reason != verdict.reason and verdict.state in (NATIVE_NEEDS_UPDATE, NATIVE_UNSAFE):
            names = {
                "movement": "Movement",
                "god": "God Mode",
                "retryPoint": "Retry Point",
                "boss": "Instant Boss Restart",
                "items": "Items & Money",
            }
            self._append_issue(
                "WARN",
                "native-status",
                f"{names.get(key, key)}: {verdict.detail}",
                f"reason: {verdict.reason}",
            )
        if self._native_status.get(key) != entry:
            self._native_status[key] = entry
            self.nativeStatusChanged.emit()

    def _remove_orphaned_retry_point_command_at_start(self) -> None:
        """Clear a leftover Retry Point command from a panel that has exited.

        Only while Stellar Blade is closed: the native is not loaded then, and
        a command whose sender is gone can only ever be rejected as stale.
        """
        game_closed = not self._game_was_running and not self._game_pid_cached
        try:
            removed = remove_orphaned_retry_point_command(
                self.retry_point_command_file,
                game_running=not game_closed,
            )
        except Exception:
            removed = False
        if removed:
            self._append_issue(
                "OK",
                "retry-point",
                "Cleared an old Retry Point request left over from an earlier session.",
                "orphaned command from a panel that is no longer running",
                toast=False,
            )

    def _movement_native_verdict(self) -> NativeVerdict:
        native_root = self.mod_root.parent / "SBMovementNative"
        installed, trusted, _identity = native_install_state(
            native_root / "enabled.txt",
            native_root / "dlls" / "main.dll",
            {str(value).lower() for value in MOVEMENT_NATIVE_TRUSTED_SHA256},
        )
        snapshot = read_native_status(
            native_root / "heartbeat.txt",
            max_age=MOVEMENT_HEARTBEAT_FRESH_SEC,
        )

        return native_verdict(
            installed=installed,
            trusted=trusted,
            game_running=bool(self._game_running_cached),
            snapshot=snapshot,
            interpret=interpret_movement_heartbeat,
        )

    def _god_native_verdict(self, installed: bool, conn=None) -> NativeVerdict:
        if conn is None:
            conn = evaluate_connection(self.mod_root, bool(self._game_running_cached))
        # An installed build for the previous game is never enabled; the card
        # says "Needs update" instead of "Off".
        superseded = not installed and superseded_native_god(
            self.mod_root.parent / "SBGodNative" / "dlls" / "main.dll"
        )
        return god_heartbeat_verdict(
            installed=installed,
            game_running=bool(self._game_running),
            heartbeat=conn.native_heartbeat,
            heartbeat_fresh=conn.native_fresh,
            superseded=superseded,
        )

    def _native_retry_point_installed(self) -> tuple[bool, str]:
        """Require both the enable marker and the exact audited candidate hash."""
        try:
            return retry_point_native_ready(self.mod_root.parent)
        except OSError as exc:
            return False, f"hash-{type(exc).__name__}"

    @staticmethod
    def _retry_point_result_text(result: str, area: str, *, resting: bool = True) -> str:
        """The Retry Point card's sentence for the last result, or for the
        saved point's ``area`` (retry_point_area). ``resting=False`` gives
        the one-time notice when this panel's own command is answered: a
        success is news once, and the card then says what is true now."""
        if resting and result in RETRY_POINT_SUCCESS_RESULTS:
            return RETRY_POINT_SAVED_TEXT
        messages = {
            "saved": RETRY_POINT_SAVED_TEXT,
            "cleared": "Retry Point cleared.",
            "returned_verified": "Eve is back at the saved point.",
            "already_at_point": "Eve is already at the saved point.",
            "command_invalid": "Stopped safely because the request was invalid.",
            "command_stale": "Stopped safely because the request was too old.",
            "panel_gone": "Stopped safely because the panel session ended.",
            "panel_session_mismatch": "Stopped safely because the request came from an earlier panel session.",
            "busy": "Stopped safely because another Retry Point action was still finishing.",
            "point_missing": "Set a point before trying to return.",
            "point_invalid_or_modified": "Stopped safely because the saved point was invalid or modified.",
            "point_write_failed": "The point could not be saved to disk.",
            "build_mismatch": GAME_UPDATED_TEXT,
            "wrong_thread": "Stopped safely because the game wasn't ready for it.",
            "live_context_invalid": "Waiting for Eve to be fully playable in a stable loaded area.",
            "different_loaded_world": RETRY_POINT_ELSEWHERE_TEXT,
            "target_distance_refused": "Return refused because the saved point is too far away to be safe.",
            "warp_function_missing": "The game's way to move Eve could not be found. Eve was not moved.",
            "warp_function_identity_mismatch": "The game's way to move Eve did not match the tested one. Eve was not moved.",
            "game_owned_warp_requested": "The game accepted the return; checking where Eve is.",
            "return_not_verified": "The game did not confirm the return, so it was not repeated.",
            "dispatch_failed": "Stopped safely because the game couldn't take the request.",
            "dispatch_exception": "Stopped safely because the game rejected the request.",
        }
        if result in messages:
            return messages[result]
        if area == "elsewhere":
            return RETRY_POINT_ELSEWHERE_TEXT
        if area in ("here", "unchecked"):
            return RETRY_POINT_KEPT_TEXT
        return "Ready to save Eve's current point."

    def _refresh_retry_point_status(self) -> None:
        installed, identity = self._native_retry_point_installed()
        game_running = bool(self._game_running_cached)
        now_wall = time.time()
        status: dict[str, str] = {}
        status_fresh = False
        try:
            if game_running and installed and self.retry_point_status_file.is_file():
                age = now_wall - self.retry_point_status_file.stat().st_mtime
                if -2.0 <= age <= 1.5:
                    status = read_kv(self.retry_point_status_file)
                    status_fresh = bool(status)
        except OSError:
            status = {}
            status_fresh = False
        self._apply_retry_point_status(
            installed=installed,
            identity=identity,
            game_running=game_running,
            status=status,
            status_fresh=status_fresh,
            point_on_disk=self.retry_point_file.is_file(),
        )

    def _apply_retry_point_status(
        self,
        *,
        installed: bool,
        identity: str,
        game_running: bool,
        status: dict[str, str],
        status_fresh: bool,
        point_on_disk: bool,
        files_present: bool | None = None,
    ) -> None:
        """The Retry Point card from what the game mod reported (or, for the
        --ui-fixture screenshot run, from a recorded status)."""
        telemetry_ok, telemetry_detail = retry_point_telemetry_ready(status, expected_panel_pid=os.getpid())
                                                                      
                                                                        
                                                                            
                                                                           
                                                                             
                                                         
        telemetry_ok, telemetry_detail = self._retry_point_counts_guard.settle(
            status, telemetry_ok, telemetry_detail
        )
        contract_ok = bool(status_fresh and telemetry_ok)
        if files_present is None:
            files_present = self.retry_point_marker.is_file() and self.retry_point_dll.is_file()
        retry_verdict = native_verdict(
            installed=files_present,
            trusted=installed,
            game_running=game_running,
            snapshot=NativeStatusSnapshot(status, None, status_fresh, bool(status)),
            interpret=lambda _values: (
                NATIVE_READY if telemetry_ok else NATIVE_UNSAFE,
                telemetry_detail,
            ),
        )
        self._set_native_status("retryPoint", retry_verdict)

        try:
            completed_sequence = int(status.get("last_completed_command_sequence", "0") or "0")
        except (TypeError, ValueError):
            completed_sequence = 0
        if not self._ui_fixture_active:
            # This panel's own command, once answered (or with the game
            # closed), would only be read again by the next game session as a
            # stale leftover. Quiet housekeeping: nothing to tell the player.
            remove_finished_retry_point_command(
                self.retry_point_command_file,
                own_pid=os.getpid(),
                game_running=game_running,
                last_completed_sequence=completed_sequence if status_fresh else None,
            )

        timed_out = bool(
            self._retry_point_pending_seq
            and time.monotonic() - self._retry_point_command_started > 8.0
        )
        if self._retry_point_pending_seq and completed_sequence >= self._retry_point_pending_seq:
            self._retry_point_pending_seq = 0
            self._retry_point_pending_command = ""
            self._retry_point_command_started = 0.0
            answer = status.get("result", "none")
            if answer not in ("none", ""):
                answer_text = self._retry_point_result_text(answer, retry_point_area(status), resting=False)
                self._append_issue(
                    "OK" if answer in RETRY_POINT_SUCCESS_RESULTS or answer == "cleared" else "WARN",
                    "retry-point",
                    answer_text,
                )
                if answer in RETRY_POINT_RETURN_SUCCESS_RESULTS:
                    self._retry_point_success_text = answer_text
                    self._retry_point_success_until = time.monotonic() + RETRY_POINT_SUCCESS_LINE_SEC
        elif self._retry_point_pending_seq and (not game_running or timed_out):
            self._retry_point_pending_seq = 0
            self._retry_point_pending_command = ""
            self._retry_point_command_started = 0.0

        busy = self._retry_point_pending_seq > 0
        phase = status.get("phase", "offline" if not game_running else "waiting")
        result = status.get("result", "none")
        saved = status.get("point_valid") == "1" if status_fresh else point_on_disk
        # Where the point is, as far as the game mod has checked in this game
        # session: 0.2.3 every 3 s under this panel's watch lease, 0.2.1 only
        # inside Set Point and Return.
        if status_fresh:
            area = retry_point_area(status)
            area_live = retry_point_area_live(status)
        else:
            area = "unchecked" if saved else "none"
            area_live = False
        if not self._ui_fixture_active:
            self._keep_retry_point_watch(
                installed=installed, game_running=game_running, status=status, status_fresh=status_fresh
            )
        available = bool(installed and game_running and contract_ok)
        # "elsewhere" is advice. With 0.2.1 it is only what the last Set
        # Point or Return found; with 0.2.3 it is at most 3 s old. Return
        # stays usable either way: the game mod checks the area on every
        # Return and moves nothing if it differs.
        can_return = bool(available and saved)
        # A leftover request (from an earlier game session or a panel that
        # has closed) was ignored safely: its result is nobody's news.
        leftover = telemetry_detail in ("ready-awaiting-first-command", "ready-awaiting-rebind")
        # A Return that worked: its line stays on the card for a short time.
        if not game_running or time.monotonic() >= self._retry_point_success_until:
            self._retry_point_success_text = ""
        success_line = self._retry_point_success_text

        if not installed:
            if identity == "missing":
                message = "The Retry Point game mod is not installed."
            else:
                message = "Retry Point is off because its game mod file failed a safety check."
        elif not game_running:
            message = (
                "A point is saved. Start Stellar Blade to use it in the area where you set it."
                if point_on_disk
                else "Start Stellar Blade, then set a point."
            )
        elif not status_fresh:
            message = "Waiting for the game mod to report in."
        elif not contract_ok:
            # Plain words on the card; the exact reason goes to the activity log.
            message = (
                GAME_UPDATED_TEXT
                if retry_verdict.state == NATIVE_NEEDS_UPDATE
                else "Retry Point couldn't start safely, so it stays off."
            )
        elif busy:
            pending_messages = {
                "save": "Saving Eve's current point...",
                "return": "Asking the game to return Eve once, then checking it...",
                "clear": "Clearing the saved Retry Point...",
            }
            message = pending_messages.get(self._retry_point_pending_command, "Finishing Retry Point action...")
        elif timed_out:
            message = "Retry Point did not answer in time; no action will be repeated."
        elif success_line:
            message = success_line
        elif area == "elsewhere":
            message = RETRY_POINT_ELSEWHERE_NOW_TEXT if area_live else RETRY_POINT_ELSEWHERE_TEXT
        elif area == "here" and result == "different_loaded_world":
            # A Return refused in another area, and Eve is back in the
            # point's area since (0.2.3 checks): the old refusal is past.
            message = self._retry_point_result_text("none", area)
        elif leftover:
            # The last result belongs to a leftover request or to a panel
            # that has since closed, not to anything this panel asked for.
            message = self._retry_point_result_text("none", area)
        else:
            message = self._retry_point_result_text(result, area)

        values = {
            "_retry_point_installed": installed,
            "_retry_point_available": available,
            "_retry_point_saved": saved,
            "_retry_point_can_return": can_return,
            "_retry_point_area": area,
            "_retry_point_area_live": area_live,
            "_retry_point_busy": busy,
            "_retry_point_phase": phase,
            "_retry_point_status": message,
            "_retry_point_identity": identity,
        }
        changed = any(getattr(self, name) != value for name, value in values.items())
        for name, value in values.items():
            setattr(self, name, value)
        if changed:
            self.retryPointChanged.emit()

    def _keep_retry_point_watch(
        self, *, installed: bool, game_running: bool, status: dict[str, str], status_fresh: bool
    ) -> None:
        """Retry Point game mod 0.2.3: keep its watch lease fresh while a
        point is saved, so it checks the loaded area every 3 s (it reads
        nothing without the lease). A status that is not fresh right now
        changes nothing; the lease runs out by itself 5 s after the last
        write."""
        if installed and game_running and not status_fresh:
            return
        if installed and game_running and retry_point_watch_wanted(status):
            now = time.monotonic()
            if now - self._retry_point_watch_at < RETRY_POINT_WATCH_REFRESH_SEC:
                return
            try:
                write_kv_atomic(
                    self.retry_point_watch_file,
                    {
                        "schema": 1,
                        "issued_ms": int(time.time() * 1000),
                        "panel_pid": os.getpid(),
                        "token": self._retry_point_token,
                    },
                )
            except (OSError, ValueError):
                return  # tried again on the next pass; Return still checks the area
            self._retry_point_watch_at = now
            self._retry_point_watch_written = True
            return
        if self._retry_point_watch_written:
            self._remove_retry_point_watch()

    def _remove_retry_point_watch(self) -> None:
        self._retry_point_watch_at = float("-inf")
        self._retry_point_watch_written = False
        try:
            self.retry_point_watch_file.unlink(missing_ok=True)
        except OSError:
            pass

    def _send_retry_point_command(self, command: str) -> None:
        if command not in {"save", "return", "clear"}:
            self._append_issue(
                "WARN", "retry-point", "That Retry Point action isn't available.", f"unknown command: {command}"
            )
            return

        self._refresh_retry_point_status()
        if command == "clear" and not self._game_running_cached:
            try:
                self.retry_point_file.unlink(missing_ok=True)
                self.retry_point_temp_file.unlink(missing_ok=True)
                self.retry_point_command_file.unlink(missing_ok=True)
            except OSError as exc:
                self._append_issue("ERROR", "retry-point", "Couldn't clear the Retry Point.", str(exc))
                return
            self._retry_point_saved = False
            self._retry_point_can_return = False
            self._retry_point_area = "none"
            self._retry_point_phase = "cleared"
            self._retry_point_status = "Retry Point cleared while Stellar Blade was closed."
            self.retryPointChanged.emit()
            self._append_issue("OK", "retry-point", "Retry Point cleared while Stellar Blade was closed.")
            return

        if not self._retry_point_available:
            self._append_issue("WARN", "retry-point", self._retry_point_status)
            return
        if self._retry_point_busy:
            self._append_issue("WARN", "retry-point", "Retry Point is still finishing the previous action.")
            return
        if command == "return" and not self._retry_point_saved:
            self._append_issue("WARN", "retry-point", "Set a point before trying to return.")
            return

        self._retry_point_seq += 1
        sequence = self._retry_point_seq
        try:
            write_kv_atomic(
                self.retry_point_command_file,
                {
                    "schema": 1,
                    "seq": sequence,
                    "cmd": command,
                    "issued_ms": int(time.time() * 1000),
                    "panel_pid": os.getpid(),
                    "token": self._retry_point_token,
                },
            )
        except (OSError, ValueError) as exc:
            self._append_issue(
                "ERROR", "retry-point", "Couldn't send that to the game. Try again.", f"retry point write failed: {exc}"
            )
            return

        self._retry_point_pending_seq = sequence
        self._retry_point_pending_command = command
        self._retry_point_command_started = time.monotonic()
        self._retry_point_busy = True
        # The last Return's success line is replaced by this action's answer.
        self._retry_point_success_text = ""
        self._retry_point_success_until = 0.0
        self._retry_point_status = {
            "save": "Saving Eve's current point...",
            "return": "Asking the game to return Eve once, then checking it...",
            "clear": "Clearing the saved Retry Point...",
        }[command]
        self.retryPointChanged.emit()
        self._append_issue(
            "INFO", "retry-point", self._retry_point_status,
            f"native retry point {command} request sent (seq {sequence})", toast=False,
        )

    def _live_add_lease_wanted(self) -> bool:
        """Items lease: only while the game runs and Items & Money is open or
        an add is still in flight (A13: no native GameThread work otherwise)."""
        return bool(self._game_running_cached) and (
            self._active_page == "items" or self._live_add_expected_sequence > 0
        )

    def _live_add_lease_protocol(self) -> str:
        """The protocol the installed, trusted Items game mod reads its lease in
        (v3 for 0.4.0, v4 for 0.5.0); "" when none is trusted."""
        return installed_live_add_native_protocol(self.live_add_native_dll)

    def _update_live_add_lease(self) -> str:
        """Renew, stop or clean up the Items lease; return the panel-side state.

        Renewed every 2 s while wanted (the native honours it for 10 s). Leaving
        the page just stops renewing, so a quick return never re-arms from
        scratch. A closed game removes the file (the next session starts clean),
        and so does an untrusted game mod (no lease is ever written for one).
        """
        now = time.monotonic()
        protocol = self._live_add_lease_protocol() if self._live_add_lease_wanted() else ""
        if not protocol:
            if (
                (not self._game_running_cached or self._live_add_lease_wanted())
                and self._live_add_lease_written_at != float("-inf")
            ):
                self._remove_live_add_lease()
            return LIVE_ADD_LEASE_OFF
        if now - self._live_add_lease_written_at >= LIVE_ADD_LEASE_RENEW_SEC:
            gap = now - self._live_add_lease_written_at
            try:
                write_bytes_replace(
                    self.live_add_lease_file,
                    format_live_add_lease(os.getpid(), int(time.time() * 1000), protocol),
                )
            except (OSError, ValueError) as exc:
                if not self._live_add_lease_error_logged:
                    self._live_add_lease_error_logged = True
                    self._append_issue(
                        "WARN",
                        "items",
                        "Items & Money lost touch with the game for a moment. It keeps trying by itself.",
                        f"Could not renew the Items lease: {exc}",
                    )
                return LIVE_ADD_LEASE_OFF
            self._live_add_lease_error_logged = False
            if gap > LIVE_ADD_LEASE_STALE_GAP_SEC:
                self._live_add_lease_started_at = now
            self._live_add_lease_written_at = now
        if now - self._live_add_lease_started_at < LIVE_ADD_LEASE_SETTLE_SEC:
            return LIVE_ADD_LEASE_SETTLING
        return LIVE_ADD_LEASE_HELD

    def _remove_live_add_lease(self) -> None:
        self._live_add_lease_written_at = float("-inf")
        self._live_add_lease_started_at = float("-inf")
        for path in (self.live_add_lease_file, self.live_add_probe_request_file):
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass

    # -- Items & Money v0.5 probe (PLAN C7; services/item_probe.py) ----------

    def _reset_probe(self) -> None:
        if self._probe_entries or self._probe_answered_all or self._probe_id:
            self._probe_version += 1
        self._probe_id = ""
        self._probe_scope_all = False
        self._probe_entries = {}
        self._probe_answered_all = False
        self._probe_full_wanted = True
        self._probe_pending_aliases = set()
        self._probe_finished_at = float("-inf")
        self._probe_retry_after = float("-inf")
        self._probe_result_signature = None

    def _drive_items_probe(self, state, heartbeat, native_snapshot, panel_lease: str) -> None:
        """Ask the v0.5 game mod about the catalog and read its answers.

        Read-only in the game. One question at a time, only while Items &
        Money is open (the Items lease is held), the route is ready and the
        session is verified. A full question when the page opens, a short one
        for the item just added, and a full one again every minute.
        """
        if self._items_fixture is not None:
            return
        fresh = native_snapshot.values if native_snapshot.fresh else None
        if native_probe_capable(fresh, PROBE_STATUS_STATES):
            self._live_add_probe_seen = True
        protocol = live_add_route_protocol(self.live_add_script, self.live_add_native_dll)
        session = (
            str(heartbeat.get("session") or "").strip()
            if protocol and trusted_live_add_protocol(heartbeat, protocol)
            else ""
        )
        if not self._game_running_cached or not state.trusted:
            if self._probe_session or self._probe_entries:
                self._probe_session = ""
                self._reset_probe()
            return
        if session and session != self._probe_session:
            # A new game session: nothing known about it yet.
            self._reset_probe()
            self._probe_session = session
        if self._items_mode_now() != "probe" or not self._probe_session:
            return
        now = time.monotonic()
        if self._probe_id:
            self._read_probe_result(now)
        if self._probe_id and now - self._probe_issued_at > PROBE_REQUEST_TIMEOUT_SEC:
            # Unanswered (the game mod ignores a question older than 5 s):
            # the probe is read-only, so the next tick simply asks again.
            self._probe_id = ""
            self._probe_retry_after = now + 1.0
        if self._probe_id or now < self._probe_retry_after:
            return
        if not (state.ready and panel_lease == LIVE_ADD_LEASE_HELD and session == self._probe_session):
            return
        if self._probe_full_wanted or now - self._probe_finished_at >= PROBE_REFRESH_SEC:
            self._ask_probe(None, now)
        elif self._probe_pending_aliases:
            # Only items the full answer returned: one name the game mod
            # doesn't allow refuses the whole short question.
            known = sorted(alias for alias in self._probe_pending_aliases if alias in self._probe_entries)
            if known:
                self._ask_probe(known[:PROBE_MAX_LISTED], now)
            else:
                self._probe_pending_aliases = set()

    def _ask_probe(self, aliases: list[str] | None, now: float) -> None:
        probe_id = secrets.token_hex(16)
        try:
            body = format_probe_request(
                probe_id=probe_id,
                issued_unix_s=int(time.time()),
                session=self._probe_session,
                aliases=aliases,
            )
            write_bytes_replace(self.live_add_probe_request_file, body)
        except (OSError, ProbeError) as exc:
            if not self._probe_error_logged:
                self._probe_error_logged = True
                self._append_issue(
                    "WARN", "items", "Items & Money couldn't check your items this time. It tries again by itself.",
                    f"probe request not written: {exc}", toast=False,
                )
            self._probe_retry_after = now + 5.0
            return
        self._probe_error_logged = False
        self._probe_id = probe_id
        self._probe_scope_all = aliases is None
        self._probe_issued_at = now
        if aliases is None:
            self._probe_full_wanted = False
            self._probe_pending_aliases = set()
        else:
            self._probe_pending_aliases -= set(aliases)

    def _read_probe_result(self, now: float) -> None:
        path = self.live_add_probe_result_file
        try:
            info = path.stat()
        except OSError:
            return
        signature = (info.st_mtime_ns, info.st_size)
        if signature == self._probe_result_signature:
            return
        self._probe_result_signature = signature
        if info.st_size > PROBE_RESULT_MAX_BYTES:
            return
        try:
            text = path.read_bytes().decode("ascii")
            result = parse_probe_result(
                text,
                expected_probe_id=self._probe_id,
                expected_session=self._probe_session,
                catalog_aliases=[row["alias"] for row in self._items_catalog.rows],
            )
        except (OSError, UnicodeDecodeError, ProbeError):
            # An older answer, another session or a damaged file: keep
            # waiting for this question's answer (or time it out).
            return
        if result.status == "refused":
            self._probe_id = ""
            self._probe_retry_after = now + 5.0
            return
        if self._probe_scope_all and result.status == "done":
            self._probe_entries = dict(result.entries)
            self._probe_answered_all = True
        else:
            self._probe_entries.update(result.entries)
        if result.finished:
            self._probe_id = ""
            if self._probe_scope_all:
                self._probe_finished_at = now
        self._probe_version += 1

    def _refresh_live_add_status(self) -> None:
        """Refresh the pinned, fail-closed Live Add route (bridge + native, v3 or v4)."""
        panel_lease = self._update_live_add_lease()
        result = read_kv(self.spawn_status_file)
        heartbeat = read_kv(self.heartbeat_file)
        native_snapshot = read_native_status(
            self.live_add_native_status_file,
            max_age=LIVE_ADD_NATIVE_STATUS_MAX_AGE_SEC,
        )
        route_protocol = live_add_route_protocol(self.live_add_script, self.live_add_native_dll)
        current_session = (
            str(heartbeat.get("session") or "").strip()
            if route_protocol and trusted_live_add_protocol(heartbeat, route_protocol)
            else ""
        )
        # Which card the request in flight belongs to: read it before
        # _clear_live_add_request() resets it. A money add reports on the
        # Money card, an item add under Add Item.
        was_currency = bool(self._live_add_expected_currency)
        item_result = self._item_last_result
        money_result = self._money_last_result
                                                                           
                                                                     
                                                                        
                                                                           
                                                             
        running = bool(self._game_running_cached)
        results_session = (
            current_session if running and current_session
            else self._add_results_session if running
            else ""
        )
        if results_session != self._add_results_session:
            if self._items_fixture is None:
                in_flight = self._live_add_expected_sequence > 0
                if not (in_flight and not was_currency):
                    item_result = ""
                if not (in_flight and was_currency):
                    money_result = ""
            self._add_results_session = results_session
        if (
            self._live_add_expected_sequence > 0
            and (
                not self._game_running_cached
                or (current_session and current_session != self._live_add_expected_session)
            )
        ):
            if was_currency:
                money_result = "Couldn't add safely: the game session changed before the add was confirmed."
            else:
                item_result = "Couldn't add safely: the game session changed before the item was confirmed."
            self._clear_live_add_request()

        state = evaluate_live_add(
            script_path=self.live_add_script,
            bridge_marker_path=self.live_add_marker,
            native_dll_path=self.live_add_native_dll,
            native_marker_path=self.live_add_native_marker,
            heartbeat_path=self.heartbeat_file,
            heartbeat=heartbeat,
            result=result,
            game_running=bool(self._game_running_cached),
            result_path=self.spawn_status_file,
            expected_session=self._live_add_expected_session,
            expected_request_id=self._live_add_expected_request_id,
            expected_sequence=self._live_add_expected_sequence,
            expected_alias=self._live_add_expected_alias,
            native_status=native_snapshot.values,
            native_status_fresh=native_snapshot.fresh,
            expected_name=self._live_add_expected_name,
            panel_lease=panel_lease,
        )
        result_text = ""
        matching_result = live_add_status_matches(
            result,
            expected_session=self._live_add_expected_session,
            expected_request_id=self._live_add_expected_request_id,
            expected_sequence=self._live_add_expected_sequence,
            expected_alias=self._live_add_expected_alias,
        )
        added = False
        notice = ""
        if matching_result and (
            str(result.get("pending") or "") != "1" or result_outcome_unknown(result)
        ):
            result_text = friendly_live_add_result(
                result,
                self._live_add_expected_name,
                self._live_add_expected_qty,
                native_snapshot.values if native_snapshot.fresh else None,
                currency=was_currency,
            )
            if was_currency:
                money_result = result_text
            else:
                item_result = result_text
            result_signature = (
                result.get("ok", ""),
                result.get("pending", ""),
                result.get("spawnsession", ""),
                result.get("spawnrequest", ""),
                result.get("spawnseq", ""),
                result.get("detail", ""),
            )
            if result_signature != self._spawn_result_signature:
                self._spawn_result_signature = result_signature
                added = str(result.get("ok") or "") == "1"
                self._append_issue("OK" if added else "ERROR", "items", result_text)
                detail = str(result.get("detail") or "")
                if not added and is_safe_refusal(detail):
                    # A safe refusal: nothing was sent, adding stays ready.
                    notice = result_text
            if not result_outcome_unknown(result):
                # Terminal answer for this exact request; an unknown outcome
                # keeps the request (and so the Add button) locked instead.
                if self._live_add_expected_alias:
                    # Its count changed (or was refused): ask again about it.
                    self._probe_pending_aliases.add(self._live_add_expected_alias)
                self._clear_live_add_request()

        item_state, item_label, item_text = self._live_add_display(
            state, added=added, added_text=result_text if added else "", notice=notice
        )
        values = {
            "_live_add_installed": state.installed,
            "_live_add_trusted": state.trusted,
            "_live_add_ready": state.ready,
            "_live_add_busy": state.busy,
            "_live_add_phase": state.phase,
            "_live_add_status": item_text,
            "_live_add_status_state": item_state,
            "_live_add_status_label": item_label,
            "_item_last_result": item_result,
            "_money_last_result": money_result,
        }
        if self._items_fixture is not None:
            # Screenshot automation only: a ready route without a game.
            ready = bool(self._items_fixture.get("route_ready", True))
            values.update(
                _live_add_installed=True,
                _live_add_trusted=True,
                _live_add_ready=ready,
                _live_add_busy=False,
                _live_add_phase="ready" if ready else "waiting",
                _live_add_status="Ready. Pick an item and add it." if ready else "Start Stellar Blade and load a save first.",
                _live_add_status_state=NATIVE_READY if ready else NATIVE_WAITING,
                _live_add_status_label="Ready" if ready else "Waiting for game",
            )
        changed = any(getattr(self, name) != value for name, value in values.items())
        selected_changed = self._item_last_result != item_result
        for name, value in values.items():
            setattr(self, name, value)
        self._drive_items_probe(state, heartbeat, native_snapshot, panel_lease)
        self._apply_item_chips()
        self._refresh_money_state()
        if changed:
            self.liveAddChanged.emit()
        if selected_changed:
            self.selectedItemChanged.emit()

    def _clear_live_add_request(self) -> None:
        self._live_add_expected_session = ""
        self._live_add_expected_request_id = ""
        self._live_add_expected_sequence = 0
        self._live_add_expected_alias = ""
        self._live_add_expected_currency = False

    def _live_add_display(
        self, state, *, added: bool, added_text: str = "", notice: str = ""
    ) -> tuple[str, str, str]:
        """Items & Money wording: Ready / Waiting for game / Adding / Added,
        plus Off, Needs update and Couldn't start safely from the shared set.
        "Couldn't add safely" is the wording of one add's result, never a chip.

        ``added_text`` (the verified count) shows for 4 s after an add;
        ``notice`` (a safe refusal such as a full bag) shows for 8 s while
        adding stays ready."""
        now = time.monotonic()
        if added:
            self._live_add_added_until = now + 4.0
            self._live_add_added_text = added_text or "Added."
            self._live_add_notice_until = 0.0
        if notice:
            self._live_add_notice_until = now + 8.0
            self._live_add_notice_text = notice
        if state.busy and state.state == "adding":
            verdict = NativeVerdict(NATIVE_WAITING, state.message, state.reason)
            self._set_native_status("items", verdict, label="Adding")
            return "adding", "Adding", state.message
        if state.state == NATIVE_READY and now < self._live_add_added_until:
            text = self._live_add_added_text or "Added."
            verdict = NativeVerdict(NATIVE_READY, text, state.reason)
            self._set_native_status("items", verdict, label="Added")
            return NATIVE_READY, "Added", text
        if state.state == NATIVE_READY and now < self._live_add_notice_until:
            verdict = NativeVerdict(NATIVE_READY, self._live_add_notice_text, state.reason)
            self._set_native_status("items", verdict, label="Ready")
            return NATIVE_READY, "Ready", self._live_add_notice_text
        known = (NATIVE_READY, NATIVE_WAITING, NATIVE_NEEDS_UPDATE, NATIVE_OFF, NATIVE_UNSAFE)
        verdict_state = state.state if state.state in known else NATIVE_UNSAFE
        verdict = NativeVerdict(
            verdict_state,
            state.message,
            state.reason or state.phase,
            label_text=getattr(state, "label", "") or "",
        )
        label = verdict.label
        self._set_native_status("items", verdict, label=label)
        return verdict.state, label, verdict.detail

    def _send_boss_command(self, command: str) -> None:
        """The one Instant Boss Restart switch: "enable" or "disable".

        It sets enabled= in the game mod's settings.txt, which the game mod
        reads at every death, so it works right away, also while the game
        runs. Turning it on also puts back a missing UE4SS enabled.txt (that
        one takes effect when the game next starts).
        """
        if command not in ("enable", "disable"):
            self._append_issue(
                "ERROR", "boss", "That boss restart action isn't available.", f"unknown boss command: {command}"
            )
            return
        on = command == "enable"
        if self._ui_fixture_active:
            # Screenshot automation: the recorded state changes, no file does.
            install, _switch, status = self._ibr_inputs()
            self._ibr_fixture = (install, on, status)
            self._refresh_boss_status()
            return
        install, _switch, _status = self._ibr_inputs()
        if not install.installed:
            self._append_issue("ERROR", "boss", "Instant Boss Restart is not installed. Reinstall the Mod Suite to use it.",
                               f"switch not written: missing {self.ibr_dir}")
            return
        created = False
        try:
            write_boss_restart_switch(self.ibr_dir, on)
            if on:
                created = ensure_boss_restart_marker(self.ibr_dir)
        except OSError as exc:
            self._refresh_boss_status()
            self._append_issue(
                "ERROR",
                "boss",
                "Couldn't save the Instant Boss Restart switch. Check Technical details on Support.",
                f"{self.ibr_dir}: {type(exc).__name__}: {exc}",
            )
            return
        self._refresh_boss_status()
        if not on:
            self._append_issue("OK", "boss", "Instant Boss Restart is off. Revive works as normal.",
                               "settings.txt enabled=0")
        elif created and self._game_running_cached:
            self._append_issue("WARN", "boss", "Instant Boss Restart is on. Restart Stellar Blade once to start it.",
                               "settings.txt enabled=1; enabled.txt was missing and was put back")
        else:
            self._append_issue(
                "OK",
                "boss",
                "Instant Boss Restart is on. It works right away, also while the game runs.",
                "settings.txt enabled=1" + ("; enabled.txt was missing and was put back" if created else ""),
            )

    def _run_powershell_file(self, script: Path, args: list[str] | None = None, timeout: int = 180) -> subprocess.CompletedProcess:
        cmd = [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(script),
        ]
        if args:
            cmd.extend(args)
        return subprocess.run(
            cmd,
            cwd=str(self.mod_root),
            capture_output=True,
            text=True,
            timeout=timeout,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )

    def _start_backend_job(
        self,
        key: str,
        label: str,
        area: str,
        work,
        on_success,
        on_error=None,
    ) -> None:
        started = time.time()

        def summarize(result) -> str:
            if isinstance(result, dict):
                for name in ("message", "alias", "report", "path"):
                    value = result.get(name)
                    if value:
                        return str(value)
            if result is None:
                return "completed"
            return str(result)

        def success(result):
            try:
                on_success(result)
                self._record_backend_job("OK", label, summarize(result), time.time() - started)
            except Exception as exc:
                self._append_issue(
                    "ERROR", area, f"{label} finished, but its result couldn't be shown.",
                    f"result handler failed: {exc}",
                )
                self._record_backend_job("ERROR", label, f"result handler failed: {exc}", time.time() - started)

        def failure(message: str):
            if on_error is not None:
                try:
                    on_error(message)
                    self._record_backend_job("ERROR", label, message, time.time() - started)
                    return
                except Exception as exc:
                    self._append_issue(
                        "ERROR", area, f"{label} ran into a problem.", f"error handler failed: {exc}"
                    )
                    self._record_backend_job("ERROR", label, f"error handler failed: {exc}", time.time() - started)
            self._append_issue("ERROR", area, f"{label} didn't finish.", message)
            self._record_backend_job("ERROR", label, message, time.time() - started)

        if not self._tasks.start(key, label, work, success, failure):
            self._append_issue("WARN", area, f"{self._tasks.busy_text()} is still working. Please wait.")
            self._record_backend_job("WAIT", label, f"{self._tasks.busy_text()} already running", 0.0)
            return
        self._append_issue("INFO", area, f"{label}: working on it...", "started in a background worker")

    def _record_backend_job(self, status: str, label: str, detail: str, elapsed: float) -> None:
        clock = time.strftime("%H:%M:%S")
        safe_detail = (detail or "").replace("\r", " ").replace("\n", " ").strip()
        if len(safe_detail) > 140:
            safe_detail = safe_detail[:137] + "..."
        elapsed_text = f"{elapsed:.1f}s" if elapsed > 0 else "queued"
        line = f"[{clock}] {status} | {label} | {elapsed_text} | {safe_detail or 'done'}"
        self._last_job_summary = line
        self._job_history.insert(0, line)
        self._job_history = self._job_history[:8]
        self._performance.record_backend_job(label, elapsed)
        self.infrastructureChanged.emit()

    def _catalog_row_for_alias(self, alias: str) -> dict | None:
        alias = (alias or "").strip()
        if not alias:
            return None
        for row in self._catalog_rows:
            if row.get("alias") == alias or alias in (row.get("aliases") or []):
                return row
        return None

    def _set_quick_item_policy(self, alias: str) -> None:
        """The Add card for a newly chosen item (catalog decision + chip)."""
        del alias  # the selection is already stored
        self._item_last_result = ""
        self._refresh_selected_item()

    def _run_health_worker(self, repair: bool = False) -> dict:
        ctx = HealthContext(
            mod_root=self.mod_root,
            qt_root=self.qt_root,
            assets_dir=self.assets_dir,
            version_file=self.version_file,
            state_file=self.state_file,
            save_tools=self.save_tools,
            support_script=self.support_script,
            support_reports_dir=self.support_reports_dir,
            paks_mods_dir=self.paks_mods_dir,
            disabled_paks_dir=self.disabled_paks_dir,
            catalog_count=len(self._catalog_rows),
            game_running=self._game_running,
            mod_connected=self._mod_connected,
            default_state=self._default_state(),
            item_policy_file=self.policy_file,
            game_exe=self.game_exe,
            app_manifest_file=self.app_manifest_file,
            steam_exe_candidates=self._steam_exe_candidates(),
            hook_free_profile_safe=self._hook_free_profile_safe,
        )
        return run_health_check(ctx, repair=repair)

    def _write_policy_audit_worker(self) -> dict:
        stamp = time.strftime("%Y%m%d-%H%M%S")
        self.support_reports_dir.mkdir(parents=True, exist_ok=True)
        csv_path = self.support_reports_dir / f"ItemPolicyAudit-{stamp}.csv"
        report = self.support_reports_dir / f"ItemPolicyAudit-{stamp}.txt"
        counts: dict[str, int] = {}
        rows: list[dict[str, str]] = []

        # The v0.5 catalog decides; the chip is what the installed game mod
        # said this session (empty while the game is closed).
        for item in self._catalog_rows:
            alias = str(item.get("alias") or "")
            level = str(item.get("group") or "unknown")
            counts[level] = counts.get(level, 0) + 1
            rows.append({
                "alias": alias,
                "name": str(item.get("name") or alias),
                "category": str(item.get("category") or "Other"),
                "level": level,
                "text": str(item.get("chipText") or ("In the list" if item.get("listed") else "Search only")),
                "save_supported": "false",
                "live_supported": "true" if item.get("chip") == CHIP_READY else "false",
                "requires_validation": "false",
                "source": f"catalog v0.5 ({self._items_mode})",
                "detail": str(item.get("chipReason") or item.get("listReason") or ""),
            })

        with csv_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=[
                    "alias",
                    "name",
                    "category",
                    "level",
                    "text",
                    "save_supported",
                    "live_supported",
                    "requires_validation",
                    "source",
                    "detail",
                ],
            )
            writer.writeheader()
            writer.writerows(rows)

        count_text = ", ".join(f"{level}={count}" for level, count in sorted(counts.items())) or "none"
        lines = [
            "SBCheatGUI Item Policy Audit",
            f"Created: {time.strftime('%Y-%m-%d %H:%M:%S %z')}",
            f"Version: {self._read_version()}",
            f"Catalog items: {len(rows)}",
            f"Policy DB: {policy_database_summary(self._policy_db, len(rows))}",
            f"Counts: {count_text}",
            f"CSV: {csv_path}",
            "",
            "Meaning:",
            "- default: in the item list; added through the game's own inventory once the game mod allows it.",
            "- opt-in: in the list only while its More items / Money card toggle is on.",
            "- money: Gold, added on the Money card.",
            "- excluded: never added (quest, story, DLC, internal copies); shown only by search, with a reason.",
            "- live_supported: the game mod labelled it Ready this session.",
        ]
        report.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return {
            "ok": True,
            "message": f"Policy audit created: {len(rows)} items ({count_text})",
            "report": str(report),
            "csv": str(csv_path),
            "counts": counts,
        }

    def _run_panel_self_test_worker(self) -> dict:
        lines = [
            "SBCheatGUI Panel Self-Test",
            f"Created: {time.strftime('%Y-%m-%d %H:%M:%S %z')}",
            f"Version: {self._read_version()}",
            f"Backend: {self.backendRuntime}",
            "",
        ]
        checks: list[tuple[str, bool, str]] = []
        checks.append(("VERSION file", self.version_file.exists(), str(self.version_file)))
        checks.append(("QML file", (self.mod_root / "QtPanel" / "main.qml").exists() or (self.qt_root / "main.qml").exists(), "main.qml"))
        marker = self.mod_root / "panel_qml_source.txt"
        if marker.is_file():
            try:
                first = marker.read_text(encoding="utf-8", errors="replace").splitlines()[0]
                expected = "source=bundled-exe" if getattr(sys, "frozen", False) and not development_qml_requested() else "source=live-disk"
                checks.append(("QML source", first == expected, first))
            except Exception:
                pass
        # Save editing is intentionally excluded from the public safe profile.
        # A private development helper may exist, but it is never a release
        # requirement and must not make a clean consumer install fail self-test.
        checks.append(("Safe profile excludes save editing", True, "SaveTools.ps1 is not required"))
        checks.append(("Support script", self.support_script.exists(), str(self.support_script)))
        checks.append(("Catalog rows", len(self._catalog_rows) > 0, f"{len(self._catalog_rows)} loaded"))
        checks.append(("Visible item rows", self._items_proxy.rowCount() > 0, f"{self._items_proxy.rowCount()} visible"))
        try:
            self.support_reports_dir.mkdir(parents=True, exist_ok=True)
            probe = self.support_reports_dir / ".selftest.tmp"
            probe.write_text("ok\n", encoding="utf-8")
            probe.unlink(missing_ok=True)
            checks.append(("Reports folder writable", True, str(self.support_reports_dir)))
        except Exception as exc:
            checks.append(("Reports folder writable", False, str(exc)))

        failed = 0
        for name, ok, detail in checks:
            failed += 0 if ok else 1
            lines.append(f"{'PASS' if ok else 'FAIL'} | {name} | {detail}")
        lines.append("")
        lines.append("Result: " + ("PASS" if failed == 0 else f"WARN ({failed} failed check(s))"))
        stamp = time.strftime("%Y%m%d-%H%M%S")
        self.support_reports_dir.mkdir(parents=True, exist_ok=True)
        report = self.support_reports_dir / f"PanelSelfTest-{stamp}.txt"
        report.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return {"ok": failed == 0, "message": lines[-1], "report": str(report)}

    @Property(str, notify=statusChanged)
    def version(self):
        return self._version

    @Property(str, constant=True)
    def assetRootUrl(self):
        return QUrl.fromLocalFile(str(self.assets_dir.resolve())).toString() + "/"

    def _asset_roots(self) -> tuple[Path, ...]:
        """Return external assets first, then the packaged per-file fallback."""
        roots = [self.assets_dir.resolve()]
        bundled = self.bundled_assets_dir.resolve()
        if bundled not in roots:
            roots.append(bundled)
        return tuple(roots)

    @Slot(str, float, float, bool, result=QSize)
    def artDecodeSize(self, url: str, box_width: float, box_height: float, cover: bool) -> QSize:
        """Decode size for full-window art (panel audit A3).

        The smallest size that still covers (``cover``, PreserveAspectCrop)
        or fits (PreserveAspectFit) a ``box_width`` x ``box_height`` device-
        pixel box, and never larger than the file itself: nothing is ever
        upscaled, and art shown on a 1440p screen is no longer decoded and
        uploaded at 4K (the Items page fell back to a 4728x5320 file, 96 MiB).
        Reads only the image header; results are cached per file version.
        """
        natural = self._art_natural_size(url)
        if natural is None or natural.isEmpty():
            return QSize()
        width, height = natural.width(), natural.height()
        try:
            box_width = float(box_width)
            box_height = float(box_height)
        except (TypeError, ValueError):
            return QSize(width, height)
        if box_width <= 0 or box_height <= 0:
            return QSize(width, height)
        ratios = (box_width / width, box_height / height)
        scale = max(ratios) if cover else min(ratios)
        if scale >= 1.0:
            return QSize(width, height)
        return QSize(max(1, math.ceil(width * scale)), max(1, math.ceil(height * scale)))

    def _art_natural_size(self, url: str) -> QSize | None:
        path_text = QUrl(str(url or "")).toLocalFile()
        if not path_text:
            return None
        path = Path(path_text)
        try:
            key = (str(path), path.stat().st_mtime_ns)
        except OSError:
            return None
        cache = getattr(self, "_art_size_cache", None)
        if cache is None:
            cache = self._art_size_cache = {}
        if key not in cache:
            cache[key] = QImageReader(str(path)).size()
        return cache[key]

    @Slot(str, result=str)
    def assetUrlIfExists(self, relative: str) -> str:
        rel = relative.replace("\\", "/").lstrip("/")
        for root in self._asset_roots():
            path = (root / rel).resolve()
            try:
                path.relative_to(root)
            except ValueError:
                return ""
            if path.is_file():
                return QUrl.fromLocalFile(str(path)).toString()
        return ""

    @Slot(str, result=str)
    def brandUrl(self, filename: str) -> str:
        """Return a file URL for assets/brand/<filename> with mtime cache-bust."""
        name = filename.replace("\\", "/").split("/")[-1]
        for root in self._asset_roots():
            path = (root / "brand" / name).resolve()
            try:
                path.relative_to(root)
            except ValueError:
                continue
            if path.is_file():
                base = QUrl.fromLocalFile(str(path)).toString()
                return f"{base}?v={int(path.stat().st_mtime)}"
        return self.assetRootUrl + "brand/" + name

    @Property(str, constant=True)
    def uiRevision(self):
        return self._ui_revision

    @Property(str, constant=True)
    def patchNotes(self):
        return self._patch_notes

    @Property(str, notify=healthChanged)
    def healthLevel(self):
        return self._health_level

    @Property(str, notify=healthChanged)
    def healthSummary(self):
        return self._health_summary

    @Property(str, notify=healthChanged)
    def healthDetail(self):
        return self._health_detail

    @Property(str, notify=healthChanged)
    def healthReport(self):
        return self._health_report

    @Property(bool, notify=statusChanged)
    def gameRunning(self):
        return self._game_running

    @Property(str, notify=gameStartNoteChanged)
    def gameStartNote(self):
        'A few words in the top bar after a Start game that ended on its'


        return self._game_start_note

    @Property(str, notify=gameStartNoteChanged)
    def gameStartNoteDetail(self):
        return self._game_start_note_detail

    def _set_game_start_note(self, message: str) -> None:
        note = start_note_for(message)
        stamp = time.strftime('%I:%M %p').lstrip('0')
        detail = f"Start game at {stamp}: {message}" if note else ""
        if (note, detail) == (self._game_start_note, self._game_start_note_detail):
            return
        self._game_start_note, self._game_start_note_detail = note, detail
        self.gameStartNoteChanged.emit()

    def _recheck_game_start_note(self) -> None:
        """The note goes once it is no longer true: the game runs, or (for
        Steam's sign-in) Steam signed in or closed. Steam is read on the game
        check's worker thread (about 9 ms: process list, registry, two log
        tails, the window list) and only while this note is up, so neither
        the GUI thread nor the panel at rest does extra work."""
        if not self._game_start_note:
            return
        if self._game_running:
            self._set_game_start_note("")
            return
        login = getattr(self, "_steam_note_login", None)
        self._steam_note_login = None
        if self._game_start_note == STEAM_SIGNED_OUT_NOTE and login is not None:
            if not login.running or login.signed_in:
                self._set_game_start_note("")

    @Property(bool, notify=statusChanged)
    def modConnected(self):
        return self._mod_connected

    @Property(str, notify=statusChanged)
    def connectionTier(self):
        return self._connection_tier

    @Property(bool, notify=statusChanged)
    def luaReady(self):
        return self._lua_ready

    @Property(bool, notify=godChanged)
    def godMode(self):
        return self._god_enabled

    @Property(bool, notify=godChanged)
    def nativeGodReady(self):
        """True only when the trusted SBGodNative DLL and marker are present."""
        return self._native_god_ready

    @Property(bool, notify=godChanged)
    def nativeGodApplied(self):
        """True only when a fresh native heartbeat confirms God Mode is live."""
        return self._native_god_applied

    @Property(bool, notify=energyChanged)
    def energyBeta(self):
        """The Unlimited Beta Energy switch as the player left it."""
        return self._energy_beta

    @Property(bool, notify=energyChanged)
    def energyBurst(self):
        """The Unlimited Burst Energy switch as the player left it."""
        return self._energy_burst

    @Property("QVariantMap", notify=energyChanged)
    def energyStatus(self):
        """The Unlimited energy card: {state, reason, available, betaActive, burstActive}."""
        return self._energy_status.as_qml()

    @Property(str, notify=statusChanged)
    def statusText(self):
        return self._status_text

    @Property(str, notify=statusChanged)
    def statusDetail(self):
        return self._status_detail

    @Property(str, notify=statusChanged)
    def spawnApi(self):
        return self._spawn_api

    @Property(bool, notify=infrastructureChanged)
    def backendBusy(self):
        return self._tasks.active_count() > 0

    @Property(bool, notify=infrastructureChanged)
    def gameLaunchBusy(self):
        return self._tasks.is_active("game")

    @Property(str, notify=infrastructureChanged)
    def backendBusyText(self):
        return self._tasks.busy_text()

    @Property(bool, notify=infrastructureChanged)
    def saveBusy(self):
        return self._tasks.is_active("save")

    @Property(bool, notify=infrastructureChanged)
    def supportBusy(self):
        return self._tasks.is_active("support")

    @Property(str, notify=saveSnapshotsChanged)
    def saveSnapshotSummary(self):
        return self._save_snapshot_summary

    @Property(str, notify=saveSnapshotsChanged)
    def saveSnapshotNote(self):
        return self._save_snapshot_note

    @Property(bool, notify=saveSnapshotsChanged)
    def saveSnapshotBusy(self):
        return self._save_snapshot_job is not None

    @Property(str, notify=infrastructureChanged)
    def backendLastJob(self):
        return self._last_job_summary

    @Property(str, notify=infrastructureChanged)
    def backendJobHistory(self):
        return "\n".join(self._job_history)

    @Property(int, notify=infrastructureChanged)
    def backendActiveCount(self):
        return self._tasks.active_count()

    @Property(str, constant=True)
    def backendRuntime(self):
        return "Qt/Python async service bridge"

    @Property(QObject, constant=True)
    def performance(self):
        return self._performance

    @Property(QObject, constant=True)
    def gameTelemetry(self):
        return self._game_telemetry

    @Property(str, notify=rendererChanged)
    def panelRendererMode(self):
        actual = (self._renderer_actual or "unknown").casefold()
        if actual in {"unknown", ""}:
            return "checking"
        if actual == "software":
            if self._renderer_safe_mode_reason:
                return "safe_mode"
            return "software_override" if self._renderer_requested == "software" else "software"
        return "hardware"

    @Property(str, notify=rendererChanged)
    def panelRendererSummary(self):
        mode = self.panelRendererMode
        text = {"checking": "Checking panel graphics", "hardware": "Graphics card in use",
                "software_override": "Software graphics selected manually",
                "software": "Software graphics in use", "safe_mode": "Software graphics for compatibility or crash recovery"}[mode]
        if mode == "hardware":
            text += f" ({self._renderer_actual})"
        return text

    @Property(str, notify=rendererChanged)
    def panelRendererTechnicalSummary(self):
        actual = self._renderer_actual or "unknown"
        if os.environ.get("QSG_RENDER_LOOP", PANEL_RENDER_LOOP) == "threaded":
            summary = f"{actual}; frame rate {PANEL_FRAME_CAP_TEXT}"
        else:
            # Software renderer or a --render-loop basic diagnostic run: Qt's
            # 16 ms animation timer paces it, not the monitor.
            summary = f"{actual}; frame rate up to 60 frames/s (Qt animation timer, not vsync)"
        if self._renderer_safe_mode_reason:
            summary += f"; compatibility safety mode: {self._renderer_safe_mode_reason}"
        return summary

    @Property(str, constant=True)
    def panelRendererRequested(self):
        return self._renderer_requested

    @Property(str, notify=rendererChanged)
    def panelGraphicsIsolationSummary(self):
        if self._remaining_graphics_hooks:
            return "Known overlay or capture modules still loaded: " + ", ".join(self._remaining_graphics_hooks)
        text = "No known overlay or capture module detected"
        if self._extension_mitigation_status != "enabled":
            text += "; Windows overlay mitigation unavailable"
        return text

    @Property(str, notify=rendererChanged)
    def panelGraphicsIsolationTechnicalSummary(self):
        return (f"extension-point mitigation {self._extension_mitigation_status}; "
                f"remaining hooks: {', '.join(self._remaining_graphics_hooks) or 'none detected'}")

    @Property(str, notify=rendererChanged)
    def externalFramePolicySummary(self):
        return self._external_frame_policy_summary

    @Slot()
    def refreshExternalFramePolicy(self):
        summary = read_external_frame_policy()
        if summary != self._external_frame_policy_summary:
            self._external_frame_policy_summary = summary
            self.rendererChanged.emit()

    def set_renderer_actual(self, actual: str) -> None:
        actual = (actual or "unknown").strip()
        if actual == self._renderer_actual:
            return
        self._renderer_actual = actual
        self.rendererChanged.emit()

    def set_remaining_graphics_hooks(self, modules: list[str]) -> None:
        modules = sorted(set(modules), key=str.casefold)
        if modules == self._remaining_graphics_hooks:
            return
        self._remaining_graphics_hooks = modules
        self.rendererChanged.emit()

    @Property(str, notify=logChanged)
    def issueLog(self):
        """Support > Activity log: plain words only (plain_issue_line)."""
        return plain_issue_log(self._issue_log)

    @Property(str, notify=logChanged)
    def technicalLog(self):
        """Support > Technical details > Technical log: the same lines with
        their level, area and technical detail, newest first."""
        return self._issue_log

    @Property(QObject, constant=True)
    def itemsModel(self):
        return self._items_proxy

    @Property(int, notify=itemsChanged)
    def itemCount(self):
        """Listed items the current search and category show."""
        return self._items_match_counts()[0]

    @Property(int, notify=itemsChanged)
    def itemSearchOnlyCount(self):
        """Items a search found that can't be added from the list."""
        return self._items_match_counts()[1]

    @Property(int, notify=itemsChanged)
    def catalogCount(self):
        """Items in the list (default items plus the opt-in groups that are on)."""
        return self._items_listed_count()

    @Property("QVariantList", notify=itemsChanged)
    def categories(self):
        return self._categories

    @Property(str, notify=selectedItemChanged)
    def selectedAlias(self):
        return self._selected_alias

    @Property(str, notify=selectedItemChanged)
    def selectedName(self):
        return self._selected_name

    @Property(str, notify=selectedItemChanged)
    def itemPolicyLevel(self):
        return self._item_policy_level

    @Property(str, notify=selectedItemChanged)
    def itemPolicyText(self):
        return self._item_policy_text

    @Property(str, notify=selectedItemChanged)
    def itemPolicyDetail(self):
        return self._item_policy_detail

    @Property(str, notify=itemsChanged)
    def itemPolicyDbSummary(self):
        return self._item_policy_db_summary

    @Property(bool, notify=selectedItemChanged)
    def itemLiveSupported(self):
        return self._item_live_supported

    # -- the Add card: the chosen item as the game mod sees it --------------

    @Property(str, notify=selectedItemChanged)
    def selectedChipText(self):
        return CHIP_LABELS.get(self._selected_chip, "")

    @Property(str, notify=selectedItemChanged)
    def selectedChipKind(self):
        return CHIP_KINDS.get(self._selected_chip, "off")

    @Property(str, notify=selectedItemChanged)
    def selectedReason(self):
        """Why the chosen item can't be added now ("" when it can)."""
        return self._selected_chip_reason

    @Property(bool, notify=selectedItemChanged)
    def selectedAddable(self):
        return self._selected_chip == CHIP_READY and self._selected_max_qty > 0

    @Property(int, notify=selectedItemChanged)
    def selectedMaxQty(self):
        """The most one add may ask for now (1 for a one-of-a-kind item)."""
        return self._selected_max_qty

    @Property(str, notify=selectedItemChanged)
    def selectedDescription(self):
        return str(self._selected_row.get("description") or "")

    @Property(str, notify=selectedItemChanged)
    def selectedCategory(self):
        return str(self._selected_row.get("category") or "")

    @Property(str, notify=selectedItemChanged)
    def selectedNote(self):
        """Plain notes for the chosen item: opt-in caution, quest and trophy."""
        row = self._selected_row
        notes = [str(row.get("note") or "")] if row.get("note") else []
        if row.get("listed"):
            if row.get("one_copy") and "One of each" not in " ".join(notes):
                notes.append("One of a kind: added once.")
            if row.get("quest"):
                notes.append("Also used in a quest.")
            if row.get("trophy"):
                notes.append("Counts toward a trophy.")
        return " ".join(notes)

    @Property(bool, notify=statusChanged)
    def liveProbeReady(self):
        return self._live_probe_ready_cached

    @Property(str, notify=statusChanged)
    def liveProbeText(self):
        return self._live_probe_text_cached

    @Property(str, notify=selectedItemChanged)
    def itemLastResult(self):
        return self._item_last_result

    @Property(int, notify=selectedItemChanged)
    def qty(self):
        return self._qty

    @Property(bool, notify=liveAddChanged)
    def liveAddInstalled(self):
        return self._live_add_installed

    @Property(bool, notify=liveAddChanged)
    def liveAddTrusted(self):
        return self._live_add_trusted

    @Property(bool, notify=liveAddChanged)
    def liveAddReady(self):
        return self._live_add_ready

    @Property(bool, notify=liveAddChanged)
    def liveAddBusy(self):
        return self._live_add_busy

    @Property(str, notify=liveAddChanged)
    def liveAddStatus(self):
        return self._live_add_status

    @Property(bool, notify=liveAddChanged)
    def moneyLiveAddReady(self):
        return self._money_live_add_ready

    @Property(str, notify=liveAddChanged)
    def moneyStatusState(self):
        return self._money_status_state

    @Property(str, notify=liveAddChanged)
    def moneyLiveAddStatus(self):
        return self._money_live_add_status

    @Property(str, notify=liveAddChanged)
    def moneyLastResult(self):
        """The last money add's own line (Adding / Added / why not)."""
        return self._money_last_result

    @Property(str, notify=liveAddChanged)
    def moneyAlias(self):
        return self._money_alias

    @Property(str, notify=liveAddChanged)
    def moneyName(self):
        return str(self._money_row().get("name") or "Gold")

    @Property(int, notify=liveAddChanged)
    def moneyBalance(self):
        """The chosen currency in the bag, or -1 while unknown."""
        return self._money_balance

    @Property(int, notify=liveAddChanged)
    def moneyMaxAdd(self):
        """The most one add may send now (the tier, then the room left)."""
        return self._money_max_add

    @Property(int, notify=liveAddChanged)
    def moneyTierMax(self):
        return int(self._money_row().get("max") or 0)

    @Property("QVariantList", notify=liveAddChanged)
    def moneyPresets(self):
        """Quick amounts, never above what one add may send now."""
        tier = int(self._money_row().get("max") or 0)
        if self._money_alias == MONEY_ALIAS:
            presets = list(self._items_catalog.money.get("presets") or [])
        else:
            presets = [10, 100, 1000, tier]
        ceiling = self._money_max_add if self._money_live_add_ready else tier
        return [value for value in dict.fromkeys(presets) if 0 < value <= max(ceiling, 1)]

    @Property(int, notify=liveAddChanged)
    def moneyConfirmAmount(self):
        """A large amount waiting for the player's second "Add" (0: none)."""
        return self._money_confirm_amount

    @Property(bool, notify=liveAddChanged)
    def moneyAdding(self):
        """A money add (not an item add) is in flight."""
        return bool(self._live_add_busy and self._live_add_expected_currency)

    @Property("QVariantList", notify=itemsChanged)
    def moneyCurrencies(self):
        """[{alias, name}] for the currency picker: Gold, then (opt-in) the rest."""
        return [{"alias": row["alias"], "name": row["name"]} for row in self._money_currency_rows()]

    @Property("QVariantList", notify=itemsChanged)
    def itemsOptIns(self):
        """[{key, name, hint, count, on}] for the More items switches."""
        return [
            {"key": t.key, "name": t.name, "hint": t.hint, "count": t.count,
             "on": bool(self._items_optins.get(t.key))}
            for t in self._items_catalog.toggles
        ]

    @Property(bool, notify=itemsChanged)
    def moneyOtherCurrencies(self):
        return bool(self._items_optins.get("currencies"))

    @Property(str, notify=liveAddChanged)
    def itemsStatusLabel(self):
        """Ready / Waiting for game / Adding / Added / Off / Needs update / Couldn't start safely."""
        return self._live_add_status_label

    @Property(str, notify=liveAddChanged)
    def itemsStatusState(self):
        return self._live_add_status_state

    @Property("QVariantMap", notify=nativeStatusChanged)
    def nativeStatus(self):
        """Per-card {state, label, detail, ready} from each native's own status."""
        return {key: dict(value) for key, value in self._native_status.items()}

    @Property(int, notify=movementChanged)
    def speedPct(self):
        return int(round(self._speed * 100))

    @Property(int, notify=movementChanged)
    def walkPct(self):
        return int(round(self._walk * 100))

    @Property(int, notify=movementChanged)
    def jumpPct(self):
        return int(round(self._jump * 100))

    @Property(int, notify=movementChanged)
    def fovDegrees(self):
        return int(round(self._fov))

    @Property(bool, notify=movementChanged)
    def movementAvailable(self):
        """Offline-capable install truth: exact trusted DLL plus enable marker."""
        return self._native_movement_installed()

    @Property(bool, notify=movementChanged)
    def nativeMovementReady(self):
        return self._native_movement_live_state()[0]

    @Property(bool, notify=movementChanged)
    def nativeMovementApplied(self):
        return self._native_movement_live_state()[1]

    @Property(bool, notify=movementChanged)
    def nativeFovApplied(self):
        return self._native_movement_live_state()[2]

    @Property(bool, notify=retryPointChanged)
    def retryPointInstalled(self):
        return self._retry_point_installed

    @Property(bool, notify=retryPointChanged)
    def retryPointAvailable(self):
        return self._retry_point_available

    @Property(bool, notify=retryPointChanged)
    def retryPointSaved(self):
        return self._retry_point_saved

    @Property(bool, notify=retryPointChanged)
    def retryPointCanReturn(self):
        """Return can be used now: a point is saved and the game mod is ready
        (it checks the area itself on every Return)."""
        return self._retry_point_can_return

    @Property(bool, notify=retryPointChanged)
    def retryPointElsewhere(self):
        """Eve is outside the point's area now: the game mod's own area check
        (0.2.3, every 3 s under this panel's watch lease) found her there.
        A 0.2.1 game mod checks only inside Set Point and Return, so its
        answer is left to the card's line."""
        return self._retry_point_area == "elsewhere" and self._retry_point_area_live

    @Property(bool, notify=retryPointChanged)
    def retryPointBusy(self):
        return self._retry_point_busy

    @Property(str, notify=retryPointChanged)
    def retryPointPhase(self):
        return self._retry_point_phase

    @Property(str, notify=retryPointChanged)
    def retryPointStatus(self):
        return self._retry_point_status

    @Property(bool, notify=bossChanged)
    def bossEnabled(self):
        """The one Instant Boss Restart switch (the game mod's settings.txt)."""
        return self._boss_enabled

    @Property(bool, notify=bossChanged)
    def bossReady(self):
        """The game mod reported ready in this game session."""
        return self._boss_ready

    @Property(str, notify=bossChanged)
    def bossStatusText(self):
        return self._boss_status_text

    @Property(int, notify=bossChanged)
    def bossRestartCount(self):
        """Fights the game mod started over in this game session
        (Status.bossLine keeps "Restarts so far: N." on the God Mode line)."""
        return int(self._boss_retry_count or 0)

    @Property(bool, notify=bossChanged)
    def bossReviving(self):
        """The screen is black while the game mod restarts the fight."""
        return self._boss_reviving

    @Property(bool, notify=bossChanged)
    def bossSupportsStory(self):
        return self._boss_supports_story

    @Property(str, notify=bossChanged)
    def bossDiagnostics(self):
        """Support > Technical details only: the game mod's version and state."""
        return self._boss_diagnostics

    @Property(bool, notify=settingsChanged)
    def alwaysOnTop(self):
        return self._always_on_top

    @Property(bool, notify=settingsChanged)
    def stellarAccent(self):
        return self._stellar_accent

    @Property(bool, notify=settingsChanged)
    def reduceMotion(self):
        return self._reduce_motion

    @Property(bool, notify=settingsChanged)
    def performanceOverlayEnabled(self):
        return self._performance_overlay_enabled

    @Property(bool, notify=settingsChanged)
    def hardwareAlertsEnabled(self):
        return self._hardware_alerts

    @Property(bool, notify=updateChanged)
    def updateCheckAvailable(self):
        return bool(read_update_source(self.mod_root).version_url)

    @Property(bool, notify=updateChanged)
    def updateCheckEnabled(self):
        return self._update_check_enabled

    @Property(str, notify=updateChanged)
    def updateAvailableVersion(self):
        """The newer version to mention, or "" (no notice)."""
        return self._update_version

    @Property(str, notify=updateChanged)
    def updateDownloadUrl(self):
        return self._update_url

    @Property(str, notify=settingsChanged)
    def performanceOverlaySize(self):
        """compact / standard / large reading size for the in-game HUD."""
        return self._performance_overlay_size

    @Property("QVariantMap", notify=settingsChanged)
    def performanceOverlayMetrics(self):
        return dict(self._performance_overlay_metrics)

    @Property(str, notify=settingsChanged)
    def savedActivePage(self):
        return self._active_page

    @Property(str, notify=settingsChanged)
    def dockMode(self):
        return self._dock_mode

    @Slot()
    def refresh(self):
        reduce_motion = not windows_animations_enabled()
        if reduce_motion != self._reduce_motion:
            self._reduce_motion = reduce_motion
            self.settingsChanged.emit()
        self.refresh_status()
        self.refresh_log()

    @Slot()
    def refresh_status(self):
        if self._ui_fixture_active:
            # Screenshot automation only: the recorded state stays on screen.
            return
        was_running = self._game_was_running
        # Non-blocking: kick the native process probe onto a dedicated worker and
        # use the cached result, so this 1s poll never stalls rendering.
        self._kick_game_check()
        self._game_running = self._game_running_cached
        self._game_telemetry.set_target_process(self._game_pid_cached if self._game_running else 0)
        self._recheck_game_start_note()
        if was_running and not self._game_running:
            # Runtime movement is a per-game-session choice. FOV remains
            # remembered, but speed/jump must be explicitly applied next run.
            self._movement_enabled = False
            reset_native_god_state(self.mod_root)
            cleared, heartbeat_errors = clear_stale_heartbeat_files(
                self.mod_root,
                force=True,
            )
            if heartbeat_errors:
                self._append_issue(
                    "WARN",
                    "connection",
                    "Couldn't tidy up the game connection after the game closed. "
                    "If the game mods don't connect next time, run One-Click Repair on Support.",
                    "closed-game heartbeat cleanup: " + ", ".join(heartbeat_errors),
                )
            elif cleared:
                self._append_issue(
                    "OK",
                    "connection",
                    "Tidied up the game connection after the game closed.",
                    "cleared closed-game heartbeat leases: " + ", ".join(cleared),
                    toast=False,
                )
            result = apply_pending_god_pak_changes(self.mod_root, self.paks_mods_dir, self.disabled_paks_dir)
            if result is None:
                result = sync_god_paks_with_state(
                    self.mod_root,
                    self.paks_mods_dir,
                    self.disabled_paks_dir,
                    False,
                )
            if result is not None:
                level = "OK" if result.ok else "WARN"
                message, toast = friendly_god_files_message(result)
                self._append_issue(level, "god", message, result.message, toast=toast)
        elif not self._game_running:
            self._migrate_live_god_paks(log=False)
        elif not was_running and self._game_running:
            reset_native_god_state(self.mod_root)
            if self._read_god_enabled():
                self._nudge_god_reapply()
            # The reset wrote both energy switches off; put the remembered
            # ones back for this game session.
            self._publish_energy_switches()
            self._request_save_snapshot("game start")
            # A restore's note and its Undo belong to before this game
            # session (its "Before restore" copy stays in Save history).
            if self._save_restore_note or self._save_undo_name:
                self._save_restore_note = ""
                self._save_undo_name = ""
                self.saveSnapshotsChanged.emit()
        self._game_was_running = self._game_running
        if self._native_movement_installed():
            self._write_native_movement_state(quiet=True)
        self._set_native_status("movement", self._movement_native_verdict())
        # Item results are read only by _refresh_live_add_status, bound to the
        # exact request this panel sent; unrelated status rows are ignored.
        spawn_status = read_kv(self.spawn_status_file)
        self._spawn_api = spawn_status.get("spawnapi") or ""
        profile = inspect_hook_free_retry_profile(self.mod_root.parent)
        self._hook_free_profile_safe = profile.safe
        self._hook_free_profile_status = profile.detail
        self.movementChanged.emit()
        # Instant Boss Restart's game mod reporting in this game session
        # proves the game mods are loaded (the "external" tier).
        conn = evaluate_connection(
            self.mod_root,
            self._game_running,
            self._spawn_api,
            external_ready=bool(self._boss_ready and profile.safe),
            external_active=bool(self._boss_enabled),
            allow_legacy=not profile.safe,
            allow_lua=not profile.safe,
            allow_native=profile.native_bridge_ready,
        )
        heartbeat = conn.lua_heartbeat
        if not self._spawn_api:
            self._spawn_api = heartbeat.get("spawnapi") or ""
        self._connection_tier = conn.tier
        self._lua_ready = conn.lua_ready
        self._mod_connected = conn.mod_connected
        self._status_text = conn.status_text
        self._status_detail = conn.status_detail
        native_god_installed = bool(profile.native_bridge_ready)
        # Installed files only allow God Mode. While the game runs, the native
        # heartbeat must also prove hooks_installed=1 on this exact game build;
        # otherwise the card says "Needs update" and never claims protection.
        god_verdict = self._god_native_verdict(native_god_installed, conn)
        self._god_verdict = god_verdict
        self._set_native_status("god", god_verdict)
        self._native_god_installed = native_god_installed
        self._refresh_energy_status(conn)
        native_god_ready = native_god_installed and god_verdict.state in (NATIVE_READY, NATIVE_WAITING)
        native_god_applied = native_god_protection_applied(
            conn.native_heartbeat,
            game_running=bool(self._game_running),
            native_ready=native_god_ready,
            heartbeat_fresh=conn.native_fresh,
        )
        god_now = self._read_god_enabled()
        if (
            god_now != self._god_enabled
            or native_god_ready != self._native_god_ready
            or native_god_applied != self._native_god_applied
        ):
            self._god_enabled = god_now
            self._native_god_ready = native_god_ready
            self._native_god_applied = native_god_applied
            self.godChanged.emit()
        # Do not rewrite native_god_state here — it was zeroing actorptr/bagptr from Lua.
        self._refresh_boss_status()
        self._refresh_live_add_status()
        if not self._game_running:
            # Its fast timer is off while the game is closed (see
            # _sync_game_timers); this slow pass keeps the card current.
            self._refresh_retry_point_status()
        self._sync_game_timers()
        self._live_probe_ready_cached, self._live_probe_text_cached = self._live_probe_ready()
        signature = (
            self._game_running,
            self._mod_connected,
            self._connection_tier,
            self._lua_ready,
            self._status_text,
            self._status_detail,
            self._spawn_api,
            self._live_probe_ready_cached,
            self._live_probe_text_cached,
        )
        # Do not invalidate every status binding once per second when the values
        # are identical. This keeps QML animation and scrolling work predictable.
        if signature != self._status_signature:
            self._status_signature = signature
            self.statusChanged.emit()

    @Slot()
    def refresh_log(self):
        new_log = self._read_issue_tail()
        if new_log != self._issue_log:
            self._issue_log = new_log
            self.logChanged.emit()

    @Slot(str, str)
    def setItemFilter(self, text: str, category: str):
        self._filter = text or ""
        self._category = category or "All"
        self._filter_timer.start()

    @Slot(str, str)
    def selectItem(self, alias: str, name: str):
        clean_alias = (alias or "").strip()
        if clean_alias and not re.fullmatch(r"[A-Za-z0-9_+]{1,128}", clean_alias):
            self._selected_alias = ""
            self._selected_name = "Pick an item"
            self._append_issue(
                "WARN", "items", "That item couldn't be selected.", "invalid catalog item identifier"
            )
            self.selectedItemChanged.emit()
            return
        clean_name = re.sub(r"[\x00-\x1f\x7f]", "", name or clean_alias).strip()[:160]
        self._selected_alias = clean_alias
        self._selected_name = clean_name or clean_alias or "Pick an item"
        self._set_quick_item_policy(self._selected_alias)
        self.selectedItemChanged.emit()

    @Slot(int)
    def setQty(self, qty: int):
        limit = self._selected_max_qty or LIVE_ADD_LEGACY_MAX_QTY
        self._qty = max(1, min(limit, int(qty or 1)))
        self.selectedItemChanged.emit()

    @Slot()
    def requestLiveAdd(self):
        """Send exactly one add of the chosen item through gui_state.txt."""
        if not self._selected_alias:
            self._append_issue("WARN", "items", "Pick an item first.")
            return
        # Judge the click on fresh facts: the route, the probe answers and
        # the chosen item's chip.
        self._refresh_live_add_status()
        if self._item_policy_level == "BLOCKED":
            self._append_issue(
                "WARN", "items", "This item can't be added.",
                f"search-only catalog row: {self._selected_chip_reason}",
            )
            return
        if not self._item_live_supported:
            self._append_issue(
                "WARN", "items", self._selected_chip_reason or "This item can't be added right now.",
                f"chip {self._selected_chip or 'none'}",
            )
            return
        if not self._live_add_ready or self._live_add_busy:
            self._append_issue("WARN", "items", self._live_add_status)
            return
        if self._selected_chip != CHIP_READY or self._selected_max_qty <= 0:
            self._append_issue(
                "WARN", "items", self._selected_chip_reason or "This item can't be added right now.",
                f"chip {self._selected_chip or 'none'}, limit {self._selected_max_qty}",
            )
            return
        quantity = max(1, min(self._selected_max_qty, int(self._qty)))
        self._send_live_add(
            self._selected_alias, self._selected_name, quantity,
            max_quantity=self._selected_max_qty, currency=False,
        )

    def _send_live_add(
        self, alias: str, name: str, quantity: int, *, max_quantity: int, currency: bool
    ) -> None:
        """One request, one add: the game-owned route, no retries."""
        try:
            state = read_kv(self.state_file)
            previous_sequence = int(state.get("spawnseq") or "0")
            heartbeat = read_kv(self.heartbeat_file)
            protocol = live_add_route_protocol(self.live_add_script, self.live_add_native_dll)
            if not protocol or not trusted_live_add_protocol(heartbeat, protocol):
                raise ValueError("the game session is not verified")
            session = str(heartbeat.get("session") or "").strip()
            request_id = secrets.token_hex(16)
            if self._items_mode != "probe":
                # The Live Add v3 route never sends more than 99.
                max_quantity = min(max_quantity, LIVE_ADD_LEGACY_MAX_QTY)
            quantity = max(1, min(max_quantity, int(quantity)))
            updates = build_live_add_updates(
                alias=alias,
                quantity=quantity,
                previous_sequence=previous_sequence,
                session=session,
                request_id=request_id,
                issued_unix_s=int(time.time()),
                max_quantity=max_quantity,
            )
            self._live_add_expected_session = session
            self._live_add_expected_request_id = request_id
            self._live_add_expected_sequence = int(updates["spawnseq"])
            self._live_add_expected_alias = alias
            self._live_add_expected_name = name
            self._live_add_expected_qty = quantity
            self._live_add_expected_currency = currency
            self._update_state(updates)
        except (OSError, TypeError, ValueError, OverflowError) as exc:
            self._clear_live_add_request()
            self._append_issue("ERROR", "items", "Couldn't add safely. Nothing was changed.", str(exc))
            return
        amount = f"{quantity:,} {name}" if currency else f"{quantity} x {name}"
        self._live_add_ready = False
        self._live_add_busy = True
        self._live_add_phase = "adding"
        self._live_add_status = f"Adding {amount}..."
        self._live_add_status_label = "Adding"
        self._live_add_status_state = "adding"
        if currency:
            self._money_last_result = self._live_add_status
        else:
            self._item_last_result = self._live_add_status
        self._refresh_money_state()
        self.liveAddChanged.emit()
        self.selectedItemChanged.emit()
        self._append_issue("INFO", "items", self._live_add_status)

    @Slot(int)
    def requestLiveAddMoney(self, amount: int):
        """Add the chosen currency (Gold unless another one is picked).

        Never more than one add may send now. MONEY_CONFIRM_AT or more is
        not sent here: it waits for confirmLiveAddMoney (the Money card's
        second "Add"), so a large amount never goes out on one click.
        """
        self._refresh_live_add_status()
        self._clear_money_confirm()
        row = self._money_row()
        if not self._money_live_add_ready or not row or self._money_max_add <= 0:
            self._append_issue("WARN", "items", self._money_live_add_status)
            return
        try:
            wanted = int(amount)
        except (TypeError, ValueError, OverflowError):
            wanted = 0
        if wanted < 1:
            self._append_issue("WARN", "items", "Pick an amount first.")
            return
        quantity = min(wanted, self._money_max_add)
        if quantity >= MONEY_CONFIRM_AT:
            self._money_confirm_amount = quantity
            self._money_confirm_alias = row["alias"]
            self._money_confirm_at = time.monotonic()
            self.liveAddChanged.emit()
            return
        self._send_live_add(
            row["alias"], str(row.get("name") or "Gold"), quantity,
            max_quantity=self._money_max_add, currency=True,
        )

    def _clear_money_confirm(self) -> None:
        if self._money_confirm_amount:
            self._money_confirm_amount = 0
            self._money_confirm_alias = ""
            self._money_confirm_at = float("-inf")
            self.liveAddChanged.emit()

    @Slot()
    def confirmLiveAddMoney(self):
        """Send the large amount the player just confirmed, exactly as shown."""
        amount = self._money_confirm_amount
        alias = self._money_confirm_alias
        # Fresh facts; a confirmation that can't be sent as shown lapses here.
        self._refresh_live_add_status()
        row = self._money_row()
        if (
            not amount
            or self._money_confirm_amount != amount
            or alias != self._money_alias
            or not row
            or not self._money_live_add_ready
            or amount > self._money_max_add
        ):
            self._clear_money_confirm()
            self._append_issue(
                "WARN", "items", "That amount can't be added right now. Nothing was added.",
                f"money confirmation lapsed: {amount} {alias}",
            )
            return
        self._clear_money_confirm()
        self._send_live_add(
            row["alias"], str(row.get("name") or "Gold"), amount,
            max_quantity=self._money_max_add, currency=True,
        )

    @Slot()
    def cancelLiveAddMoney(self):
        self._clear_money_confirm()

    @Slot(str)
    def setMoneyCurrency(self, alias: str):
        """Gold, or (with Other currencies on) one of the shop currencies."""
        wanted = str(alias or "").strip()
        allowed = {row["alias"] for row in self._money_currency_rows()}
        if wanted not in allowed:
            wanted = MONEY_ALIAS
        if wanted != self._money_alias:
            self._money_alias = wanted
            if not (self._live_add_busy and self._live_add_expected_currency):
                # The line was about the other currency.
                self._money_last_result = ""
            self._refresh_money_state()
            self.liveAddChanged.emit()

    def _apply_items_fixture(self, data: dict) -> None:
        """Screenshot automation only (--items-fixture): label the catalog
        from recorded probe answers, as a ready v0.5 game mod would. Nothing
        is written to the game or the mod folders."""
        entries: dict[str, ProbeEntry] = {}
        for alias, raw in (data.get("entries") or {}).items():
            entries[str(alias)] = ProbeEntry(
                state=str(raw.get("state") or "not_read"),
                count=int(raw.get("count") or 0),
                max=int(raw.get("max") or 0),
                addable_now=int(raw.get("addable_now") or 0),
            )
        self._items_fixture = {
            "mode": str(data.get("mode") or "probe"),
            "route_ready": bool(data.get("route_ready", True)),
        }
        self._probe_entries = entries
        self._probe_answered_all = bool(data.get("answered_all", True))
        self._probe_version += 1
        # The last add's lines as a finished add leaves them (item_result
        # under Add Item, money_result on the Money card).
        self._item_last_result = str(data.get("item_result") or self._item_last_result)
        self._money_last_result = str(data.get("money_result") or self._money_last_result)
        self._refresh_live_add_status()

    def _apply_ui_fixture(self, data: dict) -> None:
        """Screenshot automation only (--ui-fixture): show the game-running
        states of the Dashboard, God Mode and Instant Boss Restart from
        recorded inputs, through the same functions the live panel uses.

        The panel's own polling stops for this run so the recorded state
        stays on screen. No game is started or touched, no input is sent,
        and nothing is written to the game, the Mods folder or the panel's
        settings (the activity log may get the lines a live run would
        write). Keys: game_running, mod_connected, god_on, god_heartbeat_file (a
        recorded native_heartbeat.txt), energy {beta, burst, supported} (the
        Unlimited energy card, read from that same recorded file; supported =
        the installed game mod has the switches), movement {installed, ready, applied,
        fov_applied}, boss {enabled (the switch), status_file (a recorded
        SBInstantBossRestart status.txt, read as written in this game
        session), status_overrides {key: value}, installed, trusted},
        retry_point {status_file (a recorded retry_point_status.txt),
        status_overrides {key: value}, bound_to_this_panel (the recorded
        status was bound to the panel that recorded it: rebind it to this
        run), point_on_disk, installed, just_returned (the line a Return
        that worked leaves on the card for a short time)}, old_ue4ss_win64 (a folder checked
        for old UE4SS files instead of the game's Binaries/Win64), update_available
        {version, url} (the quiet update line) and last_bug_report (a file name: the
        line under Create Bug Report).
        """
        self._ui_fixture_active = True
        update = data.get("update_available")
        if isinstance(update, dict):
            self._update_version = str(update.get("version") or "")
            self._update_url = safe_download_url(update.get("url"))
            self.updateChanged.emit()
        if data.get("last_bug_report"):
            self._last_bug_report = str(data["last_bug_report"])
            self.bugReportChanged.emit()
        old_ue4ss_win64 = str(data.get("old_ue4ss_win64") or "")
        if old_ue4ss_win64:
            # A test folder checked for old UE4SS files (Support captures).
            self.win64_dir = Path(old_ue4ss_win64)
            self.refreshOldUe4ssFiles()
        for timer in (getattr(self, "_status_timer", None), *self._game_timers()):
            if timer is not None:
                timer.stop()
        running = bool(data.get("game_running", False))
        self._game_running = running
        self._game_running_cached = running
        # A PID no process has: the monitor's capture finds no game window.
        self._game_pid_cached = 0x7FFFFFF0 if running else 0
        self._mod_connected = bool(data.get("mod_connected", running))
        # game_start_message: a Start game result whose note the top bar keeps
        # (captures of the build 4d note; the toast itself is not replayed).
        self._set_game_start_note(str(data.get("game_start_message") or ""))
        heartbeat_file = str(data.get("god_heartbeat_file") or "")
        if heartbeat_file:
            from services.native_status import parse_status_text

            heartbeat = parse_status_text(Path(heartbeat_file).read_text(encoding="utf-8", errors="replace"))
            verdict = god_heartbeat_verdict(
                installed=True,
                game_running=running,
                heartbeat=heartbeat,
                heartbeat_fresh=running,
            )
            self._set_native_status("god", verdict)
            native_ready = verdict.state in (NATIVE_READY, NATIVE_WAITING)
            self._god_enabled = bool(data.get("god_on", True))
            self._native_god_ready = native_ready
            self._native_god_applied = native_god_protection_applied(
                heartbeat,
                game_running=running,
                native_ready=native_ready,
                heartbeat_fresh=running,
            )
            energy = data.get("energy")
            if isinstance(energy, dict):
                self._energy_beta = bool(energy.get("beta", False))
                self._energy_burst = bool(energy.get("burst", False))
                self._energy_status = energy_status(
                    beta_wanted=self._energy_beta,
                    burst_wanted=self._energy_burst,
                    installed=True,
                    supported=bool(energy.get("supported", True)),
                    god_state=verdict.state,
                    game_running=running,
                    heartbeat=heartbeat,
                    heartbeat_fresh=running,
                )
        boss = data.get("boss") or {}
        if boss:
            from services.native_status import parse_status_text

            status: dict[str, str] | None = None
            status_file = str(boss.get("status_file") or "")
            if status_file:
                status = dict(parse_status_text(
                    Path(status_file).read_text(encoding="utf-8", errors="replace")
                ))
            if boss.get("status_overrides"):
                status = dict(status or {})
                status.update({str(k): str(v) for k, v in boss["status_overrides"].items()})
            if status is not None:
                # Recorded in another game session: read as written in this one.
                status["loaded"] = str(int(time.time()))
            installed = bool(boss.get("installed", True))
            trusted = installed and bool(boss.get("trusted", True))
            self._ibr_fixture = (
                IbrInstall(installed, trusted, str(boss.get("version") or "0.4.0") if trusted else "", installed, "ui-fixture"),
                bool(boss.get("enabled", True)),
                status,
            )
            self._ibr_started = (int(self._game_pid_cached or 0), time.time() - 60.0)
            self._refresh_boss_status()
        retry = data.get("retry_point") or {}
        if retry:
            from services.native_status import parse_status_text

            status: dict[str, str] = {}
            status_file = str(retry.get("status_file") or "")
            if status_file:
                status = dict(parse_status_text(
                    Path(status_file).read_text(encoding="utf-8", errors="replace")
                ))
            status.update({str(k): str(v) for k, v in (retry.get("status_overrides") or {}).items()})
            if retry.get("bound_to_this_panel"):
                status["bound_panel_pid"] = str(os.getpid())
            self._retry_point_pending_seq = 0
            if retry.get("just_returned"):
                self._retry_point_success_text = "Eve is back at the saved point."
                self._retry_point_success_until = time.monotonic() + 3600.0
            self._apply_retry_point_status(
                installed=bool(retry.get("installed", True)),
                files_present=bool(retry.get("installed", True)),
                identity="ui-fixture",
                game_running=running,
                status=status if running else {},
                status_fresh=bool(running and status),
                point_on_disk=bool(retry.get("point_on_disk", status.get("point_valid") == "1")),
            )
        movement = data.get("movement") or {}
        if movement:
            # The movement game mod's install and live verdicts, for this run
            # only; its state file is never written (writes become no-ops).
            installed = bool(movement.get("installed", True))
            live = (
                (bool(movement.get("ready", True)), bool(movement.get("applied", False)),
                 bool(movement.get("fov_applied", False)))
                if installed else (False, False, False)
            )
            self._native_movement_installed = lambda: installed
            self._native_movement_live_state = lambda: live
            self._write_native_movement_state = lambda quiet=False: True
            self._persist_fov_setting = lambda: None
            self._update_state = lambda values: None
            self.movementChanged.emit()
        self.statusChanged.emit()
        self.godChanged.emit()
        self.energyChanged.emit()
        self.bossChanged.emit()
        self.nativeStatusChanged.emit()

    def _stage_money_confirm_for_run(self, amount: int) -> None:
        """Screenshot automation only (--money-confirm): show the Money
        card's large-amount question exactly as a click leaves it. Nothing is
        sent and nothing is written."""
        self._refresh_money_state()
        if MONEY_CONFIRM_AT <= amount <= self._money_max_add and self._money_live_add_ready:
            self._money_confirm_amount = amount
            self._money_confirm_alias = self._money_alias
            self._money_confirm_at = time.monotonic()
            self.liveAddChanged.emit()

    def _set_items_optins_for_run(self, keys: list[str]) -> None:
        """Screenshot automation only: turn opt-in groups on without saving."""
        self._items_optins = dict(
            self._items_optins, **{key: True for key in keys if key in ITEMS_TOGGLE_KEYS}
        )
        self._rebuild_item_rows()
        self.itemsChanged.emit()
        self.liveAddChanged.emit()

    def _money_currency_rows(self) -> list[dict]:
        rows = [self._catalog_row_for_alias(MONEY_ALIAS)]
        if self._items_optins.get("currencies"):
            rows += [row for row in self._catalog_rows if row.get("toggle") == "currencies"]
        return [row for row in rows if row]

    @Slot(str, bool)
    def setItemsOptIn(self, key: str, enabled: bool):
        """Turn an opt-in group (More items / Other currencies) on or off."""
        key = str(key or "")
        if key not in ITEMS_TOGGLE_KEYS:
            return
        enabled = bool(enabled)
        if self._items_optins.get(key) == enabled:
            return
        self._items_optins = dict(self._items_optins, **{key: enabled})
        try:
            self._save_panel_setting(f"itemsOptIn_{key}", "1" if enabled else "0")
        except OSError as exc:
            self._append_issue("WARN", "settings", "Couldn't save that choice.", str(exc))
        if key == "currencies" and not enabled:
            self._money_alias = MONEY_ALIAS
        self._rebuild_item_rows()
        self.itemsChanged.emit()
        self.liveAddChanged.emit()

    @Slot()
    def openGame(self):
        def work():
            return self._launch_game_worker()

        def done(result):
            self.refresh_status()
            attempts = result.get("attempts") or []
            tail = attempts[-1] if attempts else ""
            # The toast fades; the top bar keeps a note while it is true.
            self._set_game_start_note("" if result.get("ok") else str(result.get("message") or ""))
            if result.get("ok"):
                self._append_issue("OK", "game", result.get("message") or "Stellar Blade started.", tail)
            else:
                # A start that ended on its own (the game closed while
                # starting, Steam signed out) is a warning; a start that
                # could not be sent at all is an error.
                report = result.get("report", "")
                self._append_issue(
                    result.get("level") or "ERROR", "game", result.get("message") or "Stellar Blade didn't start.",
                    f"{tail} | launch report: {report}" if report else tail,
                )

        self._set_game_start_note("")
        self._start_backend_job("game", "Starting Stellar Blade", "game", work, done)

    @Slot()
    def quitGame(self):
        if not self._game_running:
            self._append_issue("INFO", "game", "Stellar Blade is not running.")
            return
        script = "Get-Process -Name 'SB-Win64-Shipping' -ErrorAction SilentlyContinue | ForEach-Object { $_.CloseMainWindow() | Out-Null }"
        try:
            subprocess.Popen(
                ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
                cwd=str(self.mod_root),
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            self._append_issue("INFO", "game", "Closing Stellar Blade...", "graceful close requested")
        except Exception as exc:
            self._append_issue("ERROR", "game", "Couldn't close the game.", str(exc))

    @Slot()
    def forceQuitGame(self):
        if not self._game_running:
            self._append_issue("INFO", "game", "Stellar Blade is not running.")
            return
        try:
            subprocess.Popen(
                ["taskkill", "/IM", "SB-Win64-Shipping.exe", "/T", "/F"],
                cwd=str(self.mod_root),
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            self._append_issue("WARN", "game", "Force quitting Stellar Blade...", "taskkill requested")
        except Exception as exc:
            self._append_issue("ERROR", "game", "Couldn't force quit the game.", str(exc))

    @Slot()
    def restartGame(self):
        # Restart only a running game; a closed game is started with Start.
        if not self._game_running or self._tasks.is_active("game"):
            self._append_issue("INFO", "game", "Restart works while Stellar Blade is running. Use Start game to open it.")
            return
        self.forceQuitGame()
        QTimer.singleShot(3500, self.openGame)

    @Slot(bool)
    def setGodMode(self, enabled: bool):
        profile = enforce_hook_free_retry_profile(self.mod_root.parent)
        self._hook_free_profile_safe = profile.safe
        self._hook_free_profile_status = profile.detail
        self.movementChanged.emit()
        native_god_ready = bool(profile.native_bridge_ready)
        readiness_changed = native_god_ready != self._native_god_ready
        self._native_god_ready = native_god_ready
        if not native_god_ready:
            readiness_changed = self._native_god_applied or readiness_changed
            self._native_god_applied = False
        if enabled and not native_god_ready:
            # Re-notify even if readiness was already false so the switch snaps
            # back to the unchanged desired state after this refused click.
            self.godChanged.emit()
            self._append_issue(
                "ERROR",
                "god",
                "God Mode didn't turn on: its game mod isn't installed or couldn't start safely. "
                "Close Stellar Blade and run One-Click Repair on Support.",
                f"trusted SBGodNative DLL and enabled marker unavailable: {profile.detail}",
            )
            return
        if enabled and self._game_running:
            god_verdict = self._god_native_verdict(native_god_ready)
            self._god_verdict = god_verdict
            self._set_native_status("god", god_verdict)
            if god_verdict.state in (NATIVE_NEEDS_UPDATE, NATIVE_UNSAFE):
                self._native_god_ready = False
                self._native_god_applied = False
                self.godChanged.emit()
                self._append_issue(
                    "ERROR",
                    "god",
                    f"God Mode didn't turn on. {god_verdict.detail}",
                    f"reason: {god_verdict.reason}",
                )
                return
        if readiness_changed:
            self.godChanged.emit()
        state = read_kv(self.state_file)
        try:
            seq = int(state.get("godseq", "0")) + 1
        except Exception:
            seq = 1
        self._update_state({"godlive": "1" if enabled else "0", "godseq": seq, "god": "0"})
        # SBGodNative now discovers Eve on UE4SS's game-thread update callback,
        # so the panel can safely write only the desired ON/OFF state. It never
        # sends or reuses process pointers from the external panel.
        write_native_god_state(self.mod_root, enabled)
        prepare_live_god_mode(self.mod_root, self.paks_mods_dir, self.disabled_paks_dir)

        self._god_enabled = bool(enabled)
        self.godChanged.emit()

        if self._game_running:
            if profile.changed:
                self._append_issue(
                    "WARN",
                    "god",
                    "God Mode was set up. Restart Stellar Blade once and it switches on by itself.",
                    "native bridge repaired; UE4SS loads it on the next game start",
                )
                return
            self._append_issue(
                "INFO",
                "god",
                "Turning God Mode on..." if enabled else "Turning God Mode off...",
                "requested; the native heartbeat confirms the live state",
            )
            return

        self._append_issue(
            "INFO",
            "god",
            "God Mode is requested. Eve can take damage until the card shows Active."
            if enabled
            else "God Mode is off.",
        )

    @Slot(bool)
    def setUnlimitedBeta(self, enabled: bool):
        self._set_energy_switch("beta", bool(enabled))

    @Slot(bool)
    def setUnlimitedBurst(self, enabled: bool):
        self._set_energy_switch("burst", bool(enabled))

    def _set_energy_switch(self, gauge: str, enabled: bool) -> None:
        """One of the two Unlimited energy switches (Gameplay, under God Mode).

        Both energy lines go to the God Mode game mod's state file in one
        atomic replace that leaves God Mode's own lines as they are, and the
        choice is remembered. Independent of the God Mode switch: neither
        switch reads or changes it.
        """
        name = "Unlimited Beta Energy" if gauge == "beta" else "Unlimited Burst Energy"
        if self._ui_fixture_active:
            # Screenshot automation: nothing is written; the switch snaps back.
            self.energyChanged.emit()
            return
        self._refresh_energy_status()
        usable = self._energy_status.available
        if enabled and not usable:
            # Re-notify so the switch snaps back to the unchanged state.
            self.energyChanged.emit()
            self._append_issue(
                "ERROR",
                "energy",
                f"{name} didn't turn on. Its card on Gameplay says why.",
                f"reason: {self._energy_status.reason}",
            )
            return
        beta = enabled if gauge == "beta" else self._energy_beta
        burst = enabled if gauge == "burst" else self._energy_burst
        try:
            write_native_energy_state(
                self.mod_root,
                beta_live=bool(beta and usable),
                burst_live=bool(burst and usable),
                god_live_default=self._read_god_enabled(),
            )
        except (OSError, ValueError) as exc:
            self.energyChanged.emit()
            self._append_issue(
                "ERROR",
                "energy",
                f"Couldn't save the {name} switch. Check Technical details on Support.",
                f"native_god_state.txt: {type(exc).__name__}: {exc}",
            )
            return
        self._energy_beta = bool(beta)
        self._energy_burst = bool(burst)
        try:
            self._save_panel_setting("energyBeta" if gauge == "beta" else "energyBurst", "1" if enabled else "0")
        except (OSError, ValueError) as exc:
            self._append_issue(
                "WARN",
                "energy",
                f"{name} is set, but the panel couldn't remember it for next time.",
                f"panel_settings.txt: {type(exc).__name__}: {exc}",
            )
        self._refresh_energy_status()
        self.energyChanged.emit()
        if not enabled:
            self._append_issue("OK", "energy", f"{name} is off.", f"{gauge}live=0")
        elif self._game_running:
            self._append_issue(
                "INFO",
                "energy",
                f"{name} is switching on. Wait for Active on its card.",
                f"{gauge}live=1; the game mod's own report confirms the live state",
            )
        else:
            self._append_issue(
                "INFO",
                "energy",
                f"{name} is on for your next game session.",
                f"{gauge}live=1",
            )

    # healFull() intentionally does not exist. It only bumped a "healseq"
    # counter that the legacy Lua module read, and that module is not loaded in
    # the safe profile, so the button never healed anything. Writing health from
    # the panel is not a supported route here; see
    # test_hook_free_gameplay_surface_has_no_health_write_route.

    @Slot()
    def refreshCatalog(self):
        seq = self._inc_state_seq("itemprobeseq")
        self._append_issue(
            "INFO", "catalog", "Refreshing the item list from the game...", f"live catalog refresh seq {seq}"
        )

    @Slot()
    def runPanelSelfTest(self):
        def work():
            return self._run_panel_self_test_worker()

        def done(result):
            level = "OK" if result.get("ok") else "WARN"
            summary = (
                "Panel test: everything passed."
                if result.get("ok")
                else "Panel test found a problem. Details are in the report (Open Reports)."
            )
            self._append_issue(
                level, "panel", summary, f"{result.get('message', 'self-test complete')}; report: {result.get('report')}"
            )

        self._start_backend_job("diagnostic", "Panel test", "panel", work, done)

    @Slot()
    def runHealthCheck(self):
        def work():
            return self._run_health_worker(repair=False)

        def done(result):
            self._health_level = result.get("level", "UNKNOWN")
            self._health_summary = result.get("summary", "Health check finished.")
            self._health_detail = result.get("detail", "")
            self._health_report = result.get("report", "")
            self.healthChanged.emit()
            self._append_issue(
                "OK" if result.get("ok") else "WARN", "health",
                f"Health Check: {self._health_summary}.", f"report: {self._health_report}",
            )

        self._start_backend_job("diagnostic", "Health Check", "health", work, done)

    @Slot()
    def runOneClickRepair(self):
        def work():
            return self._run_health_worker(repair=True)

        def done(result):
            self._health_level = result.get("level", "UNKNOWN")
            self._health_summary = result.get("summary", "Repair finished.")
            self._health_detail = result.get("detail", "")
            self._health_report = result.get("report", "")
            self._hook_free_profile_safe = bool(result.get("profile_safe", False))
            self.movementChanged.emit()
            self.healthChanged.emit()
            self._load_catalog()
            self.refresh_status()
            self._refresh_boss_status()
            self._append_issue(
                "OK" if result.get("ok") else "WARN", "repair",
                f"One-Click Repair: {self._health_summary}.",
                f"report: {self._health_report}",
            )

        self._start_backend_job("repair", "One-Click Repair", "repair", work, done)

    @Slot()
    def resetPanelLink(self):
        def work():
            profile = enforce_hook_free_retry_profile(self.mod_root.parent)
            cleared, heartbeat_errors = clear_stale_heartbeat_files(
                self.mod_root,
                force=not self._game_running,
            )
            return {
                "profile": profile,
                "cleared": cleared,
                "heartbeat_errors": heartbeat_errors,
            }

        def done(result):
            profile = result["profile"]
            self._hook_free_profile_safe = profile.safe
            self._hook_free_profile_status = profile.detail
            self.movementChanged.emit()
            self.refresh_status()
            self._refresh_boss_status()
            cleared = result.get("cleared") or ()
            heartbeat_errors = result.get("heartbeat_errors") or ()
            if not profile.safe or heartbeat_errors:
                detail = profile.detail
                if heartbeat_errors:
                    detail += "; " + ", ".join(heartbeat_errors)
                self._append_issue(
                    "ERROR", "connection",
                    "Couldn't reconnect the game mods. Close Stellar Blade and run One-Click Repair on Support.",
                    f"panel link reset needs attention: {detail}",
                )
            elif profile.changed and self._game_running:
                self._append_issue(
                    "WARN",
                    "connection",
                    "Game mods reconnected. Restart Stellar Blade once to finish.",
                    "unsafe UE4SS modules were active when this session began",
                )
            else:
                suffix = f"; cleared stale files: {', '.join(cleared)}" if cleared else ""
                self._append_issue(
                    "OK",
                    "connection",
                    "Game mods reconnected.",
                    "game mod safety profile and the native gameplay bridge verified" + suffix,
                )

        self._start_backend_job("repair", "Reconnecting game mods", "connection", work, done)

    @Slot(float)
    def setSpeed(self, value: float):
        self._speed = max(0.5, min(3.0, float(value)))
        self.movementChanged.emit()
        self._publish_live_movement()

    @Slot(float)
    def setWalk(self, value: float):
        self._walk = max(0.5, min(3.0, float(value)))
        self.movementChanged.emit()

    @Slot(float)
    def setJump(self, value: float):
        self._jump = max(0.5, min(3.0, float(value)))
        self.movementChanged.emit()
        self._publish_live_movement()

    def _publish_live_movement(self) -> bool:
        """Publish one semantic speed/jump change through the native lease."""
        if not self._native_movement_installed():
            return False
        self._movement_enabled = True
        if not self._write_native_movement_state(quiet=True):
            return False
        self._update_state({
            "speed": f"{self._speed:.2f}",
            "walk": f"{self._walk:.2f}",
            "jump": f"{self._jump:.2f}",
        })
        return True

    @Slot(float)
    def setFov(self, value: float):
        # Absolute degrees, applied LIVE as the slider moves - no Apply button.
        # Clamped to the range the game mod accepts. Each change is written to
        # the mod's state file (which the mod polls ~twice a second) and saved to
        # panel settings so it is remembered across restarts.
        self._fov = max(50.0, min(170.0, float(value)))
        self.movementChanged.emit()
        if self._native_movement_installed():
            self._write_native_movement_state(quiet=True)
        self._persist_fov_setting()

    def _persist_fov_setting(self) -> None:
        try:
            settings = read_kv(self.settings_file)
            settings["fovDegrees"] = f"{self._fov:.0f}"
            write_kv_atomic(self.settings_file, settings)
        except OSError:
            pass

    @Slot()
    def applyMovement(self):
        if not self._native_movement_installed():
            self._append_issue(
                "WARN",
                "movement",
                "Movement was not applied: the movement game mod is not installed or not switched on.",
            )
            return
        if not self._publish_live_movement():
            return
        self._append_issue(
            "INFO",
            "movement",
            f"Movement updated: speed {self._speed * 100:.0f}%, jump {self._jump * 100:.0f}%.",
        )

    @Slot()
    def createAudit(self):
        def work():
            return self._run_save_tool("Audit")

        def done(result):
            msg = f"Item report created: {result.get('safe','?')} safe, {result.get('caution','?')} caution, {result.get('missing','?')} missing."
            self._append_issue("OK", "save", msg)

        self._start_backend_job("save", "Item report", "save", work, done)

    @Slot()
    def createPolicyAudit(self):
        def work():
            return self._write_policy_audit_worker()

        def done(result):
            self._health_report = result.get("report", self._health_report)
            msg = result.get("message", "Policy audit created.")
            self.healthChanged.emit()
            self._append_issue(
                "OK", "support", "Item safety report created.",
                f"{msg} report: {result.get('report')} csv: {result.get('csv')}",
            )

        self._start_backend_job("support", "Item safety report", "support", work, done)

    @Slot(str)
    def sendBossCommand(self, command: str):
        self._send_boss_command((command or "").strip().lower())

    @Slot(str)
    def sendRetryPointCommand(self, command: str):
        self._send_retry_point_command((command or "").strip().lower())

    @Slot(bool)
    def setAlwaysOnTop(self, enabled: bool):
        self._always_on_top = bool(enabled)
        self._save_panel_setting("onTop", "1" if self._always_on_top else "0")
        self.settingsChanged.emit()
        self._append_issue("INFO", "panel", f"Always on top is {'on' if self._always_on_top else 'off'}.")

    @Slot(bool)
    def setPerformanceOverlayEnabled(self, enabled: bool):
        self._performance_overlay_enabled = bool(enabled)
        self._save_panel_setting("perfOverlayEnabled", "1" if self._performance_overlay_enabled else "0")
        self._game_telemetry.set_overlay_active(self._performance_overlay_enabled)
        self.settingsChanged.emit()
        self._append_issue(
            "INFO",
            "performance",
            f"In-game overlay is {'on' if self._performance_overlay_enabled else 'off'}.",
        )

    @Slot(str)
    def setPerformanceOverlaySize(self, size: str):
        size = normalize_overlay_size(size)
        if size == self._performance_overlay_size:
            return
        self._performance_overlay_size = size
        self._save_panel_setting("perfOverlaySize", size)
        self.settingsChanged.emit()
        self._append_issue("INFO", "performance", f"In-game overlay size: {size.capitalize()}.")

    @Slot(str, str)
    def _on_hardware_warning(self, level: str, detail: str):
        # Only reached when the user enabled temperature alerts; the telemetry
        # controller already limits it to one notice per ten minutes.
        self._append_issue("WARN", "hardware", f"{detail}.")

    @Slot(bool)
    def setHardwareAlertsEnabled(self, enabled: bool):
        enabled = bool(enabled)
        if enabled == self._hardware_alerts:
            return
        self._hardware_alerts = enabled
        self._save_panel_setting("hardwareAlerts", "1" if enabled else "0")
        self._game_telemetry.set_alerts_enabled(enabled)
        self.settingsChanged.emit()

    @Slot(bool)
    def setUpdateCheckEnabled(self, enabled: bool):
        enabled = bool(enabled) and bool(read_update_source(self.mod_root).version_url)
        if enabled == self._update_check_enabled:
            return
        self._update_check_enabled = enabled
        self._save_panel_setting("updateCheck", "1" if enabled else "0")
        if not enabled:
            self._update_version = ""
            self._update_url = ""
        self.updateChanged.emit()
        if enabled:
            self._maybe_check_for_update()

    @Slot()
    def openUpdateDownload(self):
        """Open the download page in the browser; nothing is downloaded here."""
        if not read_update_source(self.mod_root).version_url:
            return
        url = safe_download_url(self._update_url)
        if url:
            QDesktopServices.openUrl(QUrl(url))

    def _maybe_check_for_update(self) -> None:
        source = read_update_source(self.mod_root)
        if not source.version_url:
            self._update_check_enabled = False
            self._update_version = ""
            self._update_url = ""
            self.updateChanged.emit()
            return
        if not self._update_check_enabled or self._update_check_running or self._ui_fixture_active:
            return
        now = time.time()
        if not update_check_due(self._update_checked_at, now):
            return
        self._update_check_running = True
        # Counted when it starts, so a failed check also waits a day.
        self._update_checked_at = now
        self._save_panel_setting("updateCheckedAt", f"{now:.0f}")

        def run():
            info = None
            try:
                info = fetch_update_info(source.version_url)
            except Exception:  # noqa: BLE001 - an update check must always finish silently
                info = None
            finally:
                self._updateCheckDone.emit((info, source.download_page))

        threading.Thread(target=run, name="update-check", daemon=True).start()

    @Slot(object)
    def _on_update_check_done(self, result) -> None:
        self._update_check_running = False
        info, fallback_url = result
        source = read_update_source(self.mod_root)
        if not source.version_url:
            self._update_check_enabled = False
            self._update_version = ""
            self._update_url = ""
            self.updateChanged.emit()
            return
        if info is None or not self._update_check_enabled:
            return  # silent: offline, blocked or not published
        newer = version_is_newer(info.version, self._version)
        version = info.version if newer else ""
        url = (info.url or fallback_url) if newer else ""
        self._save_panel_setting("updateLatestVersion", version)
        self._save_panel_setting("updateLatestUrl", url)
        if (version, url) == (self._update_version, self._update_url):
            return
        self._update_version, self._update_url = version, url
        self.updateChanged.emit()
        if version:
            self._append_issue("INFO", "support", f"Version {version} is available.", toast=False)

    @Slot(str, bool)
    def setPerformanceOverlayMetric(self, metric: str, enabled: bool):
        metric = (metric or "").strip()
        if metric not in PERFORMANCE_OVERLAY_DEFAULTS or metric in HUD_DIAGNOSTIC_ONLY_METRICS:
            return
        self._performance_overlay_metrics[metric] = bool(enabled)
        self._save_panel_setting(f"perfMetric_{metric}", "1" if enabled else "0")
        self.settingsChanged.emit()

    @Slot(bool)
    def setStellarAccent(self, enabled: bool):
        self._stellar_accent = bool(enabled)
        self._save_panel_setting("stellarAccent", "1" if self._stellar_accent else "0")
        self.settingsChanged.emit()

    @Slot(bool)
    def setSupportVisible(self, visible: bool):
        """Support is on screen: count redraws and poll sensors for it."""
        if visible:
            self.refreshExternalFramePolicy()
        self._performance.setFrameCountingActive(bool(visible))
        self._game_telemetry.set_diagnostics_active(bool(visible))

    @Slot(str)
    def setActivePage(self, page: str):
        page = self._normalize_active_page(page)
        if page == self._active_page:
            return
        self._active_page = page
        self._save_panel_setting("activePage", page)
        self.settingsChanged.emit()
        if page == "items" and self._game_running_cached:
            # Take the Items lease now rather than on the next 250 ms tick.
            self._refresh_live_add_status()

    @Slot(str)
    def dockPanel(self, mode: str):
        mode = (mode or "center").strip().lower()
        ok = self._apply_dock_mode(mode, save=True)
        if ok:
            placed = {
                "left": "Panel moved to the left side.",
                "right": "Panel moved to the right side.",
                "center": "Panel centered.",
                "top": "Panel moved to the top.",
                "bottom": "Panel moved to the bottom.",
                "max": "Panel maximized.",
                "free": "Panel can now be moved freely.",
            }
            self._append_issue("OK", "panel", placed.get(mode, "Panel moved."), f"dock mode: {mode}")
        else:
            self._append_issue(
                "WARN", "panel", "The panel moves there in a moment.", f"dock request queued: {mode}"
            )

    @Slot()
    def applySavedDock(self):
        self._dock_restore_done = False
        self._dock_restore_attempts = 0
        self._schedule_saved_dock_apply()

    @Slot()
    def safeReset(self):
        self._speed = 1.0
        self._walk = 1.0
        self._jump = 1.0
        self._update_state({"speed": "1.00", "walk": "1.00", "jump": "1.00"})
        self.movementChanged.emit()
        self._append_issue("OK", "movement", "Safe Reset: movement speed and jump are back to 100%.")

    def enable_save_snapshots(self) -> None:
        """Turn automatic save snapshots on and take the panel-start one.

        From then on the save folder is also watched while the game runs:
        each time the game writes its saves a snapshot follows once the
        writes have settled (Save history on Support)."""
        self._save_snapshots_enabled = True
        self._save_watch.prime(default_save_root())
        self._save_watch_timer.start()
        self._request_save_snapshot("panel start")

    def _poll_save_writes(self) -> None:
        """Every 2 s: has the game written its saves (file sizes and times
        only, nothing is read)? Only while the game runs and for a minute
        after it closes; never while a restore runs."""
        if not self._save_snapshots_enabled or self._save_restore_job is not None:
            return
        now = time.monotonic()
        if self._game_running_cached:
            self._save_watch_until = now + SAVE_WATCH_AFTER_CLOSE_SEC
        elif now > self._save_watch_until:
            return
        if self._save_watch.poll(default_save_root()):
            self._request_save_snapshot(REASON_GAME_SAVED)

    def _request_save_snapshot(self, reason: str) -> None:
        """Copy the save folder (read-only) into a new verified snapshot.

        One snapshot runs at a time; a request that arrives meanwhile runs
        right after it, so a game start during the panel-start copy still
        gets its own check.
        """
        if not self._save_snapshots_enabled:
            return
        if self._save_snapshot_job is not None or self._save_restore_job is not None:
            self._save_snapshot_pending = reason
            return
        snapshot_root = self._save_snapshot_root
        self._save_snapshot_reason = reason

        def work():
            if threading.current_thread() is not threading.main_thread():
                QThread.currentThread().setPriority(QThread.Priority.LowestPriority)
            result = take_snapshot(default_save_root(), snapshot_root, reason=reason)
            snapshots = list_snapshots(snapshot_root)
            return result, save_snapshot_summary_text(snapshots), save_history_rows(snapshots)

        job = BackendJob("save-snapshot", work)
        job.signals.succeeded.connect(self._on_save_snapshot_done)
        job.signals.failed.connect(self._on_save_snapshot_failed)
        job.signals.finished.connect(self._on_save_snapshot_finished)
        self._save_snapshot_job = job
        self.saveSnapshotsChanged.emit()
        self._snapshot_pool.start(job)

    @Slot(str, object)
    def _on_save_snapshot_done(self, _key: str, payload) -> None:
        result, summary, rows = payload
        self._save_snapshot_summary = summary
        self._save_history_rows = rows
        self._save_snapshot_note = ""
        # Toasts use plain words; the snapshot name and sizes stay in the
        # technical log. A copy made because the game saved is routine: the
        # activity log only, no toast.
        automatic = self._save_snapshot_reason == REASON_GAME_SAVED
        if result.state == "created":
            self._append_issue(
                "OK", "save",
                "The game saved; a copy is in Save history." if automatic
                else "Your save was backed up and checked.",
                result.message, toast=not automatic,
            )
        elif result.state == "unchanged":
            self._append_issue(
                "INFO", "save", "Your save hasn't changed since the last backup.", result.message,
                toast=False,
            )
        else:
            self._append_issue("INFO", "save", "No save to back up yet.", result.message, toast=not automatic)
        if result.removed:
            self._append_issue(
                "INFO",
                "save",
                f"Older save copies were thinned out; {len(result.removed)} went, "
                "packed small, into the .recycle folder inside the save copies folder.",
                ", ".join(result.removed),
                toast=False,
            )

    @Slot(str, str)
    def _on_save_snapshot_failed(self, _key: str, message: str) -> None:
        self._save_snapshot_note = "The last backup failed. Your saves were not touched."
        if self._save_snapshot_reason == REASON_GAME_SAVED:
            # Tried again once the game's writes settle next time.
            self._save_watch.retry()
        self._append_issue(
            "WARN",
            "save",
            "Couldn't back up your save this time. Your saves were not touched.",
            f"save snapshot not made: {message}",
        )

    @Slot(str)
    def _on_save_snapshot_finished(self, _key: str) -> None:
        self._save_snapshot_job = None
        self.saveSnapshotsChanged.emit()
        restore, self._save_restore_pending = self._save_restore_pending, ""
        if restore:
            # A Restore pressed while this copy was being made goes first;
            # a queued copy runs after it (_on_save_restore_finished).
            self.restoreSaveSnapshot(restore)
            return
        pending, self._save_snapshot_pending = self._save_snapshot_pending, ""
        if pending:
            self._request_save_snapshot(pending)

    # Save history: putting a snapshot back (Support > Save history).

    @Property("QVariantList", notify=saveSnapshotsChanged)
    def saveHistory(self):
        """[{name, when, label}], newest first (services/save_snapshots.py)."""
        return list(self._save_history_rows)

    @Property(str, notify=saveSnapshotsChanged)
    def saveRestoreNote(self):
        return self._save_restore_note

    @Property(bool, notify=saveSnapshotsChanged)
    def saveRestoreBusy(self):
        return self._save_restore_job is not None or bool(self._save_restore_pending)

    @Property(bool, notify=saveSnapshotsChanged)
    def saveUndoAvailable(self):
        return bool(self._save_undo_name) and any(
            row.get("name") == self._save_undo_name for row in self._save_history_rows
        )

    @Slot(str)
    def restoreSaveSnapshot(self, name: str) -> None:
        """Put one save copy back, only while the game is closed. The save as
        it is now is copied first ("Before restore"), so it can be undone."""
        name = str(name or "")
        if not self._save_snapshots_enabled:
            self._append_issue(
                "INFO", "save", "Save history is off while the panel runs a check.",
                "restoreSaveSnapshot: save snapshots are disabled in this mode", toast=False,
            )
            return
        if self._game_running_cached:
            self._save_restore_note = "Close Stellar Blade first, then press Restore."
            self.saveSnapshotsChanged.emit()
            self._append_issue("WARN", "save", self._save_restore_note, f"restore {name} refused: the game is running")
            return
        if self._save_restore_job is not None:
            self._append_issue(
                "INFO", "save", "A restore is already running.", f"restore {name} not started: one is running",
            )
            return
        if self._save_snapshot_job is not None:
            # Runs as soon as the copy being made now is done.
            self._save_restore_pending = name
            self._save_restore_note = "Restoring…"
            self.saveSnapshotsChanged.emit()
            return
        snapshot_root = self._save_snapshot_root
        game_running = self._is_game_running
        undo = bool(self._save_undo_name) and name == self._save_undo_name

        def work():
            if threading.current_thread() is not threading.main_thread():
                QThread.currentThread().setPriority(QThread.Priority.LowestPriority)
            try:
                result = restore_snapshot(default_save_root(), snapshot_root, name, game_running=game_running)
            except (RestoreRefused, RestoreFailed) as exc:
                result = exc
            snapshots = list_snapshots(snapshot_root)
            return undo, result, save_snapshot_summary_text(snapshots), save_history_rows(snapshots)

        job = BackendJob("save-restore", work)
        job.signals.succeeded.connect(self._on_save_restore_done)
        job.signals.failed.connect(self._on_save_restore_failed)
        job.signals.finished.connect(self._on_save_restore_finished)
        self._save_restore_job = job
        self._save_restore_note = "Restoring…"
        self.saveSnapshotsChanged.emit()
        self._snapshot_pool.start(job)

    @Slot()
    def undoSaveRestore(self) -> None:
        """Undo the last restore: put back its "Before restore" copy."""
        if self._save_undo_name:
            self.restoreSaveSnapshot(self._save_undo_name)

    @Slot(str, object)
    def _on_save_restore_done(self, _key: str, payload) -> None:
        undo, result, summary, rows = payload
        self._save_snapshot_summary = summary
        self._save_history_rows = rows
        if isinstance(result, RestoreRefused):
            self._save_restore_note = str(result)
            self._append_issue("WARN", "save", str(result))
            return
        if isinstance(result, RestoreFailed):
            self._on_save_restore_stopped(result, undo)
            return
        # The restore's own writes are not a new game save.
        self._save_watch.prime(default_save_root())
        if undo:
            self._save_undo_name = ""
            self._save_restore_note = SAVE_UNDONE_TEXT
        else:
            self._save_undo_name = result.backup
            self._save_restore_note = RESTORED_TEXT
        detail = (
            f"restored save copy {result.restored} ({len(result.files)} files, dated now); "
            f"the save before it is copy {result.backup or 'none (the save folder was empty)'}"
        )
        self._append_issue("OK", "save", self._save_restore_note, detail)

    def _on_save_restore_stopped(self, failure: RestoreFailed, undo: bool) -> None:
        """A restore that started but could not finish: say what the save
        folder holds now, and how to get the save back when it is only
        partly restored (Undo restore = its "Before restore" copy)."""
        # The restore's own writes are not a new game save.
        self._save_watch.prime(default_save_root())
        if failure.outcome == RESTORE_PARTIAL:
            if failure.backup:
                self._save_undo_name = failure.backup
                note = SAVE_RESTORE_PARTIAL_TEXT
            else:
                note = SAVE_RESTORE_PARTIAL_NO_BACKUP_TEXT
            level = "ERROR"
        elif failure.outcome == RESTORE_ROLLED_BACK:
            note = SAVE_RESTORE_ROLLED_BACK_TEXT
            level = "WARN"
        else:
            note = SAVE_RESTORE_UNCHANGED_TEXT
            level = "WARN"
        self._save_restore_note = note
        detail = f"restore {'undo ' if undo else ''}{failure.outcome}: {failure}"
        if failure.backup:
            detail += f"; the save before it is copy {failure.backup}"
        self._append_issue(level, "save", note, detail)

    @Slot(str, str)
    def _on_save_restore_failed(self, _key: str, message: str) -> None:
        # An error restore_snapshot did not expect: what the save folder
        # holds is not known, so the note says how to get the save back.
        self._save_restore_note = SAVE_RESTORE_UNKNOWN_TEXT
        self._append_issue("ERROR", "save", self._save_restore_note, f"restore failed: {message}")

    @Slot(str)
    def _on_save_restore_finished(self, _key: str) -> None:
        self._save_restore_job = None
        self.saveSnapshotsChanged.emit()
        pending, self._save_snapshot_pending = self._save_snapshot_pending, ""
        if pending:
            self._request_save_snapshot(pending)

    @Slot()
    def openSaveSnapshotsFolder(self):
        try:
            self._save_snapshot_root.mkdir(parents=True, exist_ok=True)
            os.startfile(str(self._save_snapshot_root))
        except Exception as exc:
            self._append_issue("ERROR", "save", "Couldn't open the save copies folder.", str(exc))

    @Slot()
    def backupSaves(self):
        """Support > Back up now: one verified save snapshot now.

        The same read-only copy the panel makes on start, when the game
        starts and when the game saves (services/save_snapshots.py, older
        copies thinned out by age); it needs no external script, so it works
        in every install.
        """
        if not self._save_snapshots_enabled:
            self._append_issue(
                "INFO", "save", "Save backups are off while the panel runs a check.",
                "backupSaves: save snapshots are disabled in this mode", toast=False,
            )
            return
        self._request_save_snapshot("backup button")

    @Property("QVariantList", notify=oldUe4ssChanged)
    def oldUe4ssFiles(self):
        """Old UE4SS files directly in Binaries/Win64 (services/old_ue4ss_files.py)."""
        return list(self._old_ue4ss_files)

    @Slot()
    def refreshOldUe4ssFiles(self):
        names = [path.name for path in find_old_ue4ss_files(self.win64_dir)]
        if names != self._old_ue4ss_files:
            self._old_ue4ss_files = names
            self.oldUe4ssChanged.emit()

    @Slot()
    def moveOldUe4ssFiles(self):
        """Support > Move old files to a backup folder: a dated folder next to
        them in Binaries/Win64. Nothing is deleted; a file that can't move
        puts the others back.
        """
        if self._game_running:
            self._append_issue(
                "WARN", "support", "Close the game first, then move the old files.",
                "old UE4SS files not moved: the game is running",
            )
            return
        try:
            result = move_old_ue4ss_files(self.win64_dir)
        except FileNotFoundError:
            self._append_issue("INFO", "support", "The old mod loader files are already gone.", str(self.win64_dir))
        except OSError as exc:
            self._append_issue(
                "ERROR", "support", "Couldn't move the old mod loader files. Close the game and try again.",
                f"old UE4SS files not moved from {self.win64_dir}: {exc}",
            )
        else:
            self._append_issue(
                "OK", "support", "Moved the old mod loader files to a backup folder.",
                f"{old_ue4ss_text(list(result.moved))} -> {result.backup_dir}",
            )
        self.refreshOldUe4ssFiles()

    @Slot()
    def createBugReport(self):
        """Support > Create Bug Report: one privacy-safe zip (services/bug_report.py)
        in the panel's own reports folder, then File Explorer with it selected."""
        try:
            # Sensors are idle while the game is closed; read them once so the
            # report never carries values from an earlier session.
            self._game_telemetry.poll_once()
            self._performance.write_snapshot(
                self.mod_root / "performance_diagnostics.txt",
                ["", *self._game_telemetry.summary_lines()],
            )
        except OSError as exc:
            self._append_issue(
                "WARN", "support", "The bug report won't include performance numbers this time.",
                f"could not write performance snapshot: {exc}",
            )
        frozen_exe = Path(sys.executable) if getattr(sys, "frozen", False) else None
        sources = BugReportSources(
            mod_root=self.mod_root,
            reports_dir=self.support_reports_dir,
            panel_version=self._version,
            activity_log=self.issue_log_file,
            game_exe=self.game_exe,
            app_manifest=self.app_manifest_file,
            paks_mods_dir=self.paks_mods_dir,
            crash_root=default_crash_root(),
            panel_exe=frozen_exe or self.mod_root / "Stellar Blade Control Panel.exe",
            extra_texts={"version_details.txt": "\n".join(self._version_detail_lines()) + "\n"},
        )

        def work():
            return {"message": "Bug report created.", "path": str(build_bug_report(sources))}

        def done(result):
            path = Path(result["path"])
            self._last_bug_report = path.name
            self.bugReportChanged.emit()
            self._append_issue(
                "OK", "support", f"Bug report saved. {BUG_REPORT_SEND_HINT}", f"report: {path}",
            )
            try:
                reveal_in_explorer(path)
            except OSError as exc:
                self._append_issue(
                    "WARN", "support", "Couldn't open File Explorer. Click Open Reports to find the file.",
                    f"explorer /select failed: {exc}",
                )

        self._start_backend_job("support", "Bug report", "support", work, done)

    @Property(str, notify=bugReportChanged)
    def lastBugReport(self):
        return self._last_bug_report

    @Slot()
    def openReportsFolder(self):
        try:
            self.support_reports_dir.mkdir(parents=True, exist_ok=True)
            os.startfile(str(self.support_reports_dir))
            self._append_issue("INFO", "support", "Opened the reports folder.", str(self.support_reports_dir))
        except Exception as exc:
            self._append_issue("ERROR", "support", "Couldn't open the reports folder.", str(exc))

    def _version_detail_lines(self) -> list[str]:
        return [
            f"Panel version: {self._version}",
            f"Game running: {self._game_running}",
            f"Mod connected: {self._mod_connected}",
            f"Spawn API: {self._spawn_api or 'unknown'}",
            f"Boss ready: {self._boss_ready}",
            f"Boss status: {self._boss_status_text}",
            f"Instant Boss Restart: {self._boss_technical_diagnostics}",
            *(
                f"Game mod {key}: {entry.get('label')} "
                f"(reason: {self._native_status_reasons.get(key, 'not checked yet')})"
                for key, entry in self._native_status.items()
            ),
            f"Backend runtime: {self.backendRuntime}",
            f"Backend busy: {self.backendBusyText}",
            f"Last backend job: {self._last_job_summary}",
            f"Panel renderer: {self.panelRendererTechnicalSummary}",
            f"Panel isolation: {self.panelGraphicsIsolationTechnicalSummary}",
            f"External frame policy: {self.externalFramePolicySummary}",
            *self._performance.summary_lines(),
            *self._game_telemetry.summary_lines(),
        ]

    @Slot()
    def copyVersionDetails(self):
        text = "\n".join(self._version_detail_lines())
        clip = QGuiApplication.clipboard()
        if clip is not None:
            clip.setText(text)
        self._append_issue("INFO", "support", "Version details copied to clipboard.")


# QML problems that load "successfully" but are still bugs.
#
# A missing type or syntax error empties rootObjects() and is already caught.
# These are not: the panel comes up looking fine while a binding silently
# resolves to null, loops forever, or never assigns. Two such bugs had been
# shipping unnoticed (a binding loop on every section label, and a null deref on
# the Support page) and neither showed up in a fully green test run.
_SEVERE_QML_WARNINGS = (
    "binding loop",                    # property depends on itself; burns CPU
    "is not defined",                  # typo'd id or property
    "unable to assign",                # type mismatch on a binding
    "cannot assign",
    "property value set multiple times",
    "unavailable",                     # component failed to resolve
    "does not have a property",
    "invalid property name",
    "cannot read property",            # null deref, e.g. a shadowed appBackend
)


def panel_ui_font() -> QFont:
    """The application font every QML Text inherits.

    Full hinting makes DirectWrite rasterise with GDI-classic ClearType: stems,
    x-height and baseline land on whole pixels. Qt already chooses that at
    100 % scaling, but at 150 % its default is vertical-only hinting, which
    leaves stems straddling pixels. QML sets the same value in
    Tokens.textHinting for controls that carry their own font.
    """
    font = QFont("Segoe UI Variable Text", 10)
    font.setHintingPreference(QFont.HintingPreference.PreferFullHinting)
    return font


def _severe_qml_warnings(lines: list[str]) -> list[str]:
    """Filter collected QML warnings down to ones that mean a real defect."""
    return [
        line for line in lines
        if any(pattern in line.lower() for pattern in _SEVERE_QML_WARNINGS)
    ]


def _start_panel_log(automation_mode: bool) -> None:
    """logs/panel.log + logs/panel-crash.txt, headed by the build id (A6)."""
    mod_root, resource_root = resolve_runtime_paths()

    def _first_line(*paths: Path) -> str:
        for path in paths:
            try:
                text = path.read_text(encoding="utf-8").strip()
            except OSError:
                continue
            if text:
                return text.splitlines()[0]
        return "unknown"

    version = _first_line(mod_root / "VERSION")
    ui_revision = _first_line(resource_root / "UI_REVISION", mod_root / "QtPanel" / "UI_REVISION")
    logger = install_panel_logging(mod_root, version, ui_revision)
    if automation_mode:
        logger.info("Automation run: %s", " ".join(sys.argv[1:]))


UI_ACTION_FLAGS = ("--hover", "--press", "--click", "--open", "--tab", "--toast")


def _ui_actions(argv: list[str]) -> list[tuple[str, str]]:
    """Screenshot automation: the state-matrix actions in command-line order,
    e.g. ``--click topBarGameMenu --hover topBarRefresh``. OBJNAME may carry
    ``@fx,fy`` (a point inside the item as fractions of its size)."""
    actions = []
    for index, flag in enumerate(argv[:-1]):
        if flag in UI_ACTION_FLAGS:
            actions.append((flag, argv[index + 1]))
    return actions


def _schedule_ui_actions(root, backend) -> None:
    """Run the --hover/--press/--click/--open/--tab/--toast actions on the
    real window, 350 ms apart from 1.2 s, as synthetic input events sent to
    the window (QtTest is not in the packaged build): the pointer on the
    desktop does not move, nothing is sent to the game and nothing is saved
    (a click only opens menus and dialogs in the capture scripts)."""
    from PySide6.QtCore import QEvent, QMetaObject, QPointF, Qt
    from PySide6.QtGui import QKeyEvent, QMouseEvent

    def mouse(kind, point: QPointF, button, buttons) -> None:
        global_point = QPointF(root.mapToGlobal(point.toPoint()))
        QGuiApplication.sendEvent(
            root, QMouseEvent(kind, point, global_point, button, buttons, Qt.KeyboardModifier.NoModifier)
        )

    def find(spec: str, popup: bool = False):
        name, _, where = spec.partition("@")
        fx, fy = (float(part) for part in where.split(",")) if where else (0.5, 0.5)
        for item in root.findChildren(QObject, name):
            # A Popup (menus, dialogs) is not an item: --open finds it hidden.
            if popup or (hasattr(item, "isVisible") and item.isVisible()):
                return item, fx, fy
        # Rows a Repeater made (Save history's Restore buttons) are items of
        # the scene, not QObject children of the window.
        stack = [root.contentItem()] if hasattr(root, "contentItem") else []
        while stack:
            item = stack.pop(0)
            if item.objectName() == name and item.isVisible():
                return item, fx, fy
            stack.extend(item.childItems())
        print(f"screenshot action: {name} not found", file=sys.stderr)
        return None, fx, fy

    def run(flag: str, value: str) -> None:
        if flag == "--toast":
            message, _, level = value.partition("|")
            backend.operationNotice.emit(message, level or "OK")
            return
        if flag == "--tab":
            for _ in range(max(1, int(value))):
                for kind in (QEvent.Type.KeyPress, QEvent.Type.KeyRelease):
                    QGuiApplication.sendEvent(root, QKeyEvent(kind, Qt.Key.Key_Tab, Qt.KeyboardModifier.NoModifier))
            return
        item, fx, fy = find(value, popup=flag == "--open")
        if item is None:
            return
        if flag == "--open":
            QMetaObject.invokeMethod(item, "open")
            return
        scene = item.mapToScene(QPointF(item.width() * fx, item.height() * fy))
        point = QPointF(round(scene.x()), round(scene.y()))
        left, none = Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton
        mouse(QEvent.Type.MouseMove, point, none, none)
        if flag in ("--press", "--click"):
            mouse(QEvent.Type.MouseButtonPress, point, left, left)
        if flag == "--click":
            mouse(QEvent.Type.MouseButtonRelease, point, left, none)

    for step, (flag, value) in enumerate(_ui_actions(sys.argv)):
        QTimer.singleShot(1200 + 350 * step, lambda flag=flag, value=value: run(flag, value))


def main() -> int:
    automation_mode = any(
        flag in sys.argv
        for flag in ("--smoke", "--screenshot", "--pace-probe")
    )
    mod_root, _resource_root = resolve_runtime_paths()
    if not automation_mode and "--launch-diagnostic" not in sys.argv:
        if not try_acquire_panel_mutex():
            focus_existing_panel(mod_root)
            return 0

    _start_panel_log(automation_mode)
    set_windows_app_user_model_id()
    requested_renderer = configure_qt_renderer()

    os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Material")
    os.environ.setdefault("QT_QUICK_CONTROLS_MATERIAL_VARIANT", "Dense")
    os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")

    fmt = QSurfaceFormat()
    fmt.setSamples(4)
    # Pace only this utility window to the display.  Stellar Blade remains
    # independently configured for VSync Off and an unlimited frame rate.
    fmt.setSwapInterval(1)
    QSurfaceFormat.setDefaultFormat(fmt)
    QQuickWindow.setDefaultAlphaBuffer(True)
    QQuickWindow.setTextRenderType(QQuickWindow.NativeTextRendering)

    app = QGuiApplication(sys.argv)
    app.setFont(panel_ui_font())
    app.setApplicationName(APP_DISPLAY_NAME)
    app.setOrganizationName("SBCheatGUI")

    mod_root, resource_root = resolve_runtime_paths()
    icon_file, icon_path = load_app_icon(mod_root, resource_root)
    if icon_file is not None:
        app.setWindowIcon(icon_file)

    backend = Backend(mod_root, requested_renderer)
    if automation_mode:
        backend.use_scratch_issue_log()
    if not automation_mode:
        app.aboutToQuit.connect(backend._persist_window_on_close)
        app.aboutToQuit.connect(backend.gameTelemetry.shutdown)
        # Release the Items lease at once instead of letting it run out.
        app.aboutToQuit.connect(backend._remove_live_add_lease)
        # The same for the Retry Point watch lease (area checks stop at once).
        app.aboutToQuit.connect(backend._remove_retry_point_watch)

    if "--launch-diagnostic" in sys.argv:
        result = backend._launch_game_worker()
        print("OK" if result.get("ok") else "FAIL")
        print(result.get("message", ""))
        for attempt in result.get("attempts", []):
            print(f"- {attempt}")
        if result.get("report"):
            print(f"Report: {result.get('report')}")
        return 0 if result.get("ok") else 2

    if not automation_mode:
        # A verified read-only copy of the saves now, and at every game start.
        backend.enable_save_snapshots()
        # Reopen where it was closed, and remember moves, resizes and the close.
        backend.enable_window_memory()

    QQmlEngine.setObjectOwnership(backend, QQmlEngine.CppOwnership)
    engine = QQmlApplicationEngine()
    automation_mode = any(
        flag in sys.argv
        for flag in ("--smoke", "--screenshot", "--pace-probe")
    )
    qml_warnings: list[str] = []

    def _on_qml_warnings(warnings) -> None:
        for warning in warnings:
            line = str(warning.toString())
            qml_warnings.append(line)
            if not automation_mode:
                print(line, file=sys.stderr)

    engine.warnings.connect(_on_qml_warnings)
    engine.rootContext().setContextProperty("backend", backend)
    qml_path = resolve_qml_path(mod_root, resource_root)
    engine.addImportPath(str(qml_path.parent))
    write_qml_source_marker(mod_root, resource_root, qml_path)
    engine.load(QUrl.fromLocalFile(str(qml_path)))
    if not engine.rootObjects():
        for line in qml_warnings:
            print(line, file=sys.stderr)
        return 1
    write_panel_running_version(mod_root, backend.version)

    roots = engine.rootObjects()
    if roots:
        backend.attach_window(roots[0])
        if automation_mode and "--window-rect" in sys.argv:
                                                                            
                                                                          
                                                                        
                                                         
            try:
                index = sys.argv.index("--window-rect")
                x, y, w, h = (int(part) for part in sys.argv[index + 1].split(","))
                place_window_exactly(roots[0], QRect(x, y, w, h))
            except (ValueError, IndexError) as exc:
                print(f"--window-rect ignored: {exc}", file=sys.stderr)

        # main.qml accepts the close event and calls Qt.quit() explicitly. Do
        # not also connect QQuickWindow.closing to Python: PySide cannot convert
        # its private QQuickCloseEvent pointer and logs a shutdown TypeError.
        # The explicit QML quit still closes the metrics overlay and reaches
        # aboutToQuit for normal geometry/telemetry cleanup.

        def _record_renderer() -> None:
            try:
                actual = roots[0].rendererInterface().graphicsApi().name
            except Exception:
                actual = "unknown"
            backend.set_renderer_actual(actual)
            remaining_hooks = loaded_graphics_hook_modules()
            backend.set_remaining_graphics_hooks(remaining_hooks)
            diagnostic = mod_root / "panel_renderer_status.txt"
            try:
                diagnostic.write_text(
                    "\n".join([
                        f"requested={requested_renderer}",
                        f"actual={actual}",
                        "render_loop=" + os.environ.get("QSG_RENDER_LOOP", "automatic"),
                        "renderer_mode=" + ("compatibility" if requested_renderer == "software" else "hardware"),
                        "renderer_selection_reason=" + _RENDERER_SELECTION_REASON.replace("\n", " "),
                        "safe_mode_reason=" + (_RENDERER_SAFE_MODE_REASON.replace("\n", " ") or "none"),
                        "panel_frame_pacing=" + (
                            "vsync"
                            if os.environ.get("QSG_RENDER_LOOP", "") == "threaded"
                            else "qt-animation-timer"
                        ),
                        "app_fps_cap=" + PANEL_FRAME_CAP_TEXT,
                        "fixed_animation_step=none",
                        "extension_point_mitigation=" + _EXTENSION_POINT_MITIGATION_STATUS,
                        "graphics_layer_opt_outs=active",
                        "isolated_layers=" + ",".join(_DISABLED_GRAPHICS_HOOKS),
                        "remaining_hook_modules=" + (",".join(remaining_hooks) or "none"),
                        f"pid={os.getpid()}",
                    ]) + "\n",
                    encoding="utf-8",
                )
            except OSError:
                pass
            if automation_mode:
                print(f"Qt renderer requested={requested_renderer} actual={actual}")

        QTimer.singleShot(350, _record_renderer)

    if icon_file is not None:
        for root in roots:
            if hasattr(root, "setIcon"):
                root.setIcon(icon_file)

    if icon_path is not None and roots:
        root = roots[0]

        def _apply_icons() -> None:
            if hasattr(root, "setIcon") and icon_file is not None:
                root.setIcon(icon_file)
            apply_native_windows_icons(root, icon_path)

        QTimer.singleShot(0, _apply_icons)
        QTimer.singleShot(250, _apply_icons)

    def _arg_value(flag: str, default: str = "") -> str:
        try:
            index = sys.argv.index(flag)
            value = sys.argv[index + 1]
            if value.startswith("--"):
                return default
            return value
        except Exception:
            return default

    pace_probe_path = _arg_value("--pace-probe")
    if pace_probe_path and roots:
        # Frame pacing measurement (automation only): the real window runs a
        # fixed script (Gameplay at rest, page switches, wheel
        # glides, hover, Support at rest) and every frame swap is timed on the
        # render thread. See infrastructure/pace_probe.py.
        from infrastructure.pace_probe import PaceProbe

        roots[0].setProperty("activePage", "gameplay")
        probe = PaceProbe(app, roots[0], backend, pace_probe_path)
        QTimer.singleShot(250, probe.start)
        return app.exec()

    screenshot_path = _arg_value("--screenshot")
    if screenshot_path and roots:
        root = roots[0]
        page = _arg_value("--page", "gameplay")
        selected_alias = _arg_value("--select")
        theme = _arg_value("--theme")

        def _items_page_flick():
            """The Items page's own scroll view (every page has one, so the
            first "pageScrollFlick" found may belong to another page)."""
            item = root.findChild(QObject, "itemsCatalogList")
            while item is not None:
                if item.objectName() == "pageScrollFlick":
                    return item
                item = item.parentItem() if hasattr(item, "parentItem") else None
            return root.findChild(QObject, "pageScrollFlick")

        def _drive_catalog(steps: dict[str, str], attempt: int = 0) -> None:
            """Screenshot automation only: search, filter and scroll the item catalog."""
            from PySide6.QtCore import QMetaObject, QPointF

            catalog = root.findChild(QObject, "itemsCatalogList")
            search = root.findChild(QObject, "itemsSearchField")
            category_box = root.findChild(QObject, "itemsCategoryBox")
            if catalog is None or search is None or category_box is None:
                if attempt < 60:
                    QTimer.singleShot(100, lambda: _drive_catalog(steps, attempt + 1))
                else:
                    print("screenshot setup warning: item catalog not found", file=sys.stderr)
                return
            category = steps.get("category") or ""
            if category:
                categories = [str(value) for value in backend.categories]
                if category in categories:
                    category_box.setProperty("currentIndex", categories.index(category))
            # Bring the whole catalog on screen, clear of the bottom notices.
            flick = _items_page_flick()
            if flick is not None:
                content = flick.property("contentItem")
                top = catalog.mapToItem(content, QPointF(0, 0)).y()
                span = float(flick.property("contentHeight")) - float(flick.property("height"))
                wanted = top + float(catalog.property("height")) + 140 - float(flick.property("height"))
                flick.setProperty("contentY", max(0.0, min(max(0.0, span), wanted)))
            if steps.get("search"):
                search.setProperty("text", steps["search"])
            if steps.get("focus"):
                # The typing state: the field keeps focus and its caret.
                root.requestActivate()
                QMetaObject.invokeMethod(search, "forceActiveFocus")
            if steps.get("scroll"):
                def _scroll() -> None:
                    from PySide6.QtCore import Q_ARG, QMetaObject

                    fraction = max(0.0, min(1.0, float(steps["scroll"])))
                    count = int(catalog.property("count") or 0)
                    if count <= 0:
                        return
                    # ListView.Beginning (0): land on a row boundary so the
                    # capture shows whole rows.
                    index = int(round(fraction * (count - 1)))
                    QMetaObject.invokeMethod(
                        catalog, "positionViewAtIndex", Q_ARG(int, index), Q_ARG(int, 0)
                    )
                QTimer.singleShot(450, _scroll)

        def _capture_screenshot() -> None:
            try:
                capture_width = _arg_value("--width")
                capture_height = _arg_value("--height")
                if capture_width:
                    root.setWidth(max(1, int(capture_width)))
                if capture_height:
                    root.setHeight(max(1, int(capture_height)))
                if page:
                    root.setProperty("activePage", page)
                if theme:
                    root.setProperty("activeTheme", int(theme))
                # Items & Money review captures: chip states from a fixture
                # (no game, nothing written anywhere), opt-in groups for this
                # run only, and a chosen currency.
                ui_fixture_path = _arg_value("--ui-fixture")
                if ui_fixture_path:
                    backend._apply_ui_fixture(
                        json.loads(Path(ui_fixture_path).read_text(encoding="utf-8"))
                    )
                fixture_path = _arg_value("--items-fixture")
                if fixture_path:
                    backend._apply_items_fixture(
                        json.loads(Path(fixture_path).read_text(encoding="utf-8"))
                    )
                opt_ins = [key for key in _arg_value("--opt-in").split(",") if key]
                if opt_ins:
                    backend._set_items_optins_for_run(opt_ins)
                money_currency = _arg_value("--money-currency")
                if money_currency:
                    backend.setMoneyCurrency(money_currency)
                money_confirm = _arg_value("--money-confirm")
                if money_confirm:
                    # The large-amount question as a click would leave it
                    # (once the page exists); nothing is sent.
                    def _stage_money_confirm(amount: int = int(money_confirm)) -> None:
                        money_box = root.findChild(QObject, "itemsMoneyBox")
                        if money_box is not None:
                            money_box.setProperty("value", amount)
                        backend._stage_money_confirm_for_run(amount)
                    # Again later: the page may still be loading at first.
                    QTimer.singleShot(900, _stage_money_confirm)
                    QTimer.singleShot(2000, _stage_money_confirm)
                if selected_alias:
                    row = backend._catalog_row_for_alias(selected_alias) or {}
                    backend.selectItem(selected_alias, str(row.get("name") or selected_alias))
                catalog_steps = {
                    "search": _arg_value("--catalog-search"),
                    "category": _arg_value("--catalog-category"),
                    "scroll": _arg_value("--catalog-scroll"),
                    "focus": "1" if "--catalog-focus" in sys.argv else "",
                }
                if any(catalog_steps.values()):
                    QTimer.singleShot(150, lambda: _drive_catalog(catalog_steps))
                page_scroll = _arg_value("--page-scroll")
                if page_scroll:
                    # Review captures: scroll the page itself (0 = top, 1 = end)
                    # after the catalog steps have placed it.
                    def _scroll_page() -> None:
                        flick = _items_page_flick() if page == "items" else None
                        if flick is None:
                            # The active page's own scroll view: every page
                            # has one, so pick the one whose PageScroll
                            # carries this pageId.
                            for candidate in root.findChildren(QObject, "pageScrollFlick"):
                                owner = candidate.parentItem() if hasattr(candidate, "parentItem") else None
                                if owner is not None and owner.property("pageId") == page:
                                    flick = candidate
                                    break
                        if flick is None:
                            flick = root.findChild(QObject, "pageScrollFlick")
                        if flick is None:
                            return
                        span = max(0.0, float(flick.property("contentHeight")) - float(flick.property("height")))
                        flick.setProperty("contentY", span * max(0.0, min(1.0, float(page_scroll))))
                    # Again later: a busy machine may still be laying the
                    # page out at the first try.
                    QTimer.singleShot(900, _scroll_page)
                    QTimer.singleShot(2000, _scroll_page)
                if "--expand-all" in sys.argv:
                    # Review captures: open every collapsible card and every
                    # "show more" group so one image shows the whole page.
                    def _expand_all() -> None:
                        for item in root.findChildren(QObject):
                            try:
                                if item.property("collapsible") is True:
                                    item.setProperty("expanded", True)
                                if item.property("showMoreMetrics") is False:
                                    item.setProperty("showMoreMetrics", True)
                            except Exception:
                                pass
                    QTimer.singleShot(600, _expand_all)
                movement = _arg_value("--movement")
                if movement:
                    # Review captures: speed %, jump % and field of view shown
                    # on Gameplay, in memory only (nothing is sent or saved).
                    speed, jump, fov = (float(part) for part in movement.split(","))
                    backend._speed, backend._jump, backend._fov = speed / 100.0, jump / 100.0, fov
                    backend.movementChanged.emit()
                _schedule_ui_actions(root, backend)
            except Exception as exc:
                print(f"screenshot setup warning: {exc}", file=sys.stderr)

            def _save_screenshot() -> None:
                try:
                    path = Path(screenshot_path)
                    path.parent.mkdir(parents=True, exist_ok=True)
                    image = root.grabWindow()
                    if not image.save(str(path)):
                        print(f"screenshot save failed: {path}", file=sys.stderr)
                        app.exit(2)
                        return
                    print(str(path))
                    app.quit()
                except Exception as exc:
                    print(f"screenshot failed: {exc}", file=sys.stderr)
                    app.exit(2)

            QTimer.singleShot(int(_arg_value("--holdms", "850")), _save_screenshot)

        QTimer.singleShot(250, _capture_screenshot)
        return app.exec()

    if "--smoke" in sys.argv:
        QTimer.singleShot(1300, app.quit)
        code = app.exec()
        # The engine can load a tree that still misbehaves. Fail on those too,
        # otherwise a silent binding bug ships looking like a clean pass.
        severe = _severe_qml_warnings(qml_warnings)
        if severe and code == 0:
            print("SMOKE FAILED - QML problems detected:", file=sys.stderr)
            for line in severe:
                print(f"  {line}", file=sys.stderr)
            return 3
        return code
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
