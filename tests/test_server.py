"""Backend (server/app.py) rules: auth, limits, input validation. The AI provider is faked."""
import pytest

pytest.importorskip("fastapi")
pytest.importorskip("google.auth")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient  # noqa: E402

from server import app as srv  # noqa: E402


class _FakeUpstream:
    status_code = 200

    def iter_content(self, chunk_size=None):
        yield b'data: {"choices":[{"delta":{"content":"hi"}}]}\n\ndata: [DONE]\n\n'

    def close(self):
        pass


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(srv, "SQLITE_PATH", str(tmp_path / "t.db"))
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "cid")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    srv._recent.clear()
    monkeypatch.setattr(srv, "_verify", lambda auth: {"sub": "u1", "email": "a@b.com"} if auth == "Bearer good" else
                        (_ for _ in ()).throw(srv.HTTPException(401, "Sign in required.")))
    sent = {}

    def fake_post(url, json=None, **kw):
        sent["payload"] = json
        return _FakeUpstream()

    monkeypatch.setattr(srv.requests, "post", fake_post)
    c = TestClient(srv.app)
    c.sent = sent
    return c


GOOD = {"Authorization": "Bearer good"}
BODY = {"messages": [{"role": "user", "content": "hello"}]}


def test_health_open(client):
    body = client.get("/health").json()
    assert body["ok"] is True and body["storage"] == "sqlite" and body["db_ok"] is True


def test_public_pages_for_google_consent_screen(client):
    home, priv = client.get("/"), client.get("/privacy")
    assert home.status_code == 200 and "Consiz" in home.text and 'href="/privacy"' in home.text
    assert priv.status_code == 200 and "Privacy Policy" in priv.text and "OpenRouter" in priv.text
    assert "Limited Use" in priv.text


def test_requires_sign_in(client):
    assert client.post("/v1/chat/completions", json=BODY).status_code == 401


def test_answer_streams_and_server_picks_model(client):
    body = dict(BODY, model="evil/expensive", models=["x"], max_tokens=10**6, temperature=99,
                reasoning={"enabled": True, "weird": 1})
    r = client.post("/v1/chat/completions", json=body, headers=GOOD)
    assert r.status_code == 200 and "hi" in r.text
    p = client.sent["payload"]
    assert p["model"] != "evil/expensive" and "x" not in p["models"]
    assert p["max_tokens"] <= 5000 and p["temperature"] <= 1.0
    assert p["reasoning"] == {"enabled": False, "exclude": True}


def test_daily_limit_blocks(client, monkeypatch):
    monkeypatch.setenv("DAILY_LIMIT", "2")
    codes = [client.post("/v1/chat/completions", json=BODY, headers=GOOD).status_code for _ in range(3)]
    assert codes == [200, 200, 429]


def test_failed_provider_refunds_quota(client, monkeypatch):
    monkeypatch.setenv("DAILY_LIMIT", "1")

    class Bad(_FakeUpstream):
        status_code = 500

    monkeypatch.setattr(srv.requests, "post", lambda *a, **k: Bad())
    assert client.post("/v1/chat/completions", json=BODY, headers=GOOD).status_code == 502
    monkeypatch.setattr(srv.requests, "post", lambda *a, **k: _FakeUpstream())
    assert client.post("/v1/chat/completions", json=BODY, headers=GOOD).status_code == 200


def test_per_minute_rate_limit(client, monkeypatch):
    monkeypatch.setenv("RATE_PER_MIN", "2")
    codes = [client.post("/v1/chat/completions", json=BODY, headers=GOOD).status_code for _ in range(3)]
    assert codes == [200, 200, 429]


def test_input_size_and_shape_caps(client, monkeypatch):
    monkeypatch.setenv("MAX_INPUT_CHARS", "50")
    big = {"messages": [{"role": "user", "content": "x" * 51}]}
    assert client.post("/v1/chat/completions", json=big, headers=GOOD).status_code == 413
    bad_role = {"messages": [{"role": "tool", "content": "hi"}]}
    assert client.post("/v1/chat/completions", json=bad_role, headers=GOOD).status_code == 400
    assert client.post("/v1/chat/completions", json={"messages": []}, headers=GOOD).status_code == 400


def test_ip_limit(client, monkeypatch):
    monkeypatch.setenv("IP_DAILY_LIMIT", "1")
    h = dict(GOOD, **{"X-Forwarded-For": "1.2.3.4"})
    assert client.post("/v1/chat/completions", json=BODY, headers=h).status_code == 200
    assert client.post("/v1/chat/completions", json=BODY, headers=h).status_code == 429
