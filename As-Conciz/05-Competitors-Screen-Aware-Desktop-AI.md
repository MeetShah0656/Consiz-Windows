# Competitors — Screen-Aware Desktop AI

> **REALITY CHECK (31 Aug 2026):** Still accurate and worth reading. Update: our deterministic-numbers differentiator is now BUILT and demonstrable (attendance CSV → exact sums + lowest/highest employees). The 'mouse button' differentiator is real too — middle-click works. What we have NOT done: entered the market. Being different in private counts for nothing.
### The category we're actually competing in. Updated August 2026.

---

## Read this first

Earlier research compared As Conciz to Microsoft Copilot and Perplexity Comet. That was incomplete.

There is a whole category of products doing something much closer to what we planned: **desktop apps that read your screen and answer on a keyboard shortcut.** They are funded, shipping, and have paying users right now.

This is not a reason to stop. It is a reason to stop believing we are first.

---

## The direct competitors

### Highlight AI — the closest one
- Desktop assistant (Mac + PC) that reads anything on screen across any app
- Raised **$40M Series A from Khosla Ventures in March 2026**, total funding **$73M+**, new CEO appointed
- Free tier with unlimited chats on base models; Pro ~$15–20/month
- Integrates Gmail, Slack, Linear, Notion, GitHub, Google Calendar
- Also does meeting transcription and task detection
- Claims screen processing can happen locally, not uploaded

**Reality:** this is our idea, funded, shipped, and 18 months ahead of us.

### Shadow
- Mac-native, screen capture + on-device voice, triggered by keyboard shortcut
- Free tier, Plus $8/month
- "Action Skills" combine screen view with voice on a shortcut

### HeyClicky — the most dangerous one for us
- Mac app that sits **next to your cursor**. Hold Control+Option, ask out loud, it answers and draws an arrow at the exact button
- Founder **Farza Majeed** — previously built Buildspace, a 125,000+ builder community
- **YC Spring 2026 batch. ~$10.1M raised** (YC, Founders Inc, Pioneer Fund, Weekend Fund)
- Went from a tweet to a YC company in weeks: demo video ~3M views, open-source repo 6,300+ GitHub stars
- Free tier, Pro $20/month, Max $100/month
- Open source. Runs on Claude + AssemblyAI + ElevenLabs
- Mac only. Windows on a waitlist with no date
- Recently added screen-aware dictation and memory

**Why they matter more than the others:** they occupy the cursor. That was supposed to be our space. Their trigger is a keyboard shortcut today, but they are one product decision away from "select something, click, get an answer."

**Their structural weakness:** everything is **screenshot-driven**. They capture pixels via ScreenCaptureKit and send images to a vision model. That means:
- Numbers are read from an image, not computed. Worse accuracy than ours by design, not by effort.
- A folder is not a screenshot. Selecting a folder and getting file sizes and dates is a file-system operation they cannot do from pixels.
- A CSV with 5,000 rows does not fit on screen. They can only see what's visible.

They also hit the same Electron problem we identified — their changelog notes dictation falling back to the clipboard in apps like Discord.

**Outside analysts' read on them:** thin client over commodity model APIs, no real moat today, defensibility depends entirely on habit and UX lock-in.

### Jarvis (getjarvis.eu)
- Cmd+/ (Mac) or Ctrl+/ (Windows) floating bar, screenshots current screen
- 30+ OAuth connectors
- Routes between fast and deep models per task
- Reads and drafts freely; sending/deleting needs your approval
- ~$16/month Pro

### Raycast — the sleeper threat
- Mac launcher with AI built in, $8/month Pro
- Users describe it as "the first app I install on a new machine"
- Auto Model feature picks the best model per task automatically
- Bring your own API key and skip the AI tier entirely
- Thousands of community extensions

**Reality:** Raycast has the habit we want. People already press a shortcut and get an answer, dozens of times a day. Adding "summarize my selection" is a small feature for them, not a new product.

### Cluely
- Invisible desktop overlay, defeats screen capture on Zoom/Meet/Teams
- $15M from a16z at $120M valuation (June 2025)
- Pro $19.99/month, Pro + Undetectability $149.99/month
- Started as interview cheating tool, pivoted to "meeting assistant"
- Had a data breach in 2025; documented billing/refund complaints on Trustpilot

**Reality:** proof that a viral story beats a good product for early distribution — and also proof of how that reputation follows you.

### Screenpipe
- Open source, local-first, replaced Rewind in this niche
- Free

### Apple Visual Intelligence
- Built into macOS, free, on-device, M-series only
- The OS-level threat we flagged earlier is no longer hypothetical

---

## What's actually left for us

Honest read: "AI that reads your screen on a shortcut" is taken. Multiple funded companies do it. If our pitch is that sentence, we lose.

What none of them do well:

**1. Numbers.** Every product here sends content to an LLM and lets it answer. Microsoft has publicly admitted Excel Copilot "can give incorrect responses" for calculations. Nobody in this list computes deterministically. Our spec already does. Select a column of numbers, get a real sum — not a model's guess at a sum.

**2. The mouse.** All of them are keyboard shortcuts. Ours is a button under the finger already on the mouse. Small difference, but it's the only physical differentiator left, and it costs the user nothing.

**3. Files and folders.** They read *screens*. Select a folder, get contents, sizes, dates — that's a file-system operation, not a screenshot. Same for CSVs. This is genuinely a gap.

**4. India pricing.** Everything here is $8–$20/month, priced for US users. Nobody is priced for the market where 50% of buyers cite price as the deciding factor.

---

## What we should learn from each

| From | Lesson |
|---|---|
| HeyClicky | Distribution before product. Farza had 125k builders from Buildspace, posted one demo, got 3M views and YC in weeks. We have Hitarth's audience — that is an asset we have not used yet. |
| HeyClicky | Open-sourcing the app was the distribution engine, not a giveaway. 6,300 GitHub stars is a launch channel. |
| HeyClicky | Screenshots are the easy path and the wrong one for data. Their architecture cannot compute, read folders, or see off-screen rows. Ours can. Do not follow them into vision-only. |
| Highlight AI | $73M and a CEO change means the market believes in this category. Also means we can't outspend them — we have to be narrower and sharper. |
| Raycast | The habit is the moat. Users install it and never remove it. Build for daily use, not impressive demos. |
| Raycast (again) | Let users bring their own API key. Costs us nothing, kills the price objection instantly for technical users. |
| Cluely | Distribution can come from a story, not a feature list. Also: one data breach follows you forever in this category. |
| Jarvis | Read and draft freely, but ask before sending or deleting. Good safety default, copy it. |
| Shadow | $8/month is the floor price in this category. Our earlier $8 model was at the floor, not below it. |
| Screenpipe | Local-first and open source is a real position. If we go cloud-only we should say why. |
| Comet (from earlier research) | Four security incidents in 12 months, all from treating page content as instructions. Our untrusted-content design is a real advantage — market it. |

---

## What this changes about our plan

**Stop saying:** "the first product that lets you understand anything on your screen instantly."
That's false and any investor who searches for 30 seconds will find Highlight AI.

**Start saying:** "the only one that gets numbers right, works on files and folders, and lives on a mouse button instead of a keyboard shortcut."
Narrower. Defensible. True.

**Reconsider the wedge.** Text summarization is the crowded part. CSV/spreadsheet/data selection is the empty part. Analysts and finance people have a real, specific pain here that nobody is solving properly, and it's the one place an LLM-only competitor structurally cannot follow us without rebuilding their pipeline.

**Reconsider the price.** $8/month is not cheap in this category, it's average. Free tier is table stakes — Highlight, Shadow, Raycast, Screenpipe all have one.

**Reconsider the timeline.** Highlight raised $40M in March 2026. This category will consolidate. Being 18 months late with a general product is fatal; being narrow and correct on a specific job is survivable.
