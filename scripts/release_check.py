"""One command that answers "is this build safe to publish?" with PASS / FAIL / WARN and the evidence.

    python scripts/release_check.py                 # everything (builds the exe: ~4 min)
    python scripts/release_check.py --skip-build    # fast: tests, secrets, docs, server
    python scripts/release_check.py --server https://consiz-windows.onrender.com

Exit code 1 if anything FAILs. Run it before every push/release; paste the table in the PR.
Nothing here changes your settings or sends your data: it only reads, builds, and calls the public server URLs.
"""
from __future__ import annotations

import argparse
import csv
import os
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

RESULTS: list[tuple[str, str, str]] = []          # (status, check, evidence)


def record(status: str, name: str, evidence: str = "") -> None:
    RESULTS.append((status, name, evidence))
    print(f"[{status:4}] {name}" + (f" - {evidence}" if evidence else ""), flush=True)


def run(cmd: list[str], timeout: int = 900) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, encoding="utf-8", errors="replace")


# ------------------------------------------------------------------ 1. tests
def check_tests() -> None:
    p = run([sys.executable, "-m", "pytest", "tests", "-q", "-p", "no:cacheprovider"])
    tail = (p.stdout.strip().splitlines() or ["(no output)"])[-1]
    record("PASS" if p.returncode == 0 else "FAIL", "unit tests", tail)


# ------------------------------------------------------------------ 2. secrets
def check_secrets() -> None:
    from secret_scan import scan                     # scripts/secret_scan.py (this folder is on sys.path when run as a script)
    problems, n = scan(ROOT)
    if problems:
        record("FAIL", "no secrets in git", "; ".join(problems)[:300])
    else:
        record("PASS", "no secrets in git", f"{n} tracked files scanned; .env/.env.txt not tracked")


# ------------------------------------------------------------------ 3. checkpoints + docs
def check_docs() -> None:
    need = ["docs/SYSTEM_DESIGN.md", "docs/ARCHITECTURE_AND_KNOWN_ISSUES.md", "team/CHECKPOINTS.md", "render.yaml",
            "server/DEPLOY.md", ".env.example"]
    missing = [n for n in need if not (ROOT / n).exists()]
    record("FAIL" if missing else "PASS", "required docs/config exist", ", ".join(missing) or f"{len(need)} files")
    mine: list[str] = []                       # this platform's file: breaking the rules blocks the release
    others: list[str] = []                     # other platforms' files: the owner must fix them (warning only)
    for f in (ROOT / "team").glob("checkpoints-*.csv"):
        bucket = mine if "windows" in f.name else others
        seen: set[str] = set()
        with f.open(encoding="utf-8", newline="") as fh:
            for row in csv.DictReader(fh):
                if row["status"] not in ("todo", "in-progress", "done", "blocked"):
                    bucket.append(f"{f.name}:{row['id']} bad status {row['status']!r}")
                if row["id"] in seen:
                    bucket.append(f"{f.name}:{row['id']} duplicate id")
                seen.add(row["id"])
                if row["status"] == "done" and not row["verified_by"].strip():
                    bucket.append(f"{f.name}:{row['id']} done without verified_by")
    record("FAIL" if mine else "PASS", "Windows checkpoint CSV follows the rules", "; ".join(mine[:4]) or "ok")
    if others:
        record("WARN", "other platforms' checkpoint CSVs", f"{len(others)} problems, e.g. {others[0]}")


# ------------------------------------------------------------------ 4. the exe
def check_exe(skip_build: bool) -> None:
    exe = ROOT / "dist" / "Consiz" / "Consiz.exe"
    if not skip_build:
        t = time.time()
        p = run([sys.executable, "build_exe.py"], timeout=1500)
        if p.returncode != 0 or not exe.exists():
            record("FAIL", "exe builds", (p.stderr or p.stdout)[-200:])
            return
        record("PASS", "exe builds", f"{time.time() - t:.0f}s")
    if not exe.exists():
        record("SKIP", "exe checks", "no dist/Consiz/Consiz.exe (run without --skip-build)")
        return
    total_mb = sum(f.stat().st_size for f in exe.parent.rglob("*") if f.is_file()) / 1024 / 1024
    record("PASS" if total_mb < 250 else "WARN", "exe folder size", f"{total_mb:.0f} MB (limit 250)")

    key = ""
    env = ROOT / ".env"
    if env.exists():
        m = re.search(r"(?m)^OPENROUTER_API_KEY=(\S{20,})", env.read_text(encoding="utf-8", errors="ignore"))
        key = m.group(1) if m else ""
    if key:
        needle = key.encode()
        leaked = [f.name for f in exe.parent.rglob("*") if f.is_file() and f.stat().st_size < 60_000_000
                  and needle in f.read_bytes()]
        record("FAIL" if leaked else "PASS", "AI key not inside the exe", ", ".join(leaked) or "raw scan clean")
    if (ROOT / "consiz" / "_build_config.py").exists():
        record("FAIL", "baked config removed from source tree", "consiz/_build_config.py still exists")

    # An isolated copy (own settings folder, own lock), stopped by its process id: the Consiz you are using is untouched.
    p = run([sys.executable, str(ROOT / "scripts" / "smoke_ui.py"), "--exe", str(exe)], timeout=300)
    lines = [ln for ln in p.stdout.splitlines() if ln.startswith("[")]
    record("PASS" if p.returncode == 0 else "FAIL", "exe smoke test (scripts/smoke_ui.py)",
           f"{len(lines)} checks; " + ("all passed" if p.returncode == 0 else next((ln for ln in lines if ln.startswith("[FAIL")), p.stdout[-160:])))


# ------------------------------------------------------------------ 5. the live server
def check_server(base: str) -> None:
    import requests
    base = base.rstrip("/")
    try:
        h = requests.get(base + "/health?deep=1", timeout=90).json()
    except Exception as e:
        record("FAIL", "server reachable", f"{type(e).__name__}: {e}"[:160])
        return
    record("PASS" if h.get("ok") else "FAIL", "server /health", str(h))
    record("PASS" if h.get("storage") == "postgres" and h.get("db_ok") else "WARN",
           "daily limits stored in Postgres", f"storage={h.get('storage')} db_ok={h.get('db_ok')}")
    home = requests.get(base + "/", timeout=60)
    priv = requests.get(base + "/privacy", timeout=60)
    ok_home = home.status_code == 200 and 'href="/privacy"' in home.text and "Consiz" in home.text
    record("PASS" if ok_home else "FAIL", "home page (Google consent link)", f"HTTP {home.status_code}")
    need = ["Privacy Policy", "Limited Use", "OpenRouter"]
    miss = [n for n in need if n not in priv.text]
    record("PASS" if priv.status_code == 200 and not miss else "FAIL", "privacy policy page",
           f"HTTP {priv.status_code}; missing: {miss or 'nothing'}")
    newer = "Ask about my PC" in priv.text and "picture" in priv.text.lower()
    record("PASS" if newer else "WARN", "privacy page covers PC mode + pictures",
           "yes" if newer else "server is older than the app: redeploy on Render")
    body = {"messages": [{"role": "user", "content": "hi"}]}
    r1 = requests.post(base + "/v1/chat/completions", json=body, timeout=60)
    r2 = requests.post(base + "/v1/chat/completions", json=body, headers={"Authorization": "Bearer a.b.c"}, timeout=60)
    record("PASS" if (r1.status_code, r2.status_code) == (401, 401) else "FAIL", "AI endpoint refuses anonymous/fake",
           f"{r1.status_code}/{r2.status_code}")
    pic = {"messages": [{"role": "user", "content": [{"type": "text", "text": "x"}, {"type": "image_url",
           "image_url": {"url": "https://evil.example/a.jpg"}}]}]}
    r3 = requests.post(base + "/v1/chat/completions", json=pic, headers={"Authorization": "Bearer a.b.c"}, timeout=60)
    record("PASS" if r3.status_code == 401 else "WARN", "pictures need sign-in first", f"HTTP {r3.status_code}")


# ------------------------------------------------------------------ 6. git state
def check_git() -> None:
    dirty = run(["git", "status", "--porcelain"]).stdout.strip()
    record("WARN" if dirty else "PASS", "working tree committed", f"{len(dirty.splitlines())} uncommitted files" if dirty else "clean")
    ahead = run(["git", "rev-list", "--count", "@{u}..HEAD"]).stdout.strip()
    if ahead.isdigit():
        record("INFO", "commits not pushed yet", ahead)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-build", action="store_true", help="skip building/starting the exe")
    ap.add_argument("--server", default=os.environ.get("CONSIZ_SERVER_URL", "https://consiz-windows.onrender.com"))
    args = ap.parse_args()
    check_tests()
    check_secrets()
    check_docs()
    check_exe(args.skip_build)
    check_server(args.server)
    check_git()
    fails = [r for r in RESULTS if r[0] == "FAIL"]
    warns = [r for r in RESULTS if r[0] == "WARN"]
    print("\n" + "=" * 60)
    print(f"RESULT: {'NOT READY' if fails else 'READY'}  |  {len(RESULTS) - len(fails) - len(warns)} ok, "
          f"{len(warns)} warnings, {len(fails)} failures")
    for st, name, ev in fails + warns:
        print(f"  {st}: {name} - {ev}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
