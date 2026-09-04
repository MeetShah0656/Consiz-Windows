# REALITY UPDATE — What Is Actually Built (31 Aug 2026)
Read this before any other file. Every other document was written before one line of code existed. This is the current truth, including what we got wrong.

---

## What exists today (working, tested on macOS)

- **Phase 1 + Phase 2 are BUILT.** Python app: select anything → middle mouse button → frosted-glass popup next to the cursor with the answer.
- Trigger: middle-click, intercepted at the OS level and swallowed (the app under the cursor never sees it). Keyboard fallback `ctrl+alt+s`.
- Capture: Accessibility API → clipboard fallback (⌘C simulate + restore). Finder files/folders/multi-select via file URLs. Address-bar false-capture guarded.
- Intent detection: the model decides ANSWER / DEFINE / EXPLAIN / SUMMARY / CODE / MATH and formats accordingly (Q:/A: pairs for questions).
- Deterministic engine: CSV/XLSX profiled and computed by pandas — sums, means, date ranges, % shares, per-entity breakdown (e.g. attendance lowest/highest). The LLM never does arithmetic. Grounding check flags any number the narrative invents.
- Files: pdf/docx/xlsx/rtf/txt read (first ~3k chars) → metadata + AI overview. Folders: dates, counts, sizes, previews → AI overview.
- Security: credential redaction before the model; prompt-injection defense tested (selected "ignore instructions" text gets summarized, not obeyed).
- Popup: dark glass, resizable via corner grip (size remembered), streams text answers, holds files/data results behind "Processing…" then reveals at once, Copy button, click-outside dismiss, friendly error lines.
- All answers in short bullets, simple language. 20 unit tests passing.

## Decisions that override the old documents

| Old documents said | Reality |
|---|---|
| Modified mouse with extra button (doc 01) | Dead. Software-only, user's existing middle button. |
| "Direct button interception is unsafe, use hotkey relay" (doc 03 §3) | **Partly wrong.** Middle-button interception via macOS event tap works reliably — built and tested. The caveat was only ever true for branded-mouse *side* buttons. |
| Cloud small-tier (Haiku/GPT-4o-mini), ~$0.003/query (doc 03 §4) | Using OpenRouter **free** models (minimax-m2.7 primary). BLUNT: free tier is flaky — upstream 429s, one "fallback" answered as a content-safety classifier. A paid product cannot run on free models. Budget the paid API (~₹0.02–0.10/query); the doc's cost math still holds. |
| Stripe Billing (docs 02, 03 §5) | For India: UPI via Razorpay/Cashfree first. Stripe only for global. Not built yet. |
| $6–10/month pricing (docs 03, 04) | ₹289/month (limited daily uses) and ₹499/month (high/unlimited), 14-day trial (30 was floated — too long), annual ~₹1,999 to add. |
| "Lead with Windows, build Windows first" (docs 09, 12) | **We did the opposite** — built Mac first because the dev machine is a Mac. Own it: Windows is now the single most important unbuilt thing. ~70% of code is cross-platform; 3 files need Windows twins. |
| Target: broad "knowledge workers" | India-first, ranked: exam aspirants → CA/GST staff → HR/back-office → students → SMB/tender teams. Mobile: Android (`ACTION_PROCESS_TEXT`) before iOS; iOS only as share-sheet + Dynamic Island companion — global selection capture is impossible on iOS. |

## What is NOT built (be honest when asked)

- Windows version. Billing. Onboarding. Packaged .app installer. CSV write-back (doc 10 called it "the wedge" — still zero code). Follow-up box / draft-reply / insert-into-app (WhatsApp/LinkedIn idea — agreed design: second lighter panel, "you click the field, we type"; it types, never sends). Hindi/regional output toggle. Usage metering.

## Blunt self-criticism (fix these, don't defend them)

1. **Zero real users.** Everything about "habit" is theory until 3 strangers use it daily for a week.
2. **The product runs on free-tier AI.** It failed mid-demo twice during development. This WILL embarrass us in a live pitch. Move trials to paid API before showing anyone.
3. **Mac-only contradicts our own strategy docs** and our own target users (Windows India). Every week without Windows is a week the thesis is untested.
4. **118KB of business documents preceded the first line of code.** The docs themselves warned about this. It happened anyway. Ship > write.
5. **The demo reel is a script, not a video.** The 5-second CSV demo doesn't exist as a file anyone can watch.
6. **Nobody has validated ₹289.** Not one person has been asked to pay. Willingness-to-pay is assumed, not measured.
7. **Latency honesty:** free-tier answers took 4–16 s in testing. The spec's <3 s target is only met on good days. Users notice.
