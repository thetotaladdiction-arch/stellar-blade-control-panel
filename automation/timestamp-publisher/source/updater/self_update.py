"""Private Windows onedir self-update staging and account-bound handoff.

Only check_for_update() obtains publisher authority, through the shared TUF
boundary. A staged plan retains those ORIGINAL bytes in a DPAPI envelope. This
is a local authorization receipt, not a publisher signature: malicious code
running as the same Windows account (or administrator) is outside the threat
model, as in core.py. No production configuration or unsigned fallback exists.

The installed bundle and its sibling .Aeroneus-update store must be ordinary
local NTFS directories. Program inventory is exact; user-data is reserved.
QSettings outside the bundle is never read or written. All scratch, preimages,
old versions and records are retained. No API deletes or clobbers a file.
"""
from __future__ import annotations

import base64
import contextlib
import ctypes
import hashlib
import os
from pathlib import Path
import re
import stat
import threading
import time
import uuid
from ctypes import wintypes

from . import core, launcher_targets, tuf_channel

UpdateError = core.UpdateError
TARGET = launcher_targets.target_for_baseline()
PRODUCT = "aeroneus-launcher"
EXE = "Aeroneus.exe"
CONTROL = ".Aeroneus-update"
MAX_NOTICE = 2 * 1024 * 1024
MAX_PLAN = core.MAX_JOURNAL_BYTES
_GRANTS = {}
_GRANT_LOCK = threading.Lock()
_BUSY = set()
_BUSY_LOCK = threading.Lock()
_EVENTS = frozenset({"ui-exit", "dispatch", "dispatch-recover", "dispatch-rollback", "applying", "committed",
                    "recovering", "rolled-back", "cancelled", "rollback-request", "rollback-exit", "rollback-cancel", "relaunch", "relaunch-restored"})


def _event_name(name):
    return (name in _EVENTS or re.fullmatch(r"(?:dispatch-attempt|spawn-failed|helper-used)-[0-9a-f]{32}", name)
            or re.fullmatch(r"rollback-(?:request|exit|cancel)-[0-9]{4}", name))


class Release:
    """Opaque short-lived UI capability; copies/dictionaries are not authority."""
    __slots__ = ("version", "notes")

    def __init__(self, version, notes):
        self.version, self.notes = version, notes


def _inventory(value):
    if type(value) is not list or not 1 <= len(value) <= core.MAX_FILES:
        raise UpdateError("The launcher inventory is empty or exceeds its limit.")
    names, folded, total = {}, set(), 0
    for row in value:
        core._shape(row, {"path", "size", "sha256"}, "Launcher file")
        name = core._relative(row["path"])
        if name.split("/")[0].casefold() in {"user-data", CONTROL.casefold()}:
            raise UpdateError("The launcher package cannot own settings or updater storage.")
        key = name.casefold()
        if key in folded:
            raise UpdateError("The launcher inventory has colliding filenames.")
        folded.add(key)
        core._integer(row["size"], 0, core.MAX_FILE_BYTES, "Launcher file size")
        core._hash_text(row["sha256"])
        total += row["size"]
        names[name] = row
    if total > core.MAX_UNCOMPRESSED_BYTES or EXE not in names or names[EXE]["size"] == 0:
        raise UpdateError("The complete launcher bundle is missing or too large.")
    for name in folded:
        if any("/".join(name.split("/")[:i]) in folded for i in range(1, len(name.split("/")))):
            raise UpdateError("The launcher inventory contains a file/directory collision.")
    return names


def _notice(raw):
    obj = core._json(raw, MAX_NOTICE, "Authenticated launcher notice")
    core._shape(obj, {"schema", "product", "version", "baseline", "files", "archive", "notes"}, "Launcher notice")
    core._integer(obj["schema"], 1, 1, "Launcher schema")
    if obj["product"] != PRODUCT:
        raise UpdateError("This authenticated target is not a launcher release.")
    baseline = core._shape(obj["baseline"], {"version", "files"}, "Launcher baseline")
    if core._version(obj["version"]) <= core._version(baseline["version"]):
        raise UpdateError("Launcher releases must advance the exact baseline version.")
    before, after = _inventory(baseline["files"]), _inventory(obj["files"])
    # Case changes and file-to-directory transitions need a new packaging layout.
    union = {name.casefold(): name for name in before}
    for name in after:
        if name.casefold() in union and union[name.casefold()] != name:
            raise UpdateError("Case-only launcher renames are not supported.")
        union[name.casefold()] = name
    for name in union:
        if any("/".join(name.split("/")[:i]) in union for i in range(1, len(name.split("/")))):
            raise UpdateError("A launcher update cannot change a file into a directory.")
    archive = core._shape(obj["archive"], {"url", "size", "sha256", "prefix"}, "Launcher archive")
    core._url(archive["url"], initial=True)
    core._integer(archive["size"], 22, core.MAX_ARCHIVE_BYTES, "Launcher archive size")
    core._hash_text(archive["sha256"])
    if archive["prefix"] != "":
        core._relative(archive["prefix"], "Archive prefix")
    core._text(obj["notes"], 16000, "Release notes", empty=True)
    return obj


def check_for_update(cancel_event=None):
    """Refresh the compiled TUF target, returning a capability for prepare_update.

    Root integration must supply tuf_channel.fetch_target. Missing integration,
    configuration or failed authentication is an error, never a raw-feed path.
    """
    target = launcher_targets.target_for_baseline()
    fetch = getattr(tuf_channel, "fetch_target", None)
    if fetch is None:
        raise UpdateError("The reviewed launcher TUF target hook is not integrated.")
    try:
        raw = fetch(target, cancel_event=cancel_event)
    except tuf_channel.TargetNotPublished as exc:
        if exc.target_name != target:
            raise
        return None  # Authenticated absence creates no installation capability.
    notice = _notice(raw)
    launcher_targets.validate_notice(target, notice)
    release = Release(notice["version"], notice["notes"])
    with _GRANT_LOCK:
        if len(_GRANTS) >= 16:
            _GRANTS.pop(next(iter(_GRANTS)))
        _GRANTS[id(release)] = (release, raw, time.monotonic() + 600)
    return release


def _authority(release):
    with _GRANT_LOCK:
        grant = _GRANTS.get(id(release))
        if grant is None or grant[0] is not release or time.monotonic() >= grant[2]:
            raise UpdateError("Check the authenticated launcher channel again before staging.")
        return grant[1], _notice(grant[1])


def _path(value):
    raw = os.fspath(value)
    if not isinstance(raw, str):
        raise UpdateError("Use an ordinary absolute Windows path.")
    components = raw.replace("\\", "/").split("/")[1:]
    if any(p in (".", "..") or p.endswith((".", " ")) or "~" in p for p in components if p):
        raise UpdateError("Path aliases and shortened Windows names are not supported.")
    return core._absolute(raw)


def _kernel():
    kernel = core._kernel()
    signatures = {
        "GetFinalPathNameByHandleW": ([wintypes.HANDLE, wintypes.LPWSTR, wintypes.DWORD, wintypes.DWORD], wintypes.DWORD),
        "QueryDosDeviceW": ([wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.DWORD], wintypes.DWORD),
        "OpenProcess": ([wintypes.DWORD, wintypes.BOOL, wintypes.DWORD], wintypes.HANDLE),
        "GetProcessTimes": ([wintypes.HANDLE, *([ctypes.POINTER(wintypes.FILETIME)] * 4)], wintypes.BOOL),
        "QueryFullProcessImageNameW": ([wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)], wintypes.BOOL),
    }
    for name, (args, result) in signatures.items():
        getattr(kernel, name).argtypes, getattr(kernel, name).restype = args, result
    return kernel


def _canonical_handle(handle, path):
    kernel = _kernel()
    final = ctypes.create_unicode_buffer(1024)
    length = kernel.GetFinalPathNameByHandleW(handle, final, len(final), 0)
    if not 0 < length < len(final) or final.value.removeprefix("\\\\?\\").casefold() != str(path).casefold():
        raise UpdateError("A filesystem path resolves through an alias.")
    device = ctypes.create_unicode_buffer(1024)
    if not kernel.QueryDosDeviceW(path.drive, device, len(device)) or not device.value.startswith("\\Device\\HarddiskVolume"):
        raise UpdateError("Only ordinary local volume paths are supported.")


def _streams(path, *, allow_origin=False):
    from .origin import inspect
    return inspect(path, allow_origin=allow_origin)


class Guard(core._Guard):
    """GENERIC_READ directory leases: READ_ATTRIBUTES alone does not deny rename."""
    def directory(self, path, *, create=False):
        path, kernel = _path(path), _kernel()
        for current in reversed((path, *path.parents)):
            key = str(current).casefold()
            if key in self.handles:
                continue
            if create and not core._exists(current):
                current.mkdir(mode=0o700)
            before = core._plain(current, directory=True)
            handle = kernel.CreateFileW(str(current), 0x80000000, 3, None, 3, 0x02200000, None)
            if handle in (None, ctypes.c_void_p(-1).value):
                raise UpdateError("Cannot hold the launcher directory against renames.")
            try:
                info = core._FileInfo()
                identity = core._FileIdInfo()
                if (not kernel.GetFileInformationByHandle(handle, ctypes.byref(info))
                        or info.attributes & 0x400 or not info.attributes & 0x10
                        or not kernel.GetFileInformationByHandleEx(handle, 18, ctypes.byref(identity), ctypes.sizeof(identity))
                        or (identity.volume, int.from_bytes(identity.file_id, "little")) != (before.st_dev, before.st_ino)):
                    raise UpdateError("The launcher directory changed during inspection.")
                _canonical_handle(handle, current)
            except BaseException:
                kernel.CloseHandle(handle)
                raise
            self.handles[key] = handle


class Held(core._HeldFile):
    def __init__(self, path, *, allow_origin=False, **kwargs):
        super().__init__(_path(path), allow_origin=allow_origin, **kwargs)
        try:
            _canonical_handle(self.handle, self.path)
            self.origin.check()
        except BaseException:
            self.__exit__()
            raise


def _identity(path):
    info = core._plain(path, directory=True)
    return f"{info.st_dev}:{info.st_ino}"


@contextlib.contextmanager
def _mutex(root, namespace):
    key = namespace + hashlib.sha256(str(root).casefold().encode()).hexdigest()
    with _BUSY_LOCK:
        if key in _BUSY:
            raise UpdateError("Another launcher operation is already active.")
        _BUSY.add(key)
    handle, acquired = None, False
    try:
        handle = _kernel().CreateMutexW(None, False, "Global\\Aeroneus.SelfUpdate." + key)
        if not handle:
            raise UpdateError("Cannot acquire the launcher update lease.")
        acquired = _kernel().WaitForSingleObject(handle, 0) in (0, 0x80)
        if not acquired:
            raise UpdateError("Another launcher operation is already active.")
        yield
    finally:
        if acquired:
            _kernel().ReleaseMutex(handle)
        if handle:
            _kernel().CloseHandle(handle)
        with _BUSY_LOCK:
            _BUSY.discard(key)


def lease(root):
    return _mutex(root, "transaction.")


@contextlib.contextmanager
def launcher_session(launcher_root):
    """Root bootstrap must hold this before initializing UI until UI exit.

    Helpers hold the SAME gate throughout mutation. This prevents another
    cooperating launcher instance starting between process scan and swap.
    Acquire/release on one thread (Windows mutex ownership is thread-bound).
    """
    root, _ = _location(launcher_root)
    with Guard() as guard:
        guard.directory(root)
        with _mutex(root, "session."):
            yield


def require_stopped(root, plan, *, _exclude_current=False):
    """Read-only native scan for bundle executable images, including child EXEs.

    Unqueryable matching process names fail closed. The launcher_session gate
    covers cooperating startup races; hostile same-user execution is excluded.
    """
    class Entry(ctypes.Structure):
        _fields_ = [("size", wintypes.DWORD), ("usage", wintypes.DWORD), ("pid", wintypes.DWORD),
                    ("heap", ctypes.c_size_t), ("module", wintypes.DWORD), ("threads", wintypes.DWORD),
                    ("parent", wintypes.DWORD), ("priority", wintypes.LONG), ("flags", wintypes.DWORD),
                    ("exe", wintypes.WCHAR * 260)]
    kernel = _kernel()
    kernel.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    kernel.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    for function in (kernel.Process32FirstW, kernel.Process32NextW):
        function.argtypes, function.restype = [wintypes.HANDLE, ctypes.POINTER(Entry)], wintypes.BOOL
    names = {Path(n).name.casefold() for n in set(plan["before"]) | set(plan["after"]) if n.casefold().endswith(".exe")}
    snapshot = kernel.CreateToolhelp32Snapshot(2, 0)
    if snapshot in (None, ctypes.c_void_p(-1).value):
        raise UpdateError("Cannot inspect running launcher processes.")
    try:
        entry = Entry()
        entry.size = ctypes.sizeof(entry)
        if not kernel.Process32FirstW(snapshot, ctypes.byref(entry)):
            raise UpdateError("Cannot read the running-process inventory.")
        while True:
            if entry.exe.casefold() in names and not (_exclude_current and entry.pid == os.getpid()):
                handle = kernel.OpenProcess(0x1000, False, entry.pid)
                if not handle:
                    raise UpdateError("Cannot rule out another running launcher process.")
                try:
                    buffer, length = ctypes.create_unicode_buffer(1024), wintypes.DWORD(1024)
                    if not kernel.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(length)):
                        raise UpdateError("Cannot identify another launcher process.")
                    image = str(_path(buffer.value)).casefold()
                    if image.startswith(str(root).casefold() + "\\"):
                        raise UpdateError("Close every process using this launcher bundle before updating.")
                finally:
                    kernel.CloseHandle(handle)
            if not kernel.Process32NextW(snapshot, ctypes.byref(entry)):
                if ctypes.get_last_error() != 18:
                    raise UpdateError("The launcher process scan was incomplete.")
                break
    finally:
        kernel.CloseHandle(snapshot)


def require_runner_idle(tx, plan):
    """Under transaction lease, rule out any earlier runner/helper process.

    This is a complete native image scan, not absent-PID-as-UI-exit evidence.
    An active caller may exclude ONLY itself, after verifying its native image
    is the exact retained runner. Helpers hold the same transaction lease for
    their entire mutation, closing the scan/startup race between dispatchers.
    """
    runner = tx / "runner"
    probe = object.__new__(ProcessGuard)
    probe.expected = {"pid": os.getpid()}
    probe.handle = _kernel().OpenProcess(0x100000 | 0x1000, False, os.getpid())
    if not probe.handle:
        raise UpdateError("Cannot verify the recovery dispatcher process.")
    with probe:
        own = probe.identity()
    exclude = own["image"].casefold() == str(runner / EXE).casefold()
    require_stopped(runner, plan, _exclude_current=exclude)


def _tree(root, guard, *, user_data=False):
    """Bounded inventory. Never recurse through a redirect, including settings."""
    files, pending, count = {}, [root], 0
    while pending:
        folder = pending.pop()
        guard.directory(folder)
        with os.scandir(folder) as entries:
            for entry in entries:
                count += 1
                if count > 4096:
                    raise UpdateError("The launcher folder exceeds its inventory limit.")
                path = Path(entry.path)
                relative = path.relative_to(root).as_posix()
                core._relative(relative)
                info = path.lstat()
                if stat.S_ISDIR(info.st_mode):
                    core._plain(path, directory=True)
                    pending.append(path)
                else:
                    core._plain(path)
                    if user_data and relative.startswith("user-data/"):
                        continue
                    if relative.casefold() in {x.casefold() for x in files}:
                        raise UpdateError("The launcher tree contains aliases.")
                    files[relative] = path
    return files


def _hold_inventory(root, specs, guard, stack, *, move=False, recorded=None, user_data=False, allow_origin=False):
    files = _tree(root, guard, user_data=user_data)
    if set(files) != set(specs):
        raise UpdateError("The launcher folder does not match its exact owned inventory.")
    held, identities = {}, {}
    for name in sorted(specs):
        file = stack.enter_context(Held(files[name], move=move, exclusive=move, allow_origin=allow_origin))
        actual = file.fingerprint()
        if not core._signed_match(actual, specs[name]) or recorded is not None and actual != recorded[name]:
            raise UpdateError("A launcher file differs from the authorized baseline: " + name)
        held[name], identities[name] = file, actual
    return held, identities


def _seal(path, value, guard):
    """Append only: flush a new DPAPI record, then publish without replacement."""
    guard.directory(path.parent, create=True)
    if core._exists(path):
        raise UpdateError("This launcher operation was already recorded.")
    raw = core._canonical(value)
    if len(raw) > MAX_PLAN:
        raise UpdateError("The launcher handoff exceeds its supported limit.")
    temporary = path.parent / ("pending-" + uuid.uuid4().hex)
    with Held(temporary, create=True) as output:
        encrypted = core._dpapi(raw)
        if output.fp.write(encrypted) != len(encrypted):
            raise UpdateError("The launcher record could not be written completely.")
        output.fp.flush()
        os.fsync(output.fp.fileno())
    if not _kernel().MoveFileExW(str(temporary), str(path), 8):
        raise UpdateError("The launcher record could not be published; pending bytes were retained.")


def _unseal(path):
    with Held(path) as file:
        encrypted = core._read_held(file, MAX_PLAN + 65536)
    return core._json(core._dpapi(encrypted, decrypt=True), MAX_PLAN, "Launcher handoff")


def _slot(tx, section, name):
    return core._slot(tx, section, name)


def _copy(source, destination, spec, guard, cancel_event=None, deadline=float("inf"), *, origin_source):
    # Preserve self-update's additional canonical-file/local-volume checks at
    # BOTH create and readback; the generic core copier does not supply these.
    guard.directory(destination.parent, create=True)
    origin_source.origin.check()
    source.seek(0)
    with Held(destination, create=True, allow_origin=True) as output:
        core._stream_copy(source, output.fp, spec["size"], spec["sha256"], cancel_event, deadline)
        output.origin.inherit(origin_source.origin.raw)
    with Held(destination, allow_origin=True) as check:
        actual = check.fingerprint()
        if not core._signed_match(actual, spec) or check.origin.raw != origin_source.origin.raw:
            raise UpdateError("The launcher copy failed content/origin readback.")
    origin_source.origin.check()
    return actual


def _ticks(value):
    return str((value.dwHighDateTime << 32) | value.dwLowDateTime)


class ProcessGuard:
    """Pinned kernel object; absent PID, reused PID and query failure all refuse."""
    def __init__(self, expected):
        _process_shape(expected)
        self.expected, self.handle = expected, None
        handle = _kernel().OpenProcess(0x100000 | 0x1000, False, expected["pid"])
        if not handle:
            raise UpdateError("The original UI process cannot be identity-checked. No helper was started.")
        self.handle = handle
        try:
            if self.identity() != expected:
                raise UpdateError("The UI process identity changed or its PID was reused.")
        except BaseException:
            self.close()
            raise

    def identity(self):
        created, ended, kernel_time, user_time = (wintypes.FILETIME() for _ in range(4))
        if not _kernel().GetProcessTimes(self.handle, ctypes.byref(created), ctypes.byref(ended), ctypes.byref(kernel_time), ctypes.byref(user_time)):
            raise UpdateError("Cannot verify original UI creation time.")
        buffer, length = ctypes.create_unicode_buffer(1024), wintypes.DWORD(1024)
        if not _kernel().QueryFullProcessImageNameW(self.handle, 0, buffer, ctypes.byref(length)):
            raise UpdateError("Cannot verify original UI image identity.")
        return {"pid": self.expected["pid"], "created": _ticks(created), "image": str(_path(buffer.value))}

    def wait(self, timeout=30, cancel_event=None):
        if type(timeout) not in (int, float) or not 0 <= timeout <= 60:
            raise UpdateError("Use a bounded UI exit wait of at most 60 seconds.")
        end = time.monotonic() + timeout
        while True:
            if cancel_event is not None and cancel_event.is_set():
                raise UpdateError("Waiting for UI exit was cancelled.")
            state = _kernel().WaitForSingleObject(self.handle, 0)
            if state == 0:
                times = [wintypes.FILETIME() for _ in range(4)]
                if (not _kernel().GetProcessTimes(self.handle, *(ctypes.byref(t) for t in times))
                        or _ticks(times[0]) != self.expected["created"] or int(_ticks(times[1])) == 0):
                    raise UpdateError("The original UI exit could not be proved.")
                return {"process": self.expected, "exited": _ticks(times[1])}
            if state != 258 or time.monotonic() >= end:
                raise UpdateError("The original UI has not verifiably exited; update refused.")
            time.sleep(min(0.05, max(0, end - time.monotonic())))

    def close(self):
        if self.handle:
            _kernel().CloseHandle(self.handle)
            self.handle = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


def _process_shape(value):
    core._shape(value, {"pid", "created", "image"}, "Original UI identity")
    core._integer(value["pid"], 1, 0xffffffff, "Original UI PID")
    if type(value["created"]) is not str or not re.fullmatch(r"[1-9][0-9]{0,19}", value["created"]):
        raise UpdateError("The original UI creation time is invalid.")
    _path(value["image"])


def _current_ui(root):
    handle = _kernel().OpenProcess(0x100000 | 0x1000, False, os.getpid())
    if not handle:
        raise UpdateError("Cannot identify the current launcher process.")
    process = object.__new__(ProcessGuard)
    process.handle, process.expected = handle, {"pid": os.getpid()}
    with process:
        identity = process.identity()
    if identity["image"].casefold() != str(root / EXE).casefold():
        raise UpdateError("Self-update must be prepared by this installed onedir launcher.")
    return identity


def _location(root):
    root = _path(root)
    if root.name != "Aeroneus" or root.parent == root:
        raise UpdateError("The portable owned launcher directory must be named Aeroneus.")
    return root, root.parent / CONTROL


def _pending(control, guard, *, except_tx=None):
    guard.directory(control, create=True)
    entries = list(control.iterdir())
    if len(entries) > 256:
        raise UpdateError("Too many retained launcher transactions; review retained storage.")
    for entry in entries:
        if not re.fullmatch(r"tx-[0-9a-f]{32}", entry.name):
            raise UpdateError("Unrecognized content in launcher transaction storage.")
        core._plain(entry, directory=True)
        if entry == except_tx or not core._exists(entry / "plan.dpapi"):
            continue  # incomplete staging cannot have authority to change the bundle
        plan = read_plan(entry, guard)
        terminal = any(read_event(entry, plan, event) is not None for event in ("rolled-back", "cancelled"))
        complete = (read_event(entry, plan, "committed") is not None
                    and read_event(entry, plan, "recovering") is None and active_rollback(entry, plan) is None)
        if not terminal and not complete:
            raise UpdateError("Recover or cancel the earlier launcher transaction first: " + str(entry))


def prepare_update(release, launcher_root, cancel_event=None):
    """Download/copy into a new sibling transaction; never changes installed files.

    Call from the original UI. A separate already-running broker must acquire
    ExitBroker before that UI exits. No updater process is launched here.
    """
    raw, notice = _authority(release)
    root, control = _location(launcher_root)
    before, after = _inventory(notice["baseline"]["files"]), _inventory(notice["files"])
    with lease(root), Guard() as guard, contextlib.ExitStack() as stack:
        guard.directory(root)
        core._ntfs(root)
        _pending(control, guard)
        ui = _current_ui(root)
        sources, old = _hold_inventory(root, before, guard, stack, user_data=True, allow_origin=True)
        need = notice["archive"]["size"] + sum(f["size"] for f in after.values()) + 2 * sum(f["size"] for f in before.values())
        need += (1 + len(after) + 2 * len(before)) * core.MAX_ORIGIN_BYTES
        core._space(control, need)
        tx = control / ("tx-" + uuid.uuid4().hex)
        guard.directory(tx, create=True)
        deadline = time.monotonic() + core.DOWNLOAD_SECONDS
        core._cancel(cancel_event, deadline)
        core._download(notice, tx / "release.zip", cancel_event, deadline)
        fresh = {}
        with Held(tx / "release.zip", allow_origin=True) as archive_file:
            if not core._signed_match(archive_file.fingerprint(core.MAX_ARCHIVE_BYTES), notice["archive"]):
                raise UpdateError("The staged launcher archive is not the authenticated release.")
            archive, indexed = core._zip_index(archive_file.fp, notice)
            with archive:
                for name, spec in after.items():
                    with archive.open(indexed[name]) as source:
                        # ZipExtFile is already at offset zero; _copy uses seek(0).
                        fresh[name] = _copy(source, _slot(tx, "prepared", name), spec, guard, cancel_event, deadline, origin_source=archive_file)
        runner, backup = {}, {}
        for name, file in sources.items():
            backup[name] = _copy(file.fp, _slot(tx, "backup", name), before[name], guard, cancel_event, deadline, origin_source=file)
            runner[name] = _copy(file.fp, tx / "runner" / name, before[name], guard, cancel_event, deadline, origin_source=file)
            if file.fingerprint() != old[name]:
                raise UpdateError("The baseline changed during staging.")
        _authority(release)  # short-lived authority must still be current
        plan = {"schema": 1, "product": PRODUCT, "transaction": str(tx), "root": str(root),
                "root_id": _identity(root), "control_id": _identity(control), "tx_id": _identity(tx),
                "notice": base64.b64encode(raw).decode("ascii"), "notice_sha256": hashlib.sha256(raw).hexdigest(),
                "before": old, "after": fresh, "runner": runner, "backup": backup, "process": ui,
                "prepared_at": int(time.time())}
        _seal(tx / "plan.dpapi", plan, guard)
        with _GRANT_LOCK:
            _GRANTS.pop(id(release), None)
        return tx


def read_plan(transaction, guard):
    tx = _path(transaction)
    if not re.fullmatch(r"tx-[0-9a-f]{32}", tx.name) or tx.parent.name != CONTROL:
        raise UpdateError("Select a retained launcher transaction.")
    guard.directory(tx)
    plan = _unseal(tx / "plan.dpapi")
    core._shape(plan, {"schema", "product", "transaction", "root", "root_id", "control_id", "tx_id", "notice", "notice_sha256", "before", "after", "runner", "backup", "process", "prepared_at"}, "Launcher plan")
    core._integer(plan["schema"], 1, 1, "Plan schema")
    core._integer(plan["prepared_at"], 1, 2**53, "Preparation time")
    root, control = _location(plan["root"])
    if plan["product"] != PRODUCT or plan["transaction"] != str(tx) or control != tx.parent:
        raise UpdateError("The launcher transaction belongs to another product or location.")
    guard.directory(root)
    if (plan["root_id"], plan["control_id"], plan["tx_id"]) != (_identity(root), _identity(control), _identity(tx)):
        raise UpdateError("A launcher transaction directory was replaced.")
    raw = core._b64(plan["notice"], MAX_NOTICE, "Original authenticated notice")
    if hashlib.sha256(raw).hexdigest() != plan["notice_sha256"]:
        raise UpdateError("The retained authenticated notice changed.")
    notice = _notice(raw)
    for key, specs in (("before", _inventory(notice["baseline"]["files"])), ("after", _inventory(notice["files"])), ("runner", _inventory(notice["baseline"]["files"])), ("backup", _inventory(notice["baseline"]["files"]))):
        if type(plan[key]) is not dict or set(plan[key]) != set(specs):
            raise UpdateError("The launcher transaction inventory is inconsistent.")
        for name, fingerprint in plan[key].items():
            core._fingerprint_shape(fingerprint)
            if not core._signed_match(fingerprint, specs[name]):
                raise UpdateError("A retained identity differs from the authenticated notice.")
    _process_shape(plan["process"])
    if plan["process"]["image"].casefold() != str(root / EXE).casefold():
        raise UpdateError("The original process is not this launcher.")
    allowed = {"plan.dpapi", "release.zip", *(e + ".dpapi" for e in _EVENTS),
               *("runner/" + name for name in plan["runner"])}
    for section, names in (("backup", plan["backup"]), ("originals", plan["before"]),
                           ("prepared", plan["after"]), ("reverted", plan["after"])):
        allowed.update(_slot(tx, section, name).relative_to(tx).as_posix() for name in names)
    for relative in _tree(tx, guard):
        dynamic = relative.endswith(".dpapi") and _event_name(relative[:-6])
        if relative not in allowed and not dynamic and not re.fullmatch(r"pending-[0-9a-f]{32}", relative):
            raise UpdateError("The launcher transaction contains an unrecognized file.")
    return plan


def write_event(tx, plan, name, data, guard):
    if not _event_name(name):
        raise UpdateError("Invalid launcher event.")
    _seal(tx / (name + ".dpapi"), {"schema": 1, "transaction": str(tx),
          "plan_sha256": hashlib.sha256(core._canonical(plan)).hexdigest(), "event": name, "data": data}, guard)


def read_event(tx, plan, name):
    if not _event_name(name):
        raise UpdateError("Invalid launcher event.")
    path = tx / (name + ".dpapi")
    if not core._exists(path):
        return None
    value = _unseal(path)
    core._shape(value, {"schema", "transaction", "plan_sha256", "event", "data"}, "Launcher event")
    if (type(value["schema"]) is not int or value["schema"] != 1 or value["transaction"] != str(tx)
            or value["plan_sha256"] != hashlib.sha256(core._canonical(plan)).hexdigest() or value["event"] != name):
        raise UpdateError("The launcher event does not belong to this transaction.")
    return value["data"]


def cancel_prepared(transaction):
    tx = _path(transaction)
    with Guard() as guard:
        plan = read_plan(tx, guard)
        with lease(Path(plan["root"])):
            if any(read_event(tx, plan, e) is not None for e in ("dispatch", "applying", "committed", "rolled-back", "cancelled")):
                raise UpdateError("This transaction can no longer be cancelled; use recovery.")
            write_event(tx, plan, "cancelled", {}, guard)


def describe_transaction(transaction):
    """Read-only UI summary of authenticated journal state, not a health verdict."""
    tx = _path(transaction)
    with Guard() as guard:
        plan = read_plan(tx, guard)
        notice = _notice(core._b64(plan["notice"], MAX_NOTICE, "Notice"))
        state = "staged"
        for name, status in (("ui-exit", "ready"), ("applying", "recovery-required"), ("committed", "committed"),
                             ("rollback-request", "rollback-requested"), ("recovering", "recovery-required"),
                             ("rolled-back", "rolled-back"), ("cancelled", "cancelled")):
            present = active_rollback(tx, plan) is not None if name == "rollback-request" else read_event(tx, plan, name) is not None
            if present:
                state = status
        return {"transaction_dir": str(tx), "launcher_root": plan["root"], "status": state,
                "version": notice["version"], "version_before": notice["baseline"]["version"],
                "apply_authorization_current": 0 <= time.time() - plan["prepared_at"] <= 1800}


def pending_transactions(launcher_root):
    """Root bootstrap calls this before normal UI initialization; never writes."""
    root, control = _location(launcher_root)
    with Guard() as guard:
        guard.directory(root)
        if not core._exists(control):
            return []
        guard.directory(control)
        result, count = [], 0
        for tx in control.iterdir():
            count += 1
            if count > 256 or not re.fullmatch(r"tx-[0-9a-f]{32}", tx.name):
                raise UpdateError("Unrecognized or excessive launcher transaction storage.")
            core._plain(tx, directory=True)
            if core._exists(tx / "plan.dpapi"):
                summary = describe_transaction(tx)
                if summary["status"] not in {"committed", "rolled-back", "cancelled"}:
                    result.append(summary)
        return result


class ExitBroker:
    """Root-owned bootstrap coordination, NOT the replacement helper.

    Construct in a separate existing host BEFORE asking the UI to exit. The
    kernel process handle stays open until wait() proves that exact object has
    exited. A missing PID is never evidence. Only then may dispatch_helper run.
    """
    def __init__(self, transaction, *, rollback=False):
        self.tx, self.rollback = _path(transaction), rollback
        with Guard() as guard:
            self.plan = read_plan(self.tx, guard)
            self.rollback_request = active_rollback(self.tx, self.plan) if rollback else None
            expected = self.rollback_request["process"] if self.rollback_request is not None else (None if rollback else self.plan["process"])
            if expected is None:
                raise UpdateError("A rollback exit request is required.")
            self.process = ProcessGuard(expected)

    def wait(self, timeout=30, cancel_event=None):
        proof = self.process.wait(timeout, cancel_event)
        with lease(Path(self.plan["root"])), Guard() as guard:
            if read_plan(self.tx, guard) != self.plan:
                raise UpdateError("The launcher plan changed while waiting.")
            if self.rollback and active_rollback(self.tx, self.plan) != self.rollback_request:
                raise UpdateError("The rollback request was cancelled or superseded; this broker has no authority.")
            event = _rollback_event("exit", self.rollback_request["index"]) if self.rollback else "ui-exit"
            prior = read_event(self.tx, self.plan, event)
            if prior is None:
                write_event(self.tx, self.plan, event, proof, guard)
            elif prior != proof:
                raise UpdateError("Conflicting UI exit evidence.")
        return proof

    def close(self):
        self.process.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


def require_exit(tx, plan, *, rollback=False):
    request = active_rollback(tx, plan) if rollback else None
    expected = request["process"] if request is not None else (None if rollback else plan["process"])
    proof = read_event(tx, plan, _rollback_event("exit", request["index"])) if request is not None else (None if rollback else read_event(tx, plan, "ui-exit"))
    if type(proof) is not dict or set(proof) != {"process", "exited"} or proof["process"] != expected:
        raise UpdateError("Verified original UI process exit is required before running the helper.")
    if (type(proof["exited"]) is not str or not re.fullmatch(r"[1-9][0-9]{0,19}", proof["exited"])
            or int(proof["exited"]) < int(expected["created"])):
        raise UpdateError("The UI exit proof is invalid.")


def require_fresh_apply(plan):
    # The generic TUF API authenticates at staging time. This account-bound
    # authorization is deliberately short-lived; recovery has no such timeout.
    if not 0 <= time.time() - plan["prepared_at"] <= 1800:
        raise UpdateError("The staged launcher authorization expired or the clock moved backwards. Cancel and check again.")


def _rollback_event(kind, index):
    return "rollback-" + kind + (f"-{index:04d}" if index else "")


def _rollback_history(tx, plan):
    indices = {0} if read_event(tx, plan, "rollback-request") is not None else set()
    for path in tx.iterdir():
        match = re.fullmatch(r"rollback-(?:request|exit|cancel)-([0-9]{4})\.dpapi", path.name)
        if match:
            indices.add(int(match[1]))
    if len(indices) > 64 or indices and indices != set(range(max(indices) + 1)):
        raise UpdateError("The rollback request history is incomplete or excessive.")
    rows = []
    for index in sorted(indices):
        process = read_event(tx, plan, _rollback_event("request", index))
        _process_shape(process)
        if process["image"].casefold() != str(Path(plan["root"]) / EXE).casefold():
            raise UpdateError("A rollback request came from a different launcher.")
        cancelled = read_event(tx, plan, _rollback_event("cancel", index))
        if index < max(indices) and cancelled is None:
            raise UpdateError("A rollback request was replaced without retained cancellation evidence.")
        rows.append({"index": index, "process": process, "cancelled": cancelled is not None})
    return rows


def active_rollback(tx, plan):
    rows = _rollback_history(tx, plan)
    if rows and not rows[-1]["cancelled"]:
        return {"index": rows[-1]["index"], "process": rows[-1]["process"]}
    return None


def _unstarted_rollback(tx, plan, guard, stack):
    root = Path(plan["root"])
    if (read_event(tx, plan, "committed") is None or read_event(tx, plan, "recovering") is not None
            or read_event(tx, plan, "rolled-back") is not None):
        raise UpdateError("Only an unstarted rollback of the complete committed bundle can be resolved.")
    require_runner_idle(tx, plan)
    _hold_inventory(root, plan["after"], guard, stack, recorded=plan["after"], user_data=True, allow_origin=True)
    return _current_ui(root)


def cancel_rollback(transaction):
    """Current verified updated UI resolves an unstarted request; no fake exit.

    Complete installed inventory + native no-runner scan + transaction lease
    prove no mutator has begun. The old request/exit records remain retained.
    """
    tx = _path(transaction)
    with Guard() as guard:
        plan = read_plan(tx, guard)
        with lease(Path(plan["root"])), contextlib.ExitStack() as stack:
            ui = _unstarted_rollback(tx, plan, guard, stack)
            request = active_rollback(tx, plan)
            if request is None:
                raise UpdateError("There is no unresolved rollback request.")
            write_event(tx, plan, _rollback_event("cancel", request["index"]), {"by": ui, "reason": "cancelled"}, guard)


def request_rollback(transaction):
    """Called from the UPDATED UI before its separate broker observes exit."""
    tx = _path(transaction)
    with Guard() as guard:
        plan = read_plan(tx, guard)
        root = Path(plan["root"])
        with lease(root), contextlib.ExitStack() as stack:
            _pending(tx.parent, guard, except_tx=tx)
            ui = _unstarted_rollback(tx, plan, guard, stack)
            rows, prior = _rollback_history(tx, plan), active_rollback(tx, plan)
            if prior is not None:
                if prior["process"] == ui:
                    raise UpdateError("This UI already requested rollback.")
                write_event(tx, plan, _rollback_event("cancel", prior["index"]), {"by": ui, "reason": "superseded"}, guard)
            index = len(rows)
            if index >= 64:
                raise UpdateError("Too many retained rollback requests; review retained history.")
            write_event(tx, plan, _rollback_event("request", index), ui, guard)
            return {"index": index, "process": ui}


def dispatch_helper(transaction, *, action="apply", attempt=None):
    """Start ONLY the verified retained original runner, AFTER proved UI exit.

    The frozen runner must route --self-update-helper to update_helper.main
    before creating Qt/windows. No configurable executable, shell, elevation,
    working directory or relaunch arguments are accepted. Each attempt is at
    most once. Explicit recovery may retry only after a full native runner scan
    under the serialized transaction lease proves no earlier helper remains.
    """
    import subprocess
    if action not in {"apply", "recover", "rollback"}:
        raise UpdateError("Unsupported launcher helper action.")
    tx = _path(transaction)
    attempt = uuid.uuid4().hex if attempt is None else attempt
    if type(attempt) is not str or not re.fullmatch(r"[0-9a-f]{32}", attempt):
        raise UpdateError("Invalid helper attempt identifier.")
    with Guard() as guard:
        plan = read_plan(tx, guard)
        root = Path(plan["root"])
        with lease(root), contextlib.ExitStack() as stack:
            rollback_started = (read_event(tx, plan, "committed") is not None
                                and read_event(tx, plan, "recovering") is not None)
            require_exit(tx, plan, rollback=action == "rollback" or rollback_started)
            if read_event(tx, plan, "cancelled") is not None:
                raise UpdateError("The launcher transaction was cancelled.")
            if action == "apply":
                require_fresh_apply(plan)
                if any(read_event(tx, plan, e) is not None for e in ("applying", "committed", "rolled-back", "recovering")):
                    raise UpdateError("The launcher helper has already been used; request recovery.")
            require_runner_idle(tx, plan)
            attempts = [p for p in tx.iterdir() if re.fullmatch(r"dispatch-attempt-[0-9a-f]{32}\.dpapi", p.name)]
            if len(attempts) >= 128:
                raise UpdateError("Too many retained helper attempts; review the transaction.")
            runner = tx / "runner"
            _hold_inventory(runner, plan["runner"], guard, stack, recorded=plan["runner"], allow_origin=True)
            event = "dispatch" if action == "apply" else "dispatch-" + action
            if action == "apply" or read_event(tx, plan, event) is None:
                write_event(tx, plan, event, {}, guard)
            rollback = active_rollback(tx, plan) if action == "rollback" or rollback_started else None
            write_event(tx, plan, "dispatch-attempt-" + attempt, {"action": action, "rollback": rollback,
                        "prior_runner_scan": "idle", "created_at": int(time.time())}, guard)
            executable = str(runner / EXE)
            try:
                child = subprocess.Popen([executable, "--self-update-helper", "--transaction", str(tx), "--action", action, "--attempt", attempt],
                    executable=executable, cwd=str(runner), shell=False, close_fds=True,
                    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    creationflags=subprocess.CREATE_NO_WINDOW)
            except OSError:
                write_event(tx, plan, "spawn-failed-" + attempt, {"action": action}, guard)
                raise
            return child.pid


def launch_updated(transaction):
    """Optional broker call after helper completion: exact verified EXE, no args.

    At most once, including an ambiguous spawn/crash. It never launches from
    interrupted or rolled-back state and never accepts a command or arguments.
    """
    import subprocess
    tx = _path(transaction)
    with Guard() as guard:
        plan = read_plan(tx, guard)
        root = Path(plan["root"])
        with lease(root), contextlib.ExitStack() as stack:
            require_exit(tx, plan)
            _pending(tx.parent, guard, except_tx=tx)
            if (read_event(tx, plan, "committed") is None
                    or any(read_event(tx, plan, e) is not None for e in ("cancelled", "rolled-back", "recovering"))
                    or active_rollback(tx, plan) is not None):
                raise UpdateError("Only the completed, verified update can be relaunched.")
            _hold_inventory(root, plan["after"], guard, stack, recorded=plan["after"], user_data=True, allow_origin=True)
            require_stopped(root, plan)
            write_event(tx, plan, "relaunch", {}, guard)
            executable = str(root / EXE)
            child = subprocess.Popen([executable], executable=executable, cwd=str(root), shell=False, close_fds=True,
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return child.pid


def launch_restored(transaction):
    """Launch the exact restored baseline once, with no caller-supplied args.

    Only a rolled-back transaction qualifies. The coordinator additionally
    requires observed successful helper exit before invoking this function.
    An ambiguous spawn remains recorded; do not automatically retry it.
    """
    import subprocess
    tx = _path(transaction)
    with Guard() as guard:
        plan = read_plan(tx, guard)
        root = Path(plan["root"])
        with lease(root), contextlib.ExitStack() as stack:
            require_exit(tx, plan)
            _pending(tx.parent, guard, except_tx=tx)
            if read_event(tx, plan, "rolled-back") is None or read_event(tx, plan, "cancelled") is not None:
                raise UpdateError("Only the completed restored launcher can be relaunched.")
            if read_event(tx, plan, "committed") is not None:
                require_exit(tx, plan, rollback=True)
            _hold_inventory(root, plan["before"], guard, stack, recorded=plan["before"], user_data=True, allow_origin=True)
            require_stopped(root, plan)
            write_event(tx, plan, "relaunch-restored", {}, guard)
            executable = str(root / EXE)
            child = subprocess.Popen([executable], executable=executable, cwd=str(root), shell=False, close_fds=True,
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return child.pid
