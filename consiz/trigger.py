"""Trigger facade: dynamically loads macOS or Windows native trigger implementation."""
from __future__ import annotations

import sys

if sys.platform == "darwin":
    from consiz.platform.darwin.trigger import Trigger
elif sys.platform == "win32":
    from consiz.platform.win32.trigger import Trigger
else:
    raise RuntimeError(f"Unsupported platform for Trigger: {sys.platform}")

__all__ = ["Trigger"]
