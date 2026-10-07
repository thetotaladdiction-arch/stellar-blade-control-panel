"""Small, dependency-free Windows process probes.

The panel polls game state frequently.  Using ``tasklist`` for every poll creates
a console process, parses text, and can momentarily contend with the Qt render
thread.  Toolhelp reads the same information in-process and normally completes
in a few milliseconds without opening a child process.
"""

from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes


TH32CS_SNAPPROCESS = 0x00000002
MAX_PATH = 260


class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("th32DefaultHeapID", ctypes.c_size_t),
        ("th32ModuleID", wintypes.DWORD),
        ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD),
        ("pcPriClassBase", wintypes.LONG),
        ("dwFlags", wintypes.DWORD),
        ("szExeFile", wintypes.WCHAR * MAX_PATH),
    ]


def find_process_id(executable_name: str) -> int | None:
    """Return PID, ``0`` when absent, or ``None`` when probing is unavailable."""

    target = (executable_name or "").strip().casefold()
    if not target:
        return 0
    if sys.platform != "win32":
        return None

    snapshot = None
    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        create_snapshot = kernel32.CreateToolhelp32Snapshot
        create_snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
        create_snapshot.restype = wintypes.HANDLE
        process_first = kernel32.Process32FirstW
        process_first.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
        process_first.restype = wintypes.BOOL
        process_next = kernel32.Process32NextW
        process_next.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
        process_next.restype = wintypes.BOOL

        snapshot = create_snapshot(TH32CS_SNAPPROCESS, 0)
        invalid = ctypes.c_void_p(-1).value
        if not snapshot or int(snapshot) == invalid:
            return None

        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
        if not process_first(snapshot, ctypes.byref(entry)):
            return None
        while True:
            if entry.szExeFile.casefold() == target:
                return int(entry.th32ProcessID)
            if not process_next(snapshot, ctypes.byref(entry)):
                break
        return 0
    except (AttributeError, OSError, TypeError, ValueError):
        return None
    finally:
        if snapshot:
            try:
                ctypes.windll.kernel32.CloseHandle(snapshot)
            except (AttributeError, OSError, ValueError):
                pass


def is_process_running(executable_name: str) -> bool | None:
    """Return process presence, or ``None`` when the native probe is unavailable.

    ``None`` lets callers use a conservative fallback on non-Windows hosts or
    unusually restricted Windows installations. Matching is case-insensitive.
    """

    pid = find_process_id(executable_name)
    return None if pid is None else pid > 0


_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_STILL_ACTIVE = 259
_ERROR_ACCESS_DENIED = 5
_ERROR_INVALID_PARAMETER = 87


def is_pid_alive(pid: int) -> bool | None:
    """Return whether a process id is running, or ``None`` when unknown.

    ``OpenProcess`` fails with ERROR_INVALID_PARAMETER for an id that does not
    exist and ERROR_ACCESS_DENIED for a protected process that does.
    """
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False
    if pid <= 0:
        return False
    if sys.platform != "win32":
        return None
    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        kernel32.GetExitCodeProcess.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL
        handle = kernel32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            error = ctypes.get_last_error()
            if error == _ERROR_INVALID_PARAMETER:
                return False
            if error == _ERROR_ACCESS_DENIED:
                return True
            return None
        try:
            code = wintypes.DWORD()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                return None
            return code.value == _STILL_ACTIVE
        finally:
            kernel32.CloseHandle(handle)
    except (AttributeError, OSError, TypeError, ValueError):
        return None
