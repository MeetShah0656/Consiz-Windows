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
from fastapi.responses import HTMLResponse, StreamingResponse
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


# ------------------------------------------------------------------ public pages (Google consent screen links)
# App name here MUST match the OAuth consent screen name exactly ("Consiz"): Google compares them.
APP_NAME = "Consiz"

_PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
{verify}<title>{title}</title><style>
body{{font-family:Segoe UI,Arial,sans-serif;background:#F8F1E3;color:#43151B;margin:0;line-height:1.6}}
main{{max-width:760px;margin:0 auto;padding:40px 20px}}h1{{color:#611E29}}h3{{color:#611E29;margin-top:28px}}
a{{color:#7A2835}}li{{margin:6px 0}}footer{{margin-top:40px;font-size:14px}}
</style></head><body><main>{body}<footer><a href="/">Home</a> &middot; <a href="/privacy">Privacy Policy</a> &middot;
Contact: <a href="mailto:{contact}">{contact}</a></footer></main></body></html>"""


def _contact() -> str:
    return _cfg("CONTACT_EMAIL", "alpha.kore25@gmail.com")


def _page(title: str, body: str) -> str:
    """GOOGLE_SITE_VERIFICATION (optional) = the content value of the Search Console HTML-tag verification."""
    token = _cfg("GOOGLE_SITE_VERIFICATION")
    verify = f'<meta name="google-site-verification" content="{token}">' if token else ""
    return _PAGE.format(verify=verify, title=title, body=body, contact=_contact())


@app.get("/", response_class=HTMLResponse)
def home():
    return _page(APP_NAME, (
        f"<h1>{APP_NAME}</h1>"
        f"<p><b>{APP_NAME}</b> is a Windows desktop app that explains anything on your screen. Select some text "
        "or a file, press the middle mouse button, and a small window shows a short, simple explanation, summary, "
        "translation or answer. You can then ask follow-up questions in the same chat window.</p>"
        "<h3>Why sign in with Google?</h3>"
        f"<p>{APP_NAME} uses Google Sign-In only to know who is using the service, so we can apply a fair daily "
        "limit per person and prevent abuse. We request only your basic profile (name and email address). "
        "We do not access your Gmail, Drive, contacts, calendar or any other Google data.</p>"
        '<p>Read our <a href="/privacy">Privacy Policy</a>.</p>'))


@app.get("/privacy", response_class=HTMLResponse)
def privacy():
    return _page(f"{APP_NAME} Privacy Policy", (
        f"<h1>{APP_NAME} Privacy Policy</h1>"
        "<p>Last updated: October 2026. This policy explains what information the "
        f"{APP_NAME} Windows app and its service collect, how it is used, and your choices.</p>"
        "<h3>Information we collect</h3><ul>"
        "<li><b>Google account information:</b> when you sign in with Google we receive your name, email address "
        "and a unique Google account ID. We never receive your Google password.</li>"
        "<li><b>Usage counts:</b> the number of answers you request each day, linked to your Google account ID "
        "and email, plus a daily count per network (IP address) to prevent abuse.</li>"
        "<li><b>Content you choose to send:</b> the text (or file excerpt) you select and the follow-up questions "
        "you type are sent through our server to an AI provider to produce your answer.</li></ul>"
        "<h3>How we use it</h3><ul>"
        "<li>Google account information: to sign you in and to apply daily usage limits. Nothing else.</li>"
        "<li>Selected content and questions: only to generate your answer. We do not store them on our server "
        "and we do not use them to train models. The AI provider (OpenRouter and the model it routes to) processes "
        "them under its own terms.</li>"
        "<li>On your computer, sensitive patterns such as passwords, API keys and card numbers are removed "
        "before anything is sent.</li></ul>"
        "<h3>Google user data</h3>"
        f"<p>{APP_NAME}'s use and transfer of information received from Google APIs adheres to the "
        '<a href="https://developers.google.com/terms/api-services-user-data-policy">Google API Services User Data '
        "Policy</a>, including the Limited Use requirements. We use Google data only for sign-in and usage limits. "
        "We do not sell it, do not use it for advertising, and do not let people read it except as needed to run "
        "the service or comply with law.</p>"
        "<h3>Sharing</h3><p>We do not sell your data. We share information only with the services that run "
        "the product: Google (sign-in), OpenRouter and its AI model providers (answers), Render (hosting) and Neon "
        "(database for usage counts).</p>"
        "<h3>Retention and deletion</h3><p>Usage counts and account identifiers are kept only as long as needed to "
        "run daily limits and prevent abuse. To delete your data, email us at the address below and we will remove "
        "it. You can also tap <i>Sign out</i> in the app's tray menu to remove the sign-in from your computer, and "
        'revoke access at any time at <a href="https://myaccount.google.com/permissions">'
        "myaccount.google.com/permissions</a>.</p>"
        "<h3>Security</h3><p>Connections use HTTPS. The sign-in token is stored in the Windows Credential Manager. "
        "Our AI provider key is kept only on our server, never in the app.</p>"
        "<h3>Children</h3><p>The service is not directed to children under 13.</p>"
        "<h3>Changes and contact</h3><p>We may update this policy and will change the date above. Questions or "
        f'deletion requests: <a href="mailto:{_contact()}">{_contact()}</a>.</p>'))


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
