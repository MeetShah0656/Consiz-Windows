# As Conciz — Full Contents Index

> **REALITY CHECK (31 Aug 2026):** This index predates files 12 and 13. Read 13 FIRST — it corrects every file below with what is actually built.

Every file, what's inside it, and the key facts it holds. Use this to find something without opening all eleven files.

**Folder:** `As-Conciz/` — 11 files, 128 KB total.

---

## 00 — START HERE
`00-START-HERE-What-Each-File-Contains.md`

Quick table of all files and who each is for. Read first. This file (11) is the longer version.

---

## 01 — Engineering Spec
`01-Engineering-Spec-System-Architecture-and-Testing.md` · 15 KB

The original technical documentation for engineers.

- 11 system components and what each does
- Data flow from trigger to result
- Content capture layer, classification engine, processing router
- Deterministic numerical module (never let the LLM do arithmetic)
- AI reasoning module, verification layer, result UI
- Error state table — 7 defined failure modes, each with required behaviour
- API contracts between modules
- Non-functional requirements: latency targets, platform matrix, security
- Testing procedures: unit, integration, security stress, beta validation
- Explicit non-goals to prevent scope creep

**Note:** hardware sections here are superseded by file 02.

---

## 02 — Team Execution Plan
`02-Team-Execution-Plan-Who-Builds-What.md` · 8 KB

Revised architecture after dropping hardware. Give this to the whole team.

- No custom mouse. Pure software company.
- The hotkey trigger design — user maps a spare mouse button to a shortcut in their own mouse software, we listen for that shortcut
- Onboarding flow (build this first — it's the core UX moment)
- Workstream table: who owns capture, classification, AI, deterministic processing, UI, billing, privacy, QA
- Application compatibility matrix — which apps work with which capture method
- Stripe billing checklist, 6 steps
- What changed from file 01 and why

---

## 03 — Feasibility
`03-Feasibility-Can-We-Build-It-Model-Size-and-Costs.md` · 12 KB

Reality check. Can this be built, with what, at what cost.

- **Windows:** UI Automation API. Works for native apps, not uniformly for Electron.
- **macOS:** Accessibility API (AXUIElement). Needs user permission. Mac App Store distribution likely won't work — ship a notarized .dmg.
- **Clipboard fallback is core scope, not an edge case.** Every real product does this.
- **Direct mouse button interception fails** on branded gaming mice — G HUB, Synapse, iCUE intercept first. Hotkey relay is the correct approach.
- **Model tier:** small/fast (Claude Haiku 4.5 / GPT-4o mini class) for most queries, mid-tier escalation for complex ones, never frontier-tier by default
- **Real cost per user per month:** $0.06 (GPT-4o mini) to $0.45 (Haiku) at 5 uses/day
- Stripe Billing architecture — the easiest part of the project
- What's genuinely hard: cross-app capture reliability

---

## 04 — Business Analysis
`04-Business-Analysis-Market-Size-and-Financials.md` · 15 KB

Market sizing, competitive landscape, financial scenarios. No recommendations — findings only.

- Three market categories we span: AI wearables ($9.6B–$69B, estimates vary wildly), AI copilot software (heading to $196.8B by 2036), computer peripherals (~$3.85B)
- Humane AI Pin: raised $230M, sold to HP for $116M, discontinued Feb 2025
- Rabbit R1: 100K units at $199, mass returns, still operating but strained
- Copilot: 20M paid seats, ~36% actually used
- Illustrative Year-1 revenue scenarios: $196K conservative / $1.12M base / $3.81M optimistic
- AI inference flagged as the key cost variable — **since resolved in file 03**

---

## 05 — Competitors: Screen-Aware AI
`05-Competitors-Screen-Aware-Desktop-AI.md` · 8 KB

**Read before pitching anyone.** The category we're actually in.

- **We are not first.** Multiple funded companies already ship this.
- **Highlight AI** — $40M Series A March 2026, $73M+ total, Mac + PC, always-on
- **HeyClicky** — YC Spring 2026, ~$10.1M, cursor-adjacent, voice-first, Mac only
- **Raycast** — $8/month, keyboard shortcut, users never uninstall it. The habit is the moat.
- **Cluely** — $15M from a16z, invisible overlay, had a data breach
- **Shadow, Jarvis, Screenpipe, Apple Visual Intelligence**
- What's left for us: numbers, files/folders, the mouse button, India pricing
- Lessons table from each competitor
- **Stop saying "first." Start saying "the only one that gets numbers right."**

---

## 06 — Competitors: Copilot, Comet, India
`06-Competitors-Copilot-Comet-and-India-Market.md` · 15 KB

Deeper dive on the two biggest incumbents, plus India reality.

- **Copilot's decline:** accuracy NPS fell from -3.5 to -24.1; only 8% voluntary preference; Microsoft's own terms warned against relying on it; Microsoft publicly admits Excel Copilot gets calculations wrong
- **Comet's four security failures:** CometJacking, incomplete injection fix, PerplexedBrowser (open ~4 months), MCP local-execution risk — all from treating page content as instructions
- **India isn't under-adopting AI** — 19% of global AI-app users, 180M ChatGPT MAU, ahead of the US
- The real India problem: we're desktop-only in a mobile-first market
- **~50% of Indian adopters cite price as the primary factor** — $8/month is likely wrong there
- DPDP Act full enforcement: May 13, 2027
- 7 suggested changes to strengthen our position

---

## 07 — Investor Readiness
`07-Investor-Readiness-What-to-Show-and-Why.md` · 11 KB

**Read before any investor call.**

- Honest position: zero product, zero users, zero revenue. That's pre-seed, not seed. Don't overstate.
- **The Delta question** — you're already raising ₹2.5 Cr for Delta. Every investor will ask why you're starting a second product. Need a one-sentence structural answer before any meeting.
- Tier 1 must-haves: working demo, usage evidence, 10–12 slide deck, the "why hasn't this been done" answer, unit economics
- Tier 2 expected: cap table, incorporation status, team slide, 18–24 month model, use of funds
- Numbers you must know cold without checking notes
- 7 questions they will ask, with prep
- 6 reasons they'd fund this
- 7 things that would make them say no
- Recommended 8–10 week sequence

---

## 08 — YC Application
`08-YC-Application-Draft-and-Deadlines.md` · 9 KB

- YC funds idea stage — ~40% of funded companies have no revenue
- But shipped product converts to interview at several times the rate
- Winter 2027 deadline not yet published — estimated late Oct/early Nov 2026. Confirm at ycombinator.com/apply.
- Drafted answers for every core application question
- One-minute founder video structure
- Rapid-fire interview prep
- Known weak points to get ahead of
- Pre-submission checklist

---

## 09 — HeyClicky Playbook
`09-HeyClicky-Playbook-and-How-to-Answer-Comparisons.md` · 8 KB

**Read before any comparison question.**

- Links to his original tweet (~3M views, 15K likes) and YC launch
- His framing: nostalgia and "a lil buddy," not "AI-powered productivity"
- His 10-step sequence: audience first → weekend build → 5-second demo → open source → free → Instagram → YC at 4 weeks → monetize after
- **Which parts you can copy and which you can't** — his distribution was inherited, not built
- **Corrected gap analysis.** Two of my earlier claims were wrong: they DO have filesystem access, they COULD compute via agents.
- Gaps that survive checking: **no Windows**, voice-first constraint, vision-only instant path, $20–100/month, wrong segment
- **The exact script for "how is yours better than theirs"**
- What NOT to say

---

## 10 — Write-Back
`10-Write-Back-Editing-Files-Not-Just-Reading.md` · 5 KB

Can we edit content, not just read it.

- Yes. Three mechanisms: file-level rewrite (easy), clipboard-paste replacement (medium), live app automation (hard, skip)
- **CSV write-back is the strong case** — compute a column, save a new file, sits on our differentiator
- **Docs Q&A write-back is weak** — Copilot territory, no accuracy edge
- Three costs: prompt injection becomes dangerous, product becomes destructive, softens the no-chat promise
- Non-negotiables: never overwrite originals, preview before apply, undo
- Recommendation on what to build when

---

# The 10 facts that matter most

1. **We are not first.** Highlight AI ($73M), HeyClicky (YC, $10.1M), Raycast, Cluely all ship versions of this.
2. **HeyClicky has no Windows product.** India is overwhelmingly Windows. Biggest open gap.
3. **Direct mouse-button interception doesn't work** on branded gaming mice. Use hotkey relay.
4. **Real AI cost is $0.06–$0.45 per user per month.** Unit economics work.
5. **Microsoft publicly admits Copilot gets calculations wrong.** Our deterministic math is a real, citable edge.
6. **Comet had four security incidents in 12 months**, all from treating content as instructions. Our design avoids this — market it.
7. **~50% of Indian buyers decide on price.** $8/month is likely wrong for India. Free tier is table stakes.
8. **Nobody in this category has a technology moat.** Including us. Habit and segment are the only defence.
9. **Zero code exists.** Every competitor named above is shipping.
10. **The Delta focus question will be asked by every investor.** Have the one-sentence answer ready.
