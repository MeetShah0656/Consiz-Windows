"""Trigger implementation for Windows (win32).

Uses native Win32 SetWindowsHookExW (WH_MOUSE_LL) with valid module handle and dedicated
message pump to reliably intercept and swallow middle mouse button clicks system-wide.
Also uses Win32 RegisterHotKey to register Ctrl+Alt+S at the OS kernel level,
guaranteeing it fires even when other applications have active hooks.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import threading
from typing import Callable

from pynput import keyboard

from consiz.config import CONFIG
from consiz.platform.win32.priority import set_high_priority, set_thread_high_priority

# Win32 Constants
WH_MOUSE_LL = 14
WM_MBUTTONDOWN = 0x0207
WM_MBUTTONUP = 0x0208
WM_MBUTTONDBLCLK = 0x0209
WM_HOTKEY = 0x0312
WM_QUIT = 0x0012

MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
VK_S = 0x53
VK_D = 0x44
HOTKEY_ID = 0xC001
HOTKEY_DICTATE_ID = 0xC002

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

# Function prototypes with full 64-bit types
kernel32.GetModuleHandleW.restype = wintypes.HINSTANCE
kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]

LRESULT = ctypes.c_longlong
HOOKPROC = ctypes.WINFUNCTYPE(LRESULT, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)

user32.SetWindowsHookExW.argtypes = [ctypes.c_int, HOOKPROC, wintypes.HINSTANCE, wintypes.DWORD]
user32.SetWindowsHookExW.restype = wintypes.HHOOK

user32.CallNextHookEx.argtypes = [wintypes.HHOOK, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM]
user32.CallNextHookEx.restype = LRESULT

user32.UnhookWindowsHookEx.argtypes = [wintypes.HHOOK]
user32.UnhookWindowsHookEx.restype = wintypes.BOOL

user32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
user32.RegisterHotKey.restype = wintypes.BOOL

user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
user32.UnregisterHotKey.restype = wintypes.BOOL


class Trigger:
    def __init__(
        self,
        on_fire: Callable[[str], None],
        on_busy: Callable[[], None] | None = None,
        on_dictate: Callable[[str], None] | None = None,
    ):
        self._on_fire = on_fire
        self._on_busy = on_busy
        self._on_dictate = on_dictate
        self._busy = threading.Lock()
        self._listeners: list = []
        self._hook_thread: threading.Thread | None = None
        self._hook_tid = 0
        self._mouse_hook = None
        self._mouse_cb = None
        self._running = False

    def _fire(self, source: str) -> None:
        if not self._busy.acquire(blocking=False):
            if self._on_busy:
                self._on_busy()
            return

        def run():
            try:
                self._on_fire(source)
            finally:
                self._busy.release()

        threading.Thread(target=run, name="consiz-worker", daemon=True).start()

    def _fire_dictate(self, source: str) -> None:
        if self._on_dictate is None:
            return
        if not self._busy.acquire(blocking=False):
            if self._on_busy:
                self._on_busy()
            return

        def run():
            try:
                self._on_dictate(source)
            finally:
                self._busy.release()

        threading.Thread(target=run, name="consiz-dictate-worker", daemon=True).start()

    def _mouse_hook_proc(self, nCode: int, wParam: int, lParam: int) -> int:
        if nCode >= 0:
            if wParam == WM_MBUTTONDOWN:
                self._fire("middle-click")
                return 1  # Swallow middle-click so selection is never lost
            elif wParam in (WM_MBUTTONUP, WM_MBUTTONDBLCLK):
                return 1  # Swallow release/double-click as well
        return user32.CallNextHookEx(None, nCode, wParam, lParam)

    def _run_native_event_pump(self) -> None:
        set_thread_high_priority()
        self._hook_tid = kernel32.GetCurrentThreadId()

        # 1. Register Kernel HotKeys (Ctrl+Alt+S and Ctrl+Alt+D)
        user32.RegisterHotKey(None, HOTKEY_ID, MOD_CONTROL | MOD_ALT, VK_S)
        if self._on_dictate:
            user32.RegisterHotKey(None, HOTKEY_DICTATE_ID, MOD_CONTROL | MOD_ALT, VK_D)

        # 2. Install Low-Level Mouse Hook (hmod must be None for WH_MOUSE_LL in thread)
        self._mouse_cb = HOOKPROC(self._mouse_hook_proc)
        self._mouse_hook = user32.SetWindowsHookExW(WH_MOUSE_LL, self._mouse_cb, None, 0)
        if not self._mouse_hook:
            err = kernel32.GetLastError()
            from consiz import output
            output.notify(f"Warning: Low-level mouse hook failed (Error {err}). Fallback hotkey {CONFIG.hotkey} active.")

        # 3. Dedicated message pump for hook & hotkey events
        msg = wintypes.MSG()
        while self._running and user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            if msg.message == WM_HOTKEY:
                if msg.wParam == HOTKEY_ID:
                    self._fire("hotkey")
                elif msg.wParam == HOTKEY_DICTATE_ID:
                    self._fire_dictate("dictate-hotkey")
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))

        # Cleanup
        if self._mouse_hook:
            user32.UnhookWindowsHookEx(self._mouse_hook)
            self._mouse_hook = None
        user32.UnregisterHotKey(None, HOTKEY_ID)
        user32.UnregisterHotKey(None, HOTKEY_DICTATE_ID)

    def start(self) -> None:
        self._running = True
        set_high_priority()

        # Start unified native hook & hotkey message pump
        self._hook_thread = threading.Thread(target=self._run_native_event_pump, name="consiz-native-events", daemon=True)
        self._hook_thread.start()

        # Extra fallback: pynput GlobalHotKeys
        hotkeys = {}
        if CONFIG.hotkey:
            hotkeys[CONFIG.hotkey] = lambda: self._fire("hotkey")
        if getattr(CONFIG, "dictate_hotkey", None) and self._on_dictate:
            hotkeys[CONFIG.dictate_hotkey] = lambda: self._fire_dictate("dictate-hotkey")
        if hotkeys:
            try:
                hk = keyboard.GlobalHotKeys(hotkeys)
                hk.daemon = True
                hk.start()
                self._listeners.append(hk)
            except Exception:
                pass

    def stop(self) -> None:
        self._running = False
        for l in self._listeners:
            try:
                l.stop()
            except Exception:
                pass
        self._listeners.clear()

        if self._hook_tid:
            user32.PostThreadMessageW(self._hook_tid, WM_QUIT, 0, 0)
            self._hook_tid = 0
