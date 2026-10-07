"""Instant Boss Restart: the panel side of the SBInstantBossRestart game mod.

The game mod (UE4SS Lua, ``Mods/SBInstantBossRestart``; source
``GameMods/SBInstantBossRestart`` in this repository) does the restart inside
the game: after a death in a supported boss fight the player presses the
game's own Revive (any key or controller button), the game mod holds the
screen black, puts Eve at the arena's intro trigger with the game's own warp
and lets the boss intro play. It never presses anything itself.

The panel owns two things:

* the switch, ``settings.txt`` in the game mod's folder (``enabled=0`` turns
  it off, a missing file or any other value is on). The game mod reads it at
  every death, so the switch works right away, also while the game runs;
* the card's words, from ``status.txt``, which the game mod writes at load and
  whenever a value changes (never on a timer): version, state (``ready``,
  ``needs_update`` for another game build, ``no_game_file``), switch, phase of
  the death cycle, restarts so far and how the last cycle ended. A status
  counts only when it is complete (``end=1``) and was written in this game
  session (``loaded`` is not older than the game process).
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from infrastructure.native_files import replace_file

from services.native_status import (
    GAME_CLOSED_TEXT,
    GAME_UPDATED_TEXT,
    NATIVE_NEEDS_UPDATE,
    NATIVE_OFF,
    NATIVE_READY,
    NATIVE_UNSAFE,
    NATIVE_WAITING,
    NO_REPORT_TEXT,
    READY_TEXT,
    UNSAFE_TEXT,
    NativeVerdict,
    parse_status_text,
)

MOD_FOLDER = "SBInstantBossRestart"
IBR_VERSION = "0.5.2"
# Exact approved Scripts/main.lua (LF line endings), lower-case SHA-256 ->
# version. 0.5.0 adds learned story restarts behind the same panel switch.
# Keep the previous approved release recognizable during an upgrade.
IBR_SCRIPT_BUILDS: dict[str, str] = {
    "c0038fa0049d725be181033c8be8ab38010a4b6589ccc1b228cfd6a156d7870f": "0.5.0",
    "5ea3fbc1ed63759227a9e0910e23f569a223e99f0f69c0373a6ed463b8ed9739": "0.5.1",
    "05df982f0e0fcbb5874ba7e1e99fdb6e3275fe63eefe1facc4f0e565fa85e815": "0.5.1",
    "714654138c6cb50aa10f9d764a5bf77d0a4f87fc3b91551621df21b0cdccbd17": IBR_VERSION,
    "480a2bef16b899888e3f559e6203136292472dc52ef87115334afdd0426829bc": "0.5.2",
    "a5bced90de2d1ee86c5a2f4c61330d5e8d0a184ce4c80b35542f8d956d4e98a1": "0.5.2",
    "b5b7b197fa10a48a210ac7fb922dc66053f9b9b0937f093905ffe2776e2ceaef": "0.5.2",
    "e852711c51ecd7a59a880bfd4ffe96988e80ddd52d3d2491b69ad4f62b2e3549": "0.5.2",
    "eff780b966566ce236701735b8df8fb8bb7d3dbb92e7d5c45fa99c57a0b6739b": "0.5.2",
    "b89ec5bdca271c3109c5dfa4574e2a58f422ddf2830f7771305835a06c9a9e28": "0.5.2",
    "4611281114b88d58adb217255f9f79ba0d18b79caaeb7c5b203980c142df0ee0": "0.5.2",
    "c644d53375def8579b43b1de06c0e9bf9317aff6bcf6801b950f7d1f03c112c5": "0.5.2",
    "93b6d1614ccce1202decd1cb0b8a53607c199d051723d64484d5fa4d9a0279cd": "0.5.2",
    "98f735e2caabe30e5c01ee31a167648143106f03ea22f9371cf3912e6763b164": "0.5.2",
    "073d5447277bb5774263bfde4297679ab589ffb2398d53799c62ceddbc2a8674": "0.5.2",
}
# Lua BUILD_SHA is SHA256 of exact source bytes with its single 64-hex value
# zeroed. This avoids a circular self-hash; installed whole-file SHA remains
# the trust-map key. Status build carries the first12 normalized hex characters.
IBR_BUILD_IDENTITIES: dict[str, str] = {
    "5ea3fbc1ed63759227a9e0910e23f569a223e99f0f69c0373a6ed463b8ed9739": "A7AA7909E8F8",
    "05df982f0e0fcbb5874ba7e1e99fdb6e3275fe63eefe1facc4f0e565fa85e815": "1846A36C64F7",
    "714654138c6cb50aa10f9d764a5bf77d0a4f87fc3b91551621df21b0cdccbd17": "EE51CE489869",
    "480a2bef16b899888e3f559e6203136292472dc52ef87115334afdd0426829bc": "5ED3F915B3FF",
    "a5bced90de2d1ee86c5a2f4c61330d5e8d0a184ce4c80b35542f8d956d4e98a1": "97023128DDA7",
    "b5b7b197fa10a48a210ac7fb922dc66053f9b9b0937f093905ffe2776e2ceaef": "799943A8CDD8",
    "e852711c51ecd7a59a880bfd4ffe96988e80ddd52d3d2491b69ad4f62b2e3549": "B8F14078CFDB",
    "eff780b966566ce236701735b8df8fb8bb7d3dbb92e7d5c45fa99c57a0b6739b": "30D596B52F18",
    "b89ec5bdca271c3109c5dfa4574e2a58f422ddf2830f7771305835a06c9a9e28": "F419FAA28B48",
    "4611281114b88d58adb217255f9f79ba0d18b79caaeb7c5b203980c142df0ee0": "AB2CAD40DA40",
    "c644d53375def8579b43b1de06c0e9bf9317aff6bcf6801b950f7d1f03c112c5": "561E767A2F29",
    "93b6d1614ccce1202decd1cb0b8a53607c199d051723d64484d5fa4d9a0279cd": "A24CBF782DD7",
    "98f735e2caabe30e5c01ee31a167648143106f03ea22f9371cf3912e6763b164": "F20823E14FFF",
    "073d5447277bb5774263bfde4297679ab589ffb2398d53799c62ceddbc2a8674": "7434C98B2C35",
}
TRUSTED_IBR_SCRIPT_SHA256 = frozenset(IBR_SCRIPT_BUILDS)

SCRIPT_RELATIVE = Path("Scripts") / "main.lua"
MARKER_NAME = "enabled.txt"
SETTINGS_NAME = "settings.txt"
STATUS_NAME = "status.txt"
LOG_NAME = "SBInstantBossRestart.log"
PREVIOUS_LOG_NAME = "SBInstantBossRestart.previous.log"

# The death cycle while the screen is black: Revive accepted, Eve respawned
# and settling, warped into the intro trigger, intro camera about to show.
RESTART_PHASES = frozenset({"reviving", "settle", "intro_wait", "intro_cam", "native_fight_wait"})
# UE4SS starts its mods a second or two after the game process; a game mod
# that has not written its status this long after the start did not start.
REPORT_GRACE_SEC = 90.0
SESSION_SLACK_SEC = 5.0
STATUS_MAX_BYTES = 16 * 1024

OFF_LINE = "Off. Revive works as normal."
READY_LINE = "On. Works in supported Boss Challenge and learned story boss fights."
RESTARTING_LINE = "Restarting: the screen stays black while the fight resets."
NOT_INSTALLED_LINE = "Its game mod isn't installed. Reinstall the Mod Suite to use it."
RESTART_GAME_LINE = "Restart Stellar Blade once to start it."
DID_NOT_START_LINE = (
    "No report has been received for this game session. The panel cannot confirm it started. "
    "Check Technical details on Support."
)
# How the last death cycle ended when it was the game's normal respawn
# (status.txt last=...), in player words.
FALLBACK_REASONS = {
    "native_respawn": "the game reset the fight itself",
    "no_intro": "this fight's start isn't known yet",
    "not_settled": "Eve didn't come to a stop after Revive",
    "intro_not_seen": "the boss intro didn't start",
    "revive_timeout": "the game took too long to revive",
    "warp_failed": "Eve couldn't be moved to the fight",
    "watchdog": "the restart took too long",
    "died_again": "the death screen came back",
    "intro_off": "the intro restart is turned off in its settings",
}
# These results can follow a submitted warp; they do not prove a normal respawn.
ATTEMPT_RESULTS = {
    "fight_unconfirmed": "The encounter was not confirmed.",
    "attempt_invalid": "The restart attempt was canceled.",
}


@dataclass(frozen=True)
class IbrInstall:
    installed: bool
    trusted: bool
    version: str
    marker: bool
    identity: str


@dataclass(frozen=True)
class IbrCard:
    verdict: NativeVerdict
    enabled: bool
    ready: bool
    restarting: bool
    restarts: int
    line: str
    detail: str
    last: str
    last_at: int
    loaded: int
    technical_detail: str = ""


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def read_switch(mod_dir: Path) -> bool:
    """The switch as the game mod reads it: only ``enabled=0`` turns it off."""
    try:
        text = (Path(mod_dir) / SETTINGS_NAME).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return True
    on = True
    for raw in text.splitlines():
        key, sep, value = raw.partition("=")
        if sep and key.strip() == "enabled":
            on = value.strip().split("#", 1)[0].strip() != "0"
    return on


def write_switch(mod_dir: Path, on: bool) -> None:
    """Set ``enabled=`` in settings.txt, keeping every other line (LF).

    Written to a temporary file and renamed over the old one (POSIX rename,
    so a read by the game mod at that moment neither fails nor sees half a
    file). Raises OSError when the folder can't be written.
    """
    folder = Path(mod_dir)
    path = folder / SETTINGS_NAME
    wanted = f"enabled={1 if on else 0}"
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except FileNotFoundError:
        lines = []
    out: list[str] = []
    replaced = False
    for raw in lines:
        key, sep, _value = raw.partition("=")
        if sep and key.strip() == "enabled":
            if not replaced:
                out.append(wanted)
                replaced = True
            continue
        out.append(raw)
    if not replaced:
        out.append(wanted)
    temporary = folder / (SETTINGS_NAME + ".tmp")
    temporary.write_bytes(("\n".join(out) + "\n").encode("utf-8"))
    replace_file(temporary, path)


def ensure_marker(mod_dir: Path) -> bool:
    """Create the UE4SS ``enabled.txt`` of an installed game mod; True if created."""
    folder = Path(mod_dir)
    marker = folder / MARKER_NAME
    if marker.is_file() or not (folder / SCRIPT_RELATIVE).is_file():
        return False
    marker.write_bytes(b"")
    return True


def inspect_install(mod_dir: Path) -> IbrInstall:
    folder = Path(mod_dir)
    script = folder / SCRIPT_RELATIVE
    marker = (folder / MARKER_NAME).is_file()
    if not script.is_file():
        return IbrInstall(False, False, "", marker, "missing")
    try:
        digest = _sha256_file(script)
    except OSError as exc:
        return IbrInstall(True, False, "", marker, f"unreadable:{type(exc).__name__}")
    version = IBR_SCRIPT_BUILDS.get(digest, "")
    return IbrInstall(True, bool(version), version, marker, digest)


def read_status(mod_dir: Path) -> dict[str, str] | None:
    """status.txt when complete (``end=1``), else None."""
    path = Path(mod_dir) / STATUS_NAME
    try:
        if path.stat().st_size > STATUS_MAX_BYTES:
            return None
        values = parse_status_text(path.read_text(encoding="utf-8", errors="replace"))
    except OSError:
        return None
    return dict(values) if values.get("end") == "1" else None


def _int(values: Mapping[str, str], key: str) -> int:
    try:
        return max(0, int(str(values.get(key, "0")).strip()))
    except ValueError:
        return 0


class IbrFiles:
    """The game mod's files, read again only when they change."""

    def __init__(self, mod_dir: Path) -> None:
        self.mod_dir = Path(mod_dir)
        self._install_key: tuple | None = None
        self._install: IbrInstall | None = None
        self._status_key: tuple | None = None
        self._status: dict[str, str] | None = None

    @staticmethod
    def _key(path: Path) -> tuple:
        try:
            info = path.stat()
        except OSError:
            return ("missing",)
        return (info.st_mtime_ns, info.st_size)

    def install(self) -> IbrInstall:
        key = (self._key(self.mod_dir / SCRIPT_RELATIVE), (self.mod_dir / MARKER_NAME).is_file())
        if key != self._install_key or self._install is None:
            self._install = inspect_install(self.mod_dir)
            self._install_key = key
        return self._install

    def status(self) -> dict[str, str] | None:
        key = self._key(self.mod_dir / STATUS_NAME)
        if key != self._status_key:
            self._status = read_status(self.mod_dir)
            self._status_key = key
        return self._status

    def switch(self) -> bool:
        return read_switch(self.mod_dir)


def ibr_card(
    install: IbrInstall,
    switch_on: bool,
    status: Mapping[str, str] | None,
    *,
    game_running: bool,
    game_started_at: float | None,
    now: float,
) -> IbrCard:
    """The card's verdict, one line and Support line from the game mod's files."""
    session = None
    if game_running and status is not None:
        loaded = _int(status, "loaded")
        if game_started_at is None or loaded >= game_started_at - SESSION_SLACK_SEC:
            session = status
    if not install.installed:
        verdict = NativeVerdict(NATIVE_OFF, NOT_INSTALLED_LINE, "not-installed")
    elif install.identity.startswith("unreadable:"):
        verdict = NativeVerdict(NATIVE_UNSAFE, "Its game mod file could not be read. The panel cannot verify it; it may still run. Check Technical details on Support.", install.identity)
    elif not install.trusted:
        verdict = NativeVerdict(NATIVE_UNSAFE, "Its installed file is not approved, so the panel cannot check it. It may still restart boss fights. Reinstall the Mod Suite to restore the approved file.", f"untrusted:{install.identity[:12]}")
    elif not game_running:
        verdict = NativeVerdict(NATIVE_WAITING, GAME_CLOSED_TEXT, "game-closed")
    elif session is None:
        if not install.marker:
            verdict = NativeVerdict(NATIVE_WAITING, RESTART_GAME_LINE, "not-loaded-this-session",
                                    label_text="Restart game")
        elif game_started_at is None or now - game_started_at < REPORT_GRACE_SEC:
            verdict = NativeVerdict(NATIVE_WAITING, NO_REPORT_TEXT, "waiting-for-report")
        else:
            verdict = NativeVerdict(NATIVE_UNSAFE, DID_NOT_START_LINE, "no-report")
    elif install.version in ("0.5.1", IBR_VERSION) and (
        session.get("version") != install.version
        or not IBR_BUILD_IDENTITIES.get(install.identity)
        or session.get("build") != IBR_BUILD_IDENTITIES.get(install.identity)
    ):
        verdict = NativeVerdict(NATIVE_UNSAFE, "The loaded game mod does not match the approved file. Restart the game after updating the Mod Suite.", "loaded-build-mismatch")
    elif session.get("state") == "needs_update":
        verdict = NativeVerdict(NATIVE_NEEDS_UPDATE, GAME_UPDATED_TEXT, "game-build-mismatch")
    elif session.get("state") == "ready":
        verdict = NativeVerdict(NATIVE_READY, READY_TEXT, "ready")
    else:
        verdict = NativeVerdict(NATIVE_UNSAFE, UNSAFE_TEXT, f"state-{session.get('state', '')}")

    values = session or {}
    phase = str(values.get("phase", "idle"))
    restarts = _int(values, "restarts")
    last = str(values.get("last", "none"))
    ready = verdict.ready
    restarting = bool(ready and switch_on and phase in RESTART_PHASES)
    broken = verdict.state in (NATIVE_OFF, NATIVE_UNSAFE, NATIVE_NEEDS_UPDATE)
    if not switch_on and not broken:
        line = OFF_LINE
    elif not ready:
        line = verdict.detail
    elif restarting:
        line = RESTARTING_LINE
    else:
        if last in ATTEMPT_RESULTS:
            line = f"On. {ATTEMPT_RESULTS[last]}"
        elif last in FALLBACK_REASONS:
            line = f"On. The last Revive used the normal respawn: {FALLBACK_REASONS[last]}."
        else:
            line = "On. Works in Boss Challenge fights." if install.version == "0.4.0" else READY_LINE
        if restarts:
            line += f" Restarts so far: {restarts}."
    technical_detail = (
        f"{MOD_FOLDER} {install.version or '(not approved)'} [{install.identity[:12]}]: {verdict.reason}; "
        f"switch {'on' if switch_on else 'off'}; phase {phase}; restarts {restarts}; last {last}"
    )
    installed_text = (f"Game mod {install.version} installed" if install.trusted else
                      "Game mod file not approved" if install.installed else "Game mod not installed")
    if install.identity.startswith("unreadable:"):
        installed_text = "Game mod file could not be read"
    if install.installed and not install.identity.startswith("unreadable:"):
        installed_text += f" [{install.identity[:12]}]"
    detail = installed_text + f"; switch {'on' if switch_on else 'off'}. "
    if not game_running:
        detail += "Game closed; no current session report."
    elif session is None:
        detail += "Current session report not received."
    else:
        detail += verdict.detail
        if ready:
            detail += f" Restarts this session: {restarts}. "
            detail += "Fight resetting." if restarting else "Waiting for a supported fight."
            if last in ATTEMPT_RESULTS:
                detail += f" Last restart: {ATTEMPT_RESULTS[last]}"
            elif last in FALLBACK_REASONS:
                detail += f" Last Revive used normal respawn: {FALLBACK_REASONS[last]}."
    return IbrCard(
        verdict=verdict,
        enabled=bool(switch_on),
        ready=ready,
        restarting=restarting,
        restarts=restarts,
        line=line,
        detail=detail,
        last=last,
        last_at=_int(values, "last_at"),
        loaded=_int(values, "loaded"),
        technical_detail=technical_detail,
    )
