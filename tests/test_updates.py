"""T-08: update check, minimum-version switch on the server, and the app's reaction to HTTP 426."""
import pytest

from consiz import llm, updater


# ---------------------------------------------------------------- version maths
@pytest.mark.parametrize("latest,current,newer", [
    ("0.4.0", "0.3.0", True), ("0.3.1", "0.3.0", True), ("0.3.10", "0.3.9", True), ("1.0.0", "0.99.99", True),
    ("0.3.0", "0.3.0", False), ("0.2.9", "0.3.0", False), ("", "0.3.0", False), ("v0.4.0", "0.3.0", True),
    ("0.3.0.1", "0.3.0", True), ("garbage", "0.3.0", False),
])
def test_is_newer(latest, current, newer):
    assert updater.is_newer(latest, current) is newer


def test_is_below_minimum():
    assert updater.is_below("0.3.0", "0.3.1") and not updater.is_below("0.3.1", "0.3.1")
    assert not updater.is_below("0.1.0", ""), "no minimum set means nobody is blocked"


@pytest.mark.parametrize("url,ok", [("https://example.com/Consiz-Setup.exe", True), ("http://example.com/x.exe", False),
                                    ("javascript:alert(1)", False), ("file:///C:/x.exe", False), ("", False)])
def test_only_https_download_links_are_kept(url, ok):
    assert (updater.safe_url(url) != "") is ok


# ---------------------------------------------------------------- client check
class _Resp:
    def __init__(self, data, status=200):
        self._d, self.status_code = data, status

    def json(self):
        if isinstance(self._d, Exception):
            raise self._d
        return self._d


def test_check_reports_update_and_required(monkeypatch):
    data = {"latest": "0.4.0", "minimum": "0.3.5", "url": "https://dl.example/Consiz.exe", "notes": "faster"}
    monkeypatch.setattr(updater.requests, "get", lambda url, timeout=0: _Resp(data))
    info = updater.check("http://srv", current="0.3.0")
    assert info["update_available"] and info["required"] and info["url"] == "https://dl.example/Consiz.exe"
    assert updater.last() == info
    info = updater.check("http://srv", current="0.4.0")
    assert not info["update_available"] and not info["required"]


def test_check_never_fails_loudly(monkeypatch):
    def boom(*a, **k):
        raise updater.requests.ConnectionError("offline")
    monkeypatch.setattr(updater.requests, "get", boom)
    assert updater.check("http://srv", current="0.3.0") is None
    monkeypatch.setattr(updater.requests, "get", lambda *a, **k: _Resp({}, status=500))
    assert updater.check("http://srv", current="0.3.0") is None
    monkeypatch.setattr(updater.requests, "get", lambda *a, **k: _Resp(ValueError("not json")))
    assert updater.check("http://srv", current="0.3.0") is None
    monkeypatch.setattr(updater.requests, "get", lambda *a, **k: _Resp(["a list"]))
    assert updater.check("http://srv", current="0.3.0") is None
    monkeypatch.delenv("CONSIZ_SERVER_URL", raising=False)
    assert updater.check("", current="0.3.0") is None              # no server configured -> nothing to ask


def test_a_non_https_link_from_the_server_is_dropped(monkeypatch):
    monkeypatch.setattr(updater.requests, "get", lambda *a, **k: _Resp({"latest": "9.9.9", "url": "http://evil/x.exe"}))
    assert updater.check("http://srv", current="0.3.0")["url"] == ""


# ---------------------------------------------------------------- server side
pytest.importorskip("fastapi")
pytest.importorskip("google.auth")
pytest.importorskip("httpx")
from fastapi.testclient import TestClient  # noqa: E402

from server import app as srv  # noqa: E402
from tests.test_server import BODY, GOOD, _FakeUpstream  # noqa: E402


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(srv, "SQLITE_PATH", str(tmp_path / "t.db"))
    for name in ("OPENROUTER_MODEL", "OPENROUTER_FALLBACKS", "MIN_VERSION", "LATEST_VERSION", "DOWNLOAD_URL", "RELEASE_NOTES"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "cid")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    srv._recent.clear()
    srv._mem_counts.clear()
    monkeypatch.setattr(srv, "_verify", lambda auth: {"sub": "u1", "email": "a@b.com"} if auth == "Bearer good" else
                        (_ for _ in ()).throw(srv.HTTPException(401, "Sign in required.")))
    monkeypatch.setattr(srv.requests, "post", lambda *a, **k: _FakeUpstream())
    monkeypatch.setattr(srv, "_live_model_ids", lambda: set())
    return TestClient(srv.app)


def test_version_endpoint_reports_the_servers_settings(client, monkeypatch):
    assert client.get("/version").json() == {"latest": "", "minimum": "", "url": "", "notes": ""}
    monkeypatch.setenv("LATEST_VERSION", "0.4.0")
    monkeypatch.setenv("MIN_VERSION", "0.3.0")
    monkeypatch.setenv("DOWNLOAD_URL", "https://dl.example/Consiz-Setup-0.4.0.exe")
    monkeypatch.setenv("RELEASE_NOTES", "Stop button, Pause, sharper text")
    assert client.get("/version").json() == {"latest": "0.4.0", "minimum": "0.3.0",
                                             "url": "https://dl.example/Consiz-Setup-0.4.0.exe",
                                             "notes": "Stop button, Pause, sharper text"}


def test_nothing_is_blocked_unless_a_minimum_is_set(client):
    assert client.post("/v1/chat/completions", json=BODY, headers=GOOD).status_code == 200            # no header, no minimum
    assert client.post("/v1/chat/completions", json=BODY, headers={**GOOD, "X-Consiz-Version": "0.0.1"}).status_code == 200


def test_old_apps_are_refused_with_426_when_a_minimum_is_set(client, monkeypatch):
    monkeypatch.setenv("MIN_VERSION", "0.3.0")
    monkeypatch.setenv("DOWNLOAD_URL", "https://dl.example/Consiz.exe")
    old = client.post("/v1/chat/completions", json=BODY, headers={**GOOD, "X-Consiz-Version": "0.2.9"})
    assert old.status_code == 426 and "no longer supported" in old.json()["detail"] and "https://dl.example/Consiz.exe" in old.json()["detail"]
    assert client.post("/v1/chat/completions", json=BODY, headers=GOOD).status_code == 426, "no version header = oldest"
    ok = client.post("/v1/chat/completions", json=BODY, headers={**GOOD, "X-Consiz-Version": "0.3.0"})
    assert ok.status_code == 200


def test_a_refused_old_app_is_not_charged_a_quota_answer(client, monkeypatch):
    monkeypatch.setenv("MIN_VERSION", "0.3.0")
    monkeypatch.setenv("DAILY_LIMIT", "1")
    for _ in range(3):
        assert client.post("/v1/chat/completions", json=BODY, headers={**GOOD, "X-Consiz-Version": "0.1.0"}).status_code == 426
    assert client.post("/v1/chat/completions", json=BODY, headers={**GOOD, "X-Consiz-Version": "0.3.0"}).status_code == 200


def test_unsigned_requests_still_get_401_not_426(client, monkeypatch):
    monkeypatch.setenv("MIN_VERSION", "9.0.0")
    assert client.post("/v1/chat/completions", json=BODY).status_code == 401


def test_a_non_https_download_url_is_not_put_in_the_error_text(client, monkeypatch):
    monkeypatch.setenv("MIN_VERSION", "9.0.0")
    monkeypatch.setenv("DOWNLOAD_URL", "http://insecure/x.exe")
    detail = client.post("/v1/chat/completions", json=BODY, headers=GOOD).json()["detail"]
    assert "insecure" not in detail


# ---------------------------------------------------------------- app side: header sent, 426 understood
class _Stream:
    def __init__(self, status, lines=(), detail=None):
        self.status_code, self._lines, self._detail = status, list(lines), detail

    def __enter__(self):
        return self

    def __exit__(self, *a):
        pass

    def iter_lines(self):
        return iter(self._lines)

    def json(self):
        return {"detail": self._detail}


def _sse():
    return list(llm._openrouter_sse([{"role": "user", "content": "hi"}], llm._REASONING_OFF, 100))


def test_app_sends_its_version_and_understands_426(monkeypatch):
    monkeypatch.setattr(llm, "_server_url", lambda: "http://srv")
    monkeypatch.setattr(llm, "_api_key", lambda: "tok")
    seen = {}

    def post(url, headers=None, **kw):
        seen["headers"] = headers
        return _Stream(426, detail="This version of Consiz is no longer supported. Please install the latest version.")

    monkeypatch.setattr(llm._SESSION, "post", post)
    with pytest.raises(llm.UpdateRequired) as e:
        _sse()
    from consiz import __version__
    assert seen["headers"]["X-Consiz-Version"] == __version__
    assert "no longer supported" in str(e.value)
    assert not isinstance(e.value, llm.LLMUnavailable), "an old app must never fall back to offline answers"


def test_426_is_friendly_in_the_popup():
    from consiz.platform.win32.popup import _friendly_error
    assert "update" in _friendly_error("This version of Consiz is no longer supported. Please install...").lower()
