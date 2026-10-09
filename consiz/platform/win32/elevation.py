"""Windows that run "as administrator" cannot be read by a normal program (UIPI blocks its input and its screen text), so
Consiz must say so instead of silently finding nothing (T-16).

Consiz itself runs as a normal user on purpose. The fix for the person is to start Consiz as administrator.
"""
from __future__ import annotations

import ctypes
import os
from ctypes import wintypes

kernel32 = ctypes.windll.kernel32
advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
user32 = ctypes.windll.user32

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
TOKEN_QUERY = 0x0008
TOKEN_ELEVATION = 20                    # TOKEN_INFORMATION_CLASS.TokenElevation
ERROR_ACCESS_DENIED = 5

kernel32.OpenProcess.restype = wintypes.HANDLE
kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
advapi32.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
advapi32.GetTokenInformation.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD,
                                         ctypes.POINTER(wintypes.DWORD)]

ELEVATED_NOTE = ("{app} is running as administrator, so Consiz cannot read it. To use Consiz there, close Consiz and "
                 "start it with a right-click on Consiz.exe > Run as administrator.")      # shown through i18n.tf in capture


def process_is_elevated(pid: int) -> bool | None:
    """True / False for "runs with administrator rights"; None when it cannot be told (a protected system process)."""
    process = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not process:
        return None
    try:
        token = wintypes.HANDLE()
        if not advapi32.OpenProcessToken(process, TOKEN_QUERY, ctypes.byref(token)):
            # A normal program is refused the token of an elevated one: that refusal is itself the answer.
            return True if ctypes.get_last_error() == ERROR_ACCESS_DENIED or kernel32.GetLastError() == ERROR_ACCESS_DENIED \
                else None
        try:
            elevation = wintypes.DWORD(0)
            size = wintypes.DWORD(0)
            if not advapi32.GetTokenInformation(token, TOKEN_ELEVATION, ctypes.byref(elevation), ctypes.sizeof(elevation),
                                                ctypes.byref(size)):
                return None
            return bool(elevation.value)
        finally:
            kernel32.CloseHandle(token)
    finally:
        kernel32.CloseHandle(process)


def window_needs_admin(hwnd: int) -> bool:
    """True when the window belongs to an administrator process and Consiz is not one (so it cannot read it)."""
    if not hwnd:
        return False
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    if not pid.value or pid.value == os.getpid():
        return False
    from .priority import is_admin
    if is_admin():
        return False
    return process_is_elevated(pid.value) is True
