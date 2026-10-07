from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QFileSystemWatcher, QObject, QTimer, Signal


class CoalescedFileWatcher(QObject):
    """Immediate file notifications with atomic-replace recovery and slow polling fallback."""

    changed = Signal(str)

    def __init__(self, tagged_paths: dict[str, Path], parent=None):
        super().__init__(parent)
        self._paths = {str(path.resolve()): tag for tag, path in tagged_paths.items()}
        self._signatures = {path: self._signature(Path(path)) for path in self._paths}
        self._pending: set[str] = set()
        self._watcher = QFileSystemWatcher(self)
        self._watcher.fileChanged.connect(self._on_file_changed)
        self._watcher.directoryChanged.connect(self._on_directory_changed)

        self._flush_timer = QTimer(self)
        self._flush_timer.setSingleShot(True)
        self._flush_timer.setInterval(70)
        self._flush_timer.timeout.connect(self._flush)

        self._recovery_timer = QTimer(self)
        self._recovery_timer.setInterval(10000)
        self._recovery_timer.timeout.connect(self._scan_all)
        self._recovery_timer.start()
        self._rearm()

    @staticmethod
    def _signature(path: Path) -> tuple[bool, int, int]:
        try:
            stat = path.stat()
            return True, stat.st_mtime_ns, stat.st_size
        except OSError:
            return False, 0, 0

    def _rearm(self) -> None:
        watched_files = set(self._watcher.files())
        for raw_path in self._paths:
            if raw_path not in watched_files and Path(raw_path).is_file():
                self._watcher.addPath(raw_path)
        watched_dirs = set(self._watcher.directories())
        for directory in {str(Path(path).parent) for path in self._paths}:
            if directory not in watched_dirs and Path(directory).is_dir():
                self._watcher.addPath(directory)

    def _queue(self, raw_path: str) -> None:
        tag = self._paths.get(str(Path(raw_path).resolve()))
        if tag:
            self._pending.add(tag)
            self._flush_timer.start()

    def _on_file_changed(self, raw_path: str) -> None:
        resolved = str(Path(raw_path).resolve())
        self._signatures[resolved] = self._signature(Path(resolved))
        self._queue(resolved)
        QTimer.singleShot(80, self._rearm)

    def _on_directory_changed(self, _directory: str) -> None:
        self._scan_all()
        QTimer.singleShot(80, self._rearm)

    def _scan_all(self) -> None:
        for raw_path in self._paths:
            current = self._signature(Path(raw_path))
            if current != self._signatures.get(raw_path):
                self._signatures[raw_path] = current
                self._queue(raw_path)
        self._rearm()

    def _flush(self) -> None:
        pending = sorted(self._pending)
        self._pending.clear()
        for tag in pending:
            self.changed.emit(tag)
