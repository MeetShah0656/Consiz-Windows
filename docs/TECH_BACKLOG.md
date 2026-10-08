# Consiz — Technical Backlog (what is still missing to build)
Audited 2026-10-07 against the code. "Verified" = I ran/grepped it; nothing here is guessed. Size: S ≤ 1 day · M 2–4 days · L > 1 week.

## P0 — must exist before strangers use it

| ID | Gap | Evidence | Fix | Size |
|---|---|---|---|---|
| T-01 | ✅ **DONE 2026-10-07** — **Middle button was swallowed everywhere** (KI-08): browser "open link in new tab", tab close, autoscroll, Blender/CAD panning all stop working while Consiz runs | `trigger.py` returns 1 for every middle down/up; no exclusion, no pass-through | Built: tray → Trigger (Middle click / Ctrl+middle only / Keyboard only); a plain click with nothing selected is re-sent to the app; drags (autoscroll/pan) always go to the app; CAD/3D apps excluded by default; terminals and password managers never get a simulated Ctrl+C; empty clicks skip the slow page scan and clipboard step (capture 517 ms → ~290 ms). Open: user-editable exclusion list (T-09) | M |
| T-02 | ✅ **DONE 2026-10-07** — **No error log or crash handler** — the exe has no console, so every error vanishes | no `excepthook`, no log handler anywhere (only the auth log) | Built: rotating `~/.consiz/consiz.log` (512 KB ×3), secrets scrubbed, never logs user text; main/thread/Tk crashes written with tracebacks; fatal error shows a message box with the log path; tray → Help → Open log folder / Copy diagnostics | S |
| T-03 | **Server has no database fallback** — if Neon is down every answer fails with a bare `500 Internal Server Error` | verified by pointing `DATABASE_URL` at a dead host | catch DB errors → 503 + friendly text; fail-soft counter in memory for a few minutes; show in `/health` | S |
| T-04 | ✅ **DONE 2026-10-08 (WIN-027)** — server → offline Ollama (only when the server is unreachable/overloaded and Ollama is running; visible note; switch in Settings). Only logic-tested: no Ollama on the dev PC. **No fallback chain when the cloud fails** — server down / overloaded gives an error even if Ollama is installed | provider is a manual setting only (`llm.py`) | order: server → (if installed) Ollama → clear "try again" with next step; one-click "use offline for now" | M |
| T-05 | ✅ **DONE 2026-10-08 (WIN-026)** — Send turns into Stop; closing the window / New chat also stops, and the HTTP stream is closed so the server stops paying. **No Stop button** — wrong/slow answers cannot be cancelled; window close keeps the request running | no cancel anywhere in `popup.py` | Stop button + cancel on close/new chat (close the HTTP stream) | S |
| T-06 | ✅ **DONE 2026-10-08 (WIN-028)** — system-DPI aware, popup/sign-in/welcome sized in real pixels, popup opens on the monitor under the cursor. Checked by eye at 125% on ONE monitor only; 100%/150% and 2 monitors need a teammate. **Popup ignores multi-monitor and DPI** — placement uses the primary screen only; process is not DPI-aware (blurry at 125–150%) | no virtual-screen / DPI calls in `popup.py`, `main.py`, `build_exe.py` | per-monitor placement from cursor, DPI-aware manifest, test at 100/125/150% and 2 monitors | M |
| T-07 | ✅ **DONE 2026-10-08 (WIN-027)** — tables read only the first 100,000 rows (stated in the answer), giant workbooks and pasted selections refused clearly. **Big CSV/XLSX files freeze or exhaust memory** (KI-05) | `pd.read_csv/read_excel` with no size guard (`deterministic.py:507,561,563`) | size/row guard → friendly "file too big" + sample mode | S |
| T-08 | 🟡 **PARTLY DONE 2026-10-08 (WIN-030)** — built: update check (`/version`, tray 'Download'), `MIN_VERSION` kill-switch (HTTP 426), `installer/consiz.iss` + `scripts/build_installer.py`. NOT done: the installer has never been built (Inno Setup not installed on the dev PC), no code signing (needs a purchased certificate), no silent auto-install (unsafe while unsigned). **No installer, no auto-update, no version check** — you cannot ship a fix to users | none exist (`WIN-011`) | installer (Inno Setup/MSIX), code signing decision, update check against a version file, uninstaller | L |
| T-09 | ✅ **DONE 2026-10-08 (WIN-029)** — five-tab Settings (trigger, shortcuts, pause, excluded programs, start with Windows, AI source + fallback, PC-mode permission/never-read words, account, reset popup size, clear local data); end users are no longer asked for an AI key. **Settings are thin** — only API key + language | `settings.py` has 2 options | trigger mode, hotkeys, start-with-Windows, PC mode (on/off, reset consent, forget allowed windows, blocklist editor), AI source (cloud/offline), account + sign-out, popup size/position memory (KI-13), "clear local data" | M |
| T-10 | ✅ **DONE 2026-10-08 (WIN-026)** — tray Pause/Resume (grey icon, shortcuts released) and auto-pause while Windows reports a full-screen app or presentation. **No Pause** — no way to turn Consiz off for a game, a presentation or a remote desktop | tray has no toggle | tray "Pause Consiz" (unhooks the mouse, ignores hotkeys), auto-pause for full-screen apps | S |

## Found 2026-10-08 while measuring a 10-second answer (all verified)

| ID | Finding | Status |
|---|---|---|
| T-22 | **The whole product shares ONE OpenRouter key limited to 50 free-model requests per day** (1,000/day after adding 10 credits). Our per-user limit of 50 protects nobody — 1 heavy user empties it for everyone. Today's allowance was used up by testing; answers fail until 00:00 UTC (5:30 AM IST). | **BLOCKER for launch.** Add 10 credits to the OpenRouter account (one-time, free models still cost 0) or move to a paid model; server now says "Today's shared free AI allowance is used up…" instead of a generic error |
| T-23 | Free models vary wildly: same question 3.4 s – 11 s; one auto-routed model took 11.6 s median in one run; the default model had been removed by OpenRouter so EVERY request first failed on it | ✅ server drops dead models by itself (checks OpenRouter's model list every 30 min), defaults = measured-fastest (`nemotron-3-super`, `ling-3.0-flash-sante`) + auto-router as safety net; `scripts/model_check.py` re-ranks them (run monthly) |
| T-24 | Server added ~2.5 s per request: new database connection each time + 4 round trips + table check on every request | ✅ pooled connections, table created once, both limits counted in 1 statement; if the database is down the server keeps answering with in-memory limits (T-03 done) |
| T-25 | App opened a new secure connection per question and paid a 2.6 s Google token refresh on the first question | ✅ one kept-alive connection, token refreshed at startup and 5 min before expiry, server pinged every 8 min so it never sleeps while the app runs |
| T-26 | 🟡 **PREPARED 2026-10-08** — `render.yaml` now says `region: singapore`; still needs a NEW Render service (a region cannot be changed) — user action. Render service is in the US while users are in India and the database is in Singapore (every request crosses the world twice) | OPEN — re-create the Render service in **Singapore**; expected to save roughly 1–2 s per answer. Needs a new Render service (region cannot be changed) |
| T-27 | We could not tell what an answer really costs (server only counted answers) | ✅ server now stores tokens in/out + cost per user/day/model (`spend` table, counts only) and `scripts/spend_report.py` prices real usage on paid models. Free models show $0 but tokens are real. Needs server redeploy |

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
