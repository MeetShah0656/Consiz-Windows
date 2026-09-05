"""Capture facade: dynamically loads macOS or Windows native capture implementation."""
from __future__ import annotations

import sys

if sys.platform == "darwin":
    from consiz.platform.darwin.capture import capture, frontmost_app
elif sys.platform == "win32":
    from consiz.platform.win32.capture import capture, frontmost_app
else:
    raise RuntimeError(f"Unsupported platform for Capture: {sys.platform}")

__all__ = ["capture", "frontmost_app"]
