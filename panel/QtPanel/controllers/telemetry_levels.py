"""Steady colour levels for live hardware and frame numbers.

Raw sensor values wobble around any threshold (a CPU at 84-86 C, a game at
59-61 FPS), so colouring each 10 Hz sample made HUD rows blink.  Every metric
here is first smoothed with a short moving average and then latched:

* it turns amber/red only after the smoothed value has stayed past the limit
  for ``escalate_seconds`` (about 5 s), and
* it returns only after the value has stayed ``margin`` inside the limit for
  ``recover_seconds`` (about 10 s).

Levels are plain strings so QML can map them to colours: ``"ok"``, ``"warn"``,
``"crit"``, or ``"none"`` when there is no fresh value.
"""

from __future__ import annotations

import re
from collections import deque
from dataclasses import dataclass

LEVEL_NONE = "none"
LEVEL_OK = "ok"
LEVEL_WARN = "warn"
LEVEL_CRIT = "crit"
_LEVEL_NAMES = (LEVEL_OK, LEVEL_WARN, LEVEL_CRIT)

ESCALATE_SECONDS = 5.0
RECOVER_SECONDS = 10.0
SMOOTHING_SECONDS = 2.0

# Temperatures in C; FPS limits apply to the smoothed frame rate.
CPU_TEMP_WARN = 85.0
CPU_TEMP_CRIT = 95.0
GPU_TEMP_WARN_DEFAULT = 83.0
GPU_TEMP_CRIT_DEFAULT = 90.0
TEMP_MARGIN = 5.0
FPS_WARN = 55.0
FPS_CRIT = 30.0
FPS_MARGIN = 5.0

# CPU colours follow the CPU's own limit (TjMax): amber 10 C and red 3 C
# below it. An Intel 12th-14th gen part is built to run up to 100 C, so a
# normal 80-89 C gaming load stays plain; amber starts at 90, red at 97.
# An unknown CPU keeps the old 85/95.
CPU_WARN_BELOW_TJMAX = 10.0
CPU_CRIT_BELOW_TJMAX = 3.0
LEGACY_CPU_TJMAX = 100.0

# Per-model AMD product specifications (Max. Operating Temperature / Tjmax).
# Do not extrapolate a limit to other SKUs, including similarly named parts.
_AMD_TJMAX = {
    ("5", "5600x"): 95.0,
    ("7", "5800x"): 90.0,
    ("7", "7800x3d"): 89.0,
    ("9", "7950x"): 95.0,
    ("7", "9800x3d"): 95.0,
    ("threadripper", "1950x"): 68.0,
}


@dataclass(frozen=True)
class CpuTempLimits:
    """Colour limits for one CPU; ``tjmax`` is where the health line says CRITICAL."""

    warn: float = CPU_TEMP_WARN
    crit: float = CPU_TEMP_CRIT
    tjmax: float = LEGACY_CPU_TJMAX
    cpu_name: str = ""
    known: bool = False


def cpu_tjmax(cpu_name: str) -> float | None:
    """The CPU's maximum junction temperature from its model name, or None."""
    name = " ".join(str(cpu_name or "").split())
    if not name:
        return None
    lower = name.casefold()
    if "intel" in lower or re.search(r"\bcore\(tm\)|\bcore i\d", lower):
        ultra = re.search(r"ultra\s+\d+\s+(\d)(\d{2})([a-z]*)", lower)
        if ultra:
            if ultra.group(1) == "1":
                return 110.0  # Core Ultra 100 (Meteor Lake)
            return 100.0 if "v" in ultra.group(3) else 105.0  # Lunar Lake / Arrow Lake
        return 100.0  # Core i3/i5/i7/i9 6th-14th gen, Core 3/5/7, Pentium...
    if "amd" in lower or "ryzen" in lower:
        model = re.search(
            r"\bryzen(?:\(tm\))?\s+(threadripper(?:\s+pro)?|[3579])\s+(\d{4}[a-z0-9]*)\b", lower
        )
        if model:
            return _AMD_TJMAX.get((model.group(1), model.group(2)))
    return None


def cpu_temp_limits(cpu_name: str) -> CpuTempLimits:
    tjmax = cpu_tjmax(cpu_name)
    if tjmax is None:
        return CpuTempLimits(cpu_name=str(cpu_name or "").strip())
    return CpuTempLimits(
        warn=tjmax - CPU_WARN_BELOW_TJMAX,
        crit=tjmax - CPU_CRIT_BELOW_TJMAX,
        tjmax=tjmax,
        cpu_name=" ".join(str(cpu_name).split()),
        known=True,
    )


def read_cpu_name() -> str:
    """The CPU's model name as Windows reports it ("" when unknown)."""
    try:
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0"
        ) as key:
            return str(winreg.QueryValueEx(key, "ProcessorNameString")[0]).strip()
    except (ImportError, OSError):
        return ""


class MovingAverage:
    """Mean of the samples seen in the last ``window_seconds``."""

    def __init__(self, window_seconds: float = SMOOTHING_SECONDS):
        self.window_seconds = max(0.1, float(window_seconds))
        self._samples: deque[tuple[float, float]] = deque()
        self._total = 0.0

    def reset(self) -> None:
        self._samples.clear()
        self._total = 0.0

    def add(self, value: float, now: float) -> float:
        self._samples.append((now, value))
        self._total += value
        horizon = now - self.window_seconds
        while len(self._samples) > 1 and self._samples[0][0] < horizon:
            self._total -= self._samples.popleft()[1]
        return self.value

    @property
    def value(self) -> float:
        return self._total / len(self._samples) if self._samples else 0.0


class LatchedLevel:
    """Hysteresis + hold time for one metric (see the module docstring)."""

    def __init__(
        self,
        warn: float,
        crit: float,
        *,
        higher_is_worse: bool = True,
        margin: float = TEMP_MARGIN,
        escalate_seconds: float = ESCALATE_SECONDS,
        recover_seconds: float = RECOVER_SECONDS,
        smoothing_seconds: float = SMOOTHING_SECONDS,
    ):
        self.warn = float(warn)
        self.crit = float(crit)
        self.higher_is_worse = bool(higher_is_worse)
        self.margin = abs(float(margin))
        self.escalate_seconds = float(escalate_seconds)
        self.recover_seconds = float(recover_seconds)
        self.average = MovingAverage(smoothing_seconds)
        self._rank = 0
        self._has_value = False
        self._bad_since: dict[int, float | None] = {1: None, 2: None}
        self._clear_since: dict[int, float | None] = {1: None, 2: None}

    def set_limits(self, warn: float, crit: float) -> None:
        self.warn = float(warn)
        self.crit = float(crit)

    def reset(self) -> None:
        self.average.reset()
        self._rank = 0
        self._has_value = False
        self._bad_since = {1: None, 2: None}
        self._clear_since = {1: None, 2: None}

    def _threshold(self, rank: int) -> float:
        return self.warn if rank == 1 else self.crit

    def _is_bad(self, value: float, rank: int) -> bool:
        limit = self._threshold(rank)
        return value >= limit if self.higher_is_worse else value <= limit

    def _is_clear(self, value: float, rank: int) -> bool:
        limit = self._threshold(rank)
        if self.higher_is_worse:
            return value < limit - self.margin
        return value > limit + self.margin

    @property
    def level(self) -> str:
        return _LEVEL_NAMES[self._rank] if self._has_value else LEVEL_NONE

    @property
    def smoothed(self) -> float:
        return self.average.value

    def update(self, value: float | None, now: float) -> str:
        """Feed one sample (``None`` = no fresh reading) and return the level."""
        if value is None:
            self.reset()
            return LEVEL_NONE
        smoothed = self.average.add(float(value), float(now))
        self._has_value = True
        for rank in (1, 2):
            if self._is_bad(smoothed, rank):
                if self._bad_since[rank] is None:
                    self._bad_since[rank] = now
            else:
                self._bad_since[rank] = None
            if self._is_clear(smoothed, rank):
                if self._clear_since[rank] is None:
                    self._clear_since[rank] = now
            else:
                self._clear_since[rank] = None

        for rank in (2, 1):
            since = self._bad_since[rank]
            if self._rank < rank and since is not None and now - since >= self.escalate_seconds:
                self._rank = rank
                break
        while self._rank > 0:
            since = self._clear_since[self._rank]
            if since is None or now - since < self.recover_seconds:
                break
            self._rank -= 1
        return self.level


def _finite(values: dict, key: str) -> float | None:
    try:
        number = float(values.get(key))
    except (TypeError, ValueError):
        return None
    if number != number or number in (float("inf"), float("-inf")) or number <= 0:
        return None
    return number


class TelemetryLevels:
    """Smoothed display values and latched colour levels for the HUD."""

    SMOOTHED_KEYS = ("cpu_temp", "gpu_temp", "cpu_usage", "gpu_usage")

    def __init__(self, cpu_limits: CpuTempLimits | None = None):
        self.cpu_limits = cpu_limits or CpuTempLimits()
        self.cpu_temp = LatchedLevel(self.cpu_limits.warn, self.cpu_limits.crit)
        self.gpu_temp = LatchedLevel(GPU_TEMP_WARN_DEFAULT, GPU_TEMP_CRIT_DEFAULT)
        self.fps = LatchedLevel(FPS_WARN, FPS_CRIT, higher_is_worse=False, margin=FPS_MARGIN)
        self.cpu_usage = MovingAverage()
        self.gpu_usage = MovingAverage()

    def reset(self) -> None:
        for latch in (self.cpu_temp, self.gpu_temp, self.fps):
            latch.reset()
        self.cpu_usage.reset()
        self.gpu_usage.reset()

    def update(self, values: dict, now: float) -> dict:
        """Return extra keys to merge into the telemetry values."""
        out: dict[str, float | str] = {}

        gpu_max = _finite(values, "gpu_max_temp")
        if gpu_max:
            self.gpu_temp.set_limits(gpu_max - TEMP_MARGIN, gpu_max)
        else:
            self.gpu_temp.set_limits(GPU_TEMP_WARN_DEFAULT, GPU_TEMP_CRIT_DEFAULT)

        cpu_temp = _finite(values, "cpu_temp")
        if cpu_temp is not None and values.get("cpu_sample_fresh") is False:
            cpu_temp = None  # a frozen sensor must not colour the row
        out["level_cpu_temp"] = self.cpu_temp.update(cpu_temp, now)
        out["level_gpu_temp"] = self.gpu_temp.update(_finite(values, "gpu_temp"), now)
        out["level_fps"] = self.fps.update(_finite(values, "fps"), now)
        if cpu_temp is not None:
            out["smooth_cpu_temp"] = self.cpu_temp.smoothed
        if out["level_gpu_temp"] != LEVEL_NONE:
            out["smooth_gpu_temp"] = self.gpu_temp.smoothed

        for key, average in (("cpu_usage", self.cpu_usage), ("gpu_usage", self.gpu_usage)):
            value = values.get(key)
            try:
                number = float(value)
            except (TypeError, ValueError):
                average.reset()
                continue
            if number != number:
                average.reset()
                continue
            out[f"smooth_{key}"] = average.add(number, now)
        return out

    def temperature_alert_level(self) -> str:
        """The worst latched temperature level, for optional user alerts."""
        ranks = [latch.level for latch in (self.cpu_temp, self.gpu_temp)]
        if LEVEL_CRIT in ranks:
            return LEVEL_CRIT
        if LEVEL_WARN in ranks:
            return LEVEL_WARN
        return LEVEL_OK
