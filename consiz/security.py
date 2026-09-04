"""Privacy controls (spec §5.7): detect credential-like patterns before content reaches any model.

We run a local model, so nothing leaves the machine — but the spec still requires that
credentials never be silently fed to a backend. We redact and warn.
"""
from __future__ import annotations

import re

# (label, compiled pattern) — deliberately conservative; false positives only cost a redaction.
_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("OpenAI-style key", re.compile(r"\bsk-[A-Za-z0-9_\-]{20,}\b")),
    ("Anthropic key", re.compile(r"\bsk-ant-[A-Za-z0-9_\-]{20,}\b")),
    ("AWS access key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("GitHub token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b")),
    ("Slack token", re.compile(r"\bxox[abpr]-[A-Za-z0-9\-]{10,}\b")),
    ("Google API key", re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b")),
    ("Bearer token", re.compile(r"(?i)\bbearer\s+[A-Za-z0-9_\-\.=]{20,}")),
    ("Private key block", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----")),
    ("Password assignment", re.compile(r"(?i)\b(password|passwd|pwd|secret|api[_\-]?key|token)\s*[:=]\s*\S{6,}")),
    ("Card number", re.compile(r"\b(?:\d[ -]?){13,19}\b")),
]


def _luhn_ok(digits: str) -> bool:
    total, alt = 0, False
    for ch in reversed(digits):
        d = int(ch)
        if alt:
            d = d * 2 - 9 if d * 2 > 9 else d * 2
        total += d
        alt = not alt
    return total % 10 == 0


def redact(text: str) -> tuple[str, list[str]]:
    """Return (redacted_text, list of labels found)."""
    found: list[str] = []
    out = text
    for label, pat in _PATTERNS:
        def _sub(m: re.Match) -> str:
            if label == "Card number":
                digits = re.sub(r"\D", "", m.group(0))
                if not _luhn_ok(digits):
                    return m.group(0)          # just a long number, not a card
            if label not in found:
                found.append(label)
            return f"[REDACTED {label.upper()}]"
        out = pat.sub(_sub, out)
    return out, found
