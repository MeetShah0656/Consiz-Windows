"""Read the visible TEXT inside one window using Windows UI Automation (Win32). Read-only.

Used only after the user allows it for that window (see consiz/pc_mode.py). It never types, clicks or changes
anything. Time- and size-boxed so a huge web page or spreadsheet cannot freeze the app.
"""
from __future__ import annotations

import time

# Control types whose Name/Value hold the text a person sees.
_TEXT_TYPES = {"TextControl", "EditControl", "DocumentControl", "ListItemControl", "DataItemControl",
               "HyperlinkControl", "ButtonControl", "TabItemControl", "MenuItemControl", "TreeItemControl",
               "HeaderItemControl", "CheckBoxControl", "RadioButtonControl", "ComboBoxControl"}
_PRIMARY = {"TextControl", "EditControl", "DocumentControl", "ListItemControl", "DataItemControl",
            "HyperlinkControl", "TreeItemControl"}
MAX_CHARS = 8000
MAX_SECONDS = 6.0
MAX_NODES = 4000


def read_window_text(hwnd: int, max_chars: int = MAX_CHARS, max_seconds: float = MAX_SECONDS) -> tuple[str, str]:
    """(text, method). `method` says how it was read: 'document', 'tree' or 'none'. Empty text = nothing readable."""
    import uiautomation as auto
    auto.SetGlobalSearchTimeout(0.5)
    deadline = time.time() + max_seconds
    try:
        win = auto.ControlFromHandle(hwnd)
    except Exception:
        return "", "none"
    if win is None:
        return "", "none"

    # 1. A document/text view that exposes its whole text (Word, Notepad, many editors, browsers' page body).
    try:
        doc = win.DocumentControl(searchDepth=12)
        if doc.Exists(0.5, 0):
            tp = doc.GetTextPattern()
            if tp is not None:
                text = (tp.DocumentRange.GetText(max_chars) or "").strip()
                if len(text) > 40:
                    return text[:max_chars], "document"
    except Exception:
        pass

    # 2. Otherwise walk the control tree and collect what is visible (spreadsheet cells, chat messages, lists).
    seen: set[str] = set()
    pieces: list[str] = []
    total = nodes = 0

    def add(s: str) -> bool:
        nonlocal total
        s = " ".join((s or "").split())
        if len(s) < 2 or s in seen:
            return True
        seen.add(s)
        pieces.append(s)
        total += len(s) + 1
        return total < max_chars

    try:
        for ctrl, _depth in auto.WalkControl(win, includeTop=False, maxDepth=14):
            nodes += 1
            if nodes > MAX_NODES or time.time() > deadline:
                break
            try:
                if ctrl.ControlTypeName not in _TEXT_TYPES or ctrl.IsOffscreen:
                    continue
                name = ctrl.Name or ""
                value = ""
                if ctrl.ControlTypeName in ("EditControl", "ComboBoxControl", "DataItemControl"):
                    try:
                        value = ctrl.GetValuePattern().Value or ""
                    except Exception:
                        value = ""
                if ctrl.ControlTypeName in _PRIMARY or value:
                    if not add(value or name):
                        break
            except Exception:
                continue
    except Exception:
        pass
    text = "\n".join(pieces)[:max_chars]
    return text, ("tree" if text else "none")


# ---------------------------------------------------------------- picture of a window (for apps that hide their text)
def capture_window_jpeg_b64(hwnd: int, max_side: int = 1400, quality: int = 72) -> str | None:
    """A JPEG picture of ONE window as base64, or None (minimized, empty, or blocked by the app).
    Uses PrintWindow, so it works even if other windows cover it; the picture never touches the disk."""
    import base64
    import ctypes
    import io
    from ctypes import wintypes

    from PIL import Image

    user32, gdi32 = ctypes.windll.user32, ctypes.windll.gdi32
    if not user32.IsWindow(hwnd) or user32.IsIconic(hwnd):
        return None

    class BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG), ("biHeight", wintypes.LONG),
                    ("biPlanes", wintypes.WORD), ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                    ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG),
                    ("biYPelsPerMeter", wintypes.LONG), ("biClrUsed", wintypes.DWORD),
                    ("biClrImportant", wintypes.DWORD)]

    r = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(r))
    w, h = r.right - r.left, r.bottom - r.top
    if w < 50 or h < 50 or w * h > 40_000_000:
        return None
    hdc = user32.GetWindowDC(hwnd)
    mem = gdi32.CreateCompatibleDC(hdc)
    bmp = gdi32.CreateCompatibleBitmap(hdc, w, h)
    try:
        gdi32.SelectObject(mem, bmp)
        if not user32.PrintWindow(hwnd, mem, 2):          # 2 = PW_RENDERFULLCONTENT (GPU-drawn web pages too)
            return None
        bi = BITMAPINFOHEADER(ctypes.sizeof(BITMAPINFOHEADER), w, -h, 1, 32, 0)
        buf = ctypes.create_string_buffer(w * h * 4)
        gdi32.GetDIBits(mem, bmp, 0, h, buf, ctypes.byref(bi), 0)
    finally:
        gdi32.DeleteObject(bmp)
        gdi32.DeleteDC(mem)
        user32.ReleaseDC(hwnd, hdc)
    img = Image.frombuffer("RGBA", (w, h), buf, "raw", "BGRA", 0, 1).convert("RGB")
    if all(hi < 6 for _lo, hi in img.getextrema()):       # a blank (all-black) capture means the app blocked it
        return None
    if max(img.size) > max_side:
        scale = max_side / max(img.size)
        img = img.resize((max(1, int(img.width * scale)), max(1, int(img.height * scale))))
    out = io.BytesIO()
    img.save(out, format="JPEG", quality=quality, optimize=True)
    return base64.b64encode(out.getvalue()).decode("ascii")
