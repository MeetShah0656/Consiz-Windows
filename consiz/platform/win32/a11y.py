"""Accessibility helpers (T-17): keyboard use, Windows' text size, high contrast, names for screen readers.

What this gives, honestly:
  - Keyboard: every button in the answer window can be reached with Tab and pressed with Enter or Space, and shows a focus ring.
  - Text size: the Windows setting "Text size" (Settings > Accessibility) is followed; fonts AND window sizes grow together.
  - High contrast: when a Windows high-contrast theme is on, Consiz uses the theme's own colours (read when Consiz starts).
  - Names: the windows and buttons get a name that screen readers can read (the Win32 window text).
What it cannot give: Tk (the toolkit under the windows) does not expose buttons, states or live text to screen readers the
way a native control does, so Narrator and NVDA can read the names but will not announce an answer as it streams in.
See docs/ACCESSIBILITY.md.
"""
from __future__ import annotations

import ctypes
import os
import sys
from ctypes import wintypes

SPI_GETHIGHCONTRAST = 0x0042
SPI_GETSCREENREADER = 0x0046
HCF_HIGHCONTRASTON = 0x00000001
FOCUS_RING = "#A84D59"                       # the same colour as theme.FOCUS_RING (theme imports this module, not the reverse)

_cache: dict = {}


class _HIGHCONTRAST(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.UINT), ("dwFlags", wintypes.DWORD), ("lpszDefaultScheme", wintypes.LPWSTR)]


def high_contrast() -> bool:
    """A Windows high-contrast theme is on (CONSIZ_HIGH_CONTRAST=1/0 overrides, for testing)."""
    override = os.environ.get("CONSIZ_HIGH_CONTRAST")
    if override in ("0", "1"):
        return override == "1"
    if sys.platform != "win32":
        return False
    try:
        hc = _HIGHCONTRAST(ctypes.sizeof(_HIGHCONTRAST), 0, None)
        ctypes.windll.user32.SystemParametersInfoW(SPI_GETHIGHCONTRAST, hc.cbSize, ctypes.byref(hc), 0)
        return bool(hc.dwFlags & HCF_HIGHCONTRASTON)
    except Exception:
        return False


def screen_reader_running() -> bool:
    """Windows says an assistive program (Narrator, NVDA, JAWS) is running."""
    if sys.platform != "win32":
        return False
    try:
        flag = wintypes.BOOL(0)
        ctypes.windll.user32.SystemParametersInfoW(SPI_GETSCREENREADER, 0, ctypes.byref(flag), 0)
        return bool(flag.value)
    except Exception:
        return False


def text_scale() -> float:
    """Windows' 'Text size' setting as 1.0 ... 2.25 (CONSIZ_TEXT_SCALE overrides, for testing). Read once per run."""
    if "text_scale" in _cache:
        return _cache["text_scale"]
    value = 1.0
    try:
        override = float(os.environ.get("CONSIZ_TEXT_SCALE", "0"))
    except ValueError:
        override = 0.0
    if override > 0:
        value = override
    elif sys.platform == "win32":
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Accessibility") as key:
                percent = int(winreg.QueryValueEx(key, "TextScaleFactor")[0])
            value = percent / 100.0
        except (OSError, ValueError):
            value = 1.0
    _cache["text_scale"] = min(max(value, 1.0), 2.25)
    return _cache["text_scale"]


def popup_takes_focus() -> bool:
    """Should the answer window take the keyboard focus when it opens? Off by default (the person's own app keeps
    the focus), on by default while a screen reader runs. Settings > General > Accessibility changes it."""
    from consiz import prefs
    setting = prefs.get("popup_takes_focus")
    return bool(setting) if setting is not None else screen_reader_running()


def apply_to_root(root) -> None:
    """Follow Windows' text size in every font (once per run) and give focus rings a visible colour."""
    if _cache.get("applied"):
        return
    _cache["applied"] = True
    try:
        factor = text_scale()
        if factor != 1.0:
            root.tk.call("tk", "scaling", float(root.tk.call("tk", "scaling")) * factor)
        root.option_add("*Button.highlightColor", FOCUS_RING)
        root.option_add("*Checkbutton.highlightColor", FOCUS_RING)
        root.option_add("*Radiobutton.highlightColor", FOCUS_RING)
    except Exception:
        pass


def set_name(widget, name: str) -> None:
    """The name a screen reader reads for this control: the Win32 window text of the widget's window."""
    if sys.platform != "win32":
        return
    try:
        user32 = ctypes.windll.user32
        hwnd = widget.winfo_id()
        if widget.winfo_toplevel() is widget:                    # a Tk window sits inside the real top-level window
            hwnd = user32.GetParent(hwnd) or hwnd
        user32.SetWindowTextW(wintypes.HWND(hwnd), name)
    except Exception:
        pass


def make_clickable(widget, command, name: str | None = None) -> None:
    """A label that works as a button: reachable with Tab, pressed with Enter or Space, with a visible focus ring."""
    normal_bg = widget.cget("bg")
    widget.configure(takefocus=True, highlightthickness=2, highlightbackground=normal_bg, highlightcolor=FOCUS_RING)

    def press(_event=None):
        command()
        return "break"

    widget.bind("<Return>", press)
    widget.bind("<space>", press)
    if name:
        set_name(widget, name)
