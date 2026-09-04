# As Conciz — Technical Feasibility Reality Check

> **REALITY CHECK (31 Aug 2026):** §3.1 ('direct capture doesn't reliably work') was over-broad — middle-button interception via event tap is built and reliable; the caveat only applies to branded side buttons. §4 model advice superseded: currently on OpenRouter FREE models — which are flaky (429s, one classifier-instead-of-chat incident). BLUNT: free models are for development only; the paid-tier cost math here (~$0.06–0.45/user/month) is still correct and is the plan. §5 billing: Stripe→Razorpay/UPI for India.
Grounded in verified sources (August 2026). Every claim below is checked against real documentation, real vendor behavior, or real pricing — not assumption.

---

## 1. Is it possible? — Yes, with one major scope correction

The core loop (select content → trigger → capture → AI result) is technically achievable on Windows and macOS today using existing, documented OS APIs. The corrected part is **how the trigger is captured** — see §3. Nothing in this product requires new invention; it requires correct integration of existing, well-documented mechanisms.

---

## 2. Content Capture — What actually works, verified

### 2.1 Windows
- **Microsoft UI Automation (UIA)** is the real, documented, currently-supported API for reading UI content — including selected text — from other running applications. It replaced the older MSAA (Active Accessibility) API and is what screen readers and RPA tools use today.
- **Reality check:** UIA works well for native Win32/WPF/UWP apps. It does **not** work uniformly for Electron apps (many popular apps — Slack, VS Code, Discord) or for canvas-rendered content (e.g., some web app UIs, PDF viewers using custom renderers). Coverage is good, not universal.

### 2.2 macOS
- **Accessibility API (`AXUIElement`)** is the real, documented API — `AXUIElementCreateSystemWide()` + `kAXFocusedUIElementAttribute` + `kAXSelectedTextRangeAttribute` retrieves the selected text of the frontmost focused element, verified against Apple's own accessibility documentation and multiple independent working implementations.
- **Reality check:** requires the user to explicitly grant Accessibility permission in System Settings — this is a hard OS-level gate, not optional, and will show a permission prompt on first use. Sandboxed apps (App Store distribution) have restricted access to this API — **if As Conciz is distributed via the Mac App Store, this feature may not work reliably; direct distribution (notarized .dmg) is the realistic path.** There are also known, documented edge-case bugs (e.g., Electron apps mis-reporting selection ranges when a line starts with whitespace).

### 2.3 The honest fallback (and what real shipping products actually do)
Independent working implementations of "get selected text from any app" (verified: a cross-platform open-source library used in production) confirm the real-world approach: **use the Accessibility/UIA API first, and if it fails or the app doesn't support it, simulate Ctrl+C / Cmd+C and read the clipboard.** This is not a hack — it's the standard, documented fallback used across the industry, and it should be designed in from day one, not treated as an edge case. It does mean As Conciz will briefly touch the user's clipboard on unsupported apps, which is a privacy/UX detail worth disclosing to users (restore prior clipboard contents after reading).

**Verdict: content capture is solid, well-precedented engineering — not a research problem. Budget for the clipboard-fallback path as core scope, not a stretch goal.**

---

## 3. The Trigger — Corrected Scope (this changes the plan)

Your proposed pivot — assigning the action to an existing button on the user's own mouse (DPI button, side button) instead of shipping new hardware — is the right direction, but the mechanism needs correcting based on how mouse vendor software actually behaves:

### 3.1 What does NOT reliably work
Directly intercepting raw button-press events at the driver/HID level for a **branded gaming mouse** (Logitech, Razer, Corsair, SteelSeries) is unreliable, because the vendor's own software (G HUB, Synapse, iCUE) sits between the hardware and the OS and can consume/remap the button before any third-party app sees it. Verified reports (including vendor support forums) confirm side-button behavior can be captured or altered by the vendor driver, and third-party apps cannot assume they'll see the raw event. Building this as "we hook the button directly" is not a safe engineering assumption across the branded-mouse install base.

### 3.2 What DOES reliably work (this is the real design)
1. **Hotkey-based trigger (recommended default):** the user opens their mouse's existing software (Logi Options+/G HUB, Razer Synapse, or a generic tool like X-Mouse Button Control for unbranded mice) — a step they already know how to do — and assigns a specific keyboard shortcut (e.g. a rarely-used combination) to their chosen spare button. As Conciz's desktop app then registers a **global hotkey listener** for that exact combination. This is standard, low-risk, cross-vendor, and requires zero driver-level work.
2. **Direct HID capture as a bonus path for unbranded/generic mice:** for mice with no vendor software running (most non-gaming mice), a generic input hook (Windows Raw Input API / macOS IOKit HID Manager) can capture an unused button directly, with a one-time onboarding flow to detect and assign it. This is a genuine "nice to have" for a cleaner setup experience on generic hardware, not a requirement for MVP.

**Verdict: the hotkey-based trigger, layered on the button the user already assigned via their own mouse software, is the technically honest MVP mechanism. It is less "magical" than direct button capture but is dramatically lower engineering risk and works across every mouse brand on day one — recommend this be the stated mechanism in all documentation, including the YC application, rather than implying direct button interception.**

---

## 4. What Model Size Should You Use? (grounded in real August 2026 pricing)

### 4.1 Recommendation: small/fast-tier models for the default path, mid-tier as an escalation, nothing frontier-tier by default

| Task | Recommended tier | Why |
|---|---|---|
| Text/paragraph summarization | Small (Claude Haiku 4.5 / GPT-4o mini class) | Anthropic's own positioning for Haiku 4.5 is explicitly "classification, extraction, routing" and high-volume, latency-sensitive workloads — this is exactly the As Conciz use case |
| Simple Q&A on selected text | Small tier, same as above | Same reasoning — bounded context, low complexity |
| File/folder metadata summarization | Deterministic code, no LLM needed for the data itself; small-tier model only for the narrative wrapper | Per the engineering spec, this should not touch AI reasoning for the factual parts at all |
| CSV/numerical narrative | Deterministic computation (no LLM) + small-tier model for the plain-English explanation | Same principle — never let the LLM do arithmetic |
| Long/complex documents, multi-step reasoning, ambiguous queries | Mid tier (Claude Sonnet 5 / GPT-5.2 class) as an escalation path, not the default | Reserve for cases the small model flags low-confidence on |
| Anything Opus/Fable/o1-class | **Not recommended for this product** | Priced 5–10x above the mid tier; a per-selection consumer summarization tool has no task in current scope that needs frontier-tier reasoning |

### 4.2 Real cost math (not estimated — computed from published August 2026 rates)

Assume a realistic query: ~1,500 input tokens (selected content + prompt) + ~300 output tokens (result).

| Model | Input rate | Output rate | Cost per query |
|---|---|---|---|
| GPT-4o mini | $0.15/MTok | $0.60/MTok | ~$0.0004 |
| Claude Haiku 4.5 | $1.00/MTok | $5.00/MTok | ~$0.003 |
| Claude Sonnet 5 (introductory) | $2.00/MTok | $10.00/MTok | ~$0.006 |
| Claude Opus 4.8 | $5.00/MTok | $25.00/MTok | ~$0.015 |

At an assumed 5 uses/day (≈150/month) per active subscriber:
- GPT-4o-mini-class: **~$0.06/user/month**
- Claude Haiku-class: **~$0.45/user/month**
- Even Sonnet-class as a fallback for ~10% of queries adds only a few cents

**This directly changes the earlier risk flag in the business-analysis report.** AI inference cost at a small-model tier is a small, controllable fraction of an $8/month subscription price — nothing like the catastrophic cost dynamic reported for compute-heavy generative products (e.g., video generation). The prior report's caution about inference cost as a "high-sensitivity variable" was correct to flag as unknown at the time, but with model tier now specified, the actual number is low and the unit economics are workable, provided the product resists the temptation to default to a frontier-tier model.

### 4.3 Local/on-device option (mentioned in the original vision, worth a reality check)
Running a genuinely capable summarization model fully on-device (no cloud call) is possible but adds real engineering cost: model packaging, hardware-dependent performance (older/low-RAM machines will struggle), and update/versioning complexity. **Recommend this be an explicit Phase 2+ item, not MVP** — MVP should use cloud small-tier models with the privacy controls already specified (local sensitivity classification before anything is transmitted), which gets most of the privacy benefit without the on-device engineering cost.

---

## 5. Monthly Subscription / Billing — What to actually build

### 5.1 Recommended architecture (standard, not custom)
- **Stripe Billing** (Stripe Checkout for signup + Stripe Customer Portal for self-serve plan management + Stripe webhooks for entitlement sync) is the standard, low-risk choice for this kind of desktop-app subscription — well-documented, handles card failures/dunning/proration/tax automatically, and avoids building custom payment infrastructure.
- **Entitlement flow:** desktop app authenticates the user (email/OAuth) → backend checks subscription status via a cached webhook-driven database (subscription active/inactive/past_due), not a live Stripe API call on every use, to avoid latency and rate-limit risk on the hot path.
- **Usage metering (optional, Phase 2):** if a future tier caps or meters queries, Stripe's metered billing / usage records API supports this without custom billing logic — not needed for a flat-rate MVP tier.
- **Free tier / trial:** technically trivial to implement via Stripe's trial-period support on a Checkout subscription; the harder problem is abuse prevention (one device fingerprint or account per trial), which needs its own basic anti-abuse logic (not Stripe's responsibility).

### 5.2 Reality check on this part
This is the least risky part of the entire project. Subscription billing for a desktop app is a solved, extremely well-documented problem — there is no technical uncertainty here, unlike the OS capture and trigger mechanisms above.

---

## 6. Summary Reality Check (no fabrication, direct answers)

- **Is it possible?** Yes — every core mechanism (content capture, trigger, AI processing, billing) maps to real, documented, currently-working technology. Nothing requires a research breakthrough.
- **What was wrong in the original plan?** Direct hardware/button-level interception of a branded gaming mouse's side buttons is not a reliable engineering assumption — the hotkey-relay approach (§3.2) is the corrected, honest mechanism.
- **What model size?** Small/fast tier (Haiku 4.5 / GPT-4o mini class) for the large majority of queries, with a mid-tier escalation path for complex cases. Frontier-tier models are unnecessary cost for this product's task profile.
- **What's the actual per-user AI cost?** Roughly $0.06–$0.45/month per active user at realistic usage, depending on model choice — a small, controllable fraction of a $6–10/month subscription price.
- **What's genuinely hard?** Cross-application content-capture reliability (Electron apps, sandboxed apps, canvas-rendered content) is the real, ongoing engineering surface — not a one-time solved problem. Budget QA time against a real application compatibility matrix, not just the happy path.
- **What's not hard?** Billing. Use Stripe Billing as designed; do not build custom subscription infrastructure.
