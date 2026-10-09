"""The words in Consiz's own windows (T-18): English, and Hindi first. The AI's answers have their own setting (Answer language).

How it works, in one place:
  - t("English text") returns the Hindi text when the app language is Hindi, else the same text. The English sentence IS
    the key, so code stays readable and a missing translation simply shows English.
  - install() makes every Tk widget and window title go through t(), so labels, buttons, checkboxes and titles are
    translated without touching each call site. Text that is built from pieces uses tf("... {name} ...", name=...).
  - The language is chosen in Settings > General (Automatic follows the Windows display language). It is read when
    Consiz starts: changing it asks the person to restart Consiz.
Hindi lives in strings_hi.py. tests/test_i18n.py fails when a window's text has no translation, so it cannot be forgotten.
"""
from __future__ import annotations

import os
import sys

LANGUAGES = {"auto": "Automatic (Windows language)", "en": "English", "hi": "हिन्दी (Hindi)"}
_cache: dict = {}
record: set[str] | None = None            # tests/tools set this to collect every widget string a window uses


def windows_language() -> str:
    """'hi' when Windows itself is shown in Hindi, else 'en'."""
    if sys.platform != "win32":
        return "en"
    try:
        import ctypes
        primary = ctypes.windll.kernel32.GetUserDefaultUILanguage() & 0x3FF
        return "hi" if primary == 0x39 else "en"
    except Exception:
        return "en"


def language() -> str:
    """The language of Consiz's windows: 'en' or 'hi' (CONSIZ_UI_LANGUAGE overrides, for testing)."""
    if "lang" in _cache:
        return _cache["lang"]
    chosen = os.environ.get("CONSIZ_UI_LANGUAGE")
    if not chosen:
        from . import prefs
        chosen = prefs.get("ui_language", "auto")
    lang = windows_language() if chosen == "auto" else chosen
    _cache["lang"] = lang if lang in ("en", "hi") else "en"
    return _cache["lang"]


def reset() -> None:
    """Forget the chosen language (tests; the app reads it once per run)."""
    _cache.clear()


def _table() -> dict[str, str]:
    if "table" not in _cache:
        from .strings_hi import HI
        _cache["table"] = HI
    return _cache["table"]


def t(text):
    """The text in the app language (English text passes through unchanged when there is no translation)."""
    if not isinstance(text, str) or not text.strip():
        return text
    if record is not None:
        record.add(text)
    if language() == "en":
        return text
    return _table().get(text, text)


def tl(text):
    """t() for a line of text that may start or end with spaces or new lines (they are kept as they are)."""
    if not isinstance(text, str) or not text.strip() or language() == "en" and record is None:
        return text
    core = text.strip()
    start = text.index(core[0])
    return text[:start] + t(core) + text[start + len(core):]


def tf(template: str, **values) -> str:
    """A translated sentence with parts filled in: tf("Saved: {path}", path=...)."""
    return t(template).format(**values)


_installed = {"done": False}


def install() -> None:
    """Route every Tk widget option called 'text' (and window titles) through t(). Idempotent."""
    if _installed["done"]:
        return
    _installed["done"] = True
    import tkinter

    original_options = tkinter.Misc._options

    def _options(self, cnf, kw=None):
        merged = dict(cnf or {})
        if kw:
            merged.update(kw)
        if isinstance(merged.get("text"), str):
            merged["text"] = t(merged["text"])
        return original_options(self, merged, None)

    tkinter.Misc._options = _options

    original_title = tkinter.Wm.wm_title

    def wm_title(self, string=None):
        return original_title(self, t(string) if isinstance(string, str) else string)

    tkinter.Wm.wm_title = wm_title
    tkinter.Wm.title = wm_title
