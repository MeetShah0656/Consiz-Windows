"""Saved chats (T-13): optional, local, readable.

  - OFF until the person turns it on (Settings > General > Chat history): chats can hold private text.
  - Saved only on this PC, one small JSON file per chat in a folder the person can open (~/.consiz/history). Nothing is
    uploaded. Passwords, keys and card numbers are removed before a word is written (the same filter used before sending).
  - At most 200 chats; the oldest are removed first.
  - "Save as text" (export) is an explicit action and works even with history off: it writes one .txt the person can send.
Platform-free: the window code calls save(), the tray lists with recent() and the popup replays load().
"""
from __future__ import annotations

import json
import os
import re
import time
import uuid
from datetime import datetime
from pathlib import Path

from . import prefs, security

MAX_CHATS = 200
MAX_TEXT_CHARS = 20000


def enabled() -> bool:
    return bool(prefs.get("history_enabled", False))


def folder() -> Path:
    path = prefs.STORE.parent / "history"
    path.mkdir(parents=True, exist_ok=True)
    return path


def new_id() -> str:
    return time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:4]


def _clean(text: str) -> str:
    return security.redact(str(text))[0][:MAX_TEXT_CHARS]


def _title(messages: list[dict], fallback: str) -> str:
    first = next((m["text"] for m in messages if m["who"] == "You" and m["text"].strip()), "")
    text = (first or fallback or "Chat").strip().replace("\n", " ")
    return text[:60] + ("…" if len(text) > 60 else "")


def save(chat_id: str, mode: str, window_title: str, app: str, transcript: list[list[str]], started: float) -> bool:
    """Write (or update) one chat. Returns True when something was saved. Never raises: a full disk must not hurt a chat."""
    messages = [{"who": who, "text": _clean(text)} for who, text in transcript if str(text).strip()]
    if not enabled() or not any(m["who"] == "Consiz" for m in messages):
        return False
    record = {"id": chat_id, "started": started, "updated": time.time(), "mode": mode, "app": str(app)[:80],
              "title": _title(messages, window_title), "messages": messages}
    try:
        target = folder() / f"{chat_id}.json"
        tmp = target.with_suffix(".tmp")
        tmp.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, target)
        _prune()
        return True
    except OSError:
        return False


def _files() -> list[Path]:
    try:
        return sorted(folder().glob("*.json"), key=lambda p: p.name, reverse=True)       # names start with the date
    except OSError:
        return []


def _prune() -> None:
    for old in _files()[MAX_CHATS:]:
        try:
            old.unlink()
        except OSError:
            pass


def load(chat_id: str) -> dict | None:
    if not re.fullmatch(r"[0-9]{8}-[0-9]{6}-[0-9a-f]{4}", str(chat_id)):          # never a path from outside
        return None
    try:
        data = json.loads((folder() / f"{chat_id}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) and isinstance(data.get("messages"), list) else None


def recent(limit: int = 10) -> list[dict]:
    """Newest first: [{id, title, updated, mode, messages: n}]."""
    out = []
    for path in _files()[:limit * 3]:
        rec = load(path.stem)
        if rec:
            out.append({"id": rec.get("id", path.stem), "title": rec.get("title", "Chat"), "updated": rec.get("updated", 0),
                        "mode": rec.get("mode", "selection"), "messages": len(rec["messages"])})
        if len(out) >= limit:
            break
    return out


def count() -> int:
    return len(_files())


def delete_all() -> int:
    n = 0
    for path in _files() + list(folder().glob("*.tmp")):
        try:
            path.unlink()
            n += 1
        except OSError:
            pass
    return n


def to_text(record: dict) -> str:
    """The chat as plain text a person can read, print or send."""
    when = datetime.fromtimestamp(record.get("started") or time.time()).strftime("%d %b %Y, %H:%M")
    head = f"Consiz chat · {when}" + (f" · {record['app']}" if record.get("app") else "")
    body = "\n\n".join(f"{m['who']}:\n{m['text']}" for m in record["messages"])
    return f"{head}\n{'-' * len(head)}\n\n{body}\n"


def export_text(transcript: list[list[str]], title: str, app: str, started: float, where: Path | None = None) -> Path:
    """Write the chat shown on screen to a .txt file (default: Documents\\Consiz chats). Raises OSError if it cannot."""
    messages = [{"who": who, "text": _clean(text)} for who, text in transcript if str(text).strip()]
    record = {"started": started, "app": app, "messages": messages}
    where = where or (Path.home() / "Documents" / "Consiz chats")
    where.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[^\w\- ]+", "", _title(messages, title))[:40].strip() or "chat"
    path = where / f"{safe} {time.strftime('%Y-%m-%d %H%M%S')}.txt"
    path.write_text(to_text(record), encoding="utf-8")
    return path
