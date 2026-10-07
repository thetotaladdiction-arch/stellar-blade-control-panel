"""Replace the small files a native game mod reads while the game runs (A12).

The natives built on sbcore open every panel-written file (God state, Movement
state, Retry Point and Boss Restart commands, the Items lease) with
``FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE``. Python's
``os.replace`` (``MoveFileExW``) still fails with "access denied" while such a
reader holds the destination open; a rename with POSIX semantics
(``FileRenameInfoEx`` with ``REPLACE_IF_EXISTS | POSIX_SEMANTICS``) does not:
the reader keeps the old contents and the next open sees the new file.

A reader that did not allow delete sharing (an older native, an antivirus scan,
the indexer) still blocks both kinds of rename for a moment, so a transient
"access denied" or sharing violation is retried a few times (5 x 20 ms) before
it is reported, exactly as ``os.replace`` would have reported it.

Anything the POSIX rename cannot do (not Windows, a file system without POSIX
rename, a relative path) falls back to ``os.replace``; nothing here is ever
worse than the plain replace it wraps.
"""

from __future__ import annotations

import ctypes
import os
import sys
import time
from pathlib import Path

REPLACE_ATTEMPTS = 5
REPLACE_RETRY_DELAY_SEC = 0.02

_ERROR_ACCESS_DENIED = 5
_ERROR_SHARING_VIOLATION = 32
_TRANSIENT_ERRORS = frozenset({_ERROR_ACCESS_DENIED, _ERROR_SHARING_VIOLATION})

_DELETE = 0x00010000
_SYNCHRONIZE = 0x00100000
_FILE_SHARE_ALL = 0x00000001 | 0x00000002 | 0x00000004
_OPEN_EXISTING = 3
_FILE_ATTRIBUTE_NORMAL = 0x00000080
_FILE_FLAG_OPEN_REPARSE_POINT = 0x00200000
_FILE_RENAME_INFO_EX = 22  # FILE_INFO_BY_HANDLE_CLASS.FileRenameInfoEx
_FILE_RENAME_FLAG_REPLACE_IF_EXISTS = 0x00000001
_FILE_RENAME_FLAG_POSIX_SEMANTICS = 0x00000002


class _PosixRenameUnavailable(Exception):
    """The POSIX rename cannot be used here; the caller falls back."""


if sys.platform == "win32":
    from ctypes import wintypes

    class _FileRenameInfo(ctypes.Structure):
        # union { BOOLEAN ReplaceIfExists; DWORD Flags; }; HANDLE RootDirectory;
        # DWORD FileNameLength; WCHAR FileName[1];  (x64: 0, 8, 16, 20; size 24)
        _fields_ = [
            ("Flags", wintypes.DWORD),
            ("RootDirectory", wintypes.HANDLE),
            ("FileNameLength", wintypes.DWORD),
            ("FileName", wintypes.WCHAR * 1),
        ]

    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _CreateFileW = _kernel32.CreateFileW
    _CreateFileW.argtypes = (
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    )
    _CreateFileW.restype = wintypes.HANDLE
    _SetFileInformationByHandle = _kernel32.SetFileInformationByHandle
    _SetFileInformationByHandle.argtypes = (
        wintypes.HANDLE,
        ctypes.c_int,
        wintypes.LPVOID,
        wintypes.DWORD,
    )
    _SetFileInformationByHandle.restype = wintypes.BOOL
    _CloseHandle = _kernel32.CloseHandle
    _CloseHandle.argtypes = (wintypes.HANDLE,)
    _CloseHandle.restype = wintypes.BOOL
    _INVALID_HANDLE_VALUE = wintypes.HANDLE(-1).value
else:  # pragma: no cover - the panel ships for Windows only
    _FileRenameInfo = None


def _is_absolute_windows_path(text: str) -> bool:
    drive = (
        len(text) >= 3
        and text[0].isalpha()
        and text[1] == ":"
        and text[2] in ("\\", "/")
    )
    unc = text.startswith("\\\\")
    return drive or unc


def _posix_rename(source: Path, target: Path) -> None:
    """Rename ``source`` over ``target`` with POSIX semantics.

    Raises ``PermissionError`` for a transient sharing conflict,
    ``_PosixRenameUnavailable`` for anything the caller should hand to
    ``os.replace`` instead.
    """
    if _FileRenameInfo is None:
        raise _PosixRenameUnavailable("not-windows")
    source_text = os.path.abspath(os.fspath(source))
    target_text = os.path.abspath(os.fspath(target))
    # KernelBase converts FileName as a DOS path; a bare name would resolve
    # against the current directory, so only an absolute path is used.
    if not _is_absolute_windows_path(target_text):
        raise _PosixRenameUnavailable("relative-target")
    handle = _CreateFileW(
        source_text,
        _DELETE | _SYNCHRONIZE,
        _FILE_SHARE_ALL,
        None,
        _OPEN_EXISTING,
        _FILE_ATTRIBUTE_NORMAL | _FILE_FLAG_OPEN_REPARSE_POINT,
        None,
    )
    if handle in (None, 0, _INVALID_HANDLE_VALUE):
        raise _PosixRenameUnavailable(f"open-source-{ctypes.get_last_error()}")
    try:
        encoded = target_text.encode("utf-16-le")
        name_offset = _FileRenameInfo.FileName.offset
        size = ctypes.sizeof(_FileRenameInfo) + len(encoded)
        buffer = ctypes.create_string_buffer(size)
        info = _FileRenameInfo.from_buffer(buffer)
        info.Flags = _FILE_RENAME_FLAG_REPLACE_IF_EXISTS | _FILE_RENAME_FLAG_POSIX_SEMANTICS
        info.RootDirectory = None
        info.FileNameLength = len(encoded)
        ctypes.memmove(ctypes.addressof(buffer) + name_offset, encoded, len(encoded))
        if _SetFileInformationByHandle(handle, _FILE_RENAME_INFO_EX, buffer, size):
            return
        error = ctypes.get_last_error()
    finally:
        _CloseHandle(handle)
    if error in _TRANSIENT_ERRORS:
        raise PermissionError(error, os.strerror(13), os.fspath(target))
    # ERROR_INVALID_PARAMETER / NOT_SUPPORTED / INVALID_FUNCTION (no POSIX
    # rename on this file system) and anything unexpected: plain replace.
    raise _PosixRenameUnavailable(f"rename-{error}")


def replace_file(
    source: Path | str,
    target: Path | str,
    *,
    attempts: int = REPLACE_ATTEMPTS,
    retry_delay: float = REPLACE_RETRY_DELAY_SEC,
) -> None:
    """Atomically replace ``target`` with ``source`` (see the module docstring).

    Raises the last ``PermissionError`` when every attempt met a sharing
    conflict, or whatever ``os.replace`` raises for a real failure.
    """
    source_path = Path(source)
    target_path = Path(target)
    last_error: PermissionError | None = None
    for attempt in range(max(1, int(attempts))):
        if attempt:
            time.sleep(max(0.0, float(retry_delay)))
        try:
            try:
                _posix_rename(source_path, target_path)
                return
            except _PosixRenameUnavailable:
                os.replace(source_path, target_path)
                return
        except PermissionError as exc:
            last_error = exc
    assert last_error is not None
    raise last_error


def write_bytes_replace(path: Path | str, data: bytes, *, durable: bool = False) -> None:
    """Write ``data`` to a new temporary file next to ``path``, then replace.

    The temporary file is created exclusively (never reused), written and
    closed before the rename, so a reader never sees a partial body. ``durable``
    adds an fsync for files that must survive a power cut (panel settings);
    short-lived IPC files (leases, commands) skip it.
    """
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.{os.getpid()}.{time.time_ns()}.tmp")
    try:
        with temporary.open("xb") as stream:
            stream.write(data)
            stream.flush()
            if durable:
                os.fsync(stream.fileno())
        replace_file(temporary, target)
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
