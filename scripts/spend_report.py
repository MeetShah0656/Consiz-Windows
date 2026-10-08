"""What does one answer really cost? Reads the server's `spend` table and prices the real usage on paid models.

  python scripts/spend_report.py                      # DATABASE_URL (Neon) if set, else conciz_server.db
  python scripts/spend_report.py --days 14 --inr 90
  python scripts/spend_report.py --price google/gemini-3.1-flash-lite,openai/gpt-5.4-mini

Free models bill $0, so the money columns stay 0 until we go paid; the token columns are real either way and the
"if paid" table multiplies them by OpenRouter's live prices. Only token counts are stored, never prompts or answers.
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

DEFAULT_PRICE = ("nvidia/nemotron-3-super-120b-a12b", "google/gemini-3.1-flash-lite", "openai/gpt-5.4-mini")


def _connect(path: str):
    url = os.environ.get("DATABASE_URL", "").strip()
    if url.startswith(("postgres://", "postgresql://")):
        import psycopg2
        return psycopg2.connect(url, connect_timeout=10), "%s"
    return sqlite3.connect(path), "?"


def _prices(models: list[str]) -> dict[str, tuple[float, float]]:
    """{model: ($ per 1M input tokens, $ per 1M output tokens)} from OpenRouter's public model list."""
    try:
        data = requests.get("https://openrouter.ai/api/v1/models", timeout=15).json()["data"]
    except Exception as e:
        print(f"(could not fetch live prices: {type(e).__name__})")
        return {}
    by_id = {m["id"]: m.get("pricing", {}) for m in data if isinstance(m, dict) and "id" in m}
    out = {}
    for name in models:
        p = by_id.get(name)
        if p:
            out[name] = (float(p["prompt"]) * 1e6, float(p["completion"]) * 1e6)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default=os.environ.get("CONSIZ_SERVER_DB", "conciz_server.db"), help="SQLite file (when no DATABASE_URL)")
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--inr", type=float, default=90.0, help="rupees per US dollar")
    ap.add_argument("--price", default=",".join(DEFAULT_PRICE), help="comma list of OpenRouter model ids to price")
    args = ap.parse_args()

    env = Path(__file__).resolve().parent.parent / ".env"
    if env.exists():
        try:
            from dotenv import load_dotenv
            load_dotenv(env)
        except ImportError:
            pass
    con, ph = _connect(args.db)
    since = (datetime.now(timezone.utc) - timedelta(days=args.days - 1)).strftime("%Y-%m-%d")
    cur = con.cursor()
    try:
        cur.execute(f"SELECT day, sub, model, calls, tokens_in, tokens_out, cost_usd, unmetered FROM spend WHERE day >= {ph}", [since])
    except Exception as e:
        print(f"No spend table yet ({type(e).__name__}). Deploy the new server and make a few answers first.")
        return 1
    rows = cur.fetchall()
    con.close()
    if not rows:
        print(f"No answers recorded since {since}.")
        return 0

    answers = sum(r[3] for r in rows)
    unmetered = sum(r[7] for r in rows)
    metered = answers - unmetered
    tin, tout = sum(r[4] for r in rows), sum(r[5] for r in rows)
    billed = sum(r[6] for r in rows)
    users = {r[1] for r in rows}
    active_days = {(r[0], r[1]) for r in rows}
    print(f"Since {since}: {answers} answers | {len(users)} users | {metered} with token counts ({unmetered} without)")
    print(f"Billed by OpenRouter: ${billed:.4f}  (Rs {billed * args.inr:.2f})")
    print("\nBy model:")
    for model in sorted({r[2] for r in rows}):
        sub = [r for r in rows if r[2] == model]
        print(f"  {model:55s} {sum(r[3] for r in sub):6d} answers  in {sum(r[4] for r in sub):9d}  out {sum(r[5] for r in sub):8d}  ${sum(r[6] for r in sub):.4f}")
    per_user: dict[str, int] = {}
    for r in rows:
        per_user[r[1]] = per_user.get(r[1], 0) + r[3]
    print("\nHeaviest users (answers):  " + ", ".join(f"..{u[-6:]} {n}" for u, n in sorted(per_user.items(), key=lambda x: -x[1])[:5]))

    if not metered:
        print("\nNo token counts yet, so nothing to price.")
        return 0
    avg_in, avg_out = tin / metered, tout / metered
    per_user_day = answers / max(len(active_days), 1)
    print(f"\nMeasured: {avg_in:.0f} tokens in + {avg_out:.0f} out per answer | {per_user_day:.1f} answers per user per active day")
    print(f"\nIf we paid for the same usage (Rs {args.inr:g} per $, 30 days):")
    print(f"  {'model':45s} {'Rs/answer':>10s} {'Rs/user/month':>14s} {'worst user (50/day)':>20s}")
    prices = _prices([m.strip() for m in args.price.split(",") if m.strip()])
    for name, (pin, pout) in prices.items():
        per_answer = (avg_in * pin + avg_out * pout) / 1e6 * args.inr
        print(f"  {name:45s} {per_answer:10.3f} {per_answer * per_user_day * 30:14.1f} {per_answer * 50 * 30:20.0f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
