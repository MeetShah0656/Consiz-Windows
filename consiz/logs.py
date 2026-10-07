"""Application log + crash handling (shared).

The Windows exe has no console, so without this every error vanishes. Everything goes to one rotating file,
~/.consiz/consiz.log (512 KB x 3). Rules:
  - NEVER log what the user selected, typed or read — only events, sizes, app names and error types.
  - Every line is passed through the same secret redaction as outgoing text, as a second safety net.
  - Crashes (main thread, worker threads, Tk callbacks) are written with a traceback instead of disappearing.
"""
from __future__ import annotations

import logging
import logging.handlers
import platform
import sys
import threading
import time
from pathlib import Path

from . import prefs, security

LOG_FILE: Path = prefs.STORE.parent / "consiz.log"
_MAX_BYTES, _BACKUPS = 512_000, 2
_state = {"ready": False}


class _RedactFilter(logging.Filter):
    """Second line of defence: scrub anything that looks like a key/token/password from every record."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            record.msg, record.args = security.redact(record.getMessage())[0], ()   # traceback (exc_info) is kept
        except Exception:
            pass
        return True


def get() -> logging.Logger:
    return logging.getLogger("consiz")


def setup() -> logging.Logger:
    """Idempotent. Creates the log file handler and installs the crash hooks."""
    log = get()
    if _state["ready"]:
        return log
    log.setLevel(logging.INFO)
    log.propagate = False
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        handler = logging.handlers.RotatingFileHandler(LOG_FILE, maxBytes=_MAX_BYTES, backupCount=_BACKUPS,
                                                       encoding="utf-8", delay=True)
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)-8s %(message)s", "%Y-%m-%d %H:%M:%S"))
        handler.addFilter(_RedactFilter())
        log.addHandler(handler)
    except OSError:
        log.addHandler(logging.NullHandler())        # a broken disk must never break the app
    sys.excepthook = _on_main_exception
    threading.excepthook = _on_thread_exception
    sys.unraisablehook = _on_unraisable
    _state["ready"] = True
    return log


def _on_main_exception(exc_type, exc, tb) -> None:
    get().critical("UNHANDLED %s", exc_type.__name__, exc_info=(exc_type, exc, tb))


def _on_thread_exception(args: "threading.ExceptHookArgs") -> None:
    if args.exc_type is SystemExit:
        return
    name = args.thread.name if args.thread else "?"
    get().error("THREAD CRASH in %s: %s", name, args.exc_type.__name__,
                exc_info=(args.exc_type, args.exc_value, args.exc_traceback))


def _on_unraisable(u) -> None:
    get().warning("unraisable %s in %s", type(u.exc_value).__name__ if u.exc_value else "?", u.object)


def exception(where: str) -> None:
    """Log the exception being handled right now (call inside an `except` block)."""
    get().exception("ERROR in %s", where)


def log_folder() -> Path:
    return LOG_FILE.parent


def tail(lines: int = 40) -> str:
    try:
        return "\n".join(LOG_FILE.read_text(encoding="utf-8", errors="replace").splitlines()[-lines:])
    except OSError:
        return "(no log yet)"


def diagnostics() -> str:
    """Text the user can paste to support: versions, settings that matter, recent log. No content, no secrets."""
    from . import auth, __version__
    from .config import CONFIG
    try:
        who = "signed in" if auth.signed_in() else "signed out"
    except Exception:
        who = "unknown"
    head = [
        f"Consiz {__version__}  ({time.strftime('%Y-%m-%d %H:%M:%S')})",
        f"Windows {platform.version()} · Python {platform.python_version()} · "
        f"{'packaged exe' if getattr(sys, 'frozen', False) else 'from source'}",
        f"provider={CONFIG.provider} · trigger={getattr(CONFIG, 'trigger_mode', '?')} · account={who}",
        f"log file: {LOG_FILE}",
        "---- last log lines ----",
    ]
    return "\n".join(head) + "\n" + security.redact(tail())[0]
