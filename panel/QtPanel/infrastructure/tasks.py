from __future__ import annotations

import logging

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, Slot

_log = logging.getLogger("panel.tasks")


class BackendJobSignals(QObject):
    succeeded = Signal(str, object)
    failed = Signal(str, str)
    finished = Signal(str)


class BackendJob(QRunnable):
    def __init__(self, key: str, work):
        super().__init__()
        self.key = key
        self.work = work
        self.signals = BackendJobSignals()

    @Slot()
    def run(self):
        try:
            result = self.work()
            self.signals.succeeded.emit(self.key, result)
        except Exception as exc:
            _log.exception("Background job %s failed", self.key)
            self.signals.failed.emit(self.key, str(exc))
        finally:
            self.signals.finished.emit(self.key)


class FnRunnable(QRunnable):
    """Fire-and-forget callable used by cheap off-thread probes."""

    def __init__(self, fn):
        super().__init__()
        self._fn = fn

    def run(self):
        try:
            self._fn()
        except Exception:
            # Still fire-and-forget: the probe's caller keeps its cached
            # value. The failure is written to logs/panel.log.
            _log.exception("Background probe failed")


class BackendTaskRunner(QObject):
    activeChanged = Signal()

    def __init__(self, max_threads: int = 2, parent=None):
        super().__init__(parent)
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(max(1, int(max_threads)))
        self._active: dict[str, str] = {}
        self._jobs: dict[str, BackendJob] = {}

    def active_count(self) -> int:
        return len(self._active)

    def busy_text(self) -> str:
        return "Idle" if not self._active else " / ".join(self._active.values())

    def is_active(self, key: str) -> bool:
        return key in self._active

    def start(self, key: str, label: str, work, on_success, on_error) -> bool:
        if key in self._active:
            return False
        job = BackendJob(key, work)
        self._active[key] = label
        self._jobs[key] = job
        job.signals.succeeded.connect(lambda _key, result: on_success(result))
        job.signals.failed.connect(lambda _key, message: on_error(message))
        job.signals.finished.connect(self._finish)
        self.activeChanged.emit()
        self.pool.start(job)
        return True

    @Slot(str)
    def _finish(self, key: str):
        self._active.pop(key, None)
        self._jobs.pop(key, None)
        self.activeChanged.emit()
