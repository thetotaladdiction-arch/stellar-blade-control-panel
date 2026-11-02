"""Authenticate an explicitly supplied published metadata snapshot and ledger.

This offline operator API does not fetch Git or establish its current remote tip.
The caller must bind the supplied bytes to the independently verified commit and
later publish with an expected-parent compare-and-swap. A commit string by itself
is not a remote observation. No signer/private key is accepted here.
"""
from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from dataclasses import dataclass

from updater import catalog, channel, core, tuf_channel

from . import staging

BRANCH = "aeroneus-updates"
ROLES = ("root", "targets", "snapshot", "timestamp")
MAX_LEDGER_BYTES = 16 * 1024


@dataclass(frozen=True)
class PublishedState:
    """Immutable bytes, revalidated at every signing operation; not a capability."""

    commit: str
    root_sha256: str
    ledger_bytes: bytes
    metadata: tuple[tuple[str, bytes], ...]

    def files(self):
        return dict(self.metadata)


def pin(raw):
    return {"size": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


def verify(*, commit, trusted_root_sha256, metadata, ledger_bytes, now):
    """Verify role signatures, parent pins and the exact public-ledger schema.

    An expired previous timestamp may be renewed while root/snapshot/targets
    remain valid. This supplies no rollback protection beyond the caller's
    current, serialized commit/ledger binding; offline arbitrary history is not
    automatically the latest published repository.
    """
    staging._require(type(commit) is str and re.fullmatch(r"[0-9a-f]{40}", commit) is not None,
                     "An explicit canonical GitHub commit is required.")
    core._hash_text(trusted_root_sha256)
    now = staging._utc(now)
    staging._require(isinstance(metadata, Mapping) and set(metadata) == {r + ".json" for r in ROLES},
                     "Supply exactly root, targets, snapshot and timestamp bytes.")
    copied = {}
    for role in ROLES:
        raw = metadata[role + ".json"]
        staging._require(type(raw) is bytes and 0 < len(raw) <= staging.METADATA_LIMITS[role],
                         "Metadata must be bounded immutable bytes.")
        copied[role + ".json"] = raw
    staging._require(pin(copied["root.json"])["sha256"] == trusted_root_sha256,
                     "The supplied root differs from the explicitly approved public root.")
    # Initial supported publisher policy is the independently reviewed root-v1
    # ceremony. Rotation must add its own reviewed state transition, not bypass it.
    root, _ = staging._root(copied["root.json"], now)
    checked = {r: staging._parse(copied[r + ".json"], r) for r in ROLES}
    for role in ROLES:
        staging._verify(root, checked[role], role)
        expiry = checked[role].signed.expires
        staging._require(expiry <= root.expires,
                         "Published metadata extends beyond its root.")
        if role != "timestamp":
            staging._require(expiry > now, "Published root, targets or snapshot has expired.")
    staging._require(checked["timestamp"].signed.expires <= checked["snapshot"].signed.expires
                     <= checked["targets"].signed.expires <= root.expires,
                     "Published expiry order is inconsistent.")
    for parent, child in (("timestamp", "snapshot"), ("snapshot", "targets")):
        spec = (checked[parent].signed.snapshot_meta if parent == "timestamp"
                else checked[parent].signed.meta[child + ".json"])
        staging._version(spec.version)
        staging._require(not spec.unrecognized_fields and type(spec.length) is int
                         and 0 < spec.length <= staging.METADATA_LIMITS[child]
                         and type(spec.hashes) is dict and set(spec.hashes) == {"sha256"}
                         and spec.version == checked[child].signed.version,
                         "Published child metadata pins are incomplete.")
        core._hash_text(spec.hashes["sha256"])
        spec.verify_length_and_hashes(copied[child + ".json"])
    for name, spec in checked["targets"].signed.targets.items():
        staging._require(not spec.unrecognized_fields and type(spec.length) is int
                         and 0 < spec.length <= tuf_channel.target_limit(name)
                         and type(spec.hashes) is dict and set(spec.hashes) == {"sha256"},
                         "Unsupported published target descriptor.")
        core._hash_text(spec.hashes["sha256"])
    staging._require(type(ledger_bytes) is bytes, "Supply immutable public ledger bytes.")
    ledger = catalog.bounded_json(ledger_bytes, MAX_LEDGER_BYTES)
    core._shape(ledger, {"schema", "repository", "branch", "sequence", "roles"}, "Public ledger")
    core._integer(ledger["schema"], 1, 1, "Public ledger schema")
    staging._require(ledger["repository"] == channel.REPOSITORY and ledger["branch"] == BRANCH,
                     "Public ledger repository/branch differs from the compiled channel.")
    core._integer(ledger["sequence"], 1, 2**31 - 1, "Public ledger sequence")
    core._shape(ledger["roles"], set(ROLES), "Public ledger roles")
    for role in ROLES:
        row = core._shape(ledger["roles"][role], {"version", "size", "sha256"}, "Public role pin")
        staging._version(row["version"])
        core._integer(row["size"], 1, staging.METADATA_LIMITS[role], "Public metadata size")
        core._hash_text(row["sha256"])
        staging._require(row == {"version": checked[role].signed.version,
                                 **pin(copied[role + ".json"])},
                         "Published ledger does not match the exact signed metadata bytes.")
    return PublishedState(commit, trusted_root_sha256, ledger_bytes,
                          tuple((name, copied[name]) for name in sorted(copied)))


def revalidate(state, now):
    staging._require(type(state) is PublishedState, "An explicit published state is required.")
    staging._require(type(state.metadata) is tuple and len(state.metadata) == len(ROLES),
                     "Published state contains invalid metadata records.")
    pairs = state.metadata
    staging._require(all(type(row) is tuple and len(row) == 2 and type(row[0]) is str for row in pairs)
                     and len({row[0] for row in pairs}) == len(ROLES),
                     "Published state contains duplicate or malformed names.")
    return verify(commit=state.commit, trusted_root_sha256=state.root_sha256,
                  metadata=dict(pairs), ledger_bytes=state.ledger_bytes, now=now)
