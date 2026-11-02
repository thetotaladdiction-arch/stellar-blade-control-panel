"""Bounded NTFS origin metadata, never content or execution authority.

Only consumers opt in. Markers are opaque: no parsing, URL access, zone trust,
normalization or removal. Unknown/malformed stream sets always refuse. This is
not protection from a malicious same-user process adding a future stream.
"""
from __future__ import annotations

import ctypes as C
from ctypes import wintypes as W

from . import core

MAX_BYTES = core.MAX_ORIGIN_BYTES  # Application quota, not a Windows maximum.
NAME = ":Zone.Identifier:$DATA"
INVALID = C.c_void_p(-1).value


class CleanupError(core.UpdateError):
    """Failed native closes retain their exact handles/closers for recovery."""
    def __init__(self, errors, owner=None, resources=()):
        super().__init__("Origin/file inspection or cleanup failed; partial files were retained.")
        self.errors, self.owner = tuple(errors), owner
        pending, seen, retained = list(errors), set(), list(resources)
        while pending:
            exc = pending.pop()
            if id(exc) in seen:
                continue
            seen.add(id(exc))
            retained.extend(getattr(exc, "resources", ()))
            pending.extend(getattr(exc, "errors", ()))
        self.resources = tuple(dict.fromkeys(retained))


def _kernel():
    k = C.WinDLL("kernel32", use_last_error=True)
    k.FindFirstStreamW.argtypes = [W.LPCWSTR, C.c_int, C.c_void_p, W.DWORD]
    k.FindFirstStreamW.restype = W.HANDLE
    k.FindNextStreamW.argtypes = [W.HANDLE, C.c_void_p]
    k.FindNextStreamW.restype = W.BOOL
    for name in ("CloseHandle", "FindClose", "FlushFileBuffers"):
        fn = getattr(k, name)
        fn.argtypes, fn.restype = [W.HANDLE], W.BOOL
    k.CreateFileW.argtypes = [W.LPCWSTR, W.DWORD, W.DWORD, C.c_void_p, W.DWORD, W.DWORD, W.HANDLE]
    k.CreateFileW.restype = W.HANDLE
    k.GetFileSizeEx.argtypes, k.GetFileSizeEx.restype = [W.HANDLE, C.POINTER(C.c_longlong)], W.BOOL
    k.SetFilePointerEx.argtypes = [W.HANDLE, C.c_longlong, C.POINTER(C.c_longlong), W.DWORD]
    k.SetFilePointerEx.restype = W.BOOL
    for name in ("ReadFile", "WriteFile"):
        fn = getattr(k, name)
        fn.argtypes = [W.HANDLE, C.c_void_p, W.DWORD, C.POINTER(W.DWORD), C.c_void_p]
        fn.restype = W.BOOL
    return k


def _ok(result, message):
    if not result:
        raise core.UpdateError(message) from C.WinError(C.get_last_error())


def _close(k, kind, handle):
    try:
        _ok(getattr(k, kind)(handle), "An origin inspection handle could not be closed.")
    except BaseException as exc:
        raise CleanupError([exc], resources=[(kind, handle)]) from exc


def inspect(path, *, allow_origin=False):
    """Exact bounded stream set. EOF is success; every other error refuses."""
    class Data(C.Structure):
        _fields_ = [("size", C.c_longlong), ("name", W.WCHAR * 296)]
    k, data = _kernel(), Data()
    h = k.FindFirstStreamW(str(path), 0, C.byref(data), 0)
    if h in (None, INVALID):
        raise core.UpdateError("Cannot inspect file streams.") from C.WinError(C.get_last_error())
    seen, marker_size = set(), None
    try:
        while True:
            name, size = data.name.casefold(), data.size
            if (name in seen or name not in {"::$data", NAME.casefold()}
                    or size < 0 or name == NAME.casefold() and (not allow_origin or size > MAX_BYTES)):
                raise core.UpdateError("Unsupported, malformed, or oversized file data streams.")
            seen.add(name)
            if name == NAME.casefold():
                marker_size = size
            if not k.FindNextStreamW(h, C.byref(data)):
                if C.get_last_error() != 38:
                    raise core.UpdateError("File stream inspection did not finish successfully.")
                break
        if "::$data" not in seen:
            raise core.UpdateError("The ordinary file data stream is missing.")
        return marker_size
    finally:
        _close(k, "FindClose", h)


def _same_file(base, handle):
    k = core._kernel()
    before, other = core._FileIdInfo(), core._FileIdInfo()
    info = core._FileInfo()
    _ok(k.GetFileInformationByHandleEx(base.handle, 18, C.byref(before), C.sizeof(before)), "Cannot identify base file.")
    _ok(k.GetFileInformationByHandleEx(handle, 18, C.byref(other), C.sizeof(other)), "Cannot identify origin stream.")
    _ok(k.GetFileInformationByHandle(handle, C.byref(info)), "Cannot inspect origin stream identity.")
    if ((before.volume, bytes(before.file_id)) != (other.volume, bytes(other.file_id))
            or info.attributes & (0x400 | 0x10) or info.links != 1):
        raise core.UpdateError("Origin metadata is not on the exact held ordinary file.")
    base.assert_name()


def _read(k, handle):
    size = C.c_longlong()
    _ok(k.GetFileSizeEx(handle, C.byref(size)), "Cannot size origin metadata.")
    if not 0 <= size.value <= MAX_BYTES:
        raise core.UpdateError("Origin metadata exceeds its supported quota.")
    _ok(k.SetFilePointerEx(handle, 0, None, 0), "Cannot seek origin metadata.")
    buf, count = C.create_string_buffer(MAX_BYTES + 1), W.DWORD()
    _ok(k.ReadFile(handle, buf, len(buf), C.byref(count), None), "Cannot read origin metadata.")
    if count.value != size.value:
        raise core.UpdateError("Origin metadata changed or could not be read completely.")
    return buf.raw[:count.value]


def _stream_path(base):
    # The base has passed ordinary-path/identity gates. Internal extended syntax
    # accommodates the stream suffix without silently shrinking the 240-char
    # supported base-path limit or relying on machine long-path policy.
    return "\\\\?\\" + str(base.path) + NAME


class Lease:
    def __init__(self, base, *, allow_origin=False):
        self.base, self.allow_origin, self.k = base, allow_origin, _kernel()
        self.handle, self.raw = None, None
        try:
            size = inspect(base.path, allow_origin=allow_origin)
            if size is not None:
                self._open()
                self.raw = _read(self.k, self.handle)
                if len(self.raw) != size:
                    raise core.UpdateError("Origin metadata changed while acquiring its lease.")
            self.check()
        except BaseException as exc:
            try:
                self.close(check=False)
            except BaseException as close_exc:
                raise CleanupError([exc, close_exc], self) from close_exc
            raise

    def _open(self):
        # Sharing is PER STREAM. Deny writers, allow same-file handle rename.
        h = self.k.CreateFileW(_stream_path(self.base), 0x80000000, 5, None, 3, 0x00200000, None)
        if h in (None, INVALID):
            raise core.UpdateError("Cannot hold origin metadata against writes.") from C.WinError(C.get_last_error())
        self.handle = h
        _same_file(self.base, h)

    def check(self):
        self.base.assert_name()
        size = inspect(self.base.path, allow_origin=self.allow_origin)
        if (size is None) != (self.raw is None):
            raise core.UpdateError("Origin metadata appeared or disappeared while held.")
        if self.handle is not None:
            _same_file(self.base, self.handle)
            if size != len(self.raw) or _read(self.k, self.handle) != self.raw:
                raise core.UpdateError("Origin metadata changed while held.")

    def inherit(self, raw):
        """One explicit NEW metadata stream on a held NEW consumer destination."""
        self.check()
        if raw is None:
            return
        if (not self.allow_origin or self.raw is not None or not self.base.created
                or type(raw) is not bytes or len(raw) > MAX_BYTES):
            raise core.UpdateError("Origin inheritance requires a new compatible consumer file.")
        h = self.k.CreateFileW(_stream_path(self.base), 0xC0000000, 5, None, 1, 0x80200000, None)
        if h in (None, INVALID):
            raise core.UpdateError("Cannot exclusively create destination origin metadata.") from C.WinError(C.get_last_error())
        try:
            _same_file(self.base, h)
            data, count = C.create_string_buffer(raw), W.DWORD()
            _ok(self.k.WriteFile(h, data, len(raw), C.byref(count), None), "Origin metadata write failed.")
            if count.value != len(raw):
                raise core.UpdateError("Origin metadata was only partially written.")
            _ok(self.k.FlushFileBuffers(h), "Origin metadata flush failed.")
            if _read(self.k, h) != raw:
                raise core.UpdateError("Origin metadata failed writer readback.")
        finally:
            # Failure retains h in CleanupError; no unmarked success fallback.
            _close(self.k, "CloseHandle", h)
        # Writer CLOSE precedes final timestamp/fingerprint and read lease.
        self._open()
        self.raw = _read(self.k, self.handle)
        if self.raw != raw:
            raise core.UpdateError("Origin metadata changed during writer handoff.")
        self.check()

    def close(self, *, check=True):
        errors = []
        if check:
            try:
                self.check()
            except BaseException as exc:
                errors.append(exc)
        if self.handle is not None:
            try:
                _close(self.k, "CloseHandle", self.handle)
                self.handle = None
            except BaseException as exc:
                errors.append(exc)
        if errors:
            raise CleanupError(errors, self) from errors[0]
