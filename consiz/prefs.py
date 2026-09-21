"""Per-user preferences that survive restarts (currently: onboarding-completed flag). Stored next
to the .env file, in the user's home directory — same place regardless of where the app is run from."""
from __future__ import annotations

import json
import os
import pathlib

STORE = pathlib.Path(os.environ.get("CONSIZ_STATE_DIR", pathlib.Path.home() / ".consiz")) / "prefs.json"


def _load() -> dict:
    try:
        return json.loads(STORE.read_text())
    except (OSError, ValueError):
        return {}


def get(key: str, default=None):
    return _load().get(key, default)


def set(key: str, value) -> None:            # noqa: A001 — small, intentional
    data = _load()
    data[key] = value
    try:
        STORE.parent.mkdir(parents=True, exist_ok=True)
        STORE.write_text(json.dumps(data))
    except OSError:
        pass                                  # a broken prefs file must never break the app
