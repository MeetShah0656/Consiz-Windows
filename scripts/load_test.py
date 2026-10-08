"""Load test for the Consiz server (no AI cost, no Google, no database server needed).

  python scripts/load_test.py                       # 20, 50, 100, 200 simultaneous users
  python scripts/load_test.py --users 300 --verify-ms 120

How it works (three processes on your PC):
  1. a FAKE AI provider that streams an answer slowly (default: 0.8 s before the first word, then ~2 s of words);
  2. the REAL server code (`server/app.py`) pointed at that fake AI, with Google sign-in replaced by a stub;
  3. this script, firing N users at the same moment and timing what each one sees.

What to read:
  first word   how long a user waits before text starts (ideal: ~0.8 s, the fake AI's own delay)
  finished     how long the whole answer takes (ideal: ~2.8 s)
  health       how long GET /health takes WHILE under load (the server must stay reachable)
  errors       any request that failed
--certs-ms N  run the REAL sign-in code (signature, expiry, audience) with a fake Google that takes N ms to hand out its
              signing keys; every request carries a genuinely signed token. This is the part of the server that talks to Google.
With 100 users at once an ideal server finishes everyone in about 3 s; a server that can only serve 40 at a time
makes the last users wait for 3 rounds.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
UP_PORT, APP_PORT = 18081, 18080


# ---------------------------------------------------------------- role: fake AI provider
def run_upstream(first_ms: int, words: int, word_ms: int) -> None:
    import uvicorn
    from starlette.applications import Starlette
    from starlette.responses import StreamingResponse
    from starlette.routing import Route

    async def chat(request):
        await request.body()

        async def gen():
            await asyncio.sleep(first_ms / 1000)
            for i in range(words):
                yield f'data: {{"choices":[{{"delta":{{"content":"word{i} "}}}}]}}\n\n'.encode()
                await asyncio.sleep(word_ms / 1000)
            yield b'data: {"model":"fake/model","choices":[],"usage":{"prompt_tokens":900,"completion_tokens":120,"cost":0}}\n\n'
            yield b"data: [DONE]\n\n"
        return StreamingResponse(gen(), media_type="text/event-stream")

    app = Starlette(routes=[Route("/v1/chat/completions", chat, methods=["POST"])])
    uvicorn.run(app, host="127.0.0.1", port=UP_PORT, log_level="error")


# ---------------------------------------------------------------- fake Google (real signed tokens, fake key server)
KEY_FILE = Path(tempfile.gettempdir()) / "consiz_load_test_key.pem"
CLIENT_ID = "load-test-client"


def _private_pem() -> bytes:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    if not KEY_FILE.exists():
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        KEY_FILE.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                               serialization.NoEncryption()))
    return KEY_FILE.read_bytes()


def make_token(i: int) -> str:
    from google.auth import crypt, jwt
    now = int(time.time())
    signer = crypt.RSASigner.from_string(_private_pem(), key_id="k1")
    return jwt.encode(signer, {"iss": "accounts.google.com", "aud": CLIENT_ID, "sub": f"user{i}", "email": f"user{i}@load.test",
                               "email_verified": True, "iat": now, "exp": now + 3600}).decode()


class FakeGoogleKeys:
    """Stands in for the HTTPS call to Google's key server: takes `ms` and returns the public key."""

    def __init__(self, ms: int):
        self.ms, self.calls = ms, 0

    def __call__(self, url, method="GET", body=None, headers=None, timeout=None, **kw):
        from cryptography.hazmat.primitives import serialization
        time.sleep(self.ms / 1000)
        self.calls += 1
        pub = serialization.load_pem_private_key(_private_pem(), None).public_key().public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode()

        class Resp:
            status = 200
            data = json.dumps({"k1": pub}).encode()
            headers = {"cache-control": "public, max-age=3600"}
        return Resp()


# ---------------------------------------------------------------- role: the real server with stubs
def run_app(verify_ms: int, certs_ms: int) -> None:
    import uvicorn
    sys.path.insert(0, str(ROOT))
    os.environ.update(OPENROUTER_API_KEY="load-test", GOOGLE_CLIENT_ID=CLIENT_ID, DAILY_LIMIT="1000000",
                      IP_DAILY_LIMIT="1000000", RATE_PER_MIN="1000000", CONSIZ_SERVER_DB=os.path.join(tempfile.mkdtemp(), "lt.db"))
    os.environ.pop("DATABASE_URL", None)
    from server import app as srv
    srv.SQLITE_PATH = os.environ["CONSIZ_SERVER_DB"]
    srv.OPENROUTER_URL = f"http://127.0.0.1:{UP_PORT}/v1/chat/completions"
    srv._live_model_ids = lambda: set()

    def fake_verify(authorization, _ms=verify_ms):
        if _ms:
            time.sleep(_ms / 1000)                     # stands in for the (blocking) Google sign-in check
        who = (authorization or "").split()[-1]
        return {"sub": who, "email": who + "@load.test"}
    if certs_ms:                                       # keep the REAL _verify; only Google's key server is fake
        fake = FakeGoogleKeys(certs_ms)
        if hasattr(srv._g_request, "_transport"):      # newer server: a caching wrapper around the transport
            srv._g_request._transport = fake
        else:                                          # older server: the transport itself
            srv._g_request = fake
    else:
        srv._verify = fake_verify
    uvicorn.run(srv.app, host="127.0.0.1", port=APP_PORT, log_level="error")


# ---------------------------------------------------------------- role: the swarm of users
async def one_user(client, i: int, out: list, token: str = "") -> None:
    t0 = time.perf_counter()
    first = None
    try:
        async with client.stream("POST", f"http://127.0.0.1:{APP_PORT}/v1/chat/completions",
                                 headers={"Authorization": "Bearer " + (token or f"user{i}")},
                                 json={"messages": [{"role": "user", "content": "hello"}]}) as r:
            if r.status_code != 200:
                out.append(("err", f"HTTP {r.status_code}", 0, time.perf_counter() - t0))
                return
            async for chunk in r.aiter_bytes():
                if first is None and b"word0" in chunk:
                    first = time.perf_counter() - t0
        out.append(("ok", "", first or 0, time.perf_counter() - t0))
    except Exception as e:                              # noqa: BLE001
        out.append(("err", type(e).__name__, 0, time.perf_counter() - t0))


async def health_probe(client, stop: asyncio.Event, out: list) -> None:
    while not stop.is_set():
        t = time.perf_counter()
        try:
            await client.get(f"http://127.0.0.1:{APP_PORT}/health", timeout=30)
            out.append(time.perf_counter() - t)
        except Exception:                               # noqa: BLE001
            out.append(30.0)
        await asyncio.sleep(0.1)


def pct(values, p):
    values = sorted(values)
    return values[min(len(values) - 1, int(len(values) * p))] if values else 0.0


async def swarm(n: int, real_tokens: bool = False) -> dict:
    import httpx
    limits = httpx.Limits(max_connections=n + 20, max_keepalive_connections=n + 20)
    async with httpx.AsyncClient(limits=limits, timeout=httpx.Timeout(120.0)) as client:
        tokens = [make_token(i) for i in range(n)] if real_tokens else [""] * n       # signed BEFORE the clock starts
        results, health, stop = [], [], asyncio.Event()
        probe = asyncio.create_task(health_probe(client, stop, health))
        await asyncio.sleep(0.3)
        t0 = time.perf_counter()
        await asyncio.gather(*(one_user(client, i, results, tokens[i]) for i in range(n)))
        wall = time.perf_counter() - t0
        stop.set()
        await probe
    ok = [r for r in results if r[0] == "ok"]
    errs = [r[1] for r in results if r[0] == "err"]
    return {"n": n, "wall": wall, "first": [r[2] for r in ok], "total": [r[3] for r in ok], "health": health, "errors": errs}


def wait_for(url: str, seconds: float = 30) -> None:
    import httpx
    end = time.time() + seconds
    while time.time() < end:
        try:
            httpx.get(url, timeout=1)
            return
        except Exception:                               # noqa: BLE001
            time.sleep(0.2)
    raise SystemExit(f"could not start {url}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--role", choices=["upstream", "app"], help=argparse.SUPPRESS)
    ap.add_argument("--users", type=int, nargs="*", default=[20, 50, 100, 200])
    ap.add_argument("--first-ms", type=int, default=800, help="fake AI: wait before the first word")
    ap.add_argument("--words", type=int, default=14)
    ap.add_argument("--word-ms", type=int, default=150)
    ap.add_argument("--verify-ms", type=int, default=0, help="simulate a slow blocking sign-in check on every request")
    ap.add_argument("--show-server-log", action="store_true", help="print the server's own log lines")
    ap.add_argument("--certs-ms", type=int, default=0, help="run the real sign-in code; fake Google key server takes this long")
    a = ap.parse_args()
    if a.role == "upstream":
        run_upstream(a.first_ms, a.words, a.word_ms)
        return 0
    if a.role == "app":
        run_app(a.verify_ms, a.certs_ms)
        return 0

    me = [sys.executable, str(Path(__file__).resolve())]
    kw = dict(cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    app_kw = dict(cwd=ROOT, stdout=sys.stdout if a.show_server_log else subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    procs = [subprocess.Popen(me + ["--role", "upstream", "--first-ms", str(a.first_ms), "--words", str(a.words), "--word-ms", str(a.word_ms)], **kw),
             subprocess.Popen(me + ["--role", "app", "--verify-ms", str(a.verify_ms), "--certs-ms", str(a.certs_ms)], **app_kw)]
    try:
        wait_for(f"http://127.0.0.1:{APP_PORT}/health")
        ideal = a.first_ms / 1000 + a.words * a.word_ms / 1000
        print(f"fake AI: first word after {a.first_ms} ms, whole answer ~{ideal:.1f} s | sign-in: " + (f"REAL code, Google key server {a.certs_ms} ms" if a.certs_ms else f"stub {a.verify_ms} ms"))
        asyncio.run(swarm(8, real_tokens=bool(a.certs_ms)))          # warm-up round: start-up costs are not what we measure
        print(f"{'users':>6} {'errors':>6} | {'first word p50/p95 (s)':>24} | {'finished p50/p95/max (s)':>26} | {'health p95 (s)':>14} | {'all done in (s)':>15}")
        for n in a.users:
            r = asyncio.run(swarm(n, real_tokens=bool(a.certs_ms)))
            f, t, h = r["first"], r["total"], r["health"]
            print(f"{n:>6} {len(r['errors']):>6} | {statistics.median(f) if f else 0:>11.2f} /{pct(f, .95):>10.2f} | "
                  f"{statistics.median(t) if t else 0:>9.2f} /{pct(t, .95):>7.2f} /{max(t) if t else 0:>6.2f} | {pct(h, .95):>14.2f} | {r['wall']:>15.2f}")
            if r["errors"]:
                print("        errors:", {e: r["errors"].count(e) for e in set(r["errors"])})
    finally:
        for p in procs:
            p.terminate()
    return 0


if __name__ == "__main__":
    sys.exit(main())
