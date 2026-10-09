"""Server concurrency: answers must not tie up worker threads, Google's keys are cached, the database pool cannot be
exhausted, and memory does not grow with every user ever seen. (`python scripts/load_test.py` shows the same with real
processes and numbers.)"""
import asyncio
import threading
import time

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("google.auth")
pytest.importorskip("httpx")
import httpx  # noqa: E402

from server import app as srv  # noqa: E402


# ---------------------------------------------------------------- Google's signing keys are cached
class _Resp:
    def __init__(self, status=200, cache_control="public, max-age=3600"):
        self.status, self.headers, self.data = status, {"cache-control": cache_control}, b'{"k1":"pem"}'


class _Transport:
    def __init__(self, resp=None, fail=False):
        self.calls, self.resp, self.fail = 0, resp or _Resp(), fail

    def __call__(self, url, method="GET", body=None, headers=None, timeout=None, **kw):
        self.calls += 1
        if self.fail:
            raise ConnectionError("Google unreachable")
        return self.resp


def test_keys_are_downloaded_once_not_for_every_sign_in_check():
    t = _Transport()
    keys = srv._CachedKeys(t)
    first = keys("https://certs.example/keys")
    for _ in range(50):
        assert keys("https://certs.example/keys") is first
    assert t.calls == 1


def test_keys_expire_after_the_time_google_allows(monkeypatch):
    t = _Transport(_Resp(cache_control="public, max-age=120"))
    keys = srv._CachedKeys(t)
    now = [1000.0]
    monkeypatch.setattr(srv.time, "time", lambda: now[0])
    keys("u")
    now[0] += 100
    keys("u")
    assert t.calls == 1
    now[0] += 30                                              # 130 s: past max-age=120
    keys("u")
    assert t.calls == 2


def test_cache_time_is_bounded_whatever_google_says(monkeypatch):
    now = [0.0]
    monkeypatch.setattr(srv.time, "time", lambda: now[0])
    for cc, expect_calls in [("max-age=1", 2), ("max-age=99999999", 2), ("garbage", 1)]:
        t = _Transport(_Resp(cache_control=cc))
        keys = srv._CachedKeys(t)
        now[0] = 0.0
        keys("u")
        now[0] = 61.0                                         # a tiny max-age is raised to 60 s...
        keys("u")
        if cc == "max-age=99999999":
            now[0] = 6 * 3600 + 5                              # ...and a huge one is cut to 6 h
            keys("u")
        assert t.calls == expect_calls, cc


def test_old_keys_are_used_when_google_cannot_be_reached(monkeypatch):
    t = _Transport()
    keys = srv._CachedKeys(t)
    now = [0.0]
    monkeypatch.setattr(srv.time, "time", lambda: now[0])
    good = keys("u")
    t.fail = True
    now[0] = 99999.0                                          # expired, and Google is down
    assert keys("u") is good, "a Google outage must not sign everyone out"
    fresh = srv._CachedKeys(_Transport(fail=True))
    with pytest.raises(ConnectionError):
        fresh("u")                                            # nothing cached yet: the error is real


def test_failed_downloads_are_not_cached():
    t = _Transport(_Resp(status=500))
    keys = srv._CachedKeys(t)
    keys("u")
    keys("u")
    assert t.calls == 2


def test_only_gets_are_cached():
    t = _Transport()
    keys = srv._CachedKeys(t)
    keys("u", method="POST", body=b"x")
    keys("u", method="POST", body=b"x")
    assert t.calls == 2


def test_many_threads_at_once_cause_one_download():
    t = _Transport()
    slow = t.__call__

    def slow_call(*a, **k):
        time.sleep(0.05)
        return slow(*a, **k)
    keys = srv._CachedKeys(slow_call)
    threads = [threading.Thread(target=keys, args=("u",)) for _ in range(30)]
    [th.start() for th in threads]
    [th.join() for th in threads]
    assert t.calls == 1, "no stampede right after a restart"


# ---------------------------------------------------------------- streams do not hold worker threads
class _SlowUpstream:
    """An AI that takes a while to answer; counts how many answers are in flight at the same moment."""
    status_code = 200
    in_flight = 0
    peak = 0

    async def aiter_bytes(self):
        _SlowUpstream.in_flight += 1
        _SlowUpstream.peak = max(_SlowUpstream.peak, _SlowUpstream.in_flight)
        try:
            await asyncio.sleep(0.4)
            yield b'data: {"choices":[{"delta":{"content":"hi"}}]}\n\n'
            yield b"data: [DONE]\n\n"
        finally:
            _SlowUpstream.in_flight -= 1

    async def aread(self):
        return b""

    async def aclose(self):
        pass


def test_a_hundred_slow_answers_run_at_once_even_with_only_four_worker_threads(tmp_path, monkeypatch):
    monkeypatch.setattr(srv, "SQLITE_PATH", ":memory:")      # no disk: a slow shared CI disk made the 400 short database jobs take 39 s
    for name, value in (("OPENROUTER_API_KEY", "k"), ("GOOGLE_CLIENT_ID", "cid"), ("DAILY_LIMIT", "1000"),
                        ("IP_DAILY_LIMIT", "100000"), ("RATE_PER_MIN", "1000")):
        monkeypatch.setenv(name, value)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("MIN_VERSION", raising=False)
    monkeypatch.setattr(srv, "_verify", lambda auth: {"sub": auth[-4:] + "u", "email": "a@b.com"})
    monkeypatch.setattr(srv, "_live_model_ids", lambda: set())

    async def opener(payload, key):
        return _SlowUpstream()
    monkeypatch.setattr(srv, "_open_upstream", opener)
    srv._recent.clear()
    srv._mem_counts.clear()
    _SlowUpstream.in_flight = _SlowUpstream.peak = 0

    async def run(n):
        import anyio.to_thread
        anyio.to_thread.current_default_thread_limiter().total_tokens = 4     # the old design could do 4 at a time
        transport = httpx.ASGITransport(app=srv.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
            t0 = time.perf_counter()
            rs = await asyncio.gather(*(c.post("/v1/chat/completions", json={"messages": [{"role": "user", "content": "x"}]},
                                               headers={"Authorization": f"Bearer {i:04d}"}) for i in range(n)))
            return rs, time.perf_counter() - t0

    rs, took = asyncio.run(run(100))
    assert all(r.status_code == 200 and "hi" in r.text for r in rs)
    assert _SlowUpstream.peak >= 90, f"only {_SlowUpstream.peak} answers ran at the same time"
    # one thread per answer would need 100 x 0.4 s / 4 threads = 10 s; what is left is 400 short database/sign-in jobs
    assert took < 15.0, f"100 answers of 0.4 s took {took:.1f} s: they are being served in waves (one at a time would be 40 s)"


# ---------------------------------------------------------------- database connections: wait, never fail
def test_more_callers_than_database_connections_wait_instead_of_failing(monkeypatch):
    state = {"now": 0, "peak": 0, "lock": threading.Lock()}

    class Cur:
        def execute(self, *a, **k):
            time.sleep(0.01)

        def fetchall(self):
            return []

    class Con:
        closed = 0

        def cursor(self):
            return Cur()

        def commit(self):
            pass

        def rollback(self):
            pass

    class Pool:                                               # like psycopg2's: refuses (raises) when it is empty
        def getconn(self):
            with state["lock"]:
                if state["now"] >= srv._DB_CONNECTIONS:
                    raise RuntimeError("connection pool exhausted")
                state["now"] += 1
                state["peak"] = max(state["peak"], state["now"])
            return Con()

        def putconn(self, con, close=False):
            with state["lock"]:
                state["now"] -= 1

    monkeypatch.setattr(srv, "_use_pg", lambda: True)
    monkeypatch.setattr(srv, "_pg_pool", lambda: Pool())
    srv._schema_ready["done"] = True
    errors = []

    def job():
        try:
            srv._run_db(lambda cur, ph: cur.execute("SELECT 1"))
        except Exception as e:                                # noqa: BLE001
            errors.append(e)

    threads = [threading.Thread(target=job) for _ in range(60)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert not errors, errors[:1]
    assert state["peak"] <= srv._DB_CONNECTIONS and state["now"] == 0


# ---------------------------------------------------------------- memory does not grow forever
def test_idle_users_are_forgotten(monkeypatch):
    srv._recent.clear()
    srv._mem_counts.clear()
    now = time.time()
    for i in range(2500):
        srv._recent[f"old{i}"].append(now - 500)              # seen long ago
    srv._recent["busy"].append(now)
    srv._mem_counts[("u", "2020-01-01")] = 3                  # a previous day's fallback counter
    srv._mem_counts[("u", srv._today())] = 1
    monkeypatch.setenv("RATE_PER_MIN", "12")
    srv._rate_limit("someone")                                # more than 2000 users known: triggers the clean-up
    assert "busy" in srv._recent and "someone" in srv._recent
    assert len(srv._recent) < 10
    assert ("u", "2020-01-01") not in srv._mem_counts and ("u", srv._today()) in srv._mem_counts
    srv._recent.clear()
    srv._mem_counts.clear()
