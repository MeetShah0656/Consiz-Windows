"""Popup facade: dynamically loads macOS or Windows native popup UI implementation."""
from __future__ import annotations

import sys

if sys.platform == "darwin":
    from consiz.platform.darwin.popup import PopupUI, run_app_loop, _friendly_error
elif sys.platform == "win32":
    from consiz.platform.win32.popup import PopupUI, run_app_loop, _friendly_error
else:
    raise RuntimeError(f"Unsupported platform for PopupUI: {sys.platform}")

__all__ = ["PopupUI", "run_app_loop", "_friendly_error"]
