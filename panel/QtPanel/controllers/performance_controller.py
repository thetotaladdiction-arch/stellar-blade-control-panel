from __future__ import annotations

import statistics
import time
from collections import deque
from pathlib import Path

from PySide6.QtCore import QObject, Property, QTimer, Signal, Slot


class PerformanceController(QObject):
    """Low-overhead render/backend telemetry exposed to QML and support reports."""

    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._window = None
        self._frame_samples: deque[float] = deque(maxlen=10)
        self._frame_sampled_at = 0.0
        self._fps = 0.0
        self._frame_ms = 0.0
        self._slow_frames = 0
        self._counting = False
        self._frame_count = 0
        self._count_started = 0.0
        self._count_timer = QTimer(self)
        self._count_timer.setInterval(1000)
        self._count_timer.timeout.connect(self._sample_frame_rate)
        self._catalog_filter_ms = 0.0
        self._backend_job_ms = 0.0
        self._backend_job_name = "Nothing yet"

    def attach_window(self, window) -> None:
        if self._window is window:
            return
        self.setFrameCountingActive(False)
        self._window = window

    @Slot(bool)
    def setFrameCountingActive(self, active: bool) -> None:
        """Count the window's real redraws, only while Support shows them.

        The count comes from QQuickWindow.frameSwapped, so an idle panel
        reports 0 frames/s instead of the refresh rate of a forced clock.
        """
        active = bool(active) and self._window is not None
        if active == self._counting:
            return
        self._counting = active
        if active:
            self._frame_count = 0
            self._count_started = time.monotonic()
            self._window.frameSwapped.connect(self._on_frame_swapped)
            self._count_timer.start()
            return
        self._count_timer.stop()
        try:
            self._window.frameSwapped.disconnect(self._on_frame_swapped)
        except (RuntimeError, TypeError, AttributeError):
            pass
        self.markFrameSamplingInactive()

    @Slot()
    def _on_frame_swapped(self) -> None:
        self._frame_count += 1

    @Slot()
    def _sample_frame_rate(self) -> None:
        now = time.monotonic()
        elapsed = now - self._count_started
        if elapsed <= 0:
            return
        rate = self._frame_count / elapsed
        self._frame_count = 0
        self._count_started = now
        self._frame_samples.append(rate)
        self._frame_sampled_at = now
        self._fps = statistics.fmean(self._frame_samples)
        self._frame_ms = 1000.0 / self._fps if self._fps > 0 else 0.0
        self.changed.emit()

    @Slot()
    def markFrameSamplingInactive(self) -> None:
        """Invalidate the redraw rate when Support is not counting frames."""
        if not self._frame_samples and self._fps == 0.0 and self._frame_ms == 0.0:
            return
        self._frame_samples.clear()
        self._frame_sampled_at = 0.0
        self._fps = 0.0
        self._frame_ms = 0.0
        self.changed.emit()

    def record_catalog_filter(self, elapsed_ms: float) -> None:
        self._catalog_filter_ms = max(0.0, float(elapsed_ms))
        self.changed.emit()

    def record_backend_job(self, label: str, elapsed_seconds: float) -> None:
        self._backend_job_name = label or "Backend job"
        self._backend_job_ms = max(0.0, float(elapsed_seconds) * 1000.0)
        self.changed.emit()

    def _frame_sample_is_fresh(self) -> bool:
        return (
            self._counting
            and self._frame_sampled_at > 0
            and time.monotonic() - self._frame_sampled_at <= 2.5
        )

    def summary_lines(self) -> list[str]:
        fresh = self._frame_sample_is_fresh()
        return [
            "Panel redraws per second: " + (
                f"{self._fps:.1f}" if fresh else "unavailable (counted only while Support is open)"
            ),
            "Panel frame interval: " + (
                f"{self._frame_ms:.2f} ms" if fresh and self._fps > 0 else "unavailable"
            ),
            f"Panel slow frames (>25 ms): {self._slow_frames}",
            f"Last catalog filter: {self._catalog_filter_ms:.3f} ms",
            f"Last backend job: {self._backend_job_name}",
            f"Last backend duration: {self._backend_job_ms:.1f} ms",
        ]

    def write_snapshot(self, path: Path, extra_lines: list[str] | None = None) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        lines = [
            "SBCheatGUI Performance Diagnostics",
            f"Created: {time.strftime('%Y-%m-%d %H:%M:%S %z')}",
            "",
            *self.summary_lines(),
            *(extra_lines or []),
        ]
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    @Property(float, notify=changed)
    def fps(self):
        return self._fps if self._frame_sample_is_fresh() else 0.0

    @Property(float, notify=changed)
    def frameTimeMs(self):
        return self._frame_ms if self._frame_sample_is_fresh() else 0.0

    @Property(bool, notify=changed)
    def frameSampleFresh(self):
        return self._frame_sample_is_fresh()

    @Property(int, notify=changed)
    def slowFrames(self):
        return self._slow_frames

    @Property(float, notify=changed)
    def catalogFilterMs(self):
        return self._catalog_filter_ms

    @Property(float, notify=changed)
    def backendJobMs(self):
        return self._backend_job_ms

    @Property(str, notify=changed)
    def backendJobName(self):
        return self._backend_job_name
