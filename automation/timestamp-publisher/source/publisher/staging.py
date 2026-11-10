"""Stage a flat TUF repository using supplied public trust and signer objects.

Windows/NTFS only. Nothing here fetches, publishes, loads keys, creates keys,
executes target content, or edits the client's trust configuration. See README.
"""
from __future__ import annotations

import ctypes
import hashlib
import importlib.metadata
import os
import re
import shutil
from collections.abc import Mapping
from contextlib import ExitStack
from ctypes import wintypes
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from securesystemslib.signer import Signer
from tuf.api.metadata import (
    Metadata,
    MetaFile,
    Root,
    Snapshot,
    TargetFile,
    Targets,
    Timestamp,
)
from updater import (
    catalog,
    core,
    fresh_install,
    launcher_targets,
    self_update,
    tuf_channel,
)

ROLES = ("targets", "snapshot", "timestamp")
METADATA_LIMITS = {"root": 512000, "targets": 2_000_000,
                   "snapshot": 2_000_000, "timestamp": 16384}
MAX_TARGETS = 128
MAX_TOTAL_BYTES = 128 * 1024**2
MAX_VERSION = 2**31 - 1
RESERVE = 80 * 1024**3
RECEIPT = "staging-complete.json"
_LIFETIMES = {"targets": timedelta(days=31), "snapshot": timedelta(days=7),
              "timestamp": timedelta(days=1)}


class StagingError(ValueError):
    """Refused staging; existing files and any partial directory are retained."""


class StagingCommitUncertain(StagingError):
    """Completion could not be disproved; no candidate is admitted by this error."""


@dataclass(frozen=True)
class RolePolicy:
    version: int
    expires: datetime


@dataclass(frozen=True)
class Policy:
    targets: RolePolicy
    snapshot: RolePolicy
    timestamp: RolePolicy


def _require(condition, message):
    if not condition:
        raise StagingError(message)


def _version(value):
    _require(type(value) is int and 1 <= value <= MAX_VERSION,
             "Metadata version must be a bounded positive integer.")
    return value


def _utc(value):
    _require(isinstance(value, datetime) and value.tzinfo is not None
             and value.utcoffset() is not None and value.microsecond == 0,
             "Expiry must be timezone-aware and have whole-second precision.")
    return value.astimezone(timezone.utc)


def _parse(raw, role):
    # Reject duplicate fields, floats, excessive nesting and private-key fields
    # before the maintained TUF parser sees the same bytes.
    obj = catalog.bounded_json(raw, METADATA_LIMITS[role])
    _require(type(obj) is dict and set(obj) == {"signed", "signatures"},
             "Metadata must contain only signed data and signatures.")
    signed = obj["signed"]
    common = {"_type", "spec_version", "version", "expires"}
    fields = {"root": {"keys", "roles", "consistent_snapshot"},
              "targets": {"targets"}, "snapshot": {"meta"}, "timestamp": {"meta"}}
    _require(type(signed) is dict and set(signed) == common | fields[role]
             and signed["_type"] == role, "Unsupported metadata role or fields.")
    _version(signed["version"])
    if role in {"snapshot", "timestamp"}:
        expected = "targets.json" if role == "snapshot" else "snapshot.json"
        _require(type(signed["meta"]) is dict and set(signed["meta"]) == {expected},
                 "Only a flat repository with exact metadata pins is supported.")
    # All input metadata for this compact API is flat, without extensions.
    signatures = obj["signatures"]
    _require(type(signatures) is list and 1 <= len(signatures) <= 8,
             "Missing or excessive metadata signatures.")
    ids = set()
    for sig in signatures:
        _require(type(sig) is dict and set(sig) == {"keyid", "sig"},
                 "Unsupported signature fields.")
        _require(type(sig["keyid"]) is str and sig["keyid"] not in ids
                 and type(sig["sig"]) is str
                 and re.fullmatch(r"[0-9a-f]{128}", sig["sig"]) is not None,
                 "Duplicate or malformed Ed25519 signature.")
        ids.add(sig["keyid"])
    result = Metadata.from_bytes(raw)
    _require(type(result.signed) is {"root": Root, "targets": Targets,
             "snapshot": Snapshot, "timestamp": Timestamp}[role], "Wrong metadata type.")
    return result


def _verify(root, metadata, role):
    allowed = root.roles[role].keyids
    for keyid, signature in metadata.signatures.items():
        _require(keyid in allowed, "Signature is not authorized for this role.")
        root.keys[keyid].verify_signature(signature, metadata.signed_bytes)
    root.verify_delegate(role, metadata.signed_bytes, metadata.signatures)


def _root(raw, now):
    metadata = _parse(raw, "root")
    root = metadata.signed
    _require(root.version == 1, "Only supplied bootstrap root version 1 is supported; no root rotation.")
    _require(type(root.consistent_snapshot) is bool and root.expires > now,
             "The supplied root is expired or has invalid consistent_snapshot policy.")
    _require(set(root.roles) == {"root", *ROLES}, "Exactly four top-level roles are required.")
    keyids, public = set(), set()
    for role, spec in root.roles.items():
        _require(not spec.unrecognized_fields and type(spec.threshold) is int
                 and 1 <= spec.threshold <= len(spec.keyids) <= 8,
                 "Invalid role key policy.")
        _require(role != "root" or (spec.threshold == 2 and len(spec.keyids) == 3),
                 "Bootstrap root must use exactly three keys with threshold two.")
        _require(not keyids.intersection(spec.keyids), "Top-level roles must use distinct keys.")
        for keyid in spec.keyids:
            _require(type(keyid) is str and keyid in root.keys, "A role references a missing key.")
            key = root.keys[keyid].to_dict()
            _require(set(key) == {"keytype", "scheme", "keyval"}
                     and key["keytype"] == key["scheme"] == "ed25519"
                     and type(key["keyval"]) is dict and set(key["keyval"]) == {"public"},
                     "Only public Ed25519 root keys are supported.")
            value = key["keyval"]["public"]
            _require(type(value) is str and re.fullmatch(r"[0-9a-f]{64}", value) is not None
                     and value not in public, "Public key material must be distinct under every key ID.")
            public.add(value)
        keyids.update(spec.keyids)
    _require(set(root.keys) == keyids, "Unassigned root keys are not supported.")
    _verify(root, metadata, "root")
    return root, public


def _policy(policy, root, now):
    _require(type(policy) is Policy, "An explicit Policy is required.")
    for role in ROLES:
        spec = getattr(policy, role)
        _require(type(spec) is RolePolicy, "Every role needs an explicit version and expiry.")
        _version(spec.version)
        expires = _utc(spec.expires)
        _require(now < expires <= now + _LIFETIMES[role], "Role expiry exceeds its supported lifetime.")
    _require(policy.timestamp.expires <= policy.snapshot.expires <= policy.targets.expires <= root.expires,
             "Expiry order must be timestamp <= snapshot <= targets <= root.")


def _signers(value, root):
    _require(isinstance(value, Mapping) and set(value) == set(ROLES),
             "Supply targets, snapshot and timestamp signer objects, without root signers.")
    result = {}
    for role in ROLES:
        items = value[role]
        items = (items,) if isinstance(items, Signer) else items
        _require(type(items) in (tuple, list) and root.roles[role].threshold <= len(items) <= 8,
                 "Insufficient or excessive role signers.")
        ids = set()
        for signer in items:
            _require(isinstance(signer, Signer), "A securesystemslib Signer object is required.")
            key = signer.public_key
            _require(key.keyid in root.roles[role].keyids and key.keyid not in ids
                     and key.to_dict() == root.keys[key.keyid].to_dict(),
                     "Signer public identity does not match its root-authorized role.")
            ids.add(key.keyid)
        result[role] = tuple(items)
    return result


def _keyring(value, tuf_public):
    _require(isinstance(value, Mapping) and len(value) <= 32, "Provide a bounded public inner keyring.")
    keys = dict(value)
    for keyid, public in keys.items():
        _require(type(keyid) is str and re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", keyid) is not None
                 and type(public) is bytes and len(public) == 32
                 and public.hex() not in tuf_public,
                 "Inner keyring requires separate public Ed25519 keys.")
    return keys


def _previous(value, root_raw, root, policy):
    if value is None:
        _require(all(getattr(policy, r).version == 1 for r in ROLES),
                 "Initial role versions must be 1; advancement requires the previous signed repository.")
        return None
    _require(isinstance(value, Mapping) and set(value) == {"root.json", *(r + ".json" for r in ROLES)}
             and value["root.json"] == root_raw, "Previous repository must use the exact same bootstrap root.")
    old = {r: _parse(value[r + ".json"], r) for r in ROLES}
    for role in ROLES:
        _verify(root, old[role], role)
        _require(getattr(policy, role).version > old[role].signed.version,
                 "Every new role version must advance the provided signed repository.")
    _require(set(old["snapshot"].signed.meta) == {"targets.json"}, "Previous snapshot must be flat.")
    for parent, child in (("timestamp", "snapshot"), ("snapshot", "targets")):
        spec = (old[parent].signed.snapshot_meta if parent == "timestamp"
                else old[parent].signed.meta[child + ".json"])
        _version(spec.version)
        _require(not spec.unrecognized_fields and type(spec.length) is int and spec.length > 0
                 and spec.hashes is not None and set(spec.hashes) == {"sha256"}
                 and spec.version == old[child].signed.version, "Previous metadata pins are incomplete.")
        spec.verify_length_and_hashes(value[child + ".json"])
    for name, spec in old["targets"].signed.targets.items():
        _require(not spec.unrecognized_fields and type(spec.length) is int
                 and 0 < spec.length <= tuf_channel.target_limit(name)
                 and set(spec.hashes) == {"sha256"}, "Unsupported previous target descriptor.")
        core._hash_text(spec.hashes["sha256"])
    return {r: {"version": old[r].signed.version,
                "sha256": hashlib.sha256(value[r + ".json"]).hexdigest()} for r in ROLES}


def _release(notice):
    archive = notice["archive"]
    parts = core._url(archive["url"], initial=True)
    tag = parts.path.split("/")[-2]
    _require(tag.casefold() not in {"latest", "stable", "main", "master", "head"},
             "Archive notices must name a fixed versioned release asset.")
    return {"url": archive["url"], "size": archive["size"], "sha256": archive["sha256"]}


def _previous_launcher_notices(previous, notices):
    supplied = {} if notices is None else notices
    _require(isinstance(supplied, Mapping) and len(supplied) <= MAX_TARGETS,
             "Previous launcher notices must be bounded public byte mappings.")
    supplied = dict(supplied)
    descriptors = {} if previous is None else _parse(previous["targets.json"], "targets").signed.targets
    names = {name for name in descriptors if launcher_targets.is_launcher_target(name)}
    _require(len(names) <= MAX_TARGETS and set(supplied) == names,
             "Supply all and only the previous signed launcher notices.")
    parsed, total = [], 0
    for name in sorted(names):
        raw = supplied[name]
        _require(type(raw) is bytes and 0 < len(raw) <= tuf_channel.target_limit(name),
                 "Previous launcher notice bytes exceed their bound.")
        total += len(raw)
        _require(total <= MAX_TOTAL_BYTES, "Previous launcher notices exceed their aggregate bound.")
        descriptors[name].verify_length_and_hashes(raw)
        notice = self_update._notice(raw)
        launcher_targets.validate_notice(name, notice)
        parsed.append((name, notice))
    return parsed


def _contents(files, keys, now, previous_launcher_notices=()):
    parsed, artwork, archives = {}, {}, {}
    launcher_notices = list(previous_launcher_notices)
    for name, (held, _) in files.items():
        held.fp.seek(0)
        raw = held.fp.read(tuf_channel.target_limit(name) + 1)
        if name == "catalog-stable.json":
            value = catalog.parse_catalog(raw)
            value.require_current(now)
            parsed[name] = value
        elif name == "stellar-blade-stable.json":
            parsed[name] = core.load_signed_manifest(raw, keys)
        elif name == "stellar-blade-install-stable.json":
            parsed[name] = fresh_install.load_signed_manifest(raw, keys)
        elif launcher_targets.is_launcher_target(name):
            parsed[name] = self_update._notice(raw)
            launcher_notices.append((name, parsed[name]))
        else:
            # The client target boundary also recognizes JPEG/WebP, but its
            # current catalog decoder supports only this strict PNG subset.
            _require(name.endswith(".png"), "Only validated catalog PNG artwork is supported.")
            artwork[name] = None
        if name in parsed and name != "catalog-stable.json":
            archives[name] = _release(parsed[name])
    launcher_targets.validate_canonical_notices(launcher_notices)
    declarations = {}
    if "catalog-stable.json" in parsed:
        for game in parsed["catalog-stable.json"].games:
            if game.release_target is not None:
                tuf_channel.target_limit(game.release_target)
                if game.status == "available":
                    _require(game.release_target in parsed
                             and parsed[game.release_target]["version"] == game.version,
                             "An available card requires its matching validated release notice.")
            if game.artwork is not None:
                declarations[game.artwork.target] = game.artwork
    _require(set(artwork) == set(declarations), "Catalog declarations and staged artwork must match exactly.")
    for name, spec in declarations.items():
        held, _ = files[name]
        held.fp.seek(0)
        catalog.validate_artwork(held.fp.read(tuf_channel.target_limit(name) + 1), spec)
    return archives, parsed.get("catalog-stable.json")


def _retain_uncertain_receipt(held, output, guard):
    """Preserve this exact owned receipt after a post-rename identity error.

    The original exclusive DELETE-capable handle was created here. Its object
    identity remains known even if a path identity query has failed. Never
    reopen a possibly unrelated completion-marker path, replace or delete it.
    """
    destination = output / "staging-commit-uncertain.json"
    guard.directory(output)
    if core._exists(destination):
        raise StagingCommitUncertain(
            "Completion state is uncertain. Do not publish or infer success from a marker. Retain this stage for review.")
    class RenameInfo(ctypes.Structure):
        _fields_ = [("replace", wintypes.DWORD), ("root", wintypes.HANDLE),
                    ("length", wintypes.DWORD), ("name", wintypes.WCHAR * 1)]
    encoded = str(destination).encode("utf-16-le")
    buffer = ctypes.create_string_buffer(max(ctypes.sizeof(RenameInfo), RenameInfo.name.offset + len(encoded) + 2))
    info = RenameInfo.from_buffer(buffer)
    info.replace, info.root, info.length = 0, None, len(encoded)
    ctypes.memmove(ctypes.addressof(buffer) + RenameInfo.name.offset, encoded, len(encoded))
    if not core._kernel().SetFileInformationByHandle(held.handle, 3, buffer, len(buffer)):
        raise StagingCommitUncertain(
            "Completion state is uncertain. Do not publish or infer success from a marker. Retain this stage for review.")
    held.path = destination


def _signed(payload, role, signers, root):
    metadata = Metadata(payload)
    for signer in signers[role]:
        signature = metadata.sign(signer, append=True)
        _require(signature.keyid == signer.public_key.keyid, "Signer returned the wrong key identity.")
    raw = metadata.to_bytes()
    checked = _parse(raw, role)
    _verify(root, checked, role)
    return raw


def _pin(held, maximum):
    return held.fingerprint(maximum)


def _write(path, raw, stack):
    held = stack.enter_context(self_update.Held(path, create=True))
    held.fp.write(raw)
    held.fp.flush()
    os.fsync(held.fp.fileno())
    pin = _pin(held, len(raw))
    _require((pin["size"], pin["sha256"]) == (len(raw), hashlib.sha256(raw).hexdigest()),
             "An output failed exact length/SHA-256 readback.")
    return held, pin


def _layout(output, expected):
    found = set()
    for folder in (output, output / "metadata", output / "targets", output / "targets" / "assets"):
        if not folder.exists():
            continue
        for path in folder.iterdir():
            relative = path.relative_to(output).as_posix()
            if relative in {"metadata", "targets", "targets/assets"}:
                core._plain(path, directory=True)
            else:
                core._plain(path)
                found.add(relative)
    _require(found == set(expected), "Unexpected or missing staging output entries.")


def stage_repository(*, root_bytes: bytes, signers: Mapping, inner_keys: Mapping,
                     policy: Policy, data_targets: Mapping, output_dir,
                     previous: Mapping[str, bytes] | None = None,
                     previous_launcher_notices: Mapping[str, bytes] | None = None) -> dict:
    """Create a NEW offline stage and return its completion receipt.

    ``previous`` contains original public root/targets/snapshot/timestamp bytes
    under unversioned role names. It is a caller-selected baseline, never a
    network assertion of latest state. Expired previous non-root roles may be
    renewed. No root rotations or delegated metadata are supported. If previous
    Targets contains launcher baseline roles, previous_launcher_notices must
    provide their exact public bytes; their signed descriptor pins are verified.
    """
    from .launcher_package import CheckedGuard, PackageCloseError
    completion_written = False
    try:
        _require(importlib.metadata.version("tuf") == "7.0.1"
                 and importlib.metadata.version("securesystemslib") == "1.6.0",
                 "Use the reviewed tuf 7.0.1 / securesystemslib 1.6.0 environment.")
        now = datetime.now(timezone.utc)
        root, public = _root(root_bytes, now)
        _policy(policy, root, now)
        role_signers = _signers(signers, root)
        keys = _keyring(inner_keys, public)
        if previous is not None:
            _require(isinstance(previous, Mapping) and len(previous) == 4,
                     "Previous repository must contain exactly four public metadata roles.")
            previous = dict(previous)  # The verified metadata and notice proofs consume one snapshot.
        prior = _previous(previous, root_bytes, root, policy)
        prior_launcher = _previous_launcher_notices(previous, previous_launcher_notices)
        _require(isinstance(data_targets, Mapping) and 1 <= len(data_targets) <= MAX_TARGETS,
                 "Provide a bounded explicit target-to-local-file mapping.")
        sources = {}
        for name, path in data_targets.items():
            tuf_channel.target_limit(name)
            core._relative(name)
            sources[name] = self_update._path(path)
        output = self_update._path(output_dir)
        core._ntfs(output)
        with ExitStack() as stack:
            guard = stack.enter_context(CheckedGuard())
            guard.directory(output.parent)
            _require(not core._exists(output), "Output directory exists; partial and completed stages cannot be reused.")
            files, identities, total = {}, set(), 0
            for name, path in sorted(sources.items()):
                guard.directory(path.parent)
                held = stack.enter_context(self_update.Held(path))
                pin = _pin(held, tuf_channel.target_limit(name))
                _require(0 < pin["size"] and pin["file_id"] not in identities,
                         "Targets must be nonempty ordinary distinct files without aliases.")
                identities.add(pin["file_id"])
                total += pin["size"]
                _require(total <= MAX_TOTAL_BYTES, "The aggregate target byte budget is exceeded.")
                files[name] = held, pin
            archives, approved_catalog = _contents(files, keys, now, prior_launcher)
            target_data = {name: TargetFile(pin["size"], {"sha256": pin["sha256"]}, name)
                           for name, (_, pin) in files.items()}
            targets = _signed(Targets(version=policy.targets.version, expires=policy.targets.expires,
                                      targets=target_data), "targets", role_signers, root)
            snapshot = _signed(Snapshot(version=policy.snapshot.version, expires=policy.snapshot.expires,
                meta={"targets.json": MetaFile.from_data(policy.targets.version, targets, ["sha256"])}),
                "snapshot", role_signers, root)
            timestamp = _signed(Timestamp(version=policy.timestamp.version, expires=policy.timestamp.expires,
                snapshot_meta=MetaFile.from_data(policy.snapshot.version, snapshot, ["sha256"])),
                "timestamp", role_signers, root)
            needed = total + 2 * len(root_bytes) + len(targets) + len(snapshot) + len(timestamp) + 2 * 1024**2
            _require(shutil.disk_usage("C:/").free >= RESERVE
                     and shutil.disk_usage(output.parent).free >= RESERVE + needed,
                     "Keep at least 80 GiB free on C: and the staging drive after this job.")
            output.mkdir(mode=0o700)  # Exclusive claim: never exist_ok or overwrite.
            guard.directory(output)
            for directory in (output / "metadata", output / "targets"):
                directory.mkdir(mode=0o700)
                guard.directory(directory)
            if any(name.startswith("assets/") for name in files):
                (output / "targets" / "assets").mkdir(mode=0o700)
                guard.directory(output / "targets" / "assets")
            outputs = {}
            metadata = {"1.root.json": root_bytes, "root.json": root_bytes, "timestamp.json": timestamp}
            for role, raw in (("targets", targets), ("snapshot", snapshot)):
                prefix = str(getattr(policy, role).version) + "." if root.consistent_snapshot else ""
                metadata[prefix + role + ".json"] = raw
            for name, raw in metadata.items():
                relative = "metadata/" + name
                outputs[relative] = _write(output / relative, raw, stack)
            for name, (source, pin) in files.items():
                parts = name.rsplit("/", 1)
                filename = (pin["sha256"] + "." if root.consistent_snapshot else "") + parts[-1]
                relative = "targets/" + (parts[0] + "/" if len(parts) == 2 else "") + filename
                held = stack.enter_context(self_update.Held(output / relative, create=True))
                source.fp.seek(0)
                core._stream_copy(source.fp, held.fp, pin["size"], pin["sha256"])
                actual = _pin(held, pin["size"])
                _require((actual["size"], actual["sha256"]) == (pin["size"], pin["sha256"]),
                         "A copied target failed exact length/SHA-256 readback.")
                outputs[relative] = held, actual
            # Every source and output stays held against writes/deletes. Rehash
            # the exact names again before admitting a completion record.
            for name, (source, pin) in files.items():
                _require(_pin(source, tuf_channel.target_limit(name)) == pin, "A source changed while staging.")
            for relative, (held, pin) in outputs.items():
                _require(_pin(held, pin["size"]) == pin, "A staged output changed during verification.")
            _layout(output, outputs)
            _require(root.expires > datetime.now(timezone.utc), "Root expired during staging.")
            _policy(policy, root, datetime.now(timezone.utc))
            if approved_catalog is not None:
                approved_catalog.require_current(datetime.now(timezone.utc))
            receipt = {"schema": 1, "status": "offline-stage-complete", "published": False,
                "consistent_snapshot": root.consistent_snapshot,
                "root_sha256": hashlib.sha256(root_bytes).hexdigest(),
                "versions": {"root": 1, **{r: getattr(policy, r).version for r in ROLES}},
                "expires": {r: catalog.format_time(getattr(policy, r).expires) for r in ROLES},
                "previous": prior, "archives": archives,
                "archive_verification": "signed descriptions only; release assets not read or fetched",
                "files": {name: {k: pin[k] for k in ("size", "sha256")}
                          for name, (_, pin) in sorted(outputs.items())}}
            # A crash or write failure keeps a partial receipt under a different
            # name. Only a fully fsynced, read-back receipt is renamed LAST.
            raw = core._canonical(receipt)
            with self_update.Held(output / "staging-receipt.partial", create=True, move=True) as held:
                held.fp.write(raw)
                held.fp.flush()
                os.fsync(held.fp.fileno())
                pin = _pin(held, 2 * 1024**2)
                _require((pin["size"], pin["sha256"]) == (len(raw), hashlib.sha256(raw).hexdigest()),
                         "Completion receipt failed readback.")
                try:
                    # Recheck data freshness at the commit boundary as well as
                    # before writing the record. No signer/backend call follows.
                    commit_now = datetime.now(timezone.utc)
                    _require(root.expires > commit_now, "Root expired before staging commit.")
                    _policy(policy, root, commit_now)
                    if approved_catalog is not None:
                        approved_catalog.require_current(commit_now)
                    held.move_to(output / RECEIPT, guard)
                    completion_written = True
                except Exception:  # noqa: BLE001 - every failed commit must retain evidence
                    if held.path == output / RECEIPT:
                        try:
                            _retain_uncertain_receipt(held, output, guard)
                        except Exception:  # noqa: BLE001 - keep uncertain native errors explicit and secret-free
                            raise StagingCommitUncertain(
                                "Completion state is uncertain. Do not publish or infer success from a marker. Retain this stage for review.") from None
                    raise StagingError(
                        "Staging commit failed. Receipt evidence was retained; no candidate is admitted. Use a new directory.") from None
            return receipt
    except PackageCloseError:
        # Preserve exact failed ownership; receipt existence never admits a close failure.
        raise
    except StagingError:
        if completion_written:
            raise StagingCommitUncertain(
                "Completion state is uncertain. Do not publish or infer success from a marker. Retain this stage for review.") from None
        raise
    except Exception:  # noqa: BLE001 - injected signer backends must not disclose exception text
        if completion_written:
            raise StagingCommitUncertain(
                "Completion state is uncertain. Do not publish or infer success from a marker. Retain this stage for review.") from None
        # Signer exceptions can contain device/service secrets: callers receive
        # a fixed message, without exposing the backend's exception chain.
        raise StagingError("Offline staging refused. Partial output, if any, was retained; use a new directory.") from None
