"""Stellar Blade adapter for the Aeroneus launcher.

Ordinary updates require an EXISTING, supported suite installation. The separate
compiled fresh_install adapter supplies clean-game and bootstrap-byte policy
to this module's recovery engine. Neither route accepts the old, general-purpose
release ZIP. A signed update ZIP contains only the listed program files, below
``archive.prefix``; settings, enable markers and unrelated mods are excluded
from ordinary updates.

Trust is supplied by the caller, never by a downloaded file. A manifest is an
ordinary dictionary, but its verification capability lives in this process.
Reload the original envelope with the configured pinned keyring after restart.
Windows transactions use DPAPI-authenticated journals and retained preimages.
They are recoverable file swaps, not an atomic filesystem-wide transaction.
No protection against a malicious process running as the same Windows user or
an administrator is claimed. No public key/feed is configured in this module.
"""

from __future__ import annotations

import base64
import binascii
import contextlib
import ctypes
import hashlib
import http.client
import json
import os
import re
import shutil
import socket
import ssl
import stat
import struct
import sys
import threading
import time
import urllib.parse
import uuid
import zipfile
import zlib
from collections import OrderedDict
from ctypes import wintypes
from pathlib import Path
from typing import Any, Mapping


class UpdateError(Exception):
    """A refused or unsuccessful operation, explained without secrets."""


PRODUCT = "stellar-blade-mod-suite"
FRESH_INSTALL_ENGINE_VERSION = 1
STEAM_APP_ID = "3489700"
SUPPORTED_BUILD_ID = "24463856"
SUPPORTED_EXE_SIZE = 359186432
SUPPORTED_EXE_SHA256 = "573aaff1c9455f85ea6036ef6f6ccb0774de4164722a296276fbbfc7fa87545c"
SUPPORTED_PE_TIMESTAMP = 0x6A6A3B74
SUPPORTED_PE_IMAGE_SIZE = 0x15981000
MAX_PAYLOAD_BYTES = 1024 * 1024
MAX_ARCHIVE_BYTES = 2 * 1024**3
MAX_UNCOMPRESSED_BYTES = 4 * 1024**3
MAX_FILE_BYTES = 512 * 1024**2
MAX_FILES = 512
MAX_ZIP_ENTRIES = 1024
MAX_COMPRESSION_RATIO = 200
MAX_JOURNAL_BYTES = 4 * 1024**2
DOWNLOAD_SECONDS = 1200
NETWORK_TIMEOUT_SECONDS = 20
IO_CHUNK = 1024 * 1024
SPACE_RESERVE = 256 * 1024**2
MAX_ORIGIN_BYTES = 64 * 1024
WIN64 = "SB/Binaries/Win64/"
MODS = WIN64 + "ue4ss/Mods/"
PANEL = MODS + "SBCheatGUI/"
VERSION_PATH = PANEL + "VERSION"
GAME_EXE_PATH = WIN64 + "SB-Win64-Shipping.exe"
_RELEASE_PATH = "/thetotaladdiction-arch/stellar-blade-control-panel/releases/download/"
_CDN_HOSTS = frozenset({"release-assets.githubusercontent.com", "objects.githubusercontent.com", "github-releases.githubusercontent.com"})
_VERSION_RE = re.compile(r"(0|[1-9][0-9]{0,5})\.(0|[1-9][0-9]{0,5})\.(0|[1-9][0-9]{0,5})\Z")
_HASH_RE = re.compile(r"[0-9a-f]{64}\Z")
_COMPONENT_RE = re.compile(r"[A-Za-z0-9_. -]+\Z")
_DEVICE_RE = re.compile(r"(?:CON|PRN|AUX|NUL|COM[0-9]|LPT[0-9]|CONIN\$|CONOUT\$)(?:\..*)?\Z", re.I)

# Exact loader/shared-runtime identity from the unmodified public v2.6.11 ZIP.
# A different runtime needs a reviewed adapter revision, not a feed-only change.
APPROVED_RUNTIME = {
    WIN64 + "dwmapi.dll": (124928, "a30732477f2d7134b712aa1d295ebdf2f1b5a9dd46a10b6ce494819cba1774fa"),
    WIN64 + "ue4ss/UE4SS.dll": (24511488, "f3f0229e8d046824c6d71db256f1c9bbbda9652a193643c28fa4e6c329e17670"),
    WIN64 + "ue4ss/UE4SS_Signatures/GNatives.lua": (463, "4db0fc05062679f45df37c6be49bd7aa6fc4c5c3e56ce7506ce57a9b2d03c2f2"),
    WIN64 + "ue4ss/UE4SS_Signatures/GUObjectArray.lua": (258, "ef0e4473c529c73844fd1458d38f73f6d9b29e4df664075434a795d88e17101d"),
    MODS + "shared/UEHelpers/UEHelpers.lua": (10642, "c24f01c676536149a2cb49d5a050ff49c43afaaad6e8e0979bee560e703e35d3"),
}
_VTABLE_PATH = WIN64 + "ue4ss/VTableLayout.ini"
_VTABLE_ID = (15740, "bc37e960c9ea5057d5e1a29fbccf85c4d8a59d3527560ed78e6a4bea13100d1e")
_NATIVES = ("SBGodNative", "SBLiveAddNative", "SBMovementNative", "SBRetryPointNative")
_SCRIPTS = ("SBInstantBossRestart", "SBLiveAddBridge")
REQUIRED_FILES = frozenset({
    *APPROVED_RUNTIME, VERSION_PATH, PANEL + "Stellar Blade Control Panel.exe",
    *(MODS + name + "/dlls/main.dll" for name in _NATIVES),
    *(MODS + name + "/Scripts/main.lua" for name in _SCRIPTS),
})
ALLOWED_FILES = frozenset({
    *REQUIRED_FILES, WIN64 + "ue4ss/LICENSE",
    *(MODS + name + "/README.txt" for name in (*_NATIVES, *_SCRIPTS)),
    *(PANEL + name for name in (
        "Create-SupportReport.ps1", "Launch-Panel-Hidden.vbs", "PATCH_NOTES.md",
        "PanelLauncherCommon.ps1", "QtPanel/BUILD_ARTIFACT.txt", "QtPanel/UI_REVISION",
        "README.txt", "Show-Panel-ForceVisible.ps1", "eve.ico",
        "disabled_paks/EveStanceNoDamage_P.pak", "disabled_paks/EveStanceNoDamage_P.ucas",
        "disabled_paks/EveStanceNoDamage_P.utoc", "disabled_paks/README.txt",
    )),
})
_BASELINE_FILES = {
    **APPROVED_RUNTIME,
    PANEL + "Stellar Blade Control Panel.exe": (65990219, "f0b190c525b1d0da62ac158a943d1aecdaf6346388f8ad51514761af95043e79"),
    VERSION_PATH: (7, "0f886717df79545c6e681dbd1496a2802569802d9758ac28c8dda35ac7b4f13e"),
    MODS + "SBGodNative/dlls/main.dll": (157696, "f3b0e52a114018c18de37e7f56d530e277b11fdb44abda2c29429f93473c2643"),
    MODS + "SBLiveAddNative/dlls/main.dll": (226816, "3df532fedf404c86378592ccdeaf1b8e9e2c0ac2e5cfbf8a05bf195fdec197cf"),
    MODS + "SBMovementNative/dlls/main.dll": (89088, "2ec681952f6f737951816c59e41769d235c478b0e50f980548015e893166b88c"),
    MODS + "SBRetryPointNative/dlls/main.dll": (113664, "360877da3e235f0aae0c9059404b1e5f19ebbe9a4fcfb6254d6ac4fe7365fdab"),
    MODS + "SBInstantBossRestart/Scripts/main.lua": (189911, "98f735e2caabe30e5c01ee31a167648143106f03ea22f9371cf3912e6763b164"),
    MODS + "SBLiveAddBridge/Scripts/main.lua": (60402, "b8c9f17bb6130dc12b6e94d70baaca44239f7436aaca678cc46617de09c127ff"),
}
_CONTROL_NAME = ".aeroneus-suite-updater"
_TRUST_LOCK = threading.RLock()
# Strong identity references prevent id reuse. Bounded; reload an evicted envelope.
_TRUST: OrderedDict[int, tuple[dict, bytes, bytes, dict]] = OrderedDict()


def _shape(value: Any, keys: set[str], label: str) -> dict:
    if type(value) is not dict or set(value) != keys:
        raise UpdateError(f"{label} has missing, extra, or invalid fields.")
    return value


def _integer(value: Any, minimum: int, maximum: int, label: str) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise UpdateError(f"{label} must be a whole number between {minimum} and {maximum}.")
    return value


def _text(value: Any, limit: int, label: str, *, empty: bool = False) -> str:
    if type(value) is not str or len(value) > limit or (not empty and not value):
        raise UpdateError(f"{label} is not valid text.")
    try:
        value.encode("utf-8", errors="strict")
    except UnicodeError as exc:
        raise UpdateError(f"{label} contains invalid characters.") from exc
    return value


def _pairs(pairs: list[tuple[str, Any]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise UpdateError("JSON contains a duplicate field.")
        result[key] = value
    return result


def _bad_number(value: str) -> None:
    raise UpdateError("JSON contains an unsupported number.")


def _json(raw: bytes, limit: int, label: str) -> Any:
    if type(raw) is not bytes or len(raw) > limit:
        raise UpdateError(f"{label} exceeds its size limit.")
    try:
        return json.loads(raw.decode("utf-8", errors="strict"), object_pairs_hook=_pairs,
                          parse_constant=_bad_number, parse_float=_bad_number)
    except (UnicodeError, ValueError, RecursionError) as exc:
        raise UpdateError(f"{label} is not valid strict UTF-8 JSON.") from exc


def _canonical(value: Any) -> bytes:
    try:
        return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("ascii")
    except (TypeError, ValueError, RecursionError) as exc:
        raise UpdateError("Update information cannot be serialized.") from exc


def _b64(value: Any, maximum: int, label: str) -> bytes:
    _text(value, ((maximum + 2) // 3) * 4, label)
    try:
        result = base64.b64decode(value, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise UpdateError(f"{label} is not valid base64.") from exc
    if len(result) > maximum or base64.b64encode(result).decode("ascii") != value:
        raise UpdateError(f"{label} is not canonical base64 or exceeds its size limit.")
    return result


def _relative(value: Any, label: str = "File path") -> str:
    _text(value, 220, label)
    if "\\" in value or ":" in value or value.startswith("/"):
        raise UpdateError(f"{label} must be a relative path with forward slashes.")
    for component in value.split("/"):
        if (component in ("", ".", "..") or len(component) > 120
                or component.endswith((".", " ")) or component.startswith(" ")
                or not _COMPONENT_RE.fullmatch(component) or _DEVICE_RE.fullmatch(component)):
            raise UpdateError(f"{label} contains an unsafe Windows filename.")
    return value


def _version(value: Any) -> tuple[int, int, int]:
    if type(value) is not str or not _VERSION_RE.fullmatch(value):
        raise UpdateError("The release version must contain three numeric parts, such as 2.6.12.")
    return tuple(int(part) for part in value.split("."))


def _hash_text(value: Any) -> str:
    if type(value) is not str or not _HASH_RE.fullmatch(value):
        raise UpdateError("A SHA-256 value must contain exactly 64 lowercase hexadecimal characters.")
    return value


def _url(value: Any, *, initial: bool) -> urllib.parse.SplitResult:
    _text(value, 16384, "Release URL")
    if any(ord(c) < 33 or ord(c) > 126 for c in value) or "\\" in value:
        raise UpdateError("The release URL contains unsafe characters.")
    try:
        parts = urllib.parse.urlsplit(value)
        if (parts.scheme != "https" or parts.username is not None or parts.password is not None
                or parts.port is not None or "#" in value or parts.netloc != parts.hostname):
            raise ValueError
    except ValueError as exc:
        raise UpdateError("Only HTTPS release URLs without credentials, ports, or fragments are allowed.") from exc
    if parts.hostname == "github.com":
        tail = parts.path.removeprefix(_RELEASE_PATH)
        if (not parts.path.startswith(_RELEASE_PATH) or "?" in value
                or not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\.zip", tail)
                or any(part in (".", "..") for part in tail.split("/"))):
            raise UpdateError("The archive must be a release ZIP from the approved GitHub repository.")
    elif initial or parts.hostname not in _CDN_HOSTS or not parts.path.startswith("/"):
        raise UpdateError("The download redirected outside approved GitHub asset hosts.")
    return parts


def _validate_payload(payload: Any) -> dict:
    _shape(payload, {"schema", "product", "version", "build_id", "archive", "files", "notes"}, "Release payload")
    _integer(payload["schema"], 1, 1, "Release schema")
    if payload["product"] != PRODUCT or type(payload["product"]) is not str:
        raise UpdateError("This release belongs to a different product.")
    _version(payload["version"])
    if type(payload["build_id"]) is not str or payload["build_id"] != SUPPORTED_BUILD_ID:
        raise UpdateError("This adapter only supports Steam game build 24463856.")
    _text(payload["notes"], MAX_PAYLOAD_BYTES, "Release notes", empty=True)
    archive = _shape(payload["archive"], {"url", "size", "sha256", "prefix"}, "Archive description")
    _url(archive["url"], initial=True)
    _integer(archive["size"], 22, MAX_ARCHIVE_BYTES, "Archive size")
    _hash_text(archive["sha256"])
    prefix = _text(archive["prefix"], 180, "Archive prefix", empty=True)
    if prefix:
        _relative(prefix[:-1] if prefix.endswith("/") else prefix, "Archive prefix")
    files = payload["files"]
    if type(files) is not list or not 1 <= len(files) <= MAX_FILES:
        raise UpdateError("The release file list is empty or too large.")
    paths: set[str] = set()
    folded: set[str] = set()
    total = 0
    for entry in files:
        _shape(entry, {"path", "size", "sha256"}, "Release file")
        path = _relative(entry["path"])
        if path not in ALLOWED_FILES:
            raise UpdateError(f"The release attempts to replace an unapproved file: {path}")
        if path.casefold() in folded:
            raise UpdateError("Release file paths collide on Windows.")
        paths.add(path)
        folded.add(path.casefold())
        total += _integer(entry["size"], 1, MAX_FILE_BYTES, "File size")
        _hash_text(entry["sha256"])
        if path in APPROVED_RUNTIME and (entry["size"], entry["sha256"]) != APPROVED_RUNTIME[path]:
            raise UpdateError("The release changes the approved UE4SS runtime; a reviewed adapter is required.")
    if not REQUIRED_FILES <= paths:
        raise UpdateError("The release is missing part of the compatible panel, mod, and UE4SS bundle.")
    if total > MAX_UNCOMPRESSED_BYTES:
        raise UpdateError("The release expands beyond the 4 GiB limit.")
    return payload


def _verify(raw: bytes, signature: bytes, key: bytes) -> None:
    try:
        from cryptography.exceptions import InvalidSignature, UnsupportedAlgorithm
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    except ImportError as exc:
        raise UpdateError("The cryptography package is required to verify releases.") from exc
    try:
        Ed25519PublicKey.from_public_bytes(key).verify(signature, raw)
    except (ValueError, InvalidSignature, UnsupportedAlgorithm) as exc:
        raise UpdateError("The release signature is invalid or Ed25519 verification is unavailable.") from exc


def load_signed_manifest(envelope: bytes | dict, trusted_keys: Mapping[str, bytes]) -> dict:
    """Verify raw JSON envelope with caller-pinned 32-byte Ed25519 public keys.

    Returns the ordinary validated payload dictionary. Do not reconstruct it
    from disk or copy it before staging/apply: reload its envelope instead.
    Empty keyrings, duplicate JSON fields, unknown fields and booleans fail.
    """
    if not isinstance(trusted_keys, Mapping) or not trusted_keys:
        raise UpdateError("No trusted release signing keys are configured. Installation is unavailable.")
    keys = dict(trusted_keys)
    for key_id, key in keys.items():
        if (type(key_id) is not str or not re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", key_id)
                or type(key) is not bytes or len(key) != 32):
            raise UpdateError("The configured public signing keyring is invalid.")
    if type(envelope) is bytes:
        obj = _json(envelope, 2 * MAX_PAYLOAD_BYTES, "Signed release envelope")
    elif type(envelope) is dict:
        obj = _json(_canonical(envelope), 2 * MAX_PAYLOAD_BYTES, "Signed release envelope")
    else:
        raise UpdateError("The release envelope must be JSON bytes or an ordinary dictionary.")
    _shape(obj, {"payload_b64", "key_id", "signature_b64"}, "Signed release envelope")
    key_id = _text(obj["key_id"], 64, "Signing key ID")
    if key_id not in keys:
        raise UpdateError("The release uses an untrusted signing key.")
    raw = _b64(obj["payload_b64"], MAX_PAYLOAD_BYTES, "Release payload")
    signature = _b64(obj["signature_b64"], 64, "Release signature")
    if len(signature) != 64:
        raise UpdateError("An Ed25519 signature must contain 64 bytes.")
    _verify(raw, signature, keys[key_id])
    payload = _validate_payload(_json(raw, MAX_PAYLOAD_BYTES, "Release payload"))
    with _TRUST_LOCK:
        _TRUST[id(payload)] = (payload, raw, keys[key_id], obj)
        while len(_TRUST) > 64:
            _TRUST.popitem(last=False)
    return payload


def _trusted(manifest: dict) -> tuple[dict, dict]:
    with _TRUST_LOCK:
        record = _TRUST.get(id(manifest))
    if record is None or record[0] is not manifest:
        raise UpdateError("Reload the signed release envelope with the pinned keyring before installing.")
    _, raw, key, envelope = record
    _verify(raw, _b64(envelope["signature_b64"], 64, "Release signature"), key)
    original = _validate_payload(_json(raw, MAX_PAYLOAD_BYTES, "Release payload"))
    if _canonical(manifest) != _canonical(original):
        raise UpdateError("The verified release information was changed. Reload the signed envelope.")
    return original, envelope


def _absolute(value: os.PathLike | str) -> Path:
    try:
        path = Path(value)
    except (TypeError, ValueError) as exc:
        raise UpdateError("Select an ordinary absolute local folder.") from exc
    text = str(path)
    if not path.is_absolute() or ".." in path.parts or "\x00" in text:
        raise UpdateError("Select an absolute folder without parent-directory shortcuts.")
    if os.name == "nt" and (not re.match(r"^[A-Za-z]:[\\/]", text) or ":" in text[2:]):
        raise UpdateError("Network, device, and alternate-stream paths are not supported.")
    if len(text) > 240:
        raise UpdateError("Choose a shorter folder path for this Windows updater.")
    return path


def _plain(path: Path, *, directory: bool = False) -> os.stat_result:
    info = path.lstat()
    if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
        raise UpdateError(f"Links, junctions, and reparse points are not allowed: {path.name}")
    if directory:
        if not stat.S_ISDIR(info.st_mode):
            raise UpdateError(f"An ordinary folder is required: {path.name}")
    elif not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise UpdateError(f"An ordinary file with one link is required: {path.name}")
    return info


def _ancestors(path: Path) -> None:
    for part in reversed((path, *path.parents)):
        _plain(part, directory=True)


def _exists(path: Path) -> bool:
    try:
        path.lstat()
        return True
    except FileNotFoundError:
        return False


def _space(path: Path, needed: int) -> None:
    if shutil.disk_usage(path).free < needed + SPACE_RESERVE:
        raise UpdateError("There is not enough free space for the staged files, backups, and recovery reserve.")


def _new_dir(parent: Path, prefix: str) -> Path:
    _ancestors(parent)
    path = parent / (prefix + uuid.uuid4().hex)
    path.mkdir(mode=0o700)
    _plain(path, directory=True)
    return path


def _mkdirs(path: Path) -> None:
    missing = []
    current = path
    while not _exists(current):
        missing.append(current)
        current = current.parent
    _ancestors(current)
    for current in reversed(missing):
        current.mkdir(mode=0o700)
        _plain(current, directory=True)


def _cancel(cancel_event: Any, deadline: float) -> None:
    if cancel_event is not None and cancel_event.is_set():
        raise UpdateError("Download cancelled. Partial staging files were retained.")
    if time.monotonic() > deadline:
        raise UpdateError("The download and staging time limit was reached. Partial files were retained.")


def _download(manifest: dict, target: Path, cancel_event: Any, deadline: float) -> None:
    # Qt owns asynchronous DNS/connect as well as streamed body reads, so
    # cancellation does not depend on a synchronous socket being assigned.
    from .archive_transport import download_archive
    download_archive(manifest, target, cancel_event, deadline)


def _prefix(manifest: dict) -> str:
    value = manifest["archive"]["prefix"]
    return value.rstrip("/") + "/" if value else ""


def _slot(parent: Path, section: str, signed_path: str) -> Path:
    # Flat retained storage keeps the normal launcher directory layout below
    # Win32's path limit. The authenticated journal keeps the original paths.
    return parent / section / hashlib.sha256(signed_path.encode("ascii")).hexdigest()


def _zip_index(stream, manifest: dict) -> tuple[zipfile.ZipFile, dict[str, zipfile.ZipInfo]]:
    """Bound the central directory BEFORE ZipFile allocates/parses it."""
    stream.seek(0, 2)
    length = stream.tell()
    stream.seek(max(0, length - 65557))
    tail = stream.read(65557)
    offset = tail.rfind(b"PK\x05\x06")
    if offset < 0 or len(tail) - offset < 22:
        raise UpdateError("The archive has no valid ZIP directory.")
    eocd = struct.unpack_from("<4s4H2IH", tail, offset)
    _, disk, cd_disk, on_disk, count, cd_size, cd_offset, comment = eocd
    eocd_offset = length - len(tail) + offset
    if (disk or cd_disk or on_disk != count or not 1 <= count <= MAX_ZIP_ENTRIES
            or cd_size > 4 * 1024**2 or cd_offset + cd_size != eocd_offset
            or len(tail) - offset != 22 + comment or cd_offset == 0xFFFFFFFF):
        raise UpdateError("Split, ZIP64, oversized, or malformed ZIP directories are not supported.")
    stream.seek(0)
    archive = zipfile.ZipFile(stream, "r")
    try:
        infos = archive.infolist()
        if len(infos) != count:
            raise UpdateError("The ZIP entry count is inconsistent.")
        expected = {_prefix(manifest) + entry["path"]: entry for entry in manifest["files"]}
        allowed_dirs = set()
        for name in expected:
            parts = name.split("/")
            allowed_dirs.update("/".join(parts[:i]) for i in range(1, len(parts)))
        seen: set[str] = set()
        found = {}
        total = 0
        for entry in infos:
            name = entry.orig_filename
            directory = name.endswith("/")
            clean = name[:-1] if directory else name
            _relative(clean, "ZIP path")
            if name != entry.filename or clean.casefold() in seen:
                raise UpdateError("The ZIP contains truncated or colliding names.")
            seen.add(clean.casefold())
            mode = entry.external_attr >> 16
            kind = stat.S_IFMT(mode)
            if (kind not in (0, stat.S_IFDIR if directory else stat.S_IFREG)
                    or entry.external_attr & (0x400 | 0x40 | 0x08)
                    or entry.flag_bits & (0x01 | 0x40)
                    or entry.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED)):
                raise UpdateError("The ZIP contains links, special files, encryption, or unsupported compression.")
            if entry.header_offset < 0 or entry.header_offset + entry.compress_size + 30 > cd_offset:
                raise UpdateError("A ZIP member lies outside the bounded archive data.")
            if directory:
                if clean not in allowed_dirs or entry.file_size != 0 or entry.compress_size > 2:
                    raise UpdateError("The ZIP contains an unneeded or invalid directory.")
                continue
            if name not in expected:
                raise UpdateError("The ZIP contains files that are not in the signed update list.")
            signed = expected[name]
            if entry.file_size != signed["size"] or entry.file_size > max(1, entry.compress_size) * MAX_COMPRESSION_RATIO:
                raise UpdateError("A ZIP member has an invalid size or excessive compression ratio.")
            total += entry.file_size
            if total > MAX_UNCOMPRESSED_BYTES:
                raise UpdateError("The ZIP expands beyond the allowed quota.")
            found[signed["path"]] = entry
        if set(found) != {entry["path"] for entry in manifest["files"]}:
            raise UpdateError("The ZIP does not contain the complete signed bundle.")
        return archive, found
    except BaseException:
        archive.close()
        raise


def _stream_copy(source, output, size: int, digest: str, cancel_event=None, deadline=float("inf")) -> None:
    total, actual = 0, hashlib.sha256()
    while True:
        _cancel(cancel_event, deadline)
        chunk = source.read(min(IO_CHUNK, size - total + 1))
        if not chunk:
            break
        total += len(chunk)
        if total > size:
            raise UpdateError("A file exceeded its signed or backed-up size.")
        output.write(chunk)
        actual.update(chunk)
    output.flush()
    os.fsync(output.fileno())
    if total != size or actual.hexdigest() != digest:
        raise UpdateError("A file failed its size or SHA-256 check.")


def _extract_payloads(archive_file, stage, signed, guard, cancel_event=None, deadline=float("inf")):
    """Inherit held ZIP origin before final payload fingerprint or use."""
    archive_file.origin.check()
    archive, entries = _zip_index(archive_file.fp, signed)
    with archive:
        for spec in signed["files"]:
            _cancel(cancel_event, deadline)
            destination = _slot(stage, "files", spec["path"])
            guard.directory(destination.parent, create=True)
            with archive.open(entries[spec["path"]], "r") as source:
                _consumer_copy(source, destination, spec, guard, archive_file, cancel_event, deadline)
    archive_file.origin.check()


def _consumer_copy(source, destination, spec, guard, origin_source, cancel_event=None, deadline=float("inf")):
    """New default bytes plus ONLY the existing origin stream; never all ADS."""
    guard.directory(destination.parent, create=True)
    origin_source.origin.check()
    source.seek(0)
    with _HeldFile(destination, create=True, exclusive=True, allow_origin=True) as output:
        _stream_copy(source, output.fp, spec["size"], spec["sha256"], cancel_event, deadline)
        output.origin.inherit(origin_source.origin.raw)
    with _HeldFile(destination, allow_origin=True) as check:
        actual = check.fingerprint()
        if not _signed_match(actual, spec) or check.origin.raw != origin_source.origin.raw:
            raise UpdateError("The consumer copy failed content/origin readback.")
    origin_source.origin.check()
    return actual


def download_and_stage(manifest: dict, stage_parent: os.PathLike | str, cancel_event=None) -> Path:
    """Download into a NEW suite-stage-* folder; return its absolute Path.

    Network cancellation and the common deadline are checked by a Qt timer
    through DNS, connect, headers and streamed body reads. Extraction checks
    cancellation between chunks. Partial/failed files are retained here.
    """
    signed, envelope = _trusted(manifest)
    parent = _absolute(stage_parent)
    stage = None
    try:
        _mkdirs(parent)
        _ancestors(parent)
        _space(parent, signed["archive"]["size"] + sum(f["size"] for f in signed["files"]) + (1 + len(signed["files"])) * MAX_ORIGIN_BYTES)
        deadline = time.monotonic() + DOWNLOAD_SECONDS
        _cancel(cancel_event, deadline)
        stage = _new_dir(parent, "suite-stage-")
        archive_path = stage / "release.zip"
        _download(signed, archive_path, cancel_event, deadline)
        with _Guard() as guard, _HeldFile(archive_path, allow_origin=True) as archive_file:
            if not _signed_match(archive_file.fingerprint(MAX_ARCHIVE_BYTES), signed["archive"]):
                raise UpdateError("The staged archive failed its signed hash and size check.")
            _extract_payloads(archive_file, stage, signed, guard, cancel_event, deadline)
        if _slot(stage, "files", VERSION_PATH).read_bytes().decode("ascii").strip() != signed["version"]:
            raise UpdateError("The staged panel VERSION file differs from the signed release version.")
        with (stage / "release-envelope.json").open("xb") as output:
            output.write(_canonical(envelope))
            output.flush()
            os.fsync(output.fileno())
        return stage
    except UpdateError:
        raise
    except (OSError, ValueError, zipfile.BadZipFile, RuntimeError, UnicodeError, zlib.error) as exc:
        raise UpdateError("Staging failed. The partial staging folder was retained; no game files were changed.") from exc


# Mutations are Windows/NTFS only. Directory handles deny ancestor renames;
# file handles deny competing writes/deletes. Handle-based, non-clobber renames
# avoid a hash-check / replace-path race. An interrupted swap can temporarily
# leave an owned target absent; the durable journal precedes every such swap.
_KERNEL = None


class _FileIdInfo(ctypes.Structure):
    _fields_ = [("volume", ctypes.c_ulonglong), ("file_id", ctypes.c_ubyte * 16)]


class _FileInfo(ctypes.Structure):
    _fields_ = [("attributes", wintypes.DWORD), ("created", wintypes.FILETIME),
                ("accessed", wintypes.FILETIME), ("written", wintypes.FILETIME),
                ("volume", wintypes.DWORD), ("size_high", wintypes.DWORD),
                ("size_low", wintypes.DWORD), ("links", wintypes.DWORD),
                ("index_high", wintypes.DWORD), ("index_low", wintypes.DWORD)]


def _kernel():
    global _KERNEL
    if os.name != "nt":
        raise UpdateError("Installing and recovery require Windows on a local NTFS drive.")
    if _KERNEL is None:
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        signatures = {
            "CreateFileW": ([wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE], wintypes.HANDLE),
            "CloseHandle": ([wintypes.HANDLE], wintypes.BOOL),
            "GetFileInformationByHandle": ([wintypes.HANDLE, ctypes.POINTER(_FileInfo)], wintypes.BOOL),
            "GetFileInformationByHandleEx": ([wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD], wintypes.BOOL),
            "SetFileInformationByHandle": ([wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD], wintypes.BOOL),
            "MoveFileExW": ([wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD], wintypes.BOOL),
            "CreateMutexW": ([ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR], wintypes.HANDLE),
            "WaitForSingleObject": ([wintypes.HANDLE, wintypes.DWORD], wintypes.DWORD),
            "ReleaseMutex": ([wintypes.HANDLE], wintypes.BOOL),
            "LocalFree": ([ctypes.c_void_p], ctypes.c_void_p),
            "GetVolumeInformationW": ([wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.DWORD, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, wintypes.LPWSTR, wintypes.DWORD], wintypes.BOOL),
        }
        for name, (arguments, result) in signatures.items():
            function = getattr(kernel, name)
            function.argtypes, function.restype = arguments, result
        _KERNEL = kernel
    return _KERNEL


def _ntfs(path: Path) -> None:
    filesystem = ctypes.create_unicode_buffer(64)
    if (not _kernel().GetVolumeInformationW(path.anchor, None, 0, None, None, None, filesystem, len(filesystem))
            or filesystem.value != "NTFS"):
        raise UpdateError("This updater requires a local NTFS drive for recoverable file swaps.")


class _Guard:
    def __init__(self):
        self.handles: dict[str, int] = {}

    def __enter__(self):
        return self

    def __exit__(self, *args):
        for handle in reversed(list(self.handles.values())):
            _kernel().CloseHandle(handle)
        self.handles.clear()

    def directory(self, path: Path, *, create: bool = False) -> None:
        path = _absolute(path)
        kernel = _kernel()
        for current in reversed((path, *path.parents)):
            key = str(current).casefold()
            if key in self.handles:
                continue
            if create and not _exists(current):
                current.mkdir(mode=0o700)
            before = _plain(current, directory=True)
            # GENERIC_READ establishes share-delete denial for the directory
            # itself; attribute-only access does not prevent a leaf rename.
            handle = kernel.CreateFileW(str(current), 0x80000000, 3, None, 3, 0x02200000, None)
            if handle in (None, ctypes.c_void_p(-1).value):
                raise UpdateError(f"Cannot hold an ordinary folder against renames: {current.name}")
            info = _FileInfo()
            identity = _FileIdInfo()
            if (not kernel.GetFileInformationByHandle(handle, ctypes.byref(info))
                    or info.attributes & 0x400 or not info.attributes & 0x10
                    or not kernel.GetFileInformationByHandleEx(handle, 18, ctypes.byref(identity), ctypes.sizeof(identity))
                    or (identity.volume, int.from_bytes(identity.file_id, "little")) != (before.st_dev, before.st_ino)):
                kernel.CloseHandle(handle)
                raise UpdateError("A folder changed or became a link while it was being checked.")
            self.handles[key] = handle


class _HeldFile:
    def __init__(self, path: Path, *, move: bool = False, create: bool = False, exclusive: bool = False, allow_origin: bool = False):
        self.path = _absolute(path)
        self.fp = None
        self.handle = None
        self.created, self.origin = create, None
        if not create:
            _plain(self.path)
        import msvcrt
        access = 0x80000000 | (0x10000 if move else 0) | (0x40000000 if create else 0)
        handle = _kernel().CreateFileW(str(self.path), access, 0 if exclusive or create else 1, None,
                                       1 if create else 3, 0x08200000, None)
        if handle in (None, ctypes.c_void_p(-1).value):
            raise UpdateError(f"Close programs using this file, or check access permissions: {self.path.name}")
        try:
            info = _FileInfo()
            if (not _kernel().GetFileInformationByHandle(handle, ctypes.byref(info))
                    or info.attributes & (0x400 | 0x10) or info.links != 1):
                raise UpdateError("A file is a link, special file, or has multiple hard links.")
            fd = msvcrt.open_osfhandle(int(handle), (os.O_RDWR if create else os.O_RDONLY) | os.O_BINARY)
        except BaseException:
            _kernel().CloseHandle(handle)
            raise
        try:
            self.fp = os.fdopen(fd, "r+b" if create else "rb", buffering=0)
        except BaseException:
            os.close(fd)
            raise
        self.handle = handle
        try:
            self.assert_name()
            from .origin import Lease
            self.origin = Lease(self, allow_origin=allow_origin)
        except BaseException:
            self.fp.close()
            raise

    def __enter__(self):
        return self

    def __exit__(self, *args):
        from .origin import CleanupError
        errors = []
        try:
            self.origin.close()
        except BaseException as exc:
            errors.append(exc)
        try:
            self.fp.close()
        except BaseException as exc:
            errors.append(exc)
        if errors:
            if len(args) > 1 and args[1] is not None:
                errors.insert(0, args[1])
            raise CleanupError(errors, self) from errors[0]

    def assert_name(self) -> None:
        path_info = _plain(self.path)
        file_info = os.fstat(self.fp.fileno())
        if (path_info.st_ino, path_info.st_dev) != (file_info.st_ino, file_info.st_dev):
            raise UpdateError("A file changed identity while it was being checked.")

    def fingerprint(self, maximum: int = MAX_FILE_BYTES) -> dict:
        self.origin.check()
        self.assert_name()
        before = os.fstat(self.fp.fileno())
        if before.st_size > maximum:
            raise UpdateError(f"A file exceeds the backup or verification quota: {self.path.name}")
        self.fp.seek(0)
        digest, total = hashlib.sha256(), 0
        while True:
            chunk = self.fp.read(IO_CHUNK)
            if not chunk:
                break
            digest.update(chunk)
            total += len(chunk)
            if total > maximum:
                raise UpdateError("A file grew beyond its verification quota.")
        after = os.fstat(self.fp.fileno())
        if (before.st_size, before.st_mtime_ns, before.st_ino) != (after.st_size, after.st_mtime_ns, after.st_ino) or total != before.st_size:
            raise UpdateError("A file changed during verification.")
        self.fp.seek(0)
        self.origin.check()
        return {"size": total, "sha256": digest.hexdigest(), "file_id": f"{before.st_dev}:{before.st_ino}", "mtime_ns": str(before.st_mtime_ns)}

    def move_to(self, destination: Path, guard: _Guard) -> None:
        """Rename THIS held object. Never replace an existing destination."""
        self.origin.check()
        self.assert_name()
        destination = _absolute(destination)
        guard.directory(destination.parent, create=True)
        if _exists(destination):
            raise UpdateError("A destination was created or changed by another program; nothing was overwritten.")
        class RenameInfo(ctypes.Structure):
            _fields_ = [("replace", wintypes.DWORD), ("root", wintypes.HANDLE),
                        ("length", wintypes.DWORD), ("name", wintypes.WCHAR * 1)]
        encoded = str(destination).encode("utf-16-le")
        buffer = ctypes.create_string_buffer(max(ctypes.sizeof(RenameInfo), RenameInfo.name.offset + len(encoded) + 2))
        info = RenameInfo.from_buffer(buffer)
        info.replace, info.root, info.length = 0, None, len(encoded)
        ctypes.memmove(ctypes.addressof(buffer) + RenameInfo.name.offset, encoded, len(encoded))
        if not _kernel().SetFileInformationByHandle(self.handle, 3, buffer, len(buffer)):
            raise UpdateError("An owned file could not be moved safely. Recovery files were retained.")
        self.path = destination
        self.assert_name()
        self.origin.check()


@contextlib.contextmanager
def _lease(root: Path):
    key = hashlib.sha256(str(root).casefold().encode("utf-8")).hexdigest()
    handle = _kernel().CreateMutexW(None, False, "Global\\Aeroneus.StellarBlade.Updater." + key)
    if not handle:
        raise UpdateError("Cannot acquire the exclusive updater lock.")
    acquired = False
    try:
        result = _kernel().WaitForSingleObject(handle, 0)
        acquired = result in (0, 0x80)
        if not acquired:
            raise UpdateError("Another updater is already working on this game.")
        yield
    finally:
        if acquired:
            _kernel().ReleaseMutex(handle)
        _kernel().CloseHandle(handle)


def _process_blockers() -> list[str]:
    class Entry(ctypes.Structure):
        _fields_ = [("size", wintypes.DWORD), ("usage", wintypes.DWORD), ("pid", wintypes.DWORD),
                    ("heap", ctypes.c_size_t), ("module", wintypes.DWORD), ("threads", wintypes.DWORD),
                    ("parent", wintypes.DWORD), ("priority", wintypes.LONG), ("flags", wintypes.DWORD),
                    ("exe", wintypes.WCHAR * 260)]
    kernel = _kernel()
    snapshot_fn = kernel.CreateToolhelp32Snapshot
    snapshot_fn.argtypes, snapshot_fn.restype = [wintypes.DWORD, wintypes.DWORD], wintypes.HANDLE
    first, following = kernel.Process32FirstW, kernel.Process32NextW
    for function in (first, following):
        function.argtypes, function.restype = [wintypes.HANDLE, ctypes.POINTER(Entry)], wintypes.BOOL
    snapshot = snapshot_fn(2, 0)
    if snapshot in (None, ctypes.c_void_p(-1).value):
        raise UpdateError("Cannot check running game and panel processes. Installation is unavailable.")
    blockers = []
    try:
        entry = Entry()
        entry.size = ctypes.sizeof(entry)
        if not first(snapshot, ctypes.byref(entry)):
            raise UpdateError("Cannot read the running-process list.")
        while True:
            name = entry.exe.casefold()
            if entry.pid != os.getpid():
                if (name in {"sb-win64-shipping.exe", "stellarblade.exe", "stellar blade.exe", "sb.exe",
                             "aeroneus.exe", "aeroneuslauncher.exe", "aeroneus launcher.exe",
                             "aeroneus-mod-launcher.exe"}
                        or ("stellar" in name and any(word in name for word in ("panel", "updat", "modsuite", "mod suite")))):
                    blockers.append(entry.exe)
                elif name in {"python.exe", "pythonw.exe", "py.exe", "pyw.exe"}:
                    command = _python_command(int(entry.pid))
                    if command is None:
                        raise UpdateError("Cannot rule out a running Python panel or old updater. Close it before installing.")
                    normalized = command.casefold().replace("\\", "/")
                    if ("qtpanel/main.py" in normalized or "stellarbladecontrolpanel" in normalized
                            or re.search(r"/(?:updater)/(?:launcher|shell|__main__)\.py(?:[\s\"]|$)", normalized)
                            or re.search(r"(?:^|\s)-m\s+updater(?:[.\s\"]|$)", normalized)
                            or re.search(r"/(?:stellarblade[-_ ]?)?(?:suite[-_ ]?)?updater(?:[-_ ]gui)?\.py(?:[\s\"]|$)", normalized)):
                        blockers.append("Python panel or updater")
            if not following(snapshot, ctypes.byref(entry)):
                if ctypes.get_last_error() != 18:
                    raise UpdateError("The running-process check did not finish.")
                break
    finally:
        kernel.CloseHandle(snapshot)
    return sorted(set(blockers))


def _python_command(pid: int) -> str | None:
    # Read command lines locally; never return them in an API result or log.
    kernel = _kernel()
    opening = kernel.OpenProcess
    opening.argtypes, opening.restype = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD], wintypes.HANDLE
    handle = opening(0x1000, False, pid)
    if not handle:
        return "" if ctypes.get_last_error() == 87 else None
    class UnicodeString(ctypes.Structure):
        _fields_ = [("length", wintypes.USHORT), ("maximum", wintypes.USHORT), ("buffer", ctypes.c_void_p)]
    try:
        query = ctypes.WinDLL("ntdll").NtQueryInformationProcess
        query.argtypes = [wintypes.HANDLE, ctypes.c_uint, ctypes.c_void_p, wintypes.ULONG, ctypes.POINTER(wintypes.ULONG)]
        query.restype = ctypes.c_long
        needed = wintypes.ULONG()
        query(handle, 60, None, 0, ctypes.byref(needed))
        if not ctypes.sizeof(UnicodeString) <= needed.value <= 65536:
            return None
        data = ctypes.create_string_buffer(needed.value)
        if query(handle, 60, data, len(data), ctypes.byref(needed)) < 0:
            return None
        text = UnicodeString.from_buffer(data)
        start, end = ctypes.addressof(data), ctypes.addressof(data) + len(data)
        if not text.buffer or text.length % 2 or not start <= text.buffer <= text.buffer + text.length <= end:
            return None
        return ctypes.string_at(text.buffer, text.length).decode("utf-16-le", errors="strict")
    except (OSError, UnicodeError, ValueError):
        return None
    finally:
        kernel.CloseHandle(handle)


def _read_held(file: _HeldFile, maximum: int) -> bytes:
    file.fp.seek(0)
    result = file.fp.read(maximum + 1)
    file.fp.seek(0)
    if len(result) > maximum:
        raise UpdateError("A configuration or control file exceeds its read limit.")
    return result


def _vdf(raw: bytes) -> dict:
    try:
        text = raw.decode("utf-8-sig", errors="strict")
    except UnicodeError as exc:
        raise UpdateError("The Steam app manifest is not readable UTF-8.") from exc
    tokens = []
    position = 0
    pattern = re.compile(r'\s+|//[^\r\n]*|"((?:[^"\\]|\\["\\])*)"|([{}])')
    while position < len(text):
        match = pattern.match(text, position)
        if not match:
            raise UpdateError("The Steam app manifest has invalid syntax.")
        position = match.end()
        if match.group(1) is not None:
            tokens.append(match.group(1).replace('\\"', '"').replace("\\\\", "\\"))
        elif match.group(2):
            tokens.append(match.group(2))
    index = 0
    def parse(depth: int = 0, nested: bool = False):
        nonlocal index
        if depth > 12:
            raise UpdateError("The Steam app manifest is nested too deeply.")
        result = {}
        while index < len(tokens):
            key = tokens[index]
            index += 1
            if key == "}":
                if not nested:
                    raise UpdateError("The Steam app manifest has an extra closing brace.")
                return result
            if key == "{" or index >= len(tokens) or key.casefold() in result:
                raise UpdateError("The Steam app manifest has ambiguous or missing fields.")
            value = tokens[index]
            index += 1
            if value == "}":
                raise UpdateError("The Steam app manifest has a missing value.")
            result[key.casefold()] = parse(depth + 1, True) if value == "{" else value
        if nested:
            raise UpdateError("The Steam app manifest has a missing closing brace.")
        return result
    return parse()


def _appmanifest(root: Path) -> Path:
    if root.parent.name.casefold() != "common" or root.parent.parent.name.casefold() != "steamapps":
        raise UpdateError("Select the Stellar Blade folder inside its Steam library's steamapps/common folder.")
    return root.parent.parent / f"appmanifest_{STEAM_APP_ID}.acf"


def _game_identity(root: Path, guard: _Guard, stack: contextlib.ExitStack, *, exclusive: bool = True) -> dict:
    guard.directory(root)
    _ntfs(root)
    exe_path, app_path = root / GAME_EXE_PATH, _appmanifest(root)
    guard.directory(exe_path.parent)
    guard.directory(app_path.parent)
    # Exclusive read blocks new executable opens while a transaction is active.
    exe = stack.enter_context(_HeldFile(exe_path, exclusive=exclusive, allow_origin=True))
    app = stack.enter_context(_HeldFile(app_path, allow_origin=True))
    app_state = _vdf(_read_held(app, MAX_PAYLOAD_BYTES)).get("appstate")
    if (type(app_state) is not dict or app_state.get("appid") != STEAM_APP_ID
            or app_state.get("installdir", "").casefold() != root.name.casefold()
            or app_state.get("buildid") != SUPPORTED_BUILD_ID or app_state.get("stateflags") != "4"):
        raise UpdateError("The Steam app manifest does not identify a fully installed Stellar Blade build 24463856 in this folder.")
    fingerprint = exe.fingerprint()
    if (fingerprint["size"], fingerprint["sha256"]) != (SUPPORTED_EXE_SIZE, SUPPORTED_EXE_SHA256):
        raise UpdateError("The game executable does not match the supported Stellar Blade build. Installation is unavailable.")
    return {"exe": fingerprint, "appmanifest": app.fingerprint(MAX_PAYLOAD_BYTES), "root_id": f"{root.stat().st_dev}:{root.stat().st_ino}"}


def _suite_version(root: Path, guard: _Guard) -> str:
    path = root / VERSION_PATH
    guard.directory(path.parent)
    with _HeldFile(path, allow_origin=True) as file:
        try:
            version = _read_held(file, 64).decode("ascii").strip()
        except UnicodeError as exc:
            raise UpdateError("The installed suite VERSION file is invalid.") from exc
    _version(version)
    return version


def _suite_check(root: Path, guard: _Guard) -> dict[str, tuple[int, str]]:
    # Unknown loaders or shared helpers may belong to another mod. Refuse them.
    for path, expected in {**APPROVED_RUNTIME, _VTABLE_PATH: _VTABLE_ID}.items():
        guard.directory((root / path).parent)
        with _HeldFile(root / path, allow_origin=True) as file:
            actual = file.fingerprint()
        if (actual["size"], actual["sha256"]) != expected:
            raise UpdateError(f"Unrecognized loader or shared runtime file: {path}. Resolve the mod conflict before updating.")
    expected_files = dict(_BASELINE_FILES)
    pointer = _anchor(root)
    if pointer:
        if pointer["state"] == "active":
            raise UpdateError("Recover the interrupted update before opening the panel or installing.")
        transaction = _absolute(pointer["transaction_dir"])
        history = _journal(transaction, guard)
        if history["game_root"] != str(root):
            raise UpdateError("The installed suite receipt belongs to a different game.")
        if pointer["state"] == "committed" and history["state"] == "committed":
            expected_files = {f["path"]: (f["size"], f["sha256"]) for f in history["manifest"]["files"]}
        elif pointer["state"] == "clear" and history["state"] == "rolled_back":
            expected_files = {f["path"]: (f["size"], f["sha256"]) for f in history["manifest"]["files"]}
            for action in history["actions"]:
                before = action["before"]
                if before is not None:
                    expected_files[action["path"]] = (before["size"], before["sha256"])
                else:
                    expected_files.pop(action["path"], None)
        else:
            raise UpdateError("The installed suite receipt needs recovery before the panel can be opened.")
    for path in REQUIRED_FILES - APPROVED_RUNTIME.keys():
        guard.directory((root / path).parent)
        with _HeldFile(root / path, allow_origin=True) as file:
            actual = file.fingerprint()
        if (actual["size"], actual["sha256"]) != expected_files.get(path):
            raise UpdateError(f"The installed panel or mod file is unknown or changed: {path}")
    settings = root / (WIN64 + "ue4ss/UE4SS-settings.ini")
    _plain(settings)
    if settings.stat().st_size > 1024 * 1024:
        raise UpdateError("The UE4SS settings file exceeds the supported size.")
    win64 = root / WIN64
    if any(_exists(win64 / name) for name in ("UE4SS.dll", "UE4SS-settings.ini", "UE4SS_Signatures")):
        raise UpdateError("An older loose UE4SS installation conflicts with this bundle. Resolve it before updating.")
    return expected_files


class _Blob(ctypes.Structure):
    _fields_ = [("size", wintypes.DWORD), ("data", ctypes.POINTER(ctypes.c_ubyte))]


def _dpapi(raw: bytes, *, decrypt: bool = False) -> bytes:
    _kernel()
    storage = ctypes.create_string_buffer(raw)
    incoming = _Blob(len(raw), ctypes.cast(storage, ctypes.POINTER(ctypes.c_ubyte)))
    outgoing = _Blob()
    crypt = ctypes.WinDLL("crypt32", use_last_error=True)
    function = crypt.CryptUnprotectData if decrypt else crypt.CryptProtectData
    second_type = ctypes.c_void_p if decrypt else wintypes.LPCWSTR
    function.argtypes = [ctypes.POINTER(_Blob), second_type, ctypes.c_void_p, ctypes.c_void_p,
                         ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(_Blob)]
    function.restype = wintypes.BOOL
    if not function(ctypes.byref(incoming), None if decrypt else "Aeroneus Stellar Blade updater", None, None, None, 1, ctypes.byref(outgoing)):
        raise UpdateError("The recovery journal cannot be authenticated for this Windows account.")
    try:
        if outgoing.size > MAX_JOURNAL_BYTES + 65536:
            raise UpdateError("The recovery journal exceeds its size limit.")
        return ctypes.string_at(outgoing.data, outgoing.size)
    finally:
        _kernel().LocalFree(outgoing.data)


def _read_sealed(path: Path) -> dict:
    with _HeldFile(path) as file:
        raw = _read_held(file, MAX_JOURNAL_BYTES + 65536)
    result = _json(_dpapi(raw, decrypt=True), MAX_JOURNAL_BYTES, "Recovery journal")
    if type(result) is not dict:
        raise UpdateError("The authenticated recovery journal is invalid.")
    return result


def _write_sealed(path: Path, value: dict, guard: _Guard) -> None:
    guard.directory(path.parent, create=True)
    raw = _canonical(value)
    if len(raw) > MAX_JOURNAL_BYTES:
        raise UpdateError("The recovery journal exceeds its size limit.")
    if _exists(path):
        _read_sealed(path)  # Never silently replace a foreign or corrupt file.
    temporary = path.parent / ("journal-pending-" + uuid.uuid4().hex)
    with temporary.open("xb") as output:
        output.write(_dpapi(raw))
        output.flush()
        os.fsync(output.fileno())
    # Only our authenticated metadata is replaced. No player file uses this API.
    if not _kernel().MoveFileExW(str(temporary), str(path), 0x1 | 0x8):
        raise UpdateError("The durable recovery journal could not be committed. Its pending copy was retained.")


def _anchor_path(root: Path) -> Path:
    return root / _CONTROL_NAME / "active.dpapi"


def _anchor(root: Path) -> dict | None:
    path = _anchor_path(root)
    if not _exists(path):
        return None
    _ancestors(path.parent)
    obj = _shape(_read_sealed(path), {"schema", "game_root", "transaction_dir", "state"}, "Updater recovery pointer")
    _integer(obj["schema"], 1, 1, "Recovery pointer schema")
    if obj["game_root"] != str(root) or obj["state"] not in ("active", "committed", "clear"):
        raise UpdateError("The recovery pointer belongs to a different game or is invalid.")
    if obj["state"] != "clear":
        _absolute(obj["transaction_dir"])
    return obj


def _set_anchor(root: Path, transaction: Path, state: str, guard: _Guard) -> None:
    _write_sealed(_anchor_path(root), {"schema": 1, "game_root": str(root),
                  "transaction_dir": str(transaction), "state": state}, guard)


def inspect_install(game_root: os.PathLike | str) -> dict:
    """Read-only inspection. A stage cannot be authorized by inspection alone.

    ``supported_build`` means the exact executable AND Steam build matched.
    ``ready_for_update`` additionally checks suite/runtime/process/recovery state.
    ``install_available`` stays False here: apply independently verifies a stage.
    """
    result = {"game_root": str(game_root), "version": "", "build_id": "", "supported_build": False,
              "supported": False, "ready_for_update": False, "install_available": False,
              "blockers": [], "recovery_transaction": "", "panel_verified": False}
    try:
        root = _absolute(game_root)
        result["game_root"] = str(root)
        with _Guard() as guard, contextlib.ExitStack() as stack:
            guard.directory(root)
            pointer = _anchor(root)
            if pointer and pointer["state"] == "active":
                result["recovery_transaction"] = pointer["transaction_dir"]
                result["blockers"].append("An interrupted update must be rolled back before installing.")
            _game_identity(root, guard, stack, exclusive=False)
            result.update(build_id=SUPPORTED_BUILD_ID, supported_build=True, supported=True)
            result["version"] = _suite_version(root, guard)
            _suite_check(root, guard)
            result["panel_verified"] = True
            blocked = _process_blockers()
            if blocked:
                result["blockers"].append("Close the game, panel, and other updater: " + ", ".join(blocked))
            result["ready_for_update"] = not result["blockers"]
    except (UpdateError, OSError, ValueError) as exc:
        result["blockers"].append(str(exc) if isinstance(exc, UpdateError) else "The selected game or suite files cannot be verified.")
    return result


def _matches(actual: dict | None, expected: dict | None) -> bool:
    return actual == expected


def _signed_match(actual: dict, spec: dict) -> bool:
    return (actual["size"], actual["sha256"]) == (spec["size"], spec["sha256"])


def _different_trees(first: Path, second: Path) -> None:
    first_parts = tuple(part.casefold() for part in first.parts)
    second_parts = tuple(part.casefold() for part in second.parts)
    common = min(len(first_parts), len(second_parts))
    if first_parts[:common] == second_parts[:common]:
        raise UpdateError("Game, staging, and transaction folders must be separate directory trees.")


def _stage_files(stage: Path, signed: dict, envelope: dict, guard: _Guard,
                 stack: contextlib.ExitStack) -> dict[str, _HeldFile]:
    if not re.fullmatch(r"suite-stage-[0-9a-f]{32}", stage.name):
        raise UpdateError("Select a staging folder created by this updater.")
    guard.directory(stage)
    allowed = {"release.zip", "release-envelope.json", *(_slot(stage, "files", f["path"]).relative_to(stage).as_posix() for f in signed["files"])}
    directories = set()
    for name in allowed:
        components = name.split("/")
        directories.update("/".join(components[:i]) for i in range(1, len(components)))
    pending = [stage]
    found = set()
    while pending:
        parent = pending.pop()
        guard.directory(parent)
        with os.scandir(parent) as entries:
            for entry in entries:
                path = Path(entry.path)
                relative = path.relative_to(stage).as_posix()
                info = path.lstat()
                if stat.S_ISDIR(info.st_mode):
                    _plain(path, directory=True)
                    if relative not in directories:
                        raise UpdateError("The stage contains an unapproved folder.")
                    pending.append(path)
                else:
                    _plain(path)
                    if relative not in allowed or relative.casefold() in found:
                        raise UpdateError("The stage contains unexpected or colliding files.")
                    found.add(relative.casefold())
    if found != {name.casefold() for name in allowed}:
        raise UpdateError("The stage is incomplete. Download the signed bundle again.")
    saved_envelope = stack.enter_context(_HeldFile(stage / "release-envelope.json"))
    if _canonical(_json(_read_held(saved_envelope, 2 * MAX_PAYLOAD_BYTES), 2 * MAX_PAYLOAD_BYTES, "Staged envelope")) != _canonical(envelope):
        raise UpdateError("The stage belongs to a different signed release.")
    archive_file = stack.enter_context(_HeldFile(stage / "release.zip", allow_origin=True))
    if not _signed_match(archive_file.fingerprint(MAX_ARCHIVE_BYTES), signed["archive"]):
        raise UpdateError("The retained archive no longer matches the signed release.")
    archive, _ = _zip_index(archive_file.fp, signed)
    archive.close()
    files = {}
    for spec in signed["files"]:
        source = _slot(stage, "files", spec["path"])
        guard.directory(source.parent)
        held = stack.enter_context(_HeldFile(source, allow_origin=True))
        if not _signed_match(held.fingerprint(), spec):
            raise UpdateError(f"A staged file no longer matches the signed release: {spec['path']}")
        files[spec["path"]] = held
    try:
        version = _read_held(files[VERSION_PATH], 64).decode("ascii").strip()
    except UnicodeError as exc:
        raise UpdateError("The staged VERSION file is not valid ASCII.") from exc
    if version != signed["version"]:
        raise UpdateError("The staged VERSION file differs from the signed release.")
    return files


def _fingerprint_shape(value: Any) -> dict:
    _shape(value, {"size", "sha256", "file_id", "mtime_ns"}, "Recorded file identity")
    _integer(value["size"], 0, MAX_FILE_BYTES, "Recorded file size")
    _hash_text(value["sha256"])
    if (type(value["file_id"]) is not str or not re.fullmatch(r"[0-9]{1,24}:[0-9]{1,40}", value["file_id"])
            or type(value["mtime_ns"]) is not str or not re.fullmatch(r"[0-9]{1,24}", value["mtime_ns"])):
        raise UpdateError("A recorded file identity is invalid.")
    return value


def _journal(transaction: Path, guard: _Guard) -> dict:
    if not re.fullmatch(r"suite-transaction-[0-9a-f]{32}", transaction.name):
        raise UpdateError("Select a retained transaction folder created by this updater.")
    guard.directory(transaction)
    decoded = _read_sealed(transaction / "journal.dpapi")
    fresh = type(decoded) is dict and decoded.get("schema") == 2
    obj = _shape(decoded, {
        "schema", "product", "transaction_dir", "game_root", "game_identity", "version_before",
        "version", "manifest", "state", "actions",
    } | ({"operation"} if fresh else set()), "Recovery transaction")
    _integer(obj["schema"], 2 if fresh else 1, 2 if fresh else 1, "Recovery schema")
    if obj["product"] != PRODUCT or obj["transaction_dir"] != str(transaction):
        raise UpdateError("The authenticated transaction belongs to a different location or product.")
    root = _absolute(obj["game_root"])
    _different_trees(root, transaction)
    identity = _shape(obj["game_identity"], {"exe", "appmanifest", "root_id"}, "Recorded game identity")
    _fingerprint_shape(identity["exe"])
    _fingerprint_shape(identity["appmanifest"])
    if type(identity["root_id"]) is not str or not re.fullmatch(r"[0-9]{1,24}:[0-9]{1,40}", identity["root_id"]):
        raise UpdateError("The recorded game folder identity is invalid.")
    _version(obj["version"])
    if fresh:
        from . import fresh_install
        if obj["operation"] != fresh_install.OPERATION or obj["version_before"] is not None:
            raise UpdateError("The first-install recovery operation is invalid.")
        signed = fresh_install._validate_payload(obj["manifest"])
    else:
        _version(obj["version_before"])
        signed = _validate_payload(obj["manifest"])
    if (signed["version"] != obj["version"] or
            (not fresh and _version(obj["version"]) <= _version(obj["version_before"]))):
        raise UpdateError("The transaction's release versions are inconsistent.")
    if obj["state"] not in {"prepared", "applying", "committed", "rolling_back", "rolled_back", "recovery_required"}:
        raise UpdateError("The recovery transaction has an invalid state.")
    specs = {f["path"]: f for f in signed["files"]}
    actions = obj["actions"]
    if type(actions) is not list or not 1 <= len(actions) <= MAX_FILES:
        raise UpdateError("The recovery transaction has an invalid action list.")
    seen, total = set(), 0
    for action in actions:
        _shape(action, {"path", "before", "after", "phase"}, "Recovery action")
        path = _relative(action["path"])
        if path not in specs or path in seen:
            raise UpdateError("The recovery transaction lists an unapproved or repeated file.")
        seen.add(path)
        _fingerprint_shape(action["after"])
        if not _signed_match(action["after"], specs[path]):
            raise UpdateError("The recovery target differs from the verified release.")
        if action["before"] is not None:
            if fresh:
                raise UpdateError("A first installation cannot replace a pre-existing file.")
            _fingerprint_shape(action["before"])
            total += action["before"]["size"]
        if action["phase"] not in {"prepared", "swapping", "applied", "restoring", "rolled_back"}:
            raise UpdateError("A recovery action has an invalid state.")
    if total > MAX_UNCOMPRESSED_BYTES or VERSION_PATH not in seen:
        raise UpdateError("The recovery plan is incomplete or exceeds its backup quota.")
    if fresh:
        ordered = sorted(specs, key=lambda path: (path == fresh_install.LOADER_PATH,
                                                  path == VERSION_PATH, path))
        if [action["path"] for action in actions] != ordered:
            raise UpdateError("The first-install recovery plan must cover every file with loader activation last.")
    return obj


def describe_transaction(transaction_dir: os.PathLike | str) -> dict:
    """Authenticate a retained journal before showing the rollback target.

    Returns game_root, version, version_before, status, transaction_dir,
    files_changed. It does not authorize a write or claim files are unchanged.
    """
    try:
        transaction = _absolute(transaction_dir)
        with _Guard() as guard:
            obj = _journal(transaction, guard)
            return {"game_root": obj["game_root"], "version": obj["version"],
                    "version_before": obj["version_before"], "status": obj["state"],
                    "transaction_dir": str(transaction), "files_changed": len(obj["actions"])}
    except UpdateError:
        raise
    except (OSError, ValueError) as exc:
        raise UpdateError("The recovery transaction cannot be read or authenticated.") from exc


def _save_journal(transaction: Path, obj: dict, guard: _Guard) -> None:
    _write_sealed(transaction / "journal.dpapi", obj, guard)


def apply_update(game_root: os.PathLike | str, stage_dir: os.PathLike | str,
                 manifest: dict, backup_parent: os.PathLike | str) -> dict:
    """Install only the signed code list, with a complete backup and journal first.

    Returns {transaction_dir, status:'committed', version, files_changed}.
    Existing configurations and unlisted files are never installed/removed.
    Unknown loader bytes, stale stages, older/equal versions, busy processes,
    other volumes and interrupted transactions fail closed. Swaps use two
    atomic non-clobber renames: old to retained originals, prepared to target.
    There can be a recoverable missing-file window; the whole update is not
    globally atomic. An error attempts rollback and always reports failure.
    """
    return _apply_release(game_root, stage_dir, manifest, backup_parent, fresh=False)


def apply_fresh_install(game_root: os.PathLike | str, stage_dir: os.PathLike | str,
                        manifest: dict, backup_parent: os.PathLike | str) -> dict:
    """Install the separately authenticated clean-game inventory; activate last.

    The compiled fresh adapter checks exact bootstrap bytes and conflicts. The
    existing retained-handle transaction and rollback machinery owns all writes.
    An interrupted first install has a schema-2 journal and no prior version.
    """
    return _apply_release(game_root, stage_dir, manifest, backup_parent, fresh=True)


def _apply_release(game_root, stage_dir, manifest, backup_parent, *, fresh):
    if fresh:
        from . import fresh_install
        trust = fresh_install._trusted
    else:
        trust = _trusted
    signed, envelope = trust(manifest)
    root, stage, parent = _absolute(game_root), _absolute(stage_dir), _absolute(backup_parent)
    _different_trees(root, stage)
    transaction = None
    active = False
    try:
        with _lease(root), _Guard() as guard, contextlib.ExitStack() as stack:
            guard.directory(root)
            pointer = _anchor(root)
            if pointer and pointer["state"] == "active":
                raise UpdateError("Recover the interrupted update before installing: " + pointer["transaction_dir"])
            blocked = _process_blockers()
            if blocked:
                raise UpdateError("Close the game, panel, and other updater before installing: " + ", ".join(blocked))
            identity = _game_identity(root, guard, stack)
            if fresh:
                fresh_install._clean_check(root, guard)
                previous_version, expected_before = None, {}
            else:
                previous_version = _suite_version(root, guard)
                if _version(signed["version"]) <= _version(previous_version):
                    raise UpdateError("This release is older than or equal to the installed suite. Use explicit rollback to restore a backup.")
                expected_before = _suite_check(root, guard)
            sources = _stage_files(stage, signed, envelope, guard, stack)
            guard.directory(parent, create=True)
            _ntfs(parent)
            if parent.stat().st_dev != root.stat().st_dev:
                raise UpdateError("Choose a backup folder on the same NTFS volume as the selected game.")
            transaction = _new_dir(parent, "suite-transaction-")
            _different_trees(root, transaction)
            _different_trees(stage, transaction)
            guard.directory(transaction)
            # Hold every existing target before taking ANY preimage. These
            # handles deny write/delete and remain held through all swaps.
            targets: dict[str, _HeldFile | None] = {}
            before_by_path = {}
            for spec in signed["files"]:
                destination = root / spec["path"]
                if not fresh:
                    guard.directory(destination.parent, create=True)
                elif _exists(destination):
                    raise UpdateError("First installation would replace an existing file.")
                target = stack.enter_context(_HeldFile(destination, move=True, exclusive=True, allow_origin=True)) if _exists(destination) else None
                targets[spec["path"]] = target
                before_by_path[spec["path"]] = target.fingerprint() if target else None
                if not fresh and spec["path"] in REQUIRED_FILES:
                    actual = before_by_path[spec["path"]]
                    if actual is None or (actual["size"], actual["sha256"]) != expected_before.get(spec["path"]):
                        raise UpdateError("An installed loader, panel, or mod changed after compatibility inspection.")
            changed = [spec for spec in signed["files"] if before_by_path[spec["path"]] is None
                       or not _signed_match(before_by_path[spec["path"]], spec)]
            # VERSION is switched last; its changed bytes bind every update.
            if fresh:
                changed.sort(key=lambda spec: (spec["path"] == fresh_install.LOADER_PATH,
                                               spec["path"] == VERSION_PATH, spec["path"]))
            else:
                changed.sort(key=lambda spec: (spec["path"] == VERSION_PATH, spec["path"]))
            if VERSION_PATH not in {spec["path"] for spec in changed}:
                raise UpdateError("The installed VERSION file does not permit this release transition.")
            backup_bytes = sum(before_by_path[s["path"]]["size"] for s in changed if before_by_path[s["path"]] is not None)
            if backup_bytes > MAX_UNCOMPRESSED_BYTES:
                raise UpdateError("The existing owned files exceed the 4 GiB backup quota.")
            _space(parent, backup_bytes + sum(s["size"] for s in changed) + 2 * len(changed) * MAX_ORIGIN_BYTES)
            prepared = {}
            actions = []
            for spec in changed:
                path, before = spec["path"], before_by_path[spec["path"]]
                if before is not None:
                    backup = _slot(transaction, "backup", path)
                    guard.directory(backup.parent, create=True)
                    target = targets[path]
                    _consumer_copy(target.fp, backup, before, guard, target)
                replacement = _slot(transaction, "prepared", path)
                guard.directory(replacement.parent, create=True)
                # Finish the writer before recording mtime. Windows can defer
                # its last-write timestamp until the writing handle closes.
                _consumer_copy(sources[path].fp, replacement, spec, guard, sources[path])
                prepared_handle = stack.enter_context(_HeldFile(replacement, move=True, exclusive=True, allow_origin=True))
                after = prepared_handle.fingerprint()
                prepared[path] = prepared_handle
                actions.append({"path": path, "before": before, "after": after, "phase": "prepared"})
            obj = {"schema": 1, "product": PRODUCT, "transaction_dir": str(transaction),
                   "game_root": str(root), "game_identity": identity, "version_before": previous_version,
                   "version": signed["version"], "manifest": signed, "state": "prepared", "actions": actions}
            if fresh:
                fresh_install._precommit_clean_check(root, guard, signed)
                obj.update(schema=2, operation=fresh_install.OPERATION)
            _save_journal(transaction, obj, guard)
            _set_anchor(root, transaction, "active", guard)
            active = True
            obj["state"] = "applying"
            _save_journal(transaction, obj, guard)
            if _process_blockers():
                raise UpdateError("The game, panel, or another updater started during preparation.")
            # Signature and payload are rechecked at the mutation boundary.
            trust(manifest)
            for action in actions:
                path = action["path"]
                if fresh:
                    if path == fresh_install.LOADER_PATH:
                        fresh_install._installed_layout_check(root, guard, signed, exclude_loader=True)
                    guard.directory((root / path).parent, create=True)
                target = targets[path]
                if target is not None and not _matches(target.fingerprint(), action["before"]):
                    raise UpdateError("An installed file changed after its backup was made.")
                if not _matches(prepared[path].fingerprint(), action["after"]):
                    raise UpdateError("A prepared file changed before installation.")
                action["phase"] = "swapping"
                _save_journal(transaction, obj, guard)
                if target is not None:
                    target.move_to(_slot(transaction, "originals", path), guard)
                prepared[path].move_to(root / path, guard)
                action["phase"] = "applied"
                _save_journal(transaction, obj, guard)
            for action in actions:
                if not _matches(prepared[action["path"]].fingerprint(), action["after"]):
                    raise UpdateError("An installed file did not match the prepared release.")
            if fresh:
                fresh_install._installed_layout_check(root, guard, signed, exclude_loader=False)
            obj["state"] = "committed"
            _save_journal(transaction, obj, guard)
            _set_anchor(root, transaction, "committed", guard)
            active = False
            return {"transaction_dir": str(transaction), "status": "committed", "version": signed["version"], "files_changed": len(actions)}
    except (UpdateError, OSError, ValueError, zipfile.BadZipFile, RuntimeError) as exc:
        reason = str(exc) if isinstance(exc, UpdateError) else "An update file operation failed."
        if active and transaction is not None:
            try:
                rollback(transaction, expected_game_root=root)
            except (UpdateError, OSError, ValueError) as recovery_error:
                raise UpdateError(reason + " Recovery is required; nothing was discarded. Transaction: " + str(transaction)
                                  + ". " + str(recovery_error)) from exc
            raise UpdateError(reason + " The update was rolled back. Retained transaction: " + str(transaction)) from exc
        raise UpdateError(reason + (" Retained preparation: " + str(transaction) if transaction else "")) from exc


def rollback(transaction_dir: os.PathLike | str, expected_game_root: os.PathLike | str | None = None) -> dict:
    """Restore exact owned preimages, retaining every replaced/new release file.

    Returns {transaction_dir, status:'rolled_back', version, files_restored}.
    Also handles crashes before/after either swap rename. A changed identity,
    hash, or modification time is a conflict, even when bytes look similar.
    All conflicts and backups are checked before restoring ANY file. The
    optional expected_game_root must match the authenticated target exactly.
    """
    try:
        transaction = _absolute(transaction_dir)
        with _Guard() as initial_guard:
            initial = _journal(transaction, initial_guard)
        root = _absolute(initial["game_root"])
        if expected_game_root is not None and str(_absolute(expected_game_root)).casefold() != str(root).casefold():
            raise UpdateError("This recovery transaction belongs to a different selected game folder.")
        with _lease(root), _Guard() as guard, contextlib.ExitStack() as stack:
            obj = _journal(transaction, guard)
            if obj["game_root"] != str(root):
                raise UpdateError("The recovery target changed while acquiring the updater lock.")
            guard.directory(root)
            if transaction.stat().st_dev != root.stat().st_dev:
                raise UpdateError("The retained transaction must be on the game's NTFS volume.")
            if _process_blockers():
                raise UpdateError("Close the game, panel, and other updater before recovery.")
            identity = _game_identity(root, guard, stack)
            if identity["root_id"] != obj["game_identity"]["root_id"] or identity["exe"] != obj["game_identity"]["exe"]:
                raise UpdateError("The game folder or executable changed since this transaction. Automatic recovery is unavailable.")
            pointer = _anchor(root)
            if pointer and pointer["state"] != "clear" and pointer["transaction_dir"] != str(transaction):
                raise UpdateError("A different, newer transaction owns this game. Recover it first.")
            plans = []
            # Preflight every target and retained original before any mutation.
            for action in reversed(obj["actions"]):
                path, before, after = action["path"], action["before"], action["after"]
                destination = root / path
                guard.directory(destination.parent, create=True)
                current = stack.enter_context(_HeldFile(destination, move=True, exclusive=True, allow_origin=True)) if _exists(destination) else None
                current_id = current.fingerprint() if current else None
                if _matches(current_id, before):
                    plans.append((action, None, None))
                    continue
                if current_id is not None and not _matches(current_id, after):
                    raise UpdateError(f"Recovery refused to overwrite a file changed outside this update: {path}")
                original = None
                if before is not None:
                    backup_path = _slot(transaction, "backup", path)
                    original_path = _slot(transaction, "originals", path)
                    guard.directory(backup_path.parent)
                    guard.directory(original_path.parent)
                    backup = stack.enter_context(_HeldFile(backup_path, allow_origin=True))
                    if not _signed_match(backup.fingerprint(), before):
                        raise UpdateError(f"The exact preimage backup is missing or changed: {path}")
                    original = stack.enter_context(_HeldFile(original_path, move=True, exclusive=True, allow_origin=True))
                    if not _matches(original.fingerprint(), before):
                        raise UpdateError(f"A retained original changed; it will not be used for recovery: {path}")
                if current is not None and _exists(_slot(transaction, "failed", path)):
                    raise UpdateError("A retained failed-file destination already exists; recovery will not overwrite it.")
                plans.append((action, current, original))
            obj["state"] = "rolling_back"
            _save_journal(transaction, obj, guard)
            _set_anchor(root, transaction, "active", guard)
            restored = 0
            for action, current, original in plans:
                if current is None and original is None:
                    action["phase"] = "rolled_back"
                    continue
                action["phase"] = "restoring"
                _save_journal(transaction, obj, guard)
                if current is not None:
                    if not _matches(current.fingerprint(), action["after"]):
                        raise UpdateError("An installed file changed during recovery. It was not overwritten.")
                    current.move_to(_slot(transaction, "failed", action["path"]), guard)
                if original is not None:
                    if not _matches(original.fingerprint(), action["before"]):
                        raise UpdateError("A retained original changed during recovery.")
                    original.move_to(root / action["path"], guard)
                action["phase"] = "rolled_back"
                _save_journal(transaction, obj, guard)
                restored += 1
            obj["state"] = "rolled_back"
            _save_journal(transaction, obj, guard)
            _set_anchor(root, transaction, "clear", guard)
            return {"transaction_dir": str(transaction), "status": "rolled_back", "version": obj["version_before"], "files_restored": restored}
    except UpdateError:
        raise
    except (OSError, ValueError, RuntimeError) as exc:
        raise UpdateError("Recovery could not finish safely. The transaction and all retained files remain available.") from exc

