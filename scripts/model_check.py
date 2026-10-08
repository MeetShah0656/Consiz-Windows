"""Which free AI models are fast AND reliable right now?  (free models come and go and vary a lot)

    python scripts/model_check.py                 # tests up to 14 free text models, 3 tries each (~3 min)
    python scripts/model_check.py --tries 5 --max 20
    python scripts/model_check.py --vision        # image-reading models

Prints a ranking and the exact Render settings to paste (OPENROUTER_MODEL / OPENROUTER_FALLBACKS).
Uses OPENROUTER_API_KEY from .env; sends only a tiny test sentence. Read-only.
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import requests
from dotenv import load_dotenv

load_dotenv(ROOT / ".env")
URL = "https://openrouter.ai/api/v1"
PROMPT = [{"role": "system", "content": "Reply in one short bullet."},
          {"role": "user", "content": "What is compound interest?"}]
# a 1x1 white JPEG, only used for --vision
TINY_JPEG = ("/9j/4AAQSkZJRgABAQEASABIAAD/2wBDAP//////////////////////////////////////////////////////////////////////////////////////"
             "wgALCAABAAEBAREA/8QAFBABAAAAAAAAAAAAAAAAAAAAAP/aAAgBAQABPxA=")


def candidates(vision: bool, limit: int) -> list[str]:
    data = requests.get(f"{URL}/models", timeout=20).json()["data"]
    out = []
    for m in data:
        arch = m.get("architecture", {})
        free = str(m.get("pricing", {}).get("prompt")) == "0" and str(m.get("pricing", {}).get("completion")) == "0"
        ins, outs = arch.get("input_modalities") or [], arch.get("output_modalities") or []
        if not free or "text" not in outs or outs != ["text"]:
            continue
        if vision != ("image" in ins):
            continue
        if any(x in m["id"] for x in ("safety", "guard", "embed", "lyria", "rerank")):
            continue
        out.append(m["id"])
    out.sort(key=lambda i: (i != "openrouter/free", i))
    return out[:limit]


def one_try(model: str, vision: bool) -> tuple[float | None, float, str]:
    """(seconds to first text or None, seconds total, outcome)"""
    msgs = PROMPT
    if vision:
        msgs = [{"role": "user", "content": [{"type": "text", "text": "What colour is this? One word."},
                {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + TINY_JPEG}}]}]
    body = {"model": model, "messages": msgs, "max_tokens": 80, "stream": True,
            "reasoning": {"enabled": False, "exclude": True}}
    t0, first = time.time(), None
    try:
        with requests.post(f"{URL}/chat/completions", json=body, stream=True, timeout=(10, 40),
                           headers={"Authorization": "Bearer " + os.environ.get("OPENROUTER_API_KEY", "")}) as r:
            if r.status_code != 200:
                return None, time.time() - t0, f"HTTP {r.status_code}"
            for raw in r.iter_lines():
                if not raw.startswith(b"data:"):
                    continue
                d = raw[5:].strip()
                if d == b"[DONE]":
                    break
                try:
                    obj = json.loads(d)
                except ValueError:
                    continue
                if "error" in obj:
                    return None, time.time() - t0, "error"
                piece = ((obj.get("choices") or [{}])[0].get("delta") or {}).get("content")
                if piece and first is None:
                    first = time.time() - t0
    except requests.RequestException as e:
        return None, time.time() - t0, type(e).__name__
    return first, time.time() - t0, "ok" if first is not None else "empty"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tries", type=int, default=3)
    ap.add_argument("--max", type=int, default=14)
    ap.add_argument("--vision", action="store_true")
    a = ap.parse_args()
    if not os.environ.get("OPENROUTER_API_KEY"):
        print("OPENROUTER_API_KEY is not set (.env)")
        return 2
    models = candidates(a.vision, a.max)
    print(f"Testing {len(models)} free {'vision' if a.vision else 'text'} models x {a.tries} tries...\n", flush=True)
    rows = []
    for m in models:
        firsts, totals, bad = [], [], 0
        for _ in range(a.tries):
            f, tot, outcome = one_try(m, a.vision)
            if f is None:
                bad += 1
            else:
                firsts.append(f)
                totals.append(tot)
        med = statistics.median(totals) if totals else None              # ranked by the WHOLE answer: what users feel
        rows.append((m, med, max(totals) if totals else None, bad, statistics.median(firsts) if firsts else None))
        print(f"  {m:52} first text {('%.1fs' % rows[-1][4]) if firsts else '  -  '}  whole answer median "
              f"{('%.1fs' % med) if totals else '  -  '} worst {('%.1fs' % max(totals)) if totals else ' - '}  "
              f"failed {bad}/{a.tries}", flush=True)
    good = sorted([r for r in rows if r[3] == 0 and r[1] is not None], key=lambda r: r[1])
    ok = sorted([r for r in rows if 0 < r[3] < a.tries and r[1] is not None], key=lambda r: r[1])
    ranked = [r[0] for r in good + ok if r[0] != "openrouter/free"]
    print("\nRanking (never failed; fastest whole answer first):")
    for i, r in enumerate(good, 1):
        print(f"  {i}. {r[0]}  ({r[1]:.1f}s whole answer, {r[4]:.1f}s to first text)")
    if ranked:
        print("\nPaste into Render > Environment:")
        prefix = "VISION_" if a.vision else "OPENROUTER_"
        print(f"  {prefix}MODEL={ranked[0]}")
        if len(ranked) > 1:
            print(f"  {prefix}FALLBACKS={','.join(ranked[1:3])}")
        print("  (the server always adds openrouter/free as the last safety net)")
    else:
        print("\nNo model answered reliably right now. Try again in a few minutes, or add paid credit.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
