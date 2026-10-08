"""Pause Consiz (T-10). While paused, the mouse hook gives every click back to the app and the hotkeys are released,
so a game, a presentation or a remote desktop never notices Consiz. Not saved: Consiz always starts active."""
from __future__ import annotations

import threading
from typing import Callable

_paused = False
_listeners: list[Callable[[bool], None]] = []
_lock = threading.Lock()


def is_paused() -> bool:
    return _paused


def set_paused(value: bool) -> None:
    global _paused
    with _lock:
        if _paused == bool(value):
            return
        _paused = bool(value)
        listeners = list(_listeners)
    for fn in listeners:
        try:
            fn(_paused)
        except Exception:
            pass


def toggle() -> bool:
    set_paused(not _paused)
    return _paused


def on_change(fn: Callable[[bool], None]) -> None:
    """Called (on whichever thread changed it) with the new state; used to refresh hotkeys and the tray icon."""
    with _lock:
        _listeners.append(fn)
