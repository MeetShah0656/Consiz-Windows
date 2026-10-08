"""Trigger implementation for Windows (win32).

Uses native Win32 SetWindowsHookExW (WH_MOUSE_LL) with valid module handle and dedicated
message pump to reliably intercept and swallow middle mouse button clicks system-wide.
Also uses Win32 RegisterHotKey to register Ctrl+Alt+S at the OS kernel level,
guaranteeing it fires even when other applications have active hooks.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import os
import threading
import time
from typing import Callable

import psutil
from pynput import keyboard

from consiz import pause, prefs
from consiz.config import CONFIG
from consiz.platform.win32 import mousegate
from consiz.platform.win32.priority import set_high_priority, set_thread_high_priority

PASSTHROUGH = "passthrough"     # an on_fire handler returns this when nothing was selected: re-send the click

# Win32 Constants
WH_MOUSE_LL = 14
WM_MBUTTONDOWN = 0x0207
WM_MBUTTONUP = 0x0208
WM_MBUTTONDBLCLK = 0x0209
WM_MOUSEMOVE = 0x0200
MOUSEEVENTF_MIDDLEDOWN = 0x0020
MOUSEEVENTF_MIDDLEUP = 0x0040
VK_CONTROL = 0x11
OWN_EVENT = 0x434F4E53          # "CONS": marks clicks Consiz re-sends, so its own hook ignores them
WM_HOTKEY = 0x0312
WM_QUIT = 0x0012
WM_PAUSE_CHANGED = 0x8001      # WM_APP + 1: wakes the message pump so hotkeys are released/re-taken at once

MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008

HOTKEY_ID = 0xC001
HOTKEY_DICTATE_ID = 0xC002
HOTKEY_PC_ID = 0xC003

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

user32.mouse_event.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, ctypes.c_size_t]
user32.mouse_event.restype = None
user32.GetForegroundWindow.restype = wintypes.HWND
user32.PostThreadMessageW.argtypes = [wintypes.DWORD, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.PostThreadMessageW.restype = wintypes.BOOL
user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
user32.GetAsyncKeyState.restype = ctypes.c_short


class MSLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [("pt", wintypes.POINT), ("mouseData", wintypes.DWORD), ("flags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


def parse_hotkey_to_win32(hotkey_str: str) -> tuple[int, int] | None:
    """Parses a pynput-style hotkey string into Win32 (modifiers, virtual_key)."""
    if not hotkey_str:
        return None
    parts = [p.strip().lower() for p in hotkey_str.split("+") if p.strip()]
    mods = 0
    vk = None
    for part in parts:
        if part in ("<ctrl>", "<control>", "ctrl", "control"):
            mods |= MOD_CONTROL
        elif part in ("<alt>", "alt"):
            mods |= MOD_ALT
        elif part in ("<shift>", "shift"):
            mods |= MOD_SHIFT
        elif part in ("<cmd>", "<win>", "<super>", "win"):
            mods |= MOD_WIN
        else:
            key_name = part.strip("<> ")
            if len(key_name) == 1:
                vk = ord(key_name.upper())
            elif key_name.startswith("f") and key_name[1:].isdigit() and 1 <= int(key_name[1:]) <= 24:
                vk = 0x70 + (int(key_name[1:]) - 1)
            elif key_name == "space":
                vk = 0x20
            else:
                return None
    if vk is None:
        return None
    return mods, vk


_PERMANENT_HOOK_CB = None


class Trigger:
    def __init__(
        self,
        on_fire: Callable[[str], None],
        on_busy: Callable[[], None] | None = None,
        on_dictate: Callable[[str], None] | None = None,
        on_pc: Callable[[str], None] | None = None,
    ):
        self._on_pc = on_pc
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
        self._native_ready = threading.Event()
        self._native_registered: set[str] = set()
        self._last_middle_click_time = 0.0
        self._gate = mousegate.MiddleGate()
        self._fg_names: dict[int, str] = {}
        self._hotkey_defs: list[tuple[int, str, str, str]] = []     # (id, name, hotkey text, what it fires)
        self._hotkeys_on = False
        self._load_gate_settings()
        pause.on_change(lambda _p: self._wake_pump())

    # ------------------------------------------------------------------ settings (re-read every few seconds)
    def _load_gate_settings(self) -> None:
        mode = os.environ.get("CONSIZ_TRIGGER_MODE") or prefs.get("trigger_mode")
        self._gate.settings = mousegate.GateSettings.build(mode, prefs.get("trigger_excluded_apps"))
        CONFIG.trigger_mode = self._gate.settings.mode            # shown in "Copy diagnostics"

    def _apply_hook_mode(self) -> None:
        """Hotkey-only mode must not hook the mouse at all; switch it on/off when the setting changes."""
        wants_hook = self._gate.settings.mode != "hotkey"
        if wants_hook and not self._mouse_hook and self._mouse_cb:
            self._install_mouse_hook()
        elif not wants_hook and self._mouse_hook:
            user32.UnhookWindowsHookEx(self._mouse_hook)
            self._mouse_hook = None

    # ------------------------------------------------------------------ pause (T-10)
    def _mouse_paused(self) -> bool:
        """Paused by the user, or (setting, on by default) a full-screen app is in front."""
        if pause.is_paused():
            return True
        if prefs.get("pause_in_fullscreen", True):
            from consiz.platform.win32.fullscreen import foreground_is_fullscreen
            return foreground_is_fullscreen()
        return False

    def _wake_pump(self) -> None:
        if self._hook_tid:
            user32.PostThreadMessageW(self._hook_tid, WM_PAUSE_CHANGED, 0, 0)

    def _sync_hotkeys(self) -> None:
        """Runs on the pump thread (RegisterHotKey belongs to the thread that made it). Paused = keys are released,
        so the app in front gets Ctrl+Alt+S / Ctrl+Alt+A itself."""
        want = not pause.is_paused()
        if want == self._hotkeys_on:
            return
        for hk_id, name, text, _what in self._hotkey_defs:
            if want:
                parsed = parse_hotkey_to_win32(text)
                if parsed and user32.RegisterHotKey(None, hk_id, parsed[0], parsed[1]):
                    self._native_registered.add(name)
            elif name in self._native_registered:
                user32.UnregisterHotKey(None, hk_id)
                self._native_registered.discard(name)
        self._hotkeys_on = want

    # ------------------------------------------------------------------ firing
    def _fire(self, source: str) -> None:
        if pause.is_paused() and source != "tray":
            return
        if not self._busy.acquire(blocking=False):
            if self._on_busy:
                self._on_busy()
            return

        def run():
            result = None
            try:
                result = self._on_fire(source)
            except Exception:
                from consiz import logs
                logs.exception("trigger handler")
                result = PASSTHROUGH if source == "middle-click" else None   # never lose the user's click on a bug
            finally:
                self._busy.release()
            if result == PASSTHROUGH and source == "middle-click":
                self._inject_click()            # nothing was selected: the app gets the click it was meant to get

        threading.Thread(target=run, name="consiz-worker", daemon=True).start()

    def _inject_click(self) -> None:
        user32.mouse_event(MOUSEEVENTF_MIDDLEDOWN, 0, 0, 0, OWN_EVENT)
        user32.mouse_event(MOUSEEVENTF_MIDDLEUP, 0, 0, 0, OWN_EVENT)

    def _inject_down(self) -> None:
        user32.mouse_event(MOUSEEVENTF_MIDDLEDOWN, 0, 0, 0, OWN_EVENT)

    def _foreground_app(self) -> str:
        """Lower-case exe name of the window under the user's hands (cached per process id; fast)."""
        try:
            hwnd = user32.GetForegroundWindow()
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            name = self._fg_names.get(pid.value)
            if name is None:
                if len(self._fg_names) > 64:
                    self._fg_names.clear()
                name = self._fg_names[pid.value] = psutil.Process(pid.value).name().lower()
            return name
        except Exception:
            return ""

    def _fire_dictate(self, source: str) -> None:
        if self._on_dictate is None or pause.is_paused():
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

    def _fire_pc(self, source: str) -> None:
        if self._on_pc is None or pause.is_paused():
            return
        # Opening the PC chat is quick; the slow snapshot runs later on the ask worker, so no busy lock here.
        threading.Thread(target=self._on_pc, args=(source,), name="consiz-pc-worker", daemon=True).start()

    def _mouse_hook_proc(self, nCode: int, wParam: int, lParam: int) -> int:
        """Runs for every mouse event on the system, so it must be fast and must never raise."""
        if nCode >= 0 and wParam in (WM_MBUTTONDOWN, WM_MBUTTONUP, WM_MBUTTONDBLCLK, WM_MOUSEMOVE):
            try:
                if wParam == WM_MOUSEMOVE and not self._gate.pending:
                    return user32.CallNextHookEx(None, nCode, wParam, lParam)
                info = ctypes.cast(lParam, ctypes.POINTER(MSLLHOOKSTRUCT)).contents
                if info.dwExtraInfo == OWN_EVENT:                  # a click Consiz re-sent: let it through
                    return user32.CallNextHookEx(None, nCode, wParam, lParam)
                now = time.time()
                if wParam == WM_MBUTTONDOWN:
                    ctrl = bool(user32.GetAsyncKeyState(VK_CONTROL) & 0x8000)
                    act = self._gate.down(info.pt.x, info.pt.y, ctrl, self._foreground_app(), now, self._mouse_paused())
                elif wParam == WM_MOUSEMOVE:
                    act = self._gate.move(info.pt.x, info.pt.y, now)
                elif wParam == WM_MBUTTONUP:
                    act = self._gate.up(now)
                else:
                    act = self._gate.double_click()

                if act is mousegate.Act.SWALLOW:
                    return 1
                if act is mousegate.Act.FIRE:
                    # W-02: never block the hook thread; the worker re-sends the click if nothing was selected
                    threading.Thread(target=self._fire, args=("middle-click",), daemon=True).start()
                    return 1
                if act is mousegate.Act.DRAG:
                    # The "click" became a drag (autoscroll, panning): give the app its button press back
                    threading.Thread(target=self._inject_down, daemon=True).start()
            except Exception:
                pass                                              # a bug here must never freeze the mouse
        return user32.CallNextHookEx(None, nCode, wParam, lParam)

    def _install_mouse_hook(self) -> None:
        """Installs or refreshes the WH_MOUSE_LL hook (W-02)."""
        hmod = kernel32.GetModuleHandleW(None)
        new_hook = user32.SetWindowsHookExW(WH_MOUSE_LL, self._mouse_cb, hmod, 0)
        if new_hook:
            old_hook = self._mouse_hook
            self._mouse_hook = new_hook
            if old_hook:
                try:
                    user32.UnhookWindowsHookEx(old_hook)
                except Exception:
                    pass

    def _run_native_event_pump(self) -> None:
        global _PERMANENT_HOOK_CB
        set_thread_high_priority()
        self._hook_tid = kernel32.GetCurrentThreadId()

        # 1. Register Kernel HotKeys dynamically from CONFIG (released while Consiz is paused)
        self._hotkey_defs = [(HOTKEY_ID, "hotkey", CONFIG.hotkey, "explain")]
        if self._on_dictate and getattr(CONFIG, "dictate_hotkey", ""):
            self._hotkey_defs.append((HOTKEY_DICTATE_ID, "dictate", CONFIG.dictate_hotkey, "dictate"))
        if self._on_pc and getattr(CONFIG, "pc_hotkey", ""):
            self._hotkey_defs.append((HOTKEY_PC_ID, "pc", CONFIG.pc_hotkey, "pc"))
        self._hotkeys_on = False
        self._sync_hotkeys()

        # 2. Install Low-Level Mouse Hook with global permanent callback reference
        self._mouse_cb = HOOKPROC(self._mouse_hook_proc)
        _PERMANENT_HOOK_CB = self._mouse_cb
        if self._gate.settings.mode != "hotkey":
            self._install_mouse_hook()
        if self._gate.settings.mode != "hotkey" and not self._mouse_hook:
            err = kernel32.GetLastError()
            from consiz import output
            output.notify(f"Warning: Low-level mouse hook failed (Error {err}). Fallback hotkey {CONFIG.hotkey} active.")

        # Set a 3-second watchdog timer to refresh hook in case Windows drops slow hooks (W-02)
        user32.SetTimer(None, 0x5001, 3000, None)
        self._native_ready.set()

        # 3. Dedicated message pump for hook, timer, & hotkey events
        msg = wintypes.MSG()
        while self._running and user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            if msg.message == WM_HOTKEY:
                if msg.wParam == HOTKEY_ID:
                    self._fire("hotkey")
                elif msg.wParam == HOTKEY_DICTATE_ID:
                    self._fire_dictate("dictate-hotkey")
                elif msg.wParam == HOTKEY_PC_ID:
                    self._fire_pc("pc-hotkey")
            elif msg.message == WM_PAUSE_CHANGED:
                self._sync_hotkeys()
            elif msg.message == 0x0113:  # WM_TIMER
                # Watchdog tick: refresh mouse hook to ensure it never dies silently
                if self._running:
                    self._sync_hotkeys()
                    self._load_gate_settings()                       # picks up Settings changes without a restart
                    if self._gate.settings.mode == "hotkey":
                        self._apply_hook_mode()
                    else:
                        self._install_mouse_hook()
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))

        # Cleanup
        user32.KillTimer(None, 0x5001)
        if self._mouse_hook:
            user32.UnhookWindowsHookEx(self._mouse_hook)
            self._mouse_hook = None
        for hk_id, name, _text, _what in self._hotkey_defs:
            if name in self._native_registered:
                user32.UnregisterHotKey(None, hk_id)
        self._native_registered.clear()

    def start(self) -> None:
        self._running = True
        set_high_priority()

        # Start unified native hook & hotkey message pump
        self._hook_thread = threading.Thread(target=self._run_native_event_pump, name="consiz-native-events", daemon=True)
        self._hook_thread.start()
        self._native_ready.wait(timeout=1.0)

        # Fallback with pynput ONLY for hotkeys that Windows RegisterHotKey could not register
        fallback_hotkeys = {}
        if CONFIG.hotkey and "hotkey" not in self._native_registered:
            fallback_hotkeys[CONFIG.hotkey] = lambda: self._fire("hotkey")
        if getattr(CONFIG, "dictate_hotkey", None) and self._on_dictate and "dictate" not in self._native_registered:
            fallback_hotkeys[CONFIG.dictate_hotkey] = lambda: self._fire_dictate("dictate-hotkey")

        if getattr(CONFIG, "pc_hotkey", None) and self._on_pc and "pc" not in self._native_registered:
            fallback_hotkeys[CONFIG.pc_hotkey] = lambda: self._fire_pc("pc-hotkey")

        if fallback_hotkeys:
            try:
                hk = keyboard.GlobalHotKeys(fallback_hotkeys)
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
