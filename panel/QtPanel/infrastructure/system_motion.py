"""Windows "Animation effects" preference, for the panel's reduced-motion mode.

Settings > Accessibility > Visual effects > Animation effects maps to
SPI_GETCLIENTAREAANIMATION. When it is off, the panel keeps colour fades but
stops sliding, scaling and rotating its interface.
"""
from __future__ import annotations

import sys

SPI_GETCLIENTAREAANIMATION = 0x1042


def windows_animations_enabled(default: bool = True) -> bool:
    """True unless Windows reports that animation effects are turned off."""
    if sys.platform != "win32":
        return default
    try:
        import ctypes
        from ctypes import wintypes

        value = wintypes.BOOL(True)
        ok = ctypes.windll.user32.SystemParametersInfoW(
            SPI_GETCLIENTAREAANIMATION, 0, ctypes.byref(value), 0
        )
        if not ok:
            return default
        return bool(value.value)
    except Exception:
        return default
