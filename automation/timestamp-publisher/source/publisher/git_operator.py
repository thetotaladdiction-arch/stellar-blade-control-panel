"""Data-only local SHA-1 bare Git operator. No transport, signing or key loader.

The four entry points always bind actual Git objects/ref bytes, not receipts.
First version deliberately refuses packed/alternate/promisor stores and foreign
configuration. See GIT-OPERATOR.md for the exact supported local workflow.
"""
from __future__ import annotations

import argparse
import ctypes
import hashlib
import io
import json
import os
import re
import stat
import subprocess
import threading
import time
from collections.abc import Mapping
from contextlib import ExitStack
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from updater import core, launcher_targets, self_update, tuf_channel

from . import public_state, renewal, repository, staging

REF = 'refs/heads/aeroneus-updates'
BRANCH = 'aeroneus-updates'
MAX_FILES = 4096
MAX_BYTES = 256 * 1024**2
MAX_TREE_BYTES = 2 * 1024**2
MAX_OBJECTS = 65536
COMMAND_SECONDS = 15
OPERATION_SECONDS = 180
RESERVE = 80 * 1024**3
IDENTITY = 'Aeroneus Local Operator <local-operator@invalid> 946684800 +0000'
SEED_MESSAGE = b'Aeroneus local metadata empty seed v1\n'
COMMIT_MESSAGE = b'Aeroneus local metadata candidate v1\n'
OID = re.compile(r'[0-9a-f]{40}')
HASH = re.compile(r'[0-9a-f]{64}')
_VERSION = re.compile(r'([1-9][0-9]{0,9})\.(targets|snapshot)\.json')
_RETAINED_SESSIONS = set()


class OperatorError(staging.StagingError):
    """Local operation refused; partial files and Git objects are retained."""


class OperatorBusy(OperatorError):
    """Another operator owns this ordinary local repository's physical lease."""


class ActivationUncertain(OperatorError):
    """CAS may have happened. Inspect actual ref; no completion is admitted."""


class GitCleanupUncertain(OperatorError):
    """The actual owner and physical lease remain held until owned cleanup."""

    def __init__(self, owner):
        super().__init__('Owned local Git cleanup is uncertain; keep this process alive and retain the owner. No completion is admitted.')
        self.owner = owner


class ProgramCloseError(OperatorError):
    """A failed owned program close retains its actual handle for review."""

    def __init__(self, handle, owner=None):
        super().__init__('An owned trusted-program handle failed to close; no completion is admitted.')
        self.handle, self.owner = handle, owner


def _require(value, message):
    if not value:
        raise OperatorError(message)


def _oid(value):
    _require(type(value) is str and OID.fullmatch(value), 'A canonical SHA-1 object ID is required.')
    return value


def _hash(value):
    _require(type(value) is str and HASH.fullmatch(value), 'A canonical trusted SHA-256 is required.')
    return value


def _object_id(kind, raw):
    return hashlib.sha1(kind.encode('ascii') + b' ' + str(len(raw)).encode('ascii') + b'\0' + raw).hexdigest()


def _commit_bytes(tree, parent=None):
    rows = ['tree ' + _oid(tree)]
    if parent is not None:
        rows.append('parent ' + _oid(parent))
    rows += ['author ' + IDENTITY, 'committer ' + IDENTITY]
    return ('\n'.join(rows) + '\n\n').encode('ascii') + (SEED_MESSAGE if parent is None else COMMIT_MESSAGE)


def _tree_id(files):
    nested = {}
    for name, raw in files.items():
        node = nested
        parts = name.split('/')
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = _object_id('blob', raw)

    def tree(node):
        rows = []
        for name, value in sorted(node.items(), key=lambda item: item[0] + ('/' if isinstance(item[1], dict) else '')):
            mode, oid = ('40000', tree(value)) if isinstance(value, dict) else ('100644', value)
            rows.append((mode + ' ' + name).encode('ascii') + b'\0' + bytes.fromhex(oid))
        return _object_id('tree', b''.join(rows))
    return tree(nested)


EMPTY_TREE = _object_id('tree', b'')
SEED = _object_id('commit', _commit_bytes(EMPTY_TREE))


def _path(value):
    path = self_update._path(value)
    _require(re.fullmatch(r'[A-Za-z]:', path.drive) is not None, 'Only an explicit ordinary local volume path is supported.')
    return path


def _limit(name):
    _require(type(name) is str and name.isascii() and len(name) <= 240 and '\\' not in name,
             'Repository paths must be bounded canonical ASCII slash paths.')
    core._relative(name)
    if name == 'public-ledger.json':
        return public_state.MAX_LEDGER_BYTES
    if name in {'metadata/root.json', 'metadata/1.root.json'}:
        return staging.METADATA_LIMITS['root']
    if name == 'metadata/timestamp.json':
        return staging.METADATA_LIMITS['timestamp']
    if name.startswith('metadata/'):
        match = _VERSION.fullmatch(name[9:])
        _require(match is not None, 'Foreign metadata path refused.')
        staging._version(int(match[1]))
        return staging.METADATA_LIMITS[match[2]]
    _require(name.startswith('targets/'), 'Only public metadata, ledger and target data are supported.')
    logical = name[8:]
    prefix, _, base = logical.rpartition('/')
    digest, dot, suffix = base.partition('.')
    _require(dot and HASH.fullmatch(digest), 'Target data needs a canonical SHA-256 prefix.')
    return tuf_channel.target_limit((prefix + '/' if prefix else '') + suffix)


def _read_held(held, maximum):
    pin = held.fingerprint(maximum)
    held.fp.seek(0)
    raw = held.fp.read(maximum + 1)
    _require(len(raw) == pin['size'] and hashlib.sha256(raw).hexdigest() == pin['sha256'],
             'Held public bytes changed while read.')
    return raw


def _paths(directory, limit):
    # Path.iterdir can eagerly collect an untrusted directory on this Python.
    # Stream and stop at the explicit ceiling before collecting names/handles.
    with os.scandir(directory) as entries:
        for count, entry in enumerate(entries):
            _require(count < limit, 'Filesystem directory entry ceiling exceeded.')
            yield Path(entry.path)


@dataclass(frozen=True)
class Snapshot:
    commit: str
    tree: str
    parent: str | None
    files: tuple[tuple[str, bytes], ...]


@dataclass(frozen=True)
class Prepared:
    expected_parent: str
    commit: str
    tree: str
    directory: Path


@dataclass(frozen=True)
class Activated:
    previous: str
    commit: str
    tree: str
    local_only: bool = True


class _PinnedExecutable:
    """Trusted program only: Git's installed builtin hard links share this lock.

    All public data still uses the unchanged one-link Held. This retained file
    object permits reads only, including through its other existing hard links.
    """

    def __init__(self, path):
        import msvcrt
        self.path = path
        kernel = self_update._kernel()
        handle = kernel.CreateFileW(str(path), 0x80000000, 1, None, 3, 0x08200000, None)
        _require(handle not in (None, ctypes.c_void_p(-1).value), 'Cannot hold trusted Git executable.')
        fd = None
        self.fp = None
        try:
            info = core._FileInfo()
            _require(kernel.GetFileInformationByHandle(handle, ctypes.byref(info))
                     and not info.attributes & (0x400 | 0x10) and info.links >= 1,
                     'Trusted Git executable is not an ordinary non-reparse file.')
            self_update._canonical_handle(handle, path)
            self_update._streams(path)
            fd = msvcrt.open_osfhandle(int(handle), os.O_RDONLY | os.O_BINARY)
            self.fp = os.fdopen(fd, 'rb', buffering=0)
            self.handle = handle
            self.assert_name()
        except BaseException as error:
            if self.fp is not None:
                try:
                    self.fp.close()
                except Exception as exc:  # Failed owned close must retain handle/owner, not disappear.
                    raise ProgramCloseError(handle, self) from exc
            elif fd is None:
                try:
                    closed = bool(kernel.CloseHandle(handle))
                except Exception:  # noqa: BLE001 - preserve the raw owned handle on native close failure
                    closed = False
                if not closed:
                    raise ProgramCloseError(handle) from error
            else:
                try:
                    os.close(fd)
                except OSError as exc:
                    raise ProgramCloseError(handle) from exc
            raise

    def __enter__(self):
        return self

    def __exit__(self, *args):
        try:
            self.fp.close()
        except Exception as exc:  # Preserve failed owned close under post-CAS uncertainty as well.
            raise ProgramCloseError(self.handle, self) from exc

    def assert_name(self):
        actual, opened = os.lstat(self.path), os.fstat(self.fp.fileno())
        _require(stat.S_ISREG(actual.st_mode) and not actual.st_file_attributes & 0x400
                 and (actual.st_dev, actual.st_ino) == (opened.st_dev, opened.st_ino),
                 'Trusted Git executable identity changed.')
        self_update._canonical_handle(self.handle, self.path)

    def fingerprint(self, maximum):
        self.assert_name()
        before = os.fstat(self.fp.fileno())
        _require(before.st_size <= maximum, 'Trusted executable byte ceiling exceeded.')
        self.fp.seek(0)
        raw = self.fp.read(maximum + 1)
        after = os.fstat(self.fp.fileno())
        _require((before.st_ino, before.st_size, before.st_mtime_ns) == (after.st_ino, after.st_size, after.st_mtime_ns)
                 and len(raw) == before.st_size, 'Trusted Git executable changed while hashed.')
        return {'sha256': hashlib.sha256(raw).hexdigest()}


class _GitChild:
    """Retain the actual child, attempted workers and pipes across any failure."""

    def __init__(self):
        self.process = None
        self.workers = []
        self.outputs = [bytearray(), bytearray()]
        self.overflow = threading.Event()
        self.failures = []
        self.exited = self.joined = self.settled = False

    def error(self, exc):
        if len(self.failures) < 32:
            self.failures.append(type(exc).__name__)

    def cleanup(self, *, abort):
        """Five seconds total per attempt; never close a pipe under a worker."""
        self.exited = self.joined = self.settled = False
        process = self.process
        if process is None:
            self.joined = self.settled = True
            return True
        deadline = time.monotonic() + 5
        try:
            if abort:
                try:
                    if process.poll() is None:
                        process.kill()  # Only this retained local Git child's process handle.
                except BaseException as exc:  # noqa: BLE001 - retain even failed owned termination
                    self.error(exc)
            process.wait(timeout=max(0, deadline - time.monotonic()))
            self.exited = process.poll() is not None
            if not self.exited:
                return False
            self.joined = True
            for worker in self.workers:
                # An attempted start can raise AFTER actually starting. ident
                # survives thread exit; joining a never-started worker raises.
                if worker.ident is not None:
                    try:
                        worker.join(max(0, deadline - time.monotonic()))
                        self.joined &= not worker.is_alive()
                    except BaseException as exc:  # noqa: BLE001 - an unconfirmed join retains the owner
                        self.error(exc)
                        self.joined = False
            if not self.joined:
                return False
            # In particular, stdin.close cannot contend with a blocked feeder:
            # the owned child has exited and every actual worker was joined.
            for pipe in (process.stdin, process.stdout, process.stderr):
                if pipe is not None and not pipe.closed:
                    pipe.close()
            self.settled = all(p is None or p.closed for p in (process.stdin, process.stdout, process.stderr))
        except BaseException as exc:  # noqa: BLE001 - never infer cleanup from its failed acknowledgment
            self.error(exc)
        return self.settled


class _Session:
    """One exclusive operator; only closed builtin plumbing argv are emitted."""

    _limit = staticmethod(_limit)

    def __init__(self, *, git_exe, git_sha256, repo, work_dir, clock, new=False):
        self.exe, self.repo, self.work = map(_path, (git_exe, repo, work_dir))
        self.exe_hash = _hash(git_sha256)
        self.clock, self.new = clock, new
        self.stack = ExitStack()
        self.guard = None
        self.config = self.head = None
        self.started = time.monotonic()
        self.commands = 0
        self.objects_read = []
        self.cas_started = False
        self.child = None

    def __enter__(self):
        try:
            _require(os.name == 'nt', 'The reviewed Windows held-file guards are required.')
            _require(self.repo != self.work and self.repo not in self.work.parents and self.work not in self.repo.parents,
                     'The new work directory must be separate from the bare repository.')
            self.guard = self.stack.enter_context(renewal.CheckedGuard())
            self.guard.directory(self.repo.parent)
            self.guard.directory(self.work.parent)
            core._ntfs(self.work.parent)
            core._space(Path('C:/'), RESERVE + 3 * MAX_BYTES + 4 * 1024**2)
            core._space(self.repo.parent, RESERVE + 3 * MAX_BYTES + 4 * 1024**2)
            core._space(self.work.parent, RESERVE + 3 * MAX_BYTES + 4 * 1024**2)
            _require(not core._exists(self.work), 'Use a new work directory; partial evidence is retained.')
            self.work.mkdir(mode=0o700)
            self.guard.directory(self.work)
            lease_path = self.repo.with_name(self.repo.name + '.aeroneus-operator.lease')
            lease_raw = b'Aeroneus local bare operator v1\n' + hashlib.sha256(str(self.repo).casefold().encode()).hexdigest().encode() + b'\n'
            if not core._exists(lease_path):
                try:
                    with self_update.Held(lease_path, create=True) as held:
                        held.fp.write(lease_raw)
                        held.fp.flush()
                        os.fsync(held.fp.fileno())
                except core.UpdateError as exc:
                    raise OperatorBusy('Local operator lease is busy or could not be created.') from exc
            try:
                self.lease = self.stack.enter_context(self_update.Held(lease_path, exclusive=True))
            except core.UpdateError as exc:
                raise OperatorBusy('Another local operator owns the repository lease.') from exc
            _require(_read_held(self.lease, 256) == lease_raw, 'Foreign or partial operator lease refused.')
            self.guard.directory(self.exe.parent)
            self.binary = self.stack.enter_context(_PinnedExecutable(self.exe))
            _require(self.binary.fingerprint(32 * 1024**2)['sha256'] == self.exe_hash, 'Trusted Git executable hash differs.')
            for name in ('hooks-empty', 'home-empty', 'temp'):
                (self.work / name).mkdir(mode=0o700)
                self.guard.directory(self.work / name)
            self.hooks = self.work / 'hooks-empty'
            empty_path = self.work / 'empty-config'
            with self_update.Held(empty_path, create=True) as held:
                held.fp.flush()
                os.fsync(held.fp.fileno())
            self.empty_config = self.stack.enter_context(self_update.Held(empty_path))
            self.log = self.stack.enter_context(self_update.Held(self.work / 'git-commands.jsonl', create=True))
            self.env = self._environment(empty_path)
            if self.new:
                _require(not core._exists(self.repo), 'Initialization requires a new owned bare directory.')
            else:
                self._gate_repo()
            return self
        except BaseException:
            self.stack.close()
            raise

    def __exit__(self, *args):
        if self.child is not None and not self.child.settled:
            _RETAINED_SESSIONS.add(self)
            raise GitCleanupUncertain(self)
        return self.stack.__exit__(*args)

    def retry_cleanup(self):
        """Cleanup only, never acknowledgment/retry of a Git or ref operation."""
        _require(self in _RETAINED_SESSIONS, 'This session has no retained uncertain Git cleanup.')
        if not self.child.cleanup(abort=True):
            raise GitCleanupUncertain(self)
        self.stack.close()
        self.child = None
        _RETAINED_SESSIONS.discard(self)

    def _environment(self, empty):
        # No inherited GIT_*, credential, SSH, pager, loader or user-config vars.
        system = Path(os.environ['SystemRoot'])
        return {
            'SystemRoot': str(system), 'WINDIR': str(system),
            'PATH': str(self.exe.parent) + os.pathsep + str(system / 'System32'),
            'TEMP': str(self.work / 'temp'), 'TMP': str(self.work / 'temp'),
            'HOME': str(self.work / 'home-empty'), 'USERPROFILE': str(self.work / 'home-empty'),
            'XDG_CONFIG_HOME': str(self.work / 'home-empty'),
            'GIT_CONFIG_NOSYSTEM': '1', 'GIT_CONFIG_SYSTEM': str(empty), 'GIT_CONFIG_GLOBAL': str(empty),
            'GIT_CONFIG_COUNT': '0', 'GIT_ALLOW_PROTOCOL': '', 'GIT_PROTOCOL_FROM_USER': '0',
            'GIT_TERMINAL_PROMPT': '0', 'GCM_INTERACTIVE': 'never', 'GCM_GUI_PROMPT': '0',
            'GIT_NO_LAZY_FETCH': '1', 'GIT_NO_REPLACE_OBJECTS': '1', 'GIT_OPTIONAL_LOCKS': '0',
            'GIT_ATTR_NOSYSTEM': '1', 'GIT_LITERAL_PATHSPECS': '1', 'LC_ALL': 'C',
            'GIT_AUTHOR_NAME': 'Aeroneus Local Operator', 'GIT_COMMITTER_NAME': 'Aeroneus Local Operator',
            'GIT_AUTHOR_EMAIL': 'local-operator@invalid', 'GIT_COMMITTER_EMAIL': 'local-operator@invalid',
            'GIT_AUTHOR_DATE': '2000-01-01T00:00:00Z', 'GIT_COMMITTER_DATE': '2000-01-01T00:00:00Z',
        }

    def _hold(self, path, maximum):
        self.guard.directory(path.parent)
        held = self.stack.enter_context(self_update.Held(path))
        return held, _read_held(held, maximum)

    def _empty_dir(self, path):
        self.guard.directory(path)
        with os.scandir(path) as entries:
            _require(next(entries, None) is None, 'A directory required to be empty contains foreign entries.')

    def _gate_repo(self):
        self.guard.directory(self.repo)
        allowed = {'HEAD', 'config', 'objects', 'refs', 'description', 'hooks', 'info'}
        _require({p.name for p in _paths(self.repo, 8)} <= allowed, 'Foreign bare-repository layout refused.')
        self.config, raw = self._hold(self.repo / 'config', 4096)
        try:
            lines = raw.decode('ascii').splitlines()
        except UnicodeError as exc:
            raise OperatorError('Repository config must be the supported literal ASCII core profile.') from exc
        _require(lines and lines[0] == '[core]', 'Only the literal bare core config section is supported.')
        values = {}
        for line in lines[1:]:
            match = re.fullmatch(r'\s*([a-z]+)\s*=\s*([a-z0-9]+)\s*', line)
            _require(match is not None and match[1] not in values, 'Foreign/duplicate repository configuration refused.')
            values[match[1]] = match[2]
        _require(values.get('repositoryformatversion') == '0' and values.get('bare') == 'true'
                 and values.get('filemode') in {'true', 'false'}
                 and all(k in {'repositoryformatversion', 'bare', 'filemode', 'ignorecase', 'symlinks'} for k in values)
                 and values.get('ignorecase', 'true') == 'true' and values.get('symlinks', 'false') == 'false',
                 'Only the supported local SHA-1 bare core profile is admitted.')
        self.config_raw = raw
        self.head, raw = self._hold(self.repo / 'HEAD', 128)
        _require(raw == ('ref: ' + REF + '\n').encode(), 'HEAD must name the one fixed branch.')
        for name in ('hooks', 'info'):
            if core._exists(self.repo / name):
                self._empty_dir(self.repo / name)
        if core._exists(self.repo / 'description'):
            self._hold(self.repo / 'description', 4096)
        self.guard.directory(self.repo / 'refs')
        _require({p.name for p in _paths(self.repo / 'refs', 3)} <= {'heads', 'tags'}, 'Arbitrary refs are not supported.')
        self.guard.directory(self.repo / 'refs/heads')
        _require({p.name for p in _paths(self.repo / 'refs/heads', 2)} <= {BRANCH}, 'Only the fixed branch may exist.')
        if core._exists(self.repo / 'refs/tags'):
            self._empty_dir(self.repo / 'refs/tags')
        objects = self.repo / 'objects'
        self.guard.directory(objects)
        count = 0
        for path in _paths(objects, 258):
            if path.name in {'pack', 'info'}:
                self._empty_dir(path)
                continue
            _require(re.fullmatch('[0-9a-f]{2}', path.name), 'Unsupported object-store entry.')
            self.guard.directory(path)
            for item in _paths(path, MAX_OBJECTS + 1):
                count += 1
                _require(count <= MAX_OBJECTS and re.fullmatch('[0-9a-f]{38}', item.name), 'Object-store ceiling or foreign object path.')
                core._plain(item)

    def _command_gate(self):
        _require(time.monotonic() - self.started < OPERATION_SECONDS, 'Local operation time bound exceeded.')
        self.lease.assert_name()
        self.binary.assert_name()
        self.empty_config.assert_name()
        self._empty_dir(self.hooks)
        if self.config is not None:
            _require(_read_held(self.config, 4096) == self.config_raw, 'Held repository configuration changed.')
            _require(_read_held(self.head, 128) == ('ref: ' + REF + '\n').encode(), 'Held HEAD changed.')
            for name in ('objects/info', 'objects/pack'):
                self._empty_dir(self.repo / name)

    def git(self, args, data=b'', maximum=2 * 1024**2, before_start=None):
        _require(args and args[0] in {'init', 'rev-parse', 'cat-file', 'hash-object', 'mktree', 'commit-tree', 'update-ref'},
                 'Only controlled local builtin plumbing is supported.')
        _require(type(data) is bytes and len(data) <= MAX_BYTES + 2 * 1024**2, 'Git input exceeds its explicit bound.')
        self._command_gate()
        prefix = [str(self.exe), '--no-pager', '--no-replace-objects', '--no-lazy-fetch', '--no-optional-locks']
        options = {'core.hooksPath': str(self.hooks), 'core.attributesFile': str(self.work / 'empty-config'),
                   'core.fsmonitor': 'false', 'core.untrackedCache': 'false', 'core.commitGraph': 'false',
                   'commit.gpgsign': 'false', 'tag.gpgsign': 'false', 'gc.auto': '0', 'maintenance.auto': 'false',
                   'protocol.allow': 'never', 'credential.helper': '', 'safe.bareRepository': 'explicit',
                   'safe.directory': str(self.repo), 'i18n.commitEncoding': 'UTF-8'}
        for key, value in options.items():
            prefix.extend(['-c', key + '=' + value])
        if args[0] != 'init':
            prefix += ['--git-dir=' + str(self.repo)]
        if before_start is not None:
            before_start()
        _require(self.child is None, 'Prior owned Git cleanup has not completed.')
        owner = self.child = _GitChild()
        timed_out = False
        failure = None
        try:
            # Ownership protection includes every instruction after Popen,
            # including pipe-worker construction and each start acknowledgment.
            owner.process = subprocess.Popen(prefix + list(args), cwd=self.work, env=self.env, stdin=subprocess.PIPE,
                                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, close_fds=True,
                                            creationflags=subprocess.CREATE_NO_WINDOW)
            process = owner.process

            def drain(pipe, index, limit):
                try:
                    while chunk := pipe.read(65536):
                        if len(owner.outputs[index]) + len(chunk) > limit:
                            owner.overflow.set()
                            process.kill()  # Only this retained local Git child.
                            break
                        owner.outputs[index].extend(chunk)
                except BaseException as exc:  # noqa: BLE001 - keep worker errors with the retained owner
                    owner.error(exc)
                finally:
                    try:
                        pipe.close()
                    except BaseException as exc:  # noqa: BLE001 - pipe close failure must be retained
                        owner.error(exc)

            def feed():
                try:
                    process.stdin.write(data)
                except BaseException as exc:  # noqa: BLE001 - every feeder failure requires owned cleanup
                    owner.error(exc)
                finally:
                    try:
                        process.stdin.close()
                    except BaseException as exc:  # noqa: BLE001 - retain feeder close failure
                        owner.error(exc)

            for target, worker_args in ((drain, (process.stdout, 0, maximum)),
                                        (drain, (process.stderr, 1, 32768)), (feed, ())):
                worker = threading.Thread(target=target, args=worker_args, daemon=False)
                owner.workers.append(worker)
                worker.start()
            process.wait(timeout=COMMAND_SECONDS)
        except BaseException as exc:  # noqa: BLE001 - no failure may escape owned child cleanup
            timed_out = isinstance(exc, subprocess.TimeoutExpired)
            failure = exc
        finally:
            settled = owner.cleanup(abort=failure is not None)
            if not settled:
                _RETAINED_SESSIONS.add(self)
            self.commands += 1
            try:
                process = owner.process
                record = {'argv': prefix + list(args), 'pid': process.pid if process is not None else None,
                          'exit_code': process.returncode if process is not None else None,
                          'timed_out': timed_out, 'overflow': owner.overflow.is_set(),
                          'stdout_bytes': len(owner.outputs[0]), 'stdout_sha256': hashlib.sha256(owner.outputs[0]).hexdigest(),
                          'stderr': bytes(owner.outputs[1]).decode('utf-8', 'replace')[:2000], 'pipe_errors': owner.failures,
                          'owned_exit': owner.exited, 'pipe_threads_done': owner.joined, 'cleanup_confirmed': settled}
                self.log.fp.write(core._canonical(record) + b'\n')
                self.log.fp.flush()
                os.fsync(self.log.fp.fileno())
            except BaseException as exc:  # noqa: BLE001 - a failed receipt cannot release an uncertain child
                if failure is None:
                    failure = exc
            if not settled:
                raise GitCleanupUncertain(self) from failure
            self.child = None
        if failure is not None:
            raise failure
        _require(not timed_out and not owner.overflow.is_set() and not owner.failures and process.returncode == 0,
                 'Local Git plumbing failed; retain the owned command receipt.')
        return bytes(owner.outputs[0])

    def tip(self):
        path = self.repo / REF
        self.guard.directory(path.parent)
        with self_update.Held(path) as held:
            raw = _read_held(held, 64)
        _require(re.fullmatch(rb'[0-9a-f]{40}\n', raw), 'Fixed branch must be an ordinary direct SHA-1 ref.')
        observed = self.git(['rev-parse', '--verify', REF], maximum=128).decode('ascii').strip()
        _require(observed == raw[:-1].decode('ascii'), 'Branch changed while read.')
        return _oid(observed)

    def objects(self, ids, kind, maximum):
        ids = list(dict.fromkeys(map(_oid, ids)))
        if not ids:
            return {}
        _require(len(ids) <= MAX_OBJECTS, 'Git object batch ceiling exceeded.')
        raw = self.git(['cat-file', '--batch'], ''.join(i + '\n' for i in ids).encode(),
                       maximum=maximum + 128 * len(ids))
        result, offset = {}, 0
        for wanted in ids:
            end = raw.find(b'\n', offset)
            _require(end >= 0, 'Truncated object header.')
            header = raw[offset:end].split(b' ')
            _require(len(header) == 3 and header[0] == wanted.encode() and header[1] == kind.encode()
                     and re.fullmatch(rb'0|[1-9][0-9]{0,9}', header[2]), 'Missing/wrong Git object type or header.')
            size = int(header[2])
            _require(size <= maximum and end + 1 + size < len(raw), 'Git object size exceeds its bound.')
            body = raw[end + 1:end + 1 + size]
            _require(raw[end + 1 + size:end + 2 + size] == b'\n' and _object_id(kind, body) == wanted,
                     'Git object SHA-1 or framing differs from its actual bytes.')
            result[wanted], offset = body, end + 2 + size
        _require(offset == len(raw), 'Trailing object-batch data refused.')
        self.objects_read.append((kind, len(ids)))
        return result

    def snapshot(self, commit):
        commit = _oid(commit)
        body = self.objects([commit], 'commit', 65536)[commit]
        header = body.split(b'\n\n', 1)[0].splitlines()
        _require(header and re.fullmatch(rb'tree [0-9a-f]{40}', header[0]), 'Noncanonical Git commit header.')
        tree = header[0][5:].decode()
        parents = [line[7:].decode('ascii') for line in header if line.startswith(b'parent ')]
        _require(len(parents) <= 1, 'Merge commits are not supported.')
        parent = _oid(parents[0]) if parents else None
        _require(body == _commit_bytes(tree, parent), 'Only canonical local metadata commits are supported.')
        if parent is None:
            _require(commit == SEED and tree == EMPTY_TREE, 'Only the canonical empty seed may have no parent.')
        entries, pending, tree_bytes, directories = {}, [(tree, '')], 0, set()
        seen_trees = 0
        while pending:
            level, pending = pending, []
            objects = self.objects([oid for oid, _ in level], 'tree', MAX_TREE_BYTES)
            for oid, prefix in level:
                seen_trees += 1
                _require(seen_trees <= MAX_FILES + 1 and prefix.count('/') <= 16, 'Tree/depth ceiling exceeded.')
                data, offset, last = objects[oid], 0, None
                tree_bytes += len(data)
                _require(tree_bytes <= MAX_TREE_BYTES, 'Aggregate tree bytes exceed their bound.')
                while offset < len(data):
                    split, nul = data.find(b' ', offset), data.find(b'\0', offset)
                    _require(offset < split < nul and nul + 21 <= len(data), 'Malformed Git tree framing.')
                    mode, name = data[offset:split], data[split + 1:nul]
                    _require(mode in {b'40000', b'100644'} and name and b'/' not in name,
                             'Only directories and ordinary100644 data blobs are admitted.')
                    try:
                        name = name.decode('ascii')
                    except UnicodeError as exc:
                        raise OperatorError('Noncanonical repository path encoding.') from exc
                    core._relative(name)
                    child = data[nul + 1:nul + 21].hex()
                    key = (name + ('/' if mode == b'40000' else '')).encode()
                    _require(last is None or last < key, 'Unsorted/duplicate Git tree entry.')
                    last, offset = key, nul + 21
                    path = prefix + name
                    if mode == b'40000':
                        _require(len(path) <= 240, 'Directory path too long.')
                        _require(path not in directories, 'Duplicate directory path.')
                        directories.add(path)
                        pending.append((child, path + '/'))
                    else:
                        self._limit(path)
                        _require(path not in entries and len(entries) < MAX_FILES, 'Duplicate path/file ceiling exceeded.')
                        entries[path] = child
        _require(len({n.casefold() for n in entries}) == len(entries), 'Windows path aliases collide.')
        expected_dirs = set()
        for name in entries:
            parts = name.split('/')
            expected_dirs.update('/'.join(parts[:i]) for i in range(1, len(parts)))
        _require(directories == expected_dirs, 'Empty/foreign Git directories are not part of the exact data tree.')
        ids = list(dict.fromkeys(entries.values()))
        sizes = {}
        if ids:
            raw = self.git(['cat-file', '--batch-check'], ''.join(i + '\n' for i in ids).encode(), maximum=128 * len(ids))
            rows = raw.splitlines()
            _require(len(rows) == len(ids), 'Truncated object-size batch.')
            for wanted, row in zip(ids, rows):
                fields = row.split(b' ')
                _require(len(fields) == 3 and fields[0] == wanted.encode() and fields[1] == b'blob'
                         and re.fullmatch(rb'0|[1-9][0-9]{0,9}', fields[2]), 'Missing/nonblob data object.')
                sizes[wanted] = int(fields[2])
        # Enforce all path/mode/count/per-file/aggregate limits BEFORE blob bodies.
        total = sum(sizes[oid] for oid in entries.values())
        _require(total <= MAX_BYTES and all(0 < sizes[oid] <= self._limit(n) for n, oid in entries.items()),
                 'Repository aggregate/per-file data ceiling exceeded.')
        blobs = self.objects(ids, 'blob', total)
        files = {name: blobs[oid] for name, oid in entries.items()}
        return Snapshot(commit, tree, parent, tuple(sorted(files.items())))

    def branch_snapshot(self, expected=None):
        start = self.tip()
        _require(expected is None or start == _oid(expected), 'Actual local branch differs from expected parent.')
        result = self.snapshot(start)
        _require(self.tip() == start, 'Branch changed during complete snapshot read.')
        return result

    def commit(self, tree, parent=None):
        args = ['commit-tree', '--no-gpg-sign', _oid(tree)]
        if parent is not None:
            args += ['-p', _oid(parent)]
        raw = _commit_bytes(tree, parent)
        message = SEED_MESSAGE if parent is None else COMMIT_MESSAGE
        oid = self.git(args, message, maximum=128).decode('ascii').strip()
        _require(_oid(oid) == _object_id('commit', raw), 'Git emitted an unexpected commit object.')
        return oid

    def write_tree(self, files, directory):
        held = {}
        for name, raw in sorted(files.items()):
            self.guard.directory((directory / name).parent)
            item = self.stack.enter_context(self_update.Held(directory / name))
            _require(_read_held(item, self._limit(name)) == raw, 'Physical assembled-tree bytes differ.')
            held[name] = item
        paths = ''.join(str(directory / name).replace('\\', '/') + '\n' for name in sorted(files)).encode('utf-8')
        output = self.git(['hash-object', '-w', '--no-filters', '--stdin-paths'], paths, maximum=64 * len(files))
        oids = output.decode('ascii').splitlines()
        _require(len(oids) == len(files), 'Hash-object result count differs.')
        nested = {}
        for name, oid in zip(sorted(files), oids):
            _require(_oid(oid) == _object_id('blob', files[name]), 'Git blob hash differs from held source data.')
            node = nested
            parts = name.split('/')
            for part in parts[:-1]:
                node = node.setdefault(part, {})
            node[parts[-1]] = oid

        def write(node):
            rows = []
            for name, value in sorted(node.items(), key=lambda item: item[0] + ('/' if isinstance(item[1], dict) else '')):
                mode, kind, oid = ('40000', 'tree', write(value)) if isinstance(value, dict) else ('100644', 'blob', value)
                rows.append((mode, kind, oid, name))
            data = b''.join((m + ' ' + k + ' ' + oid + '\t' + name).encode('ascii') + b'\0' for m, k, oid, name in rows)
            payload = b''.join((m + ' ' + name).encode('ascii') + b'\0' + bytes.fromhex(oid) for m, _, oid, name in rows)
            oid = self.git(['mktree', '-z'], data, maximum=128).decode('ascii').strip()
            _require(_oid(oid) == _object_id('tree', payload), 'Git tree bytes differ from the complete data plan.')
            return oid
        return write(nested)


def _extract(files):
    _require(files.get('metadata/root.json') == files.get('metadata/1.root.json')
             and files.get('metadata/root.json') is not None, 'Exact supplied numbered root is required.')
    timestamp = staging._parse(files['metadata/timestamp.json'], 'timestamp')
    version = staging._version(timestamp.signed.snapshot_meta.version)
    snapshot_raw = files['metadata/' + str(version) + '.snapshot.json']
    snapshot = staging._parse(snapshot_raw, 'snapshot')
    version = staging._version(snapshot.signed.meta['targets.json'].version)
    targets_raw = files['metadata/' + str(version) + '.targets.json']
    targets = staging._parse(targets_raw, 'targets')
    _require(len(targets.signed.targets) <= staging.MAX_TARGETS, 'Current target count exceeds its bound.')
    metadata = {'root.json': files['metadata/root.json'], 'timestamp.json': files['metadata/timestamp.json'],
                'snapshot.json': snapshot_raw, 'targets.json': targets_raw}
    data, paths = {}, {}
    for logical, spec in targets.signed.targets.items():
        maximum = tuf_channel.target_limit(logical)
        _require(type(spec.hashes) is dict and set(spec.hashes) == {'sha256'} and type(spec.length) is int
                 and 0 < spec.length <= maximum, 'Invalid current target descriptor.')
        digest = _hash(spec.hashes['sha256'])
        prefix, _, name = logical.rpartition('/')
        path = 'targets/' + (prefix + '/' if prefix else '') + digest + '.' + name
        raw = files[path]
        spec.verify_length_and_hashes(raw)
        data[logical], paths[logical] = raw, path
    return metadata, data, paths


def _stage(session, stage_dir):
    root = _path(stage_dir)
    _require(root != session.repo and session.repo not in root.parents and root not in session.repo.parents,
             'Signed stage and bare repository must be separate.')
    pending, files, helds, total = [root], {}, {}, 0
    directories = 0
    while pending:
        directory = pending.pop()
        session.guard.directory(directory)
        directories += 1
        _require(directories <= MAX_FILES, 'Stage directory ceiling exceeded.')
        for path in _paths(directory, MAX_FILES + 4):
            relative = path.relative_to(root).as_posix()
            if path.is_dir():
                core._plain(path, directory=True)
                _require(relative in {'metadata', 'targets', 'targets/assets'}, 'Foreign stage directory refused.')
                pending.append(path)
                continue
            maximum = 2 * 1024**2 if relative == staging.RECEIPT else _limit(relative)
            held, raw = session._hold(path, maximum)
            if relative == staging.RECEIPT:
                continue  # Neither marker presence nor its contents grants authority.
            total += len(raw)
            _require(total <= MAX_BYTES and len(files) < MAX_FILES, 'Stage data ceiling exceeded.')
            _require(relative not in files, 'Duplicate stage path.')
            files[relative], helds[relative] = raw, held
    metadata, data, paths = _extract(files)
    expected = {'metadata/root.json', 'metadata/1.root.json', 'metadata/timestamp.json'}
    expected |= {'metadata/' + str(staging._parse(metadata[r + '.json'], r).signed.version) + '.' + r + '.json'
                 for r in ('snapshot', 'targets')}
    _require(set(files) == expected | set(paths.values()), 'Already-signed stage has foreign or retained-extra files.')
    return metadata, data, {logical: (helds[path], {}) for logical, path in paths.items()}


def _trust(session, public_root, root_sha256, inner_keys):
    _hash(root_sha256)
    _, raw = session._hold(_path(public_root), staging.METADATA_LIMITS['root'])
    _require(hashlib.sha256(raw).hexdigest() == root_sha256, 'Explicit public root SHA-256 differs.')
    _, public = staging._root(raw, renewal._observed(session.clock()))
    return raw, staging._keyring(inner_keys, public)


def _prior(snapshot, root_sha256, now, *, previous=False):
    files = dict(snapshot.files)
    if not files:
        _require(snapshot.commit == SEED, 'Initial publication requires the actual canonical empty seed.')
        return ()
    repository.verify_tree(files=files, expected_parent=snapshot.commit, trusted_root_sha256=root_sha256,
                           now=now, previous=previous)
    metadata, data, _ = _extract(files)
    proofs = {name: raw for name, raw in data.items() if launcher_targets.is_launcher_target(name)}
    return staging._previous_launcher_notices(metadata, proofs)


def _semantic(metadata, data, keys, now, previous, held=None):
    # Git bytes were independently object-hashed. This adapter supplies only the
    # read interface used by _contents; it is not a claimed filesystem handle.
    readers = held or {name: (type('PublicBytesReader', (), {'fp': io.BytesIO(raw)})(), {}) for name, raw in data.items()}
    return staging._contents(readers, keys, now, previous)[1]


def _fresh(session, metadata, catalog):
    now = renewal._observed(session.clock())
    root, _ = staging._root(metadata['root.json'], now)
    policy = staging.Policy(*(staging.RolePolicy(staging._parse(metadata[r + '.json'], r).signed.version,
                                                 staging._parse(metadata[r + '.json'], r).signed.expires)
                              for r in staging.ROLES))
    staging._policy(policy, root, now)
    if catalog is not None:
        catalog.require_current(now)
    return now


def _initial_history(session, directory):
    """Hold only the two prior signed public files, never a prior-state receipt."""
    root = _path(directory)
    _require(root != session.repo and session.repo not in root.parents and root not in session.repo.parents,
             'Initial history and bare repository must be separate.')
    session.guard.directory(root)
    paths = tuple(_paths(root, 3))
    _require({p.name for p in paths} == {'1.targets.json', '1.snapshot.json'} and len(paths) == 2,
             'Initial history directory must contain exactly two numbered metadata files.')
    result = {}
    for path in paths:
        role = path.name.split('.')[1]
        _, result['metadata/' + path.name] = session._hold(path, staging.METADATA_LIMITS[role])
    return result


def _candidate(session, prior, candidate, root_raw, root_sha256, keys, *, initial_publication=False):
    _require(type(initial_publication) is bool, 'Initial publication selection must be an explicit bool.')
    _require(candidate.parent == prior.commit, 'Candidate must have exactly the actual expected parent.')
    metadata, data, _ = _extract(dict(candidate.files))
    _require(metadata['root.json'] == root_raw, 'Candidate differs from the explicit public root bytes.')
    now = renewal._observed(session.clock())
    previous = _prior(prior, root_sha256, now, previous=True)
    history = None
    if initial_publication:
        _require(not prior.files and prior.commit == SEED,
                 'Initial publication requires the actual canonical empty seed, not prior publication.')
        files = dict(candidate.files)
        _require(repository.INITIAL_HISTORY <= files.keys(), 'Initial signed issuance history is missing.')
        history = {name: files[name] for name in repository.INITIAL_HISTORY}
    assembled = repository.assemble(previous_tree=dict(prior.files), metadata=metadata, target_data=data,
        expected_parent=prior.commit, trusted_root_sha256=root_sha256, now=now,
        ledger_bytes=dict(candidate.files).get('public-ledger.json'), initial_history=history)
    _require(assembled.files == candidate.files, 'Candidate actual full Git tree differs from freshly recomputed assembly.')
    _require(candidate.tree == _tree_id(dict(assembled.files)), 'Candidate tree object differs from the canonical complete100644 tree.')
    catalog = _semantic(metadata, data, keys, now, previous)
    _fresh(session, metadata, catalog)
    return metadata, catalog


def init(*, git_exe, git_sha256, repo, work_dir, clock=lambda: datetime.now(timezone.utc)):
    """Create only a new local bare repo and canonical empty seed branch."""
    with _Session(git_exe=git_exe, git_sha256=git_sha256, repo=repo, work_dir=work_dir, clock=clock, new=True) as session:
        session.git(['init', '--bare', '--object-format=sha1', '--initial-branch=' + BRANCH,
                     '--template=' + str(session.hooks), str(session.repo)], maximum=8192)
        session.new = False
        session._gate_repo()
        tree = session.git(['mktree', '-z'], maximum=128).decode().strip()
        _require(tree == EMPTY_TREE, 'Git empty tree differs.')
        seed = session.commit(tree)
        session.git(['update-ref', '--no-deref', REF, seed, '0' * 40], maximum=8192)
        result = session.branch_snapshot(seed)
    return result


def inspect(*, git_exe, git_sha256, repo, work_dir, public_root, root_sha256, inner_keys,
            clock=lambda: datetime.now(timezone.utc)):
    """Return a stable actual fixed-branch snapshot; a receipt cannot substitute."""
    with _Session(git_exe=git_exe, git_sha256=git_sha256, repo=repo, work_dir=work_dir, clock=clock) as session:
        root_raw, keys = _trust(session, public_root, root_sha256, inner_keys)
        result = session.branch_snapshot()
        previous = _prior(result, root_sha256, renewal._observed(clock()))
        if result.files:
            metadata, data, _ = _extract(dict(result.files))
            _require(metadata['root.json'] == root_raw, 'Actual branch root differs from explicit root.')
            catalog = _semantic(metadata, data, keys, renewal._observed(clock()), previous)
            _fresh(session, metadata, catalog)
        _require(session.tip() == result.commit, 'Branch changed before snapshot acknowledgment.')
    return result


def prepare(*, git_exe, git_sha256, repo, work_dir, stage_dir, expected_parent, public_root,
            root_sha256, inner_keys, clock=lambda: datetime.now(timezone.utc), initial_history_dir=None):
    """Produce complete retained files and a real one-parent object; no ref write."""
    with _Session(git_exe=git_exe, git_sha256=git_sha256, repo=repo, work_dir=work_dir, clock=clock) as session:
        root_raw, keys = _trust(session, public_root, root_sha256, inner_keys)
        prior = session.branch_snapshot(_oid(expected_parent))
        metadata, data, held = _stage(session, stage_dir)
        _require(metadata['root.json'] == root_raw, 'Signed stage differs from supplied public root.')
        now = renewal._observed(clock())
        previous = _prior(prior, root_sha256, now, previous=True)
        inputs = {'previous_tree': dict(prior.files), 'metadata': metadata, 'target_data': data,
                  'expected_parent': prior.commit, 'trusted_root_sha256': root_sha256}
        if initial_history_dir is not None:
            _require(not prior.files and prior.commit == SEED,
                     'Initial publication requires the actual canonical empty seed.')
            inputs['initial_history'] = _initial_history(session, initial_history_dir)
        assembled = repository.assemble(now=now, **inputs)
        approved_catalog = _semantic(metadata, data, keys, now, previous, held)
        output = repository.stage(output_dir=session.work / 'assembled', clock=clock, **inputs)
        tree = session.write_tree(dict(assembled.files), output / 'repository')
        commit = session.commit(tree, prior.commit)
        actual = session.snapshot(commit)
        _candidate(session, prior, actual, root_raw, root_sha256, keys,
                   initial_publication=initial_history_dir is not None)
        _fresh(session, metadata, approved_catalog)
        _require(session.tip() == prior.commit, 'Branch changed before prepared acknowledgment.')
        receipt = {'schema': 1, 'status': 'prepared-local-object-no-ref-advance', 'published': False,
                   'expected_parent': prior.commit, 'commit': commit, 'tree': tree,
                   'trusted_root_sha256': root_sha256, 'files': len(actual.files)}
        staging._write(session.work / 'candidate.json', core._canonical(receipt), session.stack)
        result = Prepared(prior.commit, commit, tree, session.work)
    _fresh(session, metadata, approved_catalog)
    return result


def activate(*, git_exe, git_sha256, repo, work_dir, candidate_commit, expected_parent, public_root,
             root_sha256, inner_keys, clock=lambda: datetime.now(timezone.utc), initial_publication=False):
    """Local-only fixed-ref atomic new/old CAS after full actual-byte admission."""
    session = _Session(git_exe=git_exe, git_sha256=git_sha256, repo=repo, work_dir=work_dir, clock=clock)
    try:
        with session:
            root_raw, keys = _trust(session, public_root, root_sha256, inner_keys)
            prior = session.branch_snapshot(_oid(expected_parent))
            candidate = session.snapshot(_oid(candidate_commit))
            metadata, catalog = _candidate(session, prior, candidate, root_raw, root_sha256, keys,
                                           initial_publication=initial_publication)

            def final_gate():
                _require(session.tip() == prior.commit, 'Actual expected parent changed before local CAS.')
                _fresh(session, metadata, catalog)

            final_gate()
            session.cas_started = True
            session.git(['update-ref', '--no-deref', REF, candidate.commit, prior.commit], maximum=8192,
                        before_start=lambda: _fresh(session, metadata, catalog))
            _require(session.tip() == candidate.commit, 'Local ref acknowledgment differs.')
            acknowledged = session.branch_snapshot(candidate.commit)
            _require(acknowledged == candidate, 'Activated actual Git bytes differ from candidate.')
            _candidate(session, prior, acknowledged, root_raw, root_sha256, keys,
                       initial_publication=initial_publication)
            _fresh(session, metadata, catalog)
            result = Activated(prior.commit, candidate.commit, candidate.tree)
        _fresh(session, metadata, catalog)
        return result
    except Exception as exc:  # Any error after entering CAS is explicit uncertainty.
        if session.cas_started:
            raise ActivationUncertain('Local activation state is uncertain. Retain all files and inspect the actual fixed ref; no completion is admitted.') from exc
        raise


def main(argv=None):
    selected = __import__('sys').argv[1:] if argv is None else argv
    if selected and selected[0] in {'init-v2', 'inspect-v2', 'prepare-v2', 'activate-v2', 'prepare-renewal-v2'}:
        if __name__ == '__main__':
            # v2 imports this module by its package name. Bind that name to the
            # actual CLI host so its accepted cleanup loop owns the SAME set.
            modules = __import__('sys').modules
            current = modules[__name__]
            canonical = __package__ + '.git_operator'
            _require(modules.get(canonical) in (None, current), 'Use a fresh module CLI host; an operator is already imported.')
            modules[canonical] = current
        from . import git_operator_v2
        return git_operator_v2.main(selected)
    parser = argparse.ArgumentParser(description='Offline local-only data Git operator; no transports or signing.')
    parser.add_argument('command', choices=('init', 'inspect', 'prepare', 'activate'))
    for name in ('git-exe', 'git-sha256', 'repo', 'work-dir'):
        parser.add_argument('--' + name, required=True)
    parser.add_argument('--public-root')
    parser.add_argument('--root-sha256')
    parser.add_argument('--inner-keys')
    parser.add_argument('--stage-dir')
    parser.add_argument('--expected-parent')
    parser.add_argument('--candidate-commit')
    args = parser.parse_args(argv)
    common = {name: getattr(args, name) for name in ('git_exe', 'git_sha256', 'repo', 'work_dir')}
    if args.command == 'init':
        _require(all(getattr(args, name) is None for name in ('public_root', 'root_sha256', 'inner_keys', 'stage_dir', 'expected_parent', 'candidate_commit')),
                 'Init accepts only the four local common inputs.')
        result = init(**common)
    else:
        _require(args.public_root and args.root_sha256 and args.inner_keys, 'Explicit public root/hash/public inner keyring are required.')
        # Read immutable public-only input, then check all input closes BEFORE
        # a possible ref operation. No private format, signer or key loader.
        with ExitStack() as stack:
            guard = stack.enter_context(renewal.CheckedGuard())
            path = _path(args.inner_keys)
            guard.directory(path.parent)
            held = stack.enter_context(self_update.Held(path))
            value = core._json(_read_held(held, 8192), 8192, 'Public inner keyring')
            _require(isinstance(value, Mapping) and len(value) <= 32 and all(type(k) is str and type(v) is str and HASH.fullmatch(v) for k, v in value.items()),
                     'Only a bounded public32-byte hex key mapping is accepted.')
            keys = {k: bytes.fromhex(v) for k, v in value.items()}
        common.update(public_root=args.public_root, root_sha256=args.root_sha256, inner_keys=keys)
        if args.command == 'inspect':
            _require(not args.stage_dir and not args.expected_parent and not args.candidate_commit, 'Inspect accepts no candidate/ref inputs.')
            result = inspect(**common)
        elif args.command == 'prepare':
            _require(args.stage_dir and args.expected_parent and not args.candidate_commit, 'Prepare requires only signed stage and expected parent.')
            result = prepare(**common, stage_dir=args.stage_dir, expected_parent=args.expected_parent)
        else:
            _require(args.candidate_commit and args.expected_parent and not args.stage_dir, 'Activate requires candidate object and expected parent.')
            result = activate(**common, candidate_commit=args.candidate_commit, expected_parent=args.expected_parent)
    try:
        print(json.dumps({'status': args.command + '-local-only', 'published': False, 'commit': result.commit,
                          'tree': result.tree, **({'files': len(result.files)} if isinstance(result, Snapshot) else {})}, sort_keys=True))
    except Exception as exc:  # Failed completion output cannot disprove the local ref write.
        if isinstance(result, Activated):
            raise ActivationUncertain('Local activation acknowledgment failed. Retain all files and inspect the actual fixed ref.') from exc
        raise
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception as error:  # noqa: BLE001 - fixed no-secret CLI failure; full evidence remains local
        print(type(error).__name__ + ': local operator refused or uncertain; retain the work directory.', file=__import__('sys').stderr)
        # An uncertain owner must outlive this error, including when no worker
        # started. Do not exit the CLI and silently drop the physical lease.
        while _RETAINED_SESSIONS:
            for session in tuple(_RETAINED_SESSIONS):
                try:
                    session.retry_cleanup()
                except BaseException:  # noqa: BLE001 - CLI must retain uncertain physical ownership
                    time.sleep(1)
        raise SystemExit(2) from None
