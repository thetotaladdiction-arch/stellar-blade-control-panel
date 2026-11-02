"""First installation of the Stellar Blade suite into an inspected clean game.

This compiled adapter owns only the updater's program inventory plus the nine
bootstrap files below. It never interprets catalog paths or commands. A fresh
release is a separate authenticated capability; it is NOT an updater manifest.
The shared core owns transactions/recovery. If its fresh-install entry point is
unavailable, applying refuses before any write to the game. Staging is usable
independently. No installer, panel, script, DLL or game is executed here.
"""
from __future__ import annotations

import contextlib
import os
import re
import threading
import time
import zipfile
import zlib
from collections import OrderedDict
from collections.abc import Mapping
from pathlib import Path
from types import MappingProxyType

from . import core

UpdateError = core.UpdateError
TARGET_NAME = "stellar-blade-install-stable.json"
OPERATION = "fresh-install"
ENGINE_VERSION = 1
LOADER_PATH = core.WIN64 + "dwmapi.dll"
APPROVED_SOURCE_VERSION = "2.6.11"
APPROVED_SOURCE_ARCHIVE_SIZE = 74450993
APPROVED_SOURCE_ARCHIVE_SHA256 = "c864702fef397983f7b32ce3d6c312fd82c17683d34b0693776b9742bf843fd9"
APPROVED_SOURCE_PREFIX = "StellarBlade-ModSuite-v2.6.11/Stellar Blade/"
_EMPTY_SHA256 = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"

# Exact bytes in the hash-bound public ZIP, including BOM/line endings. Neither
# settings nor markers are generated from defaults. mods.txt was NOT shipped.
BOOTSTRAP_FILES = MappingProxyType({
    core.WIN64 + "ue4ss/UE4SS-settings.ini":
        (5222, "3f9987621826e83fbaff0d74db647b08bc3fb7458cc7ea8206b7449d2459ad1b"),
    core.WIN64 + "ue4ss/VTableLayout.ini":
        (15740, "bc37e960c9ea5057d5e1a29fbccf85c4d8a59d3527560ed78e6a4bea13100d1e"),
    core.PANEL + "update_source.json":
        (99, "83f882fa19a446d4180f16da793e3467ea68012613537014f200c298fa50de09"),
    **{core.MODS + name + "/enabled.txt": (0, _EMPTY_SHA256) for name in (
        "SBGodNative", "SBInstantBossRestart", "SBLiveAddBridge",
        "SBLiveAddNative", "SBMovementNative", "SBRetryPointNative",
    )},
})
PROGRAM_FILES = frozenset(core.ALLOWED_FILES)
ALLOWED_FILES = PROGRAM_FILES | BOOTSTRAP_FILES.keys()
REQUIRED_FILES = core.REQUIRED_FILES | BOOTSTRAP_FILES.keys()

# Conservative conflict detection in the two game executable directories. The
# adapter refuses these installations; it never disables/moves another mod.
# Pak mods elsewhere in the game remain outside the adapter's ownership.
CONFLICT_NAMES = frozenset({
    "ue4ss", "ue4ss.dll", "ue4ss-settings.ini", "ue4ss_signatures",
    "ue4ss.log", "mods", "mods.txt", "vtablelayout.ini",
    "dwmapi.dll", "xinput1_3.dll", "xinput1_4.dll", "xinput9_1_0.dll",
    "dxgi.dll", "d3d11.dll", "d3d12.dll", "dinput8.dll", "dsound.dll",
    "version.dll", "winmm.dll", "winhttp.dll", "opengl32.dll",
})
_TRUST_LOCK = threading.RLock()
_TRUST: OrderedDict[int, tuple[dict, bytes, bytes, dict]] = OrderedDict()


def _validate_payload(value) -> dict:
    """Strict new schema. Never relax core._validate_payload/ALLOWED_FILES."""
    core._shape(value, {"schema", "product", "operation", "version", "build_id",
                        "archive", "files", "notes"}, "Fresh install release")
    if type(value["operation"]) is not str or value["operation"] != OPERATION:
        raise UpdateError("This is not a first-install release.")
    if core._version(value["version"]) < core._version(APPROVED_SOURCE_VERSION):
        raise UpdateError("This first-install adapter requires suite 2.6.11 or newer.")
    files = value["files"]
    if type(files) is not list or not 1 <= len(files) <= core.MAX_FILES:
        raise UpdateError("The fresh install file inventory is missing or too large.")
    seen, programs, total = set(), [], 0
    for spec in files:
        core._shape(spec, {"path", "size", "sha256"}, "Fresh install file")
        path = core._relative(spec["path"])
        if path not in ALLOWED_FILES or path.casefold() in seen:
            raise UpdateError("The fresh install inventory has an unowned or repeated path.")
        seen.add(path.casefold())
        total += core._integer(spec["size"], 0, core.MAX_FILE_BYTES, "Fresh install file size")
        core._hash_text(spec["sha256"])
        if path in BOOTSTRAP_FILES:
            if (spec["size"], spec["sha256"]) != BOOTSTRAP_FILES[path]:
                raise UpdateError("Initial settings and enable markers must match the approved shipped package.")
        else:
            programs.append(spec)
    if not {p.casefold() for p in REQUIRED_FILES} <= seen or total > core.MAX_UNCOMPRESSED_BYTES:
        raise UpdateError("The fresh install inventory is incomplete or exceeds its size limit.")
    program_payload = {k: v for k, v in value.items() if k != "operation"}
    program_payload["files"] = programs
    core._validate_payload(program_payload)
    return value


def load_signed_manifest(envelope: bytes | dict, trusted_keys: Mapping[str, bytes]) -> dict:
    """Verify with caller-pinned keys; only this exact returned object is usable.

    Like the core API this is the inner signature boundary, not freshness or
    rollback protection. Public checks must use check_for_install and TUF.
    A copied/mutated dictionary or ordinary updater capability is refused.
    """
    if not isinstance(trusted_keys, Mapping) or not trusted_keys:
        raise UpdateError("No trusted first-install signing keys are configured.")
    keys = dict(trusted_keys)
    for name, key in keys.items():
        if (type(name) is not str or not re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", name)
                or type(key) is not bytes or len(key) != 32):
            raise UpdateError("The first-install signing keyring is invalid.")
    if type(envelope) is dict:
        envelope = core._canonical(envelope)
    obj = core._json(envelope, 2 * core.MAX_PAYLOAD_BYTES, "Signed first-install envelope")
    core._shape(obj, {"payload_b64", "key_id", "signature_b64"}, "Signed first-install envelope")
    key_id = core._text(obj["key_id"], 64, "First-install signing key ID")
    if key_id not in keys:
        raise UpdateError("The first-install release uses an untrusted signing key.")
    raw = core._b64(obj["payload_b64"], core.MAX_PAYLOAD_BYTES, "First-install payload")
    signature = core._b64(obj["signature_b64"], 64, "First-install signature")
    if len(signature) != 64:
        raise UpdateError("The first-install Ed25519 signature must contain 64 bytes.")
    core._verify(raw, signature, keys[key_id])
    payload = _validate_payload(core._json(raw, core.MAX_PAYLOAD_BYTES, "First-install payload"))
    with _TRUST_LOCK:
        _TRUST[id(payload)] = (payload, raw, keys[key_id], obj)
        while len(_TRUST) > 64:
            _TRUST.popitem(last=False)
    return payload


def _trusted(manifest: dict) -> tuple[dict, dict]:
    with _TRUST_LOCK:
        record = _TRUST.get(id(manifest))
    if record is None or record[0] is not manifest:
        raise UpdateError("Reload the authenticated first-install release before installing.")
    _, raw, key, envelope = record
    core._verify(raw, core._b64(envelope["signature_b64"], 64, "First-install signature"), key)
    original = _validate_payload(core._json(raw, core.MAX_PAYLOAD_BYTES, "First-install payload"))
    if core._canonical(original) != core._canonical(manifest):
        raise UpdateError("The verified first-install release was changed.")
    # Do not hand the stored envelope out to callers, including shared staging.
    return original, core._json(core._canonical(envelope), 2 * core.MAX_PAYLOAD_BYTES, "Envelope")


def check_for_install(cancel_event=None) -> dict:
    """Fetch only the compiled first-install TUF role, then verify its envelope."""
    from . import channel, tuf_channel
    fetch = getattr(tuf_channel, "fetch_target", None)
    if not callable(fetch):
        raise UpdateError("Authenticated first-install downloads are not configured in this launcher.")
    core._cancel(cancel_event, float("inf"))
    try:
        raw = fetch(TARGET_NAME, cancel_event=cancel_event)
    except (ValueError, OSError, RuntimeError) as exc:
        raise UpdateError("The authenticated first-install release could not be checked.") from exc
    core._cancel(cancel_event, float("inf"))
    if type(raw) is not bytes:
        raise UpdateError("The authenticated first-install target must be verified bytes.")
    return load_signed_manifest(raw, channel.TRUSTED_KEYS)


def _root_path(value) -> Path:
    root = core._absolute(value)
    core._ancestors(root)
    # Reject junctions before resolving, and reject short-name path aliases so
    # they cannot acquire a different path-based core lease for the same game.
    if str(root.resolve(strict=True)).casefold() != str(root).casefold():
        raise UpdateError("Select the game's original full folder path, without aliases.")
    return root


def _runtime_inventory(root: Path, guard: core._Guard, signed: dict,
                       *, installed: bool = False) -> None:
    """Inspect only the bounded runtime tree; never follow links or hash via aliases.

    Core retains exclusive handles to installed files. This checks names and
    single-link ordinary identities; core checks bytes using those handles.
    """
    runtime = root / (core.WIN64 + "ue4ss")
    allowed = set()
    expected_files = {spec["path"] for spec in signed["files"]} - {LOADER_PATH}
    for spec in signed["files"]:
        parts = spec["path"].split("/")
        allowed.update("/".join(parts[:i]) for i in range(1, len(parts)))
    if not core._exists(runtime):
        if installed:
            raise UpdateError("The prepared runtime tree is missing before loader activation.")
        return
    pending = [runtime]
    count, found = 0, set()
    while pending:
        directory = pending.pop()
        guard.directory(directory)
        with os.scandir(directory) as entries:
            for entry in entries:
                count += 1
                if count > core.MAX_FILES * 12:
                    raise UpdateError("The recovered runtime folder has too many entries.")
                path = Path(entry.path)
                relative = path.relative_to(root).as_posix()
                if relative in allowed:
                    core._plain(path, directory=True)
                    pending.append(path)
                elif installed and relative in expected_files:
                    core._plain(path)
                    if relative.casefold() in found:
                        raise UpdateError("The runtime contains colliding installed files.")
                    found.add(relative.casefold())
                else:
                    raise UpdateError("The runtime tree contains an existing file or unowned folder.")
    if installed and found != {p.casefold() for p in expected_files}:
        raise UpdateError("The complete suite inventory must be installed before loader activation.")


def _loader_conflicts(root: Path, guard: core._Guard, *, allow_runtime: bool = False,
                      allow_loader: bool = False) -> None:
    for folder in (root, root / core.WIN64):
        guard.directory(folder)
        seen = set()
        with os.scandir(folder) as entries:
            for count, entry in enumerate(entries, 1):
                if count > 4096:
                    raise UpdateError("The game executable folder contains too many entries to inspect safely.")
                folded = entry.name.casefold()
                if folded in seen:
                    raise UpdateError("The game folder contains names that collide on Windows.")
                seen.add(folded)
                if folded in CONFLICT_NAMES or folded.endswith(".asi"):
                    if allow_runtime and folder == root / core.WIN64 and entry.name == "ue4ss":
                        core._plain(Path(entry.path), directory=True)
                    elif allow_loader and folder == root / core.WIN64 and entry.name == "dwmapi.dll":
                        core._plain(Path(entry.path))
                    else:
                        raise UpdateError("An existing loader, runtime or mod conflicts with first installation: " + entry.name)


def _clean_check(root: Path, guard: core._Guard) -> None:
    """Called under the shared lease before preparation and target creation.

    No files are changed. Any runtime tree, known proxy loader, loose UE4SS
    layout or existing transaction conflicts. The sole exception is empty
    owned folders after an authenticated rollback of this adapter.
    """
    root = _root_path(root)
    recovered = None
    control = root / core._CONTROL_NAME
    if core._exists(control):
        guard.directory(control)
        pointer = core._anchor(root)
        if pointer is None or pointer["state"] != "clear":
            raise UpdateError("An existing installation or interrupted operation needs recovery first.")
        journal = core._journal(core._absolute(pointer["transaction_dir"]), guard)
        if (journal.get("schema") != 2 or journal.get("operation") != OPERATION
                or journal["manifest"].get("operation") != OPERATION
                or journal["state"] != "rolled_back"
                or journal["game_root"] != str(root)):
            raise UpdateError("The existing recovery state does not describe a rolled-back first install.")
        _validate_payload(journal["manifest"])
        for entry in control.iterdir():
            if entry.name != "active.dpapi":
                raise UpdateError("The installation control folder contains unrecognized files.")
        recovered = journal
    _loader_conflicts(root, guard, allow_runtime=recovered is not None)
    if recovered:
        _runtime_inventory(root, guard, recovered["manifest"])
    # Be explicit about the whole bounded owned list, even when an ancestor
    # conflict already covers it. lstat sees dangling reparse points too.
    for relative in ALLOWED_FILES:
        if core._exists(root / relative):
            raise UpdateError("First installation would replace an existing suite file: " + relative)


def _precommit_clean_check(root: Path, guard: core._Guard, signed: dict) -> None:
    """After initial _clean_check, permit only empty authorized parent folders.

    Called by core under its lease/identity handles after preparation, before
    the first file mutation. This is not a substitute for initial inspection.
    """
    _validate_payload(signed)
    root = _root_path(root)
    _loader_conflicts(root, guard, allow_runtime=True)
    _runtime_inventory(root, guard, signed)


def _preactivation_check(root: Path, guard: core._Guard, signed: dict) -> None:
    """Just before loader-last swap: exact full inventory, absent loader.

    Core must additionally match every prepared/installed handle fingerprint.
    This refuses foreign additions during preparation, including other loaders.
    """
    _installed_layout_check(root, guard, signed, exclude_loader=True)


def _installed_layout_check(root: Path, guard: core._Guard, signed: dict,
                            *, exclude_loader: bool = True) -> None:
    """Membership/ordinary-path check immediately before and after activation.

    Existing exclusive core handles provide content/identity verification.
    Unrelated paths outside the owned runtime tree are never traversed.
    """
    _validate_payload(signed)
    root = _root_path(root)
    _loader_conflicts(root, guard, allow_runtime=True, allow_loader=not exclude_loader)
    _runtime_inventory(root, guard, signed, installed=True)
    if not exclude_loader:
        core._plain(root / LOADER_PATH)


def engine_available() -> bool:
    return (getattr(core, "FRESH_INSTALL_ENGINE_VERSION", None) == ENGINE_VERSION
            and callable(getattr(core, "apply_fresh_install", None)))


def inspect_clean_install(game_root) -> dict:
    """Read-only exact retail identity and conflict inspection, never authority."""
    result = {"game_root": str(game_root), "version": "", "build_id": "",
              "supported": False, "supported_build": False, "clean_install": False,
              "ready_for_install": False, "install_available": False,
              "recovery_transaction": "", "blockers": []}
    try:
        root = _root_path(game_root)
        result["game_root"] = str(root)
        with core._lease(root), core._Guard() as guard, contextlib.ExitStack() as stack:
            guard.directory(root)
            pointer = core._anchor(root)
            if pointer and pointer["state"] == "active":
                result["recovery_transaction"] = pointer["transaction_dir"]
            core._game_identity(root, guard, stack, exclusive=False)
            result.update(supported=True, supported_build=True, build_id=core.SUPPORTED_BUILD_ID)
            _clean_check(root, guard)
            result["clean_install"] = True
            blocked = core._process_blockers()
            if blocked:
                result["blockers"].append("Close the game, panel and other updater: " + ", ".join(blocked))
            result["ready_for_install"] = not result["blockers"]
            result["install_available"] = result["ready_for_install"] and engine_available()
    except (UpdateError, OSError, ValueError) as exc:
        result["blockers"].append(str(exc) if isinstance(exc, UpdateError) else "The selected game files cannot be verified.")
    return result


def download_and_stage(manifest: dict, stage_parent, cancel_event=None) -> Path:
    """Stage a narrowed signed ZIP, preserving every failed/partial artifact.

    The old general-purpose manual ZIP is NOT accepted as a narrowed package.
    Release building must copy the owned bytes verbatim from approved inputs.
    Same flat storage and exact ZIP checks as core; extra members are refused.
    """
    signed, envelope = _trusted(manifest)
    parent = core._absolute(stage_parent)
    try:
        core._mkdirs(parent)
        with core._Guard() as guard, contextlib.ExitStack() as stack:
            guard.directory(parent)
            core._ntfs(parent)
            core._space(parent, signed["archive"]["size"] + sum(f["size"] for f in signed["files"]) + (1 + len(signed["files"])) * core.MAX_ORIGIN_BYTES)
            deadline = time.monotonic() + core.DOWNLOAD_SECONDS
            core._cancel(cancel_event, deadline)
            stage = core._new_dir(parent, "suite-stage-")
            guard.directory(stage)
            archive_path = stage / "release.zip"
            core._download(signed, archive_path, cancel_event, deadline)
            archive_file = stack.enter_context(core._HeldFile(archive_path, allow_origin=True))
            if not core._signed_match(archive_file.fingerprint(core.MAX_ARCHIVE_BYTES), signed["archive"]):
                raise UpdateError("The first-install archive failed its signed hash and size check.")
            core._extract_payloads(archive_file, stage, signed, guard, cancel_event, deadline)
            with core._HeldFile(stage / "release-envelope.json", create=True, exclusive=True) as output:
                raw = core._canonical(envelope)
                output.fp.write(raw)
                output.fp.flush()
                os.fsync(output.fp.fileno())
        # Includes signed VERSION, exact stage membership and a second check
        # of archive/payload bytes under retained read handles.
        with core._Guard() as guard, contextlib.ExitStack() as stack:
            _stage_files(stage, manifest, guard, stack)
        return stage
    except UpdateError:
        raise
    except (OSError, ValueError, RuntimeError, zipfile.BadZipFile, UnicodeError, zlib.error) as exc:
        raise UpdateError("First-install staging failed. Partial files were retained; no game files were changed.") from exc


def _stage_files(stage: Path, manifest: dict, guard: core._Guard,
                 stack: contextlib.ExitStack) -> dict:
    signed, envelope = _trusted(manifest)
    return core._stage_files(stage, signed, envelope, guard, stack)


def apply_install(game_root, stage_dir, manifest: dict, backup_parent) -> dict:
    """Dispatch only to the shared, explicitly versioned transaction engine."""
    _trusted(manifest)
    if not engine_available():
        raise UpdateError("First installation requires the reviewed shared recovery engine; this launcher cannot install yet.")
    return core.apply_fresh_install(game_root, stage_dir, manifest, backup_parent)


def rollback(transaction_dir, expected_game_root=None) -> dict:
    """Use the same authenticated core recovery engine as ordinary updates."""
    if not engine_available():
        raise UpdateError("First-install recovery requires the reviewed shared recovery engine.")
    transaction = core._absolute(transaction_dir)
    with core._Guard() as guard:
        obj = core._journal(transaction, guard)
        if (obj.get("schema") != 2 or obj.get("operation") != OPERATION
                or obj["manifest"].get("operation") != OPERATION):
            raise UpdateError("Select a first-install transaction for this recovery action.")
    return core.rollback(transaction, expected_game_root=expected_game_root)
