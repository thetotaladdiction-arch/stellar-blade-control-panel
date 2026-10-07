"""Items & Money probe: the read-only "what would the game say" question (PLAN C7).

The panel asks the Items & Money game mod (SBLiveAddNative v0.5) about its
items; the game mod answers from the same row lookup, count read and carry
stat read an add makes, and labels each item with the decision an add of one
would get (so a label never promises more than an add does). Nothing is sent
to the game's inventory: no add, no remove, no write. The labels become the
catalog chips: Ready, Owned, At limit, Needs DLC or Not available.

The wire format is the one SBLiveAddNative v0.5.0 implements (see its
source file ``native/SBLiveAddNative/
live_add.cpp`` "v0.5.0 (C7): the read-only probe", checked by its protocol
harness ``probe_request_tests``). It rides on the add protocol
``native-live-add-v4``.

Request, written by the panel as ``<SBCheatGUI>/live_add_native_probe_request.txt``
(replaced atomically with a POSIX rename, ASCII, LF endings, no blank line;
exactly these five keys, each once - the game mod refuses any other key)::

    protocol=native-live-add-v4
    session=<the live session the bridge heartbeat reports, 32-64 hex>
    probe_id=<32-64 hex>
    issued_unix_s=<Unix seconds; the game mod refuses one older than 5 s>
    aliases=*                         (every addable and DLC-gated item)
    aliases=A,B,...                   (or 1..64 distinct allowlisted names)

A listed name the game mod doesn't allow refuses the whole question
(``policy_blocked``), so a short question only names items a full answer
already returned. The game mod takes a question only while the panel holds
the Items lease, claims the file (it disappears), reads at most 32 items per
GameThread callback and never mutates anything.

Result, written by the game mod as ``<SBCheatGUI>/live_add_native_probe_result.txt``
once the whole question is answered (CRLF lines, ``end=1`` last)::

    protocol=native-live-add-v4
    module=SBLiveAddNative
    version=0.5.0
    session=<session>
    probe_id=<echo>
    status=ok                         (or the refusal, e.g. panel_lease_missing)
    items=<N; 0 on a refusal>
    bucket_guid=<n>
    instance_evidence=gear:0,exospine:0,nanosuit:0
    allowlist_catalog_sha256=<hex>
    item.<alias>=<state>|<count>|<max>|<addable_now>
    end=1

``state`` is one of ``available``, ``owned``, ``at_limit``, ``needs_dlc``,
``locked_by_stat``, ``limit_unknown``, ``unproven``, ``not_in_game``,
``unreadable``, ``not_read``, ``data_mismatch`` and, from SBLiveAddNative
0.5.1, ``auto_level_up`` (the game spends the item on an upgrade as soon as
enough are carried: Body Core, Beta Core) and ``per_unit_unproven`` (an owned
item the bag shows one per slot, outside the kinds proven to add safely).
``count`` is the bag count
(``unknown`` when unreadable), ``max`` the carry limit (a number, ``none``
or ``unknown``) and ``addable_now`` the most one add would send now (0 unless
``available``). ``aliases=*`` answers every item on the game mod's allowlist,
so a finished full answer that leaves a listed catalog item out means the
game mod doesn't allow it.

A game mod that answers probes reports ``probe_state`` (idle, reading,
publishing or done) in ``live_add_native_status.txt``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Iterable, Mapping

PROBE_PROTOCOL = "native-live-add-v4"
PROBE_MODULE = "SBLiveAddNative"
PROBE_REQUEST_FILE = "live_add_native_probe_request.txt"
PROBE_RESULT_FILE = "live_add_native_probe_result.txt"
PROBE_ALL = "*"
PROBE_MAX_LISTED = 64
# ``probe_state`` values in live_add_native_status.txt (v0.5.0 and later).
PROBE_STATUS_STATES = frozenset({"idle", "reading", "publishing", "done"})
PROBE_REQUEST_MAX_BYTES = 8192
# A result file larger than this is not a probe answer (770 rows fit easily).
PROBE_RESULT_MAX_BYTES = 256 * 1024
# The game mod ignores a request older than 5 s; the panel asks again after
# this long without a finished answer (the probe is read-only).
PROBE_REQUEST_TIMEOUT_SEC = 10.0
# While Items & Money stays open, counts are refreshed this often (pickups,
# purchases and use in game change them).
PROBE_REFRESH_SEC = 60.0

PROBE_STATES = frozenset({
    "available",
    "owned",
    "at_limit",
    "needs_dlc",
    "locked_by_stat",
    "limit_unknown",
    "unproven",
    "not_in_game",
    "unreadable",
    "not_read",
    "data_mismatch",
    "auto_level_up",
    "per_unit_unproven",
})

_SAFE_ALIAS = re.compile(r"^[A-Za-z0-9_+]{1,128}$")
_SAFE_PROBE_ID = re.compile(r"^[a-f0-9]{32}$")
_SAFE_SESSION = re.compile(r"^[A-Fa-f0-9]{32,64}$")
_INT = re.compile(r"^\d{1,12}$")
_REFUSAL = re.compile(r"^[a-z_]{1,48}$")

# The five catalog chips.
CHIP_READY = "ready"
CHIP_OWNED = "owned"
CHIP_AT_LIMIT = "at_limit"
CHIP_NEEDS_DLC = "needs_dlc"
CHIP_NOT_AVAILABLE = "not_available"
CHIP_LABELS = {
    CHIP_READY: "Ready",
    CHIP_OWNED: "Owned",
    CHIP_AT_LIMIT: "At limit",
    CHIP_NEEDS_DLC: "Needs DLC",
    CHIP_NOT_AVAILABLE: "Not available",
}
# StatusChip kinds (Status.js): green, accent, amber, amber, neutral.
CHIP_KINDS = {
    CHIP_READY: "ok",
    CHIP_OWNED: "info",
    CHIP_AT_LIMIT: "warn",
    CHIP_NEEDS_DLC: "warn",
    CHIP_NOT_AVAILABLE: "off",
}

DLC_REASON = "Needs a DLC or edition, so it can't be added yet."
LEGACY_REASON = "Comes with the next Items & Money update."
NOT_ALLOWED_REASON = "The Items & Money game mod doesn't allow this item yet."
# Probe label -> (chip, reason). "not_read" is not a verdict: no chip.
_STATE_CHIPS = {
    "owned": (CHIP_OWNED, "You already have it, and it's one of a kind."),
    "at_limit": (CHIP_AT_LIMIT, "You're carrying the most the game allows."),
    "needs_dlc": (CHIP_NEEDS_DLC, DLC_REASON),
    "locked_by_stat": (CHIP_NOT_AVAILABLE, "Unlock this ammo in the story first."),
    "limit_unknown": (CHIP_NOT_AVAILABLE, "The game didn't say how many you can carry, so it can't be added now."),
    "unproven": (
        CHIP_NOT_AVAILABLE,
        "Can be added once the game mod has seen one you already own of this kind.",
    ),
    "not_in_game": (CHIP_NOT_AVAILABLE, "The game doesn't have this item right now."),
    "unreadable": (CHIP_NOT_AVAILABLE, "The game didn't report this item. Try again in a moment."),
    "data_mismatch": (CHIP_NOT_AVAILABLE, "The game lists this item differently now, so it can't be added."),
    "auto_level_up": (
        CHIP_NOT_AVAILABLE,
        "The game spends this item on an upgrade as soon as you have enough, so it can't be added.",
    ),
    "per_unit_unproven": (CHIP_OWNED, "Can only be added when you don't have any yet."),
}
# Why an item the game spends on an upgrade by itself is never offered, when
# the item has no reason of its own below (see AUTO_LEVEL_UP_ALIASES).
AUTO_LEVEL_UP_REASON = _STATE_CHIPS["auto_level_up"][1]


class ProbeError(ValueError):
    pass


def state_reason(state: str) -> str:
    """The plain reason for a probe label that can't be added ("" otherwise)."""
    return _STATE_CHIPS.get(state, ("", ""))[1]


def format_probe_request(
    *,
    probe_id: str,
    issued_unix_s: int,
    session: str,
    aliases: Iterable[str] | None = None,
) -> bytes:
    """The exact request body; ``aliases=None`` asks about every item."""
    if isinstance(issued_unix_s, bool):
        raise ProbeError("invalid request")
    issued = int(issued_unix_s)
    if issued <= 0:
        raise ProbeError("invalid request")
    if not _SAFE_PROBE_ID.fullmatch(str(probe_id or "")):
        raise ProbeError("invalid probe id")
    if not _SAFE_SESSION.fullmatch(str(session or "")):
        raise ProbeError("invalid session")
    if aliases is None:
        wanted = PROBE_ALL
    else:
        unique: list[str] = []
        seen: set[str] = set()
        for alias in aliases:
            text = str(alias or "").strip()
            if not _SAFE_ALIAS.fullmatch(text):
                raise ProbeError(f"unsafe item identifier {text[:40]!r}")
            if text.lower() not in seen:
                seen.add(text.lower())
                unique.append(text)
        if not 0 < len(unique) <= PROBE_MAX_LISTED:
            raise ProbeError(f"a list probe asks about 1..{PROBE_MAX_LISTED} items")
        wanted = ",".join(unique)
    lines = [
        f"protocol={PROBE_PROTOCOL}",
        f"session={session}",
        f"probe_id={probe_id}",
        f"issued_unix_s={issued}",
        f"aliases={wanted}",
    ]
    body = ("\n".join(lines) + "\n").encode("ascii")
    if len(body) > PROBE_REQUEST_MAX_BYTES:
        raise ProbeError("request too large")
    return body


@dataclass(frozen=True)
class ProbeEntry:
    """One item as the game mod labelled it."""

    state: str
    count: int = 0
    max: int = 0
    addable_now: int = 0


@dataclass(frozen=True)
class ProbeResult:
    """One finished answer: ``status`` is ``done`` (the game mod's ``ok``)
    or ``refused`` (then ``reason`` is its refusal, e.g. panel_lease_missing)."""

    probe_id: str
    session: str
    status: str
    reason: str
    items: int
    entries: dict[str, ProbeEntry] = field(default_factory=dict)

    @property
    def finished(self) -> bool:
        # The game mod publishes a probe only once it is fully answered.
        return self.status in {"done", "refused"}


def _int(value: str | None, *, unknown: tuple[str, ...] = ()) -> int:
    """A decimal; the listed words (``unknown``, ``none``) read as 0."""
    text = str(value if value is not None else "").strip()
    if text in unknown:
        return 0
    if not _INT.fullmatch(text):
        raise ProbeError(f"bad number {text[:20]!r}")
    return int(text)


def parse_probe_entry(value: str) -> ProbeEntry:
    """``<state>|<count>|<max>|<addable_now>`` as SBLiveAddNative writes it."""
    parts = str(value or "").split("|")
    if len(parts) != 4:
        raise ProbeError(f"bad item answer {str(value)[:40]!r}")
    state = parts[0].strip()
    if state not in PROBE_STATES:
        raise ProbeError(f"unknown item state {state[:24]!r}")
    entry = ProbeEntry(
        state=state,
        count=_int(parts[1], unknown=("unknown",)),
        max=_int(parts[2], unknown=("unknown", "none")),
        addable_now=_int(parts[3]),
    )
    if entry.addable_now and state != "available":
        raise ProbeError("only an available item can be added now")
    return entry


def parse_probe_result(
    text: str,
    *,
    expected_probe_id: str,
    expected_session: str,
    catalog_aliases: Iterable[str],
) -> ProbeResult:
    """Parse and bind a result file to one request and one live session.

    Raises ``ProbeError`` for anything that is not exactly the answer to this
    request in this session. A malformed item line, or a file without its
    closing ``end=1``, rejects the whole file: a half-trusted answer never
    labels a row. Items the panel's catalog does not know are ignored (the
    game mod may answer more than the panel shows).
    """
    if len(text) > PROBE_RESULT_MAX_BYTES:
        raise ProbeError("result too large")
    known = {str(alias).lower(): str(alias) for alias in catalog_aliases}
    header: dict[str, str] = {}
    entries: dict[str, ProbeEntry] = {}
    answered: set[str] = set()
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if header.get("end") is not None:
            raise ProbeError("a line after the end marker")
        key, sep, value = line.partition("=")
        key = key.strip()
        if not sep:
            raise ProbeError(f"bad line {line[:40]!r}")
        if key.startswith("item."):
            alias = key[5:]
            if not _SAFE_ALIAS.fullmatch(alias):
                raise ProbeError("unsafe item identifier in the answer")
            if alias.lower() in answered:
                raise ProbeError(f"two answers for {alias[:40]!r}")
            answered.add(alias.lower())
            entry = parse_probe_entry(value)
            canonical = known.get(alias.lower())
            if canonical is not None:
                entries[canonical] = entry
        elif key in header:
            raise ProbeError(f"repeated key {key[:40]!r}")
        else:
            header[key] = value.strip()
    if header.get("protocol") != PROBE_PROTOCOL or header.get("module") != PROBE_MODULE:
        raise ProbeError("not a probe answer")
    if header.get("end") != "1":
        raise ProbeError("an unfinished answer")
    probe_id = header.get("probe_id", "")
    if not expected_probe_id or probe_id != expected_probe_id:
        raise ProbeError("answer to another request")
    session = header.get("session", "")
    if not _SAFE_SESSION.fullmatch(session) or session != expected_session:
        raise ProbeError("answer from another game session")
    raw_status = header.get("status", "")
    items = _int(header.get("items"))
    if raw_status == "ok":
        if len(answered) != items:
            raise ProbeError("a finished answer is missing items")
        return ProbeResult(probe_id, session, "done", "", items, entries)
    if not _REFUSAL.fullmatch(raw_status) or raw_status == "none":
        raise ProbeError(f"bad status {raw_status[:24]!r}")
    if items or answered:
        raise ProbeError("a refusal carries no items")
    return ProbeResult(probe_id, session, "refused", raw_status, 0, {})


                                                                             
                                                                     
                                                                        
                                                                             
                                                                              
                                                                         
                                                                             
AUTO_LEVEL_UP_ALIASES = frozenset({"bodycore", "betacore", "exospinecore"})
# The reason on each one's row, naming what the game spends it on (the game's
# own item descriptions: "enhancement material for Max HP" / "for Max Beta
# Energy", "material for Exospine Socket expansion"; ExospineCore's English
# name is Omnicard).
AUTO_LEVEL_UP_REASONS = {
    "bodycore": "The game spends Body Cores on a Max HP upgrade as soon as you have enough, "
                "so they can't be added.",
    "betacore": "The game spends Beta Cores on a Max Beta Energy upgrade as soon as you have enough, "
                "so they can't be added.",
    "exospinecore": "The game spends Omnicards on an Exospine Socket expansion as soon as you have "
                    "enough, so they can't be added.",
}


def is_auto_level_up_item(alias: object) -> bool:
    return str(alias or "").strip().casefold() in AUTO_LEVEL_UP_ALIASES


def auto_level_up_reason(alias: object) -> str:
    """The plain reason an item the game spends on an upgrade can't be added."""
    return AUTO_LEVEL_UP_REASONS.get(str(alias or "").strip().casefold(), AUTO_LEVEL_UP_REASON)


def item_chip(
    row: Mapping[str, object],
    entry: ProbeEntry | None,
    *,
    route_ready: bool,
    mode: str,
    answered_all: bool = False,
) -> tuple[str, str]:
    """(chip, reason) for one LISTED catalog row.

    ``mode`` is ``probe`` (a v0.5 game mod), ``legacy`` (a trusted older game
    mod that can add only its embedded allowlist; ``row['legacy']`` says
    whether this item is on it) or ``none`` (no usable game mod: the status
    card explains, rows stay quiet). ``entry`` is this item's probe answer and
    ``answered_all`` whether a finished full probe has been read this session.

    The chip is "" when nothing specific is known, for example while the game
    is closed: a row is never called Ready before the whole route is ready.
    """
    if bool(row.get("dlc")):
        return CHIP_NEEDS_DLC, DLC_REASON
    if mode in ("probe", "legacy") and is_auto_level_up_item(row.get("alias")):
        # Whatever the game mod answers: 0.5.0 would still send it.
        return CHIP_NOT_AVAILABLE, auto_level_up_reason(row.get("alias"))
    if mode == "legacy":
        if not bool(row.get("legacy")):
            return CHIP_NOT_AVAILABLE, LEGACY_REASON
        return (CHIP_READY, "") if route_ready else ("", "")
    if mode != "probe":
        return "", ""
    if entry is None:
        if answered_all:
            return CHIP_NOT_AVAILABLE, NOT_ALLOWED_REASON
        return "", ""
    if entry.state == "available":
        if entry.addable_now <= 0:
            return CHIP_AT_LIMIT, _STATE_CHIPS["at_limit"][1]
        return (CHIP_READY, "") if route_ready else ("", "")
    if entry.state == "not_read":
        return "", ""
    return _STATE_CHIPS.get(entry.state, (CHIP_NOT_AVAILABLE, NOT_ALLOWED_REASON))


def per_add_limit(row: Mapping[str, object], entry: ProbeEntry | None, *, mode: str) -> int:
    """Largest quantity one add may ask for now: the catalog tier, bounded by
    what the game mod says it would send (probe) or the v3 route's 99."""
    if is_auto_level_up_item(row.get("alias")):
        return 0
    try:
        tier = int(row.get("max") or 0)
    except (TypeError, ValueError):
        tier = 0
    if tier <= 0:
        return 0
    if mode == "legacy":
        return min(tier, 99)
    if mode == "probe":
        if entry is None or entry.state != "available":
            return 0
        return max(0, min(tier, entry.addable_now))
    return 0
