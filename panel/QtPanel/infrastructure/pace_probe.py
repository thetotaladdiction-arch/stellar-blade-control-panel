"""Frame pacing probe for the packaged panel (automation only: --pace-probe).

Design rule: 60 frames per second is the minimum. Whenever anything in
the panel moves, frames follow the monitor refresh and no frame interval
exceeds 16.7 ms; frames where nothing changes are not drawn.

``--pace-probe <out.json>`` runs the real window through a fixed script and
records every ``frameSwapped`` on the render thread (a direct connection, so
the time is when the frame was handed to the display, not when the GUI
thread got round to it). Each phase reports its frames, frames/s, the
interval distribution and the process CPU time:

* every page at rest - the Dashboard, Gameplay, Items & Money (build 4d),
  Settings and Support (2.5.504: every page is a still image - build 4
  removed the Dashboard video - so nothing may be drawn), a page switch
  into and out of each kind of page, wheel
  glides on the Items page and on Support (its folds opened first, so the
  page really scrolls; each scroll phase records how far the page moved),
  a hover in and out on a Support button, the Technical details fold
  opening and then resting open (its redraw counter must not redraw the
  page), and a select popup opening on Settings.

A "burst" is a run of frames closer than 50 ms. Between bursts nothing on
screen changed (Support at rest, or between two hover fades), so those gaps
are skipped frames, not slow ones; ``burst`` stats hold only the intervals
inside bursts. Nothing is written to the game or to panel settings.
"""

from __future__ import annotations

import json
import os
import statistics
import sys
import threading
import time
from pathlib import Path

from PySide6.QtCore import QEvent, QMetaObject, QObject, QPoint, QPointF, Qt, QTimer
from PySide6.QtGui import QGuiApplication, QMouseEvent, QWheelEvent

BURST_GAP_MS = 50.0
BUDGET_MS = 1000.0 / 60.0
# The GUI thread's watchdog ticks every 5 ms; a tick later than this means
# the GUI thread was busy (building a page, laying out a fold) and could not
# advance animations or answer input.
GUI_WATCH_MS = 5
GUI_STALL_MS = 40.0


def _process_cpu_seconds() -> float:
    times = os.times()
    return float(times.user + times.system)


def interval_stats(intervals: list[float]) -> dict:
    if not intervals:
        return {"n": 0}
    ordered = sorted(intervals)

    def q(p: float) -> float:
        return round(ordered[min(len(ordered) - 1, int(p * len(ordered)))], 2)

    return {
        "n": len(ordered),
        "p50_ms": q(0.5),
        "p90_ms": q(0.9),
        "p99_ms": q(0.99),
        "max_ms": round(ordered[-1], 2),
        "mean_ms": round(statistics.fmean(ordered), 2),
        "over_16_7_ms": sum(1 for value in ordered if value > BUDGET_MS),
        "over_8_ms": sum(1 for value in ordered if value > 8.0),
    }


def summarize(stamps: list[float], start: float, end: float, cpu_seconds: float,
              gui_stalls: list[tuple[float, float]] | None = None) -> dict:
    """Stats for the frames swapped in [start, end) (perf_counter seconds).

    ``gui_stalls``: (perf_counter second, ms) where the GUI thread was held
    up for longer than GUI_STALL_MS (the probe's own watchdog timer)."""
    inside = [stamp for stamp in stamps if start <= stamp < end]
    intervals = [(b - a) * 1000.0 for a, b in zip(inside, inside[1:])]
    bursts: list[list[float]] = []
    current: list[float] = []
    for value in intervals:
        if value <= BURST_GAP_MS:
            current.append(value)
        elif current:
            bursts.append(current)
            current = []
    if current:
        bursts.append(current)
    burst_intervals = [value for burst in bursts for value in burst]
    # Where the slow frames were: (ms after the phase began, interval ms).
    slow = [
        (round((b - start) * 1000.0, 1), round((b - a) * 1000.0, 2))
        for a, b in zip(inside, inside[1:])
        if BUDGET_MS < (b - a) * 1000.0 <= 250.0
    ][:40]
    # And every longer interval (a stretch with no frame at all), same form.
    # Build 4c review: the 322/350 ms intervals on the Support fold were in
    # neither list, so a report quoting burst maxima never saw them.
    long_gaps = [
        (round((b - start) * 1000.0, 1), round((b - a) * 1000.0, 2))
        for a, b in zip(inside, inside[1:])
        if (b - a) * 1000.0 > 250.0
    ][:40]
    seconds = max(1e-6, end - start)
    first_after_start_ms = round((inside[0] - start) * 1000.0, 2) if inside else None
    return {
        "seconds": round(seconds, 3),
        "frames": len(inside),
        "frames_per_s": round(len(inside) / seconds, 1),
        "cpu_pct_core": round(100.0 * cpu_seconds / seconds, 2),
        "first_frame_after_ms": first_after_start_ms,
        "all": interval_stats(intervals),
        "burst": interval_stats(burst_intervals),
        "bursts": len(bursts),
        "slow_frames": slow,
        "long_gaps": long_gaps,
        # Every frame, ms after the phase began (the raw record behind the stats).
        "frames_ms": [round((stamp - start) * 1000.0, 1) for stamp in inside][:600],
        "gui_stalls": [
            (round((at - start) * 1000.0, 1), round(ms, 1))
            for at, ms in (gui_stalls or []) if start <= at < end
        ],
    }


class PaceProbe(QObject):
    """Drives the window through the phases and writes one JSON report."""

    def __init__(self, app, root, backend, out_path: str, parent=None):
        super().__init__(parent)
        self.app = app
        self.root = root
        self.backend = backend
        self.out_path = Path(out_path)
        self.stamps: list[float] = []
        self._lock = threading.Lock()
        self.phases: list[dict] = []
        self._steps: list[tuple] = []
        self._index = 0
        self._phase: dict | None = None
        # Shorter GIL hand-off so the render thread's timestamp is not held
        # back by Python code on the GUI thread.
        sys.setswitchinterval(0.0005)
        root.frameSwapped.connect(self._on_swapped, Qt.ConnectionType.DirectConnection)
        # GUI-thread watchdog (see GUI_STALL_MS).
        self.gui_stalls: list[tuple[float, float]] = []
        self._watch_last = time.perf_counter()
        self._watch = QTimer(self)
        self._watch.setTimerType(Qt.TimerType.PreciseTimer)
        self._watch.setInterval(GUI_WATCH_MS)
        self._watch.timeout.connect(self._on_watch)
        self._watch.start()

    def _on_watch(self) -> None:
        now = time.perf_counter()
        late_ms = (now - self._watch_last) * 1000.0
        if late_ms > GUI_STALL_MS:
            self.gui_stalls.append((now, late_ms))
        self._watch_last = now

    # Render thread.
    def _on_swapped(self) -> None:
        now = time.perf_counter()
        with self._lock:
            self.stamps.append(now)

    # ----------------------------------------------------------------- input
    def _find_flick(self, page: str):
        for candidate in self.root.findChildren(QObject, "pageScrollFlick"):
            owner = candidate.parentItem() if hasattr(candidate, "parentItem") else None
            if owner is not None and owner.property("pageId") == page:
                return candidate
        return None

    def _item_center(self, item) -> QPointF | None:
        try:
            width = float(item.property("width"))
            height = float(item.property("height"))
            point = item.mapToScene(QPointF(width / 2.0, height / 2.0))
            return QPointF(point.x(), point.y())
        except Exception:
            return None

    def _mouse_move(self, point: QPointF) -> None:
        global_point = self.root.mapToGlobal(point.toPoint())
        event = QMouseEvent(
            QEvent.Type.MouseMove,
            point,
            QPointF(global_point),
            Qt.MouseButton.NoButton,
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
        )
        QGuiApplication.sendEvent(self.root, event)

    def _wheel(self, point: QPointF, notches: int = -1) -> None:
        global_point = self.root.mapToGlobal(point.toPoint())
        event = QWheelEvent(
            point,
            QPointF(global_point),
            QPoint(0, 0),
            QPoint(0, 120 * notches),
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
            Qt.ScrollPhase.NoScrollPhase,
            False,
        )
        QGuiApplication.sendEvent(self.root, event)

    def _support_button(self):
        """A visible, enabled SbButton on Support (hover target)."""
        best = None
        for item in self.root.findChildren(QObject):
            try:
                if item.property("danger") is None or item.property("text") in (None, ""):
                    continue
                if not item.isVisible() or not item.property("enabled"):
                    continue
            except Exception:
                continue
            center = self._item_center(item)
            if center is None:
                continue
            if 0 < center.x() < self.root.width() and 80 < center.y() < self.root.height() - 40:
                best = item
                break
        return best

    def _page_point(self, page: str) -> QPointF:
        flick = self._find_flick(page)
        center = self._item_center(flick) if flick is not None else None
        return center or QPointF(self.root.width() * 0.5, self.root.height() * 0.5)

    # ---------------------------------------------------------------- phases
    def _go(self, page: str) -> None:
        self.root.setProperty("activePage", page)

    def _begin(self, name: str, note: str = "") -> None:
        self._phase = {"name": name, "note": note, "start": time.perf_counter(), "cpu": _process_cpu_seconds()}

    def _end(self) -> None:
        phase = self._phase
        if phase is None:
            return
        end = time.perf_counter()
        cpu = _process_cpu_seconds() - phase["cpu"]
        with self._lock:
            stamps = list(self.stamps)
        result = {"name": phase["name"], "note": phase["note"], "t0": round(phase["start"], 4)}
        result.update(summarize(stamps, phase["start"], end, cpu, self.gui_stalls))
        self.phases.append(result)
        self._phase = None

    def _hover_in(self) -> None:
        button = self._support_button()
        center = self._item_center(button) if button is not None else None
        self._hover_target = center
        if center is not None:
            self._mouse_move(center)

    def _hover_out(self) -> None:
        self._mouse_move(QPointF(8, self.root.height() - 8))

    def _support_sections(self) -> list:
        return [item for item in self.root.findChildren(QObject)
                if item.objectName() in ("supportActivityLog", "supportTechnicalDetails", "supportWhatsNew")]

    def _set_folds(self, names: tuple[str, ...], expanded: bool) -> None:
        for item in self._support_sections():
            if item.objectName() in names:
                item.setProperty("expanded", expanded)

    def _scroller(self, page: str):
        """What the wheel scrolls there: the item list on Items (the pointer
        is over it), the page itself elsewhere."""
        if page == "items":
            found = self.root.findChild(QObject, "itemsCatalogList")
            if found is not None:
                return found
        return self._find_flick(page)

    def _mark_scroll(self, page: str) -> None:
        view = self._scroller(page)
        self._scroll_from = float(view.property("contentY")) if view is not None else None

    def _end_scroll(self, page: str) -> None:
        view = self._scroller(page)
        before = getattr(self, "_scroll_from", None)
        self._end()
        if view is not None and before is not None and self.phases:
            self.phases[-1]["scrolled_px"] = round(float(view.property("contentY")) - before, 1)

    def _select_popup(self, name: str, open_it: bool) -> None:
        # The popup is a child object of the box (its "popup" property has no
        # Python converter for QQuickPopup*).
        box = self.root.findChild(QObject, name)
        for child in box.children() if box is not None else []:
            if "Popup" in child.metaObject().className():
                QMetaObject.invokeMethod(child, "open" if open_it else "close")
                return

    def _scroll(self, page: str, notches: int) -> None:
        self._wheel(self._page_point(page), notches)

    def build_steps(self) -> None:
        s = self._steps
        # (delay_ms_before, action, args)
        # The first seconds are start-up: the other pages are built in the
        # background, one every 1.5 s (AnimatedPageHost warmTimer), so this
        # phase is not a rest measurement; gameplay-at-rest below is.
        s.append((3500, self._begin, ("gameplay-start-up", "the other pages are built in the background")))
        s.append((6000, self._end, ()))
        s.append((0, self._begin, ("gameplay-at-rest", "still image, nothing moves (expect 0 frames)")))
        s.append((5000, self._end, ()))
        s.append((0, self._begin, ("switch-gameplay-to-items", "page switch")))
        s.append((0, self._go, ("items",)))
        s.append((1500, self._end, ()))
        s.append((500, self._mark_scroll, ("items",)))
        s.append((0, self._begin, ("items-wheel-scroll", "6 wheel notches, 90 ms apart")))
        for index in range(6):
            s.append((0 if index == 0 else 90, self._scroll, ("items", -1)))
        s.append((900, self._end_scroll, ("items",)))
        # Build 4c review: Items & Money at rest had never been measured.
        s.append((1500, self._begin, ("items-at-rest", "the glide has ended, nothing moves (expect 0 frames)")))
        s.append((5000, self._end, ()))
        s.append((0, self._begin, ("switch-items-to-support", "page switch")))
        s.append((0, self._go, ("support",)))
        s.append((1500, self._end, ()))
        s.append((2000, self._begin, ("support-at-rest", "nothing moves (expect 0 frames); the redraw counter reads only while Technical details is open")))
        s.append((6000, self._end, ()))
        s.append((0, self._begin, ("support-hover-in", "pointer onto a button")))
        s.append((0, self._hover_in, ()))
        s.append((700, self._end, ()))
        s.append((0, self._begin, ("support-hover-out", "pointer off the button")))
        s.append((0, self._hover_out, ()))
        s.append((700, self._end, ()))
        s.append((300, self._begin, ("support-fold-open", "Technical details opens (200 ms fold)")))
        s.append((0, self._set_folds, (("supportTechnicalDetails",), True)))
        s.append((700, self._end, ()))
        s.append((2500, self._begin, ("support-open-at-rest",
                                      "Technical details open, nothing moves: its redraw counter must not redraw")))
        s.append((6000, self._end, ()))
        # Every fold open, so the page is taller than the window and the
        # wheel really scrolls it (scrolled_px says how far).
        s.append((0, self._set_folds, (("supportActivityLog", "supportWhatsNew"), True)))
        s.append((800, self._mark_scroll, ("support",)))
        s.append((0, self._begin, ("support-wheel-scroll", "4 wheel notches, 120 ms apart, every fold open")))
        for index in range(4):
            s.append((0 if index == 0 else 120, self._scroll, ("support", -1)))
        s.append((700, self._end_scroll, ("support",)))
        s.append((0, self._set_folds, (("supportActivityLog", "supportTechnicalDetails", "supportWhatsNew"), False)))
        s.append((600, self._begin, ("switch-support-to-settings", "page switch")))
        s.append((0, self._go, ("settings",)))
        s.append((1500, self._end, ()))
        s.append((0, self._begin, ("settings-at-rest", "still image, nothing moves (expect 0 frames)")))
        s.append((4000, self._end, ()))
        s.append((0, self._begin, ("settings-select-open", "the overlay Size popup opens (140 ms)")))
        s.append((0, self._select_popup, ("settingsOverlaySize", True)))
        s.append((600, self._end, ()))
        s.append((0, self._select_popup, ("settingsOverlaySize", False)))
        s.append((0, self._begin, ("switch-settings-to-gameplay", "page switch")))
        s.append((0, self._go, ("gameplay",)))
        s.append((1500, self._end, ()))
        s.append((0, self._begin, ("gameplay-after-tour-at-rest", "every page built; still image, nothing moves (expect 0 frames)")))
        s.append((5000, self._end, ()))
        # Second round: every page has been shown once (created, its text
        # drawn, its art still in memory), as when the player goes back and
        # forth.
        for source, target in (("gameplay", "items"), ("items", "support"),
                               ("support", "settings"), ("settings", "gameplay")):
            s.append((300, self._begin, (f"again-{source}-to-{target}", "page switch, page seen before")))
            s.append((0, self._go, (target,)))
            s.append((1200, self._end, ()))
        s.append((0, self._finish, ()))

    def start(self) -> None:
        self.build_steps()
        self._next()

    def _next(self) -> None:
        if self._index >= len(self._steps):
            return
        delay, action, args = self._steps[self._index]
        self._index += 1

        def run() -> None:
            try:
                action(*args)
            except Exception as exc:  # pragma: no cover - diagnostic path
                self.phases.append({"name": "error", "note": f"{type(exc).__name__}: {exc}"})
            self._next()

        QTimer.singleShot(max(0, int(delay)), run)

    def _finish(self) -> None:
        screen = self.root.screen()
        try:
            actual = self.root.rendererInterface().graphicsApi().name
        except Exception:
            actual = "unknown"
        report = {
            "screen": screen.name() if screen else "",
            "refresh_hz": round(float(screen.refreshRate()), 2) if screen else None,
            "dpr": float(screen.devicePixelRatio()) if screen else None,
            "window": [self.root.x(), self.root.y(), self.root.width(), self.root.height()],
            "renderer": actual,
            "render_loop": os.environ.get("QSG_RENDER_LOOP", ""),
            "budget_ms": round(BUDGET_MS, 2),
            "burst_gap_ms": BURST_GAP_MS,
            "pid": os.getpid(),
            # Qt's threaded loop steps animations on vsync only while exactly
            # one window is exposed; list them all.
            "top_level_windows": [
                {
                    "type": type(window).__name__,
                    "title": window.title(),
                    "visible": window.isVisible(),
                    "exposed": window.isExposed(),
                    "geometry": [window.x(), window.y(), window.width(), window.height()],
                }
                for window in QGuiApplication.topLevelWindows()
            ],
            "phases": self.phases,
        }
        self.out_path.parent.mkdir(parents=True, exist_ok=True)
        self.out_path.write_text(json.dumps(report, indent=1), encoding="utf-8")
        print(str(self.out_path))
        self.app.quit()
