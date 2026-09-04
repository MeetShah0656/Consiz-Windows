"""Context Capture Layer (spec §5.1), macOS.

Order: Finder selection (paths) → Accessibility API selected text → clipboard fallback (simulate ⌘C, read, restore).
"""
from __future__ import annotations

import subprocess
import time

from AppKit import NSURL, NSPasteboard, NSPasteboardTypeString, NSPasteboardURLReadingFileURLsOnlyKey, NSWorkspace
from ApplicationServices import (
    AXUIElementCopyAttributeValue,
    AXUIElementCreateSystemWide,
    kAXFocusedUIElementAttribute,
    kAXSelectedTextAttribute,
)
from Quartz import (
    CGEventCreateKeyboardEvent,
    CGEventPost,
    CGEventSetFlags,
    kCGEventFlagMaskCommand,
    kCGHIDEventTap,
)

from .config import CONFIG
from .models import CapturedContext, CaptureMethod

_KEY_C = 8  # kVK_ANSI_C


def frontmost_app() -> str:
    app = NSWorkspace.sharedWorkspace().frontmostApplication()
    return app.localizedName() if app else "unknown"


# ---------------------------------------------------------------- Finder
_FINDER_SCRIPT = '''
tell application "Finder"
    set sel to selection
    set out to ""
    repeat with itm in sel
        set out to out & (POSIX path of (itm as alias)) & linefeed
    end repeat
    return out
end tell
'''


def finder_selection() -> list[str]:
    try:
        r = subprocess.run(["osascript", "-e", _FINDER_SCRIPT], capture_output=True, text=True, timeout=3)
    except (subprocess.TimeoutExpired, OSError):
        return []
    if r.returncode != 0:
        return []
    return [p.rstrip("/") if len(p) > 1 else p for p in r.stdout.splitlines() if p.strip()]


# ---------------------------------------------------------------- Accessibility
def ax_selected_text() -> str:
    try:
        system = AXUIElementCreateSystemWide()
        err, focused = AXUIElementCopyAttributeValue(system, kAXFocusedUIElementAttribute, None)
        if err != 0 or focused is None:
            return ""
        err, text = AXUIElementCopyAttributeValue(focused, kAXSelectedTextAttribute, None)
        if err != 0 or not text:
            return ""
        return str(text)
    except Exception:
        return ""


# ---------------------------------------------------------------- Clipboard fallback
def _press_cmd_c() -> None:
    for down in (True, False):
        ev = CGEventCreateKeyboardEvent(None, _KEY_C, down)
        CGEventSetFlags(ev, kCGEventFlagMaskCommand)
        CGEventPost(kCGHIDEventTap, ev)


def _clipboard_file_paths(pb) -> list[str]:
    """If the clipboard holds file URLs (Finder/Desktop copy), return their POSIX paths."""
    paths: list[str] = []
    try:
        urls = pb.readObjectsForClasses_options_([NSURL], {NSPasteboardURLReadingFileURLsOnlyKey: True}) or []
        paths = [u.path() for u in urls if u.path()]
    except Exception:
        pass
    return [p.rstrip("/") if len(p) > 1 else p for p in paths]


def clipboard_fallback() -> tuple[str, list[str]]:
    """Return (text, file_paths). Exactly one of them is normally non-empty."""
    pb = NSPasteboard.generalPasteboard()
    previous = pb.stringForType_(NSPasteboardTypeString)
    pb.clearContents()
    _press_cmd_c()
    time.sleep(CONFIG.clipboard_settle_s)
    paths = _clipboard_file_paths(pb)
    captured = pb.stringForType_(NSPasteboardTypeString) or ""
    # restore what the user had (string content only — images etc. are not preserved)
    pb.clearContents()
    if previous is not None:
        pb.setString_forType_(previous, NSPasteboardTypeString)
    return captured, paths


def _looks_like_address_bar(text: str) -> bool:
    t = text.strip()
    return bool(t) and "\n" not in t and " " not in t and t.lower().startswith(("http://", "https://", "file://"))


def _path_context(app: str, paths: list[str]) -> CapturedContext:
    import os
    method = CaptureMethod.FOLDER_PATH if os.path.isdir(paths[0]) else CaptureMethod.FILE_PATH
    return CapturedContext(source_app=app, capture_method=method, raw_content=paths[0], paths=paths)


# ---------------------------------------------------------------- entry
def capture() -> CapturedContext:
    app = frontmost_app()

    if app == "Finder":
        paths = finder_selection()
        if paths:
            return _path_context(app, paths)

    text = ax_selected_text()
    if _looks_like_address_bar(text):
        text = ""          # focus was in the browser's address bar — fall through to the clipboard path
    if text.strip():
        return CapturedContext(source_app=app, capture_method=CaptureMethod.TEXT_SELECTION, raw_content=text)

    text, paths = clipboard_fallback()
    if paths:                       # Finder / Desktop item copied as file URL(s)
        return _path_context(app, paths)
    if _looks_like_address_bar(text):
        # ⌘C copied the browser's URL: focus was in the address bar, not the page. Treat as no selection.
        return CapturedContext(source_app=app, capture_method=CaptureMethod.NONE, raw_content="",
                               paths=[], note="address bar was copied — click into the page text and reselect")
    if text.strip():
        return CapturedContext(source_app=app, capture_method=CaptureMethod.CLIPBOARD_FALLBACK, raw_content=text)

    return CapturedContext(source_app=app, capture_method=CaptureMethod.NONE, raw_content="")
