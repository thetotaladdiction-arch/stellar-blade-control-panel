from __future__ import annotations

import csv
import ctypes
import math
import queue
import statistics
import struct
import subprocess
import sys
import threading
import time
from collections import deque
from ctypes import wintypes
from functools import lru_cache
from pathlib import Path

from PySide6.QtCore import QObject, Property, QTimer, Signal, Slot

from controllers.telemetry_levels import (
    LEVEL_CRIT,
    CpuTempLimits,
    TelemetryLevels,
    cpu_temp_limits,
    read_cpu_name,
)
from infrastructure.screen_geometry import Rect, resolve_qt_placement


RTSS_SIGNATURE = 0x52545353
MAHM_SIGNATURE = 0x4D41484D
FILE_MAP_READ = 0x0004
MEM_COMMIT = 0x1000
PAGE_NOACCESS = 0x01
PAGE_GUARD = 0x100
MAX_SHARED_MAPPING_BYTES = 64 * 1024 * 1024
INVALID_FLOAT = 3.0e38
FAST_TELEMETRY_POLL_MS = 100
NORMAL_TELEMETRY_POLL_MS = 750
CPU_SENSOR_STALE_AFTER_SECONDS = 5.0
FRAME_SENSOR_STALE_AFTER_SECONDS = 2.5
PRESENTMON_STATS_WINDOW_SECONDS = 12.0
# Optional temperature alerts (off by default) never repeat sooner than this.
HARDWARE_ALERT_MIN_INTERVAL_SECONDS = 600.0
# While the game is closed, sensors are read only for the Support page.
DIAGNOSTICS_TELEMETRY_POLL_MS = 1000

GPU_SENSOR_KEYS = {
    "gpu_usage", "gpu_temp", "gpu_power", "gpu_clock", "gpu_fan", "vram_mb",
}
HARDWARE_ONLY_EXCLUDED_KEYS = {
    "source", "poll_time", "fallback_fps", "fallback_frame_ms",
    "one_percent_low", "point_one_percent_low",
}
FRAME_VALUE_KEYS = {
    "fps", "average_fps", "frame_time_ms", "instant_frame_time_ms",
    "min_fps", "stat_average_fps", "max_fps", "one_percent_low",
    "point_one_percent_low", "gpu_active_ms", "gpu_frame_ms",
    "gpu_frame_label", "present_latency_ms", "present_mode", "api", "resolution_x",
    "resolution_y", "process_ram_mb", "process_vram_mb", "sample_id",
    "frame_times_ms",
}
FRAME_STATE_KEYS = FRAME_VALUE_KEYS | {
    "source", "process_name", "frame_sample_age_ms", "frame_sample_fresh",
    "stutters", "pacing_deviation_ms", "live",
}


def telemetry_poll_interval_ms(overlay_active: bool, process_id: int) -> int:
    """Use the fluid HUD cadence only while there is a game to observe."""
    return (
        FAST_TELEMETRY_POLL_MS
        if overlay_active and int(process_id or 0) > 0
        else NORMAL_TELEMETRY_POLL_MS
    )


def telemetry_polling_wanted(process_id: int, diagnostics_active: bool) -> bool:
    """Sensors are read only while a game runs or the Support page shows them."""
    return int(process_id or 0) > 0 or bool(diagnostics_active)


def summarize_frame_history(frame_times_ms: list[float]) -> tuple[list[float], float, float]:
    """Return the graph window and full-buffer 1%/0.1% low estimates.

    RTSS exposes up to 1024 samples.  The HUD graph only needs 180, while low
    percentiles benefit from the full sample.  Sort the full buffer once and
    derive both lows from that ordering.
    """
    recent = list(frame_times_ms[-180:])
    if not frame_times_ms:
        return recent, 0.0, 0.0
    slowest_first = sorted(frame_times_ms, reverse=True)

    def low_fps(fraction: float) -> float:
        count = max(1, math.ceil(len(slowest_first) * fraction))
        mean_slow = statistics.fmean(slowest_first[:count])
        return 1000.0 / mean_slow if mean_slow > 0 else 0.0

    return recent, low_fps(0.01), low_fps(0.001)


def _row_number(row: dict, *names: str) -> float:
    for name in names:
        value = row.get(name)
        if value not in (None, ""):
            try:
                parsed = float(value)
                return parsed if _finite(parsed) else 0.0
            except (TypeError, ValueError):
                continue
    return 0.0


def summarize_presentmon_rows(
    rows: list[dict],
    *,
    now: float | None = None,
    stale_after_seconds: float = FRAME_SENSOR_STALE_AFTER_SECONDS,
) -> dict | None:
    """Build PID-attributed frame metrics from fresh PresentMon rows.

    The raw intervals feed the graph, pacing deviation, stutter detector and
    low-percentile calculations.  A previously captured row is never allowed
    to remain a plausible-looking live FPS value after the stream stops.
    """
    if not rows:
        return None
    now = time.monotonic() if now is None else float(now)
    latest = rows[-1]
    received_at = float(latest.get("_received_at", now) or now)
    age_seconds = max(0.0, now - received_at)
    if age_seconds > max(0.1, float(stale_after_seconds)):
        return None

    intervals = [
        _row_number(row, "msBetweenPresents", "MsBetweenPresents")
        for row in rows
    ]
    intervals = [value for value in intervals if 0.05 <= value <= 1000.0]
    if not intervals:
        return None

    recent, one_low, point_one_low = summarize_frame_history(intervals)
    mean_ms = statistics.fmean(recent)
    overall_mean_ms = statistics.fmean(intervals)
    gpu_active_ms = _row_number(latest, "msGPUActive", "MsGPUActive")
    snapshot: dict[str, float | int | str | bool | list[float]] = {
        "source": "PresentMon",
        "fps": 1000.0 / mean_ms if mean_ms > 0 else 0.0,
        "average_fps": 1000.0 / overall_mean_ms if overall_mean_ms > 0 else 0.0,
        "frame_time_ms": mean_ms,
        "instant_frame_time_ms": recent[-1],
        "min_fps": 1000.0 / max(intervals),
        "stat_average_fps": 1000.0 / overall_mean_ms if overall_mean_ms > 0 else 0.0,
        "max_fps": 1000.0 / min(intervals),
        "one_percent_low": one_low,
        "point_one_percent_low": point_one_low,
        "present_latency_ms": _row_number(latest, "msUntilDisplayed", "MsUntilDisplayed"),
        "present_mode": latest.get("PresentMode", ""),
        "api": latest.get("Runtime", ""),
        "sample_id": latest.get("QPCTime", latest.get("TimeInSeconds", len(rows))),
        "frame_times_ms": recent,
        "frame_sample_age_ms": age_seconds * 1000.0,
        "frame_sample_fresh": True,
        "gpu_frame_label": "GPU active",
    }
    # msBetweenPresents is total CPU/present interval, not GPU frame time.
    # PresentMon's closest supported GPU contribution is msGPUActive.
    if gpu_active_ms > 0:
        snapshot["gpu_active_ms"] = gpu_active_ms
        snapshot["gpu_frame_ms"] = gpu_active_ms
    return snapshot


def advance_frame_freshness(
    sample_key,
    previous_key,
    previous_progress_at: float | None,
    now: float,
    *,
    stale_after_seconds: float = FRAME_SENSOR_STALE_AFTER_SECONDS,
) -> tuple[object, float, bool, float]:
    """Track whether a frame source is advancing, independent of poll rate."""
    now = float(now)
    if sample_key != previous_key or previous_progress_at is None:
        previous_key = sample_key
        previous_progress_at = now
    age = max(0.0, now - float(previous_progress_at))
    return previous_key, float(previous_progress_at), age <= stale_after_seconds, age


def capture_row_matches(row: dict, process_id: int, generation: int) -> bool:
    """Reject rows left behind by a stopped capture or a previous game PID."""
    try:
        return (
            int(row.get("_capture_pid", -1)) == int(process_id)
            and int(row.get("_capture_generation", -1)) == int(generation)
        )
    except (TypeError, ValueError):
        return False


def merge_hardware_snapshots(afterburner: dict, nvml: dict, pdh: dict) -> dict:
    """Merge sensors per metric so a partial NVML read has safe fallbacks."""
    hardware: dict[str, float | int | str | bool] = {}
    valid_zero_keys = {"cpu_usage", "gpu_usage", "gpu_fan"}
    for key, value in afterburner.items():
        if key in {"source", "poll_time"}:
            continue
        if key in GPU_SENSOR_KEYS and key in nvml and nvml.get(key) is not None:
            continue
        if isinstance(value, (int, float)) and value == 0 and key not in valid_zero_keys:
            continue
        hardware[key] = value
    hardware.update({
        key: value for key, value in nvml.items()
        if key != "source" and value is not None
    })
    hardware.update(pdh)
    return hardware


def merge_frame_and_hardware(frame: dict | None, hardware: dict | None) -> dict:
    """Combine telemetry without misattributing global MAHM FPS to the game."""
    values = dict(frame or {})
    if hardware:
        for key, value in hardware.items():
            if key not in HARDWARE_ONLY_EXCLUDED_KEYS:
                values[key] = value
    return values


def remove_frame_values(values: dict, *, keep_source_state: bool = True) -> dict:
    excluded = FRAME_VALUE_KEYS if keep_source_state else FRAME_STATE_KEYS
    return {key: value for key, value in values.items() if key not in excluded}


def _finite(value: float | int | None) -> bool:
    try:
        return math.isfinite(float(value)) and abs(float(value)) < INVALID_FLOAT
    except (TypeError, ValueError, OverflowError):
        return False


def _decode_c_string(data: bytes) -> str:
    raw = data.split(b"\0", 1)[0]
    try:
        return raw.decode("mbcs", errors="replace")
    except LookupError:
        return raw.decode("utf-8", errors="replace")


class _MemoryBasicInformation(ctypes.Structure):
    _fields_ = [
        ("BaseAddress", ctypes.c_void_p),
        ("AllocationBase", ctypes.c_void_p),
        ("AllocationProtect", wintypes.DWORD),
        ("RegionSize", ctypes.c_size_t),
        ("State", wintypes.DWORD),
        ("Protect", wintypes.DWORD),
        ("Type", wintypes.DWORD),
    ]


def _mapping_view(name: str):
    """Return a validated read-only mapping view and its accessible byte size."""
    if sys.platform != "win32":
        return None, None, None, 0
    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenFileMappingW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
        kernel32.OpenFileMappingW.restype = wintypes.HANDLE
        kernel32.MapViewOfFile.argtypes = [
            wintypes.HANDLE,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.DWORD,
            ctypes.c_size_t,
        ]
        kernel32.MapViewOfFile.restype = ctypes.c_void_p
        kernel32.VirtualQuery.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(_MemoryBasicInformation),
            ctypes.c_size_t,
        ]
        kernel32.VirtualQuery.restype = ctypes.c_size_t
        handle = kernel32.OpenFileMappingW(FILE_MAP_READ, False, name)
        if not handle:
            return None, None, None, 0
        pointer = kernel32.MapViewOfFile(handle, FILE_MAP_READ, 0, 0, 0)
        if not pointer:
            kernel32.CloseHandle(handle)
            return None, None, None, 0

        info = _MemoryBasicInformation()
        queried = kernel32.VirtualQuery(
            ctypes.c_void_p(pointer), ctypes.byref(info), ctypes.sizeof(info)
        )
        base = int(info.BaseAddress or 0)
        view_pointer = int(pointer)
        region_size = int(info.RegionSize or 0)
        bytes_remaining = (base + region_size) - view_pointer
        readable = (
            queried == ctypes.sizeof(info)
            and info.State == MEM_COMMIT
            and not (info.Protect & (PAGE_GUARD | PAGE_NOACCESS))
            and base <= view_pointer < base + region_size
            and 0 < bytes_remaining <= MAX_SHARED_MAPPING_BYTES
        )
        if not readable:
            kernel32.UnmapViewOfFile(ctypes.c_void_p(pointer))
            kernel32.CloseHandle(handle)
            return None, None, None, 0
        return kernel32, handle, view_pointer, bytes_remaining
    except (AttributeError, OSError, TypeError, ValueError):
        return None, None, None, 0


def _close_mapping(kernel32, handle, pointer) -> None:
    if not kernel32:
        return
    try:
        if pointer:
            kernel32.UnmapViewOfFile(ctypes.c_void_p(pointer))
        if handle:
            kernel32.CloseHandle(handle)
    except (AttributeError, OSError, TypeError, ValueError):
        pass


def read_rtss_snapshot(process_id: int) -> dict | None:
    """Read RTSS' live per-process frame counters without writing to its OSD."""
    kernel32, handle, pointer, view_size = _mapping_view("RTSSSharedMemoryV2")
    if not pointer:
        return None
    try:
        if view_size < 96:
            return None
        mapped = ctypes.string_at(pointer, view_size)
        header = mapped[:96]
        signature, version, entry_size, array_offset, array_size = struct.unpack_from("<5I", header, 0)
        if signature != RTSS_SIGNATURE or version < 0x00020000:
            return None
        if not (320 <= entry_size <= 65536 and 0 < array_size <= 4096):
            return None
        if array_offset < 96 or array_size > (view_size - array_offset) // entry_size:
            return None
        perf_entry_size, perf_array_offset = struct.unpack_from("<II", header, 72)
        for index in range(array_size):
            base = array_offset + index * entry_size
            entry = mapped[base:base + entry_size]
            if len(entry) != entry_size:
                return None
            pid = struct.unpack_from("<I", entry, 0)[0]
            if pid != int(process_id):
                continue
            name = _decode_c_string(entry[4:264])
            flags, time0, time1, frames, frame_us = struct.unpack_from("<5I", entry, 264)
            instant_fps = 1_000_000.0 / frame_us if frame_us else 0.0
            averaged_fps = 1000.0 * frames / (time1 - time0) if time1 > time0 and frames else 0.0

            def dword(offset: int, default: int = 0) -> int:
                if offset + 4 > len(entry):
                    return default
                return struct.unpack_from("<I", entry, offset)[0]

            def valid_fps(value: int) -> float:
                return float(value) if value not in (0, 0xFFFFFFFF) and value < 10000 else 0.0

            frame_times_ms: list[float] = []
            if len(entry) >= 5028:
                buffer_count = min(1024, dword(920))
                buffer_pos = dword(5020) % 1024
                raw_buffer = list(struct.unpack_from("<1024I", entry, 924))
                ordered_buffer = raw_buffer[buffer_pos:] + raw_buffer[:buffer_pos]
                if buffer_count < 1024:
                    ordered_buffer = ordered_buffer[-buffer_count:]
                frame_times_ms = [value / 1000.0 for value in ordered_buffer if 50 <= value <= 1_000_000]

            recent_times, calculated_one_low, calculated_point_one_low = summarize_frame_history(
                frame_times_ms
            )
            mean_frame_ms = statistics.fmean(recent_times) if recent_times else (
                1000.0 / averaged_fps if averaged_fps > 0 else frame_us / 1000.0
            )
            fps = 1000.0 / mean_frame_ms if mean_frame_ms > 0 else instant_fps

            native_one_low = valid_fps(dword(9176))
            native_point_one_low = valid_fps(dword(9180))
            snapshot = {
                "source": "RTSS",
                "process_name": name,
                "fps": fps,
                "average_fps": averaged_fps,
                "frame_time_ms": mean_frame_ms,
                "instant_frame_time_ms": frame_us / 1000.0 if frame_us else 0.0,
                "min_fps": (1000.0 / max(frame_times_ms)) if frame_times_ms else valid_fps(dword(304)),
                "stat_average_fps": (1000.0 / statistics.fmean(frame_times_ms)) if frame_times_ms else valid_fps(dword(308)),
                "max_fps": (1000.0 / min(frame_times_ms)) if frame_times_ms else valid_fps(dword(312)),
                "one_percent_low": native_one_low or calculated_one_low,
                "point_one_percent_low": native_point_one_low or calculated_point_one_low,
                "resolution_x": dword(9224),
                "resolution_y": dword(9228),
                "gpu_active_ms": dword(9336) / 1000.0,
                "gpu_frame_ms": dword(9340) / 1000.0,
                "gpu_frame_label": "GPU frame",
                "api": {
                    1: "OpenGL", 2: "DirectDraw", 3: "D3D8", 4: "D3D9",
                    5: "D3D9Ex", 6: "D3D10", 7: "D3D11", 8: "D3D12",
                    9: "D3D12 AFR", 10: "Vulkan",
                }.get(flags & 0xFFFF, ""),
                "process_ram_mb": 0.0,
                "process_vram_mb": 0.0,
                "sample_id": (time1, frames, frame_us, dword(5020)),
                "frame_times_ms": recent_times,
            }

            counter_count = min(256, dword(9196))
            if perf_entry_size >= 12 and perf_array_offset + counter_count * perf_entry_size <= entry_size:
                for counter_index in range(counter_count):
                    offset = perf_array_offset + counter_index * perf_entry_size
                    counter_id, _param, data = struct.unpack_from("<III", entry, offset)
                    # RTSS exposes these values in KiB.
                    if counter_id == 0x00000001:
                        snapshot["process_ram_mb"] = data / 1024.0
                    elif counter_id == 0x00000100:
                        snapshot["process_vram_mb"] += data / 1024.0
            post_header = ctypes.string_at(pointer, 96)
            if post_header[:20] != header[:20] or post_header[72:80] != header[72:80]:
                return None
            return snapshot
        return None
    except (OSError, TypeError, ValueError, struct.error):
        return None
    finally:
        _close_mapping(kernel32, handle, pointer)


def read_afterburner_snapshot() -> dict | None:
    """Read optional hardware sensors exposed by MSI Afterburner shared memory."""
    kernel32, handle, pointer, view_size = _mapping_view("MAHMSharedMemory")
    if not pointer:
        return None
    try:
        if view_size < 32:
            return None
        mapped = ctypes.string_at(pointer, view_size)
        header = mapped[:32]
        signature, version, header_size, count, entry_size, poll_time, _gpu_count, _gpu_size = struct.unpack(
            "<8I", header
        )
        if signature != MAHM_SIGNATURE or version < 0x00020000:
            return None
        if not (32 <= header_size <= view_size and 1324 <= entry_size <= 65536 and 0 <= count <= 4096):
            return None
        if count > (view_size - header_size) // entry_size:
            return None

        entries: list[dict] = []
        for index in range(count):
            offset = header_size + index * entry_size
            raw = mapped[offset:offset + entry_size]
            if len(raw) != entry_size:
                return None
            value = struct.unpack_from("<f", raw, 1300)[0]
            _flags, gpu, source_id = struct.unpack_from("<III", raw, 1312)
            if not _finite(value):
                continue
            entries.append({
                "name": _decode_c_string(raw[0:260]),
                "units": _decode_c_string(raw[260:520]),
                "value": float(value),
                "gpu": gpu,
                "source_id": source_id,
            })

        def values(source_id: int, *, gpu: int | None = None) -> list[float]:
            return [
                row["value"] for row in entries
                if row["source_id"] == source_id and (gpu is None or row["gpu"] == gpu)
            ]

        gpu_ids = sorted({row["gpu"] for row in entries if row["gpu"] != 0xFFFFFFFF})
        selected_gpu = None
        if gpu_ids:
            selected_gpu = max(
                gpu_ids,
                # A discrete render adapter normally exposes framebuffer usage
                # and/or a fan counter. Prefer that identity over board power:
                # on hybrid systems the integrated-GPU row can contain CPU
                # package power and otherwise win the old heuristic at idle.
                key=lambda gpu: (
                    bool(values(0x32, gpu=gpu)),
                    bool(values(0x10, gpu=gpu)),
                    max(values(0x31, gpu=gpu) or [0.0]),
                    max(values(0x30, gpu=gpu) or [0.0]),
                ),
            )

        def first(source_id: int, *, gpu: int | None = None, mode: str = "first") -> float:
            found = values(source_id, gpu=gpu)
            if not found:
                return 0.0
            if mode == "max":
                return max(found)
            if mode == "avg":
                return statistics.fmean(found)
            return found[0]

        def cpu_temperature_sensor() -> tuple[float, str, str]:
            """Select a named Celsius CPU sensor, never an ID-only guess."""
            candidates = []
            for row in entries:
                if row["source_id"] != 0x80:
                    continue
                name = str(row["name"] or "").strip()
                units = str(row["units"] or "").strip().lower().replace("°", "")
                value = float(row["value"])
                lowered = name.lower()
                if "cpu" not in lowered or "temp" not in lowered:
                    continue
                if units not in {"c", "celsius"} or not 10.0 <= value <= 115.0:
                    continue
                candidates.append(row)
            if not candidates:
                return 0.0, "", "unavailable"

            # MSI Afterburner's documented global CPU temperature has GPU index
            # 0xFFFFFFFF. If only per-core counters exist, use the hottest core
            # and label it honestly instead of presenting it as package data.
            global_rows = [row for row in candidates if row["gpu"] == 0xFFFFFFFF]
            if global_rows:
                selected = max(global_rows, key=lambda row: row["value"])
                return float(selected["value"]), str(selected["name"]), "global"
            selected = max(candidates, key=lambda row: row["value"])
            return float(selected["value"]), str(selected["name"]), "hottest_core"

        global_gpu = selected_gpu if selected_gpu is not None else None
        cpu_usage = first(0x90, gpu=0xFFFFFFFF)
        if not cpu_usage:
            cpu_usage = first(0x90, mode="avg")
        cpu_temp, cpu_temp_sensor, cpu_temp_kind = cpu_temperature_sensor()
        cpu_clock = first(0xA0, gpu=0xFFFFFFFF)
        if not cpu_clock:
            cpu_clock = first(0xA0, mode="avg")
        snapshot = {
            "source": "MSI Afterburner",
            "poll_time": poll_time,
            "gpu_usage": first(0x30, gpu=global_gpu, mode="max"),
            "gpu_temp": first(0x00, gpu=global_gpu, mode="max"),
            "gpu_power": first(0x61, gpu=global_gpu, mode="max"),
            "gpu_clock": first(0x20, gpu=global_gpu, mode="max"),
            "gpu_fan": first(0x10, gpu=global_gpu, mode="max"),
            "vram_mb": first(0x31, gpu=global_gpu, mode="max"),
            "cpu_usage": cpu_usage,
            "cpu_temp": cpu_temp,
            "cpu_temp_sensor": cpu_temp_sensor,
            "cpu_temp_kind": cpu_temp_kind,
            "cpu_power": first(0x100, gpu=0xFFFFFFFF),
            "cpu_clock": cpu_clock,
            "ram_mb": first(0x91, gpu=0xFFFFFFFF),
            "fallback_fps": first(0x50, gpu=0xFFFFFFFF),
            "fallback_frame_ms": first(0x51, gpu=0xFFFFFFFF),
            "one_percent_low": first(0x55, gpu=0xFFFFFFFF),
            "point_one_percent_low": first(0x56, gpu=0xFFFFFFFF),
        }
        post_header = ctypes.string_at(pointer, 32)
        if post_header != header:
            return None
        return snapshot
    except (OSError, TypeError, ValueError, struct.error):
        return None
    finally:
        _close_mapping(kernel32, handle, pointer)


NVML_CLOCK_REASON_NAMES = {
    0x0000000000000001: "GPU idle",
    0x0000000000000002: "application clocks",
    0x0000000000000004: "software power cap",
    0x0000000000000008: "hardware slowdown",
    0x0000000000000010: "sync boost",
    0x0000000000000020: "software thermal slowdown",
    0x0000000000000040: "hardware thermal slowdown",
    0x0000000000000080: "hardware power brake",
    0x0000000000000100: "display clock setting",
}
NVML_THERMAL_REASON_MASK = 0x20 | 0x40
NVML_LIMIT_REASON_MASK = 0x2 | 0x4 | 0x8 | 0x10 | 0x20 | 0x40 | 0x80


class NvmlMonitor:
    """Persistent NVML session bound to one stable high-memory NVIDIA GPU."""

    class Utilization(ctypes.Structure):
        _fields_ = [("gpu", ctypes.c_uint), ("memory", ctypes.c_uint)]

    class Memory(ctypes.Structure):
        _fields_ = [
            ("total", ctypes.c_ulonglong),
            ("free", ctypes.c_ulonglong),
            ("used", ctypes.c_ulonglong),
        ]

    def __init__(self):
        self.library = None
        self.handle = None
        self.index = -1
        self.name = ""
        self.total_memory = 0
        if sys.platform != "win32":
            return
        for candidate in (
            "nvml.dll",
            r"C:\Windows\System32\nvml.dll",
            r"C:\Program Files\NVIDIA Corporation\NVSMI\nvml.dll",
        ):
            try:
                self.library = ctypes.WinDLL(candidate)
                break
            except OSError:
                continue
        if self.library is None:
            return
        try:
            if self.library.nvmlInit_v2() != 0:
                self.library = None
                return
            count = ctypes.c_uint()
            if self.library.nvmlDeviceGetCount_v2(ctypes.byref(count)) != 0:
                self.shutdown()
                return
            candidates: list[tuple[int, int, ctypes.c_void_p, str]] = []
            for index in range(count.value):
                handle = ctypes.c_void_p()
                if self.library.nvmlDeviceGetHandleByIndex_v2(index, ctypes.byref(handle)) != 0:
                    continue
                memory = self.Memory()
                total = 0
                if self.library.nvmlDeviceGetMemoryInfo(handle, ctypes.byref(memory)) == 0:
                    total = int(memory.total)
                buffer = ctypes.create_string_buffer(128)
                name = f"NVIDIA GPU {index}"
                try:
                    if self.library.nvmlDeviceGetName(handle, buffer, len(buffer)) == 0:
                        name = buffer.value.decode("utf-8", errors="replace")
                except (AttributeError, OSError):
                    pass
                candidates.append((total, index, handle, name))
            if not candidates:
                self.shutdown()
                return
            total, index, handle, name = max(candidates, key=lambda row: (row[0], -row[1]))
            self.handle = handle
            self.index = index
            self.name = name
            self.total_memory = total
        except (AttributeError, OSError, TypeError, ValueError):
            self.shutdown()

    def _uint(self, function_name: str, *arguments, scale: float = 1.0) -> float | None:
        if self.library is None or self.handle is None:
            return None
        try:
            value = ctypes.c_uint()
            function = getattr(self.library, function_name)
            if function(self.handle, *arguments, ctypes.byref(value)) != 0:
                return None
            return float(value.value) / scale
        except (AttributeError, OSError, TypeError, ValueError):
            return None

    def _clock_reasons(self) -> tuple[int | None, int | None]:
        if self.library is None or self.handle is None:
            return None, None

        def query(names: tuple[str, ...]) -> int | None:
            for name in names:
                try:
                    function = getattr(self.library, name)
                    value = ctypes.c_ulonglong()
                    if function(self.handle, ctypes.byref(value)) == 0:
                        return int(value.value)
                except (AttributeError, OSError, TypeError, ValueError):
                    continue
            return None

        current = query((
            "nvmlDeviceGetCurrentClocksEventReasons",
            "nvmlDeviceGetCurrentClocksThrottleReasons",
        ))
        supported = query((
            "nvmlDeviceGetSupportedClocksEventReasons",
            "nvmlDeviceGetSupportedClocksThrottleReasons",
        ))
        return current, supported

    def snapshot(self) -> dict | None:
        if self.library is None or self.handle is None:
            return None
        values: dict[str, float | int | str | bool] = {
            "source": "NVML",
            "gpu_name": self.name,
            "gpu_index": self.index,
        }
        try:
            utilization = self.Utilization()
            if self.library.nvmlDeviceGetUtilizationRates(self.handle, ctypes.byref(utilization)) == 0:
                values["gpu_usage"] = float(utilization.gpu)
                values["gpu_memory_usage"] = float(utilization.memory)
            memory = self.Memory()
            if self.library.nvmlDeviceGetMemoryInfo(self.handle, ctypes.byref(memory)) == 0:
                values["vram_mb"] = memory.used / (1024.0 * 1024.0)
                values["vram_total_mb"] = memory.total / (1024.0 * 1024.0)

            for key, function, args, scale in (
                ("gpu_temp", "nvmlDeviceGetTemperature", (0,), 1.0),
                ("gpu_power", "nvmlDeviceGetPowerUsage", (), 1000.0),
                ("gpu_clock", "nvmlDeviceGetClockInfo", (0,), 1.0),
                ("gpu_fan", "nvmlDeviceGetFanSpeed", (), 1.0),
            ):
                reading = self._uint(function, *args, scale=scale)
                if reading is not None:
                    values[key] = reading

            for key, threshold_type in (
                ("gpu_shutdown_temp", 0),
                ("gpu_slowdown_temp", 1),
                ("gpu_max_temp", 3),
            ):
                reading = self._uint("nvmlDeviceGetTemperatureThreshold", threshold_type)
                if reading is not None:
                    values[key] = reading

            current, supported = self._clock_reasons()
            if current is not None:
                active_names = [
                    label for mask, label in NVML_CLOCK_REASON_NAMES.items()
                    if current & mask
                ]
                limiting_names = [
                    label for mask, label in NVML_CLOCK_REASON_NAMES.items()
                    if current & mask & NVML_LIMIT_REASON_MASK
                ]
                values["gpu_clock_reason_mask"] = current
                values["gpu_clock_reasons"] = ", ".join(active_names) or "None"
                values["gpu_throttle_active"] = bool(current & NVML_LIMIT_REASON_MASK)
                values["gpu_thermal_throttle"] = bool(current & NVML_THERMAL_REASON_MASK)
                values["gpu_throttle_status"] = ", ".join(limiting_names) or "No performance limit"
            if supported is not None:
                values["gpu_supported_reason_mask"] = supported
            values["hardware_sample_time"] = time.time()
            return values
        except (AttributeError, OSError, TypeError, ValueError):
            return None

    def shutdown(self) -> None:
        library = self.library
        self.library = None
        self.handle = None
        if library is not None:
            try:
                library.nvmlShutdown()
            except (AttributeError, OSError, TypeError, ValueError):
                pass


def read_nvml_snapshot() -> dict | None:
    """One-shot compatibility helper used by diagnostics and unit tests."""
    monitor = NvmlMonitor()
    try:
        return monitor.snapshot()
    finally:
        monitor.shutdown()


def is_process_foreground(process_id: int) -> bool:
    """Return whether the foreground window belongs to the target process.

    This deliberately avoids window enumeration so it is cheap enough to run
    at the overlay's 10 Hz cadence.  Keeping focus fresher than the slower
    geometry poll prevents a topmost HUD from lingering over another app after
    Alt-Tab.
    """
    if sys.platform != "win32" or not process_id:
        return False
    try:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        foreground = user32.GetForegroundWindow()
        if not foreground:
            return False
        foreground_pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(foreground, ctypes.byref(foreground_pid))
        return foreground_pid.value == int(process_id)
    except (AttributeError, OSError, TypeError, ValueError):
        return False


def find_process_window(process_id: int) -> tuple[int, int, int, int, bool]:
    """Largest visible, non-minimized window of the process in PHYSICAL pixels.

    Callers must map the rectangle with ``infrastructure.screen_geometry``
    before handing it to Qt, which positions windows in logical pixels.
    """
    if sys.platform != "win32" or not process_id:
        return 0, 0, 0, 0, False
    try:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        rect = wintypes.RECT()
        best = [0, 0, 0, 0]

        @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        def callback(hwnd, _lparam):
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if (pid.value != int(process_id)
                    or not user32.IsWindowVisible(hwnd)
                    or user32.IsIconic(hwnd)):
                return True
            if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
                return True
            width = rect.right - rect.left
            height = rect.bottom - rect.top
            if width * height > max(0, (best[2] - best[0]) * (best[3] - best[1])):
                best[:] = [rect.left, rect.top, rect.right, rect.bottom]
            return True

        user32.EnumWindows(callback, 0)
        return *best, is_process_foreground(process_id)
    except (AttributeError, OSError, TypeError, ValueError):
        return 0, 0, 0, 0, False


@lru_cache(maxsize=1)
def read_system_memory_total_mb() -> float:
    """Installed physical capacity, cached once rather than polled with sensors."""
    if sys.platform != "win32":
        return 0.0
    try:
        installed_kb = ctypes.c_ulonglong()
        read_capacity = ctypes.WinDLL("kernel32", use_last_error=True).GetPhysicallyInstalledSystemMemory
        read_capacity.argtypes = [ctypes.POINTER(ctypes.c_ulonglong)]
        read_capacity.restype = wintypes.BOOL
        if read_capacity(ctypes.byref(installed_kb)):
            return installed_kb.value / 1024.0
    except (AttributeError, OSError, TypeError, ValueError):
        pass
    return 0.0


def read_system_memory_used_mb() -> float:
    if sys.platform != "win32":
        return 0.0
    try:
        class MemoryStatus(ctypes.Structure):
            _fields_ = [
                ("dwLength", wintypes.DWORD),
                ("dwMemoryLoad", wintypes.DWORD),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]
        status = MemoryStatus()
        status.dwLength = ctypes.sizeof(MemoryStatus)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            return (status.ullTotalPhys - status.ullAvailPhys) / (1024.0 * 1024.0)
    except (AttributeError, OSError, TypeError, ValueError):
        pass
    return 0.0


def read_cpu_times() -> tuple[int, int] | None:
    """Return (idle, total) 100-ns ticks for low-cost CPU usage deltas."""
    if sys.platform != "win32":
        return None
    try:
        idle = wintypes.FILETIME()
        kernel = wintypes.FILETIME()
        user = wintypes.FILETIME()
        if not ctypes.windll.kernel32.GetSystemTimes(
            ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user)
        ):
            return None

        def ticks(value) -> int:
            return (int(value.dwHighDateTime) << 32) | int(value.dwLowDateTime)

        return ticks(idle), ticks(kernel) + ticks(user)
    except (AttributeError, OSError, TypeError, ValueError):
        return None


class _PdhValueUnion(ctypes.Union):
    _fields_ = [
        ("longValue", ctypes.c_long),
        ("doubleValue", ctypes.c_double),
        ("largeValue", ctypes.c_longlong),
    ]


class _PdhFormattedValue(ctypes.Structure):
    _fields_ = [("status", wintypes.DWORD), ("value", _PdhValueUnion)]


class PdhPerformanceLimitMonitor:
    """Read Windows CPU performance-limit counters without a subprocess."""

    PDH_FMT_LONG = 0x00000100
    PDH_FMT_DOUBLE = 0x00000200

    def __init__(self):
        self.library = None
        self.query = ctypes.c_void_p()
        self.counters: dict[str, ctypes.c_void_p] = {}
        if sys.platform != "win32":
            return
        try:
            library = ctypes.WinDLL("pdh.dll")
            if library.PdhOpenQueryW(None, 0, ctypes.byref(self.query)) != 0:
                return
            self.library = library
            for key, path in (
                ("cpu_performance_limit_percent", r"\Processor Information(_Total)\% Performance Limit"),
                ("cpu_performance_limit_flags", r"\Processor Information(_Total)\Performance Limit Flags"),
                ("cpu_windows_frequency", r"\Processor Information(_Total)\Processor Frequency"),
            ):
                counter = ctypes.c_void_p()
                if library.PdhAddEnglishCounterW(self.query, path, 0, ctypes.byref(counter)) == 0:
                    self.counters[key] = counter
            library.PdhCollectQueryData(self.query)
        except (AttributeError, OSError, TypeError, ValueError):
            self.shutdown()

    def _value(self, key: str, format_flag: int) -> float | int | None:
        if self.library is None or key not in self.counters:
            return None
        try:
            value = _PdhFormattedValue()
            result = self.library.PdhGetFormattedCounterValue(
                self.counters[key], format_flag, None, ctypes.byref(value)
            )
            if result != 0 or value.status != 0:
                return None
            if format_flag == self.PDH_FMT_LONG:
                return int(value.value.longValue)
            return float(value.value.doubleValue)
        except (AttributeError, OSError, TypeError, ValueError):
            return None

    def snapshot(self) -> dict:
        if self.library is None or not self.query:
            return {}
        try:
            if self.library.PdhCollectQueryData(self.query) != 0:
                return {}
        except (AttributeError, OSError, TypeError, ValueError):
            return {}
        percent = self._value("cpu_performance_limit_percent", self.PDH_FMT_DOUBLE)
        flags = self._value("cpu_performance_limit_flags", self.PDH_FMT_LONG)
        frequency = self._value("cpu_windows_frequency", self.PDH_FMT_DOUBLE)
        result: dict[str, float | int | str | bool] = {}
        if percent is not None and _finite(percent):
            result["cpu_performance_limit_percent"] = max(0.0, min(100.0, float(percent)))
        if flags is not None:
            result["cpu_performance_limit_flags"] = int(flags)
        if frequency is not None and _finite(frequency):
            result["cpu_windows_frequency"] = max(0.0, float(frequency))
        if percent is not None or flags is not None:
            limited = (percent is not None and float(percent) < 99.5) or bool(flags)
            result["cpu_performance_limited"] = limited
            result["cpu_limit_status"] = (
                f"Limited to {float(percent):.0f}% (flags 0x{int(flags or 0):X})"
                if limited and percent is not None
                else (f"Limit flags 0x{int(flags or 0):X}" if limited else "No performance limit")
            )
        return result

    def shutdown(self) -> None:
        library = self.library
        query = self.query
        self.library = None
        self.query = ctypes.c_void_p()
        self.counters.clear()
        if library is not None and query:
            try:
                library.PdhCloseQuery(query)
            except (AttributeError, OSError, TypeError, ValueError):
                pass


def cpu_temperature_label(values: dict) -> str:
    """Describe the CPU sensor without promoting a fallback to package/global."""
    kind = str(values.get("cpu_temp_kind") or "").strip().casefold()
    if kind == "hottest_core":
        return "CPU hottest core"
    if kind == "global":
        return "CPU global temp"
    sensor = str(values.get("cpu_temp_sensor") or "").strip()
    return sensor or "CPU temperature"


_HARDWARE_WARNING_SEVERITY = {
    "OK": 0,
    "STALE": 1,
    "LIMITED": 2,
    "WARM": 2,
    "HOT": 3,
    "CRITICAL": 4,
}


class HardwareWarningLimiter:
    """At most one optional hardware alert per ``cooldown_seconds``.

    Repeated "CRITICAL" toasts every minute are noisy, so nothing
    bypasses the interval, not even an escalation: one quiet notice, then at
    least ten minutes of silence.
    """

    def __init__(
        self,
        cooldown_seconds: float = HARDWARE_ALERT_MIN_INTERVAL_SECONDS,
        recovery_seconds: float = 10.0,
    ):
        self.cooldown_seconds = max(HARDWARE_ALERT_MIN_INTERVAL_SECONDS, float(cooldown_seconds))
        self.recovery_seconds = max(1.0, float(recovery_seconds))
        self._last_emit_at = float("-inf")

    def should_emit(self, level: str, now: float) -> bool:
        severity = _HARDWARE_WARNING_SEVERITY.get(str(level or "OK").upper(), 0)
        now = float(now)
        if severity <= 0:
            return False
        if now - self._last_emit_at < self.cooldown_seconds:
            return False
        self._last_emit_at = now
        return True


def evaluate_hardware_health(values: dict, cpu_limits: CpuTempLimits | None = None) -> dict[str, str | bool]:
    """Classify fresh sensor values without inventing a throttle cause.

    CPU words follow the CPU's own limits (``cpu_limits``, the HUD colours):
    WARM from amber, HOT from red, CRITICAL at its maximum (TjMax).
    """
    limits = cpu_limits or CpuTempLimits()
    cpu_temp = float(values.get("cpu_temp") or 0.0)
    cpu_fresh = bool(values.get("cpu_sample_fresh", True))
    cpu_label = cpu_temperature_label(values)
    gpu_temp = float(values.get("gpu_temp") or 0.0)
    gpu_max = float(values.get("gpu_max_temp") or 0.0)
    gpu_slowdown = float(values.get("gpu_slowdown_temp") or 0.0)
    cpu_limited = bool(values.get("cpu_performance_limited", False))
    gpu_limited = bool(values.get("gpu_throttle_active", False))
    gpu_thermal = bool(values.get("gpu_thermal_throttle", False))

    level = "OK"
    details: list[str] = []
    if cpu_temp > 0 and not cpu_fresh:
        level = "STALE"
        details.append(f"{cpu_label} sample is stale")
    elif cpu_temp >= limits.tjmax:
        level = "CRITICAL"
        details.append(f"{cpu_label} {cpu_temp:.0f} C")
    elif cpu_temp >= limits.crit:
        level = "HOT"
        details.append(f"{cpu_label} {cpu_temp:.0f} C")
    elif cpu_temp >= limits.warn:
        level = "WARM"
        details.append(f"{cpu_label} {cpu_temp:.0f} C")

    if gpu_thermal or (gpu_slowdown > 0 and gpu_temp >= gpu_slowdown):
        level = "CRITICAL"
        details.append("GPU thermal slowdown active")
    elif gpu_max > 0 and gpu_temp >= gpu_max:
        if level not in {"CRITICAL", "HOT"}:
            level = "HOT"
        details.append(f"GPU at maximum operating threshold ({gpu_temp:.0f} C)")
    elif gpu_max > 0 and gpu_temp >= gpu_max - 5:
        if level == "OK":
            level = "WARM"
        details.append(f"GPU near maximum threshold ({gpu_temp:.0f} C)")

    if cpu_limited:
        details.append(str(values.get("cpu_limit_status") or "CPU performance limited"))
    if gpu_limited:
        details.append(str(values.get("gpu_throttle_status") or "GPU clock limit active"))
    if (cpu_limited or gpu_limited) and level in {"OK", "STALE"}:
        level = "LIMITED"
    if not details:
        details.append("Temperatures and performance-limit flags are normal")
    return {
        "hardware_health_level": level,
        "hardware_health_text": "; ".join(details),
        "hardware_performance_limited": cpu_limited or gpu_limited,
        "cpu_temp_label": cpu_label,
    }


def telemetry_source_summary(game_running: bool, frame: dict | None, hardware: dict | None,
                             frame_error: str, frame_stopped: bool) -> str:
    """Name only reported sources and keep frame failures visible beside sensors."""
    parts = []
    if hardware and hardware.get("source"):
        parts.append("Sensors: " + str(hardware["source"]))
    if not game_running:
        parts.append("Game closed; frame readings unavailable")
    elif frame and frame.get("frame_sample_fresh", True) and frame.get("source"):
        parts.append("Frames: " + str(frame["source"]))
    elif frame_error:
        parts.append("Frame counter: " + frame_error)
    elif frame and not frame.get("frame_sample_fresh", True):
        parts.append("Frame readings stopped")
    elif frame_stopped:
        parts.append("Frame counter stopped; waiting to restart")
    else:
        parts.append("Waiting for game frame readings")
    return "; ".join(parts)


def hardware_limit_summary(values: dict) -> str:
    """Translate reported flags without diagnosing an unknown underlying cause."""
    parts = []
    if "gpu_clock_reason_mask" in values:
        mask = int(values["gpu_clock_reason_mask"])
        labels = {0x2: "configured clock limit", 0x4: "configured power cap", 0x8: "hardware slowdown (cause not reported)",
                  0x10: "clock synchronization limit", 0x20: "temperature limit", 0x40: "hardware temperature limit",
                  0x80: "hardware power limit (cause not reported)"}
        names = [name for bit, name in labels.items() if mask & bit]
        unknown = mask & ~(0x1 | 0x100 | sum(labels))
        if unknown:
            names.append("additional limit flags (cause not reported)")
        parts.append("GPU: " + (", ".join(names) or "no performance limit reported"))
    if "cpu_performance_limited" in values:
        percent = values.get("cpu_performance_limit_percent")
        detail = "no performance limit reported"
        if values["cpu_performance_limited"]:
            detail = (f"performance limited to {float(percent):.0f}%" if percent is not None else "performance limit reported")
            detail += "; cause not reported"
        parts.append("CPU: " + detail)
    return " · ".join(parts) or "No reading yet"


class GameTelemetryController(QObject):
    """Low-overhead game telemetry for the independent in-game HUD."""

    changed = Signal()
    hardwareWarning = Signal(str, str)

    def __init__(self, presentmon_path: Path | None = None, parent=None):
        super().__init__(parent)
        self._presentmon_path = Path(presentmon_path) if presentmon_path else None
        self._process_id = 0
        self._overlay_active = False
        self._values: dict[str, float | int | str | bool] = {}
        self._source = "Waiting for Stellar Blade"
        self._live = False
        self._history: deque[float] = deque(maxlen=180)
        self._stutters = 0
        self._last_sample_id = None
        self._last_frame_progress_key = None
        self._last_frame_progress_at: float | None = None
        self._reset_window_geometry()
        self._game_foreground = False
        self._last_window_poll = 0.0
        self._last_cpu_times = read_cpu_times()
        self._hardware_cache = None
        self._last_hardware_poll = 0.0
        self._afterburner_poll_time: int | None = None
        self._afterburner_sample_monotonic = 0.0
        self._afterburner_sample_time = 0.0
        self._nvml_monitor = NvmlMonitor()
        self._pdh_monitor = PdhPerformanceLimitMonitor()
        self._thermal_history: deque[tuple[float, float, float, str]] = deque(maxlen=60)
        self._warning_limiter = HardwareWarningLimiter()
                                                                                           
        self._cpu_limits = cpu_temp_limits(read_cpu_name())
        self._levels = TelemetryLevels(self._cpu_limits)
        self._alerts_enabled = False
        self._diagnostics_active = False
        self._presentmon_process = None
        self._presentmon_thread = None
        self._presentmon_pid = 0
        self._presentmon_failed_pid = 0
        self._presentmon_retry_after = 0.0
        self._presentmon_failure_count = 0
        self._presentmon_generation = 0
        self._presentmon_error = ""
        self._presentmon_queue: queue.Queue[dict] = queue.Queue(maxsize=4096)
        self._presentmon_dropped_rows = 0
        self._presentmon_frames: deque[dict] = deque(maxlen=3000)
        self._timer = QTimer(self)
        self._timer.setInterval(NORMAL_TELEMETRY_POLL_MS)
        self._timer.timeout.connect(self._poll)
        # Idle until a game runs or the Support page asks for sensor values:
        # a closed game has nothing to observe, so no timer ticks at all.
        self._update_timer()

    def _update_timer(self) -> None:
        if not telemetry_polling_wanted(self._process_id, self._diagnostics_active):
            self._timer.stop()
            return
        if self._process_id:
            interval = telemetry_poll_interval_ms(self._overlay_active, self._process_id)
        else:
            interval = DIAGNOSTICS_TELEMETRY_POLL_MS
        if self._timer.interval() != interval:
            self._timer.setInterval(interval)
        if not self._timer.isActive():
            self._timer.start()

    def set_diagnostics_active(self, active: bool) -> None:
        """The Support page shows sensor values; poll slowly while it is open."""
        active = bool(active)
        if active == self._diagnostics_active:
            return
        self._diagnostics_active = active
        was_idle = not self._timer.isActive()
        self._update_timer()
        if active and was_idle:
            self._poll()

    def set_alerts_enabled(self, enabled: bool) -> None:
        """Optional, user-enabled temperature notices (default off)."""
        self._alerts_enabled = bool(enabled)

    def poll_once(self) -> None:
        """Refresh the values once, e.g. before writing a support report."""
        self._poll()

    def set_target_process(self, process_id: int) -> None:
        process_id = max(0, int(process_id or 0))
        if process_id == self._process_id:
            return
        self._stop_presentmon()
        self._process_id = process_id
        self._levels.reset()
        self._update_timer()
        self._presentmon_failed_pid = 0
        self._presentmon_retry_after = 0.0
        self._presentmon_failure_count = 0
        self._presentmon_error = ""
        self._presentmon_dropped_rows = 0
        self._history.clear()
        self._stutters = 0
        self._last_sample_id = None
        self._last_frame_progress_key = None
        self._last_frame_progress_at = None
        self._reset_window_geometry()
        self._game_foreground = False
        # Keep independent CPU/GPU monitoring alive, but never carry frame
        # values across a process restart (PID changes can happen without an
        # observed game-closed interval).
        self._values = remove_frame_values(self._values, keep_source_state=False)
        self._values.pop("source_summary", None)
        if not process_id:
            self._source = "Hardware monitoring (game closed)"
            self._live = False
        else:
            self._source = "Waiting for Stellar Blade frame telemetry"
            self._live = False
        self.changed.emit()

    def _clear_presentmon_queue(self) -> None:
        while True:
            try:
                self._presentmon_queue.get_nowait()
            except queue.Empty:
                return

    def _stop_presentmon(self) -> None:
        self._presentmon_generation += 1
        process = self._presentmon_process
        thread = self._presentmon_thread
        self._presentmon_process = None
        self._presentmon_thread = None
        self._presentmon_pid = 0
        self._presentmon_frames.clear()
        self._clear_presentmon_queue()
        if process is not None:
            try:
                process.terminate()
            except (OSError, ProcessLookupError):
                pass
            try:
                process.wait(timeout=0.25)
            except subprocess.TimeoutExpired:
                try:
                    process.kill()
                except (OSError, ProcessLookupError):
                    pass
            except (OSError, ProcessLookupError):
                pass
        if thread is not None and thread is not threading.current_thread() and thread.is_alive():
            thread.join(timeout=0.25)

    def _ensure_presentmon(self) -> None:
        if not self._overlay_active or not self._process_id:
            return
        if self._presentmon_pid == self._process_id and self._presentmon_thread is not None:
            if self._presentmon_thread.is_alive():
                return
        if (
            self._presentmon_failed_pid == self._process_id
            and time.monotonic() < self._presentmon_retry_after
        ):
            return
        if not self._presentmon_path or not self._presentmon_path.is_file():
            self._presentmon_failed_pid = self._process_id
            self._presentmon_error = "PresentMon executable is unavailable"
            self._presentmon_retry_after = time.monotonic() + 30.0
            return

        target_pid = self._process_id
        self._presentmon_generation += 1
        generation = self._presentmon_generation
        command = [
            str(self._presentmon_path),
            "-process_id", str(target_pid),
            "-output_stdout",
            "-no_top",
            "-qpc_time_s",
            "-track_gpu",
            "-terminate_on_proc_exit",
            "-session_name", f"SBCheatGUI_{target_pid}",
            "-stop_existing_session",
        ]

        def capture() -> None:
            header = None
            process = None

            def enqueue(payload: dict) -> None:
                payload["_capture_pid"] = target_pid
                payload["_capture_generation"] = generation
                try:
                    self._presentmon_queue.put_nowait(payload)
                except queue.Full:
                    try:
                        self._presentmon_queue.get_nowait()
                    except queue.Empty:
                        pass
                    self._presentmon_dropped_rows += 1
                    try:
                        self._presentmon_queue.put_nowait(payload)
                    except queue.Full:
                        self._presentmon_dropped_rows += 1

            try:
                process = subprocess.Popen(
                    command,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    bufsize=1,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                if (
                    generation != self._presentmon_generation
                    or target_pid != self._process_id
                    or not self._overlay_active
                ):
                    process.terminate()
                    try:
                        process.wait(timeout=0.25)
                    except subprocess.TimeoutExpired:
                        process.kill()
                    return
                self._presentmon_process = process
                if process.stdout is None:
                    raise RuntimeError("PresentMon did not expose a data stream")
                for raw in process.stdout:
                    line = raw.strip()
                    if not line:
                        continue
                    if line.startswith("Application,"):
                        header = next(csv.reader([line]))
                        continue
                    if header is not None and "," in line:
                        fields = next(csv.reader([line]))
                        if len(fields) == len(header):
                            row = dict(zip(header, fields))
                            row["_received_at"] = time.monotonic()
                            enqueue(row)
                            continue
                    if "access denied" in line.casefold() or line.casefold().startswith("error:"):
                        enqueue({"_error": line})
                code = process.wait()
                if code and target_pid == self._process_id and generation == self._presentmon_generation:
                    enqueue({"_error": f"PresentMon exited with code {code}"})
            except Exception as exc:
                if target_pid == self._process_id and generation == self._presentmon_generation:
                    enqueue({"_error": str(exc)})
            finally:
                if process is not None and self._presentmon_process is process:
                    self._presentmon_process = None

        self._presentmon_pid = target_pid
        self._presentmon_thread = threading.Thread(
            target=capture,
            name="SBCheatGUI-PresentMon",
            daemon=True,
        )
        self._presentmon_thread.start()

    @staticmethod
    def _row_float(row: dict, *names: str) -> float:
        return _row_number(row, *names)

    def _presentmon_snapshot(self) -> dict | None:
        had_error = False
        while True:
            try:
                row = self._presentmon_queue.get_nowait()
            except queue.Empty:
                break
            if not capture_row_matches(row, self._process_id, self._presentmon_generation):
                continue
            if "_error" in row:
                had_error = True
                detail = str(row.get("_error") or "PresentMon capture failed").strip()
                lowered = detail.casefold()
                self._presentmon_error = (
                    "PresentMon access denied; add this user to Performance Log Users"
                    if "access denied" in lowered or "privilege" in lowered
                    else f"PresentMon: {detail[:180]}"
                )
                self._presentmon_failed_pid = self._process_id
                self._presentmon_failure_count += 1
                delay = min(30.0, float(2 ** min(self._presentmon_failure_count, 4)))
                self._presentmon_retry_after = time.monotonic() + delay
            else:
                self._presentmon_frames.append(row)
                self._presentmon_failed_pid = 0
                self._presentmon_failure_count = 0
                self._presentmon_retry_after = 0.0
                self._presentmon_error = ""
        if had_error:
            self._stop_presentmon()

        now = time.monotonic()
        while (
            self._presentmon_frames
            and now - float(self._presentmon_frames[0].get("_received_at", now))
            > PRESENTMON_STATS_WINDOW_SECONDS
        ):
            self._presentmon_frames.popleft()
        return summarize_presentmon_rows(list(self._presentmon_frames), now=now)

    def _reset_window_geometry(self) -> None:
        self._window_left = self._window_top = self._window_right = self._window_bottom = 0
        self._screen_left = self._screen_top = self._screen_right = self._screen_bottom = 0
        self._raw_window = (0, 0, 0, 0)
        self._game_screen_name = ""
        self._game_monitor_dpi = 0
        self._game_screen_scale = 1.0
        self._geometry_dirty = True

    def _map_window_geometry(self, left: int, top: int, right: int, bottom: int) -> tuple[int, int, int, int]:
        """Return the game's window rectangle in Qt logical coordinates.

        Also records the logical geometry of the screen that shows the game
        (for clamping and ``Window.screen``) plus raw values for diagnostics.
        Geometry that cannot be tied to a screen is reported as empty, so the
        HUD hides instead of guessing a position on the wrong monitor.
        """
        raw = (int(left), int(top), int(right), int(bottom))
        placement = None
        if raw[2] > raw[0] and raw[3] > raw[1]:
            placement, _screen = resolve_qt_placement(Rect(*raw))
        if placement is None:
            logical = (0, 0, 0, 0)
            screen = (0, 0, 0, 0)
            name = ""
            dpi = 0
            scale = 1.0
        else:
            window = placement.window
            screen_rect = placement.screen
            logical = (window.left, window.top, window.right, window.bottom)
            screen = (screen_rect.left, screen_rect.top, screen_rect.right, screen_rect.bottom)
            name = placement.screen_name
            dpi = int(placement.dpi)
            scale = float(placement.scale)
        previous = (
            self._raw_window,
            (self._screen_left, self._screen_top, self._screen_right, self._screen_bottom),
            self._game_screen_name,
            self._game_monitor_dpi,
            self._game_screen_scale,
        )
        if (raw, screen, name, dpi, scale) != previous:
            self._geometry_dirty = True
        self._raw_window = raw
        self._screen_left, self._screen_top, self._screen_right, self._screen_bottom = screen
        self._game_screen_name = name
        self._game_monitor_dpi = dpi
        self._game_screen_scale = scale
        return logical

    def set_overlay_active(self, active: bool) -> None:
        active = bool(active)
        if active == self._overlay_active:
            return
        self._overlay_active = active
        # Ten updates per second are useful only while the HUD has a live game.
        # An enabled-but-idle overlay returns to the normal cadence.
        self._update_timer()
        if not active:
            self._stop_presentmon()

    @Slot()
    def _poll(self) -> None:
        now = time.monotonic()
        frame = None
        if self._process_id:
            if now - self._last_window_poll >= 0.45 or not self._window_right:
                raw_left, raw_top, raw_right, raw_bottom, foreground = find_process_window(self._process_id)
                self._last_window_poll = now
                # Win32 reports physical pixels; QML positions windows in Qt
                # logical pixels of the screen that shows the game.
                left, top, right, bottom = self._map_window_geometry(
                    raw_left, raw_top, raw_right, raw_bottom
                )
            else:
                left, top, right, bottom, foreground = (
                    self._window_left,
                    self._window_top,
                    self._window_right,
                    self._window_bottom,
                    self._game_foreground,
                )
            # Geometry changes slowly and is intentionally sampled less often,
            # but focus must be current: this controls whether the topmost HUD
            # may appear at all.  Refresh it on every overlay telemetry tick.
            foreground = is_process_foreground(self._process_id)
            frame = read_rtss_snapshot(self._process_id)
            if frame:
                self._stop_presentmon()
            else:
                self._ensure_presentmon()
                frame = self._presentmon_snapshot()
        else:
            self._stop_presentmon()
            left, top, right, bottom = self._map_window_geometry(0, 0, 0, 0)
            foreground = False

        if self._hardware_cache is None or now - self._last_hardware_poll >= 0.9:
            afterburner = read_afterburner_snapshot() or {}
            nvml = self._nvml_monitor.snapshot() or {}
            pdh = self._pdh_monitor.snapshot()
            afterburner_poll_time = int(afterburner.get("poll_time") or 0)
            has_cpu_temperature = float(afterburner.get("cpu_temp") or 0.0) > 0
            if has_cpu_temperature:
                # MAHM's poll marker advances only when Afterburner publishes a
                # new sensor set. Track it independently from the always-fresh
                # NVML timestamp so a frozen CPU reading cannot look current.
                if not afterburner_poll_time or afterburner_poll_time != self._afterburner_poll_time:
                    self._afterburner_poll_time = afterburner_poll_time or None
                    self._afterburner_sample_monotonic = now
                    self._afterburner_sample_time = time.time()

            # Prefer NVML per metric, while retaining an Afterburner fallback
            # for individual readings an NVML driver does not expose.
            hardware = merge_hardware_snapshots(afterburner, nvml, pdh)
            if has_cpu_temperature and self._afterburner_sample_monotonic > 0:
                cpu_sample_age = max(0.0, now - self._afterburner_sample_monotonic)
                hardware.update({
                    "cpu_sample_time": self._afterburner_sample_time,
                    "cpu_sample_age_ms": cpu_sample_age * 1000.0,
                    "cpu_sample_fresh": cpu_sample_age <= CPU_SENSOR_STALE_AFTER_SECONDS,
                    "cpu_sample_poll_time": afterburner_poll_time,
                })
            hardware.update(evaluate_hardware_health(hardware, self._cpu_limits))
            sources = [
                name for name in (
                    nvml.get("source"),
                    afterburner.get("source"),
                    "Windows PDH" if pdh else "",
                ) if name
            ]
            if hardware:
                hardware["source"] = " + ".join(dict.fromkeys(sources)) or "System"
                hardware["hardware_sample_time"] = float(
                    hardware.get("hardware_sample_time") or time.time()
                )
                cpu_temp = float(hardware.get("cpu_temp") or 0.0)
                gpu_temp = float(hardware.get("gpu_temp") or 0.0)
                level = str(hardware.get("hardware_health_level") or "OK")
                self._thermal_history.append((time.time(), cpu_temp, gpu_temp, level))
            self._hardware_cache = hardware or None
            self._last_hardware_poll = now
        hardware = self._hardware_cache
        if frame:
            progress_key = (str(frame.get("source") or ""), frame.get("sample_id"))
            (
                self._last_frame_progress_key,
                self._last_frame_progress_at,
                frame_fresh,
                frame_age,
            ) = advance_frame_freshness(
                progress_key,
                self._last_frame_progress_key,
                self._last_frame_progress_at,
                now,
            )
            frame["frame_sample_fresh"] = frame_fresh
            frame["frame_sample_age_ms"] = frame_age * 1000.0
            if not frame_fresh:
                frame = remove_frame_values(frame)
                self._history.clear()
                self._stutters = 0
        elif (
            self._process_id
            and self._last_frame_progress_at is not None
            and now - self._last_frame_progress_at > FRAME_SENSOR_STALE_AFTER_SECONDS
        ):
            self._history.clear()
            self._stutters = 0

        values: dict[str, float | int | str | bool] = merge_frame_and_hardware(frame, hardware)

        if not values.get("ram_mb"):
            values["ram_mb"] = read_system_memory_used_mb()
        values["ram_total_mb"] = read_system_memory_total_mb()
        sample_time = float(values.get("hardware_sample_time") or 0.0)
        if sample_time > 0:
            values["hardware_sample_age_ms"] = max(0.0, (time.time() - sample_time) * 1000.0)
        cpu_times = read_cpu_times()
        if cpu_times and self._last_cpu_times and "cpu_usage" not in values:
            idle_delta = max(0, cpu_times[0] - self._last_cpu_times[0])
            total_delta = max(0, cpu_times[1] - self._last_cpu_times[1])
            if total_delta:
                values["cpu_usage"] = max(0.0, min(100.0, 100.0 * (total_delta - idle_delta) / total_delta))
        self._last_cpu_times = cpu_times

        # Smoothed numbers and latched colour levels (hysteresis + hold time).
        values.update(self._levels.update(values, now))
        if self._alerts_enabled and self._process_id:
            self._maybe_alert(values, now)

        source_parts = []
        if frame:
            source_parts.append(str(frame.get("source") or "Frame source"))
        if hardware:
            source_parts.append(str(hardware.get("source") or "Hardware sensors"))
        source = " + ".join(source_parts) if source_parts else (
            self._presentmon_error or "Frame source unavailable"
        )
        live = bool(
            self._process_id
            and values.get("frame_sample_fresh", True)
            and values.get("fps")
            and float(values.get("fps", 0.0)) > 0
        )

        sample_id = values.get("sample_id")
        frame_samples = values.pop("frame_times_ms", None)
        frame_ms = float(values.get("instant_frame_time_ms", values.get("frame_time_ms", 0.0)) or 0.0)
        if frame_samples:
            self._history = deque((float(value) for value in frame_samples[-180:]), maxlen=180)
            baseline = statistics.median(frame_samples)
            self._stutters = sum(
                1 for value in frame_samples
                if value > max(50.0, baseline * 2.5)
            )
            self._last_sample_id = sample_id
        elif live and frame_ms > 0 and sample_id != self._last_sample_id:
            baseline = statistics.median(self._history) if len(self._history) >= 12 else frame_ms
            if len(self._history) >= 12 and frame_ms > max(50.0, baseline * 2.5):
                self._stutters += 1
            self._history.append(frame_ms)
            self._last_sample_id = sample_id

        values["stutters"] = self._stutters
        values["pacing_deviation_ms"] = statistics.pstdev(self._history) if len(self._history) >= 2 else 0.0
        values["source_summary"] = telemetry_source_summary(
            bool(self._process_id), frame, hardware, self._presentmon_error,
            bool(self._process_id and not self._presentmon_process and not frame))
        values["source"] = source
        values["live"] = live
        values["presentmon_dropped_rows"] = self._presentmon_dropped_rows

        changed = (
            values != self._values
            or source != self._source
            or live != self._live
            or self._geometry_dirty
            or (left, top, right, bottom, foreground)
            != (self._window_left, self._window_top, self._window_right, self._window_bottom, self._game_foreground)
        )
        self._geometry_dirty = False
        self._values = values
        self._source = source
        self._live = live
        self._window_left, self._window_top, self._window_right, self._window_bottom = left, top, right, bottom
        self._game_foreground = foreground
        if changed:
            self.changed.emit()

    def _maybe_alert(self, values: dict, now: float) -> None:
        """Optional notice when a temperature stays critical (>= 5 s)."""
        if self._levels.temperature_alert_level() != LEVEL_CRIT:
            return
        if not self._warning_limiter.should_emit("CRITICAL", now):
            return
        parts = []
        if values.get("level_cpu_temp") == LEVEL_CRIT:
            parts.append(f"CPU {float(values.get('smooth_cpu_temp') or values.get('cpu_temp') or 0):.0f} \u00b0C")
        if values.get("level_gpu_temp") == LEVEL_CRIT:
            parts.append(f"GPU {float(values.get('smooth_gpu_temp') or values.get('gpu_temp') or 0):.0f} \u00b0C")
        self.hardwareWarning.emit("CRITICAL", "Running very hot: " + ", ".join(parts))

    def summary_lines(self) -> list[str]:
        v = self._values
        return [
            f"Game telemetry source: {self._source}",
            f"Game FPS: {float(v.get('fps', 0.0)):.1f}",
            f"Game frame time: {float(v.get('frame_time_ms', 0.0)):.3f} ms",
            f"1% low: {float(v.get('one_percent_low', 0.0)):.1f}",
            f"0.1% low: {float(v.get('point_one_percent_low', 0.0)):.1f}",
            f"Sampled stutters: {self._stutters}",
            f"Hardware telemetry: {v.get('hardware_health_level', 'unavailable')} - {v.get('hardware_health_text', 'No sensor sample')}",
            f"CPU sensor: {v.get('cpu_temp_sensor', 'unavailable')} ({v.get('cpu_temp_kind', 'unavailable')})",
            f"CPU temperature: {float(v.get('cpu_temp', 0.0)):.1f} C",
            f"CPU sensor freshness: {'fresh' if v.get('cpu_sample_fresh') else 'stale/unavailable'} ({float(v.get('cpu_sample_age_ms', 0.0)):.0f} ms)",
            f"CPU performance limit: {v.get('cpu_limit_status', 'unavailable')}",
            (
                f"CPU temperature colours: amber from {self._cpu_limits.warn:.0f} C, red from "
                f"{self._cpu_limits.crit:.0f} C ({self._cpu_limits.cpu_name or 'CPU model unknown'}"
                + (f", max {self._cpu_limits.tjmax:.0f} C)" if self._cpu_limits.known else ", default limits)")
            ),
            f"GPU: {v.get('gpu_name', 'unavailable')} (NVML index {v.get('gpu_index', 'n/a')})",
            f"GPU temperature: {float(v.get('gpu_temp', 0.0)):.1f} C / max {float(v.get('gpu_max_temp', 0.0)):.1f} C / slowdown {float(v.get('gpu_slowdown_temp', 0.0)):.1f} C",
            f"GPU clock limits: {v.get('gpu_throttle_status', 'unavailable')} (mask 0x{int(v.get('gpu_clock_reason_mask', 0)):X})",
            f"Hardware sample age: {float(v.get('hardware_sample_age_ms', 0.0)):.0f} ms",
            f"PresentMon dropped rows: {self._presentmon_dropped_rows}",
            f"PresentMon fallback error: {self._presentmon_error or 'none'}",
            (
                "HUD placement: game window physical "
                f"{self._raw_window} -> logical "
                f"({self._window_left}, {self._window_top}, {self._window_right}, {self._window_bottom}) "
                f"on screen {self._game_screen_name or 'unknown'} "
                f"({self._screen_left}, {self._screen_top}, {self._screen_right}, {self._screen_bottom}) "
                f"at {self._game_monitor_dpi or 'unknown'} dpi, scale {self._game_screen_scale:g}"
            ),
        ]

    @Slot()
    def shutdown(self) -> None:
        self._stop_presentmon()
        self._timer.stop()
        self._nvml_monitor.shutdown()
        self._pdh_monitor.shutdown()

    @Property("QVariantMap", notify=changed)
    def values(self):
        return dict(self._values)

    @Property("QVariantList", notify=changed)
    def frameHistory(self):
        return list(self._history)

    @Property(str, notify=changed)
    def sourceSummary(self):
        return str(self._values.get("source_summary") or telemetry_source_summary(
            bool(self._process_id), None, None, self._presentmon_error, False))

    @Property(str, notify=changed)
    def hardwareLimitsSummary(self):
        return hardware_limit_summary(self._values)

    @Property(float, constant=True)
    def cpuTempRedLimit(self):
        return self._cpu_limits.crit

    @Property(str, notify=changed)
    def source(self):
        return self._source

    @Property(bool, notify=changed)
    def live(self):
        return self._live

    @Property(int, notify=changed)
    def windowLeft(self):
        """Logical (Qt device-independent) game window edges."""
        return self._window_left

    @Property(int, notify=changed)
    def windowTop(self):
        return self._window_top

    @Property(int, notify=changed)
    def windowRight(self):
        return self._window_right

    @Property(int, notify=changed)
    def windowBottom(self):
        return self._window_bottom

    @Property(int, notify=changed)
    def screenLeft(self):
        """Logical left edge of the screen that shows the game."""
        return self._screen_left

    @Property(int, notify=changed)
    def screenTop(self):
        return self._screen_top

    @Property(int, notify=changed)
    def screenRight(self):
        return self._screen_right

    @Property(int, notify=changed)
    def screenBottom(self):
        return self._screen_bottom

    @Property(str, notify=changed)
    def gameScreenName(self):
        return self._game_screen_name

    @Property(int, notify=changed)
    def gameMonitorDpi(self):
        return self._game_monitor_dpi

    @Property(float, notify=changed)
    def gameScreenScale(self):
        return self._game_screen_scale

    @Property(int, notify=changed)
    def rawWindowLeft(self):
        """Physical (Win32) game window edges, for diagnostics only."""
        return self._raw_window[0]

    @Property(int, notify=changed)
    def rawWindowTop(self):
        return self._raw_window[1]

    @Property(int, notify=changed)
    def rawWindowRight(self):
        return self._raw_window[2]

    @Property(int, notify=changed)
    def rawWindowBottom(self):
        return self._raw_window[3]

    @Property(bool, notify=changed)
    def gameForeground(self):
        return self._game_foreground
