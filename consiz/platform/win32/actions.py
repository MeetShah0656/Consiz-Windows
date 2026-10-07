"""Windows executor for the whitelisted actions in consiz/pc_actions.py. Opens things; changes nothing."""
from __future__ import annotations

import ctypes
import os
from pathlib import Path

user32 = ctypes.windll.user32
SW_RESTORE = 9


def launch(target: str) -> tuple[bool, str]:
    """Open a Settings page, Task Manager, Disk Cleanup or the Downloads folder (targets come from the whitelist)."""
    if target == "downloads":
        target = str(Path.home() / "Downloads")
    os.startfile(target)                                       # noqa: S606 - target is whitelisted, never user/model text
    return True, "Opened."


def focus(hwnd: int) -> tuple[bool, str]:
    """Bring an existing window to the front (restores it if minimized)."""
    if not user32.IsWindow(hwnd):
        return False, "That window is closed now."
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, SW_RESTORE)
    user32.SetForegroundWindow(hwnd)
    return True, "Switched."
