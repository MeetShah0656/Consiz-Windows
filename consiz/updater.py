"""Update check (T-08). Asks OUR server what the newest version is; never downloads or runs anything by itself.

  GET {server}/version  ->  {"latest": "0.4.0", "minimum": "0.3.0", "url": "https://.../Consiz-Setup-0.4.0.exe", "notes": "..."}

  latest   newest released version (the operator sets LATEST_VERSION on the server: no app release needed to announce it)
  minimum  oldest version still allowed to use the AI (MIN_VERSION): the server refuses older apps with HTTP 426
  url      where the user downloads the installer: opened in the browser only when the user clicks (https only)

Why no silent auto-install: running a downloaded program is only safe when the installer is code-signed and verified.
Until Consiz has a signing certificate, the user clicks the link and installs it themselves.
"""
from __future__ import annotations

import os
import threading
import time
from typing import Callable, Optional

import requests

CHECK_EVERY_SECONDS = 24 * 3600
FIRST_CHECK_DELAY_SECONDS = 20          # never compete with start-up

_last: dict = {"info": None}


def parse(version: str) -> tuple[int, ...]:
    """'0.3.10' -> (0, 3, 10). Anything unreadable counts as 0, so a bad value never blocks the app."""
    out = []
    for part in str(version or "").strip().lstrip("vV").split("."):
        digits = "".join(ch for ch in part if ch.isdigit())
        out.append(int(digits) if digits else 0)
    return tuple(out) or (0,)


def is_newer(latest: str, current: str) -> bool:
    return bool(str(latest or "").strip()) and parse(latest) > parse(current)


def is_below(current: str, minimum: str) -> bool:
    return bool(str(minimum or "").strip()) and parse(current) < parse(minimum)


def safe_url(url: str) -> str:
    """Only an https link may be opened from here (the value comes from the server's settings)."""
    url = (url or "").strip()
    return url if url.lower().startswith("https://") else ""


def check(server_url: str = "", current: str = "", timeout: float = 8.0) -> Optional[dict]:
    """The server's answer plus two flags, or None when it cannot be reached (an update check must never nag or fail loudly)."""
    from . import __version__
    base = (server_url or os.environ.get("CONSIZ_SERVER_URL", "")).strip().rstrip("/")
    current = current or __version__
    if not base:
        return None
    try:
        r = requests.get(f"{base}/version", timeout=timeout)
        if r.status_code != 200:
            return None
        data = r.json()
    except (requests.RequestException, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    info = {
        "current": current,
        "latest": str(data.get("latest") or ""),
        "minimum": str(data.get("minimum") or ""),
        "url": safe_url(str(data.get("url") or "")),
        "notes": str(data.get("notes") or "")[:300],
    }
    info["update_available"] = is_newer(info["latest"], current)
    info["required"] = is_below(current, info["minimum"])
    _last["info"] = info
    return info


def last() -> Optional[dict]:
    return _last["info"]


def start_background_check(on_result: Callable[[dict], None]) -> None:
    """Check shortly after start and then once a day while the app runs. on_result runs on the worker thread, only
    when there is something to tell (a newer version, or this version is no longer supported)."""
    def loop():
        time.sleep(FIRST_CHECK_DELAY_SECONDS)
        while True:
            info = check()
            if info and (info["update_available"] or info["required"]):
                try:
                    on_result(info)
                except Exception:
                    pass
            time.sleep(CHECK_EVERY_SECONDS)

    threading.Thread(target=loop, name="consiz-update-check", daemon=True).start()
