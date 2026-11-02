"""Timestamp-only renewal: authenticate a pinned state, sign with that role only.

No network, key loading, public write, snapshot/targets signing or rotation.
The source public state must come from the operator's verified current commit.
"""
from __future__ import annotations

import hashlib
import os
from contextlib import ExitStack
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from securesystemslib.signer import Signer
from tuf.api.metadata import MetaFile, Timestamp
from updater import core, self_update

from . import public_state, staging


class DirectoryCloseError(staging.StagingError):
    """No completion; retain the guard's failed owned handles for recovery."""

    def __init__(self, guard):
        super().__init__("An owned publisher directory handle failed to close; no candidate is admitted.")
        self.guard = guard


class CheckedGuard(self_update.Guard):
    """Check native closes without altering the shared historical guard."""

    def __exit__(self, *args):
        failed = False
        for key, handle in reversed(tuple(self.handles.items())):
            try:
                closed = bool(core._kernel().CloseHandle(handle))
            except Exception:  # noqa: BLE001 - finish all other owned closes before refusing
                closed = False
            if closed:
                del self.handles[key]
            else:
                failed = True
        if failed:
            raise DirectoryCloseError(self)
        return False


def _observed(value):
    # Signed expiry inputs remain strict whole-second values. Observed clock
    # samples may have normal fractional seconds. Floor only the observation;
    # whole-second deadlines still refuse at their exact boundary.
    staging._require(isinstance(value, datetime) and value.tzinfo is not None
                     and value.utcoffset() is not None, "An aware observed UTC clock is required.")
    return staging._utc(value.astimezone(timezone.utc).replace(microsecond=0))


def _deadline(value):
    result = staging._utc(value)
    staging._require(result.microsecond == 0,
                     "Signed UTC deadlines must retain whole-second precision after timezone conversion.")
    return result


@dataclass(frozen=True)
class Renewal:
    expected_parent: str
    timestamp_bytes: bytes
    ledger_bytes: bytes
    unchanged_pins: tuple[tuple[str, int, str], ...]


@dataclass(frozen=True)
class Candidate:
    directory: Path
    expected_parent: str
    files: tuple[tuple[str, int, str], ...]
    verified_at: datetime


def create(state, *, signers, expires, now):
    """Return a checked candidate; it is not publication or a commit authority.

    The caller must serialize renewal, revalidate its actual remote tip and
    atomically publish the complete candidate tree against expected_parent.
    All roots, snapshots, targets and their versioned files must be retained.
    """
    now, expires = _deadline(now), _deadline(expires)
    state = public_state.revalidate(state, now)
    files = state.files()
    root, _ = staging._root(files["root.json"], now)
    old = {role: staging._parse(files[role + ".json"], role)
           for role in ("targets", "snapshot", "timestamp")}
    staging._require(now < expires <= min(now + timedelta(days=1), root.expires,
                     old["targets"].signed.expires, old["snapshot"].signed.expires),
                     "Timestamp expiry exceeds its role or child/root deadline.")
    items = (signers,) if isinstance(signers, Signer) else signers
    spec = root.roles["timestamp"]
    staging._require(type(items) in (tuple, list) and spec.threshold <= len(items) <= 8,
                     "Supply sufficient bounded timestamp-only Signer objects.")
    identities = set()
    for signer in items:
        staging._require(isinstance(signer, Signer), "A timestamp Signer object is required.")
        key = signer.public_key
        staging._require(key.keyid in spec.keyids and key.keyid not in identities
                         and key.to_dict() == root.keys[key.keyid].to_dict(),
                         "Signer is not a distinct root-authorized timestamp key.")
        identities.add(key.keyid)
    version = old["timestamp"].signed.version + 1
    staging._version(version)
    snapshot = old["snapshot"].signed
    snapshot_bytes = files["snapshot.json"]
    payload = Timestamp(version=version, expires=expires,
                        snapshot_meta=MetaFile(version=snapshot.version,
                            length=len(snapshot_bytes),
                            hashes={"sha256": hashlib.sha256(snapshot_bytes).hexdigest()}))
    raw = staging._signed(payload, "timestamp", {"timestamp": tuple(items)}, root)
    actual_expiry = staging._parse(raw, "timestamp").signed.expires
    staging._require(actual_expiry == expires and actual_expiry > now,
                     "The actual signed timestamp deadline changed or has already expired.")
    # Refresh the clock/policy in the staging operator immediately before commit;
    # a slow signer cannot make this pure candidate a completed publication.
    ledger = core._json(state.ledger_bytes, public_state.MAX_LEDGER_BYTES, "Public ledger")
    ledger["sequence"] += 1
    core._integer(ledger["sequence"], 1, 2**31 - 1, "Public ledger sequence")
    ledger["roles"]["timestamp"] = {"version": version, **public_state.pin(raw)}
    ledger_bytes = core._canonical(ledger)
    files["timestamp.json"] = raw
    public_state.verify(commit=state.commit, trusted_root_sha256=state.root_sha256,
                        metadata=files, ledger_bytes=ledger_bytes, now=now)
    retained = tuple((role + ".json", len(files[role + ".json"]),
                      hashlib.sha256(files[role + ".json"]).hexdigest())
                     for role in ("root", "targets", "snapshot"))
    return Renewal(state.commit, raw, ledger_bytes, retained)


def stage(state, *, signers, expires, output_dir, expected_parent,
          clock=lambda: datetime.now(timezone.utc)):
    """Write an exclusive checked metadata candidate; never a complete repository.

    This tree deliberately has no target-data files or historical root/versioned
    files. An operator must merge it into the retained exact prior repository,
    revalidate all bytes/deadlines and publish against the actual current parent.
    The JSON receipt is diagnostic, never sufficient publication authority.
    All failures retain their new partial output and propagate as failures.
    """
    staging._require(os.name == "nt", "Candidate staging requires the reviewed Windows file guards.")
    now = _observed(clock())
    state = public_state.revalidate(state, now)
    staging._require(expected_parent == state.commit,
                     "Candidate parent differs from the explicitly verified published state.")
    result = create(state, signers=signers, expires=expires, now=now)
    metadata = state.files()
    metadata["timestamp.json"] = result.timestamp_bytes
    files = {**metadata, "public-ledger.json": result.ledger_bytes}
    output = self_update._path(output_dir)
    core._space(Path("C:/"), 80 * 1024**3)
    with ExitStack() as stack:
        guard = stack.enter_context(CheckedGuard())
        guard.directory(output.parent)
        staging._require(not core._exists(output), "Candidate directory already exists; choose a new one.")
        core._space(output.parent, 80 * 1024**3 + 3 * sum(map(len, files.values())) + 2 * 1024**2)
        output.mkdir(mode=0o700)
        guard.directory(output)
        held = {}
        for name, raw in sorted(files.items()):
            held[name], _ = staging._write(output / name, raw, stack)
        verified_at = _observed(clock())
        public_state.verify(commit=state.commit, trusted_root_sha256=state.root_sha256,
                            metadata=metadata, ledger_bytes=result.ledger_bytes, now=verified_at)
        staging._require(_deadline(expires) > verified_at
                         and staging._parse(result.timestamp_bytes, "timestamp").signed.expires > verified_at,
                         "Timestamp candidate expired while signing or writing.")
        pins = tuple((name, len(raw), hashlib.sha256(raw).hexdigest())
                     for name, raw in sorted(files.items()))
        receipt = {
            "schema": 1, "status": "timestamp-candidate-needs-operator-assembly",
            "published": False, "complete_repository": False,
            "expected_parent": expected_parent, "trusted_root_sha256": state.root_sha256,
            "verified_at": verified_at.isoformat(),
            "files": [{"path": name, "size": size, "sha256": digest}
                      for name, size, digest in pins],
            "requirements": ["retain prior targets/versioned metadata/root chain",
                             "revalidate current remote parent and local bytes",
                             "serialize expected-parent publication",
                             "revalidate expiry immediately before commit"],
        }
        raw_receipt = core._canonical(receipt)
        held["renewal-receipt.json"], _ = staging._write(output / "renewal-receipt.json", raw_receipt, stack)
        expected = {**files, "renewal-receipt.json": raw_receipt}
        names = set()
        with os.scandir(output) as entries:
            for entry in entries:
                staging._require(len(names) < len(expected), "Unexpected candidate output entry.")
                core._plain(Path(entry.path))
                names.add(entry.name)
        staging._require(names == set(expected), "Missing or unexpected candidate output entries.")
        for name, raw in expected.items():
            spec = held[name].fingerprint(len(raw))
            staging._require((spec["size"], spec["sha256"]) == (len(raw), hashlib.sha256(raw).hexdigest()),
                             "Candidate output changed during final readback.")
    # Closing all guards/files is part of success; exceptions above never return
    # this object. Persistent JSON is explicitly not an authorization token.
    verified_at = _observed(clock())
    public_state.verify(commit=state.commit, trusted_root_sha256=state.root_sha256,
                        metadata=metadata, ledger_bytes=result.ledger_bytes, now=verified_at)
    staging._require(_deadline(expires) > verified_at
                     and staging._parse(result.timestamp_bytes, "timestamp").signed.expires > verified_at,
                     "Timestamp candidate expired before staging completed.")
    return Candidate(output, expected_parent, pins, verified_at)
