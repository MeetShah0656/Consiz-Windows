"""Verification/Grounding Layer (spec §3.1 #7) — MVP: check that numbers in an LLM narrative exist in the computed stats."""
from __future__ import annotations

import re

_NUM = re.compile(r"(?<![\w.])[-+]?\d[\d,]*\.?\d*(?![\w.])")
_DATE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b|\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b|\b(19|20)\d{2}\b")


def _flatten_numbers(obj, out: set[float]) -> None:
    if isinstance(obj, bool):
        return
    if isinstance(obj, (int, float)):
        if obj == obj:  # not nan
            out.add(round(float(obj), 2))
    elif isinstance(obj, str):
        for m in _NUM.finditer(obj):            # numbers inside string stats (dates, labels like "Emp19")
            try:
                out.add(round(float(m.group(0).replace(",", "")), 2))
            except ValueError:
                pass
    elif isinstance(obj, dict):
        for v in obj.values():
            _flatten_numbers(v, out)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            _flatten_numbers(v, out)


def check_numbers(narrative: str, stats: dict) -> list[str]:
    """Return warnings for numbers in the narrative that don't appear (±rounding) in the computed stats."""
    allowed: set[float] = set()
    _flatten_numbers(stats, allowed)
    bad: list[str] = []
    narrative = _DATE.sub(" ", narrative)       # dates and years are not "computed numbers"
    for m in _NUM.finditer(narrative):
        raw = m.group(0)
        try:
            val = float(raw.replace(",", ""))
        except ValueError:
            continue
        if val in (0.0, 1.0, 2.0, 3.0, 4.0, 5.0):   # ordinal/small counts in prose are fine
            continue
        ok = any(abs(val - a) <= max(0.5, abs(a) * 0.005) for a in allowed)
        if not ok and raw not in bad:
            bad.append(raw)
    return [f"ungrounded number in narrative: {b} (not in computed stats)" for b in bad]
