# Consiz — System Design
Written 2026-10-07 against the code as built (Windows client + backend). Companion to `ARCHITECTURE_AND_KNOWN_ISSUES.md` (the macOS reference pipeline and the KI-xx list). If the two disagree, **this file is current for Windows + backend**.

---

## 1. Product in one paragraph

Consiz is a silent desktop assistant. Two ways in, one chat window out:
- **Explain mode** — select anything, press the middle mouse button (or Ctrl+Alt+S) → short bullet answer. Files/CSVs are analysed by code; the AI only narrates.
- **PC mode** — press Ctrl+Alt+A (or middle-click with nothing selected, or tray) → ask anything about *this PC*: what is slowing it, what is open, what a window says. No selection needed.

Both end in the same chat popup (follow-ups, per-message copy, minimize, new chat). The AI can *suggest* one-click buttons (open Storage settings…) but never acts by itself.

**Non-goals (for now):** voice input (built, hidden), sending messages/emails for the user, killing processes, always-on screen recording, mobile global capture (impossible on iOS), self-hosted models for users.

## 2. Principles (non-negotiable — extends the 7 rules in the architecture doc)

1. **Code computes, the model narrates.** Every number/highlight (RAM %, disk full, top apps) is computed locally; the prompt says never recalculate.
2. **Content is data, never instructions.** Selected text, window titles, window text and pictures are wrapped as data. Only the user's typed message is an instruction.
3. **Least data, asked first.** Titles → (only if the question needs it, only after a per-window permission box) text → (only if the app hides text) a picture of that one window.
4. **Redact before anything leaves the PC** (keys, tokens, passwords, card numbers). Pictures cannot be redacted — the permission box says so.
5. **The AI suggests, the user clicks.** Actions are a fixed whitelist; each runs only on a button click and only *opens* things.
6. **No secret in the client.** The OpenRouter key lives only on the server. The exe bakes only public values.
7. **Honest failure.** No fabricated answers; backend errors say why; unreadable windows say so and how to fix.
8. **Free to run.** Every dependency has a free tier; the paid path is explicit (§12).

## 3. System context

```
 ┌────────────────────────── USER'S WINDOWS PC ──────────────────────────┐
 │  Consiz.exe (tray app, Python+Tk)                                       │
 │   triggers → capture / PC snapshot → redact → router → chat popup       │
 │   session: Credential Manager (refresh token) + ~/.consiz/session.json  │
 └───────────────┬───────────────────────────────┬────────────────────────┘
        browser  │ Google sign-in (PKCE,         │ HTTPS + Google ID token
        (once)   │ loopback 127.0.0.1)           ▼
                 ▼                      ┌──────────────────────┐   ┌──────────────┐
          Google OAuth                  │ Consiz server        │──▶│ OpenRouter   │
                                        │ FastAPI on Render    │   │ (free models │
                                        │ verify · limit ·     │   │  text+vision)│
                                        │ validate · proxy     │   └──────────────┘
                                        └─────────┬────────────┘
                                                  ▼
                                        Neon Postgres (usage counts)
```

**Trust boundaries:** (1) PC ↔ internet — everything crossing it is redacted/consented; (2) client ↔ server — the client is untrusted, the server re-validates everything; (3) server ↔ OpenRouter — only the server holds the key.

## 4. Client architecture

Shared logic lives in `consiz/` (never forked per platform); OS code lives in `consiz/platform/<os>/` behind facades (`trigger.py`, `capture.py`, `popup.py`, `sysinfo.py`).

| Layer | Modules | Notes |
|---|---|---|
| TRIGGER | `platform/win32/trigger.py`, `mousegate.py` | `WH_MOUSE_LL` hook + a pure click/drag state machine: a middle CLICK is Consiz's only in the chosen mode (middle / Ctrl+middle / keyboard-only) and outside excluded apps; nothing selected → the click is re-sent to the app; drags always go to the app. RegisterHotKey for Ctrl+Alt+S / +A / +D; pynput fallback |
| CAPTURE | `platform/win32/capture.py`, `readwin.py`, `sysinfo.py` | selection (UIA TextPattern → Ctrl+C fallback), window text (UIA), window picture (PrintWindow), PC snapshot (psutil + EnumWindows) |
| CLASSIFY / SECURITY | `classify.py`, `security.py` | rule-based type; redaction regexes |
| ROUTER | `router.py` | explain-mode dispatcher, all error states |
| DETERMINISTIC | `deterministic.py` | CSV/file/folder facts by code |
| PC MODE | `pc_mode.py`, `pc_actions.py` | snapshot → text, READ protocol, permission, picture fallback, action whitelist |
| LLM | `llm.py` | prompts (`_SYSTEM`, `_PC_*`), streaming, retry/cold-start, vision model choice |
| AUTH | `auth.py`, `platform/win32/login.py` | Google PKCE; refresh token in Credential Manager |
| UI | `platform/win32/popup.py`, `tray.py`, `onboarding.py`, `settings.py` | chat popup, minimize, chips/buttons, tray menu |
| CONFIG | `config.py`, `prefs.py`, `.env`, baked `_build_config.py` | tunables only here; real env wins over baked |
| LOGGING | `logs.py` | one rotating log file, secrets scrubbed, no user text; crash hooks for main/threads/Tk; diagnostics text for support |

**Threads:** UI loop on the main thread (Tk). Trigger → one worker per request (busy lock for Explain). Ask / PC questions run on their own worker and write only to the chat via `_dispatch`. The mouse-hook callback returns immediately.

### 4.1 Data contracts (same field names on every platform)
- `CapturedContext {source_app, capture_method, raw_content, paths[], note}` → `Result {title, content_type, source_app, body, stream, warnings[], error}` (Explain mode).
- **PC snapshot** `{taken_at, system{cpu,ram,disks,battery,uptime,process_count}, apps[{name,processes,ram_mb,cpu_percent}], windows[{title,app,foreground,minimized,hwnd}], startup[], network}` — produced by the platform collector, rendered to ≤ 6,500 chars by `pc_mode.render`.
- **Chat messages**: OpenAI-style `{role, content}`; `content` may be a list of `text` + `image_url` parts (user role only).

## 5. Key flows

### 5.1 Explain (select → answer)
`trigger → capture (selection/files) → classify → redact → router → [deterministic stats | LLM] → grounding check → popup (stream)`; follow-ups reuse `chat_messages(context, first answer, last 12 turns, question)`.

### 5.2 PC mode (ask → answer)
```
Ctrl+Alt+A ─▶ first-use consent ─▶ chat opens with starter questions
question ─▶ snapshot (≈2.5 s, cached 15 s) ─▶ redact titles ─▶ LLM call #1
   ├─ plain answer ──────────────────────────────────────────▶ stream to chat
   └─ "READ: 2" ─▶ permission box names the window(s) ─ No ─▶ honest line
                    │ Yes (remembered this session)
                    ├─ blocklist (password managers, bank/private titles) → never read
                    ├─ UIA text (≤6,000 chars/window, ≤12,000 total, ≤3 windows) → redact
                    ├─ text too thin (<250 chars: browsers, Electron) → picture of that window (≤2)
                    └─▶ LLM call #2 with <window_contents> (+pictures → vision model) ─▶ stream
answer may end with "ACTION: …" ─▶ validated against whitelist ─▶ button ─▶ runs only on click
```

### 5.3 Sign-in
Login window → browser to Google (PKCE, state, loopback port) → code → tokens; refresh token to Credential Manager; startup re-validates with Google (revoked ⇒ signed out; offline ⇒ stay); each request uses a fresh ID token (cached ~50 min). Expiry mid-use ⇒ `SignInRequired` ⇒ login window reopens.

### 5.4 Cold start (free host sleeps)
Startup pings `/health` in the background; requests wait up to 100 s and retry 3× on 502/503/504/connection errors before any text arrived.

## 6. Backend (`server/app.py`)

| Route | Purpose |
|---|---|
| `POST /v1/chat/completions` | the only AI door: verify → validate → limit → proxy stream |
| `GET /health` | `{ok, storage, db_ok}` (no secrets) |
| `GET /` · `/privacy` · `/google….html` | public pages required by Google's consent screen (+ Search Console file, exact name only) |

Per request, in order: **verify** Google ID token (signature, audience = our client id, expiry, verified email, optional `ALLOWED_EMAILS`) → **validate** input (roles; ≤30 messages; ≤40,000 text chars; pictures only in a *user* message, inline JPEG/PNG, ≤2, ≤1.8 M base64 chars each) → **limit** (50/day/user, 300/day/IP, 12/min/user) → **force** model, temperature, max_tokens ≤ 5,000, reasoning policy (client choices ignored; vision model chosen by the server when pictures are present) → **stream** from OpenRouter → **refund** the count if the provider failed.

Config (Render env): `OPENROUTER_API_KEY`, `GOOGLE_CLIENT_ID`, `DATABASE_URL` (Neon), `DAILY_LIMIT`, `IP_DAILY_LIMIT`, `RATE_PER_MIN`, `MAX_*`, `OPENROUTER_MODEL/FALLBACKS`, `VISION_MODEL/FALLBACKS`, `ALLOWED_EMAILS`, `CONTACT_EMAIL`.

## 7. Data model & retention

One table: `usage(sub TEXT, email TEXT, day TEXT, n INTEGER, PRIMARY KEY(sub, day))` (+ rows keyed `ip:<address>`) and `spend(day, sub, model, calls, tokens_in, tokens_out, cost_usd, unmetered, PRIMARY KEY(day, sub, model))` = what the AI really cost, read by `scripts/spend_report.py`. Nothing else is stored server-side: **no prompts, answers, window text or pictures are persisted**. Client keeps: `~/.consiz/session.json` (profile only), refresh token in Credential Manager, prefs, `consiz.log` (no secrets), optional `profile.md`. Deletion = email request (usage rows) + Sign out (client).

## 8. Privacy & permission matrix (what leaves the PC)

| Mode / step | Sent to server → AI | Permission |
|---|---|---|
| Explain | the selection (redacted) | the user's own action |
| PC question | snapshot text: app names, memory/CPU, window **titles**, disk, startup, network (redacted) | one-time consent box |
| Read inside a window | that window's text (redacted, capped) | per-window box, once per session |
| Picture fallback | a JPEG of that one window | same box, says "cannot be redacted" |
| Action button | nothing (opens a local screen) | the click |
| Always blocked | password managers, remote desktop, titles with password/bank/incognito/wallet/OTP | — |

## 9. Threat model (short)

| Threat | Control |
|---|---|
| Prompt injection via window text/title/picture | content wrapped as data; model can only emit READ/ACTION; ACTION validated against a whitelist; READ validated (numbers in range, ≤3); nothing runs without a click |
| Token theft | refresh token in Credential Manager; ID tokens short-lived; server verifies audience |
| Abusing our AI key | key only on server; limits per user/IP/min; size and picture caps; server picks model |
| Stolen/forged picture or remote image URL | only inline `data:image/jpeg|png`, user role, size-bounded |
| Phishing the consent page | Search Console ownership verified; app name matches |
| Closed beta bypass | `ALLOWED_EMAILS` enforced on every request |
| Privacy overreach | consent boxes, blocklist, "Looked at: …" line, no persistence |

## 10. Deployment & operations

- **Server:** Render free web service (`render.yaml`), deploy is *manual* (Deploy latest commit) — pushing does not redeploy. Sleeps after ~15 min idle (30–60 s wake).
- **DB:** Neon Postgres (free, no expiry). SQLite fallback only for local runs.
- **Client:** `python build_exe.py` → `dist/Consiz/Consiz.exe` (onedir, ~1 s start). Bakes `CONSIZ_SERVER_URL`, `GOOGLE_CLIENT_ID/SECRET` (public client values); never the AI key. Startup shortcut points at the built exe.
- **Observability:** `/health`; client log `~/.consiz/consiz.log`; Render logs. No analytics yet.
- **Release gate:** `python -m pytest tests -q` (117 tests: 115 pass, 2 skip when the optional voice packages are absent) and `python scripts/release_check.py` — see `RELEASE_READINESS.md`.

## 11. Quality, limits and known gaps (continue the KI list)

| ID | Gap | Impact / plan |
|---|---|---|
| KI-18 | Chrome/Brave/Edge/Electron hide page text from UI Automation | picture fallback built; text route needs the user to enable accessibility |
| KI-19 | Minimized windows cannot be photographed | **fixed 2026-10-07**: AI is told to end with `ACTION: focus_window n` → "Switch to" button, then ask again |
| KI-20 | Chat history keeps only answer text, not the window text/picture read earlier | **fixed 2026-10-07**: reads and pictures cached 5 min per window, so follow-ups do not re-read or re-photograph |
| KI-21 | No "draft a message / tell X" intent in PC mode | **fixed 2026-10-07**: prompt writes a ready-to-send `Draft:`; user copies it; nothing is sent |
| KI-22 | Model may echo the internal `READ: n` line in a normal answer | **fixed 2026-10-07**: any line mentioning `READ: <n>` is stripped before display |
| KI-23 | Free text/vision models are rate-limited or overloaded; **one shared OpenRouter key allows only 50 free requests/day** (1,000 with 10 credits) | server self-heals its model list, uses measured-fastest defaults and says clearly when the daily allowance is gone; **add credits before launch** (§12) |
| KI-24 | Render free sleeps; first answer slow | wake ping + long timeout; paid always-on plan removes it |
| KI-25 | PC mode and chat UI are Windows-only; macOS lacks them | port `sysinfo` + popup chat; shared modules already portable |

Failure behaviour: server unreachable → friendly retry text; 401 → sign in again; 429 → daily/minute limit message; empty answer → explicit warning; unreadable window → says so + how to fix.

## 12. Cost, scale, and the paid path

- **Today: ₹0.** Render free + Neon free + OpenRouter free models + Google OAuth. Per-user cap 50 answers/day keeps free-model usage polite.
- **First paid steps (in order):** (1) paid OpenRouter credit → reliable models, higher limits; (2) Render Starter (~$7/mo) → no sleep; (3) per-plan limits and billing (`BILLING` layer) — free/₹289/₹499 as already planned; (4) phone sign-in only when revenue covers SMS.
- **Capacity guide:** a request is ≈ 2–6 k tokens (PC snapshot ≈ 2.7 k chars); picture requests cost more and use the slower vision model. The limits in §6 are the lever; DB write per request is the only server state.

## 13. Roadmap (by layer) and decisions still open

1. **Hardening (now):** fix KI-19/21/22; installer + auto-update (`WIN-011`); app compatibility matrix (`WIN-010`); full checklist on a clean Windows laptop (`WIN-012`); teammate verification of `WIN-014…021`.
2. **PC mode depth:** session-cached window reads, draft-and-copy, "Switch to it", more safe actions, optional background watcher (alerts) — opt-in only.
3. **Reach:** macOS port of PC mode + chat; Android/iOS thin clients over the same server (JSON contract already shared).
4. **Business:** plans, billing, usage analytics, onboarding for non-technical users.

**Decisions needed from the team:**
- Default AI: stay on free models or fund a paid default? (quality vs ₹)
- Is picture fallback on by default, or opt-in per user? (privacy vs convenience)
- Ship `ALLOWED_EMAILS` closed beta first, or open sign-up now?
- Phone sign-in: which SMS provider, and when?
- Open-source the client core (distribution) — yes/no/when?

## 14. Changes since this was first written (2026-10-08, WIN-025 … WIN-030)

| Area | What exists now | Where |
|---|---|---|
| Real cost | server records tokens/cost per user/day/model (`spend` table); `scripts/spend_report.py` prices real usage on paid models | `server/app.py`, `scripts/spend_report.py` |
| Stop / cancel | per-request `CancelToken`; Send turns into Stop; closing the window / New chat cancels; the HTTP stream is closed so the server stops paying; errors are typed (`Cancelled`, `LLMUnavailable`, `UpdateRequired`) | `consiz/llm.py`, `popup.py` |
| Pause | tray Pause/Resume, hotkeys released while paused, auto-pause for full-screen apps (Windows' own busy signal) | `consiz/pause.py`, `trigger.py`, `fullscreen.py` |
| Fallback chain | cloud → offline Ollama **only** for unreachable/overloaded errors, never after text started, never for limits/sign-in/426; visible note | `llm._with_offline_fallback` |
| Big files | first 100,000 rows only (stated in the answer); workbooks > 150 MB and pasted > 20 M chars refused | `deterministic.analyze_csv` |
| DPI / monitors | system-DPI aware; `px()` for fixed sizes; popup placed in the work area of the monitor under the cursor | `platform/win32/dpi.py` |
| Settings | five tabs, changes apply at once; shortcuts validated and re-registered live; clear local data keeps `profile.md` | `platform/win32/settings.py`, `hotkeys.py`, `localdata.py` |
| Updates | `GET /version` (LATEST_VERSION, MIN_VERSION, DOWNLOAD_URL from server settings); app asks daily, shows a tray "Download" item, never installs by itself; `MIN_VERSION` makes the server refuse old apps with HTTP 426 | `consiz/updater.py`, `server/app.py` |
| Server concurrency | async answer route (httpx), Google keys cached, DB wait-not-fail, idle-memory clean-up; `scripts/load_test.py` measures it with a fake AI (no cost) | `server/app.py`, `scripts/load_test.py` |
| Installer | Inno Setup script (per-user, no admin, same autostart key as the tray) + build script. **Never built yet; unsigned** | `installer/consiz.iss`, `scripts/build_installer.py` |

Still open from §13: macOS port of PC mode/chat, Android/iOS clients, plans + billing, background watcher and confirm-first actions (T-12: conflicts with the non-goal "killing processes" above, so it needs a product decision), teammate verification, installer build + signing, compatibility matrix (WIN-010), Render in Singapore.

