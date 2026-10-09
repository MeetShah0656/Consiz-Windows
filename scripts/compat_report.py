"""Describe this PC in a few lines a tester can paste into docs/COMPAT_MATRIX.md (Windows version, screens, scaling,
rights, what Consiz can use). Reads only: it changes nothing and sends nothing.

    python scripts/compat_report.py
"""
from __future__ import annotations

import ctypes
import importlib.util
import platform
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def main() -> int:
    if sys.platform != "win32":
        print("compat_report.py runs on Windows only")
        return 1
    user32 = ctypes.windll.user32
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        user32.SetProcessDPIAware()
    build = sys.getwindowsversion().build
    edition = "11" if build >= 22000 else "10"
    dpi = user32.GetDpiForSystem() if hasattr(user32, "GetDpiForSystem") else 96
    from consiz import __version__, voice
    from consiz.platform.win32.priority import is_admin
    have = lambda mod: importlib.util.find_spec(mod) is not None                      # noqa: E731
    print(f"- Windows {edition} (build {build}), {platform.machine()}, Python {platform.python_version()}")
    print(f"- Screens: {user32.GetSystemMetrics(80)}, main screen {user32.GetSystemMetrics(0)}x{user32.GetSystemMetrics(1)} px, "
          f"scale {round(dpi / 96 * 100)}%")
    print(f"- Consiz {__version__}, running as {'administrator' if is_admin() else 'a normal user'}")
    print(f"- Window text reading (uiautomation): {'yes' if have('uiautomation') else 'MISSING'}; "
          f"tray (pystray): {'yes' if have('pystray') else 'MISSING'}; sign-in storage (keyring): {'yes' if have('keyring') else 'MISSING'}")
    print(f"- Voice parts included: {'yes' if voice.available() else 'no'}; speech model on this PC: "
          f"{'yes' if voice.available() and voice.model_cached() else 'no'}")
    print("- Paste these lines into docs/COMPAT_MATRIX.md next to your results.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
