"""Sign-in (shared logic, no UI): Google OAuth straight to Google (PKCE + local loopback), no middle service.

Auth is OPTIONAL: without GOOGLE_CLIENT_ID in .env, `enabled()` is False and the app runs exactly as
before. Use a Google Cloud "Desktop app" OAuth client. Its secret is not truly secret for desktop apps
(Google says so) but Google's token endpoint still asks for it, so it lives in .env too.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Optional

import requests

from . import prefs

SESSION_FILE = prefs.STORE.parent / "session.json"
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"
TIMEOUT_S = 20
GOOGLE_WAIT_S = 180


_attempt = {"n": 0}


def log(msg: str) -> None:
    """Auth events go to the shared application log (no tokens, no emails — callers only pass event names)."""
    from . import logs
    logs.get().info(msg)


def cancel_pending() -> None:
    """Stop any sign-in attempt still waiting for the browser (e.g. the user closed the window)."""
    _attempt["n"] += 1


class AuthError(Exception):
    """Friendly, user-showable auth failure. `rejected` = Google itself said no (vs. a network problem)."""
    rejected = False


def _client_id() -> str:
    return os.environ.get("GOOGLE_CLIENT_ID", "").strip()


def _client_secret() -> str:
    return os.environ.get("GOOGLE_CLIENT_SECRET", "").strip()


def enabled() -> bool:
    return bool(_client_id())


# ------------------------------------------------------------------ session store
# The refresh token (long-lived, powerful) lives in the Windows Credential Manager via `keyring`; the
# session file only holds the profile. If keyring is unavailable we fall back to the file.
KEYRING_SERVICE = "Consiz"
KEYRING_USER = "google_refresh_token"


def _kr_get() -> str:
    try:
        import keyring
        return keyring.get_password(KEYRING_SERVICE, KEYRING_USER) or ""
    except Exception:
        return ""


def _kr_set(token: str) -> bool:
    try:
        import keyring
        keyring.set_password(KEYRING_SERVICE, KEYRING_USER, token)
        return True
    except Exception:
        return False


def _kr_delete() -> None:
    try:
        import keyring
        keyring.delete_password(KEYRING_SERVICE, KEYRING_USER)
    except Exception:
        pass


def _write_file(data: dict) -> None:
    try:
        SESSION_FILE.parent.mkdir(parents=True, exist_ok=True)
        SESSION_FILE.write_text(json.dumps(data))
    except OSError:
        pass


def _save(user: dict, refresh_token: str) -> dict:
    data = {"user": user}
    if _kr_set(refresh_token):
        data["token_in_keyring"] = True
    else:
        data["refresh_token"] = refresh_token           # fallback only
    _write_file(data)
    return data


def _load() -> dict:
    try:
        return json.loads(SESSION_FILE.read_text())
    except (OSError, ValueError):
        return {}


def _refresh_token() -> str:
    s = _load()
    if s.get("token_in_keyring"):
        return _kr_get()
    tok = s.get("refresh_token", "")
    if tok and _kr_set(tok):                            # migrate an old plain-text session
        _write_file({"user": s.get("user", {}), "token_in_keyring": True})
    return tok


def sign_out() -> None:
    _ID["token"], _ID["exp"] = "", 0.0
    _kr_delete()
    try:
        SESSION_FILE.unlink()
    except OSError:
        pass


def current_user() -> Optional[dict]:
    """The signed-in user ({email, name, picture}) or None. Local read — no network on every click."""
    s = _load()
    if s.get("user") and _refresh_token():
        return s["user"]
    return None


def signed_in() -> bool:
    return current_user() is not None


def display_name() -> str:
    u = current_user() or {}
    return u.get("name") or u.get("email") or "you"


def revalidate() -> bool:
    """Ask Google whether the saved sign-in is still valid (access revoked, or a Testing-mode token
    expired). Signs out if Google rejects it; being offline keeps the user signed in.
    Returns True if still signed in. Blocking — call from a worker thread."""
    tok = _refresh_token()
    if not (enabled() and tok):
        return signed_in()
    try:
        res = _token_request({"grant_type": "refresh_token", "refresh_token": tok})
        _remember_id(res)                    # keep the fresh ID token: the first question then needs no extra round trip
    except AuthError as e:
        if e.rejected:
            sign_out()
            return False
    return signed_in()


_ID = {"token": "", "exp": 0.0}


def _remember_id(res: dict) -> None:
    if res.get("id_token"):
        _ID["token"] = res["id_token"]
        _ID["exp"] = time.time() + int(res.get("expires_in", 3600))


def id_token() -> str:
    """A fresh Google ID token for the backend (cached ~50 min). Raises AuthError if not signed in."""
    if _ID["token"] and _ID["exp"] - 300 > time.time():       # refresh early (5 min) so a question never waits for it
        return _ID["token"]
    tok = _refresh_token()
    if not tok:
        raise AuthError("Please sign in first.")
    try:
        res = _token_request({"grant_type": "refresh_token", "refresh_token": tok})
    except AuthError as e:
        if e.rejected:
            sign_out()
            raise AuthError("Your sign-in expired. Please sign in again.")
        raise
    _remember_id(res)
    if not _ID["token"]:
        raise AuthError("Google didn't return an identity token. Sign in again.")
    return _ID["token"]


# ------------------------------------------------------------------ Google (PKCE via browser)
def _token_request(data: dict) -> dict:
    data = {**data, "client_id": _client_id()}
    if _client_secret():
        data["client_secret"] = _client_secret()
    try:
        r = requests.post(TOKEN_URL, data=data, timeout=TIMEOUT_S)
    except requests.RequestException:
        raise AuthError("Can't reach Google. Check your internet.")
    if r.status_code >= 400:
        try:
            msg = r.json().get("error_description") or r.json().get("error")
        except ValueError:
            msg = None
        err = AuthError(msg or f"Google sign-in failed ({r.status_code}).")
        err.rejected = 400 <= r.status_code < 500
        raise err
    return r.json()


def sign_in_google(open_browser=None) -> dict:
    """Opens the browser, waits for Google to redirect back to a one-shot local port."""
    import webbrowser
    if not enabled():
        raise AuthError("Google sign-in isn't set up (GOOGLE_CLIENT_ID missing in .env).")
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    state = secrets.token_urlsafe(16)
    got: dict = {}

    class _Handler(BaseHTTPRequestHandler):
        def do_GET(self):                                  # noqa: N802
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            if "code" not in q and "error" not in q:       # e.g. favicon request — ignore
                self.send_response(404)
                self.end_headers()
                return
            got["code"] = (q.get("code") or [""])[0]
            got["error"] = (q.get("error") or [""])[0]
            got["state"] = (q.get("state") or [""])[0]
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"<html><body style='font-family:Segoe UI;text-align:center;margin-top:20vh;"
                             b"background:#F8F1E3;color:#43151B'><h2>Signed in to Consiz</h2>"
                             b"<p>You can close this tab.</p></body></html>")

        def log_message(self, *a):
            pass

    server = HTTPServer(("127.0.0.1", 0), _Handler)
    server.timeout = 1
    redirect = f"http://127.0.0.1:{server.server_port}"
    url = AUTH_URL + "?" + urllib.parse.urlencode({
        "client_id": _client_id(), "redirect_uri": redirect, "response_type": "code",
        "scope": "openid email profile", "state": state,
        "code_challenge": challenge, "code_challenge_method": "S256",
        "access_type": "offline", "prompt": "select_account consent",
    })
    _attempt["n"] += 1
    mine = _attempt["n"]
    opened = (open_browser or webbrowser.open)(url)
    log(f"google sign-in: browser open returned {opened!r}, listening on port {server.server_port}")
    if not opened:
        # No default browser handler: let the user finish by hand instead of failing silently.
        try:
            import subprocess
            subprocess.run(["clip"], input=url.encode("utf-16le"), check=False, timeout=5)
        except Exception:
            pass
        server.server_close()
        raise AuthError("Couldn't open your browser. The sign-in link was copied: paste it into a browser.")
    deadline = time.time() + GOOGLE_WAIT_S
    try:
        while not got and time.time() < deadline and _attempt["n"] == mine:
            server.handle_request()
    finally:
        server.server_close()
    if _attempt["n"] != mine and not got:
        raise AuthError("Sign-in was cancelled.")
    if got.get("error"):
        raise AuthError("Google sign-in was cancelled." if got["error"] == "access_denied" else got["error"])
    if not got.get("code"):
        raise AuthError("Google sign-in timed out. Try again.")
    if got.get("state") != state:
        raise AuthError("Sign-in check failed. Try again.")

    tok = _token_request({"grant_type": "authorization_code", "code": got["code"],
                          "code_verifier": verifier, "redirect_uri": redirect})
    try:
        info = requests.get(USERINFO_URL, headers={"Authorization": f"Bearer {tok['access_token']}"},
                            timeout=TIMEOUT_S).json()
    except (requests.RequestException, ValueError, KeyError):
        raise AuthError("Signed in, but couldn't read your Google profile. Try again.")
    if not info.get("email"):
        raise AuthError("Google didn't share an email. Try again.")
    if not tok.get("refresh_token"):
        raise AuthError("Google didn't keep you signed in. Try again.")
    return _save(
        {"email": info["email"], "name": info.get("name", ""), "picture": info.get("picture", "")},
        tok["refresh_token"],
    )


def run_async(fn, on_ok, on_err) -> None:
    """Run a blocking auth call off the UI thread; callbacks fire on that worker thread."""
    def _w():
        try:
            on_ok(fn())
        except AuthError as e:
            on_err(str(e))
        except Exception as e:                              # never crash the app over sign-in
            on_err(f"Something went wrong: {e}")
    threading.Thread(target=_w, daemon=True).start()
