from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Mapping

from infrastructure.native_files import replace_file
from services.native_status import (
    NATIVE_NEEDS_UPDATE,
    NATIVE_OFF,
    NATIVE_READY,
    NATIVE_UNSAFE,
    NATIVE_WAITING,
    NativeVerdict,
    NativeStatusSnapshot,
    file_is_superseded,
    file_sha256,
    native_verdict,
    reports_build_mismatch,
    reports_current_build,
)

GOD_FILES = (
    "EveStanceNoDamage_P.pak",
    "EveStanceNoDamage_P.ucas",
    "EveStanceNoDamage_P.utoc",
)

GOD_PENDING_DISABLE_FLAG = "god_paks_pending_disable.flag"
GOD_PENDING_ENABLE_FLAG = "god_paks_pending_enable.flag"
NATIVE_GOD_STATE_FILE = "native_god_state.txt"
# Exact SBGodNative builds the panel may enable and drive. Membership here also
# lets the hook-free profile create Mods/SBGodNative/enabled.txt, so only builds
# that gate on the current game before touching any game code belong here.
TRUSTED_GOD_NATIVE_SHA256 = frozenset(
    {
                                                                               
                                                                        
                                                                             
                                                                             
                                                                               
                                                                    
        "e7693771222de1bacceef26ce9a664d6f2face8bdd0588c9684ada9c1ff7b11e",
                                                                           
                                                                            
                                                                            
                                                                             
                                                                               
                                                                               
        "4291b6a1be4840c7bb052c59ab6706e8286271ac8ca29dc21715c8c0c522de67",
                                                                         
                                                                            
                                                                          
                                                                             
                                                                          
                                                                        
                                                                             
                                                                        
                                                                            
                           
        "1b14b860fe110060c0df36a76e0866fa0681620ce88642431c1a1f69b4d31a46",
                                                                           
                                                                               
                                                                              
                                                                         
                                                                             
                                                                            
                                                                            
                                                                             
                                                                             
                                                                       
                                                                   
                                                                           
                                                           
                                                                              
                                                 
        "d6ea85af6bb4c6a0d1e0c62095308d05b340f13db847771cc4c9795b6bbebbfe",
                                                                           
                                                                                 
                                                                              
                                                                           
                                                                                                
                                                                            
                                                                          
                                                                         
                                                                              
                                                                       
                                                                    
                                                                        
                                                                         
                                                                             
                                                                     
        "7ac22db46d2805eed918fb019127665e30d01e157c6014544dc9f5bea494cc3b",
                                                                  
                                                                       
                                                                     
                                                                         
                                                                    
                                                                    
                                                       
                                                                         
                                                                        
                                   
        "3761f9844a8915d8237da0344b10ead5a559a33b43932dba192e79b49242428a",
                                                                        
                                                                       
                                                                          
                                                                           
                                                                         
        "fa0c2d38ed572599fa4ecd8a42af54c403ca4b010740b3bdeb42e1802ad83667",
        # Diagnostic-only v1.3.3 read-only death-path probe startup repair; exact
        # build retains the shipping guards and protocol 1. No other probe
        # or variant is enabled by this pin; live protection is unverified.
        "3180c0141c085bdc10f2f13ba45828a14f51032a09a99f335a8500dc5bdb3b6a",
                                                                              
        "04f8fa438b5e52563fc015c42116fec4780bb1733aac7dd47caaf58adcd790c4",
                                                                                    
        "f3b0e52a114018c18de37e7f56d530e277b11fdb44abda2c29429f93473c2643",
    }
)
# Earlier builds made for the previous game build (1.4.1, 0x68C46FBF/0x1416C000).
# They are never trusted: the card shows "Needs update" and the hook-free
# profile keeps them disabled.
SUPERSEDED_GOD_NATIVE_SHA256 = frozenset(
    {
                                                                         
                                                                             
                                                                             
                                                                            
        "bafcd5f5afa09dfda28c9e2bc916cacf099a94b429f3fd7dd653b4ce66c4bd14",
    }
)
# The heartbeat version written by the newest trusted build above.
GOD_NATIVE_VERSION = "1.3.5"
# Heartbeat versions written by the trusted builds above. The installed
# Approved v1.3.2 and earlier builds stay accepted so a partial install
# never reads as untrusted.
GOD_NATIVE_VERSIONS = frozenset({"1.1.0", "1.1.2", "1.2.1", "1.3.0", "1.3.1", "1.3.2", "1.3.3", "1.3.4", GOD_NATIVE_VERSION})
# God is on in the panel but the native has not armed it (self-check pending).
# The game is running, so the card must not say "Waiting for game".
GOD_SELF_CHECK_REASON_PREFIX = "self-check-"
GOD_SELF_CHECK_LABEL = "Safety check"
GOD_SELF_CHECK_WAITING_TEXT = (
    "Checking that it is really Eve before protection starts. "
    "She can take damage until the card shows Active."
)
# The self-check has passed but the native has not armed God yet (it arms on
# its next game-thread tick). Saying "safety check in your first fight" here
# would be wrong: the check is already done.
GOD_SELF_CHECK_PASSED_REASON = GOD_SELF_CHECK_REASON_PREFIX + "pass"
GOD_ARMING_LABEL = "Switching on"
GOD_ARMING_TEXT = "Safety check passed. God Mode is switching on now."
# SBGodNative 1.3.0+ reports a proof field. A matching proof is evidence of
# identity; absent/failed proof gives no deadline for protection. Normal
# corroboration may still arm before combat. Neither path guarantees a hit.
GOD_FAST_ARM_VERSIONS = frozenset({"1.3.0", "1.3.1", "1.3.2", "1.3.3", "1.3.4", "1.3.5"})
GOD_FAST_ARM_PROOF_MATCH = "match"
GOD_FAST_ARM_PROOF_NOT_CHECKED = "not_checked"
GOD_SELF_CHECK_FAST_TEXT = "The game confirmed Eve's identity. Protection is pending until the safety check passes and Active appears."
GOD_SELF_CHECK_PENDING_TEXT = (
    "Checking that it's really Eve. Load your save and play normally; "
    "God Mode switches on as soon as the check passes."
)
# 1.3.0+ keeps watching after it arms: a hit that reached Eve anyway is
# reported as god_protection=damage_got_through. God stays requested on, but the card must not claim Active.
# This warning is incomplete history and does not prove repair succeeded. 1.3.0 also reported every dip it repaired on the
# next tick; 1.3.1 reports only real HP loss (still below the floor after
# the repair, or a death command for Eve), so the warning is truthful.
GOD_DAMAGE_GOT_THROUGH_REASON = "damage-got-through"
GOD_DAMAGE_GOT_THROUGH_LABEL = "Protection warning"
GOD_DAMAGE_GOT_THROUGH_TEXT = (
    "God Mode reported unrepaired health loss or a death command for Eve. "
    "Protection may be incomplete this session. Please share a bug report."
)
# native_heartbeat.txt is rewritten continuously while the game runs.
GOD_HEARTBEAT_MAX_AGE_SEC = 15.0

# ---- Unlimited Beta / Burst energy ------------------------------------------
# Two more switches of the God Mode game mod, independent of godlive. They are
# two lines in native_god_state.txt. The game mod reads them strictly: a key
# counts only at the start of a line, ON is exactly the value "1", and a
# missing line or a key written twice is OFF.
ENERGY_STATE_KEYS = ("betalive", "burstlive")
# A third line the game mod also reads. The panel never writes it, so every
# panel write of the state file leaves it OFF.
ENERGY_TOPUP_KEY = "energytopup"
# The game mod refuses a larger state file and keeps its last values.
NATIVE_GOD_STATE_MAX_BYTES = 4096
# The game mod reads a line through a 256-byte buffer: 254 characters and the
# line end. It reads a longer line in pieces, and a later piece can start with
# godlive=. No panel write makes such a line; an energy write refuses a file
# that has one (only made by hand) instead of guessing what it means.
NATIVE_GOD_STATE_LINE_MAX = 254
# Exact SBGodNative builds that have the two energy switches. Empty until
# such a build is trusted above: add its hash to both lists together. While
# the installed file is not listed here the card says "Needs update" and both
# switches stay off. A running game must prove it as well (ENERGY_IDS).
ENERGY_GOD_NATIVE_SHA256: frozenset[str] = frozenset({"f3b0e52a114018c18de37e7f56d530e277b11fdb44abda2c29429f93473c2643"})
# The energy record is the last block of the god_fast_arm heartbeat value and
# starts with this field. A report without it comes from a build without the
# switches; an id that is not listed here is a record this panel cannot read.
ENERGY_ID_FIELD = "energy_id"
ENERGY_IDS = frozenset({"beta-burst-r1"})
# Card states (the chip) of the Unlimited energy card.
ENERGY_OFF = "off"
ENERGY_WAITING = "waiting"
ENERGY_ACTIVE = "active"
ENERGY_UNSAFE = "unsafe"
ENERGY_NEEDS_UPDATE = "needs_update"
# energy_state words that mean the game mod stopped itself (never "Active").
ENERGY_STOP_STATES = ("stopped", "identity_check_failed", "hooks_not_installed")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def trusted_native_god(dll_path: Path) -> tuple[bool, str]:
    """Return whether the exact God Mode DLL is approved for auto-enable."""
    path = Path(dll_path)
    if not path.is_file():
        return False, "missing"
    try:
        identity = _sha256_file(path)
    except OSError as exc:
        return False, f"hash-{type(exc).__name__}"
    return identity in TRUSTED_GOD_NATIVE_SHA256, identity


def superseded_native_god(dll_path: Path) -> bool:
    """True when the installed God DLL is a known build for an earlier game."""
    return file_is_superseded(Path(dll_path), SUPERSEDED_GOD_NATIVE_SHA256)


def _write_ascii_atomic(path: Path, text: str) -> None:
    """Replace a small state file without exposing a partially written body."""
    _write_bytes_atomic(path, text.encode("ascii"))


def _write_bytes_atomic(path: Path, body: bytes) -> None:
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as stream:
            temporary = Path(stream.name)
            stream.write(body)
            stream.flush()
            os.fsync(stream.fileno())
        # A12: POSIX-semantics rename, retried 5 x 20 ms on a sharing
        # conflict, so a God toggle no longer fails with PermissionError
        # while SBGodNative is reading the state file.
        replace_file(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def read_native_god_state(mod_root: Path) -> dict[str, int]:
    path = mod_root / NATIVE_GOD_STATE_FILE
    out = {"godlive": 0, "playerguid": 0, "actorptr": 0, "bagptr": 0}
    if not path.is_file():
        return out
    for line in path.read_text(encoding="ascii", errors="ignore").splitlines():
        if line.startswith("godlive="):
            out["godlive"] = 1 if line.split("=", 1)[1].strip() in ("1", "true", "True") else 0
        elif line.startswith("playerguid="):
            try:
                out["playerguid"] = int(line.split("=", 1)[1].strip(), 10)
            except ValueError:
                pass
        elif line.startswith("actorptr="):
            try:
                out["actorptr"] = int(line.split("=", 1)[1].strip(), 16)
            except ValueError:
                pass
        elif line.startswith("bagptr="):
            try:
                out["bagptr"] = int(line.split("=", 1)[1].strip(), 16)
            except ValueError:
                pass
    return out


def parse_native_energy_state(raw: bytes) -> dict[str, bool]:
    """The two energy switches exactly as SBGodNative reads them.

    Same rules as its parse_energy_switches: lines end at LF (one CR before
    it is dropped), a Ctrl-Z ends the input, a key counts only at the start
    of a line, ON is exactly ``1`` and a key that appears twice is OFF.
    """
    seen = dict.fromkeys(ENERGY_STATE_KEYS, 0)
    on = dict.fromkeys(ENERGY_STATE_KEYS, False)
    for line in raw.split(b"\x1a", 1)[0].split(b"\n"):
        if line.endswith(b"\r"):
            line = line[:-1]
        for key in ENERGY_STATE_KEYS:
            prefix = key.encode("ascii") + b"="
            if line.startswith(prefix):
                seen[key] += 1
                on[key] = line[len(prefix):] == b"1"
    return {key: seen[key] == 1 and on[key] for key in ENERGY_STATE_KEYS}


def read_native_energy_state(mod_root: Path) -> dict[str, bool]:
    """``{"betalive": bool, "burstlive": bool}`` from the state file (missing = off)."""
    try:
        raw = (mod_root / NATIVE_GOD_STATE_FILE).read_bytes()
    except OSError:
        raw = b""
    return parse_native_energy_state(raw)


def _god_state_text(god_live: bool, playerguid: int, actorptr: int, bagptr: int) -> str:
    return (
        f"godlive={1 if god_live else 0}\n"
        f"playerguid={max(0, int(playerguid))}\n"
        f"actorptr={max(0, int(actorptr)):X}\n"
        f"bagptr={max(0, int(bagptr)):X}\n"
    )


def _energy_state_text(beta_live: bool, burst_live: bool) -> str:
    # Each key once, value exactly 0 or 1. energytopup is never written.
    return f"betalive={1 if beta_live else 0}\nburstlive={1 if burst_live else 0}\n"


def write_native_god_state(
    mod_root: Path,
    god_live: bool,
    playerguid: int = 0,
    actorptr: int = 0,
    bagptr: int = 0,
    *,
    beta_live: bool | None = None,
    burst_live: bool | None = None,
) -> None:
    """Push only desired state to SBGodNative, preserving live-discovered pointers.

    The two energy switches keep the value the file has (as the game mod
    reads it) unless one is given here, so a God Mode toggle never changes them.
    """
    path = mod_root / NATIVE_GOD_STATE_FILE
    existing = read_native_god_state(mod_root)
    energy = read_native_energy_state(mod_root)
    if playerguid <= 0:
        playerguid = existing["playerguid"]
    if actorptr <= 0:
        actorptr = existing["actorptr"]
    if bagptr <= 0:
        bagptr = existing["bagptr"]
    text = _god_state_text(god_live, playerguid, actorptr, bagptr) + _energy_state_text(
        energy["betalive"] if beta_live is None else bool(beta_live),
        energy["burstlive"] if burst_live is None else bool(burst_live),
    )
    _write_ascii_atomic(path, text)


def write_native_energy_state(
    mod_root: Path,
    *,
    beta_live: bool,
    burst_live: bool,
    god_live_default: bool = False,
) -> None:
    """Set the two energy switches without touching God Mode's own lines.

    Every other line of the file is written back as it is (only CR LF becomes
    LF and empty lines go), so God Mode's line means exactly what it meant.
    Old energy lines and an ``energytopup`` line are dropped; the two new
    lines go last. Only when the file has no ``godlive=`` line at all (first
    use, or the file is gone) is the usual God block written, with
    ``god_live_default`` as its switch. One atomic replace, as for God Mode.
    A file the game mod would read differently than line by line (a line over
    ``NATIVE_GOD_STATE_LINE_MAX`` characters) or would refuse (over
    ``NATIVE_GOD_STATE_MAX_BYTES``) is left alone: ``ValueError``.
    """
    path = mod_root / NATIVE_GOD_STATE_FILE
    try:
        raw = path.read_bytes()
    except OSError:
        raw = b""
    dropped = tuple(f"{key}=".encode("ascii") for key in (*ENERGY_STATE_KEYS, ENERGY_TOPUP_KEY))
    kept: list[bytes] = []
    # The game mod reads nothing after a Ctrl-Z, so nothing after it is kept.
    for line in raw.split(b"\x1a", 1)[0].split(b"\n"):
        if line.endswith(b"\r"):
            line = line[:-1]
        if len(line) > NATIVE_GOD_STATE_LINE_MAX:
            raise ValueError(f"{NATIVE_GOD_STATE_FILE} has a line of {len(line)} characters; the game mod "
                             f"reads at most {NATIVE_GOD_STATE_LINE_MAX} in one piece")
        if line and not line.startswith(dropped):
            kept.append(line)
    if any(line.startswith(b"godlive=") for line in kept):
        body = b"".join(line + b"\n" for line in kept)
    else:
        existing = read_native_god_state(mod_root)
        body = _god_state_text(
            god_live_default, existing["playerguid"], existing["actorptr"], existing["bagptr"]
        ).encode("ascii")
    body += _energy_state_text(beta_live, burst_live).encode("ascii")
    if len(body) > NATIVE_GOD_STATE_MAX_BYTES:
        raise ValueError(f"{NATIVE_GOD_STATE_FILE} would be {len(body)} bytes; the game mod reads at most "
                         f"{NATIVE_GOD_STATE_MAX_BYTES}")
    _write_bytes_atomic(path, body)


def reset_native_god_state(mod_root: Path) -> None:
    """Clear process-local pointers before a newly launched game can reuse them.

    Both energy switches are written off as well; the panel publishes the
    remembered ones again right after a game start.
    """
    path = mod_root / NATIVE_GOD_STATE_FILE
    _write_ascii_atomic(path, _god_state_text(False, 0, 0, 0) + _energy_state_text(False, False))


@dataclass(frozen=True)
class GodPakResult:
    ok: bool
    state: str
    locked: bool
    message: str


def god_files_present_count(directory: Path) -> int:
    if not directory.exists():
        return 0
    count = 0
    for name in GOD_FILES:
        if (directory / name).is_file():
            count += 1
        elif (directory / f"{name}.off").is_file():
            count += 1
    return count


def god_files_complete(directory: Path) -> bool:
    if not directory.exists():
        return False
    return all((directory / name).is_file() for name in GOD_FILES)


def _active_god_paths(paks_mods_dir: Path) -> list[Path]:
    paths: list[Path] = []
    if not paks_mods_dir.exists():
        return paths
    for path in sorted(paks_mods_dir.iterdir()):
        if path.is_file() and path.name.upper().startswith("EVESTANCENODAMAGE_P"):
            paths.append(path)
    return paths


def repair_god_file_set(paks_mods_dir: Path, disabled_paks_dir: Path) -> None:
    """Keep god pak sets consistent without changing ON/OFF intent."""
    paks_mods_dir.mkdir(parents=True, exist_ok=True)
    disabled_paks_dir.mkdir(parents=True, exist_ok=True)

    active_count = god_files_present_count(paks_mods_dir)
    disabled_count = god_files_present_count(disabled_paks_dir)
    live_names = {p.name for p in _active_god_paths(paks_mods_dir) if not p.name.endswith(".off")}

    if 0 < len(live_names) < len(GOD_FILES):
        for name in GOD_FILES:
            active = paks_mods_dir / name
            disabled = disabled_paks_dir / name
            if active.exists() and not disabled.exists():
                try:
                    shutil.copy2(active, disabled)
                except OSError:
                    pass

    if god_files_complete(paks_mods_dir) and not god_files_complete(disabled_paks_dir):
        for name in GOD_FILES:
            active = paks_mods_dir / name
            disabled = disabled_paks_dir / name
            if active.exists() and not disabled.exists():
                try:
                    shutil.copy2(active, disabled)
                except OSError:
                    pass

    if active_count == 0 and 0 < disabled_count < len(GOD_FILES):
        for name in GOD_FILES:
            disabled = disabled_paks_dir / name
            active = paks_mods_dir / name
            if not disabled.exists() and active.exists():
                try:
                    shutil.copy2(active, disabled)
                except OSError:
                    pass


def get_god_pak_state(paks_mods_dir: Path, disabled_paks_dir: Path) -> str:
    repair_god_file_set(paks_mods_dir, disabled_paks_dir)
    if god_files_complete(paks_mods_dir):
        return "on"
    for path in _active_god_paths(paks_mods_dir):
        if not path.name.endswith(".off"):
            return "on"
    if god_files_complete(disabled_paks_dir):
        return "off"
    return "missing"


def _remove_path(path: Path) -> bool:
    if not path.exists():
        return True
    try:
        path.unlink()
        return True
    except OSError:
        if path.name.endswith(".off"):
            return False
        off_path = path.with_name(path.name + ".off")
        try:
            if off_path.exists():
                off_path.unlink()
            path.rename(off_path)
            return True
        except OSError:
            return False


def set_god_paks_enabled(paks_mods_dir: Path, disabled_paks_dir: Path, enable: bool) -> GodPakResult:
    repair_god_file_set(paks_mods_dir, disabled_paks_dir)
    paks_mods_dir.mkdir(parents=True, exist_ok=True)
    disabled_paks_dir.mkdir(parents=True, exist_ok=True)

    if enable:
        if not god_files_complete(disabled_paks_dir) and not god_files_complete(paks_mods_dir):
            return GodPakResult(False, "missing", False, "God pak files are missing.")
        locked: list[str] = []
        for name in GOD_FILES:
            src = disabled_paks_dir / name
            dst = paks_mods_dir / name
            off = paks_mods_dir / f"{name}.off"
            if off.exists():
                try:
                    off.rename(dst)
                    continue
                except OSError:
                    locked.append(name)
                    continue
            if src.exists():
                try:
                    shutil.copy2(src, dst)
                except OSError:
                    locked.append(name)
        state = get_god_pak_state(paks_mods_dir, disabled_paks_dir)
        if locked:
            return GodPakResult(False, state, True, f"Could not enable god pak files (in use): {', '.join(locked)}")
        return GodPakResult(state == "on", state, False, "God pak files enabled in ~mods.")

    locked: list[str] = []
    for name in GOD_FILES:
        active = paks_mods_dir / name
        disabled = disabled_paks_dir / name
        if active.exists():
            try:
                shutil.copy2(active, disabled)
            except OSError:
                pass
    for path in _active_god_paths(paks_mods_dir):
        if not _remove_path(path):
            locked.append(path.name)
    state = get_god_pak_state(paks_mods_dir, disabled_paks_dir)
    if locked:
        return GodPakResult(
            False,
            state,
            True,
            "God pak files are still loaded because the game has them open. Fully quit Stellar Blade, then toggle God Mode OFF again or reopen the panel.",
        )
    return GodPakResult(state != "on", state, False, "God pak files removed from ~mods.")


def write_pending_disable(mod_root: Path) -> None:
    (mod_root / GOD_PENDING_DISABLE_FLAG).write_text("1\n", encoding="ascii")


def clear_pending_disable(mod_root: Path) -> None:
    (mod_root / GOD_PENDING_DISABLE_FLAG).unlink(missing_ok=True)


def pending_disable_requested(mod_root: Path) -> bool:
    return (mod_root / GOD_PENDING_DISABLE_FLAG).exists()


def apply_pending_disable(mod_root: Path, paks_mods_dir: Path, disabled_paks_dir: Path) -> GodPakResult | None:
    if not pending_disable_requested(mod_root):
        state = read_state_wants_off(mod_root)
        if not state:
            return None
    result = set_god_paks_enabled(paks_mods_dir, disabled_paks_dir, False)
    if result.ok and not result.locked:
        clear_pending_disable(mod_root)
    return result


def read_state_wants_off(mod_root: Path) -> bool:
    state_file = mod_root / "gui_state.txt"
    if not state_file.exists():
        return False
    try:
        for raw in state_file.read_text(encoding="utf-8", errors="replace").splitlines():
            if raw.startswith("godlive="):
                return raw.split("=", 1)[1].strip() != "1"
    except Exception:
        return False
    return False


def write_pending_enable(mod_root: Path) -> None:
    (mod_root / GOD_PENDING_ENABLE_FLAG).write_text("1\n", encoding="ascii")


def clear_pending_enable(mod_root: Path) -> None:
    (mod_root / GOD_PENDING_ENABLE_FLAG).unlink(missing_ok=True)


def pending_enable_requested(mod_root: Path) -> bool:
    return (mod_root / GOD_PENDING_ENABLE_FLAG).exists()


def read_state_wants_on(mod_root: Path) -> bool:
    state_file = mod_root / "gui_state.txt"
    if not state_file.exists():
        return False
    try:
        for raw in state_file.read_text(encoding="utf-8", errors="replace").splitlines():
            if raw.startswith("godlive="):
                return raw.split("=", 1)[1].strip() == "1"
    except Exception:
        return False
    return False


def restore_god_pak_backup(disabled_paks_dir: Path, mod_root: Path) -> GodPakResult | None:
    """Ensure disabled_paks holds a complete god pak set (copy from release staging if needed)."""
    disabled_paks_dir.mkdir(parents=True, exist_ok=True)
    if god_files_complete(disabled_paks_dir):
        return None
    candidates = [
        mod_root / "release" / "StellarBlade-ControlPanel-v2.5.50" / "Stellar Blade" / "SB" / "Content" / "Paks" / "~mods",
        mod_root / "release" / "StellarBlade-ControlPanel-v2.5.49" / "Stellar Blade" / "SB" / "Content" / "Paks" / "~mods",
    ]
    for src_dir in candidates:
        if not god_files_complete(src_dir):
            continue
        for name in GOD_FILES:
            src = src_dir / name
            dst = disabled_paks_dir / name
            if src.exists() and not dst.exists():
                try:
                    shutil.copy2(src, dst)
                except OSError:
                    pass
        if god_files_complete(disabled_paks_dir):
            return GodPakResult(True, "off", False, "Restored god pak backup into disabled_paks.")
    return GodPakResult(False, "missing", False, "God pak files are missing from disabled_paks and release backup.")


def prepare_live_god_mode(
    mod_root: Path,
    paks_mods_dir: Path,
    disabled_paks_dir: Path,
) -> GodPakResult | None:
    """Keep god pak files out of ~mods so live toggle works mid-session."""
    restore_god_pak_backup(disabled_paks_dir, mod_root)
    clear_pending_enable(mod_root)
    clear_pending_disable(mod_root)
    if get_god_pak_state(paks_mods_dir, disabled_paks_dir) == "on":
        return set_god_paks_enabled(paks_mods_dir, disabled_paks_dir, False)
    return None


def sync_god_paks_with_state(
    mod_root: Path,
    paks_mods_dir: Path,
    disabled_paks_dir: Path,
    game_running: bool,
) -> GodPakResult | None:
    """Live-first God Mode uses SBGodNative; fallback paks stay disabled."""
    _ = game_running
    return prepare_live_god_mode(mod_root, paks_mods_dir, disabled_paks_dir)


def apply_pending_god_pak_changes(
    mod_root: Path,
    paks_mods_dir: Path,
    disabled_paks_dir: Path,
) -> GodPakResult | None:
    """After game close, ensure god paks are not left active in ~mods."""
    return prepare_live_god_mode(mod_root, paks_mods_dir, disabled_paks_dir)


def migrate_paks_for_live_god_mode(
    mod_root: Path,
    paks_mods_dir: Path,
    disabled_paks_dir: Path,
    game_running: bool,
) -> GodPakResult | None:
    """Deprecated alias — god mode uses pak sync, not live-only pak removal."""
    return sync_god_paks_with_state(mod_root, paks_mods_dir, disabled_paks_dir, game_running)


def _flag(heartbeat: Mapping[str, str], key: str) -> str:
    return str(heartbeat.get(key, "")).strip()


def god_heartbeat_proves_hooks(heartbeat: Mapping[str, str]) -> bool:
    """True only when the God native says its hooks are installed on THIS game.

    Contract for SBGodNative v1.1.0 heartbeats (``native_heartbeat.txt``):

    * ``version=1.1.0``, ``hooks_installed=1`` and ``validation_all_ok=1`` -
      every hook window, anchor and TaskGraph site was byte-validated and the
      hooks were installed.
    * ``build=6A6A3B74/15981000`` (TimeDateStamp/SizeOfImage of the running
      SB-Win64-Shipping.exe; ``0x`` prefixes and ``exe_timestamp``/
      ``exe_image_size`` are also accepted) with ``build_ok=1``.
    * ``dispatch_poisoned=0`` - the GameThread dispatch has not faulted.
    * ``selfcheck`` is not ``fail`` - the runtime GUID-offset check has not
      disproved the actor layout (``pending`` is fine: God simply stays
      disarmed until it passes).

    Older builds that report none of this prove nothing, however many
    ``blocks`` they count, because their counters can move without any hook
    installed.
    """
    return (
        _flag(heartbeat, "hooks_installed") == "1"
        and _flag(heartbeat, "version") in GOD_NATIVE_VERSIONS
        and reports_current_build(heartbeat)
        and not reports_build_mismatch(heartbeat)
        and _flag(heartbeat, "build_ok") == "1"
        and _flag(heartbeat, "validation_all_ok") == "1"
        and _flag(heartbeat, "dispatch_poisoned") == "0"
        and _flag(heartbeat, "selfcheck").lower() != "fail"
    )


def god_heartbeat_armed(heartbeat: Mapping[str, str]) -> bool:
    """True only while the native itself reports God armed after its self-check.

    ``godlive`` echoes the panel's desired state (the Boss Auto Retry
    precondition reads it), so it never proves protection on its own.
    """
    return (
        god_heartbeat_proves_hooks(heartbeat)
        and _flag(heartbeat, "god_armed") == "1"
        and _flag(heartbeat, "selfcheck").lower() == "pass"
    )


def god_fast_arm_proof(heartbeat: Mapping[str, str]) -> str:
    """The ``proof`` field of SBGodNative 1.3.0's ``god_fast_arm`` key ("" if absent)."""
    for part in _flag(heartbeat, "god_fast_arm").split(";"):
        name, sep, value = part.partition(":")
        if sep and name.strip() == "proof":
            return value.strip().lower()
    return ""


def god_self_check_text(heartbeat: Mapping[str, str], heartbeat_fresh: bool) -> str:
    """Card line while God is on but not armed yet (review B3: never promise speed without proof)."""
    if not heartbeat_fresh or _flag(heartbeat, "version") not in GOD_FAST_ARM_VERSIONS:
        return GOD_SELF_CHECK_WAITING_TEXT
    proof = god_fast_arm_proof(heartbeat)
    if proof == GOD_FAST_ARM_PROOF_MATCH:
        return GOD_SELF_CHECK_FAST_TEXT
    if proof == GOD_FAST_ARM_PROOF_NOT_CHECKED:
        return GOD_SELF_CHECK_PENDING_TEXT
    return GOD_SELF_CHECK_WAITING_TEXT


def interpret_god_heartbeat(heartbeat: Mapping[str, str]) -> tuple[str, str]:
    if god_heartbeat_proves_hooks(heartbeat):
        wanted = _flag(heartbeat, "god_desired") == "1" or _flag(heartbeat, "godlive") == "1"
        if wanted and _flag(heartbeat, "god_armed") != "1":
            # God is on in the panel, but the native has not armed it yet: its
            # runtime self-check is still pending (or blocked), so nothing is
            # protected. Never read this as Ready.
            state = _flag(heartbeat, "selfcheck").lower() or "pending"
            return NATIVE_WAITING, f"{GOD_SELF_CHECK_REASON_PREFIX}{state}"
        if wanted and _flag(heartbeat, "god_protection") == "damage_got_through":
            # A latched warning remains a warning even when the last event looks repaired.
            return NATIVE_WAITING, GOD_DAMAGE_GOT_THROUGH_REASON
        return NATIVE_READY, "hooks-installed-on-current-build"
    has_build = any(
        _flag(heartbeat, key) for key in ("build", "exe_timestamp", "build_timestamp")
    )
    if "hooks_installed" not in heartbeat or not has_build:
        # A God native from before the heartbeat build contract.
        return NATIVE_NEEDS_UPDATE, "heartbeat-without-build-proof"
    if not reports_current_build(heartbeat):
        return NATIVE_NEEDS_UPDATE, "heartbeat-other-build"
    if _flag(heartbeat, "version") not in GOD_NATIVE_VERSIONS:
        return NATIVE_UNSAFE, "heartbeat-unexpected-version"
    if _flag(heartbeat, "hooks_installed") != "1":
        error = _flag(heartbeat, "install_error") or "unknown"
        if error == "pending":
            # The native writes install_error=pending until install() returns.
            return NATIVE_WAITING, "install-pending"
        return NATIVE_UNSAFE, f"hooks-not-installed:{error}"
    if _flag(heartbeat, "dispatch_poisoned") != "0":
        return NATIVE_UNSAFE, "game-thread-dispatch-stopped"
    if _flag(heartbeat, "selfcheck").lower() == "fail":
        reason = _flag(heartbeat, "selfcheck_reason") or "unknown"
        return NATIVE_UNSAFE, f"self-check-failed:{reason}"
    return NATIVE_UNSAFE, "validation-incomplete"


def god_heartbeat_verdict(
    *,
    installed: bool,
    game_running: bool,
    heartbeat: Mapping[str, str],
    heartbeat_fresh: bool,
    trusted: bool | None = None,
    superseded: bool = False,
) -> NativeVerdict:
    """God Mode card state.

    ``installed`` means the DLL and its enable marker are present; ``trusted``
    (default: same as ``installed``) that the DLL matches an approved hash.
    ``superseded`` means the installed DLL is a known build for an earlier
    game build, which reads "Needs update" even while its marker is off.
    """
    if superseded and not trusted:
        installed, trusted = True, False
    snapshot = NativeStatusSnapshot(
        dict(heartbeat) if heartbeat_fresh else {},
        None,
        bool(heartbeat_fresh and heartbeat),
        bool(heartbeat),
    )
    verdict = native_verdict(
        installed=installed,
        trusted=installed if trusted is None else bool(trusted),
        game_running=game_running,
        snapshot=snapshot,
        interpret=interpret_god_heartbeat,
        superseded=superseded,
    )
    if verdict.state == NATIVE_WAITING and verdict.reason == GOD_SELF_CHECK_PASSED_REASON:
        return replace(verdict, detail=GOD_ARMING_TEXT, label_text=GOD_ARMING_LABEL)
    if verdict.state == NATIVE_WAITING and verdict.reason == GOD_DAMAGE_GOT_THROUGH_REASON:
        detail = GOD_DAMAGE_GOT_THROUGH_TEXT
        if _flag(heartbeat, "version") == "1.3.0":
            detail = ("God Mode reported a protection event. Its health restoration is unconfirmed "
                      "by this report. Protection may be incomplete; please share a bug report.")
        return replace(verdict, detail=detail, label_text=GOD_DAMAGE_GOT_THROUGH_LABEL)
    if verdict.state == NATIVE_WAITING and verdict.reason.startswith(GOD_SELF_CHECK_REASON_PREFIX):
        return replace(verdict, detail=god_self_check_text(heartbeat, heartbeat_fresh),
                       label_text=GOD_SELF_CHECK_LABEL)
    return verdict


# ---- Unlimited Beta / Burst energy: what the card shows ----------------------


def energy_native_supported(dll_path: Path) -> bool:
    """True when the installed God Mode game mod file is a trusted build with the energy switches."""
    path = Path(dll_path)
    try:
        if not path.is_file():
            return False
        identity = file_sha256(path)
    except OSError:
        return False
    return identity in ENERGY_GOD_NATIVE_SHA256 and identity in TRUSTED_GOD_NATIVE_SHA256


def god_fast_arm_energy_fields(heartbeat: Mapping[str, str]) -> dict[str, str]:
    """The energy record packed at the end of ``god_fast_arm`` ({} without one).

    Read like ``god_fast_arm_proof``: split on ``;``, then each part at its
    first ``:``. The record starts at its ``energy_id`` field and nothing
    before that field is read, so an older field can never pose as one.
    """
    fields: dict[str, str] = {}
    started = False
    for part in _flag(heartbeat, "god_fast_arm").split(";"):
        name, sep, value = part.partition(":")
        name = name.strip()
        if not sep or not name:
            continue
        if name == ENERGY_ID_FIELD:
            started = True
            fields = {}
        if started:
            fields[name] = value.strip()
    return fields


@dataclass(frozen=True)
class EnergyStatus:
    """The Unlimited energy card: ``state`` picks the chip, ``reason`` the line.

    ``available`` is whether the two switches can be used at all. ``detail``
    is the game mod's own report, for the activity log and support reports only.
    """

    state: str
    reason: str
    available: bool
    beta_active: bool = False
    burst_active: bool = False
    detail: str = ""

    def as_qml(self) -> dict[str, object]:
        return {
            "state": self.state,
            "reason": self.reason,
            "available": self.available,
            "betaActive": self.beta_active,
            "burstActive": self.burst_active,
        }


def energy_status(
    *,
    beta_wanted: bool,
    burst_wanted: bool,
    installed: bool,
    supported: bool,
    god_state: str,
    game_running: bool,
    heartbeat: Mapping[str, str],
    heartbeat_fresh: bool,
) -> EnergyStatus:
    """One truthful state for the two energy switches.

    ``installed`` is the trusted God Mode game mod with its marker,
    ``supported`` that this exact file has the switches
    (``energy_native_supported``) and ``god_state`` the God Mode card's own
    verdict for the same report. "Active" needs a fresh report from this game
    session whose energy record echoes both switches as the panel set them and
    says the game mod is holding the bars; anything less is never shown as on.
    """
    wanted = bool(beta_wanted or burst_wanted)
    if god_state == NATIVE_NEEDS_UPDATE:
        return EnergyStatus(ENERGY_NEEDS_UPDATE, "game-updated", False)
    if not installed or god_state == NATIVE_OFF:
        return EnergyStatus(ENERGY_OFF, "mod-off", False)
    live = bool(game_running and heartbeat_fresh)
    fields = god_fast_arm_energy_fields(heartbeat) if live else {}
    energy_id = fields.get(ENERGY_ID_FIELD, "")
    known = energy_id in ENERGY_IDS
    text = fields.get("energy_state", "") if known else ""
    detail = ""
    if known:
        detail = (
            f"energy_state={text or 'missing'} energy_armed={fields.get('energy_armed', '')} "
            f"energy_beta={fields.get('energy_beta', '')} energy_burst={fields.get('energy_burst', '')} "
            f"burst_unlocked={fields.get('burst_unlocked', '')}"
        )
    elif live:
        detail = f"energy_id={energy_id or 'missing'}"
    if god_state == NATIVE_UNSAFE:
        # The God Mode card shows this fault too; the energy record names it when it can.
        reason = text.replace("_", "-") if text in ENERGY_STOP_STATES else "mod-problem"
        return EnergyStatus(ENERGY_UNSAFE, reason, False, detail=detail)
    if not supported:
        return EnergyStatus(ENERGY_NEEDS_UPDATE, "mod-older", False)
    if not live:
        if not wanted:
            return EnergyStatus(ENERGY_OFF, "off", True)
        return EnergyStatus(ENERGY_WAITING, "no-report" if game_running else "game-closed", True)
    if not energy_id:
        # The game that is running loaded a build without the switches.
        return EnergyStatus(ENERGY_NEEDS_UPDATE, "mod-older", False, detail=detail)
    if not known:
        return EnergyStatus(ENERGY_NEEDS_UPDATE, "mod-unknown", False, detail=detail)
    if fields.get("energy_sites_ok") == "0" or text.startswith("not_supported"):
        return EnergyStatus(ENERGY_NEEDS_UPDATE, "not-supported", False, detail=detail)
    # A partial/malformed report cannot establish either switch echo or site proof.
    if fields.get("energy_sites_ok") != "1" or any(
        fields.get(key) not in ("0", "1") for key in ("energy_beta", "energy_burst")
    ):
        return EnergyStatus(ENERGY_WAITING, "no-report", True, detail=detail)
    echo = (fields.get("energy_beta") == "1", fields.get("energy_burst") == "1")
    if echo != (bool(beta_wanted), bool(burst_wanted)):
        # The game mod reads the file ten times a second; it has not caught up.
        return EnergyStatus(ENERGY_WAITING, "switching-on" if wanted else "switching-off", True, detail=detail)
    if not wanted:
        return EnergyStatus(ENERGY_OFF, "off", True, detail=detail)
    if text == "hooks_not_installed" and _flag(heartbeat, "install_error") == "pending":
        return EnergyStatus(ENERGY_WAITING, "no-report", True, detail=detail)
    if text in ENERGY_STOP_STATES:
        return EnergyStatus(ENERGY_UNSAFE, text.replace("_", "-"), True, detail=detail)
    if text.startswith("waiting_for_eve"):
        return EnergyStatus(ENERGY_WAITING, "waiting-for-eve", True, detail=detail)
    if text in ("waiting_for_game_thread", "off", ""):
        return EnergyStatus(ENERGY_WAITING, "switching-on", True, detail=detail)
    if text != "active":
        return EnergyStatus(ENERGY_UNSAFE, "unknown-report", True, detail=detail)
    if fields.get("energy_armed") != "1" or not god_heartbeat_proves_hooks(heartbeat):
        return EnergyStatus(ENERGY_WAITING, "switching-on", True, detail=detail)
    # Native publishes a signed integer: -1 is unread, zero is locked,
    # and a valid positive unlock is bounded by its 100000 pool-reader limit.
    unlock = fields.get("burst_unlocked", "")
    if burst_wanted and not (
        unlock.isascii() and unlock.isdecimal() and len(unlock) <= 6 and int(unlock) <= 100000
    ):
        return EnergyStatus(ENERGY_WAITING, "no-report", True, detail=detail)
    burst_locked = bool(burst_wanted) and int(unlock) == 0
    beta_active = bool(beta_wanted)
    burst_active = bool(burst_wanted) and not burst_locked
    if not beta_active and not burst_active:
        # Only Burst is switched on and this save has not unlocked the gauge.
        return EnergyStatus(ENERGY_WAITING, "burst-locked", True, detail=detail)
    return EnergyStatus(
        ENERGY_ACTIVE,
        "active-burst-locked" if burst_locked else "active",
        True,
        beta_active=beta_active,
        burst_active=burst_active,
        detail=detail,
    )
