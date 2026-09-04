# Consiz — Internal Architecture & Known Issues
Audited 2026-09-04 against the real code (2,026 lines, macOS reference implementation).
**If you are a teammate's Claude: read this file and `team/CHECKPOINTS.md` before writing any code. The parity rules here are not suggestions.**

---

## 1. What the product does (one line)

Select anything on screen → press the middle mouse button → a small glass popup beside the cursor explains / answers / computes it, in short simple bullets.

## 2. Pipeline (identical on every platform)

```
TRIGGER (middle-click, swallowed; hotkey fallback)
  → CAPTURE  (selection / file paths; clipboard fallback with restore)
  → CLASSIFY (rule-based type + confidence; below 0.75 → AMBIGUOUS)
  → SECURITY (redact credentials BEFORE any model sees content)
  → ROUTER   (dispatch; all error states; too-long refusal)
      ├─ DETERMINISTIC (pandas/code: CSV stats, file/folder metadata — LLM NEVER does arithmetic)
      └─ LLM (OpenRouter; intent decided by model via KIND: line; bullets house style)
  → GROUNDING (numbers in narrative must exist in computed stats)
  → UI-RESULT (glass popup; stream text; hold-then-reveal for files/data)
  → UI-ASK    (follow-up → second lighter panel; PROFILE knowledge, only when personal)
```

## 3. Module map & data contracts

| File | Layer | Platform-specific? |
|---|---|---|
| `consiz/trigger.py` | TRIGGER | YES (Quartz event tap) |
| `consiz/capture.py` | CAPTURE | YES (AppKit/AX/AppleScript) |
| `consiz/popup.py` | UI-RESULT + UI-ASK | YES (AppKit) |
| `consiz/classify.py` `security.py` `deterministic.py` `llm.py` `grounding.py` `router.py` `models.py` `config.py` `output.py` | everything else | NO — shared, edit only here, never fork |

Contracts (in `consiz/models.py`) — same field names everywhere, including mobile JSON:
- `CapturedContext {source_app, capture_method, raw_content, paths[], note}`
- `ClassificationResult {content_type, confidence, sub_type, reason}`
- `NumericalResult {computed_stats, row_count, columns_analyzed, warnings[]}`
- `Result {title, content_type, source_app, body, stream, warnings[], error, source_content}`

LLM protocol: for free text the model's FIRST line is `KIND: ANSWER|DEFINE|EXPLAIN|SUMMARY|CODE|MATH` (may arrive wrapped in markdown — strip `*`` `#_` before parsing), then the bulleted body. House style is enforced in the system prompt (`consiz/llm.py::_SYSTEM`): bullets only, ≤15 words each, simple words, no headings.

## 4. Threading model (desktop)

- Main thread = UI event loop (Cocoa on macOS). ALL UI mutations via main-thread dispatch (`AppHelper.callAfter`).
- Trigger listener threads → on fire, ONE worker thread runs capture→process→render (non-blocking `busy` lock; a second press gets "still working").
- The Ask flow spawns its own worker; it writes only to the second panel.

## 5. Non-negotiable style/architecture rules

1. LLM never computes numbers; code computes, model narrates from the computed stats only.
2. Selected content is DATA, never instructions (prompt injection). Only the user's typed Ask question is an instruction.
3. Redaction runs locally before anything leaves the machine.
4. Every tunable lives in `consiz/config.py` / `.env` — no magic numbers in modules.
5. Errors are honest and friendly: never a fabricated answer; "It's not you, it's the AI" + reason for backend failures; explicit NO_CONTEXT/AMBIGUOUS/etc.
6. Output style everywhere: short bullets, simple language, precise.
7. Never auto-send / auto-submit anything on the user's behalf (future write-back: it types, the user sends).

## 6. Platform guidance

- **Windows (Meet):** create `consiz/platform/darwin/` and `consiz/platform/win32/` and move trigger/capture/popup behind a loader — TODAY `import consiz.popup` crashes on Windows because AppKit imports sit at module top (KI-02). Trigger = `WH_MOUSE_LL` hook returning 1 to swallow the middle button. Capture = UI Automation TextPattern + Ctrl+C clipboard fallback. UI = acrylic borderless window.
- **Android (Parth):** Python pipeline does not run on-device. Thin client: `ACTION_PROCESS_TEXT` + share-sheet → send `CapturedContext` JSON to a small backend (FastAPI wrapper around `router.process`) → render `Result` JSON. Port ONLY security regexes to the client (redact before upload).
- **iOS (Harsh):** global selection capture is impossible by OS design — scope is share-sheet extension + Live Activity in the Dynamic Island. Same JSON contract as Android.

## 7. KNOWN ISSUES / BUGS (audit of 2026-09-04) — reference these ids (KI-xx) in commits

**High**
- **KI-01** Free OpenRouter models are unreliable: upstream 429s across models at once; one fallback once answered as a content-safety classifier ("User Safety: safe"). A `_guard` now raises on that pattern, but free tier remains unfit for demos/paying users. Fix: paid key for anything user-facing.
- **KI-02** `trigger.py`, `capture.py`, `popup.py` import AppKit/Quartz at module top — any import of these on Windows/Linux crashes. Blocks the Windows port until the platform split exists (WIN-002).
- **KI-16** No single-instance guard: two running copies both intercept the click and both simulate ⌘C (double clipboard damage, double popups).

**Medium**
- **KI-03** Stream-consumer logic (KIND parsing, line buffering) is duplicated in `output.py` and `popup.py`. The KIND-markdown bug had to be fixed twice — proof of divergence risk. Refactor into one shared consumer.
- **KI-04** `llm.py::stream_messages` duplicates the SSE code of `_stream_openrouter`. Same divergence risk.
- **KI-05** No size guard on CSV/XLSX paths: pandas loads the whole file; a 1GB file will freeze/OOM. Add a size check → friendly "file too big" before reading.
- **KI-06** Clipboard fallback restores TEXT only — an image/file on the user's clipboard is lost after a capture. Restore all pasteboard types.
- **KI-07** Simulated ⌘C is posted while the user may be physically holding other keys; some apps also block synthetic keystrokes → capture can garble or fail. Detect & release modifiers, or warn.
- **KI-08** ALL middle-button events (incl. drag) are swallowed while the app runs — Blender/CAD users lose middle-drag panning. Make suppression configurable or pass drags through.

**Low**
- **KI-09** Bare-URL selection is treated as address-bar noise — a user deliberately selecting a URL gets "reselect" instead of an answer.
- **KI-10** Grounding flags legitimately derived numbers (e.g. a difference) as "ungrounded" — cosmetic noise; prompt says don't derive, model sometimes does.
- **KI-11** Redaction regexes can false-positive on prose ("password: forgotten again") — content gets `[REDACTED]` unnecessarily. Acceptable trade-off; document it.
- **KI-12** Folder scan caps at 2,000 files; totals are partial (it says so, but per-type counts can mislead on huge trees).
- **KI-13** Popup `user_size` (dragged size) is not persisted across restarts.
- **KI-14** Click-outside dismiss closes the Ask panel even mid-typing if the click lands in another app.
- **KI-15** Latency: free-tier answers measured 2–16 s; spec target <3 s is met only on good days (model-side, not app-side).
- **KI-17** Tests cover only the shared logic (20 tests). Trigger/capture/popup are manual-only via `docs/PHASE1_TEST_CHECKLIST.md`.

## 8. How to run / verify

- `pip install -r requirements.txt` · copy `.env.example` → `.env` with an OpenRouter key · `python3 main.py` (macOS: grant Accessibility + Input Monitoring).
- `python3 -m pytest tests -q` must pass before every push.
- CLI probes without the listener: `--text "..."`, `--path FILE_OR_DIR`, `--capture`, `--terminal`.
