"""Everything Consiz keeps on this PC, and a way to wipe it (Settings > Account & data > Clear local data).

Removed: preferences (incl. the welcome-screen flag and PC-mode permission), the saved sign-in (Credential Manager
refresh token + session file) and the app log. NOT removed: profile.md, which the user wrote themselves.
"""
from __future__ import annotations

from pathlib import Path


def local_files() -> list[Path]:
    from . import logs, prefs
    log = logs.LOG_FILE
    return [prefs.STORE, log, log.with_name(log.name + ".1"), log.with_name(log.name + ".2")]


def clear_local_data() -> list[str]:
    """Delete our files and sign out. Returns a short list of what was done (for the confirmation message)."""
    done: list[str] = []
    try:
        from . import auth
        if auth.enabled() and auth.signed_in():
            auth.sign_out()
            done.append("signed out and removed the saved sign-in")
    except Exception:
        pass
    for path in local_files():
        try:
            if path.exists():
                try:
                    path.unlink()
                except PermissionError:                       # the log file is open: empty it instead
                    with open(path, "w", encoding="utf-8"):
                        pass
                done.append(f"removed {path.name}")
        except OSError:
            pass
    return done
