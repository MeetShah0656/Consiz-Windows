"""PC-snapshot facade: loads the native collector (Windows today; macOS later). Same snapshot contract everywhere."""
from __future__ import annotations

import sys

if sys.platform == "win32":
    from consiz.platform.win32.sysinfo import snapshot
else:
    def snapshot() -> dict:                               # pragma: no cover - macOS port is a later checkpoint
        raise RuntimeError(f"PC mode is not available on {sys.platform} yet")

__all__ = ["snapshot"]
