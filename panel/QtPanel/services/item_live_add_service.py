"""Items & Money through the audited Live Add route (v3 and v4).

Ported from the earlier Items service of this panel
(item_live_add_service.py) and extended for SBLiveAddNative v0.3.0
and v0.3.1 (carry-limit check, longer verification, measured status), 0.4.0
(the Items lease), 0.5.0 (the v0.5 catalog, Gold and the probe) and 0.5.1
(refuses items the game spends on an upgrade by itself, and adds to an owned
one-per-bag-slot item only where that was proven).

The route has three parts, all of which must be the exact approved files:

* ``Mods/SBLiveAddBridge/Scripts/main.lua`` - the Lua bridge. It reads one
  request from ``gui_state.txt`` (``spawn*`` keys), checks it against its own
  embedded allowlist and forwards it to the native. It writes
  ``sbcheat_heartbeat.txt`` and ``item_spawn_status.txt``.
* ``Mods/SBLiveAddNative/dlls/main.dll`` - the dedicated native. It gates on
  the exact game build, runs a read-only self-check on first use and calls the
  game's own ServerItemBucketAdd once per request on the certified GameThread.
  It writes ``Mods/SBLiveAddNative/live_add_native_status.txt``.
* Both ``enabled.txt`` markers.

Two wire protocols exist, and the bridge and the native must speak the same
one (``LIVE_ADD_NATIVE_BUILDS`` / ``LIVE_ADD_BRIDGE_BUILDS``):

* ``native-live-add-v3``: bridge v3 with SBLiveAddNative 0.3.0, 0.3.1 or
  0.4.0. Only the bridge's 23 embedded items, 1-99 per add, no money.
* ``native-live-add-v4``: bridge v4 with SBLiveAddNative 0.5.0 or 0.5.1. The v0.5
  catalog's addable rows with per-group limits (Gold 1-1,000,000 per add and
  never above 100,000,000), the read-only probe (services/item_probe.py) and
  the watched side effects.

Every direct wallet, inventory or save write stays blocked on both: money is
only ever added through the game's own add, like any item.

Player copy follows the Items & Money rules: Ready / Waiting for game /
Adding / Added (plus Off, Needs update and Couldn't start safely). One add's
result that was refused reads "Couldn't add safely: ...".
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import time
from typing import Iterable, Mapping

from services.native_status import (
    GAME_UPDATED_TEXT,
    NATIVE_NEEDS_UPDATE,
    NATIVE_OFF,
    NATIVE_READY,
    NATIVE_UNSAFE,
    NATIVE_WAITING,
    file_sha256,
)


# The Live Add v3 wire protocol (bridge v3, SBLiveAddNative 0.3.x/0.4.0).
LIVE_ADD_API = "native-live-add-v3"
# The Live Add v4 wire protocol (bridge v4, SBLiveAddNative 0.5.0/0.5.1): the same
# files and keys as v3, plus the v0.5 limits, the probe and the watch.
LIVE_ADD_API_V4 = "native-live-add-v4"
LIVE_ADD_PROTOCOLS = frozenset({LIVE_ADD_API, LIVE_ADD_API_V4})
TRUSTED_BRIDGE_ID = "trusted-live-add-only"
LIVE_ADD_NATIVE_MODULE = "SBLiveAddNative"
LIVE_ADD_NATIVE_VERSION = "0.5.1"
# Each trusted native reports one of these versions. The installed v0.5.0 and
# v0.4.0 (and v0.3.1/v0.3.0) stay accepted so a partial install never reads as
# untrusted; the status version must still be the installed DLL's own
# (LIVE_ADD_NATIVE_BUILDS).
LIVE_ADD_NATIVE_VERSIONS = frozenset({"0.3.0", "0.3.1", "0.4.0", "0.5.0", LIVE_ADD_NATIVE_VERSION})
# The (protocol, version) pairs a trusted native's status may report.
LIVE_ADD_STATUS_PAIRS = frozenset({
    (LIVE_ADD_API, "0.3.0"),
    (LIVE_ADD_API, "0.3.1"),
    (LIVE_ADD_API, "0.4.0"),
    (LIVE_ADD_API_V4, "0.5.0"),
    (LIVE_ADD_API_V4, LIVE_ADD_NATIVE_VERSION),
})
# SBLiveAddNative 0.4.0 (A13) and 0.5.0 refresh the inventory - and run their
# first-use self-check - only while the panel holds this Items lease, which the
# panel renews while the Items & Money page is open or an add is in flight.
# Exactly three lines, no blank line: protocol (the installed native's own:
# v3 for 0.4.0, v4 for 0.5.0), panel_pid, issued_ms (Unix ms). The native
# accepts it for 10 s while this panel process is alive.
LIVE_ADD_LEASE_FILE = "live_add_native_lease.txt"
LIVE_ADD_LEASE_RENEW_SEC = 2.0
# The native honours a lease for 10 s; a pause in renewing shorter than this
# (leaving the page and coming back) never let it lapse.
LIVE_ADD_LEASE_STALE_GAP_SEC = 8.0
# A new lease needs about a second before the native has refreshed and the
# bridge reports ready; until then the card says "Connecting" instead of
# flashing "Waiting for game".
LIVE_ADD_LEASE_SETTLE_SEC = 3.0
# Panel-side lease states passed to evaluate_live_add().
LIVE_ADD_LEASE_OFF = "off"
LIVE_ADD_LEASE_SETTLING = "settling"
LIVE_ADD_LEASE_HELD = "held"
LIVE_ADD_ACTION_LEASE_SEC = 2.0
# live_add_native_status.txt is rewritten every 100 ms while the game runs.
LIVE_ADD_NATIVE_STATUS_MAX_AGE_SEC = 3.0
LIVE_ADD_NATIVE_STATUS_FILE = "live_add_native_status.txt"

                                                                       
         
                                                                   
                                          
                                                              
                                                                              
                                                                            
                                                                        
LIVE_ADD_BRIDGE_BUILDS: dict[str, str] = {
    "C7CA14FCCC331BAC510517490754113E4666A6EA5A88E6081A894CCC146DE94C": LIVE_ADD_API,
    "B8C9F17BB6130DC12B6E94D70BAACA44239F7436AACA678CC46617DE09C127FF": LIVE_ADD_API_V4,
}
TRUSTED_LIVE_ADD_SCRIPT_SHA256 = frozenset(LIVE_ADD_BRIDGE_BUILDS)
                                                                               
                                                                            
                                                                             
                                                                               
                                                                             
                                                                           
                                                                            
                       
                                                                          
                                                                          
                                                                           
                                       
                                                                              
                                                                       
                                                                              
                                                                              
                                                                        
                                                                   
                                                                             
            
                                                                          
                                                                            
                                                                         
                                                                             
                                                                            
                                                                          
                                                                         
                                       
                                                                          
                                                                          
                                                                           
                                                                            
                                                                         
                                                                           
                                                                           
                                                                          
                                                                           
                                                         
                                                                           
                                                 
LIVE_ADD_NATIVE_BUILDS: dict[str, tuple[str, str]] = {
    "3DF532FEDF404C86378592CCDEAF1B8E9E2C0AC2E5CFBF8A05BF195FDEC197CF": ("0.5.1", LIVE_ADD_API_V4),
    "E6D54C4A5FAED9B42657A7901142763212B1323BF994BFB10C84413B49D4D683": ("0.5.0", LIVE_ADD_API_V4),
    "BA42D07600DDE73022F92AE0660BDF5410C91BA7D0E8BA178D7BC8D9194037BD": ("0.4.0", LIVE_ADD_API),
    "A934279BCB65BB93DA9FA3621A4E764B23B7787993CC222D0A4C5590F9A65E2B": ("0.3.1", LIVE_ADD_API),
    "12A82F5D01F7A296EB4B48F08A649887FEE1738099327F98C78EBA2B47FC44B2": ("0.3.0", LIVE_ADD_API),
}
TRUSTED_LIVE_ADD_NATIVE_SHA256 = frozenset(LIVE_ADD_NATIVE_BUILDS)
# Trusted natives above that answer the v0.5 Items probe (PLAN C7,
# services/item_probe.py) and add every catalog tier (SBLiveAddNative 0.5.0
# and 0.5.1).
# Every other trusted native is a Live Add v3 native that can add only its
# embedded allowlist. (A fresh status that reports probe_state also counts.)
PROBE_CAPABLE_LIVE_ADD_NATIVE_SHA256: frozenset[str] = frozenset(
    {
        "3DF532FEDF404C86378592CCDEAF1B8E9E2C0AC2E5CFBF8A05BF195FDEC197CF",
        "E6D54C4A5FAED9B42657A7901142763212B1323BF994BFB10C84413B49D4D683",
    }
)
# Earlier approved files made for the previous game build and wire protocol
# (native-live-add-v2). They are never trusted; the card reads "Needs update".
SUPERSEDED_LIVE_ADD_SCRIPT_SHA256 = frozenset(
    {
                                          
        "BDEE33EBE226D76158D5EDDB5E57CA6F43360B64C367DFE9D669EE5D45A008AE",
    }
)
SUPERSEDED_LIVE_ADD_NATIVE_SHA256 = frozenset(
    {
                                                                           
                                           
        "A93D2A5465D4D3C7E3BB9AF8119582DAE00C55ECD072A425D7B234368AA42630",
    }
)
# A gate failure with one of these names is a problem with the install or the
# process (0.4.0: the sbcore fault handler could not be set up), not a
# different game build, so the card says "Couldn't start safely".
_LOCAL_GATE_FAILURES = frozenset({"runtime_paths", "module_pin", "fault_init"})
# Fields the native writes as fixed literals; anything else is not this build.
_NATIVE_ZERO_FIELDS = (
    "hooks",
    "direct_inventory_writes",
    "direct_wallet_writes",
    "save_game_writes",
)

_SAFE_ALIAS = re.compile(r"^[A-Za-z0-9_+]{1,128}$")
_SAFE_SESSION = re.compile(r"^[A-Fa-f0-9]{32,64}$")
_SAFE_REQUEST_ID = re.compile(r"^[A-Fa-f0-9]{32,64}$")

READY_TEXT = "Ready. Pick an item and add it."
NOT_INSTALLED_TEXT = "Not installed or turned off."
TURNED_OFF_TEXT = "Items & Money is turned off."
GAME_CLOSED_TEXT = "Start Stellar Blade and load a save first."
WAITING_BRIDGE_TEXT = "Waiting for game. Load your save and open the Bag once."
WAITING_NATIVE_TEXT = "Waiting for the game mod to report in."
WAITING_SELF_CHECK_TEXT = "Waiting for game. Load your save in a normal area."
UNTRUSTED_TEXT = (
    "Couldn't add safely: the installed Items & Money files are not the approved "
    "version, so adding stays off."
)
UNSAFE_SESSION_TEXT = (
    "Couldn't add safely, so adding stays off until the game is restarted. "
    "Nothing was changed in your game."
)
# The bridge and the game mod are both approved files, but from different
# versions (for example a new game mod with the old bridge): they can't talk.
MISMATCHED_FILES_TEXT = (
    "Couldn't add safely: the Items & Money files are from different versions of "
    "the mod. Install the whole mod again."
)
# SBLiveAddNative 0.5.0 (C6): another watched item grew with the last add.
SIDE_EFFECT_TEXT = (
    "Another item changed together with the last add, so adding stays off until "
    "the game is restarted. Check your bag."
)
# The game still runs a different Items & Money game mod than the one now in
# the Mods folder (it was replaced while the game was running).
RESTART_GAME_TEXT = (
    "The game is still running the previous Items & Money game mod. Restart the "
    "game to use the new one."
)
OUTCOME_UNKNOWN_TEXT = (
    "The game didn't confirm the last add. Restart the game and check your "
    "inventory before adding again."
)
ADDING_TEXT = "Adding once..."
ADDING_PAUSED_TEXT = (
    "Adding once... The game looks paused, so the item is added when you "
    "unpause. Don't add again."
)
# SBLiveAddNative 0.4.0 idles (no game work) while Items & Money is closed.
# Its safety check has passed this session: open the page and add.
STANDBY_READY_TEXT = "Ready. Open Items & Money to add an item."
# Its one-time safety check has not run yet this session; it runs when the
# page is opened.
STANDBY_CHECK_LABEL = "Safety check"
STANDBY_CHECK_TEXT = "Runs a quick safety check when you open Items & Money."
# The page was just opened; the native answers within about a second.
CONNECTING_LABEL = "Connecting"
CONNECTING_TEXT = "Connecting to the game..."


@dataclass(frozen=True)
class LiveAddState:
    installed: bool
    trusted: bool
    ready: bool
    busy: bool
    phase: str
    message: str
    last_result: str
    # Shared card vocabulary (services.native_status) plus "adding".
    state: str = NATIVE_WAITING
    reason: str = ""
    # Optional card word for a sub-state ("Safety check", "Connecting");
    # ``state`` (and so the chip colour and every readiness rule) is unchanged.
    label: str = ""


def format_live_add_lease(panel_pid: int, issued_ms: int, protocol: str = LIVE_ADD_API) -> bytes:
    """The exact Items lease body SBLiveAddNative 0.4.0 / 0.5.0 accepts.

    Three ``key=value`` lines in this order, canonical decimals, LF endings
    and no blank line (the native refuses anything else). ``protocol`` is the
    installed native's own (``installed_live_add_native_protocol``).
    """
    if isinstance(panel_pid, bool) or isinstance(issued_ms, bool):
        raise ValueError("The Items lease is invalid.")
    if protocol not in LIVE_ADD_PROTOCOLS:
        raise ValueError("The Items lease protocol is invalid.")
    pid = int(panel_pid)
    issued = int(issued_ms)
    if pid <= 0 or pid > 0xFFFFFFFF:
        raise ValueError("The Items lease panel id is invalid.")
    if issued <= 0 or issued > 18_446_744_073_709_551_615:
        raise ValueError("The Items lease time is invalid.")
    return f"protocol={protocol}\npanel_pid={pid}\nissued_ms={issued}\n".encode("ascii")


def _sha256(path: Path) -> str:
    # Cached by (path, size, mtime): the route is re-judged four times a second.
    return file_sha256(path).upper()


def _native_build(native_sha: str) -> tuple[str, str] | None:
    """(version, protocol) of a trusted native; None when it isn't trusted.

    A trusted hash that no build entry names (only possible when tests swap
    the trust set) is a v3 native of any v3 version.
    """
    if native_sha not in _upper_set(TRUSTED_LIVE_ADD_NATIVE_SHA256):
        return None
    return LIVE_ADD_NATIVE_BUILDS.get(native_sha, ("", LIVE_ADD_API))


def _bridge_protocol(script_sha: str) -> str:
    """The protocol a trusted bridge speaks; "" when it isn't trusted."""
    if script_sha not in _upper_set(TRUSTED_LIVE_ADD_SCRIPT_SHA256):
        return ""
    return LIVE_ADD_BRIDGE_BUILDS.get(script_sha, LIVE_ADD_API)


def installed_live_add_native_protocol(native_dll_path: Path) -> str:
    """The protocol the installed, trusted Items game mod speaks ("" = none).

    The Items lease is written in this protocol: 0.4.0 reads a v3 lease,
    0.5.0 a v4 one, and nothing is written for an untrusted file.
    """
    try:
        build = _native_build(_sha256(Path(native_dll_path)))
    except OSError:
        return ""
    return build[1] if build else ""


def live_add_route_protocol(script_path: Path, native_dll_path: Path) -> str:
    """The protocol of the installed bridge + game mod pair ("" unless both are
    trusted and speak the same one)."""
    try:
        script_protocol = _bridge_protocol(_sha256(Path(script_path)))
        build = _native_build(_sha256(Path(native_dll_path)))
    except OSError:
        return ""
    if not script_protocol or not build or build[1] != script_protocol:
        return ""
    return script_protocol


def _upper_set(values) -> frozenset[str]:
    return frozenset(str(value).strip().upper() for value in values if str(value).strip())


def _is_true(value: object) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _file_age(path: Path, now: float | None = None) -> float | None:
    try:
        return (time.time() if now is None else float(now)) - path.stat().st_mtime
    except OSError:
        return None


# Native refusals made before anything was sent to the game (terminal, so
# adding stays ready): a full bag, an item used on pickup, an item without a
# row in the game's item table, and the v0.5 up-front refusals (PLAN C2-C5):
# a DLC/edition item, a row that no longer matches the catalog, locked or
# unreadable ammo limits, a redirected copy, a one-of-a-kind item that is
# already owned, an amount outside the item's range, a hard-denied category
# and a unique item whose count this session can't prove yet; SBLiveAddNative
# 0.5.1 adds an item the game spends on an upgrade by itself (Body Core, Beta
# Core) and an add to an owned one-per-bag-slot item outside the proven kinds.
# (A watched side effect is not one of them: it locks the session.)
SAFE_REFUSAL_DETAILS = (
    "inventory_at_capacity",
    "item_used_on_pickup",
    "item_row_not_found",
    "entitlement_gated",
    "data_mismatch",
    "locked_by_stat",
    "limit_unknown",
    "use_canonical_alias",
    "already_owned",
    "quantity_not_allowed",
    "quantity_blocked",
    "category_denied",
    "instance_count_unproven",
    "item_auto_level_up",
    "item_per_unit_owned_unproven",
)
# Largest single request any route accepts: v0.5 Gold is 1..1,000,000 per add
# (PLAN C3); the v3 route stays at 1..99.
LIVE_ADD_LEGACY_MAX_QTY = 99
LIVE_ADD_MAX_QTY = 1_000_000
# A v0.5 game mod that answers probes reports its probe state in
# live_add_native_status.txt (SBLiveAddNative v0.5.0: idle, reading,
# publishing or done); older ones have no such key.
LIVE_ADD_PROBE_STATUS_KEY = "probe_state"


def native_probe_capable(values: Mapping[str, str] | None, states: Iterable[str]) -> bool:
    """The fresh native status says the game mod answers probes."""
    return bool(values) and str(values.get(LIVE_ADD_PROBE_STATUS_KEY, "")).strip() in set(states)


def is_safe_refusal(detail: object) -> bool:
    text = str(detail or "")
    return any(token in text for token in SAFE_REFUSAL_DETAILS)


_DETAIL_TOKEN = re.compile(r"\b([a-z_]+)=([A-Za-z0-9_.+-]+)")


def _detail_tokens(detail: object) -> dict[str, str]:
    """``key=value`` tokens of a native result detail (first occurrence wins)."""
    tokens: dict[str, str] = {}
    for key, value in _DETAIL_TOKEN.findall(str(detail or "")):
        tokens.setdefault(key, value)
    return tokens


def _int_token(value: object) -> int | None:
    text = str(value or "").strip()
    if not text.isdigit() or len(text) > 12:
        return None
    return int(text)


def _clean_name(display_name: object) -> str:
    name = re.sub(r"[\x00-\x1f\x7f]", "", str(display_name or "item")).strip()
    return name[:160] or "item"


def _seconds_text(milliseconds: int) -> str:
    seconds = max(1, round(milliseconds / 1000))
    return f"{seconds} second" + ("" if seconds == 1 else "s")


def unconfirmed_add_text(
    display_name: object,
    *,
    before: int | None,
    after: int | None,
    window_ms: int | None,
    condition_group: bool,
    frames_frozen: bool,
    sent: int | None = None,
) -> str:
    """Plain wording for an add the game never confirmed (Live Add stays locked).

    A count that moved is reported as it moved ("went from 2 to 0 instead of
    3"); only an unchanged count "stayed at".
    """
    name = _clean_name(display_name)
    parts = ["The game didn't confirm the last add."]
    if after is not None and before is not None and after != before:
        moved = f"{name} went from {before} to {after}"
        if sent and after != before + sent:
            moved += f" instead of {before + sent}"
        parts.append(moved + ".")
    elif after is not None and window_ms is not None:
        parts.append(f"{name} stayed at {after} for {_seconds_text(window_ms)}.")
    if frames_frozen:
        parts.append("The game looked paused, so it may still arrive after you unpause.")
    elif condition_group and before is not None and after == before:
        parts.append("The game may only allow this item after it's unlocked in your story.")
    parts.append("Restart the game and check your bag before adding again.")
    return " ".join(parts)


def describe_native_last_add(values: Mapping[str, str] | None, display_name: object = "") -> str:
    """Status-line sentence from the v0.3.1 ``live_add_native_status.txt`` fields.

    Returns "" when the native does not report its last add (v0.3.0) or the
    last add is not an unconfirmed one.
    """
    if not values:
        return ""
    outcome = str(values.get("last_outcome", "")).strip()
    if outcome not in {"authoritative_server_no_verified_count_change", "inventory_count_mismatch"}:
        return ""
    frame_at_add = _int_token(values.get("server_frame_at_add"))
    frame_last = _int_token(values.get("server_frame_last"))
    frames_frozen = (
        str(values.get("server_frame_live", "")).strip() == "1"
        and frame_at_add is not None
        and frame_at_add == frame_last
    )
    name = str(display_name or "").strip()
    if not name or name.lower() == "item":
        # Never show the internal alias; the panel passes the display name.
        name = "The item"
    return unconfirmed_add_text(
        name,
        before=_int_token(values.get("count_before")),
        after=_int_token(values.get("count_after_last")),
        window_ms=_int_token(values.get("verify_window_ms")),
        condition_group=str(values.get("item_condition_group", "")).strip() == "1",
        frames_frozen=frames_frozen,
        sent=_int_token(values.get("last_qty_sent")),
    )


def trusted_live_add_protocol(heartbeat: Mapping[str, object], protocol: str = "") -> bool:
    """The bridge heartbeat proves a ready native session (sbcheat_heartbeat.txt).

    ``protocol`` is the installed pair's (``live_add_route_protocol``); the
    heartbeat must report exactly it. Empty accepts either known protocol
    (only where the pair is judged separately).
    """
    session = str(heartbeat.get("session") or "").strip()
    try:
        native_beat = int(str(heartbeat.get("nativebeat") or "0"))
    except (TypeError, ValueError, OverflowError):
        native_beat = 0
    spawn_api = str(heartbeat.get("spawnapi") or "")
    return (
        str(heartbeat.get("bridge") or "") == TRUSTED_BRIDGE_ID
        and (spawn_api == protocol if protocol else spawn_api in LIVE_ADD_PROTOCOLS)
        and _is_true(heartbeat.get("cheatmanager"))
        and _is_true(heartbeat.get("eve"))
        and _SAFE_SESSION.fullmatch(session) is not None
        and native_beat > 0
    )


def live_add_status_matches(
    result: Mapping[str, object],
    *,
    expected_session: str,
    expected_request_id: str,
    expected_sequence: int,
    expected_alias: str = "",
) -> bool:
    """Bind a status row to one exact panel request and native session."""
    session = str(result.get("spawnsession") or "").strip()
    request_id = str(result.get("spawnrequest") or "").strip()
    alias = str(result.get("itemalias") or "").strip()
    try:
        sequence = int(str(result.get("spawnseq") or "0"))
    except (TypeError, ValueError, OverflowError):
        return False
    return bool(
        _SAFE_SESSION.fullmatch(expected_session or "")
        and _SAFE_REQUEST_ID.fullmatch(expected_request_id or "")
        and session == expected_session
        and request_id == expected_request_id
        and sequence == expected_sequence
        and expected_sequence > 0
        and (not expected_alias or alias.lower() == expected_alias.lower())
    )


def result_outcome_unknown(result: Mapping[str, object]) -> bool:
    """The bridge says the native never gave a final answer for this request."""
    return "outcome_unknown" in str(result.get("detail") or "").lower()


def interpret_live_add_native_status(
    values: Mapping[str, str], expected_build: tuple[str, str] | None = None
) -> tuple[str, str]:
    """Card state from a fresh ``live_add_native_status.txt``.

    ``Ready`` here only means the native itself is ready: gate passed,
    self-check passed and game code still allowed this session. The bridge
    heartbeat must still prove a ready session before an add is offered.

    ``expected_build`` is the installed DLL's (version, protocol) from
    ``LIVE_ADD_NATIVE_BUILDS``: the running game mod must be that one (a
    DLL replaced while the game runs is not what the game loaded).
    """
    protocol = str(values.get("protocol", "")).strip()
    version = str(values.get("version", "")).strip()
    gate = str(values.get("gate", "")).strip().lower()
    failed_check = str(values.get("gate_failed_check", "")).strip().lower()
    if (protocol, version) not in LIVE_ADD_STATUS_PAIRS:
        # Older natives (v0.1.0, native-live-add-v2) also report build_mismatch
        # on this game; either way it is not an approved native.
        if str(values.get("result", "")).strip().lower() == "build_mismatch":
            return NATIVE_NEEDS_UPDATE, "older-native-build-mismatch"
        return NATIVE_UNSAFE, f"unexpected-native:{protocol or '-'}:{version or '-'}"
    if expected_build is not None:
        expected_version, expected_protocol = expected_build
        if protocol != expected_protocol or (expected_version and version != expected_version):
            return NATIVE_UNSAFE, f"running-native-differs:{version}"
    if gate != "pass":
        if failed_check in _LOCAL_GATE_FAILURES:
            return NATIVE_UNSAFE, f"gate-failed:{failed_check}"
        return NATIVE_NEEDS_UPDATE, f"gate-failed:{failed_check or 'unknown'}"
    for key in _NATIVE_ZERO_FIELDS:
        if str(values.get(key, "")).strip() != "0":
            return NATIVE_UNSAFE, f"policy-field:{key}"
    if str(values.get("shutting_down", "0")).strip() == "1":
        return NATIVE_UNSAFE, "shutting-down"
    if _is_true(values.get("game_code_disabled")):
        reason = str(values.get("game_code_disabled_reason", "")).strip() or "unknown"
        return NATIVE_UNSAFE, f"game-code-disabled:{reason}"
    selfcheck = str(values.get("selfcheck", "")).strip().lower()
    if selfcheck == "fail":
        step = str(values.get("selfcheck_step", "")).strip() or "unknown"
        return NATIVE_UNSAFE, f"self-check-failed:{step}"
    if _is_true(values.get("dispatch_poisoned")):
        return NATIVE_UNSAFE, "game-thread-dispatch-stopped"
    if _is_true(values.get("outcome_unknown")):
        return NATIVE_UNSAFE, "outcome-unknown"
    if _is_true(values.get("side_effect_latched")):
        # 0.5.0 (C6): another watched item grew with an add; locked until the
        # game restarts.
        return NATIVE_UNSAFE, "side-effect-detected"
    if str(values.get("ready", "")).strip() != "1":
        return NATIVE_UNSAFE, "native-not-ready"
    if selfcheck != "pass":
        step = str(values.get("selfcheck_step", "")).strip() or "pending"
        return NATIVE_WAITING, f"self-check-pending:{step}"
    return NATIVE_READY, "native-ready"


def evaluate_live_add(
    *,
    script_path: Path,
    bridge_marker_path: Path,
    native_dll_path: Path,
    native_marker_path: Path,
    heartbeat_path: Path,
    heartbeat: Mapping[str, object],
    result: Mapping[str, object],
    game_running: bool,
    result_path: Path | None = None,
    now: float | None = None,
    expected_session: str = "",
    expected_request_id: str = "",
    expected_sequence: int = 0,
    expected_alias: str = "",
    native_status: Mapping[str, str] | None = None,
    native_status_fresh: bool = False,
    expected_name: str = "",
    panel_lease: str = "",
) -> LiveAddState:
    """Judge the whole route; every doubt keeps adding off.

    ``native_status`` is the parsed ``live_add_native_status.txt``; pass
    ``None`` only in tests that exercise the bridge protocol alone.

    ``panel_lease`` is the panel's Items lease (``LIVE_ADD_LEASE_OFF``,
    ``_SETTLING`` or ``_HELD``; empty = not tracked). A native that reports
    ``refresh_requires_panel_lease=1`` (0.4.0) does no game work without the
    lease, so a healthy native with no lease is on standby rather than
    "Waiting for game". Standby never makes adding ready.
    """
    del result_path
    script_path = Path(script_path)
    native_dll_path = Path(native_dll_path)
    installed = script_path.is_file() and native_dll_path.is_file()
    if not installed:
        return LiveAddState(
            False, False, False, False, "unavailable", NOT_INSTALLED_TEXT, "",
            NATIVE_OFF, "not-installed",
        )

    try:
        dedicated_native = native_dll_path.parent.parent.name == LIVE_ADD_NATIVE_MODULE
        script_sha = _sha256(script_path)
        native_sha = _sha256(native_dll_path)
    except OSError:
        dedicated_native, script_sha, native_sha = False, "", ""
    script_trusted = script_sha in _upper_set(TRUSTED_LIVE_ADD_SCRIPT_SHA256)
    native_trusted = native_sha in _upper_set(TRUSTED_LIVE_ADD_NATIVE_SHA256)
    trusted = dedicated_native and script_trusted and native_trusted
    native_build = _native_build(native_sha) if trusted else None
    route_protocol = _bridge_protocol(script_sha) if trusted else ""
    if trusted and (native_build is None or native_build[1] != route_protocol):
        # Both files are approved, but from different versions of the mod
        # (for example the 0.5.0 game mod with the v3 bridge): they don't
        # speak the same protocol, so nothing could ever be added.
        return LiveAddState(
            True, False, False, False, "blocked", MISMATCHED_FILES_TEXT, "",
            NATIVE_UNSAFE, "bridge-native-mismatch",
        )
    if not trusted:
        script_known = script_trusted or script_sha in _upper_set(SUPERSEDED_LIVE_ADD_SCRIPT_SHA256)
        native_known = native_trusted or native_sha in _upper_set(SUPERSEDED_LIVE_ADD_NATIVE_SHA256)
        if dedicated_native and script_known and native_known:
            return LiveAddState(
                True, False, False, False, "needs_update", GAME_UPDATED_TEXT, "",
                NATIVE_NEEDS_UPDATE, "superseded-files",
            )
        return LiveAddState(
            True, False, False, False, "blocked", UNTRUSTED_TEXT, "",
            NATIVE_UNSAFE, "untrusted-files",
        )

    if not Path(bridge_marker_path).is_file() or not Path(native_marker_path).is_file():
        return LiveAddState(
            True, True, False, False, "off", TURNED_OFF_TEXT, "",
            NATIVE_OFF, "marker-missing",
        )
    if not game_running:
        return LiveAddState(
            True, True, False, False, "waiting", GAME_CLOSED_TEXT, "",
            NATIVE_WAITING, "game-closed",
        )

    request_expected = bool(
        _SAFE_SESSION.fullmatch(expected_session or "")
        and _SAFE_REQUEST_ID.fullmatch(expected_request_id or "")
        and expected_sequence > 0
    )
    matching_status = live_add_status_matches(
        result,
        expected_session=expected_session,
        expected_request_id=expected_request_id,
        expected_sequence=expected_sequence,
        expected_alias=expected_alias,
    )
    last_add_text = describe_native_last_add(
        native_status if native_status_fresh else None, expected_name
    )
    if request_expected and matching_status and result_outcome_unknown(result):
        # The native never gave a final answer. Stay locked for this session.
        return LiveAddState(
            True, True, False, True, "outcome_unknown", last_add_text or OUTCOME_UNKNOWN_TEXT, "",
            NATIVE_UNSAFE, "outcome-unknown",
        )

    if native_status is not None:
        if not native_status_fresh or not native_status:
            return LiveAddState(
                True, True, False, False, "waiting", WAITING_NATIVE_TEXT, "",
                NATIVE_WAITING, "native-status-missing-or-stale",
            )
        try:
            native_state, native_reason = interpret_live_add_native_status(native_status, native_build)
        except Exception as exc:  # a malformed report must never read as ready
            native_state, native_reason = NATIVE_UNSAFE, f"interpret-{type(exc).__name__}"
        if native_state == NATIVE_NEEDS_UPDATE:
            return LiveAddState(
                True, True, False, False, "needs_update", GAME_UPDATED_TEXT, "",
                NATIVE_NEEDS_UPDATE, native_reason,
            )
        if native_state == NATIVE_UNSAFE:
            if native_reason == "outcome-unknown":
                text = last_add_text or OUTCOME_UNKNOWN_TEXT
            elif native_reason == "side-effect-detected":
                text = SIDE_EFFECT_TEXT
            elif native_reason.startswith("running-native-differs"):
                text = RESTART_GAME_TEXT
            else:
                text = UNSAFE_SESSION_TEXT
            return LiveAddState(
                True, True, False, False, "unsafe", text, "",
                NATIVE_UNSAFE, native_reason,
            )
    # SBLiveAddNative 0.4.0 without a held panel lease: it is idle by design.
    lease_idle = bool(
        native_status is not None
        and native_status_fresh
        and str(native_status.get("refresh_requires_panel_lease", "")).strip() == "1"
        and panel_lease in (LIVE_ADD_LEASE_OFF, LIVE_ADD_LEASE_SETTLING)
        and not request_expected
    )
    if native_status is not None:
        if native_state != NATIVE_READY:
            if lease_idle and native_reason.startswith("self-check-pending"):
                if panel_lease == LIVE_ADD_LEASE_SETTLING:
                    return LiveAddState(
                        True, True, False, False, "connecting", CONNECTING_TEXT, "",
                        NATIVE_WAITING, "lease-settling", CONNECTING_LABEL,
                    )
                return LiveAddState(
                    True, True, False, False, "standby", STANDBY_CHECK_TEXT, "",
                    NATIVE_WAITING, "standby-self-check", STANDBY_CHECK_LABEL,
                )
            return LiveAddState(
                True, True, False, False, "waiting", WAITING_SELF_CHECK_TEXT, "",
                NATIVE_WAITING, native_reason,
            )

    age = _file_age(Path(heartbeat_path), now)
    protocol_ready = (
        age is not None
        and 0 <= age <= LIVE_ADD_ACTION_LEASE_SEC
        and trusted_live_add_protocol(heartbeat, route_protocol)
    )
    if not protocol_ready:
        if lease_idle and panel_lease == LIVE_ADD_LEASE_SETTLING:
            return LiveAddState(
                True, True, False, False, "connecting", CONNECTING_TEXT, "",
                NATIVE_WAITING, "lease-settling", CONNECTING_LABEL,
            )
        if lease_idle:
            # The native passed its safety check this session and reports
            # ready; it only stopped reading the inventory because Items &
            # Money is closed. Opening the page re-arms it within a second.
            return LiveAddState(
                True, True, False, False, "standby", STANDBY_READY_TEXT, "",
                NATIVE_READY, "standby-no-lease",
            )
        return LiveAddState(
            True, True, False, False, "waiting", WAITING_BRIDGE_TEXT, "",
            NATIVE_WAITING, "bridge-not-ready",
        )

    # A timeout is not a terminal native acknowledgement. Once a request is
    # issued, the panel remains fail-closed until the exact correlated status
    # becomes terminal or a new native session makes completion impossible.
    bridge_pending = _is_true(heartbeat.get("requestpending"))
    busy = bridge_pending or (
        request_expected and (not matching_status or _is_true(result.get("pending")))
    )
    if busy:
        paused = bool(
            native_status_fresh
            and native_status
            and str(native_status.get("verify_paused_wait", "")).strip() == "1"
        )
        return LiveAddState(
            True, True, False, True, "adding", ADDING_PAUSED_TEXT if paused else ADDING_TEXT, "",
            "adding", "request-in-flight-paused" if paused else "request-in-flight",
        )
    return LiveAddState(
        True, True, True, False, "ready", READY_TEXT, "",
        NATIVE_READY, "ready",
    )


def build_live_add_updates(
    *,
    alias: str,
    quantity: int,
    previous_sequence: int,
    session: str,
    request_id: str,
    issued_unix_s: int,
    max_quantity: int = LIVE_ADD_LEGACY_MAX_QTY,
) -> dict[str, str]:
    """The ``gui_state.txt`` keys the bridge (v3 and v4) reads for exactly one request.

    ``max_quantity`` is the item's per-add tier (PLAN C3); the v3 route never
    passes more than 99, and nothing passes more than 1,000,000.
    """
    clean_alias = str(alias or "").strip()
    if not _SAFE_ALIAS.fullmatch(clean_alias):
        raise ValueError("The selected item identifier is invalid.")
    clean_session = str(session or "").strip()
    clean_request_id = str(request_id or "").strip()
    if not _SAFE_SESSION.fullmatch(clean_session):
        raise ValueError("The Live Add game session is invalid.")
    if not _SAFE_REQUEST_ID.fullmatch(clean_request_id):
        raise ValueError("The Live Add request identity is invalid.")
    if (
        isinstance(quantity, bool)
        or isinstance(previous_sequence, bool)
        or isinstance(issued_unix_s, bool)
        or isinstance(max_quantity, bool)
    ):
        raise ValueError("The Live Add request is invalid.")
    try:
        ceiling = max(1, min(LIVE_ADD_MAX_QTY, int(max_quantity)))
        clean_quantity = max(1, min(ceiling, int(quantity)))
        sequence = int(previous_sequence) + 1
        clean_issued_unix_s = int(issued_unix_s)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("The Live Add request is invalid.") from exc
    if sequence <= 0 or sequence > 9_007_199_254_740_991:
        raise ValueError("The Live Add sequence is invalid.")
    if clean_issued_unix_s <= 0 or clean_issued_unix_s > 9_007_199_254_740_991:
        raise ValueError("The Live Add issue time is invalid.")
    return {
        "spawnalias": clean_alias,
        "spawnqty": str(clean_quantity),
        "spawnlevel": "0",
        "spawnmode": "inventory",
        "spawnseq": str(sequence),
        "spawnsession": clean_session,
        "spawnrequest": clean_request_id,
        "spawnissuedunixs": str(clean_issued_unix_s),
    }


def _amount(count: int, name: str, currency: bool) -> str:
    return f"{count:,} {name}" if currency else f"{count} x {name}"


def friendly_live_add_result(
    result: Mapping[str, object],
    display_name: str,
    quantity: int,
    native_status: Mapping[str, str] | None = None,
    *,
    currency: bool = False,
) -> str:
    """Player wording for one terminal (or locked) bridge status row.

    ``native_status`` (optional, v0.3.1) adds the carry limit to an add the
    game shortened to the room left. ``currency`` words an amount of money
    ("Added 10,000 Gold.") instead of a count of items.
    """
    name = _clean_name(display_name)
    count = max(1, min(LIVE_ADD_MAX_QTY, int(quantity)))
    detail_text = str(result.get("detail") or "")
    tokens = _detail_tokens(detail_text)
    before_after = re.search(r"\bbefore=(\d+)\s+after=(\d+)\b", detail_text)
    pending_count = re.search(r"\bqty=(\d+)\b", detail_text)
    if before_after:
        before, after = (int(value) for value in before_after.groups())
        if after > before:
            count = max(1, min(LIVE_ADD_MAX_QTY, after - before))
    elif pending_count:
        count = max(1, min(LIVE_ADD_MAX_QTY, int(pending_count.group(1))))
    detail = detail_text.lower()
    if "outcome_unknown" in detail:
        if "window_ms" in tokens and "after" in tokens:
            frames = _int_token(tokens.get("frames_since_add"))
            return unconfirmed_add_text(
                name,
                before=_int_token(tokens.get("before")),
                after=_int_token(tokens.get("after")),
                window_ms=_int_token(tokens.get("window_ms")),
                sent=_int_token(tokens.get("sent")),
                condition_group=tokens.get("condition_group") == "1",
                frames_frozen=frames == 0 and bool(
                    native_status and str(native_status.get("server_frame_live", "")).strip() == "1"
                ),
            )
        return OUTCOME_UNKNOWN_TEXT
    if _is_true(result.get("pending")):
        return f"Adding {_amount(count, name, currency)}..."
    if _is_true(result.get("ok")):
        text = f"Added {_amount(count, name, currency)}."
        if native_status:
            limit = _int_token(native_status.get("count_max_if_known"))
            sent = _int_token(native_status.get("last_qty_sent"))
            requested = _int_token(native_status.get("last_qty_requested"))
            same_item = str(native_status.get("last_alias", "")).lower() == str(
                result.get("itemalias", "")
            ).lower()
            if same_item and limit and sent is not None and requested and sent < requested:
                text += f" That's the most you can carry ({limit})."
        return text
    if "inventory_at_capacity" in detail:
        limit = _int_token(tokens.get("max"))
        suffix = f" ({limit})" if limit else ""
        return f"{name} is already at the maximum you can carry{suffix}. Nothing was added."
    if "item_used_on_pickup" in detail:
        return f"{name} is used as soon as it's picked up, so it can't be stored. Nothing was added."
    if "item_auto_level_up" in detail:
        return (
            f"The game uses {name} for an upgrade as soon as you have enough, "
            "so it can't be added. Nothing was added."
        )
    if "item_per_unit_owned_unproven" in detail:
        return f"{name} can only be added when you don't have any yet. Nothing was added."
    if "item_row_not_found" in detail:
        return f"The game doesn't list {name} as an item it can add right now. Nothing was added."
    if "entitlement_gated" in detail:
        return f"{name} needs a DLC or edition, so it can't be added. Nothing was added."
    if "side_effect_detected" in detail:
        return (
            f"Another item changed together with {name}, so adding stays off until the "
            "game is restarted. Check your bag."
        )
    if "session_locked" in detail:
        return "Adding stays off until the game is restarted. Nothing was added."
    if "already_owned" in detail:
        return f"You already have {name}, and it's one of a kind. Nothing was added."
    if "instance_count_unproven" in detail:
        return (
            f"The game hasn't shown yet that it counts items like {name}, so nothing "
            "was added. Keep Items & Money open for a moment and try again."
        )
    if "quantity_not_allowed" in detail or "quantity_blocked" in detail:
        return f"That amount isn't allowed for {name}. Nothing was added."
    if "category_denied" in detail or "policy_blocked" in detail:
        return "This item can't be added. Nothing was added."
    if "panel_lease_missing" in detail:
        return "Couldn't add safely: Items & Money was closed before the game took the item. Nothing was added."
    if "locked_by_stat" in detail:
        return f"{name} isn't unlocked in your story yet. Nothing was added."
    if "limit_unknown" in detail:
        return f"The game didn't say how many {name} you can carry, so nothing was added."
    if "data_mismatch" in detail or "use_canonical_alias" in detail:
        return f"The game lists {name} differently now, so nothing was added."

    if "inventory_not_ready" in detail or "inventory_bucket_not_ready" in detail:
        return "Couldn't add safely. Open the Bag once, then try again."
    if "request_expired" in detail or "request_stale" in detail:
        return "Couldn't add safely: the game didn't pick up the request in time. Nothing was added."
    if "session" in detail:
        return "Couldn't add safely: the game session changed. Nothing was added."
    if "timeout" in detail:
        return "Couldn't add safely: the game didn't confirm the add, so nothing was repeated."
    if "category_blocked" in detail or "mode_blocked" in detail or "alias_blocked" in detail:
        return "This item is not supported yet."
    if "invalid" in detail:
        return "Couldn't add safely: this item couldn't be identified."
    if "self_check" in detail:
        return "Couldn't add safely, so adding stays off until the game is restarted."
    return "Couldn't add safely. The game did not confirm the item."
