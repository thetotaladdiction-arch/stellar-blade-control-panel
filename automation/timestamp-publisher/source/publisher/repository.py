"""Offline assembly of a complete, retained consistent-snapshot repository.

No network, Git ref writes, signer/key loader or claim about the current remote
tip. Explicit bytes must first be bound to the operator's serialized parent.
Receipts and return values are diagnostic, never publication capabilities.
"""
from __future__ import annotations

import hashlib
import os
import re
from collections.abc import Mapping
from contextlib import ExitStack
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from updater import channel, core, launcher_targets, self_update, tuf_channel

from . import public_state, renewal, staging

MAX_FILES = 4096
MAX_BYTES = 256 * 1024**2
_VERSIONED = re.compile(r"([1-9][0-9]{0,9})\.(targets|snapshot)\.json")
_DIGEST = re.compile(r"([0-9a-f]{64})\.(.+)")
INITIAL_HISTORY = frozenset({"metadata/1.targets.json", "metadata/1.snapshot.json"})


@dataclass(frozen=True)
class Assembly:
    expected_parent: str
    trusted_root_sha256: str
    files: tuple[tuple[str, bytes], ...]


def _copy(value, label):
    staging._require(isinstance(value, Mapping) and len(value) <= MAX_FILES,
                     label + " must be a bounded explicit file mapping.")
    result, total = {}, 0
    for name, raw in value.items():
        staging._require(type(name) is str and type(raw) is bytes,
                         label + " contains a non-string path or mutable/non-byte data.")
        core._relative(name)
        staging._require("\\" not in name and len(name) <= 240,
                         "Repository names must be bounded canonical slash paths.")
        total += len(raw)
        staging._require(total <= MAX_BYTES, "Repository byte ceiling exceeded.")
        result[name] = raw
    staging._require(len({n.casefold() for n in result}) == len(result),
                     "Repository paths collide on Windows.")
    return result


def _data_path(name, raw):
    tuf_channel.target_limit(name)
    core._relative(name)
    parts = name.rsplit("/", 1)
    return ("targets/" + (parts[0] + "/" if len(parts) == 2 else "")
            + hashlib.sha256(raw).hexdigest() + "." + parts[-1])


def _child(spec, raw):
    staging._version(spec.version)
    staging._require(not spec.unrecognized_fields and type(spec.length) is int
                     and spec.length > 0 and type(spec.hashes) is dict
                     and set(spec.hashes) == {"sha256"}, "Incomplete child metadata pin.")
    core._hash_text(spec.hashes["sha256"])
    spec.verify_length_and_hashes(raw)


def verify_tree(*, files, expected_parent, trusted_root_sha256, now, previous=False):
    """Verify every retained blob and historical metadata link, not just HEAD.

    The explicit parent is a caller binding, not proof of the actual branch tip.
    This operator currently supports the reviewed root-v1 ceremony and requires
    consistent snapshots. Inner content admission remains the staging API's job.
    ``previous=True`` authenticates historical non-root deadlines for replacement;
    signatures, root freshness, ledger pins and all retained links still apply.
    """
    files = _copy(files, "Repository")
    now = staging._utc(now)
    for name in ("metadata/root.json", "metadata/1.root.json", "metadata/timestamp.json",
                 "public-ledger.json"):
        staging._require(name in files, "Repository is missing a required public file.")
    root_raw = files["metadata/root.json"]
    root, _ = staging._root(root_raw, now)
    staging._require(root.consistent_snapshot is True
                     and files["metadata/1.root.json"] == root_raw,
                     "Retained-tree publication requires consistent snapshots and the exact numbered root.")
    timestamp = staging._parse(files["metadata/timestamp.json"], "timestamp")
    staging._version(timestamp.signed.snapshot_meta.version)
    snapshot_name = "metadata/" + str(timestamp.signed.snapshot_meta.version) + ".snapshot.json"
    staging._require(snapshot_name in files, "The current versioned snapshot is missing.")
    snapshot = staging._parse(files[snapshot_name], "snapshot")
    target_version = snapshot.signed.meta["targets.json"].version
    staging._version(target_version)
    targets_name = "metadata/" + str(target_version) + ".targets.json"
    staging._require(targets_name in files, "The current versioned targets metadata is missing.")
    metadata = {"root.json": root_raw, "timestamp.json": files["metadata/timestamp.json"],
                "snapshot.json": files[snapshot_name], "targets.json": files[targets_name]}
    state = public_state.verify(commit=expected_parent, trusted_root_sha256=trusted_root_sha256,
                                metadata=metadata, ledger_bytes=files["public-ledger.json"], now=now,
                                previous=previous)
    referenced_data = set()
    actual_data = set()
    launcher_history = {}
    current_versions = {"targets": target_version, "snapshot": snapshot.signed.version}
    retained_versions = {"targets": set(), "snapshot": set()}
    for name, raw in files.items():
        if name in {"metadata/root.json", "metadata/1.root.json", "metadata/timestamp.json",
                    "public-ledger.json"}:
            continue
        if name.startswith("metadata/"):
            match = _VERSIONED.fullmatch(name[len("metadata/"):])
            staging._require(match is not None, "Unsupported retained metadata filename.")
            version, role = int(match[1]), match[2]
            staging._version(version)
            staging._require(version <= current_versions[role], "Retained metadata is newer than the published ledger.")
            retained_versions[role].add(version)
            staging._require(len(raw) <= staging.METADATA_LIMITS[role], "Historical metadata exceeds its limit.")
            md = staging._parse(raw, role)
            staging._verify(root, md, role)
            staging._require(md.signed.version == version and md.signed.expires <= root.expires,
                             "Historical metadata version/expiry does not match its name or root.")
            if role == "snapshot":
                child = md.signed.meta["targets.json"]
                child_name = "metadata/" + str(child.version) + ".targets.json"
                staging._require(child_name in files, "A historical snapshot lost its targets metadata.")
                _child(child, files[child_name])
            else:
                for logical, spec in md.signed.targets.items():
                    maximum = tuf_channel.target_limit(logical)
                    staging._require(type(spec.length) is int and 0 < spec.length <= maximum
                                     and not spec.unrecognized_fields and type(spec.hashes) is dict
                                     and set(spec.hashes) == {"sha256"}, "Invalid historical target descriptor.")
                    core._hash_text(spec.hashes["sha256"])
                    parts = logical.rsplit("/", 1)
                    path = ("targets/" + (parts[0] + "/" if len(parts) == 2 else "")
                            + spec.hashes["sha256"] + "." + parts[-1])
                    staging._require(path in files, "A retained targets version lost a referenced data blob.")
                    spec.verify_length_and_hashes(files[path])
                    referenced_data.add(path)
                    if launcher_targets.is_launcher_target(logical):
                        identity = (logical, spec.hashes["sha256"])
                        if identity not in launcher_history:
                            staging._require(len(launcher_history) < launcher_targets.MAX_NOTICE_BINDINGS,
                                             "Distinct launcher notice history exceeds its explicit bound.")
                            notice = self_update._notice(files[path])
                            launcher_targets.validate_notice(logical, notice)
                            launcher_history[identity] = logical, notice
        elif name.startswith("targets/"):
            parts = name[len("targets/"):].rsplit("/", 1)
            match = _DIGEST.fullmatch(parts[-1])
            staging._require(match is not None, "Target data has no canonical SHA-256 prefix.")
            logical = (parts[0] + "/" if len(parts) == 2 else "") + match[2]
            maximum = tuf_channel.target_limit(logical)
            staging._require(0 < len(raw) <= maximum and hashlib.sha256(raw).hexdigest() == match[1],
                             "Retained target data differs from its path digest or byte limit.")
            actual_data.add(name)
        else:
            raise staging.StagingError("Foreign files are not permitted in the data-only repository tree.")
    staging._require(actual_data == referenced_data, "Repository contains unreferenced target data.")
    staging._require(all(len(retained_versions[r]) == current_versions[r] for r in retained_versions),
                     "A historical metadata version is missing from the retained chain.")
    launcher_targets.validate_canonical_notices(launcher_history.values())
    return state


def _assemble_initial_two(*, previous_tree, metadata, target_data, expected_parent,
                          trusted_root_sha256, now, ledger_bytes, initial_history):
    """First publication of already-issued role2; no claim of earlier publication.

    Retain signed targets1/snapshot1 as issuance history, not a prior Git tree.
    The Git caller must prove its actual canonical empty seed. No historical
    timestamp is used, backdated or made current; ledger sequence starts at1.
    """
    staging._require(not _copy(previous_tree, "Previous repository"),
                     "Initial role2 publication requires an empty previous tree.")
    staging._require(isinstance(metadata, Mapping)
                     and set(metadata) == {r + ".json" for r in public_state.ROLES},
                     "Supply exactly four signed metadata roles.")
    metadata = _copy(metadata, "Candidate metadata")
    data = _copy(target_data, "Candidate target data")
    history = _copy(initial_history, "Initial signed issuance history")
    staging._require(set(history) == INITIAL_HISTORY,
                     "Initial role2 requires exactly signed targets1 and snapshot1.")
    now = staging._utc(now)
    root, _ = staging._root(metadata["root.json"], now)
    checked = {r: staging._parse(metadata[r + ".json"], r) for r in public_state.ROLES}
    staging._require(root.consistent_snapshot is True and root.version == 1
                     and all(checked[r].signed.version == 2 for r in staging.ROLES),
                     "This explicit initial route supports only root1 and role2.")
    staging._policy(staging.Policy(*(staging.RolePolicy(checked[r].signed.version, checked[r].signed.expires)
                                    for r in staging.ROLES)), root, now)
    ledger = {"schema": 1, "repository": channel.REPOSITORY,
              "branch": public_state.BRANCH, "sequence": 1,
              "roles": {r: {"version": checked[r].signed.version, **public_state.pin(metadata[r + ".json"])}
                        for r in public_state.ROLES}}
    computed_ledger = core._canonical(ledger)
    staging._require(ledger_bytes is None or (type(ledger_bytes) is bytes and ledger_bytes == computed_ledger),
                     "Initial ledger must describe the exact current bytes and first publication.")
    tree = dict(history)
    tree.update({"metadata/root.json": metadata["root.json"], "metadata/1.root.json": metadata["root.json"],
                 "metadata/2.targets.json": metadata["targets.json"],
                 "metadata/2.snapshot.json": metadata["snapshot.json"],
                 "metadata/timestamp.json": metadata["timestamp.json"], "public-ledger.json": computed_ledger})
    for logical, raw in data.items():
        staging._require(logical in checked["targets"].signed.targets,
                         "Initial target data must be referenced by current signed targets.")
        checked["targets"].signed.targets[logical].verify_length_and_hashes(raw)
        tree[_data_path(logical, raw)] = raw
    # Original verifier enforces root trust, every role/history signature,
    # contiguous versions, child byte pins, exact referenced blobs, and notice
    # history. Current role deadlines were checked above, including timestamp.
    verify_tree(files=tree, expected_parent=expected_parent, trusted_root_sha256=trusted_root_sha256, now=now)
    return Assembly(expected_parent, trusted_root_sha256, tuple(sorted(tree.items())))


def assemble(*, previous_tree, metadata, target_data, expected_parent,
             trusted_root_sha256, now, ledger_bytes=None, initial_history=None):
    """Reconcile one explicit parent and preserve all prior versioned files.

    Empty previous_tree is an explicit first-publication request against a
    separately observed real parent commit; all role versions must then be1.
    A changed release must advance targets and snapshot together; timestamp-only
    renewal preserves both exact signed byte strings. A role version can never
    be reused for different bytes. No root rotation is implied or supported.
    """
    if initial_history is not None:
        return _assemble_initial_two(previous_tree=previous_tree, metadata=metadata, target_data=target_data,
            expected_parent=expected_parent, trusted_root_sha256=trusted_root_sha256, now=now,
            ledger_bytes=ledger_bytes, initial_history=initial_history)
    now = staging._utc(now)
    previous = _copy(previous_tree, "Previous repository")
    staging._require(isinstance(metadata, Mapping)
                     and set(metadata) == {r + ".json" for r in public_state.ROLES},
                     "Supply exactly four signed metadata roles.")
    metadata = _copy(metadata, "Candidate metadata")
    data = _copy(target_data, "Candidate target data")
    root, _ = staging._root(metadata["root.json"], now)
    staging._require(root.consistent_snapshot is True, "Consistent snapshots are required.")
    checked = {r: staging._parse(metadata[r + ".json"], r) for r in public_state.ROLES}
    staging._policy(staging.Policy(*(staging.RolePolicy(checked[r].signed.version, checked[r].signed.expires)
                                    for r in staging.ROLES)), root, now)
    prior = (verify_tree(files=previous, expected_parent=expected_parent,
                         trusted_root_sha256=trusted_root_sha256, now=now, previous=True) if previous else None)
    sequence = 1
    if prior is None:
        staging._require(all(checked[r].signed.version == 1 for r in public_state.ROLES),
                         "Initial publication must start every role at version1.")
    else:
        old = prior.files()
        staging._require(metadata["root.json"] == old["root.json"], "Root rotation needs a separate reviewed ceremony.")
        unchanged = [metadata[r + ".json"] == old[r + ".json"] for r in ("targets", "snapshot")]
        staging._require(all(unchanged) or not any(unchanged),
                         "Targets and snapshot must advance together or both remain byte-identical.")
        for role in ("targets", "snapshot", "timestamp"):
            old_version = staging._parse(old[role + ".json"], role).signed.version
            if role != "timestamp" and all(unchanged):
                staging._require(checked[role].signed.version == old_version, "Unchanged role version differs.")
            else:
                staging._require(checked[role].signed.version == old_version + 1,
                                 "Changed role versions must advance exactly once without rollback/reuse/gaps.")
        sequence = core._json(prior.ledger_bytes, public_state.MAX_LEDGER_BYTES, "Previous ledger")["sequence"] + 1
    ledger = {"schema": 1, "repository": channel.REPOSITORY,
              "branch": public_state.BRANCH, "sequence": sequence,
              "roles": {r: {"version": checked[r].signed.version, **public_state.pin(metadata[r + ".json"])}
                        for r in public_state.ROLES}}
    computed_ledger = core._canonical(ledger)
    staging._require(ledger_bytes is None or (type(ledger_bytes) is bytes and ledger_bytes == computed_ledger),
                     "Supplied candidate ledger differs from the reconciled exact bytes.")
    public_state.verify(commit=expected_parent, trusted_root_sha256=trusted_root_sha256,
                        metadata=metadata, ledger_bytes=computed_ledger, now=now)
    tree = dict(previous)
    additions = {"metadata/root.json": metadata["root.json"], "metadata/1.root.json": metadata["root.json"],
                 "metadata/timestamp.json": metadata["timestamp.json"], "public-ledger.json": computed_ledger}
    for role in ("targets", "snapshot"):
        additions["metadata/" + str(checked[role].signed.version) + "." + role + ".json"] = metadata[role + ".json"]
    for logical, raw in data.items():
        staging._require(logical in checked["targets"].signed.targets, "Candidate data is not a current signed target.")
        checked["targets"].signed.targets[logical].verify_length_and_hashes(raw)
        additions[_data_path(logical, raw)] = raw
    for name, raw in additions.items():
        staging._require(name in {"metadata/timestamp.json", "public-ledger.json"}
                         or name not in tree or tree[name] == raw, "An immutable repository filename would be overwritten.")
        tree[name] = raw
    verify_tree(files=tree, expected_parent=expected_parent, trusted_root_sha256=trusted_root_sha256, now=now)
    return Assembly(expected_parent, trusted_root_sha256, tuple(sorted(tree.items())))


def stage(*, output_dir, clock=lambda: datetime.now(timezone.utc).replace(microsecond=0), **inputs):
    """Write/read back a new complete tree; never update an existing path/ref.

    The returned directory still needs current-tip reconciliation, independent
    admission and expected-parent publication. Partial outputs remain on error.
    """
    staging._require(os.name == "nt", "Use the reviewed Windows handle guards.")
    inputs = dict(inputs)
    for name in ("previous_tree", "metadata", "target_data"):
        inputs[name] = _copy(inputs[name], name)
    if inputs.get("initial_history") is not None:
        inputs["initial_history"] = _copy(inputs["initial_history"], "Initial signed issuance history")
    result = assemble(now=renewal._observed(clock()), **inputs)
    files = dict(result.files)
    output = self_update._path(output_dir)
    core._space(Path("C:/"), 80 * 1024**3)
    expected_dirs = {"repository"}
    for name in files:
        parent = Path("repository") / Path(name).parent
        while str(parent) != ".":
            expected_dirs.add(parent.as_posix())
            parent = parent.parent
    with ExitStack() as stack:
        guard = stack.enter_context(renewal.CheckedGuard())
        guard.directory(output.parent)
        staging._require(not core._exists(output), "Choose a new output directory.")
        core._space(output.parent, 80 * 1024**3 + 3 * sum(map(len, files.values())) + 2 * 1024**2)
        output.mkdir(mode=0o700)
        guard.directory(output)
        for directory in sorted(expected_dirs, key=lambda p: (p.count("/"), p)):
            path = output / directory
            path.mkdir(mode=0o700)
            guard.directory(path)
        held = {name: staging._write(output / "repository" / name, raw, stack)[0]
                for name, raw in files.items()}
        for name, item in held.items():
            staging._require(item.fingerprint(len(files[name]))["sha256"] == hashlib.sha256(files[name]).hexdigest(),
                             "Written repository bytes changed.")
        assemble(now=renewal._observed(clock()), **inputs)
        receipt = {"schema": 1, "status": "complete-local-tree-not-published", "published": False,
                   "expected_parent": result.expected_parent, "trusted_root_sha256": result.trusted_root_sha256,
                   "files": [{"path": n, **public_state.pin(raw)} for n, raw in result.files],
                   "requires": ["independently bind actual current Git parent", "recheck deadlines and exact files",
                                "independent admission", "expected-parent publication and HTTPS readback"]}
        raw_receipt = core._canonical(receipt)
        receipt_held = staging._write(output / "operator-receipt.json", raw_receipt, stack)[0]
        _layout(output, expected_dirs, {"repository/" + n for n in files} | {"operator-receipt.json"})
        staging._require(receipt_held.fingerprint(len(raw_receipt))["sha256"] == hashlib.sha256(raw_receipt).hexdigest(),
                         "Operator receipt changed.")
    # No completion return until all writes, readback and guard closes succeed.
    with ExitStack() as stack:
        guard = stack.enter_context(renewal.CheckedGuard())
        guard.directory(output)
        for directory in sorted(expected_dirs, key=lambda p: (p.count("/"), p)):
            guard.directory(output / directory)
        for name, raw in {**{"repository/" + n: b for n, b in files.items()}, "operator-receipt.json": raw_receipt}.items():
            item = stack.enter_context(self_update.Held(output / name))
            spec = item.fingerprint(len(raw))
            staging._require((spec["size"], spec["sha256"]) == (len(raw), hashlib.sha256(raw).hexdigest()),
                             "Closed repository readback differs.")
        _layout(output, expected_dirs, {"repository/" + n for n in files} | {"operator-receipt.json"})
        assemble(now=renewal._observed(clock()), **inputs)
    assemble(now=renewal._observed(clock()), **inputs)
    return output


def _layout(output, directories, files):
    found_files, found_dirs = set(), set()
    pending = [output]
    while pending:
        folder = pending.pop()
        with os.scandir(folder) as entries:
            for entry in entries:
                path = Path(entry.path)
                name = path.relative_to(output).as_posix()
                if entry.is_dir(follow_symlinks=False):
                    staging._require(name in directories and name not in found_dirs, "Unexpected repository directory.")
                    core._plain(path, directory=True)
                    found_dirs.add(name)
                    pending.append(path)
                else:
                    staging._require(name in files and name not in found_files, "Unexpected repository file.")
                    core._plain(path)
                    found_files.add(name)
    staging._require(found_files == files and found_dirs == directories, "Repository layout differs from the exact planned tree.")
