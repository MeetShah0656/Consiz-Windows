# As Conciz — Execution Plan for the Team

> **REALITY CHECK (31 Aug 2026):** Written for a team that doesn't exist — one founder + AI tooling built the whole MVP. The hotkey-relay trigger design (§3) was superseded: direct middle-click interception works (see 13). Stripe checklist (§6) is wrong for India-first — UPI/Razorpay first. The compatibility matrix (§5) is the one part to actively maintain; browser=clipboard-fallback confirmed, Electron untested.
### Revised for the software-integration pivot (no new hardware). Distribute to all engineers before kickoff.

This document supersedes the hardware sections of the original technical documentation. Read alongside `as-conciz-feasibility-reality-check.md` for the evidence behind each decision below — every mechanism here has been verified against real OS documentation and vendor behavior, not assumed.

---

## 1. What We're Building (corrected scope)

A desktop application (Windows + macOS) that:
1. Listens for a user-configured global hotkey (mapped by the user, in their own mouse software, to a spare mouse button — see §3).
2. On trigger, captures whatever content is currently selected on the user's screen.
3. Classifies the content type and routes it to the right processing pipeline.
4. Returns a result (summary / metadata / computed answer / direct answer) in a lightweight overlay.
5. Is distributed as a monthly subscription via Stripe Billing.

**No custom hardware. No modified mouse. No manufacturing, inventory, or shipping.** This is a pure software company.

---

## 2. Architecture (updated)

```
User's existing mouse (any brand)
        │  (button already mapped to a hotkey via the user's own mouse software)
        ▼
Global Hotkey Listener (As Conciz desktop app)
        │
Content Capture Layer
   — Windows: UI Automation API, clipboard (Ctrl+C) fallback
   — macOS: Accessibility API (AXUIElement), clipboard (Cmd+C) fallback
        │
Context Classification Engine  →  content_type + confidence
        │
Processing Router
        │
   ┌────┴─────────────────────────┐
   │                               │
Deterministic Processing      AI Reasoning Module
(CSV math, file/folder         (small-tier model default,
 metadata — never LLM)          mid-tier escalation path)
   │                               │
   └──────────┬────────────────────┘
              ▼
      Verification/Grounding Layer
              ▼
        Result Overlay UI
              ▼
   Privacy/Security + Error Handling (cross-cutting, all stages)
              ▼
        Telemetry (metadata only)
```

Full component-level spec (capture layer contracts, classification thresholds, error-state table, API contracts) carries over unchanged from the original engineering documentation — only the trigger mechanism and hardware sections are replaced by this document.

---

## 3. The Trigger — Onboarding Flow (build this first, it's the core UX)

1. On first launch, As Conciz detects the user's mouse (best-effort, informational only — no dependency on detection succeeding).
2. Onboarding screen instructs: *"Open your mouse's software (Logi Options+, G HUB, Razer Synapse, or similar) and assign one of your spare buttons to this keyboard shortcut: `[generated combination]`. Don't have extra buttons or software? Use X-Mouse Button Control (link) — free, works with any mouse."*
3. As Conciz registers a system-wide hotkey listener for that combination (`RegisterHotKey` on Windows, `CGEventTap`/`NSEvent` global monitor on macOS).
4. A "test your trigger" step in onboarding confirms the hotkey fires before the user leaves setup — this is the single most important UX moment and should have zero ambiguity if it fails (clear "not detected, try again" state, not silence).

This is genuinely simple to build — it is a global hotkey listener, a well-trodden pattern on both platforms. Do not build custom HID-level button interception for MVP; see feasibility doc §3.1 for why that's the wrong bet for branded mice.

---

## 4. Team Workstreams

| Workstream | Owner responsibility | Key deliverable |
|---|---|---|
| Capture & Trigger | Desktop platform engineer(s) | Hotkey listener + UIA/Accessibility capture + clipboard fallback, both OSes |
| Classification & Routing | Backend/ML engineer | Classifier (rule-based + confidence scoring is sufficient for MVP — no need for a trained model at this stage) |
| AI Reasoning | Backend engineer | Model routing logic (small-tier default, mid-tier escalation), prompt templates per content type, verification/grounding checks |
| Deterministic Processing | Backend engineer | CSV/numeric computation library, file/folder metadata extraction — must never depend on the LLM for factual/numeric output |
| Result UI | Frontend/desktop UI engineer | Lightweight overlay, copy-to-clipboard, error states |
| Billing | Backend engineer | Stripe Billing integration (Checkout, Customer Portal, webhook-driven entitlement cache) |
| Privacy/Security | Cross-cutting, reviewed by all | Local sensitivity classification, credential redaction, clipboard-restore after fallback capture, sensitivity-based cloud routing gate |
| QA | Dedicated or rotating | Application compatibility matrix (see §5) — this is the highest-uncertainty surface in the whole project |

---

## 5. Application Compatibility Matrix (build and maintain this — do not skip)

Per the feasibility findings, content-capture reliability varies by how an app renders its UI. Track this explicitly rather than assuming uniform coverage:

| App category | Expected capture method | Risk level |
|---|---|---|
| Native OS apps (Explorer/Finder, Notepad, TextEdit) | UIA / Accessibility API, direct | Low |
| Native browsers (Chrome, Edge, Safari, Firefox) | Accessibility API works for page text in most cases; companion browser extension recommended for reliable DOM-level paragraph/page capture | Medium — build the extension, don't rely on Accessibility API alone for browser content |
| Electron apps (Slack, VS Code, Discord, Notion desktop) | Clipboard fallback (simulate Ctrl+C/Cmd+C) — do not assume UIA/Accessibility works | Medium-High |
| Sandboxed/Mac App Store apps | Accessibility API access may be restricted | High — flag as a known limitation, not a bug to "fix" |
| PDF viewers, canvas-rendered UIs | Likely requires clipboard fallback | Medium-High |
| CSV/spreadsheet apps (Excel, Numbers, Google Sheets in browser) | File-path-based read for local files; clipboard fallback for in-app cell selection | Medium |

This matrix should be a living QA artifact, expanded during Phase 5 (per the original engineering roadmap's reliability/security phase) with real test results, not assumptions.

---

## 6. Billing Implementation Checklist

1. Stripe account + product/price objects for the monthly subscription tier(s).
2. Stripe Checkout for signup flow (embedded or hosted — hosted is faster to ship for MVP).
3. Webhook endpoint (`checkout.session.completed`, `customer.subscription.updated`, `customer.subscription.deleted`, `invoice.payment_failed`) → updates a local entitlement cache/database.
4. Desktop app checks the local entitlement cache (synced periodically + on app launch), not live Stripe calls on every trigger press — keeps the hot path fast and avoids rate limits.
5. Stripe Customer Portal linked from in-app settings for self-serve cancel/upgrade/payment-method update — do not build this UI yourselves.
6. Trial-abuse mitigation: basic device/account-level check before granting a free trial (Stripe does not handle this for you).

---

## 7. What Changed From the Original Engineering Spec (summary for the team)

- **Removed:** all custom hardware sections (mouse modification, firmware, HID debounce spec, hardware BOM).
- **Replaced:** the trigger mechanism is now a global hotkey listener, fed by a button the user maps themselves via their existing mouse software — not a new physical device.
- **Unchanged:** context capture pipeline, classification engine, processing router, deterministic numerical module, AI reasoning module, verification layer, result UI, privacy/security controls, error handling — the software architecture from the original spec stands.
- **Added:** application compatibility matrix as an explicit, tracked QA artifact; Stripe Billing integration; specific model-tier guidance (§4 of the feasibility doc).
- **Net effect on timeline:** removing hardware development (originally weeks 5–8 and part of weeks 21–28 in the phased roadmap) shortens the path to a working MVP substantially — the team can now realistically target a demoable product before a YC application deadline.
