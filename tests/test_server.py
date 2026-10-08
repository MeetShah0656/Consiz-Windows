"""Backend (server/app.py) rules: auth, limits, input validation. The AI provider is faked."""
import pytest

pytest.importorskip("fastapi")
pytest.importorskip("google.auth")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient  # noqa: E402

from server import app as srv  # noqa: E402


class _FakeUpstream:
    """The AI provider's streaming response, as the (async) server sees it. Subclasses override status_code / text /
    iter_content to play other situations."""
    status_code = 200
    text = ""
    closed = False

    def iter_content(self, chunk_size=None):
        yield b'data: {"choices":[{"delta":{"content":"hi"}}]}\n\ndata: [DONE]\n\n'

    async def aiter_bytes(self):
        for chunk in self.iter_content():
            yield chunk

    async def aread(self):
        return self.text.encode()

    async def aclose(self):
        self.closed = True


def _opener(upstream, sent=None):
    """What the server calls to start the AI request; hands back `upstream` and remembers the payload."""
    async def open_upstream(payload, key):
        if sent is not None:
            sent["payload"], sent["key"] = payload, key
        return upstream
    return open_upstream


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(srv, "SQLITE_PATH", str(tmp_path / "t.db"))
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "cid")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    for name in ("OPENROUTER_MODEL", "OPENROUTER_FALLBACKS", "VISION_MODEL", "VISION_FALLBACKS"):
        monkeypatch.delenv(name, raising=False)                          # a developer's own .env must not change tests
    srv._recent.clear()
    monkeypatch.setattr(srv, "_verify", lambda auth: {"sub": "u1", "email": "a@b.com"} if auth == "Bearer good" else
                        (_ for _ in ()).throw(srv.HTTPException(401, "Sign in required.")))
    sent = {}

    monkeypatch.setattr(srv, "_open_upstream", _opener(_FakeUpstream(), sent))
    monkeypatch.setattr(srv, "_live_model_ids", lambda: set())          # tests never call the real model list
    srv._mem_counts.clear()
    c = TestClient(srv.app)
    c.sent = sent
    return c


GOOD = {"Authorization": "Bearer good"}
BODY = {"messages": [{"role": "user", "content": "hello"}]}


def test_health_open(client):
    cheap = client.get("/health").json()
    assert cheap == {"ok": True, "storage": "sqlite"}                    # no database call: it is the wake-up ping
    deep = client.get("/health?deep=1").json()
    assert deep["ok"] is True and deep["db_ok"] is True


def test_public_pages_for_google_consent_screen(client):
    home, priv = client.get("/"), client.get("/privacy")
    assert home.status_code == 200 and "Consiz" in home.text and 'href="/privacy"' in home.text
    assert priv.status_code == 200 and "Privacy Policy" in priv.text and "OpenRouter" in priv.text
    assert "Limited Use" in priv.text


def test_search_console_file_only_the_configured_name(client):
    ok = client.get("/google4a2c47af0ffeb6d0.html")
    assert ok.status_code == 200 and ok.text == "google-site-verification: google4a2c47af0ffeb6d0.html"
    assert client.get("/google0000000000000000.html").status_code == 404
    assert client.get("/random.html").status_code == 404


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

    monkeypatch.setattr(srv, "_open_upstream", _opener(Bad()))
    assert client.post("/v1/chat/completions", json=BODY, headers=GOOD).status_code == 502
    monkeypatch.setattr(srv, "_open_upstream", _opener(_FakeUpstream()))
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


# ------------------------------------------------------------------ pictures of windows (vision requests)
PIC = "data:image/jpeg;base64,QUJD"


def _pic_body(url=PIC, role="user", n=1):
    parts = [{"type": "text", "text": "what does it say?"}] + [{"type": "image_url", "image_url": {"url": url}}] * n
    return {"messages": [{"role": role, "content": parts}]}


def test_picture_request_uses_the_vision_model(client):
    r = client.post("/v1/chat/completions", json=_pic_body(), headers=GOOD)
    assert r.status_code == 200
    p = client.sent["payload"]
    assert "gemma" in p["model"] and p["models"][0] == p["model"]
    assert isinstance(p["messages"][0]["content"], list)


def test_text_request_still_uses_the_text_model(client):
    client.post("/v1/chat/completions", json=BODY, headers=GOOD)
    assert "gemma" not in client.sent["payload"]["model"]


@pytest.mark.parametrize("body,code", [
    (_pic_body(url="https://evil.example/x.jpg"), 400),            # only inline data, never a remote URL
    (_pic_body(url="data:text/html;base64,QUJD"), 400),
    (_pic_body(role="assistant"), 400),                            # pictures only from the user
    (_pic_body(role="system"), 400),
    (_pic_body(n=3), 400),                                         # at most 2 pictures
    (_pic_body(url="data:image/jpeg;base64," + "A" * 2_000_000), 413),
])
def test_picture_rules(client, body, code):
    assert client.post("/v1/chat/completions", json=body, headers=GOOD).status_code == code


# ------------------------------------------------------------------ speed + resilience (measured problems)
def test_counting_both_limits_is_one_database_statement(client, monkeypatch):
    seen = []
    real_connect = srv.sqlite3.connect

    def connect(path, *a, **k):
        con = real_connect(path, *a, **k)
        con.set_trace_callback(lambda sql: seen.append(sql.split()[0].upper()))
        return con

    monkeypatch.setattr(srv.sqlite3, "connect", connect)
    srv._take_quota({"sub": "u9", "email": "u9@x.com"}, "9.9.9.9")
    data_statements = [x for x in seen if x in ("INSERT", "SELECT", "UPDATE")]
    assert data_statements == ["INSERT"]                                 # was SELECT+INSERT for each of 2 keys


def test_refused_request_is_not_charged(client, monkeypatch):
    monkeypatch.setenv("DAILY_LIMIT", "1")
    info = {"sub": "u8", "email": "u8@x.com"}
    srv._take_quota(info, "")
    for _ in range(3):
        with pytest.raises(srv.HTTPException):
            srv._take_quota(info, "")
    got = srv._run_db(lambda cur, ph: cur.execute(f"SELECT n FROM usage WHERE sub={ph}", ("u8",)).fetchone())
    assert got[0] == 1                                                   # the refusals did not inflate the count


def test_database_down_keeps_the_service_up_with_memory_limits(client, monkeypatch):
    def down(work):
        raise RuntimeError("database unreachable")

    monkeypatch.setattr(srv, "_run_db", down)
    monkeypatch.setenv("DAILY_LIMIT", "2")
    codes = [client.post("/v1/chat/completions", json=BODY, headers=GOOD).status_code for _ in range(3)]
    assert codes == [200, 200, 429]                                      # still answering, still limiting


def test_stale_pooled_connection_is_retried_once(client):
    class OperationalError(Exception):
        pass
    OperationalError.__module__ = "psycopg2.errors"
    calls = []

    def work(cur, ph):
        calls.append(1)
        if len(calls) == 1:
            raise OperationalError("server closed the connection")
        return "ok"

    assert srv._run_db(work) == "ok" and len(calls) == 2
    with pytest.raises(ValueError):                                      # other errors are not retried
        srv._run_db(lambda cur, ph: (_ for _ in ()).throw(ValueError("bug")))


def test_dead_models_are_dropped_and_the_auto_router_is_the_safety_net(monkeypatch):
    monkeypatch.setattr(srv, "_live_model_ids", lambda: {"good/one:free", "good/two:free", srv.AUTO_ROUTER})
    assert srv._pick_models(["dead/old:free", "good/one:free", "good/two:free"]) == [
        "good/one:free", "good/two:free", srv.AUTO_ROUTER]
    assert srv._pick_models(["dead/a:free", "dead/b:free"]) == [srv.AUTO_ROUTER]
    monkeypatch.setattr(srv, "_live_model_ids", lambda: set())           # list unavailable: trust the configuration
    assert srv._pick_models(["a:free", "b:free", "c:free"]) == ["a:free", "b:free", srv.AUTO_ROUTER]


def test_default_models_are_not_the_removed_one(client):
    client.post("/v1/chat/completions", json=BODY, headers=GOOD)
    models = client.sent["payload"]["models"]
    assert "ling-3.0-flash-fin" not in " ".join(models) and models[-1] == srv.AUTO_ROUTER and len(models) <= 3


def test_shared_free_allowance_used_up_gets_a_clear_message(client, monkeypatch):
    class Limited(_FakeUpstream):
        status_code = 429
        text = '{"error":{"message":"Rate limit exceeded: free-models-per-day. Add 10 credits to unlock 1000"}}'

    monkeypatch.setattr(srv, "_open_upstream", _opener(Limited()))
    r = client.post("/v1/chat/completions", json=BODY, headers=GOOD)
    assert r.status_code == 503 and "5:30 AM IST" in r.json()["detail"] and r.headers["retry-after"] == "3600"
    monkeypatch.setenv("DAILY_LIMIT", "1")                                # and the user is not charged for it
    assert client.post("/v1/chat/completions", json=BODY, headers=GOOD).status_code == 503


def test_ordinary_provider_rate_limit_says_busy_not_used_up(client, monkeypatch):
    class Busy(_FakeUpstream):
        status_code = 429
        text = '{"error":{"message":"Provider returned error"}}'

    monkeypatch.setattr(srv, "_open_upstream", _opener(Busy()))
    r = client.post("/v1/chat/completions", json=BODY, headers=GOOD)
    assert r.status_code == 503 and "busy" in r.json()["detail"].lower() and "allowance" not in r.json()["detail"]


def test_default_models_are_the_measured_fast_ones(client):
    client.post("/v1/chat/completions", json=BODY, headers=GOOD)
    models = client.sent["payload"]["models"]
    assert models[0] == "nvidia/nemotron-3-super-120b-a12b:free" and models[1].endswith("ling-3.0-flash-sante:free")
    assert models[-1] == srv.AUTO_ROUTER


# ---------------------------------------------------------------- real cost per answer (spend table)
def _spend_rows():
    import sqlite3
    con = sqlite3.connect(srv.SQLITE_PATH)
    try:
        return con.execute("SELECT sub, model, calls, tokens_in, tokens_out, cost_usd, unmetered FROM spend").fetchall()
    finally:
        con.close()


def test_answer_cost_is_recorded_from_the_last_stream_chunk(client, monkeypatch):
    class WithUsage(_FakeUpstream):
        def iter_content(self, chunk_size=None):
            yield b'data: {"choices":[{"delta":{"content":"hi"}}],"usage":null}\n\n'
            # the counts arrive split across two network chunks: they must still be read
            yield b'data: {"model":"vendor/real-model","choices":[],"usage":{"prompt_tokens":1200,'
            yield b'"completion_tokens":150,"cost":0.00042}}\n\ndata: [DONE]\n\n'

    monkeypatch.setattr(srv, "_open_upstream", _opener(WithUsage()))
    r = client.post("/v1/chat/completions", json=BODY, headers=GOOD)
    assert r.status_code == 200 and "hi" in r.text and "real-model" in r.text       # the app still gets every byte
    assert _spend_rows() == [("u1", "vendor/real-model", 1, 1200, 150, 0.00042, 0)]
    client.post("/v1/chat/completions", json=BODY, headers=GOOD)
    assert _spend_rows()[0][2:5] == (2, 2400, 300)                                  # same row, added up


def test_answer_without_counts_is_marked_unmetered(client):
    assert client.post("/v1/chat/completions", json=BODY, headers=GOOD).status_code == 200
    (_sub, _model, calls, tin, tout, cost, unmetered), = _spend_rows()
    assert (calls, tin, tout, cost, unmetered) == (1, 0, 0, 0.0, 1)


def test_server_adds_no_deprecated_usage_flag(client):
    client.post("/v1/chat/completions", json=BODY, headers=GOOD)
    assert "usage" not in client.sent["payload"] and "stream_options" not in client.sent["payload"]


def test_spend_table_failure_never_breaks_an_answer(client, monkeypatch):
    real = srv._run_db

    def broken_for_spend(work):
        if getattr(work, "__name__", "") == "work":                                   # only the spend writer
            raise RuntimeError("disk full")
        return real(work)

    monkeypatch.setattr(srv, "_run_db", broken_for_spend)
    r = client.post("/v1/chat/completions", json=BODY, headers=GOOD)
    assert r.status_code == 200 and "hi" in r.text
