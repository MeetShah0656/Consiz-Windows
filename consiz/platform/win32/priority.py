"""Process priority and Administrator elevation helpers for Windows (win32)."""
from __future__ import annotations

import ctypes
import os
import sys

kernel32 = ctypes.windll.kernel32
shell32 = ctypes.windll.shell32
user32 = ctypes.windll.user32

HIGH_PRIORITY_CLASS = 0x00000080
REALTIME_PRIORITY_CLASS = 0x00000100
THREAD_PRIORITY_HIGHEST = 2
THREAD_PRIORITY_TIME_CRITICAL = 15
MSGFLT_ALLOW = 1
WM_HOTKEY = 0x0312


def is_admin() -> bool:
    """Checks if the current process has elevated Administrator privileges."""
    try:
        return shell32.IsUserAnAdmin() != 0
    except Exception:
        return False


def set_high_priority() -> None:
    """Sets the process priority to HIGH and unblocks UIPI message filters."""
    try:
        # Set process priority to HIGH so no normal application can starve or override hooks
        kernel32.SetPriorityClass(kernel32.GetCurrentProcess(), HIGH_PRIORITY_CLASS)
    except Exception:
        pass

    try:
        # Allow WM_HOTKEY to bypass UIPI (User Interface Privilege Isolation)
        user32.ChangeWindowMessageFilter(WM_HOTKEY, MSGFLT_ALLOW)
    except Exception:
        pass


def set_thread_high_priority() -> None:
    """Sets the calling thread to highest priority for real-time hook processing."""
    try:
        kernel32.SetThreadPriority(kernel32.GetCurrentThread(), THREAD_PRIORITY_HIGHEST)
    except Exception:
        pass


def request_admin_elevation() -> bool:
    """If not running as admin, launches an elevated instance and exits the non-elevated one."""
    if is_admin():
        return True

    params = " ".join([f'"{arg}"' for arg in sys.argv])
    ret = shell32.ShellExecuteW(None, "runas", sys.executable, params, None, 1)
    if ret > 32:
        sys.exit(0)
    return False
