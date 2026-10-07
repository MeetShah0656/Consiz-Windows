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
_cache: dict = {"at": 0.0, "text": "", "summary": "", "windows": []}
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

    lines += ["", "OPEN WINDOWS (only titles are listed here; you CAN look inside any window by replying READ: <number>)"]
    wins = snap["windows"][:30]
    for n, w in enumerate(wins, 1):
        flag = " [FOCUSED]" if w["foreground"] else (" [minimized]" if w["minimized"] else "")
        lines.append(f"[{n}] {w['app']}: {w['title']}{flag}")
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
    snap = collect()
    text, summary = render(snap)
    with _lock:
        _cache.update(at=time.time(), text=text, summary=summary, windows=list(snap["windows"][:30]))
    return text, summary


def last_windows() -> list[dict]:
    """The numbered windows from the latest snapshot ([1] = first), for READ / focus-window lookups."""
    with _lock:
        return list(_cache["windows"])


# ====================================================================== layer 3: reading INSIDE windows
# The model first sees only window titles. If a question needs what is inside a window it replies
# "READ: 2, 5" (window numbers). Code then — only after the user allows it — reads those windows' text,
# removes secrets, and asks the model again with that text attached.
import re

SENSITIVE_APPS = {"keepass.exe", "keepassxc.exe", "1password.exe", "bitwarden.exe", "lastpass.exe",
                  "dashlane.exe", "enpass.exe", "nordpass.exe", "authy desktop.exe", "mstsc.exe"}
SENSITIVE_TITLE = re.compile(r"(?i)password|passcode|incognito|inprivate|private browsing|net ?banking|"
                             r"\bbank\b|paypal|wallet|authenticator|\b2fa\b|one-time|\botp\b")
BROWSERS = {"chrome.exe", "brave.exe", "msedge.exe", "firefox.exe", "opera.exe", "vivaldi.exe"}
READ_RE = re.compile(r"^\W*READ\s*:\s*([\d,\s]+)", re.IGNORECASE)
MAX_READ_WINDOWS = 3
MAX_IMAGES = 2                        # pictures of windows per question (apps that do not share their text)
TEXT_TOO_THIN = 250                   # fewer readable characters than this = "this app is hiding its text"
MAX_PER_WINDOW = 6000
MAX_TOTAL = 12000
_allowed: set[int] = set()            # windows the user approved during this run of the app
READ_CACHE_SECONDS = 300              # follow-ups about the same window reuse what was just read
_read_cache: dict[tuple[int, str], tuple[str, str | None, float]] = {}   # (hwnd, title) -> (text, picture, when)


def _cache_get(w: dict):
    hit = _read_cache.get((w["hwnd"], w["title"]))
    if hit and time.time() - hit[2] < READ_CACHE_SECONDS:
        return hit[0], hit[1]
    return None


def _cache_put(w: dict, text: str, pic: str | None) -> None:
    if len(_read_cache) > 20:
        _read_cache.clear()
    _read_cache[(w["hwnd"], w["title"])] = (text, pic, time.time())


def sensitive_reason(win: dict) -> str | None:
    """Why a window must never be read (password managers, private/banking windows), or None."""
    if win["app"].lower() in SENSITIVE_APPS:
        return "it is a password manager or remote-desktop window"
    if SENSITIVE_TITLE.search(win["title"]):
        return "its title looks private (password, banking, incognito...)"
    return None


def parse_read(first_line: str, n_windows: int) -> list[int]:
    """'READ: 2, 5' -> [2, 5] (1-based, valid, unique, at most MAX_READ_WINDOWS). Not a READ line -> []."""
    m = READ_RE.match(first_line.strip())
    if not m:
        return []
    out: list[int] = []
    for tok in re.split(r"[,\s]+", m.group(1).strip()):
        if tok.isdigit() and 1 <= int(tok) <= n_windows and int(tok) not in out:
            out.append(int(tok))
    return out[:MAX_READ_WINDOWS]


def _clean_stream(pieces, drop):
    """Pass a text stream through line by line, dropping lines for which drop(line) is true."""
    buf = ""
    for p in pieces:
        buf += p
        while "\n" in buf:
            line, buf = buf.split("\n", 1)
            if not drop(line):
                yield line + "\n"
    if buf and not drop(buf):
        yield buf


def gather_contents(indices: list[int], windows: list[dict], read_text, confirm, notify,
                    capture_image=None) -> tuple[str, list[str], bool]:
    """(contents block for the model, pictures [base64 JPEG], declined).
    Asks `confirm(titles)` once for windows not yet approved. If an app shares almost no text (browsers, many
    Electron apps), a picture of that one window is taken instead (`capture_image`), at most MAX_IMAGES."""
    wins = [(i, windows[i - 1]) for i in indices]
    blocked = [(i, w, sensitive_reason(w)) for i, w in wins]
    ok = [(i, w) for i, w, why in blocked if not why]
    notes = [f"[{i}] {w['app']}: NOT READ — {why}." for i, w, why in blocked if why]
    new = [w for _, w in ok if w["hwnd"] not in _allowed]
    if new and not confirm([f"{w['app']}: {w['title']}" for w in new]):
        return "", [], True
    _allowed.update(w["hwnd"] for _, w in ok)

    parts, used, images = [], 0, []
    for i, w in ok:
        cached = _cache_get(w)
        if cached is not None:
            text, pic = cached
            notify(f"Using what I read earlier: {w['title'][:40]}")
            if pic and len(images) < MAX_IMAGES:
                images.append(pic)
                parts.append(f"[{i}] {w['app']}: {w['title']}\n(A PICTURE of the window is attached as image "
                             f"{len(images)}. Read the text from the picture.)")
                continue
            if len(text.strip()) >= TEXT_TOO_THIN:
                used += len(text)
                parts.append(f"[{i}] {w['app']}: {w['title']}\n{text}")
                continue
        notify(f"Reading: {w['title'][:50]}")
        try:
            text, method = read_text(w["hwnd"])
        except Exception as e:
            text, method = "", f"error {type(e).__name__}"
        text, _found = security.redact(text or "")
        text = text[:MAX_PER_WINDOW]
        text = text[:max(0, MAX_TOTAL - used)]
        used += len(text)
        if len(text.strip()) < TEXT_TOO_THIN and w.get("minimized"):
            # A minimized window cannot be photographed: offer the Switch button instead of failing silently.
            parts.append(f"[{i}] {w['app']}: {w['title']}\n(This window is MINIMIZED, so I cannot see it. Tell the "
                         f"user to switch to it and ask again; end your answer with the line: ACTION: focus_window {i})")
            continue
        if len(text.strip()) < TEXT_TOO_THIN and capture_image is not None and len(images) < MAX_IMAGES:
            notify(f"Taking a picture of: {w['title'][:45]}")
            try:
                pic = capture_image(w["hwnd"])
            except Exception:
                pic = None
            if pic:
                images.append(pic)
                _cache_put(w, text, pic)
                parts.append(f"[{i}] {w['app']}: {w['title']}\n(This app does not share its text, so a PICTURE of "
                             f"the window is attached as image {len(images)}. Read the text from the picture.)")
                continue
        if w["app"].lower() in BROWSERS and len(text) < TEXT_TOO_THIN:
            text += ("\n(Only the browser's own controls were readable. Browsers hide page text from other apps "
                     "unless accessibility is on: open chrome://accessibility (or edge://, brave://) and turn on "
                     "'Native accessibility API support', then ask again. Or select the text and press the "
                     "middle mouse button.)")
        if not text.strip():
            text = "(nothing readable — this app does not share its text with other programs)"
        elif len(text.strip()) >= TEXT_TOO_THIN:
            _cache_put(w, text, None)
        parts.append(f"[{i}] {w['app']}: {w['title']}\n{text}")
    return "\n\n".join(notes + parts), images, False


_LEAK_RE = re.compile(r"(?i)\bREAD\s*:\s*\d")


def stream_answer(question: str, history: list[dict], snapshot_text: str, windows: list[dict], *,
                  stream_fn, read_text, confirm, notify, capture_image=None):
    """Yield the answer text. Handles the READ round-trip; everything else streams straight through.
    Any line that still mentions the internal 'READ: n' protocol is removed — users never see it."""
    yield from _clean_stream(
        _stream_answer_raw(question, history, snapshot_text, windows, stream_fn=stream_fn, read_text=read_text,
                           confirm=confirm, notify=notify, capture_image=capture_image),
        lambda ln: bool(_LEAK_RE.search(ln)))


def _stream_answer_raw(question: str, history: list[dict], snapshot_text: str, windows: list[dict], *,
                       stream_fn, read_text, confirm, notify, capture_image=None):
    from . import llm
    pieces = stream_fn(llm.pc_messages(snapshot_text, history, question))
    buf, decided = "", False
    for piece in pieces:
        buf += piece
        if not decided and ("\n" in buf or len(buf) >= 90):
            decided = True
            if parse_read(buf.lstrip().split("\n", 1)[0], len(windows)):
                break                                   # a READ request: do not show it, handle below
            yield buf
        elif decided:
            yield piece
    else:
        if not decided:
            if not parse_read(buf.strip().split("\n", 1)[0], len(windows)):
                yield buf
                return
    indices = parse_read(buf.lstrip().split("\n", 1)[0], len(windows))
    if not indices:
        return
    block, images, declined = gather_contents(indices, windows, read_text, confirm, notify, capture_image)
    if declined:
        yield "- You chose not to let me read that window, so I can't answer from what is inside it.\n"
        return
    msgs = llm.pc_messages(snapshot_text, history, question, contents=block, images=images)
    yield from _clean_stream(stream_fn(msgs), lambda ln: bool(READ_RE.match(ln.strip())))
