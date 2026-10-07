"""Conciz backend: the ONLY place the OpenRouter key lives.

The desktop app sends a Google ID token; we verify it (signature, audience, expiry, verified email),
apply limits, force our own model/limits, and stream the answer back.

Run:  pip install -r server/requirements.txt
      uvicorn server.app:app --host 0.0.0.0 --port 8080
Env (required): OPENROUTER_API_KEY, GOOGLE_CLIENT_ID (same desktop client the app uses)
Env (optional): OPENROUTER_MODEL, OPENROUTER_FALLBACKS, MAX_OUTPUT_TOKENS (5000), ALLOWED_EMAILS (comma list),
  DAILY_LIMIT (50 answers per user/day), IP_DAILY_LIMIT (300 per IP/day), RATE_PER_MIN (12 per user),
  MAX_INPUT_CHARS (40000), MAX_MESSAGES (30),
  DATABASE_URL  -> Postgres (e.g. a free Neon/Render database) so counts survive restarts.
                   Without it counts live in a local SQLite file (wiped when a free host restarts).
"""
from __future__ import annotations

import os
import sqlite3
import threading
import time
from collections import defaultdict, deque
from contextlib import contextmanager
from datetime import datetime, timezone

import requests
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import StreamingResponse
from google.auth.transport import requests as g_requests
from google.oauth2 import id_token as g_id_token

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
SQLITE_PATH = os.environ.get("CONSIZ_SERVER_DB", "conciz_server.db")

app = FastAPI(title="Conciz backend")
_db_lock = threading.Lock()
_g_request = g_requests.Request()
_recent: dict[str, deque] = defaultdict(deque)      # per-user timestamps for the per-minute limit


def _cfg(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


# ------------------------------------------------------------------ storage (SQLite or Postgres)
def _use_pg() -> bool:
    return _cfg("DATABASE_URL").startswith(("postgres://", "postgresql://"))


@contextmanager
def _db():
    """Yields (connection, placeholder). Commits on success, rolls back on error."""
    if _use_pg():
        import psycopg2
        con = psycopg2.connect(_cfg("DATABASE_URL"))
        ph = "%s"
    else:
        con = sqlite3.connect(SQLITE_PATH)
        ph = "?"
    try:
        cur = con.cursor()
        cur.execute("CREATE TABLE IF NOT EXISTS usage (sub TEXT, email TEXT, day TEXT, n INTEGER, "
                    "PRIMARY KEY (sub, day))")
        yield cur, ph
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _bump(cur, ph: str, key: str, email: str, limit: int, what: str) -> None:
    cur.execute(f"SELECT n FROM usage WHERE sub={ph} AND day={ph}", (key, _today()))
    row = cur.fetchone()
    if (row[0] if row else 0) >= limit:
        raise HTTPException(429, f"{what} limit of {limit} answers reached. Try again tomorrow.")
    cur.execute(f"INSERT INTO usage (sub, email, day, n) VALUES ({ph},{ph},{ph},1) "
                f"ON CONFLICT(sub, day) DO UPDATE SET n = usage.n + 1", (key, email, _today()))


def _take_quota(info: dict, ip: str) -> None:
    with _db_lock, _db() as (cur, ph):
        _bump(cur, ph, info["sub"], info["email"], int(_cfg("DAILY_LIMIT", "50")), "Daily")
        if ip:
            _bump(cur, ph, "ip:" + ip, "", int(_cfg("IP_DAILY_LIMIT", "300")), "Network daily")


def _refund_quota(info: dict, ip: str) -> None:
    """The AI provider failed, so the user shouldn't lose an answer."""
    try:
        with _db_lock, _db() as (cur, ph):
            for key in (info["sub"], "ip:" + ip if ip else None):
                if key:
                    cur.execute(f"UPDATE usage SET n = n - 1 WHERE sub={ph} AND day={ph} AND n > 0", (key, _today()))
    except Exception:
        pass


def _rate_limit(sub: str) -> None:
    limit, now = int(_cfg("RATE_PER_MIN", "12")), time.time()
    q = _recent[sub]
    while q and now - q[0] > 60:
        q.popleft()
    if len(q) >= limit:
        raise HTTPException(429, "Too many requests. Wait a few seconds.")
    q.append(now)


# ------------------------------------------------------------------ auth + input validation
def _verify(authorization: str | None) -> dict:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "Sign in required.")
    token = authorization[7:].strip()
    client_id = _cfg("GOOGLE_CLIENT_ID")
    if not client_id:
        raise HTTPException(500, "Server is not configured.")
    try:
        info = g_id_token.verify_oauth2_token(token, _g_request, client_id, clock_skew_in_seconds=10)
    except ValueError:
        raise HTTPException(401, "Sign-in expired. Please sign in again.")
    if not info.get("email_verified"):
        raise HTTPException(403, "Your Google email is not verified.")
    allowed = {e.strip().lower() for e in _cfg("ALLOWED_EMAILS").split(",") if e.strip()}
    if allowed and info["email"].lower() not in allowed:
        raise HTTPException(403, "This account is not allowed.")
    return info


def _clean_messages(messages) -> list[dict]:
    """Only plain role/content text, bounded in count and size (a custom client can't run up the bill)."""
    if not isinstance(messages, list) or not messages or len(messages) > int(_cfg("MAX_MESSAGES", "30")):
        raise HTTPException(400, "Bad request.")
    out, total = [], 0
    for m in messages:
        if not isinstance(m, dict) or m.get("role") not in ("system", "user", "assistant") \
                or not isinstance(m.get("content"), str):
            raise HTTPException(400, "Bad request.")
        total += len(m["content"])
        out.append({"role": m["role"], "content": m["content"]})
    if total > int(_cfg("MAX_INPUT_CHARS", "40000")):
        raise HTTPException(413, "That is too long. Select less text.")
    return out


def _num(value, default, lo, hi):
    try:
        return min(max(type(default)(value), lo), hi)
    except (TypeError, ValueError):
        return default


def _reasoning(raw) -> dict:
    """Allow only the two reasoning policies the app uses; ignore anything else."""
    if isinstance(raw, dict) and raw.get("enabled") is False:
        return {"enabled": False, "exclude": True}
    if isinstance(raw, dict) and "max_tokens" in raw:
        return {"max_tokens": _num(raw.get("max_tokens"), 256, 1, 1024), "exclude": True}
    return {"enabled": False, "exclude": True}


def _client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for", "")
    return (fwd.split(",")[0].strip() if fwd else (request.client.host if request.client else ""))[:64]


# ------------------------------------------------------------------ routes
@app.get("/health")
def health():
    """Also reports which storage backs the daily limits (no secrets) and whether it is reachable."""
    storage, db_ok = ("postgres" if _use_pg() else "sqlite"), True
    try:
        with _db() as (cur, ph):
            cur.execute("SELECT 1")
    except Exception as e:
        db_ok = False
        return {"ok": True, "storage": storage, "db_ok": db_ok, "db_error": type(e).__name__}
    return {"ok": True, "storage": storage, "db_ok": db_ok}


@app.post("/v1/chat/completions")
def chat(body: dict, request: Request, authorization: str | None = Header(default=None)):
    info = _verify(authorization)
    key = _cfg("OPENROUTER_API_KEY")
    if not key:
        raise HTTPException(500, "Server is not configured.")
    messages = _clean_messages(body.get("messages"))
    ip = _client_ip(request)
    _rate_limit(info["sub"])
    _take_quota(info, ip)

    # The client never picks the model or the budget; the server does.
    cap = int(_cfg("MAX_OUTPUT_TOKENS", "5000"))
    model = _cfg("OPENROUTER_MODEL", "inclusionai/ling-3.0-flash-fin:free")
    fallbacks = [m.strip() for m in _cfg(
        "OPENROUTER_FALLBACKS",
        "inclusionai/ling-3.0-flash-sante:free,nvidia/nemotron-3-ultra-550b-a55b:free").split(",") if m.strip()]
    payload = {
        "model": model,
        "models": [model, *fallbacks][:3],
        "messages": messages,
        "temperature": _num(body.get("temperature"), 0.2, 0.0, 1.0),
        "max_tokens": _num(body.get("max_tokens"), 2500, 1, cap),
        "reasoning": _reasoning(body.get("reasoning")),
        "stream": True,
    }
    try:
        upstream = requests.post(OPENROUTER_URL, json=payload, stream=True, timeout=(10, 60), headers={
            "Authorization": f"Bearer {key}", "Content-Type": "application/json", "X-Title": "As Conciz"})
    except requests.RequestException:
        _refund_quota(info, ip)
        raise HTTPException(502, "The AI provider is unreachable.")
    if upstream.status_code != 200:
        _refund_quota(info, ip)
        raise HTTPException(502 if upstream.status_code >= 500 else upstream.status_code,
                            f"AI provider error ({upstream.status_code}).")

    def relay():
        try:
            for chunk in upstream.iter_content(chunk_size=None):
                yield chunk
        finally:
            upstream.close()

    return StreamingResponse(relay(), media_type="text/event-stream")
