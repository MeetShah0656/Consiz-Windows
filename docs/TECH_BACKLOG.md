# Consiz — Technical Backlog (what is still missing to build)
Audited 2026-10-07 against the code. "Verified" = I ran/grepped it; nothing here is guessed. Size: S ≤ 1 day · M 2–4 days · L > 1 week.

## P0 — must exist before strangers use it

| ID | Gap | Evidence | Fix | Size |
|---|---|---|---|---|
| T-01 | **Middle button is swallowed everywhere** (KI-08): browser "open link in new tab", tab close, autoscroll, Blender/CAD panning all stop working while Consiz runs | `trigger.py` returns 1 for every middle down/up; no exclusion, no pass-through | Trigger mode setting: *Middle-click* / *Ctrl+Middle* / *Hotkey only*; re-inject the click when nothing is selected; per-app exclusion list | M |
| T-02 | **No error log or crash handler** — the exe has no console, so every error vanishes | no `excepthook`, no log handler anywhere (only the auth log) | rotating `~/.consiz/consiz.log`, `sys`/thread excepthooks, tray → "Open log folder / Copy diagnostics" | S |
| T-03 | **Server has no database fallback** — if Neon is down every answer fails with a bare `500 Internal Server Error` | verified by pointing `DATABASE_URL` at a dead host | catch DB errors → 503 + friendly text; fail-soft counter in memory for a few minutes; show in `/health` | S |
| T-04 | **No fallback chain when the cloud fails** — server down / overloaded gives an error even if Ollama is installed | provider is a manual setting only (`llm.py`) | order: server → (if installed) Ollama → clear "try again" with next step; one-click "use offline for now" | M |
| T-05 | **No Stop button** — wrong/slow answers cannot be cancelled; window close keeps the request running | no cancel anywhere in `popup.py` | Stop button + cancel on close/new chat (close the HTTP stream) | S |
| T-06 | **Popup ignores multi-monitor and DPI** — placement uses the primary screen only; process is not DPI-aware (blurry at 125–150%) | no virtual-screen / DPI calls in `popup.py`, `main.py`, `build_exe.py` | per-monitor placement from cursor, DPI-aware manifest, test at 100/125/150% and 2 monitors | M |
| T-07 | **Big CSV/XLSX files freeze or exhaust memory** (KI-05) | `pd.read_csv/read_excel` with no size guard (`deterministic.py:507,561,563`) | size/row guard → friendly "file too big" + sample mode | S |
| T-08 | **No installer, no auto-update, no version check** — you cannot ship a fix to users | none exist (`WIN-011`) | installer (Inno Setup/MSIX), code signing decision, update check against a version file, uninstaller | L |
| T-09 | **Settings are thin** — only API key + language | `settings.py` has 2 options | trigger mode, hotkeys, start-with-Windows, PC mode (on/off, reset consent, forget allowed windows, blocklist editor), AI source (cloud/offline), account + sign-out, popup size/position memory (KI-13), "clear local data" | M |
| T-10 | **No Pause** — no way to turn Consiz off for a game, a presentation or a remote desktop | tray has no toggle | tray "Pause Consiz" (unhooks the mouse, ignores hotkeys), auto-pause for full-screen apps | S |

## P1 — what makes it good, not just working

| ID | Gap | Fix | Size |
|---|---|---|---|
| T-11 | Images/screenshots are only *labelled* by type; nothing reads them (`deterministic.py:260`) — the vision pipeline now exists | Explain mode for an image file or clipboard screenshot via the vision model, with consent | M |
| T-12 | PC mode only *opens* things | confirm-first actions: disable a startup item, clear temp files, end a runaway program (confirmation box names it; never System processes); opt-in background watcher with alerts | M–L |
| T-13 | Chats vanish when the popup closes | optional saved history (local), export/copy as text, pin popup | M |
| T-14 | Server polish: one new Postgres connection per request; no request metrics; per-minute limiter lives in memory; no body cap before JSON parsing (a 5 MB body is parsed then rejected, verified 413 in 0.1 s) | connection pool, request log + counters on `/health`, ASGI body-size cap, cleanup of the in-memory limiter | S–M |
| T-15 | First request after a server restart pays ~1.5 s to fetch Google's signing keys (verified) | warm them in the server startup hook | XS |
| T-16 | Windows 10, non-admin and elevated apps untested; hooks cannot see elevated windows without admin | test matrix (`WIN-010`), clear message when a window is elevated | M |
| T-17 | Keyboard/accessibility: tab order, screen-reader labels, high contrast, text scaling | accessibility pass on popup, login, settings | M |
| T-18 | UI text is English-only (answers are localized) | string table, Hindi first | M |
| T-19 | Product name is mixed "Conciz" / "Consiz" in UI strings and code | one name everywhere + test that greps for the wrong one | XS |
| T-20 | Hidden dictation code is a maintenance risk | either re-enable behind a setting or remove it | S |
| T-21 | Real-exe checks are manual (I ran them ad hoc): login window, hotkey, PC chat, consent box | turn them into `scripts/smoke_ui.py`; add GitHub Actions for unit tests + secret scan | M |

## P2 — later
macOS parity for chat/PC mode/sign-in (L) · plans and billing on the server (L) · anonymous opt-in usage counts (M) · phone sign-in (needs paid SMS) · Android/iOS thin clients over the same server (L).

## Suggested build order (technical, one release)
1. **T-02 + T-01** (see what breaks, then stop breaking people's mouse) → 2. **T-05, T-10** (control) → 3. **T-03, T-04** (failure paths) → 4. **T-06, T-07** (robustness) → 5. **T-09** (settings that expose all of it) → 6. **T-08** (installer/update) → then P1.
