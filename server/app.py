"""Conciz backend: the ONLY place the OpenRouter key lives.

The desktop app sends a Google ID token; we verify it (signature, audience, expiry, verified email),
apply a per-user daily limit, force our own model/limits, and stream the answer back.

Run:  pip install -r server/requirements.txt
      uvicorn server.app:app --host 0.0.0.0 --port 8080
Env:  OPENROUTER_API_KEY, GOOGLE_CLIENT_ID (same desktop client the app uses),
      OPENROUTER_MODEL, DAILY_LIMIT (default 50), MAX_OUTPUT_TOKENS, ALLOWED_EMAILS (optional, comma list)
"""
from __future__ import annotations

import os
import sqlite3
import threading
from datetime import datetime, timezone

import requests
from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import StreamingResponse
from google.auth.transport import requests as g_requests
from google.oauth2 import id_token as g_id_token

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
DB_PATH = os.environ.get("CONSIZ_SERVER_DB", "conciz_server.db")

app = FastAPI(title="Conciz backend")
_db_lock = threading.Lock()
_g_request = g_requests.Request()


def _cfg(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _db() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PATH)
    con.execute("CREATE TABLE IF NOT EXISTS usage (sub TEXT, email TEXT, day TEXT, n INTEGER, PRIMARY KEY (sub, day))")
    return con


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


def _take_quota(info: dict) -> None:
    limit = int(_cfg("DAILY_LIMIT", "50"))
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    with _db_lock, _db() as con:
        row = con.execute("SELECT n FROM usage WHERE sub=? AND day=?", (info["sub"], day)).fetchone()
        n = row[0] if row else 0
        if n >= limit:
            raise HTTPException(429, f"Daily limit of {limit} answers reached. Try again tomorrow.")
        con.execute("INSERT INTO usage (sub, email, day, n) VALUES (?,?,?,1) "
                    "ON CONFLICT(sub, day) DO UPDATE SET n = n + 1", (info["sub"], info["email"], day))


@app.get("/health")
def health():
    return {"ok": True}


@app.post("/v1/chat/completions")
def chat(body: dict, authorization: str | None = Header(default=None)):
    info = _verify(authorization)
    key = _cfg("OPENROUTER_API_KEY")
    if not key:
        raise HTTPException(500, "Server is not configured.")
    messages = body.get("messages")
    if not isinstance(messages, list) or not messages:
        raise HTTPException(400, "Bad request.")
    _take_quota(info)

    # The client never picks the model or the budget; the server does.
    cap = int(_cfg("MAX_OUTPUT_TOKENS", "5000"))
    model = _cfg("OPENROUTER_MODEL", "inclusionai/ling-3.0-flash-fin:free")
    fallbacks = [m for m in _cfg("OPENROUTER_FALLBACKS", "inclusionai/ling-3.0-flash-sante:free,nvidia/nemotron-3-ultra-550b-a55b:free").split(",") if m.strip()]
    payload = {
        "model": model,
        "models": [model, *fallbacks][:3],
        "messages": messages,
        "temperature": min(float(body.get("temperature", 0.2)), 1.0),
        "max_tokens": min(int(body.get("max_tokens", 2500)), cap),
        "reasoning": body.get("reasoning") or {"enabled": False, "exclude": True},
        "stream": True,
    }
    try:
        upstream = requests.post(OPENROUTER_URL, json=payload, stream=True, timeout=(10, 60), headers={
            "Authorization": f"Bearer {key}", "Content-Type": "application/json", "X-Title": "As Conciz"})
    except requests.RequestException:
        raise HTTPException(502, "The AI provider is unreachable.")
    if upstream.status_code != 200:
        raise HTTPException(502 if upstream.status_code >= 500 else upstream.status_code,
                            f"AI provider error ({upstream.status_code}).")

    def relay():
        try:
            for chunk in upstream.iter_content(chunk_size=None):
                yield chunk
        finally:
            upstream.close()

    return StreamingResponse(relay(), media_type="text/event-stream")
