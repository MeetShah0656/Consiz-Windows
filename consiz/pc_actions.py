"""One-click actions the AI may SUGGEST in Ask-about-my-PC mode (shared logic).

Safety model:
  - A fixed whitelist. The model can only name an entry from it; anything else is dropped.
  - Nothing runs by itself. An action appears as a button; it runs only when the user clicks it.
  - Two kinds of action:
      OPEN actions (a Settings page, Task Manager, a folder, bring a window forward) just run when clicked.
      CHANGE actions (close a program, clear old temporary files, stop a program starting with Windows) are
      CONFIRM-FIRST: after the click a box names exactly what will happen and nothing is touched until the person
      says Yes (T-12). They are refused for Windows' own programs and for anything Consiz cannot undo safely.
  - Never: typing, sending, deleting a person's own files, ending a System / Windows program.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from . import i18n

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
CONFIRM_KINDS = frozenset({"end_program", "clear_temp", "disable_startup"})

ALLOWED_TEXT = (
    "open_settings <" + "|".join(SETTINGS) + ">, " + ", ".join(SIMPLE) + ", focus_window <number from OPEN WINDOWS>, "
    "end_program <number from OPEN WINDOWS> (only a frozen or runaway program the user asked about; the user must confirm), "
    "clear_temp (old temporary files; the user must confirm), "
    "disable_startup <S-number from STARTS WITH WINDOWS> (the user must confirm)"
)

Confirm = Callable[[str, str], bool]          # (title, text) -> the person said Yes


@dataclass(frozen=True)
class Action:
    kind: str          # "launch", "focus", or a CONFIRM_KINDS entry
    target: str        # launch target, the window handle as text, or the startup item's name
    label: str         # the button text shown to the user


def needs_confirm(action: Action) -> bool:
    return action.kind in CONFIRM_KINDS


def parse(line: str, windows: list[dict], startup: list[str] | None = None) -> Action | None:
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
        return Action("launch", target, i18n.t(label))
    if name in SIMPLE and not arg:
        label, target = SIMPLE[name]
        return Action("launch", target, i18n.t(label))
    if name == "focus_window" and arg.isdigit() and 1 <= int(arg) <= len(windows):
        w = windows[int(arg) - 1]
        return Action("focus", str(w["hwnd"]), i18n.tf("Switch to: {title}", title=w["title"][:40]))
    if name == "end_program" and arg.isdigit() and 1 <= int(arg) <= len(windows):
        w = windows[int(arg) - 1]
        return Action("end_program", str(w["hwnd"]), i18n.tf("Close {app}: {title}", app=w["app"], title=w["title"][:34]))
    if name == "clear_temp" and not arg:
        return Action("clear_temp", "", i18n.t("Clear old temporary files"))
    if name == "disable_startup" and startup:
        number = arg.lstrip("s")
        if number.isdigit() and 1 <= int(number) <= len(startup):
            item = startup[int(number) - 1]
            return Action("disable_startup", item, i18n.tf("Stop {item} starting with Windows", item=item[:36]))
    return None


def is_action_line(line: str) -> bool:
    return line.strip().strip("*`_ ").upper().startswith("ACTION")


def run(action: Action, confirm: Confirm | None = None) -> tuple[bool, str]:
    """Do it (only ever called from a button click). Returns (ok, short message). A CHANGE action does nothing at all
    unless `confirm` is given: it is called with a title and a plain description and must return True for Yes."""
    import sys
    if sys.platform != "win32":
        return False, i18n.t("Actions are Windows-only for now.")
    from consiz.platform.win32 import actions
    try:
        if action.kind == "focus":
            return actions.focus(int(action.target))
        if needs_confirm(action):
            if confirm is None:
                return False, i18n.t("This needs your confirmation first.")
            if action.kind == "end_program":
                return actions.end_program(int(action.target), confirm)
            if action.kind == "clear_temp":
                return actions.clear_temp(confirm)
            return actions.disable_startup(action.target, confirm)
        return actions.launch(action.target)
    except Exception as e:                                   # never crash the UI over a button
        return False, f"Could not do that ({type(e).__name__})."
