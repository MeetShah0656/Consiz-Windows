"""Sharp text on every Windows scale setting, and windows that open on the screen the user is looking at (T-06).

Before: Consiz was DPI-unaware, so Windows stretched its windows as a bitmap (blurry at 125 % / 150 %), and the popup
was placed using the PRIMARY screen only (it could open on the wrong monitor or run off the edge of a second one).

Now: the process is system-DPI aware (crisp on the main screen; a second screen with a different scale is stretched
by Windows, still the right size). Fixed pixel sizes go through px(); everything measured in points (all fonts)
already scales by itself. Window placement uses the work area (screen minus taskbar) of the monitor under the cursor.
"""
from __future__ import annotations

import ctypes
import os
from ctypes import wintypes

_state = {"done": False, "scale": 1.0}
MONITOR_DEFAULTTONEAREST = 2


def enable() -> None:
    """Make the process DPI aware. Idempotent; must run before the first window is created."""
    if _state["done"]:
        return
    _state["done"] = True
    user32 = ctypes.windll.user32
    try:                                                    # -2 = DPI_AWARENESS_CONTEXT_SYSTEM_AWARE
        user32.SetProcessDpiAwarenessContext.argtypes = [ctypes.c_void_p]
        ok = bool(user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-2)))
    except Exception:
        ok = False
    if not ok:
        try:
            ok = ctypes.windll.shcore.SetProcessDpiAwareness(1) == 0
        except Exception:
            ok = False
    if not ok:
        try:
            user32.SetProcessDPIAware()
        except Exception:
            pass
    try:
        dpi = user32.GetDpiForSystem()                      # 96 when Windows is still virtualising us
    except Exception:
        dpi = 96
    _state["scale"] = max(1.0, dpi / 96.0)


def scale() -> float:
    """1.0 at 100 %, 1.25 at 125 %, 1.5 at 150 %... (CONSIZ_UI_SCALE overrides, for testing)."""
    enable()
    try:
        override = float(os.environ.get("CONSIZ_UI_SCALE", "0"))
    except ValueError:
        override = 0.0
    if override > 0:
        return override
    from . import a11y
    return _state["scale"] * a11y.text_scale()           # Windows' "Text size": fonts (tk scaling) and these sizes grow together


def px(n: float) -> int:
    """A size in 100 %-scale pixels, converted for this screen."""
    return int(round(n * scale()))


class _MONITORINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT), ("rcWork", wintypes.RECT),
                ("dwFlags", wintypes.DWORD)]


def work_area_at(x: int, y: int) -> tuple[int, int, int, int]:
    """(left, top, right, bottom) of the usable area (screen minus taskbar) of the monitor nearest to the point.
    Coordinates may be negative (a monitor to the left of / above the main one)."""
    user32 = ctypes.windll.user32
    try:
        user32.MonitorFromPoint.argtypes = [wintypes.POINT, wintypes.DWORD]
        user32.MonitorFromPoint.restype = ctypes.c_void_p
        user32.GetMonitorInfoW.argtypes = [ctypes.c_void_p, ctypes.POINTER(_MONITORINFO)]
        user32.GetMonitorInfoW.restype = wintypes.BOOL
        mon = user32.MonitorFromPoint(wintypes.POINT(int(x), int(y)), MONITOR_DEFAULTTONEAREST)
        info = _MONITORINFO()
        info.cbSize = ctypes.sizeof(_MONITORINFO)
        if mon and user32.GetMonitorInfoW(mon, ctypes.byref(info)):
            r = info.rcWork
            return r.left, r.top, r.right, r.bottom
    except Exception:
        pass
    return 0, 0, user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)       # fall back to the primary screen


def fit_size(size: tuple[int, int], area: tuple[int, int, int, int], fraction: float = 0.92) -> tuple[int, int]:
    """A window size that fits the screen it opens on: never more than `fraction` of the usable width/height."""
    w, h = size
    left, top, right, bottom = area
    return min(w, int((right - left) * fraction)), min(h, int((bottom - top) * fraction))


def place_near(point: tuple[int, int], size: tuple[int, int], area: tuple[int, int, int, int],
               gap: int = 15, margin: int = 10) -> tuple[int, int]:
    """Top-left for a window of `size` just below-right of `point`, kept fully inside `area`
    (a window larger than the area is pinned to its top-left corner)."""
    px_, py_ = point
    w, h = size
    left, top, right, bottom = area
    x = min(max(px_ + gap, left + margin), right - w - margin)
    y = min(max(py_ + gap, top + margin), bottom - h - margin)
    return max(x, left), max(y, top)
