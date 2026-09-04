"""Trigger (spec §4): middle mouse button (Phase 1 choice) + keyboard hotkey fallback. Both fire the same callback.

macOS detail: the middle-click is INTERCEPTED and swallowed, so the app under the cursor never sees it.
Otherwise the browser's mousedown clears the user's text selection before we can copy it.
"""
from __future__ import annotations

import threading
from typing import Callable

import Quartz
from pynput import keyboard, mouse

from .config import CONFIG

_MIDDLE = 2
_MIDDLE_EVENTS = (Quartz.kCGEventOtherMouseDown, Quartz.kCGEventOtherMouseUp, Quartz.kCGEventOtherMouseDragged)


class Trigger:
    def __init__(self, on_fire: Callable[[str], None], on_busy: Callable[[], None] | None = None):
        self._on_fire = on_fire
        self._on_busy = on_busy
        self._busy = threading.Lock()
        self._listeners: list = []

    def _fire(self, source: str) -> None:
        # Re-entrancy guard: one request at a time. Say so instead of silently dropping the click.
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

    # -- mouse
    def _on_click(self, x, y, button, pressed, *_):
        if button == mouse.Button.middle and pressed:      # fire on PRESS: earliest moment, selection still intact
            self._fire("middle-click")

    @staticmethod
    def _intercept(event_type, event):
        """Return None to swallow the event, or the event to let it through."""
        if event_type in _MIDDLE_EVENTS and \
                Quartz.CGEventGetIntegerValueField(event, Quartz.kCGMouseEventButtonNumber) == _MIDDLE:
            return None
        return event

    def start(self) -> None:
        if CONFIG.use_middle_click:
            ml = mouse.Listener(on_click=self._on_click, darwin_intercept=self._intercept)
            ml.daemon = True
            ml.start()
            self._listeners.append(ml)
        if CONFIG.hotkey:
            hk = keyboard.GlobalHotKeys({CONFIG.hotkey: lambda: self._fire("hotkey")})
            hk.daemon = True
            hk.start()
            self._listeners.append(hk)

    def stop(self) -> None:
        for l in self._listeners:
            l.stop()
