"""Hotkey text helpers (shared, no OS calls). Hotkeys are stored in pynput style: "<ctrl>+<alt>+s"."""
from __future__ import annotations

import re

_MOD_NAMES = {"ctrl": "<ctrl>", "control": "<ctrl>", "alt": "<alt>", "shift": "<shift>",
              "win": "<cmd>", "windows": "<cmd>", "cmd": "<cmd>", "super": "<cmd>"}
_MOD_ORDER = ["<ctrl>", "<alt>", "<shift>", "<cmd>"]
_PRETTY = {"<ctrl>": "Ctrl", "<alt>": "Alt", "<shift>": "Shift", "<cmd>": "Win"}


def _split(text: str) -> list[str]:
    cleaned = (text or "").replace("<", "").replace(">", "").strip().lower()
    return [p for p in re.split(r"\s*\+\s*|\s+", cleaned) if p]


def normalize(text: str) -> str | None:
    """'Ctrl + Alt + S' or '<ctrl>+<alt>+s' -> '<ctrl>+<alt>+s'; None when it is not a safe shortcut.
    Safe means: exactly one key (a letter, digit, F1-F24 or Space) plus either two or more modifiers, or one modifier
    with a function key. A bare Ctrl+S would hijack Save in every app, so it is refused."""
    parts = _split(text)
    if not parts:
        return None
    mods, keys = set(), []
    for p in parts:
        if p in _MOD_NAMES:
            mods.add(_MOD_NAMES[p])
        else:
            keys.append(p)
    if len(keys) != 1:
        return None
    key = keys[0]
    is_f = bool(re.fullmatch(r"f([1-9]|1\d|2[0-4])", key))
    if is_f:
        token = f"<{key}>"
    elif key == "space":
        token = "<space>"
    elif re.fullmatch(r"[a-z0-9]", key):
        token = key
    else:
        return None
    if len(mods) < 2 and not (is_f and len(mods) == 1):
        return None
    ordered = [m for m in _MOD_ORDER if m in mods]
    return "+".join(ordered + [token])


def pretty(hotkey: str) -> str:
    """'<ctrl>+<alt>+s' -> 'Ctrl+Alt+S' (what a person reads)."""
    out = []
    for p in (hotkey or "").split("+"):
        p = p.strip()
        if p in _PRETTY:
            out.append(_PRETTY[p])
        else:
            key = p.strip("<>")
            out.append(key.upper() if len(key) <= 3 else key.capitalize())
    return "+".join(out)
