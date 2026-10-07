"""Panel log and crash file (panel audit A6).

The windowed exe has no console: ``sys.stderr`` is ``None``, so Qt/QML
warnings, worker exceptions and hard crashes used to vanish. This keeps:

* ``logs/panel.log``: rotating, 1 MB x 3. Qt/QML warnings, uncaught Python
  exceptions (main and worker threads) and background-job failures.
* ``logs/panel-crash.txt``: ``faulthandler`` output for hard crashes
  (access violations, aborts), each run headed by the build id so a crash
  can be matched to the exact panel build.

Nothing here changes behaviour: every fail-closed decision in the panel is
unchanged, it is only written down.
"""

from __future__ import annotations

import faulthandler
import logging
import logging.handlers
import os
import sys
import threading
import time
from pathlib import Path

LOGGER_NAME = "panel"
LOG_MAX_BYTES = 1_000_000
LOG_BACKUPS = 3
CRASH_MAX_BYTES = 256 * 1024

_state: dict[str, object] = {}


def build_id(version: str, ui_revision: str) -> str:
    """One line that names the exact build: version, UI revision, runtime."""
    mode = "exe" if getattr(sys, "frozen", False) else "source"
    try:
        from PySide6 import __version__ as pyside_version
    except ImportError:  # pragma: no cover - PySide is always bundled
        pyside_version = "unknown"
    stamp = ""
    try:
        target = Path(sys.executable if getattr(sys, "frozen", False) else __file__)
        stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime(target.stat().st_mtime))
    except OSError:
        pass
    return (
        f"panel {version or 'unknown'} ui {ui_revision or 'unknown'} {mode}"
        f"{' ' + stamp if stamp else ''} python {sys.version.split()[0]} pyside {pyside_version}"
    )


def _rotate_crash_file(path: Path) -> None:
    try:
        if path.stat().st_size > CRASH_MAX_BYTES:
            os.replace(path, path.with_name(path.name + ".1"))
    except OSError:
        pass


def _qt_message_handler(mode, context, message) -> None:
    from PySide6.QtCore import QtMsgType

    logger = logging.getLogger(LOGGER_NAME + ".qt")
    if mode == QtMsgType.QtDebugMsg or mode == QtMsgType.QtInfoMsg:
        return
    text = str(message)
    last = _state.get("last_qt")
    if last == text:
        _state["repeat_qt"] = int(_state.get("repeat_qt", 0)) + 1
        return
    repeats = int(_state.get("repeat_qt", 0))
    if repeats:
        logger.warning("(previous Qt message repeated %d more times)", repeats)
    _state["last_qt"] = text
    _state["repeat_qt"] = 0
    where = ""
    try:
        if context is not None and context.file:
            where = f" [{context.file}:{context.line}]"
    except (AttributeError, RuntimeError):
        pass
    if mode == QtMsgType.QtWarningMsg:
        logger.warning("%s%s", text, where)
    else:
        logger.error("%s%s", text, where)
    stream = sys.__stderr__
    if stream is not None:
        try:
            stream.write(text + "\n")
        except (OSError, ValueError):
            pass


def install_panel_logging(mod_root: Path, version: str, ui_revision: str) -> logging.Logger:
    """Start the panel log and crash file once per process; safe to call again."""
    logger = logging.getLogger(LOGGER_NAME)
    if _state.get("installed"):
        return logger
    logs = Path(mod_root) / "logs"
    identity = build_id(version, ui_revision)
    try:
        logs.mkdir(parents=True, exist_ok=True)
        handler = logging.handlers.RotatingFileHandler(
            logs / "panel.log",
            maxBytes=LOG_MAX_BYTES,
            backupCount=LOG_BACKUPS,
            encoding="utf-8",
            delay=True,
        )
    except OSError:
        return logger
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    _state["installed"] = True
    _state["handler"] = handler

    crash_path = logs / "panel-crash.txt"
    _rotate_crash_file(crash_path)
    try:
        crash_stream = open(crash_path, "a", encoding="utf-8", buffering=1)
        crash_stream.write(
            f"=== {time.strftime('%Y-%m-%d %H:%M:%S %z')} pid {os.getpid()} {identity}\n"
        )
        crash_stream.flush()
        faulthandler.enable(file=crash_stream, all_threads=True)
        _state["crash_stream"] = crash_stream  # must stay open for faulthandler
    except OSError:
        pass

    previous_hook = sys.excepthook

    def _excepthook(exc_type, exc, tb):
        logger.error("Uncaught exception", exc_info=(exc_type, exc, tb))
        if previous_hook is not None and previous_hook is not sys.__excepthook__:
            previous_hook(exc_type, exc, tb)
        elif sys.__stderr__ is not None:
            sys.__excepthook__(exc_type, exc, tb)

    def _thread_excepthook(args):
        logger.error(
            "Uncaught exception in thread %s",
            getattr(args.thread, "name", "?"),
            exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
        )

    sys.excepthook = _excepthook
    threading.excepthook = _thread_excepthook

    try:
        from PySide6.QtCore import qInstallMessageHandler

        qInstallMessageHandler(_qt_message_handler)
    except ImportError:  # pragma: no cover
        pass

    logger.info("Panel start: %s", identity)
    return logger
