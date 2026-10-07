'Window placement across monitors with different device-pixel ratios. Preserve native screen origins and map physical window rectangles to Qt logical coordinates before placing overlays.'




















from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Mapping, Optional, Sequence


# QML ApplicationWindow minimumWidth/minimumHeight in main.qml.
MIN_WIDTH = 720
MIN_HEIGHT = 540

SETTINGS_KEYS = (
    "windowScreen",
    "windowScreenSerial",
    "windowScreenModel",
    "windowScreenMaker",
    "windowScreenGeometry",
    "windowOffset",
    "windowLegacy",
)

_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


@dataclass(frozen=True)
class Box:
    """Integer rectangle in Qt logical pixels (x, y, width, height)."""

    x: int
    y: int
    width: int
    height: int

    @property
    def right(self) -> int:  # exclusive
        return self.x + self.width

    @property
    def bottom(self) -> int:  # exclusive
        return self.y + self.height

    @property
    def area(self) -> int:
        return max(0, self.width) * max(0, self.height)

    @property
    def center(self) -> tuple[float, float]:
        return self.x + self.width / 2.0, self.y + self.height / 2.0

    def contains_point(self, px: float, py: float) -> bool:
        return self.x <= px < self.right and self.y <= py < self.bottom

    def contains(self, other: "Box") -> bool:
        return (
            self.x <= other.x
            and self.y <= other.y
            and other.right <= self.right
            and other.bottom <= self.bottom
        )

    def intersection_area(self, other: "Box") -> int:
        width = min(self.right, other.right) - max(self.x, other.x)
        height = min(self.bottom, other.bottom) - max(self.y, other.y)
        return max(0, width) * max(0, height)

    def text(self) -> str:
        return f"{self.x},{self.y},{self.width},{self.height}"


@dataclass(frozen=True)
class ScreenDesc:
    """What Qt reports for one QScreen (geometry values are logical)."""

    name: str
    geometry: Box
    available: Box
    serial: str = ""
    model: str = ""
    manufacturer: str = ""
    dpr: float = 1.0


@dataclass(frozen=True)
class RestoredPlacement:
    """Where to put the window: its normal rect, then maximize if asked."""

    rect: Box  # normal (un-maximized) client rect, logical
    maximized: bool
    screen_index: int  # index into the screens passed to restore_placement
    source: str  # "saved-screen" | "legacy" | "fallback-primary"


def _clean(value: object) -> str:
    return _CONTROL.sub("", str(value or "")).strip()


def _parse_ints(text: object, count: int) -> Optional[tuple[int, ...]]:
    parts = [part.strip() for part in str(text or "").split(",")]
    if len(parts) != count:
        return None
    try:
        return tuple(int(part) for part in parts)
    except ValueError:
        return None


def _parse_int(text: object) -> Optional[int]:
    try:
        return int(str(text).strip())
    except (TypeError, ValueError):
        return None


def _legacy_text(left: object, top: object, width: object, height: object, maximized: object) -> str:
    return ",".join(str(value).strip() for value in (left, top, width, height, maximized))


def placement_to_settings(
    normal_rect: Box,
    normal_screen: Optional[ScreenDesc],
    maximized: bool,
    maximized_screen: Optional[ScreenDesc] = None,
) -> dict[str, str]:
    """Settings updates that describe the window's current placement.

    ``normal_rect`` is the last un-maximized client rect (absolute logical) and
    ``normal_screen`` the screen it was on. When the window is maximized on a
    different screen (moved with Win+Shift+Arrow), the same relative offset is
    recorded against that screen, which is what Windows itself restores to.
    """
    screen = maximized_screen if (maximized and maximized_screen is not None) else normal_screen
    if normal_screen is not None:
        offset_x = normal_rect.x - normal_screen.geometry.x
        offset_y = normal_rect.y - normal_screen.geometry.y
    elif screen is not None:
        offset_x = normal_rect.x - screen.geometry.x
        offset_y = normal_rect.y - screen.geometry.y
    else:
        offset_x, offset_y = normal_rect.x, normal_rect.y
    if screen is not None:
        left = screen.geometry.x + offset_x
        top = screen.geometry.y + offset_y
    else:
        left, top = normal_rect.x, normal_rect.y
    width, height = int(normal_rect.width), int(normal_rect.height)
    flag = "1" if maximized else "0"
    updates = {
        "bounds": "1",
        "left": str(int(left)),
        "top": str(int(top)),
        "width": str(width),
        "height": str(height),
        "maximized": flag,
        "windowScreen": _clean(screen.name) if screen is not None else "",
        "windowScreenSerial": _clean(screen.serial) if screen is not None else "",
        "windowScreenModel": _clean(screen.model) if screen is not None else "",
        "windowScreenMaker": _clean(screen.manufacturer) if screen is not None else "",
        "windowScreenGeometry": screen.geometry.text() if screen is not None else "",
        "windowOffset": f"{int(offset_x)},{int(offset_y)}" if screen is not None else "",
    }
    # What the legacy keys held when this build wrote them. If an older build
    # rewrites left/top/width/height later, they no longer match and win.
    updates["windowLegacy"] = _legacy_text(updates["left"], updates["top"], width, height, flag)
    return updates


def match_saved_screen(settings: Mapping[str, str], screens: Sequence[ScreenDesc]) -> int:
    """Index of the saved screen among ``screens``, or -1 when it is gone.

    Serial number first (unique per physical monitor), then the Qt name, then
    model + manufacturer; the saved logical geometry breaks remaining ties.
    Geometry alone identifies a screen only when nothing else was recorded.
    """
    if not screens:
        return -1
    serial = _clean(settings.get("windowScreenSerial"))
    name = _clean(settings.get("windowScreen"))
    model = _clean(settings.get("windowScreenModel"))
    maker = _clean(settings.get("windowScreenMaker"))
    geometry = _parse_ints(settings.get("windowScreenGeometry"), 4)
    candidates = list(range(len(screens)))
    narrowed = False

    def pick(matches: list[int]) -> Optional[int]:
        nonlocal candidates, narrowed
        if len(matches) == 1:
            return matches[0]
        if matches:
            candidates = matches
            narrowed = True
        return None

    if serial:
        found = pick([i for i in candidates if _clean(screens[i].serial) == serial])
        if found is not None:
            return found
    if name:
        found = pick([i for i in candidates if _clean(screens[i].name) == name])
        if found is not None:
            return found
    if model:
        found = pick(
            [
                i
                for i in candidates
                if _clean(screens[i].model) == model
                and (not maker or _clean(screens[i].manufacturer) == maker)
            ]
        )
        if found is not None:
            return found
    if narrowed or not (serial or name or model):
        if geometry is not None:
            box = Box(*geometry)
            for index in candidates:
                if screens[index].geometry == box:
                    return index
        if narrowed:
            return candidates[0]
    return -1


def _screen_for_rect(rect: Box, screens: Sequence[ScreenDesc]) -> int:
    """The screen that holds a legacy absolute rect (center, then overlap)."""
    cx, cy = rect.center
    for index, screen in enumerate(screens):
        if screen.geometry.contains_point(cx, cy):
            return index
    best_index, best_area = -1, 0
    for index, screen in enumerate(screens):
        area = screen.geometry.intersection_area(rect)
        if area > best_area:
            best_index, best_area = index, area
    return best_index


def _fully_visible(rect: Box, screens: Sequence[ScreenDesc], top_reserve: int) -> bool:
    """Every pixel of the client rect is on some screen's available area and
    the title bar above it is on screen too (so the window can be dragged)."""
    if rect.width <= 0 or rect.height <= 0:
        return False
    covered = sum(screen.available.intersection_area(rect) for screen in screens)
    if covered < rect.area:
        return False
    probe_x = rect.x + rect.width / 2.0
    probe_y = rect.y - max(0, int(top_reserve)) // 2
    return any(screen.available.contains_point(probe_x, probe_y) for screen in screens)


def _clamp_into(rect: Box, avail: Box, min_size: tuple[int, int], top_reserve: int) -> Box:
    reserve = max(0, min(int(top_reserve), max(0, avail.height - 1)))
    room_w = max(1, avail.width)
    room_h = max(1, avail.height - reserve)
    min_w = min(int(min_size[0]), room_w)
    min_h = min(int(min_size[1]), room_h)
    width = min(max(rect.width, min_w), room_w)
    height = min(max(rect.height, min_h), room_h)
    x = max(avail.x, min(rect.x, avail.right - width))
    y = max(avail.y + reserve, min(rect.y, avail.bottom - height))
    return Box(int(x), int(y), int(width), int(height))


def _centered_on(screen: ScreenDesc, width: int, height: int, min_size: tuple[int, int], top_reserve: int) -> Box:
    avail = screen.available
    reserve = max(0, min(int(top_reserve), max(0, avail.height - 1)))
    room_w = max(1, avail.width)
    room_h = max(1, avail.height - reserve)
    width = min(max(int(width), min(int(min_size[0]), room_w)), room_w)
    height = min(max(int(height), min(int(min_size[1]), room_h)), room_h)
    x = avail.x + (room_w - width) // 2
    y = avail.y + reserve + (room_h - height) // 2
    return Box(int(x), int(y), int(width), int(height))


def fit_on_screens(
    rect: Box,
    screen_index: int,
    screens: Sequence[ScreenDesc],
    *,
    min_size: tuple[int, int] = (MIN_WIDTH, MIN_HEIGHT),
    top_reserve: int = 0,
) -> Box:
    """``rect`` unchanged when it is fully visible, else clamped into the
    available area of ``screens[screen_index]`` (never below the QML minimum
    unless that screen is smaller)."""
    width = max(int(rect.width), int(min_size[0]))
    height = max(int(rect.height), int(min_size[1]))
    rect = Box(int(rect.x), int(rect.y), width, height)
    if _fully_visible(rect, screens, top_reserve):
        return rect
    return _clamp_into(rect, screens[screen_index].available, min_size, top_reserve)


def restore_placement(
    settings: Mapping[str, str],
    screens: Sequence[ScreenDesc],
    primary_index: int = 0,
    *,
    min_size: tuple[int, int] = (MIN_WIDTH, MIN_HEIGHT),
    top_reserve: int = 0,
) -> Optional[RestoredPlacement]:
    """Target rect, maximized flag and screen for the saved window placement.

    Returns ``None`` when nothing usable was saved (the caller keeps its
    default). ``top_reserve`` is the title-bar height (the window's top frame
    margin) that must stay on screen when a rect has to be moved.
    """
    if not screens or settings.get("bounds") != "1":
        return None
    if not 0 <= primary_index < len(screens):
        primary_index = 0
    width = _parse_int(settings.get("width"))
    height = _parse_int(settings.get("height"))
    if width is None or height is None or width <= 0 or height <= 0:
        return None
    maximized = settings.get("maximized") == "1"
    width = max(width, int(min_size[0]))
    height = max(height, int(min_size[1]))

    def fallback() -> RestoredPlacement:
        rect = _centered_on(screens[primary_index], width, height, min_size, top_reserve)
        return RestoredPlacement(rect, maximized, primary_index, "fallback-primary")

    offset = _parse_ints(settings.get("windowOffset"), 2)
    has_identity = any(
        _clean(settings.get(key))
        for key in ("windowScreen", "windowScreenSerial", "windowScreenModel", "windowScreenGeometry")
    )
    recorded = _clean(settings.get("windowLegacy"))
    current = _legacy_text(
        settings.get("left", ""), settings.get("top", ""), settings.get("width", ""),
        settings.get("height", ""), settings.get("maximized", "0") or "0",
    )
    stale = bool(recorded) and recorded != current
    if offset is not None and has_identity and not stale:
        index = match_saved_screen(settings, screens)
        if index < 0:
            return fallback()
        geo = screens[index].geometry
        rect = Box(geo.x + offset[0], geo.y + offset[1], width, height)
        rect = fit_on_screens(rect, index, screens, min_size=min_size, top_reserve=top_reserve)
        return RestoredPlacement(rect, maximized, index, "saved-screen")

    left = _parse_int(settings.get("left"))
    top = _parse_int(settings.get("top"))
    if left is None or top is None:
        return fallback()
    rect = Box(left, top, width, height)
    index = _screen_for_rect(rect, screens)
    if index < 0:
        return fallback()
    rect = fit_on_screens(rect, index, screens, min_size=min_size, top_reserve=top_reserve)
    return RestoredPlacement(rect, maximized, index, "legacy")


# Settings > Screen position: the dock modes that put the window at a fixed
# rect on its screen (Backend._apply_dock_mode), and the size floor they use.
DOCK_MODES = ("left", "right", "top", "bottom", "center")
DOCK_MIN_WIDTH = 860
DOCK_MIN_HEIGHT = 680
# Qt logical rounding on a 150 % screen can land a docked rect 1 px off.
DOCK_TOLERANCE = 2


def dock_rect(mode: str, avail: Box) -> Box | None:
    """The client rect a dock mode gives the window on a screen whose
    available area is ``avail``; ``None`` for "max", "free" and unknown
    modes (they have no fixed rect)."""
    mode = (mode or "").strip().lower()
    ax, ay, aw, ah = avail.x, avail.y, avail.width, avail.height
    side_w = min(aw, max(DOCK_MIN_WIDTH, int(aw * 0.46)))
    band_h = min(ah, max(DOCK_MIN_HEIGHT, int(ah * 0.52)))
    if mode == "left":
        return Box(ax, ay, side_w, ah)
    if mode == "right":
        return Box(ax + aw - side_w, ay, side_w, ah)
    if mode == "top":
        return Box(ax, ay, aw, band_h)
    if mode == "bottom":
        return Box(ax, ay + ah - band_h, aw, band_h)
    if mode == "center":
        w = min(aw, max(DOCK_MIN_WIDTH, min(1280, int(aw * 0.82))))
        h = min(ah, max(DOCK_MIN_HEIGHT, min(900, int(ah * 0.86))))
        return Box(ax + int((aw - w) / 2), ay + int((ah - h) / 2), w, h)
    return None


def _near(a: Box, b: Box, tolerance: int) -> bool:
    return (
        abs(a.x - b.x) <= tolerance
        and abs(a.y - b.y) <= tolerance
        and abs(a.width - b.width) <= tolerance
        and abs(a.height - b.height) <= tolerance
    )


def current_dock_mode(
    rect: Box | None,
    screen: ScreenDesc | None,
    maximized: bool,
    previous: str = "free",
) -> str:
    """What Settings > Screen position must say for the window as it is now.

    "max" while it is maximized. A side or Center mode only while the
    (un-maximized) window still sits where that mode puts it on its screen,
    the previous mode checked first; once the user moves or resizes it
    anywhere else it is "free" (2.5.504 build 3 kept saying "Left side").
    Without a rect or screen the previous mode stands.
    """
    if maximized:
        return "max"
    previous = (previous or "free").strip().lower()
    if rect is None or screen is None:
        return previous or "free"
    order = ([previous] if previous in DOCK_MODES else []) + [m for m in DOCK_MODES if m != previous]
    for mode in order:
        target = dock_rect(mode, screen.available)
        if target is not None and _near(rect, target, DOCK_TOLERANCE):
            return mode
    return "free"


def screen_from_qscreen(screen) -> ScreenDesc:
    """Qt adapter: a QScreen as a ScreenDesc (GUI thread only)."""

    def text(method: str) -> str:
        try:
            return _clean(getattr(screen, method)())
        except Exception:
            return ""

    geometry = screen.geometry()
    available = screen.availableGeometry()
    try:
        dpr = float(screen.devicePixelRatio() or 1.0)
    except Exception:
        dpr = 1.0
    return ScreenDesc(
        name=text("name"),
        geometry=Box(geometry.x(), geometry.y(), geometry.width(), geometry.height()),
        available=Box(available.x(), available.y(), available.width(), available.height()),
        serial=text("serialNumber"),
        model=text("model"),
        manufacturer=text("manufacturer"),
        dpr=dpr,
    )
