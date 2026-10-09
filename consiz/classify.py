"""Context Classification Engine (spec §5.2). Rule-based + confidence — no trained model needed for MVP.

Precedence: explicit signals (path exists, file extension) before content inference (CSV shape, question form).
"""
from __future__ import annotations

import csv
import io
import os
import re

from .config import CONFIG
from .models import CapturedContext, CaptureMethod, ClassificationResult, ContentType

_QUESTION_STARTS = re.compile(
    r"^(who|what|when|where|why|how|which|is|are|was|were|do|does|did|can|could|should|would|will|"
    r"explain|define|tell me|calculate|convert)\b",
    re.IGNORECASE,
)
_NUMERIC = re.compile(r"^\s*[-+]?\$?\s*[\d,]*\.?\d+\s*%?\s*$")


def _csv_shape(text: str) -> tuple[float, str]:
    """Return (confidence that text is delimited tabular data, delimiter)."""
    lines = [ln for ln in text.strip().splitlines() if ln.strip()]
    if len(lines) < 2:
        return 0.0, ""
    try:
        dialect = csv.Sniffer().sniff("\n".join(lines[:20]), delimiters=",\t;|")
        delim = dialect.delimiter
    except csv.Error:
        delim = "\t" if "\t" in lines[0] else ("," if "," in lines[0] else "")
        if not delim:
            return 0.0, ""
    rows = list(csv.reader(io.StringIO("\n".join(lines)), delimiter=delim))
    widths = [len(r) for r in rows if r]
    if not widths or max(widths) < 2:
        return 0.0, ""
    consistent = sum(1 for w in widths if w == widths[0]) / len(widths)
    cells = [c for r in rows[1:] for c in r]  # skip header row
    if not cells:
        return 0.0, ""
    numeric = sum(1 for c in cells if _NUMERIC.match(c)) / len(cells)
    score = 0.5 * consistent + 0.5 * numeric
    return round(score, 2), delim


import urllib.parse

_URL_REGEX = re.compile(
    r"^(https?://|www\.)[^\s<>{}\\|^`\[\]]+$",
    re.IGNORECASE,
)
_COMMON_TLDS = (".com", ".org", ".net", ".edu", ".gov", ".io", ".ai", ".co", ".dev", ".app", ".in", ".uk", ".de", ".me")


def _is_url(text: str) -> bool:
    t = text.strip("'\"` ")
    if "\n" in t or " " in t or len(t) < 4:
        return False
    if _URL_REGEX.match(t):
        return True
    # Domain-like strings: e.g. github.com/owner/repo or python.org
    low = t.lower()
    for tld in _COMMON_TLDS:
        if (f"{tld}/" in low or low.endswith(tld)) and "." in low and not low.startswith("."):
            return True
    return False


def classify(ctx: CapturedContext) -> ClassificationResult:
    # 1. Explicit signals: Explorer/Finder selection
    if ctx.capture_method in (CaptureMethod.FILE_PATH, CaptureMethod.FOLDER_PATH):
        return _classify_path(ctx.raw_content, ctx.paths)

    text = ctx.raw_content.strip()
    if not text:
        return ClassificationResult(ContentType.UNSUPPORTED, 0.0, reason="empty")

    # 2. Selected text that is itself a path on disk (or file:// URI)
    clean_path = text.strip("'\"` ")
    if clean_path.lower().startswith("file:///"):
        clean_path = urllib.parse.unquote(clean_path[8:])
    elif clean_path.lower().startswith("file://"):
        clean_path = urllib.parse.unquote(clean_path[7:])
    candidate = os.path.expanduser(clean_path)
    if len(text) < 1024 and "\n" not in text and os.path.exists(candidate):
        return _classify_path(candidate, [candidate])

    # 3. URL / Web Link (Chrome, Edge, document link, or address bar)
    if _is_url(text):
        return ClassificationResult(ContentType.URL, 0.95, sub_type="web_link", reason="url link")

    # 3. Tabular data pasted/selected as text
    csv_conf, delim = _csv_shape(text)
    if csv_conf >= 0.7:
        return ClassificationResult(ContentType.CSV_DATA, csv_conf, sub_type=f"delimiter={delim!r}", reason="tabular shape")

    # 4. Question
    if len(text) <= CONFIG.question_max_chars:
        if text.endswith("?"):
            return ClassificationResult(ContentType.QUESTION, 0.95, reason="ends with ?")
        if _QUESTION_STARTS.match(text) and text.count("\n") == 0:
            return ClassificationResult(ContentType.QUESTION, 0.8, reason="interrogative opener")

    # 5. Plain text
    return ClassificationResult(ContentType.TEXT_SELECTION, 0.9, sub_type="long" if len(text) > 2000 else "short")


def _classify_path(path: str, paths: list[str]) -> ClassificationResult:
    if len(paths) > 1:
        return ClassificationResult(ContentType.FOLDER, 0.85, sub_type="multi-select", reason=f"{len(paths)} items selected")
    if os.path.isdir(path):
        return ClassificationResult(ContentType.FOLDER, 1.0, reason="isdir")
    if os.path.isfile(path):
        ext = os.path.splitext(path)[1].lower()
        if ext in (".csv", ".tsv", ".xlsx", ".xls"):
            return ClassificationResult(ContentType.CSV_DATA, 1.0, sub_type="file", reason=f"extension {ext}")
        return ClassificationResult(ContentType.FILE, 1.0, sub_type=ext or "no-ext", reason="isfile")
    return ClassificationResult(ContentType.UNSUPPORTED, 0.3, reason="path does not exist")
