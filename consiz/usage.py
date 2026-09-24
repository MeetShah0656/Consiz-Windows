"""Local quota meter for the OpenRouter free tier. Counts requests per key per UTC day."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import os
import pathlib
import threading

STORE = pathlib.Path(os.environ.get("CONSIZ_STATE_DIR", pathlib.Path.home() / ".consiz")) / "usage.json"
FREE_LIMIT_NO_CREDITS = 50
FREE_LIMIT_WITH_CREDITS = 1000
_lock = threading.Lock()


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _load() -> dict:
    try:
        data = json.loads(STORE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if data.get("date") == _today() else {}


def _save(data: dict) -> None:
    data["date"] = _today()
    try:
        STORE.parent.mkdir(parents=True, exist_ok=True)
        STORE.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except OSError:
        pass


def record(key: str, exhausted: bool = False) -> None:
    with _lock:
        data = _load()
        counts = data.setdefault("counts", {})
        tail = key[-8:] if key else "local"
        counts[tail] = counts.get(tail, 0) + (0 if exhausted else 1)
        if exhausted:
            exhausted_list = data.setdefault("exhausted", [])
            if tail not in exhausted_list:
                exhausted_list.append(tail)
        _save(data)


def limit_for(has_credits: bool) -> int:
    return FREE_LIMIT_WITH_CREDITS if has_credits else FREE_LIMIT_NO_CREDITS


def snapshot(keys: list[str], has_credits: bool = False) -> dict:
    data = _load()
    counts, spent = data.get("counts", {}), set(data.get("exhausted", []))
    per_key = limit_for(has_credits)
    used = total = 0
    for k in keys or []:
        tail = k[-8:]
        used += per_key if tail in spent else min(counts.get(tail, 0), per_key)
        total += per_key
    left = max(total - used, 0)
    reset = (datetime.now(timezone.utc) + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    now_utc = datetime.now(timezone.utc)
    return {
        "used": used,
        "total": total,
        "left": left,
        "pct_left": round(100 * left / total) if total else 0,
        "keys": len(keys or []),
        "resets_in": reset - now_utc,
        "reset_local": reset.astimezone().strftime("%H:%M"),
    }


def bar(pct: int, width: int = 10) -> str:
    filled = round(width * pct / 100)
    return "█" * filled + "░" * (width - filled)


def compact(keys: list[str], has_credits: bool = False) -> str:
    s = snapshot(keys, has_credits)
    if not s["total"]:
        return ""
    if s["left"] == 0:
        return "quota used up"
    if s["pct_left"] <= 20:
        return f"⚠ {s['left']} left today"
    return f"{bar(s['pct_left'], 5)} {s['pct_left']}%"


def line(keys: list[str], has_credits: bool = False) -> str:
    s = snapshot(keys, has_credits)
    if not s["total"]:
        return ""
    hrs, rem = divmod(int(s["resets_in"].total_seconds()), 3600)
    key_note = f" across {s['keys']} keys" if s["keys"] > 1 else ""
    return (
        f"free quota {s['used']}/{s['total']} used today{key_note} · {bar(s['pct_left'])} "
        f"{s['pct_left']}% left · resets {s['reset_local']} (in {hrs}h{rem // 60:02d}m)"
    )
