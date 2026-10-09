"""Windows executor for the whitelisted actions in consiz/pc_actions.py.

launch / focus only OPEN things. The three CHANGE actions at the bottom (close a program, clear old temporary files, stop a
program starting with Windows) never act without the person's Yes, asked through `confirm(title, text)`, and each refuses
what it must not touch (Windows' own programs, files that are not old temp files, startup items for all users)."""
from __future__ import annotations

import ctypes
import os
import struct
import time
from ctypes import wintypes
from pathlib import Path

from consiz.i18n import t, tf

user32 = ctypes.windll.user32
SW_RESTORE = 9
WM_CLOSE = 0x0010
FILE_ATTRIBUTE_REPARSE_POINT = 0x400


def launch(target: str) -> tuple[bool, str]:
    """Open a Settings page, Task Manager, Disk Cleanup or the Downloads folder (targets come from the whitelist)."""
    if target == "downloads":
        target = str(Path.home() / "Downloads")
    os.startfile(target)                                       # noqa: S606 - target is whitelisted, never user/model text
    return True, t("Opened.")


def focus(hwnd: int) -> tuple[bool, str]:
    """Bring an existing window to the front (restores it if minimized)."""
    if not user32.IsWindow(hwnd):
        return False, t("That window is closed now.")
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, SW_RESTORE)
    user32.SetForegroundWindow(hwnd)
    return True, t("Switched.")


# ====================================================================== CHANGE actions (always confirm first)
# Programs Consiz will never end, whatever the AI suggests: Windows' own parts, security software, and Consiz itself.
PROTECTED_PROGRAMS = frozenset({
    "system", "registry", "smss.exe", "csrss.exe", "wininit.exe", "winlogon.exe", "services.exe", "lsass.exe",
    "lsaiso.exe", "svchost.exe", "explorer.exe", "dwm.exe", "fontdrvhost.exe", "sihost.exe", "taskhostw.exe",
    "runtimebroker.exe", "searchhost.exe", "searchindexer.exe", "startmenuexperiencehost.exe",
    "shellexperiencehost.exe", "textinputhost.exe", "ctfmon.exe", "spoolsv.exe", "audiodg.exe", "wudfhost.exe",
    "msmpeng.exe", "nissrv.exe", "securityhealthservice.exe", "securityhealthsystray.exe", "consiz.exe",
    "applicationframehost.exe", "lockapp.exe", "logonui.exe", "memory compression",
})
NL = chr(10)


def protected_reason(proc) -> str | None:
    """Why this program must not be ended (a short phrase), or None when it may be offered to the person."""
    import psutil
    try:
        name = (proc.name() or "").lower()
        if name in PROTECTED_PROGRAMS:
            return "it is part of Windows or your security software"
        me = psutil.Process(os.getpid())
        if proc.pid == me.pid or proc.pid in {p.pid for p in me.parents()}:
            return "it is Consiz itself, or the program that started Consiz"
        windir = os.environ.get("SystemRoot", "C:" + chr(92) + "Windows").lower().rstrip(chr(92)) + chr(92)
        if (proc.exe() or "").lower().startswith(windir):
            return "it is a Windows program"
        if proc.username() != me.username():
            return "it belongs to another account"
    except psutil.NoSuchProcess:
        return "it has already closed"
    except psutil.AccessDenied:
        return "Windows does not let Consiz change it (it may be running as administrator)"
    return None


def _windows_of(pid: int) -> list[int]:
    found: list[int] = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def each(hwnd, _):
        owner = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value == pid and user32.IsWindowVisible(hwnd):
            found.append(int(hwnd))
        return True

    user32.EnumWindows(each, 0)
    return found


def _title_of(hwnd: int) -> str:
    n = user32.GetWindowTextLengthW(hwnd)
    buf = ctypes.create_unicode_buffer(n + 1)
    user32.GetWindowTextW(hwnd, buf, n + 1)
    return buf.value


def end_program(hwnd: int, confirm, wait_s: float = 8.0) -> tuple[bool, str]:
    """Close the program that owns this window: ask it to close, and only force it if the person says yes a second time."""
    import psutil
    if not user32.IsWindow(hwnd):
        return False, "That window is already closed."
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    try:
        proc = psutil.Process(pid.value)
    except psutil.NoSuchProcess:
        return False, "That program has already closed."
    return _end_process(proc, _title_of(hwnd), confirm, wait_s)


def _end_process(proc, title: str, confirm, wait_s: float = 8.0) -> tuple[bool, str]:
    import psutil
    why = protected_reason(proc)
    if why:
        return False, tf("Consiz will not close this: {why}.", why=t(why))
    name = proc.name()
    asked = confirm(t("Consiz - close a program"),
                    tf("Close this program?\n\n  {name}\n  Window: {title}\n\nConsiz asks it to close first, like "
                       "pressing its X. If it asks you to save, answer there.", name=name, title=title[:80]))
    if not asked:
        return False, t("Cancelled. Nothing was changed.")
    for hwnd in _windows_of(proc.pid):
        user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)
    try:
        proc.wait(timeout=wait_s)
        return True, t("Closed.")
    except psutil.TimeoutExpired:
        pass
    except psutil.NoSuchProcess:
        return True, t("Closed.")
    if not confirm(t("Consiz - force it to stop?"),
                   tf("{name} did not close by itself (it may be stuck, or waiting for you to save).\n\n"
                      "Force it to stop? Anything unsaved in it is lost.", name=name)):
        return False, t("Left running: it did not close by itself.")
    try:
        proc.terminate()
        proc.wait(timeout=5)
    except psutil.TimeoutExpired:
        return False, "Windows did not let it stop."
    except psutil.NoSuchProcess:
        pass
    except psutil.AccessDenied:
        return False, "Windows would not allow Consiz to stop it."
    return True, t("Stopped.")


# ---- clear old temporary files
TEMP_MIN_AGE_S = 24 * 3600


def _is_link(entry) -> bool:
    """Symbolic links and junctions: never followed, never deleted through."""
    try:
        st = entry.stat(follow_symlinks=False)
        return entry.is_symlink() or bool(getattr(st, "st_file_attributes", 0) & FILE_ATTRIBUTE_REPARSE_POINT)
    except OSError:
        return True


def temp_root() -> str:
    import tempfile
    return tempfile.gettempdir()


def old_temp_files(root: str, now: float | None = None, limit: int = 300_000) -> tuple[list[tuple[str, int]], int]:
    """(files older than a day under `root`, total bytes). Looks only; never follows links."""
    now = now or time.time()
    found: list[tuple[str, int]] = []
    total, stack = 0, [root]
    while stack and len(found) < limit:
        folder = stack.pop()
        try:
            with os.scandir(folder) as it:
                for entry in it:
                    if _is_link(entry):
                        continue
                    if entry.is_dir(follow_symlinks=False):
                        stack.append(entry.path)
                    elif entry.is_file(follow_symlinks=False):
                        st = entry.stat(follow_symlinks=False)
                        if now - max(st.st_mtime, st.st_ctime) > TEMP_MIN_AGE_S:
                            found.append((entry.path, st.st_size))
                            total += st.st_size
        except OSError:
            continue
    return found, total


def _size_text(n: int) -> str:
    return f"{n / 1024 ** 3:.1f} GB" if n >= 1024 ** 3 else f"{n / 1024 ** 2:.0f} MB" if n >= 1024 ** 2 else f"{n / 1024:.0f} KB"


def _is_a_temp_folder(root: str) -> bool:
    real = os.path.realpath(root)
    return os.path.basename(real).lower() in ("temp", "tmp") and os.path.splitdrive(real)[1].count(os.sep) >= 2


def _is_link_path(path: str) -> bool:
    try:
        st = os.lstat(path)
        return os.path.islink(path) or bool(getattr(st, "st_file_attributes", 0) & FILE_ATTRIBUTE_REPARSE_POINT)
    except OSError:
        return True


def clear_temp(confirm, root: str | None = None, now: float | None = None) -> tuple[bool, str]:
    """Delete the files in the user's Temp folder that are more than a day old, after a Yes that says how many and how big."""
    root = root or temp_root()
    if not _is_a_temp_folder(root):
        return False, t("Consiz will only clear a folder named Temp.")
    files, total = old_temp_files(root, now)
    if not files:
        return True, t("Nothing to clear: no temporary file is more than a day old.")
    if not confirm(t("Consiz - clear temporary files"),
                   tf("Delete {count} temporary files ({size}) that are more than a day old?\n\n  Folder: {root}\n\n"
                      "These are leftovers that programs wrote and no longer need. Files that are in use are skipped. "
                      "They are deleted for good (not moved to the Recycle Bin).",
                      count=f"{len(files):,}", size=_size_text(total), root=root)):
        return False, t("Cancelled. Nothing was changed.")
    deleted = freed = 0
    for path, size in files:
        try:
            os.remove(path)
            deleted += 1
            freed += size
        except OSError:
            continue                                            # in use, or already gone
    for folder, _dirs, _files in os.walk(root, topdown=False):  # tidy up folders that are now empty
        if folder != root and not _is_link_path(folder):
            try:
                os.rmdir(folder)
            except OSError:
                pass
    return True, tf("Deleted {n} files and freed {size}.", n=f"{deleted:,}", size=_size_text(freed))


# ---- stop a program starting with Windows
RUN_KEY = "Software" + chr(92) + "Microsoft" + chr(92) + "Windows" + chr(92) + "CurrentVersion" + chr(92) + "Run"
APPROVED_KEY = ("Software" + chr(92) + "Microsoft" + chr(92) + "Windows" + chr(92) + "CurrentVersion" + chr(92)
                + "Explorer" + chr(92) + "StartupApproved" + chr(92) + "Run")


def disable_startup(name: str, confirm, run_key: str = RUN_KEY, approved_key: str = APPROVED_KEY) -> tuple[bool, str]:
    """Turn a startup item off the way Task Manager does (a flag Windows reads; nothing is deleted, so it is reversible).
    Only items of this user: the ones for everybody need administrator, so Settings is opened for those instead."""
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, run_key) as k:
            winreg.QueryValueEx(k, name)
    except OSError:
        launch("ms-settings:startupapps")
        return True, t("That one is set for all users of this PC, so Windows asks for permission to change it. "
                       "I opened Startup apps for you.")
    if not confirm(t("Consiz - startup program"),
                   tf("Stop {name} from starting with Windows?\n\nThe program is not removed and nothing is deleted. "
                      "You can turn it back on any time in Settings > Apps > Startup.", name=name)):
        return False, t("Cancelled. Nothing was changed.")
    filetime = int((time.time() + 11644473600) * 10_000_000)
    flag = bytes([3, 0, 0, 0]) + struct.pack("<Q", filetime)    # what Task Manager writes when you press Disable
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, approved_key, 0, winreg.KEY_SET_VALUE) as k:
        winreg.SetValueEx(k, name, 0, winreg.REG_BINARY, flag)
    return True, t("Turned off. It will not start with Windows next time.")
