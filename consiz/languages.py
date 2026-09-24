"""Answer languages the user can choose from. One list, shared by the prompt, the popup picker and the CLI.

Each entry: (code, label shown in the UI, name used in the prompt, extra instruction for the model).
"""
from __future__ import annotations

LANGUAGES: list[tuple[str, str, str, str]] = [
    ("auto",      "Auto",       "auto",       ""),
    ("english",   "English",    "English",    ""),
    ("hindi",     "हिन्दी",      "Hindi",      "Devanagari script."),
    ("hinglish",  "Hinglish",   "Hinglish",   "Hindi words written in English/Latin letters, casual everyday Indian style, e.g. 'yeh file ek hiring plan hai'."),
    ("gujarati",  "ગુજરાતી",     "Gujarati",   "Gujarati script."),
    ("marathi",   "मराठी",       "Marathi",    "Devanagari script."),
    ("tamil",     "தமிழ்",       "Tamil",      ""),
    ("telugu",    "తెలుగు",      "Telugu",     ""),
    ("bengali",   "বাংলা",       "Bengali",    ""),
    ("kannada",   "ಕನ್ನಡ",       "Kannada",    ""),
    ("malayalam", "മലയാളം",     "Malayalam",  ""),
    ("punjabi",   "ਪੰਜਾਬੀ",      "Punjabi",    "Gurmukhi script."),
    ("urdu",      "اردو",        "Urdu",       ""),
    ("spanish",   "Español",    "Spanish",    ""),
    ("french",    "Français",   "French",     ""),
    ("german",    "Deutsch",    "German",     ""),
    ("arabic",    "العربية",     "Arabic",     ""),
    ("chinese",   "中文",         "Chinese",    "Simplified characters."),
    ("japanese",  "日本語",       "Japanese",   ""),
]
CODES = [c for c, *_ in LANGUAGES]
_BY_CODE = {c: (label, name, extra) for c, label, name, extra in LANGUAGES}


def normalize(code: str | None) -> str:
    c = (code or "auto").strip().lower()
    return c if c in _BY_CODE else "auto"


def label(code: str) -> str:
    return _BY_CODE[normalize(code)][0]


def prompt_rule(code: str) -> str:
    """The one paragraph appended to the system prompt. KIND: stays English so parsing never breaks."""
    code = normalize(code)
    fixed = ("Keep numbers (Western digits 0-9), dates, names, code, file names and technical terms exactly as they are — "
             "never translate proper nouns or code. The very first line `KIND: ...`, when required, stays in English exactly as specified.")
    if code == "auto":
        return ("\nANSWER LANGUAGE: reply in the same language as the selected content. If the content is mixed, unclear, "
                "or a file/data profile, use English. " + fixed)
    _, name, extra = _BY_CODE[code]
    return (f"\nANSWER LANGUAGE: ALWAYS write the answer in {name}{' (' + extra + ')' if extra else ''}, "
            f"whatever language the content is in. Translate the meaning, keep the bullet format. " + fixed)


_SCRIPTS = [
    ("gujarati",  0x0A80, 0x0AFF), ("hindi",    0x0900, 0x097F),
    ("punjabi",   0x0A00, 0x0A7F), ("bengali",  0x0980, 0x09FF), ("tamil",   0x0B80, 0x0BFF),
    ("telugu",    0x0C00, 0x0C7F), ("kannada",  0x0C80, 0x0CFF), ("malayalam", 0x0D00, 0x0D7F),
    ("urdu",      0x0600, 0x06FF),
    ("japanese",  0x3040, 0x30FF),
    ("chinese",   0x4E00, 0x9FFF),
]


def detect(text: str, min_share: float = 0.3) -> str | None:
    counts: dict[str, int] = {}
    letters = 0
    for ch in text[:4000]:
        if not ch.isalpha():
            continue
        letters += 1
        o = ord(ch)
        for code, lo, hi in _SCRIPTS:
            if lo <= o <= hi:
                counts[code] = counts.get(code, 0) + 1
                break
    if not letters or not counts:
        return None
    code, n = max(counts.items(), key=lambda kv: kv[1])
    if code == "chinese" and counts.get("japanese"):
        code = "japanese"
    return code if n / letters >= min_share else None


def effective(code: str, content: str | None) -> str:
    code = normalize(code)
    if code != "auto" or not content:
        return code
    return detect(content) or "auto"
