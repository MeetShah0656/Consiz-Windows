"""One-click actions the AI may SUGGEST in Ask-about-my-PC mode (shared logic).

Safety model:
  - A fixed whitelist. The model can only name an entry from it; anything else is dropped.
  - Nothing runs by itself. An action appears as a button; it runs only when the user clicks it.
  - Actions only OPEN things (a Settings page, Task Manager, a folder, bring a window forward).
    No deleting, no ending programs, no typing, no sending.
"""
from __future__ import annotations

from dataclasses import dataclass

# name -> {arg -> (button label, target)}.  Targets are launched by the platform layer.
SETTINGS = {
    "storage": ("Open Storage settings", "ms-settings:storagesense"),
    "startup": ("Open Startup apps settings", "ms-settings:startupapps"),
    "apps": ("Open Installed apps", "ms-settings:appsfeatures"),
    "battery": ("Open Battery settings", "ms-settings:batterysaver"),
    "updates": ("Open Windows Update", "ms-settings:windowsupdate"),
    "network": ("Open Network settings", "ms-settings:network"),
}
SIMPLE = {
    "open_task_manager": ("Open Task Manager", "taskmgr.exe"),
    "open_disk_cleanup": ("Open Disk Cleanup", "cleanmgr.exe"),
    "open_downloads": ("Open Downloads folder", "downloads"),
}
MAX_ACTIONS = 2

ALLOWED_TEXT = (
    "open_settings <" + "|".join(SETTINGS) + ">, " + ", ".join(SIMPLE) + ", focus_window <number from OPEN WINDOWS>"
)


@dataclass(frozen=True)
class Action:
    kind: str          # "launch" (open a target) or "focus" (bring a window to the front)
    target: str        # launch target, or the window handle as text
    label: str         # the button text shown to the user


def parse(line: str, windows: list[dict]) -> Action | None:
    """Turn a model line like 'ACTION: open_settings storage' into a validated Action, else None."""
    body = line.strip().strip("*`_ ")
    if not body.upper().startswith("ACTION"):
        return None
    body = body[6:].lstrip(" :").strip()
    parts = body.replace("`", "").split()
    if not parts:
        return None
    name, arg = parts[0].lower(), (parts[1].lower() if len(parts) > 1 else "")
    if name == "open_settings" and arg in SETTINGS:
        label, target = SETTINGS[arg]
        return Action("launch", target, label)
    if name in SIMPLE and not arg:
        label, target = SIMPLE[name]
        return Action("launch", target, label)
    if name == "focus_window" and arg.isdigit() and 1 <= int(arg) <= len(windows):
        w = windows[int(arg) - 1]
        return Action("focus", str(w["hwnd"]), f"Switch to: {w['title'][:40]}")
    return None


def is_action_line(line: str) -> bool:
    return line.strip().strip("*`_ ").upper().startswith("ACTION")


def run(action: Action) -> tuple[bool, str]:
    """Do it (only ever called from a button click). Returns (ok, short message)."""
    import sys
    if sys.platform != "win32":
        return False, "Actions are Windows-only for now."
    from consiz.platform.win32 import actions
    try:
        if action.kind == "focus":
            return actions.focus(int(action.target))
        return actions.launch(action.target)
    except Exception as e:                                   # never crash the UI over a button
        return False, f"Could not do that ({type(e).__name__})."
