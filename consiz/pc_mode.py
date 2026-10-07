"""Ask-about-my-PC mode (shared logic): turn a PC snapshot into the compact, redacted text the model sees.

Rules (same as the rest of Consiz):
  - Code computes every number and highlight; the model only explains them (no arithmetic by the LLM).
  - The snapshot is DATA, never instructions (window titles can contain anything).
  - Window titles go through the same secret redaction as selected text before leaving the machine.
  - Read-only: nothing here changes, closes or sends anything on the PC.
"""
from __future__ import annotations

import threading
import time

from . import security

MAX_CHARS = 6500                 # the whole snapshot block; keeps the request small and fast
CACHE_SECONDS = 15               # follow-up questions inside this window reuse the same snapshot
_cache: dict = {"at": 0.0, "text": "", "summary": ""}
_lock = threading.Lock()


def _gb(mb: float) -> str:
    return f"{mb / 1024:.1f} GB" if mb >= 1024 else f"{mb:.0f} MB"


def highlights(snap: dict) -> list[str]:
    """Things worth a person's attention, worked out by code (never by the model)."""
    sysd, out = snap["system"], []
    for d in sysd.get("disks", []):
        if d["percent_used"] >= 90:
            out.append(f"Disk {d['drive']} is {d['percent_used']}% full — only {d['free_gb']} GB free of {d['total_gb']} GB.")
    if sysd["ram_percent"] >= 80:
        out.append(f"Memory is {sysd['ram_percent']}% used ({sysd['ram_used_gb']} of {sysd['ram_total_gb']} GB).")
    if sysd["cpu_percent"] >= 70:
        out.append(f"CPU is busy right now ({sysd['cpu_percent']}%).")
    if sysd["uptime_hours"] >= 24 * 7:
        out.append(f"The PC has not restarted for {sysd['uptime_hours'] / 24:.0f} days.")
    b = sysd.get("battery")
    if b and b["percent"] <= 20 and not b["plugged"]:
        out.append(f"Battery is low ({b['percent']}%) and not charging.")
    used_mb = sysd["ram_used_gb"] * 1024
    apps = snap["apps"][:3]
    if apps and used_mb:
        top_mb = sum(a["ram_mb"] for a in apps)
        out.append("The 3 biggest memory users ("
                   + ", ".join(a["name"] for a in apps)
                   + f") hold {_gb(top_mb)}, about {top_mb / used_mb * 100:.0f}% of used memory.")
    return out


def render(snap: dict) -> tuple[str, str]:
    """(text for the model, one-line summary for the UI), both from the same snapshot."""
    sysd = snap["system"]
    lines = [f"PC snapshot taken {snap['taken_at']}.", "", "SYSTEM"]
    lines.append(f"- CPU {sysd['cpu_percent']}% busy ({sysd['cpu_cores']} logical cores); "
                 f"memory {sysd['ram_used_gb']} of {sysd['ram_total_gb']} GB used ({sysd['ram_percent']}%); "
                 f"{sysd['process_count']} processes; up {sysd['uptime_hours']} hours.")
    for d in sysd.get("disks", []):
        lines.append(f"- Disk {d['drive']} {d['free_gb']} GB free of {d['total_gb']} GB ({d['percent_used']}% used).")
    b = sysd.get("battery")
    if b:
        lines.append(f"- Battery {b['percent']}%, {'charging/plugged in' if b['plugged'] else 'on battery'}.")

    hl = highlights(snap)
    if hl:
        lines += ["", "HIGHLIGHTS (worked out by code)"] + [f"- {h}" for h in hl]

    lines += ["", "OPEN WINDOWS (title only; contents are not visible)"]
    wins = snap["windows"][:30]
    for w in wins:
        flag = " [FOCUSED]" if w["foreground"] else (" [minimized]" if w["minimized"] else "")
        lines.append(f"- {w['app']}: {w['title']}{flag}")
    if not wins:
        lines.append("- (none found)")

    lines += ["", "PROGRAMS BY MEMORY (a program with many processes is shown once)"]
    for a in snap["apps"][:15]:
        lines.append(f"- {a['name']}: {a['processes']} process(es), {_gb(a['ram_mb'])}, CPU {a['cpu_percent']}%")
    busy = [a for a in sorted(snap["apps"], key=lambda a: a["cpu_percent"], reverse=True)[:6] if a["cpu_percent"] >= 0.5]
    if busy:
        lines += ["", "BUSIEST ON CPU (last half second)"]
        lines += [f"- {a['name']}: {a['cpu_percent']}%" for a in busy]

    if snap.get("startup"):
        lines += ["", "STARTS WITH WINDOWS", "- " + ", ".join(snap["startup"][:25])]
    net = snap.get("network")
    if net:
        lines += ["", f"NETWORK: {net['established']} active connections; most: "
                  + ", ".join(f"{x['app']} ({x['connections']})" for x in net["by_app"][:6])]

    text, _found = security.redact("\n".join(lines))
    if len(text) > MAX_CHARS:
        text = text[:MAX_CHARS] + "\n[... snapshot truncated ...]"
    summary = f"{len(snap['windows'])} windows · {len(snap['apps'])} programs"
    return text, summary


def get_context(collect=None, force: bool = False) -> tuple[str, str]:
    """(snapshot text, summary). Reuses a snapshot younger than CACHE_SECONDS. `collect` is injectable for tests."""
    with _lock:
        if not force and _cache["text"] and time.time() - _cache["at"] < CACHE_SECONDS:
            return _cache["text"], _cache["summary"]
    if collect is None:
        from . import sysinfo
        collect = sysinfo.snapshot
    text, summary = render(collect())
    with _lock:
        _cache.update(at=time.time(), text=text, summary=summary)
    return text, summary
