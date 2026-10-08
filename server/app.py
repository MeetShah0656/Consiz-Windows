"""Conciz backend: the ONLY place the OpenRouter key lives.

The desktop app sends a Google ID token; we verify it (signature, audience, expiry, verified email),
apply limits, force our own model/limits, and stream the answer back.

Run:  pip install -r server/requirements.txt
      uvicorn server.app:app --host 0.0.0.0 --port 8080
Env (required): OPENROUTER_API_KEY, GOOGLE_CLIENT_ID (same desktop client the app uses)
Env (optional): OPENROUTER_MODEL, OPENROUTER_FALLBACKS, MAX_OUTPUT_TOKENS (5000), ALLOWED_EMAILS (comma list),
  DAILY_LIMIT (50 answers per user/day), IP_DAILY_LIMIT (300 per IP/day), RATE_PER_MIN (12 per user),
  MAX_INPUT_CHARS (40000), MAX_MESSAGES (30), MAX_IMAGES (2 pictures of windows per request),
  VISION_MODEL / VISION_FALLBACKS (image-reading models used when a request has pictures),
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
from fastapi.responses import HTMLResponse, PlainTextResponse, StreamingResponse
from google.auth.transport import requests as g_requests
from google.oauth2 import id_token as g_id_token

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
SQLITE_PATH = os.environ.get("CONSIZ_SERVER_DB", "conciz_server.db")

app = FastAPI(title="Conciz backend")
_g_request = g_requests.Request()
_recent: dict[str, deque] = defaultdict(deque)      # per-user timestamps for the per-minute limit


def _cfg(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


# ------------------------------------------------------------------ storage (SQLite or Postgres)
# Speed + resilience notes (measured: the old version spent ~2.5 s per request here):
#  - Postgres connections are POOLED and kept alive: a fresh connection to a far-away database costs ~1 s.
#  - The table is created once per process, not on every request.
#  - Counting both limits (user + network) is ONE database round trip (multi-row upsert with RETURNING).
#  - If the database is unreachable the server keeps answering, using best-effort in-memory limits (T-03).
_pool: dict = {"p": None}
_pool_lock = threading.Lock()
_schema_ready = {"done": False}
_mem_counts: dict[tuple[str, str], int] = defaultdict(int)       # fallback only: (key, day) -> n
_mem_lock = threading.Lock()
_SCHEMA = "CREATE TABLE IF NOT EXISTS usage (sub TEXT, email TEXT, day TEXT, n INTEGER, PRIMARY KEY (sub, day))"


def _use_pg() -> bool:
    return _cfg("DATABASE_URL").startswith(("postgres://", "postgresql://"))


def _pg_pool():
    with _pool_lock:
        if _pool["p"] is None:
            from psycopg2 import pool
            _pool["p"] = pool.ThreadedConnectionPool(
                1, 6, _cfg("DATABASE_URL"), connect_timeout=8,
                keepalives=1, keepalives_idle=30, keepalives_interval=10, keepalives_count=3)
        return _pool["p"]


def _is_connection_error(e: Exception) -> bool:
    return type(e).__module__.startswith("psycopg2") and type(e).__name__ in ("OperationalError", "InterfaceError")


@contextmanager
def _db():
    """Yields (cursor, placeholder). Commits on success, rolls back on error."""
    if _use_pg():
        pool = _pg_pool()
        con = pool.getconn()
        bad = False
        try:
            cur = con.cursor()
            if not _schema_ready["done"]:
                cur.execute(_SCHEMA)
                con.commit()
                _schema_ready["done"] = True
            yield cur, "%s"
            con.commit()
        except Exception as e:
            bad = _is_connection_error(e)
            if not bad:
                try:
                    con.rollback()
                except Exception:
                    bad = True
            raise
        finally:
            pool.putconn(con, close=bad or bool(con.closed))
    else:
        con = sqlite3.connect(SQLITE_PATH)
        try:
            cur = con.cursor()
            cur.execute(_SCHEMA)
            yield cur, "?"
            con.commit()
        except Exception:
            con.rollback()
            raise
        finally:
            con.close()


def _run_db(work):
    """work(cursor, placeholder) -> result, in one transaction. A pooled connection the database closed while
    idle is dropped and the work is retried once on a fresh one."""
    for attempt in (1, 2):
        try:
            with _db() as (cur, ph):
                return work(cur, ph)
        except Exception as e:
            if attempt == 1 and _is_connection_error(e):
                continue
            raise


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _bump_all(cur, ph: str, keys: list[tuple[str, str, int, str]]):
    """Count one answer for every key in ONE statement. Returns (what, limit) of the first limit exceeded, else None
    (and in that case the count is taken back so a refused request is not charged)."""
    day = _today()
    params: list = []
    for key, email, _limit, _what in keys:
        params += [key, email, day]
    values = ",".join(f"({ph},{ph},{ph},1)" for _ in keys)
    cur.execute(f"INSERT INTO usage (sub, email, day, n) VALUES {values} "
                f"ON CONFLICT(sub, day) DO UPDATE SET n = usage.n + 1 RETURNING sub, n", params)
    counts = {row[0]: row[1] for row in cur.fetchall()}
    for key, _email, limit, what in keys:
        if counts.get(key, 0) > limit:
            cur.execute(f"UPDATE usage SET n = n - 1 WHERE day={ph} AND sub IN ({','.join([ph] * len(keys))})",
                        [day] + [k[0] for k in keys])
            return what, limit
    return None


def _bump_memory(keys: list[tuple[str, str, int, str]]):
    day = _today()
    with _mem_lock:
        for key, _email, limit, what in keys:
            if _mem_counts[(key, day)] >= limit:
                return what, limit
        for key, *_ in keys:
            _mem_counts[(key, day)] += 1
    return None


def _take_quota(info: dict, ip: str) -> None:
    keys = [(info["sub"], info["email"], int(_cfg("DAILY_LIMIT", "50")), "Daily")]
    if ip:
        keys.append(("ip:" + ip, "", int(_cfg("IP_DAILY_LIMIT", "300")), "Network daily"))
    try:
        over = _run_db(lambda cur, ph: _bump_all(cur, ph, keys))
    except Exception as e:                                   # database down: stay up with in-memory limits
        print(f"[server] database unavailable ({type(e).__name__}); using in-memory limits", flush=True)
        over = _bump_memory(keys)
    if over:
        what, limit = over
        raise HTTPException(429, f"{what} limit of {limit} answers reached. Try again tomorrow.")


def _refund_quota(info: dict, ip: str) -> None:
    """The AI provider failed, so the user shouldn't lose an answer."""
    keys = [info["sub"]] + (["ip:" + ip] if ip else [])
    day = _today()
    with _mem_lock:
        for k in keys:
            if _mem_counts.get((k, day), 0) > 0:
                _mem_counts[(k, day)] -= 1
    try:
        _run_db(lambda cur, ph: cur.execute(
            f"UPDATE usage SET n = n - 1 WHERE day={ph} AND n > 0 AND sub IN ({','.join([ph] * len(keys))})",
            [day] + keys))
    except Exception:
        pass


# ------------------------------------------------------------------ AI models: self-healing list
# Free models come and go (the old default was removed and every request first failed on it). The server asks
# OpenRouter which models exist (cached 30 min) and silently drops dead ones, ending with the auto-router.
_models_cache: dict = {"at": 0.0, "ids": set()}
_MODELS_TTL = 1800
AUTO_ROUTER = "openrouter/free"


def _live_model_ids() -> set[str]:
    if _models_cache["ids"] and time.time() - _models_cache["at"] < _MODELS_TTL:
        return _models_cache["ids"]
    try:
        data = requests.get("https://openrouter.ai/api/v1/models", timeout=8).json()["data"]
        ids = {m["id"] for m in data if isinstance(m, dict) and "id" in m}
        if ids:
            _models_cache.update(at=time.time(), ids=ids)
    except Exception:
        _models_cache["at"] = time.time() - _MODELS_TTL + 60       # could not ask: retry in a minute, use the old list
    return _models_cache["ids"]


def _pick_models(preferred: list[str]) -> list[str]:
    """Configured models that really exist right now (all of them if the list cannot be fetched), then the
    auto-router as the last resort; at most 3 (OpenRouter's limit)."""
    live = _live_model_ids()
    chosen = [m for m in preferred if m and m != AUTO_ROUTER and (not live or m in live)]
    return chosen[:2] + [AUTO_ROUTER]          # always keep the safety net; OpenRouter accepts at most 3


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
    out, total, images = [], 0, 0
    max_images = int(_cfg("MAX_IMAGES", "2"))
    max_image_chars = int(_cfg("MAX_IMAGE_CHARS", "1800000"))        # base64 length per picture (~1.3 MB)
    for m in messages:
        if not isinstance(m, dict) or m.get("role") not in ("system", "user", "assistant"):
            raise HTTPException(400, "Bad request.")
        c = m.get("content")
        if isinstance(c, str):
            total += len(c)
            out.append({"role": m["role"], "content": c})
            continue
        # Pictures of windows: only in a USER message, only inline JPEG/PNG data, bounded in number and size.
        if m["role"] != "user" or not isinstance(c, list) or not c or len(c) > max_images + 1:
            raise HTTPException(400, "Bad request.")
        parts = []
        for part in c:
            kind = part.get("type") if isinstance(part, dict) else None
            if kind == "text" and isinstance(part.get("text"), str):
                total += len(part["text"])
                parts.append({"type": "text", "text": part["text"]})
            elif kind == "image_url" and isinstance(part.get("image_url"), dict):
                url = part["image_url"].get("url")
                if not isinstance(url, str) or not url.startswith(("data:image/jpeg;base64,", "data:image/png;base64,")) \
                        or len(url) > max_image_chars:
                    raise HTTPException(413 if isinstance(url, str) and len(url) > max_image_chars else 400,
                                        "That picture is not allowed or is too big.")
                images += 1
                if images > max_images:
                    raise HTTPException(400, "Too many pictures.")
                parts.append({"type": "image_url", "image_url": {"url": url}})
            else:
                raise HTTPException(400, "Bad request.")
        out.append({"role": "user", "content": parts})
    if total > int(_cfg("MAX_INPUT_CHARS", "40000")):
        raise HTTPException(413, "That is too long. Select less text.")
    return out


def _has_images(messages: list[dict]) -> bool:
    return any(isinstance(m["content"], list) and any(p["type"] == "image_url" for p in m["content"])
               for m in messages)


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
        "you type are sent through our server to an AI provider to produce your answer.</li>"
        "<li><b>\"Ask about my PC\" (optional, only after you allow it):</b> when you ask a question in this mode, "
        "a summary of your computer is sent with it: names of running programs and their memory/CPU use, titles of "
        "open windows (not their contents), disk space, battery, and startup programs. Passwords and keys are "
        "removed first. It is used only to answer that question and is not stored by us.</li>"
        "<li><b>Reading inside a window (optional, asked every time):</b> if your question needs it, Consiz names "
        "the exact window and asks permission first. Only if you allow, the visible text of that window is read on "
        "your computer, passwords and keys are removed, and it is sent with your question to answer it. If the app "
        "does not share its text (for example a web browser), a picture of that one window is sent instead; a "
        "picture cannot have secrets removed, so you are told this in the permission box. Password "
        "managers and private or banking windows are never read. It is not stored by us.</li>"
        "<li><b>One-click suggestions:</b> Consiz may suggest a button (for example &quot;Open Storage settings&quot;). "
        "Nothing happens unless you click it, and it only opens a Windows screen or program.</li></ul>"
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
def health(deep: int = 0):
    """Cheap by default (the app pings it to wake the server). `?deep=1` also checks the database."""
    storage = "postgres" if _use_pg() else "sqlite"
    out = {"ok": True, "storage": storage}
    if deep:
        try:
            _run_db(lambda cur, ph: cur.execute("SELECT 1"))
            out["db_ok"] = True
        except Exception as e:
            out.update(db_ok=False, db_error=type(e).__name__)
    return out


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
    # Defaults from `python scripts/model_check.py` (fastest models that answered every time); re-run it monthly.
    model = _cfg("OPENROUTER_MODEL", "nvidia/nemotron-3-super-120b-a12b:free")
    fallbacks = [m.strip() for m in _cfg("OPENROUTER_FALLBACKS", "inclusionai/ling-3.0-flash-sante:free").split(",")
                 if m.strip()]
    models = _pick_models([model, *fallbacks])
    if _has_images(messages):                       # the server decides from the content, not from a client flag
        vision = _cfg("VISION_MODEL", "google/gemma-4-31b-it:free")
        vfall = [m.strip() for m in _cfg("VISION_FALLBACKS", "google/gemma-4-26b-a4b-it:free,"
                                         "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free").split(",") if m.strip()]
        models = _pick_models([vision, *vfall])
    payload = {
        "model": models[0],
        "models": models,
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
        try:
            detail = upstream.text[:600]
        except Exception:
            detail = ""
        upstream.close()
        if upstream.status_code == 429:
            # The whole product shares ONE OpenRouter key: 50 free-model requests/day (1000 with 10 credits).
            if "free-models-per-day" in detail:
                print("[server] OpenRouter free daily allowance is used up", flush=True)
                raise HTTPException(503, "Today's shared free AI allowance is used up. It resets at 5:30 AM IST "
                                         "(midnight UTC). Please try again then.", headers={"Retry-After": "3600"})
            raise HTTPException(503, "The AI is busy right now. Please try again in a moment.",
                                headers={"Retry-After": "10"})
        raise HTTPException(502 if upstream.status_code >= 500 else upstream.status_code,
                            f"AI provider error ({upstream.status_code}).")

    def relay():
        try:
            for chunk in upstream.iter_content(chunk_size=None):
                yield chunk
        finally:
            upstream.close()

    return StreamingResponse(relay(), media_type="text/event-stream")


# Keep this LAST: a catch-all path would otherwise shadow the fixed routes above.
@app.get("/{filename}", response_class=PlainTextResponse, include_in_schema=False)
def search_console_file(filename: str):
    """Google Search Console 'HTML file' ownership check. Serves ONLY the one file name we configured
    (GOOGLE_VERIFY_FILE), never an arbitrary googleXXXX.html — otherwise anyone could claim this site."""
    expected = _cfg("GOOGLE_VERIFY_FILE", "google4a2c47af0ffeb6d0.html")
    if expected and filename == expected:
        return f"google-site-verification: {expected}"
    raise HTTPException(404, "Not found")
