# Consiz — Release Readiness ("is it publication level?")
Updated 2026-10-07. Companion to `SYSTEM_DESIGN.md`.

## The idea (for someone who builds by prompting)

You cannot prompt your way to quality — you **gate** it. A feature is not done when the AI says "done". It is done when:
1. **A check ran and printed PASS** (`python scripts/release_check.py`), and
2. **A human who is not the builder signed it off** (the team's `verified_by` rule).

So the working loop is always: *pick one gate → ask Claude to make it pass → read the PASS/FAIL table yourself → a teammate verifies on a real PC → only then push/release.*

**Paste this at the start of any request:**
> Work on gate "<name>" from docs/RELEASE_READINESS.md. Don't tell me it works — show me the output of `python scripts/release_check.py --skip-build` (and the real-exe test if it touches the app) before and after. Commit locally; don't push until I say.

## The one command

```
python scripts/release_check.py --skip-build   # 1 min: tests, secrets, docs, live server
python scripts/release_check.py                # + builds the exe and checks it starts (~5 min)
```
It checks: unit tests · no secrets in git · required docs · checkpoint rules · exe builds / size / starts / AI key not inside · live server health, Postgres, privacy pages, anonymous access refused · git state. Exit code 1 = NOT READY.

## The 10 gates (what "production level" means for Consiz)

| # | Gate | Automated by | Status today | To pass |
|---|---|---|---|---|
| 1 | **Correct** — features do what they claim | `pytest` (115 pass, 2 skip) | PASS | keep adding a test with every fix |
| 2 | **Reliable** — survives slow/failed AI, sleeping server, expired login | tests + retries built | PARTIAL | paid AI default (free models get overloaded, KI-23); 24 h soak test with 5 users |
| 3 | **Secure** — no secrets out, abuse limited, content can't hijack the AI | secret scan, server tests, threat table in design doc | PASS (self-checked) | independent security review of the diff before launch (`/security-review`); rotate the Exa key |
| 4 | **Private & legal** — consent, policy, Google verification | privacy page check | PARTIAL | Terms of Service page; data-deletion process; Google consent screen published ✔; privacy page must be redeployed (server older than app) |
| 5 | **Installable** — normal people can install, update, remove it | `scripts/build_installer.py` (needs Inno Setup) | PARTIAL | built: installer script, update check, `MIN_VERSION` switch. To pass: build the installer once and test install / update-in-place / uninstall on a clean PC; code-signing certificate (or users see "Windows protected your PC"); silent auto-install only after signing |
| 6 | **Compatible** — works in the apps and PCs people really use | unit tests for placement maths | PARTIAL | built: DPI awareness + multi-monitor placement (checked by eye at 125%, 1 monitor). To pass: `WIN-010` matrix: Chrome, Edge, Brave, Word, Excel, Notepad, Tally, WhatsApp; Windows 10 + 11; 100%/150%/175% scaling; 2 monitors; non-admin user |
| 7 | **Observable & supportable** — you learn about problems | `/health`, local log | PARTIAL | opt-in crash/error report, in-app "Send feedback", support email + short FAQ page |
| 8 | **Fast & light** | exe start ≈ 1 s ✔, snapshot ≈ 2.5 s ✔ | PARTIAL | measure idle memory/CPU over 8 h; set budgets (< 150 MB idle) |
| 9 | **Polished** — one name, no dead ends, clear errors | manual | PARTIAL | one product name everywhere (code/UI mix "Conciz" and "Consiz"); keyboard/accessibility pass; every error has a next step |
| 10 | **Verified by humans** | CSV rule check | FAIL | teammate signs `verified_by` on `WIN-001…021` after testing on their own PC; 5–10 real beta users for 1 week |

**Order that gets you to a public launch fastest:** 10 (get verification started now, it takes calendar time) → 5 (installer + signing decision) → 6 (compat matrix) → 2 (paid AI) → 4 (Terms) → 7 → 9 → 8.

## Rules that keep quality from sliding back
- No push without a green `release_check` (warnings explained in the commit message).
- Every bug fix adds a test that fails without the fix.
- Anything that sends data off the PC changes `server/app.py` privacy text **and** the consent box in the same commit.
- A checkpoint is `done` only with a teammate's name in `verified_by` (`team/CHECKPOINTS.md` rule 2).
- Server changes need a manual Render deploy; run `release_check` afterwards (it reads the live server).

## Decisions only the team can make (cost / policy)
1. Code-signing certificate: buy (≈ ₹5–20k/year, removes the SmartScreen warning) or launch unsigned with install instructions?
2. Paid AI credit for a reliable default model (how much per month?).
3. Open-source the client core or keep closed?
4. Closed beta first (`ALLOWED_EMAILS`) or open sign-up?
5. Phone sign-in: skip until revenue (needs paid SMS).
