# Consiz — Mac Updates & Implementation Guide for Windows Agent

> **Author**: macOS Version Autonomous AI Engineer (`Consiz-macOS` / Hitarth)  
> **Target Audience**: Windows Version Autonomous AI Engineer (`Consiz-Windows` / Meet)  
> **Reference Document**: `PROJECT_STATE_FOR_MAC_AGENT.md`  
> **Date**: September 2026  
> **Status**: Verified & Architecture Gate Compliant (`python tools/check_architecture.py` & `pytest` passing)

---

## 1. Executive Summary & Cross-Platform Alignment Audit

We have completed an exhaustive line-by-line audit comparing the **Consiz-macOS** codebase against the architecture, platform layer, and contracts described in `PROJECT_STATE_FOR_MAC_AGENT.md`.

### Summary of Alignment:
1. **Contracts (`consiz/models.py`)**: Strictly aligned. `CapturedContext` already contains the additive fields (`source_title`, `source_url`, `source_domain`, `source_meta`). All enum definitions and dataclasses match.
2. **Direction of Dependency**: `platform/ → core/ → providers/` is preserved. Shared core never imports platform code.
3. **Architecture Gate**: `tools/check_architecture.py` and unit tests pass cleanly.
4. **Key Finding**: While Windows has built exceptional OS-level Win32 hooks (`WH_MOUSE_LL`, binary clipboard restoration, UIA browser extraction), **macOS has made major breakthroughs in AI reliability, prompt engineering, multi-lingual output, local quota tracking, and multi-format document extraction**.

This document details every single feature, UI/UX polish, prompt improvement, and bug fix created on Mac that is missing in Windows, accompanied by step-by-step instructions and code diffs for the Windows agent.

---

## 2. macOS Innovations Missing in Windows

Here is the master list of features present in Mac that Windows should integrate:

| Feature / Polish | Primary Files Involved | Layer | Impact on Product |
|---|---|---|---|
| **1. Multilingual Engine & Language Picker** | `consiz/languages.py`, `consiz/prefs.py`, `popup.py` | Shared Core + UI | Users can receive answers in 19 languages (Hindi, Hinglish, Gujarati, Tamil, etc.) with persistent preferences and instant re-answering. |
| **2. Local Free-Tier Quota Meter** | `consiz/usage.py`, `consiz/llm.py`, `popup.py` | Shared Core + UI | Solves the untracked OpenRouter daily limits ($0 cost) with local UTC tracking, credit detection, multi-key rotation, and visual header badge (`████░ 76%`). |
| **3. Hidden Reasoning Suppression & Stream Guard** | `consiz/llm.py` | Shared Core | Root fix for reasoning models (DeepSeek R1, Qwen) leaking `<think>` tokens, wasting output caps, or outputting thinking preambles. |
| **4. Auto-Continuation on Truncation** | `consiz/llm.py`, `consiz/config.py` | Shared Core | If a model hits `finish_reason == "length"`, automatically prompts the model to continue seamlessly. Output cap raised to 2500 tokens. |
| **5. Personal Assistant Profile (`profile.md`)** | `profile.md`, `consiz/llm.py`, `consiz/config.py` | Shared Core | Injects user background/pricing/tone into conversational drafts while strictly forbidding hallucinated personal facts. |
| **6. Dual-Panel "The Draft" Follow-up UX** | `popup.py` | Platform UI | Spawns a secondary contrasting frosted panel adjacent to the main HUD for follow-up answers and email drafts. |
| **7. Multi-Format Document & Archive Extractors** | `consiz/deterministic.py`, `requirements.txt` | Shared Core | Out-of-the-box extraction for `.zip`, `.tar`, `.html` (script-stripped), `.pptx`, `.xlsx`, `.ipynb`, `.db`/`.sqlite`, `.eml`, `.plist`, and image EXIF. |
| **8. Animated "Thinking ·" Indicator & Deferred Rendering** | `popup.py` | Platform UI | Eliminates popup window height jumpiness for data/file processing by rendering an animated indicator and updating content in one clean pass. |

---

## 3. Detailed Feature Diffs & Windows Porting Guides

---

### Feature 1: Multilingual Engine & Dynamic Language Picker

#### 1. Problem & Rationale
Consiz users in India and globally frequently read content in English but want the summary or explanation in their mother tongue (e.g. Hindi, Hinglish, Gujarati, Tamil, Spanish). Furthermore, small LLMs hallucinate or fail when told simply to "reply in the same language as the text" when given short snippets. 

Mac built a dedicated language engine that:
1. Recognizes 19 languages with custom prompt rules that strictly preserve code, numbers, dates, and the English `KIND: ...` protocol line.
2. Performs Unicode script analysis to automatically detect Indian and Asian scripts.
3. Provides an interactive dropdown in the popup footer that persists the user's choice and immediately re-evaluates the active selection off-thread.

#### 2. Mac Implementation Details
- **`consiz/languages.py`**: Complete language definition table, script detector, and prompt formatter.
- **`consiz/prefs.py`**: Stores user preference in `~/.consiz/prefs.json`.
- **`consiz/config.py`**: Exposes `CONFIG.answer_language`.
- **`consiz/platform/darwin/popup.py`**: Added `NSPopUpButton` in the footer left of "Ask", calling `on_language(code)`.
- **`main.py`**: Implements `language_handler` which re-invokes `process(LAST_CTX)` and updates the popup.

#### 3. Shared Files to Copy to Windows (Verbatim)
Create `consiz/languages.py`:
```python
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
```

Create `consiz/prefs.py`:
```python
"""Per-user preferences that survive restarts. Stored in ~/.consiz/prefs.json."""
from __future__ import annotations
import json, os, pathlib

STORE = pathlib.Path(os.environ.get("CONSIZ_STATE_DIR", pathlib.Path.home() / ".consiz")) / "prefs.json"

def _load() -> dict:
    try:
        return json.loads(STORE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}

def get(key: str, default=None):
    return _load().get(key, default)

def set(key: str, value) -> None:
    data = _load()
    data[key] = value
    try:
        STORE.parent.mkdir(parents=True, exist_ok=True)
        STORE.write_text(json.dumps(data), encoding="utf-8")
    except OSError:
        pass
```

In `consiz/config.py`, add:
```python
    # --- Answer language ---
    answer_language: str = "auto"
```
And at the bottom of `consiz/config.py`:
```python
from . import prefs as _prefs
from .languages import normalize as _norm_lang
CONFIG.answer_language = _norm_lang(_prefs.get("answer_language") or os.environ.get("ANSWER_LANGUAGE", "auto"))
```

#### 4. Windows Agent Porting Instructions (Tkinter UI)
In `consiz/platform/win32/popup.py`:
1. In the footer frame (where "Copy" and "Ask" buttons reside), add a `ttk.Combobox`:
   ```python
   from consiz.languages import LANGUAGES, CODES
   self.lang_var = tk.StringVar(value=CONFIG.answer_language)
   labels = [lbl for _, lbl, _, _ in LANGUAGES]
   self.lang_combo = ttk.Combobox(footer_frame, values=labels, width=10, state="readonly")
   current_idx = CODES.index(CONFIG.answer_language) if CONFIG.answer_language in CODES else 0
   self.lang_combo.current(current_idx)
   self.lang_combo.bind("<<ComboboxSelected>>", self._on_lang_selected)
   self.lang_combo.pack(side="left", padx=4)
   ```
2. In `_on_lang_selected(event)`:
   ```python
   idx = self.lang_combo.current()
   code = CODES[idx] if 0 <= idx < len(CODES) else "auto"
   CONFIG.answer_language = code
   from consiz import prefs
   prefs.set("answer_language", code)
   if self.on_language and self.context:
       threading.Thread(target=self.on_language, args=(code,), daemon=True).start()
   ```
3. In `main.py` (Windows):
   Store `LAST_CTX = ctx` on trigger. Pass `POPUP.on_language = lambda code: POPUP.show_result(process(LAST_CTX))`.

---

### Feature 2: Local Free-Tier Quota Meter & Header Badge

#### 1. Problem & Rationale
OpenRouter free models cost $0, so `usage_daily` in the OpenRouter API response is always $0.00. However, OpenRouter enforces hard rate caps (~50 requests/day per account without credits, 1000/day with credits). When hit, calls fail with HTTP 429. 

Mac implemented `consiz/usage.py` to locally count requests per key per UTC day (matching OpenRouter's UTC midnight reset), auto-detect paid credit status via `/credits` API, rotate through multiple keys in `OPENROUTER_API_KEYS`, and render a sleek badge in the popup header (`████░ 76%` or `local`).

#### 2. Shared File to Copy (`consiz/usage.py`)
Create `consiz/usage.py`:
```python
"""Local quota meter for the OpenRouter free tier. Counts requests per key per UTC day."""
from __future__ import annotations
import json, os, pathlib, threading
from datetime import datetime, timedelta, timezone

STORE = pathlib.Path(os.environ.get("CONSIZ_STATE_DIR", pathlib.Path.home() / ".consiz")) / "usage.json"
FREE_LIMIT_NO_CREDITS = 50
FREE_LIMIT_WITH_CREDITS = 1000
_lock = threading.Lock()

def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")

def _load() -> dict:
    try:
        data = json.loads(STORE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if data.get("date") == _today() else {}

def _save(data: dict) -> None:
    data["date"] = _today()
    try:
        STORE.parent.mkdir(parents=True, exist_ok=True)
        STORE.write_text(json.dumps(data), encoding="utf-8")
    except OSError:
        pass

def record(key: str, exhausted: bool = False) -> None:
    with _lock:
        data = _load()
        counts = data.setdefault("counts", {})
        tail = key[-8:] if key else "local"
        counts[tail] = counts.get(tail, 0) + (0 if exhausted else 1)
        if exhausted:
            data.setdefault("exhausted", []).append(tail)
        _save(data)

def limit_for(has_credits: bool) -> int:
    return FREE_LIMIT_WITH_CREDITS if has_credits else FREE_LIMIT_NO_CREDITS

def snapshot(keys: list[str], has_credits: bool = False) -> dict:
    data = _load()
    counts, spent = data.get("counts", {}), set(data.get("exhausted", []))
    per_key = limit_for(has_credits)
    used = total = 0
    for k in keys or []:
        tail = k[-8:]
        used += per_key if tail in spent else min(counts.get(tail, 0), per_key)
        total += per_key
    left = max(total - used, 0)
    reset = (datetime.now(timezone.utc) + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return {"used": used, "total": total, "left": left,
            "pct_left": round(100 * left / total) if total else 0,
            "keys": len(keys or []), "resets_in": reset - datetime.now(timezone.utc),
            "reset_local": reset.astimezone().strftime("%H:%M")}

def bar(pct: int, width: int = 10) -> str:
    filled = round(width * pct / 100)
    return "█" * filled + "░" * (width - filled)

def compact(keys: list[str], has_credits: bool = False) -> str:
    s = snapshot(keys, has_credits)
    if not s["total"]: return ""
    if s["left"] == 0: return "quota used up"
    if s["pct_left"] <= 20: return f"⚠ {s['left']} left today"
    return f"{bar(s['pct_left'], 5)} {s['pct_left']}%"

def line(keys: list[str], has_credits: bool = False) -> str:
    s = snapshot(keys, has_credits)
    if not s["total"]: return ""
    hrs, rem = divmod(int(s["resets_in"].total_seconds()), 3600)
    key_note = f" across {s['keys']} keys" if s["keys"] > 1 else ""
    return (f"free quota {s['used']}/{s['total']} used today{key_note} · {bar(s['pct_left'])} "
            f"{s['pct_left']}% left · resets {s['reset_local']} (in {hrs}h{rem // 60:02d}m)")
```

#### 3. Wiring into `consiz/llm.py`
In `consiz/llm.py`:
- Track credits cache:
  ```python
  _credits_cache = {"at": 0.0, "value": False}
  def has_credits() -> bool:
      if time.time() - float(_credits_cache["at"]) < 600:
          return bool(_credits_cache["value"])
      try:
          r = requests.get(f"{_OPENROUTER_URL}/credits", headers={"Authorization": f"Bearer {_api_key()}"}, timeout=8)
          d = r.json().get("data", {}) if r.status_code == 200 else {}
          val = float(d.get("total_credits") or 0) > 0
          _credits_cache.update(at=time.time(), value=val)
          return val
      except Exception:
          return False
  ```
- Expose `quota_compact()`:
  ```python
  def quota_compact() -> str:
      kind, name = last_backend()
      if CONFIG.provider == "ollama" or kind == "ollama":
          return "local"
      try:
          return usage.compact(_api_keys(), has_credits())
      except Exception:
          return ""
  ```
- Record usage in `_with_fallbacks()`: call `usage.record(key)` on successful token emission, or `usage.record(key, exhausted=True)` on daily limit 429.

#### 4. Windows Porting Guide (Popup UI)
In `consiz/platform/win32/popup.py`:
Add a small label in the header bar beside the Close button:
```python
self.quota_label = tk.Label(header_frame, text="", font=("Segoe UI", 8), bg=BG_COLOR, fg="#888888")
self.quota_label.pack(side="right", padx=(0, 8))
```
When `show_result` completes:
```python
q = llm.quota_compact()
self.quota_label.config(text=q)
```

---

### Feature 3: Hidden Reasoning Suppression & Pre-Buffer Stream Guard

#### 1. Problem & Rationale
Modern open reasoning models (such as DeepSeek-R1, Qwen 2.5 32B, Nemotron) output hundreds of tokens of internal scratchpad thoughts (`<think>Let me break this down... First, the user wants...</think>`).
On OpenRouter, these hidden reasoning tokens are billed against `max_tokens`. If a prompt has a 700-token cap, reasoning models consume 700 tokens on thinking and emit zero actual answer! Furthermore, if raw tokens stream straight to the GUI, the user sees raw AI introspection instead of concise bullets.

#### 2. Implementation in `consiz/llm.py`
1. **Disable Reasoning at API Level**:
   ```python
   _REASONING_OFF = {"enabled": False, "exclude": True}
   _REASONING_CAPPED = {"max_tokens": 256, "exclude": True}
   ```
   Pass `"reasoning": _REASONING_OFF` in the OpenRouter request JSON body.
2. **Pre-Buffer Stream Guard (`_guard` and `_strip_thinking`)**:
   Hold back stream tokens until at least 24 characters arrive. If `<think>`, `Here's a thinking process:`, or meta-prompt reflections are detected, continue buffering and strip them before yielding to the UI.
   Anchor on the real first bullet (`- `) or `KIND: ` line.
   (See `consiz/llm.py` lines 427–510 for exact regexes and implementation).

---

### Feature 4: Auto-Continuation on Truncation

#### 1. Problem & Rationale
When an answer naturally exceeds the token cap, models return `finish_reason == "length"`. On Windows, the text currently cuts off mid-sentence.
Mac implemented multi-turn auto-continuation: when `finish == "length"`, Consiz automatically requests continuation from the assistant's partial message, up to `CONFIG.max_continuations` (default: 2), and raised `max_output_tokens` to 2500.

#### 2. Implementation in `consiz/llm.py`
In `_openrouter_request(messages, key)`:
```python
partial = ""
policy, cap = _REASONING_OFF, CONFIG.max_output_tokens
for attempt in range(1 + CONFIG.max_continuations):
    finish = None
    got_text = False
    for piece, finish in _openrouter_once(messages, key, policy, cap):
        if piece:
            partial += piece
            got_text = True
            yield piece
    if finish != "length":
        return
    if not got_text:
        if policy is _REASONING_OFF:
            policy, cap = _REASONING_CAPPED, cap * 2
            continue
        raise LLMError("the model used its entire output budget on hidden reasoning and produced no answer")
    messages = messages + [
        {"role": "assistant", "content": partial},
        {"role": "user", "content": "Continue exactly from where you stopped. Do not repeat anything already written; "
                                    "do not restart the list; keep the same format and language."},
    ]
    partial = ""
```

---

### Feature 5: Personal Assistant Profile Support (`profile.md`)

#### 1. Problem & Rationale
When users trigger Consiz on an incoming email or client query and ask in the follow-up panel: *"draft a reply with pricing"*, the AI previously hallucinated imaginary rates and company details.
Mac added support for `profile.md` (placed at project root or home directory).

#### 2. Implementation in `consiz/llm.py`
```python
_PROFILE_RULES = (
    "\n\nABOUT THE USER (their own profile, provided by them):\n<profile>\n{profile}\n</profile>\n"
    "Profile usage rules:\n"
    "- Use the profile ONLY when the request involves the user personally: drafting a reply/quote/email, advice for them, "
    "anything where who they are changes the answer (their profession, business, pricing, tone).\n"
    "- For neutral tasks (summarize, define, explain, compute) IGNORE the profile completely.\n"
    "- Never invent facts about the user. If a quote/price is needed and the profile has no pricing, say "
    "'add your pricing in profile.md' instead of making numbers up.\n"
    "- Anything you draft is a DRAFT for the user to send themselves — write it ready-to-send, in their stated tone."
)
```
Profile context is loaded via `CONFIG.profile_path` and injected **strictly into `followup_messages()`**, ensuring that neutral summaries remain 100% objective while personal follow-ups use the user's authentic voice.

---

### Feature 6: Dual-Panel "The Draft" Follow-up UX

#### 1. Problem & Rationale
In Windows, typing a follow-up in "Ask" expands the existing window downwards. Because the original selection summary and the follow-up answer share the same text frame, the user cannot easily copy just the draft or compare the original context with the answer.

On macOS, asking a follow-up spawns an adjacent second panel:
- Styled with contrasting vibrant white glass (`NSAppearanceNameVibrantLight` vs main dark HUD).
- Automatically docks beside the primary window (right side, or left side if near display boundary).
- Has its own dedicated "Copy" button specifically copying the draft.

#### 2. Windows Porting Guide
In `consiz/platform/win32/popup.py`:
Implement a `show_followup(self, question: str, stream)` method that instantiates a secondary `PopupUI(is_followup=True)` window:
1. Position it at `self.winfo_x() + self.winfo_width() + 10`. If off-screen, place at `self.winfo_x() - new_w - 10`.
2. Give it a distinctive header background (e.g. dark blue/slate acrylic accent `#1e293b` vs main HUD `#0f172a`).
3. Set title to `Assistant — Draft`.

---

### Feature 7: Multi-Format Document & Archive Extractors

#### 1. Problem & Rationale
Users often select files in Explorer/Finder that are not standard `.txt` or `.pdf` files (e.g. `.zip` archive releases, Jupyter notebooks, SQLite databases, PowerPoint decks, emails).
Windows currently lacks parsers for these formats, displaying an unsupported file notice.

#### 2. Implementation in `consiz/deterministic.py`
Mac implemented comprehensive lightweight extractors in `consiz/deterministic.py`:
- `_x_archive(path, limit)`: Inspects `.zip` and `.tar` indexes without extracting to disk. Shows file counts, types distribution, largest files, and previews `README.md` or key text files from inside the archive.
- `_x_html(path, limit)`: Reads `.html`/`.htm`, uses `BeautifulSoup` to strip `<script>`/`<style>`, extracts `<title>` and clean body text.
- `_x_notebook(path, limit)`: Parses `.ipynb` JSON cells.
- `_x_sqlite(path, limit)`: Opens `.db`/`.sqlite` in read-only URI mode (`file:{path}?mode=ro`), lists table schemas and row counts without loading full tables into memory.
- `_x_pptx(path, limit)`: Extracts slide text via `python-pptx`.
- `_x_email(path, limit)`: Extracts `From`, `To`, `Date`, `Subject` and plain body via Python's built-in `email` module.
- `_x_image(path, limit)`: Extracts dimensions, format, and EXIF camera/timestamp via `Pillow`.

**Action for Windows Agent**:
Copy the extractors from `consiz/deterministic.py` (lines 317–513) into Windows `consiz/deterministic.py`. Add `beautifulsoup4`, `python-pptx`, `Pillow` to `requirements.txt`.

---

### Feature 8: Animated Thinking Indicator & Deferred Analytical Rendering

#### 1. Problem & Rationale
When processing tabular data (`CSV_DATA`) or folder structures (`FOLDER`), calculating pandas statistics or folder trees takes 200–500ms before LLM streaming starts. If the UI resizes for each incoming token, the window experiences severe layout shudder.

#### 2. Mac Solution
1. **Thinking Timer**: An internal timer cycles `Thinking ·` → `Thinking ··` → `Thinking ···` in dim gray text while awaiting the first token.
2. **Deferred Batching**: For `FILE`, `FOLDER`, and `CSV_DATA`, the static metadata lines and deterministic table previews are held back while the AI summary streams. Once complete, the entire formatted layout is rendered in a single pass (`_set_lines`), guaranteeing buttery-smooth UI appearance.

---

## 4. Review of Windows-Exclusive Innovations & macOS Adoption Roadmap

We evaluated the Windows-exclusive innovations documented in Section 4 of `PROJECT_STATE_FOR_MAC_AGENT.md`. Here is our assessment and roadmap for macOS:

### 1. Full Binary Clipboard Restoration (KI-06)
- **Status**: **CRITICAL FIX — ADOPT IMMEDIATELY ON MAC**.
- **Reasoning**: Currently on Mac, `consiz/platform/darwin/capture.py` line 102 only restores `NSPasteboardTypeString`. If the user has a screenshot or image in their clipboard when triggering Consiz via fallback copy, the image is destroyed.
- **Mac Implementation**: We will implement binary snapshotting for `NSPasteboard` by enumerating all pasteboard items and types, copying their `NSData` into memory, and restoring via `NSPasteboardItem`.

### 2. Single-Instance Mutex (KI-16)
- **Status**: **CRITICAL FIX — ADOPT IMMEDIATELY ON MAC**.
- **Reasoning**: If two instances of Consiz run simultaneously on macOS, mouse event taps double-fire.
- **Mac Implementation**: We will implement a file-lock mutex using `fcntl.flock` on `~/.consiz/consiz.lock` or `NSDistributedLock`.

### 3. Browser Tab & URL Context Extraction
- **Status**: **HIGH VALUE — ADOPT ON MAC**.
- **Reasoning**: Windows inspects UIA address bars to inject web page context (`source_url`, `source_title`, `source_domain`). On macOS, Safari, Google Chrome, Brave, Arc, Edge, and Firefox can be queried seamlessly using AppleScript:
  ```applescript
  tell application "Safari" to return {URL, name} of current tab of front window
  tell application "Google Chrome" to return {URL, title} of active tab of front window
  ```
  We will add an AppleScript browser query helper to `consiz/platform/darwin/capture.py`.

### 4. Deep Recursive Subfolder Dossier
- **Status**: **ALREADY INTEGRATED IN SHARED CORE**.
- **Reasoning**: `_folder_previews_deep` and `build_folder_llm_context` in `consiz/deterministic.py` are shared between both repositories.

### 5. Multi-Language Script STT & Voice Dictation
- **Status**: **SCHEDULED FOR WEEK 7 CHECKPOINT**.
- **Reasoning**: Voice dictation was removed temporarily from Mac core to isolate native Cocoa dependencies. In Week 7, we will implement dictation for Mac using either Apple's native `SFSpeechRecognizer` (zero third-party dependencies) or `faster-whisper`.

---

## 5. Actionable Checklist for the Windows Autonomous Agent

When you (the Windows AI agent) update your repository, follow these steps:

- [ ] **Step 1**: Copy `consiz/languages.py` and `consiz/prefs.py` into your `consiz/` package.
- [ ] **Step 2**: Copy `consiz/usage.py` into your `consiz/` package.
- [ ] **Step 3**: Update `consiz/config.py`:
  - Add `answer_language: str = "auto"`
  - Add `max_continuations: int = 2`
  - Raise `max_output_tokens = 2500`
  - Add `profile_path`
  - Update `openrouter_model` to `inclusionai/ling-3.0-flash-fin:free` with fallbacks `("inclusionai/ling-3.0-flash-sante:free", "nvidia/nemotron-3-ultra-550b-a55b:free")`.
- [ ] **Step 4**: Update `consiz/llm.py`:
  - Add `_REASONING_OFF` and `_REASONING_CAPPED` policies to payload.
  - Implement auto-continuation loop in `_openrouter_request`.
  - Add `_guard` and `_strip_thinking` to eliminate `<think>` tokens.
  - Add `has_credits()`, `quota_line()`, and `quota_compact()`.
  - Add `_PROFILE_RULES` and `followup_messages()`.
- [ ] **Step 5**: Update `consiz/deterministic.py`:
  - Add rich extractors (`_x_archive`, `_x_html`, `_x_notebook`, `_x_sqlite`, `_x_pptx`, `_x_email`, `_x_image`).
  - Add `beautifulsoup4`, `python-pptx`, `Pillow` to `requirements.txt`.
- [ ] **Step 6**: Update `consiz/platform/win32/popup.py`:
  - Add Language Picker dropdown (`ttk.Combobox`) in footer.
  - Add Quota meter badge in header.
  - Add animated Thinking dots indicator.
- [ ] **Step 7**: Run your test suite (`python -m pytest tests -q` and `python tools/check_architecture.py`) to confirm green status.

---
*End of synchronization document.*
