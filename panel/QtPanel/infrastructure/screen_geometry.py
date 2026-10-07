'Physical Win32 rectangles mapped to Qt logical coordinates. Example: a3840x2160 monitor at150% next to a2560x1440 monitor at100% has differing device-pixel ratios. Qt keeps native screen origins and scales screen sizes. Convert every Win32 rectangle through map_physical_rect before positioning a Qt overlay.'





















from __future__ import annotations

import ctypes
import math
import sys
from ctypes import wintypes
from dataclasses import dataclass
from typing import Sequence


USER_DEFAULT_DPI = 96
MONITOR_DEFAULTTONEAREST = 0x00000002
MDT_EFFECTIVE_DPI = 0


@dataclass(frozen=True)
class Rect:
    """Half-open integer rectangle: ``right``/``bottom`` are exclusive."""

    left: int
    top: int
    right: int
    bottom: int

    @property
    def width(self) -> int:
        return self.right - self.left

    @property
    def height(self) -> int:
        return self.bottom - self.top

    @property
    def empty(self) -> bool:
        return self.width <= 0 or self.height <= 0

    @property
    def center(self) -> tuple[float, float]:
        return (self.left + self.right) / 2.0, (self.top + self.bottom) / 2.0

    def contains_point(self, x: float, y: float) -> bool:
        return self.left <= x < self.right and self.top <= y < self.bottom

    def contains_rect(self, other: "Rect") -> bool:
        return (
            self.left <= other.left
            and self.top <= other.top
            and other.right <= self.right
            and other.bottom <= self.bottom
        )

    def intersection_area(self, other: "Rect") -> int:
        width = min(self.right, other.right) - max(self.left, other.left)
        height = min(self.bottom, other.bottom) - max(self.top, other.top)
        return max(0, width) * max(0, height)

    @classmethod
    def from_xywh(cls, x: int, y: int, width: int, height: int) -> "Rect":
        return cls(int(x), int(y), int(x) + int(width), int(y) + int(height))


@dataclass(frozen=True)
class MonitorInfo:
    """What Win32 reports for the monitor that holds a window."""

    rect: Rect  # rcMonitor, physical pixels
    work: Rect  # rcWork, physical pixels
    device: str  # szDevice, e.g. \\.\DISPLAY1
    dpi: int  # effective DPI (96 = 100 %)

    @property
    def scale(self) -> float:
        return (self.dpi or USER_DEFAULT_DPI) / float(USER_DEFAULT_DPI)


@dataclass(frozen=True)
class ScreenInfo:
    """What Qt reports for one QScreen (logical geometry plus its DPR)."""

    name: str
    geometry: Rect  # QScreen.geometry(), logical pixels
    dpr: float  # QScreen.devicePixelRatio()

    @property
    def native_rect(self) -> Rect:
        """The screen in physical pixels (Qt 6 keeps the native origin)."""
        g = self.geometry
        dpr = self.dpr if self.dpr > 0 else 1.0
        return Rect(
            g.left,
            g.top,
            g.left + _round_half_up(g.width * dpr),
            g.top + _round_half_up(g.height * dpr),
        )


@dataclass(frozen=True)
class LogicalPlacement:
    """A physical window rectangle expressed in Qt logical coordinates."""

    window: Rect  # logical window rectangle
    screen: Rect  # logical geometry of the screen that holds the window
    scale: float  # physical pixels per logical pixel on that screen
    screen_index: int  # index into the screens list, or -1 when unmatched
    screen_name: str
    physical_window: Rect
    physical_screen: Rect
    dpi: int


def _round_half_up(value: float) -> int:
    return int(math.floor(value + 0.5))


def physical_rect_to_logical(
    rect: Rect,
    monitor_origin: tuple[int, int],
    scale: float,
    screen_logical_origin: tuple[int, int],
) -> Rect:
    """Convert one physical rectangle on a monitor into Qt logical pixels.

    ``monitor_origin`` is the monitor's physical top-left, ``scale`` its
    physical-per-logical ratio, and ``screen_logical_origin`` the matching
    QScreen's logical top-left (equal to the physical origin on Qt 6).
    """
    if not math.isfinite(scale) or scale <= 0:
        scale = 1.0
    ox, oy = monitor_origin
    lx, ly = screen_logical_origin

    def x(value: int) -> int:
        return lx + _round_half_up((value - ox) / scale)

    def y(value: int) -> int:
        return ly + _round_half_up((value - oy) / scale)

    return Rect(x(rect.left), y(rect.top), x(rect.right), y(rect.bottom))


def logical_point_to_physical(
    x: float,
    y: float,
    screen: ScreenInfo,
) -> tuple[int, int]:
    """Inverse mapping, used by tests and diagnostics."""
    dpr = screen.dpr if screen.dpr > 0 else 1.0
    g = screen.geometry
    return (
        g.left + _round_half_up((x - g.left) * dpr),
        g.top + _round_half_up((y - g.top) * dpr),
    )


def select_screen(monitor: MonitorInfo | None, screens: Sequence[ScreenInfo], rect: Rect) -> int:
    """Pick the QScreen that is the given Win32 monitor.

    Order: exact native origin (Qt 6 keeps it), then the device name, then the
    screen whose native rectangle holds the most of the window.
    """
    if not screens:
        return -1
    if monitor is not None:
        origin = (monitor.rect.left, monitor.rect.top)
        origin_matches = [
            index
            for index, screen in enumerate(screens)
            if (screen.geometry.left, screen.geometry.top) == origin
        ]
        if len(origin_matches) == 1:
            return origin_matches[0]
        device = (monitor.device or "").strip().casefold()
        if device:
            for index in origin_matches or range(len(screens)):
                if (screens[index].name or "").strip().casefold() == device:
                    return index
        if origin_matches:
            return origin_matches[0]
        cx, cy = monitor.rect.center
        for index, screen in enumerate(screens):
            if screen.native_rect.contains_point(cx, cy):
                return index
    best_index = -1
    best_area = 0
    for index, screen in enumerate(screens):
        area = screen.native_rect.intersection_area(rect)
        if area > best_area:
            best_index, best_area = index, area
    if best_index >= 0:
        return best_index
    cx, cy = rect.center
    for index, screen in enumerate(screens):
        if screen.native_rect.contains_point(cx, cy):
            return index
    return -1


def map_physical_rect(
    rect: Rect,
    monitor: MonitorInfo | None,
    screens: Sequence[ScreenInfo],
) -> LogicalPlacement | None:
    """Map a physical window rectangle onto the Qt screen that shows it.

    Returns ``None`` when nothing can be identified; callers must then treat
    the geometry as unknown (fail closed) rather than guess.
    """
    if rect.empty:
        return None
    index = select_screen(monitor, screens, rect)
    if index >= 0:
        screen = screens[index]
        scale = screen.dpr if screen.dpr > 0 else (monitor.scale if monitor else 1.0)
        origin = (screen.geometry.left, screen.geometry.top)
        window = physical_rect_to_logical(rect, origin, scale, origin)
        return LogicalPlacement(
            window=window,
            screen=screen.geometry,
            scale=scale,
            screen_index=index,
            screen_name=screen.name,
            physical_window=rect,
            physical_screen=monitor.rect if monitor is not None else screen.native_rect,
            dpi=monitor.dpi if monitor is not None else _round_half_up(scale * USER_DEFAULT_DPI),
        )
    if monitor is None:
        return None
    scale = monitor.scale
    origin = (monitor.rect.left, monitor.rect.top)
    window = physical_rect_to_logical(rect, origin, scale, origin)
    screen_rect = physical_rect_to_logical(monitor.rect, origin, scale, origin)
    return LogicalPlacement(
        window=window,
        screen=screen_rect,
        scale=scale,
        screen_index=-1,
        screen_name=monitor.device,
        physical_window=rect,
        physical_screen=monitor.rect,
        dpi=monitor.dpi,
    )


def overlay_position(
    window: Rect,
    screen: Rect | None,
    width: int,
    height: int,
    margin: int,
) -> tuple[int, int]:
    """Top-right HUD position, clamped to the game's screen.

    Mirrors the ``x``/``y`` bindings in ``components/PerformanceOverlay.qml``.
    """
    x = window.right - width - margin
    y = window.top + margin
    if screen is not None and not screen.empty:
        x = max(screen.left, min(x, screen.right - width))
        y = max(screen.top, min(y, screen.bottom - height))
    return x, y


# --------------------------------------------------------------------------
# Win32 adapter
# --------------------------------------------------------------------------


class _MONITORINFOEXW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("rcMonitor", wintypes.RECT),
        ("rcWork", wintypes.RECT),
        ("dwFlags", wintypes.DWORD),
        ("szDevice", wintypes.WCHAR * 32),
    ]


def _rect_from_win32(value: wintypes.RECT) -> Rect:
    return Rect(int(value.left), int(value.top), int(value.right), int(value.bottom))


def monitor_for_rect(rect: Rect) -> MonitorInfo | None:
    """Win32 monitor that holds most of ``rect`` (physical pixels)."""
    if sys.platform != "win32" or rect.empty:
        return None
    try:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.MonitorFromRect.argtypes = [ctypes.POINTER(wintypes.RECT), wintypes.DWORD]
        user32.MonitorFromRect.restype = ctypes.c_void_p
        user32.GetMonitorInfoW.argtypes = [ctypes.c_void_p, ctypes.POINTER(_MONITORINFOEXW)]
        user32.GetMonitorInfoW.restype = wintypes.BOOL
        native = wintypes.RECT(rect.left, rect.top, rect.right, rect.bottom)
        monitor = user32.MonitorFromRect(ctypes.byref(native), MONITOR_DEFAULTTONEAREST)
        if not monitor:
            return None
        info = _MONITORINFOEXW()
        info.cbSize = ctypes.sizeof(_MONITORINFOEXW)
        if not user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
            return None
        dpi = USER_DEFAULT_DPI
        try:
            shcore = ctypes.WinDLL("shcore", use_last_error=True)
            shcore.GetDpiForMonitor.argtypes = [
                ctypes.c_void_p,
                ctypes.c_int,
                ctypes.POINTER(ctypes.c_uint),
                ctypes.POINTER(ctypes.c_uint),
            ]
            shcore.GetDpiForMonitor.restype = ctypes.c_long
            dpi_x = ctypes.c_uint(0)
            dpi_y = ctypes.c_uint(0)
            if shcore.GetDpiForMonitor(
                monitor, MDT_EFFECTIVE_DPI, ctypes.byref(dpi_x), ctypes.byref(dpi_y)
            ) == 0 and dpi_x.value:
                dpi = int(dpi_x.value)
        except (AttributeError, OSError):
            pass
        return MonitorInfo(
            rect=_rect_from_win32(info.rcMonitor),
            work=_rect_from_win32(info.rcWork),
            device=str(info.szDevice),
            dpi=dpi,
        )
    except (AttributeError, OSError, TypeError, ValueError):
        return None


# --------------------------------------------------------------------------
# Qt adapter (GUI thread only)
# --------------------------------------------------------------------------


def qt_screens():
    """The application's QScreen objects, or [] without a QGuiApplication."""
    try:
        from PySide6.QtGui import QGuiApplication
    except ImportError:  # pragma: no cover - PySide6 is a hard dependency
        return []
    app = QGuiApplication.instance()
    if not isinstance(app, QGuiApplication):
        return []
    try:
        return list(QGuiApplication.screens())
    except RuntimeError:
        return []


def screen_info_from_qscreen(screen) -> ScreenInfo:
    geometry = screen.geometry()
    return ScreenInfo(
        name=str(screen.name() or ""),
        geometry=Rect.from_xywh(geometry.x(), geometry.y(), geometry.width(), geometry.height()),
        dpr=float(screen.devicePixelRatio() or 1.0),
    )


def resolve_qt_placement(rect: Rect, *, monitor: MonitorInfo | None = None, screens=None):
    """Return ``(LogicalPlacement | None, QScreen | None)`` for a physical rect.

    ``monitor`` and ``screens`` are injectable for tests; by default they come
    from Win32 and the running QGuiApplication.
    """
    if rect.empty:
        return None, None
    qscreens = qt_screens() if screens is None else list(screens)
    infos = [screen_info_from_qscreen(screen) for screen in qscreens]
    if monitor is None:
        monitor = monitor_for_rect(rect)
    placement = map_physical_rect(rect, monitor, infos)
    if placement is None:
        return None, None
    qscreen = qscreens[placement.screen_index] if placement.screen_index >= 0 else None
    return placement, qscreen
