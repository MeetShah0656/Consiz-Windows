"""PC snapshot for "Ask about my PC" mode (Win32): what is running, how heavy, and which windows are open.

Read-only and local. It returns plain data (no AI, no network); consiz/pc_mode.py turns it into the text the
model sees, after redaction. It never reads inside windows — only their titles.

Snapshot contract (same field names on every platform):
  {taken_at, system{cpu_percent,cpu_cores,ram_total_gb,ram_used_gb,ram_percent,uptime_hours,process_count,
   disks[{drive,total_gb,free_gb,percent_used}],battery{percent,plugged}|None},
   apps[{name,processes,ram_mb,cpu_percent}], windows[{title,app,foreground,minimized,hwnd}],
   startup[str], network{established,by_app[{app,connections}]}|None}
"""
from __future__ import annotations

import ctypes
import os
import time
from ctypes import wintypes

import psutil

user32 = ctypes.windll.user32
dwmapi = ctypes.windll.dwmapi

GWL_EXSTYLE = -20
WS_EX_TOOLWINDOW = 0x00000080
DWMWA_CLOAKED = 14
_OWN_NAMES = {"consiz.exe"}
GB = 1024 ** 3


def _system() -> dict:
    vm = psutil.virtual_memory()
    out = {
        "cpu_percent": round(psutil.cpu_percent(interval=None), 1),
        "cpu_cores": psutil.cpu_count(logical=True),
        "ram_total_gb": round(vm.total / GB, 1),
        "ram_used_gb": round(vm.used / GB, 1),
        "ram_percent": round(vm.percent, 1),
        "uptime_hours": round((time.time() - psutil.boot_time()) / 3600, 1),
        "process_count": len(psutil.pids()),
        "disks": [],
        "battery": None,
    }
    for part in psutil.disk_partitions(all=False):
        if "cdrom" in part.opts or not part.fstype:
            continue
        try:
            u = psutil.disk_usage(part.mountpoint)
        except OSError:
            continue
        out["disks"].append({"drive": part.device, "total_gb": round(u.total / GB, 1),
                             "free_gb": round(u.free / GB, 1), "percent_used": round(u.percent, 1)})
    try:
        b = psutil.sensors_battery()
        if b is not None:
            out["battery"] = {"percent": round(b.percent), "plugged": bool(b.power_plugged)}
    except Exception:
        pass
    return out


def _apps(sample_s: float = 0.5) -> list[dict]:
    """Processes grouped by program name (Chrome = 1 line, not 40), with memory and recent CPU use.

    Reading every process costs ~2 s on a busy PC (antivirus slows each OpenProcess call), so: one full pass
    for names + memory + CPU time, then a short second sample of CPU time for only the likely busy ones
    (largest memory + most CPU time so far). CPU % = change in CPU time over the window."""
    rows: dict[int, tuple[str, float, float]] = {}          # pid -> (name, rss_bytes, cpu_seconds)
    for p in psutil.process_iter():
        if p.pid == 0:                                       # "System Idle Process": its CPU is the spare capacity
            continue
        try:
            with p.oneshot():
                t = p.cpu_times()
                rows[p.pid] = (p.name() or "?", p.memory_info().rss, t.user + t.system)
        except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
            continue
    candidates = {pid for pid, _ in sorted(rows.items(), key=lambda kv: kv[1][1], reverse=True)[:50]}
    candidates |= {pid for pid, _ in sorted(rows.items(), key=lambda kv: kv[1][2], reverse=True)[:30]}
    time.sleep(sample_s)
    cores = psutil.cpu_count(logical=True) or 1
    used: dict[int, float] = {}
    for pid in candidates:
        try:
            t = psutil.Process(pid).cpu_times()
            used[pid] = max(0.0, t.user + t.system - rows[pid][2])
        except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
            continue
    groups: dict[str, dict] = {}
    for pid, (name, rss, _) in rows.items():
        g = groups.setdefault(name, {"name": name, "processes": 0, "ram_mb": 0.0, "cpu_percent": 0.0})
        g["processes"] += 1
        g["ram_mb"] += rss / (1024 ** 2)
        g["cpu_percent"] += used.get(pid, 0.0) / sample_s / cores * 100   # share of the whole CPU, like Task Manager
    for g in groups.values():
        g["ram_mb"] = round(g["ram_mb"])
        g["cpu_percent"] = round(g["cpu_percent"], 1)
    return sorted(groups.values(), key=lambda g: g["ram_mb"], reverse=True)


def _windows() -> list[dict]:
    """Visible top-level windows: title, owning program, focused?, minimized?. Titles only — no contents."""
    fg = user32.GetForegroundWindow()
    own_pid = os.getpid()
    found: list[dict] = []
    names: dict[int, str] = {}

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def cb(hwnd, _):
        if not user32.IsWindowVisible(hwnd):
            return True
        if user32.GetWindowLongW(hwnd, GWL_EXSTYLE) & WS_EX_TOOLWINDOW:
            return True
        cloaked = ctypes.c_int(0)
        if dwmapi.DwmGetWindowAttribute(hwnd, DWMWA_CLOAKED, ctypes.byref(cloaked), ctypes.sizeof(cloaked)) == 0 \
                and cloaked.value:
            return True                                   # hidden UWP shells, other virtual desktops
        n = user32.GetWindowTextLengthW(hwnd)
        if n <= 0:
            return True
        buf = ctypes.create_unicode_buffer(n + 1)
        user32.GetWindowTextW(hwnd, buf, n + 1)
        title = buf.value.strip()
        if not title or title == "Program Manager":
            return True
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value == own_pid:
            return True
        if pid.value not in names:
            try:
                names[pid.value] = psutil.Process(pid.value).name()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                names[pid.value] = "?"
        if names[pid.value].lower() in _OWN_NAMES:
            return True
        found.append({"title": title[:140], "app": names[pid.value], "foreground": hwnd == fg,
                      "minimized": bool(user32.IsIconic(hwnd)), "hwnd": int(hwnd or 0)})
        return True

    user32.EnumWindows(cb, 0)
    return found


def _startup() -> list[str]:
    """Programs set to start with Windows (the Run registry keys — what Task Manager's Startup tab shows)."""
    import winreg
    names: list[str] = []
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        try:
            with winreg.OpenKey(hive, r"Software\Microsoft\Windows\CurrentVersion\Run") as k:
                i = 0
                while True:
                    names.append(winreg.EnumValue(k, i)[0])
                    i += 1
        except OSError:
            continue
    return sorted(set(names))


def _network() -> dict | None:
    try:
        conns = [c for c in psutil.net_connections(kind="inet") if c.status == psutil.CONN_ESTABLISHED and c.pid]
    except (psutil.AccessDenied, OSError):
        return None
    counts: dict[str, int] = {}
    for c in conns:
        try:
            nm = psutil.Process(c.pid).name()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
        counts[nm] = counts.get(nm, 0) + 1
    top = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)[:8]
    return {"established": len(conns), "by_app": [{"app": a, "connections": n} for a, n in top]}


def snapshot() -> dict:
    psutil.cpu_percent(interval=None)                 # prime the system-wide counter
    apps = _apps()                                    # includes the 0.4 s CPU sampling window
    return {
        "taken_at": time.strftime("%Y-%m-%d %H:%M"),
        "system": _system(),
        "apps": apps,
        "windows": _windows(),
        "startup": _startup(),
        "network": _network(),
    }
